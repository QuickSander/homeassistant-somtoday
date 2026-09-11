"""Unit tests for the SomToday OAuth2 authentication client.

All HTTP is mocked through ``FakeSession``; the real SomToday API is never
called.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest

from custom_components.sometoday.auth import SomTodayAuthClient, async_get_schools
from custom_components.sometoday.const import (
    AUTH_METHOD_PASSWORD,
    CLIENT_ID_APP,
    CLIENT_ID_SSO,
    CONF_AUTH_METHOD,
    LOGIN_BASE_URL,
    PASSWORD_FIELD,
    PKCE_CHARSET,
    TOKEN_URL,
    TOKEN_URL_SSO,
    USERNAME_FIELD,
)
from custom_components.sometoday.exceptions import (
    SomTodayApiError,
    SomTodayAuthError,
    SomTodayConnectionError,
    SomTodayRateLimitError,
)
from custom_components.sometoday.models import SomTodayTokens

TENANT = "099ce144-c400-4468-95d4-ad36f9f5cb5c"
USERNAME = "450000@live.bc-enschede.nl"
PASSWORD = "secret"

AUTH_LOCATION = "https://inloggen.somtoday.nl/?auth=SESSION123"
FINAL_LOCATION = (
    "somtoday://nl.topicus.somtoday.leerling/oauth/callback?code=FINAL123"
)
TOKEN_PAYLOAD: dict[str, Any] = {
    "access_token": "access",
    "refresh_token": "refresh",
    "somtoday_api_url": "https://api.somtoday.nl",
    "somtoday_tenant": "bonhoeffer",
    "token_type": "Bearer",
    "scope": "openid",
    "expires_in": 3600,
}


def _pkce_script(
    fake_response: Any,
    *,
    username_password_flow: bool,
    token_response: Any = None,
) -> list[Any]:
    """Build the scripted response sequence for a PKCE login."""
    form_location = AUTH_LOCATION if username_password_flow else f"{LOGIN_BASE_URL}/login"
    return [
        fake_response(
            302,
            headers={"Location": AUTH_LOCATION},
            cookies={"production-authenticator-stickiness": "stick"},
        ),
        fake_response(200, cookies={"JSESSIONID": "jsess"}),
        fake_response(302, headers={"Location": form_location}),
        fake_response(302, headers={"Location": FINAL_LOCATION}),
        fake_response(200, json_data=token_response or dict(TOKEN_PAYLOAD)),
    ]


@pytest.mark.asyncio
async def test_pkce_username_first_flow(fake_session: Any, fake_response: Any) -> None:
    """The username-first flow submits the password separately and exchanges the code."""
    session = fake_session(_pkce_script(fake_response, username_password_flow=False))
    auth = SomTodayAuthClient(session, TENANT)

    before = datetime.now(UTC)
    tokens = await auth.async_login(USERNAME, PASSWORD)

    assert len(session.calls) == 5
    # Step 1: authorize request.
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://inloggen.somtoday.nl/oauth2/authorize"
    params = kwargs["params"]
    assert params["client_id"] == CLIENT_ID_APP
    assert params["tenant_uuid"] == TENANT
    assert params["code_challenge_method"] == "S256"
    assert params["response_type"] == "code"
    assert len(params["state"]) == 8
    # Step 2: login session established with the stickiness cookie.
    assert session.calls[1][2]["params"] == {"auth": "SESSION123"}
    assert session.calls[1][2]["cookies"]["production-authenticator-stickiness"] == "stick"
    # Step 3: username submitted.
    assert session.calls[2][1] == f"{LOGIN_BASE_URL}/0-1.-panel-signInForm"
    assert session.calls[2][2]["data"] == {USERNAME_FIELD: USERNAME}
    assert session.calls[2][2]["cookies"]["JSESSIONID"] == "jsess"
    # Step 4: username-first password step.
    assert session.calls[3][1] == f"{LOGIN_BASE_URL}/login?2-1.-passwordForm"
    assert session.calls[3][2]["data"][PASSWORD_FIELD] == PASSWORD
    # Step 5: token exchange.
    token_call = session.calls[4]
    assert token_call[1] == TOKEN_URL
    token_data = token_call[2]["data"]
    assert token_data["grant_type"] == "authorization_code"
    assert token_data["code"] == "FINAL123"
    assert token_data["client_id"] == CLIENT_ID_APP
    expected_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(token_data["code_verifier"].encode("ascii")).digest()
        )
        .decode("ascii")
        .rstrip("=")
    )
    assert params["code_challenge"] == expected_challenge

    assert tokens.access_token == "access"
    assert tokens.refresh_token == "refresh"
    assert tokens.api_url == "https://api.somtoday.nl"
    assert auth.tokens is tokens
    assert before + timedelta(seconds=3500) < tokens.expires_at < before + timedelta(seconds=3700)


@pytest.mark.asyncio
async def test_pkce_username_password_flow(fake_session: Any, fake_response: Any) -> None:
    """The username+password flow submits both fields in a single POST."""
    session = fake_session(_pkce_script(fake_response, username_password_flow=True))
    auth = SomTodayAuthClient(session, TENANT)

    await auth.async_login(USERNAME, PASSWORD)

    assert session.calls[3][1] == f"{LOGIN_BASE_URL}/?0-1.-panel-signInForm"
    data = session.calls[3][2]["data"]
    assert data[USERNAME_FIELD] == USERNAME
    assert data[PASSWORD_FIELD] == PASSWORD


@pytest.mark.asyncio
async def test_sso_school_falls_back_to_password_grant(
    fake_session: Any, fake_response: Any
) -> None:
    """An external IdP redirect triggers the legacy password grant fallback."""
    session = fake_session(
        [
            fake_response(302, headers={"Location": "https://idp.example.com/login"}),
            fake_response(200, json_data=dict(TOKEN_PAYLOAD)),
        ]
    )
    auth = SomTodayAuthClient(session, TENANT)

    tokens = await auth.async_login(USERNAME, PASSWORD)

    assert len(session.calls) == 2
    method, url, kwargs = session.calls[1]
    assert method == "POST"
    assert url == TOKEN_URL_SSO
    assert kwargs["data"] == {
        "grant_type": "password",
        "username": f"{TENANT}\\{USERNAME}",
        "password": PASSWORD,
        "scope": "openid",
        "client_id": CLIENT_ID_SSO,
    }
    assert tokens.access_token == "access"


@pytest.mark.asyncio
async def test_invalid_credentials_do_not_fall_back(
    fake_session: Any, fake_response: Any
) -> None:
    """A rejected token exchange raises SomTodayAuthError without the fallback."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[-1] = fake_response(400, json_data={"error": "invalid_grant"})
    session = fake_session(script)
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayAuthError):
        await auth.async_login(USERNAME, PASSWORD)

    # The fallback endpoint must not have been called.
    assert all(call[1] != TOKEN_URL_SSO for call in session.calls)


@pytest.mark.asyncio
async def test_missing_authorization_code(fake_session: Any, fake_response: Any) -> None:
    """A password step without a code raises SomTodayAuthError."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[3] = fake_response(302, headers={"Location": f"{LOGIN_BASE_URL}/error"})
    session = fake_session(script)
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayAuthError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_network_error_maps_to_connection_error(
    fake_session: Any,
) -> None:
    """Network failures are mapped to SomTodayConnectionError."""
    session = fake_session([aiohttp.ClientError("boom")])
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayConnectionError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_post_network_error_maps_to_connection_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A network failure during a POST is mapped to SomTodayConnectionError."""
    session = fake_session(
        [
            fake_response(302, headers={"Location": AUTH_LOCATION}),
            fake_response(200),
            aiohttp.ClientError("boom"),
        ]
    )
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayConnectionError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_refresh_after_password_grant_uses_sso_endpoint(
    fake_session: Any, fake_response: Any
) -> None:
    """Refreshing a password-grant session uses the SSO token endpoint."""
    session = fake_session(
        [
            fake_response(302, headers={"Location": "https://idp.example.com/login"}),
            fake_response(200, json_data=dict(TOKEN_PAYLOAD)),
            fake_response(200, json_data={**TOKEN_PAYLOAD, "refresh_token": "rotated"}),
        ]
    )
    auth = SomTodayAuthClient(session, TENANT)

    await auth.async_login(USERNAME, PASSWORD)
    await auth.async_refresh()

    assert session.calls[2][1] == TOKEN_URL_SSO
    assert session.calls[2][2]["data"]["client_id"] == CLIENT_ID_SSO


@pytest.mark.asyncio
async def test_refresh_after_pkce_login_uses_pkce_endpoint(
    fake_session: Any, fake_response: Any
) -> None:
    """Refreshing a PKCE session uses the inloggen token endpoint."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script.append(fake_response(200, json_data={**TOKEN_PAYLOAD, "refresh_token": "rotated"}))
    session = fake_session(script)
    auth = SomTodayAuthClient(session, TENANT)

    await auth.async_login(USERNAME, PASSWORD)
    await auth.async_refresh()

    refresh_call = session.calls[-1]
    assert refresh_call[1] == TOKEN_URL
    assert refresh_call[2]["data"]["client_id"] == CLIENT_ID_APP


@pytest.mark.asyncio
async def test_token_endpoint_server_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A 5xx token response maps to SomTodayApiError (architecture 5.1)."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[-1] = fake_response(500)
    auth = SomTodayAuthClient(fake_session(script), TENANT)

    with pytest.raises(SomTodayApiError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_token_endpoint_invalid_json(
    fake_session: Any, fake_response: Any
) -> None:
    """A non-JSON token response maps to SomTodayApiError."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[-1] = fake_response(200)
    auth = SomTodayAuthClient(fake_session(script), TENANT)

    with pytest.raises(SomTodayApiError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_token_endpoint_unexpected_payload(
    fake_session: Any, fake_response: Any
) -> None:
    """A JSON array or incomplete payload maps to SomTodayApiError."""
    for payload in (["nope"], {"somtoday_api_url": "https://api.somtoday.nl"}):
        script = _pkce_script(fake_response, username_password_flow=False)
        script[-1] = fake_response(200, json_data=payload)
        auth = SomTodayAuthClient(fake_session(script), TENANT)

        with pytest.raises(SomTodayApiError):
            await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_refresh_rotates_refresh_token(
    fake_session: Any, fake_response: Any
) -> None:
    """A rotating refresh token replaces the stored one."""
    rotated = {**TOKEN_PAYLOAD, "refresh_token": "rotated"}
    session = fake_session([fake_response(200, json_data=rotated)])
    auth = SomTodayAuthClient(session, TENANT)
    auth.tokens = SomTodayTokens(
        access_token="old",
        refresh_token="oldrefresh",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC),
    )

    tokens = await auth.async_refresh()

    assert tokens.refresh_token == "rotated"
    assert auth.tokens is not None
    assert auth.tokens.refresh_token == "rotated"
    assert session.calls[0][1] == TOKEN_URL
    assert session.calls[0][2]["data"]["refresh_token"] == "oldrefresh"
    assert session.calls[0][2]["data"]["client_id"] == CLIENT_ID_APP


@pytest.mark.asyncio
async def test_refresh_keeps_token_when_not_rotated(
    fake_session: Any, fake_response: Any
) -> None:
    """When SomToday does not rotate, the existing refresh token is kept."""
    payload = {k: v for k, v in TOKEN_PAYLOAD.items() if k != "refresh_token"}
    session = fake_session([fake_response(200, json_data=payload)])
    auth = SomTodayAuthClient(session, TENANT)
    auth.tokens = SomTodayTokens(
        access_token="old",
        refresh_token="oldrefresh",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC),
    )

    tokens = await auth.async_refresh()

    assert tokens.refresh_token == "oldrefresh"


@pytest.mark.asyncio
async def test_refresh_rejected(fake_session: Any, fake_response: Any) -> None:
    """A rejected refresh raises SomTodayAuthError."""
    session = fake_session([fake_response(400)])
    auth = SomTodayAuthClient(session, TENANT)
    auth.tokens = SomTodayTokens(
        access_token="old",
        refresh_token="oldrefresh",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC),
    )

    with pytest.raises(SomTodayAuthError):
        await auth.async_refresh()


@pytest.mark.asyncio
async def test_refresh_without_token(fake_session: Any) -> None:
    """Refreshing without a stored refresh token raises SomTodayAuthError."""
    session = fake_session([])
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayAuthError):
        await auth.async_refresh()


@pytest.mark.asyncio
async def test_ensure_valid_refreshes_expiring_token(
    fake_session: Any, fake_response: Any
) -> None:
    """async_ensure_valid refreshes a token that is about to expire."""
    session = fake_session([fake_response(200, json_data=dict(TOKEN_PAYLOAD))])
    auth = SomTodayAuthClient(session, TENANT)
    auth.tokens = SomTodayTokens(
        access_token="old",
        refresh_token="oldrefresh",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )

    await auth.async_ensure_valid()

    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_ensure_valid_skips_fresh_token(fake_session: Any) -> None:
    """async_ensure_valid does not refresh a valid token."""
    session = fake_session([])
    auth = SomTodayAuthClient(session, TENANT)
    auth.tokens = SomTodayTokens(
        access_token="fresh",
        refresh_token="refresh",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    await auth.async_ensure_valid()

    assert session.calls == []


@pytest.mark.asyncio
async def test_ensure_valid_without_tokens(fake_session: Any) -> None:
    """async_ensure_valid raises when no tokens are present."""
    auth = SomTodayAuthClient(fake_session([]), TENANT)

    with pytest.raises(SomTodayAuthError):
        await auth.async_ensure_valid()


def test_generate_pkce_pair(fake_session: Any) -> None:
    """The PKCE verifier matches the documented alphabet and challenge."""
    auth = SomTodayAuthClient(fake_session([]), TENANT)

    verifier, challenge = auth._generate_pkce_pair()

    assert len(verifier) == 128
    assert set(verifier) <= set(PKCE_CHARSET)
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert challenge == expected

    other_verifier, _ = auth._generate_pkce_pair()
    assert other_verifier != verifier


def test_extract_query_params(fake_session: Any) -> None:
    """Query parameters are extracted from redirect locations."""
    auth = SomTodayAuthClient(fake_session([]), TENANT)

    assert auth._extract_code(FINAL_LOCATION) == "FINAL123"
    assert auth._extract_code(AUTH_LOCATION) is None
    assert auth._extract_auth(AUTH_LOCATION) == "SESSION123"
    assert auth._extract_code("") is None


@pytest.mark.asyncio
async def test_get_schools(fake_session: Any, fake_response: Any) -> None:
    """The school list is parsed into School models."""
    payload = [
        {
            "instellingen": [
                {
                    "uuid": "u1",
                    "naam": "Etty Hillesum Lyceum",
                    "plaats": "DEVENTER",
                    "oidcurls": [],
                },
                {"uuid": "u2", "naam": "Marianum", "plaats": "GROENLO"},
            ]
        }
    ]
    session = fake_session([fake_response(200, json_data=payload)])

    schools = await async_get_schools(session)

    assert [school.uuid for school in schools] == ["u1", "u2"]
    assert schools[0].name == "Etty Hillesum Lyceum"
    assert schools[0].has_oidc is False
    assert session.calls[0][1] == "https://servers.somtoday.nl/organisaties.json"


@pytest.mark.asyncio
async def test_get_schools_connection_error(fake_session: Any) -> None:
    """A network error while fetching schools maps to SomTodayConnectionError."""
    session = fake_session([aiohttp.ClientError("nope")])

    with pytest.raises(SomTodayConnectionError):
        await async_get_schools(session)


@pytest.mark.asyncio
async def test_get_schools_malformed_payload(
    fake_session: Any, fake_response: Any
) -> None:
    """A malformed school list maps to SomTodayApiError."""
    session = fake_session([fake_response(200, json_data="not-a-list")])

    with pytest.raises(SomTodayApiError):
        await async_get_schools(session)


# ---------------------------------------------------------------------------
# Additional coverage for behavioural paths not exercised by the first pass.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_timeout_maps_to_connection_error(fake_session: Any) -> None:
    """A timeout during the authorize GET maps to SomTodayConnectionError."""
    session = fake_session([TimeoutError("timed out")])
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayConnectionError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_post_timeout_maps_to_connection_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A timeout during a POST is mapped to SomTodayConnectionError."""
    session = fake_session(
        [
            fake_response(302, headers={"Location": AUTH_LOCATION}),
            fake_response(200),
            TimeoutError("timed out"),
        ]
    )
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayConnectionError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_token_endpoint_auth_status_maps_to_auth_error(
    fake_session: Any, fake_response: Any, status: int
) -> None:
    """Token endpoint 401/403 responses map to SomTodayAuthError."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[-1] = fake_response(status)
    auth = SomTodayAuthClient(fake_session(script), TENANT)

    with pytest.raises(SomTodayAuthError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_ensure_valid_propagates_refresh_failure(
    fake_session: Any, fake_response: Any
) -> None:
    """A failed refresh inside async_ensure_valid propagates SomTodayAuthError."""
    session = fake_session([fake_response(400, json_data={"error": "invalid_grant"})])
    auth = SomTodayAuthClient(session, TENANT)
    auth.tokens = SomTodayTokens(
        access_token="old",
        refresh_token="oldrefresh",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC),
    )

    with pytest.raises(SomTodayAuthError):
        await auth.async_ensure_valid()


@pytest.mark.asyncio
async def test_get_schools_http_error_status_maps_to_api_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A 5xx school list response maps to SomTodayApiError (architecture 5.1)."""
    session = fake_session([fake_response(500)])

    with pytest.raises(SomTodayApiError):
        await async_get_schools(session)


@pytest.mark.asyncio
async def test_get_schools_invalid_json_maps_to_api_error(
    fake_session: Any, fake_response: Any
) -> None:
    """Invalid JSON from the school list maps to SomTodayApiError."""
    session = fake_session([fake_response(200)])

    with pytest.raises(SomTodayApiError):
        await async_get_schools(session)


@pytest.mark.asyncio
async def test_refresh_preserves_api_url_and_tenant_when_omitted(
    fake_session: Any, fake_response: Any
) -> None:
    """Refresh keeps api_url/tenant if the response omits them."""
    session = fake_session(
        [
            fake_response(
                200,
                json_data={
                    "access_token": "new",
                    "refresh_token": "newrefresh",
                    "expires_in": 3600,
                },
            )
        ]
    )
    auth = SomTodayAuthClient(session, TENANT)
    auth.tokens = SomTodayTokens(
        access_token="old",
        refresh_token="oldrefresh",
        api_url="https://school-specific.example/api",
        tenant="school",
        expires_at=datetime.now(UTC),
    )

    tokens = await auth.async_refresh()

    assert tokens.api_url == "https://school-specific.example/api"
    assert tokens.tenant == "school"


# ---------------------------------------------------------------------------
# Regression tests for review findings B3/B4 and the 429/cookie findings.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_authorize_server_error_does_not_fall_back(
    fake_session: Any, fake_response: Any
) -> None:
    """An authorize 5xx is an ApiError and must not trigger the password fallback."""
    session = fake_session([fake_response(500)])
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayApiError):
        await auth.async_login(USERNAME, PASSWORD)

    assert len(session.calls) == 1
    assert all(call[1] != TOKEN_URL_SSO for call in session.calls)


@pytest.mark.asyncio
async def test_authorize_client_error_maps_to_auth_error(
    fake_session: Any, fake_response: Any
) -> None:
    """An authorize 4xx maps to SomTodayAuthError and does not fall back."""
    session = fake_session([fake_response(400)])
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayAuthError):
        await auth.async_login(USERNAME, PASSWORD)

    assert all(call[1] != TOKEN_URL_SSO for call in session.calls)


@pytest.mark.asyncio
async def test_auth_method_property_tracks_login_method(
    fake_session: Any, fake_response: Any
) -> None:
    """auth_method reflects the method of the last login."""
    pkce = SomTodayAuthClient(
        fake_session(_pkce_script(fake_response, username_password_flow=False)), TENANT
    )
    assert pkce.auth_method == "pkce"
    await pkce.async_login(USERNAME, PASSWORD)
    assert pkce.auth_method == "pkce"

    sso = SomTodayAuthClient(
        fake_session(
            [
                fake_response(
                    302, headers={"Location": "https://idp.example.com/login"}
                ),
                fake_response(200, json_data=dict(TOKEN_PAYLOAD)),
            ]
        ),
        TENANT,
    )
    await sso.async_login(USERNAME, PASSWORD)
    assert sso.auth_method == "password"


@pytest.mark.asyncio
async def test_as_entry_data_includes_auth_method(
    fake_session: Any, fake_response: Any
) -> None:
    """The persistable entry data includes the refresh pairing's auth method."""
    sso = SomTodayAuthClient(
        fake_session(
            [
                fake_response(
                    302, headers={"Location": "https://idp.example.com/login"}
                ),
                fake_response(200, json_data=dict(TOKEN_PAYLOAD)),
            ]
        ),
        TENANT,
    )
    await sso.async_login(USERNAME, PASSWORD)

    entry_data = sso.as_entry_data()

    assert entry_data[CONF_AUTH_METHOD] == AUTH_METHOD_PASSWORD
    assert entry_data["refresh_token"] == "refresh"
    assert "access_token" not in entry_data

    with pytest.raises(SomTodayAuthError):
        SomTodayAuthClient(fake_session([]), TENANT).as_entry_data()


@pytest.mark.asyncio
async def test_restored_password_session_refreshes_against_sso_endpoint(
    fake_session: Any, fake_response: Any
) -> None:
    """A restart restores the password-grant refresh pairing from the entry."""
    entry = SimpleNamespace(
        data={
            "refresh_token": "stored",
            "api_url": "https://api.somtoday.nl",
            CONF_AUTH_METHOD: AUTH_METHOD_PASSWORD,
        }
    )
    session = fake_session([fake_response(200, json_data=dict(TOKEN_PAYLOAD))])
    auth = SomTodayAuthClient(
        session, TENANT, auth_method=entry.data[CONF_AUTH_METHOD]
    )
    auth.tokens = SomTodayTokens.from_entry(entry)

    await auth.async_refresh()

    assert session.calls[0][1] == TOKEN_URL_SSO
    assert session.calls[0][2]["data"]["client_id"] == CLIENT_ID_SSO


@pytest.mark.asyncio
async def test_token_endpoint_rate_limit_maps_to_rate_limit_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A 429 token response maps to SomTodayRateLimitError (architecture 5.1)."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[-1] = fake_response(429)
    auth = SomTodayAuthClient(fake_session(script), TENANT)

    with pytest.raises(SomTodayRateLimitError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_login_resets_cookies_between_attempts(
    fake_session: Any, fake_response: Any
) -> None:
    """A re-login does not send cookies from the previous attempt."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script += _pkce_script(fake_response, username_password_flow=False)
    session = fake_session(script)
    auth = SomTodayAuthClient(session, TENANT)

    await auth.async_login(USERNAME, PASSWORD)
    await auth.async_login(USERNAME, PASSWORD)

    # The second login's authorize request (index 5) must start cookie-less.
    assert session.calls[5][0] == "GET"
    assert session.calls[5][2]["cookies"] == {}


class _ErrorBodyResponse:
    """A response whose JSON body cannot be read (raises a scripted error)."""

    def __init__(self, error: Exception, status: int = 200) -> None:
        self._error = error
        self.status = status
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, str] = {}

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        raise self._error


@pytest.mark.asyncio
async def test_get_schools_rate_limit_maps_to_rate_limit_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A 429 school list response maps to SomTodayRateLimitError."""
    session = fake_session([fake_response(429)])

    with pytest.raises(SomTodayRateLimitError):
        await async_get_schools(session)


@pytest.mark.asyncio
async def test_get_schools_body_error_maps_to_connection_error(
    fake_session: Any,
) -> None:
    """A body-read error while fetching schools maps to SomTodayConnectionError."""
    session = fake_session([_ErrorBodyResponse(aiohttp.ClientError("boom"))])

    with pytest.raises(SomTodayConnectionError):
        await async_get_schools(session)


@pytest.mark.asyncio
async def test_authorize_without_login_session_raises_auth_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A 200 authorize page without an auth token is not treated as SSO-only."""
    session = fake_session([fake_response(200)])
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayAuthError):
        await auth.async_login(USERNAME, PASSWORD)

    assert all(call[1] != TOKEN_URL_SSO for call in session.calls)


@pytest.mark.asyncio
async def test_token_endpoint_unexpected_status_maps_to_connection_error(
    fake_session: Any, fake_response: Any
) -> None:
    """An unexpected non-2xx token status maps to SomTodayConnectionError."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[-1] = fake_response(404)
    auth = SomTodayAuthClient(fake_session(script), TENANT)

    with pytest.raises(SomTodayConnectionError):
        await auth.async_login(USERNAME, PASSWORD)


@pytest.mark.asyncio
async def test_token_endpoint_body_error_maps_to_connection_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A body-read error while parsing tokens maps to SomTodayConnectionError."""
    script = _pkce_script(fake_response, username_password_flow=False)
    script[-1] = _ErrorBodyResponse(aiohttp.ClientError("boom"))
    auth = SomTodayAuthClient(fake_session(script), TENANT)

    with pytest.raises(SomTodayConnectionError):
        await auth.async_login(USERNAME, PASSWORD)


# ---------------------------------------------------------------------------
# Second-pass coverage: the new login-form status checks and the only
# uncovered branch in _store_cookies.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("form_index", [2, 3])
async def test_login_form_error_maps_to_api_error_without_fallback(
    fake_session: Any, fake_response: Any, form_index: int
) -> None:
    """A 5xx on either login form step maps to SomTodayApiError, no fallback.

    ``form_index`` 2 is the username step, 3 is the password step. Both use
    ``_raise_for_error_status`` and must not be mistaken for an SSO-only school.
    """
    script = _pkce_script(fake_response, username_password_flow=False)
    script[form_index] = fake_response(
        500, headers={"Location": f"{LOGIN_BASE_URL}/login"}
    )
    session = fake_session(script)
    auth = SomTodayAuthClient(session, TENANT)

    with pytest.raises(SomTodayApiError):
        await auth.async_login(USERNAME, PASSWORD)

    assert all(call[1] != TOKEN_URL_SSO for call in session.calls)


class _Morsel:
    """Minimal ``http.cookies.Morsel`` stand-in exposing ``value``."""

    def __init__(self, value: str) -> None:
        self.value = value


def test_store_cookies_skips_empty_values_and_reads_morsels(
    fake_session: Any,
) -> None:
    """Empty cookie values are skipped; Morsel objects are unwrapped."""
    auth = SomTodayAuthClient(fake_session([]), TENANT)
    response = SimpleNamespace(
        cookies={
            "keep": _Morsel("kept"),
            "empty": _Morsel(""),
            "raw": "raw-value",
        }
    )

    auth._store_cookies(response)

    assert auth._cookies == {"keep": "kept", "raw": "raw-value"}


# ---------------------------------------------------------------------------
# Response lifecycle (review N5): every response must be released.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pkce_login_releases_every_response(
    fake_session: Any, fake_response: Any
) -> None:
    """The authorize, session, form and token responses are all released."""
    script = _pkce_script(fake_response, username_password_flow=False)
    session = fake_session(script)
    auth = SomTodayAuthClient(session, TENANT)

    await auth.async_login(USERNAME, PASSWORD)

    assert [response.release_count for response in script] == [1, 1, 1, 1, 1]


@pytest.mark.asyncio
async def test_sso_redirect_releases_authorize_response(
    fake_session: Any, fake_response: Any
) -> None:
    """The authorize response is released even when the SSO fallback runs."""
    authorize = fake_response(
        302, headers={"Location": "https://idp.example.com/login"}
    )
    script = [authorize, fake_response(200, json_data=dict(TOKEN_PAYLOAD))]
    auth = SomTodayAuthClient(fake_session(script), TENANT)

    await auth.async_login(USERNAME, PASSWORD)

    assert authorize.release_count == 1


@pytest.mark.asyncio
async def test_get_schools_releases_response(
    fake_session: Any, fake_response: Any
) -> None:
    """The school-list response is released after parsing."""
    response = fake_response(
        200, json_data=[{"instellingen": [{"uuid": "u1", "naam": "A"}]}]
    )
    session = fake_session([response])

    await async_get_schools(session)

    assert response.release_count == 1


@pytest.mark.asyncio
async def test_get_schools_releases_error_response(
    fake_session: Any, fake_response: Any
) -> None:
    """The school-list response must be released even on an error status."""
    response = fake_response(500)
    session = fake_session([response])

    with pytest.raises(SomTodayApiError):
        await async_get_schools(session)

    assert response.release_count == 1
