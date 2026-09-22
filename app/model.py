"""额度数据模型。

面板的行靠位置区分、不写标签，所以真实服务的窗口长度未必正好是
5H / 1W / 1M，统一按窗口分钟数归槽；具体显示哪几个槽位由
``assets.Service.slots`` 声明（Codex 没有月额度，只显示两行）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: 面板的固定行序：5H / 1W / 1M
PERIOD_KEYS = ("h5", "week", "month")

#: 期限的语义长度（仅用于 EXP 文案兜底；有真实 windowMinutes 时以真实值为准）
PERIOD_WINDOW_SEC = {"h5": 5 * 3600, "week": 7 * 86400, "month": 30 * 86400}
PERIOD_LABEL = {"h5": "5H", "week": "1W", "month": "1M"}


def slot_for_window_minutes(minutes: float | None) -> str | None:
    """把真实窗口长度归到 5H / 1W / 1M 三个槽位。"""
    if minutes is None:
        return None
    if minutes <= 12 * 60:
        return "h5"
    if minutes <= 14 * 24 * 60:
        return "week"
    return "month"


@dataclass
class QuotaWindow:
    """一个额度窗口。"""

    used_ratio: float  # 0..1 已用比例
    window_minutes: int | None = None
    resets_at: float | None = None  # epoch 秒

    @property
    def remaining_ratio(self) -> float:
        return min(1.0, max(0.0, 1.0 - self.used_ratio))

    def seconds_to_reset(self, now: float | None = None) -> float | None:
        if self.resets_at is None:
            return None
        now = time.time() if now is None else now
        return max(0.0, self.resets_at - now)


@dataclass
class ServiceSnapshot:
    """一次取数的结果。失败时保留上一份可用数据并把 error 填上（陈旧标记）。"""

    service_id: str
    windows: dict[str, QuotaWindow | None] = field(default_factory=dict)
    reset_credits: int | None = None
    #: 最近一张「额度重置卡」的过期时间（epoch 秒）。只有 Codex 有这种东西。
    reset_expires_at: float | None = None
    plan: str | None = None
    source: str | None = None
    fetched_at: float = 0.0
    error: str | None = None

    @property
    def age(self) -> float:
        if not self.fetched_at:
            return float("inf")
        return max(0.0, time.time() - self.fetched_at)

    @property
    def has_data(self) -> bool:
        return any(w is not None for w in self.windows.values())
