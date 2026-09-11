"""Config and options flow for the SomToday integration.

The config flow discovers the school (tenant UUID), authenticates the account
with the PKCE/password flow and validates the resulting session by reading
``/rest/v1/leerlingen``. A reauth flow reuses the stored username. The options
flow configures the poll interval and feature toggles.
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
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import SomTodayApiClient
from .auth import SomTodayAuthClient, async_get_schools
from .const import (
    CONF_AUTH_METHOD,
    CONF_ENABLE_ABSENCE,
    CONF_ENABLE_GRADES,
    CONF_ENABLE_HOMEWORK,
    CONF_HOMEWORK_DAYS_AHEAD,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DAYS_AHEAD,
    CONF_SCHOOL_NAME,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    CONF_TENANT_UUID,
    CONF_USERNAME,
    DEFAULT_HOMEWORK_DAYS_AHEAD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEDULE_DAYS_AHEAD,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .exceptions import (
    SomTodayAuthError,
    SomTodayConnectionError,
    SomTodayError,
    SomTodaySsoNotSupported,
)
from .models import School, Student

_LOGGER = logging.getLogger(__name__)


def _school_option(school: School) -> SelectOptionDict:
    """Return the selector option for a school."""
    label = school.name or school.uuid
    if school.place:
        label = f"{label} ({school.place})"
    return SelectOptionDict(value=school.uuid, label=label)


class SomTodayOptionsFlow(OptionsFlow):
    """Handle the SomToday options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the integration options."""
        if user_input is not None:
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
        """Initialise the flow state."""
        self._schools: list[School] = []
        self._school_names: dict[str, str] = {}
        self._tenant_uuid: str | None = None
        self._school_name: str | None = None
        self._username: str | None = None
        self._auth: SomTodayAuthClient | None = None
        self._students: list[Student] = []
        self._reauth_entry: ConfigEntry | None = None

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
        """Select the school and continue to the credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None and CONF_TENANT_UUID in user_input:
            self._tenant_uuid = user_input[CONF_TENANT_UUID]
            self._school_name = self._school_names.get(self._tenant_uuid)
            return await self.async_step_credentials()

        if not self._schools:
            try:
                self._schools = await async_get_schools(
                    async_get_clientsession(self.hass)
                )
            except SomTodayConnectionError:
                errors["base"] = "cannot_connect"
            except SomTodayError:
                _LOGGER.exception("Unexpected error while fetching the school list")
                errors["base"] = "unknown"
            else:
                self._school_names = {
                    school.uuid: school.name for school in self._schools
                }

        if not self._schools:
            # No options to show yet; the empty form lets the user retry.
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema({}), errors=errors
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TENANT_UUID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                _school_option(school) for school in self._schools
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                            sort=True,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Authenticate the account and validate the session."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(
                f"{self._tenant_uuid}:{username}", raise_on_progress=False
            )
            self._abort_if_unique_id_configured()

            auth = SomTodayAuthClient(
                async_get_clientsession(self.hass), self._tenant_uuid
            )
            try:
                await auth.async_login(username, password)
            except SomTodaySsoNotSupported:
                errors["base"] = "sso_not_supported"
            except SomTodayAuthError:
                errors["base"] = "invalid_auth"
            except SomTodayConnectionError:
                errors["base"] = "cannot_connect"
            except SomTodayError:
                _LOGGER.exception("Unexpected error during SomToday login")
                errors["base"] = "unknown"
            else:
                students = await self._async_fetch_students(auth, errors)
                if students is not None:
                    self._username = username
                    self._auth = auth
                    self._students = students
                    if len(students) > 1:
                        return await self.async_step_student()
                    return await self._async_create_entry(students[0])

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): TextSelector(),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_student(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the student when the account has more than one."""
        if user_input is not None:
            student = next(
                (
                    candidate
                    for candidate in self._students
                    if str(candidate.id) == user_input[CONF_STUDENT_ID]
                ),
                None,
            )
            if student is None:
                return self.async_show_form(
                    step_id="student",
                    data_schema=self._student_schema(),
                    errors={"base": "no_students"},
                )
            return await self._async_create_entry(student)

        return self.async_show_form(
            step_id="student", data_schema=self._student_schema()
        )

    # ------------------------------------------------------------------
    # Re-authentication
    # ------------------------------------------------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the reauth flow for an expired session."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        self._reauth_entry = entry
        if entry is not None:
            self._tenant_uuid = entry.data.get(CONF_TENANT_UUID)
            self._username = entry.data.get(CONF_USERNAME)
            self._school_name = entry.data.get(CONF_SCHOOL_NAME)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-authenticate using the stored username and a new password."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if entry is not None and user_input is not None:
            auth = SomTodayAuthClient(
                async_get_clientsession(self.hass),
                self._tenant_uuid,
                auth_method=entry.data.get(CONF_AUTH_METHOD),
            )
            try:
                await auth.async_login(self._username, user_input[CONF_PASSWORD])
            except SomTodaySsoNotSupported:
                errors["base"] = "sso_not_supported"
            except SomTodayAuthError:
                errors["base"] = "invalid_auth"
            except SomTodayConnectionError:
                errors["base"] = "cannot_connect"
            except SomTodayError:
                _LOGGER.exception("Unexpected error during SomToday reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=auth.as_entry_data(),
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"username": self._username or ""},
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _student_schema(self) -> vol.Schema:
        """Return the schema for the student selection step."""
        return vol.Schema(
            {
                vol.Required(CONF_STUDENT_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=str(student.id), label=student.display_name
                            )
                            for student in self._students
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def _async_fetch_students(
        self, auth: SomTodayAuthClient, errors: dict[str, str]
    ) -> list[Student] | None:
        """Validate the session by reading the student list."""
        if auth.tokens is None:  # pragma: no cover - defensive
            errors["base"] = "unknown"
            return None

        api = SomTodayApiClient(
            async_get_clientsession(self.hass), auth, auth.tokens.api_url
        )
        try:
            students = await api.async_get_students()
        except SomTodayAuthError:
            errors["base"] = "invalid_auth"
        except SomTodayConnectionError:
            errors["base"] = "cannot_connect"
        except SomTodayError:
            _LOGGER.exception("Unexpected error while fetching the student list")
            errors["base"] = "unknown"
        else:
            if not students:
                errors["base"] = "no_students"
            else:
                return students
        return None

    async def _async_create_entry(self, student: Student) -> ConfigFlowResult:
        """Create the config entry for the selected student."""
        assert self._auth is not None
        assert self._tenant_uuid is not None
        assert self._username is not None

        data = {
            **self._auth.as_entry_data(),
            CONF_TENANT_UUID: self._tenant_uuid,
            CONF_SCHOOL_NAME: self._school_name,
            CONF_USERNAME: self._username,
            CONF_STUDENT_ID: student.id,
            CONF_STUDENT_NAME: student.display_name,
        }
        return self.async_create_entry(
            title=f"SomToday {student.display_name}", data=data
        )
