"""Unit tests for the SomToday browser authorization-code + PKCE flow.

All HTTP is mocked through ``FakeSession``; the real SomToday API is never
called.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

from custom_components.sometoday.auth import (
    SomTodayAuth,
    async_exchange_code,
    async_refresh_tokens,
    build_authorize_url,
    code_challenge_from_verifier,
    extract_code,
    generate_code_verifier,
    generate_state,
)
from custom_components.sometoday.const import (
    AUTHORIZE_URL,
    CLIENT_ID_APP,
    CODE_VERIFIER_LENGTH,
    PKCE_CHARSET,
    REDIRECT_URI,
    SCOPE,
    SESSION_NO_SESSION,
    STATE_LENGTH,
    TOKEN_URL,
)
from custom_components.sometoday.exceptions import (
    SomTodayApiError,
    SomTodayAuthError,
    SomTodayConnectionError,
    SomtodayInvalidAuth,
    SomTodayRateLimitError,
)
from custom_components.sometoday.models import SomTodayTokens

TOKEN_PAYLOAD: dict[str, Any] = {
    "access_token": "access",
    "refresh_token": "refresh",
    "somtoday_api_url": "https://api.somtoday.nl",
    "somtoday_tenant": "bonhoeffer",
    "token_type": "Bearer",
    "scope": "openid",
    "expires_in": 3600,
}


def _tokens(refresh_token: str = "refresh") -> SomTodayTokens:
    """Return a fresh token set for the holder tests."""
    return SomTodayTokens(
        access_token="access",
        refresh_token=refresh_token,
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC) + timedelta(seconds=3600),
    )


# ---------------------------------------------------------------------------
# PKCE / authorize URL
# ---------------------------------------------------------------------------
def test_generate_code_verifier() -> None:
    """The verifier has the documented length and alphabet and is random."""
    verifier = generate_code_verifier()

    assert len(verifier) == CODE_VERIFIER_LENGTH
    assert set(verifier) <= set(PKCE_CHARSET)
    assert generate_code_verifier() != verifier


def test_code_challenge_from_verifier() -> None:
    """The S256 challenge is base64url(SHA-256(verifier)) without padding."""
    verifier = "abc123"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )

    assert code_challenge_from_verifier(verifier) == expected


def test_generate_state() -> None:
    """The state is long enough and random."""
    state = generate_state()

    assert len(state) == STATE_LENGTH
    assert generate_state() != state


def test_build_authorize_url_omits_tenant_uuid() -> None:
    """The authorize URL carries PKCE and state but no tenant_uuid."""
    url = build_authorize_url("CHALLENGE", "STATE")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_URL
    assert params["redirect_uri"] == [REDIRECT_URI]
    assert params["client_id"] == [CLIENT_ID_APP]
    assert params["response_type"] == ["code"]
    assert params["scope"] == [SCOPE]
    assert params["session"] == [SESSION_NO_SESSION]
    assert params["state"] == ["STATE"]
    assert params["code_challenge"] == ["CHALLENGE"]
    assert params["code_challenge_method"] == ["S256"]
    assert "tenant_uuid" not in params
    assert "tenant_uuid" not in url


# ---------------------------------------------------------------------------
# extract_code
# ---------------------------------------------------------------------------
def test_extract_code_full_redirect_url() -> None:
    """A full somtoday:// redirect with a matching state is accepted."""
    pasted = (
        "somtoday://nl.topicus.somtoday.leerling/oauth/callback"
        "?code=THECODE&state=STATE"
    )

    assert extract_code(pasted, "STATE") == "THECODE"


def test_extract_code_skips_state_check_when_absent() -> None:
    """A redirect without a state parameter skips the best-effort check."""
    pasted = "somtoday://nl.topicus.somtoday.leerling/oauth/callback?code=THECODE"

    assert extract_code(pasted, "STATE") == "THECODE"


def test_extract_code_state_mismatch() -> None:
    """A present but wrong state is a definitive rejection."""
    pasted = "somtoday://callback?code=THECODE&state=WRONG"

    with pytest.raises(ValueError) as err:
        extract_code(pasted, "STATE")

    assert str(err.value) == "state_mismatch"


def test_extract_code_devtools_location_header() -> None:
    """A DevTools ``location:`` header line is accepted."""
    pasted = "location: somtoday://callback?code=THECODE&state=STATE"

    assert extract_code(pasted, "STATE") == "THECODE"


def test_extract_code_response_header_block() -> None:
    """A full response-header block is accepted."""
    pasted = (
        "HTTP/1.1 302 Found\r\n"
        "Location: somtoday://callback?code=THECODE&state=STATE\r\n"
        "Content-Length: 0\r\n"
    )

    assert extract_code(pasted, "STATE") == "THECODE"


def test_extract_code_bare_code() -> None:
    """A bare code is accepted when it is a single token."""
    assert extract_code("ABCDEFGHIJKLMNOP", "STATE") == "ABCDEFGHIJKLMNOP"


def test_extract_code_bare_url_encoded_code() -> None:
    """A bare percent-encoded code is decoded (finding T2)."""
    assert extract_code("ABCDEFGH%2FIJ%2BK", "STATE") == "ABCDEFGH/IJ+K"


def test_extract_code_ignores_code_challenge() -> None:
    """``code_challenge=`` must not be mistaken for ``code=``."""
    pasted = "https://x/callback?code_challenge=CHALLENGE&code=REALCODE"

    assert extract_code(pasted, None) == "REALCODE"


def test_extract_code_url_decodes() -> None:
    """Percent-encoded codes are decoded."""
    pasted = "somtoday://callback?code=AB%2FC%2BD&state=STATE"

    assert extract_code(pasted, "STATE") == "AB/C+D"


@pytest.mark.parametrize(
    "pasted",
    [
        "https://inloggen.somtoday.nl/?auth=SESSION123",
        "https://inloggen.somtoday.nl/",
        "https://inloggen.somtoday.nl/oauth2/authorize?client_id=x",
    ],
)
def test_extract_code_login_page(pasted: str) -> None:
    """A login-page paste is reported as login_page."""
    with pytest.raises(ValueError) as err:
        extract_code(pasted, "STATE")

    assert str(err.value) == "login_page"


@pytest.mark.parametrize("pasted", ["", "   ", "not a code", "abc", "https://example.com/x"])
def test_extract_code_no_code(pasted: str) -> None:
    """Empty or unstructured input is reported as no_code."""
    with pytest.raises(ValueError) as err:
        extract_code(pasted, "STATE")

    assert str(err.value) == "no_code"


def test_extract_code_rejects_sso_callback() -> None:
    """A Microsoft Entra ID callback is rejected with its own reason."""
    pasted = (
        "https://inloggen.somtoday.nl/oidc?code=1.AQUAabc&state=dc4c605eb4"
        "&session_state=008b30ea-6861-91ea-e789-1a5895bb19ef"
    )

    with pytest.raises(ValueError) as err:
        extract_code(pasted, "STATE")

    assert str(err.value) == "sso_callback"


def test_extract_code_strips_quotes_around_location() -> None:
    """A quoted Location value has its quotes stripped before matching."""
    pasted = (
        "HTTP/1.1 302 Found\r\n"
        'Location: "somtoday://callback?code=REALCODE&state=STATE"\r\n'
    )

    assert extract_code(pasted, "STATE") == "REALCODE"


def test_extract_code_value_stops_at_trailing_bracket() -> None:
    """Trailing punctuation after the code is not captured."""
    pasted = "somtoday://callback?code=REALCODE&state=STATE>"

    assert extract_code(pasted, "STATE") == "REALCODE"


class _BodyErrorResponse:
    """A response whose JSON body read raises a scripted error."""

    def __init__(self, error: Exception, status: int = 200) -> None:
        self._error = error
        self.status = status
        self.headers: dict[str, str] = {}
        self.release_count = 0

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        raise self._error

    def release(self) -> None:
        self.release_count += 1


# ---------------------------------------------------------------------------
# async_exchange_code
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exchange_code_body_and_headers(
    fake_session: Any, fake_response: Any
) -> None:
    """The exchange posts the documented form body with Accept: application/json."""
    session = fake_session([fake_response(200, json_data=dict(TOKEN_PAYLOAD))])

    tokens = await async_exchange_code(session, "THECODE", "VERIFIER")

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == TOKEN_URL
    assert kwargs["headers"] == {"Accept": "application/json"}
    assert kwargs["data"] == {
        "grant_type": "authorization_code",
        "code": "THECODE",
        "code_verifier": "VERIFIER",
        "client_id": CLIENT_ID_APP,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "session": SESSION_NO_SESSION,
    }
    assert tokens.access_token == "access"
    assert tokens.refresh_token == "refresh"
    assert tokens.api_url == "https://api.somtoday.nl"
    assert tokens.tenant == "bonhoeffer"


@pytest.mark.asyncio
async def test_exchange_code_invalid_grant_is_definitive(
    fake_session: Any, fake_response: Any
) -> None:
    """HTTP 400 + invalid_grant raises SomtodayInvalidAuth."""
    session = fake_session(
        [fake_response(400, json_data={"error": "invalid_grant"})]
    )

    with pytest.raises(SomtodayInvalidAuth):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_logs_oauth_error_description(
    fake_session: Any, fake_response: Any, caplog: Any
) -> None:
    """A failed exchange logs the OAuth2 error/description but never secrets."""
    session = fake_session(
        [
            fake_response(
                400,
                json_data={
                    "error": "invalid_grant",
                    "error_description": "AADB2C90088: code already redeemed",
                },
            )
        ]
    )

    with caplog.at_level("WARNING"), pytest.raises(SomtodayInvalidAuth):
        await async_exchange_code(session, "THECODE", "VERIFIER")

    assert "invalid_grant" in caplog.text
    assert "already redeemed" in caplog.text
    assert "THECODE" not in caplog.text
    assert "VERIFIER" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param(("400", {"error": "invalid_request"}), id="400-other"),
        pytest.param(("500", None), id="500"),
        pytest.param(("404", None), id="404"),
    ],
)
async def test_exchange_code_retryable_errors(
    fake_session: Any, fake_response: Any, response: Any
) -> None:
    """Other non-200 responses are retryable connection errors."""
    status, body = response
    session = fake_session([fake_response(int(status), json_data=body)])

    with pytest.raises(SomTodayConnectionError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_rate_limit(fake_session: Any, fake_response: Any) -> None:
    """A 429 maps to SomTodayRateLimitError."""
    session = fake_session([fake_response(429)])

    with pytest.raises(SomTodayRateLimitError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_invalid_json(
    fake_session: Any, fake_response: Any
) -> None:
    """A 200 with a non-JSON body maps to SomTodayApiError."""
    session = fake_session([fake_response(200)])

    with pytest.raises(SomTodayApiError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_missing_access_token(
    fake_session: Any, fake_response: Any
) -> None:
    """A 200 without an access token maps to SomTodayAuthError."""
    session = fake_session([fake_response(200, json_data={"refresh_token": "r"})])

    with pytest.raises(SomTodayAuthError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_non_mapping_payload(
    fake_session: Any, fake_response: Any
) -> None:
    """A 200 JSON array maps to SomTodayApiError."""
    session = fake_session([fake_response(200, json_data=["nope"])])

    with pytest.raises(SomTodayApiError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_error_body_non_mapping(
    fake_session: Any, fake_response: Any
) -> None:
    """A 400 with a non-mapping error body is still retryable."""
    session = fake_session([fake_response(400, json_data=["nope"])])

    with pytest.raises(SomTodayConnectionError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_body_read_error(fake_session: Any) -> None:
    """A body-read error on a 200 response maps to SomTodayConnectionError."""
    session = fake_session([_BodyErrorResponse(aiohttp.ClientError("boom"))])

    with pytest.raises(SomTodayConnectionError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_network_error(fake_session: Any) -> None:
    """A network failure maps to SomTodayConnectionError."""
    session = fake_session([aiohttp.ClientError("boom")])

    with pytest.raises(SomTodayConnectionError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_timeout(fake_session: Any) -> None:
    """A timeout maps to SomTodayConnectionError."""
    session = fake_session([TimeoutError("timed out")])

    with pytest.raises(SomTodayConnectionError):
        await async_exchange_code(session, "THECODE", "VERIFIER")


@pytest.mark.asyncio
async def test_exchange_code_releases_response(
    fake_session: Any, fake_response: Any
) -> None:
    """The token response is released after parsing."""
    response = fake_response(200, json_data=dict(TOKEN_PAYLOAD))
    session = fake_session([response])

    await async_exchange_code(session, "THECODE", "VERIFIER")

    assert response.release_count == 1


# ---------------------------------------------------------------------------
# async_refresh_tokens
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refresh_tokens_body(fake_session: Any, fake_response: Any) -> None:
    """The refresh posts the documented form body."""
    session = fake_session([fake_response(200, json_data=dict(TOKEN_PAYLOAD))])

    await async_refresh_tokens(session, "oldrefresh")

    _, url, kwargs = session.calls[0]
    assert url == TOKEN_URL
    assert kwargs["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "oldrefresh",
        "client_id": CLIENT_ID_APP,
        "scope": SCOPE,
    }


@pytest.mark.asyncio
async def test_refresh_tokens_rotates(fake_session: Any, fake_response: Any) -> None:
    """A rotated refresh token replaces the stored one."""
    session = fake_session(
        [fake_response(200, json_data={**TOKEN_PAYLOAD, "refresh_token": "rotated"})]
    )

    tokens = await async_refresh_tokens(session, "oldrefresh")

    assert tokens.refresh_token == "rotated"


@pytest.mark.asyncio
async def test_refresh_tokens_preserves_when_omitted(
    fake_session: Any, fake_response: Any
) -> None:
    """When the response omits the refresh token, the old one is kept."""
    payload = {k: v for k, v in TOKEN_PAYLOAD.items() if k != "refresh_token"}
    session = fake_session([fake_response(200, json_data=payload)])

    tokens = await async_refresh_tokens(session, "oldrefresh")

    assert tokens.refresh_token == "oldrefresh"


@pytest.mark.asyncio
async def test_refresh_tokens_preserves_api_url_and_tenant(
    fake_session: Any, fake_response: Any
) -> None:
    """Fallbacks keep api_url/tenant when the response omits them."""
    session = fake_session(
        [
            fake_response(
                200,
                json_data={"access_token": "new", "expires_in": 3600},
            )
        ]
    )

    tokens = await async_refresh_tokens(
        session,
        "oldrefresh",
        fallback_api_url="https://school.example/api",
        fallback_tenant="school",
    )

    assert tokens.api_url == "https://school.example/api"
    assert tokens.tenant == "school"
    assert tokens.refresh_token == "oldrefresh"


@pytest.mark.asyncio
async def test_refresh_tokens_invalid_grant(
    fake_session: Any, fake_response: Any
) -> None:
    """A refresh invalid_grant is definitive."""
    session = fake_session([fake_response(400, json_data={"error": "invalid_grant"})])

    with pytest.raises(SomtodayInvalidAuth):
        await async_refresh_tokens(session, "oldrefresh")


# ---------------------------------------------------------------------------
# SomTodayAuth holder
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_holder_ensure_valid_refreshes_expiring(
    fake_session: Any, fake_response: Any
) -> None:
    """An expiring token is refreshed."""
    session = fake_session([fake_response(200, json_data=dict(TOKEN_PAYLOAD))])
    auth = SomTodayAuth(session, tokens=_tokens())
    assert auth.tokens is not None
    auth.tokens.expires_at = datetime.now(UTC) + timedelta(seconds=30)

    await auth.async_ensure_valid()

    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_holder_ensure_valid_skips_fresh(fake_session: Any) -> None:
    """A fresh token is not refreshed."""
    session = fake_session([])
    auth = SomTodayAuth(session, tokens=_tokens())

    await auth.async_ensure_valid()

    assert session.calls == []


@pytest.mark.asyncio
async def test_holder_ensure_valid_without_tokens(fake_session: Any) -> None:
    """ensure_valid raises when no tokens are present."""
    auth = SomTodayAuth(fake_session([]))

    with pytest.raises(SomTodayAuthError):
        await auth.async_ensure_valid()


@pytest.mark.asyncio
async def test_holder_get_access_token(fake_session: Any) -> None:
    """get_access_token returns the current access token."""
    auth = SomTodayAuth(fake_session([]), tokens=_tokens())

    assert await auth.async_get_access_token() == "access"


@pytest.mark.asyncio
async def test_holder_refresh_preserves_account_metadata(
    fake_session: Any,
) -> None:
    """Account metadata is carried over a refresh."""
    tokens = _tokens()
    tokens.account_id = "account-1"
    tokens.student_id = 1234
    tokens.student_name = "Eli Saado"
    auth = SomTodayAuth(fake_session([]), tokens=tokens)

    async def _refresh(*args: Any, **kwargs: Any) -> SomTodayTokens:
        return _tokens("rotated")

    with patch("custom_components.sometoday.auth.async_refresh_tokens", new=_refresh):
        refreshed = await auth.async_refresh()

    assert refreshed.refresh_token == "rotated"
    assert refreshed.account_id == "account-1"
    assert refreshed.student_id == 1234
    assert refreshed.student_name == "Eli Saado"


@pytest.mark.asyncio
async def test_holder_refresh_without_token(fake_session: Any) -> None:
    """Refreshing without a refresh token raises SomTodayAuthError."""
    tokens = _tokens()
    tokens.refresh_token = ""
    auth = SomTodayAuth(fake_session([]), tokens=tokens)

    with pytest.raises(SomTodayAuthError):
        await auth.async_refresh()


def test_holder_as_entry_data(fake_session: Any) -> None:
    """as_entry_data persists the refresh token, api_url and metadata."""
    tokens = _tokens()
    tokens.account_id = "account-1"
    tokens.student_id = 1234
    tokens.student_name = "Eli Saado"
    auth = SomTodayAuth(fake_session([]), tokens=tokens)

    data = auth.as_entry_data()

    assert data["refresh_token"] == "refresh"
    assert data["api_url"] == "https://api.somtoday.nl"
    assert data["account_id"] == "account-1"
    assert data["student_id"] == 1234
    assert data["student_name"] == "Eli Saado"
    assert "access_token" not in data


def test_holder_as_entry_data_without_tokens(fake_session: Any) -> None:
    """as_entry_data raises when no tokens are present."""
    auth = SomTodayAuth(fake_session([]))

    with pytest.raises(SomTodayAuthError):
        auth.as_entry_data()


# ---------------------------------------------------------------------------
# Additional independent probes (tester-agent)
# ---------------------------------------------------------------------------
def test_extract_code_header_block_prefers_location_over_cookie() -> None:
    """A cookie/header ``code=`` must not shadow the Location redirect code."""
    pasted = (
        "HTTP/1.1 302 Found\r\n"
        "Set-Cookie: code=COOKIEVALUE; Path=/\r\n"
        "Location: somtoday://callback?code=REALCODE&state=STATE\r\n"
    )

    assert extract_code(pasted, "STATE") == "REALCODE"


class _YieldingSession:
    """A session whose POST yields to the event loop, exposing refresh races."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls = 0

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(0.01)
        return self._response


@pytest.mark.asyncio
async def test_holder_ensure_valid_serialises_concurrent_refreshes(
    fake_response: Any,
) -> None:
    """Concurrent ensure_valid calls trigger exactly one token refresh.

    Architecture §3.4 requires refresh to be serialised with an ``asyncio.Lock``
    so a rotating refresh token cannot be raced. Without the lock the second
    caller would observe the still-expiring token and issue a second request.
    """
    session = _YieldingSession(fake_response(200, json_data=dict(TOKEN_PAYLOAD)))
    tokens = _tokens()
    tokens.expires_at = datetime.now(UTC) + timedelta(seconds=10)
    auth = SomTodayAuth(session, tokens=tokens)

    await asyncio.gather(
        auth.async_ensure_valid(),
        auth.async_ensure_valid(),
        auth.async_ensure_valid(),
    )

    assert session.calls == 1
    assert auth.tokens is not None
    assert auth.tokens.access_token == "access"
