"""REST API client for SomToday.

The client only depends on an injectable ``aiohttp.ClientSession`` and a
:class:`~custom_components.sometoday.auth.SomTodayAuth`, so every HTTP call can
be mocked in tests. This slice implements the endpoints needed by the config
flow; the remaining data endpoints are added alongside the coordinator and
entities.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import aiohttp

from .auth import SomTodayAuth
from .const import REQUEST_TIMEOUT
from .exceptions import (
    SomTodayApiError,
    SomTodayConnectionError,
    SomtodayInvalidAuth,
    SomTodayRateLimitError,
)
from .models import Account, Student, parse_account, parse_students

_LOGGER = logging.getLogger(__name__)

ACCOUNT_PATH = "/rest/v1/account/me"
STUDENTS_PATH = "/rest/v1/leerlingen"
APPOINTMENTS_PATH = "/rest/v1/afspraken"

# SomToday paginates list endpoints with ``Range: items=<start>-<end>`` and
# answers ``206 Partial Content`` plus a ``Content-Range`` header. Pages are
# requested in blocks of 100; the hard cap only guards against a broken server
# that never reports the end of the list.
APPOINTMENTS_PAGE_SIZE = 100
MAX_PAGINATION_PAGES = 50

_CONTENT_RANGE_RE = re.compile(r"items\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE)

# Bound the diagnostic summary so a large HTML error page cannot flood the log.
_MAX_DIAGNOSTIC_BODY = 500
_MAX_DIAGNOSTIC_LOCATION = 200


def _release(response: Any) -> None:
    """Release an ``aiohttp`` response if it supports it."""
    release = getattr(response, "release", None)
    if release is not None:
        release()


def _extract_items(payload: Any) -> list[Any]:
    """Return the ``items`` list of a paginated response."""
    if isinstance(payload, Mapping):
        items: Any = payload.get("items", [])
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        items = payload
    else:
        raise SomTodayApiError("The paginated response has an unexpected payload")

    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise SomTodayApiError("The paginated response has an unexpected payload")
    return list(items)


def _parse_content_range(value: str | None) -> tuple[int, int, int | None] | None:
    """Parse a ``Content-Range: items <start>-<end>/<total>`` header."""
    if not value:
        return None
    match = _CONTENT_RANGE_RE.search(value)
    if match is None:
        return None
    start, end, total = match.groups()
    return int(start), int(end), None if total == "*" else int(total)


def _is_last_page(
    headers: Mapping[str, str],
    page_length: int,
    page_size: int,
) -> bool:
    """Return whether no further page should be requested.

    A short page always ends the walk; otherwise the ``Content-Range`` header
    decides when the server reports the total number of items.
    """
    if page_length < page_size:
        return True
    content_range = headers.get("Content-Range") if headers else None
    parsed = _parse_content_range(content_range)
    if parsed is None:
        return False
    _, end, total = parsed
    if total is None:
        return False
    return end + 1 >= total


class SomTodayApiClient:
    """Thin async wrapper around the SomToday REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: SomTodayAuth,
        base_url: str,
    ) -> None:
        """Initialise the client with an injectable session and auth holder."""
        self._session = session
        self._auth = auth
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    @property
    def base_url(self) -> str:
        """Return the API base URL the client talks to."""
        return self._base_url

    async def async_get_account(self) -> Account:
        """Return the authenticated account from ``/rest/v1/account/me``."""
        payload = await self._request("GET", ACCOUNT_PATH)
        try:
            return parse_account(payload)
        except (TypeError, ValueError) as err:
            raise SomTodayApiError(
                "The account has an unexpected format"
            ) from err

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

    async def async_get_appointments(
        self, start: date, end: date
    ) -> list[dict[str, Any]]:
        """Return every appointment in the ``start``..``end`` window.

        The endpoint is paginated: pages are requested with a ``Range`` header
        and merged until the server reports the end of the list. The result is
        intentionally **not** filtered by student; the coordinator applies the
        per-student scope (docs/architecture.md section 7.2.1).
        """
        params = [
            ("begindatum", start.isoformat()),
            ("einddatum", end.isoformat()),
            ("sort", "asc-id"),
            ("additional", "vak"),
            ("additional", "docentAfkortingen"),
            ("additional", "leerlingen"),
        ]
        return await self._request_paginated(APPOINTMENTS_PATH, params=params)

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
        response = await self._request_raw(method, path, params=params)
        return await self._async_decode(response, method=method, path=path)

    async def _request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> aiohttp.ClientResponse:
        """Send a request, refreshing once on ``401``, and return the response.

        The caller owns the returned response and must release it.
        """
        await self._auth.async_ensure_valid()
        response = await self._send(method, path, params=params, headers=headers)

        if response.status == 401:
            # Release the rejected response before refreshing and retrying.
            _release(response)
            # The access token may have been revoked mid-flight.
            _LOGGER.debug("SomToday returned 401, refreshing the access token")
            await self._auth.async_refresh()
            response = await self._send(
                method, path, params=params, headers=headers
            )

        return response

    async def _request_paginated(
        self,
        path: str,
        *,
        params: Any,
        page_size: int = APPOINTMENTS_PAGE_SIZE,
    ) -> list[Any]:
        """Walk a ``Range``-paginated list endpoint and merge its items.

        Both ``200`` (the server returned the whole list) and ``206 Partial
        Content`` are treated as success. The walk stops on a short page, when
        the ``Content-Range`` header reports no more items, or after the hard
        page cap.
        """
        items: list[Any] = []
        offset = 0
        for _ in range(MAX_PAGINATION_PAGES):
            headers = {"Range": f"items={offset}-{offset + page_size - 1}"}
            response = await self._request_raw(
                "GET", path, params=params, headers=headers
            )

            if response.status not in (200, 206):
                # ``_async_decode`` maps the status and releases the response.
                await self._async_decode(response, method="GET", path=path)
                raise SomTodayApiError(
                    f"The GET {path} request returned HTTP {response.status}"
                )

            try:
                payload = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise SomTodayConnectionError(
                    f"Could not read the GET {path} response: {err}"
                ) from err
            except ValueError as err:
                raise SomTodayApiError(
                    f"The GET {path} response is not valid JSON"
                ) from err
            finally:
                _release(response)

            page_items = _extract_items(payload)
            items.extend(page_items)

            if response.status == 200 or _is_last_page(
                response.headers, len(page_items), page_size
            ):
                break
            offset += page_size
        else:
            _LOGGER.warning(
                "SomToday pagination for %s hit the %s page cap",
                path,
                MAX_PAGINATION_PAGES,
            )

        return items

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> aiohttp.ClientResponse:
        """Perform the raw HTTP request, mapping network errors."""
        url = f"{self._base_url}{path}"
        request_headers = self._build_headers()
        if headers:
            request_headers.update(headers)
        try:
            if method.upper() == "GET":
                return await self._session.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=self._timeout,
                )
            return await self._session.post(
                url,
                params=params,
                headers=request_headers,
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
            if status == 401:
                # The reactive refresh already ran in ``_request``; a second
                # 401 means the session is genuinely gone → escalate to reauth.
                await self._log_error_summary(response, method, path)
                raise SomtodayInvalidAuth(
                    f"SomToday rejected the {method} {path} session (HTTP 401)"
                )
            if status == 403:
                # Permission denied is not a dead session (typically the account
                # cannot see this endpoint) — retryable, never reauth.
                await self._log_error_summary(response, method, path)
                raise SomTodayApiError(
                    f"SomToday denied access to {method} {path} (HTTP 403)"
                )
            if status == 429:
                await self._log_error_summary(response, method, path)
                raise SomTodayRateLimitError(
                    f"SomToday rate limited the {method} {path} request (HTTP 429)"
                )
            if status >= 400:
                await self._log_error_summary(response, method, path)
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

    async def _log_error_summary(
        self,
        response: aiohttp.ClientResponse,
        method: str,
        path: str,
    ) -> None:
        """Log a bounded status/body/redirect summary for diagnostics.

        Only response metadata is logged; request headers (which carry the
        bearer token) are never touched.
        """
        location = ""
        headers = getattr(response, "headers", None)
        if isinstance(headers, Mapping):
            location = str(headers.get("Location", ""))

        body = ""
        text = getattr(response, "text", None)
        if text is not None:
            try:
                body = await text()
            except (aiohttp.ClientError, TimeoutError, ValueError):
                body = ""

        _LOGGER.debug(
            "SomToday %s %s returned HTTP %s (location=%s, body=%s)",
            method,
            path,
            response.status,
            location[:_MAX_DIAGNOSTIC_LOCATION],
            body[:_MAX_DIAGNOSTIC_BODY],
        )
