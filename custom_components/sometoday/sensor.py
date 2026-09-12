"""Sensor platform for the SomToday integration.

The first sensor is ``first_lesson_of_today``: it drives an alarm clock, so its
state is the start timestamp of the first lesson on the **local** date of today.
The lesson may already have started or finished; it is still "today's first
lesson". The state is ``None`` when there is no lesson today.

The platform is structured around a list of entity constructors so the other
sensors from docs/architecture.md section 8.1 can be added without touching the
platform setup.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SomTodayDataUpdateCoordinator
from .entity import SomTodayEntity
from .models import Lesson

# Constructors for the sensor entities of this platform. The tuple itself is
# declared after the entity classes; ``async_setup_entry`` resolves it at call
# time. Only ``first_lesson_of_today`` is implemented; the remaining section 8.1
# sensors are added here in later slices.
EntityConstructor = Callable[
    [SomTodayDataUpdateCoordinator, ConfigEntry], SomTodayEntity
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SomToday sensors from a config entry."""
    coordinator: SomTodayDataUpdateCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        constructor(coordinator, entry) for constructor in ENTITY_CONSTRUCTORS
    )


class SomTodayFirstLessonSensor(SomTodayEntity, SensorEntity):
    """Start timestamp of the first lesson on the local date of today."""

    _attr_translation_key = "first_lesson_of_today"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: SomTodayDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the sensor entity."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_first_lesson_of_today"
        self._first_lesson: Lesson | None = None
        self._today_lessons: list[Lesson] = []
        self._refresh_derived(dt_util.now())

    @property
    def native_value(self) -> datetime | None:
        """Return the start of today's first lesson, or ``None`` when free."""
        if self._first_lesson is None:
            return None
        return dt_util.as_local(self._first_lesson.start)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the first lesson's details, omitting missing values."""
        first = self._first_lesson
        if first is None:
            return None

        attributes: dict[str, Any] = {
            # ``end`` is normalised so the attribute is always timezone-aware,
            # matching the TIMESTAMP state.
            "end": dt_util.as_local(first.end),
            "lessons_today": len(self._today_lessons),
        }
        if first.subject is not None:
            attributes["subject"] = first.subject
        if first.room is not None:
            attributes["room"] = first.room
        if first.teacher is not None:
            attributes["teacher"] = first.teacher
        if first.id is not None:
            attributes["lesson_id"] = first.id
        return attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Recompute the derived values from a single "now" per update.

        Computing them once keeps the state and the attributes consistent even
        if local midnight passes while Home Assistant writes the entity (S4).
        """
        self._refresh_derived(dt_util.now())
        super()._handle_coordinator_update()

    def _refresh_derived(self, now: datetime) -> None:
        """Cache today's first lesson and lesson list for a single ``now``.

        The coordinator's schedule is already scoped per student and sorted, but
        the earliest lesson is selected explicitly so the sensor stays correct
        even if a caller supplies an unsorted schedule. Datetimes are normalised
        with ``dt_util.as_local`` so an offset-less timestamp cannot raise when
        it is compared with the aware local ``now``.
        """
        if self.coordinator.data is None:
            self._first_lesson = None
            self._today_lessons = []
            return

        today = now.date()
        lessons = [
            lesson
            for lesson in self.coordinator.data.schedule
            if dt_util.as_local(lesson.start).date() == today
        ]
        self._today_lessons = lessons
        self._first_lesson = (
            min(lessons, key=lambda lesson: dt_util.as_local(lesson.start))
            if lessons
            else None
        )


# Registered after the class definition so the constructor tuple can reference
# the entity class.
ENTITY_CONSTRUCTORS: tuple[EntityConstructor, ...] = (SomTodayFirstLessonSensor,)
