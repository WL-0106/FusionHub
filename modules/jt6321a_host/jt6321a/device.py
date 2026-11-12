# -*- coding: utf-8 -*-
"""设备层：把 SCPI 帧组装成业务方法，含本地量程拦截与回读确认。

要点：
  * 设置命令仪器无应答，必须「回读确认」判断是否真的生效
  * 输入开关（INP）下发后功率级要几十~几百毫秒才到位，用确认循环，
    不要只看应答就报成功（否则日志会和事实相反）
  * 本地量程拦截：越界的值直接抛 ValueError，一条报文都不发
"""
from __future__ import annotations

import time

from . import protocol as P


class DeviceError(Exception):
    pass


class LoadDevice:
    def __init__(self, transport, limits=None):
        self.t = transport
        self.limits = dict(P.DEFAULT_LIMITS)
        if limits:
            self.limits.update(limits)
        self.model = ""
        self.trace_hook = None      # (cmd, resp) 回调，供报文日志

    # ------------------------------------------------------------ 底层
    def _send(self, cmd: str):
        self.t.write(cmd)
        if self.trace_hook:
            self.trace_hook(cmd, "")

    def _ask(self, cmd: str, timeout=None) -> str:
        r = self.t.query(cmd, timeout=timeout)
        if self.trace_hook:
            self.trace_hook(cmd, r)
        return r

    def raw(self, cmd: str) -> str:
        """手动发一条命令（调试用）。"""
        return self._ask(cmd)

    # ------------------------------------------------------------ 连接
    def identify(self):
        r = self._ask("*IDN?", timeout=1.0)
        if not r:
            raise DeviceError("无应答：请检查波特率/校验位/接线（RS232 需交叉线）")
        info = P.parse_idn(r)
        self.model = info["model"]
        return info

    def reset(self):
        self._send("*RST")
        time.sleep(0.05)
        self._send("*CLS")

    def clear_error(self):
        return self._ask("SYST:ERR?")

    def set_remote(self, on=True):
        self._send("SYST:REM" if on else "SYST:LOC")

    # ------------------------------------------------------------ 模式
    def set_mode(self, mode_key: str):
        if mode_key not in P.MODES:
            raise DeviceError("未知模式: %s" % mode_key)
        self._send(P.cmd_mode(mode_key))
        time.sleep(0.05)
        back = self._ask(P.q_mode(), timeout=0.8)
        try:
            got = P.parse_mode(back)
        except Exception:
            raise DeviceError("模式回读失败（应答 %r）" % back)
        if got != mode_key:
            raise DeviceError("模式未生效：下发 %s，回读 %s" % (mode_key, got))
        return got

    def read_mode(self):
        return P.parse_mode(self._ask(P.q_mode(), timeout=0.8))

    # ------------------------------------------------------------ 设定值
    def set_value(self, mode_key: str, value: float):
        kind = {"CC": "current", "CV": "voltage", "CP": "power", "CR": "resistance"}[mode_key]
        P.check_limit(kind, float(value), self.limits)     # 越界直接抛，不下发
        self._send(P.cmd_set_value(mode_key, float(value)))
        time.sleep(0.05)
        back = self._ask(P.q_set_value(mode_key), timeout=0.8)
        try:
            got = P.parse_float(back)
        except Exception:
            raise DeviceError("设定值回读失败（应答 %r）" % back)
        if abs(got - float(value)) > max(1e-6, abs(float(value)) * 0.02 + 1e-4):
            raise DeviceError("设定值未生效：下发 %.6g，回读 %.6g" % (value, got))
        return got

    def read_value(self, mode_key: str):
        return P.parse_float(self._ask(P.q_set_value(mode_key), timeout=0.8))

    # ------------------------------------------------------------ 输入控制
    def set_input(self, on: bool, tries=6, gap=0.2):
        """下发输入开关并回读确认（不看应答，只看回读）。"""
        self._send(P.cmd_input(on))
        confirmed, last = False, None
        for i in range(max(1, tries)):
            if i:
                time.sleep(gap)
            try:
                last = P.parse_bool(self._ask(P.q_input(), timeout=0.6))
            except Exception:
                continue
            confirmed = bool(last) == bool(on)
            if confirmed:
                break
        return confirmed, last

    def set_short(self, on: bool, tries=4, gap=0.2):
        self._send(P.cmd_short(on))
        confirmed, last = False, None
        for i in range(max(1, tries)):
            if i:
                time.sleep(gap)
            try:
                last = P.parse_bool(self._ask(P.q_short(), timeout=0.6))
            except Exception:
                continue
            confirmed = bool(last) == bool(on)
            if confirmed:
                break
        return confirmed, last

    # ------------------------------------------------------------ 保护 / 系统
    def set_protection(self, current=None, power=None):
        if current is not None:
            P.check_limit("current", float(current), self.limits)
            self._send(P.cmd_prot_current(float(current)))
        if power is not None:
            P.check_limit("power", float(power), self.limits)
            self._send(P.cmd_prot_power(float(power)))

    def read_protection(self):
        out = {}
        try:
            out["current"] = P.parse_float(self._ask(P.q_prot_current(), timeout=0.6))
        except Exception:
            pass
        try:
            out["power"] = P.parse_float(self._ask(P.q_prot_power(), timeout=0.6))
        except Exception:
            pass
        return out

    def set_von_voff(self, von=None, voff=None):
        if von is not None:
            P.check_limit("voltage", float(von), self.limits)
            self._send(P.cmd_von(float(von)))
        if voff is not None:
            P.check_limit("voltage", float(voff), self.limits)
            self._send(P.cmd_voff(float(voff)))

    def set_slew(self, value: float):
        self._send(P.cmd_slew(float(value)))

    def set_dynamic(self, low, high, t_low, t_high):
        P.check_limit("current", float(low), self.limits)
        P.check_limit("current", float(high), self.limits)
        for c in P.cmd_dyn(low, high, t_low, t_high):
            self._send(c)

    # ------------------------------------------------------------ 测量 / 状态
    def read_measure(self, items=("V", "I", "P")):
        out = {}
        for it in items:
            try:
                out[it] = P.parse_float(self._ask(P.q_measure(it), timeout=0.6))
            except Exception:
                out[it] = None
        return out

    def read_status(self):
        try:
            return P.parse_status(self._ask(P.q_status(), timeout=0.6))
        except Exception:
            return {"raw": 0}

    # ------------------------------------------------------------ OCP 测试
    def ocp_setup(self, i_start, i_end, steps, dwell, vtrig):
        P.check_limit("current", float(i_start), self.limits)
        P.check_limit("current", float(i_end), self.limits)
        for c in P.cmd_ocp_param(i_start, i_end, steps, dwell, vtrig):
            self._send(c)

    def ocp_start(self, on=True):
        self._send(P.cmd_ocp(on))

    def ocp_result(self):
        try:
            v = P.parse_float(self._ask(P.q_ocp_result(), timeout=1.0))
        except Exception:
            return None
        if v is None:
            return None
        if abs(v + 1.0) < 1e-9:
            return {"state": "running", "text": "测试尚未结束(-1)"}
        if abs(v + 2.0) < 1e-9:
            return {"state": "notrig", "text": "未进入 OCP 保护(-2)"}
        return {"state": "ok", "ocp": v, "text": "%.4f A" % v}

    def ocp_pmax(self):
        r = self._ask(P.q_ocp_pmax(), timeout=1.0)
        parts = [x.strip() for x in (r or "").split(",")]
        if len(parts) < 3:
            return None
        try:
            return {"power": float(parts[0]), "voltage": float(parts[1]), "current": float(parts[2])}
        except Exception:
            return None
