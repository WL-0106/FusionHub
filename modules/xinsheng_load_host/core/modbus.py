# -*- coding: utf-8 -*-
"""新胜负载箱 Modbus RTU 栈：CRC16 / 串口与 TCP 传输 / FC03·FC06 客户端 / 写后确认。

RTU over TCP 为裸 RTU 帧（无 MBAP 头），与串口帧格式完全一致；
TCP 断线后发送时自动重连一次；每帧失败自动重试 1 次（读/写均幂等）。
"""
from __future__ import annotations

import socket
import time


def crc16(data: bytes) -> int:
    """Modbus CRC16，多项式 0xA001；发送时低字节在前。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc(frame: bytes) -> bytes:
    c = crc16(frame)
    return frame + bytes((c & 0xFF, (c >> 8) & 0xFF))


def hexs(data: bytes) -> str:
    return data.hex(" ").upper()


def _exc_text(code):
    return {1: "非法功能(01)", 2: "非法地址(02)", 3: "非法数据值(03)",
            4: "设备故障(04)"}.get(code, "异常码 %02X" % code)


class ProtocolError(Exception):
    """协议/链路错误统一包装，msg 为中文可直接展示。kind: io/timeout/exception/parse"""

    def __init__(self, msg, kind="io"):
        super().__init__(msg)
        self.kind = kind
        self.msg = msg


# ---------------------------------------------------------------- 串口传输层
class SerialTransport:
    def __init__(self, port, baud=9600, bytesize=8, parity="N", stopbits=1, timeout=0.6):
        import serial  # 延迟导入：纯网口用户无需装 pyserial
        self.ser = serial.Serial(
            port=port, baudrate=baud, bytesize=bytesize, parity=parity,
            stopbits=stopbits, timeout=timeout, write_timeout=1.0)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def exchange(self, frame: bytes, want: int, timeout: float = 0.6) -> bytes:
        """发送一帧并按期望长度累计读取。不调 flush()（Windows 上可能永久阻塞）。"""
        try:
            self.ser.reset_input_buffer()
            self.ser.write(frame)
        except Exception as e:
            raise ProtocolError("串口写入失败：%s" % e, "io")
        buf = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline:
            n = self.ser.in_waiting
            if n:
                buf += self.ser.read(n)
                if len(buf) >= want:
                    break
                deadline = min(deadline, time.time() + 0.15)  # 收到部分数据后缩短窗口
            else:
                time.sleep(0.005)
        if not buf:
            raise ProtocolError("设备无响应（超时）", "timeout")
        return bytes(buf)

    @staticmethod
    def list_ports():
        import serial.tools.list_ports
        return [p.device for p in serial.tools.list_ports.comports()]


# ---------------------------------------------------------------- 网络传输层
class TcpTransport:
    """RTU over TCP：串口服务器/透传模块场景，帧格式与串口 RTU 完全一致
    （裸 RTU 帧，无 MBAP 头），只是传输层换成 TCP。"""

    def __init__(self, host, port, timeout=0.6):
        self.addr = (host, int(port))
        self.timeout = timeout
        self.sock = None
        self._connect()

    def _connect(self):
        self.sock = socket.create_connection(self.addr, timeout=3.0)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def exchange(self, frame: bytes, want: int, timeout: float = 0.6) -> bytes:
        if self.sock is None:
            try:
                self._connect()
            except OSError as e:
                self.sock = None
                raise ProtocolError("网络重连失败：%s" % e, "io")
        try:
            self.sock.sendall(frame)
        except OSError as e:
            self.close()
            raise ProtocolError("网络发送失败：%s" % e, "io")
        buf = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.sock.settimeout(max(0.02, deadline - time.time()))
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as e:
                self.close()
                raise ProtocolError("网络接收失败：%s" % e, "io")
            if not data:
                self.close()
                raise ProtocolError("连接已断开（对端关闭）", "io")
            buf += data
            if len(buf) >= want:
                break
            deadline = min(deadline, time.time() + 0.15)
        if not buf:
            raise ProtocolError("设备无响应（超时）", "timeout")
        return bytes(buf)


# ---------------------------------------------------------------- 客户端
class LoadBankClient:
    """FC03 读 / FC06 写。每帧失败自动重试 1 次（读/写均幂等）。"""

    def __init__(self, transport, slave=1, trace=None):
        self.t = transport
        self.slave = slave
        self.trace = trace or (lambda tx, rx, note="": None)

    def _check_crc(self, rx):
        if len(rx) < 4:
            raise ProtocolError("响应帧过短: %s" % rx.hex().upper(), "parse")
        data, crc_rx = rx[:-2], rx[-2] | (rx[-1] << 8)
        if crc16(data) != crc_rx:
            raise ProtocolError("CRC 校验失败: %s" % rx.hex().upper(), "parse")

    def _exchange(self, frame, want, timeout):
        last = None
        for attempt in (0, 1):
            try:
                rx = self.t.exchange(frame, want, timeout)
            except ProtocolError as e:
                self.trace(frame, b"", "IO 错误：%s" % e.msg)
                last = e
                if e.kind in ("timeout", "io") and attempt == 0:
                    continue
                if e.kind == "io":
                    raise ProtocolError("链路错误：%s" % e.msg, "io")
                raise
            self.trace(frame, rx)
            if not rx:
                last = ProtocolError("设备无响应（超时）", "timeout")
                if attempt == 0:
                    continue
                raise last
            self._check_crc(rx)
            if rx[0] != frame[0]:
                raise ProtocolError("响应从站地址不符: %02X" % rx[0], "parse")
            f = rx[1]
            if f & 0x80:
                code = rx[2] if len(rx) > 2 else 0
                raise ProtocolError("设备返回异常：%s" % _exc_text(code), "exception")
            return rx
        raise last or ProtocolError("设备无响应（已重试）", "timeout")

    def read_regs(self, addr, count, slave=None):
        s = self.slave if slave is None else slave
        if not (1 <= count <= 125):
            raise ProtocolError("读取数量非法: %d" % count, "parse")
        frame = append_crc(bytes((s, 0x03, (addr >> 8) & 0xFF, addr & 0xFF,
                                  (count >> 8) & 0xFF, count & 0xFF)))
        rx = self._exchange(frame, 5 + 2 * count, 0.6)
        if rx[1] != 0x03 or rx[2] != 2 * count:
            raise ProtocolError("读响应格式不符: %s" % rx.hex().upper(), "parse")
        return [int.from_bytes(rx[3 + 2 * i:5 + 2 * i], "big") for i in range(count)]

    def write_reg(self, addr, value, slave=None):
        s = self.slave if slave is None else slave
        if not (0 <= value <= 0xFFFF):
            raise ProtocolError("写入值超出 16 位: %d" % value, "parse")
        frame = append_crc(bytes((s, 0x06, (addr >> 8) & 0xFF, addr & 0xFF,
                                  (value >> 8) & 0xFF, value & 0xFF)))
        rx = self._exchange(frame, 8, 0.6)
        if rx[1] != 0x06 or rx[2:6] != frame[2:6]:
            raise ProtocolError("写应答与请求不符: %s" % rx.hex().upper(), "parse")
        return True

    def read_reg(self, addr, slave=None):
        return self.read_regs(addr, 1, slave)[0]

    def ping(self, slave=None):
        try:
            self.read_regs(2, 2, slave)
            return True
        except Exception:
            return False


def confirm_fan(cli, on, reads=8, gap=0.25, slave=None):
    """开/关风机后用**状态寄存器2**（而非寄存器1回显）确认，输出回路切换
    有延时，需循环回读。返回 (confirmed, 状态值)。"""
    cli.write_reg(1, 1 if on else 0, slave)
    cur = None
    for i in range(reads):
        if i:
            time.sleep(gap)
        try:
            cur = cli.read_reg(2, slave)
        except Exception:
            continue
        if bool(cur) == bool(on):
            return True, cur
    return False, cur


def write_and_confirm(client, addr, value, reads=6, gap=0.2, slave=None):
    """写后循环回读确认。返回 (confirmed, 最终回读值)。

    设备输出回路切换有延时：写应答 ≠ 已到位。超时未一致时如实上报，
    由轮询兜底刷新。
    """
    client.write_reg(addr, value, slave)
    cur = None
    for i in range(reads):
        if i:
            time.sleep(gap)
        try:
            cur = client.read_reg(addr, slave)
        except Exception:
            continue
        if cur == value:
            return True, cur
    return False, cur
