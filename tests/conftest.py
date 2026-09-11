"""Shared fixtures and fakes for the SomToday test suite.

The SomToday API is always mocked. ``FakeSession`` implements the small subset
of the ``aiohttp.ClientSession`` interface used by the authentication client,
so no real HTTP request is ever made.
"""

from __future__ import annotations

import sys
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import aiohttp
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeResponse:
    """Minimal stand-in for an ``aiohttp.ClientResponse``."""

    def __init__(
        self,
        status: int = 200,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        json_data: Any = None,
        text: str = "",
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self.cookies = dict(cookies or {})
        self._json = json_data
        self._text = text
        self.release_count = 0

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        if self._json is None:
            raise ValueError("No JSON payload scripted")
        return self._json

    async def text(self) -> str:
        return self._text

    def release(self) -> None:
        """Record that the response was released back to the pool."""
        self.release_count += 1

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientError(f"HTTP {self.status}")


class FakeSession:
    """Scripted session returning queued responses (or raising queued errors)."""

    def __init__(self, responses: Iterable[Any]) -> None:
        self._responses: deque[Any] = deque(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._next("GET", url, kwargs)

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._next("POST", url, kwargs)

    def _next(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"No scripted response left for {method} {url}")
        response = self._responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.fixture
def fake_response() -> Any:
    """Expose the :class:`FakeResponse` class to the tests."""
    return FakeResponse


@pytest.fixture
def fake_session() -> Any:
    """Return a factory that builds a :class:`FakeSession` from responses."""

    def _factory(responses: Iterable[Any]) -> FakeSession:
        return FakeSession(responses)

    return _factory
