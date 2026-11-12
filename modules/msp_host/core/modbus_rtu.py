# -*- coding: utf-8 -*-
"""Modbus RTU 帧层：CRC-16、帧封装/解包、异常码 → 人话提示。

来源：MSP65 说明书 V2.3 §6.4 / MSP62 说明书 V1.3 §通讯协议。
手册要点：
  - 功能码：0x03 读可写寄存器区、0x04 读只读寄存器区、0x06 写单寄存器、0x10 写多寄存器
  - 读写必须地址连续；单次 1~20 个寄存器
  - CRC-16/MODBUS：x^16 + x^15 + x^2 + 1，低字节在前
  - 帧内寄存器地址/数量/数据均为大端（高字节在前）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

FC_READ_RW = 0x03      # 读多个可写寄存器
FC_READ_RO = 0x04      # 读多个只读寄存器
FC_WRITE_SINGLE = 0x06
FC_WRITE_MULTI = 0x10

EXCEPTION_FLAG = 0x80

MAX_REGISTERS_PER_FRAME = 20   # 手册：单次读写 1~20 个寄存器


class ModbusFrameError(Exception):
    """帧格式/校验错误（可重同步恢复）。"""


class ModbusExceptionResponse(Exception):
    """从站返回异常响应（功能码 | 0x80）。"""

    def __init__(self, code: int):
        self.code = code
        super().__init__(exception_text(code))


def crc16(data: bytes) -> int:
    """标准 Modbus CRC-16（多项式 0xA001，反射）。返回 16 位值。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def append_crc(payload: bytes) -> bytes:
    c = crc16(payload)
    return payload + bytes((c & 0xFF, (c >> 8) & 0xFF))   # 低字节在前


def verify_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    return crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


# ----------------------------------------------------------------------------
# 异常码映射（澄清项 4：手册未给异常码表，按标准 Modbus 映射）
# ----------------------------------------------------------------------------

_EXCEPTION_TEXT = {
    0x01: "不支持的功能码（从站拒绝执行该指令）",
    0x02: "寄存器地址越界（从站不存在该地址）",
    0x03: "数据值非法（数量/数值超出允许范围）",
    0x04: "从站执行失败（设备内部故障）",
    0x05: "从站已接收请求，但处理需要较长时间（忙）",
    0x06: "从站正忙，请稍后重试",
    0x08: "存储器奇偶校验错误",
    0x0A: "网关路径不可用",
    0x0B: "网关目标无响应",
}


def exception_text(code: int) -> str:
    return _EXCEPTION_TEXT.get(code, f"未定义的 Modbus 异常码 0x{code:02X}（需与厂家确认）")


# ----------------------------------------------------------------------------
# 请求封装
# ----------------------------------------------------------------------------

def build_read(addr: int, fc: int, start: int, count: int) -> bytes:
    if not (1 <= count <= MAX_REGISTERS_PER_FRAME):
        raise ValueError(f"单次读寄存器数量必须 1~{MAX_REGISTERS_PER_FRAME}，实际 {count}")
    if not (0 <= start <= 0xFFFF) or start + count - 1 > 0xFFFF:
        raise ValueError(f"读地址越界：{start}+{count}")
    return append_crc(bytes((addr, fc, (start >> 8) & 0xFF, start & 0xFF,
                             (count >> 8) & 0xFF, count & 0xFF)))


def build_read_rw(addr: int, start: int, count: int) -> bytes:
    return build_read(addr, FC_READ_RW, start, count)


def build_read_ro(addr: int, start: int, count: int) -> bytes:
    return build_read(addr, FC_READ_RO, start, count)


def build_write_single(addr: int, reg: int, value: int) -> bytes:
    if not (0 <= value <= 0xFFFF):
        raise ValueError(f"写值必须 0~65535，实际 {value}")
    return append_crc(bytes((addr, FC_WRITE_SINGLE, (reg >> 8) & 0xFF, reg & 0xFF,
                             (value >> 8) & 0xFF, value & 0xFF)))


def build_write_multi(addr: int, start: int, values: List[int]) -> bytes:
    n = len(values)
    if not (1 <= n <= MAX_REGISTERS_PER_FRAME):
        raise ValueError(f"单次写寄存器数量必须 1~{MAX_REGISTERS_PER_FRAME}，实际 {n}")
    payload = bytes((addr, FC_WRITE_MULTI,
                     (start >> 8) & 0xFF, start & 0xFF,
                     (n >> 8) & 0xFF, n & 0xFF,
                     n * 2))
    for v in values:
        if not (0 <= v <= 0xFFFF):
            raise ValueError(f"写值必须 0~65535，实际 {v}")
        payload += bytes(((v >> 8) & 0xFF, v & 0xFF))
    return append_crc(payload)


# ----------------------------------------------------------------------------
# 响应解析（含半包/粘包/错帧检测）
# ----------------------------------------------------------------------------

@dataclass
class Response:
    addr: int
    fc: int
    values: List[int]          # 读响应：寄存器值；写响应：[start, count/value]
    raw: bytes


def expected_response_length(req: bytes) -> Optional[int]:
    """由请求推导期望响应帧长；异常响应固定 5 字节，两者取并集在解析时处理。"""
    fc = req[1]
    if fc in (FC_READ_RW, FC_READ_RO):
        return None    # 由响应第 3 字节（数据字节数）决定
    if fc == FC_WRITE_SINGLE:
        return 8
    if fc == FC_WRITE_MULTI:
        return 8
    return None


def try_parse_frame(buf: bytes, expect_addr: int, expect_fc: int):
    """从缓冲区尝试解析一帧。

    返回 (Response, 消耗字节数) 或 None（数据不完整）。
    遇到错帧抛 ModbusFrameError，由调用方丢弃首字节后重同步。
    异常响应抛 ModbusExceptionResponse。
    """
    if len(buf) < 4:
        return None

    addr, fc = buf[0], buf[1]

    # 异常响应：addr fc|0x80 code crc → 5 字节
    if fc & EXCEPTION_FLAG:
        if len(buf) < 5:
            return None
        frame = buf[:5]
        if not verify_crc(frame):
            raise ModbusFrameError("异常响应 CRC 校验失败")
        raise ModbusExceptionResponse(frame[2])

    if addr != expect_addr:
        raise ModbusFrameError(f"响应地址 0x{addr:02X} 与请求地址 0x{expect_addr:02X} 不符")
    if fc != expect_fc:
        raise ModbusFrameError(f"响应功能码 0x{fc:02X} 与请求功能码 0x{expect_fc:02X} 不符")

    if fc in (FC_READ_RW, FC_READ_RO):
        if len(buf) < 3:
            return None
        byte_count = buf[2]
        total = 3 + byte_count + 2
        if byte_count == 0 or byte_count % 2 != 0 or byte_count > MAX_REGISTERS_PER_FRAME * 2:
            raise ModbusFrameError(f"读响应数据字节数非法：{byte_count}")
        if len(buf) < total:
            return None
        frame = buf[:total]
        if not verify_crc(frame):
            raise ModbusFrameError("读响应 CRC 校验失败")
        values = [frame[3 + i] << 8 | frame[4 + i] for i in range(0, byte_count, 2)]
        return Response(addr, fc, values, frame), total

    if fc in (FC_WRITE_SINGLE, FC_WRITE_MULTI):
        total = 8
        if len(buf) < total:
            return None
        frame = buf[:total]
        if not verify_crc(frame):
            raise ModbusFrameError("写响应 CRC 校验失败")
        v1 = frame[2] << 8 | frame[3]
        v2 = frame[4] << 8 | frame[5]
        return Response(addr, fc, [v1, v2], frame), total

    raise ModbusFrameError(f"不支持的功能码 0x{fc:02X}")
