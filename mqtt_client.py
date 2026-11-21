"""MQTT 长连接客户端：订阅车辆状态与控车结果推送（TCP/TLS）"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import uuid
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback

from .const import (
    PAYLOAD_CONTROL_RESULT,
    PAYLOAD_VEHICLE_INFO,
    TOPIC_EVENT,
    TOPIC_OTA,
    TOPIC_RCT,
    TOPIC_SINGLE_IHU,
    TOPIC_SINGLE_PHONE,
    TOPIC_VEHICLE_INFO,
)

_LOGGER = logging.getLogger(__name__)


def _new_client(client_id: str):
    """兼容 paho-mqtt 1.x / 2.x"""
    import paho.mqtt.client as mqtt

    try:
        return mqtt.Client(
            client_id=client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,  # type: ignore[attr-defined]
        )
    except (TypeError, AttributeError):
        return mqtt.Client(client_id=client_id, clean_session=True, protocol=mqtt.MQTTv311)


class JetourMqttClient:
    """捷途 MQTT 推送客户端（车辆状态 + 控车回执均为明文 JSON）"""

    def __init__(
        self,
        hass: HomeAssistant,
        vin: str,
        host: str,
        port: int = 8082,
        tls: bool = False,
        tls_insecure: bool = False,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        keepalive: int = 60,
    ) -> None:
        self.hass = hass
        self.vin = vin
        self.host = host
        self.port = port
        self.tls = tls
        self.tls_insecure = tls_insecure
        self.username = username
        self.password = password
        self.client_id = client_id or f"jetour-ha-{vin}-{uuid.uuid4().hex[:8]}"
        self.keepalive = keepalive

        # ⚠️ 只订阅本车 VIN 相关 topic。切勿使用 down/# 这类全局通配：
        #    该 broker 对前缀通配放行度过高，会收到全平台其他车辆的实时数据。
        self.topics = [
            TOPIC_VEHICLE_INFO.format(vin=vin),
            TOPIC_RCT.format(vin=vin),
            TOPIC_EVENT.format(vin=vin),
            TOPIC_OTA.format(vin=vin),
            TOPIC_SINGLE_PHONE.format(vin=vin),
            TOPIC_SINGLE_IHU.format(vin=vin),
        ]
        self._client = _new_client(self.client_id)
        self._status_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._result_waiters: list[asyncio.Future] = []
        self._connected = False
        self.last_result: dict[str, Any] | None = None

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        if username:
            self._client.username_pw_set(username, password or "")
        if tls:
            ctx = ssl.create_default_context()
            if tls_insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self._client.tls_set_context(ctx)

    # ---------- 生命周期 ----------
    def _on_connect(self, client, userdata, flags, rc):  # noqa: D401
        if rc == 0:
            self._connected = True
            _LOGGER.info("捷途 MQTT 已连接 %s:%s，订阅 %s", self.host, self.port, self.topics)
            client.subscribe([(t, 1) for t in self.topics])
        else:
            _LOGGER.error("捷途 MQTT 连接失败，rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):  # noqa: D401
        self._connected = False
        _LOGGER.warning("捷途 MQTT 断开（rc=%s），paho 将自动重连", rc)

    @staticmethod
    def _flatten(data: dict[str, Any]) -> dict[str, Any]:
        """把 {"key":{"value":"1","content":"开启"}} 压平为 {"key":"1"}"""
        out: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, dict) and "value" in value:
                out[key] = value.get("value")
            elif value is None or isinstance(value, (str, int, float, bool)):
                out[key] = value
        return out

    def _on_message(self, client, userdata, msg):  # noqa: D401
        try:
            payload = json.loads(msg.payload.decode("utf-8", "ignore"))
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return

        # 标准信封：{payloadType, body, pushTime, serialNo}
        if "payloadType" in payload and "body" in payload:
            body = payload.get("body")
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    pass
            if not isinstance(body, dict):
                return
            self.hass.add_job(self._async_dispatch(payload.get("payloadType"), body, payload))
            return

        # 裸数据族（如 down/single/phone/{vin}/checkupResult）：无信封，值为嵌套对象
        flattened = self._flatten(payload)
        if flattened:
            _LOGGER.debug("收到裸数据推送 %s，字段 %s 个", msg.topic, len(flattened))
            self.hass.add_job(self._async_dispatch(PAYLOAD_VEHICLE_INFO, flattened, payload))

    @callback
    def _async_dispatch(self, payload_type: str, body: dict[str, Any], raw: dict[str, Any]) -> None:
        if payload_type == PAYLOAD_VEHICLE_INFO:
            for listener in list(self._status_listeners):
                try:
                    listener(body)
                except Exception as err:  # pragma: no cover
                    _LOGGER.exception("处理车辆状态推送失败: %s", err)
            return
        if payload_type == PAYLOAD_CONTROL_RESULT:
            self.last_result = body
            _LOGGER.debug("控车回执: %s", body)
            for fut in list(self._result_waiters):
                if not fut.done():
                    fut.set_result(body)
            self._result_waiters.clear()

    async def async_start(self) -> None:
        """在 executor 中启动 MQTT 循环"""

        def _connect() -> None:
            self._client.connect_async(self.host, self.port, self.keepalive)
            self._client.loop_start()

        await self.hass.async_add_executor_job(_connect)

    async def async_stop(self) -> None:
        def _stop() -> None:
            self._client.loop_stop()
            self._client.disconnect()

        await self.hass.async_add_executor_job(_stop)
        self._connected = False

    # ---------- 订阅 ----------
    @callback
    def add_status_listener(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._status_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._status_listeners.remove(listener)

        return _remove

    async def async_wait_control_result(self, timeout: float = 30.0) -> dict[str, Any] | None:
        """等待车端控车回执（CONTROL_REAULT）"""
        fut: asyncio.Future = self.hass.loop.create_future()
        self._result_waiters.append(fut)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            _LOGGER.warning("等待控车回执超时（%ss）", timeout)
            return None
        finally:
            if fut in self._result_waiters:
                self._result_waiters.remove(fut)

    @property
    def connected(self) -> bool:
        return self._connected
