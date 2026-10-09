# pyright: basic
# pandas leaves too many partially-unknown types for strict mode.
"""Hide private repo names in report output."""

from __future__ import annotations

import pandas as pd


def redact_repos(metrics: pd.DataFrame, repos: pd.DataFrame) -> pd.DataFrame:
    """Rename private repos to `private repo N`, numbered by descending activity.

    Repos missing from `repos` are treated as private: when unsure, hide the name.
    """
    public = set() if repos.empty else set(repos.loc[repos["is_private"] == "false", "repo"])
    activity = metrics[metrics["repo"] != ""].groupby("repo")["value"].sum()
    hidden = sorted((r for r in activity.index if r not in public), key=lambda r: (-activity[r], r))
    names = {repo: f"private repo {i}" for i, repo in enumerate(hidden, start=1)}
    return metrics.assign(repo=metrics["repo"].map(lambda r: names.get(r, r)))
