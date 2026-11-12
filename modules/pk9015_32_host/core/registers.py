# -*- coding: utf-8 -*-
"""PK9015-32 模拟量输入模块 寄存器表与工程量换算。

依据：PK9015-32 通讯协议说明（见 F:/模型/6aa36ea09cf4429927b10267/PK9015-32_通讯协议说明.md），
从 PK9015-32-Test.exe（PyInstaller + Python 3.10）反编译反推。

设备是「32 通道模拟量输入模块」，支持电流/电压两种输入类型（寄存器 0x0001 区分），
带 CT（电流互感器）变比换算。

寄存器表（功能码 03H 读 / 06H 写，地址无偏移）：
------------------------------------------------------------
寄存器   内容            属性        换算
0x0000   ADDR+BPS      03读/06写   高 8 位=模块地址，低 8 位=波特率码(03~07H)
0x0001   类型          03读       1=电流，其他=电压
0x0002   量程          03读       值 × 100 = 实际量程（50mA → 存 5000）
0x0003~0022  测量值    03读       32 通道数据（CH0=0x0003 ... CH31=0x0022），无符号 16 位
0x0023~  修正值        03读/06写  修正值（REG_CORR_START = 35 = 0x23）

数据换算（反编译确认）：
    二次侧电流 sec_ma = raw × 量程 / 10000   （mA）
    一次侧电流 pri_a  = sec_ma × CT一次 / CT二次 / 1000   （A）
    raw 为无符号 16 位（<H 大端解包）；量程默认 50mA，CT 变比默认 100:1。
    量程寄存器值 × 100 = 实际量程（50mA 存 5000），读回后 ÷ 100 得实际量程。
    若类型为电压，量程单位取 V，公式同理（raw × 量程 / 10000，单位 V）。
"""

from __future__ import annotations

# ------------------------------------------------------------ 寄存器地址

REG_ADDR_BPS = 0x0000      # 地址(高 8 位) + 波特率码(低 8 位)
REG_TYPE = 0x0001          # 类型：1=电流，其他=电压
REG_RANGE = 0x0002         # 量程（值 × 100 = 实际量程）
REG_DATA_START = 0x0003    # 32 通道数据起始
REG_CORR_START = 35        # 修正值起始（0x23）

CHANNEL_COUNT = 32

# 类型
TYPE_CURRENT = 1
TYPE_VOLTAGE = 0

# 默认量程（mA / V）
DEFAULT_RANGE = 50.0

# CT 变比默认（一次侧 / 二次侧）
DEFAULT_CT_PRI = 100
DEFAULT_CT_SEC = 1

# 波特率码
BAUD_CODES = {1200: 0x03, 2400: 0x04, 4800: 0x05, 9600: 0x06, 19200: 0x07}
BAUD_BY_CODE = {v: k for k, v in BAUD_CODES.items()}

# 换算分母
SCALE = 10000.0


def raw_to_secondary(raw: int, rng: float = DEFAULT_RANGE) -> float:
    """原始值(无符号 16 位) → 二次侧物理量（mA 或 V）。"""
    return (raw & 0xFFFF) * rng / SCALE


def secondary_to_primary(sec: float, ct_pri: int = DEFAULT_CT_PRI,
                         ct_sec: int = DEFAULT_CT_SEC) -> float:
    """二次侧(mA) → 一次侧(A)。"""
    if ct_sec <= 0:
        ct_sec = 1
    return sec * ct_pri / ct_sec / 1000.0


def raw_to_primary_a(raw: int, rng: float = DEFAULT_RANGE,
                     ct_pri: int = DEFAULT_CT_PRI, ct_sec: int = DEFAULT_CT_SEC) -> float:
    """原始值 → 一次侧电流(A)（电流类型）。"""
    sec = raw_to_secondary(raw, rng)
    return secondary_to_primary(sec, ct_pri, ct_sec)


# ------------------------------------------------------------ 描述表（供 UI 提示）

REGISTER_NOTES = (
    "32 通道模拟量输入 CH0~CH31，数据寄存器 0x0003~0x0022，每路 16 位无符号",
    "寄存器 0x0000=地址+波特率码、0x0001=类型(1电流/其他电压)、0x0002=量程(值×100)",
    "电流：二次侧 mA = raw×量程/10000，一次侧 A = 二次侧×CT一次/CT二次/1000",
    "修正值寄存器 0x0023~（REG_CORR_START=35）",
)
