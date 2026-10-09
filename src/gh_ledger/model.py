"""Row types for the CSV tables.

These dataclasses are the schema contract between `fetch` and the later stages:
column names and order come from the field order here.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


@dataclass(frozen=True)
class RepoRow:
    repo: str
    is_private: bool
    is_fork: bool


@dataclass(frozen=True)
class PrRow:
    id: str
    repo: str
    number: int
    url: str
    title: str
    state: str  # open | closed | merged
    created_at: str
    merged_at: str | None
    closed_at: str | None
    additions: int
    deletions: int
    changed_files: int
    files_truncated: bool
    text: str  # body, then every commit message
    co_authors: tuple[str, ...]


@dataclass(frozen=True)
class IssueRow:
    id: str
    repo: str
    number: int
    url: str
    title: str
    state: str  # open | closed
    created_at: str
    closed_at: str | None
    text: str


@dataclass(frozen=True)
class ReviewRow:
    id: str
    repo: str
    pr_number: int
    pr_url: str
    pr_author: str  # empty for deleted accounts
    state: str  # approved | changes_requested | commented | dismissed
    submitted_at: str
    text: str


@dataclass(frozen=True)
class CommentRow:
    id: str
    repo: str
    kind: str  # issue | pr_conversation | review_inline
    parent_number: int
    parent_url: str
    parent_author: str  # empty for deleted accounts
    created_at: str
    text: str


@dataclass(frozen=True)
class CommitRow:
    sha: str
    repo: str
    authored_at: str
    additions: int
    deletions: int
    files_truncated: bool
    text: str
    co_authors: tuple[str, ...]


@dataclass(frozen=True)
class FileChangeRow:
    source: str  # pr | commit
    source_id: str  # PR node ID or commit SHA
    repo: str
    path: str
    additions: int
    deletions: int
    change_type: str
    date: str  # merged_at for merged PRs, created_at for unmerged PRs, authored_at for commits


@dataclass(frozen=True)
class TableSpec:
    name: str
    row_type: type[DataclassInstance]
    key: tuple[str, ...]


TABLES: tuple[TableSpec, ...] = (
    TableSpec("repos", RepoRow, ("repo",)),
    TableSpec("prs", PrRow, ("id",)),
    TableSpec("issues", IssueRow, ("id",)),
    TableSpec("reviews", ReviewRow, ("id",)),
    TableSpec("comments", CommentRow, ("id",)),
    TableSpec("commits", CommitRow, ("sha",)),
    # Keyed by group: re-fetching a PR replaces its whole file list.
    TableSpec("file_changes", FileChangeRow, ("source", "source_id")),
)


@dataclass
class FetchResult:
    """Everything one fetch run collected, before it is written."""

    repos: list[RepoRow] = field(default_factory=list[RepoRow])
    prs: list[PrRow] = field(default_factory=list[PrRow])
    issues: list[IssueRow] = field(default_factory=list[IssueRow])
    reviews: list[ReviewRow] = field(default_factory=list[ReviewRow])
    comments: list[CommentRow] = field(default_factory=list[CommentRow])
    commits: list[CommitRow] = field(default_factory=list[CommitRow])
    file_changes: list[FileChangeRow] = field(default_factory=list[FileChangeRow])
    dropped_pr_commits: int = 0
    skipped_repos: list[str] = field(default_factory=list[str])
    restricted_contributions: int = 0

    def extend(self, other: FetchResult) -> None:
        self.repos.extend(other.repos)
        self.prs.extend(other.prs)
        self.issues.extend(other.issues)
        self.reviews.extend(other.reviews)
        self.comments.extend(other.comments)
        self.commits.extend(other.commits)
        self.file_changes.extend(other.file_changes)
        self.dropped_pr_commits += other.dropped_pr_commits
        self.skipped_repos.extend(other.skipped_repos)
        self.restricted_contributions += other.restricted_contributions

    def rows(self, table: str) -> list[DataclassInstance]:
        return cast("list[DataclassInstance]", getattr(self, table))


@dataclass
class Manifest:
    user: str
    since: str  # YYYY-MM-DD
    until: str  # YYYY-MM-DD
    visibility: str  # public | all
    fetched_at: str
    tool_version: str
    author_emails: list[str] = field(default_factory=list[str])
    # commits dropped for belonging to a PR (attached, or a merge commit) in the latest run,
    # not cumulative
    dropped_pr_commits: int = 0
    skipped_repos: list[str] = field(default_factory=list[str])
    restricted_contributions: int = (
        0  # counts from the most recent fetch run's range, not cumulative
    )


def columns(row_type: type[DataclassInstance]) -> list[str]:
    return [f.name for f in dataclasses.fields(row_type)]


def to_csv_row(row: DataclassInstance) -> dict[str, str]:
    return {f.name: _format(getattr(row, f.name)) for f in dataclasses.fields(row)}


def _format(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        return ";".join(str(item) for item in cast("tuple[object, ...]", value))
    return str(value)
