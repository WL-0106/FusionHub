# -*- coding: utf-8 -*-
"""仪表高层 API：封装连接、测量设置、读数、后台轮询。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from . import scpi
from .transport import (SerialTransport, SimTransport, TcpTransport,
                        Transport, TransportError)


class NoDataError(TransportError):
    """仪器返回 +9.9E37：超量程 / 开路 / 测量尚未完成。属于正常状态，不是通信故障。"""


@dataclass
class Reading:
    value: float
    unit: str
    raw: str = ""
    func: str = ""
    ts: float = 0.0
    index: int = 0


class Meter:
    """一台 GDM-9060/9061。所有 I/O 串行化，可被多个线程调用。"""

    def __init__(self):
        self._transport: Optional[Transport] = None
        self._lock = threading.RLock()
        self.info = {}

    # -- 连接管理 ------------------------------------------------------
    def open(self, kind: str, **kw) -> dict:
        self.close()
        if kind == "serial":
            tr = SerialTransport(kw.get("port", "COM3"), int(kw.get("baud", 115200)))
        elif kind == "tcp":
            tr = TcpTransport(kw.get("host", "192.168.1.100"), int(kw.get("port", 3001)))
        elif kind == "sim":
            tr = SimTransport(kw.get("model", "GDM9061"))
        else:
            raise TransportError(f"未知接口类型：{kind}")
        tr.open()
        self._transport = tr
        try:
            idn = self.query("*IDN?")
        except Exception:
            self.close()
            raise
        self.info = self._parse_idn(idn)
        self.info["channel"] = tr.name
        self.info["kind"] = tr.kind
        return self.info

    def close(self):
        if self._transport is not None:
            try:
                self._transport.close()
            finally:
                self._transport = None

    @property
    def connected(self) -> bool:
        return self._transport is not None and self._transport.is_open

    @property
    def transport(self) -> Optional[Transport]:
        """底层通道（自检/调试用，可直接取指令流水 sent）。"""
        return self._transport

    @property
    def channel_name(self) -> str:
        return self._transport.name if self._transport else "未连接"

    @staticmethod
    def _parse_idn(text: str) -> dict:
        parts = [p.strip() for p in (text or "").split(",")]
        while len(parts) < 4:
            parts.append("")
        return {"raw": text, "vendor": parts[0], "model": parts[1],
                "serial": parts[2], "firmware": parts[3]}

    # -- 基础收发 ------------------------------------------------------
    def write(self, cmd: str):
        if not self.connected:
            raise TransportError("设备未连接")
        with self._lock:
            self._transport.write(cmd)

    def query(self, cmd: str, timeout: float = 2.0) -> str:
        if not self.connected:
            raise TransportError("设备未连接")
        with self._lock:
            self._transport.write(cmd)
            return self._transport.readline(timeout)

    def send_all(self, cmds, timeout: float = 2.0):
        for c in cmds:
            self.write(c)

    # -- 测量设置 ------------------------------------------------------
    def configure(self, func_key: str, range_value: Optional[float] = None,
                  nplc: Optional[float] = None, temp_type: str = "K",
                  temp_unit: str = "C"):
        cmds = scpi.cmd_configure(func_key, range_value, nplc, temp_type, temp_unit)
        for c in cmds:
            self.write(c)

    def set_second_display(self, second: str):
        for c in scpi.cmd_second_display(second):
            self.write(c)

    def relative_on(self, func_key: str, reference: float):
        cmds = scpi.cmd_relative_on(func_key, reference)
        for c in cmds:
            self.write(c)

    def relative_off(self, func_key: str):
        for c in scpi.cmd_relative_off(func_key):
            self.write(c)

    def autozero_once(self, func_key: str):
        for c in scpi.cmd_autozero_once(func_key):
            self.write(c)

    # -- 读数 ----------------------------------------------------------
    def read_value(self, func_key: str = "") -> Reading:
        """READ? 触发一次测量并取值（不带单位，单位由当前功能推出）。"""
        raw = self.query("READ?", timeout=5.0)
        if not raw:
            raise TransportError("设备无响应（READ?）")
        head = raw.split(",")[-1].strip()      # 多采样时取最后一个
        parsed = scpi.parse_reading(head)
        if parsed is None:
            if scpi.is_no_data(head):
                raise NoDataError("超量程 / 开路 / 测量未完成")
            raise TransportError(f"读数解析失败：{raw[:40]}")
        value, dev_unit = parsed
        unit = scpi.FUNCS[func_key].unit if func_key in scpi.FUNCS else dev_unit
        return Reading(value=value, unit=unit, raw=raw, func=func_key, ts=time.time())

    def read_last(self, func_key: str = "") -> Reading:
        """DATA:LAST? 返回 "值 单位"，不触发新测量。"""
        raw = self.query("DATA:LAST?", timeout=3.0)
        parsed = scpi.parse_reading(raw)
        if parsed is None:
            raise TransportError(f"无数据：{raw[:40]}")
        value, dev_unit = parsed
        unit = scpi.FUNCS[func_key].unit if func_key in scpi.FUNCS else dev_unit
        return Reading(value=value, unit=unit, raw=raw, func=func_key, ts=time.time())

    def read_second(self) -> Optional[float]:
        raw = self.query("DATA2:LAST?", timeout=2.0)
        parsed = scpi.parse_reading(raw)
        return parsed[0] if parsed else None

    # -- 设备杂项 ------------------------------------------------------
    def check_error(self) -> Optional[str]:
        raw = self.query(scpi.cmd_error_query(), timeout=2.0)
        if scpi.is_error_response(raw):
            return raw
        return None

    def beep(self):
        self.write("SYST:BEEP:IMM")

    def display_text(self, text: str):
        safe = text.replace('"', "'")[:40]
        self.write(f'DISP:TEXT:DATA "{safe}"')

    def display_text_clear(self):
        self.write("DISP:TEXT:CLE")

    def display_on(self, on: bool):
        self.write(f"DISP {'ON' if on else 'OFF'}")

    def remote(self):
        self.write("SYST:REM")

    def local(self):
        self.write("SYST:LOC")

    def reset(self):
        self.write("*RST")
        self.write("*CLS")

    # -- 屏幕截图（HCOPy:SDUMp:DATA? 返回 BMP 二进制块） ---------------
    def screenshot(self, path: str) -> str:
        if not self.connected:
            raise TransportError("设备未连接")
        with self._lock:
            self._transport.write("HCOP:SDUM:DATA?")
            data = self._read_block()
        if not data:
            raise TransportError("设备未返回图像数据")
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _read_block(self) -> bytes:
        """解析 IEEE488.2 的定长数据块：#<n><len><data>。"""
        tr = self._transport
        first = tr.read_raw(1, 2.0)
        if first != b"#":
            # 不是数据块，按行读掉，抛错
            rest = tr.readline(1.0)
            raise TransportError(f"响应不是二进制块：{first!r}{rest[:40]}")
        nd = tr.read_raw(1, 2.0)
        try:
            n = int(nd)
        except ValueError:
            raise TransportError("数据块长度位非法")
        if n == 0:
            return b""
        len_txt = tr.read_raw(n, 3.0)
        try:
            size = int(len_txt)
        except ValueError:
            raise TransportError("数据块长度非法")
        if size <= 0 or size > 40 * 1024 * 1024:
            raise TransportError(f"数据块长度异常：{size}")
        buf = bytearray()
        end = time.time() + 20.0
        while len(buf) < size and time.time() < end:
            chunk = tr.read_raw(size - len(buf), 5.0)
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)


class Poller:
    """后台轮询线程：按固定间隔读取一次测量值。

    这里用「组合」而非继承 threading.Thread —— 继承时 self._stop / self._target
    之类的名字会覆盖 Thread 的内部属性，导致 join() 等行为异常。
    """

    def __init__(self, meter: Meter, interval: float, func_key: str,
                 on_sample, on_error=None):
        self.meter = meter
        self.interval = float(interval)
        self.func_key = func_key
        self.on_sample = on_sample
        self.on_error = on_error
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="gdm-poll", daemon=True)
        self._thread.start()

    def stop(self, wait: float = 2.0):
        self._stop_event.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(wait)
        self._thread = None

    def _run(self):
        while not self._stop_event.is_set():
            t0 = time.time()
            try:
                reading = self.meter.read_value(self.func_key)
                if not self._stop_event.is_set():
                    self.on_sample(reading)
            except Exception as exc:            # 通信异常要能反映到界面上
                if self.on_error is not None:
                    self.on_error(exc)
                self._stop_event.wait(0.4)
                continue
            gap = self.interval - (time.time() - t0)
            self._stop_event.wait(max(0.01, gap))
