"""车辆位置（GPS）"""
from __future__ import annotations

import logging

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KEY_LAT, KEY_LNG

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([JetourDeviceTracker(coordinator)])


class JetourDeviceTracker(CoordinatorEntity, TrackerEntity):
    """车辆 GPS 位置"""

    _attr_icon = "mdi:car-side"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_tracker"
        self._attr_name = "车辆位置"
        self._attr_device_info = coordinator.device_info

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self.coordinator.get_float(KEY_LAT)  # type: ignore[attr-defined]

    @property
    def longitude(self) -> float | None:
        return self.coordinator.get_float(KEY_LNG)  # type: ignore[attr-defined]
