from datetime import UTC, date, datetime

from github_fakes import FakeGitHub, connection, contributions, noop, review_contribution

from gh_ledger.fetch.reviews import fetch_reviews

NOW = datetime(2024, 6, 1, tzinfo=UTC)


def run(fake, since=date(2024, 1, 1), until=date(2024, 1, 31)):
    return fetch_reviews(fake.client(), "octocat", since, until, now=NOW, tick=noop)


def test_review_and_inline_comment_rows():
    fake = FakeGitHub()
    node = review_contribution(
        state="CHANGES_REQUESTED",
        body="Needs tests",
        comments=[("PRRC_1", "Nit: rename", "2024-01-15T10:05:00Z")],
    )
    fake.graphql["ReviewContributions"] = lambda _b: contributions([node], restricted=2)
    result = run(fake)
    [review] = result.reviews
    assert review.state == "changes_requested"
    assert review.pr_author == "alice"
    assert review.pr_number == 7
    assert review.text == "Needs tests"
    [comment] = result.comments
    assert comment.kind == "review_inline"
    assert comment.parent_author == "alice"
    assert comment.parent_number == 7
    assert comment.text == "Nit: rename"
    assert result.restricted_contributions == 2


def test_one_query_chain_per_year_span():
    fake = FakeGitHub()
    fake.graphql["ReviewContributions"] = lambda _b: contributions([], restricted=1)
    result = run(fake, since=date(2022, 1, 1), until=date(2023, 6, 30))
    spans = fake.variables("ReviewContributions")
    assert [v["from"] for v in spans] == ["2022-01-01T00:00:00Z", "2023-01-01T00:00:00Z"]
    assert spans[-1]["to"] == "2023-06-30T23:59:59Z"
    assert result.restricted_contributions == 2


def test_contribution_pages_are_followed():
    fake = FakeGitHub()
    pages = {
        None: contributions([review_contribution("PRR_1")], end_cursor="P2"),
        "P2": contributions([review_contribution("PRR_2")]),
    }
    fake.graphql["ReviewContributions"] = lambda b: pages[b["variables"]["after"]]
    assert [r.id for r in run(fake).reviews] == ["PRR_1", "PRR_2"]


def test_inline_comments_beyond_the_first_page_are_fetched():
    fake = FakeGitHub()
    node = review_contribution(
        comments=[("PRRC_1", "a", "2024-01-15T10:05:00Z")], comments_cursor="RC1"
    )
    fake.graphql["ReviewContributions"] = lambda _b: contributions([node])
    more = [{"id": "PRRC_2", "body": "b", "createdAt": "2024-01-15T10:06:00Z", "url": "u"}]
    fake.graphql["ReviewComments"] = lambda _b: {"node": {"comments": connection(more)}}
    assert [c.id for c in run(fake).comments] == ["PRRC_1", "PRRC_2"]


def test_ghost_pr_author_is_empty():
    fake = FakeGitHub()
    node = review_contribution(pr_author=None, comments=[("PRRC_1", "x", "2024-01-15T10:05:00Z")])
    fake.graphql["ReviewContributions"] = lambda _b: contributions([node])
    result = run(fake)
    assert result.reviews[0].pr_author == ""
    assert result.comments[0].parent_author == ""
