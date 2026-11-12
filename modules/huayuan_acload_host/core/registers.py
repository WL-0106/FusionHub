# -*- coding: utf-8 -*-
"""
华源交流回馈式负载 —— 寄存器表（依据《交流回馈式负载 MODBUS 通讯协议 V1.4》2024-10-30）

单位是这份协议最大的坑，务必对照下表：

    输出功率 / 设定功率 / 各通道功率   0.1 W     写入 raw = 瓦数 × 10
    输出电流 / 设定电流 / 各通道电流   0.001 A   写入 raw = 安培 × 1000
    输出电压 / 各通道电压              0.001 V   读出值 ÷ 1000
    功率读出                           0.1 W     读出值 ÷ 10

    注意：功率单位是 0.1W，不是 0.0001kW，也不是 W。写成 W 会小 10 倍。

手册中两处明显的印刷笔误，本表按"地址连续 + 通道递增"的规律修正，并在 note 中标注：
    1) 10 通道输出电流：手册印为 0xAC（与 9 通道重复），实为 0xAE / 0xAF。
    2) 13/14/15 通道输出电流：手册的通道名分别印成了 12/13/14，实为 13/14/15。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# 标度（scale = 1 raw 对应的工程量）
# --------------------------------------------------------------------------

SCALE_POWER = 0.1        # W  / raw
SCALE_CURRENT = 0.001    # A  / raw
SCALE_VOLTAGE = 0.001    # V  / raw

# 通道数量：1~3 为 A/B/C 相，4~15 为扩展通道
CHANNEL_COUNT = 15
PHASE_CHANNELS = (1, 2, 3)
PHASE_NAMES = {1: "A相", 2: "B相", 3: "C相"}


def p2raw(watt: float) -> int:
    return int(round(watt / SCALE_POWER))


def a2raw(amp: float) -> int:
    return int(round(amp / SCALE_CURRENT))


def v2raw(volt: float) -> int:
    return int(round(volt / SCALE_VOLTAGE))


# --------------------------------------------------------------------------
# 关键地址常量
# --------------------------------------------------------------------------

ADDR_OUTPUT_CTRL = 0x20      # 输出控制：0 停止 / 1 输出
ADDR_CLEAR_FAULT = 0x28      # 清除故障：写 1
ADDR_POWER_TOTAL = 0x38      # 设置功率（32 位，0x38 高字 0x39 低字）
ADDR_MODE_OP = 0x3C          # 操作模式：0 三相统调 / 1 三相独立 / 2 单相并联
ADDR_MODE_CTRL = 0x3D        # 控制模式：0 功率模式 / 1 电流模式
ADDR_CURRENT_TOTAL = 0x3E    # 设置电流（32 位）
ADDR_CH_POWER_BASE = 0x40    # 通道 1 功率，通道 n = 0x40 + 2*(n-1)，到 0x5D

ADDR_STATUS_LOW = 0x60       # 输出状态低字 bit15~bit0
ADDR_VERSION = 0x61          # 版本号（104 → V1.4）
ADDR_STATUS_HIGH = 0x62      # 输出状态高字 bit31~bit16
ADDR_V_BASE = 0x63           # A/B/C 相电压，各 2 寄存器：0x63/0x65/0x67
ADDR_I_BASE = 0x69           # A/B/C 相电流，各 2 寄存器：0x69/0x6B/0x6D
ADDR_P_TOTAL = 0x7C          # 输出总功率（32 位）
ADDR_FAULT_1 = 0x7E          # 故障状态 1：bit47~bit32
ADDR_FAULT_2 = 0x7F          # 故障状态 2：bit31~bit16
ADDR_FAULT_3 = 0x80          # 故障状态 3：bit15~bit0
ADDR_SERIAL = 0x86           # 序列号（32 位，高位在前）

ADDR_CH4_V = 0x90            # 4~12 通道电压，各 2 寄存器，到 0xA1
ADDR_CH4_I = 0xA2            # 4~12 通道电流，各 2 寄存器，到 0xB3
ADDR_CH1_P = 0xB4            # 1~12 通道输出功率，各 2 寄存器，到 0xCB
ADDR_CH13_V = 0xCC           # 13~15 通道电压，0xCC/0xCE/0xD0
ADDR_CH13_I = 0xD2           # 13~15 通道电流，0xD2/0xD4/0xD6
ADDR_CH13_P = 0xD8           # 13~15 通道功率，0xD8/0xDA/0xDC

ADDR_CH1_I_SET = 0xE0        # 通道 1~3（A/B/C 相）电流设定：0xE0/0xE2/0xE4

# 批量读取块（尽量把连续只读寄存器合并成一条报文）
BLOCK_STATUS_START = 0x60
BLOCK_STATUS_COUNT = 0x80 - 0x60 + 1          # 0x60~0x80 共 33 个
BLOCK_CH_A_START = 0x90
BLOCK_CH_A_COUNT = 0xB3 - 0x90 + 1            # 4~12 通道电压电流，36 个
BLOCK_CH_B_START = 0xB4
BLOCK_CH_B_COUNT = 0xDD - 0xB4 + 1            # 1~12 通道功率 + 13~15 全套，42 个


def ch_power_addr(ch: int) -> int:
    """通道 n 的功率设定地址（32 位）。"""
    return ADDR_CH_POWER_BASE + 2 * (ch - 1)


def phase_i_set_addr(ch: int) -> int:
    """通道 1~3 的电流设定地址（32 位）。"""
    if ch not in PHASE_CHANNELS:
        raise ValueError("电流设定仅支持通道 1~3（A/B/C 相）")
    return ADDR_CH1_I_SET + 2 * (ch - 1)


# --------------------------------------------------------------------------
# 枚举 / 位定义
# --------------------------------------------------------------------------

MODE_OP_NAMES = {0: "三相统调", 1: "三相独立", 2: "单相并联"}
MODE_CTRL_NAMES = {0: "功率模式", 1: "电流模式"}

# 输出状态码（0x60 低字 + 0x62 高字 合成 32 位）
ST_RUNNING_BIT = 0
ST_FAULT_BIT = 16
ST_CTRL_MODE_BIT = 17
ST_OP_MODE_LOW_BIT = 18      # bit19:bit18 两位组成操作模式
ST_OP_MODE_MASK = 0x03

# 故障代码：bit0~bit7 位于 0x80
FAULT_BITS: Dict[int, str] = {
    0: "电流过流",
    1: "IGBT 过流",
    2: "母线过压",
    3: "波形数据错误",
    4: "功率过载",
    5: "输出过流",
    6: "过温保护",
    7: "超过额定电压",
}


def decode_version(raw: int) -> str:
    """104 → 'V1.4'。"""
    if raw <= 0:
        return "—"
    if raw >= 100:
        return "V%d.%d" % (raw // 100, raw % 100)
    return "V%s" % raw


# --------------------------------------------------------------------------
# 寄存器表（用于自动生成"手动调试"页和文档，也是写前校验的唯一依据）
# --------------------------------------------------------------------------

@dataclass
class Register:
    addr: int
    name: str
    dtype: str                 # u16 / u32
    access: str                # R / W / RW
    unit: str = ""
    scale: float = 1.0
    rng: Optional[Tuple[int, int]] = None     # raw 值范围
    enum: Optional[Dict[int, str]] = None
    funcs: str = ""
    note: str = ""

    @property
    def is_write(self) -> bool:
        return "W" in self.access

    @property
    def is_read(self) -> bool:
        return "R" in self.access


REGISTER_TABLE: List[Register] = [
    # ---------------- 控制与设置 ----------------
    Register(ADDR_OUTPUT_CTRL, "输出控制", "u16", "RW", "", 1.0, (0, 1),
             {0: "关闭", 1: "输出"}, "03,06", "0 关闭；1 输出"),
    Register(ADDR_CLEAR_FAULT, "清除故障", "u16", "RW", "", 1.0, (0, 1),
             {0: "—", 1: "清除"}, "03,06", "写 1 清除故障，清除完成后自动复位为 0"),
    Register(ADDR_POWER_TOTAL, "设置功率", "u32", "RW", "W", SCALE_POWER, (0, 0xFFFFFFFF),
             None, "03,10", "仅用于单相 / 三相统调；单位 0.1W"),
    Register(ADDR_MODE_OP, "操作模式", "u16", "RW", "", 1.0, (0, 2), MODE_OP_NAMES,
             "03,06", "0 三相统调；1 三相独立；2 单相并联"),
    Register(ADDR_MODE_CTRL, "控制模式", "u16", "RW", "", 1.0, (0, 1), MODE_CTRL_NAMES,
             "03,06", "0 功率模式；1 电流模式"),
    Register(ADDR_CURRENT_TOTAL, "设置电流", "u32", "RW", "A", SCALE_CURRENT, (0, 0xFFFFFFFF),
             None, "03,10", "仅用于单相 / 三相统调；单位 0.001A"),
]

for _ch in range(1, CHANNEL_COUNT + 1):
    REGISTER_TABLE.append(Register(
        ch_power_addr(_ch), "设置通道%d功率" % _ch, "u32", "RW", "W", SCALE_POWER,
        (0, 0xFFFFFFFF), None, "03,06,10",
        "单位 0.1W" + ("（%s）" % PHASE_NAMES[_ch] if _ch in PHASE_NAMES else "")))

# ---------------- 电流设定（仅 A/B/C 相） ----------------
for _ch in PHASE_CHANNELS:
    REGISTER_TABLE.append(Register(
        phase_i_set_addr(_ch), "通道%d（%s）输出电流" % (_ch, PHASE_NAMES[_ch]),
        "u32", "RW", "A", SCALE_CURRENT, (0, 0xFFFFFFFF), None, "03,06,10", "单位 0.001A"))

# ---------------- 状态查询 ----------------
REGISTER_TABLE += [
    Register(ADDR_STATUS_LOW, "输出状态低字", "u16", "R", "", 1.0, None, None, "03",
             "bit15~bit0，见输出状态码"),
    Register(ADDR_VERSION, "版本号", "u16", "R", "", 1.0, None, None, "03", "104 → V1.4"),
    Register(ADDR_STATUS_HIGH, "输出状态高字", "u16", "R", "", 1.0, None, None, "03",
             "bit31~bit16，见输出状态码"),
    Register(ADDR_V_BASE, "A相输出电压", "u32", "R", "V", SCALE_VOLTAGE, None, None, "03", ""),
    Register(ADDR_V_BASE + 2, "B相输出电压", "u32", "R", "V", SCALE_VOLTAGE, None, None, "03", ""),
    Register(ADDR_V_BASE + 4, "C相输出电压", "u32", "R", "V", SCALE_VOLTAGE, None, None, "03", ""),
    Register(ADDR_I_BASE, "A相输出电流", "u32", "R", "A", SCALE_CURRENT, None, None, "03", ""),
    Register(ADDR_I_BASE + 2, "B相输出电流", "u32", "R", "A", SCALE_CURRENT, None, None, "03", ""),
    Register(ADDR_I_BASE + 4, "C相输出电流", "u32", "R", "A", SCALE_CURRENT, None, None, "03", ""),
    Register(ADDR_P_TOTAL, "输出总功率", "u32", "R", "W", SCALE_POWER, None, None, "03", ""),
    Register(ADDR_FAULT_1, "故障状态1", "u16", "R", "", 1.0, None, None, "03", "bit47~bit32"),
    Register(ADDR_FAULT_2, "故障状态2", "u16", "R", "", 1.0, None, None, "03", "bit31~bit16"),
    Register(ADDR_FAULT_3, "故障状态3", "u16", "R", "", 1.0, None, None, "03", "bit15~bit0"),
    Register(ADDR_SERIAL, "序列号", "u32", "R", "", 1.0, None, None, "03", "高位在前"),
]

# 4~12 通道电压 / 电流
for _ch in range(4, 13):
    REGISTER_TABLE.append(Register(ADDR_CH4_V + 2 * (_ch - 4), "%d通道输出电压" % _ch,
                                   "u32", "R", "V", SCALE_VOLTAGE, None, None, "03", ""))
for _ch in range(4, 13):
    REGISTER_TABLE.append(Register(ADDR_CH4_I + 2 * (_ch - 4), "%d通道输出电流" % _ch,
                                   "u32", "R", "A", SCALE_CURRENT, None, None, "03", ""))

# 1~12 通道功率
for _ch in range(1, 13):
    REGISTER_TABLE.append(Register(ADDR_CH1_P + 2 * (_ch - 1), "%d通道输出功率" % _ch,
                                   "u32", "R", "W", SCALE_POWER, None, None, "03", ""))

# 13~15 通道电压 / 电流 / 功率（手册通道名印错，此处已按地址顺序修正）
for _i, _ch in enumerate((13, 14, 15)):
    REGISTER_TABLE.append(Register(ADDR_CH13_V + 2 * _i, "%d通道输出电压" % _ch,
                                   "u32", "R", "V", SCALE_VOLTAGE, None, None, "03",
                                   "手册标注为 15/…，按地址顺序修正"))
for _i, _ch in enumerate((13, 14, 15)):
    REGISTER_TABLE.append(Register(ADDR_CH13_I + 2 * _i, "%d通道输出电流" % _ch,
                                   "u32", "R", "A", SCALE_CURRENT, None, None, "03",
                                   "手册通道名印为 12/13/14，按地址顺序修正"))
for _i, _ch in enumerate((13, 14, 15)):
    REGISTER_TABLE.append(Register(ADDR_CH13_P + 2 * _i, "%d通道输出功率" % _ch,
                                   "u32", "R", "W", SCALE_POWER, None, None, "03", ""))

REGISTER_TABLE.sort(key=lambda r: r.addr)

REG_BY_ADDR: Dict[int, Register] = {}
for _r in REGISTER_TABLE:
    REG_BY_ADDR.setdefault(_r.addr, _r)


def describe_addr(addr: int) -> str:
    """给一个寄存器地址，返回人话描述（用于手动调试页）。"""
    r = REG_BY_ADDR.get(addr)
    if r is not None:
        return r.name
    # 可能是 32 位量的低字
    prev = REG_BY_ADDR.get(addr - 1)
    if prev is not None and prev.dtype == "u32":
        return "%s（低字）" % prev.name
    return "未定义"


def fmt_value(reg: Optional[Register], raw: int) -> str:
    """把 raw 值按寄存器单位格式化成工程值。"""
    if reg is None:
        return "0x%04X" % raw
    if reg.enum and raw in reg.enum:
        return "%s (%d)" % (reg.enum[raw], raw)
    if reg.unit and reg.scale != 1.0:
        return "%.3f %s" % (raw * reg.scale, reg.unit)
    return str(raw)
