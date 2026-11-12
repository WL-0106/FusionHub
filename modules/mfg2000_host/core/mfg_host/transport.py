"""传输层：串口(USB 虚拟 COM) / TCP(LAN) / 回环(模拟从站)。

传输层只负责字节搬运，不做任何协议语义处理。
"""
from __future__ import annotations

import socket
from abc import ABC, abstractmethod
from typing import Optional


class TransportError(Exception):
    """传输层错误(未打开/断线/IO 失败)。"""


class Transport(ABC):
    name: str = "?"

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, max_bytes: int = 4096, timeout: float = 0.1) -> bytes:
        """读取可用字节，超时返回 b''；传输断开抛 TransportError。"""

    @property
    @abstractmethod
    def is_open(self) -> bool: ...


class SerialTransport(Transport):
    """USB 枚举出的虚拟 COM 口(需 pyserial，仅真机连接时需要)。"""

    name = "serial"

    def __init__(self, port: str, baudrate: int = 115200, bytesize: int = 8,
                 parity: str = "N", stopbits: int = 1):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self._serial = None

    def open(self) -> None:
        try:
            import serial  # 惰性导入：无真机场景不需要安装
        except ImportError as e:
            raise TransportError("缺少 pyserial 依赖，真机串口连接请先 pip install pyserial") from e
        try:
            self._serial = serial.Serial(
                port=self.port, baudrate=self.baudrate, bytesize=self.bytesize,
                parity=self.parity, stopbits=self.stopbits, timeout=0.1, write_timeout=1.0,
            )
        except Exception as e:
            raise TransportError(f"串口 {self.port} 打开失败: {e}") from e

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def write(self, data: bytes) -> None:
        if not self.is_open:
            raise TransportError("串口未打开")
        try:
            self._serial.write(data)
        except Exception as e:
            raise TransportError(f"串口写失败: {e}") from e

    def read(self, max_bytes: int = 4096, timeout: float = 0.1) -> bytes:
        if not self.is_open:
            raise TransportError("串口未打开")
        try:
            self._serial.timeout = timeout
            return self._serial.read(max_bytes) or b""
        except Exception as e:
            raise TransportError(f"串口读失败: {e}") from e


class TcpTransport(Transport):
    """LAN 直连(SCPI raw socket，端口按仪器配置，常见 5025)。"""

    name = "tcp"

    def __init__(self, host: str, port: int = 5025, connect_timeout: float = 3.0):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self._sock: Optional[socket.socket] = None

    def open(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock = sock
        except OSError as e:
            raise TransportError(f"TCP {self.host}:{self.port} 连接失败: {e}") from e

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise TransportError("TCP 未连接")
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise TransportError(f"TCP 写失败: {e}") from e

    def read(self, max_bytes: int = 4096, timeout: float = 0.1) -> bytes:
        if self._sock is None:
            raise TransportError("TCP 未连接")
        self._sock.settimeout(timeout)
        try:
            data = self._sock.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as e:
            raise TransportError(f"TCP 读失败(可能断线): {e}") from e
        if data == b"":
            raise TransportError("TCP 连接被对端关闭")
        return data


class LoopbackTransport(Transport):
    """进程内回环传输，对接模拟从站，供自测与自动化验证使用。"""

    name = "loopback"

    def __init__(self, responder, max_read_chunk: int = 4096):
        self._responder = responder
        self._max_read_chunk = max_read_chunk  # 限制单次返回字节数，用于模拟半包到达
        self._rx = bytearray()
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False
        self._rx.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("回环传输未打开")
        self._rx.extend(self._responder.handle(data))

    def read(self, max_bytes: int = 4096, timeout: float = 0.1) -> bytes:
        if not self._open:
            raise TransportError("回环传输未打开")
        if not self._rx:
            return b""
        n = min(max_bytes, self._max_read_chunk)
        out = bytes(self._rx[:n])
        del self._rx[:n]
        return out
