# gh-ledger

Measure one GitHub user's activity over time and chart it

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
