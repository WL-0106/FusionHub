# -*- coding: utf-8 -*-
"""PK9018B-8 模拟从站（TCP 串口服务器）。

没设备也能先把软件跑通：起一个假的 RS-485 网关，把 8 路温度按正弦波变化喂给上位机。

寄存器表（与协议一致）：
    0x0000 地址(高字节)+波特率码(低字节)
    0x0001~0x0008 8 通道温度修正值（有符号 16 位）
    0x0009~0x0010 8 通道温度测量值（有符号 16 位，/100 = ℃）
"""

from __future__ import annotations

import math
import socket
import struct
import threading
import time

from . import registers as R
from .protocol import BAUD_CODES, append_crc, build_read, build_write_multi
from modules.pk9015_host.core.protocol import crc16


class SimSlave:
    """PK9018B 从站：真的维护 8 路温度寄存器，不是空壳应答。"""

    def __init__(self, slave=1, baud_code=0x06):
        self.slave = slave
        self.baud_code = baud_code
        self.corr = [0] * R.CHANNEL_COUNT
        self.t0 = time.time()
        self.lock = threading.Lock()

    def _temps(self):
        """8 路温度：正弦波变化，模拟真实热电阻采集（℃）。"""
        t = time.time() - self.t0
        out = []
        for ch in range(R.CHANNEL_COUNT):
            phase = ch * 0.6
            base = 25.0 + 3.0 * (ch % 4)          # 基准 25~34℃
            amp = 8.0 + 2.0 * (ch % 3)            # 幅值
            c = base + amp * math.sin(2 * math.pi * 0.06 * t + phase)
            out.append(c)
        return out

    def _regs(self):
        regs = {R.REG_ADDR_BPS: (self.slave << 8) | self.baud_code}
        for i, v in enumerate(self.corr):
            regs[R.REG_CORR0 + i] = v & 0xFFFF
        temps = self._temps()
        for i, c in enumerate(temps):
            regs[R.REG_TEMP0 + i] = R.temp_to_raw(c)
        return regs

    def read(self, start, count):
        with self.lock:
            regs = self._regs()
            return [regs.get(start + i, 0) for i in range(count)]

    def write(self, start, values):
        with self.lock:
            vals = list(values)
            if start == R.REG_ADDR_BPS and vals:
                self.slave = (vals[0] >> 8) & 0xFF or 1
                self.baud_code = vals[0] & 0xFF
            elif start == R.REG_CORR0:
                for i, v in enumerate(vals):
                    if i < R.CHANNEL_COUNT:
                        self.corr[i] = v & 0xFFFF
            return vals


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
                    if func == 0x03:
                        need = 8
                    elif func == 0x10:
                        # 先读固定头 7 字节，再按字节计数取剩余
                        need = 7
                        if len(buf) >= 7:
                            bc = buf[6]
                            need = 7 + bc + 2
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
                    elif func == 0x10:
                        start, cnt = struct.unpack(">HH", frame[2:6])
                        vals = list(struct.unpack(">%dH" % cnt, frame[7:7 + cnt * 2]))
                        dev.write(start, vals)
                        conn.sendall(append_crc(frame[:6]))
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return handle


def build_slaves(ids=(1,), baud=9600):
    slaves = {}
    for sid in ids:
        slaves[sid] = SimSlave(slave=sid, baud_code=BAUD_CODES.get(baud, 0x06))
    return slaves
