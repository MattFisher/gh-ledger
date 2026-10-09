import subprocess

import pytest

from gh_ledger.auth import AuthError, get_token


def fake_run(stdout="", returncode=0):
    def run(args, **_kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return run


def test_env_token_wins():
    assert get_token({"GITHUB_TOKEN": " env-token\n"}, run=fake_run("gh-token")) == "env-token"


def test_falls_back_to_gh_cli():
    assert get_token({}, run=fake_run("gh-token\n")) == "gh-token"


def test_error_when_gh_fails():
    with pytest.raises(AuthError, match="GITHUB_TOKEN"):
        get_token({}, run=fake_run("", returncode=1))


def test_error_when_gh_missing():
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("gh")

    with pytest.raises(AuthError, match="gh auth login"):
        get_token({}, run=missing)
