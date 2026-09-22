"""单实例保护（命名互斥体）。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """持有命名互斥体；``already_running`` 为真说明已经有一个实例在跑。"""

    def __init__(self, name: str = "TokenQuota.Panel") -> None:
        self._handle = None
        self.already_running = False
        self.available = os.name == "nt"
        if not self.available:
            return

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError:
            self.available = False
            return

        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
        self._handle = handle
        self.already_running = bool(handle) and ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        self._kernel32 = kernel32

    def release(self) -> None:
        if self._handle:
            try:
                self._kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
