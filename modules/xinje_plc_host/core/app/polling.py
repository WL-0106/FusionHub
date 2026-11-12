# -*- coding: utf-8 -*-
"""后台轮询引擎 + 报警 + 历史数据。"""
from __future__ import annotations

import csv
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from .plc import PlcClient

# 连续该轮数全部标签读取失败后标记 PLC 离线（链路仍连接、PLC 无响应）
LOST_FAIL_ROUNDS = 5


@dataclass
class MonitorTag:
    """监视标签。"""
    name: str
    label: str = ""
    kind: str = "word"          # bit | word | dword | float
    group: str = "默认"
    color: str = "#2F80ED"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    value: object = None
    raw: int = 0
    ts: float = 0.0
    ok: bool = True
    error: str = ""

    @property
    def display(self) -> str:
        if self.value is None:
            return "--"
        if self.kind == "bit":
            return "ON" if self.value else "OFF"
        if self.kind == "float":
            try:
                return f"{float(self.value):.3f}"
            except Exception:
                return str(self.value)
        try:
            v = float(self.value) * self.scale + self.offset
            if abs(v - round(v)) < 1e-9:
                return str(int(round(v)))
            return f"{v:.3f}"
        except Exception:
            return str(self.value)


@dataclass
class AlarmRule:
    tag_name: str
    rule_type: str = "hi"       # hi | lo | hihi | lolo | ne
    limit: float = 0.0
    limit2: float = 0.0
    message: str = ""
    enabled: bool = True
    active: bool = False
    active_since: float = 0.0


@dataclass
class AlarmEvent:
    ts: float
    tag_name: str
    rule_type: str
    limit: float
    value: float
    message: str
    state: str = "ON"           # ON | OFF


class PollingEngine:
    """周期读标签、写历史、触发报警。不依赖 Qt。"""

    def __init__(self, plc: PlcClient, interval: float = 0.2,
                 history_len: int = 2000):
        self.plc = plc
        self.interval = interval
        self.tags: dict[str, MonitorTag] = {}
        self.tag_order: list[str] = []
        self.alarms: list[AlarmRule] = []
        self.history: dict[str, deque] = {}
        self.history_len = history_len
        self.alarm_events: deque = deque(maxlen=500)

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()

        self.on_tags_updated: Optional[Callable[[], None]] = None
        self.on_alarm: Optional[Callable[[AlarmEvent], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_plc_state: Optional[Callable[[bool], None]] = None  # True=在线, False=离线

        self.running = False
        self.cycle_count = 0
        self.last_cycle_ms = 0.0
        self._fail_rounds = 0
        self._plc_lost = False

    # -- 标签 ------------------------------------------------------------
    def add_tag(self, tag: MonitorTag) -> None:
        with self._lock:
            if tag.name not in self.tags:
                self.tag_order.append(tag.name)
                self.history[tag.name] = deque(maxlen=self.history_len)
            self.tags[tag.name] = tag

    def remove_tag(self, name: str) -> None:
        with self._lock:
            self.tags.pop(name, None)
            self.history.pop(name, None)
            if name in self.tag_order:
                self.tag_order.remove(name)

    def clear_tags(self) -> None:
        with self._lock:
            self.tags.clear()
            self.tag_order.clear()
            self.history.clear()

    def get_tags(self) -> list[MonitorTag]:
        with self._lock:
            return [self.tags[n] for n in self.tag_order if n in self.tags]

    def add_alarm(self, rule: AlarmRule) -> None:
        with self._lock:
            self.alarms.append(rule)

    def clear_alarms(self) -> None:
        with self._lock:
            self.alarms.clear()

    def history_series(self, name: str) -> list[tuple[float, float]]:
        with self._lock:
            return list(self.history.get(name, []))

    # -- 启停 ------------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._fail_rounds = 0
        self._plc_lost = False
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="xinje-polling"
        )
        self._thread.start()
        self.running = True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.running = False

    def poll_once(self) -> None:
        self._poll_cycle()

    # -- 主循环 ----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                self._poll_cycle()
            except Exception as e:
                if self.on_error:
                    self.on_error(str(e))
            self.last_cycle_ms = (time.perf_counter() - t0) * 1000
            self.cycle_count += 1
            wait = max(0.0, self.interval - (time.perf_counter() - t0))
            self._stop.wait(wait)

    def _poll_cycle(self) -> None:
        with self._lock:
            tags = [self.tags[n] for n in self.tag_order if n in self.tags]
        if not tags:
            return

        now = time.time()
        for t in tags:
            try:
                if t.kind == "bit":
                    v = self.plc.read_bit(t.name)
                    t.value = v
                    t.raw = int(v)
                    hist_v = float(v)
                elif t.kind == "word":
                    v = self.plc.read_word(t.name)
                    signed = v - 65536 if v >= 32768 else v
                    t.value = signed
                    t.raw = v
                    hist_v = float(signed)
                elif t.kind == "dword":
                    v = self.plc.read_dword(t.name)
                    if v >= 0x80000000:
                        v -= 0x100000000
                    t.value = v
                    t.raw = v & 0xFFFFFFFF
                    hist_v = float(v)
                else:
                    fv = self.plc.read_float(t.name)
                    t.value = fv
                    t.raw = 0
                    hist_v = float(fv)
                t.ts = now
                t.ok = True
                t.error = ""
                self.history.setdefault(
                    t.name, deque(maxlen=self.history_len)
                ).append((now, hist_v))
            except Exception as e:
                t.ok = False
                t.error = str(e)

        # PLC 掉电但链路仍在：整轮全部读取失败连续达限 → 标记离线；恢复 → 自动上线
        if all(not t.ok for t in tags):
            self._fail_rounds += 1
            if self._fail_rounds >= LOST_FAIL_ROUNDS and not self._plc_lost:
                self._plc_lost = True
                self._fire_plc_state(False)
        else:
            self._fail_rounds = 0
            if self._plc_lost:
                self._plc_lost = False
                self._fire_plc_state(True)

        self._check_alarms(tags, now)
        if self.on_tags_updated:
            try:
                self.on_tags_updated()
            except Exception:
                # 回调异常不能打断轮询线程
                pass

    def _fire_plc_state(self, online: bool) -> None:
        """PLC 在线/离线状态回调（回调异常不能打断轮询线程）。"""
        if self.on_plc_state:
            try:
                self.on_plc_state(online)
            except Exception:
                pass

    def _check_alarms(self, tags: Sequence[MonitorTag], now: float) -> None:
        by_name = {t.name: t for t in tags}
        for rule in self.alarms:
            if not rule.enabled:
                continue
            t = by_name.get(rule.tag_name)
            if t is None or t.value is None:
                continue
            try:
                val = float(t.value)
            except Exception:
                continue

            rt = rule.rule_type
            triggered = False
            if rt == "hi" and val > rule.limit:
                triggered = True
            elif rt == "lo" and val < rule.limit:
                triggered = True
            elif rt == "hihi" and val > rule.limit2:
                triggered = True
            elif rt == "lolo" and val < rule.limit2:
                triggered = True
            elif rt == "ne" and abs(val - rule.limit) > 1e-9:
                triggered = True

            if triggered and not rule.active:
                rule.active = True
                rule.active_since = now
                ev = AlarmEvent(
                    ts=now, tag_name=rule.tag_name, rule_type=rt,
                    limit=rule.limit, value=val,
                    message=rule.message or f"{rule.tag_name} {rt} {rule.limit}",
                    state="ON",
                )
                self.alarm_events.append(ev)
                if self.on_alarm:
                    try:
                        self.on_alarm(ev)
                    except Exception:
                        pass
            elif not triggered and rule.active:
                rule.active = False
                ev = AlarmEvent(
                    ts=now, tag_name=rule.tag_name, rule_type=rt,
                    limit=rule.limit, value=val,
                    message=rule.message or f"{rule.tag_name} 恢复",
                    state="OFF",
                )
                self.alarm_events.append(ev)
                if self.on_alarm:
                    try:
                        self.on_alarm(ev)
                    except Exception:
                        pass

    # -- 导出 ------------------------------------------------------------
    def export_history_csv(self, path: str | Path,
                           names: Optional[Sequence[str]] = None) -> int:
        path = Path(path)
        with self._lock:
            names = list(names) if names else list(self.history.keys())
            rows = 0
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "time", "device", "value"])
                for name in names:
                    for ts, val in self.history.get(name, []):
                        w.writerow([
                            f"{ts:.3f}",
                            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                            name, val,
                        ])
                        rows += 1
        return rows

    def export_alarms_csv(self, path: str | Path) -> int:
        path = Path(path)
        events = list(self.alarm_events)
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "time", "device", "type", "limit",
                        "value", "message", "state"])
            for e in events:
                w.writerow([
                    f"{e.ts:.3f}",
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.ts)),
                    e.tag_name, e.rule_type, e.limit, e.value, e.message, e.state,
                ])
        return len(events)
