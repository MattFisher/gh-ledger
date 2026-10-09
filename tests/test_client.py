import json
import logging

import httpx
import pytest

from gh_ledger.cache import ResponseCache
from gh_ledger.client import (
    SEARCH_INTERVAL,
    GitHubClient,
    GitHubError,
    GraphQLError,
    NotFoundError,
)


def scripted(*responses):
    """A transport that replays responses in order and records requests."""
    queue = list(responses)
    seen = []

    def handler(request):
        seen.append(request)
        return queue.pop(0)

    return httpx.MockTransport(handler), seen


def make_client(transport, **kwargs):
    sleeps = []
    client = GitHubClient(
        "tok", transport=transport, sleep=sleeps.append, clock=lambda: 1000.0, **kwargs
    )
    return client, sleeps


def test_rest_sends_token_and_returns_json():
    transport, seen = scripted(httpx.Response(200, json={"ok": 1}))
    client, _ = make_client(transport)
    assert client.rest("/user", {"a": 1}) == {"ok": 1}
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert seen[0].url.params["a"] == "1"


def test_graphql_returns_data():
    transport, seen = scripted(httpx.Response(200, json={"data": {"viewer": {"login": "me"}}}))
    client, _ = make_client(transport)
    assert client.graphql("query Q { viewer { login } }") == {"viewer": {"login": "me"}}
    assert json.loads(seen[0].content)["query"].startswith("query Q")


def test_graphql_raises_on_fatal_errors():
    body = {"data": None, "errors": [{"type": "INTERNAL", "message": "boom"}]}
    transport, _ = scripted(httpx.Response(200, json=body))
    client, _ = make_client(transport)
    with pytest.raises(GraphQLError, match="boom"):
        client.graphql("query Q { x }")


def test_graphql_keeps_data_alongside_sso_forbidden_errors(caplog):
    body = {
        "data": {"user": {"login": "me"}},
        "errors": [{"type": "FORBIDDEN", "message": "SAML enforcement"}],
    }
    transport, _ = scripted(httpx.Response(200, json=body))
    client, _ = make_client(transport)
    with caplog.at_level(logging.WARNING):
        assert client.graphql("query Q { x }") == {"user": {"login": "me"}}
    assert "SAML" in caplog.text


def test_cache_hit_skips_network(tmp_path):
    transport, seen = scripted(httpx.Response(200, json={"n": 1}))
    client, _ = make_client(transport, cache=ResponseCache(tmp_path))
    assert client.rest("/x") == {"n": 1}
    assert client.rest("/x") == {"n": 1}
    assert len(seen) == 1


def test_uncacheable_requests_are_neither_read_nor_written(tmp_path):
    transport, _seen = scripted(
        httpx.Response(200, json={"n": 1}), httpx.Response(200, json={"n": 2})
    )
    client, _ = make_client(transport, cache=ResponseCache(tmp_path))
    assert client.rest("/x", cacheable=False) == {"n": 1}
    assert client.rest("/x", cacheable=False) == {"n": 2}
    assert not any(tmp_path.rglob("*.json"))


def test_refresh_ignores_cache_but_rewrites_it(tmp_path):
    cache = ResponseCache(tmp_path)
    first, _ = scripted(httpx.Response(200, json={"n": 1}))
    make_client(first, cache=cache)[0].rest("/x")
    second, seen = scripted(httpx.Response(200, json={"n": 2}))
    assert make_client(second, cache=cache, refresh=True)[0].rest("/x") == {"n": 2}
    third, _ = scripted()
    assert make_client(third, cache=cache)[0].rest("/x") == {"n": 2}
    assert len(seen) == 1


def test_primary_rate_limit_waits_until_reset():
    limited = httpx.Response(
        403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"}, text="limit"
    )
    transport, _ = scripted(limited, httpx.Response(200, json={"ok": 1}))
    waits = []
    client, _ = make_client(transport, on_wait=lambda seconds, reason: waits.append(seconds))
    assert client.rest("/x") == {"ok": 1}
    assert waits == [31.0]


def test_secondary_rate_limit_honours_retry_after():
    transport, _ = scripted(
        httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"ok": 1})
    )
    client, sleeps = make_client(transport)
    assert client.rest("/x") == {"ok": 1}
    assert sleeps == [7.0]


def test_graphql_rate_limited_error_waits_until_reset():
    limited = httpx.Response(
        200,
        headers={"X-RateLimit-Reset": "1010"},
        json={"data": None, "errors": [{"type": "RATE_LIMITED", "message": "slow down"}]},
    )
    transport, _ = scripted(limited, httpx.Response(200, json={"data": {"ok": 1}}))
    client, sleeps = make_client(transport)
    assert client.graphql("query Q { x }") == {"ok": 1}
    assert sleeps == [11.0]


def test_server_errors_retry_with_backoff_then_succeed():
    transport, _ = scripted(
        httpx.Response(502), httpx.Response(503), httpx.Response(200, json={"ok": 1})
    )
    client, sleeps = make_client(transport)
    assert client.rest("/x") == {"ok": 1}
    assert sleeps == [1.0, 2.0]


def test_server_errors_give_up_after_three_retries():
    transport, _ = scripted(*[httpx.Response(500) for _ in range(4)])
    client, sleeps = make_client(transport)
    with pytest.raises(GitHubError, match="3 retries"):
        client.rest("/x")
    assert sleeps == [1.0, 2.0, 4.0]


def test_404_raises_not_found():
    transport, _ = scripted(httpx.Response(404, json={"message": "Not Found"}))
    client, _ = make_client(transport)
    with pytest.raises(NotFoundError):
        client.rest("/repos/octo/gone/commits/abc")


def test_http_errors_carry_their_status():
    transport, _ = scripted(httpx.Response(422, json={"message": "No commit found"}))
    client, _ = make_client(transport)
    with pytest.raises(GitHubError, match="422") as info:
        client.rest("/repos/octo/app/commits/abc")
    assert info.value.status == 422


def test_graphql_responses_with_errors_are_not_cached(tmp_path):
    body = {
        "data": {"node": None},
        "errors": [{"type": "FORBIDDEN", "message": "SAML enforcement"}],
    }
    transport, seen = scripted(httpx.Response(200, json=body), httpx.Response(200, json=body))
    client, _ = make_client(transport, cache=ResponseCache(tmp_path))
    assert client.graphql("query Q { x }") == {"node": None}
    assert client.graphql("query Q { x }") == {"node": None}
    assert len(seen) == 2
    assert not any(tmp_path.rglob("*.json"))


def test_plain_403_is_an_error_not_a_wait():
    transport, _ = scripted(httpx.Response(403, text="Resource not accessible"))
    client, sleeps = make_client(transport)
    with pytest.raises(GitHubError, match="403"):
        client.rest("/x")
    assert sleeps == []


def test_search_calls_are_spaced():
    transport, _ = scripted(httpx.Response(200, json={}), httpx.Response(200, json={}))
    client, sleeps = make_client(transport)
    client.rest("/search/commits", search=True)
    client.rest("/search/commits", search=True)
    assert sleeps == [pytest.approx(SEARCH_INTERVAL)]
