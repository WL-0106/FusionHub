# -*- coding: utf-8 -*-
"""
HSPY 大功率可编程直流电源 —— Modbus-RTU 通讯协议层
====================================================
依据《HSPY大功率通讯协议(2020)》(汉晟普源) 实现。

物理层
------
    RS232 / RS485，9600bps，8 数据位，无校验，2 停止位（可配置）

应用层
------
    Modbus-RTU，本机仅支持功能码：03(读保持寄存器) / 06(写单寄存器) / 10(写多寄存器)
    CRC：标准 Modbus CRC-16（多项式 0xA001，初值 0xFFFF），低字节在前

寻址
----
    文档注明「1000H、0000H 两种地址电源都支持」，
    示例报文使用 1000H 作为起始地址，故本程序默认寄存器基址 0x1000。
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
CRC_POLY = 0xA001
CRC_INIT = 0xFFFF

FC_READ_HOLDING = 0x03   # 读多路寄存器
FC_WRITE_SINGLE = 0x06   # 写单路寄存器
FC_WRITE_MULTI = 0x10    # 写多路寄存器

ADDR_BASE = 0x1000       # 寄存器基址（文档：0x1000 与 0x0000 均支持）

# 监测用一次性读取的寄存器块：0x1000 ~ 0x100E 共 15 个
POLL_START = 0x1000
POLL_COUNT = 15

# --------------------------------------------------------------------------- #
# 运行时可变的小数位
# --------------------------------------------------------------------------- #
# 为什么需要这个？
# 协议文档（HSPY3603）给出的换算关系是「电压 2 位、电流 3 位、功率 1 位小数」。
# 但实测发现不同批次 / 不同功率段的固件换算关系并不一致，最典型的是电流：
# 上位机按 3 位小数下发 1.000 A（原始值 1000），而电源按 2 位小数理解，
# 于是 1000 被当成 10.00 A —— 表现为「设 1 A 实出 10 A」，整整差 10 倍。
# 因此把小数位做成运行时可覆盖，界面里可直接调整并与实物对齐。
_DECIMALS_OVERRIDE: dict[str, int] = {}


def set_decimals(key: str, decimals: int) -> None:
    """运行时覆盖某寄存器的小数位（影响物理量换算与显示）。"""
    _DECIMALS_OVERRIDE[key] = max(0, min(6, int(decimals)))


def reset_decimals() -> None:
    """恢复文档默认的小数位。"""
    _DECIMALS_OVERRIDE.clear()


def decimals_of(key: str) -> int:
    """取某寄存器当前生效的小数位。"""
    v = _DECIMALS_OVERRIDE.get(key)
    return REG_BY_KEY[key].decimals if v is None else v


# 同一物理量涉及的相关寄存器（设定值 + 显示值），改小数位时应一起改
QUANTITY_KEYS = {
    'voltage': ('set_u', 'u'),
    'current': ('set_i', 'i'),
    'power':   ('set_p', 'p'),
}


def set_quantity_decimals(quantity: str, decimals: int) -> None:
    """按物理量批量设置小数位（电压 / 电流 / 功率的设定值与显示值一起改）。"""
    for k in QUANTITY_KEYS[quantity]:
        set_decimals(k, decimals)


class HspyProtocolError(Exception):
    """协议层异常（帧长度、CRC、异常码等）"""


class HspyExceptionResponse(HspyProtocolError):
    """从机返回 Modbus 异常响应（功能码 | 0x80）"""

    def __init__(self, func: int, code: int):
        self.func = func
        self.code = code
        super().__init__(f"从机返回异常响应：功能码 0x{func:02X}，异常码 0x{code:02X}（{EXCEPTION_TEXT.get(code, '未知')}）")


EXCEPTION_TEXT = {
    0x01: "非法功能码",
    0x02: "非法数据地址",
    0x03: "非法数据值",
    0x04: "从机设备故障",
    0x05: "确认(处理中)",
    0x06: "从机设备忙",
    0x08: "存储奇偶校验错误",
}


# --------------------------------------------------------------------------- #
# CRC-16 / Modbus
# --------------------------------------------------------------------------- #
def crc16(data: bytes) -> int:
    """计算 Modbus CRC-16，返回 16 位整数（低字节先发送）。"""
    crc = CRC_INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ CRC_POLY
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc(pdu: bytes) -> bytes:
    """在 PDU 末尾追加 CRC（低字节在前）。"""
    crc = crc16(pdu)
    return pdu + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def verify_crc(frame: bytes) -> bool:
    """校验整帧（含 CRC）是否正确。"""
    if len(frame) < 4:
        return False
    return crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


# --------------------------------------------------------------------------- #
# 报文构造
# --------------------------------------------------------------------------- #
def build_read(slave: int, start: int, count: int) -> bytes:
    """功能码 03：读保持寄存器。"""
    if not 0 <= slave <= 255:
        raise ValueError("从机地址须在 0~255 之间")
    if not 1 <= count <= 125:
        raise ValueError("读取寄存器数量须在 1~125 之间")
    pdu = bytes((slave, FC_READ_HOLDING,
                 (start >> 8) & 0xFF, start & 0xFF,
                 (count >> 8) & 0xFF, count & 0xFF))
    return append_crc(pdu)


def build_write_single(slave: int, reg: int, value: int) -> bytes:
    """功能码 06：写单个寄存器。"""
    value &= 0xFFFF
    pdu = bytes((slave, FC_WRITE_SINGLE,
                 (reg >> 8) & 0xFF, reg & 0xFF,
                 (value >> 8) & 0xFF, value & 0xFF))
    return append_crc(pdu)


def build_write_multi(slave: int, start: int, values) -> bytes:
    """功能码 10：写多个寄存器（值均为 16 位，高字节在前）。"""
    values = [int(v) & 0xFFFF for v in values]
    n = len(values)
    if not 1 <= n <= 123:
        raise ValueError("写入寄存器数量须在 1~123 之间")
    pdu = bytearray((slave, FC_WRITE_MULTI,
                     (start >> 8) & 0xFF, start & 0xFF,
                     (n >> 8) & 0xFF, n & 0xFF,
                     n * 2))
    for v in values:
        pdu.append((v >> 8) & 0xFF)
        pdu.append(v & 0xFF)
    return append_crc(bytes(pdu))


# --------------------------------------------------------------------------- #
# 报文解析
# --------------------------------------------------------------------------- #
def parse_response(frame: bytes, slave: int, func: int):
    """
    校验并解析从机响应。

    返回：
        * 功能码 03 -> list[int]  （寄存器值列表）
        * 功能码 06 -> (reg, value)
        * 功能码 10 -> (start, count)
    """
    if not frame or len(frame) < 4:
        raise HspyProtocolError(f"响应帧过短：{frame.hex(' ').upper() if frame else '(空)'}")
    if not verify_crc(frame):
        raise HspyProtocolError(f"CRC 校验失败：{frame.hex(' ').upper()}")
    if frame[0] != slave:
        raise HspyProtocolError(f"从机地址不匹配：期望 {slave}，实际 {frame[0]}")
    if frame[1] == (func | 0x80):
        raise HspyExceptionResponse(func, frame[2] if len(frame) > 2 else 0)
    if frame[1] != func:
        raise HspyProtocolError(f"功能码不匹配：期望 0x{func:02X}，实际 0x{frame[1]:02X}")

    if func == FC_READ_HOLDING:
        byte_count = frame[2]
        if len(frame) != 3 + byte_count + 2 or byte_count % 2:
            raise HspyProtocolError(f"读取响应长度异常：{frame.hex(' ').upper()}")
        data = frame[3:3 + byte_count]
        return [(data[i] << 8) | data[i + 1] for i in range(0, byte_count, 2)]

    if func == FC_WRITE_SINGLE:
        if len(frame) != 8:
            raise HspyProtocolError(f"写单寄存器响应长度异常：{frame.hex(' ').upper()}")
        return ((frame[2] << 8) | frame[3], (frame[4] << 8) | frame[5])

    if func == FC_WRITE_MULTI:
        if len(frame) != 8:
            raise HspyProtocolError(f"写多寄存器响应长度异常：{frame.hex(' ').upper()}")
        return ((frame[2] << 8) | frame[3], (frame[4] << 8) | frame[5])

    raise HspyProtocolError(f"不支持的功能码 0x{func:02X}")


# --------------------------------------------------------------------------- #
# 寄存器表
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Register:
    key: str          # 内部键名
    name: str         # 中文名称
    addr: int         # 通讯地址（含基址）
    decimals: int     # 小数点位数
    access: str       # 'r' / 'w' / 'rw'
    lo: int           # 原始值下限
    hi: int           # 原始值上限
    unit: str         # 单位
    note: str = ""    # 备注

    @property
    def readonly(self) -> bool:
        return self.access == 'r'

    @property
    def writeonly(self) -> bool:
        return self.access == 'w'

    # ---- 定点数换算 ---- #
    @property
    def d(self) -> int:
        """当前生效的小数位（可被 set_decimals() 运行时覆盖）。"""
        v = _DECIMALS_OVERRIDE.get(self.key)
        return self.decimals if v is None else v

    @property
    def scale(self) -> float:
        return float(10 ** self.d)

    def to_physical(self, raw: int) -> float:
        """寄存器原始值 -> 实际物理量"""
        return raw / self.scale

    def to_raw(self, value: float) -> int:
        """实际物理量 -> 寄存器原始值"""
        raw = int(round(value * self.scale))
        return max(0, min(0xFFFF, raw))

    def format(self, raw: int) -> str:
        """格式化为带单位的显示文本"""
        return f"{self.to_physical(raw):.{self.d}f} {self.unit}".strip()


REGISTERS = [
    Register('set_u',    '电压设定值',   ADDR_BASE + 0x00, 2, 'rw', 0, 65535, 'V'),
    Register('set_i',    '电流设定值',   ADDR_BASE + 0x01, 3, 'rw', 0, 65535, 'A'),
    Register('u',        '电压显示值',   ADDR_BASE + 0x02, 2, 'r',  0, 65535, 'V'),
    Register('i',        '电流显示值',   ADDR_BASE + 0x03, 3, 'r',  0, 65535, 'A'),
    Register('run_stop', '输出开关',     ADDR_BASE + 0x04, 0, 'rw', 0, 1,     '',  '0=停止 1=输出'),
    Register('rs_addr',  '通讯地址',     ADDR_BASE + 0x05, 0, 'rw', 0, 255,   ''),
    Register('key_lock', '按键锁定',     ADDR_BASE + 0x06, 0, 'rw', 0, 1,     '',  '0=解锁 1=锁定'),
    Register('set_p',    '功率设定值',   ADDR_BASE + 0x07, 1, 'rw', 0, 65535, 'W'),
    Register('p',        '功率显示值',   ADDR_BASE + 0x08, 1, 'r',  0, 65535, 'W'),
    Register('mode',     '工作模式',     ADDR_BASE + 0x09, 0, 'rw', 0, 2,     '',  '0/1/2'),
    Register('up_start', '上电启动',     ADDR_BASE + 0x0A, 0, 'rw', 0, 1,     '',  '0=上电停止 1=上电启动'),
    Register('auto_err', '自动跟踪补偿', ADDR_BASE + 0x0B, 0, 'rw', 0, 1,     ''),
    Register('rs_bt',    '通讯波特率',   ADDR_BASE + 0x0C, 0, 'rw', 0, 3,     '',  '0/3'),
    Register('rs_stop',  '通讯停止位',   ADDR_BASE + 0x0D, 0, 'rw', 1, 2,     '',  '1 或 2'),
    Register('cc_cv',    '恒压恒流状态', ADDR_BASE + 0x0E, 0, 'r',  0, 1,     '',  '0=CV 恒压 1=CC 恒流'),
    Register('down_save', '掉电保存',    ADDR_BASE + 0x0F, 0, 'rw', 0, 1,     ''),
    Register('ovp',      '过压保护',     ADDR_BASE + 0x14, 3, 'rw', 0, 65535, 'V'),
    Register('ocp',      '过流保护',     ADDR_BASE + 0x15, 3, 'rw', 0, 65535, 'A'),
    Register('out_s',    '输出状态测量', ADDR_BASE + 0x16, 0, 'r',  0, 1,     '',  '0~1'),
    Register('set_out',  '极性设置',     ADDR_BASE + 0x17, 0, 'w',  0, 1,     ''),
]

REG_BY_KEY = {r.key: r for r in REGISTERS}
REG_BY_ADDR = {r.addr: r for r in REGISTERS}


def reg(key: str) -> Register:
    """按内部键名取寄存器定义。"""
    try:
        return REG_BY_KEY[key]
    except KeyError:
        raise KeyError(f"未定义的寄存器：{key}") from None


# 需要一次性全部读回的寄存器块（用于「一键读取」）
FULL_READ_BLOCKS = [(ADDR_BASE + 0x00, 16), (ADDR_BASE + 0x14, 4)]


def format_frame(frame: bytes) -> str:
    """把字节串格式化为 '01 03 10 00 …' 便于日志显示。"""
    return ' '.join(f'{b:02X}' for b in frame)


if __name__ == '__main__':
    # 自检：文档中的示例报文
    assert format_frame(build_read(0x00, 0x1000, 2)) == '00 03 10 00 00 02 C1 1A'
    assert format_frame(build_write_multi(0x00, 0x1000, [0x0E10])) == '00 10 10 00 00 01 02 0E 10 BF AD'
    assert parse_response(bytes.fromhex('0003040E10C0CBF849'), 0x00, 0x03) == [0x0E10, 0xC0CB]
    assert reg('set_u').to_physical(0x0E10) == 36.0
    assert reg('set_i').to_physical(0x0BB8) == 3.0
    assert reg('ovp').to_raw(40.5) == 40500

    # 小数位运行时覆盖：电流 3 位 -> 2 位后，1 A 的原始值应从 1000 变成 100
    assert reg('set_i').to_raw(1.0) == 1000
    set_decimals('set_i', 2)
    assert reg('set_i').d == 2
    assert reg('set_i').to_raw(1.0) == 100, reg('set_i').to_raw(1.0)
    assert reg('set_i').to_physical(1000) == 10.0
    assert reg('set_i').format(1000) == '10.00 A'
    reset_decimals()
    assert reg('set_i').to_raw(1.0) == 1000
    assert decimals_of('set_i') == 3
    print('HspyProtocol 自检通过 ✔')
