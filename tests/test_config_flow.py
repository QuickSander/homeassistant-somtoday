"""Tests for the SomToday config, reauth and options flows.

All SomToday HTTP calls are mocked; the real API is never contacted.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sometoday import (
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.sometoday.api import SomTodayApiClient
from custom_components.sometoday.auth import SomTodayAuth
from custom_components.sometoday.const import (
    CONF_ACCOUNT_ID,
    CONF_API_URL,
    CONF_ENABLE_ABSENCE,
    CONF_ENABLE_GRADES,
    CONF_ENABLE_HOMEWORK,
    CONF_HOMEWORK_DAYS_AHEAD,
    CONF_REDIRECT_URL,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DAYS_AHEAD,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    DEFAULT_API_URL,
    DOMAIN,
)
from custom_components.sometoday.exceptions import (
    SomTodayApiError,
    SomTodayConnectionError,
    SomtodayInvalidAuth,
)
from custom_components.sometoday.models import Account, SomTodayTokens, Student

API_URL = "https://api.somtoday.nl"
REDIRECT_BASE = "somtoday://nl.topicus.somtoday.leerling/oauth/callback"

ACCOUNT = Account(id="account-1", username="eli@example.com")
STUDENT = Student(id=1234, leerlingnummer="450000", roepnaam="Eli", achternaam="Saado")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Iterator[None]:
    """Enable loading the custom integration in every test."""
    yield


def _tokens(refresh_token: str = "refresh") -> SomTodayTokens:
    """Return a set of fresh tokens for the fake exchange."""
    return SomTodayTokens(
        access_token="access",
        refresh_token=refresh_token,
        api_url=API_URL,
        expires_at=datetime.now(UTC) + timedelta(seconds=3600),
    )


async def _fake_exchange(
    session: Any, code: str, code_verifier: str
) -> SomTodayTokens:
    """Fake a successful code exchange."""
    return _tokens()


async def _fake_account(self: SomTodayApiClient) -> Account:
    """Fake the account response."""
    return ACCOUNT


async def _fake_students(self: SomTodayApiClient) -> list[Student]:
    """Fake the student list response."""
    return [STUDENT]


async def _noop_ensure_valid(self: SomTodayAuth) -> None:
    """Skip token refresh during flow tests."""


@contextmanager
def _patched_login(
    *,
    exchange: Any = None,
    account_error: Exception | None = None,
    students: list[Student] | None = None,
    students_error: Exception | None = None,
) -> Iterator[None]:
    """Patch the exchange and account/student discovery used by the flow."""
    exchange = exchange or _fake_exchange
    if account_error is not None:
        account_patch = patch.object(
            SomTodayApiClient, "async_get_account", side_effect=account_error
        )
    else:
        account_patch = patch.object(
            SomTodayApiClient, "async_get_account", new=_fake_account
        )

    if students_error is not None:
        students_patch = patch.object(
            SomTodayApiClient, "async_get_students", side_effect=students_error
        )
    else:
        selected = list(students if students is not None else [STUDENT])

        async def _students(self: SomTodayApiClient) -> list[Student]:
            return selected

        students_patch = patch.object(
            SomTodayApiClient, "async_get_students", new=_students
        )

    with (
        patch(
            "custom_components.sometoday.config_flow.async_exchange_code",
            new=exchange,
        ),
        account_patch,
        students_patch,
        patch.object(SomTodayAuth, "async_ensure_valid", new=_noop_ensure_valid),
    ):
        yield


def _auth_url(result: dict[str, Any]) -> str:
    """Return the authorize URL shown by the form."""
    return result["description_placeholders"]["auth_url"]


def _state_from_url(url: str) -> str:
    """Extract the state query parameter from the authorize URL."""
    return parse_qs(urlparse(url).query)["state"][0]


def _redirect(code: str = "THECODE", state: str | None = None) -> str:
    """Build a somtoday:// redirect for the given code/state."""
    url = f"{REDIRECT_BASE}?code={code}"
    if state is not None:
        url = f"{url}&state={state}"
    return url


def _make_entry(hass: Any, *, refresh_token: str = "old-refresh") -> MockConfigEntry:
    """Create and register an entry suitable for setup/reauth tests."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        data={
            CONF_REFRESH_TOKEN: refresh_token,
            CONF_API_URL: API_URL,
            CONF_ACCOUNT_ID: "account-1",
            CONF_STUDENT_ID: STUDENT.id,
            CONF_STUDENT_NAME: "Eli Saado",
        },
    )
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# async_step_user
# ---------------------------------------------------------------------------
async def test_user_flow_success(hass: Any) -> None:
    """A valid paste creates an entry with the account metadata."""
    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        auth_url = _auth_url(result)
        assert "tenant_uuid" not in auth_url
        assert "code_challenge_method=S256" in auth_url

        state = _state_from_url(auth_url)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SomToday Eli Saado"
    assert result["data"][CONF_REFRESH_TOKEN] == "refresh"
    assert result["data"][CONF_API_URL] == API_URL
    assert result["data"][CONF_ACCOUNT_ID] == "account-1"
    assert result["data"][CONF_STUDENT_ID] == STUDENT.id
    assert result["data"][CONF_STUDENT_NAME] == "Eli Saado"

    entries = hass.config_entries.async_entries(DOMAIN)
    assert entries[0].unique_id == "account-1"


async def test_user_flow_bare_code(hass: Any) -> None:
    """A bare code is accepted without state validation."""
    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: "ABCDEFGHIJKLMNOP"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_account_fallback_to_student_id(hass: Any) -> None:
    """When /account/me fails, the student id becomes the unique id."""
    with _patched_login(account_error=SomTodayApiError("no account endpoint")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ACCOUNT_ID] == str(STUDENT.id)


async def test_user_flow_duplicate_aborts(hass: Any) -> None:
    """An account that is already configured aborts the flow."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        data={CONF_REFRESH_TOKEN: "x", CONF_API_URL: API_URL},
    )
    existing.add_to_hass(hass)

    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_no_students(hass: Any) -> None:
    """An empty student list shows no_students."""
    with _patched_login(students=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_students"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SomtodayInvalidAuth("bad code"), "invalid_auth"),
        (SomTodayConnectionError("offline"), "cannot_connect"),
        (SomTodayApiError("malformed"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_exchange_errors(
    hass: Any, error: Exception, expected: str
) -> None:
    """Exchange failures map to the documented error keys."""

    async def _exchange(session: Any, code: str, code_verifier: str) -> Any:
        raise error

    with _patched_login(exchange=_exchange):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": expected}


async def test_user_flow_login_page_paste(hass: Any) -> None:
    """Pasting the login page reports login_page."""
    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_REDIRECT_URL: "https://inloggen.somtoday.nl/?auth=SESSION"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "login_page"}


async def test_user_flow_state_mismatch(hass: Any) -> None:
    """A redirect with a wrong state reports state_mismatch."""
    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state="WRONG")}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "state_mismatch"}


async def test_user_flow_invalid_url(hass: Any) -> None:
    """Unstructured input reports invalid_url."""
    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: "not a code"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}


async def test_user_flow_sso_callback_paste(hass: Any) -> None:
    """Pasting the Microsoft Entra ID callback reports sso_callback."""
    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_REDIRECT_URL: (
                    "https://inloggen.somtoday.nl/oidc?code=1.AQUAabc"
                    "&state=dc4c605eb4&session_state=008b30ea-1234"
                )
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "sso_callback"}


async def test_authorize_url_kept_on_recoverable_paste(hass: Any) -> None:
    """A paste mistake must not invalidate the user's open login."""
    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        first_url = _auth_url(result)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: "not a code"}
        )
        second_url = _auth_url(result)

    assert first_url == second_url


async def test_authorize_url_regenerated_when_spent(hass: Any) -> None:
    """A definitive rejection mints a new PKCE pair + state."""
    calls = 0

    async def _exchange(session: Any, code: str, code_verifier: str) -> Any:
        nonlocal calls
        calls += 1
        raise SomtodayInvalidAuth("spent")

    with _patched_login(exchange=_exchange):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        first_url = _auth_url(result)
        state = _state_from_url(first_url)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )
        second_url = _auth_url(result)

    assert calls == 1
    assert first_url != second_url


# ---------------------------------------------------------------------------
# Reauth
# ---------------------------------------------------------------------------
async def test_reauth_flow_updates_refresh_token(hass: Any) -> None:
    """A reauth stores the rotated refresh token and reloads the entry."""
    entry = _make_entry(hass)

    async def _rotating(session: Any, code: str, code_verifier: str) -> Any:
        return _tokens("rotated")

    with _patched_login(exchange=_rotating):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "rotated"
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth_flow_wrong_account(hass: Any) -> None:
    """A different account signing in aborts with wrong_account."""
    entry = _make_entry(hass)
    hass.config_entries.async_update_entry(entry, unique_id="some-other-account")

    with _patched_login():
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SomtodayInvalidAuth("bad"), "invalid_auth"),
        (SomTodayConnectionError("offline"), "cannot_connect"),
    ],
)
async def test_reauth_flow_errors(
    hass: Any, error: Exception, expected: str
) -> None:
    """Reauth maps exchange failures to the documented error keys."""
    entry = _make_entry(hass)

    async def _exchange(session: Any, code: str, code_verifier: str) -> Any:
        raise error

    with _patched_login(exchange=_exchange):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": expected}


async def test_reauth_after_failed_setup_reloads_entry(hass: Any) -> None:
    """A reauth recovers an entry stuck in SETUP_ERROR back to LOADED.

    Regression test for review B1: without a reload the entry stays broken even
    though the reauth flow reports success.
    """
    entry = _make_entry(hass)

    with patch.object(
        SomTodayAuth,
        "async_ensure_valid",
        side_effect=SomtodayInvalidAuth("expired"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR

    async def _rotating(session: Any, code: str, code_verifier: str) -> Any:
        return _tokens("rotated")

    with _patched_login(exchange=_rotating):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "rotated"
    assert entry.state is ConfigEntryState.LOADED


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------
async def test_options_flow(hass: Any) -> None:
    """The options flow persists the poll interval and feature toggles."""
    entry = _make_entry(hass)

    with patch.object(SomTodayAuth, "async_ensure_valid", new=_noop_ensure_valid):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_SCAN_INTERVAL: 30,
                CONF_SCHEDULE_DAYS_AHEAD: 7,
                CONF_HOMEWORK_DAYS_AHEAD: 3,
                CONF_ENABLE_GRADES: False,
                "enable_homework": True,
                "enable_absence": True,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 30
    assert entry.options[CONF_ENABLE_GRADES] is False


async def test_options_flow_schedules_reload(hass: Any) -> None:
    """Saving options schedules an entry reload (architecture §4.1).

    There is no update listener, so the reload is the only mechanism that makes
    the new options take effect.
    """
    entry = _make_entry(hass)

    with patch.object(
        hass.config_entries, "async_schedule_reload"
    ) as schedule_reload:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_SCAN_INTERVAL: 30,
                CONF_SCHEDULE_DAYS_AHEAD: 7,
                CONF_HOMEWORK_DAYS_AHEAD: 3,
                CONF_ENABLE_GRADES: True,
                CONF_ENABLE_HOMEWORK: True,
                CONF_ENABLE_ABSENCE: True,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    schedule_reload.assert_called_once_with(entry.entry_id)


# ---------------------------------------------------------------------------
# Setup entry
# ---------------------------------------------------------------------------
async def test_setup_entry_refreshes_token(hass: Any, caplog: Any) -> None:
    """Setting up an entry refreshes and persists the rotated token."""
    entry = _make_entry(hass, refresh_token="old-refresh")

    async def _refresh(session: Any, refresh_token: str, **kwargs: Any) -> Any:
        return _tokens("new-refresh")

    with (
        caplog.at_level("INFO"),
        patch(
            "custom_components.sometoday.auth.async_refresh_tokens", new=_refresh
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.api.base_url == API_URL
    assert entry.data[CONF_REFRESH_TOKEN] == "new-refresh"
    assert "authenticated as Eli Saado (account account-1)" in caplog.text
    assert "new-refresh" not in caplog.text


async def test_setup_entry_keeps_refresh_token_when_not_rotated(hass: Any) -> None:
    """A non-rotating refresh response leaves the stored token untouched."""
    entry = _make_entry(hass, refresh_token="same-refresh")

    async def _refresh(session: Any, refresh_token: str, **kwargs: Any) -> Any:
        return _tokens("same-refresh")

    with patch(
        "custom_components.sometoday.auth.async_refresh_tokens", new=_refresh
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_REFRESH_TOKEN] == "same-refresh"


async def test_setup_entry_auth_failure(hass: Any) -> None:
    """A definitive rejection raises ConfigEntryAuthFailed."""
    entry = _make_entry(hass)

    with patch.object(
        SomTodayAuth,
        "async_ensure_valid",
        side_effect=SomtodayInvalidAuth("expired"),
    ), pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(hass, entry)


async def test_setup_entry_connection_failure(hass: Any) -> None:
    """A network failure during setup raises ConfigEntryNotReady."""
    entry = _make_entry(hass)

    with patch.object(
        SomTodayAuth,
        "async_ensure_valid",
        side_effect=SomTodayConnectionError("offline"),
    ), pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, entry)


async def test_setup_entry_unexpected_failure(hass: Any) -> None:
    """Any other SomToday error during setup raises ConfigEntryNotReady."""
    entry = _make_entry(hass)

    with patch.object(
        SomTodayAuth,
        "async_ensure_valid",
        side_effect=SomTodayApiError("boom"),
    ), pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, entry)


async def test_async_migrate_entry(hass: Any) -> None:
    """The migration hook accepts the current schema."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True


async def test_async_unload_entry(hass: Any) -> None:
    """Unloading an entry without platforms succeeds."""
    entry = _make_entry(hass)

    assert await async_unload_entry(hass, entry) is True


def test_default_api_url_constant() -> None:
    """The default API URL is the documented SomToday host."""
    assert DEFAULT_API_URL == "https://api.somtoday.nl"
