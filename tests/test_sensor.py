"""Unit tests for the SomToday first-lesson sensor.

The entity is bound to a real coordinator whose API calls are mocked, so no
network access is ever needed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.translation import async_get_translations
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
from custom_components.sometoday.coordinator import (
    SomTodayData,
    SomTodayDataUpdateCoordinator,
)
from custom_components.sometoday.models import Grade, Lesson, Student
from custom_components.sometoday.sensor import (
    SomTodayAverageGradeSensor,
    SomTodayFirstLessonSensor,
    SomTodayFirstLessonTomorrowSensor,
    SomTodayGradesCountSensor,
    SomTodayLatestGradeSensor,
    _latest_per_subject,
    _per_subject_averages,
)

STUDENT_ID = 1234


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Any:
    """Enable loading the custom integration in every test."""
    yield


def _lesson(
    start: datetime,
    end: datetime,
    *,
    lesson_id: str | None = "1",
    subject: str | None = "Wiskunde",
    room: str | None = "B12",
    teacher: str | None = "JDO",
) -> Lesson:
    """Return a parsed lesson for the coordinator snapshot."""
    return Lesson(
        id=lesson_id,
        subject=subject,
        subject_abbr="WI",
        teacher=teacher,
        room=room,
        start=start,
        end=end,
        title=None,
        type="LES",
        student_ids=frozenset(),
    )


def _grade(
    value: float,
    *,
    grade_id: str = "1",
    subject: str | None = "Wiskunde",
    subject_abbr: str | None = "WI",
    day: datetime | None = None,
    counts: bool = True,
    grade_type: str = "Toetskolom",
    not_made: bool = False,
) -> Grade:
    """Return a parsed grade for the coordinator snapshot."""
    return Grade(
        id=grade_id,
        result=value,
        valid_result=value,
        date=day,
        counts=counts,
        type=grade_type,
        subject=subject,
        subject_abbr=subject_abbr,
        not_made=not_made,
    )


def _coordinator(
    hass: Any,
    schedule: list[Lesson] | None = None,
    grades: list[Grade] | None = None,
) -> tuple[SomTodayDataUpdateCoordinator, MockConfigEntry]:
    """Build a coordinator with a pre-populated schedule and grades snapshot."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_STUDENT_ID: STUDENT_ID, CONF_STUDENT_NAME: "Eli Saado"},
        options={},
    )
    entry.add_to_hass(hass)

    auth = MagicMock()
    auth.async_ensure_valid = AsyncMock()
    api = MagicMock()
    api.async_get_appointments = AsyncMock(return_value=[])
    api.async_get_students = AsyncMock(return_value=[])

    coordinator = SomTodayDataUpdateCoordinator(hass, entry, api, auth)
    coordinator.data = SomTodayData(
        schedule=list(schedule or []),
        students=[],
        grades=list(grades or []),
        updated_at=dt_util.utcnow(),
    )
    return coordinator, entry


def _today_start() -> datetime:
    """Return the local start of today as a timezone-aware datetime."""
    return dt_util.start_of_local_day()


# ---------------------------------------------------------------------------
# State and attributes
# ---------------------------------------------------------------------------
async def test_first_lesson_state_and_attributes(hass: Any) -> None:
    """The earliest of today's lessons is the state, with its details attached."""
    day = _today_start()
    early = _lesson(day + timedelta(hours=9), day + timedelta(hours=10), lesson_id="1")
    late = _lesson(day + timedelta(hours=11), day + timedelta(hours=12), lesson_id="2")
    tomorrow = _lesson(
        day + timedelta(days=1, hours=9),
        day + timedelta(days=1, hours=10),
        lesson_id="3",
    )
    # The schedule is deliberately unsorted so the sensor must pick the earliest.
    coordinator, entry = _coordinator(hass, [late, tomorrow, early])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value == early.start
    assert entity.native_value is not None
    assert entity.native_value.tzinfo is not None

    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["subject"] == "Wiskunde"
    assert attributes["room"] == "B12"
    assert attributes["teacher"] == "JDO"
    assert attributes["end"] == early.end
    assert attributes["end"].tzinfo is not None
    assert attributes["lesson_id"] == "1"
    assert attributes["lessons_today"] == 2


async def test_no_lessons_today_returns_none(hass: Any) -> None:
    """Only lessons on other days leave the state and attributes empty."""
    day = _today_start()
    tomorrow = _lesson(
        day + timedelta(days=1, hours=9), day + timedelta(days=1, hours=10)
    )
    coordinator, entry = _coordinator(hass, [tomorrow])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


async def test_lesson_already_started_is_still_returned(hass: Any) -> None:
    """A lesson that already started (or finished) is still today's first."""
    day = _today_start()
    lesson = _lesson(day, day + timedelta(hours=1))
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value == day


async def test_missing_attributes_are_omitted(hass: Any) -> None:
    """Unset lesson fields are not exposed as attributes."""
    day = _today_start()
    lesson = _lesson(
        day + timedelta(hours=9),
        day + timedelta(hours=10),
        lesson_id=None,
        subject=None,
        room=None,
        teacher=None,
    )
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert "subject" not in attributes
    assert "room" not in attributes
    assert "teacher" not in attributes
    assert "lesson_id" not in attributes
    assert attributes["lessons_today"] == 1
    assert attributes["end"] == lesson.end


async def test_empty_schedule_returns_none(hass: Any) -> None:
    """A present but empty schedule is distinct from a missing snapshot."""
    coordinator, entry = _coordinator(hass, [])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


async def test_only_yesterday_lesson_returns_none(hass: Any) -> None:
    """A lesson on another past day is not today's first lesson."""
    day = _today_start()
    yesterday = _lesson(
        day - timedelta(days=1),
        day - timedelta(days=1) + timedelta(hours=1),
    )
    coordinator, entry = _coordinator(hass, [yesterday])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


async def test_lesson_crossing_midnight_counts_for_its_start_day(hass: Any) -> None:
    """A lesson starting late today counts for today even if it ends tomorrow."""
    day = _today_start()
    start = day + timedelta(hours=23, minutes=30)
    end = start + timedelta(hours=1)
    coordinator, entry = _coordinator(hass, [_lesson(start, end)])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value == start
    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["end"] == end
    assert attributes["lessons_today"] == 1


async def test_lesson_started_yesterday_is_not_today(hass: Any) -> None:
    """A lesson that started before local midnight is not counted for today.

    The day is derived from the lesson's *start*; a lesson that spills over
    midnight from yesterday belongs to yesterday.
    """
    day = _today_start()
    start = day - timedelta(minutes=30)
    coordinator, entry = _coordinator(
        hass, [_lesson(start, start + timedelta(hours=1))]
    )
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


# ---------------------------------------------------------------------------
# first_lesson_of_tomorrow
# ---------------------------------------------------------------------------
async def test_first_lesson_of_tomorrow_state_and_attributes(hass: Any) -> None:
    """The earliest of tomorrow's lessons is the state, today is ignored."""
    day = _today_start()
    today = _lesson(day + timedelta(hours=9), day + timedelta(hours=10), lesson_id="1")
    early = _lesson(
        day + timedelta(days=1, hours=8),
        day + timedelta(days=1, hours=9),
        lesson_id="2",
    )
    late = _lesson(
        day + timedelta(days=1, hours=11),
        day + timedelta(days=1, hours=12),
        lesson_id="3",
    )
    # Unsorted input, and a today lesson that must not be selected.
    coordinator, entry = _coordinator(hass, [late, today, early])
    entity = SomTodayFirstLessonTomorrowSensor(coordinator, entry)

    assert entity.native_value == early.start
    assert entity.native_value is not None
    assert entity.native_value.tzinfo is not None

    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["subject"] == "Wiskunde"
    assert attributes["room"] == "B12"
    assert attributes["teacher"] == "JDO"
    assert attributes["end"] == early.end
    assert attributes["lesson_id"] == "2"
    assert attributes["lessons_tomorrow"] == 2


async def test_no_lessons_tomorrow_returns_none(hass: Any) -> None:
    """Only today's lessons leave tomorrow's state and attributes empty."""
    day = _today_start()
    today = _lesson(day + timedelta(hours=9), day + timedelta(hours=10))
    coordinator, entry = _coordinator(hass, [today])
    entity = SomTodayFirstLessonTomorrowSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


def test_first_lesson_tomorrow_entity_metadata(hass: Any) -> None:
    """The tomorrow entity carries the shared device metadata and attributes."""
    coordinator, entry = _coordinator(hass, [])
    entity = SomTodayFirstLessonTomorrowSensor(coordinator, entry)

    assert entity._attr_has_entity_name is True
    assert entity._attr_translation_key == "first_lesson_of_tomorrow"
    assert entity.device_class == SensorDeviceClass.TIMESTAMP
    assert entity.unique_id == f"{entry.entry_id}_first_lesson_of_tomorrow"
    assert entity.device_info["identifiers"] == {(DOMAIN, entry.entry_id)}
    assert entity.device_info["name"] == "SomToday Eli Saado"


async def test_first_lesson_tomorrow_name_translations(hass: Any) -> None:
    """The tomorrow entity name loads from the translation key in both locales."""
    english = await async_get_translations(hass, "en", "entity", [DOMAIN])
    dutch = await async_get_translations(hass, "nl", "entity", [DOMAIN])

    key = f"component.{DOMAIN}.entity.sensor.first_lesson_of_tomorrow.name"
    assert english[key] == "First lesson of tomorrow"
    assert dutch[key] == "Eerste les morgen"


# ---------------------------------------------------------------------------
# Timezone robustness
# ---------------------------------------------------------------------------
async def test_aware_plus_two_lesson_yields_same_instant(hass: Any) -> None:
    """A lesson with a +02:00 offset keeps its instant and is normalised local."""
    local_start = dt_util.now().replace(hour=8, minute=0, second=0, microsecond=0)
    plus_two = local_start.astimezone(timezone(timedelta(hours=2)))
    lesson = _lesson(plus_two, plus_two + timedelta(hours=1))
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    value = entity.native_value
    assert value == local_start
    assert value == plus_two
    assert value is not None
    assert value.tzinfo is not None


async def test_z_suffix_lesson_yields_same_instant(hass: Any) -> None:
    """A UTC ``Z`` timestamp keeps its instant and yields a datetime value."""
    local_start = dt_util.now().replace(hour=9, minute=0, second=0, microsecond=0)
    z_string = local_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    utc_start = datetime.fromisoformat(z_string.replace("Z", "+00:00"))
    lesson = _lesson(utc_start, utc_start + timedelta(hours=1))
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    value = entity.native_value
    # The TIMESTAMP device class requires a timezone-aware datetime, not a
    # string or a date.
    assert isinstance(value, datetime)
    assert value == local_start
    assert value == utc_start
    assert value is not None
    assert value.tzinfo is not None


async def test_naive_lesson_is_handled(hass: Any) -> None:
    """An offset-less timestamp is normalised without raising."""
    today = dt_util.now().date()
    naive_start = datetime(today.year, today.month, today.day, 10, 0)  # noqa: DTZ001
    naive_end = naive_start + timedelta(hours=1)
    coordinator, entry = _coordinator(hass, [_lesson(naive_start, naive_end)])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    value = entity.native_value
    assert value == dt_util.as_local(naive_start)
    assert value is not None
    assert value.tzinfo is not None
    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["end"] == dt_util.as_local(naive_end)


async def test_without_snapshot_returns_none(hass: Any) -> None:
    """No coordinator snapshot means no state and no attributes."""
    coordinator, entry = _coordinator(hass, [])
    coordinator.data = None
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


# ---------------------------------------------------------------------------
# Entity metadata and availability
# ---------------------------------------------------------------------------
def test_first_lesson_entity_metadata(hass: Any) -> None:
    """The entity carries the shared device metadata and the sensor attributes."""
    coordinator, entry = _coordinator(hass, [])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity._attr_has_entity_name is True
    assert entity._attr_translation_key == "first_lesson_of_today"
    assert entity.device_class == SensorDeviceClass.TIMESTAMP
    assert entity.unique_id == f"{entry.entry_id}_first_lesson_of_today"
    assert entity.device_info["identifiers"] == {(DOMAIN, entry.entry_id)}
    assert entity.device_info["name"] == "SomToday Eli Saado"
    assert entity.device_info["manufacturer"] == "SomToday"


async def test_first_lesson_name_translations(hass: Any) -> None:
    """The entity name loads from the translation key in both locales."""
    english = await async_get_translations(hass, "en", "entity", [DOMAIN])
    dutch = await async_get_translations(hass, "nl", "entity", [DOMAIN])

    key = f"component.{DOMAIN}.entity.sensor.first_lesson_of_today.name"
    assert english[key] == "First lesson of today"
    assert dutch[key] == "Eerste les vandaag"


def test_unavailable_when_update_failed(hass: Any) -> None:
    """A failed coordinator update makes the entity unavailable."""
    coordinator, entry = _coordinator(hass, [])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.available is True
    coordinator.last_update_success = False
    assert entity.available is False


# ---------------------------------------------------------------------------
# Integration: full config-entry setup renders a valid TIMESTAMP state
# ---------------------------------------------------------------------------
def _raw_lesson(start: datetime) -> dict[str, Any]:
    """Return one appointment inside the coordinator window."""
    return {
        "links": [{"id": 1, "rel": "self"}],
        "locatie": "B12",
        "beginDatumTijd": start.isoformat(),
        "eindDatumTijd": (start + timedelta(minutes=50)).isoformat(),
        "afspraakType": {"naam": "LES"},
        "additionalObjects": {
            "vak": {"naam": "Wiskunde", "afkorting": "WI"},
            "docentAfkortingen": "JDO",
        },
    }


@contextmanager
def _patched_api(appointments: list[dict[str, Any]]) -> Iterator[None]:
    """Patch auth and both coordinator endpoints for a full setup."""

    async def _ensure_valid(self: SomTodayAuth) -> None:
        return None

    async def _appointments(
        self: SomTodayApiClient, start: Any, end: Any
    ) -> list[dict[str, Any]]:
        return list(appointments)

    async def _students(self: SomTodayApiClient) -> list[Student]:
        return [Student(id=STUDENT_ID, roepnaam="Eli")]

    async def _grades(
        self: SomTodayApiClient, student_id: Any
    ) -> list[dict[str, Any]]:
        return []

    with (
        patch.object(SomTodayAuth, "async_ensure_valid", new=_ensure_valid),
        patch.object(
            SomTodayApiClient, "async_get_appointments", new=_appointments
        ),
        patch.object(SomTodayApiClient, "async_get_students", new=_students),
        patch.object(SomTodayApiClient, "async_get_grades", new=_grades),
    ):
        yield


async def test_sensor_state_renders_after_setup(hass: Any) -> None:
    """A real platform setup renders the state as a UTC ISO timestamp.

    This exercises the path that unit tests cannot: the entity attached to a
    platform, where HA validates and serialises the ``TIMESTAMP`` device class.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=f"account-1:{STUDENT_ID}",
        data={
            CONF_REFRESH_TOKEN: "refresh",
            CONF_API_URL: "https://api.somtoday.nl",
            CONF_STUDENT_ID: STUDENT_ID,
            CONF_STUDENT_NAME: "Eli Saado",
        },
    )
    entry.add_to_hass(hass)

    local_start = dt_util.now().replace(hour=9, minute=0, second=0, microsecond=0)
    with _patched_api([_raw_lesson(local_start)]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entity_ids = hass.states.async_entity_ids("sensor")
    assert entity_ids == [
        "sensor.somtoday_eli_saado_first_lesson_of_today",
        "sensor.somtoday_eli_saado_first_lesson_of_tomorrow",
        "sensor.somtoday_eli_saado_average_grade",
        "sensor.somtoday_eli_saado_latest_grade",
        "sensor.somtoday_eli_saado_grades_count",
    ]
    state = hass.states.get(entity_ids[0])
    assert state is not None
    # HA stores a TIMESTAMP as a timezone-aware ISO string in UTC.
    assert state.state == dt_util.as_utc(local_start).isoformat(timespec="seconds")
    assert state.attributes["device_class"] == "timestamp"
    assert state.attributes["friendly_name"] == (
        "SomToday Eli Saado First lesson of today"
    )
    assert state.attributes["lessons_today"] == 1
    assert state.attributes["subject"] == "Wiskunde"

    # There is no lesson tomorrow in this setup, so that sensor is unknown.
    tomorrow = hass.states.get(entity_ids[1])
    assert tomorrow is not None
    assert tomorrow.state == "unknown"
    assert tomorrow.attributes["friendly_name"] == (
        "SomToday Eli Saado First lesson of tomorrow"
    )


# ---------------------------------------------------------------------------
# Consistency (finding S4) and coordinator updates
# ---------------------------------------------------------------------------
async def test_state_and_attributes_use_a_single_now(hass: Any) -> None:
    """State and attributes stay consistent across a midnight change (S4)."""
    day = _today_start()
    lesson = _lesson(day + timedelta(hours=9), day + timedelta(hours=10))
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    # A day rollover between the two reads must not desync them: both are
    # derived from one "now" captured before Home Assistant writes the state.
    tomorrow = day + timedelta(days=1)
    with patch(
        "custom_components.sometoday.sensor.dt_util.now",
        side_effect=[tomorrow, tomorrow],
    ):
        assert entity.native_value == lesson.start
        attributes = entity.extra_state_attributes

    assert attributes is not None
    assert attributes["lessons_today"] == 1
    assert attributes["lesson_id"] == "1"


async def test_coordinator_update_recomputes_the_first_lesson(hass: Any) -> None:
    """A new snapshot recomputes today's first lesson and its attributes."""
    day = _today_start()
    later = _lesson(day + timedelta(hours=11), day + timedelta(hours=12))
    coordinator, entry = _coordinator(hass, [later])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value == later.start

    earlier = _lesson(day + timedelta(hours=8), day + timedelta(hours=9))
    coordinator.data = SomTodayData(
        schedule=[later, earlier],
        students=[],
        updated_at=dt_util.utcnow(),
    )
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity.native_value == earlier.start
    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["lessons_today"] == 2


async def test_coordinator_update_rolls_over_to_the_new_day(hass: Any) -> None:
    """A coordinator update after local midnight selects the new day's lesson.

    ``_handle_coordinator_update`` is the only place the cached "now" is
    refreshed; a stale snapshot would keep returning yesterday's lesson.
    """
    day1 = _today_start()
    day2 = day1 + timedelta(days=1)
    day1_lesson = _lesson(
        day1 + timedelta(hours=9), day1 + timedelta(hours=10), lesson_id="1"
    )
    day2_lesson = _lesson(
        day2 + timedelta(hours=8), day2 + timedelta(hours=9), lesson_id="2"
    )
    coordinator, entry = _coordinator(hass, [day1_lesson, day2_lesson])
    entity = SomTodayFirstLessonSensor(coordinator, entry)

    assert entity.native_value == day1_lesson.start

    with (
        patch("custom_components.sometoday.sensor.dt_util.now", return_value=day2),
        patch.object(entity, "async_write_ha_state"),
    ):
        entity._handle_coordinator_update()

    assert entity.native_value == day2_lesson.start
    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["lesson_id"] == "2"
    assert attributes["lessons_today"] == 1


# ---------------------------------------------------------------------------
# Grade sensors
# ---------------------------------------------------------------------------
def _day(day: int) -> datetime:
    """Return a timezone-aware datetime on a given September day."""
    return datetime(2026, 9, day, 10, 0, tzinfo=timezone.utc)


async def test_average_grade_overall_and_per_subject(hass: Any) -> None:
    """The average sensor reports the overall mean and a per-subject map."""
    grades = [
        _grade(7.0, grade_id="1", day=_day(1)),
        _grade(8.0, grade_id="2", day=_day(2)),
        _grade(
            6.0, grade_id="3", subject="Scheikunde", subject_abbr="SCH", day=_day(3)
        ),
    ]
    coordinator, entry = _coordinator(hass, grades=grades)
    entity = SomTodayAverageGradeSensor(coordinator, entry)

    assert entity.native_value == 7.0
    attributes = entity.extra_state_attributes
    assert attributes is not None
    # The requirement: the average is broken down per subject (vak).
    assert attributes["averages"] == {"Wiskunde": 7.5, "Scheikunde": 6.0}
    # The newest grade per subject backs the ``grades`` map.
    assert attributes["grades"] == {"Wiskunde": 8.0, "Scheikunde": 6.0}
    assert len(attributes["grades_raw"]) == 3


async def test_average_grade_excludes_average_columns_and_non_counting(
    hass: Any,
) -> None:
    """API average columns, non-counting and not-made grades are excluded."""
    grades = [
        _grade(8.0, grade_id="1", day=_day(1)),
        _grade(
            2.0,
            grade_id="2",
            day=_day(2),
            grade_type="ToetssoortGemiddeldeKolom",
        ),
        _grade(1.0, grade_id="3", day=_day(3), counts=False),
        _grade(1.0, grade_id="4", day=_day(4), not_made=True),
    ]
    coordinator, entry = _coordinator(hass, grades=grades)
    entity = SomTodayAverageGradeSensor(coordinator, entry)

    assert entity.native_value == 8.0
    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["averages"] == {"Wiskunde": 8.0}
    assert attributes["grades"] == {"Wiskunde": 8.0}
    assert len(attributes["grades_raw"]) == 1


async def test_average_grade_no_grades_returns_none(hass: Any) -> None:
    """Without usable grades the state and attributes are empty."""
    coordinator, entry = _coordinator(hass, grades=[])
    entity = SomTodayAverageGradeSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


async def test_average_grade_rounds_to_one_decimal(hass: Any) -> None:
    """The mean is rounded to one decimal."""
    grades = [
        _grade(7.0, grade_id="1", day=_day(1)),
        _grade(8.0, grade_id="2", day=_day(2)),
        _grade(8.0, grade_id="3", day=_day(3)),
    ]
    coordinator, entry = _coordinator(hass, grades=grades)
    entity = SomTodayAverageGradeSensor(coordinator, entry)

    assert entity.native_value == 7.7


async def test_latest_grade_state_and_subject(hass: Any) -> None:
    """The latest grade sensor exposes the newest grade and its subject."""
    grades = [
        _grade(7.0, grade_id="1", day=_day(1)),
        _grade(
            8.5, grade_id="2", subject="Scheikunde", subject_abbr="SCH", day=_day(5)
        ),
    ]
    coordinator, entry = _coordinator(hass, grades=grades)
    entity = SomTodayLatestGradeSensor(coordinator, entry)

    assert entity.native_value == 8.5
    attributes = entity.extra_state_attributes
    assert attributes is not None
    # The requirement: the latest grade states which subject it was for.
    assert attributes["subject"] == "Scheikunde"
    assert attributes["subject_abbr"] == "SCH"
    assert attributes["date"] == _day(5).isoformat()
    assert attributes["type"] == "Toetskolom"
    assert attributes["counts"] is True


async def test_latest_grade_falls_back_to_abbreviation(hass: Any) -> None:
    """Without a full subject name the abbreviation is used as the subject."""
    grades = [
        _grade(7.0, grade_id="1", subject=None, subject_abbr="WI", day=_day(1))
    ]
    coordinator, entry = _coordinator(hass, grades=grades)
    entity = SomTodayLatestGradeSensor(coordinator, entry)

    attributes = entity.extra_state_attributes
    assert attributes is not None
    assert attributes["subject"] == "WI"
    assert attributes["subject_abbr"] == "WI"


async def test_latest_grade_no_grades_returns_none(hass: Any) -> None:
    """Without usable grades the state and attributes are empty."""
    coordinator, entry = _coordinator(hass, grades=[])
    entity = SomTodayLatestGradeSensor(coordinator, entry)

    assert entity.native_value is None
    assert entity.extra_state_attributes is None


async def test_grades_count_counts_only_valid_grades(hass: Any) -> None:
    """The count sensor ignores average columns and non-counting grades."""
    grades = [
        _grade(7.0, grade_id="1", day=_day(1)),
        _grade(8.0, grade_id="2", day=_day(2)),
        _grade(2.0, grade_id="3", day=_day(3), grade_type="PeriodeGemiddeldeKolom"),
        _grade(1.0, grade_id="4", day=_day(4), counts=False),
    ]
    coordinator, entry = _coordinator(hass, grades=grades)
    entity = SomTodayGradesCountSensor(coordinator, entry)

    assert entity.native_value == 2


async def test_grade_sensors_handle_a_missing_snapshot(hass: Any) -> None:
    """A coordinator without a snapshot yields empty states, not a crash."""
    coordinator, entry = _coordinator(hass, grades=[])
    coordinator.data = None

    assert SomTodayAverageGradeSensor(coordinator, entry).native_value is None
    assert SomTodayLatestGradeSensor(coordinator, entry).native_value is None
    assert SomTodayGradesCountSensor(coordinator, entry).native_value == 0


async def test_grade_sensors_handle_a_grade_without_a_date(hass: Any) -> None:
    """A grade without a date is still usable (recency 0)."""
    grades = [_grade(7.5, grade_id="1", day=None)]
    coordinator, entry = _coordinator(hass, grades=grades)

    assert SomTodayAverageGradeSensor(coordinator, entry).native_value == 7.5
    assert SomTodayLatestGradeSensor(coordinator, entry).native_value == 7.5


def test_grade_helpers_skip_gradeless_rows() -> None:
    """The helpers drop rows whose value is not numeric."""
    empty = Grade(
        id="1",
        result=None,
        valid_result=None,
        date=None,
        counts=True,
        type="Toetskolom",
        subject="Wiskunde",
        subject_abbr="WI",
    )

    assert _per_subject_averages([empty]) == {}
    assert _latest_per_subject([empty]) == {}
