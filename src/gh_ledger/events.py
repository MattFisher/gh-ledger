"""Dated events drawn as markers on every time chart."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

import yaml

KEYS = {"date", "label", "group", "url"}


class EventsError(Exception):
    """An events file is missing or malformed."""


@dataclass(frozen=True)
class Event:
    date: date
    label: str
    group: str = ""
    url: str = ""


def load_events(paths: Iterable[Path]) -> list[Event]:
    events = [event for path in paths for event in _load_file(path)]
    return sorted(events, key=lambda event: event.date)


def _load_file(path: Path) -> list[Event]:
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EventsError(f"Events file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise EventsError(f"{path}: invalid YAML: {exc}") from None
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise EventsError(f"{path}: expected a list of events")
    events: list[Event] = []
    for index, item in enumerate(cast(list[object], raw), start=1):
        where = f"{path} event {index}"
        if not isinstance(item, dict):
            raise EventsError(f"{where}: expected a mapping with date and label")
        entry = cast(dict[str, object], item)
        unknown = sorted(set(entry) - KEYS)
        if unknown:
            raise EventsError(f"{where}: unknown key {', '.join(unknown)}")
        events.append(
            Event(
                date=_date(entry.get("date"), where),
                label=_text(entry, "label", where, required=True),
                group=_text(entry, "group", where, required=False),
                url=_text(entry, "url", where, required=False),
            )
        )
    return events


def _date(value: object, where: str) -> date:
    if value is None:
        raise EventsError(f"{where}: missing date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise EventsError(f"{where}: date must be YYYY-MM-DD")


def _text(entry: dict[str, object], key: str, where: str, *, required: bool) -> str:
    value = entry.get(key)
    if value is None or value == "":
        if required:
            raise EventsError(f"{where}: missing {key}")
        return ""
    if not isinstance(value, str):
        raise EventsError(f"{where}: {key} must be text")
    return value
