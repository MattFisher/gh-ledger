# pyright: basic
# plotly is untyped and pandas leaves partially-unknown types; strict mode can't help here.
"""One function per chart: long-format metrics DataFrame in, Plotly figure out."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gh_ledger.events import Event
from gh_ledger.metrics import COUNT_METRICS, METRIC_LABELS, SHARE_METRICS, wide

# Categorical slots in fixed order; never cycled. A ninth series folds into "other".
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
OTHER = "#b5b4ae"
OTHER_LABEL = "other"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e7e6e2"
SURFACE = "#fcfcfb"
EVENT_COLORS = ("#4a3aa7", "#e34948", "#008300", "#e87ba4", "#1c5cab")

ACTIVITY_PANELS = (
    ("prs_merged", "PRs merged"),
    ("issues_opened", "Issues opened"),
    ("reviews_given", "Reviews given"),
    ("comments", "Comments"),
)
REVIEW_SERIES = (
    ("approvals", "Approved"),
    ("changes_requested", "Changes requested"),
    ("commented", "Commented"),
)
AI_SERIES = (
    ("ai_share_prs", "PRs"),
    ("ai_share_commits", "Direct commits"),
    ("ai_share_comments", "Comments"),
)


def _layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title={"text": title, "x": 0, "xanchor": "left"},
        template="plotly_white",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={
            "family": "system-ui, -apple-system, Segoe UI, sans-serif",
            "size": 13,
            "color": TEXT,
        },
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 60, "r": 20, "t": 90, "b": 40},
        bargap=0.15,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


def _bar_marker(color: str) -> dict[str, object]:
    # A thin surface-coloured outline separates stacked segments and adjacent bars.
    return {"color": color, "line": {"color": SURFACE, "width": 1.5}}


def _x(table: pd.DataFrame) -> list[pd.Timestamp]:
    return list(pd.to_datetime(table.index))


def activity(metrics: pd.DataFrame) -> go.Figure:
    table = wide(metrics, [name for name, _ in ACTIVITY_PANELS])
    fig = make_subplots(
        rows=len(ACTIVITY_PANELS),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=[label for _, label in ACTIVITY_PANELS],
    )
    x = _x(table)
    for row, (name, label) in enumerate(ACTIVITY_PANELS, start=1):
        fig.add_trace(
            go.Bar(
                x=x,
                y=table[name],
                name=label,
                marker=_bar_marker(SERIES[0]),
                showlegend=False,
                hovertemplate=f"{label}: %{{y:,}}<extra></extra>",
            ),
            row=row,
            col=1,
        )
    fig.update_layout(height=760)
    return _layout(fig, "Activity")


def lines(metrics: pd.DataFrame) -> go.Figure:
    table = wide(metrics, ["lines_added", "lines_deleted", "lines_added_raw", "lines_deleted_raw"])
    x = _x(table)
    raw_line = {"color": TEXT_MUTED, "width": 2}
    fig = go.Figure(
        [
            go.Bar(
                x=x,
                y=table["lines_added"],
                name="Added",
                marker=_bar_marker(SERIES[0]),
                hovertemplate="Added: %{y:,}<extra></extra>",
            ),
            go.Bar(
                x=x,
                y=-table["lines_deleted"],
                name="Deleted",
                marker=_bar_marker(SERIES[1]),
                customdata=table["lines_deleted"],
                hovertemplate="Deleted: %{customdata:,}<extra></extra>",
            ),
            go.Scatter(
                x=x,
                y=table["lines_added_raw"],
                name="Before filters",
                mode="lines",
                line=raw_line,
                opacity=0.45,
                legendgroup="raw",
                hovertemplate="Added before filters: %{y:,}<extra></extra>",
            ),
            go.Scatter(
                x=x,
                y=-table["lines_deleted_raw"],
                name="Before filters",
                mode="lines",
                line=raw_line,
                opacity=0.45,
                legendgroup="raw",
                showlegend=False,
                customdata=table["lines_deleted_raw"],
                hovertemplate="Deleted before filters: %{customdata:,}<extra></extra>",
            ),
        ]
    )
    fig.update_layout(barmode="relative")
    fig.update_yaxes(title_text="Lines")
    return _layout(fig, "Lines changed (generated and data files filtered out)")


def review_mix(metrics: pd.DataFrame) -> go.Figure:
    table = wide(metrics, [name for name, _ in REVIEW_SERIES])
    x = _x(table)
    fig = go.Figure(
        [
            go.Bar(
                x=x,
                y=table[name],
                name=label,
                marker=_bar_marker(SERIES[i]),
                hovertemplate=f"{label}: %{{y:,}}<extra></extra>",
            )
            for i, (name, label) in enumerate(REVIEW_SERIES)
        ]
    )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Reviews on others' PRs")
    return _layout(fig, "Review mix")


def ai_share(metrics: pd.DataFrame) -> go.Figure:
    table = wide(metrics, [name for name, _ in AI_SERIES])
    x = _x(table)
    fig = go.Figure(
        [
            go.Scatter(
                x=x,
                y=table[name],
                name=label,
                mode="lines+markers",
                line={"color": SERIES[i], "width": 2},
                marker={"size": 8, "color": SERIES[i], "line": {"color": SURFACE, "width": 2}},
                connectgaps=False,
                hovertemplate=f"{label}: %{{y:.0%}}<extra></extra>",
            )
            for i, (name, label) in enumerate(AI_SERIES)
        ]
    )
    fig.update_yaxes(tickformat=".0%", range=[0, 1.05], title_text="Share AI-assisted")
    return _layout(fig, "AI-assisted share")


def repos(metrics: pd.DataFrame, top_n: int = 8) -> go.Figure:
    per_repo = metrics[(metrics["metric"] == "lines_changed") & (metrics["repo"] != "")]
    fig = go.Figure()
    if not per_repo.empty:
        totals = (
            per_repo.groupby("repo")["value"]
            .sum()
            .sort_index()
            .sort_values(ascending=False, kind="stable")
        )
        top = list(totals.index[:top_n])
        grouped = per_repo.assign(
            repo=per_repo["repo"].where(per_repo["repo"].isin(top), OTHER_LABEL)
        )
        table = grouped.pivot_table(
            index="period", columns="repo", values="value", aggfunc="sum", fill_value=0
        )
        table = table.reindex(sorted(metrics["period"].unique()), fill_value=0)
        names = top + ([OTHER_LABEL] if OTHER_LABEL in table.columns else [])
        x = _x(table)
        for i, name in enumerate(names):
            color = OTHER if name == OTHER_LABEL else SERIES[i]
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=table[name],
                    name=name,
                    marker=_bar_marker(color),
                    hovertemplate=f"{name}: %{{y:,}}<extra></extra>",
                )
            )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Lines changed (filtered)")
    return _layout(fig, "Lines changed by repo")


def compare(metrics: pd.DataFrame, compare_at: date) -> go.Figure:
    names = [*COUNT_METRICS, *SHARE_METRICS]
    table = wide(metrics, names)
    starts = pd.to_datetime(table.index)
    cut = pd.Timestamp(compare_at)
    before = table[starts < cut].mean()
    after = table[starts >= cut].mean()
    labels = [METRIC_LABELS[name] for name in names]
    before_cells = [_fmt(before[name], share=name in SHARE_METRICS) for name in names]
    after_cells = [_fmt(after[name], share=name in SHARE_METRICS) for name in names]
    change_cells = [_change(before[name], after[name]) for name in names]
    fig = go.Figure(
        go.Table(
            header={
                "values": [
                    "Metric (mean per period)",
                    f"Before {compare_at}",
                    f"From {compare_at}",
                    "Change",
                ],
                "align": "left",
                "fill_color": GRID,
                "font": {"color": TEXT},
            },
            cells={
                "values": [labels, before_cells, after_cells, change_cells],
                "align": "left",
                "fill_color": SURFACE,
                "font": {"color": TEXT},
            },
        )
    )
    fig.update_layout(height=120 + 28 * len(names))
    return _layout(fig, f"Before and after {compare_at}")


def _fmt(value: float, *, share: bool) -> str:
    if pd.isna(value):
        return "\u2013"
    return f"{value:.0%}" if share else f"{value:,.1f}"


def _change(before: float, after: float) -> str:
    if pd.isna(before) or pd.isna(after) or before == 0:
        return "\u2013"
    return f"{(after - before) / before:+.0%}"


def add_events(
    fig: go.Figure, events: Sequence[Event], start: date, end: date, *, labels: bool
) -> go.Figure:
    """Dashed vertical lines for events in [start, end], coloured by group, with hover markers."""
    shown = [event for event in events if start <= event.date <= end]
    groups = list(dict.fromkeys(event.group for event in shown))
    named = [group for group in groups if group]
    colors = {
        group: EVENT_COLORS[i] if i < len(EVENT_COLORS) else TEXT_MUTED
        for i, group in enumerate(named)
    }
    colors[""] = TEXT_MUTED
    for event in shown:
        x = event.date.isoformat()
        fig.add_vline(x=x, line={"dash": "dash", "width": 1, "color": colors[event.group]})
        if labels:
            fig.add_annotation(
                x=x,
                y=1,
                xref="x",
                yref="paper",
                text=event.label,
                textangle=-90,
                xanchor="right",
                yanchor="top",
                showarrow=False,
                font={"size": 10, "color": TEXT_MUTED},
            )
    for group in groups:
        members = [event for event in shown if event.group == group]
        fig.add_trace(
            go.Scatter(
                x=[event.date.isoformat() for event in members],
                y=[0] * len(members),
                mode="markers",
                marker={"symbol": "triangle-up", "size": 10, "color": colors[group]},
                name=group or "Events",
                legendgroup="events",
                text=[f"{event.date:%Y-%m-%d} {event.label}" for event in members],
                hovertemplate="%{text}<extra></extra>",
            )
        )
    return fig
