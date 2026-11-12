# -*- coding: utf-8 -*-
"""传输抽象层：协议栈只依赖本接口，串口与模拟从站可互换（真机/回放同一套代码路径）。"""
import queue
import threading
from abc import ABC, abstractmethod


class Transport(ABC):
    """字节流传输接口。协议栈不感知底层是串口还是模拟链路。"""

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, max_size: int, timeout: float) -> bytes:
        """读取至多 max_size 字节；超时返回 b''；链路断开抛 TransportError。"""

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...


class TransportError(Exception):
    """链路级异常（断线、驱动错误）。"""


_PEER_CLOSED = object()   # 对端断开标记（哨兵，区别于真实数据字节）


class SerialTransport(Transport):
    """pyserial 串口传输。8808A 支持 300~19200 波特率、7/8 数据位、E/O/N 校验、1/2 停止位。"""

    def __init__(self, port: str, baudrate: int = 9600, bytesize: int = 8,
                 parity: str = "N", stopbits: int = 1, timeout: float = 0.05):
        import serial  # 延迟导入，模拟链路无需 pyserial
        parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
        self._ser = serial.Serial(
            port=port, baudrate=baudrate, bytesize=bytesize,
            parity=parity_map[parity.upper()], stopbits=stopbits,
            timeout=timeout, write_timeout=1.0,
        )

    def write(self, data: bytes) -> None:
        try:
            self._ser.write(data)
        except Exception as e:  # pyserial 抛 SerialException/OSError
            raise TransportError(f"串口写入失败: {e}") from e

    def read(self, max_size: int, timeout: float) -> bytes:
        try:
            self._ser.timeout = timeout
            return self._ser.read(max_size) or b""
        except Exception as e:
            raise TransportError(f"串口读取失败: {e}") from e

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        return bool(self._ser.is_open)


class LoopbackTransport(Transport):
    """回环传输：上位机端 <-> 模拟从站端，双向队列。

    用于模拟从站自测与自动化回归——协议栈在无真机环境下跑真实收发路径。
    半包/粘包场景通过 `peer.push_chunked()` 注入。
    """

    def __init__(self):
        self._rx: "queue.Queue[bytes]" = queue.Queue()   # 对端写入 -> 本端 read
        self._peer: "LoopbackTransport | None" = None
        self._open = True
        self._closed_evt = threading.Event()
        self._peer_closed = False   # 对端是否已断开（断开后读写立即报错，不挂死）

    @classmethod
    def pair(cls):
        a, b = cls(), cls()
        a._peer, b._peer = b, a
        return a, b   # (上位机端, 从站端)

    def write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("链路已关闭")
        if self._peer_closed:
            raise TransportError("对端链路已断开")
        self._peer._rx.put(bytes(data))

    def read(self, max_size: int, timeout: float) -> bytes:
        if not self._open:
            raise TransportError("链路已关闭")
        if self._peer_closed:                # 对端已断开 -> 立即报错（不空等超时）
            raise TransportError("对端链路已断开")
        try:
            chunk = self._rx.get(timeout=timeout)
        except queue.Empty:
            return b""
        if chunk is _PEER_CLOSED:            # 对端断开 -> 通知本端读方（LINK_DOWN 语义）
            self._peer_closed = True
            raise TransportError("对端链路已断开")
        if self._peer_closed:                # 断开标记一旦置位，后续读一律报错
            raise TransportError("对端链路已断开")
        # 顺带合并队列中已到达的数据（模拟粘包）
        merged = bytearray(chunk)
        while len(merged) < max_size:
            try:
                nxt = self._rx.get_nowait()
            except queue.Empty:
                break
            if nxt is _PEER_CLOSED:
                self._peer_closed = True
                break
            merged += nxt
        return bytes(merged[:max_size])

    def close(self) -> None:
        if not self._open:
            return
        self._open = False
        self._closed_evt.set()
        # 通知对端：本端已断开，让对端 read 报 LINK_DOWN 而不是死等到超时
        if self._peer is not None:
            self._peer._peer_closed = True
            self._peer._rx.put(_PEER_CLOSED)
        self._rx.put(b"")   # 唤醒阻塞的 read

    @property
    def is_open(self) -> bool:
        return self._open

    # --- 从站侧测试辅助：分片投递（模拟半包） ---
    def push_chunked(self, data: bytes, chunk_size: int = 3, delay: float = 0.01):
        import time
        for i in range(0, len(data), chunk_size):
            self._peer._rx.put(data[i:i + chunk_size])
            time.sleep(delay)
