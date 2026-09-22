"""Codex 额度。

主路径：`codex app-server --stdio` + JSON-RPC `account/rateLimits/read`。
        由 app-server 自己处理 OAuth 刷新，所以不受 access_token 约 1 小时过期的影响。
兜底：  本地 session JSONL（`~/.codex/sessions/**/rollout-*.jsonl`）里最后一条
        `token_count` 事件的 rate_limits —— 新鲜度 = 用户上次跑 Codex 的时间。

只读主 limit（`rateLimits`，即 limitId="codex"），不显示 rateLimitsByLimitId 里的
gpt-reserve / base_model_inference 等旁路额度。
"""

from __future__ import annotations

import glob
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .. import VERSION
from ..model import QuotaWindow, ServiceSnapshot, slot_for_window_minutes

INITIALIZE_TIMEOUT = 10.0
READ_TIMEOUT = 20.0
TAIL_BYTES = 512 * 1024


class CodexError(RuntimeError):
    pass


def find_cli() -> str | None:
    """定位 codex.exe（不在 PATH，bin 目录名含版本 hash，会随版本变化）。"""
    patterns: list[str] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        patterns.append(os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe"))
    for extra in ("OPENAI_CODEX_CLI_PATH", "CODEX_CLI_PATH"):
        val = os.environ.get(extra)
        if val:
            patterns.append(val)
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(glob.glob(pattern))
    hits = [h for h in hits if os.path.isfile(h)]
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


def _rpc(exe: str) -> dict:
    """跑一次 app-server，取回 account/rateLimits/read 的 result。"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [exe, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=flags,
        )
    except OSError as exc:
        raise CodexError(f"无法启动 app-server: {exc}") from exc

    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.put(line)
        except Exception:
            pass
        finally:
            lines.put("")  # 哨兵：进程结束

    threading.Thread(target=pump, daemon=True).start()

    def send(payload: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def wait_for(msg_id: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexError(f"等待 app-server 响应 id={msg_id} 超时")
            try:
                raw = lines.get(timeout=remaining)
            except queue.Empty:
                raise CodexError(f"等待 app-server 响应 id={msg_id} 超时") from None
            if raw == "":
                raise CodexError("app-server 进程提前退出")
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue  # 通知/日志噪声
            if msg.get("id") != msg_id:
                continue  # 这是一条 notification
            if "error" in msg:
                raise CodexError(f"app-server 返回错误: {msg['error']}")
            result = msg.get("result")
            return result if isinstance(result, dict) else {}

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "token-quota",
                        "title": "Token Quota",
                        "version": VERSION,
                    }
                },
            }
        )
        wait_for(1, INITIALIZE_TIMEOUT)
        send({"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {}})
        return wait_for(2, READ_TIMEOUT)
    finally:
        try:
            proc.kill()
        except Exception:
            pass


def _to_float(value) -> float | None:  # noqa: D401
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


#: 重置卡里表示「还能用」的 status 取值
_CREDIT_OK = {"available", "usable", "active"}


def _parse_reset_credits(payload, now: float) -> tuple[int | None, float | None]:
    """解析 ``rateLimitResetCredits``：可用张数 + 最近一张的过期时间。

    只看还能用的卡；已经过期的忽略（过期时间已过就当它不存在）。
    """
    if not isinstance(payload, dict):
        return None, None

    count = None
    raw_count = payload.get("availableCount")
    if isinstance(raw_count, int) and not isinstance(raw_count, bool):
        count = raw_count

    credits = payload.get("credits")
    if not isinstance(credits, list):
        return count, None

    expiries: list[float] = []
    for item in credits:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if isinstance(status, str) and status.lower() not in _CREDIT_OK:
            continue
        expires_at = _to_float(item.get("expiresAt", item.get("expires_at")))
        if expires_at is not None and expires_at > now:
            expiries.append(expires_at)

    if count is None and credits:
        count = len(expiries)
    return count, (min(expiries) if expiries else None)


def _windows_from_records(records) -> dict[str, QuotaWindow]:
    """records: [(used_percent, window_minutes, resets_at), ...]（camel 或 snake 已归一）"""
    windows: dict[str, QuotaWindow] = {}
    for used, minutes, resets in records:
        if used is None:
            continue
        slot = slot_for_window_minutes(minutes)
        if slot is None or slot in windows:
            continue
        windows[slot] = QuotaWindow(
            used_ratio=min(1.0, max(0.0, used / 100.0)),
            window_minutes=int(minutes) if minutes else None,
            resets_at=resets,
        )
    return windows


def _snapshot_from_app_server(result: dict) -> ServiceSnapshot:
    limits = result.get("rateLimits")
    if not isinstance(limits, dict):
        raise CodexError("app-server 未返回 rateLimits（可能尚未登录，或计划不支持额度窗口）")

    records = []
    for key in ("primary", "secondary"):
        win = limits.get(key)
        if not isinstance(win, dict):
            continue
        records.append(
            (
                _to_float(win.get("usedPercent")),
                _to_float(win.get("windowDurationMins")),
                _to_float(win.get("resetsAt")),
            )
        )
    windows = _windows_from_records(records)
    if not windows:
        raise CodexError("rateLimits 里没有任何额度窗口")

    credits = result.get("rateLimitResetCredits")
    available, expires_at = _parse_reset_credits(credits, time.time())

    plan = limits.get("planType")
    return ServiceSnapshot(
        service_id="codex",
        windows=windows,
        reset_credits=available,
        reset_expires_at=expires_at,
        plan=plan if isinstance(plan, str) else None,
        source="app-server",
        fetched_at=time.time(),
    )


def _tail_lines(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # 丢弃被截断的首行
            data = fh.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def _snapshot_from_jsonl() -> ServiceSnapshot | None:
    root = Path(os.path.expanduser("~")) / ".codex" / "sessions"
    if not root.is_dir():
        return None
    files = [Path(p) for p in glob.glob(str(root / "**" / "rollout-*.jsonl"), recursive=True)]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)

    for path in files[:8]:
        for line in reversed(_tail_lines(path)):
            if "token_count" not in line or "rate_limits" not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = rec.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            limits = payload.get("rate_limits")
            if not isinstance(limits, dict):
                continue

            records = []
            for key in ("primary", "secondary"):
                win = limits.get(key)
                if not isinstance(win, dict):
                    continue
                records.append(
                    (
                        _to_float(win.get("used_percent", win.get("usedPercent"))),
                        _to_float(win.get("window_minutes", win.get("windowDurationMins"))),
                        _to_float(win.get("resets_at", win.get("resetsAt"))),
                    )
                )
            windows = _windows_from_records(records)
            if not windows:
                continue

            return ServiceSnapshot(
                service_id="codex",
                windows=windows,
                plan=limits.get("limit_name") or limits.get("limit_id"),
                source="jsonl",
                fetched_at=path.stat().st_mtime,
            )
    return None


def fetch_codex() -> ServiceSnapshot:
    exe = find_cli()
    primary_error: Exception | None = None

    if exe:
        try:
            return _snapshot_from_app_server(_rpc(exe))
        except Exception as exc:  # noqa: BLE001 - 任何失败都退到离线兜底
            primary_error = exc
    else:
        primary_error = CodexError("未找到 codex.exe（OpenAI\\Codex\\bin\\*\\codex.exe）")

    snapshot = _snapshot_from_jsonl()
    if snapshot is not None:
        # 只挂失败原因：面板会自己拼成「实时取数失败（原因），显示 X 前的数据」，
        # 「已回退到本地记录」这件事由 source="jsonl" 表达，避免提示里自相重复。
        snapshot.error = str(primary_error)
        return snapshot

    raise CodexError(str(primary_error))
