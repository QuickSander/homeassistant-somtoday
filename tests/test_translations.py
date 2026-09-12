"""Tests for the SomToday translation files.

The English, Dutch and ``strings.json`` files must stay in sync so the config
flow renders correctly in both languages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.sometoday.const import DOMAIN

INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "sometoday"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Any:
    """Enable loading the custom integration in every test."""
    yield


def _flatten(data: dict[str, Any], prefix: str = "") -> set[str]:
    """Return the set of dotted leaf keys of a nested mapping."""
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= _flatten(value, path)
        else:
            keys.add(path)
    return keys


def test_translation_files_have_matching_keys() -> None:
    """English, Dutch and strings.json expose the same keys."""
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    english = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text())
    dutch = json.loads((INTEGRATION_DIR / "translations" / "nl.json").read_text())

    assert _flatten(strings) == _flatten(english)
    assert _flatten(strings) == _flatten(dutch)


async def test_english_config_translations_load(hass: HomeAssistant) -> None:
    """Home Assistant can load the English config-flow translations."""
    translations = await async_get_translations(hass, "en", "config", [DOMAIN])

    assert (
        translations[f"component.{DOMAIN}.config.step.user.title"]
        == "Sign in to SomToday"
    )
    assert (
        "{auth_url}"
        in translations[f"component.{DOMAIN}.config.step.user.description"]
    )
    assert (
        translations[f"component.{DOMAIN}.config.step.user.data.redirect_url"]
        == "Redirect URL or code"
    )
    for key in (
        "invalid_url",
        "login_page",
        "state_mismatch",
        "invalid_auth",
        "cannot_connect",
        "no_students",
        "wrong_account",
    ):
        assert f"component.{DOMAIN}.config.error.{key}" in translations

    assert (
        translations[f"component.{DOMAIN}.config.step.student.data.student_select"]
        == "Student"
    )
    assert (
        translations[f"component.{DOMAIN}.config.abort.student_removed"]
        != ""
    )


async def test_dutch_config_translations_load(hass: HomeAssistant) -> None:
    """Home Assistant can load the Dutch student step and abort keys.

    The structural parity test compares keys; this test additionally proves the
    new ``student`` step and ``student_removed`` abort are actually loadable in
    the non-source-of-truth locale.
    """
    translations = await async_get_translations(hass, "nl", "config", [DOMAIN])

    assert (
        translations[f"component.{DOMAIN}.config.step.student.data.student_select"]
        == "Leerling"
    )
    assert (
        translations[f"component.{DOMAIN}.config.step.student.title"]
        == "Kies een leerling"
    )
    assert (
        translations[f"component.{DOMAIN}.config.abort.student_removed"] != ""
    )
