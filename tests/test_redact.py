import pandas as pd

from gh_ledger.report.redact import redact_repos


def metrics(*rows):
    return pd.DataFrame(
        [
            {"period": "2024-01-01", "metric": "lines_changed", "value": v, "repo": r}
            for r, v in rows
        ]
        + [{"period": "2024-01-01", "metric": "prs_merged", "value": 3.0, "repo": ""}]
    )


def repos_table(*rows):
    return pd.DataFrame([{"repo": r, "is_private": p, "is_fork": "false"} for r, p in rows])


def test_private_repos_numbered_by_descending_activity():
    out = redact_repos(
        metrics(("acme/small", 100.0), ("acme/big", 500.0), ("octo/app", 1000.0)),
        repos_table(("acme/small", "true"), ("acme/big", "true"), ("octo/app", "false")),
    )
    names = dict(zip(out["value"], out["repo"], strict=True))
    assert names[500.0] == "private repo 1"
    assert names[100.0] == "private repo 2"
    assert names[1000.0] == "octo/app"
    assert "" in set(out["repo"])


def test_repo_missing_from_repos_table_is_treated_as_private():
    out = redact_repos(metrics(("mystery/repo", 5.0)), repos_table())
    assert "mystery/repo" not in set(out["repo"])
