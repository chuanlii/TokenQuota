"""桌面面板窗口：贴屏幕右边缘的额度卡片。

设计要点
--------
* **不透明卡片**：不再逐像素透明，直接把 prototype/bars.html 的视觉规范
  画成一张不透明圆角卡片，绕开 QtWebEngine / Qt 的透明渲染坑。
* **贴右边**：窗口右边缘永远钉在屏幕可用区右边缘；展开时只改窗口宽度，
  卡片右对齐绘制，于是看起来像从边缘滑出来。
* **不抢焦点**：``Qt.WindowDoesNotAcceptFocus``（= Win32 ``WS_EX_NOACTIVATE``），
  点一下不会夺走编辑器的焦点。
* **折叠态鼠标穿透**：折叠时给窗口加上 ``WS_EX_TRANSPARENT``，
  点击直接落到下面的应用上；悬停检测改用轮询 ``QCursor.pos()``，
  不依赖鼠标事件，所以穿透也不影响展开。
"""

from __future__ import annotations

import ctypes
import os
import time

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QToolTip, QWidget

from . import assets, spec

FONT_STACK = [
    "Segoe UI Variable Display",
    "Segoe UI",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
]

#: 展开/收起动画时长（毫秒）
ANIM_MS = 260
#: 折叠延迟：鼠标离开后等一会儿再收，避免边缘抖动
COLLAPSE_DELAY_MS = 300
#: 悬停轮询间隔
HOVER_POLL_MS = 80


def _font(px: float, weight: QFont.Weight) -> QFont:
    font = QFont()
    font.setFamilies(FONT_STACK)
    # Qt6 里 1 逻辑像素 = 0.75pt（与屏幕 DPI 无关），这样字号和 CSS 的 px 对得上
    font.setPointSizeF(px * 0.75)
    font.setWeight(weight)
    return font


class PanelWindow(QWidget):
    #: 用户点了左下角的设置齿轮
    settings_requested = Signal()

    def __init__(self, views: list[spec.ServiceView] | None = None) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("AI 订阅额度")
        self.setMouseTracking(True)

        self._views: list[spec.ServiceView] = list(views or [])
        self._group_rects: list[QRectF] = []
        self._icon_cache: dict[tuple, QPixmap] = {}
        self._gear_hover = False

        self._build_fonts()
        self._layout = self._measure()

        self._right = 0
        self._top = 0
        self._target = None
        self._reveal = 0.0
        self._click_through: bool | None = None

        self._anim = QPropertyAnimation(self, b"reveal", self)
        self._anim.setDuration(ANIM_MS)
        curve = QEasingCurve()
        curve.setType(QEasingCurve.Type.BezierSpline)
        # 原型里的 cubic-bezier(.22, 1, .36, 1)
        curve.addCubicBezierSegment(QPointF(0.22, 1.0), QPointF(0.36, 1.0), QPointF(1.0, 1.0))
        self._anim.setEasingCurve(curve)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._collapse)

        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(HOVER_POLL_MS)
        self._hover_timer.timeout.connect(self._poll_hover)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self.update)

    # ------------------------------------------------------------------ 字体与测量

    def _build_fonts(self) -> None:
        self.f_name = _font(spec.NAME_PX, QFont.Weight.DemiBold)
        self.f_meta = _font(spec.META_PX, QFont.Weight.Medium)
        self.f_pct = _font(spec.PCT_PX, QFont.Weight.DemiBold)
        self.f_rest = _font(spec.REST_PX, QFont.Weight.Medium)
        self.f_gear = _font(spec.GEAR_PX, QFont.Weight.Medium)
        self.f_badge = _font(8.0, QFont.Weight.Bold)

    def _measure(self) -> dict:
        from PySide6.QtGui import QFontMetricsF

        fm_name = QFontMetricsF(self.f_name)
        fm_meta = QFontMetricsF(self.f_meta)
        fm_pct = QFontMetricsF(self.f_pct)
        fm_rest = QFontMetricsF(self.f_rest)
        fm_gear = QFontMetricsF(self.f_gear)

        head_h = max(spec.ICON_SIZE, fm_name.height())
        row_h = spec.ROW_PAD_Y * 2 + max(fm_pct.height(), fm_rest.height(), spec.BAR_H)

        group_hs = [head_h + spec.HEAD_PAD_BOTTOM + len(v.rows) * row_h for v in self._views]
        body = sum(group_hs) + spec.GROUP_GAP * max(0, len(group_hs) - 1)
        card_h = (
            spec.CARD_PAD_TOP
            + body
            + spec.FOOT_PAD_TOP
            + spec.FOOT_H
            + spec.CARD_PAD_BOTTOM
        )

        return {
            "fm_name": fm_name,
            "fm_meta": fm_meta,
            "fm_pct": fm_pct,
            "fm_rest": fm_rest,
            "fm_gear": fm_gear,
            "head_h": head_h,
            "row_h": row_h,
            "row_text_h": row_h - spec.ROW_PAD_Y * 2,
            "group_hs": group_hs,
            "card_h": round(card_h),
        }

    @property
    def card_h(self) -> int:
        return int(self._layout["card_h"])

    # ------------------------------------------------------------------ 几何

    def _screen_geometry(self) -> QRect:
        screen = self._target_screen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1920, 1040)

    def target_screen_geometry(self) -> QRect:
        """面板所在屏的可用区（设置窗口用它定位）。"""
        return self._screen_geometry()

    def _target_screen(self):
        """面板要贴哪块屏。

        默认取**最靠右**的那块屏：既确定（不受启动时光标位置影响），
        又保证落在真正的屏幕外缘上，而不是两块屏之间的接缝。
        用户可以通过托盘菜单临时改到光标所在屏。
        """
        from PySide6.QtGui import QGuiApplication

        if self._target is not None:
            return self._target
        screens = QGuiApplication.screens()
        if not screens:
            return QGuiApplication.primaryScreen()
        return max(screens, key=lambda s: s.geometry().x() + s.geometry().width())

    def move_to_cursor_screen(self) -> None:
        """把面板挪到光标当前所在的那块屏（托盘菜单用）。"""
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is not None:
            self._target = screen
        self.anchor_to_edge()

    def anchor_to_edge(self) -> None:
        """重新贴合目标屏右边缘（启动、分辨率/任务栏变化时调用）。"""
        geo = self._screen_geometry()
        self._right = geo.x() + geo.width()
        self._top = geo.y() + max(0, (geo.height() - self.card_h) // 2)
        self._apply_geometry()

    def _apply_geometry(self) -> None:
        width = round(spec.COLLAPSED_W + (spec.CARD_W - spec.COLLAPSED_W) * self._reveal)
        self.setGeometry(self._right - width, self._top, width, self.card_h)

    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, value: float) -> None:
        self._reveal = max(0.0, min(1.0, float(value)))
        self._apply_geometry()
        self._sync_click_through()
        self.update()

    reveal = Property(float, _get_reveal, _set_reveal)

    # ------------------------------------------------------------------ 鼠标穿透

    def _sync_click_through(self) -> None:
        """折叠（或几乎折叠）时让点击穿透到下层窗口。"""
        if os.name != "nt":
            return
        want = self._reveal < 0.02
        if want == self._click_through:
            return
        try:
            hwnd = int(self.winId())
        except (TypeError, ValueError):
            return
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        user32 = ctypes.windll.user32
        current = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if want:
            new = current | WS_EX_TRANSPARENT | WS_EX_LAYERED
        else:
            new = current & ~WS_EX_TRANSPARENT
        if new != current:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
            SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        self._click_through = want

    # ------------------------------------------------------------------ 悬停

    def _hot_zone(self) -> QRect:
        if self._reveal > 0.02:
            return self.geometry().adjusted(-spec.HOVER_PAD, -spec.HOVER_PAD, 0, spec.HOVER_PAD)
        pill_top = self._top + (self.card_h - spec.COLLAPSED_H) // 2
        return QRect(
            self._right - spec.COLLAPSED_W - spec.HOVER_PAD,
            pill_top - spec.HOVER_PAD,
            spec.COLLAPSED_W + spec.HOVER_PAD,
            spec.COLLAPSED_H + spec.HOVER_PAD * 2,
        )

    def _poll_hover(self) -> None:
        inside = self._hot_zone().contains(QCursor.pos())
        if inside:
            self._collapse_timer.stop()
            if self._reveal < 1.0:
                self._expand()
        elif self._reveal > 0.0 and not self._collapse_timer.isActive():
            self._collapse_timer.start(COLLAPSE_DELAY_MS)

    def _expand(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._reveal)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _collapse(self) -> None:
        if self._hot_zone().contains(QCursor.pos()):
            return
        self._anim.stop()
        self._anim.setStartValue(self._reveal)
        self._anim.setEndValue(0.0)
        self._anim.start()

    # ------------------------------------------------------------------ 对外接口

    def set_views(self, views: list[spec.ServiceView]) -> None:
        self._views = list(views)
        # 行数可能变了（Codex 2 行 / 服务被关掉），卡片高度和贴边位置都要重算
        self._layout = self._measure()
        self.anchor_to_edge()
        self.update()

    def _foot_top(self) -> float:
        return self.card_h - spec.CARD_PAD_BOTTOM - spec.FOOT_H

    def _gear_rect(self) -> QRectF:
        """齿轮图标在窗口坐标里的位置（左下角）。"""
        left = self.width() - spec.CARD_W + spec.CARD_PAD_X
        return QRectF(
            left,
            self._foot_top() + (spec.FOOT_H - spec.GEAR_SIZE) / 2,
            spec.GEAR_SIZE,
            spec.GEAR_SIZE,
        )

    def _gear_hit(self) -> QRectF:
        return self._gear_rect().adjusted(-5, -5, 5, 5)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._reveal > 0.9
            and self._gear_hit().contains(QPointF(event.position()))
        ):
            event.accept()
            self.settings_requested.emit()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        hover = self._reveal > 0.9 and self._gear_hit().contains(QPointF(event.position()))
        if hover != self._gear_hover:
            self._gear_hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._gear_hover:
            self._gear_hover = False
            self.update()
        super().leaveEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self.anchor_to_edge()
        self._sync_click_through()
        self._hover_timer.start()
        self._tick_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover_timer.stop()
        self._tick_timer.stop()
        super().hideEvent(event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip and self._reveal > 0.5:
            text = self._tooltip_at(event.pos())
            if text:
                QToolTip.showText(event.globalPos(), text, self)
            return True
        return super().event(event)

    def _tooltip_at(self, pos) -> str:
        now = time.time()
        point = QPointF(pos)
        if self._gear_hit().contains(point):
            return "设置：显示哪些服务、什么条件下变色"
        for rect, view in zip(self._group_rects, self._views):
            if rect.contains(point):
                return view.tooltip(now)
        return ""

    # ------------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        now = time.time()
        # 展开后（几乎）看不到指示条：反之亦然
        pill_alpha = max(0.0, min(1.0, 1.0 - self._reveal * 3.0))
        card_alpha = max(0.0, min(1.0, (self._reveal - 0.12) / 0.45))

        if pill_alpha > 0.01:
            self._paint_pill(painter, pill_alpha, now)
        if card_alpha > 0.01:
            self._paint_card(painter, card_alpha, now)

        painter.end()

    # ---- 折叠态指示条

    def _paint_pill(self, painter: QPainter, alpha: float, now: float) -> None:
        rect = QRectF(
            self.width() - spec.COLLAPSED_W,
            (self.card_h - spec.COLLAPSED_H) / 2,
            spec.COLLAPSED_W,
            spec.COLLAPSED_H,
        )
        painter.save()
        painter.setOpacity(alpha)

        path = QPainterPath()
        path.addRoundedRect(rect, spec.COLLAPSED_RADIUS, spec.COLLAPSED_RADIUS)
        painter.fillPath(path, QColor(spec.BG))
        painter.setPen(QPen(QColor(spec.BORDER), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), spec.COLLAPSED_RADIUS, spec.COLLAPSED_RADIUS)

        count = max(1, len(self._views))
        inner_h = rect.height() - spec.COLLAPSED_INSET * 2
        slot_h = (inner_h - spec.COLLAPSED_GAP * (count - 1)) / count
        bar_x = rect.center().x() - spec.COLLAPSED_BAR_W / 2

        for index, view in enumerate(self._views):
            top = rect.top() + spec.COLLAPSED_INSET + index * (slot_h + spec.COLLAPSED_GAP)
            track = QRectF(bar_x, top, spec.COLLAPSED_BAR_W, slot_h)
            track_path = QPainterPath()
            track_path.addRoundedRect(track, spec.COLLAPSED_BAR_W / 2, spec.COLLAPSED_BAR_W / 2)
            painter.fillPath(track_path, QColor(spec.TRACK))
            if not view.rows:
                continue
            remain = max(0.0, min(1.0, view.headline_remaining()))
            fill_h = slot_h * remain
            if fill_h < 0.5:
                continue
            fill = QRectF(bar_x, top + slot_h - fill_h, spec.COLLAPSED_BAR_W, fill_h)
            fill_path = QPainterPath()
            fill_path.addRoundedRect(fill, spec.COLLAPSED_BAR_W / 2, spec.COLLAPSED_BAR_W / 2)
            painter.fillPath(fill_path, QColor(view.status_color()))
        painter.restore()

    # ---- 展开卡片

    def _paint_card(self, painter: QPainter, alpha: float, now: float) -> None:
        card = QRectF(self.width() - spec.CARD_W, 0, spec.CARD_W, self.card_h)
        painter.save()
        painter.setOpacity(alpha)

        path = QPainterPath()
        path.addRoundedRect(card, spec.CARD_RADIUS, spec.CARD_RADIUS)
        painter.fillPath(path, QColor(spec.BG))
        painter.setPen(QPen(QColor(spec.BORDER), 1))
        painter.drawRoundedRect(
            card.adjusted(0.5, 0.5, -0.5, -0.5), spec.CARD_RADIUS, spec.CARD_RADIUS
        )

        self._group_rects = []
        x = card.left() + spec.CARD_PAD_X
        y = card.top() + spec.CARD_PAD_TOP
        for index, view in enumerate(self._views):
            if index:
                y += spec.GROUP_GAP
            y = self._paint_group(painter, x, y, view, now)
        self._paint_footer(painter, card)
        painter.restore()

    def _paint_footer(self, painter: QPainter, card: QRectF) -> None:
        """左下角的设置入口：一条细分隔线 + 齿轮 + 「设置」。"""
        foot_top = self._foot_top()
        painter.setPen(QPen(QColor(spec.DIVIDER), 1))
        painter.drawLine(
            QPointF(card.left() + spec.CARD_PAD_X, foot_top - spec.FOOT_PAD_TOP / 2),
            QPointF(card.right() - spec.CARD_PAD_X, foot_top - spec.FOOT_PAD_TOP / 2),
        )

        hot = self._gear_hover and self._reveal > 0.9
        color = spec.TEXT_STRONG if hot else spec.TEXT_MUTED
        gear = QRectF(
            card.left() + spec.CARD_PAD_X,
            foot_top + (spec.FOOT_H - spec.GEAR_SIZE) / 2,
            spec.GEAR_SIZE,
            spec.GEAR_SIZE,
        )
        pixmap = self._icon_pixmap(assets.GEAR_ICON, color, spec.GEAR_SIZE)
        if pixmap is not None:
            painter.drawPixmap(gear.topLeft(), pixmap)

        fm_gear = self._layout["fm_gear"]
        painter.setFont(self.f_gear)
        painter.setPen(QColor(color))
        painter.drawText(
            QRectF(
                gear.right() + 4,
                foot_top + (spec.FOOT_H - fm_gear.height()) / 2,
                spec.CONTENT_W - spec.GEAR_SIZE - 4,
                fm_gear.height(),
            ),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "设置",
        )

    def _paint_group(self, painter: QPainter, x: float, y: float, view: spec.ServiceView, now: float) -> float:
        layout = self._layout
        head_h = layout["head_h"]
        row_h = layout["row_h"]
        row_text_h = layout["row_text_h"]
        fm_name, fm_meta = layout["fm_name"], layout["fm_meta"]
        fm_pct, fm_rest = layout["fm_pct"], layout["fm_rest"]

        self._group_rects.append(
            QRectF(x, y, spec.CONTENT_W, head_h + spec.HEAD_PAD_BOTTOM + len(view.rows) * row_h)
        )

        # ---- 第 1 行：图标 + 服务名 + (EXP 窗口 · 计数)
        icon_rect = QRectF(x, y + (head_h - spec.ICON_SIZE) / 2, spec.ICON_SIZE, spec.ICON_SIZE)
        self._paint_icon(painter, view, icon_rect)

        meta_w = 0.0
        exp_text = view.exp_text or ""
        if exp_text:
            meta_w += fm_meta.horizontalAdvance(exp_text)
        pill_text = view.count_text or ""
        pill_w = 0.0
        if pill_text:
            pill_w = fm_meta.horizontalAdvance(pill_text) + spec.PILL_PAD_X * 2
            meta_w += (spec.PILL_GAP if exp_text else 0.0) + pill_w
        badge_d = 11.0
        if view.stale:
            meta_w += (spec.PILL_GAP if meta_w else 0.0) + badge_d

        meta_x = x + spec.CONTENT_W - meta_w
        center_y = y + head_h / 2

        name_rect = QRectF(
            x + spec.ICON_SIZE + spec.HEAD_GAP,
            y + (head_h - fm_name.height()) / 2,
            max(0.0, meta_x - (x + spec.ICON_SIZE + spec.HEAD_GAP) - spec.HEAD_GAP),
            fm_name.height(),
        )
        painter.setFont(self.f_name)
        painter.setPen(QColor(spec.TEXT_STRONG))
        painter.drawText(
            name_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fm_name.elidedText(view.service.name, Qt.TextElideMode.ElideRight, name_rect.width()),
        )

        cursor_x = meta_x
        if exp_text:
            painter.setFont(self.f_meta)
            painter.setPen(QColor(spec.TEXT_MUTED))
            painter.drawText(
                QRectF(cursor_x, center_y - fm_meta.height() / 2, fm_meta.horizontalAdvance(exp_text), fm_meta.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                exp_text,
            )
            cursor_x += fm_meta.horizontalAdvance(exp_text) + spec.PILL_GAP

        if pill_text:
            pill_h = fm_meta.height() + spec.PILL_PAD_Y * 2
            pill_rect = QRectF(cursor_x, center_y - pill_h / 2, pill_w, pill_h)
            pill_path = QPainterPath()
            pill_path.addRoundedRect(pill_rect, pill_h / 2, pill_h / 2)
            painter.fillPath(pill_path, QColor(spec.PILL))
            painter.setFont(self.f_meta)
            painter.setPen(QColor(spec.TEXT_MUTED))
            painter.drawText(
                pill_rect,
                int(Qt.AlignmentFlag.AlignCenter),
                fm_meta.elidedText(pill_text, Qt.TextElideMode.ElideRight, pill_rect.width()),
            )
            cursor_x += pill_w + spec.PILL_GAP

        if view.stale:
            badge = QRectF(cursor_x, center_y - badge_d / 2, badge_d, badge_d)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(spec.STALE_BADGE))
            painter.drawEllipse(badge)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setFont(self.f_badge)
            painter.setPen(QColor(spec.BG))
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), "!")

        y += head_h + spec.HEAD_PAD_BOTTOM

        # ---- 第 2~4 行：百分比 · 长条 · 剩余时间
        bar_w = spec.bar_width()
        for row in view.rows:
            text_top = y + spec.ROW_PAD_Y

            pct_rect = QRectF(x, text_top + (row_text_h - fm_pct.height()) / 2, spec.PCT_W, fm_pct.height())
            painter.setFont(self.f_pct)
            # 正常档的百分比保持白字，只有变色档才上色，避免满屏彩色数字
            painter.setPen(QColor(row.color if row.level else spec.TEXT_STRONG))
            painter.drawText(
                pct_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                row.pct(),
            )

            bar_rect = QRectF(
                x + spec.PCT_W + spec.ROW_GAP,
                y + (row_h - spec.BAR_H) / 2,
                bar_w,
                spec.BAR_H,
            )
            track_path = QPainterPath()
            track_path.addRoundedRect(bar_rect, spec.BAR_H / 2, spec.BAR_H / 2)
            painter.fillPath(track_path, QColor(spec.TRACK))
            painter.setPen(QPen(QColor(spec.TRACK_EDGE), 1))
            painter.drawRoundedRect(
                bar_rect.adjusted(0.5, 0.5, -0.5, -0.5), spec.BAR_H / 2, spec.BAR_H / 2
            )
            painter.setPen(Qt.PenStyle.NoPen)

            if row.has_data:
                fill_w = bar_w * max(0.0, min(1.0, row.remaining))
                if fill_w > 0.6:
                    painter.save()
                    painter.setClipPath(track_path, Qt.ClipOperation.IntersectClip)
                    painter.fillRect(
                        QRectF(bar_rect.left(), bar_rect.top(), fill_w, bar_rect.height()),
                        QColor(row.color),
                    )
                    painter.restore()

            rest_rect = QRectF(
                x + spec.CONTENT_W - spec.REST_W,
                text_top + (row_text_h - fm_rest.height()) / 2,
                spec.REST_W,
                fm_rest.height(),
            )
            painter.setFont(self.f_rest)
            painter.setPen(QColor(spec.TEXT_2))
            painter.drawText(
                rest_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                row.rest(now),
            )

            y += row_h

        return y

    def _paint_icon(self, painter: QPainter, view: spec.ServiceView, rect: QRectF) -> None:
        pixmap = self._icon_pixmap(view.service.icon, view.accent, spec.ICON_SIZE)
        if pixmap is not None:
            painter.drawPixmap(rect.topLeft(), pixmap)

    def _icon_pixmap(self, svg: str, color: str, side: float = spec.ICON_SIZE) -> QPixmap | None:
        ratio = float(self.devicePixelRatioF()) or 1.0
        key = (svg, color, side, round(ratio, 2))
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        markup = svg.replace("currentColor", color)
        renderer = QSvgRenderer(QByteArray(markup.encode("utf-8")))
        if not renderer.isValid():
            return None
        pixmap = QPixmap(int(round(side * ratio)), int(round(side * ratio)))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        self._icon_cache[key] = pixmap
        return pixmap
