from contextlib import nullcontext
from datetime import UTC, date, datetime

import pytest

from gh_ledger.auth import AuthError, get_token
from gh_ledger.client import GitHubClient
from gh_ledger.fetch import FetchOptions, run_fetch
from gh_ledger.store import load_tables

pytestmark = pytest.mark.live


def test_one_week_public_fetch(tmp_path):
    try:
        token = get_token()
    except AuthError:
        pytest.skip("no GitHub token")
    options = FetchOptions(
        user="jjallaire", since=date(2025, 3, 3), until=date(2025, 3, 9), visibility="public"
    )
    with GitHubClient(token) as client:
        manifest = run_fetch(
            client,
            options,
            tmp_path,
            now=datetime.now(UTC),
            stage=lambda _n: nullcontext(lambda _c: None),
        )
    assert manifest.user.lower() == "jjallaire"
    tables = load_tables(tmp_path)
    assert sum(len(frame) for name, frame in tables.items() if name != "repos") > 0
    assert not (tables["repos"]["is_private"] == "true").any()
