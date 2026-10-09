from datetime import UTC, date, datetime

from github_fakes import FakeGitHub, issue_node, noop, search_result

from gh_ledger.fetch.issues import fetch_issues

NOW = datetime(2024, 6, 1, tzinfo=UTC)


def run(fake, public_only=False):
    return fetch_issues(
        fake.client(),
        "octocat",
        date(2024, 1, 1),
        date(2024, 1, 31),
        public_only=public_only,
        now=NOW,
        tick=noop,
    )


def test_issue_rows():
    fake = FakeGitHub()
    fake.graphql["IssueSearch"] = lambda _b: search_result(
        [issue_node(state="CLOSED", closed="2024-01-09T00:00:00+00:00")]
    )
    result = run(fake)
    [issue] = result.issues
    assert issue.state == "closed"
    assert issue.closed_at == "2024-01-09T00:00:00Z"
    assert issue.text == "It broke."
    assert result.repos[0].repo == "octo/app"


def test_search_terms():
    fake = FakeGitHub()
    fake.graphql["IssueSearch"] = lambda _b: search_result([])
    run(fake, public_only=True)
    [variables] = fake.variables("IssueSearch")
    assert variables["q"].startswith("is:issue author:octocat is:public created:")
