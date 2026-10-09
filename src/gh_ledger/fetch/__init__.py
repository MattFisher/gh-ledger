"""Fetch a user's activity from GitHub into the normalised tables."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from gh_ledger import __version__
from gh_ledger.client import GitHubClient
from gh_ledger.fetch.comments import fetch_comments
from gh_ledger.fetch.commits import fetch_commits
from gh_ledger.fetch.common import GH_TIME, Tick
from gh_ledger.fetch.issues import fetch_issues
from gh_ledger.fetch.prs import fetch_prs
from gh_ledger.fetch.reviews import fetch_reviews
from gh_ledger.model import FetchResult, Manifest
from gh_ledger.store import read_manifest, write_manifest, write_tables

Stage = Callable[[str], AbstractContextManager[Tick]]

USER_QUERY = "query UserCheck($login: String!) { user(login: $login) { login } }"


class FetchError(Exception):
    """The fetch cannot proceed with these options."""


@dataclass(frozen=True)
class FetchOptions:
    user: str
    since: date
    until: date
    visibility: str  # public | all
    author_emails: tuple[str, ...] = ()


def run_fetch(
    client: GitHubClient, options: FetchOptions, data_dir: Path, *, now: datetime, stage: Stage
) -> Manifest:
    existing = read_manifest(data_dir)
    check_compatible(existing, options, data_dir)
    user = _canonical_login(client, options.user)
    public_only = options.visibility == "public"
    since, until = options.since, options.until
    result = FetchResult()
    with stage("Pull requests") as tick:
        result.extend(
            fetch_prs(client, user, since, until, public_only=public_only, now=now, tick=tick)
        )
    with stage("Issues") as tick:
        result.extend(
            fetch_issues(client, user, since, until, public_only=public_only, now=now, tick=tick)
        )
    with stage("Reviews") as tick:
        result.extend(fetch_reviews(client, user, since, until, now=now, tick=tick))
    with stage("Comments") as tick:
        result.extend(fetch_comments(client, user, since, until, tick=tick))
    with stage("Direct commits") as tick:
        result.extend(
            fetch_commits(
                client,
                user,
                since,
                until,
                author_emails=options.author_emails,
                public_only=public_only,
                now=now,
                tick=tick,
            )
        )
    if public_only:
        result = drop_private(result)
    result.repos = list({row.repo: row for row in result.repos}.values())
    write_tables(data_dir, result)
    manifest = _merge_manifest(existing, options, user, result, now)
    write_manifest(data_dir, manifest)
    return manifest


def check_compatible(existing: Manifest | None, options: FetchOptions, data_dir: Path) -> None:
    """Refuse to mix users or visibilities in one data directory."""
    if existing is None:
        return
    if existing.user.lower() != options.user.lower():
        raise FetchError(
            f"{data_dir} holds data for {existing.user}. Use a different --data directory for {options.user}."
        )
    if existing.visibility != options.visibility:
        raise FetchError(
            f"{data_dir} was fetched with --visibility {existing.visibility}. "
            "Re-run with that, or use a different --data directory."
        )


def drop_private(result: FetchResult) -> FetchResult:
    """Remove every row belonging to a private repo."""
    private = {row.repo for row in result.repos if row.is_private}
    return dataclasses.replace(
        result,
        repos=[row for row in result.repos if not row.is_private],
        prs=[row for row in result.prs if row.repo not in private],
        issues=[row for row in result.issues if row.repo not in private],
        reviews=[row for row in result.reviews if row.repo not in private],
        comments=[row for row in result.comments if row.repo not in private],
        commits=[row for row in result.commits if row.repo not in private],
        file_changes=[row for row in result.file_changes if row.repo not in private],
    )


def _canonical_login(client: GitHubClient, login: str) -> str:
    user = client.graphql(USER_QUERY, {"login": login}, cacheable=False)["user"]
    if user is None:
        raise FetchError(f"No GitHub user {login!r}")
    return str(user["login"])


def _merge_manifest(
    existing: Manifest | None, options: FetchOptions, user: str, result: FetchResult, now: datetime
) -> Manifest:
    since, until = options.since.isoformat(), options.until.isoformat()
    emails = set(options.author_emails)
    skipped = set(result.skipped_repos)
    if existing is not None:
        since, until = min(since, existing.since), max(until, existing.until)
        emails |= set(existing.author_emails)
        skipped |= set(existing.skipped_repos)
    return Manifest(
        user=user,
        since=since,
        until=until,
        visibility=options.visibility,
        fetched_at=now.strftime(GH_TIME),
        tool_version=__version__,
        author_emails=sorted(emails),
        dropped_pr_commits=result.dropped_pr_commits,
        skipped_repos=sorted(skipped),
        restricted_contributions=result.restricted_contributions,
    )
