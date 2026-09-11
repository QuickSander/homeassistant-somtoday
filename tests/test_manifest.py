"""Tests for the integration manifest metadata."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "sometoday"

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def _manifest() -> dict[str, Any]:
    return json.loads((INTEGRATION_DIR / "manifest.json").read_text())


def test_manifest_required_fields() -> None:
    """The manifest declares the required metadata with a version string.

    The exact version is intentionally not pinned (review N16): every release
    bump would otherwise break this test.
    """
    manifest = _manifest()

    assert manifest["domain"] == "sometoday"
    assert isinstance(manifest["version"], str)
    assert VERSION_PATTERN.match(manifest["version"])
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["integration_type"] == "hub"
