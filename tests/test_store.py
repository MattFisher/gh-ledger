import pytest
from builders import file_change, manifest, pr

from gh_ledger.model import FetchResult, FileChangeRow, PrRow, columns, to_csv_row
from gh_ledger.store import (
    StoreError,
    load_table,
    read_manifest,
    upsert_table,
    write_manifest,
    write_tables,
)


def test_to_csv_row_formats_bools_none_and_lists():
    row = to_csv_row(pr(state="open", files_truncated=True, co_authors=["A <a@x>", "B <b@x>"]))
    assert row["merged_at"] == ""
    assert row["files_truncated"] == "true"
    assert row["co_authors"] == "A <a@x>;B <b@x>"
    assert row["additions"] == "10"


def test_columns_follow_field_order():
    assert columns(PrRow)[:3] == ["id", "repo", "number"]


def test_upsert_replaces_rows_with_same_key(tmp_path):
    path = tmp_path / "prs.csv"
    cols = columns(PrRow)
    upsert_table(path, cols, ("id",), [to_csv_row(pr("A", title="old")), to_csv_row(pr("B"))])
    upsert_table(path, cols, ("id",), [to_csv_row(pr("A", title="new"))])
    frame = load_table(tmp_path, "prs")
    assert sorted(frame["id"]) == ["A", "B"]
    assert frame.set_index("id").loc["A", "title"] == "new"


def test_upsert_replaces_a_whole_file_group(tmp_path):
    path = tmp_path / "file_changes.csv"
    cols = columns(FileChangeRow)
    key = ("source", "source_id")
    first = [file_change("PR_1", "a.py"), file_change("PR_1", "b.py"), file_change("PR_2", "c.py")]
    upsert_table(path, cols, key, [to_csv_row(r) for r in first])
    upsert_table(path, cols, key, [to_csv_row(file_change("PR_1", "a.py"))])
    frame = load_table(tmp_path, "file_changes")
    assert sorted(zip(frame["source_id"], frame["path"], strict=True)) == [
        ("PR_1", "a.py"),
        ("PR_2", "c.py"),
    ]


def test_text_with_newlines_and_commas_round_trips(tmp_path):
    text = 'Body, with "quotes"\n\nCo-authored-by: Claude <noreply@anthropic.com>'
    write_tables(tmp_path, FetchResult(prs=[pr(text=text)]))
    assert load_table(tmp_path, "prs").loc[0, "text"] == text


def test_write_tables_writes_every_table_even_when_empty(tmp_path):
    write_tables(tmp_path, FetchResult())
    for name in ("repos", "prs", "issues", "reviews", "comments", "commits", "file_changes"):
        assert load_table(tmp_path, name).empty


def test_upsert_rejects_a_file_with_other_columns(tmp_path):
    path = tmp_path / "prs.csv"
    path.write_text("id,title\nA,x\n", encoding="utf-8")
    with pytest.raises(StoreError, match="columns"):
        upsert_table(path, columns(PrRow), ("id",), [])


def test_load_table_missing_file_says_to_fetch(tmp_path):
    with pytest.raises(StoreError, match="gh-ledger fetch"):
        load_table(tmp_path, "prs")


def test_manifest_round_trip(tmp_path):
    assert read_manifest(tmp_path) is None
    original = manifest()
    original.skipped_repos.append("octo/gone")
    write_manifest(tmp_path, original)
    assert read_manifest(tmp_path) == original
