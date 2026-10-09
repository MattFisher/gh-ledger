# pyright: basic
# pandas leaves too many partially-unknown types for strict mode.
"""Aggregate the fetched tables into per-period metrics in long format."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from gh_ledger.config import Config, FiltersConfig
from gh_ledger.filters import AiMatcher, PathFilter
from gh_ledger.model import Manifest

PERIOD_FREQ = {"week": "W-SUN", "month": "M", "quarter": "Q"}

COUNT_METRICS = (
    "prs_opened",
    "prs_merged",
    "issues_opened",
    "direct_commits",
    "reviews_given",
    "approvals",
    "changes_requested",
    "commented",
    "comments",
    "comments_on_others",
    "lines_added",
    "lines_deleted",
    "lines_added_raw",
    "lines_deleted_raw",
    "lines_unfilterable",
    "repos_active",
)
SHARE_METRICS = ("ai_share_prs", "ai_share_commits", "ai_share_comments")

METRIC_LABELS = {
    "prs_opened": "PRs opened",
    "prs_merged": "PRs merged",
    "issues_opened": "Issues opened",
    "direct_commits": "Direct commits",
    "reviews_given": "Reviews given",
    "approvals": "Approvals",
    "changes_requested": "Changes requested",
    "commented": "Review comments only",
    "comments": "Comments",
    "comments_on_others": "Comments on others' items",
    "lines_added": "Lines added (filtered)",
    "lines_deleted": "Lines deleted (filtered)",
    "lines_added_raw": "Lines added (raw)",
    "lines_deleted_raw": "Lines deleted (raw)",
    "lines_unfilterable": "Lines in truncated file lists",
    "repos_active": "Active repos",
    "ai_share_prs": "AI-assisted PRs",
    "ai_share_commits": "AI-assisted direct commits",
    "ai_share_comments": "AI-assisted comments",
}

SUMMARY_COLUMNS = (
    "prs_opened",
    "prs_merged",
    "issues_opened",
    "reviews_given",
    "comments",
    "lines_added",
    "lines_deleted",
    "ai_share_prs",
    "repos_active",
)


def period_starts(timestamps: pd.Series, period: str) -> pd.Series:
    """Map ISO timestamps to the first day (YYYY-MM-DD) of their UTC period."""
    parsed = pd.to_datetime(timestamps, utc=True, format="ISO8601").dt.tz_convert(None)
    return parsed.dt.to_period(PERIOD_FREQ[period]).dt.start_time.dt.strftime("%Y-%m-%d")


def all_periods(since: str, until: str, period: str) -> list[str]:
    periods = pd.period_range(start=since, end=until, freq=PERIOD_FREQ[period])
    return [p.start_time.strftime("%Y-%m-%d") for p in periods]


def compute_metrics(
    tables: Mapping[str, pd.DataFrame], manifest: Manifest, config: Config, period: str
) -> pd.DataFrame:
    """Every metric for every period in the manifest's range, in long format."""
    periods = all_periods(manifest.since, manifest.until, period)
    user = manifest.user.lower()
    prs, issues, reviews, comments, commits = (
        tables[name] for name in ("prs", "issues", "reviews", "comments", "commits")
    )
    on_others = reviews[reviews["pr_author"].str.lower() != user]
    counts: dict[str, pd.Series] = {
        "prs_opened": _count(prs, "created_at", period),
        "prs_merged": _count(prs[prs["state"] == "merged"], "merged_at", period),
        "issues_opened": _count(issues, "created_at", period),
        "direct_commits": _count(commits, "authored_at", period),
        "reviews_given": _count(on_others, "submitted_at", period),
        "approvals": _count(on_others[on_others["state"] == "approved"], "submitted_at", period),
        "changes_requested": _count(
            on_others[on_others["state"] == "changes_requested"], "submitted_at", period
        ),
        "commented": _count(on_others[on_others["state"] == "commented"], "submitted_at", period),
        "comments": _count(comments, "created_at", period),
        "comments_on_others": _count(
            comments[comments["parent_author"].str.lower() != user], "created_at", period
        ),
        "repos_active": _repos_active(tables, period),
    }
    line_totals, per_repo = _lines(tables, config.filters, period)
    counts.update(line_totals)
    matcher = AiMatcher(config.ai.patterns)
    shares = {
        "ai_share_prs": _ai_share(prs, "created_at", matcher, period),
        "ai_share_commits": _ai_share(commits, "authored_at", matcher, period),
        "ai_share_comments": _ai_share(comments, "created_at", matcher, period),
    }
    frames = [
        _long(name, counts[name].reindex(periods, fill_value=0), periods) for name in COUNT_METRICS
    ]
    frames += [_long(name, shares[name].reindex(periods), periods) for name in SHARE_METRICS]
    per_repo = per_repo[per_repo["period"].isin(periods)]
    if not per_repo.empty:
        frames.append(
            per_repo.assign(metric="lines_changed")[["period", "metric", "value", "repo"]]
        )
    return pd.concat(frames, ignore_index=True)


def wide(metrics: pd.DataFrame, names: Sequence[str]) -> pd.DataFrame:
    """Overall (non-repo) metrics as one row per period and one column per metric."""
    overall = metrics[(metrics["repo"] == "") & metrics["metric"].isin(list(names))]
    table = overall.pivot(index="period", columns="metric", values="value")
    return table.reindex(columns=list(names)).sort_index()


def summary_rows(metrics: pd.DataFrame) -> list[list[str]]:
    """The terminal summary: one row per period, SUMMARY_COLUMNS formatted for display."""
    table = wide(metrics, SUMMARY_COLUMNS)
    rows: list[list[str]] = []
    for period_start, row in table.iterrows():
        cells = [str(period_start)]
        for name in SUMMARY_COLUMNS:
            v = row[name]
            if pd.isna(v):
                cells.append("\u2013")
            elif name in SHARE_METRICS:
                cells.append(f"{v:.0%}")
            else:
                cells.append(f"{int(v):,}")
        rows.append(cells)
    return rows


def _long(metric: str, values: pd.Series, periods: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"period": periods, "metric": metric, "value": values.to_numpy(dtype="float64"), "repo": ""}
    )


def _by_period(values: pd.Series, dates: pd.Series, period: str, how: str = "sum") -> pd.Series:
    if values.empty:
        return pd.Series(dtype="float64")
    return values.groupby(period_starts(dates, period).to_numpy()).agg(how)


def _count(frame: pd.DataFrame, column: str, period: str) -> pd.Series:
    dates = frame[column]
    dates = dates[dates != ""]
    return _by_period(pd.Series(1, index=dates.index), dates, period)


def _ints(frame: pd.DataFrame, *names: str) -> pd.DataFrame:
    return frame.astype(dict.fromkeys(names, "int64"))


def _lines(
    tables: Mapping[str, pd.DataFrame], filters: FiltersConfig, period: str
) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    prs = _ints(tables["prs"], "additions", "deletions")
    if not filters.count_unmerged_pr_lines:
        prs = prs[prs["state"] == "merged"]
    commits = _ints(tables["commits"], "additions", "deletions")
    sources = pd.concat(
        [
            pd.DataFrame(
                {
                    "source": "pr",
                    "source_id": prs["id"],
                    "date": prs["merged_at"].where(prs["merged_at"] != "", prs["created_at"]),
                    "additions": prs["additions"],
                    "deletions": prs["deletions"],
                }
            ),
            pd.DataFrame(
                {
                    "source": "commit",
                    "source_id": commits["sha"],
                    "date": commits["authored_at"],
                    "additions": commits["additions"],
                    "deletions": commits["deletions"],
                }
            ),
        ],
        ignore_index=True,
    )
    files = _ints(tables["file_changes"], "additions", "deletions")
    files = files.merge(sources[["source", "source_id"]], on=["source", "source_id"], how="inner")

    listed = files.groupby(["source", "source_id"], as_index=False)[
        ["additions", "deletions"]
    ].sum()
    gaps = sources.merge(listed, on=["source", "source_id"], how="left", suffixes=("", "_listed"))
    gaps = gaps.fillna({"additions_listed": 0, "deletions_listed": 0})
    unfilterable = (
        gaps["additions"] + gaps["deletions"] - gaps["additions_listed"] - gaps["deletions_listed"]
    ).clip(lower=0)

    path_filter = PathFilter(filters.exclude)
    kept = files[~files["path"].map(path_filter.excluded).astype(bool)]
    if filters.per_file_cap is not None:
        cap = filters.per_file_cap
        kept = kept.assign(
            additions=kept["additions"].clip(upper=cap), deletions=kept["deletions"].clip(upper=cap)
        )

    totals = {
        "lines_added": _by_period(kept["additions"], kept["date"], period),
        "lines_deleted": _by_period(kept["deletions"], kept["date"], period),
        "lines_added_raw": _by_period(sources["additions"], sources["date"], period),
        "lines_deleted_raw": _by_period(sources["deletions"], sources["date"], period),
        "lines_unfilterable": _by_period(unfilterable, gaps["date"], period),
    }
    per_repo = pd.DataFrame({"period": [], "repo": [], "value": []})
    if not kept.empty:
        changed = kept["additions"] + kept["deletions"]
        keys = [period_starts(kept["date"], period).to_numpy(), kept["repo"].to_numpy()]
        per_repo = (
            changed.groupby(keys)
            .sum()
            .astype("float64")
            .rename_axis(["period", "repo"])
            .reset_index(name="value")
        )
    return totals, per_repo


def _repos_active(tables: Mapping[str, pd.DataFrame], period: str) -> pd.Series:
    stamps = (
        ("prs", "created_at"),
        ("issues", "created_at"),
        ("reviews", "submitted_at"),
        ("comments", "created_at"),
        ("commits", "authored_at"),
    )
    activity = pd.concat(
        [
            pd.DataFrame({"repo": tables[name]["repo"], "date": tables[name][col]})
            for name, col in stamps
        ],
        ignore_index=True,
    )
    activity = activity[activity["date"] != ""]
    return _by_period(activity["repo"], activity["date"], period, how="nunique")


def _ai_share(frame: pd.DataFrame, date_column: str, matcher: AiMatcher, period: str) -> pd.Series:
    co_authors = (
        frame["co_authors"] if "co_authors" in frame.columns else pd.Series("", index=frame.index)
    )
    flags = pd.Series(
        [
            matcher.matches(text, [entry for entry in co.split(";") if entry])
            for text, co in zip(frame["text"], co_authors, strict=True)
        ],
        index=frame.index,
        dtype="float64",
    )
    return _by_period(flags, frame[date_column], period, how="mean")
