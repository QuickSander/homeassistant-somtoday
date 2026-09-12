"""Tests for the SomToday integration setup and unload.

All SomToday HTTP calls are mocked; the real API is never contacted.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sometoday.api import SomTodayApiClient
from custom_components.sometoday.auth import SomTodayAuth
from custom_components.sometoday.const import (
    CONF_API_URL,
    CONF_REFRESH_TOKEN,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    DOMAIN,
)
from custom_components.sometoday.coordinator import SomTodayDataUpdateCoordinator
from custom_components.sometoday.exceptions import SomTodayError, SomtodayInvalidAuth
from custom_components.sometoday.models import Student

API_URL = "https://api.somtoday.nl"
STUDENT_ID = 1234


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Iterator[None]:
    """Enable loading the custom integration in every test."""
    yield


def _raw_lesson() -> dict[str, Any]:
    """Return one appointment inside the coordinator window."""
    start = dt_util.now() + timedelta(hours=1)
    return {
        "links": [{"id": 1, "rel": "self"}],
        "vak": {"naam": "Wiskunde", "afkorting": "WI"},
        "docentAfkortingen": "JDO",
        "locatie": "B12",
        "beginDatumTijd": start.isoformat(),
        "eindDatumTijd": (start + timedelta(minutes=50)).isoformat(),
        "afspraakType": {"naam": "LES"},
    }


def _make_entry(hass: Any) -> MockConfigEntry:
    """Create and register a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=f"account-1:{STUDENT_ID}",
        data={
            CONF_REFRESH_TOKEN: "refresh",
            CONF_API_URL: API_URL,
            CONF_STUDENT_ID: STUDENT_ID,
            CONF_STUDENT_NAME: "Eli Saado",
        },
    )
    entry.add_to_hass(hass)
    return entry


@contextmanager
def _patched_setup(
    *,
    appointments: list[dict[str, Any]] | None = None,
    students: list[Student] | None = None,
    schedule_error: Exception | None = None,
) -> Iterator[None]:
    """Patch auth and the two coordinator endpoints."""

    async def _ensure_valid(self: SomTodayAuth) -> None:
        return None

    async def _appointments(
        self: SomTodayApiClient, start: Any, end: Any
    ) -> list[dict[str, Any]]:
        if schedule_error is not None:
            raise schedule_error
        return list(appointments or [])

    async def _students(self: SomTodayApiClient) -> list[Student]:
        return list(students or [])

    with (
        patch.object(SomTodayAuth, "async_ensure_valid", new=_ensure_valid),
        patch.object(
            SomTodayApiClient, "async_get_appointments", new=_appointments
        ),
        patch.object(SomTodayApiClient, "async_get_students", new=_students),
    ):
        yield


async def test_setup_entry_creates_coordinator_and_entities(hass: Any) -> None:
    """Setup builds the coordinator and forwards the calendar and sensor platforms."""
    entry = _make_entry(hass)

    with _patched_setup(
        appointments=[_raw_lesson()],
        students=[Student(id=STUDENT_ID, roepnaam="Eli")],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data.coordinator
    assert isinstance(coordinator, SomTodayDataUpdateCoordinator)
    assert [lesson.id for lesson in coordinator.data.schedule] == ["1"]
    assert len(hass.states.async_entity_ids("calendar")) == 1
    assert len(hass.states.async_entity_ids("sensor")) == 1


async def test_setup_entry_schedule_failure_is_retryable(hass: Any) -> None:
    """A transient schedule failure leaves the entry retryable."""
    entry = _make_entry(hass)

    with _patched_setup(schedule_error=SomTodayError("offline")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_invalid_auth_triggers_reauth(hass: Any) -> None:
    """A definitive auth rejection during the first poll triggers reauth."""
    entry = _make_entry(hass)

    with _patched_setup(schedule_error=SomtodayInvalidAuth("expired")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_entry_unloads_platforms(hass: Any) -> None:
    """Unloading the entry unloads the calendar and sensor platforms."""
    entry = _make_entry(hass)

    with _patched_setup(appointments=[_raw_lesson()]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_ids = [
            *hass.states.async_entity_ids("calendar"),
            *hass.states.async_entity_ids("sensor"),
        ]
        assert len(entity_ids) == 2

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # A registered entity is set to ``unavailable`` rather than deleted.
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "unavailable"
