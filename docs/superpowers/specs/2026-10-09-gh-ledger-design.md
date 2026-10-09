# gh-ledger design

Date: 2026-10-09. Status: approved in conversation, awaiting written-spec review.

## Purpose

gh-ledger measures one GitHub user's activity over a long period (typically years) and reports it as charts over time. It counts PRs, issues, reviews and approvals, comments, and lines of code changed, with generated and data files filtered out of the line counts.

The author's own use is a before/after view of personal output across AI coding tool releases, written up as a blog post. The built-in report is general purpose so it is useful to anyone. The AI-specific angle comes from two generic features: event overlays (dated markers on every chart) and AI-assistance markers (regex patterns over commit trailers and text).

No existing tool covers this combination. Surveyed on 2026-10-09:

- [d3lm/pr-stats](https://github.com/d3lm/pr-stats): PRs and reviews given, but no issues and no file filtering.
- [gitbrag](https://pypi.org/project/gitbrag/): authored PRs and lines, but no reviews, issues or comments.
- [OSS Insight](https://ossinsight.io/docs): public repos only.
- [lowlighter/metrics](https://github.com/lowlighter/metrics): profile SVG cards, not analysis.

## Requirements

- Collect authored PRs, opened issues, submitted reviews (with state), comments (issue, PR conversation, inline review), and direct commits to default branches.
- Line counts come from merged PRs plus direct commits. Commits attached to a PR are not counted twice.
- Store per-file line counts raw. Exclusions apply at analysis time, so changing a filter never needs a re-fetch.
- Whether private repos are fetched is a parameter (`--visibility public|all`).
- Hiding private repo names in report output is a separate parameter (`--redact-private`).
- Modular pipeline: fetch writes a standard CSV format; analysis and reporting read only that format.
- A built-in report with charts over time, exported as HTML plus PNG/SVG per chart.
- Event overlays from user-supplied YAML files. The repo ships a Claude model release file as an example.
- Record co-author trailers and detect AI-assistance markers with configurable patterns.

## Architecture

Three CLI commands, one per stage. Each stage reads only the previous stage's output on disk.

```
gh-ledger fetch   --user U --since DATE [--until DATE] [--visibility public|all] [--author-email E]... [--refresh] --data DIR
gh-ledger summary --data DIR [--period week|month|quarter] [--config ledger.toml]
gh-ledger report  --data DIR --out DIR [--config ledger.toml] [--events FILE]... [--redact-private]
```

- `fetch` writes raw responses to `DIR/cache/`, the normalised tables to `DIR/*.csv`, and `DIR/manifest.json`. The manifest holds the user, date range, visibility, fetch time, tool version, count of commits dropped as PR-attached or merge commits, skipped repos, and any restricted (anonymous) contribution counts.
- `summary` applies filters, aggregates by period, writes `DIR/metrics.csv` in long format (`period`, `metric`, `value`, plus `repo` for per-repo metrics), and prints a terminal table.
- `report` builds charts from the metrics and writes `OUT/report.html` and `OUT/charts/<chart>.{png,svg}`.

### Modules (`src/gh_ledger/`)

| Module       | Responsibility                                                                                                                |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `auth.py`    | Token from `GITHUB_TOKEN`, falling back to `gh auth token`                                                                    |
| `client.py`  | httpx client for REST and GraphQL: rate-limit waits, retries, on-disk cache. Accepts an injected transport for tests.         |
| `fetch/`     | One module each for PRs, issues, reviews, comments and commits. Each yields raw records and owns its search-window splitting. |
| `model.py`   | Row dataclasses. This is the schema contract.                                                                                 |
| `store.py`   | CSV and manifest read/write, upsert by ID                                                                                     |
| `filters.py` | Path exclusion, per-file cap, AI-marker detection, trailer parsing                                                            |
| `metrics.py` | Tables to per-period metrics (pandas)                                                                                         |
| `events.py`  | Event YAML loading and validation                                                                                             |
| `report/`    | One function per chart (metrics DataFrame in, Plotly figure out), the HTML assembler, image export                            |
| `config.py`  | `ledger.toml` loading with built-in defaults                                                                                  |
| `cli.py`     | Typer commands                                                                                                                |

Dependencies: httpx, typer, pandas, plotly, pyyaml. PNG/SVG export needs kaleido, which needs a local Chrome. It is an optional extra (`gh-ledger[images]`). Without it, `report` writes the HTML and prints a message saying images were skipped.

## Data model

Keys are GitHub node IDs (or commit SHAs) so incremental fetches upsert. Timestamps are UTC ISO 8601. List-valued columns (`co_authors`) are `;`-separated.

| Table              | One row per                                         | Columns                                                                                                                                                                                          |
| ------------------ | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `repos.csv`        | repo touched                                        | `repo` (owner/name), `is_private`, `is_fork`                                                                                                                                                     |
| `prs.csv`          | authored PR                                         | `id`, `repo`, `number`, `url`, `title`, `state` (open/closed/merged), `created_at`, `merged_at`, `closed_at`, `additions`, `deletions`, `changed_files`, `files_truncated`, `text`, `co_authors` |
| `issues.csv`       | opened issue                                        | `id`, `repo`, `number`, `url`, `title`, `state`, `created_at`, `closed_at`, `text`                                                                                                               |
| `reviews.csv`      | submitted review                                    | `id`, `repo`, `pr_number`, `pr_url`, `pr_author`, `state` (approved/changes_requested/commented/dismissed), `submitted_at`, `text`                                                               |
| `comments.csv`     | written comment                                     | `id`, `repo`, `kind` (issue/pr_conversation/review_inline), `parent_number`, `parent_url`, `parent_author`, `created_at`, `text`                                                                 |
| `commits.csv`      | direct default-branch commit not attached to any PR | `sha`, `repo`, `authored_at`, `additions`, `deletions`, `files_truncated`, `text`, `co_authors`                                                                                                  |
| `file_changes.csv` | file changed in a PR or direct commit               | `source` (pr/commit), `source_id`, `repo`, `path`, `additions`, `deletions`, `change_type`, `date`                                                                                               |

Rules:

- PR `co_authors` is the union of `Co-Authored-By` trailers across the PR's commits.
- `file_changes.date` is `merged_at` for PRs and `authored_at` for commits. Only merged PRs contribute file rows to line metrics unless `count_unmerged_pr_lines` is set.
- `files_truncated` is true when GitHub's file-list cap cut the list short. PR and commit totals stay exact. The difference between totals and summed file rows is reported as `lines_unfilterable`.
- Comments and reviews on the user's own items are kept, with `parent_author`/`pr_author` set. Default metrics count reviews only on other people's PRs.
- `text` holds bodies and commit messages. With `--visibility all`, `DIR` contains private text. The README says so and the scaffolded `.gitignore` ignores `data/`.

## Fetching

| Table                       | Source                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PRs                         | GraphQL search `is:pr author:U created:<window>` plus a second search `merged:<window>`, merged by ID. File lists (with additions/deletions per file) and commit messages are fetched in the same query and paged where needed.                                                                                                                                                                                                                                                                                                                                                    |
| Issues                      | GraphQL search `is:issue author:U created:<window>`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Reviews and inline comments | GraphQL `user.contributionsCollection(from, to)`, one call chain per year of range, reading `pullRequestReviewContributions` with each review's state, body and comments                                                                                                                                                                                                                                                                                                                                                                                                           |
| Conversation comments       | GraphQL `user.issueComments`, ordered newest first, stopping once past `--since`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Direct commits              | REST commit search `author:U author-date:<window>` (and `author-email:E` for each `--author-email`). A batched GraphQL check (up to 50 (commit, repo) pairs per request) reads `associatedPullRequests` and drops attached commits. Merge commits are dropped, and a SHA found in several repositories (non-fork copies of a repository's history) is one commit: dropped if attached to a PR in any copy, otherwise credited to the oldest repository containing it. Remaining commits get one REST `GET /repos/{o}/{r}/commits/{sha}` call for file stats, paged past 300 files. |

Search windows start at one calendar month. A window whose `total_count` exceeds 1,000 is bisected until every piece is under the cap.

Visibility:

- `--visibility public` adds `is:public` to every search and drops non-public records from the other sources before anything is written.
- The token's scope is the hard limit on what is visible.
- For a user other than the token owner, GitHub reports private activity only as restricted contribution counts. These go in the manifest.

Caching:

| What                                               | Re-fetched       |
| -------------------------------------------------- | ---------------- |
| Search windows ending more than 30 days before now | never            |
| Search windows within the last 30 days             | every run        |
| Merged/closed PR details and commit file lists     | never            |
| Open PR details                                    | every run        |
| Everything                                         | with `--refresh` |

Responses are cached as they arrive, keyed by a hash of method, URL and body. An interrupted fetch resumes on the next run.

Rate limits and errors:

- Search calls are spaced to stay under 30 per minute.
- On primary limit exhaustion the client sleeps until `X-RateLimit-Reset` and shows a countdown.
- Secondary limits (403/429) honour `Retry-After`.
- 5xx responses retry three times with exponential backoff.
- A 404 on a repo is skipped with a warning and recorded in the manifest.
- A progress bar shows each stage.

Known limitation: commit search only matches commits whose email is linked to the account. `--author-email` covers unlinked addresses.

## Metrics

Computed per period (default month) by `summary`:

| Group         | Metrics                                                                                                                   |
| ------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Output        | `prs_opened`, `prs_merged`, `issues_opened`, `direct_commits`                                                             |
| Review        | `reviews_given`, `approvals`, `changes_requested`, `commented` (all on others' PRs), `comments`, `comments_on_others`     |
| Code          | `lines_added`, `lines_deleted` (filtered), `lines_added_raw`, `lines_deleted_raw`, `lines_unfilterable`                   |
| AI assistance | `ai_share_prs`, `ai_share_commits`, `ai_share_comments` (fraction of that period's items; empty when the period has none) |
| Breadth       | `repos_active`                                                                                                            |
| Per repo      | `lines_changed` by `repo` (feeds the repos chart)                                                                         |

## Filters

Default path exclusions, modelled on the path-based parts of GitHub Linguist's vendored and generated rules:

- Lockfiles: `uv.lock`, `poetry.lock`, `Pipfile.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `go.sum`, `composer.lock`, `Gemfile.lock`.
- Data and notebooks: `*.json`, `*.jsonl`, `*.csv`, `*.tsv`, `*.ipynb`, `*.svg`, `*.parquet`.
- Vendored and build output: `vendor/`, `node_modules/`, `dist/`, `build/`, `*.min.js`, `*.min.css`, `*.map`.

`.gitattributes` reading is out of scope for v1.

Per-file cap: a single file's additions and deletions in one PR or commit are each capped at `per_file_cap` (default 1000). `per_file_cap = false` disables it.

AI markers: a PR, commit, comment, review or issue is AI-assisted if any `[ai].patterns` regex matches its `text` or any `co_authors` entry (as `Co-Authored-By: <entry>`). Defaults:

```
(?i)co-authored-by:.*\b(claude|copilot|cursor|codex|gemini|devin)\b
(?i)generated with \[?claude code
(?i)posted by \[?claude code
```

## Report

`report.html` is self-contained (Plotly JS inlined, works offline). It contains a headline strip of totals over the whole range, then these charts in order:

1. `activity`: four small panels on a shared time axis (PRs merged, issues opened, reviews given, comments).
2. `lines`: filtered additions as positive bars, deletions as negative bars, raw total as a faint line.
3. `review_mix`: stacked approvals, changes requested and commented.
4. `ai_share`: lines for PR, commit and comment AI-assisted share.
5. `repos`: filtered lines changed stacked by top N repos (default 8), the rest grouped as "other".
6. `compare`: table of per-period averages for each metric before and after `compare_at`. Shown only when `compare_at` is set.

Each chart is also exported to `charts/<name>.png` and `charts/<name>.svg` at `image_size` (default 1200×600).

Redaction: with `--redact-private`, private repo names become `private repo N` (numbered by descending activity) in every chart, table, hover label and image.

### Events

Event files are YAML lists:

```yaml
- date: 2025-02-24
  label: Claude 3.7 Sonnet + Claude Code preview
  group: Claude
  url: https://www.anthropic.com/news/claude-3-7-sonnet
```

`date` and `label` are required. Events draw as dashed vertical lines on every time chart, coloured by `group`, with hover text. Labels are printed on the top chart only. Events outside the data range are ignored.

`examples/events/claude-models.yaml` lists Claude model releases. Each date is checked against Anthropic's announcement during implementation and linked with `url`.

### Customisation

- `ledger.toml` `[report]`: `period`, `charts`, `top_repos`, `compare_at`, `title`, `image_size`.
- Python: each chart function takes the metrics DataFrame and returns a Plotly figure, so notebook users can adjust or compose them.

## Configuration

`ledger.toml` is optional. Every key has a built-in default.

```toml
[filters]
extra_exclude = ["fixtures/**"]      # appended to defaults; `exclude = [...]` replaces them
per_file_cap = 1000                  # false disables
count_unmerged_pr_lines = false

[ai]
patterns = ['(?i)co-authored-by:.*\b(claude|copilot)\b']

[report]
period = "month"
title = "GitHub activity"
top_repos = 8
compare_at = "2025-02-24"
charts = ["activity", "lines", "review_mix", "ai_share", "repos", "compare"]
image_size = [1200, 600]
```

## Testing

- Unit tests: path exclusion, cap, AI-marker matching, trailer parsing, window bisection, period aggregation, event loading, redaction.
- Fetch tests: recorded GitHub responses served through `httpx.MockTransport`. CI never calls the live API.
- One `live`-marked smoke test fetches a one-week window for a public user. It is skipped without a token.
- Report tests: build HTML and SVG from a fixture `metrics.csv`, assert every configured chart is present, and assert no private repo name appears anywhere in the output when redaction is on.
- basedpyright, ruff and pre-commit come from the template.

The first implementation task is a throwaway probe against the live API. It confirms that `user.issueComments` and `contributionsCollection.pullRequestReviewContributions` return what this design assumes, for the token owner and for another user.

## Repo setup

- Local path `~/Developer/gh-ledger`, scaffolded from `Generality-Labs/python-project-template` as a library with a `gh-ledger` console script. MIT licence.
- Published as `MattFisher/gh-ledger`. Built locally first. The public repo is created only after the author confirms.
- PyPI trusted publishing comes from the template. The first release waits for the author's go-ahead.

## Out of scope for v1

- Reading `.gitattributes` for `linguist-generated` / `linguist-vendored`.
- GitHub Enterprise hosts.
- Discussions.
- Team or org aggregation across users.
- The PyPI release itself.
