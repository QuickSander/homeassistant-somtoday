"""The SomToday integration.

This slice wires up the authentication and API clients and exposes them through
``entry.runtime_data``. The coordinator and entity platforms are added in later
steps; until then setup only validates that the stored refresh token still
works, so a broken session surfaces as a reauth prompt.
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
from .auth import SomTodayAuthClient
from .const import (
    CONF_API_URL,
    CONF_AUTH_METHOD,
    CONF_TENANT_UUID,
    DEFAULT_API_URL,
)
from .exceptions import SomTodayAuthError, SomTodayConnectionError, SomTodayError
from .models import SomTodayTokens

_LOGGER = logging.getLogger(__name__)

# Platforms are registered here once the entity modules exist. Keeping the list
# empty lets the integration be installed and the authorisation be tested
# without any entities.
PLATFORMS: list[Platform] = []


@dataclass
class SomTodayRuntimeData:
    """Runtime objects shared with the entity platforms."""

    auth: SomTodayAuthClient
    api: SomTodayApiClient


SomTodayConfigEntry = ConfigEntry[SomTodayRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: SomTodayConfigEntry
) -> bool:
    """Set up SomToday from a config entry."""
    session = async_get_clientsession(hass)
    auth = SomTodayAuthClient(
        session,
        entry.data[CONF_TENANT_UUID],
        auth_method=entry.data.get(CONF_AUTH_METHOD),
    )
    auth.tokens = SomTodayTokens.from_entry(entry)

    previous_refresh_token = auth.tokens.refresh_token
    try:
        await auth.async_ensure_valid()
    except SomTodayAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SomTodayConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except SomTodayError as err:
        raise ConfigEntryNotReady(str(err)) from err

    # SomToday rotates refresh tokens. Persist the new token so the next
    # restart keeps working. The coordinator will own this once it exists.
    if auth.tokens is not None and auth.tokens.refresh_token != previous_refresh_token:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **auth.as_entry_data()}
        )

    api_url = (
        auth.tokens.api_url
        if auth.tokens is not None
        else entry.data.get(CONF_API_URL) or DEFAULT_API_URL
    )
    api = SomTodayApiClient(session, auth, api_url)

    entry.runtime_data = SomTodayRuntimeData(auth=auth, api=api)

    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SomTodayConfigEntry
) -> bool:
    """Unload a config entry."""
    if PLATFORMS:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Migrate an old config entry to the current schema."""
    return True
