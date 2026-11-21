"""捷途汽车 HomeAssistant 集成（MQTT 推送 + HTTPS 远程控制）"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import (
    JetourAccountClient,
    JetourApiError,
    JetourCrypto,
    JetourLoginError,
    JetourTspClient,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AES_FIXED_KEY,
    CONF_AES_IV_SOURCE,
    CONF_AES_KEY,
    CONF_AES_MODE,
    CONF_API_BASE,
    CONF_APP_ID,
    CONF_ENABLE_HTTP,
    CONF_ENABLE_MQTT,
    CONF_EXPIRE_AT,
    CONF_HEADERS,
    CONF_MOBILE,
    CONF_MQTT_CLIENT_ID,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_TLS,
    CONF_MQTT_TLS_INSECURE,
    CONF_MQTT_USERNAME,
    CONF_MODEL_CODE,
    CONF_MODEL_NAME,
    CONF_PCODE,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SDK_TOKEN,
    CONF_SIGN_ALGO,
    CONF_SIGN_KEY,
    CONF_SIGN_TEMPLATE,
    CONF_UNLOCK_VALUE,
    CONF_USER_ID,
    CONF_VIN,
    DEFAULT_API_BASE,
    DEFAULT_MQTT_HOST,
    DEFAULT_MQTT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNLOCK_VALUE,
    DOMAIN,
    KNOWN_COMMANDS,
)
from .coordinator import JetourCoordinator, JetourPointsCoordinator
from .mqtt_client import JetourMqttClient

_LOGGER = logging.getLogger(__name__)

try:  # HA 2024.6+ 才支持服务返回值
    from homeassistant.core import SupportsResponse
except ImportError:  # pragma: no cover
    SupportsResponse = None  # type: ignore[assignment]

PLATFORMS = [
    Platform.LOCK,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
]

SERVICE_REMOTE_CONTROL = "remote_control"
SERVICE_QUERY_VEHICLE_INFO = "query_vehicle_info"

ATTR_CODE = "code"
ATTR_VALUE = "value"
ATTR_WAIT = "wait_result"
ATTR_VIN = "vin"

# 查询结果同时发到事件总线，便于自动化 / 模板触发
EVENT_VEHICLE_INFO = f"{DOMAIN}_vehicle_info"


SERVICE_REMOTE_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CODE): vol.In(KNOWN_COMMANDS),
        vol.Required(ATTR_VALUE): vol.Any(int, str),
        vol.Optional(ATTR_WAIT, default=True): cv.boolean,
    }
)

SERVICE_QUERY_VEHICLE_INFO_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_VIN): cv.string,
    }
)


def _build_crypto(entry_data: dict[str, Any]) -> JetourCrypto:
    return JetourCrypto(
        key=entry_data.get(CONF_AES_KEY),
        mode=entry_data.get(CONF_AES_MODE, "cbc"),
        iv_source=entry_data.get(CONF_AES_IV_SOURCE, "randomstr"),
        sign_key=entry_data.get(CONF_SIGN_KEY),
        sign_algo=entry_data.get(CONF_SIGN_ALGO, "sha256"),
        sign_template=entry_data.get(
            CONF_SIGN_TEMPLATE, "appId+apiCode+timestamp+randomstr+body+transationid"
        ),
    )


def _extra_headers(entry_data: dict[str, Any]) -> dict[str, str]:
    raw = entry_data.get(CONF_HEADERS)
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except json.JSONDecodeError:
        _LOGGER.warning("额外请求头解析失败，已忽略")
        return {}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置集成条目"""
    data = {**entry.data, **entry.options}
    vin: str = data[CONF_VIN]
    session = async_get_clientsession(hass)

    crypto = _build_crypto(data)
    client = JetourTspClient(
        session=session,
        vin=vin,
        user_id=data[CONF_USER_ID],
        app_id=data[CONF_APP_ID],
        access_token=data.get(CONF_ACCESS_TOKEN),
        model_code=data.get(CONF_MODEL_CODE, ""),
        pcode=data.get(CONF_PCODE, "000000"),
        base_url=data.get(CONF_API_BASE, DEFAULT_API_BASE),
        crypto=crypto,
        extra_headers=_extra_headers(data),
        unlock_value=int(data.get(CONF_UNLOCK_VALUE, DEFAULT_UNLOCK_VALUE)),
    )

    # 未配置业务密钥时，尝试用固定密钥协商动态密钥
    if not crypto.enabled and data.get(CONF_AES_FIXED_KEY):
        try:
            negotiated = await client.async_fetch_aes_key(data[CONF_AES_FIXED_KEY])
            if negotiated:
                client.crypto = JetourCrypto(
                    key=negotiated, mode=crypto.mode, iv_source=crypto.iv_source
                )
                _LOGGER.info("已通过 aesKey 接口协商动态业务密钥")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("动态密钥协商失败（将尝试明文/自定义模式）: %s", err)

    mqtt: JetourMqttClient | None = None
    if data.get(CONF_ENABLE_MQTT, True) and data.get(CONF_MQTT_HOST):
        mqtt = JetourMqttClient(
            hass=hass,
            vin=vin,
            host=data.get(CONF_MQTT_HOST, DEFAULT_MQTT_HOST),
            port=int(data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)),
            tls=bool(data.get(CONF_MQTT_TLS, False)),
            tls_insecure=bool(data.get(CONF_MQTT_TLS_INSECURE, False)),
            username=data.get(CONF_MQTT_USERNAME),
            password=data.get(CONF_MQTT_PASSWORD),
            client_id=data.get(CONF_MQTT_CLIENT_ID),
        )

    coordinator = JetourCoordinator(
        hass=hass,
        client=client,
        vin=vin,
        name=data.get("name") or data.get(CONF_MODEL_NAME) or f"捷途汽车 {vin[-6:]}",
        interval=int(data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        mqtt=mqtt,
        model_code=data.get(CONF_MODEL_CODE),
        # 短信登录拿到的是不透明 token，HTTPS 网关要求 JWT，默认不轮询
        http_enabled=bool(data.get(CONF_ENABLE_HTTP, True)),
    )

    if mqtt is not None:
        mqtt.add_status_listener(coordinator.async_push_status)
        try:
            await mqtt.async_start()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("MQTT 启动失败，将仅使用 HTTP 轮询: %s", err)
            mqtt = None
            coordinator.mqtt = None

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "mqtt": mqtt,
    }

    # 积分流水是账号级数据，多个车辆条目共用一个协调器（取第一个可用登录态）
    if "points" not in hass.data[DOMAIN]:
        try:
            account = _account_from_entry(hass, session, None)
        except HomeAssistantError:
            account = None
        if account is not None:
            points = JetourPointsCoordinator(
                hass,
                account,
                interval=int(data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            )
            hass.data[DOMAIN]["points"] = points
            await points.async_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _register_services(hass)
    return True


@callback
def _register_services(hass: HomeAssistant) -> None:
    """注册控车服务与按 VIN 查询车辆信息服务"""
    _register_remote_control(hass)
    _register_query_vehicle_info(hass)


@callback
def _register_remote_control(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REMOTE_CONTROL):
        return

    async def _handle(call: ServiceCall) -> None:
        for entry_data in hass.data.get(DOMAIN, {}).values():
            coordinator: JetourCoordinator = entry_data["coordinator"]
            try:
                await coordinator.async_command(
                    call.data[ATTR_CODE], call.data[ATTR_VALUE], call.data[ATTR_WAIT]
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("控车指令下发失败: %s", err)

    hass.services.async_register(
        DOMAIN, SERVICE_REMOTE_CONTROL, _handle, schema=SERVICE_REMOTE_CONTROL_SCHEMA
    )


def _account_from_entry(hass: HomeAssistant, session: Any, vin: str | None) -> JetourAccountClient:
    """借用已登录配置条目的 accessToken 构造账号客户端"""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_ACCESS_TOKEN)
    ]
    if vin:
        matched = [e for e in entries if str(e.data.get(CONF_VIN, "")).upper() == vin]
        entries = matched or entries
    if not entries:
        raise HomeAssistantError("没有可用的登录凭据，请先添加集成并完成短信登录")

    data = {**entries[0].data, **entries[0].options}
    return JetourAccountClient(
        session,
        client_id=data.get(CONF_APP_ID) or "bigapp",
        access_token=data[CONF_ACCESS_TOKEN],
        refresh_token=data.get(CONF_REFRESH_TOKEN),
        mobile=data.get(CONF_MOBILE),
        sdk_user_id=data.get(CONF_USER_ID),
        sdk_token=data.get(CONF_SDK_TOKEN),
        expire_at=float(data.get(CONF_EXPIRE_AT) or 0),
    )


@callback
def _register_query_vehicle_info(hass: HomeAssistant) -> None:
    """jetour.query_vehicle_info：按 VIN 查询车辆档案（车型 / modelCode / 发动机号等）

    不传 vin 时，依次查询所有已配置条目的 VIN。
    """
    if hass.services.has_service(DOMAIN, SERVICE_QUERY_VEHICLE_INFO):
        return

    async def _handle(call: ServiceCall) -> dict[str, Any]:
        vin = str(call.data.get(ATTR_VIN) or "").strip().upper() or None
        session = async_get_clientsession(hass)
        account = _account_from_entry(hass, session, vin)

        if vin:
            targets = [vin]
        else:
            targets = [
                str(entry.data.get(CONF_VIN, "")).upper()
                for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.data.get(CONF_VIN)
            ]
        if not targets:
            raise HomeAssistantError("没有可查询的 VIN，请传入 vin 参数")

        vehicles: list[dict[str, Any]] = []
        for target in dict.fromkeys(targets):
            try:
                info = await account.async_get_car_info(target)
            except (JetourApiError, JetourLoginError) as err:
                _LOGGER.warning("VIN %s 查询失败: %s", target, err)
                vehicles.append({"vin": target, "found": False, "error": str(err)})
                continue
            if not info:
                vehicles.append({"vin": target, "found": False})
                continue
            vehicles.append({"vin": target, "found": True, "data": info})

        result = {"count": len(vehicles), "vehicles": vehicles}
        hass.bus.async_fire(EVENT_VEHICLE_INFO, result)
        return result

    kwargs: dict[str, Any] = {}
    if SupportsResponse is not None:
        kwargs["supports_response"] = SupportsResponse.OPTIONAL
    hass.services.async_register(
        DOMAIN,
        SERVICE_QUERY_VEHICLE_INFO,
        _handle,
        schema=SERVICE_QUERY_VEHICLE_INFO_SCHEMA,
        **kwargs,
    )


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """配置变更时重载"""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载集成条目"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data and data.get("mqtt"):
            await data["mqtt"].async_stop()
    return unload_ok
