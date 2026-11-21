"""车辆传感器：电量、油量、续航、里程、电压、温度、胎压等"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    KEY_AVG_FUEL,
    KEY_BATTERY_VOLTAGE,
    KEY_FUEL,
    KEY_IN_TEMP,
    KEY_ODOMETER,
    KEY_OUT_TEMP,
    KEY_POWER_CONS,
    KEY_RANGE,
    KEY_SOC,
    KEY_UPLOAD_TIME,
    TPMS_KEYS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class JetourSensorDescription(SensorEntityDescription):
    """传感器描述"""

    data_key: str = ""
    scale: float = 1.0


SENSORS: tuple[JetourSensorDescription, ...] = (
    JetourSensorDescription(
        key="soc",
        name="动力电池电量",
        data_key=KEY_SOC,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    JetourSensorDescription(
        key="fuel_level",
        name="剩余油量",
        data_key=KEY_FUEL,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fuel",
    ),
    JetourSensorDescription(
        key="range",
        name="续航里程",
        data_key=KEY_RANGE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
    ),
    JetourSensorDescription(
        key="odometer",
        name="总里程",
        data_key=KEY_ODOMETER,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
    ),
    JetourSensorDescription(
        key="battery_voltage",
        name="12V 蓄电池电压",
        data_key=KEY_BATTERY_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-battery",
    ),
    JetourSensorDescription(
        key="internal_temp",
        name="车内温度",
        data_key=KEY_IN_TEMP,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    JetourSensorDescription(
        key="external_temp",
        name="车外温度",
        data_key=KEY_OUT_TEMP,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    JetourSensorDescription(
        key="power_cons",
        name="平均电耗",
        data_key=KEY_POWER_CONS,
        native_unit_of_measurement="kWh/100km",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
    ),
    JetourSensorDescription(
        key="avg_fuel",
        name="平均油耗",
        data_key=KEY_AVG_FUEL,
        native_unit_of_measurement="L/100km",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-station",
    ),
)


@dataclass(frozen=True, kw_only=True)
class JetourPointsSensorDescription(SensorEntityDescription):
    """积分传感器描述"""

    data_key: str = ""


POINTS_SENSORS: tuple[JetourPointsSensorDescription, ...] = (
    JetourPointsSensorDescription(
        key="points_balance",
        name="积分余额",
        data_key="balance",
        native_unit_of_measurement="积分",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-circle",
    ),
    JetourPointsSensorDescription(
        key="points_records_total",
        name="积分流水条数",
        data_key="total",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:format-list-numbered",
    ),
    JetourPointsSensorDescription(
        key="points_latest_change",
        name="最近积分变动",
        data_key="latest_point",
        native_unit_of_measurement="积分",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-four-points",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[JetourSensor] = [JetourSensor(coordinator, desc) for desc in SENSORS]
    entities.extend(
        JetourSensor(
            coordinator,
            JetourSensorDescription(
                key=f"tpms_{data_key}",
                name=f"{label}胎压",
                data_key=data_key,
                native_unit_of_measurement="bar",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:tire",
            ),
        )
        for data_key, label in TPMS_KEYS.items()
    )
    points = hass.data.get(DOMAIN, {}).get("points")
    if points is not None:
        entities.extend(JetourPointsSensor(points, desc) for desc in POINTS_SENSORS)
    async_add_entities(entities)


class JetourSensor(CoordinatorEntity, SensorEntity):
    """通用车辆传感器"""

    def __init__(self, coordinator, description: JetourSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.vin}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self):
        value = self.coordinator.get_float(self.entity_description.data_key)  # type: ignore[attr-defined]
        return None if value is None else round(value * self.entity_description.scale, 2)

    @property
    def extra_state_attributes(self):
        upload = self.coordinator.get(KEY_UPLOAD_TIME)  # type: ignore[attr-defined]
        return {"vehicle_upload_time": upload} if upload else {}


class JetourPointsSensor(CoordinatorEntity, SensorEntity):
    """账号积分传感器"""

    def __init__(self, coordinator, description: JetourPointsSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"jetour_points_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "account")},
            name="账户积分",
            manufacturer="捷途汽车",
        )

    @property
    def native_value(self):
        data = self.coordinator.data or {}  # type: ignore[attr-defined]
        if self.entity_description.data_key == "latest_point":
            value = (data.get("latest") or {}).get("streamPoint")
        else:
            value = data.get(self.entity_description.data_key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}  # type: ignore[attr-defined]
        latest = data.get("latest") or {}
        info = latest.get("businessInfo") or {}
        attrs: dict[str, Any] = {}
        if data.get("point_system"):
            attrs["point_system"] = data["point_system"]
        if data.get("expiring") not in (None, ""):
            attrs["expiring_point"] = data["expiring"]
        if info.get("businessName"):
            attrs["business_name"] = info["businessName"]
        if latest.get("createTime"):
            try:
                attrs["change_time"] = datetime.fromtimestamp(
                    int(latest["createTime"]) / 1000
                ).strftime("%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError, OSError):
                pass
        records = [
            {
                "business": (row.get("businessInfo") or {}).get("businessName"),
                "change": row.get("streamPoint"),
            }
            for row in (data.get("records") or [])[:5]
            if isinstance(row, dict)
        ]
        if records:
            attrs["recent_flow"] = records
        return attrs
