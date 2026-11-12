"""GPP 设备驱动：后台线程内串行执行 SCPI 锁步收发、周期测量、状态快照。"""
from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from PyQt5.QtCore import QObject, pyqtSignal as Signal

from .models import (
    ChannelSpec, ConnectionState, LinkType, MeasSample, detect_model,
    generic_specs, specs_for,
)
from .transport import (
    LanTransport, SimTransport, SerialTransport, Transport, TransportError,
)

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_numbers(text: str) -> list[float]:
    return [float(x) for x in _NUM_RE.findall(text or "")]


def decode_response(raw: bytes) -> str:
    """设备响应解码：先 UTF-8，失败回退 gb18030(固件中文信息常为 GBK)。"""
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def is_no_error(text: str) -> bool:
    """判断 :SYSTem:ERRor? 响应是否表示“队列为空/无错误”。"""
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    return (
        t.startswith("+0")
        or t.startswith("0,")
        or t.startswith("000")
        or "no error" in low
        or "无错误" in t
    )


@dataclass
class ConnectParams:
    link: LinkType = LinkType.SERIAL
    port: str = ""
    baud: int = 115200
    host: str = ""
    tcp_port: int = 1026
    simulate: bool = False
    sim_model: str = "GPP-4323"

    def describe(self) -> str:
        if self.simulate:
            return f"模拟设备 {self.sim_model}"
        if self.link == LinkType.LAN:
            return f"LAN {self.host}:{self.tcp_port}"
        return f"{self.port} @ {self.baud}"


@dataclass
class _Job:
    kind: str
    params: Optional[ConnectParams] = None
    cmd: str = ""
    expect_reply: bool = False
    done: Optional[Callable[[Optional[str], Optional[str]], None]] = None
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[str] = None
    error: str = ""


class GppDriver(QObject):
    """所有收发都在同一后台线程内串行执行，天然避免总线竞争。"""

    log_tx = Signal(str)
    log_rx = Signal(str)
    state_changed = Signal(object)          # ConnectionState
    snapshot = Signal(dict)                 # 连接后的全量初始状态
    samples = Signal(list)                  # list[MeasSample]
    notice = Signal(str)                    # 提示 / 仪器错误队列
    fatal = Signal(str)                     # 链路级故障(会自动断开)

    POLL_DEFAULT = 0.5

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._jobs: "queue.Queue[_Job]" = queue.Queue()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._transport: Optional[Transport] = None
        self._state = ConnectionState()
        self._specs: list[ChannelSpec] = []
        self._sets: dict[int, dict] = {}
        self._poll_interval = self.POLL_DEFAULT
        self._poll_enabled = True
        self._next_poll = 0.0
        self._cycle = 0
        self._last_err_check = 0.0
        self._last_err_text = ""

    # ---------------- 公共 API(UI 线程调用) ----------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gpp-driver", daemon=True)
        self._thread.start()

    def connect(self, params: ConnectParams) -> None:
        self._enqueue(_Job("connect", params=params))

    def disconnect(self, send_local: bool = True) -> None:
        self._enqueue(_Job("disconnect", cmd="LOCAL" if send_local else ""))

    def set(self, cmd: str) -> None:
        self._enqueue(_Job("set", cmd=cmd))

    def query(self, cmd: str, timeout: float = 5.0) -> tuple[Optional[str], str]:
        """阻塞式查询，仅供退出/自检等非 GUI 热路径使用。"""
        if not self._thread or not self._thread.is_alive():
            return None, "驱动线程未运行"
        job = _Job("query", cmd=cmd)
        self._enqueue(job)
        job.event.wait(timeout)
        if not job.event.is_set():
            return None, f"查询超时: {cmd}"
        return job.result, job.error

    def shutdown(self, outputs_off: bool = True, timeout: float = 3.0) -> None:
        if self.is_connected():
            if outputs_off:
                r, e = self.query(":ALLOUTOFF", timeout=timeout)
                if e:
                    r, e = self.query(":ALLOUTOFF", timeout=timeout)
            self.query(":SYSTem:LOCal", timeout=timeout)
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def is_connected(self) -> bool:
        return self._state.connected

    @property
    def specs(self) -> list[ChannelSpec]:
        return list(self._specs)

    @property
    def sets(self) -> dict[int, dict]:
        return {k: dict(v) for k, v in self._sets.items()}

    def set_local_value(self, channel: int, key: str, value: float) -> None:
        self._sets.setdefault(channel, {}).update({key: value})

    def set_poll_interval(self, seconds: float) -> None:
        self._poll_interval = max(0.1, float(seconds))

    def set_polling(self, enabled: bool) -> None:
        self._poll_enabled = enabled

    # ---------------- 内部 ----------------
    def _enqueue(self, job: _Job) -> None:
        self._jobs.put(job)
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            did = False
            try:
                did = self._drain_jobs()
                if self._state.connected and self._poll_enabled and self._transport:
                    now = time.monotonic()
                    if now >= self._next_poll:
                        self._poll()
                        self._next_poll = time.monotonic() + self._poll_interval
                        did = True
            except TransportError as e:
                self._link_lost(str(e))
            except Exception as e:  # 驱动线程绝不能死
                self.fatal.emit(f"驱动内部错误: {e!r}")
            if not did:
                timeout = 0.2
                if self._state.connected and self._poll_enabled:
                    timeout = max(0.01, min(0.2, self._next_poll - time.monotonic()))
                self._wake.wait(timeout)
                self._wake.clear()

    def _drain_jobs(self) -> bool:
        did = False
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return did
            did = True
            try:
                self._exec(job)
            except TransportError as e:
                job.error = str(e)
                if job.kind == "connect":
                    self._teardown()
                    self._state = ConnectionState(False, detail=str(e))
                    self.state_changed.emit(self._state)
                    self.fatal.emit(str(e))
                elif job.kind in ("set", "query"):
                    self._link_lost(str(e))
            finally:
                job.event.set()

    def _exec(self, job: _Job) -> None:
        if job.kind == "connect":
            self._do_connect(job)
        elif job.kind == "disconnect":
            self._do_disconnect(job)
        elif job.kind == "set":
            self._write_line(job.cmd)
        elif job.kind == "query":
            job.result = self._query(job.cmd)

    # ---- 连接/断开 ----
    def _do_connect(self, job: _Job) -> None:
        p = job.params
        if p is None:
            job.error = "缺少连接参数"
            return
        self._teardown()
        if p.simulate:
            transport: Transport = SimTransport(p.sim_model)
        elif p.link == LinkType.LAN:
            transport = LanTransport(p.host, p.tcp_port)
        else:
            transport = SerialTransport(p.port, p.baud)
        transport.open()
        self._transport = transport
        self.log_tx.emit(f"[OPEN] {transport.name}")

        idn = ""
        last_err = ""
        for _ in range(3):
            try:
                idn = self._query("*IDN?", timeout=1.5)
                break
            except TransportError as e:
                last_err = str(e)
                time.sleep(0.2)
        if not idn:
            raise TransportError(f"设备无响应(*IDN?): {last_err}")

        model = detect_model(idn)
        if model:
            self._specs = specs_for(model)
        else:
            count = self._infer_channel_count()
            self._specs = generic_specs(count)
            self.notice.emit(f"未能从 IDN 识别机型，按 {count} 通道通用规格处理: {idn}")

        self._state = ConnectionState(True, idn=idn, model=model or "GPP-????",
                                      detail=transport.name)
        self.state_changed.emit(self._state)
        snap = self._fetch_snapshot()
        self.snapshot.emit(snap)
        self._next_poll = 0.0
        self._cycle = 0

    def _infer_channel_count(self) -> int:
        """机型未知时用 :SOURce:VOLTage:ALL? 的返回个数推断通道数。"""
        try:
            nums = parse_numbers(self._query(":SOURce:VOLTage:ALL?", timeout=1.5))
            if 1 <= len(nums) <= 4:
                return len(nums)
        except TransportError:
            raise
        except Exception:
            pass
        return 2

    def _fetch_snapshot(self) -> dict:
        snap: dict = {"channels": {}, "channel_count": len(self._specs)}
        for spec in self._specs:
            n = spec.index
            v_set = self._safe_num(f":SOURce{n}:VOLTage?")
            i_set = self._safe_num(f":SOURce{n}:CURRent?")
            out = self._query(f":OUTPut{n}?").strip().upper() in ("ON", "1")
            ovp = self._safe_num(f":OUTPut{n}:OVP?")
            ocp = self._safe_num(f":OUTPut{n}:OCP?")
            ovp_en = self._query(f":OUTPut{n}:OVP:STATe?").strip().upper() in ("ON", "1")
            ocp_en = self._query(f":OUTPut{n}:OCP:STATe?").strip().upper() in ("ON", "1")
            mode = self._query(f":MODE{n}?").strip() if n <= 2 else "Independent"
            snap["channels"][n] = {
                "v_set": v_set, "i_set": i_set, "output": out,
                "ovp": ovp, "ocp": ocp, "ovp_en": ovp_en, "ocp_en": ocp_en,
                "mode": mode,
            }
            self._sets[n] = {"v": v_set, "i": i_set, "out": out}
        return snap

    def _do_disconnect(self, job: _Job) -> None:
        if job.cmd and self._transport:
            try:
                self._write_line(job.cmd)
            except TransportError:
                pass
        self._teardown()
        self._state = ConnectionState(False, detail="已断开")
        self.state_changed.emit(self._state)

    def _teardown(self) -> None:
        if self._transport:
            name = self._transport.name
            try:
                self._transport.close()
            except Exception:
                pass
            self.log_tx.emit(f"[CLOSE] {name}")
        self._transport = None

    def _link_lost(self, msg: str) -> None:
        self._teardown()
        self._state = ConnectionState(False, detail=msg)
        self.state_changed.emit(self._state)
        self.fatal.emit(f"链路中断: {msg}")

    # ---- 锁步收发 ----
    def _write_line(self, cmd: str) -> None:
        if not self._transport:
            raise TransportError("未连接设备")
        self.log_tx.emit(cmd)
        self._transport.write((cmd + "\n").encode("ascii", errors="ignore"))

    def _query(self, cmd: str, timeout: float = 1.5) -> str:
        """锁步查询。读超时先丢弃缓冲重新同步并重发一次，避免偶发无应答直接断链。"""
        last: Optional[TransportError] = None
        for attempt in range(2):
            try:
                self._write_line(cmd)
                raw = self._transport.read_line(timeout)
                resp = decode_response(raw)
                self.log_rx.emit(resp)
                return resp
            except TransportError as e:
                last = e
                if attempt == 0:
                    time.sleep(0.1)             # 给迟到的响应一点时间
                    try:
                        self._transport.discard()  # 丢弃迟到/错位数据
                    except Exception:
                        pass
                    self.log_rx.emit(f"[重试] {cmd} ({e})")
                    continue
                raise last

    def _safe_num(self, cmd: str, default: float = 0.0) -> float:
        try:
            nums = parse_numbers(self._query(cmd))
            return nums[0] if nums else default
        except TransportError:
            raise
        except Exception:
            return default

    # ---- 周期测量 ----
    def _poll(self) -> None:
        self._cycle += 1
        now = time.monotonic()
        want_io = (self._cycle % 3) == 1      # 输出状态与限流指示隔轮查
        want_err = (now - self._last_err_check) > 4.0
        out: list[MeasSample] = []
        for spec in self._specs:
            n = spec.index
            nums = parse_numbers(self._query(f":MEASure{n}:ALL?"))
            v = nums[0] if len(nums) > 0 else 0.0
            i = nums[1] if len(nums) > 1 else 0.0
            p = nums[2] if len(nums) > 2 else 0.0
            s = MeasSample(n, now, v=v, i=i, p=p)
            st = self._sets.setdefault(n, {})
            s.v_set = st.get("v", 0.0)
            s.i_set = st.get("i", 0.0)
            s.output_on = st.get("out", False)
            if want_io:
                resp = self._query(f":OUTPut{n}?").strip().upper()
                s.output_on = resp in ("ON", "1")
                st["out"] = s.output_on
                if spec.i_settable:
                    s.cc = self._query(f":SOURce{n}:CURRent:LIMit:STATe?").strip()[:1] == "1"
            out.append(s)
        self.samples.emit(out)
        if want_err:
            self._last_err_check = now
            err = self._query(":SYSTem:ERRor?").strip()
            if is_no_error(err):
                self._last_err_text = ""
            elif err != self._last_err_text:    # 连续相同内容只提示一次
                self._last_err_text = err
                self.notice.emit(f"仪器错误队列: {err}")
