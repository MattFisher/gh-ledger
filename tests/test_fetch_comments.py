from datetime import date

import pytest
from github_fakes import FakeGitHub, issue_comment, issue_comments, noop

from gh_ledger.fetch.comments import fetch_comments


def run(fake):
    return fetch_comments(fake.client(), "octocat", date(2024, 1, 1), date(2024, 1, 31), tick=noop)


def test_stops_paging_once_past_since_and_filters_by_created():
    fake = FakeGitHub()
    first = issue_comments(
        [
            issue_comment("IC_FEB", created="2024-02-03T00:00:00Z"),
            issue_comment("IC_JAN", created="2024-01-20T00:00:00Z"),
            issue_comment(
                "IC_OLD_EDITED", created="2023-11-01T00:00:00Z", updated="2024-01-02T00:00:00Z"
            ),
            issue_comment("IC_DEC", created="2023-12-20T00:00:00Z"),
        ],
        end_cursor="P2",
    )

    def handler(body):
        if body["variables"]["after"] is not None:
            pytest.fail("fetched a page after passing --since")
        return first

    fake.graphql["IssueComments"] = handler
    assert [c.id for c in run(fake).comments] == ["IC_JAN"]


def test_follows_pages_while_still_in_range():
    fake = FakeGitHub()
    pages = {
        None: issue_comments(
            [issue_comment("IC_1", created="2024-01-25T00:00:00Z")], end_cursor="P2"
        ),
        "P2": issue_comments([issue_comment("IC_2", created="2024-01-05T00:00:00Z")]),
    }
    fake.graphql["IssueComments"] = lambda b: pages[b["variables"]["after"]]
    assert [c.id for c in run(fake).comments] == ["IC_1", "IC_2"]


def test_pr_conversation_comment_takes_parent_from_pull_request():
    fake = FakeGitHub()
    fake.graphql["IssueComments"] = lambda _b: issue_comments([issue_comment(on_pr=True, number=9)])
    [comment] = run(fake).comments
    assert comment.kind == "pr_conversation"
    assert comment.parent_url.endswith("/pull/9")
    assert comment.parent_author == "alice"


def test_issue_comment_kind():
    fake = FakeGitHub()
    fake.graphql["IssueComments"] = lambda _b: issue_comments([issue_comment()])
    assert run(fake).comments[0].kind == "issue"


def test_ghost_parent_author_is_empty():
    fake = FakeGitHub()
    fake.graphql["IssueComments"] = lambda _b: issue_comments([issue_comment(parent_author=None)])
    assert run(fake).comments[0].parent_author == ""
