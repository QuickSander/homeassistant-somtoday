"""Calendar platform for the SomToday integration.

The calendar is read-only and shows the lessons of the config entry's student.
The ``event`` property serves the current or next lesson for the entity card;
``async_get_events`` serves the requested range from the coordinator's cached
schedule, or fetches it from the API when the range falls outside the cache
(docs/architecture.md section 8.3).
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SomTodayDataUpdateCoordinator
from .entity import SomTodayEntity
from .models import Lesson


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SomToday calendar from a config entry."""
    coordinator: SomTodayDataUpdateCoordinator = entry.runtime_data.coordinator
    async_add_entities([SomTodayCalendar(coordinator, entry)])


class SomTodayCalendar(SomTodayEntity, CalendarEntity):
    """A read-only calendar of the student's lessons."""

    _attr_translation_key = "calendar"

    def __init__(
        self,
        coordinator: SomTodayDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the calendar entity."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the lesson in progress, or the next upcoming lesson."""
        lesson = self._current_or_next_lesson()
        if lesson is None:
            return None
        return self._event_from_lesson(lesson)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return the lessons that overlap the requested datetime range."""
        lessons = await self._lessons_for_range(start_date, end_date)
        return [
            self._event_from_lesson(lesson)
            for lesson in lessons
            if _overlaps(lesson, start_date, end_date)
        ]

    def _current_or_next_lesson(self) -> Lesson | None:
        """Return the current lesson, else the first lesson that starts later."""
        now = dt_util.now()
        schedule = self.coordinator.data.schedule if self.coordinator.data else []
        for lesson in schedule:
            # Normalise in case a lesson carries an offset-less timestamp, so an
            # aware/naive comparison can never raise (finding S1).
            start = dt_util.as_local(lesson.start)
            end = dt_util.as_local(lesson.end)
            if start <= now <= end:
                return lesson
            if start > now:
                return lesson
        return None

    async def _lessons_for_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[Lesson]:
        """Return the cached lessons, fetching from the API when out of range."""
        window_start, window_end = self.coordinator.schedule_window
        requested_start = dt_util.as_local(start_date).date()
        requested_end = dt_util.as_local(end_date).date()

        if window_start <= requested_start and requested_end <= window_end:
            if self.coordinator.data is None:
                return []
            return list(self.coordinator.data.schedule)

        return await self.coordinator.async_fetch_schedule(
            requested_start, requested_end
        )

    def _event_from_lesson(self, lesson: Lesson) -> CalendarEvent:
        """Map a lesson to a Home Assistant calendar event."""
        room = lesson.room
        subject = lesson.subject or lesson.title or "Lesson"
        summary = f"{subject} ({room})" if room else subject
        return CalendarEvent(
            summary=summary,
            # HA's CalendarEvent requires timezone-aware datetimes; normalise in
            # case a lesson carries an offset-less timestamp (finding S1).
            start=dt_util.as_local(lesson.start),
            end=dt_util.as_local(lesson.end),
            location=room,
            description=lesson.teacher,
        )


def _overlaps(lesson: Lesson, start_date: datetime, end_date: datetime) -> bool:
    """Return whether a lesson overlaps the requested datetime range."""
    range_start = dt_util.as_local(start_date)
    range_end = dt_util.as_local(end_date)
    lesson_start = dt_util.as_local(lesson.start)
    lesson_end = dt_util.as_local(lesson.end)
    return lesson_end > range_start and lesson_start < range_end
