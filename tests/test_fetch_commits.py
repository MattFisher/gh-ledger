from datetime import UTC, date, datetime

import httpx
from github_fakes import FakeGitHub, associations, commit_detail, commit_item, noop

from gh_ledger.fetch.commits import fetch_commits

NOW = datetime(2024, 6, 1, tzinfo=UTC)


def run(fake, author_emails=(), public_only=False):
    return fetch_commits(
        fake.client(),
        "octocat",
        date(2024, 1, 1),
        date(2024, 1, 31),
        author_emails=author_emails,
        public_only=public_only,
        now=NOW,
        tick=noop,
    )


def search(*items):
    return lambda _request: {"total_count": len(items), "items": list(items)}


def test_direct_commit_rows_and_files():
    fake = FakeGitHub()
    message = "fix: thing\n\nCo-authored-by: Claude <noreply@anthropic.com>"
    fake.rest["/search/commits"] = search(commit_item("aaa", message=message))
    fake.graphql["CommitAssociations"] = associations()
    fake.rest["/repos/octo/app/commits/aaa"] = lambda _r: commit_detail(
        "aaa", [("src/a.py", 5, 1), ("data.json", 100, 0)]
    )
    result = run(fake)
    [commit] = result.commits
    assert (commit.sha, commit.repo, commit.additions, commit.deletions) == (
        "aaa",
        "octo/app",
        105,
        1,
    )
    assert commit.co_authors == ("Claude <noreply@anthropic.com>",)
    assert not commit.files_truncated
    assert [(f.source, f.source_id, f.path) for f in result.file_changes] == [
        ("commit", "aaa", "src/a.py"),
        ("commit", "aaa", "data.json"),
    ]
    assert result.repos[0].repo == "octo/app"


def test_pr_attached_commits_are_dropped_and_counted():
    fake = FakeGitHub()
    fake.rest["/search/commits"] = search(commit_item("aaa"), commit_item("bbb"))
    fake.graphql["CommitAssociations"] = associations(attached={"aaa"})
    fake.rest["/repos/octo/app/commits/bbb"] = lambda _r: commit_detail("bbb", [("x.py", 1, 0)])
    result = run(fake)
    assert [c.sha for c in result.commits] == ["bbb"]
    assert result.dropped_pr_commits == 1
    assert "/repos/octo/app/commits/aaa" not in fake.calls


def test_author_dates_are_normalised_to_utc():
    fake = FakeGitHub()
    fake.rest["/search/commits"] = search(commit_item("aaa", "2024-01-31T23:30:00.000-05:00"))
    fake.graphql["CommitAssociations"] = associations()
    fake.rest["/repos/octo/app/commits/aaa"] = lambda _r: commit_detail("aaa", [("x.py", 1, 0)])
    result = run(fake)
    assert result.commits[0].authored_at == "2024-02-01T04:30:00Z"
    assert result.file_changes[0].date == "2024-02-01T04:30:00Z"


def test_commit_files_are_paged():
    fake = FakeGitHub()
    fake.rest["/search/commits"] = search(commit_item("aaa"))
    fake.graphql["CommitAssociations"] = associations()
    first = [(f"f{i}.py", 1, 0) for i in range(100)]
    second = [(f"g{i}.py", 1, 0) for i in range(5)]
    stats = {"additions": 105, "deletions": 0}

    def detail(request):
        page = request.url.params["page"]
        return commit_detail("aaa", first if page == "1" else second, stats=stats)

    fake.rest["/repos/octo/app/commits/aaa"] = detail
    result = run(fake)
    assert len(result.file_changes) == 105
    assert not result.commits[0].files_truncated


def test_files_not_matching_stats_mark_truncated():
    fake = FakeGitHub()
    fake.rest["/search/commits"] = search(commit_item("aaa"))
    fake.graphql["CommitAssociations"] = associations()
    fake.rest["/repos/octo/app/commits/aaa"] = lambda _r: commit_detail(
        "aaa", [("x.py", 1, 0)], stats={"additions": 9000, "deletions": 0}
    )
    assert run(fake).commits[0].files_truncated


def test_vanished_repo_is_skipped_and_recorded():
    fake = FakeGitHub()
    fake.rest["/search/commits"] = search(
        commit_item("aaa", repo_name="octo/gone"), commit_item("bbb", repo_name="octo/deleted")
    )
    fake.graphql["CommitAssociations"] = associations(missing_repos={"octo/deleted"})
    fake.rest["/repos/octo/gone/commits/aaa"] = lambda _r: httpx.Response(404, json={})
    result = run(fake)
    assert result.commits == []
    assert sorted(result.skipped_repos) == ["octo/deleted", "octo/gone"]


def test_author_email_searches_are_unioned_by_sha():
    fake = FakeGitHub()
    queries = []

    def search_handler(request):
        queries.append(request.url.params["q"])
        if "author-email:" in request.url.params["q"]:
            return {"total_count": 2, "items": [commit_item("aaa"), commit_item("ccc")]}
        return {"total_count": 1, "items": [commit_item("aaa")]}

    fake.rest["/search/commits"] = search_handler
    fake.graphql["CommitAssociations"] = associations()
    for sha in ("aaa", "ccc"):
        fake.rest[f"/repos/octo/app/commits/{sha}"] = lambda _r, s=sha: commit_detail(
            s, [("x.py", 1, 0)]
        )
    result = run(fake, author_emails=["me@old-job.example"])
    assert sorted(c.sha for c in result.commits) == ["aaa", "ccc"]
    assert any(q.startswith("author-email:me@old-job.example author-date:") for q in queries)


def test_public_only_adds_is_public():
    fake = FakeGitHub()
    queries = []
    fake.rest["/search/commits"] = lambda r: (
        queries.append(r.url.params["q"]) or {"total_count": 0, "items": []}
    )
    run(fake, public_only=True)
    assert all("is:public" in q for q in queries)
