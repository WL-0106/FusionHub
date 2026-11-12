# -*- coding: utf-8 -*-
"""电阻变送器 Modbus-RTU 协议栈（零依赖，手写帧编解码 + 寄存器定义）。

依据《2946060166 电阻变送器说明书》实现：
  - 物理层：RS485，8 位数据位
  - 波特率：2400/4800/9600/19200/38400/57600/115200，出厂 9600
  - 校验：无/奇/偶，出厂无校验（8N1）
  - 从站地址：1~247，出厂 1
  - 功能码：03H/04H 读量值/参数；06H/10H 写参数

寄存器表：
  0         电阻值          UShort  无符号整数
  2048~2049 电阻值          Float   IEEE754（ABCD 高字在前，占 2 寄存器）
  7166      通信参数修改允许  Short   写 0xCCAA 才允许修改通信参数
  7167      RS485 地址       Short   1~247
  7168      RS485 波特率     Short   0~6（见 BAUD_MAP）
  7169      RS485 数据格式   Short   0=8N1 1=8O1 2=8E1 3=8N2
"""
from __future__ import annotations

import struct


# ---------------------------------------------------------------- CRC16
def crc16(data: bytes) -> int:
    """Modbus CRC16（低字节在前）。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_frame(addr: int, func: int, payload: bytes) -> bytes:
    """组一帧：地址 + 功能码 + 数据 + CRC16（低字节在前）。"""
    pdu = bytes([addr, func]) + payload
    crc = crc16(pdu)
    return pdu + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def check_frame(frame: bytes) -> bool:
    """校验回帧 CRC。"""
    if len(frame) < 4:
        return False
    crc_calc = crc16(frame[:-2])
    crc_recv = frame[-2] | (frame[-1] << 8)
    return crc_calc == crc_recv


EXCEPTION_TEXT = {
    0x01: "非法功能码 (01)",
    0x02: "非法数据地址 (02)",
    0x03: "非法数据值 (03)",
    0x04: "从站设备故障 (04)",
    0x05: "确认（服务未就绪）(05)",
    0x06: "从站忙 (06)",
    0x0A: "网关路径不可用 (0A)",
    0x0B: "网关目标设备无响应 (0B)",
}


def parse_exception(frame: bytes):
    """异常响应返回说明文本，否则 None。"""
    if len(frame) >= 3 and frame[1] & 0x80:
        code = frame[2] if len(frame) > 2 else 0
        return EXCEPTION_TEXT.get(code, "未知异常码 (0x%02X)" % code)
    return None


# ---------------------------------------------------------------- 帧构造
def read_regs(addr: int, start: int, count: int, func: int = 0x03) -> bytes:
    """读寄存器（03/04）。"""
    return build_frame(addr, func, start.to_bytes(2, "big") + count.to_bytes(2, "big"))


def write_single_reg(addr: int, reg: int, value: int) -> bytes:
    """写单个寄存器（06）。"""
    return build_frame(addr, 0x06, reg.to_bytes(2, "big") + (value & 0xFFFF).to_bytes(2, "big"))


def write_multi_regs(addr: int, start: int, values: list) -> bytes:
    """写多个寄存器（10）。values 为 16 位整数列表。"""
    n = len(values)
    payload = start.to_bytes(2, "big") + n.to_bytes(2, "big") + bytes([n * 2])
    for v in values:
        payload += (v & 0xFFFF).to_bytes(2, "big")
    return build_frame(addr, 0x10, payload)


# ---------------------------------------------------------------- 解包
def u16(data: bytes, off: int = 0) -> int:
    return int.from_bytes(data[off:off + 2], "big")


def s16(data: bytes, off: int = 0) -> int:
    return int.from_bytes(data[off:off + 2], "big", signed=True)


def f32_abcd(data: bytes, off: int = 0) -> float:
    """Float 寄存器：ABCD 顺序（高字在前）。"""
    return struct.unpack(">f", data[off:off + 4])[0]


def float_to_regs(x: float) -> list:
    """把 float 拆成两个 16 位寄存器（ABCD 高字在前）。"""
    b = struct.pack(">f", x)
    return [int.from_bytes(b[0:2], "big"), int.from_bytes(b[2:4], "big")]


# ---------------------------------------------------------------- 寄存器定义
BAUD_MAP = {0: 2400, 1: 4800, 2: 9600, 3: 19200, 4: 38400, 5: 57600, 6: 115200}
BAUD_TO_CODE = {v: k for k, v in BAUD_MAP.items()}

FMT_MAP = {
    0: "8N1（无校验 1 停止位）",
    1: "8O1（奇校验 1 停止位）",
    2: "8E1（偶校验 1 停止位）",
    3: "8N2（无校验 2 停止位）",
}

REG_ALLOW = 7166     # 写入 0xCCAA 允许修改
REG_ADDR = 7167      # RS485 地址
REG_BAUD = 7168      # 波特率
REG_FMT = 7169       # 数据格式

REG_RES_INT = 0        # UShort 整数
REG_RES_FLOAT = 2048   # Float（占 2048~2049）

ALLOW_VALUE = 0xCCAA   # 打开通信参数修改许可的魔数


def selftest() -> None:
    """用说明书 4.3 节报文举例校验协议栈。"""
    f1 = read_regs(1, 0x0000, 1, 0x03)
    assert f1 == bytes.fromhex("01 03 00 00 00 01 84 0A"), "例1帧错误: %s" % f1.hex(" ")

    f2 = read_regs(1, 2048, 2, 0x03)
    assert f2 == bytes.fromhex("01 03 08 00 00 02 C6 6B"), "例2帧错误: %s" % f2.hex(" ")

    resp1 = bytes.fromhex("01 03 02 12 C0 B4 B4")
    assert check_frame(resp1), "回帧1 CRC错误"
    assert u16(resp1, 3) == 0x12C0 == 4800

    # 说明书例2回帧原文 01 03 04 43 F0 00 00 2F 87 的 CRC 为印刷错误；
    # 正确 CRC 应为 EF 84（数据 01 03 04 43 F0 00 00 的 CRC16=0x84EF，低字节在前）。
    resp2 = bytes.fromhex("01 03 04 43 F0 00 00 EF 84")
    assert check_frame(resp2), "回帧2 CRC错误"
    assert abs(f32_abcd(resp2, 3) - 480.0) < 1e-6, "float 解包错误"

    print("电阻变送器协议自测通过：CRC16 / 组帧 / 整数解包 / Float 解包 均与说明书举例一致")


if __name__ == "__main__":
    selftest()
