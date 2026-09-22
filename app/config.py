"""设置持久化：展示哪些服务、什么条件下变什么色。

落盘位置 ``%APPDATA%\\TokenQuota\\config.json``（没有 APPDATA 就退回家目录）。

读取时一切非法值都退回默认：配置坏了最多丢设置，不能让面板起不来。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import spec
from .assets import SERVICES

CONFIG_VERSION = 1


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "TokenQuota"


def config_path() -> Path:
    return config_dir() / "config.json"


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _bool(value, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _num(value, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return fallback
    return fallback


@dataclass
class Config:
    #: service_id -> 是否展示
    enabled: dict[str, bool] = field(default_factory=dict)
    rule: spec.Rule = field(default_factory=lambda: spec.DEFAULT_RULE)
    colors: dict[str, str] = field(default_factory=lambda: dict(spec.DEFAULT_COLORS))

    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "Config":
        return cls(
            enabled={s.id: True for s in SERVICES},
            rule=spec.DEFAULT_RULE,
            colors=dict(spec.DEFAULT_COLORS),
        )

    @property
    def services(self) -> tuple:
        return tuple(s for s in SERVICES if self.enabled.get(s.id, True))

    def enabled_ids(self) -> list[str]:
        return [s.id for s in self.services]

    # ------------------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "version": CONFIG_VERSION,
            "services": {s.id: bool(self.enabled.get(s.id, True)) for s in SERVICES},
            "rule": asdict(self.rule),
            "colors": dict(self.colors),
        }

    @classmethod
    def from_json(cls, data) -> "Config":
        root = _as_dict(data)
        raw_services = _as_dict(root.get("services"))
        enabled = {s.id: _bool(raw_services.get(s.id), True) for s in SERVICES}
        if not any(enabled.values()):
            # 一个都不显示，面板就没内容了：至少保留第一个
            enabled[SERVICES[0].id] = True

        raw_rule = _as_dict(root.get("rule"))
        rule = spec.Rule(
            low_enabled=_bool(raw_rule.get("low_enabled"), spec.DEFAULT_RULE.low_enabled),
            low_pct=_num(raw_rule.get("low_pct"), spec.DEFAULT_RULE.low_pct),
            pace_enabled=_bool(raw_rule.get("pace_enabled"), spec.DEFAULT_RULE.pace_enabled),
            pace_gap_pct=_num(raw_rule.get("pace_gap_pct"), spec.DEFAULT_RULE.pace_gap_pct),
        ).clamp()

        return cls(
            enabled=enabled,
            rule=rule,
            colors=spec.normalize_colors(root.get("colors")),
        )


def load() -> Config:
    path = config_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            return Config.from_json(json.load(fh))
    except FileNotFoundError:
        return Config.default()
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        # 文件损坏就当没设置过，下次保存会覆盖它
        return Config.default()


def save(config: Config) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(config.to_json(), fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return path
