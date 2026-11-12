# -*- coding: utf-8 -*-
"""JT632xA 电子负载模拟器（内存 SCPI 从站）。

没接真机时也能把上位机跑通、把协议栈验一遍。
行为边界（与真机可能有差异，写在这里避免现场误判）：
  * 模拟的是一台理想负载：CC 下电流恒等于设定值，电压等于被测源电压
  * 过流/过功率保护设为「锁存」：触发后保持置位，直到主机关闭输入(即 INP OFF)
  * OCP 测试结果按 (起始电流+截止电流)/2 给出，Pmax 由被测源电压推算
"""
from __future__ import annotations

import math
import random

from .protocol import MODES, MODE_BY_SCPI


class SimLoad:
    def __init__(self, model="JT6321A", rated=(150.0, 30.0, 300.0)):
        self.model = model
        self.rated_v, self.rated_i, self.rated_p = rated
        self.reset()

    # ------------------------------------------------------------ 状态
    def reset(self):
        self.mode = "CURRent"
        self.input_on = False
        self.short_on = False
        self.remote = False
        self.vsrc = 12.0                      # 被测源电压（模拟被测电源）
        self.set = {"CURRent": 0.0, "VOLTage": 150.0,
                    "POWer": 0.0, "RESistance": 100.0}
        self.prot_i = self.rated_i
        self.prot_p = self.rated_p
        self.von = 1.0
        self.voff = 0.5
        self.slew = 1.0
        self.dyn = {"LOW": 0.0, "HIGH": 1.0, "TL": 0.01, "TH": 0.01}
        self.ocp = {"on": False, "istart": 1.0, "iend": 5.0,
                    "step": 100, "dwell": 0.01, "vtrig": 11.0}
        self.ovp = {"on": False, "vtrig": 15.0}
        self._oc_latch = False
        self._op_latch = False
        self._ov_latch = False

    # ------------------------------------------------------------ 物理模型
    def _measure(self):
        """返回 (V, I, P, R)。"""
        if self.input_on and self.vsrc >= self.von:
            v = self.vsrc
            m = self.mode
            if self.short_on:
                i = self.prot_i
            elif m == "CURRent":
                i = self.set["CURRent"]
            elif m == "POWer":
                i = self.set["POWer"] / max(v, 1e-6)
            elif m == "RESistance":
                i = v / max(self.set["RESistance"], 1e-6)
            elif m == "VOLTage":
                i = min(self.prot_i, max(0.0, (v - self.set["VOLTage"]) * 2.0))
            elif m == "LED":
                i = self.set["CURRent"]
            else:  # DYNAMIC，取高低准位中间值
                i = (self.dyn["LOW"] + self.dyn["HIGH"]) / 2.0
            i = min(i, self.prot_i)
            p = v * i
            if p > self.prot_p:
                p = self.prot_p
                i = p / max(v, 1e-6)
                self._op_latch = True
            if i >= self.prot_i - 1e-9 and self.prot_i > 0 and i > 0:
                self._oc_latch = True
            if v > self.rated_v:
                self._ov_latch = True
            r = v / i if i > 1e-9 else float("inf")
        else:
            v = self.vsrc if self.input_on else 0.0
            i = 0.0
            p = 0.0
            r = float("inf")
        # 加一点点噪声，让曲线像真机
        if i > 0:
            i *= (1.0 + random.uniform(-2e-4, 2e-4))
        v *= (1.0 + random.uniform(-1e-4, 1e-4))
        return v, i, p, r

    def status_word(self) -> int:
        w = 0
        if self._oc_latch:
            w |= 1 << 1
        if self._op_latch:
            w |= 1 << 3
        if self._ov_latch:
            w |= 1 << 12
        return w

    def _clear_latches(self):
        self._oc_latch = False
        self._op_latch = False
        self._ov_latch = False

    # ------------------------------------------------------------ 命令处理
    def handle(self, raw: str) -> str:
        """处理一帧，返回应答字符串（设置类命令返回空串）。"""
        cmd = (raw or "").strip()
        if not cmd:
            return ""
        u = cmd.upper()
        if "?" in u:
            return self._query(u)
        return self._write(u)

    # ---- 查询
    def _query(self, u: str) -> str:
        v, i, p, r = self._measure()
        head = u.split(" ")[0]

        if head.startswith("*IDN"):
            return "JARTUL,%s,SIM000001,A.01.02" % self.model
        if head.startswith("*OPC"):
            return "1"
        if head.startswith("*ESR") or head.startswith("*STB") or head.startswith("*TST"):
            return "0"
        if head.startswith("*ESE") or head.startswith("*SRE") or head.startswith("*PSC"):
            return "0"

        if head.startswith("SYST:ERR"):
            return "0,No error"
        if head.startswith("SYST:VERS"):
            return "1999.0"
        if head.startswith("SYST:SENS"):
            return "0"

        if head.startswith("MODE") or head.startswith("FUNC"):
            return self.mode
        if head.startswith("INP:SHOR") or head.startswith("INP:SHORT"):
            return "1" if self.short_on else "0"
        if head.startswith("INP"):
            return "1" if self.input_on else "0"

        if head.startswith("CURR:PROT"):
            return "%.6g" % self.prot_i
        if head.startswith("CURR:SLEW"):
            return "%.6g" % self.slew
        if head.startswith("CURR:RANG"):
            return "%.6g" % self.rated_i
        if head.startswith("CURR"):
            return "%.6g" % self.set["CURRent"]

        if head.startswith("POW:PROT"):
            return "%.6g" % self.prot_p
        if head.startswith("POW:RANG"):
            return "%.6g" % self.rated_p
        if head.startswith("POW"):
            return "%.6g" % self.set["POWer"]

        if head.startswith("VOLT:RANG"):
            return "%.6g" % self.rated_v
        if head.startswith("VOLT:ON"):
            return "%.6g" % self.von
        if head.startswith("VOLT:OFF"):
            return "%.6g" % self.voff
        if head.startswith("VOLT"):
            return "%.6g" % self.set["VOLTage"]

        if head.startswith("RES:RANG"):
            return "%.6g" % 50000.0
        if head.startswith("RES"):
            return "%.6g" % self.set["RESistance"]

        if head.startswith("DYN:LOW:DWEL"):
            return "%.6g" % self.dyn["TL"]
        if head.startswith("DYN:HIGH:DWEL"):
            return "%.6g" % self.dyn["TH"]
        if head.startswith("DYN:LOW"):
            return "%.6g" % self.dyn["LOW"]
        if head.startswith("DYN:HIGH"):
            return "%.6g" % self.dyn["HIGH"]

        if head.startswith("STAT:QUES:COND") or head.startswith("STAT:QUES"):
            return "%d" % self.status_word()

        if head.startswith("MEAS:VOLT:PTP"):
            return "%.6g" % (abs(v) * 0.01)
        if head.startswith("MEAS:VOLT:MAX"):
            return "%.6g" % (v * 1.005)
        if head.startswith("MEAS:VOLT:MIN"):
            return "%.6g" % (v * 0.995)
        if head.startswith("MEAS:VOLT"):
            return "%.6g" % v
        if head.startswith("MEAS:CURR:PTP"):
            return "%.6g" % (i * 0.02)
        if head.startswith("MEAS:CURR:MAX"):
            return "%.6g" % (i * 1.01)
        if head.startswith("MEAS:CURR:MIN"):
            return "%.6g" % (i * 0.99)
        if head.startswith("MEAS:CURR"):
            return "%.6g" % i
        if head.startswith("MEAS:POW"):
            return "%.6g" % p
        if head.startswith("MEAS:RES"):
            return "%.6g" % (r if math.isfinite(r) else 9.9e37)

        if head.startswith("OCP:IST"):
            return "%.6g" % self.ocp["istart"]
        if head.startswith("OCP:IEND"):
            return "%.6g" % self.ocp["iend"]
        if head.startswith("OCP:STEP"):
            return "%d" % self.ocp["step"]
        if head.startswith("OCP:DWEL"):
            return "%.6g" % self.ocp["dwell"]
        if head.startswith("OCP:VTR"):
            return "%.6g" % self.ocp["vtrig"]
        if head.startswith("OCP:RES:PMAX"):
            ip = (self.ocp["istart"] + self.ocp["iend"]) / 2.0
            return "%.4g,%.4g,%.4g" % (self.vsrc * ip, self.vsrc, ip)
        if head.startswith("OCP:RES"):
            if not self.ocp["on"]:
                return "-2"
            return "%.4g" % ((self.ocp["istart"] + self.ocp["iend"]) / 2.0)
        if head.startswith("OCP"):
            return "1" if self.ocp["on"] else "0"

        if head.startswith("OVP:RES"):
            return "%.4g" % (self.ovp["vtrig"] if self.ovp["on"] else -2)
        if head.startswith("OVP"):
            return "1" if self.ovp["on"] else "0"

        return ""

    # ---- 设置
    def _write(self, u: str) -> str:
        head = u.split(" ")[0]
        rest = u[len(head):].strip()

        if head.startswith("*RST"):
            self.reset()
            return ""
        if head.startswith("*CLS"):
            self._clear_latches()
            return ""

        if head.startswith("MODE") or head.startswith("FUNC"):
            key = (rest or "").strip().upper()
            short = MODE_BY_SCPI.get(key)
            if short is None:
                # 也可能直接下发手册里的完整关键字（大小写不敏感）
                for k, v in MODES.items():
                    if v.upper() == key:
                        short = k
                        break
            if short is not None:
                self.mode = MODES[short]
            return ""

        if head.startswith("INP:SHOR") or head.startswith("INP:SHORT"):
            self.short_on = rest.upper() in ("1", "ON")
            return ""
        if head.startswith("INP"):
            on = rest.upper() in ("1", "ON")
            self.input_on = on
            if not on:
                self.short_on = False
                self._clear_latches()      # 关输入 = 清故障锁存（模拟器约定）
            return ""

        if head.startswith("CURR:PROT"):
            self.prot_i = _num(rest, self.prot_i)
            return ""
        if head.startswith("CURR:SLEW"):
            self.slew = _num(rest, self.slew)
            return ""
        if head.startswith("CURR"):
            self.set["CURRent"] = _num(rest, self.set["CURRent"])
            return ""

        if head.startswith("POW:PROT"):
            self.prot_p = _num(rest, self.prot_p)
            return ""
        if head.startswith("POW"):
            self.set["POWer"] = _num(rest, self.set["POWer"])
            return ""

        if head.startswith("VOLT:ON"):
            self.von = _num(rest, self.von)
            return ""
        if head.startswith("VOLT:OFF"):
            self.voff = _num(rest, self.voff)
            return ""
        if head.startswith("VOLT"):
            self.set["VOLTage"] = _num(rest, self.set["VOLTage"])
            return ""

        if head.startswith("RES"):
            self.set["RESistance"] = _num(rest, self.set["RESistance"])
            return ""

        if head.startswith("DYN:LOW:DWEL"):
            self.dyn["TL"] = _num(rest, self.dyn["TL"])
            return ""
        if head.startswith("DYN:HIGH:DWEL"):
            self.dyn["TH"] = _num(rest, self.dyn["TH"])
            return ""
        if head.startswith("DYN:LOW"):
            self.dyn["LOW"] = _num(rest, self.dyn["LOW"])
            return ""
        if head.startswith("DYN:HIGH"):
            self.dyn["HIGH"] = _num(rest, self.dyn["HIGH"])
            return ""
        if head.startswith("DYN:MODE"):
            return ""

        if head.startswith("OCP:IST"):
            self.ocp["istart"] = _num(rest, self.ocp["istart"])
            return ""
        if head.startswith("OCP:IEND"):
            self.ocp["iend"] = _num(rest, self.ocp["iend"])
            return ""
        if head.startswith("OCP:STEP"):
            self.ocp["step"] = int(_num(rest, self.ocp["step"]))
            return ""
        if head.startswith("OCP:DWEL"):
            self.ocp["dwell"] = _num(rest, self.ocp["dwell"])
            return ""
        if head.startswith("OCP:VTR"):
            self.ocp["vtrig"] = _num(rest, self.ocp["vtrig"])
            return ""
        if head.startswith("OCP"):
            self.ocp["on"] = rest.upper() in ("1", "ON")
            return ""

        if head.startswith("OVP:VTR"):
            self.ovp["vtrig"] = _num(rest, self.ovp["vtrig"])
            return ""
        if head.startswith("OVP"):
            self.ovp["on"] = rest.upper() in ("1", "ON")
            return ""

        if head.startswith("SYST:REM") or head.startswith("SYST:RWL"):
            self.remote = True
            return ""
        if head.startswith("SYST:LOC"):
            self.remote = False
            return ""

        return ""


def _num(text, default):
    try:
        return float(str(text).strip())
    except Exception:
        return default
