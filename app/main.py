"""程序入口：把取数线程、面板、托盘接起来。"""

from __future__ import annotations

import ctypes
import os
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from . import APP_NAME, APP_TITLE, config, spec
from . import autostart
from .model import ServiceSnapshot
from .panel import PanelWindow
from .poller import Poller
from .settings_ui import SettingsDialog
from .single_instance import SingleInstance
from .tray import TrayIcon

#: 即使没有新数据，也定期重算一次视图（陈旧标记、年龄文案）
RESCORE_MS = 20_000


def _set_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TokenQuota.Panel")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv)
    instance = SingleInstance("TokenQuota.Panel")
    if instance.already_running:
        # 已经有一个在跑；直接退出（托盘里那份才是活的）
        print(f"{APP_TITLE} 已经在运行。", file=sys.stderr)
        return 0

    try:
        return _run(instance, args)
    finally:
        instance.release()


def _run(instance: SingleInstance, argv: list[str]) -> int:
    _set_app_user_model_id()

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    app.setQuitOnLastWindowClosed(False)

    state: dict[str, object] = {"snapshots": {}, "views": []}
    #: 设置改了就写回这个对象（不重新赋值，省得到处 nonlocal）
    cfg = config.load()

    panel = PanelWindow()
    poller = Poller()
    tray = TrayIcon(app)

    def rebuild() -> None:
        views = spec.build_views(
            state["snapshots"],  # type: ignore[arg-type]
            cfg.services,
            rule=cfg.rule,
            colors=cfg.colors,
        )
        state["views"] = views
        panel.set_views(views)
        tray.set_summary(views)

    def on_results(snapshots: dict[str, ServiceSnapshot]) -> None:
        state["snapshots"] = snapshots
        rebuild()

    poller.results.connect(on_results)

    def on_toggle() -> None:
        visible = not panel.isVisible()
        panel.setVisible(visible)
        tray.set_panel_visible(visible)

    def apply_autostart(enabled: bool) -> None:
        """把自启状态落到系统里。

        托盘菜单和设置窗口是同一份状态的两个入口，所以写完（或写失败）都要回读一次
        注册表，免得其中一处的勾选跟系统不一致。
        """
        try:
            autostart.set_enabled(enabled)
        except Exception as exc:  # noqa: BLE001
            tray.sync_autostart()
            tray.show_message("开机自启设置失败", str(exc))
            return
        tray.sync_autostart()
        tray.show_message(
            "开机自启",
            "已开启，下次登录自动启动。" if enabled else "已关闭。",
        )

    def on_quit() -> None:
        poller.stop()
        tray.hide()
        app.quit()

    def on_settings() -> None:
        dialog = SettingsDialog(cfg)
        dialog.adjustSize()
        geo = panel.target_screen_geometry()
        dialog.move(
            geo.x() + max(12, geo.width() - dialog.width() - 24),
            geo.y() + max(12, (geo.height() - dialog.height()) // 2),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.result_config()
        cfg.enabled = dict(chosen.enabled)
        cfg.rule = chosen.rule
        cfg.colors = dict(chosen.colors)
        try:
            config.save(cfg)
        except OSError as exc:  # noqa: BLE001 - 存不下也要继续用
            tray.show_message("设置没能保存", str(exc))

        # 只有真变了才动注册表：没碰这个勾的时候，不该顺手把自启命令重写一遍
        # （同一台机器上源码形态和 exe 形态写出来的命令并不一样）
        chosen_autostart = dialog.result_autostart()
        if chosen_autostart != autostart.is_enabled():
            apply_autostart(chosen_autostart)

        rebuild()

    tray.refresh_requested.connect(poller.refresh_now)
    tray.toggle_requested.connect(on_toggle)
    tray.move_requested.connect(panel.move_to_cursor_screen)
    tray.settings_requested.connect(on_settings)
    tray.autostart_toggled.connect(apply_autostart)
    tray.quit_requested.connect(on_quit)
    panel.settings_requested.connect(on_settings)

    rescore = QTimer()
    rescore.setInterval(RESCORE_MS)
    rescore.timeout.connect(rebuild)
    rescore.start()

    app.aboutToQuit.connect(poller.stop)
    for signal in (app.screenAdded, app.screenRemoved):
        signal.connect(lambda *_: panel.anchor_to_edge())

    rebuild()
    panel.show()
    tray.set_panel_visible(True)
    if tray.isSystemTrayAvailable():
        tray.show()
    poller.start()

    return app.exec()
