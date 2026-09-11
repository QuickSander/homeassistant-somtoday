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
        == "Select your school"
    )
    assert (
        translations[f"component.{DOMAIN}.config.step.credentials.title"]
        == "Sign in to SomToday"
    )
