from datetime import date
from pathlib import Path

import pytest

from gh_ledger.events import Event, EventsError, load_events

EXAMPLE = Path(__file__).parent.parent / "examples" / "events" / "claude-models.yaml"


def write(tmp_path, text, name="events.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_and_sorts_across_files(tmp_path):
    a = write(
        tmp_path,
        "- date: 2025-02-24\n  label: Later\n  group: Claude\n  url: https://x\n",
        "a.yaml",
    )
    b = write(tmp_path, "- date: '2024-06-20'\n  label: Earlier\n", "b.yaml")
    assert load_events([a, b]) == [
        Event(date(2024, 6, 20), "Earlier"),
        Event(date(2025, 2, 24), "Later", group="Claude", url="https://x"),
    ]


def test_empty_file_has_no_events(tmp_path):
    assert load_events([write(tmp_path, "")]) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- label: No date\n", "event 1: missing date"),
        ("- date: 2025-01-01\n", "event 1: missing label"),
        ("- date: 2025-01-01\n  label: x\n  colour: red\n", "unknown key colour"),
        ("- date: soon\n  label: x\n", "date must be YYYY-MM-DD"),
        ("date: 2025-01-01\n", "expected a list"),
        ("- just a string\n", "event 1: expected a mapping"),
        ("- [unclosed\n", "invalid YAML"),
    ],
)
def test_invalid_events_name_file_and_entry(tmp_path, text, message):
    path = write(tmp_path, text)
    with pytest.raises(EventsError, match=message) as info:
        load_events([path])
    assert str(path) in str(info.value)


def test_missing_file(tmp_path):
    with pytest.raises(EventsError, match="not found"):
        load_events([tmp_path / "nope.yaml"])


def test_example_claude_file_is_valid():
    events = load_events([EXAMPLE])
    assert len(events) >= 10
    assert all(e.url.startswith("https://www.anthropic.com/") for e in events)
    assert all(e.group == "Claude" for e in events)
    assert [e.date for e in events] == sorted(e.date for e in events)


def test_unreadable_events_file_is_an_events_error(tmp_path):
    with pytest.raises(EventsError, match=str(tmp_path)):
        load_events([tmp_path])
