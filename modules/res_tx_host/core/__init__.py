# -*- coding: utf-8 -*-
"""电阻变送器 core 包：Modbus-RTU 协议栈 + 寄存器定义。

protocol.py —— 手写 Modbus-RTU 帧编解码（CRC16/组帧/解包）+ 寄存器表 + 协议自测。
"""
from .protocol import (ALLOW_VALUE, BAUD_MAP, BAUD_TO_CODE, FMT_MAP, REG_ADDR,
                       REG_ALLOW, REG_BAUD, REG_FMT, REG_RES_FLOAT,
                       REG_RES_INT, build_frame, check_frame, f32_abcd,
                       parse_exception, read_regs, u16, write_single_reg)

__all__ = [
    "ALLOW_VALUE", "BAUD_MAP", "BAUD_TO_CODE", "FMT_MAP", "REG_ADDR",
    "REG_ALLOW", "REG_BAUD", "REG_FMT", "REG_RES_FLOAT", "REG_RES_INT",
    "build_frame", "check_frame", "f32_abcd", "parse_exception", "read_regs",
    "u16", "write_single_reg",
]
