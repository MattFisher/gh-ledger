"""HTTP client for GitHub's REST and GraphQL APIs: rate limits, retries and caching."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from gh_ledger import __version__
from gh_ledger.cache import ResponseCache

API_URL = "https://api.github.com"
GRAPHQL_PATH = "/graphql"
SEARCH_INTERVAL = 2.1  # seconds between search calls keeps us under 30 per minute
MAX_SERVER_RETRIES = 3
SECONDARY_LIMIT_WAIT = 60.0
# SSO-protected orgs and deleted repos answer with these alongside usable data.
TOLERATED_GRAPHQL_ERRORS = frozenset({"NOT_FOUND", "FORBIDDEN"})

log = logging.getLogger(__name__)

Params = Mapping[str, str | int]
Waiter = Callable[[float, str], None]


class GitHubError(Exception):
    """A request failed in a way that retrying will not fix."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NotFoundError(GitHubError):
    """GitHub answered 404."""


class GraphQLError(GitHubError):
    """A GraphQL response carried errors that make its data unusable."""


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        cache: ResponseCache | None = None,
        refresh: bool = False,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        on_wait: Waiter | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=API_URL,
            transport=transport,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"gh-ledger/{__version__}",
            },
        )
        self._cache = cache
        self._refresh = refresh
        self._sleep = sleep
        self._clock = clock
        self._on_wait: Waiter = on_wait or (lambda seconds, _reason: sleep(seconds))
        self._last_search: float | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def rest(
        self,
        path: str,
        params: Params | None = None,
        *,
        search: bool = False,
        cacheable: bool = True,
    ) -> Any:
        return self._request("GET", path, params, None, search=search, cacheable=cacheable)

    def graphql(
        self,
        query: str,
        variables: Mapping[str, Any] | None = None,
        *,
        search: bool = False,
        cacheable: bool = True,
    ) -> dict[str, Any]:
        body = {"query": query, "variables": dict(variables or {})}
        response = self._request(
            "POST", GRAPHQL_PATH, None, body, search=search, cacheable=cacheable
        )
        for error in response.get("errors") or []:  # pyright: ignore[reportUnknownVariableType]
            log.warning("GitHub GraphQL: %s", error.get("message"))  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
        return response["data"]

    def _request(
        self,
        method: str,
        path: str,
        params: Params | None,
        body: dict[str, Any] | None,
        *,
        search: bool,
        cacheable: bool,
    ) -> Any:
        url = str(self._http.build_request(method, path, params=params).url)
        payload = json.dumps(body, sort_keys=True) if body is not None else ""
        key = ResponseCache.key(method, url, payload)
        cache = self._cache if cacheable else None
        if cache is not None and not self._refresh:
            hit = cache.get(key)
            if hit is not None:
                return hit
        result = self._send(method, path, params, body, search=search)
        if cache is not None:
            cache.put(key, result)
        return result

    def _send(
        self,
        method: str,
        path: str,
        params: Params | None,
        body: dict[str, Any] | None,
        *,
        search: bool,
    ) -> Any:
        server_failures = 0
        while True:
            if search:
                self._space_search()
            try:
                response = self._http.request(method, path, params=params, json=body)
            except httpx.TransportError as exc:
                failure = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 500:
                    wait = self._limit_wait(response, path)
                    if wait is not None:
                        self._on_wait(wait, "GitHub rate limit")
                        continue
                    return self._decode(response, path)
                failure = f"HTTP {response.status_code}"
            if server_failures >= MAX_SERVER_RETRIES:
                raise GitHubError(
                    f"{method} {path} failed after {MAX_SERVER_RETRIES} retries: {failure}"
                )
            self._sleep(2.0**server_failures)
            server_failures += 1

    def _limit_wait(self, response: httpx.Response, path: str) -> float | None:
        """Seconds to wait if this response is a rate limit, else None."""
        if response.status_code in (403, 429):
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                return float(retry_after)
            if response.headers.get("X-RateLimit-Remaining") == "0":
                return self._until_reset(response)
            if "secondary rate limit" in response.text.lower():
                return SECONDARY_LIMIT_WAIT
            return None
        if path == GRAPHQL_PATH and response.status_code == 200:
            errors = response.json().get("errors") or []  # pyright: ignore[reportUnknownVariableType]
            if any(error.get("type") == "RATE_LIMITED" for error in errors):  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType,reportUnknownVariableType]
                return self._until_reset(response)
        return None

    def _until_reset(self, response: httpx.Response) -> float:
        reset = float(response.headers.get("X-RateLimit-Reset", "0"))
        return max(reset - self._clock(), 0.0) + 1.0

    def _decode(self, response: httpx.Response, path: str) -> Any:
        if response.status_code == 404:
            raise NotFoundError(f"404 for {path}", 404)
        if response.status_code >= 400:
            raise GitHubError(
                f"HTTP {response.status_code} for {path}: {response.text[:300]}",
                response.status_code,
            )
        data = response.json()
        if path == GRAPHQL_PATH:
            errors = data.get("errors") or []  # pyright: ignore[reportUnknownVariableType]
            fatal = [e for e in errors if e.get("type") not in TOLERATED_GRAPHQL_ERRORS]  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]
            if data.get("data") is None or fatal:
                messages = "; ".join(str(e.get("message")) for e in (fatal or errors))  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType,reportUnknownVariableType]
                raise GraphQLError(messages or "GraphQL response had no data")
        return data

    def _space_search(self) -> None:
        if self._last_search is not None:
            gap = self._clock() - self._last_search
            if gap < SEARCH_INTERVAL:
                self._sleep(SEARCH_INTERVAL - gap)
        self._last_search = self._clock()
