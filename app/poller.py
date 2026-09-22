"""后台轮询线程。

两个 provider 都是阻塞 IO（app-server 冷启动约 1s，HTTP 约 2s），
所以放在普通 Python 线程里跑，结果用 Qt 信号（跨线程自动排队）送回主线程。

失败策略：**保留上一份可用数据**，只把错误挂上去 —— 面板据此显示陈旧标记，
而不是把已经拿到的额度瞬间清空。
"""

from __future__ import annotations

import threading
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from .assets import SERVICES, Service
from .model import ServiceSnapshot
from .providers import fetch_codex, fetch_opencode_go

#: 正常刷新间隔
INTERVAL_OK = 60.0
#: 全部失败后的重试间隔，逐次翻倍
INTERVAL_FAIL_BASE = 30.0
INTERVAL_FAIL_MAX = 300.0

_FETCHERS = {
    "fetch_codex": fetch_codex,
    "fetch_opencode_go": fetch_opencode_go,
}


class Poller(QObject):
    """按固定节奏取数，每轮把 ``{service_id: ServiceSnapshot}`` 发出来。"""

    results = Signal(dict)

    def __init__(self, services: tuple[Service, ...] = SERVICES, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._last: dict[str, ServiceSnapshot] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._fail_rounds = 0

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="token-quota-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def refresh_now(self) -> None:
        """立刻插队刷新一次。"""
        self._wake.set()

    def latest(self) -> dict[str, ServiceSnapshot]:
        with self._lock:
            return dict(self._last)

    # ------------------------------------------------------------------ 取数

    def _loop(self) -> None:
        while not self._stop.is_set():
            snapshots: dict[str, ServiceSnapshot] = {}
            failed = 0
            for service in self._services:
                snapshot, ok = self._fetch(service)
                snapshots[service.id] = snapshot
                if not ok:
                    failed += 1

            self._fail_rounds = self._fail_rounds + 1 if failed == len(self._services) else 0
            with self._lock:
                self._last = snapshots

            if self._stop.is_set():
                return
            self.results.emit(snapshots)

            self._wake.wait(self._delay())
            self._wake.clear()

    def _fetch(self, service: Service) -> tuple[ServiceSnapshot, bool]:
        fetcher = _FETCHERS[service.provider_attr]
        try:
            return fetcher(), True
        except Exception as exc:  # noqa: BLE001 - provider 已把可预期错误包成自己的异常
            message = f"{type(exc).__name__}: {exc}"
            previous = self._last.get(service.id)
            if previous is not None and previous.has_data:
                # 保留旧数据 + 旧时间戳（age 继续变老 → 面板会自然显示「已过期」）
                return replace(previous, error=message), False
            return ServiceSnapshot(service_id=service.id, error=message), False

    def _delay(self) -> float:
        if self._fail_rounds == 0:
            return INTERVAL_OK
        return min(INTERVAL_FAIL_MAX, INTERVAL_FAIL_BASE * (2 ** (self._fail_rounds - 1)))
