from datetime import UTC, date, datetime

from github_fakes import FakeGitHub, connection, noop, pr_node, repo, search_result

from gh_ledger.fetch.prs import fetch_prs
from gh_ledger.filters import parse_co_authors
from gh_ledger.model import RepoRow

NOW = datetime(2024, 6, 1, tzinfo=UTC)
JAN = (date(2024, 1, 1), date(2024, 1, 31))


def created_only(*nodes):
    return lambda body: search_result(list(nodes) if "created:" in body["variables"]["q"] else [])


def run(fake, since=JAN[0], until=JAN[1], public_only=False):
    return fetch_prs(
        fake.client(), "octocat", since, until, public_only=public_only, now=NOW, tick=noop
    )


def test_merged_pr_becomes_pr_and_file_rows():
    fake = FakeGitHub()
    message = "feat: add app\n\nCo-authored-by: Claude <noreply@anthropic.com>"
    node = pr_node(files=[("src/app.py", 10, 2), ("uv.lock", 300, 100)], messages=[message])
    fake.graphql["PrSearch"] = created_only(node)
    result = run(fake)
    [pr] = result.prs
    assert pr.state == "merged"
    assert pr.merged_at == "2024-01-11T10:00:00Z"
    assert pr.additions == 310
    assert pr.co_authors == ("Claude <noreply@anthropic.com>",)
    assert "Adds the app." in pr.text
    assert "feat: add app" in pr.text
    assert not pr.files_truncated
    assert [(f.path, f.additions, f.change_type, f.date) for f in result.file_changes] == [
        ("src/app.py", 10, "modified", "2024-01-11T10:00:00Z"),
        ("uv.lock", 300, "modified", "2024-01-11T10:00:00Z"),
    ]
    assert result.repos == [RepoRow("octo/app", is_private=False, is_fork=False)]


def test_pr_found_by_both_searches_is_kept_once():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = lambda _body: search_result([pr_node()])
    assert len(run(fake).prs) == 1


def test_files_beyond_the_first_page_are_fetched():
    fake = FakeGitHub()
    node = pr_node(files=[("a.py", 1, 0), ("b.py", 1, 0)], changed_files=3, files_cursor="F1")
    fake.graphql["PrSearch"] = created_only(node)
    more = [{"path": "c.py", "additions": 4, "deletions": 0, "changeType": "ADDED"}]
    fake.graphql["PrFiles"] = lambda _body: {"node": {"files": connection(more)}}
    result = run(fake)
    assert [f.path for f in result.file_changes] == ["a.py", "b.py", "c.py"]
    assert not result.prs[0].files_truncated


def test_commit_messages_beyond_the_first_page_are_fetched():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = created_only(pr_node(commits_cursor="C1"))
    later = [{"commit": {"message": "chore: x\n\nCo-authored-by: Copilot <c@github.com>"}}]
    fake.graphql["PrCommits"] = lambda _body: {"node": {"commits": connection(later)}}
    assert run(fake).prs[0].co_authors == ("Copilot <c@github.com>",)


def test_file_list_shorter_than_changed_files_is_truncated():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = created_only(pr_node(changed_files=3001))
    assert run(fake).prs[0].files_truncated


def test_open_pr_from_a_settled_window_is_refreshed():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = created_only(pr_node(state="OPEN"))
    fake.graphql["PrNode"] = lambda _body: {"node": pr_node(state="MERGED")}
    [pr] = run(fake).prs
    assert pr.state == "merged"
    assert "PrNode" in fake.calls


def test_open_pr_that_vanished_is_skipped_and_its_repo_recorded():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = created_only(pr_node(state="OPEN", repository=repo("octo/gone")))
    fake.graphql["PrNode"] = lambda _body: {"node": None}
    result = run(fake)
    assert result.prs == []
    assert result.skipped_repos == ["octo/gone"]


def test_open_pr_from_a_recent_window_is_not_refreshed():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = created_only(pr_node(state="OPEN", created="2024-05-20T10:00:00Z"))
    [pr] = run(fake, since=date(2024, 5, 15), until=date(2024, 5, 31)).prs
    assert pr.state == "open"
    assert "PrNode" not in fake.calls


def test_unmerged_pr_files_are_dated_at_creation():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = created_only(pr_node(state="CLOSED"))
    result = run(fake)
    assert result.file_changes[0].date == "2024-01-10T10:00:00Z"


def test_public_only_adds_is_public():
    fake = FakeGitHub()
    fake.graphql["PrSearch"] = lambda _body: search_result([])
    run(fake, public_only=True)
    queries = [v["q"] for v in fake.variables("PrSearch")]
    assert queries
    assert all("is:public" in q and "author:octocat" in q for q in queries)
    assert {q.split()[-1].split(":")[0] for q in queries} == {"created", "merged"}


def test_parse_co_authors_dedupes_case_insensitively():
    messages = [
        "a\n\nCo-authored-by: Claude <noreply@anthropic.com>",
        "b\n\nco-authored-by: claude <noreply@anthropic.com>\nCo-Authored-By: Jo <jo@x>",
    ]
    assert parse_co_authors(messages) == ("Claude <noreply@anthropic.com>", "Jo <jo@x>")
