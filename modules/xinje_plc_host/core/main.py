#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信捷 XD/XL 系列上位机控制软件 — 启动入口。

用法:
    python main.py
    python main.py --demo      # 内置模拟器，无需 PLC
"""
from __future__ import annotations

import os
import sys

# 让 `core` 包可导入（app/ui 内部为包内相对导入，经 core.* 顶层包名解析）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _ensure_demo_mode() -> None:
    """注入内存模拟 PLC，便于无硬件调试。"""
    from core.app import modbus
    from core.app import plc as plc_mod

    class FakeModbus(modbus.ModbusClient):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._bits = {}          # addr -> bool
            self._regs = {}          # addr -> int
            self._connected = False

        def connect(self):
            self._connected = True
            # 预置一些典型值
            for i in range(64):
                self._regs[i] = i * 10          # D0..D63
                self._bits[i] = (i % 3 == 0)    # M0..M63
            for i in range(20480, 20480 + 16):
                self._bits[i] = (i % 2 == 0)    # X
            for i in range(24576, 24576 + 16):
                self._bits[i] = (i % 2 == 1)    # Y
            self._bits[36864] = True             # SM0 运行常 ON → 模拟 RUN

        def disconnect(self):
            self._connected = False

        @property
        def connected(self):
            return self._connected

        def read_coils(self, addr, count):
            return [self._bits.get(addr + i, False) for i in range(count)]

        def read_discrete(self, addr, count):
            return self.read_coils(addr, count)

        def write_coil(self, addr, value):
            self._bits[addr] = bool(value)

        def write_coils(self, addr, values):
            for i, v in enumerate(values):
                self._bits[addr + i] = bool(v)

        def read_holding(self, addr, count):
            return [self._regs.get(addr + i, 0) & 0xFFFF for i in range(count)]

        def read_input_regs(self, addr, count):
            return self.read_holding(addr, count)

        def write_register(self, addr, value):
            self._regs[addr] = int(value) & 0xFFFF

        def write_registers(self, addr, values):
            for i, v in enumerate(values):
                self._regs[addr + i] = int(v) & 0xFFFF

        def read_device_bits(self, addrs):
            return [self._bits.get(a, False) for a in addrs]

        def read_device_words(self, addrs):
            return [self._regs.get(a, 0) & 0xFFFF for a in addrs]

    # 替换工厂
    class FakePlc(plc_mod.PlcClient):
        def __init__(self, series="XD3"):
            super().__init__(series)
            self.modbus = FakeModbus()

    plc_mod.PlcClient = FakePlc
    modbus.list_serial_ports = lambda: ["COM1", "COM3", "COM10"]


def main() -> int:
    import faulthandler
    import traceback

    faulthandler.enable()

    # 全局异常兜底：避免闪退无痕迹
    def _excepthook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            print(msg, file=sys.stderr)
        except Exception:
            pass
        try:
            from pathlib import Path
            log = Path.home() / ".xinje_host" / "crash.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    sys.excepthook = _excepthook

    if "--demo" in sys.argv or os.environ.get("XINJE_DEMO") == "1":
        _ensure_demo_mode()
        print("[demo] 已启用内置模拟器")

    from PyQt5.QtWidgets import QApplication
    from core.ui.main_window import MainWindow
    from core.ui.styles import APP_STYLE

    app = QApplication(sys.argv)
    app.setApplicationName("Xinje Host Studio")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)

    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
