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


DEFAULT_EXCLUDES: tuple[str, ...] = (
    # Lockfiles
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
    # Data and notebooks
    "*.json",
    "*.jsonl",
    "*.csv",
    "*.tsv",
    "*.ipynb",
    "*.svg",
    "*.parquet",
    # Vendored and build output
    "vendor/",
    "node_modules/",
    "dist/",
    "build/",
    "*.min.js",
    "*.min.css",
    "*.map",
)

DEFAULT_AI_PATTERNS: tuple[str, ...] = (
    r"(?i)co-authored-by:.*\b(claude|copilot|cursor|codex|gemini|devin)\b",
    r"(?i)generated with \[?claude code",
    r"(?i)posted by \[?claude code",
)


def _glob_to_regex(pattern: str) -> str:
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return "".join(parts)


def _compile(globs: list[str]) -> re.Pattern[str] | None:
    if not globs:
        return None
    return re.compile("|".join(f"(?:{_glob_to_regex(glob)})" for glob in globs))


class PathFilter:
    """Decides whether a changed file is left out of filtered line counts.

    Patterns follow a subset of .gitignore:
    - `name/` excludes any path with a directory called `name`, at any depth.
    - A pattern without `/` matches the file name at any depth (`*.json`, `uv.lock`).
    - Any other pattern matches the whole path from the repo root (`fixtures/**`).
      `*` stays within one directory; `**` crosses directories.
    """

    def __init__(self, patterns: Iterable[str]) -> None:
        dirs: set[str] = set()
        names: list[str] = []
        paths: list[str] = []
        for raw in patterns:
            pattern = raw.lstrip("/")
            if pattern.endswith("/") and "/" not in pattern[:-1]:
                dirs.add(pattern[:-1])
            elif pattern.endswith("/"):
                paths.append(pattern + "**")
            elif "/" in pattern:
                paths.append(pattern)
            else:
                names.append(pattern)
        self._dirs = frozenset(dirs)
        self._names = _compile(names)
        self._paths = _compile(paths)

    def excluded(self, path: str) -> bool:
        *parents, name = path.split("/")
        if any(part in self._dirs for part in parents):
            return True
        if self._names is not None and self._names.fullmatch(name):
            return True
        return self._paths is not None and self._paths.fullmatch(path) is not None


class AiMatcher:
    """An item is AI-assisted if any pattern matches its text or a co-author trailer."""

    def __init__(self, patterns: Iterable[str]) -> None:
        self._patterns = [re.compile(pattern) for pattern in patterns]

    def matches(self, text: str, co_authors: Iterable[str] = ()) -> bool:
        candidates = [text, *(f"Co-Authored-By: {entry}" for entry in co_authors)]
        return any(p.search(c) for p in self._patterns for c in candidates)
