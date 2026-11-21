# 捷途控车（Home Assistant 集成）

**中文** | [English](README_EN.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![version](https://img.shields.io/badge/version-1.4.0-blue.svg)](https://github.com/jyz0501/JetourControl-Homeassistant/releases)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

通过 **MQTT 长连接**（车辆状态/控车回执推送）+ **HTTPS 远程控制**（下发指令）接入捷途 TSP，无需 adb、无需手机常驻。

## 一、协议事实（真机抓包 / 运行日志实证）

### 1. MQTT（TCP 长连接，服务端 → 客户端推送）
| 项 | 值 |
|---|---|
| Broker（生产） | `tcp://cas-emq.mychery.com:8082`（华为云 EMQ） |
| 备用 | `ssl://mqtt-app-lioncloud.mychery.com:8083`、`ssl://pushmsg.mychery.com:87` |
| 车辆状态主题 | `down/vehicleInfo/phone/{VIN}` |
| 控车回执主题 | `down/rct/phone/{VIN}` |
| 事件 / OTA | `down/event/phone/{VIN}`、`down/ota/phone/{VIN}` |

> 集成仅按本车 VIN 精确订阅，不使用通配主题。

推送报文（**明文**，无需解密）：
```json
{"body":"{\"soc\":\"48.45\",\"fuelLevel\":\"10\",\"drivMileage\":\"62.0\",\"mileage\":\"24049.0\",\"batteryVoltage\":\"10.29\",\"lockParameter\":true,\"uploadTime\":...}",
 "payloadType":"VEHICLE_INFO","pushTime":...,"serialNo":...}
```
控车回执：`payloadType = CONTROL_REAULT`
```json
{"cmdCode":"00512","code":"1000","message":"远程指令执行成功","sendId":...,"vin":"..."}
```
常见失败码：`1023 当前低压电池电量低，无法执行当前操作`。

### 2. HTTPS 网关
- 网关：`https://jetour.mychery.com:86`
- 控车：`POST /app-vehicle/v1/appVehicle/remoteControl`（apiCode `v1/appVehicle/remoteControl`）
  ```json
  业务明文: {"pcode":"000000","modelCode":"<modelCode>","vin":"...","userId":"...",
             "command":{"code":"Fortification","value":1}}
  ```
- 状态查询：`POST /app-vehicle/v2/appVehicle/queryVehStatusEV`，明文 `{"vin":"...","userId":"..."}`
- 动态密钥协商：`POST /app-key/v1/appKey/aesKey`（内置固定密钥 K0 换动态密钥 K1）
- 外层信封（统一）：
  ```json
  {"randomstr":"<32位>","apiCode":"...","appId":"...","sign":"<base64>","transationid":"<appId+时间戳+随机>",
   "body":"<AES 密文 base64>","timestamp":"yyyyMMddHHmmss"}
  ```
  响应：`{"errorCode":"200","status":"SUCCEED","body":"<密文>","randomstr":"...","sign":"..."}`

### 3. 指令码（cmdCode 为车端回执编号）
| 功能 | code | value | cmdCode |
|---|---|---|---|
| 上锁 | `Fortification` | `1`（已实测成功） | 00512 |
| 解锁 | `Fortification` | `0`（默认，配置项 `unlock_value` 可调；车辆正常时复核） | 00512 |
| 远程熄火 | `POWER_PHEV` | `1`（已实测下发） | 00754 |
| 远程启动 | `POWER_PHEV` | `2` | 00754 |
| 寻车 | `FindCar` | `1` | — |

其余指令族见 `const.KNOWN_COMMANDS`（`WindowControl`、`AirControl`、`ChargeStartStopControl`、`SentinelMode` 等），可用 `jetour.remote_control` 服务直接下发。

## 二、安装

### 方式一：HACS（推荐，自定义仓库）

1. HACS → 右上角 ⋮ → **Custom repositories**
2. Repository 填写 `https://github.com/jyz0501/JetourControl-Homeassistant`，Category 选 **Integration**
3. 搜索 **捷途控车** → Download → 重启 Home Assistant
4. 设置 → 设备与服务 → 添加集成 → 搜索 `捷途`

### 方式二：手动安装

```bash
cp -r <本目录> <HA配置目录>/custom_components/jetour
# 重启 Home Assistant → 设置 → 设备与服务 → 添加集成 → 搜索 "捷途"
```

> 提示：升级由 HACS 管理，版本取自 `manifest.json` 的 `version` 字段。

## 三、配置

添加集成时先选登录方式：

### 方式 A：短信验证码登录（推荐，无需抓包）

1. **选择登录方式** → 短信验证码登录（推荐）
2. **手机号**：填捷途 App 的手机号，提交后手机收到短信
3. **验证码**：填短信里的验证码
4. **选择车辆**：以列表形式列出该手机号下的全部车辆，选要接入的那一辆

```
⬜ 车型A · 鲁A***11
⬜ 车型B · 鲁A***22
```

需要接入多辆时，**重复添加集成**即可（每辆车一个配置条目）。

登录完成后会自动填充：VIN、`modelCode`、MQTT 用户名/密码（车联 `sdkUserId` / `sdkToken`），一般无需再改。

### 方式 B：手动填写 TSP 凭据（原方式）

1. **账号/车辆**：VIN、`userId`（形如 `U123456789012345`）、`appId`、`access_token`、`modelCode`、`网关`。本步会调用 `queryVehStatusEV` 做连通性校验。
2. **MQTT**：主机默认 `cas-emq.mychery.com:8082`,填写 MQTT 用户名/密码（如 Broker 允许匿名可留空）。
3. **加密**：填 `aes_key`（base64/hex）；若只拿到内置固定密钥，可填 `aes_fixed_key`，集成会自动调用 `aesKey` 协商动态密钥。签名规则通过 `sign_template` + `sign_algo` 配置。

> 凭据获取：`access_token` 与 MQTT 用户名/密码需从捷途 App 自行抓取（如抓包或调试手段）。若只需车辆状态，推荐改用方式 A 短信登录，无需任何抓包。

### 凭据说明

| | 短信登录（A） | 手动填写（B） |
|---|---|---|
| 是否需要抓包 | 否 | 是 |
| MQTT 车况推送 | ✅ 用 `sdkToken` 直连 | ✅ 填 captured 凭据 |
| HTTPS 主动查询/控车 | 网关要求 JWT，暂不支持 | ✅ |
| 车辆列表 | 自动列出（含车型、车牌） | 手动填 VIN |

短信登录拿到的是**不透明 token**，而 HTTPS 网关（`jetour.mychery.com:86`）要求 JWT（`Cannot convert access token to JSON`）。因此短信登录后**车况通过 MQTT 获取**即可正常工作；若要用 HTTPS 主动控车，请走方式 B。

## 四、实体

| 平台 | 实体 |
|---|---|
| lock | 车门锁（上锁 / 解锁） |
| sensor | 动力电池电量、剩余油量、续航里程、总里程、12V 蓄电池电压、车内/外温度、平均电耗/油耗、四轮胎压 |
| binary_sensor | 四门 / 引擎盖 / 后备箱、四窗 / 天窗、充电中、车辆在线 |
| button | 远程启动、远程熄火、寻车 |
| device_tracker | 车辆 GPS 位置 |

## 五、服务

```yaml
service: jetour.remote_control
data:
  code: Fortification
  value: 1
  wait_result: true   # 等待 MQTT 回执，最长 30s
```

### 按 VIN 查询车辆档案

```yaml
service: jetour.query_vehicle_info
data:
  vin: 你的VIN   # 留空则查询所有已配置条目的 VIN
```

- 复用集成里已登录的 `accessToken`（BFF 接口），无需抓包。
- 返回服务端原始档案：`productCategoryName`（车型）、`modelCode`、`carSeriesCode`、发动机号、开票信息、经销商等。
- 结果同时以事件 **`jetour_vehicle_info`** 发出，可被自动化监听。
- ⚠️ 该接口返回车辆档案可能含个人信息，请自行确认使用合规。

## 六、注意事项

- MQTT 推送为**明文**，只要拿到 Broker 凭据即可获得实时车辆状态；控制指令需 HTTPS 通道与加密参数。
- 车辆 12V 低压电池电压过低时（实测 <10.3V），所有远程控制会被车端拒绝（code 1023）。
- 轮询间隔只是兜底（默认 300s），MQTT 在线时状态为推送更新。

## 七、HACS 仓库准备

仓库需满足（本目录已内置 `hacs.json`、`.github/workflows/validate.yaml`）：

1. GitHub 仓库 **Topics** 添加：`home-assistant`、`hacs`、`integration`。
2. **Description** 填写中文简介，勾选将仓库设为 Public。
3. `manifest.json` 的 `documentation` 改为真实仓库地址（Release 后也能被 HACS 正常索引）。
4. 每次发版本：更新 `manifest.json` 的 `version` → 打 Tag（如 `v1.4.0`）→ GitHub Release 会自动触发打包流程上传 `jetour.zip`。
5. `hacs.json` 中 `homeassistant` 为最低 HA 版本要求（当前 `2024.6.0`）。

## 八、合规声明

完整条款（中英双语）见 [DISCLAIMER.md](DISCLAIMER.md)。

本集成通过解析捷途车联网协议实现车辆状态读取与远程控制，使用时请遵守以下约定：

1. **仅限自有车辆**：本集成仅供你对自己合法拥有或已获明确授权的车辆使用。不得用于访问、查询或控制任何他人车辆，不得绕过车辆厂商的权限校验或服务条款。
2. **凭据安全**：登录凭据（token、MQTT 用户名/密码、AES 密钥等）等同车辆钥匙，请妥善保管，不要分享、上传或写入公开仓库。集成仅在本地 Home Assistant 中使用这些凭据，不会向第三方发送。
3. **隐私数据**：车辆状态、位置、车辆档案等数据可能包含个人信息。请按所在地法律法规（如《个人信息保护法》《数据安全法》或 GDPR 等）处理，避免在未经授权的情况下收集、存储或传播他人隐私数据。
4. **风险自担**：远程控制涉及车辆安全，请在安全的环境下使用，并自行承担使用风险。作者不对因使用本集成造成的车辆损坏、数据泄露、财产损失或违反车厂服务条款的后果负责。
5. **非官方项目**：本项目为第三方个人开发，与捷途汽车及其关联方无关，也未获得其官方支持或背书。商标与品牌归各自权利人所有。
6. **合规使用**：你应确保使用方式符合当地法律法规及车辆厂商的服务协议；如相关方要求停止，请立即停止使用并删除相应凭据。
