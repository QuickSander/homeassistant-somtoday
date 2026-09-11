"""OAuth2 authentication client for SomToday.

The client implements the server-side PKCE authorization-code flow that the
SomToday app/webapp uses, with the legacy password grant as a fallback for
schools that cannot complete the PKCE flow. It only depends on an injectable
``aiohttp.ClientSession`` and the tenant UUID, which keeps the flow fully
unit-testable without any network access.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import string
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

from .const import (
    AUTH_METHOD_PASSWORD,
    AUTH_METHOD_PKCE,
    AUTHORIZE_URL,
    CLIENT_ID_APP,
    CLIENT_ID_SSO,
    CODE_VERIFIER_LENGTH,
    CONF_AUTH_METHOD,
    LOGIN_BASE_URL,
    PASSWORD_FIELD,
    PKCE_CHARSET,
    REDIRECT_URI,
    REQUEST_TIMEOUT,
    SCHOOLS_URL,
    SCOPE,
    SESSION_NO_SESSION,
    STATE_LENGTH,
    TOKEN_URL,
    TOKEN_URL_SSO,
    USERNAME_FIELD,
)
from .exceptions import (
    SomTodayApiError,
    SomTodayAuthError,
    SomTodayConnectionError,
    SomTodayRateLimitError,
    SomTodaySsoNotSupported,
)
from .models import School, SomTodayTokens, parse_schools

_LOGGER = logging.getLogger(__name__)


def _release(response: aiohttp.ClientResponse) -> None:
    """Release an ``aiohttp`` response if it supports it."""
    release = getattr(response, "release", None)
    if release is not None:
        release()


def _raise_for_error_status(response: aiohttp.ClientResponse, *, context: str) -> None:
    """Map an error HTTP status to the shared exception hierarchy.

    Follows ``docs/architecture.md`` section 5.1: 429 maps to
    :class:`SomTodayRateLimitError`, other 4xx/5xx responses to
    :class:`SomTodayApiError`.
    """
    status = response.status
    if status < 400:
        return
    if status == 429:
        raise SomTodayRateLimitError(
            f"SomToday rate limited the {context} request (HTTP 429)"
        )
    raise SomTodayApiError(f"The {context} endpoint returned HTTP {status}")


async def async_get_schools(
    session: aiohttp.ClientSession,
    *,
    request_timeout: int = REQUEST_TIMEOUT,
) -> list[School]:
    """Retrieve the SomToday school list used for school discovery.

    ``session`` is injected so tests can mock HTTP without touching the real
    SomToday API.
    """
    timeout = aiohttp.ClientTimeout(total=request_timeout)
    try:
        response = await session.get(SCHOOLS_URL, timeout=timeout)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise SomTodayConnectionError(f"Could not retrieve the school list: {err}") from err

    try:
        _raise_for_error_status(response, context="school list")

        try:
            payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SomTodayConnectionError(
                f"Could not retrieve the school list: {err}"
            ) from err
        except ValueError as err:
            raise SomTodayApiError("The school list has an unexpected format") from err

        try:
            return parse_schools(payload)
        except (TypeError, ValueError) as err:
            raise SomTodayApiError("The school list has an unexpected format") from err
    finally:
        _release(response)


class SomTodayAuthClient:
    """Owns the OAuth2 tokens and the login/refresh strategies."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tenant_uuid: str,
        *,
        client_id: str = CLIENT_ID_APP,
        token_url: str = TOKEN_URL,
        sso_token_url: str = TOKEN_URL_SSO,
        authorize_url: str = AUTHORIZE_URL,
        redirect_uri: str = REDIRECT_URI,
        request_timeout: int = REQUEST_TIMEOUT,
        auth_method: str | None = None,
    ) -> None:
        """Initialise the client with an injectable session and tenant UUID.

        ``auth_method`` restores the refresh pairing (client ID + token
        endpoint) of a previous login after a restart. It is read from the
        config entry as ``CONF_AUTH_METHOD`` and defaults to the PKCE pairing.
        """
        self._session = session
        self._tenant_uuid = tenant_uuid
        self._client_id = client_id
        self._token_url = token_url
        self._sso_token_url = sso_token_url
        self._authorize_url = authorize_url
        self._redirect_uri = redirect_uri
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._cookies: dict[str, str] = {}
        self._lock = asyncio.Lock()

        # Refresh must reuse the client ID and token endpoint of the login
        # method (see docs/architecture.md section 12.2), which differs between
        # the PKCE and password-grant flows.
        if auth_method == AUTH_METHOD_PASSWORD:
            self._active_client_id = CLIENT_ID_SSO
            self._active_token_url = sso_token_url
        else:
            self._active_client_id = client_id
            self._active_token_url = token_url

        self.tokens: SomTodayTokens | None = None

    @property
    def auth_method(self) -> str:
        """Return the login method matching the current refresh pairing."""
        if self._active_client_id == CLIENT_ID_SSO:
            return AUTH_METHOD_PASSWORD
        return AUTH_METHOD_PKCE

    def as_entry_data(self) -> dict[str, Any]:
        """Return the token fields and auth method to persist in the entry.

        Persisting ``auth_method`` lets a restart restore the correct refresh
        host and client ID (see docs/architecture.md section 12.2).
        """
        if self.tokens is None:
            raise SomTodayAuthError("Not authenticated")
        return {**self.tokens.as_entry_data(), CONF_AUTH_METHOD: self.auth_method}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def async_login(self, username: str, password: str) -> SomTodayTokens:
        """Authenticate with the given credentials.

        The PKCE authorization-code flow is attempted first. When the school
        only supports single sign-on, the legacy password grant is used as a
        fallback. Invalid credentials are never retried with the fallback.
        """
        async with self._lock:
            # Start each login attempt from a clean cookie jar so stale
            # JSESSIONID/stickiness cookies from a previous attempt are not sent.
            self._cookies.clear()
            try:
                tokens = await self._async_pkce_login(username, password)
                self._active_client_id = self._client_id
                self._active_token_url = self._token_url
            except SomTodaySsoNotSupported:
                _LOGGER.debug(
                    "PKCE flow unavailable for tenant %s, trying the password grant",
                    self._tenant_uuid,
                )
                tokens = await self._async_password_grant(username, password)
                self._active_client_id = CLIENT_ID_SSO
                self._active_token_url = self._sso_token_url
            self.tokens = tokens
            return tokens

    async def async_refresh(self) -> SomTodayTokens:
        """Refresh the access token using the stored refresh token.

        A rotating refresh token returned by SomToday replaces the stored one.
        When SomToday does not rotate it, the existing refresh token is kept.
        """
        async with self._lock:
            if self.tokens is None or not self.tokens.refresh_token:
                raise SomTodayAuthError("Cannot refresh without a refresh token")

            previous = self.tokens
            data = {
                "grant_type": "refresh_token",
                "refresh_token": previous.refresh_token,
                "client_id": self._active_client_id,
                "scope": SCOPE,
            }
            response = await self._post(self._active_token_url, data=data)
            self.tokens = await self._parse_token_response(
                response,
                fallback_refresh_token=previous.refresh_token,
                fallback_api_url=previous.api_url,
                fallback_tenant=previous.tenant,
            )
            return self.tokens

    async def async_ensure_valid(self) -> None:
        """Refresh the access token when it is about to expire."""
        if self.tokens is None:
            raise SomTodayAuthError("Not authenticated")
        if self.tokens.expires_soon():
            await self.async_refresh()

    # ------------------------------------------------------------------
    # PKCE authorization-code flow
    # ------------------------------------------------------------------
    async def _async_pkce_login(self, username: str, password: str) -> SomTodayTokens:
        """Run the full PKCE authorization-code flow."""
        code_verifier, code_challenge = self._generate_pkce_pair()
        state = self._generate_state()

        # Step 1: start the authorization request and capture the login session.
        authorize_params = {
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "response_type": "code",
            "state": state,
            "scope": SCOPE,
            "tenant_uuid": self._tenant_uuid,
            "session": SESSION_NO_SESSION,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        response = await self._get(self._authorize_url, params=authorize_params)
        try:
            self._store_cookies(response)
            if response.status >= 500:
                raise SomTodayApiError(
                    f"The authorize endpoint returned HTTP {response.status}"
                )
            if response.status >= 400:
                raise SomTodayAuthError(
                    f"The authorize endpoint rejected the request (HTTP {response.status})"
                )
            auth_code = self._extract_auth(self._location(response))
            if not auth_code:
                if response.status in (301, 302, 303, 307, 308):
                    # A redirect without an auth token goes to an external IdP.
                    raise SomTodaySsoNotSupported(
                        "The authorize endpoint redirected to an external identity "
                        "provider; the school likely requires single sign-on"
                    )
                raise SomTodayAuthError(
                    "The authorize endpoint did not return a SomToday login session"
                )
        finally:
            _release(response)

        # Step 2: establish the login session (JSESSIONID).
        response = await self._get(
            f"{LOGIN_BASE_URL}/", params={"auth": auth_code}
        )
        try:
            self._store_cookies(response)
        finally:
            _release(response)

        # Step 3: submit the username to detect the login flow.
        response = await self._post(
            f"{LOGIN_BASE_URL}/0-1.-panel-signInForm",
            params={"auth": auth_code},
            data={USERNAME_FIELD: username},
            headers={"Origin": LOGIN_BASE_URL},
        )
        try:
            self._store_cookies(response)
            _raise_for_error_status(response, context="login form")
            location = self._location(response)
        finally:
            _release(response)

        # Step 4: submit the password using the detected flow.
        if "auth=" in location:
            # Username + password flow: both fields are submitted together.
            response = await self._post(
                f"{LOGIN_BASE_URL}/?0-1.-panel-signInForm",
                params={"auth": auth_code},
                data={
                    USERNAME_FIELD: username,
                    PASSWORD_FIELD: password,
                    "loginLink": "x",
                },
                headers={"Origin": LOGIN_BASE_URL},
            )
        else:
            # Username-first flow: the username was already submitted.
            response = await self._post(
                f"{LOGIN_BASE_URL}/login?2-1.-passwordForm",
                params={"auth": auth_code},
                data={PASSWORD_FIELD: password, "loginLink": "x"},
                headers={"Origin": LOGIN_BASE_URL},
            )
        try:
            self._store_cookies(response)
            _raise_for_error_status(response, context="login form")
            final_code = self._extract_code(self._location(response))
            if not final_code:
                raise SomTodayAuthError(
                    "SomToday did not return an authorization code; "
                    "check the username and password"
                )
        finally:
            _release(response)

        # Step 5: exchange the authorization code for tokens.
        return await self._exchange_code(final_code, code_verifier)

    async def _exchange_code(self, code: str, code_verifier: str) -> SomTodayTokens:
        """Exchange the final authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": self._client_id,
            "tenant_uuid": self._tenant_uuid,
            "session": SESSION_NO_SESSION,
            "scope": SCOPE,
        }
        response = await self._post(self._token_url, data=data)
        return await self._parse_token_response(response)

    async def _async_password_grant(
        self, username: str, password: str
    ) -> SomTodayTokens:
        """Run the legacy ``grant_type=password`` flow as a fallback."""
        data = {
            "grant_type": "password",
            "username": f"{self._tenant_uuid}\\{username}",
            "password": password,
            "scope": SCOPE,
            "client_id": CLIENT_ID_SSO,
        }
        response = await self._post(self._sso_token_url, data=data)
        return await self._parse_token_response(response)

    # ------------------------------------------------------------------
    # Token parsing
    # ------------------------------------------------------------------
    async def _parse_token_response(
        self,
        response: aiohttp.ClientResponse,
        *,
        fallback_refresh_token: str | None = None,
        fallback_api_url: str | None = None,
        fallback_tenant: str | None = None,
    ) -> SomTodayTokens:
        """Validate a token endpoint response and build :class:`SomTodayTokens`."""
        try:
            if response.status in (400, 401, 403):
                raise SomTodayAuthError(
                    f"SomToday rejected the authentication request (HTTP {response.status})"
                )
            if response.status == 429:
                raise SomTodayRateLimitError(
                    "SomToday rate limited the token endpoint (HTTP 429)"
                )
            if response.status >= 500:
                raise SomTodayApiError(
                    f"The token endpoint returned HTTP {response.status}"
                )
            if response.status != 200:
                raise SomTodayConnectionError(
                    f"The token endpoint returned HTTP {response.status}"
                )

            try:
                payload = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError) as err:
                raise SomTodayConnectionError(
                    f"Could not read the token endpoint response: {err}"
                ) from err
            except ValueError as err:
                raise SomTodayApiError(
                    "The token endpoint returned invalid JSON"
                ) from err

            if not isinstance(payload, Mapping):
                raise SomTodayApiError(
                    "The token endpoint returned an unexpected payload"
                )

            if fallback_refresh_token and not payload.get("refresh_token"):
                payload = {**payload, "refresh_token": fallback_refresh_token}

            try:
                return SomTodayTokens.from_token_response(
                    payload,
                    fallback_api_url=fallback_api_url,
                    fallback_tenant=fallback_tenant,
                )
            except ValueError as err:
                raise SomTodayApiError(
                    "The token endpoint returned an unexpected payload"
                ) from err
        finally:
            _release(response)

    # ------------------------------------------------------------------
    # PKCE helpers
    # ------------------------------------------------------------------
    def _generate_pkce_pair(self) -> tuple[str, str]:
        """Generate a deterministic-testable PKCE verifier/challenge pair."""
        verifier = self._generate_code_verifier()
        return verifier, self._code_challenge(verifier)

    @staticmethod
    def _generate_code_verifier() -> str:
        """Generate a 128 character code verifier from the app alphabet."""
        return "".join(
            secrets.choice(PKCE_CHARSET) for _ in range(CODE_VERIFIER_LENGTH)
        )

    @staticmethod
    def _generate_state() -> str:
        """Generate a random OAuth2 state value."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(STATE_LENGTH))

    @staticmethod
    def _code_challenge(code_verifier: str) -> str:
        """Derive the S256 PKCE challenge for ``code_verifier``."""
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        allow_redirects: bool = False,
    ) -> aiohttp.ClientResponse:
        """Perform a GET request, mapping network errors."""
        try:
            return await self._session.get(
                url,
                params=params,
                cookies=dict(self._cookies),
                allow_redirects=allow_redirects,
                timeout=self._timeout,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SomTodayConnectionError(f"Request to {url} failed: {err}") from err

    async def _post(
        self,
        url: str,
        *,
        data: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        allow_redirects: bool = False,
    ) -> aiohttp.ClientResponse:
        """Perform a POST request, mapping network errors."""
        try:
            return await self._session.post(
                url,
                data=data,
                params=params,
                headers=headers,
                cookies=dict(self._cookies),
                allow_redirects=allow_redirects,
                timeout=self._timeout,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SomTodayConnectionError(f"Request to {url} failed: {err}") from err

    def _store_cookies(self, response: aiohttp.ClientResponse) -> None:
        """Persist cookies from a response for the following requests."""
        cookies = getattr(response, "cookies", None)
        if not cookies:
            return
        items = cookies.items() if hasattr(cookies, "items") else ()
        for name, morsel in items:
            value = getattr(morsel, "value", morsel)
            if value:
                self._cookies[name] = str(value)

    # ------------------------------------------------------------------
    # Location helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _location(response: aiohttp.ClientResponse) -> str:
        """Return the ``Location`` header of a response, if any."""
        return response.headers.get("Location", "")

    @classmethod
    def _extract_query_param(cls, location: str, name: str) -> str | None:
        """Extract a single query parameter from a URL."""
        if not location:
            return None
        values = parse_qs(urlparse(location).query).get(name)
        return values[0] if values else None

    @classmethod
    def _extract_code(cls, location: str) -> str | None:
        """Extract the final authorization code from a redirect location."""
        return cls._extract_query_param(location, "code")

    @classmethod
    def _extract_auth(cls, location: str) -> str | None:
        """Extract the login session token from a redirect location."""
        return cls._extract_query_param(location, "auth")
