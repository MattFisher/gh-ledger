"""Command-line interface: fetch, summary and report."""

from __future__ import annotations

import math
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from gh_ledger.auth import AuthError, get_token
from gh_ledger.cache import ResponseCache
from gh_ledger.client import GitHubClient, GitHubError, Waiter
from gh_ledger.config import ConfigError, load_config
from gh_ledger.events import EventsError, load_events
from gh_ledger.fetch import FetchError, FetchOptions, Stage, run_fetch
from gh_ledger.fetch.common import Tick
from gh_ledger.metrics import METRIC_LABELS, SUMMARY_COLUMNS, compute_metrics, summary_rows
from gh_ledger.report import build_charts, headline
from gh_ledger.report.html import build_html
from gh_ledger.report.images import export_images
from gh_ledger.report.redact import redact_repos
from gh_ledger.store import (
    StoreError,
    load_table,
    load_tables,
    read_manifest,
    read_metrics,
    write_metrics,
)

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
    except (AuthError, FetchError, GitHubError, StoreError) as exc:
        fail(exc)
    err_console.print(f"Fetched {manifest.user} {manifest.since} to {manifest.until} into {data}")
    if manifest.dropped_pr_commits:
        err_console.print(
            f"Dropped {manifest.dropped_pr_commits} commits that belong to a PR "
            "(attached to one, or merge commits)."
        )
    if manifest.skipped_repos:
        err_console.print(
            f"[yellow]Skipped repos (not found):[/] {escape(', '.join(manifest.skipped_repos))}"
        )
    if manifest.restricted_contributions:
        err_console.print(
            f"[yellow]{manifest.restricted_contributions} private contributions are hidden from this token.[/]"
        )


class Period(StrEnum):
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"


@app.command()
def summary(
    data: Annotated[Path, typer.Option(help="Data directory written by fetch.")],
    period: Annotated[
        Period | None, typer.Option(help="Aggregation period. Default: from config.")
    ] = None,
    config: Annotated[
        Path | None, typer.Option(help="ledger.toml with filters and defaults.")
    ] = None,
) -> None:
    """Aggregate fetched tables into DATA/metrics.csv and print a table."""
    try:
        cfg = load_config(config)
        manifest = read_manifest(data)
        if manifest is None:
            raise StoreError(f"{data} has no manifest.json; run `gh-ledger fetch` first")
        tables = load_tables(data)
    except (ConfigError, StoreError) as exc:
        fail(exc)
    chosen = period.value if period else cfg.report.period
    metrics = compute_metrics(tables, manifest, cfg, chosen)
    write_metrics(metrics, data / "metrics.csv")
    _print_summary(summary_rows(metrics))
    err_console.print(f"Wrote {data / 'metrics.csv'}")


@app.command()
def report(
    data: Annotated[Path, typer.Option(help="Data directory written by fetch and summary.")],
    out: Annotated[Path, typer.Option(help="Directory for report.html and charts/.")],
    config: Annotated[Path | None, typer.Option(help="ledger.toml with [report] settings.")] = None,
    events: Annotated[list[Path] | None, typer.Option(help="Event YAML file. Repeatable.")] = None,
    redact_private: Annotated[
        bool, typer.Option(help="Show private repos as 'private repo N' everywhere.")
    ] = False,
) -> None:
    """Render DATA/metrics.csv as OUT/report.html plus PNG/SVG charts."""
    try:
        cfg = load_config(config)
        manifest = read_manifest(data)
        if manifest is None:
            raise StoreError(f"{data} has no manifest.json; run `gh-ledger fetch` first")
        metrics = read_metrics(data / "metrics.csv")
        if redact_private:
            metrics = redact_repos(metrics, load_table(data, "repos"))
        overlay = load_events(events or [])
    except (ConfigError, EventsError, StoreError) as exc:
        fail(exc)
    start, end = date.fromisoformat(manifest.since), date.fromisoformat(manifest.until)
    figures = build_charts(metrics, cfg.report, overlay, start, end)
    out.mkdir(parents=True, exist_ok=True)
    subtitle = f"{manifest.user} · {manifest.since} to {manifest.until}"
    page = build_html(cfg.report.title, subtitle, headline(metrics), figures)
    (out / "report.html").write_text(page, encoding="utf-8")
    err_console.print(f"Wrote {out / 'report.html'}")
    skipped = export_images(figures, out / "charts", cfg.report.image_size)
    if skipped:
        err_console.print(f"[yellow]Images skipped:[/] {escape(skipped)}")
    else:
        err_console.print(f"Wrote {len(figures) * 2} images to {out / 'charts'}")


def _print_summary(rows: list[list[str]]) -> None:
    table = Table(title="gh-ledger summary")
    table.add_column("Period", no_wrap=True)
    for name in SUMMARY_COLUMNS:
        table.add_column(METRIC_LABELS[name], justify="right")
    for row in rows:
        table.add_row(*row)
    console.print(table)
