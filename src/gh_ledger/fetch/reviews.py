"""Submitted reviews and their inline comments, from contributionsCollection."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from gh_ledger.client import GitHubClient
from gh_ledger.fetch.common import GH_TIME, Tick, drain_connection, login_of, repo_row, to_utc_iso
from gh_ledger.fetch.search import year_spans
from gh_ledger.model import CommentRow, FetchResult, ReviewRow

QUERY = """
query ReviewContributions($login: String!, $from: DateTime!, $to: DateTime!, $after: String) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      pullRequestReviewContributions(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          pullRequestReview {
            id state body submittedAt
            comments(first: 100) {
              pageInfo { hasNextPage endCursor }
              nodes { id body createdAt url }
            }
          }
          pullRequest { number url author { login } }
          repository { nameWithOwner isPrivate isFork }
        }
      }
    }
  }
}
"""

COMMENTS_QUERY = """
query ReviewComments($id: ID!, $after: String) {
  node(id: $id) { ... on PullRequestReview {
    comments(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { id body createdAt url }
    }
  } }
}
"""


def fetch_reviews(
    client: GitHubClient, user: str, since: date, until: date, *, now: datetime, tick: Tick
) -> FetchResult:
    result = FetchResult()
    for span in year_spans(since, until):
        cacheable = span.is_settled(now)
        cursor: str | None = None
        while True:
            variables = {
                "login": user,
                "from": span.start.strftime(GH_TIME),
                "to": span.end.strftime(GH_TIME),
                "after": cursor,
            }
            collection = client.graphql(QUERY, variables, cacheable=cacheable)["user"][
                "contributionsCollection"
            ]
            if cursor is None:
                result.restricted_contributions += collection["restrictedContributionsCount"]
            conn = collection["pullRequestReviewContributions"]
            for node in conn["nodes"]:
                _add_review(client, node, result, cacheable=cacheable)
                tick(1)
            if not conn["pageInfo"]["hasNextPage"]:
                break
            cursor = conn["pageInfo"]["endCursor"]
    return result


def _add_review(
    client: GitHubClient, node: dict[str, Any], result: FetchResult, *, cacheable: bool
) -> None:
    review = node["pullRequestReview"]
    pr = node["pullRequest"]
    repo = repo_row(node["repository"])
    author = login_of(pr["author"])
    result.repos.append(repo)
    result.reviews.append(
        ReviewRow(
            id=review["id"],
            repo=repo.repo,
            pr_number=pr["number"],
            pr_url=pr["url"],
            pr_author=author,
            state=str(review["state"]).lower(),
            submitted_at=to_utc_iso(review["submittedAt"]),
            text=review["body"] or "",
        )
    )
    comments = [
        *review["comments"]["nodes"],
        *drain_connection(
            client,
            COMMENTS_QUERY,
            review["id"],
            "comments",
            review["comments"]["pageInfo"],
            cacheable=cacheable,
        ),
    ]
    result.comments.extend(
        CommentRow(
            id=c["id"],
            repo=repo.repo,
            kind="review_inline",
            parent_number=pr["number"],
            parent_url=pr["url"],
            parent_author=author,
            created_at=to_utc_iso(c["createdAt"]),
            text=c["body"] or "",
        )
        for c in comments
    )
