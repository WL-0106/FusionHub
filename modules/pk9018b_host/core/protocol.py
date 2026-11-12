# -*- coding: utf-8 -*-
"""PK9018B-8 设备对象（Modbus RTU，复用同族协议栈底层）。

底层 CRC/报文编解码/传输层 直接复用 pk9015_host.core.protocol
（同族 PK 系列设备，协议栈同源），本文件只定义 PK9018B 的语义接口。

寄存器（功能码 03H 读 / 10H 写）：
    0x0000  地址+波特率（高 8 位地址，低 8 位波特率码）
    0x0001~0x0008  8 通道温度修正值（有符号 16 位，/100 = ℃）
    0x0009~0x0010  8 通道温度测量值（有符号 16 位，/100 = ℃）
功能码 10H（写多寄存器）：
    写 0x0000 = 新地址 + 波特率码（1 个寄存器）
    写 0x0001 = 8 通道修正值（8 个寄存器）
"""

from __future__ import annotations

import struct
import threading
import time

from modules.pk9015_host.core.protocol import (
    ProtocolError, SerialTransport, TcpTransport,
    crc16, append_crc, hexs, parse_read_response,
)

from . import registers as R


BAUD_CODES = R.BAUD_CODES
BAUD_BY_CODE = R.BAUD_BY_CODE


def build_read(slave: int, start: int, count: int) -> bytes:
    if not 1 <= count <= 125:
        raise ProtocolError("读取数量 %d 非法（Modbus 允许 1~125）" % count)
    return append_crc(struct.pack(">BBHH", slave & 0xFF, 0x03, start, count))


def build_write_multi(slave: int, start: int, values) -> bytes:
    """功能码 10H 写多寄存器。"""
    regs = list(values)
    if not 1 <= len(regs) <= 123:
        raise ProtocolError("写入寄存器数 %d 非法（Modbus 允许 1~123）" % len(regs))
    body = struct.pack(">BBHHB", slave & 0xFF, 0x10, start, len(regs), len(regs) * 2)
    for v in regs:
        body += struct.pack(">H", v & 0xFFFF)
    return append_crc(body)


def expect_len_for_read(reg_count: int) -> int:
    return 5 + 2 * reg_count


def parse_write_multi_response(frame: bytes, sent: bytes) -> None:
    """解析 FC10 响应（回显起始地址+数量）。"""
    if len(frame) < 8:
        raise ProtocolError("写响应过短（%d 字节）" % len(frame))
    if frame[1] & 0x80:
        from modules.pk9015_host.core.protocol import ModbusException
        raise ModbusException(frame[1] & 0x7F, frame[2] if len(frame) > 2 else 0)
    if frame[1] != 0x10:
        raise ProtocolError("写响应功能码不匹配：期望 10H，收到 %02XH" % frame[1])
    body, got = frame[:-2], struct.unpack("<H", frame[-2:])[0]
    if crc16(body) != got:
        raise ProtocolError("写响应 CRC 校验失败")
    if frame[:6] != sent[:6]:
        raise ProtocolError("写响应回显与请求不一致")


class PK9018B:
    """锐测 PK9018B-8 8 通道热电阻温度采集模块。"""

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

    def write_registers(self, start: int, values, timeout: float = None) -> None:
        with self._lock:
            frame = build_write_multi(self.slave, start, values)
            rx = self._exchange(frame, 8, timeout)
        parse_write_multi_response(rx, frame)

    def ping(self, timeout: float = 0.35) -> bool:
        try:
            self.read_registers(R.REG_TEMP0, 1, timeout=timeout)
            return True
        except Exception:
            return False

    # ---------------- 高层 ----------------

    def read_temperatures(self, timeout: float = None) -> list:
        """读 8 通道温度原始值（16 位有符号列表，长度 8）。"""
        return self.read_registers(R.REG_TEMP0, R.CHANNEL_COUNT, timeout=timeout)

    def read_config(self, timeout: float = None) -> dict:
        r0 = self.read_registers(R.REG_ADDR_BPS, 1, timeout=timeout)
        word = r0[0]
        return {
            "addr": (word >> 8) & 0xFF,
            "baud_code": word & 0xFF,
            "baud": BAUD_BY_CODE.get(word & 0xFF, 9600),
        }

    def read_corrections(self, timeout: float = None) -> list:
        """读 8 通道修正值原始值。"""
        return self.read_registers(R.REG_CORR0, R.CORR_COUNT, timeout=timeout)

    def save_corrections(self, values, timeout: float = None) -> None:
        """写 8 通道修正值（原始 16 位列表）。"""
        if len(values) != R.CORR_COUNT:
            raise ProtocolError("修正值需 %d 个，收到 %d 个" % (R.CORR_COUNT, len(values)))
        self.write_registers(R.REG_CORR0, values, timeout=timeout)

    def save_address_baud(self, addr: int, baud: int) -> None:
        if not 1 <= addr <= 255:
            raise ProtocolError("模块地址必须在 1~255")
        if baud not in BAUD_CODES:
            raise ProtocolError("波特率 %s 不在设备支持列表（1200/2400/4800/9600/19200）" % baud)
        value = (addr << 8) | BAUD_CODES[baud]
        self.write_registers(R.REG_ADDR_BPS, [value])

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
