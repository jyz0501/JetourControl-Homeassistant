"""数据协调器：以 MQTT 推送为主，HTTP 轮询为兜底"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class JetourCoordinator(DataUpdateCoordinator):
    """捷途车辆数据协调器"""

    def __init__(
        self,
        hass: HomeAssistant,
        client,
        vin: str,
        name: str,
        interval: int = 300,
        mqtt=None,
        model_code: str | None = None,
        http_enabled: bool = True,
    ) -> None:
        self.client = client
        self.vin = vin
        self.name = name
        self.mqtt = mqtt
        self.model_code = model_code
        self.http_enabled = http_enabled
        self._http_failures = 0
        self.last_result: dict[str, Any] | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"Jetour {vin}",
            update_interval=timedelta(seconds=interval) if interval else None,
        )

    # ---------- 数据 ----------
    async def _async_update_data(self) -> dict[str, Any]:
        """车况以 MQTT 推送为主，HTTP 轮询只是兜底。

        HTTPS 网关要求 JWT，而短信登录拿到的是不透明 token（会返回 401
        Cannot convert access token to JSON）。这类鉴权失败不应拖垮整个集成：
        连续失败后自动停用轮询，保留已有数据，继续走 MQTT 推送。
        """
        if not self.http_enabled:
            return self.data or {}

        try:
            data = await self.client.async_get_status()
        except Exception as err:  # noqa: BLE001
            self._http_failures += 1
            detail = f"捷途车辆状态查询失败: {err}"
            # 401 是凭据类型不匹配（需要 JWT），重试也无意义
            if self._http_failures >= 2 or "401" in str(err):
                self.http_enabled = False
                _LOGGER.warning(
                    "%s。已停用 HTTP 轮询，改为仅依赖 MQTT 推送"
                    "（网关要求 JWT，短信登录的 token 不适用于 HTTPS 接口）",
                    detail,
                )
            else:
                _LOGGER.debug("%s（第 %s 次）", detail, self._http_failures)

            if self.data:
                return self.data
            if self.mqtt is not None:
                return {}
            raise UpdateFailed(detail) from err

        self._http_failures = 0
        return data

    @callback
    def async_push_status(self, status: dict[str, Any]) -> None:
        """MQTT 推送到达：直接更新实体，无需等待轮询"""
        merged = dict(self.data or {})
        merged.update(status)
        self.async_set_updated_data(merged)

    # ---------- 读取助手 ----------
    @property
    def status(self) -> dict[str, Any]:
        return self.data or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.status.get(key, default)

    def get_float(self, key: str) -> float | None:
        value = self.status.get(key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def locked(self) -> bool | None:
        # 真机 MQTT 车况推送为 lockParameter（bool），旧抓包为 lockP
        value = self.status.get("lockParameter", self.status.get("lockP"))
        if value is None:
            return None
        return bool(value) if isinstance(value, bool) else str(value) in ("1", "true", "True")

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.vin)},
            name=self.name,
            manufacturer="捷途汽车",
            model=self.model_code or "捷途",
            serial_number=self.vin,
        )

    # ---------- 控车 ----------
    async def async_command(self, code: str, value: int | str, wait_result: bool = True) -> dict[str, Any]:
        """下发控车指令并等待车端回执"""
        ack = await self.client.async_remote_control(code, value)
        result: dict[str, Any] | None = None
        if wait_result and self.mqtt is not None:
            result = await self.mqtt.async_wait_control_result(timeout=30)
        elif wait_result and self.mqtt is None:
            result = ack
        if result:
            self.last_result = result
        return {"ack": ack, "result": result}


class JetourPointsCoordinator(DataUpdateCoordinator):
    """账号级积分流水（独立于车辆条目，按账号刷新）"""

    def __init__(self, hass: HomeAssistant, account, interval: int = 300) -> None:
        self.account = account
        super().__init__(
            hass,
            _LOGGER,
            name="Jetour Points",
            update_interval=timedelta(seconds=interval) if interval else None,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            detail, flow = await asyncio.gather(
                self.account.async_get_point_detail(),
                self.account.async_get_point_flow(),
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"积分查询失败: {err}") from err
        account = detail.get("data") or {}
        if not isinstance(account, dict):
            account = {}
        payload = flow.get("data") or {}
        if not isinstance(payload, dict):
            payload = {}
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            rows = []
        return {
            "balance": account.get("payableBalance"),
            "expiring": account.get("expiringPoint"),
            "point_system": (account.get("pointSystem") or {}).get("name"),
            "total": payload.get("total", 0),
            "records": rows,
            "latest": rows[0] if rows else {},
        }
