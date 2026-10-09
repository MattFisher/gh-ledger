# pyright: basic
# plotly is untyped and pandas leaves partially-unknown types; strict mode can't help here.
"""Build the report's charts and headline numbers from metrics."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

import pandas as pd
import plotly.graph_objects as go

from gh_ledger.config import ReportConfig
from gh_ledger.events import Event
from gh_ledger.report import charts

TIME_CHARTS = ("activity", "lines", "review_mix", "ai_share", "repos")
HEADLINE = (
    ("prs_merged", "PRs merged"),
    ("issues_opened", "Issues opened"),
    ("reviews_given", "Reviews given"),
    ("comments", "Comments"),
    ("lines_added", "Lines added"),
    ("lines_deleted", "Lines deleted"),
)
SIMPLE_CHARTS: dict[str, Callable[[pd.DataFrame], go.Figure]] = {
    "activity": charts.activity,
    "lines": charts.lines,
    "review_mix": charts.review_mix,
    "ai_share": charts.ai_share,
}


def build_charts(
    metrics: pd.DataFrame, config: ReportConfig, events: Sequence[Event], start: date, end: date
) -> list[tuple[str, go.Figure]]:
    """Charts in configured order. Event labels go on the first time chart only."""
    figures: list[tuple[str, go.Figure]] = []
    for name in config.charts:
        if name == "compare":
            if config.compare_at is not None:
                figures.append((name, charts.compare(metrics, config.compare_at)))
            continue
        fig = (
            charts.repos(metrics, config.top_repos)
            if name == "repos"
            else SIMPLE_CHARTS[name](metrics)
        )
        first = not any(existing in TIME_CHARTS for existing, _ in figures)
        figures.append((name, charts.add_events(fig, events, start, end, labels=first)))
    return figures


def headline(metrics: pd.DataFrame) -> list[tuple[str, str]]:
    """Totals over the whole range for the strip above the charts."""
    totals = metrics[metrics["repo"] == ""].groupby("metric")["value"].sum()
    return [(label, f"{int(totals.get(name, 0)):,}") for name, label in HEADLINE]
