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
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
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
    CONF_ENABLE_ABSENCE,
    CONF_ENABLE_GRADES,
    CONF_ENABLE_HOMEWORK,
    CONF_HOMEWORK_DAYS_AHEAD,
    CONF_REDIRECT_URL,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DAYS_AHEAD,
    DEFAULT_HOMEWORK_DAYS_AHEAD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEDULE_DAYS_AHEAD,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .exceptions import (
    SomTodayError,
    SomtodayInvalidAuth,
)
from .models import SomTodayTokens, Student

_LOGGER = logging.getLogger(__name__)


class _NoStudentsError(SomTodayError):
    """Raised when the authenticated account has no students."""


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

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow and mint a fresh PKCE pair + state."""
        self._code_verifier = ""
        self._state = ""
        self._auth_url = ""
        self._tokens: SomTodayTokens | None = None
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
                account_id, student = resolved
                await self.async_set_unique_id(account_id, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                assert self._tokens is not None
                return self.async_create_entry(
                    title=f"SomToday {student.display_name}",
                    data=self._tokens.as_entry_data(),
                )

        return self._show_login_form("user", errors)

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
                account_id, _student = resolved
                if entry.unique_id is not None and account_id != entry.unique_id:
                    return self.async_abort(reason="wrong_account")
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
    ) -> tuple[str, Student] | None:
        """Exchange the pasted code and resolve the account/student.

        Returns ``(account_id, student)`` on success, or ``None`` after filling
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
            else:
                errors["base"] = "invalid_url"
            # Recoverable: keep the current authorize URL.
            return None

        session = async_get_clientsession(self.hass)
        try:
            tokens = await async_exchange_code(session, code, self._code_verifier)
            account_id, student = await self._async_identify(tokens)
        except SomtodayInvalidAuth:
            errors["base"] = "invalid_auth"
        except _NoStudentsError:
            errors["base"] = "no_students"
        except SomTodayError:
            # Every other SomToday error is retryable (network, 5xx, malformed
            # response): the user can retry with a fresh login.
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during SomToday login")
            errors["base"] = "unknown"
        else:
            self._tokens = tokens
            return account_id, student

        # The code is spent (or the failure is not a paste mistake): mint a new
        # PKCE pair + state for the next attempt.
        self._new_authorization()
        return None

    async def _async_identify(
        self, tokens: SomTodayTokens
    ) -> tuple[str, Student]:
        """Resolve the account id and the student for freshly exchanged tokens."""
        session = async_get_clientsession(self.hass)
        auth = SomTodayAuth(session, tokens=tokens, api_url=tokens.api_url)
        api = SomTodayApiClient(session, auth, tokens.api_url)

        account_id: str | None = None
        try:
            account = await api.async_get_account()
            account_id = account.id
        except SomTodayError:
            _LOGGER.debug(
                "Could not read /account/me, falling back to /leerlingen"
            )

        students = await api.async_get_students()
        if not students:
            raise _NoStudentsError("No students found for this account")

        student = students[0]
        if account_id is None:
            account_id = str(student.id)

        tokens.account_id = account_id
        tokens.student_id = student.id
        tokens.student_name = student.display_name
        return account_id, student
