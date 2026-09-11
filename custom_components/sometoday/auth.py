"""Browser-based OAuth2 authorization-code + PKCE authentication for SomToday.

SomToday removed its school-list endpoint and disabled the password grant, and
server-side login-form scraping breaks at SSO/MFA schools. This module therefore
implements the same flow as the MIT-licensed ``jonisnet/ha-somtoday``
integration:

1. the config flow builds an authorize URL (with PKCE + ``state`` and **no**
   ``tenant_uuid``, so SomToday shows its own school picker);
2. the user logs in through their own browser (SSO/MFA work);
3. the user pastes the failed ``somtoday://`` redirect (or a bare code) back
   into Home Assistant;
4. HA exchanges the code server-side for tokens.

Everything only depends on an injectable ``aiohttp.ClientSession`` so the flow
is fully unit-testable without any network access. The authorization code and
PKCE verifier are used once and never stored; only the rotating refresh token
(and account metadata) is persisted.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import secrets
import string
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlencode

import aiohttp

from .const import (
    AUTHORIZE_URL,
    CLIENT_ID_APP,
    CODE_VERIFIER_LENGTH,
    DEFAULT_API_URL,
    PKCE_CHARSET,
    REDIRECT_URI,
    REQUEST_TIMEOUT,
    SCOPE,
    SESSION_NO_SESSION,
    STATE_LENGTH,
    TOKEN_URL,
)
from .exceptions import (
    SomTodayApiError,
    SomTodayAuthError,
    SomTodayConnectionError,
    SomtodayInvalidAuth,
    SomTodayRateLimitError,
)
from .models import SomTodayTokens

_LOGGER = logging.getLogger(__name__)

# Match ``code=`` / ``state=`` / ``auth=`` as query parameters, never as a
# prefix of ``code_challenge=`` / ``code_challenge_method=`` and never as a
# header value such as ``Set-Cookie: code=...``.
_CODE_RE = re.compile(r"[?&]code=([^&\s\r\n]+)")
_STATE_RE = re.compile(r"[?&]state=([^&\s\r\n]+)")
_AUTH_RE = re.compile(r"[?&]auth=")
# A pasted DevTools/response-header block: prefer the ``Location`` line so a
# stray ``code=`` in a cookie header can never win.
_LOCATION_RE = re.compile(r"(?im)^\s*location\s*:\s*(\S+)")
_LOGIN_HOSTS = ("inloggen.somtoday.nl", "somtoday.nl/oauth2/authorize")


def _release(response: Any) -> None:
    """Release an ``aiohttp`` response if it supports it."""
    release = getattr(response, "release", None)
    if release is not None:
        release()


# ---------------------------------------------------------------------------
# PKCE / authorize URL helpers
# ---------------------------------------------------------------------------
def generate_code_verifier() -> str:
    """Generate a 128 character PKCE code verifier from the app alphabet."""
    return "".join(
        secrets.choice(PKCE_CHARSET) for _ in range(CODE_VERIFIER_LENGTH)
    )


def code_challenge_from_verifier(verifier: str) -> str:
    """Derive the S256 PKCE challenge for ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def generate_state() -> str:
    """Generate a random OAuth2 ``state`` value (>= 128 bits of entropy)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(STATE_LENGTH))


def build_authorize_url(code_challenge: str, state: str) -> str:
    """Build the SomToday authorize URL.

    ``tenant_uuid`` is deliberately omitted so SomToday presents its own school
    picker; adding it would require the removed school-list endpoint.
    """
    params = {
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID_APP,
        "response_type": "code",
        "scope": SCOPE,
        "session": SESSION_NO_SESSION,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def extract_code(pasted: str, expected_state: str | None = None) -> str:
    """Extract an authorization code from a pasted redirect or bare code.

    Accepts a full ``somtoday://...?code=...&state=...`` URL, a DevTools
    ``location:`` header line, a response-header block, or a bare code.

    Raises :class:`ValueError` with one of these reasons:

    - ``login_page``: the paste happened before login completed (it contains
      ``auth=`` or the SomToday login host);
    - ``state_mismatch``: a ``state`` parameter is present but does not match
      the value generated for this flow;
    - ``no_code``: no usable code could be found.
    """
    if not pasted:
        raise ValueError("no_code")
    text = pasted.strip()
    if not text:
        raise ValueError("no_code")

    # When a full response-header block was pasted, use its ``Location`` line so
    # a ``Set-Cookie: code=...`` header can never be mistaken for the code.
    if location_match := _LOCATION_RE.search(text):
        text = location_match.group(1)

    code_match = _CODE_RE.search(text)
    state_match = _STATE_RE.search(text)

    if code_match:
        if (
            expected_state is not None
            and state_match is not None
            and unquote(state_match.group(1)) != expected_state
        ):
            raise ValueError("state_mismatch")
        return unquote(code_match.group(1))

    # No code: a login-page paste is a distinct, recoverable user mistake.
    if _AUTH_RE.search(text) or any(host in text for host in _LOGIN_HOSTS):
        raise ValueError("login_page")

    # A bare code is a single token without URL structure or header syntax.
    if any(char in text for char in (":", "/", "=", "\n", "\r", " ")):
        raise ValueError("no_code")
    decoded = unquote(text)
    if len(decoded) >= 8:
        return decoded
    raise ValueError("no_code")


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------
async def async_exchange_code(
    session: aiohttp.ClientSession,
    code: str,
    code_verifier: str,
    *,
    client_id: str = CLIENT_ID_APP,
    request_timeout: int = REQUEST_TIMEOUT,
) -> SomTodayTokens:
    """Exchange an authorization code for tokens at ``TOKEN_URL``."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": client_id,
        "scope": SCOPE,
        "session": SESSION_NO_SESSION,
    }
    return await _async_token_request(
        session, data, request_timeout=request_timeout
    )


async def async_refresh_tokens(
    session: aiohttp.ClientSession,
    refresh_token: str,
    *,
    client_id: str = CLIENT_ID_APP,
    fallback_api_url: str | None = None,
    fallback_tenant: str | None = None,
    request_timeout: int = REQUEST_TIMEOUT,
) -> SomTodayTokens:
    """Refresh an access token using ``refresh_token``.

    When the response omits a new refresh token, the supplied ``refresh_token``
    is preserved (no-op rotation). ``fallback_api_url``/``fallback_tenant`` keep
    the previous values when the token endpoint does not echo them.
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "scope": SCOPE,
    }
    return await _async_token_request(
        session,
        data,
        fallback_refresh_token=refresh_token,
        fallback_api_url=fallback_api_url,
        fallback_tenant=fallback_tenant,
        request_timeout=request_timeout,
    )


async def _async_token_request(
    session: aiohttp.ClientSession,
    data: Mapping[str, Any],
    *,
    fallback_refresh_token: str | None = None,
    fallback_api_url: str | None = None,
    fallback_tenant: str | None = None,
    request_timeout: int = REQUEST_TIMEOUT,
) -> SomTodayTokens:
    """POST a form-encoded token request and parse the response."""
    timeout = aiohttp.ClientTimeout(total=request_timeout)
    try:
        response = await session.post(
            TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except (aiohttp.ClientError, TimeoutError) as err:
        raise SomTodayConnectionError(
            f"Token request to {TOKEN_URL} failed: {err}"
        ) from err

    try:
        return await _parse_token_response(
            response,
            fallback_refresh_token=fallback_refresh_token,
            fallback_api_url=fallback_api_url,
            fallback_tenant=fallback_tenant,
        )
    finally:
        _release(response)


async def _read_oauth_error(response: Any) -> str | None:
    """Return the OAuth2 ``error`` code from an error response, if present."""
    try:
        payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
        return None
    if isinstance(payload, Mapping):
        error = payload.get("error")
        return str(error) if error else None
    return None


async def _parse_token_response(
    response: aiohttp.ClientResponse,
    *,
    fallback_refresh_token: str | None = None,
    fallback_api_url: str | None = None,
    fallback_tenant: str | None = None,
) -> SomTodayTokens:
    """Validate a token endpoint response and build :class:`SomTodayTokens`."""
    status = response.status

    if status != 200:
        error = await _read_oauth_error(response)
        if status == 400 and error == "invalid_grant":
            raise SomtodayInvalidAuth(
                "SomToday rejected the authorization code (invalid_grant)"
            )
        if status == 429:
            raise SomTodayRateLimitError(
                "SomToday rate limited the token endpoint (HTTP 429)"
            )
        # Everything else is retryable: transient network/server failures or a
        # non-definitive OAuth2 error.
        raise SomTodayConnectionError(
            f"The token endpoint returned HTTP {status} (error={error or 'unknown'})"
        )

    try:
        payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise SomTodayConnectionError(
            f"Could not read the token endpoint response: {err}"
        ) from err
    except ValueError as err:
        raise SomTodayApiError("The token endpoint returned invalid JSON") from err

    if not isinstance(payload, Mapping):
        raise SomTodayApiError("The token endpoint returned an unexpected payload")

    try:
        return SomTodayTokens.from_token_response(
            payload,
            fallback_refresh_token=fallback_refresh_token,
            fallback_api_url=fallback_api_url,
            fallback_tenant=fallback_tenant,
        )
    except ValueError as err:
        raise SomTodayAuthError(
            "The token endpoint returned an unexpected payload"
        ) from err


# ---------------------------------------------------------------------------
# Token holder
# ---------------------------------------------------------------------------
class SomTodayAuth:
    """Holds the OAuth2 tokens and refreshes them under a lock.

    The API client depends on this object for a valid access token. Refresh is
    serialised with an :class:`asyncio.Lock` so concurrent requests cannot race
    a rotating refresh token.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        tokens: SomTodayTokens | None = None,
        api_url: str | None = None,
        tenant: str | None = None,
        client_id: str = CLIENT_ID_APP,
        request_timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        """Initialise the holder with an injectable session and optional tokens."""
        self._session = session
        self._client_id = client_id
        self._timeout = request_timeout
        self._lock = asyncio.Lock()
        self.tokens = tokens
        self.api_url = (tokens.api_url if tokens is not None else api_url) or DEFAULT_API_URL
        self.tenant = tenant if tokens is None else (tokens.tenant or tenant)

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing it when needed."""
        await self.async_ensure_valid()
        if self.tokens is None:  # pragma: no cover - defensive
            raise SomTodayAuthError("Not authenticated")
        return self.tokens.access_token

    async def async_ensure_valid(self) -> None:
        """Refresh the access token when it is about to expire."""
        async with self._lock:
            if self.tokens is None:
                raise SomTodayAuthError("Not authenticated")
            if self.tokens.expires_soon():
                await self._async_refresh_locked()

    async def async_refresh(self) -> SomTodayTokens:
        """Force a token refresh (used by the API client after a ``401``)."""
        async with self._lock:
            return await self._async_refresh_locked()

    async def _async_refresh_locked(self) -> SomTodayTokens:
        """Refresh while the lock is already held."""
        if self.tokens is None or not self.tokens.refresh_token:
            raise SomTodayAuthError("Cannot refresh without a refresh token")

        previous = self.tokens
        tokens = await async_refresh_tokens(
            self._session,
            previous.refresh_token,
            client_id=self._client_id,
            fallback_api_url=previous.api_url or self.api_url,
            fallback_tenant=previous.tenant or self.tenant,
            request_timeout=self._timeout,
        )
        # Account metadata is not part of the token response; carry it over.
        tokens.account_id = previous.account_id
        tokens.student_id = previous.student_id
        tokens.student_name = previous.student_name

        self.tokens = tokens
        self.api_url = tokens.api_url
        self.tenant = tokens.tenant
        return tokens

    def as_entry_data(self) -> dict[str, Any]:
        """Return the persistable entry data (refresh token + metadata)."""
        if self.tokens is None:
            raise SomTodayAuthError("Not authenticated")
        return self.tokens.as_entry_data()
