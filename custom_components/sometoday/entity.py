"""Shared entity base for the SomToday integration.

One device is created per config entry (per student). All entities share the
same device metadata and set ``has_entity_name`` so their friendly name is
composed from the device name and the translation key
(docs/architecture.md section 8).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STUDENT_NAME, DOMAIN
from .coordinator import SomTodayDataUpdateCoordinator


class SomTodayEntity(CoordinatorEntity[SomTodayDataUpdateCoordinator]):
    """Base class for all SomToday entities bound to the coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SomTodayDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the entity with the shared device metadata."""
        super().__init__(coordinator)
        self._entry = entry
        student_name = entry.data.get(CONF_STUDENT_NAME) or "student"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"SomToday {student_name}",
            manufacturer="SomToday",
            model="Student",
            entry_type=DeviceEntryType.SERVICE,
        )
