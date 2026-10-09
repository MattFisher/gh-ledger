"""Builders for model rows with sensible defaults, for store and metrics tests."""

from gh_ledger.model import (
    CommentRow,
    CommitRow,
    FileChangeRow,
    IssueRow,
    Manifest,
    PrRow,
    RepoRow,
    ReviewRow,
)


def repo(name="octo/app", *, private=False, fork=False):
    return RepoRow(repo=name, is_private=private, is_fork=fork)


def pr(
    node_id="PR_1",
    *,
    repo="octo/app",
    state="merged",
    created_at="2024-01-10T10:00:00Z",
    merged_at="2024-01-11T10:00:00Z",
    additions=10,
    deletions=2,
    files_truncated=False,
    title="A PR",
    text="",
    co_authors=(),
):
    return PrRow(
        id=node_id,
        repo=repo,
        number=1,
        url=f"https://github.com/{repo}/pull/1",
        title=title,
        state=state,
        created_at=created_at,
        merged_at=merged_at if state == "merged" else None,
        closed_at=merged_at if state != "open" else None,
        additions=additions,
        deletions=deletions,
        changed_files=1,
        files_truncated=files_truncated,
        text=text,
        co_authors=tuple(co_authors),
    )


def file_change(
    source_id="PR_1",
    path="src/app.py",
    *,
    source="pr",
    repo="octo/app",
    additions=10,
    deletions=2,
    date="2024-01-11T10:00:00Z",
):
    return FileChangeRow(
        source=source,
        source_id=source_id,
        repo=repo,
        path=path,
        additions=additions,
        deletions=deletions,
        change_type="modified",
        date=date,
    )


def commit(
    sha="abc123",
    *,
    repo="octo/app",
    authored_at="2024-01-12T10:00:00Z",
    additions=5,
    deletions=1,
    files_truncated=False,
    text="fix: thing",
    co_authors=(),
):
    return CommitRow(
        sha=sha,
        repo=repo,
        authored_at=authored_at,
        additions=additions,
        deletions=deletions,
        files_truncated=files_truncated,
        text=text,
        co_authors=tuple(co_authors),
    )


def review(
    node_id="R_1",
    *,
    repo="octo/app",
    pr_author="someone",
    state="approved",
    submitted_at="2024-01-15T10:00:00Z",
    text="",
):
    return ReviewRow(
        id=node_id,
        repo=repo,
        pr_number=7,
        pr_url=f"https://github.com/{repo}/pull/7",
        pr_author=pr_author,
        state=state,
        submitted_at=submitted_at,
        text=text,
    )


def comment(
    node_id="C_1",
    *,
    repo="octo/app",
    kind="issue",
    parent_author="someone",
    created_at="2024-01-15T10:00:00Z",
    text="",
):
    return CommentRow(
        id=node_id,
        repo=repo,
        kind=kind,
        parent_number=3,
        parent_url=f"https://github.com/{repo}/issues/3",
        parent_author=parent_author,
        created_at=created_at,
        text=text,
    )


def issue(node_id="I_1", *, repo="octo/app", created_at="2024-01-05T10:00:00Z", text=""):
    return IssueRow(
        id=node_id,
        repo=repo,
        number=3,
        url=f"https://github.com/{repo}/issues/3",
        title="An issue",
        state="open",
        created_at=created_at,
        closed_at=None,
        text=text,
    )


def manifest(user="octocat", since="2024-01-01", until="2024-03-31", visibility="all"):
    return Manifest(
        user=user,
        since=since,
        until=until,
        visibility=visibility,
        fetched_at="2024-04-01T00:00:00Z",
        tool_version="0.1.0",
    )
