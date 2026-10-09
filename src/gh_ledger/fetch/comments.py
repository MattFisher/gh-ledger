"""Conversation comments on issues and PRs, from user.issueComments."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from gh_ledger.client import GitHubClient
from gh_ledger.fetch.common import Tick, login_of, repo_row, to_utc_iso
from gh_ledger.model import CommentRow, FetchResult

QUERY = """
query IssueComments($login: String!, $after: String) {
  user(login: $login) {
    issueComments(first: 100, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id body createdAt updatedAt
        issue { number url author { login } }
        pullRequest { number url author { login } }
        repository { nameWithOwner isPrivate isFork }
      }
    }
  }
}
"""


def fetch_comments(
    client: GitHubClient, user: str, since: date, until: date, *, tick: Tick
) -> FetchResult:
    """Read newest-updated first until a page ends before `since`.

    The stream shifts as new comments arrive, so pages are never cached.
    """
    start = datetime.combine(since, time.min, tzinfo=UTC)
    end = datetime.combine(until, time.max, tzinfo=UTC)
    result = FetchResult()
    cursor: str | None = None
    while True:
        variables = {"login": user, "after": cursor}
        conn = client.graphql(QUERY, variables, cacheable=False)["user"]["issueComments"]
        nodes = conn["nodes"]
        for node in nodes:
            tick(1)
            if not start <= datetime.fromisoformat(node["createdAt"]) <= end:
                continue
            parent = node["pullRequest"] or node["issue"]
            repo = repo_row(node["repository"])
            result.repos.append(repo)
            result.comments.append(
                CommentRow(
                    id=node["id"],
                    repo=repo.repo,
                    kind="pr_conversation" if node["pullRequest"] else "issue",
                    parent_number=parent["number"],
                    parent_url=parent["url"],
                    parent_author=login_of(parent["author"]),
                    created_at=to_utc_iso(node["createdAt"]),
                    text=node["body"] or "",
                )
            )
        past_since = bool(nodes) and datetime.fromisoformat(nodes[-1]["updatedAt"]) < start
        if past_since or not conn["pageInfo"]["hasNextPage"]:
            return result
        cursor = conn["pageInfo"]["endCursor"]
