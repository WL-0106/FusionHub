"""SCPI 指令构造(依据 GPP 操作手册“指令详解”)。"""
from __future__ import annotations

IDN = "*IDN?"
RESET = "*RST"
CLS = "*CLS"
REMOTE = ":SYSTem:REMote"
LOCAL = ":SYSTem:LOCal"
ERR_QUERY = ":SYSTem:ERRor?"
ALLOUTON = ":ALLOUTON"
ALLOUTOFF = ":ALLOUTOFF"


def source_volt_set(n: int, volts: float) -> str:
    return f":SOURce{n}:VOLTage {volts:.4f}"


def source_volt_query(n: int) -> str:
    return f":SOURce{n}:VOLTage?"


def source_curr_set(n: int, amps: float) -> str:
    return f":SOURce{n}:CURRent {amps:.4f}"


def source_curr_query(n: int) -> str:
    return f":SOURce{n}:CURRent?"


def output_set(n: int, on: bool) -> str:
    return f":OUTPut{n} {'ON' if on else 'OFF'}"


def output_query(n: int) -> str:
    return f":OUTPut{n}?"


def measure_all(n: int) -> str:
    return f":MEASure{n}:ALL?"


def ovp_set(n: int, volts: float) -> str:
    return f":OUTPut{n}:OVP {volts:.3f}"


def ovp_query(n: int) -> str:
    return f":OUTPut{n}:OVP?"


def ovp_state_set(n: int, on: bool) -> str:
    return f":OUTPut{n}:OVP:STATe {'ON' if on else 'OFF'}"


def ovp_state_query(n: int) -> str:
    return f":OUTPut{n}:OVP:STATe?"


def ocp_set(n: int, amps: float) -> str:
    return f":OUTPut{n}:OCP {amps:.3f}"


def ocp_query(n: int) -> str:
    return f":OUTPut{n}:OCP?"


def ocp_state_set(n: int, on: bool) -> str:
    return f":OUTPut{n}:OCP:STATe {'ON' if on else 'OFF'}"


def ocp_state_query(n: int) -> str:
    return f":OUTPut{n}:OCP:STATe?"


def tracking_set(mode: str) -> str:
    """mode: independent | series | parallel (仅 CH1/CH2，1326 不支持)。"""
    if mode == "series":
        return ":OUTPut:SERies ON"
    if mode == "parallel":
        return ":OUTPut:PARallel ON"
    return ":OUTPut:SERies OFF"


def load_mode_set(n: int, kind: str) -> str:
    """kind: source | cv | cc | cr — source 表示退出负载模式。"""
    if kind == "source":
        return f":LOAD{n}:CV OFF"
    return f":LOAD{n}:{kind.upper()} ON"


def load_res_set(n: int, ohms: float) -> str:
    return f":LOAD{n}:RESistor {ohms:.3f}"


def cc_state_query(n: int) -> str:
    return f":SOURce{n}:CURRent:LIMit:STATe?"
