"""设置窗口：显示哪些服务、什么条件下变什么颜色。

改完点「保存」才落盘；面板会立刻按新设置重画（见 ``main.py``）。
默认值就在这一屏上摆着，用户随时能「恢复默认」。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from . import spec
from .assets import SERVICES
from .config import Config

_MUTED_STYLE = f"color: {spec.TEXT_MUTED};"


def _swatch(color: str, side: int = 12) -> QIcon:
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, side - 1, side - 1), 3.5, 3.5)
    painter.fillPath(path, QColor(color))
    painter.end()
    return QIcon(pixmap)


def _color_combo(slot: str, current: str) -> QComboBox:
    combo = QComboBox()
    options = list(spec.COLOR_PALETTE[slot])
    if current not in [value for _, value in options]:
        options.insert(0, ("当前", current))
    for name, value in options:
        combo.addItem(_swatch(value), f"{name}  {value.upper()}", value)
    index = combo.findData(current)
    combo.setCurrentIndex(index if index >= 0 else 0)
    return combo


def _pct_spin(value: float) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setSuffix("%")
    spin.setValue(int(round(value)))
    spin.setFixedWidth(74)
    return spin


class SettingsDialog(QDialog):
    """服务开关 + 变色条件 + 三档配色。"""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置 · AI 订阅额度")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(388)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        root.addWidget(self._build_services(config))
        root.addWidget(self._build_colors(config))

        hint = QLabel("颜色改动会同时作用在展开卡片的长条和收起后的两条竖条上。")
        hint.setWordWrap(True)
        hint.setStyleSheet(_MUTED_STYLE)
        root.addWidget(hint)

        buttons = QDialogButtonBox()
        self._reset_btn = QPushButton("恢复默认")
        buttons.addButton(self._reset_btn, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.addButton("保存", QDialogButtonBox.ButtonRole.AcceptRole)
        self._reset_btn.clicked.connect(self._restore_defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # 控件建好后按配置回填：阈值开关的勾选态只有这里会设，
        # 漏了的话用户一进来点「保存」就会把两条变色规则全关掉。
        self._apply(config)

    # ------------------------------------------------------------------ 各区块

    def _build_services(self, config: Config) -> QGroupBox:
        box = QGroupBox("显示的服务")
        layout = QVBoxLayout(box)
        layout.setSpacing(4)

        self._checks: dict[str, QCheckBox] = {}
        for service in SERVICES:
            check = QCheckBox(service.name)
            check.setChecked(bool(config.enabled.get(service.id, True)))
            self._checks[service.id] = check
            layout.addWidget(check)
        return box

    def _build_colors(self, config: Config) -> QGroupBox:
        box = QGroupBox("什么条件下用哪种颜色")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        rule = config.rule
        colors = config.colors

        # 正常档
        grid.addWidget(QLabel("正常"), 0, 0)
        grid.addWidget(QLabel("额度充足、节奏正常"), 0, 1)
        self._ok_combo = _color_combo("ok", colors["ok"])
        grid.addWidget(self._ok_combo, 0, 2, Qt.AlignmentFlag.AlignRight)

        # 危险档：剩余额度不足
        self._low_check = QCheckBox("剩余额度 ≤")
        self._low_spin = _pct_spin(rule.low_pct)
        self._danger_combo = _color_combo("danger", colors["danger"])
        grid.addWidget(self._low_check, 1, 0)
        grid.addWidget(self._low_spin, 1, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._danger_combo, 1, 2, Qt.AlignmentFlag.AlignRight)

        # 注意档：额度与时间进度对不上
        self._pace_check = QCheckBox("额度与时间进度差")
        self._pace_spin = _pct_spin(rule.pace_gap_pct)
        self._warn_combo = _color_combo("warn", colors["warn"])
        grid.addWidget(self._pace_check, 2, 0)
        grid.addWidget(self._pace_spin, 2, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._warn_combo, 2, 2, Qt.AlignmentFlag.AlignRight)

        tip = QLabel(
            "「进度差」指剩的时间和剩的额度对不上：时间快到了额度还剩一大截（用不完），"
            "或者额度掉得比时间快（撑不到下次重置）。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(_MUTED_STYLE)
        grid.addWidget(tip, 3, 0, 1, 3)

        self._low_check.toggled.connect(self._low_spin.setEnabled)
        self._pace_check.toggled.connect(self._pace_spin.setEnabled)
        self._low_spin.setEnabled(rule.low_enabled)
        self._pace_spin.setEnabled(rule.pace_enabled)
        return box

    # ------------------------------------------------------------------ 行为

    def _restore_defaults(self) -> None:
        defaults = Config.default()
        for service in SERVICES:
            self._checks[service.id].setChecked(bool(defaults.enabled.get(service.id, True)))
        self._apply(defaults)

    def _apply(self, config: Config) -> None:
        rule = config.rule
        self._low_check.setChecked(rule.low_enabled)
        self._pace_check.setChecked(rule.pace_enabled)
        self._low_spin.setValue(int(round(rule.low_pct)))
        self._pace_spin.setValue(int(round(rule.pace_gap_pct)))
        for slot, combo in (
            ("ok", self._ok_combo),
            ("warn", self._warn_combo),
            ("danger", self._danger_combo),
        ):
            index = combo.findData(config.colors[slot])
            if index >= 0:
                combo.setCurrentIndex(index)

    def result_config(self) -> Config:
        return Config(
            enabled={sid: check.isChecked() for sid, check in self._checks.items()},
            rule=spec.Rule(
                low_enabled=self._low_check.isChecked(),
                low_pct=float(self._low_spin.value()),
                pace_enabled=self._pace_check.isChecked(),
                pace_gap_pct=float(self._pace_spin.value()),
            ).clamp(),
            colors={
                "ok": self._ok_combo.currentData(),
                "warn": self._warn_combo.currentData(),
                "danger": self._danger_combo.currentData(),
            },
        )

    def accept(self) -> None:  # noqa: D102 - Qt 命名
        if not any(check.isChecked() for check in self._checks.values()):
            QMessageBox.warning(self, "至少要留一个", "面板至少要显示一个服务，否则卡片是空的。")
            return
        super().accept()
