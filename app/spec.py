"""视觉规范与呈现规则。

尺寸、配色、告警规则全部来自 ``prototype/bars.html``（同一套设计语言），
但这里的规则是**纯函数**，不导入 Qt，方便单独验证。
面板只负责把这里算出来的东西画出来。

M2 起，「什么时候变成什么颜色」由 :class:`Rule` + ``colors`` 决定，
用户可以改（见 ``app/config.py``），默认值就是这里的 :data:`DEFAULT_RULE`
与 :data:`DEFAULT_COLORS`。
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, replace

from .assets import Service
from .model import PERIOD_LABEL, PERIOD_WINDOW_SEC, QuotaWindow, ServiceSnapshot

# ============================ 尺寸（逻辑像素） ============================

CARD_W = 176
CARD_PAD_X = 13
CARD_PAD_TOP = 12
CARD_PAD_BOTTOM = 13
CARD_RADIUS = 18
CONTENT_W = CARD_W - CARD_PAD_X * 2  # 150

GROUP_GAP = 12  # .group + .group { margin-top }

HEAD_GAP = 5  # .head gap
HEAD_PAD_BOTTOM = 7  # .head padding-bottom
ICON_SIZE = 14  # .icon 14x14
NAME_PX = 11.5  # .name font-size
META_PX = 9.5  # .meta font-size
PILL_PAD_X = 4  # .cnt padding
PILL_PAD_Y = 1
PILL_GAP = 3  # .meta gap

ROW_GAP = 5  # .row gap
ROW_PAD_Y = 2  # .row padding
PCT_W = 32  # .pct width
PCT_PX = 13  # .pct font-size
BAR_H = 8  # .bar height
BAR_MAX_W = 72  # .bar max-width
REST_W = 33  # .rest width
REST_PX = 11  # .rest font-size

# 底部工具行（设置齿轮）
FOOT_H = 20
FOOT_PAD_TOP = 6
GEAR_SIZE = 14
GEAR_PX = 9.5  # 「设置」两个字

# ============================ 折叠态指示条 ============================

COLLAPSED_W = 8  # 折叠时窗口/药丸宽度
COLLAPSED_H = 96  # 药丸高度
COLLAPSED_INSET = 6  # 药丸上下内边距
COLLAPSED_BAR_W = 3  # 内部竖条宽度
COLLAPSED_GAP = 6  # 两条之间的间距
COLLAPSED_RADIUS = 4

# ============================ 配色（深色，不透明） ============================

BG = "#151a23"
BORDER = "#2a3140"
DIVIDER = "#222834"
TRACK = "#292d36"
TRACK_EDGE = "#22272f"
PILL = "#272b34"

TEXT_STRONG = "#f3f5f9"
TEXT_2 = "#cbd3e1"
TEXT_MUTED = "#9aa3b6"

#: 三档提示色。红不是纯红，偏珊瑚色，压在深色底上不刺眼
GREEN = "#2fbf71"  # 正常
ORANGE = "#f5a524"  # 注意
RED = "#f2555a"  # 危险

#: 兼容 M1 里的旧名字
LV1 = ORANGE
LV2 = RED

#: 陈旧徽标用注意色
STALE_BADGE = ORANGE

COLOR_SLOTS = ("ok", "warn", "danger")
COLOR_LABEL = {"ok": "正常", "warn": "注意", "danger": "危险"}

DEFAULT_COLORS = {"ok": GREEN, "warn": ORANGE, "danger": RED}

#: 设置里可选的配色（每档几个好看的预设）
COLOR_PALETTE: dict[str, tuple[tuple[str, str], ...]] = {
    "ok": (
        ("薄荷绿", "#2fbf71"),
        ("青竹绿", "#10a37f"),
        ("石板蓝", "#6c7bff"),
    ),
    "warn": (
        ("琥珀橙", "#f5a524"),
        ("沙金", "#d9a13b"),
        ("南瓜橙", "#f2812f"),
    ),
    "danger": (
        ("珊瑚红", "#f2555a"),
        ("胭脂红", "#e5484d"),
        ("砖橙红", "#e8663f"),
    ),
}

#: 超过这个时长没有成功取数就标记为陈旧
STALE_AFTER = 15 * 60

#: 折叠窗口在屏幕右边缘的悬停命中区外扩量
HOVER_PAD = 6

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def bar_width() -> float:
    """长条宽度：内容宽度减去两侧固定列与间距，再受 max-width 限制。"""
    return min(CONTENT_W - PCT_W - REST_W - ROW_GAP * 2, BAR_MAX_W)


# ============================ 变色规则 ============================


@dataclass(frozen=True)
class Rule:
    """什么时候变色。

    * ``low_pct``：剩余额度掉到这个百分比（含）以下 → 危险档（默认红）。
    * ``pace_gap_pct``：剩余额度与「剩余时间」差得超过这个百分比 → 注意档（默认橙）。
      时间快到但额度还剩一大堆（会浪费），或者额度掉得比时间快（撑不到重置）。
    """

    low_enabled: bool = True
    low_pct: float = 20.0
    pace_enabled: bool = True
    pace_gap_pct: float = 30.0

    def clamp(self) -> "Rule":
        return replace(
            self,
            low_pct=max(0.0, min(100.0, float(self.low_pct))),
            pace_gap_pct=max(0.0, min(100.0, float(self.pace_gap_pct))),
        )


DEFAULT_RULE = Rule()


def normalize_color(value, fallback: str) -> str:
    if isinstance(value, str) and _HEX_RE.match(value.strip()):
        return value.strip()
    return fallback


def normalize_colors(raw) -> dict[str, str]:
    """把外部（配置文件）来的配色收拾成合法的三档。"""
    data = raw if isinstance(raw, dict) else {}
    return {slot: normalize_color(data.get(slot), DEFAULT_COLORS[slot]) for slot in COLOR_SLOTS}


# ============================ 文案 ============================


def pct_text(r: float) -> str:
    """百分比：>=99.9% 直接显示 100%，否则向下取整（不虚报额度）。

    ``+1e-9`` 只是抵消补数运算的浮点误差：67% 已用算出来是
    0.32999999999999996，直接 floor 会显示成 32%。
    """
    if r >= 0.999:
        return "100%"
    return f"{math.floor(r * 100 + 1e-9)}%"


def win_text(seconds: float) -> str:
    """窗口长度：5h / 7d / 30d。"""
    days = math.floor(seconds / 86400)
    return f"{days}d" if days >= 1 else f"{math.floor(seconds / 3600)}h"


def exp_text(sec: float) -> str:
    """额度重置卡的过期时间（还剩多久过期）。"""
    s = max(0, math.floor(sec))
    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60
    if d >= 1:
        return f"{d}d"
    if h >= 1:
        return f"{h}h"
    return f"{m}m" if s >= 60 else "<1m"


def rest_text(sec: float, slot: str) -> str:
    """距下次重置。

    小时之后不带分钟单位字母（4h23m → 4h23）；只有不足 1 小时才保留 ``m``,
    否则单独一个数字无法区分「分」和「时」。
    """
    s = max(0, math.floor(sec))
    d = s // 86400
    h = (s % 86400) // 3600
    m = (s % 3600) // 60

    if slot == "h5":
        if s < 60:
            return "<1m"
        if h < 1:
            return f"{m}m"
        return f"{h}h" if m == 0 else f"{h}h{m:02d}"
    if slot == "week":
        if d >= 1:
            return f"{d}d" if h == 0 else f"{d}d{h}h"
        if h >= 1:
            return f"{h}h" if m == 0 else f"{h}h{m:02d}"
        return f"{m}m"
    # month
    if d >= 1:
        return f"{d}d"
    if h >= 1:
        return f"{h}h"
    return f"{m}m"


# ============================ 告警等级 ============================


def level_of(r: float, tr: float | None, rule: Rule | None = None) -> int:
    """0 正常（绿） / 1 注意（橙） / 2 危险（红）。

    ``r``  剩余额度比例（= 长条填充）
    ``tr`` 剩余时间比例（距重置 ÷ 窗口长度），None 表示不知道
    """
    rule = rule or DEFAULT_RULE
    if rule.low_enabled and r <= rule.low_pct / 100.0:
        return 2
    if rule.pace_enabled and tr is not None and abs(r - tr) >= rule.pace_gap_pct / 100.0:
        return 1
    return 0


def level_color(level: int, colors: dict[str, str] | None = None) -> str:
    palette = colors or DEFAULT_COLORS
    if level >= 2:
        return palette["danger"]
    if level == 1:
        return palette["warn"]
    return palette["ok"]


# ============================ 视图模型 ============================


@dataclass
class RowView:
    """一行：百分比 · 长条 · 剩余时间。"""

    slot: str
    remaining: float  # 0..1，长条填充
    level: int
    has_data: bool
    color: str = GREEN  # 这一档的提示色（画长条用）
    resets_at: float | None = None
    window_sec: float = 0.0
    #: 变色的原因（建视图时就算好，免得悬停提示和实际画出来的颜色对不上）
    reason: str | None = None

    @property
    def label(self) -> str:
        return PERIOD_LABEL.get(self.slot, self.slot.upper())

    def pct(self) -> str:
        return pct_text(self.remaining) if self.has_data else "—"

    def rest(self, now: float) -> str:
        if not self.has_data or self.resets_at is None:
            return ""
        return rest_text(max(0.0, self.resets_at - now), self.slot)

    def time_ratio(self, now: float) -> float | None:
        if not self.has_data or self.resets_at is None or self.window_sec <= 0:
            return None
        return max(0.0, min(1.0, (self.resets_at - now) / self.window_sec))

    def hint(self, now: float | None = None, rule: Rule | None = None) -> str | None:
        """这一行为什么变色（用于悬停提示）。"""
        if self.reason is not None:
            return self.reason
        rule = rule or DEFAULT_RULE
        if not self.has_data or self.level == 0:
            return None
        tr = self.time_ratio(now if now is not None else time.time())
        return _reason_for(self.remaining, self.level, tr, rule)


def _reason_for(r: float, level: int, tr: float | None, rule: Rule) -> str | None:
    if level <= 0:
        return None
    if level >= 2:
        return f"额度仅剩 {pct_text(r)}，快用完了"
    gap = rule.pace_gap_pct / 100.0
    if tr is not None:
        if r - tr >= gap:
            return "时间过半额度还剩很多，重置前用不完"
        if tr - r >= gap:
            return "按当前消耗速度撑不到下次重置"
    return "额度与时间进度不匹配"


@dataclass
class ServiceView:
    """一个订阅：1 行标题 + N 行长条（行数由服务自己声明）。"""

    service: Service
    rows: list[RowView]
    exp_text: str | None = None
    count_text: str | None = None
    stale: bool = False
    note: str | None = None
    ok_color: str = GREEN

    @property
    def accent(self) -> str:
        return self.service.accent

    def worst_level(self) -> int:
        levels = [r.level for r in self.rows if r.has_data]
        return max(levels) if levels else 0

    def status_color(self) -> str:
        """折叠指示条用的颜色：跟提示色一致。"""
        worst = self.worst_level()
        for row in self.rows:
            if row.has_data and row.level == worst:
                return row.color
        return self.ok_color

    def headline_remaining(self) -> float:
        """折叠态用来画柱状高度的代表值：取最有代表性的那行。

        5H 变化最快、最需要一眼看到，所以优先用它。
        """
        for row in self.rows:
            if row.has_data:
                return row.remaining
        return 0.0

    def tooltip(self, now: float, rule: Rule | None = None) -> str:
        lines = [self.service.name]
        for row in self.rows:
            if not row.has_data:
                continue
            rest = row.rest(now)
            seg = f"{row.label}  剩 {row.pct()}"
            if rest:
                seg += f"  ·  {rest} 后重置"
            hint = row.hint(now, rule)
            if hint:
                seg += f"（{hint}）"
            lines.append(seg)
        if self.count_text:
            lines.append(f"可用额度重置次数：{self.count_text}")
        if self.exp_text:
            lines.append(f"最近一张重置卡：{self.exp_text}")
        if self.stale and self.note:
            lines.append(f"⚠ {self.note}")
        return "\n".join(lines)


def _row_from_window(
    window: QuotaWindow | None,
    slot: str,
    now: float,
    rule: Rule,
    colors: dict[str, str],
) -> RowView:
    if window is None:
        return RowView(slot=slot, remaining=0.0, level=0, has_data=False, color=colors["ok"])

    remaining = window.remaining_ratio
    window_sec = float(window.window_minutes * 60) if window.window_minutes else PERIOD_WINDOW_SEC.get(slot, 0.0)
    resets_at = window.resets_at
    tr = None
    if resets_at is not None and window_sec > 0:
        tr = max(0.0, min(1.0, (resets_at - now) / window_sec))
    level = level_of(remaining, tr, rule)
    return RowView(
        slot=slot,
        remaining=remaining,
        level=level,
        has_data=True,
        color=level_color(level, colors),
        resets_at=resets_at,
        window_sec=window_sec,
        reason=_reason_for(remaining, level, tr, rule),
    )


def _age_text(age: float) -> str:
    if age < 3600:
        return f"{max(1, int(age // 60))} 分钟前"
    if age < 86400:
        return f"{int(age // 3600)} 小时前"
    return f"{int(age // 86400)} 天前"


#: provider / 线程抛出的异常在提示里要脱掉 "CodexError:" 这种开发者前缀
_ERROR_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception):\s*")


def human_error(message: str) -> str:
    """把异常文本收拾成给人看的说法。"""
    text = _ERROR_PREFIX.sub("", message.strip())
    return text or "未知原因"


def build_service_view(
    snapshot: ServiceSnapshot | None,
    service: Service,
    now: float,
    rule: Rule | None = None,
    colors: dict[str, str] | None = None,
) -> ServiceView:
    rule = rule or DEFAULT_RULE
    colors = colors or DEFAULT_COLORS
    rows = [
        _row_from_window(snapshot.windows.get(slot) if snapshot else None, slot, now, rule, colors)
        for slot in service.slots
    ]

    exp_text_value = None
    count_text = None
    stale = True
    note: str | None = "尚未取到数据"

    if snapshot is not None:
        # EXP = 最近一张额度重置卡的过期时间（只有 Codex 有这种东西）
        if service.show_exp and snapshot.reset_expires_at:
            left = snapshot.reset_expires_at - now
            if left > 0:
                exp_text_value = f"EXP {exp_text(left)}"

        if snapshot.reset_credits is not None:
            count_text = str(snapshot.reset_credits)

        age = snapshot.age
        if snapshot.has_data:
            if snapshot.error:
                # 有旧数据可看：说清这是什么时候的，顺带给出失败原因
                stale = True
                note = f"实时取数失败（{human_error(snapshot.error)}），显示 {_age_text(age)}的数据"
            elif age > STALE_AFTER:
                stale = True
                note = f"数据已过期（{_age_text(age)}）"
            else:
                stale = False
                note = None
        else:
            stale = True
            note = f"取数失败：{human_error(snapshot.error)}" if snapshot.error else "没有可用额度窗口"

    return ServiceView(
        service=service,
        rows=rows,
        exp_text=exp_text_value,
        count_text=count_text,
        stale=stale,
        note=note,
        ok_color=colors["ok"],
    )


def build_views(
    snapshots: dict[str, ServiceSnapshot | None],
    services,
    now: float | None = None,
    rule: Rule | None = None,
    colors: dict[str, str] | None = None,
) -> list[ServiceView]:
    now = time.time() if now is None else now
    return [build_service_view(snapshots.get(s.id), s, now, rule, colors) for s in services]
