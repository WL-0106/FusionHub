"""汇川 EASY300 / EASY500 系列 Modbus 地址映射.

依据汇川 Easy 系列通信约定（与 H5U / 小型 PLC 一致）：

| 软元件 | Modbus 区        | 起始地址(HEX) | 起始地址(DEC) | 功能码      | 编址 |
|--------|------------------|---------------|---------------|-------------|------|
| X 输入  | 线圈 / 离散输入   | 0xF800        | 63488         | 01 / 02     | 八进制 |
| Y 输出  | 线圈             | 0xFC00        | 64512         | 01 / 05 / 15 | 八进制 |
| M 辅助  | 线圈             | 0x0000        | 0             | 01 / 05 / 15 | 十进制 |
| D 数据  | 保持寄存器       | 0x0000        | 0             | 03 / 06 / 16 | 十进制 |

说明：
- X / Y 在 PLC 程序里是八进制（X0-X7, X10-X17...），Modbus 偏移为八进制数值。
- M / D 为十进制编号。
- 也可直接使用「原始 Modbus 地址」模式绕过映射。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


# 起始地址（可按手册/工程实际微调）
X_BASE = 0xF800  # 63488
Y_BASE = 0xFC00  # 64512
M_BASE = 0x0000  # 0
D_BASE = 0x0000  # 0

# 常用点数（本体 + 常见扩展，UI 显示用）
X_POINTS = 64  # X0–X77 八进制约 64 点
Y_POINTS = 64
M_POINTS = 256
D_POINTS = 256

SERIES_PRESETS = {
    "EASY300": {
        "x_points": 32,
        "y_points": 32,
        "m_points": 256,
        "d_points": 256,
        "default_baud": 9600,
        "has_ethernet": False,
    },
    "EASY500": {
        "x_points": 64,
        "y_points": 64,
        "m_points": 512,
        "d_points": 512,
        "default_baud": 19200,
        "has_ethernet": True,
    },
}


def parse_octal_index(text: str) -> int:
    """'X10' / '10' / 'Y17' -> 8 / 8 / 15（八进制→十进制偏移）."""
    t = text.strip().upper()
    for p in ("X", "Y", "M", "D"):
        if t.startswith(p):
            t = t[1:]
            break
    t = t.strip()
    if not t:
        raise ValueError("地址为空")
    return int(t, 8)


def parse_dec_index(text: str) -> int:
    t = text.strip().upper()
    for p in ("M", "D", "T", "C"):
        if t.startswith(p):
            t = t[1:]
            break
    t = t.strip()
    if not t:
        raise ValueError("地址为空")
    return int(t, 10)


@dataclass(frozen=True)
class MappedAddress:
    """映射结果."""

    device: str          # X / Y / M / D / RAW
    index: int           # 软元件号（十进制偏移）
    modbus_addr: int     # Modbus 协议地址
    table: str           # coil / discrete / holding
    writable: bool
    label: str           # 显示用，如 X10 / D20


def map_xy(device: str, index: int) -> MappedAddress:
    device = device.upper()
    if device == "X":
        addr = X_BASE + index
        return MappedAddress("X", index, addr, "coil", False, f"X{index:o}")
    if device == "Y":
        addr = Y_BASE + index
        return MappedAddress("Y", index, addr, "coil", True, f"Y{index:o}")
    raise ValueError("device must be X or Y")


def map_md(device: str, index: int) -> MappedAddress:
    device = device.upper()
    if device == "M":
        addr = M_BASE + index
        return MappedAddress("M", index, addr, "coil", True, f"M{index}")
    if device == "D":
        addr = D_BASE + index
        return MappedAddress("D", index, addr, "holding", True, f"D{index}")
    raise ValueError("device must be M or D")


def parse_device_address(text: str) -> MappedAddress:
    """解析 'X10' / 'Y0' / 'M20' / 'D100' / 'RAW coil 64512' / 'raw hold 10'."""
    raw = text.strip()
    if not raw:
        raise ValueError("地址为空")
    low = raw.lower()
    if low.startswith("raw"):
        parts = raw.split()
        if len(parts) < 3:
            raise ValueError("RAW 格式: RAW coil|discrete|hold <地址>")
        table = parts[1].lower()
        table_map = {
            "coil": "coil",
            "coils": "coil",
            "discrete": "discrete",
            "input": "discrete",
            "hold": "holding",
            "holding": "holding",
            "reg": "holding",
            "register": "holding",
        }
        if table not in table_map:
            raise ValueError("表类型应为 coil/discrete/hold")
        addr = int(parts[2], 0)
        return MappedAddress("RAW", addr, addr, table_map[table], table_map[table] != "discrete", raw)

    ch = raw[0].upper()
    if ch in ("X", "Y"):
        idx = parse_octal_index(raw)
        return map_xy(ch, idx)
    if ch in ("M", "D"):
        idx = parse_dec_index(raw)
        return map_md(ch, idx)
    raise ValueError("无法识别地址，请使用 X/Y/M/D 或 RAW 形式")


def format_xy_display(index: int) -> str:
    return f"{index:o}"


# 设备预设


@dataclass
class DeviceProfile:
    series: str
    x_points: int
    y_points: int
    m_points: int
    d_points: int
    default_baud: int
    has_ethernet: bool

    @staticmethod
    def of(series: str) -> "DeviceProfile":
        key = series.upper().replace(" ", "")
        if key in ("EASY300", "EASY301", "EASY320", "EASY321"):
            key = "EASY300"
        elif key in ("EASY500", "EASY521", "EASY520"):
            key = "EASY500"
        preset = SERIES_PRESETS.get(key, SERIES_PRESETS["EASY300"])
        return DeviceProfile(series=key, **preset)
