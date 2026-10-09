"""Date windows for GitHub search, bisected to stay under the 1,000-result cap."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from gh_ledger.client import GitHubClient

SEARCH_CAP = 1000
SETTLE_AFTER = timedelta(days=30)
QUALIFIER_TIME = "%Y-%m-%dT%H:%M:%S+00:00"
ONE_SECOND = timedelta(seconds=1)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Window:
    """An inclusive UTC time range, at one-second resolution."""

    start: datetime
    end: datetime

    def qualifier(self) -> str:
        return f"{self.start.strftime(QUALIFIER_TIME)}..{self.end.strftime(QUALIFIER_TIME)}"

    def halves(self) -> tuple[Window, Window] | None:
        seconds = int((self.end - self.start).total_seconds())
        if seconds < 1:
            return None
        mid = self.start + timedelta(seconds=seconds // 2)
        return Window(self.start, mid), Window(mid + ONE_SECOND, self.end)

    def is_settled(self, now: datetime) -> bool:
        """True when the window ended long enough ago that its results won't change."""
        return self.end < now - SETTLE_AFTER


@dataclass(frozen=True)
class Page[T]:
    total: int
    items: list[T]
    cursor: str | None  # pass back to fetch the next page; None when done


type PageFetcher[T] = Callable[[Window, str | None], Page[T]]


@dataclass(frozen=True)
class SearchHit:
    node: dict[str, Any]
    settled: bool  # came from a window old enough to be served from cache


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)


def month_windows(since: date, until: date) -> list[Window]:
    """Calendar-month windows covering [since, until], clipped at both ends."""
    windows: list[Window] = []
    current = since
    while current <= until:
        next_month = date(current.year + current.month // 12, current.month % 12 + 1, 1)
        last = min(next_month - timedelta(days=1), until)
        windows.append(Window(_day_start(current), _day_end(last)))
        current = next_month
    return windows


def year_spans(since: date, until: date) -> list[Window]:
    """Spans of at most 365 days: contributionsCollection rejects ranges over a year."""
    spans: list[Window] = []
    start, end = _day_start(since), _day_end(until)
    while start <= end:
        span_end = min(start + timedelta(days=365) - ONE_SECOND, end)
        spans.append(Window(start, span_end))
        start = span_end + ONE_SECOND
    return spans


def search_windowed[T](
    windows: Iterable[Window], fetch_page: PageFetcher[T], cap: int = SEARCH_CAP
) -> Iterator[T]:
    """Yield every result, bisecting any window whose total exceeds the cap."""
    for window in windows:
        yield from _search_window(window, fetch_page, cap)


def _search_window[T](window: Window, fetch_page: PageFetcher[T], cap: int) -> Iterator[T]:
    first = fetch_page(window, None)
    if first.total > cap:
        halves = window.halves()
        if halves is not None:
            for half in halves:
                yield from _search_window(half, fetch_page, cap)
            return
        log.warning(
            "Search window %s has %d results; only %d are reachable", window, first.total, cap
        )
    yield from first.items
    cursor = first.cursor
    while cursor is not None:
        page = fetch_page(window, cursor)
        yield from page.items
        cursor = page.cursor


def graphql_search(
    client: GitHubClient, document: str, terms: str, field: str, now: datetime
) -> PageFetcher[SearchHit]:
    """Page through a GraphQL search on one date qualifier, e.g. `created:<window>`."""

    def fetch_page(window: Window, cursor: str | None) -> Page[SearchHit]:
        settled = window.is_settled(now)
        data = client.graphql(
            document,
            {"q": f"{terms} {field}:{window.qualifier()}", "after": cursor},
            search=True,
            cacheable=settled,
        )
        found = data["search"]
        info = found["pageInfo"]
        hits = [SearchHit(node, settled) for node in found["nodes"] if node and node.get("id")]
        next_cursor = info["endCursor"] if info["hasNextPage"] else None
        return Page(total=found["issueCount"], items=hits, cursor=next_cursor)

    return fetch_page
