# -*- coding: utf-8 -*-
"""信捷 XD/XL 系列软元件 → Modbus 地址映射。

地址表依据《XD、XL系列可编程控制器用户手册（基本指令篇）》第 6-2-3 节。
X/Y 为八进制编号；Modbus 地址超过 32767 时用十六进制（如 HD0 = H0A080）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DataType(str, Enum):
    COIL = "coil"                    # 01/05/0F  位 读写
    DISCRETE_INPUT = "discrete"      # 02        位 只读
    INPUT_REGISTER = "input_reg"     # 04        字 只读
    HOLDING_REGISTER = "holding"     # 03/06/10  字 读写


# 系列分组：Modbus 地址表一致
SERIES_COMPACT = ("XD1", "XD2", "XD3", "XD3E", "XL1", "XL3", "XL3E")
SERIES_STANDARD = (
    "XD5", "XDM", "XDC", "XD5E", "XDME",
    "XL5", "XL5E", "XL5N", "XL5H", "XLME",
)
SERIES_HIGH = ("XDH", "XLH")

ALL_SERIES = SERIES_COMPACT + SERIES_STANDARD + SERIES_HIGH


@dataclass(frozen=True)
class DeviceDef:
    """一种软元件的映射定义。"""
    prefix: str
    kind: DataType
    # Modbus 起始地址（十进制）
    base: int
    # 元件个数
    count: int
    # 点数是否按八进制编号（X/Y）
    octal: bool = False
    # 读写能力
    writable: bool = True


@dataclass(frozen=True)
class ResolvedDevice:
    """解析后的单个软元件。"""
    name: str                 # 如 "Y10"
    prefix: str               # 如 "Y"
    index: int                # 十进制点序（八进制已转换）
    modbus_addr: int          # Modbus 地址（十进制）
    kind: DataType
    writable: bool
    bit_in_word: Optional[int] = None  # 位软元件若打包成字时预留


# ---------------------------------------------------------------------------
# 八进制 I/O 编号
# ---------------------------------------------------------------------------

def parse_octal_point(text: str) -> int:
    """把八进制点号字符串转为十进制序号。

    手册：Y0→H6000, Y10→H6008, Y20→H6010（八进制）。
    """
    text = text.strip()
    if not text:
        raise ValueError("空的 I/O 编号")
    return int(text, 8)


def format_io_name(prefix: str, point_octal: str) -> str:
    return f"{prefix}{point_octal}"


# ---------------------------------------------------------------------------
# 各系列软元件表（本体，不含扩展模块；扩展见 expand 模块）
# ---------------------------------------------------------------------------

def _compact_defs() -> dict[str, DeviceDef]:
    # XD1/XD2/XD3/XD3E/XL1/XL3/XL3E
    return {
        "M":  DeviceDef("M",  DataType.COIL, 0, 8000, writable=True),
        "X":  DeviceDef("X",  DataType.COIL, 0x5000, 64, octal=True, writable=False),
        "Y":  DeviceDef("Y",  DataType.COIL, 0x6000, 64, octal=True, writable=True),
        "S":  DeviceDef("S",  DataType.COIL, 0x7000, 1024, writable=True),
        "SM": DeviceDef("SM", DataType.COIL, 0x9000, 2048, writable=True),
        "T":  DeviceDef("T",  DataType.COIL, 0xA000, 576, writable=False),
        "C":  DeviceDef("C",  DataType.COIL, 0xB000, 576, writable=False),
        "ET": DeviceDef("ET", DataType.COIL, 0xC000, 32, writable=True),
        "SEM": DeviceDef("SEM", DataType.COIL, 0xC080, 32, writable=True),
        "HM": DeviceDef("HM", DataType.COIL, 0xC100, 960, writable=True),
        "HS": DeviceDef("HS", DataType.COIL, 0xD900, 128, writable=True),
        "HT": DeviceDef("HT", DataType.COIL, 0xE100, 96, writable=True),
        "HC": DeviceDef("HC", DataType.COIL, 0xE500, 96, writable=True),
        "HSC": DeviceDef("HSC", DataType.COIL, 0xE900, 32, writable=True),
        # 字元件
        "D":   DeviceDef("D",   DataType.HOLDING_REGISTER, 0, 8000, writable=True),
        "ID":  DeviceDef("ID",  DataType.INPUT_REGISTER, 0x5000, 100, writable=False),
        "QD":  DeviceDef("QD",  DataType.HOLDING_REGISTER, 0x6000, 100, writable=True),
        "SD":  DeviceDef("SD",  DataType.HOLDING_REGISTER, 0x7000, 2048, writable=True),
        "TD":  DeviceDef("TD",  DataType.HOLDING_REGISTER, 0x8000, 576, writable=False),
        "CD":  DeviceDef("CD",  DataType.HOLDING_REGISTER, 0x9000, 576, writable=False),
        "ETD": DeviceDef("ETD", DataType.HOLDING_REGISTER, 0xA000, 32, writable=True),
        "HD":  DeviceDef("HD",  DataType.HOLDING_REGISTER, 0xA080, 1000, writable=True),
        "HSD": DeviceDef("HSD", DataType.HOLDING_REGISTER, 0xB880, 500, writable=True),
        "HTD": DeviceDef("HTD", DataType.HOLDING_REGISTER, 0xBC80, 96, writable=False),
        "HCD": DeviceDef("HCD", DataType.HOLDING_REGISTER, 0xC080, 96, writable=False),
        "HSCD": DeviceDef("HSCD", DataType.HOLDING_REGISTER, 0xC480, 32, writable=False),
        "FD":  DeviceDef("FD",  DataType.HOLDING_REGISTER, 0xC4C0, 5120, writable=True),
        "SFD": DeviceDef("SFD", DataType.HOLDING_REGISTER, 0xE4C0, 2000, writable=True),
        "FS":  DeviceDef("FS",  DataType.HOLDING_REGISTER, 0xF4C0, 48, writable=True),
    }


def _standard_defs() -> dict[str, DeviceDef]:
    # XD5/XDM/XDC/XD5E/XDME/XL5/XL5E/XL5N/XL5H/XLME
    d = _compact_defs()
    d["M"] = DeviceDef("M", DataType.COIL, 0, 20480, writable=True)
    d["S"] = DeviceDef("S", DataType.COIL, 0x7000, 8000, writable=True)
    d["SM"] = DeviceDef("SM", DataType.COIL, 0x9000, 4096, writable=True)
    # D 区在标准系列更大，Modbus 表中仍从 0 起始；大容量部分见手册
    d["D"] = DeviceDef("D", DataType.HOLDING_REGISTER, 0, 8000, writable=True)
    return d


def _high_defs() -> dict[str, DeviceDef]:
    # XDH/XLH — 仅覆盖本体常用区，扩展区按手册
    d = _compact_defs()
    d["M"] = DeviceDef("M", DataType.COIL, 0, 20480, writable=True)
    d["SM"] = DeviceDef("SM", DataType.COIL, 0x9000, 4096, writable=True)
    d["D"] = DeviceDef("D", DataType.HOLDING_REGISTER, 0, 8000, writable=True)
    return d


_SERIES_MAPS = {
    "compact": _compact_defs(),
    "standard": _standard_defs(),
    "high": _high_defs(),
}


def series_group(series: str) -> str:
    s = series.upper().replace(" ", "")
    if s in SERIES_COMPACT:
        return "compact"
    if s in SERIES_STANDARD:
        return "standard"
    if s in SERIES_HIGH:
        return "high"
    # 默认按标准系列
    return "standard"


def get_device_defs(series: str) -> dict[str, DeviceDef]:
    return _SERIES_MAPS[series_group(series)]


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------

def parse_device(name: str, series: str = "XD3") -> ResolvedDevice:
    """把 'Y10' / 'Y10100' / 'D200' / 'M0' / 'HD10' 解析成 Modbus 地址。

    规则（手册 6-2-3 ※5 ※7）：
    - X/Y 本体八进制：Y10 的点序是 8，Modbus = 0x6000 + 8
    - X/Y 扩展：Y10100 = 扩展模块 #2 点00 → 0x6140
    - 其余十进制：M100 → base + 100
    """
    raw = name.strip().upper().replace(" ", "")
    if not raw:
        raise ValueError("空设备名")

    defs = get_device_defs(series)

    # 最长前缀优先（HSCD > HSC > HS > H，避免误匹配）
    prefix = ""
    for p in sorted(defs.keys(), key=len, reverse=True):
        if raw.startswith(p) and len(raw) > len(p):
            prefix = p
            break
    if not prefix:
        raise ValueError(f"未知软元件类型: {name}")

    rest = raw[len(prefix):]
    dev = defs[prefix]

    if dev.octal:
        # X/Y：走扩展模块专用解析
        _, addr, point = parse_io_name(raw)
        return ResolvedDevice(
            name=raw,
            prefix=prefix,
            index=point,
            modbus_addr=addr,
            kind=dev.kind,
            writable=dev.writable,
        )

    if not rest.isdigit():
        raise ValueError(f"{prefix} 编号必须是十进制: {name}")
    point = int(rest)
    addr = dev.base + point
    return ResolvedDevice(
        name=raw,
        prefix=prefix,
        index=point,
        modbus_addr=addr,
        kind=dev.kind,
        writable=dev.writable,
    )


def device_range_names(prefix: str, series: str = "XD3",
                       start: int = 0, count: int = 16) -> list[str]:
    """生成一段设备名，用于监视表批量添加。"""
    defs = get_device_defs(series)
    if prefix not in defs:
        raise ValueError(f"未知软元件: {prefix}")
    dev = defs[prefix]
    out = []
    for i in range(start, min(start + count, dev.count)):
        if dev.octal:
            out.append(f"{prefix}{format_octal(i)}")
        else:
            out.append(f"{prefix}{i}")
    return out


def format_octal(value: int) -> str:
    """十进制点序 → 八进制字符串（X/Y 用）。"""
    return oct(value)[2:].upper()


# ---------------------------------------------------------------------------
# X/Y 扩展模块寻址（手册 6-2-3 ※5 ※7）
# ---------------------------------------------------------------------------
# 命名：X1MMPP / Y1MMPP
#   1 = 扩展模块站段，MM = 模块号 00~15（#1~#16），PP = 八进制点号 00~77
#   X2MMPP = BD 板，X3MMPP = ED 模块
# Modbus：
#   模块 #n (n=1..16):  X = 0x5100 + (n-1)*0x40 + point
#                       Y = 0x6100 + (n-1)*0x40 + point
#   BD #n (n=1..2):     X = 0x58D0 + (n-1)*0x40 + point
#                       Y = 0x68D0 + (n-1)*0x40 + point
#   ED #1:              X = 0x5BF0 + point
#                       Y = 0x6BF0 + point

_EXP_MODULE_X_BASE = 0x5100
_EXP_MODULE_Y_BASE = 0x6100
_EXP_BD_X_BASE = 0x58D0
_EXP_BD_Y_BASE = 0x68D0
_EXP_ED_X_BASE = 0x5BF0
_EXP_ED_Y_BASE = 0x6BF0
_EXP_BLOCK = 0x40  # 每模块 64 点


def parse_io_name(name: str) -> tuple[str, int, int]:
    """解析 X/Y 名 → (prefix, station, point_octal_dec)。

    返回 station: 0=本体, 1=扩展模块(模块号在 station_index),
    2=BD, 3=ED。额外返回 module_index (0-based) 供地址计算。
    实际返回 (prefix, modbus_addr, point_dec)。
    """
    raw = name.strip().upper()
    if not raw or raw[0] not in ("X", "Y"):
        raise ValueError(f"仅支持 X/Y: {name}")
    prefix = raw[0]
    rest = raw[1:]
    if not rest.isdigit() and not all(c in "01234567" for c in rest):
        # 允许八进制数字串
        if not all(c in "01234567" for c in rest):
            raise ValueError(f"非法 I/O 编号: {name}")

    if len(rest) <= 2:
        # 本体：八进制点号 X0~X77
        point = int(rest, 8)
        base = 0x5000 if prefix == "X" else 0x6000
        return prefix, base + point, point

    if len(rest) != 5:
        raise ValueError(
            f"I/O 编号格式应为 本体 X0~X77，或扩展 X1MMPP / X2MMPP / X3MMPP: {name}"
        )

    station = int(rest[0])
    # 模块号段为八进制：#1=00 … #9=10 … #16=17
    try:
        module = int(rest[1:3], 8)
    except ValueError as e:
        raise ValueError(f"模块号必须是八进制 00~17: {name}") from e
    try:
        point = int(rest[3:5], 8)
    except ValueError as e:
        raise ValueError(f"点号必须是八进制 00~77: {name}") from e

    if station == 1:
        if module > 15:
            raise ValueError(f"扩展模块号超出 #1~#16: {name}")
        base = (_EXP_MODULE_X_BASE if prefix == "X" else _EXP_MODULE_Y_BASE) \
            + module * _EXP_BLOCK
    elif station == 2:
        if module > 1:
            raise ValueError(f"BD 模块号超出 #1~#2: {name}")
        base = (_EXP_BD_X_BASE if prefix == "X" else _EXP_BD_Y_BASE) \
            + module * _EXP_BLOCK
    elif station == 3:
        if module > 0:
            raise ValueError(f"ED 只有 #1: {name}")
        base = _EXP_ED_X_BASE if prefix == "X" else _EXP_ED_Y_BASE
    else:
        raise ValueError(f"未知站段 {station} (应为 1/2/3): {name}")

    return prefix, base + point, point


def io_module_names(prefix: str, station: int, module: int,
                    count: int = 64) -> list[str]:
    """生成一段 X/Y 名。station: 0=本体 1=扩展 2=BD 3=ED。"""
    names = []
    if station == 0:
        i = 0
        while len(names) < count:
            names.append(f"{prefix}{oct(i)[2:].upper()}")
            i += 1
        return names
    # 扩展：X1MMPP，MM 与 PP 均为八进制
    for i in range(count):
        pt = oct(i)[2:].upper().zfill(2)
        mm = oct(module)[2:].upper().zfill(2)
        names.append(f"{prefix}{station}{mm}{pt}")
    return names


def describe_io_name(name: str) -> str:
    raw = name.strip().upper()
    prefix, addr, point = parse_io_name(name)
    if len(raw) <= 3:
        zone = "本体"
    else:
        station = int(raw[1])
        module = int(raw[2:4], 8)
        if station == 1:
            zone = f"扩展模块 #{module + 1}"
        elif station == 2:
            zone = f"BD板 #{module + 1}"
        else:
            zone = "ED模块 #1"
    return f"{raw}  →  {zone} 点{point}  Modbus {addr} (H{addr:04X})"


def describe_device(name: str, series: str = "XD3") -> str:
    """人类可读描述。"""
    d = parse_device(name, series)
    kind_cn = {
        DataType.COIL: "线圈/位",
        DataType.DISCRETE_INPUT: "输入位",
        DataType.INPUT_REGISTER: "输入寄存器",
        DataType.HOLDING_REGISTER: "保持寄存器",
    }[d.kind]
    rw = "可写" if d.writable else "只读"
    return f"{d.name}  →  Modbus {d.modbus_addr} (H{d.modbus_addr:04X})  {kind_cn}  {rw}"


# 预览：把常用软元件列成 UI 用的分类
DEVICE_CATEGORIES: list[tuple[str, list[str]]] = [
    ("输入/输出", ["X", "Y"]),
    ("辅助继电器", ["M", "HM", "SM", "SEM"]),
    ("状态/定时/计数", ["S", "HS", "T", "HT", "C", "HC", "HSC"]),
    ("数据寄存器", ["D", "HD", "SD", "TD", "CD", "FD"]),
    ("模块/扩展", ["ID", "QD"]),
]
