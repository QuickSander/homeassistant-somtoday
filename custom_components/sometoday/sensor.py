"""Sensor platform for the SomToday integration.

The first sensors are ``first_lesson_of_today`` and ``first_lesson_of_tomorrow``:
they drive an alarm clock, so their state is the start timestamp of the first
lesson on the **local** date of today (respectively tomorrow). The lesson may
already have started or finished; it is still "that day's first lesson". The
state is ``None`` when there is no lesson on that day.

The platform is structured around a list of entity constructors so the other
sensors from docs/architecture.md section 8.1 can be added without touching the
platform setup.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SomTodayData, SomTodayDataUpdateCoordinator
from .entity import SomTodayEntity
from .models import Grade, Lesson

# Grade sensors expose the raw list as an attribute, truncated to keep the
# recorder database and the state machine payload bounded.
_MAX_GRADES_RAW = 50

# Constructors for the sensor entities of this platform. The tuple itself is
# declared after the entity classes; ``async_setup_entry`` resolves it at call
# time. Only ``first_lesson_of_today`` is implemented; the remaining section 8.1
# sensors are added here in later slices.
EntityConstructor = Callable[
    [SomTodayDataUpdateCoordinator, ConfigEntry], SomTodayEntity
]


def _grade_recency(grade: Grade) -> float:
    """Return a sortable timestamp for a grade (0 when it has no date)."""
    if grade.date is None:
        return 0.0
    return grade.date.timestamp()


def _subject_key(grade: Grade) -> str:
    """Return the grouping key for a grade's subject."""
    return grade.subject or grade.subject_abbr or "Unknown"


def _valid_grades(data: SomTodayData | None) -> list[Grade]:
    """Return the usable grade rows, newest first.

    The API returns its own average columns as ordinary rows and marks rows
    that do not count; both are excluded, as are rows without a numeric grade
    (for example "V"). Excluding the average columns is what keeps the
    computed average an average of grades rather than of averages.
    """
    if data is None:
        return []
    grades = [
        grade
        for grade in data.grades
        if grade.value is not None
        and grade.counts
        and not grade.not_made
        and not grade.is_average_column
    ]
    grades.sort(key=lambda grade: (_grade_recency(grade), grade.id or ""), reverse=True)
    return grades


def _latest_grade(data: SomTodayData | None) -> Grade | None:
    """Return the most recently entered usable grade."""
    grades = _valid_grades(data)
    return grades[0] if grades else None


def _per_subject_averages(grades: list[Grade]) -> dict[str, float]:
    """Return the mean grade per subject, rounded to one decimal."""
    grouped: dict[str, list[float]] = {}
    for grade in grades:
        value = grade.value
        if value is None:
            continue
        grouped.setdefault(_subject_key(grade), []).append(value)
    return {
        subject: round(sum(values) / len(values), 1)
        for subject, values in grouped.items()
    }


def _latest_per_subject(grades: list[Grade]) -> dict[str, float]:
    """Return the newest grade per subject.

    ``grades`` must already be sorted newest first, so the first value seen for
    a subject is its latest.
    """
    latest: dict[str, float] = {}
    for grade in grades:
        value = grade.value
        if value is None:
            continue
        latest.setdefault(_subject_key(grade), value)
    return latest


def _grades_raw(grades: list[Grade]) -> list[dict[str, Any]]:
    """Return the grade rows as plain dicts, truncated for the attribute."""
    raw: list[dict[str, Any]] = []
    for grade in grades[:_MAX_GRADES_RAW]:
        entry: dict[str, Any] = {"subject": _subject_key(grade), "value": grade.value}
        if grade.type is not None:
            entry["type"] = grade.type
        if grade.date is not None:
            entry["date"] = grade.date.isoformat()
        raw.append(entry)
    return raw


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


class _SomTodayFirstLessonBase(SomTodayEntity, SensorEntity):
    """Start timestamp of the first lesson on a given local date.

    Subclasses set ``_key`` (also the unique-id suffix and translation key),
    ``_day_offset`` (days relative to the local date of "now") and
    ``_count_attribute`` (the attribute that exposes the number of lessons).
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    # Set by subclasses.
    _key: str
    _day_offset: int
    _count_attribute: str

    def __init__(
        self,
        coordinator: SomTodayDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the sensor entity."""
        super().__init__(coordinator, entry)
        self._attr_translation_key = self._key
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._first_lesson: Lesson | None = None
        self._day_lessons: list[Lesson] = []
        self._refresh_derived(dt_util.now())

    @property
    def native_value(self) -> datetime | None:
        """Return the start of the target day's first lesson, or ``None``."""
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
            self._count_attribute: len(self._day_lessons),
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
        """Cache the target day's first lesson and lesson list for a ``now``.

        The coordinator's schedule is already scoped per student and sorted, but
        the earliest lesson is selected explicitly so the sensor stays correct
        even if a caller supplies an unsorted schedule. Datetimes are normalised
        with ``dt_util.as_local`` so an offset-less timestamp cannot raise when
        it is compared with the aware local ``now``.
        """
        if self.coordinator.data is None:
            self._first_lesson = None
            self._day_lessons = []
            return

        target = now.date() + timedelta(days=self._day_offset)
        lessons = [
            lesson
            for lesson in self.coordinator.data.schedule
            if dt_util.as_local(lesson.start).date() == target
        ]
        self._day_lessons = lessons
        self._first_lesson = (
            min(lessons, key=lambda lesson: dt_util.as_local(lesson.start))
            if lessons
            else None
        )


class SomTodayFirstLessonSensor(_SomTodayFirstLessonBase):
    """Start timestamp of the first lesson on the local date of today."""

    _key = "first_lesson_of_today"
    _day_offset = 0
    _count_attribute = "lessons_today"


class SomTodayFirstLessonTomorrowSensor(_SomTodayFirstLessonBase):
    """Start timestamp of the first lesson on the local date of tomorrow."""

    _key = "first_lesson_of_tomorrow"
    _day_offset = 1
    _count_attribute = "lessons_tomorrow"


class SomTodayAverageGradeSensor(SomTodayEntity, SensorEntity):
    """Mean of the student's grades, with a per-subject breakdown.

    The state is the mean over all counting grades; the per-subject means are
    exposed as the ``averages`` attribute, so a dashboard can show the figure
    per vak without one entity per subject.
    """

    _attr_translation_key = "average_grade"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SomTodayDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the average-grade sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_average_grade"

    @property
    def native_value(self) -> float | None:
        """Return the mean of the counting grades, or ``None``."""
        grades = _valid_grades(self.coordinator.data)
        values = [grade.value for grade in grades if grade.value is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the per-subject means and the underlying grade lists."""
        grades = _valid_grades(self.coordinator.data)
        if not grades:
            return None
        return {
            "averages": _per_subject_averages(grades),
            # The newest grade per subject and the truncated raw list, as
            # described in docs/architecture.md section 8.1.
            "grades": _latest_per_subject(grades),
            "grades_raw": _grades_raw(grades),
        }


class SomTodayLatestGradeSensor(SomTodayEntity, SensorEntity):
    """The most recently entered grade, tagged with its subject."""

    _attr_translation_key = "latest_grade"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SomTodayDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the latest-grade sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_latest_grade"

    @property
    def native_value(self) -> float | None:
        """Return the most recent grade, or ``None``."""
        grade = _latest_grade(self.coordinator.data)
        return grade.value if grade is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the subject and details of the most recent grade."""
        grade = _latest_grade(self.coordinator.data)
        if grade is None:
            return None

        attributes: dict[str, Any] = {}
        subject = grade.subject or grade.subject_abbr
        if subject is not None:
            attributes["subject"] = subject
        if grade.subject_abbr is not None:
            attributes["subject_abbr"] = grade.subject_abbr
        if grade.date is not None:
            attributes["date"] = grade.date.isoformat()
        if grade.type is not None:
            attributes["type"] = grade.type
        attributes["counts"] = grade.counts
        return attributes


class SomTodayGradesCountSensor(SomTodayEntity, SensorEntity):
    """The number of counting grades in the current school year."""

    _attr_translation_key = "grades_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: SomTodayDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the grades-count sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_grades_count"

    @property
    def native_value(self) -> int:
        """Return the number of counting grades."""
        return len(_valid_grades(self.coordinator.data))


# Registered after the class definitions so the constructor tuple can reference
# the entity classes.
ENTITY_CONSTRUCTORS: tuple[EntityConstructor, ...] = (
    SomTodayFirstLessonSensor,
    SomTodayFirstLessonTomorrowSensor,
    SomTodayAverageGradeSensor,
    SomTodayLatestGradeSensor,
    SomTodayGradesCountSensor,
)
