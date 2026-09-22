"""托盘图标与菜单。

图标是运行时画出来的（两个订阅主色各一条竖条），不依赖外部资源文件。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import APP_TITLE, spec
from . import autostart

BAR_COLORS = ("#10a37f", "#6c7bff")


def _pixmap(side: int) -> QPixmap:
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    bar_w = max(2.0, side * 0.26)
    gap = max(1.0, side * 0.14)
    total = bar_w * 2 + gap
    left = (side - total) / 2
    top = side * 0.16
    height = side - top * 2

    for index, color in enumerate(BAR_COLORS):
        rect = QRectF(left + index * (bar_w + gap), top, bar_w, height)
        path = QPainterPath()
        path.addRoundedRect(rect, bar_w / 2, bar_w / 2)
        painter.fillPath(path, QColor(color))

    painter.end()
    return pixmap


def make_icon() -> QIcon:
    icon = QIcon()
    for side in (16, 20, 24, 32, 48, 64):
        icon.addPixmap(_pixmap(side))
    return icon


class TrayIcon(QSystemTrayIcon):
    refresh_requested = Signal()
    toggle_requested = Signal()
    move_requested = Signal()
    settings_requested = Signal()
    autostart_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(make_icon(), parent)
        self.setToolTip(APP_TITLE)

        menu = QMenu()

        self._refresh = QAction("立即刷新", menu)
        self._refresh.triggered.connect(self.refresh_requested.emit)
        menu.addAction(self._refresh)

        self._toggle = QAction("隐藏面板", menu)
        self._toggle.triggered.connect(self.toggle_requested.emit)
        menu.addAction(self._toggle)

        self._move = QAction("面板移到光标所在屏", menu)
        self._move.triggered.connect(self.move_requested.emit)
        menu.addAction(self._move)

        self._settings = QAction("设置…", menu)
        self._settings.triggered.connect(self.settings_requested.emit)
        menu.addAction(self._settings)

        menu.addSeparator()

        self._autostart = QAction("开机自启", menu)
        self._autostart.setCheckable(True)
        self._autostart.setChecked(autostart.is_enabled())
        self._autostart.toggled.connect(self.autostart_toggled.emit)
        menu.addAction(self._autostart)

        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_requested.emit()

    # ------------------------------------------------------------------

    def sync_autostart(self) -> None:
        self._autostart.blockSignals(True)
        self._autostart.setChecked(autostart.is_enabled())
        self._autostart.blockSignals(False)

    def set_panel_visible(self, visible: bool) -> None:
        self._toggle.setText("隐藏面板" if visible else "显示面板")

    def show_message(self, title: str, body: str) -> None:
        self.showMessage(title, body, self.icon(), 4000)

    def set_summary(self, views: list[spec.ServiceView]) -> None:
        if not views:
            self.setToolTip(f"{APP_TITLE}\n正在取数…")
            return
        now = time.time()
        self.setToolTip("\n".join(view.tooltip(now) for view in views))
