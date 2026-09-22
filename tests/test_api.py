"""Unit tests for the SomToday REST API client.

All HTTP is mocked through ``FakeSession``; the real SomToday API is never
called.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest

from custom_components.sometoday.api import (
    APPOINTMENTS_PATH,
    GRADES_PATH,
    SomTodayApiClient,
    _release,
)
from custom_components.sometoday.auth import SomTodayAuth
from custom_components.sometoday.exceptions import (
    SomTodayApiError,
    SomTodayAuthError,
    SomTodayConnectionError,
    SomtodayInvalidAuth,
    SomTodayRateLimitError,
)
from custom_components.sometoday.models import Account, SomTodayTokens

API_URL = "https://api.somtoday.nl"
STUDENT_ITEM: dict[str, Any] = {
    "links": [{"rel": "self", "id": 1234}],
    "leerlingnummer": "450000",
    "roepnaam": "Eli",
    "achternaam": "Saado",
    "additionalObjects": {"pasfoto": {"datauri": "data:image/png;base64,AA"}},
}
ACCOUNT_ITEM: dict[str, Any] = {
    "links": [{"rel": "self", "id": "account-1"}],
    "username": "eli@example.com",
}


def _tokens() -> SomTodayTokens:
    """Return a fresh token set."""
    return SomTodayTokens(
        access_token="access",
        refresh_token="refresh",
        api_url=API_URL,
        expires_at=datetime.now(UTC) + timedelta(seconds=3600),
    )


def _client(fake_session: Any) -> tuple[SomTodayApiClient, SomTodayAuth]:
    """Build an API client around the scripted session."""
    auth = SomTodayAuth(fake_session, tokens=_tokens())
    return SomTodayApiClient(fake_session, auth, API_URL), auth


# ---------------------------------------------------------------------------
# async_get_account
# ---------------------------------------------------------------------------
async def test_get_account_parses(fake_session: Any, fake_response: Any) -> None:
    """The account id and username are parsed from /account/me."""
    session = fake_session([fake_response(200, json_data=ACCOUNT_ITEM)])
    api, _ = _client(session)

    account = await api.async_get_account()

    assert account == Account(id="account-1", username="eli@example.com")
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == f"{API_URL}/rest/v1/account/me"
    assert kwargs["headers"]["Authorization"] == "Bearer access"
    assert kwargs["headers"]["Accept"] == "application/json"


async def test_get_account_invalid_payload(
    fake_session: Any, fake_response: Any
) -> None:
    """A malformed account payload maps to SomTodayApiError."""
    session = fake_session([fake_response(200, json_data=["nope"])])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_account()


# ---------------------------------------------------------------------------
# async_get_students
# ---------------------------------------------------------------------------
async def test_get_students_parses_items(
    fake_session: Any, fake_response: Any
) -> None:
    """A documented ``{"items": [...]}`` payload is parsed into students."""
    session = fake_session(
        [fake_response(200, json_data={"items": [STUDENT_ITEM]})]
    )
    api, _ = _client(session)

    students = await api.async_get_students()

    assert len(students) == 1
    assert students[0].id == 1234
    assert students[0].display_name == "Eli Saado"
    assert students[0].pasfoto == "data:image/png;base64,AA"
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == f"{API_URL}/rest/v1/leerlingen"
    assert kwargs["params"] == {"additional": "pasfoto"}
    assert kwargs["headers"]["Authorization"] == "Bearer access"
    assert kwargs["headers"]["Accept"] == "application/json"


async def test_get_students_401_refreshes_and_retries(
    fake_session: Any, fake_response: Any
) -> None:
    """A 401 triggers one reactive refresh and a retry."""
    session = fake_session(
        [
            fake_response(401),
            fake_response(200, json_data={"items": [STUDENT_ITEM]}),
        ]
    )
    api, auth = _client(session)

    refreshed = False

    async def _refresh() -> SomTodayTokens:
        nonlocal refreshed
        refreshed = True
        auth.tokens = _tokens()
        return auth.tokens

    with patch.object(auth, "async_refresh", side_effect=_refresh):
        students = await api.async_get_students()

    assert refreshed is True
    assert len(students) == 1
    assert len(session.calls) == 2


async def test_get_students_auth_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A 403 response maps to the retryable SomTodayApiError (not reauth)."""
    session = fake_session([fake_response(403)])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_students()


async def test_get_students_persistent_401_is_definitive(
    fake_session: Any, fake_response: Any
) -> None:
    """A 401 that survives the reactive refresh maps to SomtodayInvalidAuth."""
    session = fake_session([fake_response(401), fake_response(401)])
    api, auth = _client(session)

    async def _refresh() -> SomTodayTokens:
        auth.tokens = _tokens()
        return auth.tokens

    with (
        patch.object(auth, "async_refresh", side_effect=_refresh),
        pytest.raises(SomtodayInvalidAuth),
    ):
        await api.async_get_students()


async def test_get_students_rate_limit(
    fake_session: Any, fake_response: Any
) -> None:
    """A 429 response maps to SomTodayRateLimitError."""
    session = fake_session([fake_response(429)])
    api, _ = _client(session)

    with pytest.raises(SomTodayRateLimitError):
        await api.async_get_students()


async def test_get_students_server_error(
    fake_session: Any, fake_response: Any
) -> None:
    """A 5xx response maps to SomTodayApiError."""
    session = fake_session([fake_response(500, text="<html>oops</html>")])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_students()


async def test_get_students_connection_error(fake_session: Any) -> None:
    """A network error maps to SomTodayConnectionError."""
    session = fake_session([aiohttp.ClientConnectionError("boom")])
    api, _ = _client(session)

    with pytest.raises(SomTodayConnectionError):
        await api.async_get_students()


async def test_get_students_invalid_json(
    fake_session: Any, fake_response: Any
) -> None:
    """A malformed payload maps to SomTodayApiError."""
    session = fake_session([fake_response(200, json_data=["not", "a", "mapping"])])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_students()


# ---------------------------------------------------------------------------
# Reactive refresh, response lifecycle and body errors.
# ---------------------------------------------------------------------------
class _BodyErrorResponse:
    """A response whose JSON body read raises a scripted error."""

    def __init__(self, error: Exception, status: int = 200) -> None:
        self._error = error
        self.status = status
        self.headers: dict[str, str] = {}
        self.release_count = 0

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        raise self._error

    def release(self) -> None:
        self.release_count += 1


class _TextErrorResponse:
    """A response whose diagnostic text read raises a scripted error."""

    def __init__(self, error: Exception, status: int = 500) -> None:
        self._error = error
        self.status = status
        self.headers: dict[str, str] = {}
        self.release_count = 0

    async def text(self) -> str:
        raise self._error

    def release(self) -> None:
        self.release_count += 1


async def test_get_students_401_retry_still_401(
    fake_session: Any, fake_response: Any
) -> None:
    """A retry that is rejected again raises SomTodayAuthError after one refresh."""
    session = fake_session([fake_response(401), fake_response(401)])
    api, auth = _client(session)
    refreshed = 0

    async def _refresh() -> SomTodayTokens:
        nonlocal refreshed
        refreshed += 1
        auth.tokens = _tokens()
        return auth.tokens

    with (
        patch.object(auth, "async_refresh", side_effect=_refresh),
        pytest.raises(SomTodayAuthError),
    ):
        await api.async_get_students()

    assert refreshed == 1
    assert len(session.calls) == 2


async def test_get_students_401_refresh_failure_propagates(
    fake_session: Any, fake_response: Any
) -> None:
    """A failing refresh during the 401 retry propagates SomTodayAuthError."""
    session = fake_session([fake_response(401)])
    api, auth = _client(session)

    with patch.object(
        auth, "async_refresh", side_effect=SomTodayAuthError("refresh failed")
    ), pytest.raises(SomTodayAuthError):
        await api.async_get_students()

    assert len(session.calls) == 1


async def test_get_students_releases_final_response(
    fake_session: Any, fake_response: Any
) -> None:
    """The decoded response is released back to the pool."""
    response = fake_response(200, json_data={"items": [STUDENT_ITEM]})
    session = fake_session([response])
    api, _ = _client(session)

    await api.async_get_students()

    assert response.release_count == 1


async def test_get_students_releases_first_401_response(
    fake_session: Any, fake_response: Any
) -> None:
    """Both the 401 and the retried response must be released."""
    first = fake_response(401)
    second = fake_response(200, json_data={"items": [STUDENT_ITEM]})
    session = fake_session([first, second])
    api, auth = _client(session)

    async def _refresh() -> SomTodayTokens:
        auth.tokens = _tokens()
        return auth.tokens

    with patch.object(auth, "async_refresh", side_effect=_refresh):
        await api.async_get_students()

    assert first.release_count == 1
    assert second.release_count == 1


async def test_get_students_non_json_body(
    fake_session: Any, fake_response: Any
) -> None:
    """A body that cannot be decoded as JSON maps to SomTodayApiError."""
    session = fake_session([fake_response(200)])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_students()


async def test_get_students_body_read_error(fake_session: Any) -> None:
    """A transport error while reading the body maps to SomTodayConnectionError."""
    session = fake_session([_BodyErrorResponse(aiohttp.ClientError("boom"))])
    api, _ = _client(session)

    with pytest.raises(SomTodayConnectionError):
        await api.async_get_students()


async def test_error_response_releases_and_logs_diagnostics(
    fake_session: Any, fake_response: Any
) -> None:
    """A 5xx response is released even though its body is read for diagnostics."""
    response = fake_response(
        500,
        headers={"Location": "https://example.com/error"},
        text="<html>error</html>",
    )
    session = fake_session([response])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_students()

    assert response.release_count == 1


async def test_error_response_text_read_error(fake_session: Any) -> None:
    """A failing diagnostic body read does not mask the HTTP error."""
    response = _TextErrorResponse(aiohttp.ClientError("boom"))
    session = fake_session([response])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_students()

    assert response.release_count == 1


def test_build_headers_without_tokens(fake_session: Any) -> None:
    """Without tokens no Authorization header is sent."""
    session = fake_session([])
    auth = SomTodayAuth(session)
    api = SomTodayApiClient(session, auth, API_URL)

    assert api._build_headers() == {"Accept": "application/json"}


async def test_send_post_uses_session_post(
    fake_session: Any, fake_response: Any
) -> None:
    """A non-GET method is dispatched through ``session.post``."""
    response = fake_response(200, json_data={"ok": True})
    session = fake_session([response])
    auth = SomTodayAuth(session, tokens=_tokens())
    api = SomTodayApiClient(session, auth, API_URL)

    result = await api._send("POST", "/rest/v1/foo", params={"a": "b"})

    assert result is response
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == f"{API_URL}/rest/v1/foo"
    assert kwargs["params"] == {"a": "b"}


def test_release_ignores_response_without_release() -> None:
    """A response object without ``release`` is tolerated (no AttributeError)."""
    _release(object())


# ---------------------------------------------------------------------------
# async_get_appointments (paginated /rest/v1/afspraken)
# ---------------------------------------------------------------------------
def _appointment(appointment_id: int) -> dict[str, Any]:
    """Return a minimal appointment payload."""
    return {"links": [{"id": appointment_id}]}


async def test_get_appointments_single_page_200(
    fake_session: Any, fake_response: Any
) -> None:
    """A 200 response returns the whole list in one page."""
    session = fake_session(
        [fake_response(200, json_data={"items": [_appointment(1)]})]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert appointments == [_appointment(1)]
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == f"{API_URL}{APPOINTMENTS_PATH}"
    assert kwargs["params"] == [
        ("begindatum", "2026-09-11"),
        ("einddatum", "2026-09-25"),
        ("sort", "asc-id"),
        ("additional", "vak"),
        ("additional", "docentAfkortingen"),
        ("additional", "leerlingen"),
    ]
    assert kwargs["headers"]["Range"] == "items=0-99"
    assert kwargs["headers"]["Authorization"] == "Bearer access"


async def test_get_appointments_paginates_two_pages(
    fake_session: Any, fake_response: Any
) -> None:
    """A 206 page with more items triggers a second, merged request."""
    first_page = [_appointment(index) for index in range(100)]
    second_page = [_appointment(index) for index in range(100, 150)]
    session = fake_session(
        [
            fake_response(
                206,
                headers={"Content-Range": "items 0-99/150"},
                json_data={"items": first_page},
            ),
            fake_response(
                206,
                headers={"Content-Range": "items 100-149/150"},
                json_data={"items": second_page},
            ),
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert len(appointments) == 150
    assert len(session.calls) == 2
    assert session.calls[0][2]["headers"]["Range"] == "items=0-99"
    assert session.calls[1][2]["headers"]["Range"] == "items=100-199"


async def test_get_appointments_stops_on_short_page(
    fake_session: Any, fake_response: Any
) -> None:
    """A page with fewer than the page size ends the walk."""
    first_page = [_appointment(index) for index in range(100)]
    short_page = [_appointment(index) for index in range(100, 130)]
    session = fake_session(
        [
            fake_response(
                206,
                headers={"Content-Range": "items 0-99/250"},
                json_data={"items": first_page},
            ),
            fake_response(
                206,
                headers={"Content-Range": "items 100-129/130"},
                json_data={"items": short_page},
            ),
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert len(appointments) == 130
    assert len(session.calls) == 2


async def test_get_appointments_stops_when_content_range_is_complete(
    fake_session: Any, fake_response: Any
) -> None:
    """A full page whose Content-Range reports the total ends the walk."""
    page = [_appointment(index) for index in range(100)]
    session = fake_session(
        [
            fake_response(
                206,
                headers={"Content-Range": "items 0-99/100"},
                json_data={"items": page},
            )
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert len(appointments) == 100
    assert len(session.calls) == 1


async def test_get_appointments_206_single_page(
    fake_session: Any, fake_response: Any
) -> None:
    """A short 206 page is accepted as a complete response."""
    session = fake_session(
        [
            fake_response(
                206,
                headers={"Content-Range": "items 0-2/3"},
                json_data={"items": [_appointment(1)]},
            )
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert appointments == [_appointment(1)]
    assert len(session.calls) == 1


async def test_get_appointments_hard_page_cap(
    fake_session: Any, fake_response: Any
) -> None:
    """An unterminated list is bounded by the hard page cap."""
    page = [_appointment(index) for index in range(100)]

    def _page() -> Any:
        return fake_response(
            206,
            headers={"Content-Range": "items 0-99/*"},
            json_data={"items": page},
        )

    session = fake_session([_page(), _page(), _page()])
    api, _ = _client(session)

    with patch("custom_components.sometoday.api.MAX_PAGINATION_PAGES", 2):
        appointments = await api.async_get_appointments(
            date(2026, 9, 11), date(2026, 9, 25)
        )

    assert len(appointments) == 200
    assert len(session.calls) == 2


async def test_get_appointments_plain_list_payload(
    fake_session: Any, fake_response: Any
) -> None:
    """A bare list page is tolerated."""
    session = fake_session(
        [fake_response(200, json_data=[_appointment(1), _appointment(2)])]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert appointments == [_appointment(1), _appointment(2)]


async def test_get_appointments_full_page_without_content_range_continues(
    fake_session: Any, fake_response: Any
) -> None:
    """A full page without a Content-Range keeps walking to the next page."""
    first_page = [_appointment(index) for index in range(100)]
    second_page = [_appointment(index) for index in range(100, 110)]
    session = fake_session(
        [
            fake_response(206, json_data={"items": first_page}),
            fake_response(206, json_data={"items": second_page}),
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert len(appointments) == 110
    assert len(session.calls) == 2


async def test_get_appointments_releases_pages(
    fake_session: Any, fake_response: Any
) -> None:
    """Every page response is released back to the pool."""
    first = fake_response(
        206,
        headers={"Content-Range": "items 0-99/150"},
        json_data={"items": [_appointment(index) for index in range(100)]},
    )
    second = fake_response(
        206,
        headers={"Content-Range": "items 100-149/150"},
        json_data={"items": [_appointment(index) for index in range(100, 150)]},
    )
    session = fake_session([first, second])
    api, _ = _client(session)

    await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))

    assert first.release_count == 1
    assert second.release_count == 1


async def test_get_appointments_401_refreshes_and_retries(
    fake_session: Any, fake_response: Any
) -> None:
    """A 401 on the first page triggers one refresh and a retry."""
    session = fake_session(
        [
            fake_response(401),
            fake_response(200, json_data={"items": [_appointment(1)]}),
        ]
    )
    api, auth = _client(session)

    async def _refresh() -> SomTodayTokens:
        auth.tokens = _tokens()
        return auth.tokens

    with patch.object(auth, "async_refresh", side_effect=_refresh):
        appointments = await api.async_get_appointments(
            date(2026, 9, 11), date(2026, 9, 25)
        )

    assert appointments == [_appointment(1)]
    assert len(session.calls) == 2


async def test_get_appointments_error_status(
    fake_session: Any, fake_response: Any
) -> None:
    """A 5xx page maps to SomTodayApiError."""
    session = fake_session([fake_response(500, text="<html>oops</html>")])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))


async def test_get_appointments_invalid_payload(
    fake_session: Any, fake_response: Any
) -> None:
    """A page without a usable items list maps to SomTodayApiError."""
    session = fake_session([fake_response(200, json_data={"items": "nope"})])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))


async def test_get_appointments_non_json_body(
    fake_session: Any, fake_response: Any
) -> None:
    """A page body that is not JSON maps to SomTodayApiError."""
    session = fake_session([fake_response(200)])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))


async def test_get_appointments_does_not_filter_students(
    fake_session: Any, fake_response: Any
) -> None:
    """The client returns every appointment; the coordinator scopes them."""
    session = fake_session(
        [
            fake_response(
                200,
                json_data={"items": [_appointment(1), _appointment(2)]},
            )
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert appointments == [_appointment(1), _appointment(2)]


async def test_get_appointments_non_sequence_payload(
    fake_session: Any, fake_response: Any
) -> None:
    """A page that is neither a mapping nor a list maps to SomTodayApiError."""
    session = fake_session([fake_response(200, json_data=42)])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))


async def test_get_appointments_malformed_content_range_continues(
    fake_session: Any, fake_response: Any
) -> None:
    """An unparsable Content-Range keeps walking until a short page ends it."""
    first_page = [_appointment(index) for index in range(100)]
    short_page = [_appointment(index) for index in range(100, 110)]
    session = fake_session(
        [
            fake_response(
                206,
                headers={"Content-Range": "bytes 0-99/150"},
                json_data={"items": first_page},
            ),
            fake_response(
                206,
                headers={"Content-Range": "items 100-109/150"},
                json_data={"items": short_page},
            ),
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert len(appointments) == 110
    assert len(session.calls) == 2
    assert session.calls[1][2]["headers"]["Range"] == "items=100-199"


async def test_get_appointments_star_total_then_short_page(
    fake_session: Any, fake_response: Any
) -> None:
    """A ``*`` total keeps walking until a short page ends the list."""
    first_page = [_appointment(index) for index in range(100)]
    short_page = [_appointment(index) for index in range(100, 110)]
    session = fake_session(
        [
            fake_response(
                206,
                headers={"Content-Range": "items 0-99/*"},
                json_data={"items": first_page},
            ),
            fake_response(
                206,
                headers={"Content-Range": "items 100-109/110"},
                json_data={"items": short_page},
            ),
        ]
    )
    api, _ = _client(session)

    appointments = await api.async_get_appointments(
        date(2026, 9, 11), date(2026, 9, 25)
    )

    assert len(appointments) == 110
    assert len(session.calls) == 2


async def test_get_appointments_unexpected_success_status(
    fake_session: Any, fake_response: Any
) -> None:
    """A 2xx status other than 200/206 maps to SomTodayApiError."""
    session = fake_session([fake_response(201, json_data={"items": []})])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))


async def test_get_appointments_body_read_error(fake_session: Any) -> None:
    """A transport error while reading a page body maps to ConnectionError."""
    session = fake_session(
        [_BodyErrorResponse(aiohttp.ClientError("boom"), status=206)]
    )
    api, _ = _client(session)

    with pytest.raises(SomTodayConnectionError):
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))


async def test_get_appointments_persistent_401_is_definitive(
    fake_session: Any, fake_response: Any
) -> None:
    """A paginated 401 surviving the reactive refresh is a dead session."""
    session = fake_session([fake_response(401), fake_response(401)])
    api, auth = _client(session)

    async def _refresh() -> SomTodayTokens:
        auth.tokens = _tokens()
        return auth.tokens

    with (
        patch.object(auth, "async_refresh", side_effect=_refresh),
        pytest.raises(SomtodayInvalidAuth),
    ):
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))


async def test_get_appointments_403_is_retryable(
    fake_session: Any, fake_response: Any
) -> None:
    """A paginated 403 maps to the retryable SomTodayApiError (not reauth)."""
    session = fake_session([fake_response(403)])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError) as err:
        await api.async_get_appointments(date(2026, 9, 11), date(2026, 9, 25))

    assert not isinstance(err.value, SomtodayInvalidAuth)


# ---------------------------------------------------------------------------
# async_get_grades (paginated /rest/v1/resultaten/huidigVoorLeerling/{id})
# ---------------------------------------------------------------------------
def _grade(grade_id: int) -> dict[str, Any]:
    """Return a minimal grade payload."""
    return {"links": [{"id": grade_id}]}


async def test_get_grades_url_params_and_range(
    fake_session: Any, fake_response: Any
) -> None:
    """The grades endpoint is called with the student path and a Range header."""
    session = fake_session(
        [fake_response(200, json_data={"items": [_grade(1)]})]
    )
    api, _ = _client(session)

    grades = await api.async_get_grades(1234)

    assert grades == [_grade(1)]
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == f"{API_URL}{GRADES_PATH.format(student_id=1234)}"
    assert kwargs["params"] == [("additional", "toetssoortnaam")]
    assert kwargs["headers"]["Range"] == "items=0-99"
    assert kwargs["headers"]["Authorization"] == "Bearer access"


async def test_get_grades_paginates_two_pages(
    fake_session: Any, fake_response: Any
) -> None:
    """A 206 page with more items triggers a second, merged request."""
    first_page = [_grade(index) for index in range(100)]
    second_page = [_grade(index) for index in range(100, 150)]
    session = fake_session(
        [
            fake_response(
                206,
                headers={"Content-Range": "items 0-99/150"},
                json_data={"items": first_page},
            ),
            fake_response(
                206,
                headers={"Content-Range": "items 100-149/150"},
                json_data={"items": second_page},
            ),
        ]
    )
    api, _ = _client(session)

    grades = await api.async_get_grades(1234)

    assert len(grades) == 150
    assert len(session.calls) == 2
    assert session.calls[1][2]["headers"]["Range"] == "items=100-199"


async def test_get_grades_empty(fake_session: Any, fake_response: Any) -> None:
    """An empty page yields no grades."""
    session = fake_session([fake_response(200, json_data={"items": []})])
    api, _ = _client(session)

    assert await api.async_get_grades(1234) == []


async def test_get_grades_403_is_retryable(
    fake_session: Any, fake_response: Any
) -> None:
    """A 403 (no grade permission) is retryable, not a dead session."""
    session = fake_session([fake_response(403)])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError) as err:
        await api.async_get_grades(1234)

    assert not isinstance(err.value, SomtodayInvalidAuth)


async def test_get_grades_error_status(
    fake_session: Any, fake_response: Any
) -> None:
    """A 5xx page maps to SomTodayApiError."""
    session = fake_session([fake_response(500, text="oops")])
    api, _ = _client(session)

    with pytest.raises(SomTodayApiError):
        await api.async_get_grades(1234)


async def test_get_grades_401_refreshes_and_retries(
    fake_session: Any, fake_response: Any
) -> None:
    """A 401 on the first page triggers one refresh and a retry."""
    session = fake_session(
        [
            fake_response(401),
            fake_response(200, json_data={"items": [_grade(1)]}),
        ]
    )
    api, auth = _client(session)

    async def _refresh() -> SomTodayTokens:
        auth.tokens = _tokens()
        return auth.tokens

    with patch.object(auth, "async_refresh", side_effect=_refresh):
        grades = await api.async_get_grades(1234)

    assert grades == [_grade(1)]
    assert len(session.calls) == 2
