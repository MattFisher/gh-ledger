import math

from builders import comment, commit, file_change, issue, manifest, pr, review, tables

from gh_ledger.config import Config, FiltersConfig
from gh_ledger.metrics import (
    COUNT_METRICS,
    SHARE_METRICS,
    all_periods,
    compute_metrics,
    summary_rows,
    wide,
)
from gh_ledger.store import read_metrics, write_metrics

JAN, FEB, MAR = "2024-01-01", "2024-02-01", "2024-03-01"


def value(metrics, metric, period, repo=""):
    row = metrics[
        (metrics["metric"] == metric) & (metrics["period"] == period) & (metrics["repo"] == repo)
    ]
    assert len(row) == 1, (metric, period, repo)
    return row["value"].iloc[0]


def compute(config=None, period="month", **rows):
    return compute_metrics(tables(**rows), manifest(), config or Config(), period)


def test_all_periods():
    assert all_periods("2024-01-15", "2024-03-02", "month") == [JAN, FEB, MAR]
    assert all_periods("2024-01-03", "2024-01-16", "week") == [
        "2024-01-01",
        "2024-01-08",
        "2024-01-15",
    ]
    assert all_periods("2024-02-10", "2024-07-01", "quarter") == [
        "2024-01-01",
        "2024-04-01",
        "2024-07-01",
    ]


def test_output_counts():
    metrics = compute(
        prs=[
            pr("A", created_at="2024-01-05T00:00:00Z", merged_at="2024-02-02T00:00:00Z"),
            pr("B", state="open", created_at="2024-01-20T00:00:00Z"),
        ],
        issues=[issue(created_at="2024-03-03T00:00:00Z")],
        commits=[commit(authored_at="2024-02-10T00:00:00Z")],
    )
    assert value(metrics, "prs_opened", JAN) == 2
    assert value(metrics, "prs_merged", JAN) == 0
    assert value(metrics, "prs_merged", FEB) == 1
    assert value(metrics, "issues_opened", MAR) == 1
    assert value(metrics, "direct_commits", FEB) == 1


def test_review_counts_skip_own_prs():
    metrics = compute(
        reviews=[
            review("R1", state="approved"),
            review("R2", state="changes_requested"),
            review("R3", state="commented"),
            review("R4", state="dismissed"),
            review("R5", state="approved", pr_author="OctoCat"),
        ]
    )
    assert value(metrics, "reviews_given", JAN) == 4
    assert value(metrics, "approvals", JAN) == 1
    assert value(metrics, "changes_requested", JAN) == 1
    assert value(metrics, "commented", JAN) == 1


def test_reviews_on_ghost_prs_count_as_others():
    metrics = compute(reviews=[review(pr_author="")], comments=[comment(parent_author="")])
    assert value(metrics, "reviews_given", JAN) == 1
    assert value(metrics, "comments_on_others", JAN) == 1


def test_comment_counts():
    metrics = compute(
        comments=[
            comment("C1", parent_author="someone"),
            comment("C2", parent_author="octocat", kind="review_inline"),
        ]
    )
    assert value(metrics, "comments", JAN) == 2
    assert value(metrics, "comments_on_others", JAN) == 1


def test_line_filters_cap_and_raw_totals():
    metrics = compute(
        prs=[pr("A", additions=5510, deletions=402)],
        file_changes=[
            file_change("A", "src/app.py", additions=10, deletions=2),
            file_change("A", "uv.lock", additions=500, deletions=400),
            file_change("A", "src/generated.py", additions=5000, deletions=0),
        ],
    )
    assert value(metrics, "lines_added", JAN) == 10 + 1000
    assert value(metrics, "lines_deleted", JAN) == 2
    assert value(metrics, "lines_added_raw", JAN) == 5510
    assert value(metrics, "lines_deleted_raw", JAN) == 402
    assert value(metrics, "lines_unfilterable", JAN) == 0
    assert value(metrics, "lines_changed", JAN, repo="octo/app") == 1012


def test_cap_can_be_disabled():
    config = Config(filters=FiltersConfig(per_file_cap=None))
    metrics = compute(
        config, prs=[pr("A", additions=5000)], file_changes=[file_change("A", additions=5000)]
    )
    assert value(metrics, "lines_added", JAN) == 5000


def test_truncated_pr_reports_unfilterable_lines():
    metrics = compute(
        prs=[
            pr(
                "A",
                merged_at="2024-02-02T00:00:00Z",
                additions=100,
                deletions=50,
                files_truncated=True,
            )
        ],
        file_changes=[
            file_change("A", "a.py", additions=30, deletions=10, date="2024-02-02T00:00:00Z")
        ],
    )
    assert value(metrics, "lines_unfilterable", FEB) == 110
    assert value(metrics, "lines_added", FEB) == 30


def test_unmerged_pr_lines_only_count_when_configured():
    rows = {
        "prs": [pr("A", state="open", created_at="2024-03-05T00:00:00Z", additions=7, deletions=0)],
        "file_changes": [file_change("A", additions=7, deletions=0, date="2024-03-05T00:00:00Z")],
    }
    assert value(compute(**rows), "lines_added", MAR) == 0
    config = Config(filters=FiltersConfig(count_unmerged_pr_lines=True))
    assert value(compute(config, **rows), "lines_added", MAR) == 7


def test_direct_commit_lines():
    metrics = compute(
        commits=[commit("c1", authored_at="2024-03-05T00:00:00Z", additions=5, deletions=1)],
        file_changes=[
            file_change(
                "c1", source="commit", additions=5, deletions=1, date="2024-03-05T00:00:00Z"
            )
        ],
    )
    assert value(metrics, "lines_added", MAR) == 5
    assert value(metrics, "lines_added_raw", MAR) == 5


def test_ai_shares():
    metrics = compute(
        prs=[
            pr("A", text="🤖 Generated with [Claude Code](https://claude.com/claude-code)"),
            pr("B"),
            pr("C", co_authors=["Claude <noreply@anthropic.com>"]),
            pr("D"),
        ],
        comments=[comment(text="Posted by Claude Code")],
    )
    assert value(metrics, "ai_share_prs", JAN) == 0.5
    assert value(metrics, "ai_share_comments", JAN) == 1.0
    assert math.isnan(value(metrics, "ai_share_prs", FEB))
    assert math.isnan(value(metrics, "ai_share_commits", JAN))


def test_repos_active():
    metrics = compute(
        prs=[pr("A", repo="octo/a")],
        comments=[comment(repo="octo/b"), comment("C2", repo="octo/b")],
    )
    assert value(metrics, "repos_active", JAN) == 2


def test_no_activity_gives_zero_counts_and_empty_shares():
    metrics = compute()
    for metric in COUNT_METRICS:
        for period in (JAN, FEB, MAR):
            assert value(metrics, metric, period) == 0
    for metric in SHARE_METRICS:
        assert math.isnan(value(metrics, metric, JAN))
    assert not (metrics["repo"] != "").any()


def test_wide_pivots_overall_metrics():
    table = wide(compute(prs=[pr()]), ["prs_opened", "prs_merged"])
    assert list(table.columns) == ["prs_opened", "prs_merged"]
    assert list(table.index) == [JAN, FEB, MAR]


def test_metrics_csv_round_trip(tmp_path):
    metrics = compute(prs=[pr()])
    path = tmp_path / "metrics.csv"
    write_metrics(metrics, path)
    text = path.read_text(encoding="utf-8")
    assert "prs_opened,1," in text
    assert ".0," not in text
    back = read_metrics(path)
    assert math.isnan(value(back, "ai_share_prs", FEB))
    assert value(back, "prs_opened", JAN) == 1
    assert len(back) == len(metrics)


def test_summary_rows_format_counts_and_shares():
    rows = summary_rows(compute(prs=[pr()]))
    assert rows[0][:3] == [JAN, "1", "1"]
    assert rows[0][-2] == "0%"
    assert rows[1][-2] == "\u2013"
