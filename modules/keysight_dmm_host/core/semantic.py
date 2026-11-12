# -*- coding: utf-8 -*-
"""
语义化接口层（界面唯一入口）
==========================
界面只调用本模块的方法（读温度/写设定值/读直流电压…），
不接触帧字节、不拼 SCPI 命令串——保持界面与协议解耦。
单位换算、格式化、档位映射在这里完成。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .commands import COMMANDS, get as get_cmd
from .protocol import ScpiClient, Result
from .transport import Transport


class DmmService:
    """数字万用表语义化服务。"""

    def __init__(self, client: ScpiClient):
        self._c = client

    # ---------- 连接 ----------
    def connect(self) -> str:
        self._c.connect()
        return self.identify()

    def disconnect(self) -> None:
        self._c.disconnect()

    @property
    def connected(self) -> bool:
        return self._c.is_connected

    def identify(self) -> str:
        """返回仪器身份串 *IDN?。"""
        return self._c.query("idn_query")

    # ---------- 一键测量（读） ----------
    def measure_dc_voltage(self) -> float:
        return self._c.query_float("read_dc_volt")

    def measure_ac_voltage(self) -> float:
        return self._c.query_float("read_ac_volt")

    def measure_dc_current(self) -> float:
        return self._c.query_float("read_dc_curr")

    def measure_ac_current(self) -> float:
        return self._c.query_float("read_ac_curr")

    def measure_resistance_2w(self) -> float:
        return self._c.query_float("read_res")

    def measure_resistance_4w(self) -> float:
        return self._c.query_float("read_fres")

    def measure_capacitance(self) -> float:
        return self._c.query_float("read_cap")

    def measure_frequency(self) -> float:
        return self._c.query_float("read_freq")

    def measure_period(self) -> float:
        return self._c.query_float("read_period")

    def measure_temperature(self) -> float:
        return self._c.query_float("read_temp")

    def measure_continuity(self) -> float:
        return self._c.query_float("read_cont")

    def measure_diode(self) -> float:
        return self._c.query_float("read_diode")

    # 语义键 -> 读数方法，供界面/自动化统一驱动
    _MEASURE_MAP = {
        "read_dc_volt": measure_dc_voltage,
        "read_ac_volt": measure_ac_voltage,
        "read_dc_curr": measure_dc_current,
        "read_ac_curr": measure_ac_current,
        "read_res": measure_resistance_2w,
        "read_fres": measure_resistance_4w,
        "read_cap": measure_capacitance,
        "read_freq": measure_frequency,
        "read_period": measure_period,
        "read_temp": measure_temperature,
        "read_cont": measure_continuity,
        "read_diode": measure_diode,
    }

    def measure(self, key: str) -> float:
        """按语义键执行一次测量。"""
        fn = self._MEASURE_MAP.get(key)
        if fn is None:
            raise KeyError(f"无可执行的测量语义键: {key}")
        return fn(self)

    def measure_with_unit(self, key: str) -> Dict[str, object]:
        """测量并带出单位/说明，界面直接绑定。"""
        val = self.measure(key)
        cmd = get_cmd(key)
        return {"key": key, "value": val, "unit": cmd.unit,
                "desc": cmd.desc, "timestamp": __import__("time").time()}

    # ---------- 配置（写设定值） ----------
    def configure(self, key: str, value: str) -> None:
        """按语义键写配置（如 conf_dc_volt, sense_nplc）。"""
        self._c.set(key, value)

    def set_integration_nplc(self, nplc: float) -> None:
        """写积分时间 NPLC（含边界校验）。"""
        lo, hi = 0.02, 100.0
        if not (lo <= float(nplc) <= hi):
            raise ValueError(f"NPLC 越界: {nplc}（允许 {lo}~{hi}，34461A 上限100）")
        self._c.set("sense_nplc", f"{float(nplc):.3f}")

    def set_trigger_source(self, src: str) -> None:
        allowed = {"BUS", "IMMediate", "EXTernal", "INTernal"}
        if src not in allowed:
            raise ValueError(f"非法触发源: {src}，可选 {sorted(allowed)}")
        self._c.set("trig_source", src)

    def set_display_text(self, text: str) -> None:
        safe = text.replace('"', "'")[:32]
        self._c.set("disp_text", safe)

    def clear_display(self) -> None:
        self._c.set("disp_clear")

    def reset(self) -> None:
        self._c.set("reset")

    def remote(self) -> None:
        self._c.set("sys_remote")

    def local(self) -> None:
        self._c.set("sys_local")

    # ---------- 采集流程 ----------
    def init_measurement(self) -> None:
        self._c.set("init_immed")

    def fetch_reading(self) -> float:
        return self._c.query_float("fetch")

    def read_trigger(self) -> float:
        return self._c.query_float("read_trigger")

    def abort(self) -> None:
        self._c.set("abort")

    # ---------- 状态 / 错误 ----------
    def last_error_text(self) -> str:
        """异常码映射人话提示。"""
        return self._c.read_error()

    def self_test(self) -> int:
        return int(self._c.query_float("self_test"))

    def available_commands(self) -> List[Dict[str, str]]:
        """返回命令表摘要，供界面生成控件/文档，保持与协议同源。"""
        return [
            {"key": c.key, "scpi": c.scpi, "desc": c.desc, "unit": c.unit,
             "access": c.access, "verify": c.verify}
            for c in COMMANDS
        ]
