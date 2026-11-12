# -*- coding: utf-8 -*-
"""FLUKE 8808A 协议栈 —— 纯状态机实现（不用 if-else 硬堆）。

设计要点（对应开发流程第3步的质量卡点）：
- 帧封装/解包：命令行 + CR 结尾；响应按提示符(=>/?>/!>)收尾判定完成
- 半包/粘包：字节流进入重组缓冲，按提示符边界切帧，不假设一次 read=一帧
- 错帧重同步：未匹配到提示符的残留数据在超时后整段丢弃并上报
- 超时重发上限：每条命令最多 MAX_RETRIES 次，超限报错退出，不卡死
- 多命令队列化：队列 FIFO 串行执行，遵循手册"先读响应再发下一条"规则
- 异常映射人话：?>/!>/超时/断线 → 中文提示，附原始报文
"""
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

from .commands import (
    ALL_PROMPTS, PROMPT_CMD_ERR, PROMPT_EXE_ERR, PROMPT_OK,
)
from .transport import Transport, TransportError


# ---------------------------------------------------------------- 异常分类与人话映射
class ResultCode(Enum):
    OK = auto()
    CMD_ERROR = auto()       # ?>  语法/解析错误
    EXE_ERROR = auto()       # !>  执行/设备相关错误
    TIMEOUT = auto()         # 无提示符超时
    LINK_DOWN = auto()       # 链路断开
    CANCELLED = auto()       # 用户取消/断开
    PARAM_ERROR = auto()     # 本地参数校验失败（未发帧）


HUMAN_MESSAGES = {
    ResultCode.OK: "成功",
    ResultCode.CMD_ERROR: "命令错误：仪器无法解析该命令（语法错误），命令未执行",
    ResultCode.EXE_ERROR: "执行错误：命令可解析但无法执行（参数越界或当前功能不允许）",
    ResultCode.TIMEOUT: "超时：仪器未在限定时间内返回提示符（已达到重发上限）",
    ResultCode.LINK_DOWN: "链路断开：串口连接丢失或从站无响应",
    ResultCode.CANCELLED: "已取消：命令在完成前被中止",
    ResultCode.PARAM_ERROR: "参数错误：命令未发送，请检查输入值",
}

# ESR 位定义（手册表4-6）-> 人话
ESR_BITS = {
    0: ("OPC", "操作完成"),
    2: ("QYE", "查询错误：输出缓冲无数据时被读取，或新命令先于上次查询响应到达"),
    3: ("DDE", "设备相关错误：校准输入不正确，或输入缓冲溢出"),
    4: ("EXE", "执行错误：命令参数不合适"),
    5: ("CME", "命令错误：语法错误导致命令未执行"),
    7: ("PON", "自上次读取/清除 ESR 后发生过断电重启"),
}


def explain_esr(value: int) -> list:
    return [f"{name}（{desc}）" for bit, (name, desc) in sorted(ESR_BITS.items()) if value >> bit & 1]


@dataclass
class CommandResult:
    code: ResultCode
    payload: str = ""                 # 查询响应数据（不含提示符）
    raw: str = ""                     # 原始帧（诊断用）
    command: str = ""
    retries: int = 0
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.code is ResultCode.OK

    @property
    def message(self) -> str:
        return HUMAN_MESSAGES[self.code]


@dataclass
class StackConfig:
    timeout: float = 1.0        # 单次响应超时（秒）
    max_retries: int = 2        # 超时重发上限（总发送次数 = 1 + max_retries）
    read_chunk: int = 256
    read_slice: float = 0.05    # 单次 read 等待，用于累积半包
    inter_command_gap: float = 0.0  # 命令间隔（可配置，防止压垮慢速链路）


class StackState(Enum):
    IDLE = auto()
    SENDING = auto()
    WAITING = auto()      # 等待提示符（含半包累积）
    RETRYING = auto()
    STOPPED = auto()


class ProtocolStack:
    """单线程 worker 驱动的状态机协议栈，界面经回调拿结果（界面不接触帧字节）。"""

    def __init__(self, transport: Transport, config: Optional[StackConfig] = None,
                 on_frame: Optional[Callable[[str, str], None]] = None):
        self._t = transport
        self._cfg = config or StackConfig()
        self._on_frame = on_frame            # (direction, text) 收发日志回调
        self._queue: "deque[_Job]" = deque()
        self._q_cond = threading.Condition()
        self._state = StackState.IDLE
        self._state_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._rxbuf = bytearray()            # 半包/粘包重组缓冲

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_evt.clear()
        self._worker = threading.Thread(target=self._run, name="fluke8808a-stack", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        """停机：取消队列中未完成任务（退出机制，不阻塞）。"""
        self._stop_evt.set()
        with self._q_cond:
            for job in self._queue:
                if not job.done.is_set():
                    job.result = CommandResult(ResultCode.CANCELLED, command=job.command)
                    job.done.set()
            self._queue.clear()
            self._q_cond.notify_all()
        if self._worker:
            self._worker.join(timeout=2.0)
        self._set_state(StackState.STOPPED)

    @property
    def state(self) -> StackState:
        with self._state_lock:
            return self._state

    @property
    def queue_size(self) -> int:
        with self._q_cond:
            return len(self._queue)

    def clear_queue(self) -> int:
        """清空待发队列（界面"清空/停止"按钮用）。返回被取消的条数。"""
        cancelled = 0
        with self._q_cond:
            for job in self._queue:
                if not job.done.is_set():
                    job.result = CommandResult(ResultCode.CANCELLED, command=job.command)
                    job.done.set()
                    cancelled += 1
            self._queue.clear()
            self._q_cond.notify_all()
        return cancelled

    # ------------------------------------------------------------ 对外接口
    def _submit_job(self, job: "_Job") -> None:
        with self._q_cond:
            self._queue.append(job)
            self._q_cond.notify()

    def submit(self, command: str, callback: Optional[Callable[[CommandResult], None]] = None) -> threading.Event:
        """命令入队（FIFO），返回完成事件。回调在 worker 线程触发。"""
        job = _Job(command=command, callback=callback)
        self._submit_job(job)
        return job.done

    def execute(self, command: str, timeout: Optional[float] = None) -> CommandResult:
        """同步执行一条命令（自动化验证/初始化用），带等待上限。"""
        job = _Job(command=command)
        self._submit_job(job)
        wait = timeout if timeout is not None else (
            self._cfg.timeout * (1 + self._cfg.max_retries) + 2.0)
        if not job.done.wait(timeout=wait):
            return CommandResult(ResultCode.TIMEOUT, command=command)
        return job.result or CommandResult(ResultCode.TIMEOUT, command=command)

    # ------------------------------------------------------------ worker 状态机
    def _run(self) -> None:
        while not self._stop_evt.is_set():
            with self._q_cond:
                while not self._queue and not self._stop_evt.is_set():
                    self._q_cond.wait(timeout=0.2)
                if self._stop_evt.is_set():
                    break
                job = self._queue.popleft()
            result = self._process(job.command)
            job.result = result
            job.done.set()
            if job.callback:
                try:
                    job.callback(result)
                except Exception:
                    pass
            if self._cfg.inter_command_gap > 0:
                time.sleep(self._cfg.inter_command_gap)

    def _process(self, command: str) -> CommandResult:
        t0 = time.monotonic()
        retries = 0
        last = CommandResult(ResultCode.TIMEOUT, command=command)
        attempts = 1 + self._cfg.max_retries   # 总发送次数上限，超限退出
        for attempt in range(attempts):
            if self._stop_evt.is_set():
                return CommandResult(ResultCode.CANCELLED, command=command)
            self._rxbuf.clear()                # 重同步：每次发送前丢弃上一轮残留
            self._set_state(StackState.SENDING)
            frame = self._encode(command)
            try:
                self._t.write(frame)
            except TransportError as e:
                self._set_state(StackState.IDLE)
                return CommandResult(ResultCode.LINK_DOWN, command=command,
                                     raw=str(e), retries=retries,
                                     elapsed=time.monotonic() - t0)
            self._log("TX", command)

            self._set_state(StackState.RETRYING if attempt else StackState.WAITING)
            result = self._wait_response(command)
            last = result
            if result.code is not ResultCode.TIMEOUT:
                result.retries = retries       # retries = 实际重发次数（不含首发）
                result.elapsed = time.monotonic() - t0
                self._set_state(StackState.IDLE)
                return result
            if attempt < attempts - 1:         # 还有余量才计数重发，避免把首发算作重试
                retries += 1
        last.retries = retries
        last.elapsed = time.monotonic() - t0
        self._set_state(StackState.IDLE)
        return last

    def _encode(self, command: str) -> bytes:
        cmd = command.strip()
        return (cmd + "\r").encode("ascii", errors="replace")   # 输入结束符 CR

    def _wait_response(self, command: str) -> CommandResult:
        """累积字节流直到出现提示符；处理半包/粘包；超时返回 TIMEOUT。"""
        deadline = time.monotonic() + self._cfg.timeout
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raw = self._rxbuf.decode("ascii", errors="replace")
                if raw:
                    self._log("RX", raw + " <超时丢弃>")
                return CommandResult(ResultCode.TIMEOUT, command=command, raw=raw)
            try:
                chunk = self._t.read(self._cfg.read_chunk,
                                     min(self._cfg.read_slice, remain))
            except TransportError as e:
                return CommandResult(ResultCode.LINK_DOWN, command=command, raw=str(e))
            if chunk:
                self._rxbuf.extend(chunk)
                parsed = self._try_parse(command)
                if parsed is not None:
                    return parsed

    def _try_parse(self, command: str) -> Optional[CommandResult]:
        """按提示符边界解析完整帧；返回 None 表示帧未完整（继续等半包）。"""
        buf = self._rxbuf.decode("ascii", errors="replace")
        # 提示符出现在帧尾（提示符后可能跟回显的空格等，取最先出现者）
        idx = -1
        prompt = ""
        for p in ALL_PROMPTS:
            i = buf.find(p)
            if i >= 0 and (idx < 0 or i < idx):
                idx, prompt = i, p
        if idx < 0:
            return None
        # 提示符前的响应体：以 CRLF 分隔，剥掉回显行
        head = buf[:idx]
        lines = [ln for ln in re.split(r"\r\n|\r|\n", head)]
        payload = self._strip_echo(lines, command)
        self._log("RX", buf[:idx + len(prompt)])
        code = {
            PROMPT_OK: ResultCode.OK,
            PROMPT_CMD_ERR: ResultCode.CMD_ERROR,
            PROMPT_EXE_ERR: ResultCode.EXE_ERROR,
        }[prompt]
        return CommandResult(code, payload=payload,
                             raw=buf[:idx + len(prompt)], command=command)

    @staticmethod
    def _strip_echo(lines, command: str) -> str:
        """去掉回显行（回显开启时仪器回显发送内容），保留纯响应数据。"""
        cmd_head = command.strip()
        kept = []
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s == cmd_head or s == cmd_head + "\r":
                continue           # 回显行
            if s.endswith("=>") or s.endswith("?>") or s.endswith("!>"):
                s = s[:-2].strip()  # 提示符已单独处理
                if s:
                    kept.append(s)
                continue
            kept.append(s)
        # 响应体为最后一行数据；重同步时丢弃前段噪声/回显残留行（错帧掺噪声场景）
        return kept[-1] if kept else ""

    def _set_state(self, s: StackState) -> None:
        with self._state_lock:
            self._state = s

    def _log(self, direction: str, text: str) -> None:
        if self._on_frame:
            try:
                self._on_frame(direction, text)
            except Exception:
                pass


@dataclass
class _Job:
    command: str
    callback: Optional[Callable[[CommandResult], None]] = None
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[CommandResult] = None
