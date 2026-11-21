"""配置流程：短信验证码登录（推荐） / 手动填写 TSP 凭据 / MQTT / 加密参数"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    CONF_LOGIN_MODE,
    CONF_MOBILE,
    CONF_MODEL_CODE,
    CONF_MODEL_NAME,
    CONF_MQTT_CLIENT_ID,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_TLS,
    CONF_MQTT_TLS_INSECURE,
    CONF_MQTT_USERNAME,
    CONF_PCODE,
    CONF_PLATE,
    CONF_REFRESH_EXPIRE_AT,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SDK_TOKEN,
    CONF_SDK_USER_ID,
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
    LOGIN_MODE_MANUAL,
    LOGIN_MODE_SMS,
)

_LOGGER = logging.getLogger(__name__)

MOBILE_RE = re.compile(r"^1[3-9]\d{9}$")

STEP_SMS_SCHEMA = vol.Schema({vol.Required(CONF_MOBILE): str})

STEP_CODE_SCHEMA = vol.Schema({vol.Required("verification_code"): str})

STEP_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_VIN): str,
        vol.Required(CONF_USER_ID): str,
        vol.Required(CONF_APP_ID): str,
        vol.Required(CONF_ACCESS_TOKEN): str,
        vol.Optional("name", default=""): str,
        vol.Optional(CONF_MODEL_CODE, default=""): str,
        vol.Optional(CONF_PCODE, default="000000"): str,
        vol.Optional(CONF_API_BASE, default=DEFAULT_API_BASE): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=30, max=3600)
        ),
    }
)


def _mqtt_schema(defaults: dict[str, Any]) -> vol.Schema:
    """MQTT 表单：短信登录时用 sdkUserId/sdkToken 预填"""
    return vol.Schema(
        {
            vol.Required(CONF_ENABLE_MQTT, default=bool(defaults.get(CONF_ENABLE_MQTT, True))): bool,
            vol.Optional(CONF_MQTT_HOST, default=defaults.get(CONF_MQTT_HOST, DEFAULT_MQTT_HOST)): str,
            vol.Optional(
                CONF_MQTT_PORT, default=int(defaults.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT) or DEFAULT_MQTT_PORT)
            ): vol.Coerce(int),
            vol.Optional(CONF_MQTT_TLS, default=bool(defaults.get(CONF_MQTT_TLS, False))): bool,
            vol.Optional(CONF_MQTT_TLS_INSECURE, default=bool(defaults.get(CONF_MQTT_TLS_INSECURE, False))): bool,
            vol.Optional(CONF_MQTT_USERNAME, default=defaults.get(CONF_MQTT_USERNAME, "")): str,
            vol.Optional(CONF_MQTT_PASSWORD, default=defaults.get(CONF_MQTT_PASSWORD, "")): str,
            vol.Optional(CONF_MQTT_CLIENT_ID, default=defaults.get(CONF_MQTT_CLIENT_ID, "")): str,
        }
    )


STEP_CRYPTO_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_AES_KEY, default=""): str,
        vol.Optional(CONF_AES_FIXED_KEY, default=""): str,
        vol.Optional(CONF_AES_MODE, default="cbc"): vol.In(["cbc", "ecb", "gcm"]),
        vol.Optional(CONF_AES_IV_SOURCE, default="randomstr"): vol.In(["randomstr", "zero", "key"]),
        vol.Optional(CONF_SIGN_KEY, default=""): str,
        vol.Optional(CONF_SIGN_ALGO, default="sha256"): vol.In(["sha256", "md5", "none"]),
        vol.Optional(
            CONF_SIGN_TEMPLATE, default="appId+apiCode+timestamp+randomstr+body+transationid"
        ): str,
        vol.Optional(CONF_HEADERS, default=""): str,
        vol.Optional(CONF_UNLOCK_VALUE, default=DEFAULT_UNLOCK_VALUE): vol.Coerce(int),
    }
)


class JetourConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """捷途汽车配置流程"""

    VERSION = 1

    def __init__(self) -> None:
        self._account: JetourAccountClient | None = None
        self._vehicles: list[dict[str, Any]] = []
        self._base: dict[str, Any] = {}

    # ---------- 入口：选择登录方式 ----------
    async def async_step_user(self, user_input=None) -> FlowResult:
        return self.async_show_menu(step_id="user", menu_options=["sms", "manual"])

    # ---------- 短信登录 ----------
    async def async_step_sms(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mobile = str(user_input[CONF_MOBILE]).strip()
            if not MOBILE_RE.match(mobile):
                errors["base"] = "invalid_mobile"
            else:
                client = JetourAccountClient(async_get_clientsession(self.hass))
                try:
                    await client.async_send_sms(mobile)
                except JetourLoginError as err:
                    errors["base"] = "sms_failed"
                    _LOGGER.warning("短信下发失败: %s", err)
                else:
                    self._account = client
                    return await self.async_step_code()

        return self.async_show_form(step_id="sms", data_schema=STEP_SMS_SCHEMA, errors=errors)

    async def async_step_code(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = self._account
            if client is None:
                return await self.async_step_sms()
            try:
                await client.async_login(client.mobile or "", str(user_input["verification_code"]).strip())
                vehicles = await client.async_list_vehicles()
            except JetourLoginError as err:
                errors["base"] = "invalid_code"
                _LOGGER.warning("登录失败: %s", err)
            else:
                if not vehicles:
                    errors["base"] = "no_vehicles"
                else:
                    self._vehicles = vehicles
                    return await self.async_step_select()

        return self.async_show_form(step_id="code", data_schema=STEP_CODE_SCHEMA, errors=errors)

    async def async_step_select(self, user_input=None) -> FlowResult:
        """账号下多辆车时，以列表形式选择接入哪一辆"""
        errors: dict[str, str] = {}
        if user_input is not None:
            vin = user_input["vin"]
            vehicle = next((v for v in self._vehicles if v["vin"] == vin), None)
            if vehicle is None:
                errors["base"] = "unknown_vin"
            else:
                await self.async_set_unique_id(vin)
                self._abort_if_unique_id_configured()
                self._base = self._base_from_login(vehicle, user_input.get("name", ""))
                self._base[CONF_SCAN_INTERVAL] = user_input.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                )
                # 短信登录路径：sdkUserId/sdkToken 已预置为 MQTT 凭据，
                # 直接建条目并自动连接，无需用户再确认 MQTT / 加密表单
                return self._create_sms_entry()

        options = {v["vin"]: v["label"] for v in self._vehicles}
        schema = vol.Schema(
            {
                vol.Required("vin"): vol.In(options),
                vol.Optional("name", default=""): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=30, max=3600)
                ),
            }
        )
        return self.async_show_form(step_id="select", data_schema=schema, errors=errors)

    def _base_from_login(self, vehicle: dict[str, Any], name: str) -> dict[str, Any]:
        """把登录结果换算成集成所需的凭据"""
        client = self._account
        return {
            CONF_LOGIN_MODE: LOGIN_MODE_SMS,
            CONF_VIN: vehicle["vin"],
            CONF_USER_ID: client.sdk_user_id or "",
            CONF_APP_ID: client.client_id,
            CONF_ACCESS_TOKEN: client.access_token or "",
            CONF_REFRESH_TOKEN: client.refresh_token or "",
            CONF_EXPIRE_AT: client.expire_at,
            CONF_REFRESH_EXPIRE_AT: client.refresh_expire_at,
            CONF_SDK_USER_ID: client.sdk_user_id or "",
            CONF_SDK_TOKEN: client.sdk_token or "",
            CONF_MOBILE: client.mobile or "",
            CONF_MODEL_CODE: vehicle.get("model_code") or "",
            CONF_MODEL_NAME: vehicle.get("model") or "",
            CONF_PCODE: "000000",
            CONF_API_BASE: DEFAULT_API_BASE,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_PLATE: vehicle.get("plate") or "",
            "name": name or vehicle.get("model") or "",
            # MQTT 凭据直接使用车联 sdkToken
            CONF_ENABLE_MQTT: True,
            # HTTPS 网关要求 JWT，短信登录的 token 用不了，避免无效轮询报错
            CONF_ENABLE_HTTP: False,
            CONF_MQTT_HOST: DEFAULT_MQTT_HOST,
            CONF_MQTT_PORT: DEFAULT_MQTT_PORT,
            CONF_MQTT_TLS: False,
            CONF_MQTT_TLS_INSECURE: False,
            CONF_MQTT_USERNAME: client.sdk_user_id or "",
            CONF_MQTT_PASSWORD: client.sdk_token or "",
        }

    def _create_sms_entry(self) -> FlowResult:
        """短信登录：补齐被跳过表单的默认值后直接创建条目"""
        data = dict(self._base)
        data.setdefault(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        data.setdefault(CONF_UNLOCK_VALUE, DEFAULT_UNLOCK_VALUE)
        data.setdefault(CONF_AES_MODE, "cbc")
        data.setdefault(CONF_AES_IV_SOURCE, "randomstr")
        data.setdefault(CONF_SIGN_ALGO, "sha256")
        data.setdefault(
            CONF_SIGN_TEMPLATE, "appId+apiCode+timestamp+randomstr+body+transationid"
        )
        title = (
            data.get("name")
            or data.get(CONF_MODEL_NAME)
            or data.get(CONF_PLATE)
            or f"捷途汽车 {data[CONF_VIN][-6:]}"
        )
        return self.async_create_entry(title=title, data=data)

    # ---------- 手动填写（保留原方式）----------
    async def async_step_manual(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_VIN])
            self._abort_if_unique_id_configured()
            client = self._build_client(user_input)
            try:
                await client.async_get_status()
            except JetourApiError as err:
                errors["base"] = "cannot_connect"
                _LOGGER.warning("TSP 连接校验失败: %s", err)
            except Exception as err:  # noqa: BLE001
                errors["base"] = "unknown"
                _LOGGER.warning("TSP 校验异常: %s", err)
            else:
                data = dict(user_input)
                data[CONF_LOGIN_MODE] = LOGIN_MODE_MANUAL
                # 手动填写的是抓包所得 JWT，可用于 HTTPS 网关，默认启用轮询
                data.setdefault(CONF_ENABLE_HTTP, True)
                self._base = data
                return await self.async_step_mqtt()

        return self.async_show_form(step_id="manual", data_schema=STEP_MANUAL_SCHEMA, errors=errors)

    # ---------- MQTT / 加密 ----------
    async def async_step_mqtt(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._base.update(user_input)
            return await self.async_step_crypto()
        return self.async_show_form(step_id="mqtt", data_schema=_mqtt_schema(self._base))

    async def async_step_crypto(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._base.update(user_input)
            data = dict(self._base)
            title = (
                data.get("name")
                or data.get(CONF_MODEL_NAME)
                or data.get(CONF_PLATE)
                or f"捷途汽车 {data[CONF_VIN][-6:]}"
            )
            return self.async_create_entry(title=title, data=data)
        return self.async_show_form(step_id="crypto", data_schema=STEP_CRYPTO_SCHEMA)

    def _build_client(self, data: dict[str, Any], crypto: JetourCrypto | None = None) -> JetourTspClient:
        session = async_get_clientsession(self.hass)
        return JetourTspClient(
            session=session,
            vin=data[CONF_VIN],
            user_id=data[CONF_USER_ID],
            app_id=data[CONF_APP_ID],
            access_token=data.get(CONF_ACCESS_TOKEN),
            model_code=data.get(CONF_MODEL_CODE, ""),
            pcode=data.get(CONF_PCODE, "000000"),
            base_url=data.get(CONF_API_BASE, DEFAULT_API_BASE),
            crypto=crypto or JetourCrypto(),
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return JetourOptionsFlow(entry)


class JetourOptionsFlow(config_entries.OptionsFlow):
    """选项：轮询间隔、MQTT 参数、加密参数"""

    def __init__(self, entry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._entry.data, **self._entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Optional(
                    CONF_ACCESS_TOKEN, default=current.get(CONF_ACCESS_TOKEN, "")
                ): str,
                vol.Optional(
                    CONF_ENABLE_MQTT, default=current.get(CONF_ENABLE_MQTT, True)
                ): bool,
                vol.Optional(
                    CONF_ENABLE_HTTP, default=current.get(CONF_ENABLE_HTTP, True)
                ): bool,
                vol.Optional(CONF_MQTT_HOST, default=current.get(CONF_MQTT_HOST, DEFAULT_MQTT_HOST)): str,
                vol.Optional(CONF_MQTT_PORT, default=current.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)): vol.Coerce(int),
                vol.Optional(CONF_MQTT_TLS, default=current.get(CONF_MQTT_TLS, False)): bool,
                vol.Optional(CONF_MQTT_USERNAME, default=current.get(CONF_MQTT_USERNAME, "")): str,
                vol.Optional(CONF_MQTT_PASSWORD, default=current.get(CONF_MQTT_PASSWORD, "")): str,
                vol.Optional(CONF_AES_KEY, default=current.get(CONF_AES_KEY, "")): str,
                vol.Optional(CONF_AES_MODE, default=current.get(CONF_AES_MODE, "cbc")): vol.In(
                    ["cbc", "ecb", "gcm"]
                ),
                vol.Optional(CONF_UNLOCK_VALUE, default=current.get(CONF_UNLOCK_VALUE, DEFAULT_UNLOCK_VALUE)): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
