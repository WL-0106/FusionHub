# -*- coding: utf-8 -*-
"""RU 灵巧系列电源上位机 —— 协议库。"""

from .crc import crc16, append_crc, check_crc
from .modbus import (
    ModbusClient,
    ModbusError,
    TransportError,
    SerialTransport,
    TcpTransport,
    describe_serial_error,
    verify_manual_examples,
    hexs,
)
from .device import RUDevice

__version__ = "1.5.0"
__all__ = [
    "crc16", "append_crc", "check_crc",
    "ModbusClient", "ModbusError", "TransportError",
    "SerialTransport", "TcpTransport", "describe_serial_error",
    "verify_manual_examples", "hexs", "RUDevice",
]
