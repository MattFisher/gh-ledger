"""A fake GitHub API for fetch tests, plus factories for its response shapes."""

import json
import re

import httpx

from gh_ledger.client import GitHubClient


class FakeGitHub:
    """Routes GraphQL requests by operation name and REST requests by path.

    GraphQL handlers receive the request body ({"query", "variables"}) and return `data`.
    REST handlers receive the httpx.Request and return JSON or an httpx.Response.
    """

    def __init__(self):
        self.graphql = {}
        self.rest = {}
        self.calls = []
        self.bodies = []

    def handle(self, request):
        if request.url.path == "/graphql":
            body = json.loads(request.content)
            name = re.search(r"query (\w+)", body["query"]).group(1)
            self.calls.append(name)
            self.bodies.append(body)
            return httpx.Response(200, json={"data": self.graphql[name](body)})
        self.calls.append(request.url.path)
        result = self.rest[request.url.path](request)
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)

    def client(self):
        return GitHubClient(
            "test-token", transport=httpx.MockTransport(self.handle), sleep=lambda _s: None
        )

    def variables(self, name):
        return [b["variables"] for b in self.bodies if f"query {name}" in b["query"]]


def noop(_count):
    return None


def repo(name="octo/app", *, private=False, fork=False):
    return {"nameWithOwner": name, "isPrivate": private, "isFork": fork}


def connection(nodes, end_cursor=None):
    return {
        "pageInfo": {"hasNextPage": end_cursor is not None, "endCursor": end_cursor},
        "nodes": list(nodes),
    }


def search_result(nodes, *, total=None, end_cursor=None):
    return {
        "search": {
            "issueCount": len(nodes) if total is None else total,
            **connection(nodes, end_cursor),
        }
    }


def pr_node(
    node_id="PR_1",
    *,
    number=1,
    state="MERGED",
    created="2024-01-10T10:00:00Z",
    merged="2024-01-11T10:00:00Z",
    files=(("src/app.py", 10, 2),),
    messages=("feat: add app",),
    body="Adds the app.",
    changed_files=None,
    files_cursor=None,
    commits_cursor=None,
    repository=None,
):
    file_nodes = [
        {"path": p, "additions": a, "deletions": d, "changeType": "MODIFIED"} for p, a, d in files
    ]
    return {
        "id": node_id,
        "number": number,
        "url": f"https://github.com/octo/app/pull/{number}",
        "title": f"PR {number}",
        "state": state,
        "body": body,
        "createdAt": created,
        "mergedAt": merged if state == "MERGED" else None,
        "closedAt": merged if state in ("MERGED", "CLOSED") else None,
        "additions": sum(a for _, a, _ in files),
        "deletions": sum(d for _, _, d in files),
        "changedFiles": len(files) if changed_files is None else changed_files,
        "repository": repository or repo(),
        "files": connection(file_nodes, files_cursor),
        "commits": connection([{"commit": {"message": m}} for m in messages], commits_cursor),
    }


def issue_node(
    node_id="I_1",
    *,
    number=3,
    state="OPEN",
    created="2024-01-05T10:00:00Z",
    closed=None,
    body="It broke.",
    repository=None,
):
    return {
        "id": node_id,
        "number": number,
        "url": f"https://github.com/octo/app/issues/{number}",
        "title": f"Issue {number}",
        "state": state,
        "body": body,
        "createdAt": created,
        "closedAt": closed,
        "repository": repository or repo(),
    }


def review_contribution(
    review_id="PRR_1",
    *,
    state="APPROVED",
    body="",
    submitted="2024-01-15T10:00:00Z",
    pr_number=7,
    pr_author="alice",
    comments=(),
    comments_cursor=None,
    repository=None,
):
    pr_url = f"https://github.com/octo/app/pull/{pr_number}"
    return {
        "pullRequestReview": {
            "id": review_id,
            "state": state,
            "body": body,
            "submittedAt": submitted,
            "comments": connection(
                [
                    {"id": cid, "body": text, "createdAt": created, "url": f"{pr_url}#{cid}"}
                    for cid, text, created in comments
                ],
                comments_cursor,
            ),
        },
        "pullRequest": {
            "number": pr_number,
            "url": pr_url,
            "author": {"login": pr_author} if pr_author else None,
        },
        "repository": repository or repo(),
    }


def contributions(nodes, *, restricted=0, end_cursor=None):
    return {
        "user": {
            "contributionsCollection": {
                "restrictedContributionsCount": restricted,
                "pullRequestReviewContributions": connection(nodes, end_cursor),
            }
        }
    }


def issue_comment(
    comment_id="IC_1",
    *,
    created="2024-01-15T10:00:00Z",
    updated=None,
    on_pr=False,
    number=3,
    parent_author="alice",
    body="Thanks!",
    repository=None,
):
    kind = "pull" if on_pr else "issues"
    parent = {
        "number": number,
        "url": f"https://github.com/octo/app/{kind}/{number}",
        "author": {"login": parent_author} if parent_author else None,
    }
    return {
        "id": comment_id,
        "body": body,
        "createdAt": created,
        "updatedAt": updated or created,
        "issue": parent,
        "pullRequest": parent if on_pr else None,
        "repository": repository or repo(),
    }


def issue_comments(nodes, end_cursor=None):
    return {"user": {"issueComments": connection(nodes, end_cursor)}}


def commit_item(
    sha,
    date="2024-01-12T10:00:00.000+00:00",
    *,
    repo_name="octo/app",
    private=False,
    message="fix: thing",
):
    return {
        "sha": sha,
        "commit": {"author": {"date": date}, "message": message},
        "repository": {"full_name": repo_name, "private": private, "fork": False},
    }


def commit_detail(sha, files, *, stats=None):
    """files: (filename, additions, deletions) tuples. stats defaults to their sums."""
    additions = sum(a for _, a, _ in files)
    deletions = sum(d for _, _, d in files)
    stats = stats or {"additions": additions, "deletions": deletions}
    return {
        "sha": sha,
        "stats": {**stats, "total": stats["additions"] + stats["deletions"]},
        "files": [
            {"filename": f, "additions": a, "deletions": d, "status": "modified"}
            for f, a, d in files
        ],
    }


def associations(attached=(), missing_repos=()):
    """Answer a CommitAssociations query: SHAs in `attached` belong to a PR."""

    def handle(body):
        data = {}
        pattern = (
            r'(c\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\) \{ object\(oid: "(\w+)"\)'
        )
        for alias, owner, name, sha in re.findall(pattern, body["query"]):
            if f"{owner}/{name}" in missing_repos:
                data[alias] = None
            else:
                count = 1 if sha in attached else 0
                data[alias] = {"object": {"associatedPullRequests": {"totalCount": count}}}
        return data

    return handle


def empty_github():
    """A FakeGitHub answering every fetch query with no results."""
    fake = FakeGitHub()
    fake.graphql["UserCheck"] = lambda b: {"user": {"login": b["variables"]["login"].lower()}}
    fake.graphql["PrSearch"] = lambda _b: search_result([])
    fake.graphql["IssueSearch"] = lambda _b: search_result([])
    fake.graphql["ReviewContributions"] = lambda _b: contributions([])
    fake.graphql["IssueComments"] = lambda _b: issue_comments([])
    fake.rest["/search/commits"] = lambda _r: {"total_count": 0, "items": []}
    return fake
