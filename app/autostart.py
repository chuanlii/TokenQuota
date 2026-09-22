"""开机自启（当前用户 Run 项）。

两种运行形态都支持：

* 源码运行 —— 写 ``pythonw.exe "...\\run.pyw"``；
* PyInstaller 打包后的 exe —— 直接写 exe 自身路径。

靠 ``sys.frozen`` 区分，打包后不能再依赖 ``__file__``（那时它指向解包临时目录）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME

VALUE_NAME = "TokenQuota"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_frozen() -> bool:
    """当前是不是打包出来的 exe 在跑。"""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def entry_script() -> Path:
    return project_root() / "run.pyw"


def _python_exe() -> str:
    exe = sys.executable or "python.exe"
    if exe.lower().endswith("python.exe"):
        candidate = exe[: -len("python.exe")] + "pythonw.exe"
        if os.path.isfile(candidate):
            return candidate
    return exe


def launch_parts() -> tuple[str, str]:
    """自启要启动的东西：``(可执行文件, 脚本参数)``；参数为空串表示不需要脚本参数。"""
    if is_frozen():
        return sys.executable, ""
    return _python_exe(), str(entry_script())


def command() -> str:
    """注册表里要写的命令行（两种形态都不会弹控制台窗口）。"""
    exe, script = launch_parts()
    return f'"{exe}" "{script}"' if script else f'"{exe}"'


def _markers() -> tuple[str, ...]:
    """能认作「本程序写的自启项」的标记。

    同时认脚本形态的 ``run.pyw`` 和 exe 形态的可执行文件名，
    这样从源码切到 exe（或反过来）时，菜单里的勾选状态不会莫名其妙变掉。
    """
    names = ["run.pyw", f"{APP_NAME.lower()}.exe"]
    if is_frozen():
        names.append(Path(sys.executable).name.lower())
    return tuple(dict.fromkeys(names))


def _winreg():
    import winreg

    return winreg


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    if not isinstance(value, str):
        return False
    low = value.lower()
    return any(marker in low for marker in _markers())


def set_enabled(enabled: bool) -> None:
    if os.name != "nt":
        raise RuntimeError("开机自启只支持 Windows")
    winreg = _winreg()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
