from github_fakes import empty_github
from typer.testing import CliRunner

from gh_ledger import cli


def test_fetch_command_writes_tables(tmp_path, monkeypatch):
    fake = empty_github()
    monkeypatch.setattr(cli, "make_client", lambda data, *, refresh, on_wait: fake.client())
    args = [
        "fetch",
        "--user",
        "octocat",
        "--since",
        "2024-01-01",
        "--until",
        "2024-01-31",
        "--data",
        str(tmp_path),
    ]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "file_changes.csv").exists()


def test_since_after_until_is_an_error(tmp_path):
    args = [
        "fetch",
        "--user",
        "octocat",
        "--since",
        "2024-02-01",
        "--until",
        "2024-01-01",
        "--data",
        str(tmp_path),
    ]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 1
    assert "after" in result.output


def test_auth_failure_is_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def no_token(data, *, refresh, on_wait):
        raise cli.AuthError("No GitHub token: set GITHUB_TOKEN or run `gh auth login`.")

    monkeypatch.setattr(cli, "make_client", no_token)
    args = ["fetch", "--user", "octocat", "--since", "2024-01-01", "--data", str(tmp_path)]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 1
    assert "GITHUB_TOKEN" in result.output
    assert "Traceback" not in result.output


def test_corrupt_table_is_a_clean_error(tmp_path, monkeypatch):
    fake = empty_github()
    monkeypatch.setattr(cli, "make_client", lambda data, *, refresh, on_wait: fake.client())
    (tmp_path / "prs.csv").write_text("not,the,right,header\n1,2,3,4\n")
    args = ["fetch", "--user", "octocat", "--since", "2024-01-01", "--until", "2024-01-31"]
    result = CliRunner().invoke(cli.app, [*args, "--data", str(tmp_path)])
    assert result.exit_code == 1
    assert "prs.csv" in result.output
    assert "Traceback" not in result.output
    assert isinstance(result.exception, SystemExit)
