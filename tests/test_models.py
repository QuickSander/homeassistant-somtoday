"""Unit tests for the SomToday token, account and student models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.sometoday.const import (
    CONF_ACCOUNT_ID,
    CONF_API_URL,
    CONF_REFRESH_TOKEN,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
)
from custom_components.sometoday.models import (
    Account,
    SomTodayTokens,
    Student,
    parse_account,
    parse_students,
)


class _FakeEntry:
    """Minimal config entry stand-in exposing a ``data`` mapping."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "access_token": "access",
        "refresh_token": "refresh",
        "somtoday_api_url": "https://api.somtoday.nl",
        "somtoday_tenant": "bonhoeffer",
        "token_type": "Bearer",
        "scope": "openid",
        "expires_in": 3600,
    }
    payload.update(overrides)
    return payload


def test_from_token_response_computes_expiry() -> None:
    """expires_at is derived from expires_in and the supplied clock."""
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    tokens = SomTodayTokens.from_token_response(_payload(), now=now)

    assert tokens.access_token == "access"
    assert tokens.refresh_token == "refresh"
    assert tokens.api_url == "https://api.somtoday.nl"
    assert tokens.tenant == "bonhoeffer"
    assert tokens.expires_at == now + timedelta(seconds=3600)
    assert tokens.token_type == "Bearer"
    assert tokens.scope == "openid"


def test_from_token_response_defaults_api_url() -> None:
    """A missing somtoday_api_url falls back to the default API URL."""
    tokens = SomTodayTokens.from_token_response(_payload(somtoday_api_url=None))

    assert tokens.api_url == "https://api.somtoday.nl"


def test_from_token_response_uses_fallbacks() -> None:
    """Fallbacks preserve the refresh token, API URL and tenant."""
    payload = {
        "access_token": "access",
        "expires_in": 3600,
    }

    tokens = SomTodayTokens.from_token_response(
        payload,
        fallback_refresh_token="oldrefresh",
        fallback_api_url="https://school.example/api",
        fallback_tenant="school",
    )

    assert tokens.refresh_token == "oldrefresh"
    assert tokens.api_url == "https://school.example/api"
    assert tokens.tenant == "school"


def test_from_token_response_missing_fields() -> None:
    """A payload without tokens is rejected."""
    with pytest.raises(ValueError):
        SomTodayTokens.from_token_response({"somtoday_api_url": "https://api"})


def test_from_token_response_missing_refresh_token() -> None:
    """A payload without a refresh token and no fallback is rejected."""
    with pytest.raises(ValueError):
        SomTodayTokens.from_token_response(
            {"access_token": "access", "expires_in": 3600}
        )


def test_from_token_response_invalid_expires_in() -> None:
    """A non-numeric expires_in is rejected."""
    with pytest.raises(ValueError):
        SomTodayTokens.from_token_response(_payload(expires_in="soon"))


def test_expiry_helpers() -> None:
    """is_expired and expires_soon reflect the configured margin."""
    expired = SomTodayTokens(
        access_token="a",
        refresh_token="r",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert expired.is_expired is True
    assert expired.expires_soon() is True

    fresh = SomTodayTokens(
        access_token="a",
        refresh_token="r",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert fresh.is_expired is False
    assert fresh.expires_soon() is False


def test_from_entry_restores_metadata() -> None:
    """Restored tokens are expired and carry the persisted account metadata."""
    entry = _FakeEntry(
        {
            CONF_REFRESH_TOKEN: "stored-refresh",
            CONF_API_URL: "https://api.somtoday.nl",
            CONF_ACCOUNT_ID: "account-1",
            CONF_STUDENT_ID: 1234,
            CONF_STUDENT_NAME: "Eli Saado",
        }
    )

    tokens = SomTodayTokens.from_entry(entry)

    assert tokens.refresh_token == "stored-refresh"
    assert tokens.access_token == ""
    assert tokens.expires_soon() is True
    assert tokens.account_id == "account-1"
    assert tokens.student_id == 1234
    assert tokens.student_name == "Eli Saado"


def test_from_entry_defaults_api_url() -> None:
    """A missing api_url falls back to the default."""
    entry = _FakeEntry({CONF_REFRESH_TOKEN: "stored-refresh"})

    assert SomTodayTokens.from_entry(entry).api_url == "https://api.somtoday.nl"


def test_as_entry_data() -> None:
    """Only the refresh token and API URL are persisted without metadata."""
    tokens = SomTodayTokens(
        access_token="a",
        refresh_token="r",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC),
    )

    assert tokens.as_entry_data() == {
        CONF_REFRESH_TOKEN: "r",
        CONF_API_URL: "https://api.somtoday.nl",
    }


def test_as_entry_data_includes_metadata() -> None:
    """Account metadata is persisted alongside the token fields."""
    tokens = SomTodayTokens(
        access_token="a",
        refresh_token="r",
        api_url="https://api.somtoday.nl",
        expires_at=datetime.now(UTC),
        account_id="account-1",
        student_id=1234,
        student_name="Eli Saado",
    )

    assert tokens.as_entry_data() == {
        CONF_REFRESH_TOKEN: "r",
        CONF_API_URL: "https://api.somtoday.nl",
        CONF_ACCOUNT_ID: "account-1",
        CONF_STUDENT_ID: 1234,
        CONF_STUDENT_NAME: "Eli Saado",
    }


# ---------------------------------------------------------------------------
# Account / parse_account
# ---------------------------------------------------------------------------
def test_parse_account_documented_shape() -> None:
    """The account id comes from the first link and the username is kept."""
    account = parse_account(
        {
            "links": [{"id": "account-1", "rel": "self"}],
            "username": "eli@example.com",
        }
    )

    assert account.id == "account-1"
    assert account.username == "eli@example.com"


def test_parse_account_uses_first_link() -> None:
    """The first link carrying an id wins."""
    account = parse_account(
        {"links": [{"id": "first"}, {"id": "second", "rel": "self"}]}
    )

    assert account.id == "first"


def test_parse_account_falls_back_to_top_level_id() -> None:
    """Without links, the top-level id is used and coerced to a string."""
    assert Account.from_api({"id": 42}).id == "42"
    assert Account.from_api({"id": 42, "links": []}).id == "42"
    assert Account.from_api({"id": 42, "links": [{"rel": "self"}]}).id == "42"


def test_parse_account_without_username() -> None:
    """A missing username is normalised to None."""
    assert parse_account({"links": [{"id": "a"}]}).username is None
    assert parse_account({"links": [{"id": "a"}], "username": ""}).username is None


def test_parse_account_invalid() -> None:
    """Unexpected payloads raise TypeError or ValueError."""
    with pytest.raises(TypeError):
        parse_account("nope")
    with pytest.raises(TypeError):
        parse_account([{"id": "a"}])
    with pytest.raises(ValueError):
        parse_account({"links": []})


# ---------------------------------------------------------------------------
# Student / parse_students
# ---------------------------------------------------------------------------
STUDENT_PAYLOAD: dict[str, Any] = {
    "links": [{"id": 1234, "rel": "self", "href": "https://api/leerlingen/1234"}],
    "leerlingnummer": "450000",
    "roepnaam": "Eli",
    "achternaam": "Saado",
    "email": "eli@example.com",
    "mobielNummer": "0612345678",
    "geboortedatum": "2010-01-01",
    "geslacht": "MAN",
    "additionalObjects": {"pasfoto": {"datauri": "data:image/png;base64,AA"}},
}


def test_parse_students_documented_items_shape() -> None:
    """The documented ``{"items": [...]}`` payload maps every field."""
    students = parse_students({"items": [STUDENT_PAYLOAD]})

    assert len(students) == 1
    student = students[0]
    assert student.id == 1234
    assert student.leerlingnummer == "450000"
    assert student.roepnaam == "Eli"
    assert student.achternaam == "Saado"
    assert student.email == "eli@example.com"
    assert student.mobiel_nummer == "0612345678"
    assert student.geboortedatum == "2010-01-01"
    assert student.geslacht == "MAN"
    assert student.pasfoto == "data:image/png;base64,AA"
    assert student.display_name == "Eli Saado"


def test_parse_students_plain_list_shape() -> None:
    """A bare list of student objects is tolerated."""
    students = parse_students([STUDENT_PAYLOAD])

    assert [student.id for student in students] == [1234]


def test_parse_students_empty_items() -> None:
    """An empty item list yields no students."""
    assert parse_students({"items": []}) == []
    assert parse_students([]) == []


def test_student_id_prefers_self_link() -> None:
    """The ``rel == "self"`` link wins over an earlier non-self link."""
    payload = {
        "links": [
            {"id": 1, "rel": "other"},
            {"id": 2, "rel": "self"},
        ]
    }

    assert Student.from_api(payload).id == 2


def test_student_id_falls_back_to_any_link() -> None:
    """Without a self link, the first link carrying an id is used."""
    payload = {"links": [{"id": 7, "rel": "other"}]}

    assert Student.from_api(payload).id == 7


def test_student_id_falls_back_to_top_level_id() -> None:
    """Empty/unusable links fall back to the top-level ``id``."""
    assert Student.from_api({"id": 9, "links": []}).id == 9
    assert Student.from_api({"id": 9}).id == 9
    assert Student.from_api({"id": 9, "links": [{"rel": "self"}]}).id == 9
    assert Student.from_api({"id": 9, "links": "not-a-list"}).id == 9


def test_student_id_coerced_from_string() -> None:
    """A string link id is coerced to ``int``."""
    payload = {"links": [{"id": "1234", "rel": "self"}]}

    assert Student.from_api(payload).id == 1234


@pytest.mark.parametrize("bad_id", [None, True, False, "abc", {"x": 1}, []])
def test_student_invalid_id_raises(bad_id: Any) -> None:
    """A missing or non-numeric id raises ``ValueError``."""
    with pytest.raises(ValueError):
        Student.from_api({"id": bad_id})


def test_student_missing_id_raises() -> None:
    """An entry without any id raises ``ValueError``."""
    with pytest.raises(ValueError):
        Student.from_api({"roepnaam": "Eli"})


def test_student_display_name_fallback() -> None:
    """The display name falls back to the student number, then the id."""
    assert Student(id=5, leerlingnummer="450000").display_name == "450000"
    assert Student(id=5).display_name == "5"
    assert Student(id=5, roepnaam="Eli").display_name == "Eli"
    assert (
        Student.from_api({"id": 5, "roepnaam": "", "leerlingnummer": ""}).display_name
        == "5"
    )


def test_student_without_pasfoto() -> None:
    """Missing or malformed ``additionalObjects`` leave ``pasfoto`` unset."""
    assert Student.from_api({"id": 1}).pasfoto is None
    assert Student.from_api({"id": 1, "additionalObjects": ["x"]}).pasfoto is None
    assert (
        Student.from_api({"id": 1, "additionalObjects": {"pasfoto": "raw"}}).pasfoto
        is None
    )


def test_parse_students_invalid_payloads() -> None:
    """Unexpected payloads and entries raise ``TypeError``."""
    with pytest.raises(TypeError):
        parse_students("nope")
    with pytest.raises(TypeError):
        parse_students(42)
    with pytest.raises(TypeError):
        parse_students({"items": "nope"})
    with pytest.raises(TypeError):
        parse_students({"items": [1]})
