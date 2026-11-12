# -*- coding: utf-8 -*-
"""传输层抽象：真串口（pyserial）与测试用回环链路（对接模拟从站）。

界面与协议栈不接触具体字节，只通过本层收发；测试用 LoopbackTransport
可注入半包、粘包、错帧、无响应等故障。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Optional


class TransportError(Exception):
    pass


class ITransport:
    def open(self) -> None: ...
    def close(self) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read(self, max_bytes: int = 256, timeout: float = 0.0) -> bytes: ...
    @property
    def is_open(self) -> bool: ...


# ----------------------------------------------------------------------------
# 真串口
# ----------------------------------------------------------------------------

class SerialTransport(ITransport):
    """pyserial 串口传输（8N1）。pyserial 仅在真机联调时需要。"""

    def __init__(self, port: str, baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self._ser = None

    def open(self) -> None:
        try:
            import serial  # 延迟导入：无 pyserial 时模拟测试仍可用
        except ImportError as e:
            raise TransportError("缺少 pyserial，无法打开真实串口（pip install pyserial）") from e
        try:
            self._ser = serial.Serial(
                port=self.port, baudrate=self.baudrate,
                bytesize=8, parity="N", stopbits=1,
                timeout=0.05, write_timeout=1.0,
            )
        except Exception as e:
            raise TransportError(f"打开串口 {self.port} 失败：{e}") from e

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def write(self, data: bytes) -> None:
        if not self.is_open:
            raise TransportError("串口未打开")
        self._ser.write(data)

    def read(self, max_bytes: int = 256, timeout: float = 0.0) -> bytes:
        if not self.is_open:
            raise TransportError("串口未打开")
        end = time.monotonic() + timeout
        chunks = []
        while True:
            b = self._ser.read(max_bytes)
            if b:
                chunks.append(b)
                # 串口半包场景：多读一轮剩余字节
                max_bytes -= len(b)
                if max_bytes <= 0:
                    break
            if time.monotonic() >= end:
                break
            if not b:
                time.sleep(0.002)
        return b"".join(chunks)

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open


# ----------------------------------------------------------------------------
# 回环链路（测试/模拟从站用）
# ----------------------------------------------------------------------------

class LoopbackTransport(ITransport):
    """主机侧传输：write() 交给 handler（模拟从站），响应进入 rx 队列。

    handler(data) -> bytes|None（None 表示从站无响应/超时场景）
    """

    def __init__(self, handler: Callable[[bytes], Optional[bytes]],
                 chunk_size: int = 0, chunk_delay: float = 0.0):
        self._handler = handler
        self._rx: Deque[int] = deque()
        self._lock = threading.Lock()
        self._open = False
        self.chunk_size = chunk_size      # >0 时按块投递（模拟半包）
        self.chunk_delay = chunk_delay    # 块间延时

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("回环链路未打开")
        resp = self._handler(data)
        if not resp:
            return
        if self.chunk_size and self.chunk_size > 0:
            for i in range(0, len(resp), self.chunk_size):
                piece = resp[i:i + self.chunk_size]
                with self._lock:
                    self._rx.extend(piece)
                if self.chunk_delay:
                    time.sleep(self.chunk_delay)
        else:
            with self._lock:
                self._rx.extend(resp)

    def feed(self, data: bytes) -> None:
        """外部注入接收字节（模拟慢从站延迟送达，不阻塞发送方）。"""
        with self._lock:
            self._rx.extend(data)

    def read(self, max_bytes: int = 256, timeout: float = 0.0) -> bytes:
        end = time.monotonic() + timeout
        out = bytearray()
        while True:
            with self._lock:
                while self._rx and len(out) < max_bytes:
                    out.append(self._rx.popleft())
            if out or time.monotonic() >= end:
                break
            time.sleep(0.001)
        return bytes(out)
