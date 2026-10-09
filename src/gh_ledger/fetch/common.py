"""Helpers shared by the fetch modules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from gh_ledger.client import GitHubClient
from gh_ledger.model import RepoRow

GH_TIME = "%Y-%m-%dT%H:%M:%SZ"
EMPTY_CONNECTION: dict[str, Any] = {
    "pageInfo": {"hasNextPage": False, "endCursor": None},
    "nodes": [],
}

Tick = Callable[[int], None]


def to_utc_iso(value: str) -> str:
    """Normalise a GitHub timestamp with any offset to `YYYY-MM-DDTHH:MM:SSZ`."""
    return datetime.fromisoformat(value).astimezone(UTC).strftime(GH_TIME)


def optional_utc_iso(value: str | None) -> str | None:
    return to_utc_iso(value) if value else None


def repo_row(repository: dict[str, Any]) -> RepoRow:
    """Build a RepoRow from GraphQL `repository { nameWithOwner isPrivate isFork }`."""
    return RepoRow(
        repo=repository["nameWithOwner"],
        is_private=bool(repository["isPrivate"]),
        is_fork=bool(repository["isFork"]),
    )


def login_of(actor: dict[str, Any] | None) -> str:
    """Login of a GraphQL actor; empty for deleted (ghost) accounts."""
    return str(actor["login"]) if actor else ""


def connection_or_empty(value: dict[str, Any] | None) -> dict[str, Any]:
    """GitHub returns null instead of a connection for some very large PRs."""
    return value if value is not None else EMPTY_CONNECTION


def drain_connection(
    client: GitHubClient,
    query: str,
    node_id: str,
    field: str,
    page_info: dict[str, Any],
    *,
    cacheable: bool,
) -> list[dict[str, Any]]:
    """Fetch the remaining pages of `node(id).<field>` after the first page."""
    nodes: list[dict[str, Any]] = []
    while page_info["hasNextPage"]:
        variables = {"id": node_id, "after": page_info["endCursor"]}
        conn = client.graphql(query, variables, cacheable=cacheable)["node"][field]
        nodes.extend(conn["nodes"])
        page_info = conn["pageInfo"]
    return nodes
