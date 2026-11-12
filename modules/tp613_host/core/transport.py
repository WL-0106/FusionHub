# -*- coding: utf-8 -*-
"""TP613 传输层：串口(RS485) / TCP 网口 / 内置模拟从站。

三者接口一致（connect/disconnect/send/receive/is_connected），
供上层 CommThread 透明切换；语义与原上位机 SerialConnection/TcpConnection 一致。
"""
from __future__ import annotations

import socket
import time

try:
    import serial  # pyserial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

from .protocol import (BASIC_PARAMS, ENERGY_PARAMS, ModbusRTU, crc16_modbus)

SIM_PORT_NAME = '『模拟从站』(无需硬件)'


class SerialConnection:
    """真实串口（pyserial）。"""

    def __init__(self, port, baudrate=9600, bytesize=8, stopbits=1, parity='N'):
        self.port, self.baudrate = port, baudrate
        self.bytesize, self.stopbits, self.parity = bytesize, stopbits, parity
        self.ser = None

    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def connect(self):
        if serial is None:
            raise RuntimeError('未安装 pyserial 库')
        self.ser = serial.Serial(
            port=self.port, baudrate=self.baudrate, bytesize=self.bytesize,
            stopbits=self.stopbits, parity=self.parity,
            timeout=0.1, write_timeout=1.0)

    def disconnect(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def send(self, data: bytes) -> int:
        return self.ser.write(data)

    def receive(self, timeout: float = 1.0) -> bytes:
        deadline = time.time() + timeout
        buf = b''
        while time.time() < deadline:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk
                if len(buf) >= 5:
                    # 读响应长度可由第3字节推出，尽量收满后返回
                    need = 3 + buf[2] + 2 if buf[1] == 3 else 8
                    if buf[1] & 0x80:
                        need = 5
                    if len(buf) >= need:
                        return buf
            else:
                time.sleep(0.05)
        return buf


class TcpConnection:
    """TCP 网口（Modbus-RTU over TCP 透传）。"""

    def __init__(self, ip, port=502):
        self.ip, self.port = ip, port
        self.sock = None

    def is_connected(self) -> bool:
        return self.sock is not None

    def connect(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3.0)
        s.connect((self.ip, self.port))
        s.settimeout(0.1)
        self.sock = s

    def disconnect(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def send(self, data: bytes) -> int:
        self.sock.sendall(data)
        return len(data)

    def receive(self, timeout: float = 1.0) -> bytes:
        deadline = time.time() + timeout
        buf = b''
        self.sock.settimeout(0.1)
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                chunk = b''
            if chunk:
                buf += chunk
                if len(buf) >= 5:
                    need = 3 + buf[2] + 2 if buf[1] == 3 else 8
                    if buf[1] & 0x80:
                        need = 5
                    if len(buf) >= need:
                        return buf
            else:
                time.sleep(0.05)
        return buf


class _SimMeter:
    """TP613 模拟从站内部状态（Modbus 从机，FLOAT 电量随时间轻微波动）。"""

    def __init__(self, slave=1):
        self.slave = slave
        self.regs = {}
        # 电量参数初值（合理三相工况）
        base = {'Uab': 380.0, 'Ubc': 381.0, 'Uca': 379.5, 'ULLAvg': 380.2,
                'Uan': 220.0, 'Ubn': 219.5, 'Ucn': 220.5, 'ULNAvg': 220.0,
                'Ia': 5.120, 'Ib': 5.080, 'Ic': 5.150, 'In': 0.020,
                'F': 50.00, 'PF': 0.985, 'P': 3.420, 'Q': 0.580, 'S': 3.470}
        for key, _n, _u, _f, addr in BASIC_PARAMS:
            self.set_float(addr, base.get(key, 0.0))
        self.set_float(160, 1234.56)   # Ep
        self.set_float(162, 234.56)    # Eq
        self.set_float(176, 1000.00)   # Ep_forward
        self.set_float(178, 234.56)    # Ep_reverse
        self.regs[60000] = 0
        self.regs[60002] = 0
        self._t = 0.0

    def set_float(self, addr, val):
        r0, r1 = ModbusRTU.float_to_regs(val)
        self.regs[addr] = r0
        self.regs[addr + 1] = r1

    def get_float(self, addr):
        return ModbusRTU.regs_to_float(
            [self.regs.get(addr, 0), self.regs.get(addr + 1, 0)])

    def handle(self, frame: bytes) -> bytes:
        if len(frame) < 4:
            return b''
        slave, func = frame[0], frame[1]
        recv_crc = int.from_bytes(frame[-2:], 'little')
        if recv_crc != crc16_modbus(frame[:-2]) or slave != self.slave:
            return b''
        self._t += 0.5
        if func == 3:
            start = int.from_bytes(frame[2:4], 'big')
            count = int.from_bytes(frame[4:6], 'big')
            vals = [self.regs.get(start + i, 0) for i in range(count)]
            resp = bytes((slave, 3, count * 2)) + b''.join(
                v.to_bytes(2, 'big') for v in vals)
            return resp + crc16_modbus(resp).to_bytes(2, 'little')
        if func == 6:
            resp = frame[:6]
            return resp + crc16_modbus(resp).to_bytes(2, 'little')
        if func == 16:
            start = int.from_bytes(frame[2:4], 'big')
            n = int.from_bytes(frame[4:6], 'big')
            for i in range(n):
                self.regs[start + i] = int.from_bytes(
                    frame[7 + i * 2:9 + i * 2], 'big')
            resp = frame[:6]
            return resp + crc16_modbus(resp).to_bytes(2, 'little')
        exc = bytes((slave, func | 0x80, 1))
        return exc + crc16_modbus(exc).to_bytes(2, 'little')


class SimConnection:
    """内置模拟从站传输（自测/冒烟用，无硬件可开发回归）。"""

    def __init__(self, slave=1):
        self.meter = _SimMeter(slave)
        self._buf = b''
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def connect(self):
        self._connected = True

    def disconnect(self):
        self._connected = False

    def send(self, data: bytes) -> int:
        self._buf += self.meter.handle(data)
        return len(data)

    def receive(self, timeout: float = 1.0) -> bytes:
        time.sleep(0.01)
        out, self._buf = self._buf, b''
        return out


def available_ports():
    """端口列表：模拟从站永远第一，之后是系统串口 + COM1..16 候选。"""
    ports = [(SIM_PORT_NAME, 'sim')]
    detected = set()
    if list_ports is not None:
        try:
            for p in sorted(list(list_ports.comports()), key=lambda x: x.device):
                desc = (p.description or '串口设备').strip()
                ports.append((p.device, desc))
                detected.add(p.device)
        except Exception:
            pass
    for i in range(1, 17):
        name = f'COM{i}'
        if name not in detected:
            ports.append((name, '未检测到（可选）'))
    return ports
