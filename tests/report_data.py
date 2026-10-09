"""A small metrics fixture for chart and report tests."""

import pandas as pd

from gh_ledger.metrics import COUNT_METRICS, SHARE_METRICS
from gh_ledger.model import FetchResult, Manifest, RepoRow
from gh_ledger.store import write_manifest, write_metrics, write_tables

PERIODS = ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]
PRIVATE_REPO = "acme/secret-plans"
REPOS = (("octo/app", 100), (PRIVATE_REPO, 300), ("octo/lib", 50))


def sample_metrics(repos=REPOS):
    rows = []
    for i, period in enumerate(PERIODS):
        for metric in COUNT_METRICS:
            rows.append({"period": period, "metric": metric, "value": float(i + 1), "repo": ""})
        for metric in SHARE_METRICS:
            rows.append(
                {
                    "period": period,
                    "metric": metric,
                    "value": 0.25 * i if i else float("nan"),
                    "repo": "",
                }
            )
        for name, scale in repos:
            rows.append(
                {
                    "period": period,
                    "metric": "lines_changed",
                    "value": float(scale * (i + 1)),
                    "repo": name,
                }
            )
    return pd.DataFrame(rows)


def write_report_data(data_dir, metrics=None):
    data_dir.mkdir(parents=True, exist_ok=True)
    write_metrics(sample_metrics() if metrics is None else metrics, data_dir / "metrics.csv")
    write_tables(
        data_dir,
        FetchResult(
            repos=[
                RepoRow("octo/app", is_private=False, is_fork=False),
                RepoRow(PRIVATE_REPO, is_private=True, is_fork=False),
                RepoRow("octo/lib", is_private=False, is_fork=False),
            ]
        ),
    )
    write_manifest(
        data_dir,
        Manifest(
            user="octocat",
            since="2024-01-01",
            until="2024-04-30",
            visibility="all",
            fetched_at="2024-05-01T00:00:00Z",
            tool_version="0.1.0",
        ),
    )
