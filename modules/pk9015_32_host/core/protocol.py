# -*- coding: utf-8 -*-
"""PK9015-32 设备对象（Modbus RTU，复用同族协议栈底层）。

底层 CRC/报文编解码/传输层 直接复用 pk9015_host.core.protocol
（同族 PK 系列设备，协议栈同源），本文件只定义 PK9015-32 的语义接口。

寄存器（功能码 03H 读 / 06H 写）：
    0x0000  地址+波特率（高 8 位地址，低 8 位波特率码）
    0x0001  类型（1=电流，其他=电压）
    0x0002  量程（值 × 100 = 实际量程，50mA → 存 5000）
    0x0003~0x0022  32 通道数据（无符号 16 位）
    0x0023~ 修正值
"""

from __future__ import annotations

import struct
import threading
import time

from modules.pk9015_host.core.protocol import (
    ProtocolError, SerialTransport, TcpTransport,
    append_crc, hexs, parse_read_response, parse_echo_response,
)

from . import registers as R


BAUD_CODES = R.BAUD_CODES
BAUD_BY_CODE = R.BAUD_BY_CODE


def build_read(slave: int, start: int, count: int) -> bytes:
    if not 1 <= count <= 125:
        raise ProtocolError("读取数量 %d 非法（Modbus 允许 1~125）" % count)
    return append_crc(struct.pack(">BBHH", slave & 0xFF, 0x03, start, count))


def build_write_single(slave: int, addr: int, value: int) -> bytes:
    return append_crc(struct.pack(">BBHH", slave & 0xFF, 0x06, addr & 0xFFFF, value & 0xFFFF))


def expect_len_for_read(reg_count: int) -> int:
    return 5 + 2 * reg_count


class PK9015_32:
    """锐测 PK9015-32 32 通道模拟量输入模块（电流/电压 + CT 变比）。"""

    def __init__(self, transport, slave: int = 1, trace=None):
        self.t = transport
        self.slave = int(slave)
        self.trace = trace
        self._lock = threading.Lock()

    def _exchange(self, frame: bytes, want: int, timeout: float = None, retry: int = 1):
        last = None
        for attempt in range(retry + 1):
            try:
                rx = self.t.exchange(frame, want, timeout)
                if self.trace:
                    self.trace(frame, rx)
                return rx
            except ProtocolError as e:
                last = e
                if ("CRC" in str(e) or "0 字节" in str(e)) and attempt < retry:
                    time.sleep(0.05)
                    continue
                raise
        raise last

    def read_registers(self, start: int, count: int, timeout: float = None) -> list:
        with self._lock:
            frame = build_read(self.slave, start, count)
            rx = self._exchange(frame, expect_len_for_read(count), timeout)
        return parse_read_response(rx, count)

    def write_register(self, addr: int, value: int, timeout: float = None) -> int:
        with self._lock:
            frame = build_write_single(self.slave, addr, value)
            rx = self._exchange(frame, 8, timeout)
        return parse_echo_response(rx, frame)

    def ping(self, timeout: float = 0.35) -> bool:
        try:
            self.read_registers(R.REG_TYPE, 1, timeout=timeout)
            return True
        except Exception:
            return False

    # ---------------- 高层 ----------------

    def read_channels(self, timeout: float = None) -> list:
        """读 32 通道原始值（无符号 16 位列表，长度 32）。"""
        return self.read_registers(R.REG_DATA_START, R.CHANNEL_COUNT, timeout=timeout)

    def read_config(self, timeout: float = None) -> dict:
        """读配置：地址+波特率、类型、量程。"""
        r0 = self.read_registers(R.REG_ADDR_BPS, 3, timeout=timeout)
        word = r0[0]
        return {
            "addr": (word >> 8) & 0xFF,
            "baud_code": word & 0xFF,
            "baud": BAUD_BY_CODE.get(word & 0xFF, 9600),
            "type": r0[1] & 0xFF,
            "type_label": "电流" if (r0[1] & 0xFF) == R.TYPE_CURRENT else "电压",
            "range": float(r0[2] & 0xFFFF) / 100.0,
        }

    def read_corrections(self, count: int = 32, timeout: float = None) -> list:
        """读修正值原始值。"""
        return self.read_registers(R.REG_CORR_START, count, timeout=timeout)

    def save_correction(self, ch: int, raw: int, timeout: float = None) -> None:
        self.write_register(R.REG_CORR_START + ch, raw & 0xFFFF, timeout=timeout)

    def save_address_baud(self, addr: int, baud: int) -> None:
        if not 1 <= addr <= 255:
            raise ProtocolError("模块地址必须在 1~255")
        if baud not in BAUD_CODES:
            raise ProtocolError("波特率 %s 不在设备支持列表（1200/2400/4800/9600/19200）" % baud)
        value = (addr << 8) | BAUD_CODES[baud]
        self.write_register(R.REG_ADDR_BPS, value)

    def set_slave(self, slave: int) -> None:
        self.slave = int(slave)

    def close(self) -> None:
        self.t.close()


def search_slaves(transport_factory, start: int, end: int, on_hit=None, should_stop=None) -> dict:
    found, tested = [], 0
    lo, hi = sorted((int(start), int(end)))
    for slave in range(max(1, lo), min(255, hi) + 1):
        if should_stop is not None and should_stop():
            break
        tested += 1
        dev = None
        try:
            dev = transport_factory(slave)
            if dev.ping(timeout=0.30):
                item = {"slave": slave}
                found.append(item)
                if on_hit:
                    on_hit(item)
        except Exception:
            pass
        finally:
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass
    return {"found": found, "tested": tested}
