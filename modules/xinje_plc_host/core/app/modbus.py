# -*- coding: utf-8 -*-
"""Modbus RTU / TCP / ASCII 客户端。

帧格式与功能码依据手册 6-2-4：
  RTU:  [站号][功能码][数据][CRC低][CRC高]
  支持功能码 01 02 03 04 05 06 0F 10
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence, Union

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # 测试环境可无 pyserial
    serial = None
    list_ports = None


# ---------------------------------------------------------------------------
# CRC16 (Modbus)
# ---------------------------------------------------------------------------

def crc16(data: bytes) -> int:
    """标准 Modbus CRC16，返回 16 位值。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def crc_bytes(data: bytes) -> bytes:
    c = crc16(data)
    return bytes((c & 0xFF, (c >> 8) & 0xFF))  # 低在前


def lrc16(data: bytes) -> int:
    """Modbus ASCII 的 LRC。"""
    return (-sum(data)) & 0xFF


# ---------------------------------------------------------------------------
# 功能码
# ---------------------------------------------------------------------------

FC_READ_COILS = 0x01
FC_READ_DISCRETE = 0x02
FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04
FC_WRITE_COIL = 0x05
FC_WRITE_REGISTER = 0x06
FC_WRITE_COILS = 0x0F
FC_WRITE_REGISTERS = 0x10


class ModbusError(Exception):
    def __init__(self, code: int, message: str = ""):
        self.code = code
        super().__init__(message or f"Modbus exception 0x{code:02X}")


class ModbusTimeout(ModbusError):
    def __init__(self, message: str = "通讯超时"):
        super().__init__(0, message)


class ModbusCRCError(ModbusError):
    def __init__(self, message: str = "CRC 校验错误"):
        super().__init__(0, message)


@dataclass
class CommStats:
    tx: int = 0
    rx: int = 0
    err: int = 0
    timeout: int = 0
    last_ok: float = 0.0
    last_err_msg: str = ""


# ---------------------------------------------------------------------------
# 传输层
# ---------------------------------------------------------------------------

class Transport:
    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def transact(self, req: bytes, timeout: float) -> bytes:
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        raise NotImplementedError


class SerialTransport(Transport):
    """Modbus RTU over RS232/RS485/USB-COM."""

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
    ):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self._ser = None
        self._lock = threading.Lock()

    def open(self) -> None:
        if serial is None:
            raise RuntimeError("缺少 pyserial，无法使用串口通讯")
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            timeout=0.02,
            write_timeout=1.0,
        )
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def transact(self, req: bytes, timeout: float) -> bytes:
        if self._ser is None:
            raise ModbusError(0, "串口未打开")
        with self._lock:
            self._ser.reset_input_buffer()
            self._ser.write(req)
            self._ser.flush()
            deadline = time.monotonic() + timeout
            buf = bytearray()
            # RTU：至少要地址+功能码+CRC = 4 字节；读响应会更长
            while time.monotonic() < deadline:
                chunk = self._ser.read(256)
                if chunk:
                    buf.extend(chunk)
                    # 简单结束判定：静默 3ms 且已有数据
                    time.sleep(0.003)
                    more = self._ser.read(256)
                    if more:
                        buf.extend(more)
                        continue
                    if len(buf) >= 4:
                        return bytes(buf)
                else:
                    time.sleep(0.002)
            if buf:
                return bytes(buf)
            raise ModbusTimeout()


class TcpTransport(Transport):
    """Modbus TCP（MBAP + PDU）。"""

    def __init__(self, host: str, port: int = 502, unit_id: int = 1):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._sock: Optional[socket.socket] = None
        self._tid = 0
        self._lock = threading.Lock()

    def open(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(3.0)
        s.connect((self.host, self.port))
        self._sock = s

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def transact(self, req_pdu: bytes, timeout: float) -> bytes:
        """req_pdu: [unit][func][data...]  或 仅 PDU（内部补 unit）。"""
        if self._sock is None:
            raise ModbusError(0, "TCP 未连接")
        with self._lock:
            self._tid = (self._tid + 1) & 0xFFFF
            # req_pdu 若已含 unit，取其 unit；否则用默认
            if req_pdu and req_pdu[0] != 0:
                unit = req_pdu[0]
                pdu = req_pdu[1:]
            else:
                unit = self.unit_id
                pdu = req_pdu
            mbap = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, unit)
            self._sock.settimeout(timeout)
            try:
                self._sock.sendall(mbap + pdu)
            except OSError as e:
                raise ModbusError(0, f"发送失败: {e}") from e

            # 读 MBAP 头 7 字节
            head = self._recv_exact(7, timeout)
            tid, proto, length, unit_r = struct.unpack(">HHHB", head)
            body = self._recv_exact(length - 1, timeout)
            return bytes([unit_r]) + body

    def _recv_exact(self, n: int, timeout: float) -> bytes:
        assert self._sock is not None
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while len(buf) < n:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise ModbusTimeout()
            self._sock.settimeout(remain)
            try:
                chunk = self._sock.recv(n - len(buf))
            except socket.timeout as e:
                raise ModbusTimeout() from e
            if not chunk:
                raise ModbusError(0, "连接已关闭")
            buf.extend(chunk)
        return bytes(buf)


# ---------------------------------------------------------------------------
# 主客户端
# ---------------------------------------------------------------------------

@dataclass
class ModbusConfig:
    mode: str = "rtu"              # rtu | tcp
    # RTU
    port: str = "COM3"
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"              # N/E/O
    stopbits: float = 1
    # TCP
    host: str = "192.168.1.10"
    tcp_port: int = 502
    # 公共
    slave_id: int = 1
    timeout: float = 0.5
    retries: int = 1


class ModbusClient:
    """统一封装 RTU/TCP，提供线圈/寄存器读写。"""

    def __init__(self, config: Optional[ModbusConfig] = None):
        self.config = config or ModbusConfig()
        self.stats = CommStats()
        self._transport: Optional[Transport] = None
        self._lock = threading.RLock()
        # 帧日志回调：fn(direction, bytes)  direction = "TX"/"RX"/"ERR"
        self.on_frame = None

    def _log_frame(self, direction: str, data: bytes) -> None:
        if self.on_frame is not None:
            try:
                self.on_frame(direction, data)
            except Exception:
                pass

    # -- 连接 ------------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._transport is not None and self._transport.is_open

    def connect(self) -> None:
        self.disconnect()
        cfg = self.config
        if cfg.mode == "tcp":
            t: Transport = TcpTransport(cfg.host, cfg.tcp_port, cfg.slave_id)
        else:
            t = SerialTransport(
                cfg.port, cfg.baudrate, cfg.bytesize, cfg.parity, cfg.stopbits
            )
        t.open()
        self._transport = t

    def disconnect(self) -> None:
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None

    # -- 帧封装 ----------------------------------------------------------
    def _build_rtu(self, pdu: bytes) -> bytes:
        frame = bytes([self.config.slave_id]) + pdu
        return frame + crc_bytes(frame)

    def _exchange(self, pdu: bytes) -> bytes:
        """发送 PDU（含功能码），返回响应 PDU（含功能码）。"""
        with self._lock:
            if not self.connected:
                raise ModbusError(0, "未连接")
            assert self._transport is not None
            is_tcp = self.config.mode == "tcp"
            if is_tcp:
                req = bytes([self.config.slave_id]) + pdu
            else:
                req = self._build_rtu(pdu)

            last_err: Optional[Exception] = None
            for attempt in range(self.config.retries + 1):
                self.stats.tx += 1
                self._log_frame("TX", req)
                try:
                    raw = self._transport.transact(req, self.config.timeout)
                    self._log_frame("RX", raw)
                    if is_tcp:
                        # raw = [unit][func][data...]
                        resp = raw[1:]
                    else:
                        if len(raw) < 4:
                            raise ModbusError(0, "响应过短")
                        body, crc_l, crc_h = raw[:-2], raw[-2], raw[-1]
                        calc = crc16(body)
                        if (calc & 0xFF) != crc_l or (calc >> 8) != crc_h:
                            self._log_frame("ERR", raw)
                            raise ModbusCRCError()
                        resp = body[1:]  # 去站号

                    if not resp:
                        raise ModbusError(0, "空响应")
                    if resp[0] & 0x80:
                        code = resp[1] if len(resp) > 1 else 0
                        self._log_frame("ERR", raw)
                        raise ModbusError(code)

                    self.stats.rx += 1
                    self.stats.last_ok = time.time()
                    return resp
                except ModbusTimeout as e:
                    self._log_frame("ERR", b"")
                    last_err = e
                    self.stats.timeout += 1
                    self.stats.err += 1
                    self.stats.last_err_msg = str(e)
                except ModbusError as e:
                    last_err = e
                    self.stats.err += 1
                    self.stats.last_err_msg = str(e)
                    raise
                except Exception as e:
                    self._log_frame("ERR", b"")
                    last_err = e
                    self.stats.err += 1
                    self.stats.last_err_msg = str(e)
            if isinstance(last_err, ModbusError):
                raise last_err
            raise ModbusError(0, f"通讯失败: {last_err}")

    # -- 位操作 ----------------------------------------------------------
    def read_coils(self, addr: int, count: int) -> list[bool]:
        """分批读线圈（01H），避免部分固件大批量返回全 0。"""
        count = max(1, min(count, 2000))
        out: list[bool] = []
        remain = count
        cur = addr
        while remain > 0:
            n = min(remain, 64)
            out.extend(self._read_bits_fc(FC_READ_COILS, cur, n))
            cur += n
            remain -= n
        return out

    def read_discrete(self, addr: int, count: int) -> list[bool]:
        """分批读离散输入（02H）。"""
        count = max(1, min(count, 2000))
        out: list[bool] = []
        remain = count
        cur = addr
        while remain > 0:
            n = min(remain, 64)
            out.extend(self._read_bits_fc(FC_READ_DISCRETE, cur, n))
            cur += n
            remain -= n
        return out

    def _read_bits_fc(self, fc: int, addr: int, count: int) -> list[bool]:
        pdu = bytes([fc]) + struct.pack(">HH", addr, count)
        resp = self._exchange(pdu)
        # 响应 PDU: [func][byte_count][data...]  byte_count 在下标 1
        if len(resp) < 2:
            raise ModbusError(0, "读位响应过短")
        n = resp[1]
        data = resp[2:2 + n]
        bits: list[bool] = []
        for i in range(count):
            byte_i, bit_i = divmod(i, 8)
            if byte_i < len(data):
                bits.append(bool(data[byte_i] & (1 << bit_i)))
            else:
                bits.append(False)
        return bits

    def write_coil(self, addr: int, value: bool) -> None:
        # 手册：ON=0x00FF, OFF=0x0000，低字节在前（线上 FF 00）
        payload = 0xFF00 if value else 0x0000
        pdu = bytes([FC_WRITE_COIL]) + struct.pack(">HH", addr, payload)
        self._exchange(pdu)

    def write_coils(self, addr: int, values: Sequence[bool]) -> None:
        """0FH 写多个线圈。即使 1 个点也真正走 0FH，不再退回 05H。"""
        count = len(values)
        if count == 0:
            return
        if count > 1968:
            raise ValueError("一次最多写 1968 个线圈")
        byte_count = (count + 7) // 8
        data = bytearray(byte_count)
        for i, v in enumerate(values):
            if v:
                data[i // 8] |= 1 << (i % 8)
        pdu = (bytes([FC_WRITE_COILS]) + struct.pack(">HH", addr, count)
               + bytes([byte_count]) + bytes(data))
        self._exchange(pdu)

    # -- 字操作 ----------------------------------------------------------
    def read_holding(self, addr: int, count: int) -> list[int]:
        count = max(1, min(count, 125))
        pdu = bytes([FC_READ_HOLDING]) + struct.pack(">HH", addr, count)
        resp = self._exchange(pdu)
        # [func][byte_count][data...]  byte_count 在下标 1
        if len(resp) < 2:
            raise ModbusError(0, "读寄存器响应过短")
        n = resp[1]
        data = resp[2:2 + n]
        regs = []
        for i in range(count):
            off = i * 2
            if off + 1 < len(data):
                regs.append(struct.unpack(">H", data[off:off + 2])[0])
            else:
                regs.append(0)
        return regs

    def read_input_regs(self, addr: int, count: int) -> list[int]:
        count = max(1, min(count, 125))
        pdu = bytes([FC_READ_INPUT]) + struct.pack(">HH", addr, count)
        resp = self._exchange(pdu)
        if len(resp) < 2:
            raise ModbusError(0, "读输入寄存器响应过短")
        n = resp[1]
        data = resp[2:2 + n]
        regs = []
        for i in range(count):
            off = i * 2
            if off + 1 < len(data):
                regs.append(struct.unpack(">H", data[off:off + 2])[0])
            else:
                regs.append(0)
        return regs

    def write_register(self, addr: int, value: int) -> None:
        value &= 0xFFFF
        pdu = bytes([FC_WRITE_REGISTER]) + struct.pack(">HH", addr, value)
        self._exchange(pdu)

    def write_registers(self, addr: int, values: Sequence[int]) -> None:
        count = len(values)
        if count == 0:
            return
        if count == 1:
            self.write_register(addr, values[0])
            return
        if count > 123:
            raise ValueError("一次最多写 123 个寄存器")
        data = b"".join(struct.pack(">H", v & 0xFFFF) for v in values)
        pdu = (bytes([FC_WRITE_REGISTERS]) + struct.pack(">HH", addr, count)
               + bytes([len(data)]) + data)
        self._exchange(pdu)

    # -- 便捷：按解析后的设备读写 ----------------------------------------
    def read_device_bits(self, addrs: Sequence[int]) -> list[bool]:
        if not addrs:
            return []
        start, end = min(addrs), max(addrs)
        span = end - start + 1
        if span <= 2000:
            bits = self.read_coils(start, span)
            return [bits[a - start] for a in addrs]
        # 跨度过大，分批
        out: list[bool] = []
        for a in addrs:
            out.append(self.read_coils(a, 1)[0])
        return out

    def read_device_words(self, addrs: Sequence[int]) -> list[int]:
        if not addrs:
            return []
        start, end = min(addrs), max(addrs)
        span = end - start + 1
        if span <= 125:
            regs = self.read_holding(start, span)
            return [regs[a - start] for a in addrs]
        out: list[int] = []
        for a in addrs:
            out.append(self.read_holding(a, 1)[0])
        return out


def list_serial_ports() -> list[str]:
    if list_ports is None:
        return []
    return [p.device for p in list_ports.comports()]
