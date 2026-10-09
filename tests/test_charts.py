import math
from datetime import date
from itertools import pairwise

import plotly.graph_objects as go
import pytest
from report_data import sample_metrics

from gh_ledger.config import ReportConfig
from gh_ledger.events import Event
from gh_ledger.report import build_charts, headline
from gh_ledger.report.charts import (
    activity,
    add_events,
    ai_share,
    compare,
    lines,
    repos,
    review_mix,
)

START, END = date(2024, 1, 1), date(2024, 4, 30)


def test_activity_has_four_panels():
    fig = activity(sample_metrics())
    assert [t.name for t in fig.data] == [
        "PRs merged",
        "Issues opened",
        "Reviews given",
        "Comments",
    ]
    assert len({t.yaxis for t in fig.data}) == 4


def test_lines_deletions_are_negative_and_raw_is_drawn():
    fig = lines(sample_metrics())
    deleted = next(t for t in fig.data if t.name == "Deleted")
    assert all(v < 0 for v in deleted.y)
    assert sum(1 for t in fig.data if t.legendgroup == "raw") == 2


def test_review_mix_stacks_three_series():
    fig = review_mix(sample_metrics())
    assert [t.name for t in fig.data] == ["Approved", "Changes requested", "Commented"]
    assert fig.layout.barmode == "stack"


def test_ai_share_leaves_empty_periods_blank():
    fig = ai_share(sample_metrics())
    assert math.isnan(fig.data[0].y[0])
    assert fig.data[0].y[1] == 0.25


def test_repos_folds_beyond_top_n_into_other():
    many = tuple((f"octo/r{i}", 10 * (i + 1)) for i in range(10))
    fig = repos(sample_metrics(repos=many), top_n=8)
    names = [t.name for t in fig.data]
    assert len(names) == 9
    assert names[0] == "octo/r9"
    assert names[-1] == "other"


def test_repos_with_no_repo_rows_is_empty():
    assert len(repos(sample_metrics(repos=())).data) == 0


def test_compare_table_means_before_and_after():
    fig = compare(sample_metrics(), date(2024, 3, 1))
    table = fig.data[0]
    labels, before, after, change = table.cells.values
    i = labels.index("PRs merged")
    assert (before[i], after[i], change[i]) == ("1.5", "3.5", "+133%")


def test_add_events_skips_out_of_range_and_labels_only_when_asked():
    events = [
        Event(date(2023, 6, 1), "Too early", group="Claude"),
        Event(date(2024, 2, 24), "Claude 3.7 Sonnet", group="Claude"),
        Event(date(2024, 3, 10), "Team change"),
    ]
    labelled = add_events(lines(sample_metrics()), events, START, END, labels=True)
    assert len(labelled.layout.shapes) == 2
    assert [a.text for a in labelled.layout.annotations] == ["Claude 3.7 Sonnet", "Team change"]
    markers = [t for t in labelled.data if t.legendgroup == "events"]
    assert sorted(t.name for t in markers) == ["Claude", "Events"]
    plain = add_events(lines(sample_metrics()), events, START, END, labels=False)
    assert len(plain.layout.annotations) == 0


def test_build_charts_follows_config_and_labels_first_time_chart_only():
    events = [Event(date(2024, 2, 24), "Launch")]
    config = ReportConfig(compare_at=date(2024, 3, 1))
    charts = build_charts(sample_metrics(), config, events, START, END)
    assert [name for name, _ in charts] == list(config.charts)
    labels = {
        name: [a.text for a in fig.layout.annotations if a.text == "Launch"] for name, fig in charts
    }
    assert labels["activity"] == ["Launch"]
    assert labels["lines"] == []
    assert all(isinstance(fig, go.Figure) for _, fig in charts)


def test_compare_is_omitted_without_compare_at():
    charts = build_charts(sample_metrics(), ReportConfig(), [], START, END)
    assert "compare" not in [name for name, _ in charts]


def test_headline_totals():
    assert dict(headline(sample_metrics()))["PRs merged"] == "10"


def test_lines_axis_fits_filtered_bars_not_the_raw_line():
    metrics = sample_metrics()
    is_raw_deleted = metrics["metric"] == "lines_deleted_raw"
    metrics.loc[is_raw_deleted, "value"] = 650_000.0
    fig = lines(metrics)
    low, high = fig.layout.yaxis.range
    deleted = max(-trace_value for trace_value in fig.data[1].y)
    assert low == pytest.approx(-deleted * 1.15)
    assert low > -650_000
    assert high == pytest.approx(max(fig.data[0].y) * 1.15)


def test_lines_axis_without_activity_is_left_automatic():
    metrics = sample_metrics()
    metrics.loc[metrics["metric"].isin(["lines_added", "lines_deleted"]), "value"] = 0.0
    assert lines(metrics).layout.yaxis.range is None


def test_close_event_labels_are_spread_apart():
    events = [Event(date=date(2024, 4, d), label=f"E{d}") for d in (20, 21, 22)]
    fig = add_events(lines(sample_metrics()), events, START, END, labels=True)
    span = (END - START).days
    placed = sorted(
        (event_day - START).days / span * 1100 + a.xshift
        for a, event_day in zip(fig.layout.annotations, (e.date for e in events), strict=True)
    )
    assert all(later - earlier >= 13 - 1e-6 for earlier, later in pairwise(placed))
    assert any(a.xshift != 0 for a in fig.layout.annotations)


def test_repos_legend_is_vertical_beside_the_plot():
    legend = repos(sample_metrics()).layout.legend
    assert legend.orientation == "v"
    assert legend.x > 1
