"""Load `ledger.toml`. Every key is optional and falls back to a built-in default."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from gh_ledger.filters import DEFAULT_AI_PATTERNS, DEFAULT_EXCLUDES

PERIODS = ("week", "month", "quarter")
CHART_NAMES = ("activity", "lines", "review_mix", "ai_share", "repos", "compare")
MAX_TOP_REPOS = 8  # one categorical colour each; the rest fold into "other"

Table = dict[str, object]


class ConfigError(Exception):
    """ledger.toml is unreadable or holds an invalid value."""


@dataclass(frozen=True)
class FiltersConfig:
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    per_file_cap: int | None = 1000
    count_unmerged_pr_lines: bool = False


@dataclass(frozen=True)
class AiConfig:
    patterns: tuple[str, ...] = DEFAULT_AI_PATTERNS


@dataclass(frozen=True)
class ReportConfig:
    period: str = "month"
    title: str = "GitHub activity"
    top_repos: int = 8
    compare_at: date | None = None
    charts: tuple[str, ...] = CHART_NAMES
    image_size: tuple[int, int] = (1200, 600)


@dataclass(frozen=True)
class Config:
    filters: FiltersConfig = field(default_factory=FiltersConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    report: ReportConfig = field(default_factory=ReportConfig)


def load_config(path: Path | None) -> Config:
    if path is None:
        return Config()
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    try:
        _check_keys(raw, {"filters", "ai", "report"}, "the top level")
        return Config(
            filters=_filters(_table(raw, "filters")),
            ai=_ai(_table(raw, "ai")),
            report=_report(_table(raw, "report")),
        )
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None


def _table(raw: dict[str, Any], name: str) -> Table:
    value: object = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return cast(Table, value)


def _check_keys(table: dict[str, Any] | Table, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"unknown key {', '.join(unknown)} in {where}")


def _strings(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{key} must be a list of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise ConfigError(f"{key} must be a list of strings")
    return tuple(cast(list[str], items))


def _filters(table: Table) -> FiltersConfig:
    _check_keys(
        table, {"exclude", "extra_exclude", "per_file_cap", "count_unmerged_pr_lines"}, "[filters]"
    )
    exclude = (
        _strings(table["exclude"], "[filters].exclude") if "exclude" in table else DEFAULT_EXCLUDES
    )
    exclude += _strings(table.get("extra_exclude", []), "[filters].extra_exclude")
    cap = table.get("per_file_cap", 1000)
    per_file_cap: int | None
    if cap is False:
        per_file_cap = None
    elif isinstance(cap, int) and not isinstance(cap, bool) and cap > 0:
        per_file_cap = cap
    else:
        raise ConfigError("[filters].per_file_cap must be a positive integer or false")
    unmerged = table.get("count_unmerged_pr_lines", False)
    if not isinstance(unmerged, bool):
        raise ConfigError("[filters].count_unmerged_pr_lines must be true or false")
    return FiltersConfig(
        exclude=exclude, per_file_cap=per_file_cap, count_unmerged_pr_lines=unmerged
    )


def _ai(table: Table) -> AiConfig:
    _check_keys(table, {"patterns"}, "[ai]")
    patterns = (
        _strings(table["patterns"], "[ai].patterns") if "patterns" in table else DEFAULT_AI_PATTERNS
    )
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"[ai].patterns: invalid regex {pattern!r}: {exc}") from None
    return AiConfig(patterns=patterns)


def _report(table: Table) -> ReportConfig:
    _check_keys(
        table, {"period", "title", "top_repos", "compare_at", "charts", "image_size"}, "[report]"
    )
    defaults = ReportConfig()
    period = table.get("period", defaults.period)
    if not isinstance(period, str) or period not in PERIODS:
        raise ConfigError(f"[report].period must be one of {', '.join(PERIODS)}")
    title = table.get("title", defaults.title)
    if not isinstance(title, str):
        raise ConfigError("[report].title must be a string")
    top = table.get("top_repos", defaults.top_repos)
    if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= MAX_TOP_REPOS:
        raise ConfigError(f"[report].top_repos must be an integer from 1 to {MAX_TOP_REPOS}")
    charts = _strings(table["charts"], "[report].charts") if "charts" in table else defaults.charts
    unknown = [name for name in charts if name not in CHART_NAMES]
    if unknown:
        raise ConfigError(
            f"[report].charts: unknown chart {', '.join(unknown)} (choose from {', '.join(CHART_NAMES)})"
        )
    return ReportConfig(
        period=period,
        title=title,
        top_repos=top,
        compare_at=_compare_at(table.get("compare_at")),
        charts=charts,
        image_size=_image_size(table.get("image_size", list(defaults.image_size))),
    )


def _compare_at(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ConfigError("[report].compare_at must be a date like 2025-02-24")


def _image_size(value: object) -> tuple[int, int]:
    if isinstance(value, list):
        items = cast(list[object], value)
        if len(items) == 2 and all(
            isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in items
        ):
            return cast(int, items[0]), cast(int, items[1])
    raise ConfigError("[report].image_size must be [width, height] in pixels")
