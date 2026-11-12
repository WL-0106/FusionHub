# -*- coding: utf-8 -*-
"""
传输层抽象
==========
SCPI 上位机的物理链路统一抽象为 Transport 接口：
    SerialTransport   RS-232/USB-TTL 串口（pyserial）
    TcpTransport      LAN 直连 SCPI(默认端口 5025)
    LoopbackTransport 回环（对接模拟从站，用于自测/自动化验证）

协议栈只依赖本接口，界面不感知链路类型（界面与协议解耦）。
"""
from __future__ import annotations

import queue
import socket
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional


class TransportError(Exception):
    """链路层错误（断开、IO 失败等）。"""


class Transport(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, size: int = 1, timeout_s: float = 0.1) -> bytes: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...


class SerialTransport(Transport):
    """串口传输。参数与现场一致：波特率/校验/停止位可配。"""

    def __init__(self, port: str, baudrate: int = 9600, bytesize: int = 8,
                 parity: str = "N", stopbits: int = 1):
        self._cfg = dict(port=port, baudrate=baudrate, bytesize=bytesize,
                         parity=parity, stopbits=stopbits)
        self._ser = None

    def open(self) -> None:
        try:
            import serial  # pyserial
        except ImportError as e:
            raise TransportError("缺少 pyserial，请先 pip install pyserial") from e
        try:
            self._ser = serial.Serial(
                port=self._cfg["port"], baudrate=self._cfg["baudrate"],
                bytesize=self._cfg["bytesize"], parity=self._cfg["parity"],
                stopbits=self._cfg["stopbits"], timeout=0.1)
        except Exception as e:
            raise TransportError(f"串口打开失败 {self._cfg['port']}: {e}") from e

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def write(self, data: bytes) -> None:
        if not self.is_open:
            raise TransportError("串口未打开")
        try:
            self._ser.write(data)
        except Exception as e:
            raise TransportError(f"串口写失败: {e}") from e

    def read(self, size: int = 1, timeout_s: float = 0.1) -> bytes:
        if not self.is_open:
            raise TransportError("串口未打开")
        try:
            self._ser.timeout = timeout_s
            return self._ser.read(size)
        except Exception as e:
            raise TransportError(f"串口读失败: {e}") from e

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open


class TcpTransport(Transport):
    """LAN 直连 SCPI（raw socket，端口 5025）。"""

    def __init__(self, host: str, port: int = 5025, connect_timeout_s: float = 3.0):
        self._host, self._port = host, port
        self._cto = connect_timeout_s
        self._sock: Optional[socket.socket] = None

    def open(self) -> None:
        try:
            s = socket.create_connection((self._host, self._port), self._cto)
            s.settimeout(0.1)
            self._sock = s
        except Exception as e:
            raise TransportError(f"LAN 连接失败 {self._host}:{self._port}: {e}") from e

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def write(self, data: bytes) -> None:
        if not self.is_open:
            raise TransportError("LAN 未连接")
        try:
            self._sock.sendall(data)
        except Exception as e:
            raise TransportError(f"LAN 写失败: {e}") from e

    def read(self, size: int = 1, timeout_s: float = 0.1) -> bytes:
        if not self.is_open:
            raise TransportError("LAN 未连接")
        try:
            self._sock.settimeout(timeout_s)
            return self._sock.recv(max(size, 1))
        except socket.timeout:
            return b""
        except Exception as e:
            raise TransportError(f"LAN 读失败: {e}") from e

    @property
    def is_open(self) -> bool:
        return self._sock is not None


class LoopbackTransport(Transport):
    """
    回环传输：写入的命令交给 handler(command:str)->str 生成响应，供读出。
    用于模拟从站、自动化验证与协议栈自测——无真机也可开发回归。
    """

    def __init__(self, handler):
        self._handler = handler
        self._rx: "queue.Queue[int]" = queue.Queue()
        self._open = False
        self._lock = threading.Lock()

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("回环链路未打开")
        text = data.decode("ascii", errors="replace")
        # SCPI 允许一次写入多条命令，逐条生成响应
        for cmd in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if not cmd.strip():
                continue
            with self._lock:
                resp = self._handler(cmd.strip())
            if resp:
                for b in resp.encode("ascii", errors="replace"):
                    self._rx.put(b)

    def read(self, size: int = 1, timeout_s: float = 0.1) -> bytes:
        if not self._open:
            raise TransportError("回环链路未打开")
        out = bytearray()
        deadline = time.monotonic() + timeout_s
        while len(out) < size:
            remain = deadline - time.monotonic()
            if remain <= 0:
                break
            try:
                out.append(self._rx.get(timeout=min(remain, 0.05)))
            except queue.Empty:
                continue
        return bytes(out)

    @property
    def is_open(self) -> bool:
        return self._open
