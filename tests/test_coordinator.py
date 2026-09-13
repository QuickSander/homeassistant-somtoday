"""Unit tests for the SomToday data update coordinator.

All HTTP is mocked through the API client's methods; the coordinator is driven
directly so no network access is ever needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sometoday.const import (
    CONF_API_URL,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SCHEDULE_DAYS_AHEAD,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    DEFAULT_SCHEDULE_DAYS_AHEAD,
    DOMAIN,
)
from custom_components.sometoday.coordinator import (
    SomTodayData,
    SomTodayDataUpdateCoordinator,
)
from custom_components.sometoday.exceptions import SomTodayError, SomtodayInvalidAuth
from custom_components.sometoday.models import Student

API_URL = "https://api.somtoday.nl"
STUDENT_ID = 1234
OTHER_STUDENT_ID = 5678


def _raw_lesson(
    lesson_id: int,
    start: datetime,
    end: datetime,
    *,
    student_ids: list[int] | None = None,
    subject: str = "Wiskunde",
) -> dict[str, Any]:
    """Return a raw appointment payload for the mocked API client."""
    additional: dict[str, Any] = {
        "vak": {"naam": subject, "afkorting": "WI"},
        "docentAfkortingen": "JDO",
    }
    if student_ids is not None:
        additional["leerlingen"] = {
            "items": [{"links": [{"id": sid}]} for sid in student_ids]
        }
    return {
        "links": [{"id": lesson_id, "rel": "self"}],
        "locatie": "B12",
        "beginDatumTijd": start.isoformat(),
        "eindDatumTijd": end.isoformat(),
        "titel": subject,
        "afspraakType": {"naam": "LES"},
        "additionalObjects": additional,
    }


def _coordinator(
    hass: Any,
    *,
    options: dict[str, Any] | None = None,
    appointments: list[dict[str, Any]] | None = None,
    students: list[Student] | None = None,
    entry_data: dict[str, Any] | None = None,
) -> tuple[SomTodayDataUpdateCoordinator, MockConfigEntry, Any, Any]:
    """Build a coordinator around mocked API and auth objects."""
    data = {
        CONF_REFRESH_TOKEN: "old-refresh",
        CONF_API_URL: API_URL,
        CONF_STUDENT_ID: STUDENT_ID,
        CONF_STUDENT_NAME: "Eli Saado",
    }
    if entry_data:
        data.update(entry_data)
    entry = MockConfigEntry(domain=DOMAIN, data=data, options=options or {})
    entry.add_to_hass(hass)

    auth = MagicMock()
    auth.async_ensure_valid = AsyncMock()
    auth.as_entry_data = MagicMock(
        return_value={CONF_REFRESH_TOKEN: "old-refresh", CONF_API_URL: API_URL}
    )

    api = MagicMock()
    api.async_get_appointments = AsyncMock(return_value=appointments or [])
    api.async_get_students = AsyncMock(return_value=students or [])

    coordinator = SomTodayDataUpdateCoordinator(hass, entry, api, auth)
    return coordinator, entry, api, auth


async def test_update_data_success(hass: Any) -> None:
    """A successful poll returns parsed lessons, students and a timestamp."""
    start = datetime(2026, 9, 12, 8, 30, tzinfo=UTC)
    raw = _raw_lesson(1, start, start + timedelta(minutes=50))
    student = Student(id=STUDENT_ID, roepnaam="Eli", achternaam="Saado")
    coordinator, _, _, _ = _coordinator(
        hass, appointments=[raw], students=[student]
    )

    data = await coordinator._async_update_data()

    assert isinstance(data, SomTodayData)
    assert [lesson.id for lesson in data.schedule] == ["1"]
    assert data.schedule[0].subject == "Wiskunde"
    assert data.students == [student]
    assert data.updated_at.tzinfo is not None


async def test_update_data_filters_per_student(hass: Any) -> None:
    """Only this student's lessons (and unscoped ones) are kept and sorted."""
    base = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    mine = _raw_lesson(1, base + timedelta(hours=2), base + timedelta(hours=3), student_ids=[STUDENT_ID])
    other = _raw_lesson(2, base, base + timedelta(hours=1), student_ids=[OTHER_STUDENT_ID])
    unscoped = _raw_lesson(3, base + timedelta(hours=1), base + timedelta(hours=2))
    empty_scope = _raw_lesson(4, base + timedelta(hours=3), base + timedelta(hours=4), student_ids=[])
    coordinator, _, _, _ = _coordinator(
        hass, appointments=[mine, other, unscoped, empty_scope]
    )

    data = await coordinator._async_update_data()

    assert [lesson.id for lesson in data.schedule] == ["3", "1", "4"]
    assert all(
        OTHER_STUDENT_ID not in lesson.student_ids for lesson in data.schedule
    )


async def test_update_data_window_dates(hass: Any) -> None:
    """The polled window is today - 1 day .. today + schedule_days_ahead."""
    coordinator, _, api, _ = _coordinator(
        hass, options={CONF_SCHEDULE_DAYS_AHEAD: 7}
    )

    await coordinator._async_update_data()

    today = dt_util.now().date()
    api.async_get_appointments.assert_awaited_once_with(
        today - timedelta(days=1), today + timedelta(days=7)
    )


async def test_update_data_default_window(hass: Any) -> None:
    """Without options the default schedule window is used."""
    coordinator, _, api, _ = _coordinator(hass)

    await coordinator._async_update_data()

    today = dt_util.now().date()
    api.async_get_appointments.assert_awaited_once_with(
        today - timedelta(days=1),
        today + timedelta(days=DEFAULT_SCHEDULE_DAYS_AHEAD),
    )


async def test_update_interval_from_options(hass: Any) -> None:
    """The poll interval comes from the entry options."""
    coordinator, _, _, _ = _coordinator(
        hass, options={CONF_SCAN_INTERVAL: 30}
    )

    assert coordinator.update_interval == timedelta(minutes=30)


async def test_update_interval_default(hass: Any) -> None:
    """Without options the default poll interval is used."""
    coordinator, _, _, _ = _coordinator(hass)

    assert coordinator.update_interval == timedelta(minutes=15)


async def test_update_data_invalid_auth(hass: Any) -> None:
    """A definitive auth rejection maps to ConfigEntryAuthFailed."""
    coordinator, _, api, _ = _coordinator(hass)
    api.async_get_appointments.side_effect = SomtodayInvalidAuth("expired")

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_data_somtoday_error(hass: Any) -> None:
    """A SomToday error maps to UpdateFailed."""
    coordinator, _, api, _ = _coordinator(hass)
    api.async_get_appointments.side_effect = SomTodayError("boom")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_data_client_error(hass: Any) -> None:
    """An aiohttp client error maps to UpdateFailed."""
    coordinator, _, api, _ = _coordinator(hass)
    api.async_get_appointments.side_effect = aiohttp.ClientError("offline")

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_update_data_persists_rotated_token(hass: Any) -> None:
    """A rotated refresh token is written back to the config entry."""
    coordinator, entry, _, auth = _coordinator(hass)
    auth.as_entry_data.return_value = {
        CONF_REFRESH_TOKEN: "new-refresh",
        CONF_API_URL: API_URL,
    }

    await coordinator._async_update_data()

    assert entry.data[CONF_REFRESH_TOKEN] == "new-refresh"


async def test_update_data_keeps_token_when_not_rotated(hass: Any) -> None:
    """A non-rotating refresh response leaves the stored token untouched."""
    coordinator, entry, _, auth = _coordinator(hass)
    auth.as_entry_data.return_value = {
        CONF_REFRESH_TOKEN: "old-refresh",
        CONF_API_URL: API_URL,
    }

    await coordinator._async_update_data()

    assert entry.data[CONF_REFRESH_TOKEN] == "old-refresh"


async def test_update_data_keeps_previous_students_on_failure(hass: Any) -> None:
    """A failing student fetch keeps the previous snapshot."""
    previous = Student(id=STUDENT_ID, roepnaam="Eli")
    coordinator, _, api, _ = _coordinator(hass, students=[previous])
    coordinator.data = SomTodayData(
        schedule=[], students=[previous], updated_at=dt_util.utcnow()
    )
    api.async_get_students.side_effect = SomTodayError("student list down")

    data = await coordinator._async_update_data()

    assert data.students == [previous]


async def test_update_data_students_failure_without_snapshot(hass: Any) -> None:
    """A failing student fetch without a snapshot yields an empty list."""
    coordinator, _, api, _ = _coordinator(hass)
    api.async_get_students.side_effect = SomTodayError("student list down")

    data = await coordinator._async_update_data()

    assert data.students == []


async def test_async_fetch_schedule_filters_and_sorts(hass: Any) -> None:
    """The out-of-range fetch applies the same per-student scope."""
    base = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    raw = [
        _raw_lesson(1, base + timedelta(hours=1), base + timedelta(hours=2)),
        _raw_lesson(2, base, base + timedelta(hours=1), student_ids=[OTHER_STUDENT_ID]),
    ]
    coordinator, _, _, _ = _coordinator(hass, appointments=raw)

    lessons = await coordinator.async_fetch_schedule(
        dt_util.now().date(), dt_util.now().date() + timedelta(days=1)
    )

    assert [lesson.id for lesson in lessons] == ["1"]


def test_schedule_window_reflects_days_ahead(hass: Any) -> None:
    """The cached window is derived from the configured days ahead."""
    coordinator, _, _, _ = _coordinator(
        hass, options={CONF_SCHEDULE_DAYS_AHEAD: 3}
    )

    today = dt_util.now().date()
    assert coordinator.schedule_window == (
        today - timedelta(days=1),
        today + timedelta(days=3),
    )


async def test_schedule_window_tracks_the_last_fetch(hass: Any) -> None:
    """After a poll the window reflects the fetched range, not 'now'."""
    coordinator, _, api, _ = _coordinator(
        hass, options={CONF_SCHEDULE_DAYS_AHEAD: 3}
    )

    await coordinator._async_update_data()

    start, end = api.async_get_appointments.call_args.args
    assert coordinator.schedule_window == (start, end)


async def test_consecutive_polls_advance_the_window(hass: Any) -> None:
    """Each poll recomputes the fetch window from today (regression: B1)."""
    coordinator, _, api, _ = _coordinator(
        hass, options={CONF_SCHEDULE_DAYS_AHEAD: 3}
    )

    day1 = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    day2 = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)

    with patch(
        "custom_components.sometoday.coordinator.dt_util.now", return_value=day1
    ):
        await coordinator._async_update_data()
        first = api.async_get_appointments.call_args.args

    with patch(
        "custom_components.sometoday.coordinator.dt_util.now", return_value=day2
    ):
        await coordinator._async_update_data()
        second = api.async_get_appointments.call_args.args

    assert first == (
        day1.date() - timedelta(days=1),
        day1.date() + timedelta(days=3),
    )
    assert second == (
        day2.date() - timedelta(days=1),
        day2.date() + timedelta(days=3),
    )
    assert second[0] > first[0]
    assert coordinator.schedule_window == second


async def test_update_data_escalates_students_invalid_auth(hass: Any) -> None:
    """A definitive rejection while reading students still triggers reauth."""
    coordinator, _, api, _ = _coordinator(hass)
    api.async_get_students = AsyncMock(
        side_effect=SomtodayInvalidAuth("session dead")
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_update_data_mixed_naive_aware_sorts(hass: Any) -> None:
    """A mixed naive/aware payload sorts by the local instant (N1)."""
    naive = _raw_lesson(
        1,
        datetime(2026, 9, 12, 10, 0),  # noqa: DTZ001
        datetime(2026, 9, 12, 11, 0),  # noqa: DTZ001
    )
    aware = _raw_lesson(
        2,
        datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 12, 13, 0, tzinfo=UTC),
    )
    coordinator, _, _, _ = _coordinator(hass, appointments=[aware, naive])

    data = await coordinator._async_update_data()

    assert {lesson.id for lesson in data.schedule} == {"1", "2"}
    expected = sorted(
        data.schedule, key=lambda lesson: dt_util.as_local(lesson.start)
    )
    assert [lesson.id for lesson in data.schedule] == [
        lesson.id for lesson in expected
    ]


async def test_update_data_persists_token_rotated_during_fetch(hass: Any) -> None:
    """A token rotated during the fetch (reactive 401) is persisted (N5)."""
    coordinator, entry, api, auth = _coordinator(hass)
    state = {"refresh": "old-refresh"}
    auth.as_entry_data = MagicMock(
        side_effect=lambda: {
            CONF_REFRESH_TOKEN: state["refresh"],
            CONF_API_URL: API_URL,
        }
    )

    async def _appointments(start: Any, end: Any) -> list[Any]:
        state["refresh"] = "rotated-during-fetch"
        return []

    api.async_get_appointments = AsyncMock(side_effect=_appointments)

    await coordinator._async_update_data()

    assert entry.data[CONF_REFRESH_TOKEN] == "rotated-during-fetch"


async def test_schedule_window_survives_failed_poll(hass: Any) -> None:
    """A failed poll keeps the window of the last successful fetch (N3)."""
    coordinator, _, api, _ = _coordinator(hass)

    await coordinator._async_update_data()
    captured = coordinator.schedule_window

    api.async_get_appointments.side_effect = SomTodayError("offline")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator.schedule_window == captured


async def test_schedule_window_does_not_advance_between_polls(hass: Any) -> None:
    """The cached window stays at the last fetch until the next poll (B1/N3)."""
    coordinator, _, _, _ = _coordinator(
        hass, options={CONF_SCHEDULE_DAYS_AHEAD: 3}
    )
    day1 = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
    day2 = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)

    with patch(
        "custom_components.sometoday.coordinator.dt_util.now", return_value=day1
    ):
        await coordinator._async_update_data()
    cached = coordinator.schedule_window

    with patch(
        "custom_components.sometoday.coordinator.dt_util.now", return_value=day2
    ):
        # Without a poll the cache window must not move, while the next fetch
        # window must advance.
        assert coordinator.schedule_window == cached
        assert coordinator._current_window() != cached
        await coordinator._async_update_data()
        assert coordinator.schedule_window == coordinator._current_window()
