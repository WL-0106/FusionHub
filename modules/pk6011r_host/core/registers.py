# -*- coding: utf-8 -*-
"""PK6011R 单相电参数采集模块 寄存器表与工程量换算。

依据：供应商提供的《PK6011R 单相电参数采集模块使用说明书》。

设备是「单相电参数采集模块」（一路电压 + 一路电流 + 功率/功率因数/频率/电能），
**不是 12 路电流模块**。

寄存器表（功能码 03H 读，地址无偏移 = PLC/组态地址 - 40001）：
------------------------------------------------------------
寄存器  PLC地址   内容        属性        换算
0       40001    U0(高)/I0(低) 03读  Byte  电压量程=高字节*2 V；电流量程=低字节 A
1       40002    UBB(高)/IBB(低) 03读/06写 Byte  电压/电流变比，默认 1
2       40003    电压 U       03读  Uint16  实际电压=raw/10*UBB  V
3       40004    电流 I       03读  Uint16  实际电流=raw/1000*IBB  A
4       40005    有功功率 P   03读  int16   实际=raw/10*UBB*IBB  W
5       40006    无功功率 Q   03读  int16   实际=raw/10*UBB*IBB  var
6       40007    功率因数 PF  03读  int16   实际=raw/10000
7       40008    视在功率 S   03读  Uint16  实际=raw/10*UBB*IBB  VA
8       40009    频率 F       03读  Uint16  实际=raw/100  Hz
9~10    40010~11 正向有功电能 03读  Uint32  实际=raw/100*UBB*IBB  kWh
11~12   40012~13 反向有功电能 03读  Uint32  同上 kWh
13~14   40014~15 正向无功电能 03读  Uint32  同上 kvarh
15~16   40016~17 反向无功电能 03读  Uint32  同上 kvarh

功能码 06H 写：
   寄存器 0 = 地址+波特率：高字节=新地址(01~F7)，低字节=波特率码(3~7)
   寄存器 1 = 电压变比+电流变比：高字节=UBB，低字节=IBB

注意事项（手册原文）：
   模块电流量程基准为 5A，比如电流 100A 则 IBB = 100A/5A = 20。
   实际计算时电流、功率、电能都要 ×IBB×UBB。
"""

from __future__ import annotations

# ------------------------------------------------------------ 寄存器地址（PLC 地址 = 寄存器 + 40001）

REG_RANGE = 0x0000       # U0(高字节，×2=V) / I0(低字节，A)
REG_RATIO = 0x0001       # UBB(高) / IBB(低)，默认 1
REG_U = 0x0002           # 电压
REG_I = 0x0003           # 电流
REG_P = 0x0004           # 有功功率
REG_Q = 0x0005           # 无功功率
REG_PF = 0x0006          # 功率因数
REG_S = 0x0007           # 视在功率
REG_F = 0x0008           # 频率
REG_WH_POS = 0x0009      # 正向有功电能（高字 0x0009，低字 0x000A）
REG_WH_NEG = 0x000B      # 反向有功电能
REG_VARH_POS = 0x000D    # 正向无功电能
REG_VARH_NEG = 0x000F    # 反向无功电能

REG_COUNT = 17           # 0x0000 ~ 0x0010

# 波特率码（写寄存器 0 低字节）
BAUD_CODES = {1200: 0x03, 2400: 0x04, 4800: 0x05, 9600: 0x06, 19200: 0x07}
BAUD_BY_CODE = {v: k for k, v in BAUD_CODES.items()}

# 电流量程基准（手册注意事项：模块电流量程基准为 5A）
CURRENT_BASE = 5.0

# 面板标称（本机铭牌 AC50A/25mA，CT 变比 2000:1）
NOMINAL_CURRENT_RANGE = 50.0

# 电压量程预设（相电压）
VOLTAGE_RANGES = (60, 100, 250, 400, 500)
# 电流量程预设
CURRENT_RANGES = (1, 5, 10, 50, 100)


def raw_to_voltage(raw: int, ubb: float = 1.0) -> float:
    """电压：实际 = raw/10 × UBB（V）。"""
    return raw / 10.0 * ubb


def raw_to_current(raw: int, ibb: float = 1.0) -> float:
    """电流：实际 = raw/1000 × IBB（A）。"""
    return raw / 1000.0 * ibb


def raw_to_power(raw: int, ubb: float = 1.0, ibb: float = 1.0) -> float:
    """有功/无功功率：实际 = raw/10 × UBB × IBB（W/var）。raw 为 int16 有符号。"""
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / 10.0 * ubb * ibb


def raw_to_pf(raw: int) -> float:
    """功率因数：实际 = raw/10000。raw 为 int16。"""
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / 10000.0


def raw_to_freq(raw: int) -> float:
    """频率：实际 = raw/100（Hz）。"""
    return raw / 100.0


def raw_to_energy(hi: int, lo: int, ubb: float = 1.0, ibb: float = 1.0) -> float:
    """电能（32 位）：value = 高字<<16 + 低字，实际 = value/100 × UBB × IBB（kWh/kvarh）。"""
    value = (hi << 16) | lo
    return value / 100.0 * ubb * ibb


def ibb_from_range(current_range: float) -> float:
    """由电流量程求 IBB：IBB = 量程/5（手册注意事项）。"""
    return current_range / CURRENT_BASE


# ------------------------------------------------------------ 描述表（供 UI 提示）

REGISTER_NOTES = (
    "电流量程基准 5A：50A 量程 → IBB=10，实际电流 = raw/1000 × IBB",
    "寄存器 0 高字节=电压量程(×2 V)，低字节=电流量程(A)",
    "寄存器 1 高字节=电压变比 UBB，低字节=电流变比 IBB，默认均 1",
    "电能/功率/电流计算都要 ×UBB×IBB",
)
