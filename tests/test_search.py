from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

from gh_ledger.fetch.search import (
    Page,
    Window,
    month_windows,
    search_windowed,
    year_spans,
)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def test_month_windows_clip_to_range():
    windows = month_windows(date(2024, 1, 15), date(2024, 3, 10))
    assert [(w.start, w.end) for w in windows] == [
        (utc(2024, 1, 15), utc(2024, 1, 31, 23, 59, 59)),
        (utc(2024, 2, 1), utc(2024, 2, 29, 23, 59, 59)),
        (utc(2024, 3, 1), utc(2024, 3, 10, 23, 59, 59)),
    ]


def test_month_windows_cross_year_end():
    windows = month_windows(date(2023, 12, 1), date(2024, 1, 31))
    assert [w.start.month for w in windows] == [12, 1]


def test_qualifier_uses_explicit_utc_times():
    window = Window(utc(2024, 1, 1), utc(2024, 1, 31, 23, 59, 59))
    assert window.qualifier() == "2024-01-01T00:00:00+00:00..2024-01-31T23:59:59+00:00"


def test_halves_cover_window_without_gap_or_overlap():
    window = Window(utc(2024, 1, 1), utc(2024, 1, 31, 23, 59, 59))
    left, right = window.halves()
    assert left.start == window.start
    assert right.end == window.end
    assert right.start - left.end == timedelta(seconds=1)


def test_one_second_window_cannot_split():
    moment = utc(2024, 1, 1)
    assert Window(moment, moment).halves() is None


def test_is_settled_after_thirty_days():
    window = Window(utc(2024, 1, 1), utc(2024, 1, 31, 23, 59, 59))
    assert window.is_settled(utc(2024, 3, 2))
    assert not window.is_settled(utc(2024, 2, 20))


def test_year_spans_are_contiguous_and_at_most_365_days():
    spans = year_spans(date(2022, 3, 1), date(2024, 6, 30))
    assert spans[0].start == utc(2022, 3, 1)
    assert spans[-1].end == utc(2024, 6, 30, 23, 59, 59)
    for span in spans:
        assert span.end - span.start < timedelta(days=365)
    for left, right in pairwise(spans):
        assert right.start - left.end == timedelta(seconds=1)


def fake_search(stamps, page_size=2):
    """A fetch_page over a list of timestamps, recording each call."""
    calls = []

    def fetch_page(window, cursor):
        calls.append((window, cursor))
        hits = [s for s in stamps if window.start <= s <= window.end]
        offset = int(cursor or 0)
        chunk = hits[offset : offset + page_size]
        more = offset + page_size < len(hits)
        return Page(total=len(hits), items=chunk, cursor=str(offset + page_size) if more else None)

    return fetch_page, calls


def test_search_windowed_pages_through_results():
    stamps = [utc(2024, 1, d) for d in (2, 5, 9, 20, 28)]
    fetch_page, calls = fake_search(stamps)
    found = list(search_windowed(month_windows(date(2024, 1, 1), date(2024, 1, 31)), fetch_page))
    assert found == stamps
    assert len(calls) == 3


def test_search_windowed_bisects_windows_over_the_cap():
    # Twelve results inside one day, cap 3: bisection must go below a day.
    stamps = [utc(2024, 1, 10, h) for h in range(12)] + [utc(2024, 1, 25)]
    fetch_page, _ = fake_search(stamps)
    windows = month_windows(date(2024, 1, 1), date(2024, 1, 31))
    found = list(search_windowed(windows, fetch_page, cap=3))
    assert sorted(found) == sorted(stamps)
    assert len(found) == len(stamps)
