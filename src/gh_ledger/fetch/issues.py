"""Issues the user opened."""

from __future__ import annotations

from datetime import date, datetime

from gh_ledger.client import GitHubClient
from gh_ledger.fetch.common import Tick, optional_utc_iso, repo_row, to_utc_iso
from gh_ledger.fetch.search import graphql_search, month_windows, search_windowed
from gh_ledger.model import FetchResult, IssueRow

SEARCH_QUERY = """
query IssueSearch($q: String!, $after: String) {
  search(type: ISSUE, query: $q, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Issue {
        id number url title state body createdAt closedAt
        repository { nameWithOwner isPrivate isFork }
      }
    }
  }
}
"""


def fetch_issues(
    client: GitHubClient,
    user: str,
    since: date,
    until: date,
    *,
    public_only: bool,
    now: datetime,
    tick: Tick,
) -> FetchResult:
    terms = f"is:issue author:{user}" + (" is:public" if public_only else "")
    pages = graphql_search(client, SEARCH_QUERY, terms, "created", now)
    result = FetchResult()
    for hit in search_windowed(month_windows(since, until), pages):
        node = hit.node
        repo = repo_row(node["repository"])
        result.repos.append(repo)
        result.issues.append(
            IssueRow(
                id=node["id"],
                repo=repo.repo,
                number=node["number"],
                url=node["url"],
                title=node["title"],
                state=str(node["state"]).lower(),
                created_at=to_utc_iso(node["createdAt"]),
                closed_at=optional_utc_iso(node["closedAt"]),
                text=node["body"] or "",
            )
        )
        tick(1)
    return result
