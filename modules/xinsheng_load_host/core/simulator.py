# -*- coding: utf-8 -*-
"""新胜负载箱模拟从站 —— 没有真机也能把上位机跑通。

- Simulator：内存从站，真实维护寄存器（FC03/FC06），可选风机切换延时；
- FakeTransport：把传输接口接到内存 Simulator（自测/演示零开销）；
- TcpSimServer：RTU over TCP 假从站（裸 RTU 帧，无 MBAP），供「模拟从站」链路使用。

注意：模拟器行为 ≠ 真机（不模拟高温报警/延时启停/卸载的真实负载效果）。
"""
from __future__ import annotations

import socket
import threading
import time

from .modbus import ProtocolError, append_crc, crc16
from .registers import REGS


class Simulator:
    """内存从站：真实维护寄存器（FC03/FC06），可选风机切换延时。"""

    def __init__(self, switch_delay: float = 0.0):
        self.regs = {r.addr: 0 for r in REGS}
        self.regs[5] = 1          # 急停默认"正常"
        self.switch_delay = switch_delay
        self._fan_target = 0
        self._fan_t0 = 0.0
        self.frames = []          # (tx, rx) 供自测断言

    def _get(self, addr):
        if addr == 2 and self.switch_delay > 0:
            if time.time() - self._fan_t0 < self.switch_delay:
                return 1 - self._fan_target
            return self._fan_target
        return self.regs.get(addr, 0)

    def handle(self, tx: bytes) -> bytes:
        if len(tx) < 8:
            return b""
        slave, fc = tx[0], tx[1]
        if crc16(tx[:-2]) != (tx[-2] | (tx[-1] << 8)):
            return b""
        if fc == 0x03:
            addr = (tx[2] << 8) | tx[3]
            count = (tx[4] << 8) | tx[5]
            if count < 1 or count > 125:
                return append_crc(bytes((slave, 0x83, 0x02)))
            vals = []
            for i in range(count):
                if addr + i not in self.regs:
                    return append_crc(bytes((slave, 0x83, 0x02)))
                vals.append(self._get(addr + i))
            body = bytes((slave, 0x03, 2 * count))
            for v in vals:
                body += bytes(((v >> 8) & 0xFF, v & 0xFF))
            rx = append_crc(body)
        elif fc == 0x06:
            addr = (tx[2] << 8) | tx[3]
            value = (tx[4] << 8) | tx[5]
            if addr not in self.regs:
                return append_crc(bytes((slave, 0x86, 0x02)))
            if addr == 1:
                self._fan_target, self._fan_t0 = value, time.time()
                if self.switch_delay == 0:
                    self.regs[2] = value
            self.regs[addr] = value
            rx = append_crc(tx[:-2])
        else:
            rx = append_crc(bytes((slave, (fc | 0x80) & 0xFF, 0x01)))
        self.frames.append((tx, rx))
        return rx


class FakeTransport:
    """把传输接口接到内存 Simulator，供自测/演示。"""

    def __init__(self, sim: Simulator, latency: float = 0.0):
        self.sim = sim
        self.latency = latency

    def close(self):
        pass

    def exchange(self, frame: bytes, want: int, timeout: float = 0.6) -> bytes:
        if self.latency:
            time.sleep(self.latency)
        rx = self.sim.handle(frame)
        if not rx:
            raise ProtocolError("设备无响应（超时）", "timeout")
        time.sleep(0.005)
        return rx


class TcpSimServer:
    """RTU over TCP 假从站：裸 RTU 帧透传（无 MBAP），每连接单会话。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 5026,
                 switch_delay: float = 0.0):
        self.host = host
        self.port = port
        self.sim = Simulator(switch_delay)
        self._sock = None
        self._thread = None
        self._stop = threading.Event()

    def start(self) -> "TcpSimServer":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(4)
        self._sock.settimeout(0.3)
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name="xinsheng-tcp-sim")
        self._thread.start()
        return self

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._client(conn)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def _client(self, conn: socket.socket):
        buf = bytearray()
        conn.settimeout(0.3)
        while not self._stop.is_set():
            try:
                data = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if not data:
                return
            buf += data
            while True:
                frame = self._extract(buf)
                if not frame:
                    break
                rx = self.sim.handle(bytes(frame))
                del buf[:len(frame)]
                if rx:
                    try:
                        conn.sendall(rx)
                    except OSError:
                        return

    @staticmethod
    def _extract(buf: bytearray):
        """从缓冲区切出一帧 RTU（功能码 03/06 定长 8 字节）。"""
        while len(buf) >= 8:
            fc = buf[1]
            need = 8 if fc in (0x03, 0x06) else 5
            if len(buf) < need:
                return None
            frame = bytes(buf[:need])
            if crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8)):
                return frame
            del buf[0]   # CRC 不对：跳 1 字节重同步
        return None

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread:
            try:
                self._thread.join(timeout=2.0)
            except Exception:
                pass
            self._thread = None
