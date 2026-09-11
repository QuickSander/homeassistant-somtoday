"""Unit tests for the SomToday token and school models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.sometoday.const import CONF_API_URL, CONF_REFRESH_TOKEN
from custom_components.sometoday.models import (
    School,
    SomTodayTokens,
    Student,
    parse_schools,
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


def test_from_token_response_missing_fields() -> None:
    """A payload without tokens is rejected."""
    with pytest.raises(ValueError):
        SomTodayTokens.from_token_response({"somtoday_api_url": "https://api"})


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


def test_from_entry_forces_refresh() -> None:
    """Restored tokens are marked expired so they are refreshed before use."""
    entry = _FakeEntry(
        {
            CONF_REFRESH_TOKEN: "stored-refresh",
            CONF_API_URL: "https://api.somtoday.nl",
        }
    )

    tokens = SomTodayTokens.from_entry(entry)

    assert tokens.refresh_token == "stored-refresh"
    assert tokens.access_token == ""
    assert tokens.expires_soon() is True


def test_as_entry_data() -> None:
    """Only the refresh token and API URL are persisted."""
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


def test_parse_schools_documented_shape() -> None:
    """The documented organisaties.json shape is parsed."""
    payload = [
        {
            "instellingen": [
                {
                    "uuid": "u1",
                    "naam": "Etty Hillesum Lyceum",
                    "plaats": "DEVENTER",
                    "oidcurls": [{"url": "https://idp.example.com"}],
                }
            ]
        }
    ]

    schools = parse_schools(payload)

    assert len(schools) == 1
    assert schools[0].uuid == "u1"
    assert schools[0].place == "DEVENTER"
    assert schools[0].has_oidc is True


def test_parse_schools_flat_shapes() -> None:
    """A bare mapping or list of school objects is tolerated."""
    mapping = {"instellingen": [{"uuid": "u1", "naam": "A"}]}
    flat = [{"uuid": "u2", "naam": "B"}]

    assert parse_schools(mapping)[0].uuid == "u1"
    assert parse_schools(flat)[0].uuid == "u2"


def test_parse_schools_invalid() -> None:
    """Unexpected payloads raise TypeError or ValueError."""
    with pytest.raises(TypeError):
        parse_schools("nope")
    with pytest.raises(ValueError):
        parse_schools([{"naam": "missing uuid"}])
    with pytest.raises(TypeError):
        parse_schools([{"instellingen": ["not-a-mapping"]}])
    with pytest.raises(TypeError):
        parse_schools([1, 2])


def test_school_single_oidc_mapping_is_normalised() -> None:
    """A single oidcurls object is normalised to a tuple."""
    school = School.from_api({"uuid": "u", "naam": "A", "oidcurls": {"url": "x"}})

    assert school.oidc_urls == ({"url": "x"},)
    assert school.has_oidc is True


def test_school_has_oidc_false_without_urls() -> None:
    """A school without oidcurls does not advertise an IdP."""
    school = School(uuid="u", name="A")

    assert school.has_oidc is False

# ---------------------------------------------------------------------------
# Student / parse_students coverage (config-flow slice).
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
