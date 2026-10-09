# gh-ledger

gh-ledger measures one GitHub user's activity over many years: pull requests, issues, reviews, comments, commits and lines changed. It fetches the data once, aggregates it by week, month or quarter, and renders charts over time as a self-contained HTML report (plus PNG/SVG images).

## Install

```bash
uv tool install gh-ledger          # or: pipx install gh-ledger
uv tool install 'gh-ledger[images]' # adds PNG/SVG export
```

PNG/SVG export uses kaleido, which needs Chrome. If you don't have it, run `plotly_get_chrome` once. Without the `images` extra (or without Chrome) `report` still writes `report.html` and says that images were skipped.

## Quick start

```bash
gh-ledger fetch --user YOUR_LOGIN --since 2024-01-01 --data data/me
gh-ledger summary --data data/me
gh-ledger report --data data/me --out data/me/report --events examples/events/claude-models.yaml
```

Open `data/me/report/report.html`. Charts are also written to `data/me/report/charts/`.

## Authentication

gh-ledger reads a token from `GITHUB_TOKEN`; if that is unset it runs `gh auth token`. For public data any token works. To include private repos you need the `repo` scope (the `gh` CLI's default login has it) and, for organisation repos, the token must be authorised for those organisations.

## Privacy

With `--visibility all`, private repo names, PR, issue and comment bodies and commit messages are written to `DATA/*.csv` and `DATA/cache/`. Keep data directories out of git; the scaffolded `.gitignore` ignores `/data/`.

`--redact-private` renames private repos to `private repo N` in the report only. It does not change the data directory.

The default `--visibility public` fetches public repos only. In that mode review-contribution responses are not cached, so private text never lands in `DATA/cache`; conversation comments are never cached in any mode.

## Commands

### `gh-ledger fetch`

| Flag                       | Default        | Meaning                                            |
| -------------------------- | -------------- | -------------------------------------------------- |
| `--user LOGIN`             | required       | GitHub login to measure                            |
| `--since YYYY-MM-DD`       | required       | First day (UTC)                                    |
| `--data DIR`               | required       | Directory for tables, manifest and cache           |
| `--until YYYY-MM-DD`       | today          | Last day (UTC)                                     |
| `--visibility public\|all` | `public`       | Public repos only, or everything the token can see |
| `--author-email EMAIL`     | none           | Commit email not linked to the account; repeatable |
| `--refresh / --no-refresh` | `--no-refresh` | Ignore the cache and re-fetch everything           |

### `gh-ledger summary`

| Flag                            | Default                  | Meaning                                 |
| ------------------------------- | ------------------------ | --------------------------------------- |
| `--data DIR`                    | required                 | Data directory written by `fetch`       |
| `--period week\|month\|quarter` | from config (`month`)    | Aggregation period                      |
| `--config FILE`                 | none (built-in defaults) | `ledger.toml` with filters and defaults |

It writes `DIR/metrics.csv` and prints a table.

### `gh-ledger report`

| Flag                                     | Default                  | Meaning                                           |
| ---------------------------------------- | ------------------------ | ------------------------------------------------- |
| `--data DIR`                             | required                 | Data directory written by `fetch` and `summary`   |
| `--out DIR`                              | required                 | Directory for `report.html` and `charts/`         |
| `--config FILE`                          | none (built-in defaults) | `ledger.toml` with `[report]` settings            |
| `--events FILE`                          | none                     | Event YAML file; repeatable                       |
| `--redact-private / --no-redact-private` | `--no-redact-private`    | Show private repos as `private repo N` everywhere |

`report` reads `metrics.csv`, so rerun `summary` after changing filters or the period.

## What is counted

`summary` computes these per period (by UTC date):

| Metric                                               | Meaning                                                                                                                                                                              |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| PRs opened / merged                                  | PRs by creation date / by merge date                                                                                                                                                 |
| Issues opened                                        | Issues by creation date                                                                                                                                                              |
| Direct commits                                       | Commits not already part of a PR you opened. Merge commits are never counted, and a commit that appears in several copies of a repository's history is counted once, in the original |
| Reviews given                                        | Reviews you submitted on other people's PRs                                                                                                                                          |
| Approvals, changes requested, review comments only   | Reviews given, split by outcome                                                                                                                                                      |
| Comments                                             | Issue and PR conversation comments you wrote                                                                                                                                         |
| Comments on others' items                            | Comments on items someone else opened                                                                                                                                                |
| Lines added / deleted (filtered)                     | After the path exclusions and per-file cap below                                                                                                                                     |
| Lines added / deleted (raw)                          | GitHub's totals, before any filtering                                                                                                                                                |
| Lines in truncated file lists (`lines_unfilterable`) | Lines in PRs or commits whose file list GitHub truncated, so the filters cannot be applied to them. They are in the raw totals and not in the filtered ones.                         |
| AI-assisted PRs, commits, comments                   | Share of that period's items matching an AI marker; empty if none                                                                                                                    |
| Active repos                                         | Distinct repos with any activity in the period                                                                                                                                       |
| Lines changed per repo                               | Filtered additions plus deletions by repo; feeds the repos chart                                                                                                                     |

Reviews and review metrics count only other people's PRs. Lines come from merged PRs and from direct commits, never both for the same change. Unmerged PRs contribute no lines unless `count_unmerged_pr_lines = true`.

Commit author dates are normalised to UTC before they are bucketed into periods.

## Filters

Filtered line counts leave out these files by default:

- Lockfiles: `uv.lock`, `poetry.lock`, `Pipfile.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `go.sum`, `composer.lock`, `Gemfile.lock`.
- Data and notebooks: `*.json`, `*.jsonl`, `*.csv`, `*.tsv`, `*.ipynb`, `*.svg`, `*.parquet`.
- Vendored and build output: `vendor/`, `node_modules/`, `dist/`, `build/`, `*.min.js`, `*.min.css`, `*.map`.

Patterns follow a subset of `.gitignore`:

- `name/` excludes any path with a directory called `name`, at any depth.
- A pattern without `/` matches the file name at any depth (`*.json`, `uv.lock`).
- Any other pattern matches the whole path from the repo root (`fixtures/**`). `*` stays within one directory; `**` crosses directories.

Add patterns with `extra_exclude`, or replace the defaults with `exclude`. A single file's additions and deletions in one PR or commit are each capped at `per_file_cap` (default 1000); `per_file_cap = false` disables the cap. `.gitattributes` is not read.

## AI-assistance markers

A PR, direct commit or comment counts as AI-assisted (reviews and issues are not scored) if any regex in `[ai].patterns` matches its text or one of its `Co-authored-by` trailers. The defaults are:

```text
(?i)co-authored-by:.*\b(claude|copilot|cursor|codex|gemini|devin)\b
(?i)generated with \[?claude code
(?i)posted by \[?claude code
```

Setting `patterns` in `[ai]` replaces the defaults, so include any you want to keep. This is a text heuristic: work done with tools that leave no marker is not counted.

## Events

Event files are YAML lists drawn as markers on every time chart. Each entry has a `date` and `label`, and optionally a `group` and a `url`:

```yaml
- date: 2025-02-24
  label: Claude 3.7 Sonnet + Claude Code preview
  group: Claude
  url: https://www.anthropic.com/news/claude-3-7-sonnet
```

`examples/events/claude-models.yaml` lists Claude model releases. Pass `--events` more than once to combine files.

## Configuration

Pass `--config ledger.toml` to `summary` and `report`. Every key is optional; see [`examples/ledger.toml`](examples/ledger.toml) for all of them.

## Using the charts from Python

```python
from pathlib import Path

from gh_ledger.store import read_metrics
from gh_ledger.report import charts

metrics = read_metrics(Path("data/me/metrics.csv"))
charts.lines(metrics).show()  # a Plotly figure: adjust it or save it as you like
```

## Limitations

- Commit search only finds commits whose email is linked to the account. Use `--author-email` for others.
- Review coverage is slightly below GitHub's `reviewed-by` search: in a live probe the review data covered 256 of 277 and 430 of 441 PRs over a year, so a few reviews may be missing.
- Private activity the token cannot see as items (for example organisation repos where the token is not authorised, or SSO/OAuth app restrictions) appears only as a restricted contribution count, which `fetch` prints. Authorising the token for those organisations may recover it.
- The manifest's `dropped_pr_commits` and `restricted_contributions` describe the most recent fetch run's date range, not the cumulative range.
- The lines chart's axis fits the filtered bars, so a very large raw ("Before filters") value can run off the chart. Hover still shows it.
- Conversation comments are re-read from GitHub on every run.
- `.gitattributes` is not read.
- No GitHub Enterprise, Discussions or multi-user aggregation.

## Development

```bash
uv sync
uv run pre-commit install   # optional: run the lint stack on every commit
uv run pytest
uv run basedpyright src
```

Each pull request adds a changelog fragment rather than editing `CHANGELOG.md`, so concurrent PRs don't conflict. Run `uv run scriv create`, uncomment the sections that apply in the new file under `changelog.d/`, and commit it with the change, or delete it if the change needs no entry. To release, run the **Prepare release** workflow from the Actions tab. It bumps `version` in `pyproject.toml`, collects the fragments into `CHANGELOG.md`, and opens a release pull request, whose CI starts once you click **Approve workflows to run** on it; merging it tags the release. It needs _Settings → Actions → General_ → **Allow GitHub Actions to create and approve pull requests**. By hand, the same is `uv version --bump minor` and `uv run scriv collect`.

Linting (ruff, [zizmor](https://docs.zizmor.sh/), mdformat) runs via [pre-commit](https://pre-commit.com); CI runs the same stack plus basedpyright and pytest via the shared [`python-ci`](https://github.com/MattFisher/python-project-template) reusable workflow.

## Releasing

See [RELEASING.md](RELEASING.md).
