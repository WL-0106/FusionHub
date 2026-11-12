# -*- coding: utf-8 -*-
"""仪器控制器：单工作线程独占传输层，事件队列回传 UI"""

import queue
import threading
import time
from typing import Callable, List, Optional

from .transport import Transport, TransportError

# 周期测量连续失败该次数后标记设备离线（链路仍连接、仪器无响应）
MONITOR_LOST_FAILS = 5


class Dm3058Controller:
    """
    事件类型（放入 events 队列）:
      ("log", "TX"|"RX", text)          SCPI 日志
      ("connected", idn, scpi_version)  连接成功
      ("disconnected",)                 连接断开
      ("error", message)                错误提示
      ("reading", value, timestamp, secondary|None)  测量读数
      ("query", token, response)        查询结果（token 由 UI 指定）
      ("func", key)                     当前功能
      ("device_lost", message)          设备级离线（链路仍在，仪器无响应）
      ("device_recovered",)             设备级离线恢复
    """

    def __init__(self, terminator: bytes = b"\n"):
        self._jobs: "queue.Queue" = queue.Queue()
        self._events: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._transport: Optional[Transport] = None
        self._term = terminator

        self._monitor_on = False
        self._monitor_interval = 0.2
        self._monitor_cmds: List[str] = []
        self._monitor_key = ""
        self._monitor_next = 0.0
        self._monitor_timeout = 5.0
        self._monitor_fail_count = 0
        self._monitor_lost = False

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dm3058-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None

    def events(self) -> list:
        out = []
        try:
            while True:
                out.append(self._events.get_nowait())
        except queue.Empty:
            pass
        return out

    # ------------------------------------------------------------ UI 调用接口
    def connect(self, factory: Callable[[], Transport]) -> None:
        self._jobs.put(("connect", factory))

    def disconnect(self) -> None:
        self._jobs.put(("disconnect",))

    def write(self, cmd: str) -> None:
        self._jobs.put(("write", cmd))

    def query(self, cmd: str, token: str = "") -> None:
        self._jobs.put(("query", cmd, token))

    def set_monitor(self, enabled: bool, interval: float = 0.2,
                    cmds: Optional[List[str]] = None, timeout: float = 5.0,
                    key: str = "") -> None:
        """启用/停止周期测量；key 为功能标识，读数事件会原样带回，便于 UI 丢弃过期数据"""
        self._jobs.put(("monitor", enabled, interval, cmds or [], timeout, key))

    @property
    def connected(self) -> bool:
        return self._transport is not None

    # ------------------------------------------------------------ 工作线程
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.02)
            except queue.Empty:
                job = None
            if job is None:
                if self._stop.is_set():
                    break
            else:
                try:
                    self._handle_job(job)
                except Exception as e:  # noqa: BLE001 —— 工作线程兜底
                    self._events.put(("error", f"内部错误: {e}"))

            # 周期测量插在任务间隙执行
            if (self._monitor_on and self._transport is not None
                    and time.time() >= self._monitor_next):
                try:
                    self._do_monitor()
                except Exception as e:  # noqa: BLE001 —— monitor 兜底，防线程死亡
                    self._events.put(("error", f"监控异常: {e}"))

        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None

    def _handle_job(self, job) -> None:
        kind = job[0]
        if kind == "connect":
            factory = job[1]
            if self._transport:
                try:
                    self._transport.close()
                except Exception:
                    pass
                self._transport = None
            try:
                self._transport = factory()
            except TransportError as e:
                self._events.put(("error", str(e)))
                return
            except Exception as e:  # noqa: BLE001
                self._events.put(("error", f"连接失败: {e}"))
                return
            # 初始化：RIGOL 命令集 + 清状态 + 读 ID
            for cmd in ("CMDSET RIGOL", "*CLS"):
                self._raw_write(cmd)
            idn = self._raw_query("*IDN?", timeout=3.0) or "(无响应)"
            ver = self._raw_query("SYSTem:VERSion?", timeout=2.0) or "?"
            func = self._raw_query(":FUNCtion?", timeout=2.0) or ""
            self._monitor_fail_count = 0
            self._monitor_lost = False
            self._events.put(("connected", idn, ver))
            if func:
                self._events.put(("func", func.strip().upper()))
        elif kind == "disconnect":
            self._monitor_on = False
            if self._transport:
                try:
                    self._transport.close()
                except Exception:
                    pass
                self._transport = None
            self._events.put(("disconnected",))
        elif kind == "write":
            if self._transport:
                self._raw_write(job[1])
        elif kind == "query":
            if self._transport:
                resp = self._raw_query(job[1])
                if resp is not None:
                    self._events.put(("query", job[2], resp))
        elif kind == "monitor":
            _, enabled, interval, cmds, timeout, *rest = job
            key = rest[0] if rest else ""
            self._monitor_on = bool(enabled) and self._transport is not None
            self._monitor_interval = max(0.05, float(interval))
            self._monitor_cmds = list(cmds)
            self._monitor_timeout = float(timeout)
            self._monitor_key = key
            self._monitor_next = time.time()
            self._monitor_fail_count = 0
            self._monitor_lost = False

    # ------------------------------------------------------------ 底层 IO
    def _raw_write(self, cmd: str) -> None:
        if not self._transport:
            return
        payload = cmd.encode("ascii", errors="ignore") + self._term
        try:
            self._transport.write(payload)
        except TransportError as e:
            self._events.put(("error", str(e)))
            self._drop_connection()
            return
        self._events.put(("log", "TX", cmd))

    def _raw_read_until_term(self, timeout: float) -> Optional[str]:
        if not self._transport:
            return None
        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline:
            try:
                chunk = self._transport.read_some(4096)
            except TransportError as e:
                self._events.put(("error", str(e)))
                self._drop_connection()
                return None
            if chunk:
                buf += chunk
                if self._term in buf or b"\r" in buf or b"\n" in buf:
                    # 有些固件回 \r\n，等到第一个换行即可
                    for i, b in enumerate(buf):
                        if b in (0x0A, 0x0D):
                            text = buf[:i].decode("ascii", errors="ignore").strip()
                            rest = buf[i + 1:].lstrip(b"\r\n")
                            # 多读到的多余数据丢弃（查询响应不应有后续数据）
                            if rest:
                                pass
                            if text:
                                self._events.put(("log", "RX", text))
                            return text if text else ""
            else:
                time.sleep(0.01)
        self._events.put(("error", f"查询超时（{timeout:.1f}s）"))
        return None

    def _raw_query(self, cmd: str, timeout: float = 2.0) -> Optional[str]:
        self._raw_write(cmd)
        if not self._transport:
            return None
        return self._raw_read_until_term(timeout)

    def _drop_connection(self) -> None:
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._monitor_on = False
        self._monitor_fail_count = 0
        self._monitor_lost = False
        self._events.put(("disconnected",))

    # ------------------------------------------------------------ 周期测量
    def _do_monitor(self) -> None:
        self._monitor_next = time.time() + self._monitor_interval
        if not self._monitor_cmds or not self._transport:
            return
        values = []
        for cmd in self._monitor_cmds:
            resp = self._raw_query(cmd, timeout=self._monitor_timeout)
            if resp is None:
                if self._transport is None:
                    return   # 链路级异常已发 disconnected，UI 已感知
                # 设备掉电但链路仍在：连续超时计数，达限标记设备离线
                self._monitor_fail_count += 1
                if (self._monitor_fail_count >= MONITOR_LOST_FAILS
                        and not self._monitor_lost):
                    self._monitor_lost = True
                    self._events.put((
                        "device_lost",
                        f"连续 {MONITOR_LOST_FAILS} 次查询无响应，"
                        f"DM3058 可能已掉电或离线（链路仍连接）",
                    ))
                return
            values.append(resp)
        # 本轮全部有响应：失败计数清零；离线状态下自动恢复在线
        self._monitor_fail_count = 0
        if self._monitor_lost:
            self._monitor_lost = False
            self._events.put(("device_recovered",))
        primary = self._to_float(values[0])
        if primary is None:
            # P/F 等非数值查询：按字符串事件送出
            self._events.put(("reading_str", values[0], time.time(),
                              values[1] if len(values) > 1 else None,
                              self._monitor_key))
            return
        secondary = self._to_float(values[1]) if len(values) > 1 else None
        self._events.put(("reading", primary, time.time(), secondary,
                          self._monitor_key))

    @staticmethod
    def _to_float(text: str) -> Optional[float]:
        try:
            return float(text.strip())
        except (ValueError, AttributeError):
            return None
