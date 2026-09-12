"""The SomToday integration.

This slice wires up the authentication and API clients, builds the
``DataUpdateCoordinator`` and exposes the read-only schedule calendar. The
coordinator is refreshed once during setup so a broken session surfaces as a
reauth prompt (or a retry) before any entity is created.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SomTodayApiClient
from .auth import SomTodayAuth
from .config_flow import async_migrate_entry as async_migrate_entry
from .const import CONF_ACCOUNT_ID, CONF_STUDENT_NAME
from .coordinator import SomTodayDataUpdateCoordinator
from .exceptions import (
    SomTodayError,
    SomtodayInvalidAuth,
)
from .models import SomTodayTokens

_LOGGER = logging.getLogger(__name__)

# The first-lesson sensors (today/tomorrow) and the schedule calendar are
# implemented; the binary_sensor platform follows in a later slice.
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CALENDAR]


@dataclass
class SomTodayRuntimeData:
    """Runtime objects shared with the entity platforms."""

    auth: SomTodayAuth
    api: SomTodayApiClient
    coordinator: SomTodayDataUpdateCoordinator


SomTodayConfigEntry = ConfigEntry[SomTodayRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: SomTodayConfigEntry
) -> bool:
    """Set up SomToday from a config entry."""
    session = async_get_clientsession(hass)
    restored = SomTodayTokens.from_entry(entry)
    auth = SomTodayAuth(
        session,
        tokens=restored,
        api_url=restored.api_url,
        tenant=restored.tenant,
    )

    try:
        # A definitive rejection (invalid_grant) must trigger reauth; a
        # transient/connection failure should simply be retried by HA.
        await auth.async_ensure_valid()
    except SomtodayInvalidAuth as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SomTodayError as err:
        raise ConfigEntryNotReady(str(err)) from err

    # The refresh succeeded, so the stored session is valid. Log it once at INFO
    # so a working setup (and a broken one) is visible without debug logging.
    # Only the student name and account id are logged, never tokens.
    _LOGGER.info(
        "SomToday: authenticated as %s (account %s)",
        entry.data.get(CONF_STUDENT_NAME) or "unknown student",
        entry.data.get(CONF_ACCOUNT_ID) or "unknown account",
    )

    # SomToday rotates refresh tokens. Persist the rotated token (and account
    # metadata) so the next restart keeps working; the coordinator keeps it up
    # to date on later polls.
    if auth.tokens is not None:
        new_data = auth.as_entry_data()
        if any(entry.data.get(key) != value for key, value in new_data.items()):
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, **new_data}
            )

    api_url = auth.tokens.api_url if auth.tokens is not None else restored.api_url
    api = SomTodayApiClient(session, auth, api_url)

    coordinator = SomTodayDataUpdateCoordinator(hass, entry, api, auth)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SomTodayRuntimeData(
        auth=auth, api=api, coordinator=coordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SomTodayConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
