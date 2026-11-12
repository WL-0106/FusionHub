# -*- coding: utf-8 -*-
"""PK6011R-I 模拟从站（TCP 串口服务器）。

没设备也能先把软件跑通：起一个假的 RS-485 网关，把 12 路电流按正弦波变化喂给上位机。

用法：
    python tools/simulator.py --port 5023
    python app.py --sim 5023          # 上位机侧选 TCP:5023

模拟器行为不等于真机行为，已知边界见 README。
"""

from __future__ import annotations

import argparse
import math
import os
import socket
import struct
import sys
import threading
import time

from .protocol import BAUD_CODES, append_crc, build_read, build_write_single  # noqa: E402


class SimSlave:
    """PK6011R 单相电参数从站：真的维护寄存器，不是空壳应答。

    寄存器表（与真机一致）：
        0x0000 量程（高字节=电压量程/2，低字节=电流量程 A）
        0x0001 变比（高字节=UBB，低字节=IBB）
        0x0002 电压 U  raw/10×UBB
        0x0003 电流 I  raw/1000×IBB
        0x0004 有功 P   raw/10×UBB×IBB
        0x0005 无功 Q
        0x0006 功率因数 PF  raw/10000
        0x0007 视在 S
        0x0008 频率 F   raw/100
        0x0009~0x0010 电能（4 个 32 位）
    """

    def __init__(self, slave=1, baud_code=0x06, u_range=400, i_range=5,
                 ubb=1, ibb=1, u_v=220.0, i_a=1.5):
        self.slave = slave
        self.baud_code = baud_code
        self.u_range = u_range
        self.i_range = i_range
        self.ubb = ubb
        self.ibb = ibb
        self.u_v = u_v
        self.i_a = i_a
        self.t0 = time.time()
        self.lock = threading.Lock()

    def _regs(self):
        """按当前状态生成 17 个寄存器。"""
        u_raw = int(round(self.u_v * 10 / self.ubb))
        i_raw = int(round(self.i_a * 1000 / self.ibb))
        p_raw = int(round(self.u_v * self.i_a * 0.98 * 10 / (self.ubb * self.ibb)))
        q_raw = int(round(self.u_v * self.i_a * 0.199 * 10 / (self.ubb * self.ibb)))
        pf_raw = int(round(0.98 * 10000))
        s_raw = int(round(self.u_v * self.i_a * 10 / (self.ubb * self.ibb)))
        f_raw = int(round(50.0 * 100))
        # 电能模拟：随时间缓慢累加
        t = time.time() - self.t0
        wh = int(t * 100) & 0xFFFFFFFF
        wh_hi, wh_lo = (wh >> 16) & 0xFFFF, wh & 0xFFFF
        reg0 = ((self.u_range // 2) << 8) | self.i_range
        reg1 = (self.ubb << 8) | self.ibb
        return [
            reg0, reg1,
            u_raw, i_raw, p_raw, q_raw, pf_raw, s_raw, f_raw,
            wh_hi, wh_lo, 0, 0, 0, 0, 0, 0,
        ]

    def read(self, start, count):
        with self.lock:
            regs = self._regs()
            out = []
            for a in range(start, start + count):
                out.append(regs[a] if 0 <= a < len(regs) else 0)
            return out

    def write(self, addr, value):
        with self.lock:
            if addr == 0:
                self.slave = (value >> 8) & 0xFF
                self.baud_code = value & 0xFF
            elif addr == 1:
                self.ubb = (value >> 8) & 0xFF or 1
                self.ibb = value & 0xFF or 1
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
                        # 从站不在线：手册规定「如果出错就不发送任何信息」
                        log("[模拟器] 地址 %d 不在线，保持静默（模拟真实总线的从站行为）" % slave_id)
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
                        log("[模拟器] 03H addr=%d(0x%04X) count=%d -> %s"
                            % (slave_id, start, count, [r for r in regs][:4]))
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


def serve(port, slaves, verbose=True, once=False):
    """起服务。Windows 上用 SO_EXCLUSIVEADDRUSE，避免抢绑到僵尸进程。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        except OSError:
            pass
    srv.bind(("127.0.0.1", port))
    srv.listen(8)
    srv.settimeout(0.4)
    if verbose:
        print("[模拟器] 监听 127.0.0.1:%d，在站地址：%s"
              % (port, "、".join(str(s) for s in sorted(slaves))), flush=True)
    handler = make_handler(slaves, verbose)
    try:
        while True:
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=handler, args=(conn, addr), daemon=True)
            t.start()
            if once:
                break
    finally:
        srv.close()


def build_slaves(ids=(1,), baud=9600, u_range=400, i_range=5, ubb=1, ibb=1,
                 u_v=220.0, i_a=1.5):
    slaves = {}
    for sid in ids:
        slaves[sid] = SimSlave(
            slave=sid,
            baud_code=BAUD_CODES.get(baud, 0x06),
            u_range=u_range, i_range=i_range,
            ubb=ubb, ibb=ibb,
            u_v=u_v, i_a=i_a,
        )
    return slaves


def main():
    ap = argparse.ArgumentParser(description="PK6011R 单相电参数采集模块 模拟从站")
    ap.add_argument("--port", type=int, default=5023)
    ap.add_argument("--ids", default="1", help="在站从站地址，逗号分隔，如 1,2,3")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--u-range", type=float, default=400, help="电压量程 V")
    ap.add_argument("--i-range", type=float, default=5, help="电流量程 A")
    ap.add_argument("--ubb", type=int, default=1, help="电压变比")
    ap.add_argument("--ibb", type=int, default=1, help="电流变比")
    ap.add_argument("--u", type=float, default=220.0, help="模拟电压 V")
    ap.add_argument("--i", type=float, default=1.5, help="模拟电流 A")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    ids = tuple(int(x) for x in args.ids.split(",") if x.strip())
    serve(args.port, build_slaves(ids, args.baud, args.u_range, args.i_range,
                                  args.ubb, args.ibb, args.u, args.i),
          verbose=not args.quiet)


if __name__ == "__main__":
    main()
