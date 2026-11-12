# -*- coding: utf-8 -*-
"""PK9015-32 模拟从站（TCP 串口服务器）。

没设备也能先把软件跑通：起一个假的 RS-485 网关，把 32 路电流按正弦波变化喂给上位机。

寄存器表（与协议一致）：
    0x0000 地址(高字节)+波特率码(低字节)
    0x0001 类型（1=电流）、0x0002 量程（值 × 100 = 实际量程）
    0x0003~0x0022 32 通道数据（无符号 16 位）
    0x0023~ 修正值
"""

from __future__ import annotations

import math
import socket
import struct
import threading
import time

from . import registers as R
from .protocol import BAUD_CODES, append_crc, build_read, build_write_single
from modules.pk9015_host.core.protocol import crc16


class SimSlave:
    """PK9015-32 从站：真的维护 32 路通道寄存器，不是空壳应答。"""

    def __init__(self, slave=1, baud_code=0x06, rng=R.DEFAULT_RANGE):
        self.slave = slave
        self.baud_code = baud_code
        self.rng = rng
        self.t0 = time.time()
        self.lock = threading.Lock()

    def _channels(self):
        """32 路通道：正弦波变化，量程内浮动。"""
        t = time.time() - self.t0
        out = []
        for ch in range(R.CHANNEL_COUNT):
            phase = ch * 0.3
            amp = 0.35 + 0.05 * (ch % 5)
            base = 0.55 + 0.03 * (ch % 7)
            frac = base + amp * math.sin(2 * math.pi * 0.07 * t + phase)
            frac = max(0.0, min(1.0, frac))
            raw = int(round(frac * R.SCALE))
            out.append(raw & 0xFFFF)
        return out

    def _regs(self):
        regs = {
            R.REG_ADDR_BPS: (self.slave << 8) | self.baud_code,
            R.REG_TYPE: R.TYPE_CURRENT,
            R.REG_RANGE: int(round(self.rng * 100.0)),
        }
        for i, raw in enumerate(self._channels()):
            regs[R.REG_DATA_START + i] = raw
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
            elif addr == R.REG_TYPE:
                pass
            elif addr == R.REG_RANGE:
                self.rng = float(value & 0xFFFF) / 100.0
            return value


def make_handler(slaves, verbose=True):
    def handle(conn, addr):
        log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
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
                while len(buf) >= 8:
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
                    if crc16(frame[:-2]) != crc_rx:
                        continue
                    dev = slaves.get(slave_id)
                    if dev is None:
                        continue
                    if func == 0x03:
                        start, count = struct.unpack(">HH", frame[2:6])
                        if count < 1 or count > 125:
                            conn.sendall(append_crc(bytes([slave_id, 0x83, 0x02])))
                            continue
                        regs = dev.read(start, count)
                        body = bytes([slave_id, 0x03, count * 2])
                        for r in regs:
                            body += struct.pack(">H", r & 0xFFFF)
                        conn.sendall(append_crc(body))
                    elif func == 0x06:
                        addr_w, val = struct.unpack(">HH", frame[2:6])
                        dev.write(addr_w, val)
                        conn.sendall(append_crc(frame[:6]))
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return handle


def build_slaves(ids=(1,), baud=9600, rng=R.DEFAULT_RANGE):
    slaves = {}
    for sid in ids:
        slaves[sid] = SimSlave(slave=sid, baud_code=BAUD_CODES.get(baud, 0x06), rng=rng)
    return slaves
