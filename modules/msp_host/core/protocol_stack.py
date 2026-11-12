# -*- coding: utf-8 -*-
"""协议栈：状态机 + 命令队列 + 超时重发 + 半包/粘包/错帧重同步。

设计要点（对应七步流程第 3 步质量卡点）：
  - 状态机：IDLE → TX → WAIT_RESP → (DONE | RETRY | FAILED)，不用 if-else 硬堆
  - 命令队列：多命令排队串行收发，单命令在途，避免帧交织
  - 超时重发有上限（默认 2 次），超限退出并报人话错误，防止从站掉线卡死
  - RX 缓冲区处理半包/粘包；错帧丢弃首字节重同步；连续坏帧上限保护
  - 异常响应（fc|0x80）映射为人话提示
  - 界面只通过回调拿语义化结果，不接触帧字节
"""
from __future__ import annotations

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional

from .modbus_rtu import (
    FC_READ_RO, FC_READ_RW, FC_WRITE_MULTI, FC_WRITE_SINGLE,
    ModbusExceptionResponse, ModbusFrameError, Response,
    build_read, build_write_multi, build_write_single, try_parse_frame,
)
from .transport import ITransport, TransportError


class StackState(enum.Enum):
    IDLE = "空闲"
    TX = "发送中"
    WAIT_RESP = "等待响应"
    RETRY = "重发中"
    DONE = "完成"
    FAILED = "失败"


class CommandFailed(Exception):
    """命令最终失败（超时/异常帧/从站异常），message 为人话提示。"""


@dataclass
class Command:
    name: str                       # 语义名称，如 "读输出电压"
    request: bytes
    expect_addr: int
    expect_fc: int
    on_success: Optional[Callable[[Response], None]] = None
    on_error: Optional[Callable[[Exception], None]] = None
    attempts: int = 0               # 已尝试发送次数
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[Response] = None
    error: Optional[Exception] = None


class ModbusRTUStack:
    """Modbus RTU 主站协议栈。线程安全；后台 worker 串行处理命令队列。"""

    def __init__(self, transport: ITransport, *,
                 timeout: float = 0.5, max_retries: int = 2,
                 inter_frame_delay: float = 0.02,
                 on_log: Optional[Callable[[str, str], None]] = None,
                 on_state: Optional[Callable[[StackState], None]] = None):
        self._transport = transport
        self.timeout = timeout
        self.max_retries = max_retries          # 超时重发上限（总尝试 = 1 + max_retries）
        self.inter_frame_delay = inter_frame_delay
        self.on_log = on_log                    # (方向, 文本)
        self.on_state = on_state
        self._queue: Deque[Command] = deque()
        self._q_cond = threading.Condition()
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._rx_buf = bytearray()
        self._state = StackState.IDLE
        self._max_consecutive_bad = 8           # 连续坏帧上限，超过判定链路异常
        self.stats = {"tx": 0, "rx": 0, "retry": 0, "timeout": 0, "bad_frame": 0}

    # ---------------- 生命周期 ----------------

    def start(self) -> None:
        if self._running:
            return
        if not self._transport.is_open:
            self._transport.open()
        self._running = True
        self._worker = threading.Thread(target=self._run, name="modbus-stack", daemon=True)
        self._worker.start()

    def stop(self, wait: bool = True) -> None:
        self._running = False
        with self._q_cond:
            self._q_cond.notify_all()
        if wait and self._worker is not None:
            self._worker.join(timeout=2.0)
        self._worker = None

    @property
    def state(self) -> StackState:
        return self._state

    @property
    def pending(self) -> int:
        with self._q_cond:
            return len(self._queue)

    def _set_state(self, s: StackState) -> None:
        self._state = s
        if self.on_state:
            self.on_state(s)

    def _log(self, direction: str, text: str) -> None:
        if self.on_log:
            self.on_log(direction, text)

    # ---------------- 命令提交 ----------------

    def submit(self, cmd: Command) -> Command:
        """入队并立即返回；调用 cmd.done.wait() 可同步等待。"""
        with self._q_cond:
            if not self._running:
                raise CommandFailed("协议栈未启动，请先连接设备")
            self._queue.append(cmd)
            self._q_cond.notify()
        return cmd

    def request_read(self, name: str, addr: int, fc: int, start: int, count: int,
                     on_success=None, on_error=None) -> Command:
        cmd = Command(name, build_read(addr, fc, start, count), addr, fc,
                      on_success, on_error)
        return self.submit(cmd)

    def request_write(self, name: str, addr: int, reg_values: List[int], start: int,
                      on_success=None, on_error=None) -> Command:
        """reg_values 为连续寄存器值列表（1~20 个），自动选 0x06/0x10。"""
        if len(reg_values) == 1:
            req = build_write_single(addr, start, reg_values[0])
        else:
            req = build_write_multi(addr, start, reg_values)
        cmd = Command(name, req, addr, req[1], on_success, on_error)
        return self.submit(cmd)

    def transact(self, cmd: Command, wait: float = 5.0) -> Response:
        """同步等待命令完成；失败抛 CommandFailed。"""
        self.submit(cmd)
        if not cmd.done.wait(timeout=wait):
            raise CommandFailed(f"命令「{cmd.name}」等待结果超时")
        if cmd.error is not None:
            raise cmd.error
        return cmd.result

    # ---------------- 状态机 worker ----------------

    def _run(self) -> None:
        while self._running:
            with self._q_cond:
                while self._running and not self._queue:
                    self._q_cond.wait(timeout=0.2)
                if not self._running:
                    break
                cmd = self._queue.popleft()
            try:
                cmd.result = self._execute(cmd)
            except Exception as e:      # noqa: BLE001 —— 统一转为命令级失败
                cmd.error = e
                self._log("ERR", f"「{cmd.name}」失败：{e}")
            finally:
                cmd.done.set()
                self._set_state(StackState.IDLE)
            if self.on_state:
                pass
            # 命令回调在 worker 线程执行，保证顺序
            try:
                if cmd.error is not None and cmd.on_error:
                    cmd.on_error(cmd.error)
                elif cmd.result is not None and cmd.on_success:
                    cmd.on_success(cmd.result)
            except Exception as e:  # noqa: BLE001
                self._log("ERR", f"「{cmd.name}」回调异常：{e}")
            time.sleep(self.inter_frame_delay)

    def _execute(self, cmd: Command) -> Response:
        self._rx_buf.clear()
        max_attempts = 1 + self.max_retries
        last_err: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            cmd.attempts = attempt
            if attempt > 1:
                self.stats["retry"] += 1
                self._set_state(StackState.RETRY)
                self._log("INFO", f"「{cmd.name}」第 {attempt - 1} 次重发（上限 {self.max_retries} 次）")
                time.sleep(0.05)

            # --- TX ---
            self._set_state(StackState.TX)
            self.stats["tx"] += 1
            self._log("TX", f"「{cmd.name}」{cmd.request.hex(' ')}")
            try:
                self._transport.write(cmd.request)
            except TransportError as e:
                last_err = CommandFailed(f"发送失败：{e}")
                continue

            # --- WAIT_RESP ---
            self._set_state(StackState.WAIT_RESP)
            deadline = time.monotonic() + self.timeout
            bad_frames = 0
            attempt_err: Optional[Exception] = None
            while time.monotonic() < deadline:
                chunk = self._transport.read(256, timeout=0.05)
                if chunk:
                    self._rx_buf.extend(chunk)
                if not self._rx_buf:
                    continue
                while self._rx_buf:
                    try:
                        parsed = try_parse_frame(bytes(self._rx_buf), cmd.expect_addr, cmd.expect_fc)
                    except ModbusExceptionResponse as e:
                        self._rx_buf.clear()
                        self.stats["rx"] += 1
                        self._log("RX", f"异常响应：{e}（原始 {bytes(chunk).hex(' ') if chunk else ''}）")
                        raise CommandFailed(f"设备返回异常：{e}") from e
                    except ModbusFrameError as e:
                        # 错帧：丢弃首字节重同步
                        bad_frames += 1
                        self.stats["bad_frame"] += 1
                        dropped = self._rx_buf.pop(0)
                        self._log("WARN", f"错帧丢弃 0x{dropped:02X} 重同步（{e}）")
                        if bad_frames >= self._max_consecutive_bad:
                            self._rx_buf.clear()
                            attempt_err = CommandFailed("连续收到无法解析的错帧，链路数据异常")
                            break
                        continue
                    if parsed is None:
                        break    # 半包：继续等
                    resp, consumed = parsed
                    del self._rx_buf[:consumed]
                    self.stats["rx"] += 1
                    self._log("RX", f"「{cmd.name}」{resp.raw.hex(' ')}")
                    return resp
                if attempt_err is not None:
                    break

            if attempt_err is not None:
                last_err = attempt_err
            else:
                self.stats["timeout"] += 1
                last_err = CommandFailed(
                    f"「{cmd.name}」响应超时（{self.timeout * 1000:.0f}ms 无应答，已重发 {attempt - 1} 次）")
                self._log("WARN", str(last_err))

        assert last_err is not None
        raise last_err
