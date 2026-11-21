"""捷途 TSP 协议层：AES 加解密 + 信封签名 + HTTPS 远程控制/状态查询"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import random
import string
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote

import aiohttp

from .const import (
    API_AES_KEY,
    APP_CLIENT_ID,
    BFF_BASE,
    PATH_CAR_INFO,
    PATH_LOGIN,
    PATH_OWNER_LIST,
    PATH_OWNER_VINS,
    PATH_POINT_DETAIL,
    PATH_POINT_FLOW,
    PATH_SEND_SMS,
    SMS_CLIENT_ID,
    UAA_BASE,
    API_CODE_AES_KEY,
    API_CODE_REMOTE_CONTROL,
    API_CODE_VEH_DATE,
    API_CODE_VEH_STATUS,
    API_GET_VEH_FUNS,
    API_CODE_GET_VEH_FUNS,
    API_REMOTE_CONTROL,
    API_VEH_DATE,
    API_VEH_STATUS,
    DEFAULT_API_BASE,
    DEFAULT_UNLOCK_VALUE,
    VALUE_ENGINE_START,
    VALUE_ENGINE_STOP,
    VALUE_FIND_CAR,
    VALUE_LOCK,
)

_LOGGER = logging.getLogger(__name__)

_RANDOM_CHARS = string.ascii_letters + string.digits


def _random_str(length: int = 32) -> str:
    return "".join(random.choice(_RANDOM_CHARS) for _ in range(length))


def _parse_key(raw: str | None) -> bytes | None:
    """解析密钥：支持 base64 或 hex，按长度推断"""
    if not raw:
        return None
    raw = raw.strip()
    try:
        if len(raw) in (16, 24, 32):
            return raw.encode()
        return base64.b64decode(raw)
    except (binascii.Error, ValueError):
        try:
            return bytes.fromhex(raw)
        except ValueError:
            _LOGGER.warning("无法解析密钥：%s", raw[:8])
            return None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class JetourCrypto:
    """AES 加解密与签名。密钥/模式/签名规则均可配置，便于抓到真机密钥后直接填参使用。"""

    def __init__(
        self,
        key: str | None = None,
        mode: str = "cbc",
        iv_source: str = "randomstr",
        sign_key: str | None = None,
        sign_algo: str = "sha256",
        sign_template: str = "appId+apiCode+timestamp+randomstr+body+transationid",
    ) -> None:
        self._key = _parse_key(key)
        self.mode = (mode or "cbc").lower()
        self.iv_source = (iv_source or "randomstr").lower()
        self.sign_key = sign_key or ""
        self.sign_algo = (sign_algo or "sha256").lower()
        self.sign_template = sign_template

    @property
    def enabled(self) -> bool:
        return self._key is not None

    def _iv(self, randomstr: str) -> bytes | None:
        if self.mode in ("ecb",):
            return None
        if self.iv_source == "zero":
            return b"\x00" * 16
        if self.iv_source == "key":
            return (self._key or b"\x00" * 16)[:16]
        return randomstr.encode()[:16].ljust(16, b"\0")

    def encrypt(self, plaintext: str, randomstr: str) -> str:
        """业务明文 -> base64 密文；未配置密钥时回退为明文 base64（便于调试/明文网关）"""
        data = plaintext.encode()
        if not self._key:
            return _b64(data)
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            if self.mode == "gcm":
                cipher = Cipher(algorithms.AES(self._key), modes.GCM(self._iv(randomstr)))
            elif self.mode == "ecb":
                cipher = Cipher(algorithms.AES(self._key), modes.ECB())
            else:
                cipher = Cipher(algorithms.AES(self._key), modes.CBC(self._iv(randomstr)))
            enc = cipher.encryptor()
            if self.mode == "gcm":
                return _b64(enc.update(data) + enc.finalize() + enc.tag)
            return _b64(enc.update(data) + enc.finalize())
        except Exception as err:  # pragma: no cover
            _LOGGER.error("加密失败: %s", err)
            return _b64(data)

    def decrypt(self, ciphertext_b64: str, randomstr: str = "") -> str:
        """base64 密文 -> 明文字符串"""
        if not self._key:
            return base64.b64decode(ciphertext_b64).decode("utf-8", "ignore")
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            raw = base64.b64decode(ciphertext_b64)
            if self.mode == "gcm":
                body, tag = raw[:-16], raw[-16:]
                cipher = Cipher(algorithms.AES(self._key), modes.GCM(self._iv(randomstr), tag))
            elif self.mode == "ecb":
                cipher = Cipher(algorithms.AES(self._key), modes.ECB())
            else:
                cipher = Cipher(algorithms.AES(self._key), modes.CBC(self._iv(randomstr)))
            dec = cipher.decryptor()
            out = dec.update(raw if self.mode != "gcm" else body) + dec.finalize()
            return out.decode("utf-8", "ignore")
        except Exception as err:
            _LOGGER.error("解密失败: %s", err)
            return ""

    def sign(self, fields: dict[str, Any]) -> str:
        """生成 sign。默认 HMAC-SHA256(拼接待签串)，密钥为空时退化为纯摘要"""
        parts = [str(fields.get(p, "")) for p in self.sign_template.split("+")]
        raw = "".join(parts).encode()
        if self.sign_algo == "none":
            return ""
        digestmod = hashlib.md5 if self.sign_algo == "md5" else hashlib.sha256
        if self.sign_key:
            digest = hmac.new(self.sign_key.encode(), raw, digestmod).digest()
        else:
            digest = digestmod(raw).digest()
        return _b64(digest)


class JetourTspClient:
    """捷途 TSP HTTPS 客户端"""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        vin: str,
        user_id: str,
        app_id: str,
        access_token: str | None = None,
        model_code: str = "",
        pcode: str = "000000",
        base_url: str = DEFAULT_API_BASE,
        crypto: JetourCrypto | None = None,
        extra_headers: dict[str, str] | None = None,
        unlock_value: int = DEFAULT_UNLOCK_VALUE,
    ) -> None:
        self._session = session
        self.vin = vin
        self.user_id = user_id
        self.app_id = app_id
        self.access_token = access_token
        self.model_code = model_code
        self.pcode = pcode
        self.base_url = base_url.rstrip("/")
        self.crypto = crypto or JetourCrypto()
        self.extra_headers = extra_headers or {}
        self.unlock_value = unlock_value

    # ---------- 信封 ----------
    def build_envelope(self, api_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        randomstr = _random_str(32)
        timestamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
        transationid = f"{self.app_id}{timestamp}{random.randint(1000, 999999)}"
        plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        body = self.crypto.encrypt(plaintext, randomstr)
        envelope = {
            "randomstr": randomstr,
            "apiCode": api_code,
            "appId": self.app_id,
            "sign": self.crypto.sign(
                {
                    "appId": self.app_id,
                    "apiCode": api_code,
                    "timestamp": timestamp,
                    "randomstr": randomstr,
                    "body": body,
                    "transationid": transationid,
                }
            ),
            "transationid": transationid,
            "body": body,
            "timestamp": timestamp,
        }
        return envelope

    async def async_post(self, path: str, api_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送信封请求，返回解密后的业务 dict"""
        envelope = self.build_envelope(api_code, payload)
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "JetourHA/1.0",
        }
        if self.access_token:
            headers["access_token"] = self.access_token
            headers["Authorization"] = self.access_token
        headers.update(self.extra_headers)

        async with self._session.post(
            url, json=envelope, headers=headers, params={"access_token": self.access_token} if self.access_token else None
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise JetourApiError(f"HTTP {resp.status}: {text[:200]}")
            try:
                outer = json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}

        status = outer.get("status") or outer.get("errorCode")
        if status and str(status) not in ("200", "SUCCEED"):
            raise JetourApiError(f"服务端返回 {status}: {outer.get('errorMessage') or outer.get('message')}")

        body = outer.get("body")
        if body is None:
            return outer
        try:
            decrypted = self.crypto.decrypt(body, outer.get("randomstr", ""))
            parsed = json.loads(decrypted) if decrypted else {}
        except json.JSONDecodeError:
            parsed = {"raw": decrypted}
        if isinstance(parsed, dict):
            parsed.setdefault("_status", status)
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    # ---------- 业务接口 ----------
    async def async_get_status(self) -> dict[str, Any]:
        """主动查询车辆状态（含电量/油量/续航/门窗/胎压/位置）"""
        return await self.async_post(
            API_VEH_STATUS,
            API_CODE_VEH_STATUS,
            {"vin": self.vin, "userId": self.user_id},
        )

    async def async_get_veh_date(self) -> dict[str, Any]:
        return await self.async_post(API_VEH_DATE, API_CODE_VEH_DATE, {"vin": self.vin})

    async def async_get_veh_funs(self) -> dict[str, Any]:
        return await self.async_post(
            API_GET_VEH_FUNS, API_CODE_GET_VEH_FUNS, {"vin": self.vin, "userId": self.user_id}
        )

    async def async_remote_control(
        self, code: str, value: int | str, model_code: str | None = None
    ) -> dict[str, Any]:
        """下发远程控制指令。返回 HTTP 回执（最终执行结果由 MQTT CONTROL_REAULT 推送）"""
        payload = {
            "pcode": self.pcode,
            "modelCode": model_code or self.model_code,
            "vin": self.vin,
            "userId": self.user_id,
            "command": {"code": code, "value": value},
        }
        return await self.async_post(API_REMOTE_CONTROL, API_CODE_REMOTE_CONTROL, payload)

    # ---------- 便捷指令 ----------
    async def async_lock(self) -> dict[str, Any]:
        return await self.async_remote_control("Fortification", VALUE_LOCK)

    async def async_unlock(self) -> dict[str, Any]:
        return await self.async_remote_control("Fortification", self.unlock_value)

    async def async_engine_start(self) -> dict[str, Any]:
        return await self.async_remote_control("POWER_PHEV", VALUE_ENGINE_START)

    async def async_engine_stop(self) -> dict[str, Any]:
        return await self.async_remote_control("POWER_PHEV", VALUE_ENGINE_STOP)

    async def async_find_car(self) -> dict[str, Any]:
        return await self.async_remote_control("FindCar", VALUE_FIND_CAR)

    async def async_fetch_aes_key(self, fixed_key: str) -> str | None:
        """用内置固定密钥 K0 协商动态业务密钥 K1（返回 base64）"""
        negotiator = JetourCrypto(key=fixed_key, mode=self.crypto.mode, iv_source=self.crypto.iv_source)
        original, self.crypto = self.crypto, negotiator
        try:
            result = await self.async_post(API_AES_KEY, API_CODE_AES_KEY, {"appId": self.app_id})
        finally:
            self.crypto = original
        for key in ("aesKey", "key", "sessionKey", "data"):
            if result.get(key):
                return result[key]
        return None


class JetourApiError(Exception):
    """TSP 接口错误"""


class JetourLoginError(Exception):
    """账号登录（短信验证码）相关错误"""


class JetourAccountClient:
    """捷途官方账号登录（免抓包）。

    手机号 + 短信验证码即可换取：
      - accessToken / refreshToken：BFF 业务接口鉴权
      - externalToken.sdkUserId / sdkToken：车联 MQTT 凭据（cas-emq:8082）
      - 该账号下已绑定的全部车辆
    """

    TIMEOUT = 20

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str = APP_CLIENT_ID,
        sms_client_id: str = SMS_CLIENT_ID,
        access_token: str | None = None,
        refresh_token: str | None = None,
        mobile: str | None = None,
        sdk_user_id: str | None = None,
        sdk_token: str | None = None,
        expire_at: float = 0.0,
    ) -> None:
        """access_token 等参数可直接注入，复用配置条目里已登录的凭据，无需重新收验证码"""
        self._session = session
        self.client_id = client_id
        self.sms_client_id = sms_client_id

        self.mobile = mobile
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expire_at = expire_at
        self.refresh_expire_at: float = 0.0
        self.sdk_user_id = sdk_user_id
        self.sdk_token = sdk_token

    # ---------- 登录 ----------
    async def async_send_sms(self, mobile: str) -> None:
        """下发短信验证码"""
        data = await self._post(
            f"{UAA_BASE}{PATH_SEND_SMS}",
            {"mobile": mobile},
            params={"client_id": self.sms_client_id},
        )
        self._raise_if_failed(data, "短信下发失败")
        self.mobile = mobile

    async def async_login(self, mobile: str, code: str) -> dict[str, Any]:
        """用验证码完成登录，返回凭据摘要"""
        data = await self._post(
            f"{UAA_BASE}{PATH_LOGIN}",
            {"mobile": mobile, "verificationCode": code},
        )
        self._raise_if_failed(data, "验证码校验失败")

        payload = data.get("data") or {}
        self.mobile = mobile
        self.access_token = payload.get("accessToken")
        self.refresh_token = payload.get("refreshToken")

        expire = payload.get("expireAt")
        self.expire_at = expire / 1000 if expire else 0.0
        refresh_expire = payload.get("refreshExpireAt")
        self.refresh_expire_at = refresh_expire / 1000 if refresh_expire else 0.0

        external = payload.get("externalToken") or {}
        if external.get("sdkUserId"):
            self.sdk_user_id = external["sdkUserId"]
        if external.get("sdkToken"):
            # 服务端返回的是 URL 编码串，MQTT 直连前需解码
            self.sdk_token = unquote(external["sdkToken"])

        if not self.access_token:
            raise JetourLoginError("登录响应缺少 accessToken")
        return payload

    # ---------- 车辆 ----------
    async def async_list_vehicles(self) -> list[dict[str, Any]]:
        """返回账号下车辆列表（车型名 + 车牌），供配置流程选择"""
        vins = await self._vehicle_vins()
        plates = await self._vehicle_plates()

        vehicles: list[dict[str, Any]] = []
        for vin in vins:
            model = ""
            model_code = ""
            info = await self._car_info(vin) or {}
            model = info.get("productCategoryName") or ""
            model_code = info.get("modelCode") or ""
            model = model or "未知车型"
            plate = plates.get(vin, "")
            label = f"{model} · {plate}" if plate else f"{model} · {vin}"
            vehicles.append(
                {
                    "vin": vin,
                    "model": model,
                    "model_code": model_code,
                    "plate": plate,
                    "label": label,
                }
            )
        return vehicles

    async def _vehicle_vins(self) -> list[str]:
        data = await self._get(f"{BFF_BASE}{PATH_OWNER_VINS}")
        rows = (data.get("data") or {}).get("vins") if isinstance(data.get("data"), dict) else None
        if not rows:
            rows = (data.get("data") or []) if isinstance(data.get("data"), list) else []
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            rows = [r.get("vin") for r in rows if r.get("vin")]
        return [v for v in (rows or []) if v]

    async def _vehicle_plates(self) -> dict[str, str]:
        """车牌：取不到不影响主流程"""
        try:
            data = await self._get(f"{BFF_BASE}{PATH_OWNER_LIST}")
        except JetourLoginError:
            return {}
        rows = data.get("data") or []
        plates: dict[str, str] = {}
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("vin"):
                plates[row["vin"]] = row.get("licensePlate") or ""
        return plates

    async def async_get_car_info(self, vin: str) -> dict[str, Any] | None:
        """按 VIN 查询车辆档案（车型 / modelCode / 发动机号 / 开票信息等）。

        注意：该接口服务端不校验车辆归属，任意已登录账号均可按 VIN 查询。
        """
        if self.expire_at and self.expire_at < time.time():
            raise JetourLoginError(
                "登录凭据已于 %s 过期，请通过「重新配置」再次短信登录"
                % datetime.fromtimestamp(self.expire_at).strftime("%Y-%m-%d %H:%M")
            )
        data = await self._get(f"{BFF_BASE}{PATH_CAR_INFO}/{vin}")
        return data.get("data")

    async def async_get_point_detail(self) -> dict[str, Any]:
        """查询积分账户余额（BFF /web/point/consumer/detail）"""
        if not self.access_token:
            raise JetourLoginError("尚未登录，缺少 accessToken")
        if self.expire_at and self.expire_at < time.time():
            raise JetourLoginError(
                "登录凭据已于 %s 过期，请通过「重新配置」再次短信登录"
                % datetime.fromtimestamp(self.expire_at).strftime("%Y-%m-%d %H:%M")
            )
        return await self._get(f"{BFF_BASE}{PATH_POINT_DETAIL}", auth=True)

    async def async_get_point_flow(
        self, page_no: int = 1, page_size: int = 10, status: int = 2
    ) -> dict[str, Any]:
        """查询账号积分流水（BFF /web/point/flow，与会员接口共用短信登录 token）"""
        if not self.access_token:
            raise JetourLoginError("尚未登录，缺少 accessToken")
        if self.expire_at and self.expire_at < time.time():
            raise JetourLoginError(
                "登录凭据已于 %s 过期，请通过「重新配置」再次短信登录"
                % datetime.fromtimestamp(self.expire_at).strftime("%Y-%m-%d %H:%M")
            )
        path = (
            f"{BFF_BASE}{PATH_POINT_FLOW}?pageNo={page_no}"
            f"&pageSize={page_size}&status={status}"
        )
        return await self._get(path, auth=True)

    async def _car_info(self, vin: str) -> dict[str, Any] | None:
        try:
            return await self.async_get_car_info(vin)
        except JetourLoginError:
            return None

    # ---------- HTTP ----------
    async def _authed_url(self, path: str) -> str:
        if not self.access_token:
            raise JetourLoginError("尚未登录，缺少 accessToken")
        sep = "&" if "?" in path else "?"
        return f"{path}{sep}access_token={quote(self.access_token, safe='')}"

    async def _get(self, path: str, auth: bool | None = None) -> dict[str, Any]:
        need_auth = auth if auth is not None else (
            "/owner/" in path or "/car-basic-info/" in path
        )
        url = await self._authed_url(path) if need_auth else path
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=self.TIMEOUT)) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise JetourLoginError(f"网络请求失败: {err}") from err
        data = self._parse(text, resp.status)
        # 业务接口（需鉴权）必须校验状态码，否则 token 失效时会静默返回空列表
        if need_auth:
            self._raise_if_failed(data, "接口调用失败")
        return data

    async def _post(
        self,
        url: str,
        payload: dict[str, Any],
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._session.post(
                url,
                params=params,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.TIMEOUT),
                headers={"Content-Type": "application/json"},
            ) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise JetourLoginError(f"网络请求失败: {err}") from err
        return self._parse(text, resp.status)

    @staticmethod
    def _parse(text: str, status: int) -> dict[str, Any]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise JetourLoginError(f"服务端返回非 JSON（HTTP {status}）: {text[:120]}")
        if not isinstance(data, dict):
            raise JetourLoginError(f"响应格式异常: {str(data)[:120]}")
        return data

    @staticmethod
    def _raise_if_failed(data: dict[str, Any], prefix: str) -> None:
        status = data.get("status")
        if status is None:
            status = data.get("error")
        if status not in (200, "200", "maskit.success.general", None):
            detail = data.get("message") or data.get("error") or data.get("error_description")
            raise JetourLoginError(f"{prefix}: {detail or data}")
