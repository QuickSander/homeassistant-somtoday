"""Tests for the SomToday config, reauth and options flows.

All SomToday HTTP calls are mocked; the real API is never contacted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType, InvalidData
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
    CONF_STUDENT_SELECT,
    DEFAULT_API_URL,
    DOMAIN,
    unique_id_for,
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
STUDENT2 = Student(id=5678, leerlingnummer="450001", roepnaam="Sara", achternaam="Saado")


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


async def _noop_ensure_valid(self: SomTodayAuth) -> None:
    """Skip token refresh during flow tests."""


@contextmanager
def _patched_login(
    *,
    exchange: Any = None,
    account: Account | None = None,
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
        selected_account = account if account is not None else ACCOUNT

        async def _account(self: SomTodayApiClient) -> Account:
            return selected_account

        account_patch = patch.object(
            SomTodayApiClient, "async_get_account", new=_account
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


def _student_options(result: dict[str, Any]) -> list[dict[str, str]]:
    """Return the dropdown options of the student-selection step."""
    schema = result["data_schema"]
    for key, value in schema.schema.items():
        if getattr(key, "schema", key) == CONF_STUDENT_SELECT:
            return value.config["options"]
    raise AssertionError("student_select field not found in the schema")


def _make_entry(hass: Any, *, refresh_token: str = "old-refresh") -> MockConfigEntry:
    """Create and register an entry suitable for setup/reauth tests."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=unique_id_for("account-1", STUDENT.id),
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
    assert entries[0].unique_id == unique_id_for("account-1", STUDENT.id)


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


async def test_user_flow_account_lookup_failure_is_retryable(hass: Any) -> None:
    """A failing /account/me is retryable and never creates an entry.

    Regression for finding F1: the composite unique id must not fall back to a
    student id, so the flow shows cannot_connect and can be retried.
    """
    with _patched_login(account_error=SomTodayApiError("no account endpoint")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_user_flow_duplicate_aborts(hass: Any) -> None:
    """The same (account, student) pair aborts the flow."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id_for("account-1", STUDENT.id),
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
    """An empty student list shows no_students and regenerates the link."""
    with _patched_login(students=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        first_url = _auth_url(result)
        state = _state_from_url(first_url)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )
        second_url = _auth_url(result)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "no_students"}
    assert first_url != second_url


async def test_user_flow_multiple_students_shows_student_step(hass: Any) -> None:
    """An account with several unconfigured students shows the student step."""
    with _patched_login(students=[STUDENT, STUDENT2]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "student"
        options = _student_options(result)
        assert [option["value"] for option in options] == [
            str(STUDENT.id),
            str(STUDENT2.id),
        ]
        assert [option["label"] for option in options] == [
            STUDENT.display_name,
            STUDENT2.display_name,
        ]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STUDENT_SELECT: str(STUDENT2.id)}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"SomToday {STUDENT2.display_name}"
    assert result["data"][CONF_STUDENT_ID] == STUDENT2.id
    assert result["data"][CONF_STUDENT_NAME] == STUDENT2.display_name
    entries = hass.config_entries.async_entries(DOMAIN)
    assert entries[0].unique_id == unique_id_for("account-1", STUDENT2.id)


async def test_user_flow_student_step_unknown_selection_reshows_form(
    hass: Any,
) -> None:
    """An unknown student selection never leaves the student step.

    Home Assistant validates the dropdown value against the offered options
    before the flow handler runs; the flow stays on the student step so the
    user can pick again.
    """
    with _patched_login(students=[STUDENT, STUDENT2]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )
        assert result["step_id"] == "student"

        with pytest.raises(InvalidData):
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_STUDENT_SELECT: "999999"}
            )

        flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert flow[0]["step_id"] == "student"


async def test_user_flow_student_step_aborts_when_all_configured(
    hass: Any,
) -> None:
    """If every student got configured meanwhile, the student step aborts."""
    with _patched_login(students=[STUDENT, STUDENT2]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )
        assert result["step_id"] == "student"

        # Another flow configures both students while the dropdown is open.
        for student in (STUDENT, STUDENT2):
            MockConfigEntry(
                domain=DOMAIN,
                unique_id=unique_id_for("account-1", student.id),
                data={},
            ).add_to_hass(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STUDENT_SELECT: str(STUDENT.id)}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_second_student_same_account(hass: Any) -> None:
    """A second student of an already-configured account is added.

    The account is shared but the composite unique id differs, so the entry is
    created without showing the student step (exactly one student remains
    unconfigured).
    """
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id_for("account-1", STUDENT.id),
        data={CONF_REFRESH_TOKEN: "x", CONF_API_URL: API_URL},
    )
    existing.add_to_hass(hass)

    with _patched_login(students=[STUDENT, STUDENT2]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STUDENT_ID] == STUDENT2.id
    entries = hass.config_entries.async_entries(DOMAIN)
    assert {entry.unique_id for entry in entries} == {
        unique_id_for("account-1", STUDENT.id),
        unique_id_for("account-1", STUDENT2.id),
    }


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
    # The student binding is preserved: reauth only updates the tokens.
    assert entry.data[CONF_ACCOUNT_ID] == "account-1"
    assert entry.data[CONF_STUDENT_ID] == STUDENT.id
    assert entry.data[CONF_STUDENT_NAME] == STUDENT.display_name
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth_flow_wrong_account(hass: Any) -> None:
    """A different account signing in aborts with wrong_account."""
    entry = _make_entry(hass)

    with _patched_login(account=Account(id="some-other-account")):
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


async def test_reauth_flow_student_removed(hass: Any) -> None:
    """A stored student missing from the account aborts with student_removed."""
    entry = _make_entry(hass)

    with _patched_login(students=[STUDENT2]):
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
    assert result["reason"] == "student_removed"


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


async def test_async_migrate_entry_v1_to_composite(hass: Any) -> None:
    """A v1 entry gets the composite unique id and the current version."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="account-1",
        data={
            CONF_REFRESH_TOKEN: "x",
            CONF_API_URL: API_URL,
            CONF_ACCOUNT_ID: "account-1",
            CONF_STUDENT_ID: STUDENT.id,
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.unique_id == unique_id_for("account-1", STUDENT.id)
    assert entry.version == 2


async def test_async_migrate_entry_without_student_falls_back(
    hass: Any,
) -> None:
    """A v1 entry without a student id keeps the account id as unique id."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="account-1",
        data={CONF_ACCOUNT_ID: "account-1"},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.unique_id == "account-1"
    assert entry.version == 2


async def test_async_migrate_entry_without_account_keeps_unique_id(
    hass: Any,
) -> None:
    """A v1 entry without account metadata keeps its unique id and is bumped."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="legacy",
        data={},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.unique_id == "legacy"
    assert entry.version == 2


async def test_async_migrate_entry_current_version_is_noop(hass: Any) -> None:
    """A v2 entry is left untouched."""
    entry = _make_entry(hass)
    original_unique_id = entry.unique_id

    assert await async_migrate_entry(hass, entry) is True
    assert entry.unique_id == original_unique_id
    assert entry.version == 2


async def test_async_unload_entry(hass: Any) -> None:
    """Unloading an entry without platforms succeeds."""
    entry = _make_entry(hass)

    assert await async_unload_entry(hass, entry) is True


def test_default_api_url_constant() -> None:
    """The default API URL is the documented SomToday host."""
    assert DEFAULT_API_URL == "https://api.somtoday.nl"


# ---------------------------------------------------------------------------
# Identity model (Model A): one config entry per (account, student)
# ---------------------------------------------------------------------------
async def test_setup_entry_migrates_v1_entry(hass: Any) -> None:
    """HA migrates a v1 entry during setup and persists the new version.

    Exercises the re-export of ``async_migrate_entry`` from ``__init__.py`` and
    the Home Assistant migration hook (``ConfigEntry.async_migrate``), which the
    direct ``async_migrate_entry`` tests do not cover.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        unique_id="account-1",
        data={
            CONF_REFRESH_TOKEN: "x",
            CONF_API_URL: API_URL,
            CONF_ACCOUNT_ID: "account-1",
            CONF_STUDENT_ID: STUDENT.id,
            CONF_STUDENT_NAME: STUDENT.display_name,
        },
    )
    entry.add_to_hass(hass)

    with patch.object(SomTodayAuth, "async_ensure_valid", new=_noop_ensure_valid):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == unique_id_for("account-1", STUDENT.id)
    assert entry.version == 2


async def test_reauth_preserves_composite_unique_id(hass: Any) -> None:
    """Reauth updates tokens without changing the composite unique id."""
    entry = _make_entry(hass)
    original_unique_id = entry.unique_id

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

    assert result["reason"] == "reauth_successful"
    assert entry.unique_id == original_unique_id
    assert entry.unique_id == unique_id_for("account-1", STUDENT.id)


async def test_concurrent_flows_same_student_create_one_entry(hass: Any) -> None:
    """Two concurrent flows for the same (account, student) create one entry.

    Probes two framework behaviours the identity model relies on:
    ``_async_current_ids()`` only sees configured entries (not other in-progress
    flows) and ``_async_finish`` sets the unique id with
    ``raise_on_progress=False``. Even with an interleaving exchange, the
    ``_abort_if_unique_id_configured`` check keeps the second flow from
    creating a duplicate entry.
    """

    async def _yielding_exchange(session: Any, code: str, code_verifier: str) -> Any:
        await asyncio.sleep(0)
        return _tokens()

    with _patched_login(exchange=_yielding_exchange):
        first = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        second = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        first_state = _state_from_url(_auth_url(first))
        second_state = _state_from_url(_auth_url(second))
        results = await asyncio.gather(
            hass.config_entries.flow.async_configure(
                first["flow_id"], {CONF_REDIRECT_URL: _redirect(state=first_state)}
            ),
            hass.config_entries.flow.async_configure(
                second["flow_id"], {CONF_REDIRECT_URL: _redirect(state=second_state)}
            ),
        )

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].unique_id == unique_id_for("account-1", STUDENT.id)

    created = [r for r in results if r["type"] is FlowResultType.CREATE_ENTRY]
    aborted = [r for r in results if r["type"] is FlowResultType.ABORT]
    assert len(created) == 1
    assert len(aborted) == 1
    assert aborted[0]["reason"] == "already_configured"


async def test_reauth_transient_account_failure_is_retryable(hass: Any) -> None:
    """A transient ``/account/me`` failure during reauth is retryable.

    Regression for finding F1: previously the student-id fallback made this
    abort with ``wrong_account``, which a retry could not recover from.
    """
    entry = _make_entry(hass)

    with _patched_login(
        account_error=SomTodayApiError("transient account failure"),
        students=[STUDENT],
    ):
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
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_account_failure_cannot_duplicate_student(hass: Any) -> None:
    """A transient ``/account/me`` failure does not add a duplicate student.

    Regression for finding F1b: the flow now fails retryably instead of
    computing a student-based unique id.
    """
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id_for("account-1", STUDENT.id),
        data={CONF_REFRESH_TOKEN: "x", CONF_API_URL: API_URL},
    )
    existing.add_to_hass(hass)

    with _patched_login(
        account_error=SomTodayApiError("transient account failure"),
        students=[STUDENT],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    entries = hass.config_entries.async_entries(DOMAIN)
    assert [entry.unique_id for entry in entries] == [
        unique_id_for("account-1", STUDENT.id)
    ]


async def test_user_flow_student_step_reshows_remaining_after_config_change(
    hass: Any,
) -> None:
    """Selecting a student configured meanwhile re-shows the remaining options.

    Covers the handler's fall-through branch (``config_flow.py:221->226``): the
    dropdown value was valid when the form was rendered, but by submit time that
    student is configured while another remains unconfigured.
    """
    with _patched_login(students=[STUDENT, STUDENT2]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )
        assert result["step_id"] == "student"

        # Another flow configures only the first student while the dropdown is
        # open; the second remains unconfigured.
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=unique_id_for("account-1", STUDENT.id),
            data={},
        ).add_to_hass(hass)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_STUDENT_SELECT: str(STUDENT.id)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "student"
    assert [option["value"] for option in _student_options(result)] == [
        str(STUDENT2.id)
    ]


async def test_user_flow_account_lookup_failure_with_empty_list_is_retryable(
    hass: Any,
) -> None:
    """An account lookup failure is retryable even with an empty student list.

    Regression for finding F1: ``/account/me`` is required, so its failure is a
    ``cannot_connect`` (retryable) error rather than ``no_students``.
    """
    with _patched_login(account_error=SomTodayApiError("down"), students=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        state = _state_from_url(_auth_url(result))
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: _redirect(state=state)}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}
