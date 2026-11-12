"""NXR 系列充电模块通讯协议 V1.48 —— 寄存器表与状态位定义。

数据来源：《NXR系列充电模块通讯协议VER1.48（客户版）》表1、表2。
"""

# ---------------------------------------------------------------- 表1 寄存器
# reg -> (名称, 数据类型, 单位/说明)
# 数据类型: "float" 浮点(IEEE754) / "int" 整型
REGISTERS = {
    0x0001: ("模块电压", "float", "V"),
    0x0002: ("模块电流", "float", "A"),
    0x0003: ("模块限流点", "float", "0~1，×额定电流"),
    0x0004: ("DC板温度", "float", "°C"),
    0x0005: ("输入相电压(直流输入电压)", "float", "V"),
    0x0008: ("PFC0电压(正半母线)", "float", "V"),
    0x000A: ("PFC1电压(负半母线)", "float", "V"),
    0x000B: ("面板(环境)温度", "float", "°C"),
    0x000C: ("交流A相电压", "float", "V"),
    0x000D: ("交流B相电压", "float", "V"),
    0x000E: ("交流C相电压", "float", "V"),
    0x0010: ("PFC板温度", "float", "°C"),
    0x0011: ("额定输出功率", "float", "W"),
    0x0012: ("额定输出电流", "float", "A"),
    0x0017: ("设置工作海拔", "int", "m，1000~5000，掉电保存"),
    0x001B: ("设置输出电流值", "int", "值=电流×1024"),
    0x001E: ("设置组号", "int", "0~7，byte7低三位"),
    0x001F: ("设置地址分配方式", "int", "0x00000000自动/0x00010000拨码"),
    0x0020: ("设置输出功率", "float", "0.1~1，×额定功率"),
    0x0021: ("设置输出电压", "float", "V"),
    0x0022: ("设置限流点", "float", "0~1"),
    0x0023: ("设置输出电压上限值", "float", "V，过压点"),
    0x0030: ("开关机", "int", "0x00000000开机/0x00010000关机"),
    0x0031: ("过压复位", "int", "0x00000000禁止/0x00010000复位"),
    0x003E: ("输出过压保护关联允许", "int", "0x00000000允许/0x00010000禁止"),
    0x0040: ("当前告警/状态", "int", "见表2"),
    0x0043: ("拨码地址", "int", ""),
    0x0044: ("短路复位", "int", "0x00000000禁止/0x00010000复位"),
    0x0046: ("设置输入模式", "int", "0x01交流(默认)/0x02直流"),
    0x0048: ("输入功率", "int", "W"),
    0x004A: ("当前设定海拔", "int", "m，默认1000"),
    0x004B: ("当前输入工作模式", "int", "1单相/2直流/3三相/5模式不匹配"),
    0x0054: ("SerialNo低位(ID号)", "int", ""),
    0x0055: ("SerialNo高位", "int", ""),
    0x0056: ("DCDC版本号", "int", "取低16bit"),
    0x0057: ("PFC版本号", "int", "取低16bit"),
}

# ---------------------------------------------------------------- 表2 状态位
# bit -> (说明, 是否故障类)
# 0无效/1有效；bit22 为开关机状态(0开机/1关机)，不算故障。
STATUS_BITS = {
    0: ("模块故障(红指示灯亮)", True),
    1: ("模块保护(黄指示灯亮)", True),
    2: ("保留", False),
    3: ("模块内部SCI通信故障", True),
    4: ("输入模式检测错误(或输入接线错误)", True),
    5: ("监控下发输入模式与实际工作模式不匹配", True),
    6: ("保留", False),
    7: ("DCDC过压", True),
    8: ("PFC电压异常(不平衡或过压或欠压)", True),
    9: ("交流过压", True),
    10: ("保留", False),
    11: ("保留", False),
    12: ("保留", False),
    13: ("保留", False),
    14: ("交流欠压", True),
    15: ("保留", False),
    16: ("CAN通信故障", True),
    17: ("模块不均流", True),
    18: ("保留", False),
    19: ("保留", False),
    20: ("保留", False),
    21: ("保留", False),
    22: ("DCDC开关机状态(0开机/1关机)", False),
    23: ("模块限功率", True),
    24: ("温度限功率", True),
    25: ("交流限功率", True),
    26: ("保留", False),
    27: ("风扇故障", True),
    28: ("DCDC短路", True),
    29: ("保留", False),
    30: ("DCDC过温", True),
    31: ("DCDC输出过压", True),
}

STATUS_STATE_BIT = 22  # 开关机状态位

# 状态位语义（用于模拟从站/界面判断）
STATUS_BIT_DETECT_ERROR = 4   # 输入模式检测错误 / 空余相带电
STATUS_BIT_MODE_MISMATCH = 5  # 下发输入模式与实际工作模式不匹配
STATUS_BIT_OVP = 31           # DCDC 输出过压
STATUS_BIT_SHORT = 28         # DCDC 短路

INPUT_MODE_AC = 0x01
INPUT_MODE_DC = 0x02

# 读取当前输入工作模式(0x4B) 取值说明
INPUT_WORK_MODES = {
    0x01: "单相交流",
    0x02: "直流",
    0x03: "三相交流",
    0x05: "模式不匹配(相序错误)",
}

# 实际接线类型（模拟从站内部用）
LINE_SINGLE_PHASE = 0x01
LINE_DC = 0x02
LINE_THREE_PHASE = 0x03

# 地址分配方式(0x1F) 取值
ADDR_MODE_AUTO = 0x00000000
ADDR_MODE_DIP = 0x00010000

# 开关机(0x30) 取值
POWER_ON = 0x00000000
POWER_OFF = 0x00010000

# 复位命令(0x31 / 0x44) 取值
OVP_RESET_VALUE = 0x00010000
SHORT_RESET_VALUE = 0x00010000

# 输出过压保护关联(0x3E) 取值
OVP_RELATED_ALLOW = 0x00000000
OVP_RELATED_DENY = 0x00010000

# 海拔设置范围
ALTITUDE_MIN = 1000
ALTITUDE_MAX = 5000

# 扩展遥测寄存器（选中模块时补读，表1 完整覆盖）
EXT_TELEMETRY_REGS = [0x0004, 0x0010, 0x000B, 0x0008, 0x000A,
                      0x000C, 0x000D, 0x000E]
# 扩展遥测中为浮点的寄存器
EXT_TELEMETRY_FLOAT = {0x0004, 0x0010, 0x000B, 0x0008, 0x000A,
                       0x000C, 0x000D, 0x000E}


def reg_name(reg: int) -> str:
    info = REGISTERS.get(reg)
    return info[0] if info else f"未知寄存器0x{reg:04X}"


def reg_type(reg: int) -> str:
    info = REGISTERS.get(reg)
    return info[1] if info else "int"


def fault_list(status: int) -> list:
    """从 32 位状态字中解出所有已置位的故障名称（不含保留位与开关机状态位）。"""
    out = []
    for bit, (name, is_fault) in STATUS_BITS.items():
        if bit == STATUS_STATE_BIT:
            continue
        if status & (1 << bit):
            out.append(name)
    return out


def is_power_on(status: int) -> bool:
    """bit22: 0=开机, 1=关机。"""
    return not bool(status & (1 << STATUS_STATE_BIT))


def status_bit(status: int, bit: int) -> bool:
    return bool(status & (1 << bit))


def input_mode_mismatch(status: int) -> bool:
    """bit5：下发输入模式与实际工作模式不匹配。"""
    return status_bit(status, STATUS_BIT_MODE_MISMATCH)


def input_detect_error(status: int) -> bool:
    """bit4：输入模式检测错误 / 空余相带电。"""
    return status_bit(status, STATUS_BIT_DETECT_ERROR)


def decode_status(status: int) -> str:
    """把状态字解成可读文本，用于详细面板（首位为开关机状态）。"""
    parts = ["开机" if is_power_on(status) else "关机"]
    for bit in sorted(STATUS_BITS):
        name, _ = STATUS_BITS[bit]
        if bit == STATUS_STATE_BIT or name == "保留":
            continue
        if status & (1 << bit):
            parts.append(name)
    return "；".join(parts)