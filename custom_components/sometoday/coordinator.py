"""DataUpdateCoordinator for the SomToday integration.

The coordinator polls the schedule for the config entry's student and keeps the
student list for the device metadata. This first data slice only fetches the
schedule; grades, homework and absence are added in later slices.

All parsing lives in ``models.py`` and all HTTP lives in ``api.py``; the
coordinator only orchestrates, scopes the data per student and maps errors to
the Home Assistant coordinator exceptions (docs/architecture.md section 5.1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import SomTodayApiClient
from .auth import SomTodayAuth
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DAYS_AHEAD,
    CONF_STUDENT_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCHEDULE_DAYS_AHEAD,
    DOMAIN,
)
from .exceptions import SomTodayError, SomtodayInvalidAuth
from .models import Lesson, Student, parse_lessons, utcnow

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SomTodayData:
    """Snapshot of the SomToday data used by the entities."""

    schedule: list[Lesson]
    students: list[Student]
    updated_at: datetime


class SomTodayDataUpdateCoordinator(DataUpdateCoordinator[SomTodayData]):
    """Fetch and scope the SomToday data for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: SomTodayApiClient,
        auth: SomTodayAuth,
    ) -> None:
        """Initialise the coordinator for a single student."""
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=int(scan_interval)),
            config_entry=entry,
        )
        self._entry = entry
        self._api = api
        self._auth = auth
        # The student is fixed at setup time; there is no ``students[0]``
        # fallback (docs/architecture.md section 5).
        self._student_id = int(entry.data[CONF_STUDENT_ID])
        self._schedule_days_ahead = int(
            entry.options.get(
                CONF_SCHEDULE_DAYS_AHEAD, DEFAULT_SCHEDULE_DAYS_AHEAD
            )
        )
        # The window the cached schedule actually covers, captured at fetch time
        # (not recomputed from "now", which would drift across midnight or after
        # a failed poll).
        self._data_window: tuple[date, date] | None = None

    @property
    def schedule_window(self) -> tuple[date, date]:
        """Return the date window the cached schedule actually covers.

        Used by the calendar to decide whether a requested range is cached. It
        is captured at fetch time, so it does not drift across midnight or after
        a failed poll.
        """
        if self._data_window is not None:
            return self._data_window
        return self._current_window()

    def _current_window(self) -> tuple[date, date]:
        """Return a fresh fetch window derived from today.

        The fetch window must be recomputed on every poll (so it advances across
        days); only the cached-data window is captured.
        """
        today = dt_util.now().date()
        return (
            today - timedelta(days=1),
            today + timedelta(days=self._schedule_days_ahead),
        )

    async def _async_update_data(self) -> SomTodayData:
        """Fetch, scope and sort the data for this config entry."""
        start, end = self._current_window()
        try:
            await self._auth.async_ensure_valid()

            schedule = await self.async_fetch_schedule(start, end)
            students = await self._async_get_students()
        except SomtodayInvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (SomTodayError, aiohttp.ClientError) as err:
            raise UpdateFailed(str(err)) from err

        # Persist a refresh token rotated anywhere during this poll (proactive
        # at the start, or reactive on a 401 inside a request) before returning.
        self._persist_rotated_token()
        self._data_window = (start, end)

        return SomTodayData(
            schedule=schedule,
            students=students,
            updated_at=utcnow(),
        )

    async def async_fetch_schedule(self, start: date, end: date) -> list[Lesson]:
        """Fetch, parse and scope a schedule range without touching cached data.

        Used by the calendar for ranges outside the cached window.
        """
        await self._auth.async_ensure_valid()
        payload = await self._api.async_get_appointments(start, end)
        return self._filter_lessons(parse_lessons(payload))

    def _filter_lessons(self, lessons: list[Lesson]) -> list[Lesson]:
        """Keep only this student's lessons and sort them by start time.

        An appointment without a student list is kept: that is the normal
        single-student shape (docs/architecture.md section 7.2.1).
        """
        filtered = [
            lesson
            for lesson in lessons
            if not lesson.student_ids or self._student_id in lesson.student_ids
        ]
        # Normalise before sorting so a mixed naive/aware payload cannot raise
        # (finding N1; same class as the calendar S1 fix).
        filtered.sort(key=lambda lesson: dt_util.as_local(lesson.start))
        return filtered

    async def _async_get_students(self) -> list[Student]:
        """Return the student list, falling back to the previous snapshot.

        The student list is only used for device metadata, so a failure here
        must not fail the whole poll. A definitive auth rejection is the one
        exception: it must still escalate.
        """
        try:
            return await self._api.async_get_students()
        except SomtodayInvalidAuth:
            raise
        except (SomTodayError, aiohttp.ClientError) as err:
            _LOGGER.debug("Could not refresh the SomToday student list: %s", err)
            if self.data is not None:
                return list(self.data.students)
            return []

    def _persist_rotated_token(self) -> None:
        """Persist a rotated refresh token (and account metadata) when changed."""
        new_data = self._auth.as_entry_data()
        if any(self._entry.data.get(key) != value for key, value in new_data.items()):
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, **new_data}
            )
