"""Modbus ADU/PDU builders and response parsers (master side)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

# Function codes
FC_READ_COILS = 0x01
FC_READ_DISCRETE_INPUTS = 0x02
FC_READ_HOLDING = 0x03
FC_READ_INPUT_REG = 0x04
FC_WRITE_SINGLE_COIL = 0x05
FC_WRITE_SINGLE_REG = 0x06
FC_WRITE_MULTI_COILS = 0x0F
FC_WRITE_MULTI_REGS = 0x10

EXCEPTION_NAMES = {
    0x01: "非法功能码",
    0x02: "非法数据地址",
    0x03: "非法数据值",
    0x04: "从站设备故障",
    0x05: "确认（长时处理）",
    0x06: "从站设备忙",
    0x08: "存储器奇偶校验错",
    0x0A: "网关路径不可用",
    0x0B: "网关目标设备无响应",
}


class ModbusError(Exception):
    def __init__(self, code: int, message: str = ""):
        self.code = code
        name = EXCEPTION_NAMES.get(code, f"异常码 0x{code:02X}")
        super().__init__(message or name)


@dataclass
class Pdu:
    function: int
    payload: bytes


def build_read_bits(slave: int, fc: int, address: int, count: int) -> bytes:
    if fc not in (FC_READ_COILS, FC_READ_DISCRETE_INPUTS):
        raise ValueError("fc must be 0x01 or 0x02")
    if not (1 <= count <= 2000):
        raise ValueError("count must be 1..2000")
    return bytes((slave, fc, (address >> 8) & 0xFF, address & 0xFF, (count >> 8) & 0xFF, count & 0xFF))


def build_read_registers(slave: int, address: int, count: int) -> bytes:
    if not (1 <= count <= 125):
        raise ValueError("count must be 1..125")
    return bytes(
        (
            slave,
            FC_READ_HOLDING,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        )
    )


def build_write_single_coil(slave: int, address: int, on: bool) -> bytes:
    value = 0xFF00 if on else 0x0000
    return bytes(
        (
            slave,
            FC_WRITE_SINGLE_COIL,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        )
    )


def build_write_single_reg(slave: int, address: int, value: int) -> bytes:
    value &= 0xFFFF
    return bytes(
        (
            slave,
            FC_WRITE_SINGLE_REG,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        )
    )


def build_write_multi_coils(slave: int, address: int, bits: Sequence[bool]) -> bytes:
    count = len(bits)
    if not (1 <= count <= 1968):
        raise ValueError("count must be 1..1968")
    byte_count = (count + 7) // 8
    packed = bytearray(byte_count)
    for i, bit in enumerate(bits):
        if bit:
            packed[i // 8] |= 1 << (i % 8)
    head = bytes(
        (
            slave,
            FC_WRITE_MULTI_COILS,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
            byte_count,
        )
    )
    return head + bytes(packed)


def build_write_multi_regs(slave: int, address: int, values: Sequence[int]) -> bytes:
    count = len(values)
    if not (1 <= count <= 123):
        raise ValueError("count must be 1..123")
    byte_count = count * 2
    body = bytearray()
    for v in values:
        v &= 0xFFFF
        body.append((v >> 8) & 0xFF)
        body.append(v & 0xFF)
    head = bytes(
        (
            slave,
            FC_WRITE_MULTI_REGS,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
            byte_count,
        )
    )
    return head + bytes(body)


def parse_response(request_fc: int, pdu: bytes) -> object:
    """Parse response PDU (without slave id) for a known request FC.

    Returns:
      - list[bool] for bit reads
      - list[int] for register reads
      - dict for write echoes
    """
    if not pdu:
        raise ValueError("空响应")
    fc = pdu[0]
    if fc & 0x80:
        code = pdu[1] if len(pdu) > 1 else 0
        raise ModbusError(code)
    if fc != request_fc:
        raise ValueError(f"功能码不匹配: 期望 0x{request_fc:02X}, 实际 0x{fc:02X}")

    if fc in (FC_READ_COILS, FC_READ_DISCRETE_INPUTS):
        byte_count = pdu[1]
        data = pdu[2 : 2 + byte_count]
        # caller unpacks with expected count
        return list(data)

    if fc in (FC_READ_HOLDING, FC_READ_INPUT_REG):
        byte_count = pdu[1]
        data = pdu[2 : 2 + byte_count]
        return [ (data[i] << 8) | data[i + 1] for i in range(0, len(data), 2) ]

    if fc == FC_WRITE_SINGLE_COIL:
        addr = (pdu[1] << 8) | pdu[2]
        val = (pdu[3] << 8) | pdu[4]
        return {"address": addr, "on": val == 0xFF00}

    if fc == FC_WRITE_SINGLE_REG:
        addr = (pdu[1] << 8) | pdu[2]
        val = (pdu[3] << 8) | pdu[4]
        return {"address": addr, "value": val}

    if fc in (FC_WRITE_MULTI_COILS, FC_WRITE_MULTI_REGS):
        addr = (pdu[1] << 8) | pdu[2]
        count = (pdu[3] << 8) | pdu[4]
        return {"address": addr, "count": count}

    raise ValueError(f"不支持的功能码 0x{fc:02X}")


def unpack_bits(raw_bytes: List[int], count: int) -> List[bool]:
    bits: List[bool] = []
    for i in range(count):
        byte = raw_bytes[i // 8]
        bits.append(bool((byte >> (i % 8)) & 1))
    return bits


def expected_response_length(request_pdu: bytes, is_tcp: bool = False) -> int:
    """Estimate RTU response length (slave+fc+payload+crc) from request."""
    if not request_pdu:
        return 5
    fc = request_pdu[1] if is_tcp else request_pdu[1]
    # request_pdu includes slave for RTU; for TCP PDU starts at fc
    if is_tcp:
        pdu = request_pdu  # [fc, ...]
    else:
        pdu = request_pdu[1:]  # skip slave

    f = pdu[0]
    if f in (FC_READ_COILS, FC_READ_DISCRETE_INPUTS, FC_READ_HOLDING, FC_READ_INPUT_REG):
        count = (pdu[-2] << 8) | pdu[-1]
        if f in (FC_READ_COILS, FC_READ_DISCRETE_INPUTS):
            data_bytes = (count + 7) // 8
        else:
            data_bytes = count * 2
        # slave + fc + bytecount + data + crc(2)   for RTU
        # for TCP length is handled separately
        return 1 + 1 + 1 + data_bytes + 2
    if f == FC_WRITE_SINGLE_COIL or f == FC_WRITE_SINGLE_REG:
        return 8  # slave+fc+addr(2)+value(2)+crc(2)
    if f == FC_WRITE_MULTI_COILS or f == FC_WRITE_MULTI_REGS:
        return 8
    return 256
