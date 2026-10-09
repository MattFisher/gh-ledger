"""Direct commits to default branches that are not part of any PR."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from gh_ledger.client import GitHubClient, NotFoundError
from gh_ledger.fetch.common import Tick, to_utc_iso
from gh_ledger.fetch.search import (
    SEARCH_CAP,
    SETTLE_AFTER,
    Page,
    PageFetcher,
    Window,
    month_windows,
    search_windowed,
)
from gh_ledger.filters import parse_co_authors
from gh_ledger.model import CommitRow, FetchResult, FileChangeRow, RepoRow

SEARCH_PATH = "/search/commits"
PER_PAGE = 100
ASSOCIATION_BATCH = 50
MAX_FILE_PAGES = 30  # GitHub lists at most 3,000 files for one commit
ASSOCIATION = (
    'c{i}: repository(owner: {owner}, name: {name}) {{ object(oid: "{sha}") '
    "{{ ... on Commit {{ associatedPullRequests(first: 1) {{ totalCount }} }} }} }}"
)


def fetch_commits(
    client: GitHubClient,
    user: str,
    since: date,
    until: date,
    *,
    author_emails: Sequence[str],
    public_only: bool,
    now: datetime,
    tick: Tick,
) -> FetchResult:
    visibility = " is:public" if public_only else ""
    authors = [f"author:{user}", *(f"author-email:{email}" for email in author_emails)]
    windows = month_windows(since, until)
    candidates: dict[str, dict[str, Any]] = {}
    for author in authors:
        for item in search_windowed(windows, _search_pages(client, author + visibility, now)):
            candidates.setdefault(item["sha"], item)
            tick(1)
    items = sorted(candidates.values(), key=_authored)
    attached, missing = _associations(client, items, now)
    result = FetchResult(dropped_pr_commits=len(attached))
    skipped = set(missing)
    for item in items:
        full_name = item["repository"]["full_name"]
        if item["sha"] in attached or full_name in skipped:
            continue
        try:
            detail, files = _detail(client, full_name, item["sha"])
        except NotFoundError:
            skipped.add(full_name)
            continue
        _add_commit(item, detail, files, result)
    result.skipped_repos = sorted(skipped)
    return result


def _authored(item: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(item["commit"]["author"]["date"])


def _search_pages(client: GitHubClient, terms: str, now: datetime) -> PageFetcher[dict[str, Any]]:
    def fetch_page(window: Window, cursor: str | None) -> Page[dict[str, Any]]:
        page = int(cursor or "1")
        data = client.rest(
            SEARCH_PATH,
            {
                "q": f"{terms} author-date:{window.qualifier()}",
                "sort": "author-date",
                "order": "asc",
                "per_page": PER_PAGE,
                "page": page,
            },
            search=True,
            cacheable=window.is_settled(now),
        )
        total = int(data["total_count"])
        more = page * PER_PAGE < min(total, SEARCH_CAP)
        return Page(total=total, items=list(data["items"]), cursor=str(page + 1) if more else None)

    return fetch_page


def _associations(
    client: GitHubClient, items: list[dict[str, Any]], now: datetime
) -> tuple[set[str], set[str]]:
    """SHAs attached to a PR, and repos the association query could not see."""
    attached: set[str] = set()
    missing: set[str] = set()
    for start in range(0, len(items), ASSOCIATION_BATCH):
        batch = items[start : start + ASSOCIATION_BATCH]
        parts: list[str] = []
        for i, item in enumerate(batch):
            owner, name = str(item["repository"]["full_name"]).split("/", 1)
            parts.append(
                ASSOCIATION.format(
                    i=i, owner=json.dumps(owner), name=json.dumps(name), sha=item["sha"]
                )
            )
        settled = all(_authored(item) < now - SETTLE_AFTER for item in batch)
        query = "query CommitAssociations {\n" + "\n".join(parts) + "\n}"
        data = client.graphql(query, cacheable=settled)
        for i, item in enumerate(batch):
            repository = data.get(f"c{i}")
            if repository is None:
                missing.add(item["repository"]["full_name"])
                continue
            commit = repository.get("object")
            if commit and commit["associatedPullRequests"]["totalCount"] > 0:
                attached.add(item["sha"])
    return attached, missing


def _detail(
    client: GitHubClient, full_name: str, sha: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    first: dict[str, Any] | None = None
    files: list[dict[str, Any]] = []
    for page in range(1, MAX_FILE_PAGES + 1):
        data = client.rest(
            f"/repos/{full_name}/commits/{sha}", {"per_page": PER_PAGE, "page": page}
        )
        first = first or data
        page_files = list(data.get("files") or [])
        files.extend(page_files)
        if len(page_files) < PER_PAGE:
            break
    assert first is not None
    return first, files


def _add_commit(
    item: dict[str, Any], detail: dict[str, Any], files: list[dict[str, Any]], result: FetchResult
) -> None:
    repository = item["repository"]
    repo = RepoRow(
        repo=repository["full_name"],
        is_private=bool(repository["private"]),
        is_fork=bool(repository["fork"]),
    )
    authored = to_utc_iso(item["commit"]["author"]["date"])
    message = str(item["commit"]["message"])
    stats = detail["stats"]
    listed = (sum(f["additions"] for f in files), sum(f["deletions"] for f in files))
    result.repos.append(repo)
    result.commits.append(
        CommitRow(
            sha=item["sha"],
            repo=repo.repo,
            authored_at=authored,
            additions=stats["additions"],
            deletions=stats["deletions"],
            files_truncated=listed != (stats["additions"], stats["deletions"]),
            text=message,
            co_authors=parse_co_authors([message]),
        )
    )
    result.file_changes.extend(
        FileChangeRow(
            source="commit",
            source_id=item["sha"],
            repo=repo.repo,
            path=f["filename"],
            additions=f["additions"],
            deletions=f["deletions"],
            change_type=str(f["status"]),
            date=authored,
        )
        for f in files
    )
