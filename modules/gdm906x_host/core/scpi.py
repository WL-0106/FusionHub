# -*- coding: utf-8 -*-
"""GDM-906X（GW Instek）SCPI 指令封装与读数解析。

依据：《GDM-9060/9061 使用手册》「远程控制」与「指令集」章节（P244~P330）。

要点摘录：
  * 指令树用 ':' 分隔，长/短格式均可，例如 CONFigure:VOLTage:DC == CONF:VOLT:DC
  * 参数类型 <NRf> 支持 1 / 1.5 / 4.5e-1；[MIN] [MAX] [DEF] 为可选特殊参数
  * 自动量程（AUTO/DEF）时若同时指定分辨率会报错，因此自动量程只发 CONF 头
  * 消息终止符支持 LF / CR / CR+LF，本程序串口用 CR+LF、TCP 用 LF
  * DATA:LAST? 随时可查（返回 "值 单位"），READ? 只返回值、不带单位
  * 无数据时返回 +9.91000000E+37（NaN 哨兵）
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional, Tuple

# 仪器用来表示「无数据」的哨兵值
NAN_SENTINEL = 9.9e37

# 可选 NPLC（对应手册「速度 & NPLC & 分辨率关系表」的速度档）
NPLC_CHOICES = (
    (12, "12 PLC · 5 次/秒 · 慢速高精度"),
    (3, "3 PLC · 20 次/秒"),
    (1, "1 PLC · 60 次/秒 · 默认"),
    (0.6, "0.6 PLC · 100 次/秒"),
    (0.15, "0.15 PLC · 400 次/秒"),
    (0.05, "0.05 PLC · 1.2k 次/秒"),
    (0.025, "0.025 PLC · 2.4k 次/秒"),
    (0.0125, "0.0125 PLC · 4.8k 次/秒"),
    (0.0083, "0.0083 PLC · 7.2k 次/秒"),
    (0.006, "0.006 PLC · 10k 次/秒 · 快速"),
)

TEMP_TYPES = ("K", "J", "T", "E", "N", "R", "S", "B")
TEMP_UNITS = (("C", "℃"), ("F", "℉"), ("K", "K"))

SECOND_FUNCS = (
    ("NON", "关闭"),
    ("VOLT:DC", "直流电压"),
    ("VOLT:AC", "交流电压"),
    ("CURR:DC", "直流电流"),
    ("CURR:AC", "交流电流"),
    ("FREQ", "频率"),
    ("PER", "周期"),
)


@dataclass(frozen=True)
class FuncSpec:
    key: str            # 内部键
    label: str          # 中文名
    conf: str           # CONFigure 指令头
    sense: str          # SENSe 指令前缀
    unit: str           # 显示单位
    dev_units: tuple    # 仪器返回的单位标识（DATA:LAST? 后缀）
    ranges: tuple       # 支持的固定量程（基本单位）
    has_nplc: bool = True
    has_range: bool = True


FUNCS = {
    "DCV": FuncSpec("DCV", "直流电压", "VOLT:DC", "VOLT:DC", "V",
                    ("VDC", "V", "VOLT"), (0.1, 1, 10, 100, 1000)),
    "ACV": FuncSpec("ACV", "交流电压", "VOLT:AC", "VOLT:AC", "V",
                    ("VAC", "V", "VOLT"), (0.1, 1, 10, 100, 750)),
    "DCI": FuncSpec("DCI", "直流电流", "CURR:DC", "CURR:DC", "A",
                    ("ADC", "A", "AMP"), (0.01, 0.1, 1, 3, 10)),
    "ACI": FuncSpec("ACI", "交流电流", "CURR:AC", "CURR:AC", "A",
                    ("AAC", "A", "AMP"), (0.01, 0.1, 1, 3, 10)),
    "RES": FuncSpec("RES", "二线电阻", "RES", "RES", "Ω",
                    ("OHM", "Ω", "OHMS"), (100, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8)),
    "FRES": FuncSpec("FRES", "四线电阻", "FRES", "FRES", "Ω",
                     ("OHM", "Ω", "OHMS"), (100, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8)),
    "FREQ": FuncSpec("FREQ", "频率", "FREQ", "FREQ", "Hz",
                     ("HZ", "Hz"), (1, 10, 100, 1e3, 1e4, 1e5, 1e6), has_nplc=False),
    "PER": FuncSpec("PER", "周期", "PER", "PER", "s",
                    ("S", "SEC"), (1e-6, 1e-5, 1e-4, 1e-3, 1e-2), has_nplc=False),
    "CAP": FuncSpec("CAP", "电容", "CAP", "CAP", "F",
                    ("F", "FAR"), (1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3), has_nplc=False),
    "CONT": FuncSpec("CONT", "通断测试", "CONT", "CONT", "Ω",
                     ("OHM", "Ω"), (), has_nplc=False, has_range=False),
    "DIOD": FuncSpec("DIOD", "二极管", "DIOD", "DIOD", "V",
                     ("VDC", "V"), (), has_nplc=False, has_range=False),
    "TEMP": FuncSpec("TEMP", "温度", "TEMP", "TEMP", "℃",
                     ("C", "F", "K"), (), has_nplc=False, has_range=False),
}

FUNC_ORDER = ("DCV", "ACV", "DCI", "ACI", "RES", "FRES",
              "FREQ", "PER", "CAP", "CONT", "DIOD", "TEMP")


# --------------------------------------------------------------------------
# 数值格式化
# --------------------------------------------------------------------------

_PREFIX = ((-12, "p"), (-9, "n"), (-6, "µ"), (-3, "m"),
           (0, ""), (3, "k"), (6, "M"), (9, "G"))

# 这些单位不参与 SI 词头缩放
_NO_PREFIX_UNITS = {"℃", "℉", "K"}


def fmt_num(value: float) -> str:
    """给仪器发送参数时用的紧凑数字格式。"""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return ("%.10g" % value)


def si_scale(value: float):
    """返回数值对应的 SI 档位 (指数, 词头)。"""
    if not value:
        return 0, ""
    exp = int(math.floor(math.log10(abs(value)) / 3.0)) * 3
    exp = max(-12, min(9, exp))
    return exp, dict(_PREFIX).get(exp, "")


def format_si(value: Optional[float], unit: str = "", sig: int = 6) -> str:
    """把数值格式化成带 SI 词头的字符串，如 1.23456e-3 -> '1.23456 mV'。"""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "----"
    if value == 0:
        return f"0 {unit}".strip()
    if unit in _NO_PREFIX_UNITS:
        return f"{value:.{max(1, sig - 2)}f} {unit}".strip()
    exp, prefix = si_scale(value)
    mant = value / (10.0 ** exp)
    # 处理 999.9995 -> 1.000 k 的进位
    if abs(mant) >= 999.995 and exp < 9:
        exp += 3
        prefix = dict(_PREFIX).get(exp, "")
        mant = value / (10.0 ** exp)
    text = f"{mant:.{sig}g}"
    if "e" in text or "E" in text:
        text = f"{mant:.3f}"
    return f"{text} {prefix}{unit}".strip()


def format_plain(value: Optional[float], unit: str = "") -> str:
    """不带 SI 词头的工程数值（用于统计面板，同一组数字保持同样的小数位）。"""
    if value is None:
        return "----"
    if value == 0:
        return f"0 {unit}".strip()
    a = abs(value)
    if a >= 1e6 or a < 1e-6:
        return f"{value:.4e} {unit}".strip()
    if a >= 100:
        text = f"{value:.4f}"
    elif a >= 1:
        text = f"{value:.6f}"
    elif a >= 0.01:
        text = f"{value:.7f}"
    else:
        text = f"{value:.8f}"
    return f"{text} {unit}".strip()


def range_label(value: float) -> str:
    """量程下拉框里显示的文本。"""
    return format_si(value, "", sig=6)


# --------------------------------------------------------------------------
# 读数解析
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?)\s*(.*)$")


def is_no_data(text: str) -> bool:
    """判断返回串是否为「无数据」哨兵值（+9.9E37）：超量程、开路或测量未完成。"""
    t = (text or "").strip().strip("\x00").strip('"')
    m = _NUM_RE.match(t)
    if not m:
        return False
    try:
        v = float(m.group(1))
    except ValueError:
        return False
    return abs(v) >= NAN_SENTINEL


def parse_reading(text: str) -> Optional[Tuple[float, str]]:
    """解析 DATA:LAST? / 查询类指令的返回，得到 (数值, 单位后缀)。"""
    if not text:
        return None
    t = text.strip().strip("\x00").strip('"')
    if not t:
        return None
    m = _NUM_RE.match(t)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    if abs(v) >= NAN_SENTINEL:      # 仪器表示「无数据」
        return None
    return v, m.group(2).strip()


def normalize_unit(func_key: str, dev_unit: str = "") -> str:
    """把仪器返回的单位统一成界面上显示的单位符号。"""
    spec = FUNCS.get(func_key)
    if spec is None:
        return dev_unit
    if func_key == "TEMP":
        return spec.unit
    return spec.unit


# --------------------------------------------------------------------------
# 指令构建
# --------------------------------------------------------------------------

def cmd_configure(func_key: str, range_value: Optional[float] = None,
                  nplc: Optional[float] = None, temp_type: str = "K",
                  temp_unit: str = "C") -> list:
    """构建「切换测量功能 + 量程 + 速率」的指令序列。

    range_value 为 None 表示自动量程（手册明确：自动量程时不能再指定分辨率）。
    """
    spec = FUNCS[func_key]
    cmds = []

    # 1) CONFigure：设定测量功能（第一显示）
    if func_key == "TEMP":
        cmds.append(f"CONF:TEMP TCO,{temp_type}")
    elif not spec.has_range:
        cmds.append(f"CONF:{spec.conf}")
    elif range_value is None:
        cmds.append(f"CONF:{spec.conf}")                 # 默认/自动量程
    else:
        cmds.append(f"CONF:{spec.conf} {fmt_num(range_value)},DEF")

    # 2) 量程显式设定（CONF 之后更可靠）
    if spec.has_range:
        if range_value is None:
            cmds.append(f"SENS:{spec.sense}:RANG:AUTO ON")
        else:
            cmds.append(f"SENS:{spec.sense}:RANG:AUTO OFF")
            cmds.append(f"SENS:{spec.sense}:RANG {fmt_num(range_value)}")

    # 3) 积分时间（NPLC）
    if spec.has_nplc and nplc:
        cmds.append(f"SENS:{spec.sense}:NPLC {fmt_num(nplc)}")

    # 4) 温度单位
    if func_key == "TEMP":
        cmds.append(f"SENS:UNIT {temp_unit}")

    return cmds


def cmd_second_display(second: str) -> list:
    """副显示（第二显示）设置，second 取 SECOND_FUNCS 里的指令值。"""
    if second == "NON":
        return ["CONF2:OFF"]
    return [f'SENS:FUNC2 "{second}"', f"CONF2:{second}"]


def cmd_relative_on(func_key: str, reference: float) -> list:
    """以 reference 作为相对值（清零）参考。"""
    spec = FUNCS[func_key]
    if not spec.has_nplc:   # CONT/DIOD/TEMP/CAP 没有 NULL 子系统
        return []
    return [f"SENS:{spec.sense}:NULL:VAL {fmt_num(reference)}",
            f"SENS:{spec.sense}:NULL:STAT ON"]


def cmd_relative_off(func_key: str) -> list:
    spec = FUNCS[func_key]
    if not spec.has_nplc:
        return []
    return [f"SENS:{spec.sense}:NULL:STAT OFF"]


def cmd_autozero_once(func_key: str) -> list:
    spec = FUNCS[func_key]
    if not spec.has_nplc:
        return []
    return [f"SENS:{spec.sense}:ZERO:AUTO ONCE"]


def cmd_error_query() -> str:
    return "SYST:ERR?"


def is_error_response(text: str) -> bool:
    """SYST:ERR? 返回 '+0,"No error"' 表示无错误。"""
    if not text:
        return False
    m = re.match(r"^([+-]?\d+)", text.strip())
    return bool(m) and int(m.group(1)) != 0
