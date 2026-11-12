"""IT8500 系列电子负载 —— 帧格式通讯协议实现。

依据《IT8500系列 编程与语法指南 V3.0》:
  * 帧长固定 26 字节: [AA][地址][命令字][22 字节数据区][校验]
  * 校验码 = 前 25 字节累加和的低 8 位
  * 多字节数据一律低字节在前 (little-endian)
  * 缩放: 电压 1=1mV, 电流 1=0.1mA, 功率 1=1mW, 电阻 1=1mΩ,
         动态/LIST 时间 1=0.1ms, 定时器 1=1s
"""
from __future__ import annotations

from dataclasses import dataclass

SYNC = 0xAA
FRAME_LEN = 26
HEADER_LEN = 3          # 同步头+地址+命令字
DATA_LEN = FRAME_LEN - HEADER_LEN - 1   # 22 字节信息内容

# ---------------------------------------------------------------- 命令字

class Cmd:
    """协议命令字一览 (set=设置, get=读取)。"""
    CTRL_MODE_SET = 0x20          # 0 面板 / 1 远程
    INPUT_SET = 0x21              # 0 OFF / 1 ON
    OVP_SET, OVP_GET = 0x22, 0x23
    OCP_SET, OCP_GET = 0x24, 0x25
    OPP_SET, OPP_GET = 0x26, 0x27
    LOAD_MODE_SET, LOAD_MODE_GET = 0x28, 0x29   # 0CC 1CV 2CW 3CR
    CC_SET, CC_GET = 0x2A, 0x2B
    CV_SET, CV_GET = 0x2C, 0x2D
    CW_SET, CW_GET = 0x2E, 0x2F
    CR_SET, CR_GET = 0x30, 0x31
    PULLON_SET, PULLON_GET = 0x10, 0x11         # 拉载电压
    RELEASE_SET, RELEASE_GET = 0x12, 0x13       # 卸载电压 (0x12 与校验命令同码)
    DYN_CC_SET, DYN_CC_GET = 0x32, 0x33
    DYN_CV_SET, DYN_CV_GET = 0x34, 0x35
    DYN_CW_SET, DYN_CW_GET = 0x36, 0x37
    DYN_CR_SET, DYN_CR_GET = 0x38, 0x39
    LIST_MODE_SET, LIST_MODE_GET = 0x3A, 0x3B
    LIST_LOOP_SET, LIST_LOOP_GET = 0x3C, 0x3D
    LIST_STEPS_SET, LIST_STEPS_GET = 0x3E, 0x3F
    LIST_STEP_SET, LIST_STEP_GET = 0x40, 0x41    # 电流步; 42/43 电压, 44/45 功率, 46/47 电阻
    LIST_FILE_SET, LIST_FILE_GET = 0x48, 0x49
    LIST_PART_SET, LIST_PART_GET = 0x4A, 0x4B
    LIST_SAVE, LIST_RECALL = 0x4C, 0x4D
    BAT_MIN_SET, BAT_MIN_GET = 0x4E, 0x4F       # CV 模式最小电压 (电池测试)
    TIMER_SET, TIMER_GET = 0x50, 0x51           # 定时器时间 (秒)
    TIMER_EN_SET, TIMER_EN_GET = 0x52, 0x53
    ADDR_SET = 0x54
    LOCAL_KEY_SET = 0x55
    SENSE_SET, SENSE_GET = 0x56, 0x57
    TRIG_SET, TRIG_GET = 0x58, 0x59
    TRIG_BUS = 0x5A
    SETUP_SAVE, SETUP_RECALL = 0x5B, 0x5C
    WORK_MODE_SET, WORK_MODE_GET = 0x5D, 0x5E    # 0FIXED 1SHORT 2TRANS 3LIST 4BATT
    MEASURE = 0x5F
    IDENTITY = 0x6A
    BARCODE = 0x6B
    CHECK = 0x12                                 # 校验/应答命令

# 各动态参数组 / LIST 步的成对命令字
DYN_CMDS = {"CC": (Cmd.DYN_CC_SET, Cmd.DYN_CC_GET),
            "CV": (Cmd.DYN_CV_SET, Cmd.DYN_CV_GET),
            "CW": (Cmd.DYN_CW_SET, Cmd.DYN_CW_GET),
            "CR": (Cmd.DYN_CR_SET, Cmd.DYN_CR_GET)}
LIST_STEP_CMDS = {"CC": (0x40, 0x41), "CV": (0x42, 0x43),
                  "CW": (0x44, 0x45), "CR": (0x46, 0x47)}

# 模式名称与编号
LOAD_MODES = {0: "CC", 1: "CV", 2: "CW", 3: "CR"}
MODE_TO_ID = {v: k for k, v in LOAD_MODES.items()}
WORK_MODES = {0: "FIXED", 1: "SHORT", 2: "TRANSITION", 3: "LIST", 4: "BATTERY"}

# 5FH 操作状态寄存器位
OP_STATUS_BITS = {0: "CAL", 1: "WTG", 2: "REM", 3: "OUT",
                  4: "LOCAL", 5: "SENSE", 6: "LOT"}
# 5FH 查询状态寄存器位 (高 6 位保留)
QUERY_STATUS_BITS = {0: "RV", 1: "OV", 2: "OC", 3: "OP", 4: "OH", 5: "SV",
                     6: "CC", 7: "CV", 8: "CP", 9: "CR"}
FAULT_FLAGS = {"RV", "OV", "OC", "OP", "OH"}       # 故障类
RUN_FLAGS = {"CC", "CV", "CP", "CR"}               # 稳压/稳流状态类

# 设置命令应答状态码 (12H 校验命令)
STATUS_OK = 0x80
STATUS_CODES = {
    0x80: "执行成功",
    0x90: "校验和错误",
    0xA0: "参数错误或溢出",
    0xB0: "命令不能执行 — 设备处于面板(PANEL)模式时需先由 20H 进入远程模式"
          " (本软件会在首次写入前自动下发), 或设备处于校准状态",
    0xC0: "命令无效",
}


class ProtocolError(Exception):
    """帧格式/校验错误。"""


class DeviceError(Exception):
    """设备返回非成功状态。"""

    def __init__(self, code: int):
        self.code = code
        super().__init__(f"设备返回错误 {code:02X}H: {STATUS_CODES.get(code, '未知错误')}")


# ---------------------------------------------------------------- 基础编解码

def build_frame(addr: int, cmd: int, data: bytes | bytearray = b"") -> bytes:
    if not 0 <= addr <= 0xFE:
        raise ValueError(f"地址越界: {addr}")
    if not 0 <= cmd <= 0xFF:
        raise ValueError(f"命令字越界: {cmd}")
    payload = bytes(data)
    if len(payload) > DATA_LEN:
        raise ValueError(f"数据区超长: {len(payload)} > {DATA_LEN}")
    body = bytes([SYNC, addr, cmd]) + payload.ljust(DATA_LEN, b"\x00")
    return body + bytes([sum(body) & 0xFF])


def parse_frame(raw: bytes) -> "Frame":
    if len(raw) != FRAME_LEN:
        raise ProtocolError(f"帧长度错误: {len(raw)} (应为 {FRAME_LEN})")
    if raw[0] != SYNC:
        raise ProtocolError(f"同步头错误: {raw[0]:02X}H")
    if (sum(raw[:FRAME_LEN - 1]) & 0xFF) != raw[-1]:
        raise ProtocolError("校验码错误")
    return Frame(addr=raw[1], cmd=raw[2], data=raw[3:FRAME_LEN - 1])


@dataclass(frozen=True)
class Frame:
    addr: int
    cmd: int
    data: bytes  # 22 字节

    @property
    def status(self) -> int:
        """12H 应答帧的状态码。"""
        return self.data[0]

    def u32(self, offset: int = 0) -> int:
        return int.from_bytes(self.data[offset:offset + 4], "little")

    def u16(self, offset: int = 0) -> int:
        return int.from_bytes(self.data[offset:offset + 2], "little")

    def u8(self, offset: int = 0) -> int:
        return self.data[offset]


def u32le(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"u32 越界: {value}")
    return value.to_bytes(4, "little")


def u16le(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"u16 越界: {value}")
    return value.to_bytes(2, "little")


def u32_from(data: bytes) -> int:
    """从字节串起始处读取一个 LE u32。"""
    return int.from_bytes(data[0:4], "little")


# ---------------------------------------------------------------- 物理量缩放

def volts_to_raw(v: float) -> int:
    """V -> mV (1 = 1mV)。"""
    return int(round(v * 1000.0))


def raw_to_volts(r: int) -> float:
    return r / 1000.0


def amps_to_raw(a: float) -> int:
    """A -> 0.1mA (1 = 0.1mA)。"""
    return int(round(a * 10000.0))


def raw_to_amps(r: int) -> float:
    return r / 10000.0


def watts_to_raw(w: float) -> int:
    """W -> mW (1 = 1mW)。"""
    return int(round(w * 1000.0))


def raw_to_watts(r: int) -> float:
    return r / 1000.0


def ohms_to_raw(ohm: float) -> int:
    """Ω -> mΩ (1 = 1mΩ)。"""
    return int(round(ohm * 1000.0))


def raw_to_ohms(r: int) -> float:
    return r / 1000.0


def ms_to_raw(ms: float) -> int:
    """ms -> 0.1ms (1 = 0.1ms)。"""
    return int(round(ms * 10.0))


def raw_to_ms(r: int) -> float:
    return r / 10.0


# 各单位的 (转 raw 函数, 自 raw 还原函数, 显示单位)
UNIT_FUNCS = {
    "V": (volts_to_raw, raw_to_volts, "V"),
    "A": (amps_to_raw, raw_to_amps, "A"),
    "W": (watts_to_raw, raw_to_watts, "W"),
    "Ω": (ohms_to_raw, raw_to_ohms, "Ω"),
    "ms": (ms_to_raw, raw_to_ms, "ms"),
}


def value_to_raw(value: float, unit: str) -> int:
    return UNIT_FUNCS[unit][0](value)


def raw_to_value(raw: int, unit: str) -> float:
    return UNIT_FUNCS[unit][1](raw)


# ---------------------------------------------------------------- 负载模式

def encode_load_mode(mode: int | str) -> bytes:
    if isinstance(mode, str):
        mode = MODE_TO_ID[mode.upper()]
    if mode not in LOAD_MODES:
        raise ValueError(f"负载模式越界: {mode}")
    return bytes([mode])


def decode_load_mode(data: bytes) -> str:
    return LOAD_MODES.get(data[0], f"未知({data[0]})")


# ---------------------------------------------------------------- 5FH 测量

@dataclass(frozen=True)
class Measurement:
    voltage: float      # V
    current: float      # A
    power: float        # W
    op_status: int      # 操作状态寄存器
    query_status: int   # 查询状态寄存器

    @property
    def op_flags(self) -> set[str]:
        return {n for b, n in OP_STATUS_BITS.items() if self.op_status >> b & 1}

    @property
    def query_flags(self) -> set[str]:
        return {n for b, n in QUERY_STATUS_BITS.items() if self.query_status >> b & 1}

    @property
    def faults(self) -> set[str]:
        return self.query_flags & FAULT_FLAGS

    @property
    def is_output_on(self) -> bool:
        return "OUT" in self.op_flags

    @property
    def is_remote(self) -> bool:
        return "REM" in self.op_flags


def parse_measurement(data: bytes) -> Measurement:
    if len(data) < 15:
        raise ProtocolError(f"测量数据过短: {len(data)}")
    return Measurement(
        voltage=raw_to_volts(int.from_bytes(data[0:4], "little")),
        current=raw_to_amps(int.from_bytes(data[4:8], "little")),
        power=raw_to_watts(int.from_bytes(data[8:12], "little")),
        op_status=data[12],
        query_status=int.from_bytes(data[13:15], "little"),
    )


# ---------------------------------------------------------------- 6AH 设备信息

@dataclass(frozen=True)
class Identity:
    model: str
    serial: str
    version: str


def parse_identity(data: bytes) -> Identity:
    model = data[0:5].decode("ascii", errors="ignore").strip("\x00 ").strip()
    ver_high, ver_low = data[6], data[5]          # 第九字节低(BCD) 第十字节高(BCD)
    serial = data[7:17].decode("ascii", errors="ignore").strip("\x00 ").strip()
    return Identity(model=model, serial=serial,
                    version=f"V{ver_high:X}.{ver_low:02X}")


def parse_barcode(data: bytes) -> str:
    return data[0:19].decode("ascii", errors="ignore").strip("\x00 ").strip()


# ---------------------------------------------------------------- 动态参数

@dataclass(frozen=True)
class DynamicParams:
    value_a: float      # 单位随模式 (V/A/W/Ω)
    time_a_ms: float
    value_b: float
    time_b_ms: float
    dyn_mode: int       # 0 连续 1 脉冲 2 翻转

    @staticmethod
    def dyn_mode_name(mode: int) -> str:
        return {0: "连续", 1: "脉冲", 2: "翻转"}.get(mode, f"未知({mode})")


def encode_dynamic(params: DynamicParams, unit: str) -> bytes:
    to_raw = UNIT_FUNCS[unit][0]
    return (u32le(to_raw(params.value_a)) + u16le(ms_to_raw(params.time_a_ms))
            + u32le(to_raw(params.value_b)) + u16le(ms_to_raw(params.time_b_ms))
            + bytes([params.dyn_mode]))


def decode_dynamic(data: bytes, unit: str) -> DynamicParams:
    from_raw = UNIT_FUNCS[unit][1]
    return DynamicParams(
        value_a=from_raw(int.from_bytes(data[0:4], "little")),
        time_a_ms=raw_to_ms(int.from_bytes(data[4:6], "little")),
        value_b=from_raw(int.from_bytes(data[6:10], "little")),
        time_b_ms=raw_to_ms(int.from_bytes(data[10:12], "little")),
        dyn_mode=data[12],
    )


# ---------------------------------------------------------------- LIST 步

@dataclass(frozen=True)
class ListStep:
    index: int          # 0 起
    value: float        # 单位随模式
    time_ms: float


def encode_list_step(step: ListStep, unit: str) -> bytes:
    if not 0 <= step.index <= 0xFFFF:
        raise ValueError(f"步号越界: {step.index}")
    to_raw = UNIT_FUNCS[unit][0]
    return u16le(step.index) + u32le(to_raw(step.value)) + u16le(ms_to_raw(step.time_ms))


def decode_list_step(data: bytes, unit: str) -> ListStep:
    from_raw = UNIT_FUNCS[unit][1]
    return ListStep(
        index=int.from_bytes(data[0:2], "little"),
        value=from_raw(int.from_bytes(data[2:6], "little")),
        time_ms=raw_to_ms(int.from_bytes(data[6:8], "little")),
    )


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)
