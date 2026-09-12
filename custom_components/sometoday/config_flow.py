"""Config and options flow for the SomToday integration.

The config flow implements the browser-based authorization-code + PKCE login:
it shows the user a SomToday authorize URL, the user logs in through their own
browser (SSO/MFA work) and pastes the failed ``somtoday://`` redirect (or a bare
code) back into Home Assistant, which exchanges it server-side.

There is no school selection and no credential form: the authorize URL omits
``tenant_uuid`` so SomToday shows its own school picker. The options flow
configures the poll interval and feature toggles.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SomTodayApiClient
from .auth import (
    SomTodayAuth,
    async_exchange_code,
    build_authorize_url,
    code_challenge_from_verifier,
    extract_code,
    generate_code_verifier,
    generate_state,
)
from .const import (
    CONF_ACCOUNT_ID,
    CONF_ENABLE_ABSENCE,
    CONF_ENABLE_GRADES,
    CONF_ENABLE_HOMEWORK,
    CONF_HOMEWORK_DAYS_AHEAD,
    CONF_REDIRECT_URL,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DAYS_AHEAD,
    CONF_STUDENT_ID,
    CONF_STUDENT_SELECT,
    DEFAULT_HOMEWORK_DAYS_AHEAD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEDULE_DAYS_AHEAD,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    unique_id_for,
)
from .exceptions import (
    SomTodayError,
    SomtodayInvalidAuth,
)
from .models import SomTodayTokens, Student

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a v1 entry (unique id = account id) to the composite id.

    v1 used ``account_id`` as the unique id; v2 uses
    ``f"{account_id}:{student_id}"`` so a parent account can back one entry per
    student. Only the unique id and the schema version change; the entry data
    keys are unchanged.
    """
    if entry.version == 1:
        account_id = entry.data.get(CONF_ACCOUNT_ID)
        student_id = entry.data.get(CONF_STUDENT_ID)
        if account_id is None:
            # Malformed entry without account metadata: keep the old id but
            # still move to the current version so migration does not repeat.
            new_unique_id = entry.unique_id
        elif student_id is None:
            # Defensive fallback for an entry that never stored a student.
            new_unique_id = str(account_id)
        else:
            new_unique_id = unique_id_for(str(account_id), int(student_id))
        hass.config_entries.async_update_entry(
            entry, unique_id=new_unique_id, version=SomTodayConfigFlow.VERSION
        )
        return True
    return True


class SomTodayOptionsFlow(OptionsFlow):
    """Handle the SomToday options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the integration options."""
        if user_input is not None:
            # There is no update listener; reload explicitly so the new options
            # take effect.
            self.hass.config_entries.async_schedule_reload(
                self.config_entry.entry_id
            )
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Required(
                    CONF_SCHEDULE_DAYS_AHEAD,
                    default=options.get(
                        CONF_SCHEDULE_DAYS_AHEAD, DEFAULT_SCHEDULE_DAYS_AHEAD
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Required(
                    CONF_HOMEWORK_DAYS_AHEAD,
                    default=options.get(
                        CONF_HOMEWORK_DAYS_AHEAD, DEFAULT_HOMEWORK_DAYS_AHEAD
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Required(
                    CONF_ENABLE_GRADES,
                    default=options.get(CONF_ENABLE_GRADES, True),
                ): bool,
                vol.Required(
                    CONF_ENABLE_HOMEWORK,
                    default=options.get(CONF_ENABLE_HOMEWORK, True),
                ): bool,
                vol.Required(
                    CONF_ENABLE_ABSENCE,
                    default=options.get(CONF_ENABLE_ABSENCE, True),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class SomTodayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the SomToday config flow."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialise the flow and mint a fresh PKCE pair + state."""
        self._code_verifier = ""
        self._state = ""
        self._auth_url = ""
        self._tokens: SomTodayTokens | None = None
        self._account_id: str | None = None
        self._students: list[Student] = []
        self._reauth_entry: ConfigEntry | None = None
        self._new_authorization()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SomTodayOptionsFlow:
        """Return the options flow for this handler."""
        return SomTodayOptionsFlow()

    # ------------------------------------------------------------------
    # Initial setup
    # ------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the authorize URL and exchange the pasted redirect/code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            resolved = await self._async_authorize_and_identify(user_input, errors)
            if resolved is not None:
                account_id, students = resolved
                if not students:
                    # No student is linked to the account: mint a fresh PKCE
                    # pair so the user can retry with another account.
                    errors["base"] = "no_students"
                    self._new_authorization()
                else:
                    unconfigured = self._async_unconfigured_students(
                        account_id, students
                    )
                    if not unconfigured:
                        return self.async_abort(reason="already_configured")
                    if len(unconfigured) == 1:
                        return await self._async_finish(unconfigured[0])
                    return await self.async_step_student()

        return self._show_login_form("user", errors)

    async def async_step_student(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which student to configure when the account exposes several."""
        assert self._account_id is not None
        unconfigured = self._async_unconfigured_students(
            self._account_id, self._students
        )
        if not unconfigured:
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            selected = str(user_input.get(CONF_STUDENT_SELECT, ""))
            for student in unconfigured:
                if str(student.id) == selected:
                    return await self._async_finish(student)
            # Unknown selection: fall through and re-show the form.

        options = [
            {"value": str(student.id), "label": student.display_name}
            for student in sorted(
                unconfigured, key=lambda student: (student.display_name, student.id)
            )
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_STUDENT_SELECT): SelectSelector(
                    SelectSelectorConfig(options=options)
                )
            }
        )
        return self.async_show_form(step_id="student", data_schema=schema)

    # ------------------------------------------------------------------
    # Re-authentication
    # ------------------------------------------------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the reauth flow for an expired session."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-authenticate by pasting a fresh redirect/code."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if entry is not None and user_input is not None:
            resolved = await self._async_authorize_and_identify(user_input, errors)
            if resolved is not None:
                account_id, students = resolved
                if account_id != entry.data.get(CONF_ACCOUNT_ID):
                    return self.async_abort(reason="wrong_account")
                student_id = entry.data.get(CONF_STUDENT_ID)
                if not any(student.id == student_id for student in students):
                    return self.async_abort(reason="student_removed")
                assert self._tokens is not None
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=self._tokens.as_entry_data(),
                    reason="reauth_successful",
                )

        return self._show_login_form("reauth_confirm", errors)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _new_authorization(self) -> None:
        """Mint a fresh PKCE pair + state and rebuild the authorize URL."""
        self._code_verifier = generate_code_verifier()
        self._state = generate_state()
        self._auth_url = build_authorize_url(
            code_challenge_from_verifier(self._code_verifier), self._state
        )

    def _login_schema(self) -> vol.Schema:
        """Return the schema for the pasted redirect/code field."""
        return vol.Schema(
            {
                vol.Required(CONF_REDIRECT_URL): TextSelector(
                    TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
                )
            }
        )

    def _show_login_form(
        self, step_id: str, errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Show the login form with the current authorize URL."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=self._login_schema(),
            errors=errors,
            description_placeholders={"auth_url": self._auth_url},
        )

    async def _async_authorize_and_identify(
        self, user_input: dict[str, Any], errors: dict[str, str]
    ) -> tuple[str, list[Student]] | None:
        """Exchange the pasted code and resolve the account and student list.

        Returns ``(account_id, students)`` on success, or ``None`` after filling
        ``errors``. The authorize URL is only regenerated when the previous code
        can no longer be used, so a recoverable paste mistake does not
        invalidate the user's open login.
        """
        pasted = user_input.get(CONF_REDIRECT_URL, "")
        try:
            code = extract_code(pasted, self._state)
        except ValueError as err:
            reason = str(err)
            if reason == "state_mismatch":
                errors["base"] = "state_mismatch"
            elif reason == "login_page":
                errors["base"] = "login_page"
            elif reason == "sso_callback":
                errors["base"] = "sso_callback"
            else:
                errors["base"] = "invalid_url"
            # Recoverable: keep the current authorize URL.
            return None

        session = async_get_clientsession(self.hass)
        try:
            tokens = await async_exchange_code(session, code, self._code_verifier)
            account_id, students = await self._async_identify(tokens)
        except SomtodayInvalidAuth:
            errors["base"] = "invalid_auth"
        except SomTodayError:
            # Every other SomToday error is retryable (network, 5xx, malformed
            # response): the user can retry with a fresh login.
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during SomToday login")
            errors["base"] = "unknown"
        else:
            self._tokens = tokens
            self._account_id = account_id
            self._students = students
            return account_id, students

        # The code is spent (or the failure is not a paste mistake): mint a new
        # PKCE pair + state for the next attempt.
        self._new_authorization()
        return None

    async def _async_identify(
        self, tokens: SomTodayTokens
    ) -> tuple[str, list[Student]]:
        """Resolve the account id and the full student list for fresh tokens.

        ``/account/me`` is required: the composite unique id must be stable
        across flows, so a transient failure here stays retryable (mapped to
        ``cannot_connect``) instead of falling back to a student id. A fallback
        would produce duplicate entries for the same student, or a false
        ``wrong_account`` during reauth (docs/architecture.md section 1.1).
        Only ``tokens.account_id`` is set here; the student binding is chosen
        later by :meth:`_async_finish`.
        """
        session = async_get_clientsession(self.hass)
        auth = SomTodayAuth(session, tokens=tokens, api_url=tokens.api_url)
        api = SomTodayApiClient(session, auth, tokens.api_url)

        account = await api.async_get_account()
        tokens.account_id = account.id

        students = await api.async_get_students()
        return account.id, students

    def _async_unconfigured_students(
        self, account_id: str, students: list[Student]
    ) -> list[Student]:
        """Return the students whose composite unique id is not configured."""
        configured = self._async_current_ids()
        return [
            student
            for student in students
            if unique_id_for(account_id, student.id) not in configured
        ]

    async def _async_finish(self, student: Student) -> ConfigFlowResult:
        """Bind the selected student and create the config entry."""
        assert self._tokens is not None
        assert self._account_id is not None
        self._tokens.student_id = student.id
        self._tokens.student_name = student.display_name
        await self.async_set_unique_id(
            unique_id_for(self._account_id, student.id), raise_on_progress=False
        )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"SomToday {student.display_name}",
            data=self._tokens.as_entry_data(),
        )
