from contextlib import nullcontext
from datetime import UTC, date, datetime

import pytest
from builders import manifest as make_manifest
from github_fakes import (
    contributions,
    empty_github,
    pr_node,
    repo,
    review_contribution,
    search_result,
)

from gh_ledger.cache import ResponseCache
from gh_ledger.fetch import FetchError, FetchOptions, run_fetch
from gh_ledger.store import load_table, read_manifest, write_manifest

NOW = datetime(2024, 6, 1, tzinfo=UTC)


def stage(_name):
    return nullcontext(lambda _n: None)


def options(user="OctoCat", visibility="all", since=date(2024, 1, 1), until=date(2024, 1, 31)):
    return FetchOptions(user=user, since=since, until=until, visibility=visibility)


def test_writes_tables_and_manifest(tmp_path):
    fake = empty_github()
    fake.graphql["PrSearch"] = lambda b: search_result(
        [pr_node()] if "created:" in b["variables"]["q"] else []
    )
    result = run_fetch(fake.client(), options(), tmp_path, now=NOW, stage=stage)
    assert result.user == "octocat"
    assert list(load_table(tmp_path, "prs")["id"]) == ["PR_1"]
    assert list(load_table(tmp_path, "repos")["repo"]) == ["octo/app"]
    saved = read_manifest(tmp_path)
    assert saved is not None
    assert (saved.since, saved.until, saved.visibility) == ("2024-01-01", "2024-01-31", "all")
    assert saved.fetched_at == "2024-06-01T00:00:00Z"


def test_public_fetch_drops_private_rows(tmp_path):
    fake = empty_github()
    private = review_contribution("PRR_P", repository=repo("acme/secret", private=True))
    public = review_contribution("PRR_OK")
    fake.graphql["ReviewContributions"] = lambda _b: contributions([private, public])
    run_fetch(fake.client(), options(visibility="public"), tmp_path, now=NOW, stage=stage)
    assert list(load_table(tmp_path, "reviews")["id"]) == ["PRR_OK"]
    assert "acme/secret" not in set(load_table(tmp_path, "repos")["repo"])


def test_refuses_directory_of_other_user(tmp_path):
    write_manifest(tmp_path, make_manifest(user="alice"))
    with pytest.raises(FetchError, match="alice"):
        run_fetch(empty_github().client(), options(), tmp_path, now=NOW, stage=stage)
    assert not (tmp_path / "prs.csv").exists()


def test_refuses_visibility_change(tmp_path):
    write_manifest(tmp_path, make_manifest(user="octocat", visibility="all"))
    with pytest.raises(FetchError, match="--visibility all"):
        run_fetch(
            empty_github().client(), options(visibility="public"), tmp_path, now=NOW, stage=stage
        )


def test_unknown_user(tmp_path):
    fake = empty_github()
    fake.graphql["UserCheck"] = lambda _b: {"user": None}
    with pytest.raises(FetchError, match="No GitHub user"):
        run_fetch(fake.client(), options(user="nobody-here"), tmp_path, now=NOW, stage=stage)


def test_incremental_fetch_widens_manifest_range(tmp_path):
    fake = empty_github()
    run_fetch(fake.client(), options(), tmp_path, now=NOW, stage=stage)
    earlier = options(since=date(2023, 11, 1), until=date(2023, 12, 31))
    run_fetch(fake.client(), earlier, tmp_path, now=NOW, stage=stage)
    saved = read_manifest(tmp_path)
    assert (saved.since, saved.until) == ("2023-11-01", "2024-01-31")


def test_public_fetch_keeps_private_review_text_out_of_the_cache(tmp_path):
    fake = empty_github()
    private = review_contribution(
        "PRR_P", body="SECRET-REVIEW-BODY", repository=repo("acme/secret", private=True)
    )
    fake.graphql["ReviewContributions"] = lambda _b: contributions([private])
    cache_dir = tmp_path / "data" / "cache"
    client = fake.client(cache=ResponseCache(cache_dir))
    run_fetch(client, options(visibility="public"), tmp_path / "data", now=NOW, stage=stage)
    for path in cache_dir.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="ignore")
            assert "SECRET-REVIEW-BODY" not in text
            assert "acme/secret" not in text


def test_manifest_counts_describe_the_latest_run(tmp_path):
    fake = empty_github()
    fake.graphql["ReviewContributions"] = lambda _b: contributions([], restricted=3)
    run_fetch(fake.client(), options(), tmp_path, now=NOW, stage=stage)
    assert read_manifest(tmp_path).restricted_contributions == 3
    fake.graphql["ReviewContributions"] = lambda _b: contributions([], restricted=1)
    run_fetch(fake.client(), options(), tmp_path, now=NOW, stage=stage)
    assert read_manifest(tmp_path).restricted_contributions == 1
