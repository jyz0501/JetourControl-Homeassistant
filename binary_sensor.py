"""车门 / 车窗 / 充电 / 在线状态"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CHARGE_STATUS_MAP,
    DOOR_KEYS,
    DOMAIN,
    KEY_CHARGE_STATUS,
    KEY_UPLOAD_TIME,
    STATE_OPEN,
    WINDOW_KEYS,
)

_LOGGER = logging.getLogger(__name__)

ONLINE_TIMEOUT = 15 * 60  # 秒


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[JetourBinarySensor] = [
        JetourBinarySensor(
            coordinator,
            BinarySensorEntityDescription(
                key=f"door_{key}",
                name=f"{label}",
                device_class=BinarySensorDeviceClass.DOOR,
                icon="mdi:car-door",
            ),
            key,
        )
        for key, label in DOOR_KEYS.items()
    ]
    entities += [
        JetourBinarySensor(
            coordinator,
            BinarySensorEntityDescription(
                key=f"window_{key}",
                name=f"{label}",
                device_class=BinarySensorDeviceClass.WINDOW,
                icon="mdi:car-door",
            ),
            key,
        )
        for key, label in WINDOW_KEYS.items()
    ]
    entities.append(JetourChargingSensor(coordinator))
    entities.append(JetourOnlineSensor(coordinator))
    async_add_entities(entities)


class JetourBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """车门 / 车窗（0=关 1=开）"""

    def __init__(self, coordinator, description: BinarySensorEntityDescription, data_key: str) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._data_key = data_key
        self._attr_unique_id = f"{coordinator.vin}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.get(self._data_key)  # type: ignore[attr-defined]
        if value in (None, "2"):
            return None
        return str(value) == STATE_OPEN


class JetourChargingSensor(CoordinatorEntity, BinarySensorEntity):
    """充电状态"""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_charging"
        self._attr_name = "充电中"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return str(self.coordinator.get(KEY_CHARGE_STATUS)) == "1"  # type: ignore[attr-defined]

    @property
    def extra_state_attributes(self):
        code = str(self.coordinator.get(KEY_CHARGE_STATUS, ""))  # type: ignore[attr-defined]
        return {"charge_status_code": code, "charge_status": CHARGE_STATUS_MAP.get(code, code)}


class JetourOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    """车辆是否在线（依据最近一次上传时间的间隔判断）"""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:car-connected"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vin}_online"
        self._attr_name = "车辆在线"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        upload = self.coordinator.get(KEY_UPLOAD_TIME)  # type: ignore[attr-defined]
        try:
            ts = int(float(upload)) / 1000
        except (TypeError, ValueError):
            return False
        return (datetime.now(tz=timezone.utc).timestamp() - ts) < ONLINE_TIMEOUT
