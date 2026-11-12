# -*- coding: utf-8 -*-
"""PK9015 电流采集模块 寄存器表与工程量换算。

依据：从 PK 系列测试软件 PK-TEST(1).exe 反汇编反推的通讯协议
（见 F:/模型/6aa36ea09cf4429927b10267/PK9015_通讯协议说明.md）。

设备是「12 路电流采集模块」（输入通道 I0~I11），
**不是** PK6011R 的单相电参数模块、也不是 PK9018B 的热电阻温度模块。

寄存器表（功能码 03H 读 / 06H 写，地址无偏移）：
------------------------------------------------------------
寄存器   内容            属性      换算
0x0000   ADDR/BPS       03读/06写  高 8 位=模块地址(01~F7H)，低 8 位=波特率码(03~07H)
0x0001   （保留）        -         -
0x0002   （保留）        -         -
0x0003   通道0 电流      03读  Uint16  实际电流 = raw/10000 × 量程系数
0x0004   通道1 电流      03读  Uint16  同上
0x0005   通道2 电流      03读  Uint16  同上
0x0006   通道3 电流      03读  Uint16  同上
0x0007   通道4 电流      03读  Uint16  同上
0x0008   通道5 电流      03读  Uint16  同上
0x0009   通道6 电流      03读  Uint16  同上
0x000A   通道7 电流      03读  Uint16  同上
0x000B   通道8 电流      03读  Uint16  同上
0x000C   通道9 电流      03读  Uint16  同上
0x000D   通道10 电流     03读  Uint16  同上
0x000E   通道11 电流     03读  Uint16  同上
0x02BE   量程设置       03读/06写  0=0-20mA、1=4-20mA、2=0-10V

电流换算（反汇编确认）：
    原始数据为 16 位无符号整数，但有效量程为「量程万分比」：raw = 0~10000 对应 0~100% 量程；
    实际电流 = raw / 10000 × 量程系数（常量 10000.0 = 0x461C4000）。
    0-20mA 量程：raw=10000 → 20.00mA（raw/10000×20）。
    4-20mA 量程：实际 = 4 + raw/10000 × 16（mA），raw=10000 → 20.00mA。
    （软件 resourcestring 表内 16.0 / 4.0 常量对应 4-20mA 的跨度与偏移。）
"""

from __future__ import annotations

# ------------------------------------------------------------ 寄存器地址

REG_ADDR_BPS = 0x0000      # 地址(高 8 位) + 波特率码(低 8 位)
REG_I0 = 0x0003            # 通道 0 电流（12 路连续 0x0003~0x000E）
CHANNEL_COUNT = 12
REG_RANGE = 0x02BE         # 量程设置

# 读电流起始地址与数量（一条报文读完全部 12 路）
READ_START = REG_I0
READ_COUNT = CHANNEL_COUNT

# 波特率码（写寄存器 0x0000 低字节）
BAUD_CODES = {1200: 0x03, 2400: 0x04, 4800: 0x05, 9600: 0x06, 19200: 0x07}
BAUD_BY_CODE = {v: k for k, v in BAUD_CODES.items()}

# 量程选择（写 0x02BE 的值）
RANGE_0_20MA = 0           # 0-20mA
RANGE_4_20MA = 1           # 4-20mA
RANGE_0_10V = 2            # 0-10V（PK9015A 等变体）

RANGE_LABELS = {
    RANGE_0_20MA: "0-20mA",
    RANGE_4_20MA: "4-20mA",
    RANGE_0_10V: "0-10V",
}

# 电流量程系数（mA），用于换算显示
RANGE_SPAN_MA = {
    RANGE_0_20MA: 20.0,
    RANGE_4_20MA: 16.0,   # 4-20mA 跨度 16mA
    RANGE_0_10V: 20.0,    # 0-10V 电压模式按 0-20mA 满量程映射显示
}

RANGE_OFFSET_MA = {
    RANGE_0_20MA: 0.0,
    RANGE_4_20MA: 4.0,
    RANGE_0_10V: 0.0,
}

# 电流换算分母（反汇编常量 10000.0）
CURRENT_SCALE = 10000.0


def raw_to_current_ma(raw: int, range_code: int = RANGE_0_20MA) -> float:
    """原始值(16 位无符号) → 电流(mA)。

    0-20mA：实际 = raw/10000 × 20（mA）；
    4-20mA：实际 = 4 + raw/10000 × 16（mA）。
    """
    span = RANGE_SPAN_MA.get(range_code, 20.0)
    offset = RANGE_OFFSET_MA.get(range_code, 0.0)
    return offset + (raw & 0xFFFF) / CURRENT_SCALE * span


def raw_to_current_a(raw: int, range_code: int = RANGE_0_20MA) -> float:
    """原始值 → 电流(A)。"""
    return raw_to_current_ma(raw, range_code) / 1000.0


# ------------------------------------------------------------ 描述表（供 UI 提示）

REGISTER_NOTES = (
    "12 路电流 I0~I11，寄存器 0x0003~0x000E，每路 16 位无符号，raw/10000 换算",
    "量程寄存器 0x02BE：0=0-20mA、1=4-20mA、2=0-10V",
    "寄存器 0x0000 高 8 位=模块地址、低 8 位=波特率码(03~07H)",
    "4-20mA 量程：实际电流 = 4 + raw/10000×16 (mA)",
)
