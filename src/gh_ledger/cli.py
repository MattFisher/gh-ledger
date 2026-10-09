"""Command-line interface: fetch, summary and report."""

from __future__ import annotations

import math
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from gh_ledger.auth import AuthError, get_token
from gh_ledger.cache import ResponseCache
from gh_ledger.client import GitHubClient, GitHubError, Waiter
from gh_ledger.fetch import FetchError, FetchOptions, Stage, run_fetch
from gh_ledger.fetch.common import Tick

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Measure one GitHub user's activity over time.",
)
console = Console()
# soft_wrap: long paths must not split messages mid-phrase.
err_console = Console(stderr=True, soft_wrap=True)


@app.callback()
def main() -> None:
    """Measure one GitHub user's activity over time."""


class Visibility(StrEnum):
    PUBLIC = "public"
    ALL = "all"


def fail(message: object) -> NoReturn:
    # escape(): messages contain brackets ("[filters]", "gh-ledger[images]") that rich reads as markup.
    err_console.print(f"[red]Error:[/] {escape(str(message))}")
    raise typer.Exit(1)


def make_client(data: Path, *, refresh: bool, on_wait: Waiter) -> GitHubClient:
    return GitHubClient(
        get_token(), cache=ResponseCache(data / "cache"), refresh=refresh, on_wait=on_wait
    )


def _stage_runner(progress: Progress) -> Stage:
    @contextmanager
    def stage(name: str) -> Generator[Tick]:
        task = progress.add_task(name, total=None)

        def tick(count: int) -> None:
            progress.advance(task, count)

        yield tick
        progress.update(task, description=f"{name} [green]done[/]")
        progress.stop_task(task)

    return stage


def _waiter(progress: Progress) -> Waiter:
    def wait(seconds: float, reason: str) -> None:
        remaining = math.ceil(seconds)
        task = progress.add_task(f"{reason}: resuming in {remaining}s", total=None)
        while remaining > 0:
            time.sleep(1)
            remaining -= 1
            progress.update(task, description=f"{reason}: resuming in {remaining}s")
        progress.remove_task(task)

    return wait


@app.command()
def fetch(
    user: Annotated[str, typer.Option(help="GitHub login to measure.")],
    since: Annotated[datetime, typer.Option(formats=["%Y-%m-%d"], help="First day (UTC).")],
    data: Annotated[Path, typer.Option(help="Directory for tables, manifest and cache.")],
    until: Annotated[
        datetime | None, typer.Option(formats=["%Y-%m-%d"], help="Last day (UTC). Default: today.")
    ] = None,
    visibility: Annotated[
        Visibility, typer.Option(help="Public repos only, or everything the token can see.")
    ] = Visibility.PUBLIC,
    author_email: Annotated[
        list[str] | None,
        typer.Option(help="Commit email not linked to the account. Repeatable."),
    ] = None,
    refresh: Annotated[
        bool, typer.Option(help="Ignore the cache and re-fetch everything.")
    ] = False,
) -> None:
    """Fetch activity from GitHub into DATA."""
    now = datetime.now(UTC)
    start = since.date()
    end = until.date() if until else now.date()
    if start > end:
        fail(f"--since {start} is after --until {end}")
    options = FetchOptions(
        user=user,
        since=start,
        until=end,
        visibility=visibility.value,
        author_emails=tuple(author_email or ()),
    )
    columns = (
        SpinnerColumn(),
        TextColumn("{task.description}"),
        TextColumn("{task.completed:.0f} items"),
        TimeElapsedColumn(),
    )
    try:
        with (
            Progress(*columns, console=err_console) as progress,
            make_client(data, refresh=refresh, on_wait=_waiter(progress)) as client,
        ):
            manifest = run_fetch(client, options, data, now=now, stage=_stage_runner(progress))
    except (AuthError, FetchError, GitHubError) as exc:
        fail(exc)
    err_console.print(f"Fetched {manifest.user} {manifest.since} to {manifest.until} into {data}")
    if manifest.dropped_pr_commits:
        err_console.print(f"Dropped {manifest.dropped_pr_commits} commits already counted via PRs.")
    if manifest.skipped_repos:
        err_console.print(
            f"[yellow]Skipped repos (not found):[/] {escape(', '.join(manifest.skipped_repos))}"
        )
    if manifest.restricted_contributions:
        err_console.print(
            f"[yellow]{manifest.restricted_contributions} private contributions are hidden from this token.[/]"
        )
