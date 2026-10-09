"""Trailer parsing, path exclusion and AI-assistance markers."""

from __future__ import annotations

import re
from collections.abc import Iterable

_CO_AUTHOR = re.compile(r"^\s*co-authored-by:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def parse_co_authors(messages: Iterable[str]) -> tuple[str, ...]:
    """Union of `Co-authored-by` trailer values, first spelling wins, order kept."""
    seen: dict[str, str] = {}
    for message in messages:
        for match in _CO_AUTHOR.finditer(message):
            entry = match.group(1)
            seen.setdefault(entry.lower(), entry)
    return tuple(seen.values())
