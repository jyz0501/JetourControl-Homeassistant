"""控车按钮：远程启动 / 远程熄火 / 寻车"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CMD_ENGINE_START,
    CMD_ENGINE_STOP,
    CMD_FIND_CAR,
    DOMAIN,
    VALUE_ENGINE_START,
    VALUE_ENGINE_STOP,
    VALUE_FIND_CAR,
)

_LOGGER = logging.getLogger(__name__)

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="engine_start", name="远程启动", icon="mdi:car-arrow-right",
        entity_category=None,
    ),
    ButtonEntityDescription(
        key="engine_stop", name="远程熄火", icon="mdi:power",
        entity_category=None,
    ),
    ButtonEntityDescription(
        key="find_car", name="寻车", icon="mdi:map-search",
        entity_category=None,
    ),
)

COMMAND_MAP = {
    "engine_start": (CMD_ENGINE_START, VALUE_ENGINE_START),
    "engine_stop": (CMD_ENGINE_STOP, VALUE_ENGINE_STOP),
    "find_car": (CMD_FIND_CAR, VALUE_FIND_CAR),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([JetourButton(coordinator, desc) for desc in BUTTONS])


class JetourButton(CoordinatorEntity, ButtonEntity):
    """下发单条控车指令"""

    def __init__(self, coordinator, description: ButtonEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.vin}_{description.key}"
        self._attr_device_info = coordinator.device_info

    async def async_press(self, **kwargs: Any) -> None:
        code, value = COMMAND_MAP[self.entity_description.key]
        try:
            await self.coordinator.async_command(code, value)  # type: ignore[attr-defined]
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("%s 指令下发失败: %s", self.entity_description.name, err)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self.coordinator.last_result  # type: ignore[attr-defined]
        return {"last_command_result": result} if result else {}
