"""开机自启（当前用户 Run 项）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

VALUE_NAME = "TokenQuota"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


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


def command() -> str:
    """注册表里要写的命令行（pythonw + run.pyw，不弹控制台窗口）。"""
    return f'"{_python_exe()}" "{entry_script()}"'


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
    return isinstance(value, str) and Path(entry_script()).name in value


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
