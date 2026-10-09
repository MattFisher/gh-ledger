### Fixed

- `fetch` no longer crashes when a cached open PR has vanished or a commit-search SHA is stale; such items are skipped and listed.
- GraphQL responses carrying errors are no longer cached, so re-running after authorising the token for an organisation recovers its private activity (use `--refresh` for spans cached before this fix).
- An interrupted `--visibility all` fetch can no longer be followed by a public fetch into the same directory.
- Unreadable config or events files give a one-line error.
