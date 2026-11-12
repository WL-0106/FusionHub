"""SCPI 协议栈：命令队列 + 状态机 + 超时重发上限 + 错帧重同步。

设计要点(对应开发规范第 3 条)：
- 命令队列化：所有收发经单工作线程串行，杜绝交叉报文；
- 状态机：QUEUED -> SENDING -> WAITING_REPLY -> (RETRYING) -> DONE/FAILED；
- 半包/粘包：FrameDecoder 增量分帧；
- 错帧：FrameError 后清缓存重同步并计入重试；
- 超时重发：有次数上限(max_retries)，用尽后报人话错误并退出，绝不无限重发。
"""
from __future__ import annotations

import enum
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .errors import CommTimeoutError, FrameError, ProtocolError
from .framing import FrameDecoder, TERMINATOR
from .transport import Transport, TransportError

READ_SLICE = 0.05  # 单次底层读取超时(s)，保证工作线程可及时退出
DEFAULT_TIMEOUT = 1.0  # 单命令响应超时(s)，手册未规定(澄清项Q1)，可配置
DEFAULT_MAX_RETRIES = 2  # 超时/错帧重试上限(总尝试次数 = 1 + max_retries)


class CommandState(enum.Enum):
    QUEUED = "排队中"
    SENDING = "发送中"
    WAITING_REPLY = "等待响应"
    RETRYING = "重试中"
    DONE = "完成"
    FAILED = "失败"


@dataclass
class Command:
    scpi: str
    expect_reply: bool = False
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    state: CommandState = CommandState.QUEUED
    attempts: int = 0
    result: Optional[str] = None
    error: Optional[Exception] = None
    done: threading.Event = field(default_factory=threading.Event)


TrafficHook = Callable[[str, str], None]  # (方向 "TX"/"RX", 报文文本)


class ScpiStack:
    """单连接 SCPI 协议栈。"""

    def __init__(self, transport: Transport, timeout: float = DEFAULT_TIMEOUT,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 on_traffic: Optional[TrafficHook] = None):
        self._transport = transport
        self._timeout = timeout
        self._max_retries = max_retries
        self._on_traffic = on_traffic
        self._decoder = FrameDecoder()
        self._q: "queue.Queue[Optional[Command]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

    # ---------- 生命周期 ----------
    def start(self) -> None:
        if self._running:
            return
        self._transport.open()
        self._running = True
        self._worker = threading.Thread(target=self._run, name="scpi-stack", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._running = False
        self._q.put(None)
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        try:
            self._transport.close()
        except TransportError:
            pass

    @property
    def running(self) -> bool:
        return self._running

    # ---------- 对外接口 ----------
    def submit(self, cmd: Command) -> Command:
        if not self._running:
            raise ProtocolError("协议栈未启动，请先建立连接")
        self._q.put(cmd)
        return cmd

    def request(self, scpi: str, timeout: Optional[float] = None) -> str:
        """同步查询：入队并阻塞等待结果，失败抛异常。"""
        cmd = Command(scpi=scpi, expect_reply=True, timeout=timeout or self._timeout)
        self.submit(cmd)
        if not cmd.done.wait(timeout=(cmd.timeout * (cmd.max_retries + 1)) + 2.0):
            raise CommTimeoutError(f"命令 {scpi} 等待协议栈处理超时")
        if cmd.error is not None:
            raise cmd.error
        return cmd.result or ""

    def write(self, scpi: str, timeout: Optional[float] = None) -> None:
        """同步写命令(无响应)，失败抛异常。"""
        cmd = Command(scpi=scpi, expect_reply=False, timeout=timeout or self._timeout)
        self.submit(cmd)
        if not cmd.done.wait(timeout=(cmd.timeout * (cmd.max_retries + 1)) + 2.0):
            raise CommTimeoutError(f"命令 {scpi} 等待协议栈处理超时")
        if cmd.error is not None:
            raise cmd.error

    # ---------- 工作线程 ----------
    def _run(self) -> None:
        while self._running:
            cmd = self._q.get()
            if cmd is None:
                break
            try:
                self._execute(cmd)
            except Exception as e:  # noqa: BLE001 —— 铁律：绝不让协议栈线程死亡
                cmd.error = ProtocolError(f"命令 {cmd.scpi} 内部异常: {e}")
                cmd.state = CommandState.FAILED
                cmd.done.set()
                if self._on_traffic:
                    self._on_traffic("ERR", f"协议栈内部异常(已隔离，不影响后续命令): {e}")

    def _execute(self, cmd: Command) -> None:
        deadline_budget = cmd.timeout
        for attempt in range(cmd.max_retries + 1):
            cmd.attempts = attempt + 1
            cmd.state = CommandState.SENDING if attempt == 0 else CommandState.RETRYING
            self._decoder.flush()   # 丢弃上一 attempt 的迟到响应，防响应错位污染本命令
            self._drain_rx()        # 连传输层残余一起清（迟到响应可能尚未被读走）
            try:
                self._send(cmd.scpi)
            except TransportError as e:
                cmd.error = ProtocolError(f"命令 {cmd.scpi} 发送失败: {e}")
                cmd.state = CommandState.FAILED
                cmd.done.set()
                return

            if not cmd.expect_reply:
                cmd.state = CommandState.DONE
                cmd.done.set()
                return

            cmd.state = CommandState.WAITING_REPLY
            try:
                reply = self._wait_reply(deadline_budget)
                self._decoder.flush()   # 单命令单应答：清掉重试产生的多余迟到响应
                self._drain_rx()
                cmd.result = reply
                cmd.state = CommandState.DONE
                cmd.done.set()
                return
            except FrameError as e:
                # 错帧：已丢弃缓存重同步，计入重试
                cmd.error = e
                continue
            except TransportError as e:
                # 传输层断开/读写失败：立即失败退出，绝不逃逸杀死协议栈线程
                cmd.error = ProtocolError(f"命令 {cmd.scpi} 通信失败: {e}")
                cmd.state = CommandState.FAILED
                cmd.done.set()
                return
            except _ReplyTimeout as e:
                # 超时：清半包缓存防止脏数据污染下一帧，计入重试
                if e.raw and self._on_traffic:
                    self._on_traffic("WARN", f"超时前收到未组成帧的原始字节: "
                                             f"{e.raw.hex(' ')} / {e.raw!r}（查终结符与响应格式）")
                self._decoder.flush()
                self._drain_rx()
                continue

        if isinstance(cmd.error, FrameError):
            msg = (f"命令 {cmd.scpi} 连续错帧(已重试 {cmd.attempts} 次)，"
                   f"请检查串口参数(波特率/数据位/校验)是否与仪器一致")
        else:
            msg = (f"命令 {cmd.scpi} 超时无响应(已重试 {cmd.attempts} 次)，"
                   f"请检查接线/仪器电源/远程接口配置；本命令已放弃，不会无限重发")
        cmd.error = CommTimeoutError(msg)
        cmd.state = CommandState.FAILED
        self._decoder.flush()
        self._drain_rx()   # 放弃后排空迟到残余，防污染后续命令
        cmd.done.set()

    def _drain_rx(self) -> None:
        """排空传输层迟到残余（重试时仪器回的多余响应），防响应错位一拍。

        上限保护：仪器持续输出时绝不无限循环（曾因此卡死协议栈线程）。
        """
        try:
            for _ in range(64):
                if not self._transport.read(256, timeout=0.01):
                    break
        except Exception:  # noqa: BLE001
            pass

    def _send(self, scpi: str) -> None:
        payload = (scpi + "\n").encode("ascii", errors="replace")
        self._transport.write(payload)
        if self._on_traffic:
            self._on_traffic("TX", scpi)

    def _wait_reply(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        got = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _ReplyTimeout(bytes(got))
            data = self._transport.read(4096, timeout=min(READ_SLICE, remaining))
            if not data:
                continue
            got.extend(data)
            try:
                frames = self._decoder.feed(data)
            except FrameError:
                raise
            for f in frames:
                if self._on_traffic:
                    self._on_traffic("RX", f)
                return f  # 单命令单帧：取第一条完整响应


class _ReplyTimeout(Exception):
    def __init__(self, raw: bytes = b""):
        self.raw = raw   # 超时前收到的原始字节（诊断用：揭示仪器真实响应/终结符）
        super().__init__()
