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
    CONF_API_URL,
    CONF_REFRESH_TOKEN,
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


@dataclass(frozen=True, slots=True)
class School:
    """A SomToday school as returned by ``organisaties.json``."""

    uuid: str
    name: str
    place: str | None = None
    oidc_urls: tuple[Mapping[str, Any], ...] = ()

    @property
    def has_oidc(self) -> bool:
        """Return ``True`` when the school advertises an external IdP."""
        return bool(self.oidc_urls)

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> School:
        """Build a :class:`School` from a single ``instellingen`` object."""
        try:
            uuid = str(payload["uuid"])
        except (KeyError, TypeError) as err:
            raise ValueError("School entry is missing a uuid") from err

        oidc_urls = payload.get("oidcurls") or ()
        if isinstance(oidc_urls, Mapping):
            oidc_urls = (oidc_urls,)

        return cls(
            uuid=uuid,
            name=str(payload.get("naam") or ""),
            place=payload.get("plaats"),
            oidc_urls=tuple(oidc_urls),
        )


def parse_schools(payload: Any) -> list[School]:
    """Parse the ``organisaties.json`` payload into a list of schools.

    The endpoint returns a list containing a single object with an
    ``instellingen`` key, but the other common shapes are tolerated as well.
    """
    if isinstance(payload, Mapping):
        entries: Any = payload.get("instellingen", [])
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        entries = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise TypeError("Unexpected school entry in payload")
            if "instellingen" in item:
                entries.extend(item["instellingen"] or [])
            else:
                entries.append(item)
    else:
        raise TypeError("Unexpected school list payload")

    schools: list[School] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TypeError("Unexpected school entry in payload")
        schools.append(School.from_api(entry))
    return schools


def _as_str(value: Any) -> str | None:
    """Return ``value`` as a string, or ``None`` when it is empty."""
    if value is None:
        return None
    text = str(value)
    return text or None


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
        fallback_api_url: str | None = None,
        fallback_tenant: str | None = None,
    ) -> SomTodayTokens:
        """Build tokens from the ``/oauth2/token`` JSON response.

        ``fallback_api_url`` and ``fallback_tenant`` preserve the values of a
        previous token when the token endpoint does not echo them (observed for
        refreshes; see docs/architecture.md section 12.2).
        """
        try:
            access_token = str(payload["access_token"])
            refresh_token = str(payload["refresh_token"])
        except (KeyError, TypeError) as err:
            raise ValueError("Token response is missing required fields") from err

        now = now or utcnow()
        try:
            expires_in = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError) as err:
            raise ValueError("Token response has an invalid expires_in") from err

        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
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
        """Restore tokens from a config entry.

        Only the refresh token and API URL are persisted, so the access token
        is empty and ``expires_at`` is set to now. This forces
        :meth:`SomTodayAuthClient.async_ensure_valid` to refresh before the
        first request.
        """
        data = entry.data
        return cls(
            access_token="",
            refresh_token=str(data[CONF_REFRESH_TOKEN]),
            api_url=str(data.get(CONF_API_URL) or DEFAULT_API_URL),
            expires_at=utcnow(),
        )

    def as_entry_data(self) -> dict[str, Any]:
        """Return the fields that should be persisted in the config entry."""
        return {
            CONF_REFRESH_TOKEN: self.refresh_token,
            CONF_API_URL: self.api_url,
        }
