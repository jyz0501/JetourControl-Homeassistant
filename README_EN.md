# Jetour Control (Home Assistant Integration)

[中文](README.md) | **English**

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![version](https://img.shields.io/badge/version-1.4.0-blue.svg)](https://github.com/jyz0501/JetourControl-Homeassistant/releases)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Integrates with Jetour TSP via **long-lived MQTT connections** (vehicle status / command result push) + **HTTPS remote control** (command dispatch). No adb or always-on phone required.

## 1. Protocol Facts (verified by real-device captures / runtime logs)

### 1.1 MQTT (TCP long connection, server → client push)

| Item | Value |
|---|---|
| Broker (production) | `tcp://cas-emq.mychery.com:8082` (Huawei Cloud EMQ) |
| Backup | `ssl://mqtt-app-lioncloud.mychery.com:8083`, `ssl://pushmsg.mychery.com:87` |
| Vehicle status topic | `down/vehicleInfo/phone/{VIN}` |
| Command result topic | `down/rct/phone/{VIN}` |
| Event / OTA | `down/event/phone/{VIN}`, `down/ota/phone/{VIN}` |

> The integration subscribes only to the exact VIN of your vehicle; wildcard topics are never used.

Push payload (**plaintext**, no decryption required):
```json
{"body":"{\"soc\":\"48.45\",\"fuelLevel\":\"10\",\"drivMileage\":\"62.0\",\"mileage\":\"24049.0\",\"batteryVoltage\":\"10.29\",\"lockParameter\":true,\"uploadTime\":...}",
 "payloadType":"VEHICLE_INFO","pushTime":...,"serialNo":...}
```
Command result: `payloadType = CONTROL_REAULT`
```json
{"cmdCode":"00512","code":"1000","message":"远程指令执行成功","sendId":...,"vin":"..."}
```
Common failure code: `1023 Low 12V battery voltage, operation rejected`.

### 1.2 HTTPS Gateway
- Gateway: `https://jetour.mychery.com:86`
- Remote control: `POST /app-vehicle/v1/appVehicle/remoteControl` (apiCode `v1/appVehicle/remoteControl`)
  ```json
  Plaintext payload: {"pcode":"000000","modelCode":"<modelCode>","vin":"...","userId":"...",
             "command":{"code":"Fortification","value":1}}
  ```
- Status query: `POST /app-vehicle/v2/appVehicle/queryVehStatusEV`, plaintext `{"vin":"...","userId":"..."}`
- Dynamic key exchange: `POST /app-key/v1/appKey/aesKey` (built-in fixed key K0 → dynamic key K1)
- Uniform outer envelope:
  ```json
  {"randomstr":"<32 chars>","apiCode":"...","appId":"...","sign":"<base64>","transationid":"<appId+timestamp+random>",
   "body":"<AES ciphertext base64>","timestamp":"yyyyMMddHHmmss"}
  ```
  Response: `{"errorCode":"200","status":"SUCCEED","body":"<ciphertext>","randomstr":"...","sign":"..."}`

### 1.3 Command Codes (cmdCode is the vehicle-side result ID)
| Function | code | value | cmdCode |
|---|---|---|---|
| Lock | `Fortification` | `1` (verified successful) | 00512 |
| Unlock | `Fortification` | `0` (default; `unlock_value` configurable, verify on your vehicle) | 00512 |
| Remote engine off | `POWER_PHEV` | `1` (verified dispatch) | 00754 |
| Remote start | `POWER_PHEV` | `2` | 00754 |
| Find my car | `FindCar` | `1` | — |

Other command families: see `const.KNOWN_COMMANDS` (`WindowControl`, `AirControl`, `ChargeStartStopControl`, `SentinelMode`, etc.). They can be dispatched directly via the `jetour.remote_control` service.

## 2. Installation

### Option 1: HACS (recommended, custom repository)

1. HACS → top-right ⋮ → **Custom repositories**
2. Repository: `https://github.com/jyz0501/JetourControl-Homeassistant`, Category: **Integration**
3. Search **Jetour Control** → Download → restart Home Assistant
4. Settings → Devices & Services → Add Integration → search `Jetour`

### Option 2: Manual installation

```bash
cp -r <this directory> <HA config dir>/custom_components/jetour
# Restart Home Assistant → Settings → Devices & Services → Add Integration → search "Jetour"
```

> Upgrades are managed by HACS; the version comes from the `version` field in `manifest.json`.

## 3. Configuration

Choose a login method when adding the integration:

### Method A: SMS verification code (recommended, no packet capture)

1. **Select login method** → SMS verification code (recommended)
2. **Phone number**: enter the number used in the Jetour app; you will receive an SMS
3. **Verification code**: enter the code from the SMS
4. **Select vehicle**: all vehicles bound to the number are listed; choose the one to integrate

```
[ ] Model A · Plate A***11
[ ] Model B · Plate B***22
```

To integrate multiple vehicles, **add the integration again** (one config entry per vehicle).

After login, VIN, `modelCode`, and MQTT username/password (telematics `sdkUserId` / `sdkToken`) are filled in automatically; no further changes are usually needed.

### Method B: Manual TSP credentials (legacy)

1. **Account / Vehicle**: VIN, `userId` (e.g. `U123456789012345`), `appId`, `access_token`, `modelCode`, gateway. This step calls `queryVehStatusEV` to verify connectivity.
2. **MQTT**: host defaults to `cas-emq.mychery.com:8082`; enter MQTT username/password (leave blank if the broker allows anonymous access).
3. **Encryption**: enter `aes_key` (base64/hex); if you only have the built-in fixed key, use `aes_fixed_key` and the integration will negotiate the dynamic key via `aesKey`. Signing rules are configured with `sign_template` + `sign_algo`.

> Credentials: `access_token` and MQTT username/password must be captured from the Jetour app yourself (packet capture or debugging). If you only need vehicle status, use Method A (SMS login) — no packet capture required.

### Credential comparison

| | SMS login (A) | Manual (B) |
|---|---|---|
| Packet capture required | No | Yes |
| MQTT status push | ✅ Direct via `sdkToken` | ✅ With captured credentials |
| HTTPS active query / control | Not supported (gateway requires JWT) | ✅ |
| Vehicle list | Automatic (with model and plate) | Manual VIN entry |

SMS login returns an **opaque token**, while the HTTPS gateway (`jetour.mychery.com:86`) requires JWT (`Cannot convert access token to JSON`). After SMS login, **vehicle status via MQTT works normally**; for HTTPS active control, use Method B.

## 4. Entities

| Platform | Entities |
|---|---|
| lock | Door lock (lock / unlock) |
| sensor | Battery SOC, fuel level, range, mileage, 12V battery voltage, interior/exterior temperature, average energy/fuel consumption, four tire pressures |
| binary_sensor | Four doors / hood / trunk, four windows / sunroof, charging, vehicle online |
| button | Remote start, remote engine off, find my car |
| device_tracker | Vehicle GPS position |

## 5. Services

```yaml
service: jetour.remote_control
data:
  code: Fortification
  value: 1
  wait_result: true   # wait for MQTT result, up to 30s
```

### Query vehicle profile by VIN

```yaml
service: jetour.query_vehicle_info
data:
  vin: YOUR_VIN   # leave blank to query all configured VINs
```

- Reuses the logged-in `accessToken` (BFF API) — no packet capture needed.
- Returns the raw profile: `productCategoryName` (model), `modelCode`, `carSeriesCode`, engine number, invoice info, dealer, etc.
- The result is also emitted as the event **`jetour_vehicle_info`** for automation triggers.
- ⚠️ This API may return personal information; ensure your use is compliant.

## 6. Notes

- MQTT pushes are **plaintext** — anyone with broker credentials can obtain real-time vehicle status; control commands require the HTTPS channel and encryption parameters.
- When the 12V battery voltage is too low (measured <10.3V), all remote controls are rejected by the vehicle (code 1023).
- The polling interval is only a fallback (default 300s); when MQTT is online, status updates via push.

## 7. HACS Repository Preparation

Requirements (this directory already includes `hacs.json` and `.github/workflows/validate.yaml`):

1. Add GitHub repository **Topics**: `home-assistant`, `hacs`, `integration`.
2. Fill in a **Description** and set the repository to Public.
3. Set `documentation` in `manifest.json` to the real repository URL (so HACS can index it after release).
4. For each release: update `version` in `manifest.json` → create a Tag (e.g. `v1.4.0`) → GitHub Release automatically triggers packaging and uploads `jetour.zip`.
5. `homeassistant` in `hacs.json` is the minimum HA version (currently `2024.6.0`).

## 8. Compliance & Disclaimer

Full terms (bilingual) are in [DISCLAIMER.md](DISCLAIMER.md).

This integration reads vehicle status and performs remote control by parsing the Jetour telematics protocol. Please observe the following:

1. **Own vehicles only**: use only on vehicles you legally own or are explicitly authorized to use. Do not access, query, or control anyone else's vehicle, and do not bypass the manufacturer's access controls or terms of service.
2. **Credential security**: credentials (token, MQTT username/password, AES keys, etc.) are equivalent to car keys. Keep them safe and never share, upload, or commit them to public repositories. The integration uses them only locally in Home Assistant and never sends them to third parties.
3. **Privacy data**: vehicle status, location, and profile data may contain personal information. Handle it in accordance with applicable laws (e.g. PIPL, DSL, GDPR) and do not collect, store, or distribute others' private data without authorization.
4. **Use at your own risk**: remote control affects vehicle safety. Use it in a safe environment at your own risk. The author is not liable for any vehicle damage, data leakage, property loss, or violation of the manufacturer's terms resulting from use of this integration.
5. **Unofficial project**: this is an independent third-party project, not affiliated with, endorsed, or supported by Jetour or its affiliates. All trademarks belong to their respective owners.
6. **Compliant use**: ensure your use complies with local laws and the vehicle manufacturer's service agreement. If any relevant party requests cessation, stop using the integration immediately and delete the associated credentials.
