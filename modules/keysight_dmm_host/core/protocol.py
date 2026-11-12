# -*- coding: utf-8 -*-
"""
SCPI 协议栈
===========
帧模型（手册印刷页 185 命令终止符 / 186 参数类型）：
    命令帧 : <命令正文><终止符>          终止符 LF(\\n)，可选 CR LF
    响应帧 : <响应正文><终止符>          查询响应以 LF 结尾

边界处理（协议栈边界处理重于功能实现）：
    1. 半包/粘包：接收按终止符 LF 做行重组，残字节保留到下次解析。
    2. 错帧/乱字符：重组前剔除 <0x20 的杂散控制字符（保留 LF）后判定整行。
    3. 超时重发：每命令独立超时，重发有次数上限(Retries)，超限抛 TimeoutError 退出，
       严禁无限重发（防从站掉线时上位机卡死）。
    4. 多命令队列：所有命令入队串行下发，队列深度可配，满则拒绝（防界面刷太快堆积）。
    5. 异常码映射：SYSTem:ERRor? 读到的 <code>,"msg" 映射为人话提示。

状态机：DISCONNECTED -> IDLE -> SENDING -> WAIT_RESP -> (PARSED -> IDLE)
                             |__ timeout __> RETRY -> SENDING（次数用尽->FAILED->IDLE）
"""
from __future__ import annotations

import enum
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .commands import CommandDef, get as get_cmd
from .transport import Transport, TransportError

# SCPI 查询响应以 LF 结尾；剥离可能的 CR
_TERMINATOR = b"\n"


class State(enum.Enum):
    DISCONNECTED = "已断开"
    IDLE = "空闲"
    SENDING = "发送中"
    WAIT_RESP = "等待响应"
    RETRY = "重发中"
    FAILED = "失败"


@dataclass
class Result:
    ok: bool
    key: str
    raw: str = ""
    value: object = None
    error: str = ""
    attempts: int = 1


class ScpiError(Exception):
    """仪器返回的 SCPI 错误码。"""

    def __init__(self, code: int, message: str):
        self.code, self.message = code, message
        super().__init__(f"[{code}] {message}")


class TimeoutError_(Exception):
    """超时且重发次数用尽。"""


class ProtocolError(Exception):
    """帧/协议层错误。"""


# 手册印刷页 428 SCPI 错误消息；未覆盖的按数字码兜底
ERROR_MAP = {
    -100: "命令语法错误（检查命令拼写/参数）",
    -101: "无效字符（命令含非法字符）",
    -102: "命令关键字错误",
    -103: "命令参数不完整",
    -104: "参数数据类型错误",
    -105: "参数越界（量程/范围非法）",
    -108: "参数不足",
    -109: "参数过多",
    -110: "数据溢出",
    -112: "参数超出允许值（配置组合非法）",
    -113: "命令头错误",
    -121: "无效字符（数据解析）",
    -123: "数值溢出",
    -131: "无效的模板字符串",
    -138: "查询缓冲区溢出",
    -141: "命令保护：当前状态不允许",
    -200: "执行错误",
    -221: "设置冲突（参数与当前配置冲突）",
    -222: "数据无效",
    -224: "非法条件（自检/校准失败）",
    -230: "数据过早或过晚",
    0: "无错误",
}


def explain_error(code: int, msg: str = "") -> str:
    base = ERROR_MAP.get(code, f"未知错误码 {code}")
    return f"{base}（仪器: {msg}）" if msg else base


_ERR_RE = re.compile(r"^\s*(-?\d+)\s*,\s*\"?(.*?)\"?\s*$")


def parse_error_response(raw: str) -> ScpiError:
    m = _ERR_RE.match(raw.strip())
    if not m:
        return ScpiError(-1, f"错误响应格式异常: {raw!r}")
    return ScpiError(int(m.group(1)), m.group(2))


def parse_float(raw: str) -> float:
    s = raw.strip().split(",")[0]
    try:
        return float(s)
    except ValueError as e:
        raise ProtocolError(f"响应不是数值: {raw!r}") from e


class ScpiClient:
    """
    SCPI 协议栈客户端（线程安全，命令队列化）。
    对上暴露语义化接口（见 semantic 模块），界面不得直接拼帧字节。
    """

    def __init__(self, transport: Transport, default_timeout_s: float = 1.0,
                 max_retries: int = 2, queue_limit: int = 32,
                 retry_backoff_s: float = 0.05):
        self._t = transport
        self._dflt_timeout = default_timeout_s
        self._max_retries = max(0, max_retries)   # 重发上限（防卡死）
        self._queue_limit = queue_limit            # 队列上限（防界面刷太快堆积）
        self._backoff = retry_backoff_s
        self._state = State.DISCONNECTED
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max(1, queue_limit))  # 队列准入（满则拒绝）
        self._rxbuf = bytearray()                  # 半包/粘包重组缓冲
        self._on_state: Optional[Callable[[State], None]] = None

    # ---- 状态 ----
    @property
    def state(self) -> State:
        return self._state

    def set_state_listener(self, cb: Optional[Callable[[State], None]]):
        self._on_state = cb

    def _set_state(self, s: State):
        self._state = s
        if self._on_state:
            try:
                self._on_state(s)
            except Exception:
                pass

    # ---- 连接 ----
    def connect(self):
        with self._lock:
            self._t.open()
            self._rxbuf.clear()
            self._set_state(State.IDLE)

    def disconnect(self):
        with self._lock:
            try:
                self._t.close()
            finally:
                self._set_state(State.DISCONNECTED)

    @property
    def is_connected(self) -> bool:
        return self._t.is_open

    # ---- 队列准入（满则立即拒绝，防界面刷太快堆积） ----
    def _acquire_slot(self):
        if not self._slots.acquire(blocking=False):
            raise ProtocolError(
                f"命令队列已满({self._queue_limit})，界面刷新过快，请降低轮询频率")

    def _release_slot(self):
        self._slots.release()

    # ---- 行重组：处理半包/粘包/错帧 ----
    def _read_line(self, deadline: float) -> str:
        """读到一条以 LF 结尾的完整响应行；超时返回空串。"""
        while True:
            idx = self._rxbuf.find(_TERMINATOR)
            if idx >= 0:
                line = bytes(self._rxbuf[:idx])
                del self._rxbuf[:idx + 1]
                # 剔除杂散控制字符（错帧自净），再剥 CR
                clean = bytes(b for b in line if b >= 0x20 or b in (0x09,))
                return clean.decode("ascii", errors="replace").rstrip("\r")
            remain = deadline - time.monotonic()
            if remain <= 0:
                return ""
            chunk = self._t.read(64, timeout_s=min(remain, 0.1))
            if chunk:
                self._rxbuf.extend(chunk)

    def _write_raw(self, text: str):
        self._t.write(text.encode("ascii", errors="replace") + b"\n")

    # ---- 核心收发 ----
    def transact(self, cmd: CommandDef, param: Optional[str] = None,
                 query: bool = False) -> str:
        """下发命令；query=True 时取回响应。含超时重发上限，超限抛 TimeoutError_。"""
        self._acquire_slot()
        try:
            with self._lock:
                if query:
                    frame = cmd.query_form
                else:
                    frame = self._build_frame(cmd, param)
                attempts = 0
                last_err = ""
                while attempts <= self._max_retries:
                    attempts += 1
                    try:
                        self._rxbuf.clear()   # 每帧前清残包，防上一帧错帧残留污染（重同步）
                        self._set_state(State.SENDING)
                        self._write_raw(frame)
                        if not query:
                            self._set_state(State.IDLE)
                            return ""
                        self._set_state(State.WAIT_RESP)
                        timeout = cmd.timeout_s or self._dflt_timeout
                        deadline = time.monotonic() + timeout
                        line = self._read_line(deadline)
                        if line:
                            self._set_state(State.IDLE)
                            return line
                        last_err = f"响应超时({cmd.timeout_s}s)"
                    except TransportError as e:
                        last_err = str(e)
                        self._rxbuf.clear()   # 链路异常后丢弃脏缓冲，重新同步
                    if attempts <= self._max_retries:
                        self._set_state(State.RETRY)
                        time.sleep(self._backoff * attempts)
                self._set_state(State.FAILED)
                self._set_state(State.IDLE)
                raise TimeoutError_(
                    f"命令 {cmd.key} 超时/失败，已重发 {attempts - 1} 次后退出: {last_err}")
        finally:
            self._release_slot()

    @staticmethod
    def _build_frame(cmd: CommandDef, param: Optional[str]) -> str:
        if param is None:
            return cmd.scpi
        return cmd.scpi.replace("{v}", str(param))

    # ---- 语义化读写（供上层 semantic/UI 调用） ----
    def query(self, key: str) -> str:
        cmd = get_cmd(key)
        if not cmd.is_query:
            raise ProtocolError(f"{key} 不是查询命令")
        return self.transact(cmd, query=True)

    def query_float(self, key: str) -> float:
        return parse_float(self.query(key))

    def set(self, key: str, value=None) -> None:
        cmd = get_cmd(key)
        if not cmd.is_set:
            raise ProtocolError(f"{key} 不是设置命令")
        self.transact(cmd, None if value is None else str(value), query=False)

    # ---- 异常码映射人话提示 ----
    def read_error(self) -> str:
        """读取一条仪器错误队列记录并映射为人话。"""
        raw = self.query("error_query")
        err = parse_error_response(raw)
        return f"{explain_error(err.code, err.message)}（原始: {raw}）"

    def clear_errors(self):
        try:
            self.set("clear_status")
        except Exception:
            pass
