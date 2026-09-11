"""Tests for the SomToday config and options flow.

All SomToday HTTP calls are mocked; the real API is never contacted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sometoday import (
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.sometoday.api import SomTodayApiClient
from custom_components.sometoday.auth import SomTodayAuthClient
from custom_components.sometoday.config_flow import _school_option
from custom_components.sometoday.const import (
    CONF_API_URL,
    CONF_AUTH_METHOD,
    CONF_ENABLE_GRADES,
    CONF_HOMEWORK_DAYS_AHEAD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DAYS_AHEAD,
    CONF_SCHOOL_NAME,
    CONF_STUDENT_ID,
    CONF_TENANT_UUID,
    CONF_USERNAME,
    DEFAULT_API_URL,
    DOMAIN,
)
from custom_components.sometoday.exceptions import (
    SomTodayAuthError,
    SomTodayConnectionError,
    SomTodayError,
    SomTodaySsoNotSupported,
)
from custom_components.sometoday.models import School, SomTodayTokens, Student

TENANT = "099ce144-c400-4468-95d4-ad36f9f5cb5c"
USERNAME = "450000@live.bc-enschede.nl"
PASSWORD = "secret"
API_URL = "https://api.somtoday.nl"

SCHOOL = School(uuid=TENANT, name="Etty Hillesum Lyceum", place="Enschede")
STUDENT = Student(id=1234, leerlingnummer="450000", roepnaam="Eli", achternaam="Saado")
OTHER_STUDENT = Student(id=5678, leerlingnummer="450001", roepnaam="Sam")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Any:
    """Enable loading the custom integration in every test."""
    yield


def _tokens(refresh_token: str = "refresh") -> SomTodayTokens:
    """Return a set of fresh tokens for the fake login."""
    return SomTodayTokens(
        access_token="access",
        refresh_token=refresh_token,
        api_url=API_URL,
        expires_at=datetime.now(UTC) + timedelta(seconds=3600),
    )


async def _fake_login(
    self: SomTodayAuthClient, username: str, password: str, *, refresh_token: str = "refresh"
) -> SomTodayTokens:
    """Fake a successful login that stores the tokens on the client."""
    self.tokens = _tokens(refresh_token)
    return self.tokens


async def _fake_students(self: SomTodayApiClient) -> list[Student]:
    """Fake the student list response."""
    return [STUDENT]


def _login_patch(refresh_token: str = "refresh"):
    """Patch ``SomTodayAuthClient.async_login`` with a fake login."""

    async def _login(self: SomTodayAuthClient, username: str, password: str) -> Any:
        return await _fake_login(self, username, password, refresh_token=refresh_token)

    return patch.object(SomTodayAuthClient, "async_login", new=_login)


async def test_user_flow_single_student(hass: Any) -> None:
    """A single-student account creates an entry without the student step."""
    with (
        patch(
            "custom_components.sometoday.config_flow.async_get_schools",
            return_value=[SCHOOL],
        ),
        _login_patch(),
        patch.object(SomTodayApiClient, "async_get_students", new=_fake_students),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TENANT_UUID: TENANT}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "credentials"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SomToday Eli Saado"
    assert result["data"][CONF_TENANT_UUID] == TENANT
    assert result["data"][CONF_USERNAME] == USERNAME
    assert result["data"][CONF_SCHOOL_NAME] == SCHOOL.name
    assert result["data"][CONF_REFRESH_TOKEN] == "refresh"
    assert result["data"][CONF_STUDENT_ID] == STUDENT.id
    assert result["data"][CONF_AUTH_METHOD] == "pkce"


async def test_user_flow_multiple_students(hass: Any) -> None:
    """An account with multiple students asks the user to pick one."""

    async def _students(self: SomTodayApiClient) -> list[Student]:
        return [STUDENT, OTHER_STUDENT]

    with (
        patch(
            "custom_components.sometoday.config_flow.async_get_schools",
            return_value=[SCHOOL],
        ),
        _login_patch(),
        patch.object(SomTodayApiClient, "async_get_students", new=_students),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TENANT_UUID: TENANT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "student"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STUDENT_ID: str(OTHER_STUDENT.id)}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STUDENT_ID] == OTHER_STUDENT.id
    assert result["title"] == "SomToday Sam"


async def test_user_flow_invalid_auth(hass: Any) -> None:
    """Invalid credentials show the invalid_auth error."""
    with (
        patch(
            "custom_components.sometoday.config_flow.async_get_schools",
            return_value=[SCHOOL],
        ),
        patch.object(
            SomTodayAuthClient,
            "async_login",
            side_effect=SomTodayAuthError("bad credentials"),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TENANT_UUID: TENANT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_school_list_connection_error(hass: Any) -> None:
    """A failing school list shows cannot_connect and allows a retry."""
    with patch(
        "custom_components.sometoday.config_flow.async_get_schools",
        side_effect=SomTodayConnectionError("offline"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_sso_not_supported(hass: Any) -> None:
    """An SSO-only school surfaces the sso_not_supported error."""
    with (
        patch(
            "custom_components.sometoday.config_flow.async_get_schools",
            return_value=[SCHOOL],
        ),
        patch.object(
            SomTodayAuthClient,
            "async_login",
            side_effect=SomTodaySsoNotSupported("sso"),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TENANT_UUID: TENANT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "sso_not_supported"}


async def test_user_flow_duplicate_aborts(hass: Any) -> None:
    """An account that is already configured aborts the flow."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{TENANT}:{USERNAME}",
        data={CONF_TENANT_UUID: TENANT, CONF_USERNAME: USERNAME},
    )
    existing.add_to_hass(hass)

    with (
        patch(
            "custom_components.sometoday.config_flow.async_get_schools",
            return_value=[SCHOOL],
        ),
        _login_patch(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TENANT_UUID: TENANT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_updates_refresh_token(hass: Any) -> None:
    """A reauth stores the rotated refresh token and reloads the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{TENANT}:{USERNAME}",
        data={
            CONF_TENANT_UUID: TENANT,
            CONF_SCHOOL_NAME: SCHOOL.name,
            CONF_USERNAME: USERNAME,
            CONF_REFRESH_TOKEN: "old-refresh",
            CONF_API_URL: API_URL,
            CONF_AUTH_METHOD: "pkce",
        },
    )
    entry.add_to_hass(hass)

    async def _refresh(self: SomTodayAuthClient) -> SomTodayTokens:
        self.tokens = _tokens("rotated")
        return self.tokens

    with (
        _login_patch(refresh_token="rotated"),
        patch.object(SomTodayAuthClient, "async_refresh", new=_refresh),
    ):
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

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: PASSWORD}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "rotated"
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth_after_failed_setup_reloads_entry(hass: Any) -> None:
    """A reauth recovers an entry stuck in SETUP_ERROR back to LOADED.

    Regression test for review B1: without a reload the entry stays broken even
    though the reauth flow reports success.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{TENANT}:{USERNAME}",
        data={
            CONF_TENANT_UUID: TENANT,
            CONF_SCHOOL_NAME: SCHOOL.name,
            CONF_USERNAME: USERNAME,
            CONF_REFRESH_TOKEN: "old-refresh",
            CONF_API_URL: API_URL,
            CONF_AUTH_METHOD: "pkce",
        },
    )
    entry.add_to_hass(hass)

    async def _ensure_valid_fail(self: SomTodayAuthClient) -> None:
        raise SomTodayAuthError("access token rejected")

    with patch.object(
        SomTodayAuthClient, "async_ensure_valid", new=_ensure_valid_fail
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR

    async def _refresh(self: SomTodayAuthClient) -> SomTodayTokens:
        self.tokens = _tokens("rotated")
        return self.tokens

    with (
        _login_patch(refresh_token="rotated"),
        patch.object(SomTodayAuthClient, "async_refresh", new=_refresh),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: PASSWORD}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "rotated"
    assert entry.state is ConfigEntryState.LOADED


async def test_options_flow(hass: Any) -> None:
    """The options flow persists the poll interval and feature toggles."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{TENANT}:{USERNAME}",
        data={CONF_TENANT_UUID: TENANT, CONF_USERNAME: USERNAME},
    )
    entry.add_to_hass(hass)

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

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 30
    assert entry.options[CONF_ENABLE_GRADES] is False


async def test_setup_entry_refreshes_token(hass: Any) -> None:
    """Setting up an entry refreshes the stored token and exposes runtime data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{TENANT}:{USERNAME}",
        data={
            CONF_TENANT_UUID: TENANT,
            CONF_USERNAME: USERNAME,
            CONF_REFRESH_TOKEN: "old-refresh",
            CONF_API_URL: API_URL,
            CONF_AUTH_METHOD: "pkce",
        },
    )
    entry.add_to_hass(hass)

    async def _refresh(self: SomTodayAuthClient) -> SomTodayTokens:
        self.tokens = _tokens("new-refresh")
        return self.tokens

    with patch.object(SomTodayAuthClient, "async_refresh", new=_refresh):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.api.base_url == DEFAULT_API_URL
    assert entry.data[CONF_REFRESH_TOKEN] == "new-refresh"

# ---------------------------------------------------------------------------
# Config-flow slice: remaining error mappings, student-fetch validation,
# reauth errors and setup-entry exception mapping.
# ---------------------------------------------------------------------------
async def _run_credentials_flow(
    hass: Any,
    *,
    login_error: Exception | None = None,
    students: list[Student] | None = None,
    students_error: Exception | None = None,
) -> dict[str, Any]:
    """Drive the user → credentials flow and return the last result."""
    login = (
        patch.object(SomTodayAuthClient, "async_login", side_effect=login_error)
        if login_error is not None
        else _login_patch()
    )
    if students_error is not None:
        students_patch = patch.object(
            SomTodayApiClient, "async_get_students", side_effect=students_error
        )
    else:

        async def _students(self: SomTodayApiClient) -> list[Student]:
            return list(students or [])

        students_patch = patch.object(
            SomTodayApiClient, "async_get_students", new=_students
        )

    with (
        patch(
            "custom_components.sometoday.config_flow.async_get_schools",
            return_value=[SCHOOL],
        ),
        login,
        students_patch,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TENANT_UUID: TENANT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
        )
    return result


async def test_user_flow_login_connection_error(hass: Any) -> None:
    """A network failure during login shows cannot_connect."""
    result = await _run_credentials_flow(
        hass, login_error=SomTodayConnectionError("offline")
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_login_unexpected_error(hass: Any) -> None:
    """An unexpected login failure shows unknown."""
    result = await _run_credentials_flow(hass, login_error=SomTodayError("boom"))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_school_list_unexpected_error(hass: Any) -> None:
    """An unexpected school-list failure shows unknown on the user step."""
    with patch(
        "custom_components.sometoday.config_flow.async_get_schools",
        side_effect=SomTodayError("boom"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "unknown"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SomTodayAuthError("rejected"), "invalid_auth"),
        (SomTodayConnectionError("offline"), "cannot_connect"),
        (SomTodayError("boom"), "unknown"),
    ],
)
async def test_user_flow_student_fetch_errors(
    hass: Any, error: Exception, expected: str
) -> None:
    """A failing student-list validation maps to the documented error."""
    result = await _run_credentials_flow(hass, students_error=error)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": expected}


async def test_user_flow_no_students(hass: Any) -> None:
    """An empty student list shows no_students."""
    result = await _run_credentials_flow(hass, students=[])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"
    assert result["errors"] == {"base": "no_students"}


def test_school_option_labels() -> None:
    """The school selector label includes the place only when present."""
    without_place = _school_option(School(uuid="u1", name="A"))
    with_place = _school_option(School(uuid="u2", name="B", place="Enschede"))

    assert without_place == {"value": "u1", "label": "A"}
    assert with_place == {"value": "u2", "label": "B (Enschede)"}


async def _run_reauth_flow(hass: Any, entry: MockConfigEntry, error: Exception) -> Any:
    """Start a reauth flow for ``entry`` and submit a failing password."""
    with patch.object(SomTodayAuthClient, "async_login", side_effect=error):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: PASSWORD}
        )
    return result


def _reauth_entry(hass: Any) -> MockConfigEntry:
    """Create and register an entry suitable for a reauth flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{TENANT}:{USERNAME}",
        data={
            CONF_TENANT_UUID: TENANT,
            CONF_SCHOOL_NAME: SCHOOL.name,
            CONF_USERNAME: USERNAME,
            CONF_REFRESH_TOKEN: "old-refresh",
            CONF_API_URL: API_URL,
            CONF_AUTH_METHOD: "pkce",
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SomTodaySsoNotSupported("sso"), "sso_not_supported"),
        (SomTodayAuthError("bad"), "invalid_auth"),
        (SomTodayConnectionError("offline"), "cannot_connect"),
        (SomTodayError("boom"), "unknown"),
    ],
)
async def test_reauth_flow_errors(
    hass: Any, error: Exception, expected: str
) -> None:
    """Reauth maps every login failure to the documented error."""
    entry = _reauth_entry(hass)

    result = await _run_reauth_flow(hass, entry, error)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": expected}


def _setup_entry(hass: Any, refresh_token: str = "old-refresh") -> MockConfigEntry:
    """Create and register an entry for setup-entry tests."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{TENANT}:{USERNAME}",
        data={
            CONF_TENANT_UUID: TENANT,
            CONF_USERNAME: USERNAME,
            CONF_REFRESH_TOKEN: refresh_token,
            CONF_API_URL: API_URL,
            CONF_AUTH_METHOD: "pkce",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_entry_auth_failure(hass: Any) -> None:
    """A rejected stored token raises ConfigEntryAuthFailed."""
    entry = _setup_entry(hass)

    with patch.object(
        SomTodayAuthClient,
        "async_ensure_valid",
        side_effect=SomTodayAuthError("expired"),
    ), pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(hass, entry)


async def test_setup_entry_connection_failure(hass: Any) -> None:
    """A network failure during setup raises ConfigEntryNotReady."""
    entry = _setup_entry(hass)

    with patch.object(
        SomTodayAuthClient,
        "async_ensure_valid",
        side_effect=SomTodayConnectionError("offline"),
    ), pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, entry)


async def test_setup_entry_unexpected_failure(hass: Any) -> None:
    """Any other SomToday error during setup raises ConfigEntryNotReady."""
    entry = _setup_entry(hass)

    with patch.object(
        SomTodayAuthClient,
        "async_ensure_valid",
        side_effect=SomTodayError("boom"),
    ), pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, entry)


async def test_setup_entry_keeps_refresh_token_when_not_rotated(hass: Any) -> None:
    """A non-rotating refresh response leaves the stored token untouched."""
    entry = _setup_entry(hass, refresh_token="same-refresh")

    async def _refresh(self: SomTodayAuthClient) -> SomTodayTokens:
        self.tokens = _tokens("same-refresh")
        return self.tokens

    with patch.object(SomTodayAuthClient, "async_refresh", new=_refresh):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_REFRESH_TOKEN] == "same-refresh"


async def test_async_migrate_entry(hass: Any) -> None:
    """The migration hook accepts the current schema."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True


async def test_async_unload_entry(hass: Any) -> None:
    """Unloading an entry without platforms succeeds."""
    entry = _setup_entry(hass)

    assert await async_unload_entry(hass, entry) is True
