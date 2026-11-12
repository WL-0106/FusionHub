# -*- coding: utf-8 -*-
"""CRC16 (Modbus) —— 多项式 0xA001，低字节在前。"""

_CRC_TABLE = []


def _build_table():
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        _CRC_TABLE.append(crc)


_build_table()


def crc16(data) -> int:
    """返回 16 位 CRC 数值（高低字节需按低字节在前装配）。"""
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def append_crc(payload: bytes) -> bytes:
    """在报文尾部追加 CRC，低字节在前。"""
    c = crc16(payload)
    return payload + bytes([c & 0xFF, (c >> 8) & 0xFF])


def check_crc(frame: bytes) -> bool:
    """校验整帧（含末尾 2 字节 CRC）。"""
    if len(frame) < 4:
        return False
    return crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8))
