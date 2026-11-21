"""常量定义：捷途 TSP 真实协议（MQTT + HTTPS）"""
from __future__ import annotations

DOMAIN = "jetour"

# ---------- 配置键 ----------
CONF_VIN = "vin"
CONF_USER_ID = "user_id"
CONF_APP_ID = "app_id"
CONF_ACCESS_TOKEN = "access_token"
CONF_MODEL_CODE = "model_code"
CONF_PCODE = "pcode"

CONF_API_BASE = "api_base"
CONF_AES_KEY = "aes_key"                 # 业务 AES 密钥（base64/hex）
CONF_AES_FIXED_KEY = "aes_fixed_key"     # 协商用的内置固定密钥 K0
CONF_AES_MODE = "aes_mode"               # cbc / ecb / gcm
CONF_AES_IV_SOURCE = "aes_iv_source"     # randomstr / zero / key
CONF_SIGN_KEY = "sign_key"
CONF_SIGN_TEMPLATE = "sign_template"
CONF_SIGN_ALGO = "sign_algo"             # sha256 / md5 / none
CONF_HEADERS = "headers"                 # 额外请求头（JSON 字符串）

CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_TLS = "mqtt_tls"
CONF_MQTT_TLS_INSECURE = "mqtt_tls_insecure"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_MQTT_CLIENT_ID = "mqtt_client_id"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_UNLOCK_VALUE = "unlock_value"       # 解锁指令 value（车端实测待确认，默认 0）
CONF_ENABLE_MQTT = "enable_mqtt"
CONF_ENABLE_HTTP = "enable_http"         # HTTPS 网关主动查询（需要 JWT）

# ---------- 短信验证码登录（免抓包）----------
CONF_LOGIN_MODE = "login_mode"           # sms = 短信登录 / manual = 手动填写
CONF_MOBILE = "mobile"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRE_AT = "expire_at"
CONF_REFRESH_EXPIRE_AT = "refresh_expire_at"
CONF_SDK_USER_ID = "sdk_user_id"         # 车联 MQTT 账号
CONF_SDK_TOKEN = "sdk_token"             # 车联 MQTT 口令
CONF_PLATE = "plate"

LOGIN_MODE_SMS = "sms"
LOGIN_MODE_MANUAL = "manual"

DEFAULT_SCAN_INTERVAL = 300
DEFAULT_UNLOCK_VALUE = 0

# ---------- 服务端 ----------
# 生产网关（抓包实证）
DEFAULT_API_BASE = "https://jetour.mychery.com:86"

# ---------- 官方 App 账号服务（短信验证码登录，实测可用）----------
# 这是公版 App 的真实登录链路：拿 accessToken 与车联 MQTT 凭据，无需抓包
UAA_BASE = "https://uaa-consumer.jetour.com.cn"
BFF_BASE = "https://mobile-consumer.jetour.com.cn"

APP_CLIENT_ID = "bigapp"                 # App 内置 clientId，登录响应会回传
SMS_CLIENT_ID = "1"                      # 短信接口实测使用该 client_id
PATH_SEND_SMS = "/api/v1/common/mobile/sms"
PATH_LOGIN = "/api/v1/uaa/mobile/mobile-code-login"
PATH_OWNER_VINS = "/web/car-service/owner/vins"
PATH_OWNER_LIST = "/web/car-service/owner/list"
PATH_CAR_INFO = "/web/car-service/car-basic-info/info"
PATH_POINT_FLOW = "/web/point/flow"
PATH_POINT_DETAIL = "/web/point/consumer/detail"

SERVICE_APP_VEHICLE = "/app-vehicle"
SERVICE_APP_KEY = "/app-key"

API_REMOTE_CONTROL = f"{SERVICE_APP_VEHICLE}/v1/appVehicle/remoteControl"
API_CODE_REMOTE_CONTROL = "v1/appVehicle/remoteControl"

API_VEH_STATUS = f"{SERVICE_APP_VEHICLE}/v2/appVehicle/queryVehStatusEV"
API_CODE_VEH_STATUS = "v2/appVehicle/queryVehStatusEV"

API_VEH_DATE = f"{SERVICE_APP_VEHICLE}/v1/appVehicle/queryVehDate"
API_CODE_VEH_DATE = "v1/appVehicle/queryVehDate"

API_GET_VEH_FUNS = f"{SERVICE_APP_VEHICLE}/v1/appVehicle/getVehFuns"
API_CODE_GET_VEH_FUNS = "v1/appVehicle/getVehFuns"

API_AES_KEY = f"{SERVICE_APP_KEY}/v1/appKey/aesKey"
API_CODE_AES_KEY = "app-key/v1/appKey/aesKey"

# sdkAuth 抓包实证挂在 app-vehicle 服务下（aesKey 才在 app-key 下）
API_SDK_AUTH = f"{SERVICE_APP_VEHICLE}/v1/appKey/sdkAuth"
API_CODE_SDK_AUTH = "app-vehicle/v1/appKey/sdkAuth"

# ---------- MQTT（TCP 长连接，服务端→App 推送） ----------
# 实证：华为云 MQTT tcp://cas-emq.mychery.com:8082（车辆状态/控车结果）
#       备用：ssl://mqtt-app-lioncloud.mychery.com:8083、ssl://pushmsg.mychery.com:87
DEFAULT_MQTT_HOST = "cas-emq.mychery.com"
DEFAULT_MQTT_PORT = 8082
DEFAULT_MQTT_TLS = False

TOPIC_VEHICLE_INFO = "down/vehicleInfo/phone/{vin}"
TOPIC_RCT = "down/rct/phone/{vin}"        # 远程控制结果
TOPIC_EVENT = "down/event/phone/{vin}"
TOPIC_OTA = "down/ota/phone/{vin}"

# 实测额外推送族（2026-10 抓包验证）：体检报告/单车数据按 VIN 分节
# ⚠️ 严禁订阅 down/# —— 该 broker ACL 放行事件流，会收到全平台其他车辆的数据
TOPIC_SINGLE_PHONE = "down/single/phone/{vin}/#"
TOPIC_SINGLE_IHU = "down/single/ihu/{vin}/#"

PAYLOAD_VEHICLE_INFO = "VEHICLE_INFO"
PAYLOAD_CONTROL_RESULT = "CONTROL_REAULT"  # 服务端实际拼写

# ---------- 控车指令码（cmdCode 为车端回执编号） ----------
CMD_LOCK = "Fortification"        # 00512
CMD_UNLOCK = "Fortification"      # 00512
CMD_ENGINE_STOP = "POWER_PHEV"    # 00754
CMD_ENGINE_START = "POWER_PHEV"
CMD_FIND_CAR = "FindCar"

VALUE_LOCK = 1
VALUE_ENGINE_STOP = 1
VALUE_ENGINE_START = 2
VALUE_FIND_CAR = 1

# 其他已知指令族（dex: com.chery.lion.digital.core.tsp.CmdTask$*）
KNOWN_COMMANDS = [
    "Fortification", "POWER_PHEV", "FindCar", "EagleEye", "EagleEyeFindCar",
    "LockControl", "DoorControl", "WindowControl", "SkylightControl",
    "SunShadeControl", "TailgateControl", "FrontTrunkControl", "FrunkControl",
    "ChargingFlapControl", "ChargingGunControl", "ChargeStartStopControl",
    "ChargeLimit", "ChargeAppointControl", "AirControl", "CoolingControl",
    "HeatingControl", "LowBeamControl", "WelcomeLightControl", "SeatControl",
    "SteeringWheelControl", "RearWindowDefrosting", "VehicleStartControl",
    "VehicleStandby", "SentinelMode", "PetMode", "NapMode", "CampingMode",
    "DefenseMode", "BatteryPreheating", "BatteryAppointmentControl",
    "VehicleInspection", "VehicleLocation", "Engine", "Power", "Voltage",
]

# 控车结果码
RESULT_OK = "1000"

# ---------- 状态字段（VEHICLE_INFO 明文） ----------
KEY_SOC = "soc"                      # 动力电池电量 %
KEY_FUEL = "fuelLevel"               # 油量 %
KEY_RANGE = "drivMileage"            # 续航 km
KEY_ODOMETER = "mileage"             # 总里程 km
KEY_BATTERY_VOLTAGE = "batteryVoltage"   # 12V 低压电池电压
KEY_CHARGE_STATUS = "chargeStatus"
KEY_LOCK_P = "lockParameter"         # 真机 MQTT 推送字段：true=已上锁（兼容旧版 lockP）
KEY_LAT = "latitude"
KEY_LNG = "longitude"
KEY_UPLOAD_TIME = "uploadTime"
KEY_IN_TEMP = "internalTemperatureRaw"
KEY_OUT_TEMP = "externalTemperatureRaw"
KEY_POWER_CONS = "powerCons"
KEY_AVG_FUEL = "avgFuelConsumption"
KEY_VEH_STATUS = "vehStatus"
KEY_HAND_BRAKE = "handBreak"
KEY_SPEED = "vehicleSpeed"

DOOR_KEYS = {
    "lfbfDoor": "左前门",
    "rhbfDoor": "右前门",
    "lrbfDoor": "左后门",
    "rrbfDoor": "右后门",
    "engineHood": "引擎盖",
    "trunkDoor": "后备箱",
}
WINDOW_KEYS = {
    "lfbfWind": "左前窗",
    "rhbfWind": "右前窗",
    "lfatWind": "左后窗",
    "rhatWind": "右后窗",
    "scuttle": "天窗",
}
TPMS_KEYS = {
    "lfbfPsi": "左前胎压",
    "rhbfPsi": "右前胎压",
    "lfatPsi": "左后胎压",
    "rhatPsi": "右后胎压",
}

# 车门/窗状态：0=关 1=开 2=未知/不支持
STATE_CLOSED = "0"
STATE_OPEN = "1"

# 充电状态枚举（实测 3=未充电）
CHARGE_STATUS_MAP = {
    "0": "未充电",
    "1": "充电中",
    "2": "充电完成",
    "3": "未连接",
    "4": "充电故障",
}
