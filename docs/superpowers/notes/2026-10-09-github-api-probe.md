# GitHub API probe — 2026-10-09

Users probed: MattFisher, jjallaire. Script: throwaway, not committed.

## issueComments

- Ordering: `UPDATED_AT` DESC holds for both users ("updatedAt non-increasing: True" over 300 nodes each). MattFisher totalCount 921 (newest 2026-10-09, oldest fetched 2026-08-21); jjallaire totalCount 11437 (newest 2026-09-27, oldest fetched 2026-02-22).
- PR vs issue comments, parent fields: PR conversation comments carry a non-null `pullRequest` (MattFisher 250 on PRs / 50 on issues; jjallaire 208 / 92). For PR comments `issue.url` and `pullRequest.url` are both `.../pull/N`. No null `issue.author` seen. Edited comments (createdAt != updatedAt): 33 of 300 (MattFisher), 4 of 300 (jjallaire). Private-repo comments: 10 (MattFisher, token owner), 0 (jjallaire). Forks: 14 / 0.
- Visibility for another user: works; jjallaire returned nodes, public repos only (0 private).

## contributionsCollection reviews

- States seen: MattFisher APPROVED 200, COMMENTED 75, CHANGES_REQUESTED 16, DISMISSED 4. jjallaire APPROVED 390, COMMENTED 39, CHANGES_REQUESTED 2.
- Own-PR reviews included: yes. MattFisher 39 of 295; jjallaire 1 of 431.
- Inline comments: present. Total 54 (MattFisher, 112 reviews with body), 45 (jjallaire, 15 with body). No review had >100 inline comments.
- Restricted counts (other user): jjallaire restrictedContributionsCount 0, hasAnyRestricted False. (MattFisher: 905, True; private 0 in review nodes, so private-repo reviews appear only as restricted counts.)
- Coverage vs search reviewed-by: others' distinct PRs from contributions vs search upper bound: MattFisher 256 vs 277; jjallaire 430 vs 441. Contributions are slightly below the search count (about 8% and 2.5%), expected because search `updated:>=` also matches PRs reviewed earlier and updated later.
- Span limit: 400-day span rejected with GraphQL validation error "The total time spanned by 'from' and 'to' must not exceed 1 year". The script printed "accepted: True" because of a script bug (see below), but the error was shown in the output for both users, so the 1-year limit holds.

## Search and commit shapes

- Time qualifiers with +00:00: with-time count 178 equals date-only count 178 (window = last full month, MattFisher).
- PR search cost for 50 PRs with files and commits: rateLimit cost 1 (remaining 4959); issueCount 178. files.totalCount equals changedFiles in the 5 sampled PRs.
- Commit search item fields: keys author, comments_url, commit, committer, html_url, node_id, parents, repository, score, sha, url. `repository.private` and `repository.fork` both present. Author date format is offset-local, e.g. `2026-09-21T12:44:33.000+10:00`. total_count 488 for the window.
- Association check: 20 of 20 sampled commits resolved via the batched `associatedPullRequests` query had at least one PR.
- Single-commit file paging: commit 1441cf7 has 5 files (stats total 121, +89/-32); `per_page=1&page=2` returned 1 file, so paging works.

## Consequences for the plan

- none (all assumptions held; no Stop rows fired).
- Note for Task 5/10: commit author dates come with local offsets, not UTC; normalise before bucketing.
- Probe script bug (not a plan change): "400-day span accepted" check used `bool(data)`, which is truthy even when the GraphQL error nulls the field; fixed to test `contributionsCollection` non-null.
