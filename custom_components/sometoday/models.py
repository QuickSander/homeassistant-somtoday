"""Typed data models and parsers for the SomToday integration.

This module contains no Home Assistant imports. The authentication layer and
its tests only rely on these plain dataclasses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from .const import (
    CONF_ACCOUNT_ID,
    CONF_API_URL,
    CONF_REFRESH_TOKEN,
    CONF_STUDENT_ID,
    CONF_STUDENT_NAME,
    DEFAULT_API_URL,
    SCOPE,
    TOKEN_REFRESH_MARGIN,
)


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


@runtime_checkable
class _HasData(Protocol):
    """Minimal config entry interface needed by :meth:`SomTodayTokens.from_entry`."""

    data: Mapping[str, Any]


def _as_str(value: Any) -> str | None:
    """Return ``value`` as a string, or ``None`` when it is empty."""
    if value is None:
        return None
    text = str(value)
    return text or None


def _first_link_id(payload: Mapping[str, Any]) -> Any:
    """Return the id of the first ``links`` entry, falling back to ``id``."""
    links = payload.get("links")
    if isinstance(links, Sequence) and not isinstance(links, (str, bytes)):
        for link in links:
            if isinstance(link, Mapping) and link.get("id") is not None:
                return link["id"]
    return payload.get("id")


@dataclass(frozen=True, slots=True)
class Account:
    """A SomToday account as returned by ``/rest/v1/account/me``."""

    id: str
    username: str | None = None

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> Account:
        """Build an :class:`Account` from a single ``account/me`` object."""
        account_id = _first_link_id(payload)
        if account_id is None:
            raise ValueError("Account entry is missing a usable id")
        return cls(id=str(account_id), username=_as_str(payload.get("username")))


def parse_account(payload: Any) -> Account:
    """Parse a ``/rest/v1/account/me`` payload into an :class:`Account`."""
    if not isinstance(payload, Mapping):
        raise TypeError("Unexpected account payload")
    return Account.from_api(payload)


def _coerce_student_id(value: Any) -> int:
    """Coerce a SomToday student identifier to an ``int``."""
    if isinstance(value, bool) or value is None:
        raise ValueError("Student entry is missing a usable id")
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError) as err:
        raise ValueError("Student entry is missing a usable id") from err


@dataclass(frozen=True, slots=True)
class Student:
    """A student as returned by ``/rest/v1/leerlingen``."""

    id: int
    leerlingnummer: str | None = None
    roepnaam: str | None = None
    achternaam: str | None = None
    email: str | None = None
    mobiel_nummer: str | None = None
    geboortedatum: str | None = None
    geslacht: str | None = None
    pasfoto: str | None = None

    @property
    def display_name(self) -> str:
        """Return a human-readable name for the student."""
        parts = [part for part in (self.roepnaam, self.achternaam) if part]
        if parts:
            return " ".join(parts)
        return self.leerlingnummer or str(self.id)

    @staticmethod
    def _extract_id(payload: Mapping[str, Any]) -> Any:
        """Return the student id from ``links`` or the top-level ``id``."""
        links = payload.get("links")
        if isinstance(links, Sequence) and not isinstance(links, (str, bytes)):
            for link in links:
                if (
                    isinstance(link, Mapping)
                    and link.get("rel") == "self"
                    and link.get("id") is not None
                ):
                    return link["id"]
            for link in links:
                if isinstance(link, Mapping) and link.get("id") is not None:
                    return link["id"]
        return payload.get("id")

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> Student:
        """Build a :class:`Student` from a single ``leerlingen`` object."""
        student_id = _coerce_student_id(cls._extract_id(payload))

        additional = payload.get("additionalObjects") or {}
        pasfoto: str | None = None
        if isinstance(additional, Mapping):
            pasfoto_object = additional.get("pasfoto") or {}
            if isinstance(pasfoto_object, Mapping):
                pasfoto = _as_str(pasfoto_object.get("datauri"))

        return cls(
            id=student_id,
            leerlingnummer=_as_str(payload.get("leerlingnummer")),
            roepnaam=_as_str(payload.get("roepnaam")),
            achternaam=_as_str(payload.get("achternaam")),
            email=_as_str(payload.get("email")),
            mobiel_nummer=_as_str(payload.get("mobielNummer")),
            geboortedatum=_as_str(payload.get("geboortedatum")),
            geslacht=_as_str(payload.get("geslacht")),
            pasfoto=pasfoto,
        )


def parse_students(payload: Any) -> list[Student]:
    """Parse a ``/rest/v1/leerlingen`` payload into a list of students.

    Both the documented ``{"items": [...]}`` shape and a plain list are
    tolerated.
    """
    if isinstance(payload, Mapping):
        entries: Any = payload.get("items", [])
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        entries = payload
    else:
        raise TypeError("Unexpected student list payload")

    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise TypeError("Unexpected student list payload")

    students: list[Student] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TypeError("Unexpected student entry in payload")
        students.append(Student.from_api(entry))
    return students


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 datetime, returning ``None`` when unusable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _as_text(value: Any) -> str | None:
    """Return a display string from a scalar or a sequence of scalars.

    SomToday returns ``docentAfkortingen`` either as a single string or as a
    list of abbreviations depending on the appointment; both are tolerated.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        parts = [_as_text(item) for item in value]
        joined = ", ".join(part for part in parts if part)
        return joined or None
    return _as_str(value)


def _extract_student_ids(payload: Mapping[str, Any]) -> frozenset[int]:
    """Return the student ids referenced by an appointment.

    The ids live in ``additionalObjects.leerlingen.items[].links[0].id`` and are
    absent for the common single-student shape.
    """
    additional = payload.get("additionalObjects")
    if not isinstance(additional, Mapping):
        return frozenset()
    leerlingen = additional.get("leerlingen")
    if not isinstance(leerlingen, Mapping):
        return frozenset()
    items = leerlingen.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return frozenset()

    student_ids: set[int] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        try:
            student_ids.add(_coerce_student_id(_first_link_id(item)))
        except ValueError:
            continue
    return frozenset(student_ids)


@dataclass(frozen=True, slots=True)
class Lesson:
    """A single appointment (lesson) from ``/rest/v1/afspraken``."""

    id: str | None
    subject: str | None
    subject_abbr: str | None
    teacher: str | None
    room: str | None
    start: datetime
    end: datetime
    title: str | None
    type: str | None
    student_ids: frozenset[int] = frozenset()

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> Lesson:
        """Build a :class:`Lesson` from a single ``afspraken`` object.

        Raises :class:`ValueError` when the appointment has no usable start or
        end time, so :func:`parse_lesson` can skip it.
        """
        start = _parse_datetime(payload.get("beginDatumTijd"))
        end = _parse_datetime(payload.get("eindDatumTijd"))
        if start is None or end is None:
            raise ValueError("Lesson is missing a usable start or end time")

        # The ``additional`` query parameters (vak, docentAfkortingen) are
        # returned nested under ``additionalObjects``. A flat payload is also
        # tolerated (older fixtures/proxies put the objects at the top level).
        additional = payload.get("additionalObjects")
        if not isinstance(additional, Mapping):
            additional = {}

        subject: str | None = None
        subject_abbr: str | None = None
        vak = additional.get("vak")
        if not isinstance(vak, Mapping):
            vak = payload.get("vak")
        if isinstance(vak, Mapping):
            subject = _as_str(vak.get("naam"))
            subject_abbr = _as_str(vak.get("afkorting"))

        teacher = _as_text(additional.get("docentAfkortingen"))
        if teacher is None:
            teacher = _as_text(payload.get("docentAfkortingen"))

        lesson_type: str | None = None
        afspraak_type = payload.get("afspraakType")
        if isinstance(afspraak_type, Mapping):
            lesson_type = _as_str(afspraak_type.get("naam"))

        return cls(
            id=_as_str(_first_link_id(payload)),
            subject=subject,
            subject_abbr=subject_abbr,
            teacher=teacher,
            room=_as_str(payload.get("locatie")),
            start=start,
            end=end,
            title=_as_str(payload.get("titel")),
            type=lesson_type,
            student_ids=_extract_student_ids(payload),
        )


def parse_lesson(payload: Any) -> Lesson | None:
    """Parse a single appointment, returning ``None`` when unparseable."""
    if not isinstance(payload, Mapping):
        return None
    try:
        return Lesson.from_api(payload)
    except (TypeError, ValueError):
        return None


def parse_lessons(payload: Any) -> list[Lesson]:
    """Parse an ``afspraken`` payload into a list of lessons.

    Both the documented ``{"items": [...]}`` shape and a plain list are
    tolerated. Individual appointments that cannot be parsed are skipped.
    """
    if isinstance(payload, Mapping):
        entries: Any = payload.get("items", [])
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        entries = payload
    else:
        raise TypeError("Unexpected lesson list payload")

    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise TypeError("Unexpected lesson list payload")

    lessons: list[Lesson] = []
    for entry in entries:
        lesson = parse_lesson(entry)
        if lesson is not None:
            lessons.append(lesson)
    return lessons


@dataclass(slots=True)
class SomTodayTokens:
    """OAuth2 tokens and derived metadata for a SomToday account."""

    access_token: str
    refresh_token: str
    api_url: str
    expires_at: datetime
    tenant: str | None = None
    token_type: str = "Bearer"
    scope: str = SCOPE
    id_token: str | None = None
    account_id: str | None = None
    student_id: int | None = None
    student_name: str | None = None

    @property
    def is_expired(self) -> bool:
        """Return ``True`` when the access token has expired."""
        return self.expires_at <= utcnow()

    def expires_soon(self, margin: int = TOKEN_REFRESH_MARGIN) -> bool:
        """Return ``True`` when the access token expires within ``margin`` seconds."""
        return self.expires_at - utcnow() <= timedelta(seconds=margin)

    @classmethod
    def from_token_response(
        cls,
        payload: Mapping[str, Any],
        *,
        now: datetime | None = None,
        fallback_refresh_token: str | None = None,
        fallback_api_url: str | None = None,
        fallback_tenant: str | None = None,
    ) -> SomTodayTokens:
        """Build tokens from the ``/oauth2/token`` JSON response.

        ``fallback_refresh_token`` preserves the previous refresh token when a
        refresh response omits it (no-op rotation). ``fallback_api_url`` and
        ``fallback_tenant`` preserve the values of a previous token when the
        token endpoint does not echo them.
        """
        try:
            access_token = str(payload["access_token"])
        except (KeyError, TypeError) as err:
            raise ValueError("Token response is missing required fields") from err

        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            if not fallback_refresh_token:
                raise ValueError("Token response is missing required fields")
            refresh_token = fallback_refresh_token

        now = now or utcnow()
        try:
            expires_in = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError) as err:
            raise ValueError("Token response has an invalid expires_in") from err

        return cls(
            access_token=access_token,
            refresh_token=str(refresh_token),
            api_url=str(
                payload.get("somtoday_api_url") or fallback_api_url or DEFAULT_API_URL
            ),
            expires_at=now + timedelta(seconds=expires_in),
            tenant=payload.get("somtoday_tenant") or fallback_tenant,
            token_type=str(payload.get("token_type") or "Bearer"),
            scope=str(payload.get("scope") or SCOPE),
            id_token=payload.get("id_token"),
        )

    @classmethod
    def from_entry(cls, entry: _HasData) -> SomTodayTokens:
        """Restore tokens and account metadata from a config entry.

        Only the refresh token, API URL and account metadata are persisted, so
        the access token is empty and ``expires_at`` is set to now. This forces
        :meth:`SomTodayAuth.async_ensure_valid` to refresh before the first
        request.
        """
        data = entry.data
        student_id = data.get(CONF_STUDENT_ID)
        return cls(
            access_token="",
            refresh_token=str(data[CONF_REFRESH_TOKEN]),
            api_url=str(data.get(CONF_API_URL) or DEFAULT_API_URL),
            expires_at=utcnow(),
            account_id=_as_str(data.get(CONF_ACCOUNT_ID)),
            student_id=int(student_id) if student_id is not None else None,
            student_name=_as_str(data.get(CONF_STUDENT_NAME)),
        )

    def as_entry_data(self) -> dict[str, Any]:
        """Return the fields that should be persisted in the config entry."""
        data: dict[str, Any] = {
            CONF_REFRESH_TOKEN: self.refresh_token,
            CONF_API_URL: self.api_url,
        }
        if self.account_id is not None:
            data[CONF_ACCOUNT_ID] = self.account_id
        if self.student_id is not None:
            data[CONF_STUDENT_ID] = self.student_id
        if self.student_name is not None:
            data[CONF_STUDENT_NAME] = self.student_name
        return data
