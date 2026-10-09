"""Authored pull requests, with their file lists and commit messages."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from gh_ledger.client import GitHubClient
from gh_ledger.fetch.common import (
    Tick,
    connection_or_empty,
    drain_connection,
    optional_utc_iso,
    repo_row,
    to_utc_iso,
)
from gh_ledger.fetch.search import SearchHit, graphql_search, month_windows, search_windowed
from gh_ledger.filters import parse_co_authors
from gh_ledger.model import FetchResult, FileChangeRow, PrRow

PR_FIELDS = """
fragment PrFields on PullRequest {
  id number url title state body createdAt mergedAt closedAt
  additions deletions changedFiles
  repository { nameWithOwner isPrivate isFork }
  files(first: 100) {
    pageInfo { hasNextPage endCursor }
    nodes { path additions deletions changeType }
  }
  commits(first: 100) {
    pageInfo { hasNextPage endCursor }
    nodes { commit { message } }
  }
}
"""

SEARCH_QUERY = (
    """
query PrSearch($q: String!, $after: String) {
  search(type: ISSUE, query: $q, first: 50, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ...PrFields }
  }
}
"""
    + PR_FIELDS
)

NODE_QUERY = "query PrNode($id: ID!) { node(id: $id) { ...PrFields } }\n" + PR_FIELDS

FILES_QUERY = """
query PrFiles($id: ID!, $after: String) {
  node(id: $id) { ... on PullRequest {
    files(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { path additions deletions changeType }
    }
  } }
}
"""

COMMITS_QUERY = """
query PrCommits($id: ID!, $after: String) {
  node(id: $id) { ... on PullRequest {
    commits(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { commit { message } }
    }
  } }
}
"""


def fetch_prs(
    client: GitHubClient,
    user: str,
    since: date,
    until: date,
    *,
    public_only: bool,
    now: datetime,
    tick: Tick,
) -> FetchResult:
    """PRs created or merged in [since, until]: one search on each date, merged by ID."""
    terms = f"is:pr author:{user}" + (" is:public" if public_only else "")
    windows = month_windows(since, until)
    found: dict[str, SearchHit] = {}
    for field in ("created", "merged"):
        pages = graphql_search(client, SEARCH_QUERY, terms, field, now)
        for hit in search_windowed(windows, pages):
            previous = found.get(hit.node["id"])
            if previous is None or not hit.settled:  # a fresh copy beats a cached one
                found[hit.node["id"]] = hit
            tick(1)
    result = FetchResult()
    for hit in found.values():
        node = hit.node
        if hit.settled and node["state"] == "OPEN":
            # Cached search pages freeze an open PR; its details are re-read every run.
            node = client.graphql(NODE_QUERY, {"id": node["id"]}, cacheable=False)["node"]
        _add_pr(client, node, result)
    return result


def _add_pr(client: GitHubClient, node: dict[str, Any], result: FetchResult) -> None:
    cacheable = node["state"] != "OPEN"
    files_conn = connection_or_empty(node["files"])
    commits_conn = connection_or_empty(node["commits"])
    files = [
        *files_conn["nodes"],
        *drain_connection(
            client, FILES_QUERY, node["id"], "files", files_conn["pageInfo"], cacheable=cacheable
        ),
    ]
    commits = [
        *commits_conn["nodes"],
        *drain_connection(
            client,
            COMMITS_QUERY,
            node["id"],
            "commits",
            commits_conn["pageInfo"],
            cacheable=cacheable,
        ),
    ]
    messages = [str(c["commit"]["message"]) for c in commits]
    created = to_utc_iso(node["createdAt"])
    merged = optional_utc_iso(node["mergedAt"])
    repo = repo_row(node["repository"])
    result.repos.append(repo)
    result.prs.append(
        PrRow(
            id=node["id"],
            repo=repo.repo,
            number=node["number"],
            url=node["url"],
            title=node["title"],
            state=str(node["state"]).lower(),
            created_at=created,
            merged_at=merged,
            closed_at=optional_utc_iso(node["closedAt"]),
            additions=node["additions"],
            deletions=node["deletions"],
            changed_files=node["changedFiles"],
            files_truncated=len(files) < node["changedFiles"],
            text="\n\n".join([node["body"] or "", *messages]).strip(),
            co_authors=parse_co_authors(messages),
        )
    )
    file_date = merged or created
    result.file_changes.extend(
        FileChangeRow(
            source="pr",
            source_id=node["id"],
            repo=repo.repo,
            path=f["path"],
            additions=f["additions"],
            deletions=f["deletions"],
            change_type=str(f["changeType"]).lower(),
            date=file_date,
        )
        for f in files
    )
