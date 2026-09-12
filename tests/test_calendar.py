"""Unit tests for the SomToday calendar entity.

The entity is bound to a real coordinator whose API calls are mocked, so no
network access is ever needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sometoday.calendar import SomTodayCalendar
from custom_components.sometoday.const import (
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    DOMAIN,
)
from custom_components.sometoday.coordinator import (
    SomTodayData,
    SomTodayDataUpdateCoordinator,
)
from custom_components.sometoday.models import Lesson

STUDENT_ID = 1234


def _lesson(
    start: datetime,
    end: datetime,
    *,
    subject: str | None = "Wiskunde",
    room: str | None = "B12",
    teacher: str | None = "JDO",
) -> Lesson:
    """Return a parsed lesson for the coordinator snapshot."""
    return Lesson(
        id="1",
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


def _coordinator(
    hass: Any, schedule: list[Lesson] | None = None
) -> tuple[SomTodayDataUpdateCoordinator, MockConfigEntry]:
    """Build a coordinator with a pre-populated schedule snapshot."""
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
        updated_at=dt_util.utcnow(),
    )
    return coordinator, entry


# ---------------------------------------------------------------------------
# event property
# ---------------------------------------------------------------------------
async def test_event_returns_current_lesson(hass: Any) -> None:
    """A lesson in progress is returned with all mapped fields."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    lesson = _lesson(
        now - timedelta(minutes=30), now + timedelta(minutes=30)
    )
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayCalendar(coordinator, entry)

    with patch("custom_components.sometoday.calendar.dt_util.now", return_value=now):
        event = entity.event

    assert event is not None
    assert event.summary == "Wiskunde (B12)"
    assert event.start == lesson.start
    assert event.end == lesson.end
    assert event.location == "B12"
    assert event.description == "JDO"


async def test_event_returns_next_lesson(hass: Any) -> None:
    """Before the first lesson, the next upcoming one is returned."""
    now = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    lesson = _lesson(
        now + timedelta(hours=1), now + timedelta(hours=2)
    )
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayCalendar(coordinator, entry)

    with patch("custom_components.sometoday.calendar.dt_util.now", return_value=now):
        event = entity.event

    assert event is not None
    assert event.start == lesson.start


async def test_event_returns_none_after_last_lesson(hass: Any) -> None:
    """After the last lesson, no event is returned."""
    now = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
    lesson = _lesson(
        now - timedelta(hours=2), now - timedelta(hours=1)
    )
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayCalendar(coordinator, entry)

    with patch("custom_components.sometoday.calendar.dt_util.now", return_value=now):
        assert entity.event is None


async def test_event_without_room_omits_parentheses(hass: Any) -> None:
    """A missing room leaves the summary without a location suffix."""
    now = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    lesson = _lesson(
        now - timedelta(minutes=30),
        now + timedelta(minutes=30),
        room=None,
    )
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayCalendar(coordinator, entry)

    with patch("custom_components.sometoday.calendar.dt_util.now", return_value=now):
        event = entity.event

    assert event is not None
    assert event.summary == "Wiskunde"
    assert event.location is None


# ---------------------------------------------------------------------------
# async_get_events
# ---------------------------------------------------------------------------
async def test_async_get_events_from_cache(hass: Any) -> None:
    """A range inside the cached window is served from the coordinator."""
    today = dt_util.now().date()
    day_start = dt_util.start_of_local_day(today)
    lesson = _lesson(day_start + timedelta(hours=9), day_start + timedelta(hours=10))
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayCalendar(coordinator, entry)

    events = await entity.async_get_events(
        hass, day_start, day_start + timedelta(days=1)
    )

    assert len(events) == 1
    assert events[0].summary == "Wiskunde (B12)"


async def test_async_get_events_filters_outside_range(hass: Any) -> None:
    """Lessons outside the requested range are filtered out."""
    today = dt_util.now().date()
    day_start = dt_util.start_of_local_day(today)
    inside = _lesson(
        day_start + timedelta(hours=9), day_start + timedelta(hours=10)
    )
    outside = _lesson(
        day_start + timedelta(days=2, hours=9),
        day_start + timedelta(days=2, hours=10),
    )
    coordinator, entry = _coordinator(hass, [inside, outside])
    entity = SomTodayCalendar(coordinator, entry)

    events = await entity.async_get_events(
        hass, day_start, day_start + timedelta(days=1)
    )

    assert len(events) == 1
    assert events[0].start == inside.start


async def test_async_get_events_out_of_range_fetches(hass: Any) -> None:
    """A range outside the cached window is fetched without touching the cache."""
    today = dt_util.now().date()
    requested_start = today + timedelta(days=30)
    requested_end = requested_start + timedelta(days=1)
    day_start = dt_util.start_of_local_day(requested_start)
    lesson = _lesson(day_start + timedelta(hours=9), day_start + timedelta(hours=10))

    coordinator, entry = _coordinator(hass, [])
    coordinator.async_fetch_schedule = AsyncMock(return_value=[lesson])
    entity = SomTodayCalendar(coordinator, entry)

    events = await entity.async_get_events(
        hass,
        dt_util.start_of_local_day(requested_start),
        dt_util.start_of_local_day(requested_end),
    )

    coordinator.async_fetch_schedule.assert_awaited_once_with(
        requested_start, requested_end
    )
    assert len(events) == 1
    # The cached schedule is never written to by a range fetch.
    assert coordinator.data.schedule == []


async def test_async_get_events_empty_cache(hass: Any) -> None:
    """An empty cached schedule yields no events."""
    today = dt_util.now().date()
    day_start = dt_util.start_of_local_day(today)
    coordinator, entry = _coordinator(hass, [])
    entity = SomTodayCalendar(coordinator, entry)

    events = await entity.async_get_events(
        hass, day_start, day_start + timedelta(days=1)
    )

    assert events == []


# ---------------------------------------------------------------------------
# Entity metadata
# ---------------------------------------------------------------------------
def test_calendar_entity_metadata(hass: Any) -> None:
    """The entity is a read-only calendar with the shared device metadata."""
    coordinator, entry = _coordinator(hass, [])
    entity = SomTodayCalendar(coordinator, entry)

    assert isinstance(entity, CalendarEntity)
    assert entity._attr_has_entity_name is True
    assert entity._attr_translation_key == "calendar"
    assert entity.unique_id == f"{entry.entry_id}_calendar"
    assert entity.device_info["identifiers"] == {(DOMAIN, entry.entry_id)}
    assert entity.device_info["name"] == "SomToday Eli Saado"
    assert entity.device_info["manufacturer"] == "SomToday"


# ---------------------------------------------------------------------------
# Cache boundary and robustness
# ---------------------------------------------------------------------------
async def test_async_get_events_without_snapshot(hass: Any) -> None:
    """Without a coordinator snapshot an in-window range yields no events."""
    today = dt_util.now().date()
    day_start = dt_util.start_of_local_day(today)
    coordinator, entry = _coordinator(hass, [])
    coordinator.data = None
    entity = SomTodayCalendar(coordinator, entry)

    events = await entity.async_get_events(
        hass, day_start, day_start + timedelta(days=1)
    )

    assert events == []


async def test_async_get_events_full_window_uses_cache(hass: Any) -> None:
    """A request covering exactly the cached window is served from the cache."""
    coordinator, entry = _coordinator(hass, [])
    coordinator.async_fetch_schedule = AsyncMock(return_value=[])
    entity = SomTodayCalendar(coordinator, entry)

    window_start, window_end = coordinator.schedule_window
    await entity.async_get_events(
        hass,
        dt_util.start_of_local_day(window_start),
        dt_util.start_of_local_day(window_end),
    )

    coordinator.async_fetch_schedule.assert_not_awaited()


async def test_async_get_events_window_end_boundary_fetches(hass: Any) -> None:
    """A range that extends past the cached window is fetched directly."""
    coordinator, entry = _coordinator(hass, [])
    coordinator.async_fetch_schedule = AsyncMock(return_value=[])
    entity = SomTodayCalendar(coordinator, entry)

    _, window_end = coordinator.schedule_window
    start = dt_util.start_of_local_day(window_end)
    await entity.async_get_events(hass, start, start + timedelta(days=2))

    coordinator.async_fetch_schedule.assert_awaited_once()


async def test_event_with_naive_lesson_datetime(hass: Any) -> None:
    """A lesson with an offset-less timestamp must not crash the event property.

    The calendar normalises lesson datetimes with ``dt_util.as_local`` before
    comparing them with an aware ``dt_util.now()`` (finding S1).
    """
    now = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)
    naive_start = datetime(2026, 9, 12, 10, 0)  # noqa: DTZ001
    naive_end = datetime(2026, 9, 12, 11, 0)  # noqa: DTZ001
    lesson = _lesson(naive_start, naive_end)
    coordinator, entry = _coordinator(hass, [lesson])
    entity = SomTodayCalendar(coordinator, entry)

    with patch("custom_components.sometoday.calendar.dt_util.now", return_value=now):
        assert entity.event is not None


async def test_async_get_events_with_naive_lesson_datetime(hass: Any) -> None:
    """A naive lesson is normalised to a tz-aware event by async_get_events."""
    today = dt_util.now().date()
    day_start = dt_util.start_of_local_day(today)
    naive_start = datetime(  # noqa: DTZ001
        today.year, today.month, today.day, 10, 0
    )
    naive_end = naive_start + timedelta(hours=1)
    coordinator, entry = _coordinator(hass, [_lesson(naive_start, naive_end)])
    entity = SomTodayCalendar(coordinator, entry)

    events = await entity.async_get_events(
        hass, day_start, day_start + timedelta(days=1)
    )

    assert len(events) == 1
    assert events[0].start.tzinfo is not None
    assert events[0].start == dt_util.as_local(naive_start)
    assert events[0].end == dt_util.as_local(naive_end)


def test_calendar_is_read_only(hass: Any) -> None:
    """The calendar advertises no create/update/delete features (N8)."""
    coordinator, entry = _coordinator(hass, [])
    entity = SomTodayCalendar(coordinator, entry)

    features = entity.supported_features or CalendarEntityFeature(0)
    assert not features & CalendarEntityFeature.CREATE_EVENT
    assert not features & CalendarEntityFeature.DELETE_EVENT
    assert not features & CalendarEntityFeature.UPDATE_EVENT
