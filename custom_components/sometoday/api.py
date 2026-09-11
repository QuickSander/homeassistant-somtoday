"""REST API client for SomToday.

The client only depends on an injectable ``aiohttp.ClientSession`` and a
:class:`~custom_components.sometoday.auth.SomTodayAuthClient`, so every HTTP
call can be mocked in tests. This first slice implements the endpoints needed
by the config flow; the remaining data endpoints are added alongside the
coordinator and entities.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp

from .auth import SomTodayAuthClient
from .const import REQUEST_TIMEOUT
from .exceptions import (
    SomTodayApiError,
    SomTodayAuthError,
    SomTodayConnectionError,
    SomTodayRateLimitError,
)
from .models import Student, parse_students

_LOGGER = logging.getLogger(__name__)

STUDENTS_PATH = "/rest/v1/leerlingen"


def _release(response: Any) -> None:
    """Release an ``aiohttp`` response if it supports it."""
    release = getattr(response, "release", None)
    if release is not None:
        release()


class SomTodayApiClient:
    """Thin async wrapper around the SomToday REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: SomTodayAuthClient,
        base_url: str,
    ) -> None:
        """Initialise the client with an injectable session and auth client."""
        self._session = session
        self._auth = auth
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    @property
    def base_url(self) -> str:
        """Return the API base URL the client talks to."""
        return self._base_url

    async def async_get_students(self) -> list[Student]:
        """Return the students linked to the authenticated account."""
        payload = await self._request(
            "GET", STUDENTS_PATH, params={"additional": "pasfoto"}
        )
        try:
            return parse_students(payload)
        except (TypeError, ValueError) as err:
            raise SomTodayApiError(
                "The student list has an unexpected format"
            ) from err

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Perform an authenticated request and return the decoded JSON body.

        A ``401`` response triggers a single reactive token refresh and retry;
        other HTTP statuses are mapped to the shared exception hierarchy.
        """
        await self._auth.async_ensure_valid()
        response = await self._send(method, path, params=params)

        if response.status == 401:
            # Release the rejected response before refreshing and retrying.
            _release(response)
            # The access token may have been revoked mid-flight.
            _LOGGER.debug("SomToday returned 401, refreshing the access token")
            await self._auth.async_refresh()
            response = await self._send(method, path, params=params)

        return await self._async_decode(response, method=method, path=path)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> aiohttp.ClientResponse:
        """Perform the raw HTTP request, mapping network errors."""
        url = f"{self._base_url}{path}"
        headers = self._build_headers()
        try:
            if method.upper() == "GET":
                return await self._session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            return await self._session.post(
                url,
                params=params,
                headers=headers,
                timeout=self._timeout,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SomTodayConnectionError(f"Request to {url} failed: {err}") from err

    def _build_headers(self) -> dict[str, str]:
        """Return the headers required for an authenticated API request."""
        headers = {"Accept": "application/json"}
        if self._auth.tokens is not None:
            headers["Authorization"] = (
                f"{self._auth.tokens.token_type} {self._auth.tokens.access_token}"
            )
        return headers

    async def _async_decode(
        self,
        response: aiohttp.ClientResponse,
        *,
        method: str,
        path: str,
    ) -> Any:
        """Map the response status and decode its JSON body."""
        try:
            status = response.status
            if status in (401, 403):
                raise SomTodayAuthError(
                    f"SomToday rejected the {method} {path} request (HTTP {status})"
                )
            if status == 429:
                raise SomTodayRateLimitError(
                    f"SomToday rate limited the {method} {path} request (HTTP 429)"
                )
            if status >= 400:
                raise SomTodayApiError(
                    f"The {method} {path} request returned HTTP {status}"
                )

            try:
                return await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise SomTodayConnectionError(
                    f"Could not read the {method} {path} response: {err}"
                ) from err
            except ValueError as err:
                raise SomTodayApiError(
                    f"The {method} {path} response is not valid JSON"
                ) from err
        finally:
            _release(response)
