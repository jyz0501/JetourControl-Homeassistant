"""车门锁实体：上锁 / 解锁"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CMD_LOCK, CMD_UNLOCK, DOMAIN, VALUE_LOCK

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([JetourLock(coordinator)])


class JetourLock(CoordinatorEntity, LockEntity):
    """车辆门锁"""

    _attr_translation_key = "door_lock"
    _attr_icon = "mdi:car-door-lock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_lock"
        self._attr_name = "车门锁"
        self._attr_device_info = coordinator.device_info

    @property
    def is_locked(self) -> bool | None:
        return self.coordinator.locked  # type: ignore[attr-defined]

    async def async_lock(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(CMD_LOCK, VALUE_LOCK)  # type: ignore[attr-defined]

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_command(CMD_UNLOCK, self.coordinator.client.unlock_value)  # type: ignore[attr-defined]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self.coordinator.last_result  # type: ignore[attr-defined]
        return {"last_command_result": result} if result else {}
