"""后台轮询线程：周期读取 X/Y/M/D + PLC RUN/STOP，通过回调推送到 UI."""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..protocol.client import ModbusClient
from ..protocol.modbus import ModbusError
from ..protocol.transport import TransportError

from .address_map import D_BASE, M_BASE, X_BASE, Y_BASE

# Easy 系列常用 RUN 监视继电器（M8000，FX 兼容）。地址可配。
RUN_STATUS_BIT_ADDR = M_BASE + 8000

# 连续失败该轮数后标记 PLC 离线（链路仍连接、PLC 无响应）
LOST_FAIL_LIMIT = 5


@dataclass
class Snapshot:
    timestamp: float
    x: List[bool] = field(default_factory=list)
    y: List[bool] = field(default_factory=list)
    m: List[bool] = field(default_factory=list)
    d: List[int] = field(default_factory=list)
    plc_run: Optional[bool] = None  # None=未知, True=RUN, False=STOP
    error: Optional[str] = None


OnSnapshot = Callable[[Snapshot], None]
OnLog = Callable[[str], None]


class Poller:
    def __init__(
        self,
        client: ModbusClient,
        slave: int,
        x_count: int,
        y_count: int,
        m_count: int,
        d_count: int,
        interval: float = 0.2,
        on_snapshot: Optional[OnSnapshot] = None,
        on_log: Optional[OnLog] = None,
        on_plc_state: Optional[Callable[[bool], None]] = None,
    ):
        self.client = client
        self.slave = slave
        self.x_count = max(1, x_count)
        self.y_count = max(1, y_count)
        self.m_count = max(1, m_count)
        self.d_count = max(1, d_count)
        self.interval = interval
        self.on_snapshot = on_snapshot
        self.on_log = on_log
        self.on_plc_state = on_plc_state   # True=PLC 在线, False=离线

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = False
        self._status_tick = 0
        self._fail_rounds = 0
        self._plc_lost = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._stop.clear()
        self._fail_rounds = 0
        self._plc_lost = False
        self._thread = threading.Thread(target=self._run, name="easy-poller", daemon=True)
        self._running = True
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=1.5)
        self._thread = None

    def update_params(
        self,
        slave: int,
        x_count: int,
        y_count: int,
        m_count: int,
        d_count: int,
        interval: float,
    ) -> None:
        self.slave = slave
        self.x_count = max(1, x_count)
        self.y_count = max(1, y_count)
        self.m_count = max(1, m_count)
        self.d_count = max(1, d_count)
        self.interval = interval

    def _read_plc_run(self) -> Optional[bool]:
        """读 M8000 判断 RUN/STOP；失败返回 None."""
        try:
            bits = self.client.read_coils(self.slave, RUN_STATUS_BIT_ADDR, 1)
            return bool(bits[0]) if bits else None
        except Exception:
            return None

    def _fire_plc_state(self, online: bool) -> None:
        """PLC 在线/离线状态回调（回调异常不能打断轮询线程）。"""
        if self.on_plc_state:
            try:
                self.on_plc_state(online)
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            snap = Snapshot(timestamp=time.time())
            try:
                snap.x = self.client.read_coils(self.slave, X_BASE, self.x_count)
                snap.y = self.client.read_coils(self.slave, Y_BASE, self.y_count)
                if self.m_count > 0:
                    snap.m = self.client.read_coils(self.slave, M_BASE, self.m_count)
                if self.d_count > 0:
                    snap.d = self.client.read_registers(self.slave, D_BASE, self.d_count)
                # RUN/STOP：每个周期读 M8000（开销很小）
                snap.plc_run = self._read_plc_run()
            except (TransportError, ModbusError, ValueError, OSError) as exc:
                snap.error = str(exc)
                if self.on_log:
                    self.on_log(f"轮询失败: {exc}")
            except Exception as exc:  # pragma: no cover
                snap.error = f"{exc}"
                if self.on_log:
                    self.on_log(f"轮询异常: {exc}\n{traceback.format_exc()}")

            # PLC 掉电但链路仍在：连续失败达限 → 标记离线；恢复成功 → 自动上线
            if snap.error:
                self._fail_rounds += 1
                if self._fail_rounds >= LOST_FAIL_LIMIT and not self._plc_lost:
                    self._plc_lost = True
                    self._fire_plc_state(False)
            else:
                self._fail_rounds = 0
                if self._plc_lost:
                    self._plc_lost = False
                    self._fire_plc_state(True)

            if self.on_snapshot:
                try:
                    self.on_snapshot(snap)
                except Exception:
                    pass

            elapsed = time.monotonic() - t0
            wait = max(0.0, self.interval - elapsed)
            self._stop.wait(wait)

        self._running = False
