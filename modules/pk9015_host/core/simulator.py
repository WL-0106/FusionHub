# -*- coding: utf-8 -*-
"""PK9015 模拟从站（TCP 串口服务器）。

没设备也能先把软件跑通：起一个假的 RS-485 网关，把 12 路电流按正弦波变化喂给上位机。

寄存器表（与反推协议一致）：
    0x0000 地址(高字节)+波特率码(低字节)
    0x0003~0x000E 12 路电流（16 位无符号，raw/10000 = A）
    0x02BE 量程设置（0=0-20mA、1=4-20mA、2=0-10V）
"""

from __future__ import annotations

import math
import socket
import struct
import threading
import time

from . import registers as R
from .protocol import BAUD_CODES, append_crc, build_read, build_write_single


class SimSlave:
    """PK9015 从站：真的维护 12 路电流寄存器，不是空壳应答。"""

    def __init__(self, slave=1, baud_code=0x06, range_code=R.RANGE_0_20MA):
        self.slave = slave
        self.baud_code = baud_code
        self.range_code = range_code
        self.t0 = time.time()
        self.lock = threading.Lock()

    def _currents(self):
        """12 路电流：正弦波变化，量程内浮动，模拟真实采集。"""
        t = time.time() - self.t0
        out = []
        for ch in range(R.CHANNEL_COUNT):
            # 每路相位不同、幅值不同，满量程 20mA 对应 raw=20000
            phase = ch * 0.5
            amp = 0.35 + 0.05 * (ch % 5)      # 幅值占满量程比例
            base = 0.55 + 0.03 * (ch % 7)     # 基准占满量程比例
            frac = base + amp * math.sin(2 * math.pi * 0.08 * t + phase)
            frac = max(0.0, min(1.0, frac))
            raw = int(round(frac * R.CURRENT_SCALE))
            out.append(raw & 0xFFFF)
        return out

    def _regs(self):
        # 维护一个足够大的寄存器空间，0x0000 和 0x02BE 可读写
        regs = {R.REG_ADDR_BPS: (self.slave << 8) | self.baud_code,
                R.REG_RANGE: self.range_code}
        cur = self._currents()
        for i, v in enumerate(cur):
            regs[R.REG_I0 + i] = v
        return regs

    def read(self, start, count):
        with self.lock:
            regs = self._regs()
            return [regs.get(start + i, 0) for i in range(count)]

    def write(self, addr, value):
        with self.lock:
            if addr == R.REG_ADDR_BPS:
                self.slave = (value >> 8) & 0xFF or 1
                self.baud_code = value & 0xFF
            elif addr == R.REG_RANGE:
                self.range_code = value & 0xFF
            return value


def make_handler(slaves, verbose=True):
    def handle(conn, addr):
        log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
        log("[模拟器] 客户端接入 %s" % (addr,))
        conn.settimeout(0.5)
        buf = bytearray()
        try:
            while True:
                try:
                    chunk = conn.recv(512)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 2:
                    slave_id, func = buf[0], buf[1]
                    if func in (0x03, 0x06):
                        need = 8
                    else:
                        buf.clear()
                        break
                    if len(buf) < need:
                        break
                    frame = bytes(buf[:need])
                    del buf[:need]
                    crc_rx = struct.unpack("<H", frame[-2:])[0]
                    from .protocol import crc16
                    if crc16(frame[:-2]) != crc_rx:
                        log("[模拟器] CRC 错误，丢弃: %s" % frame.hex())
                        continue
                    dev = slaves.get(slave_id)
                    if dev is None:
                        log("[模拟器] 地址 %d 不在线，保持静默" % slave_id)
                        continue
                    if func == 0x03:
                        start, count = struct.unpack(">HH", frame[2:6])
                        if count < 1 or count > 125 or start + count > 0x1000:
                            conn.sendall(append_crc(bytes([slave_id, 0x83, 0x02])))
                            continue
                        regs = dev.read(start, count)
                        body = bytes([slave_id, 0x03, count * 2])
                        for r in regs:
                            body += struct.pack(">H", r & 0xFFFF)
                        conn.sendall(append_crc(body))
                        log("[模拟器] 03H addr=%d(0x%04X) count=%d" % (slave_id, start, count))
                    elif func == 0x06:
                        addr_w, val = struct.unpack(">HH", frame[2:6])
                        dev.write(addr_w, val)
                        conn.sendall(append_crc(frame[:6]))
                        log("[模拟器] 06H addr=%d(0x%04X) <- 0x%04X" % (slave_id, addr_w, val))
        finally:
            try:
                conn.close()
            except Exception:
                pass
            log("[模拟器] 客户端断开")
    return handle


def build_slaves(ids=(1,), baud=9600, range_code=R.RANGE_0_20MA):
    slaves = {}
    for sid in ids:
        slaves[sid] = SimSlave(
            slave=sid,
            baud_code=BAUD_CODES.get(baud, 0x06),
            range_code=range_code,
        )
    return slaves
