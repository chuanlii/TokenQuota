"""OpenCode Go 订阅额度。

`GET https://opencode.ai/zen/go/v1/usage`，只要 Bearer key，不需要浏览器 cookie。
响应形状：{"usage":{"rolling":{status,percent,resetsAt}, "weekly":{...}, "monthly":{...}}}

`percent` 是**已用百分比**（0..100），长条填充取 100 - percent。
该端点未写进公开文档，属于非官方接口，失败必须降级处理。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..model import QuotaWindow, ServiceSnapshot

USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
HTTP_TIMEOUT = 20.0

#: 端点的三个窗口，按经验固定为 5H / 1W / 1M
FIXED_WINDOWS = (
    ("rolling", "h5", 300),
    ("weekly", "week", 10080),
    ("monthly", "month", 43200),
)


class OpenCodeGoError(RuntimeError):
    pass


def _auth_path() -> Path:
    return Path(os.path.expanduser("~")) / ".local" / "share" / "opencode" / "auth.json"


def load_api_key() -> str:
    key = (os.environ.get("OPENCODE_API_KEY") or "").strip()
    if key:
        return key

    path = _auth_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise OpenCodeGoError(
            f"未找到 OpenCode 凭证 {path}；请设置 OPENCODE_API_KEY 或先登录 opencode"
        ) from None
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenCodeGoError(f"读取 {path} 失败: {exc}") from exc

    entry = data.get("opencode-go")
    if not isinstance(entry, dict):
        raise OpenCodeGoError("auth.json 里没有 opencode-go 条目")
    value = entry.get("key")
    if not isinstance(value, str) or not value.strip():
        raise OpenCodeGoError("auth.json 的 opencode-go.key 为空")
    return value.strip()


def _parse_iso(value) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _request(key: str) -> dict:
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            # 不带这个头也能通过，但带上更接近客户端行为
            "User-Agent": "token-quota/0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise OpenCodeGoError("OpenCode Go API key 无效或已过期") from exc
        if exc.code == 429:
            raise OpenCodeGoError("OpenCode Go 接口限流，稍后重试") from exc
        raise OpenCodeGoError(f"OpenCode Go 返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OpenCodeGoError(f"请求 OpenCode Go 失败: {exc.reason}") from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenCodeGoError(f"OpenCode Go 返回了非 JSON 内容: {exc}") from exc
    if not isinstance(payload, dict):
        raise OpenCodeGoError("OpenCode Go 返回的顶层不是对象")
    return payload


def _snapshot_from_payload(payload: dict) -> ServiceSnapshot:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise OpenCodeGoError("响应里没有 usage 字段")

    windows: dict[str, QuotaWindow] = {}
    for api_key, slot, minutes in FIXED_WINDOWS:
        entry = usage.get(api_key)
        if not isinstance(entry, dict):
            continue
        percent = entry.get("percent")
        if not isinstance(percent, (int, float)) or isinstance(percent, bool):
            continue
        windows[slot] = QuotaWindow(
            used_ratio=min(1.0, max(0.0, float(percent) / 100.0)),
            window_minutes=minutes,
            resets_at=_parse_iso(entry.get("resetsAt")),
        )

    if not windows:
        raise OpenCodeGoError("usage 里没有任何可用窗口")

    return ServiceSnapshot(
        service_id="opencode",
        windows=windows,
        # Go 订阅没有「重置次数」这个量，留空由面板隐藏
        reset_credits=None,
        plan="Go",
        source="api",
        fetched_at=time.time(),
    )


def fetch_opencode_go() -> ServiceSnapshot:
    return _snapshot_from_payload(_request(load_api_key()))
