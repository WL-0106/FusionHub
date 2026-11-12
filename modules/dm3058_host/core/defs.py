# -*- coding: utf-8 -*-
"""DM3058/DM3058E 测量功能、量程、速率定义（依据 RIGOL 编程手册）"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class FunctionDef:
    key: str
    label: str
    unit: str
    func_cmd: str                 # :FUNCtion:...
    measure_cmd: str              # :MEASure:...?（RIGOL 命令集查询当前值）
    range_cmd: Optional[str]      # :MEASure:...（设置量程，None 表示无量程）
    ranges: Tuple[Tuple[int, str], ...] = ()
    rate_cmd: Optional[str] = None
    filter_cmd: Optional[str] = None
    dual_cmd: str = ""            # :FUNCtion2:...
    supports_dual: bool = True
    notes: str = ""


# ACV / FREQ / PERI 共用交流电压量程表（手册表 3-5）
_ACV_RANGES = (
    (0, "200 mV"), (1, "2 V"), (2, "20 V"), (3, "200 V"), (4, "750 V"),
)
_DCV_RANGES = (
    (0, "200 mV"), (1, "2 V"), (2, "20 V"), (3, "200 V"), (4, "1000 V"),
)
_DCI_RANGES = (
    (0, "200 µA"), (1, "2 mA"), (2, "20 mA"), (3, "200 mA"), (4, "2 A"), (5, "10 A"),
)
_ACI_RANGES = (
    (0, "20 mA"), (1, "200 mA"), (2, "2 A"), (3, "10 A"),
)
_RES_RANGES = (
    (0, "200 Ω"), (1, "2 kΩ"), (2, "20 kΩ"), (3, "200 kΩ"),
    (4, "1 MΩ"), (5, "10 MΩ"), (6, "100 MΩ"),
)
_CAP_RANGES = (
    (0, "2 nF"), (1, "20 nF"), (2, "200 nF"), (3, "2 µF"), (4, "200 µF"), (5, "10000 µF"),
)


FUNCTIONS: List[FunctionDef] = [
    FunctionDef(
        key="DCV", label="直流电压", unit="V",
        func_cmd=":FUNCtion:VOLTage:DC",
        measure_cmd=":MEASure:VOLTage:DC?",
        range_cmd=":MEASure:VOLTage:DC",
        ranges=_DCV_RANGES,
        rate_cmd=":RATE:VOLTage:DC",
        filter_cmd=":MEASure:VOLTage:DC:FILTer",
        dual_cmd=":FUNCtion2:VOLTage:DC",
        notes="可选滤波；输入阻抗 10MΩ / >10GΩ（>10G 仅 200mV、2V 量程）",
    ),
    FunctionDef(
        key="ACV", label="交流电压", unit="V",
        func_cmd=":FUNCtion:VOLTage:AC",
        measure_cmd=":MEASure:VOLTage:AC?",
        range_cmd=":MEASure:VOLTage:AC",
        ranges=_ACV_RANGES,
        rate_cmd=":RATE:VOLTage:AC",
        dual_cmd=":FUNCtion2:VOLTage:AC",
    ),
    FunctionDef(
        key="DCI", label="直流电流", unit="A",
        func_cmd=":FUNCtion:CURRent:DC",
        measure_cmd=":MEASure:CURRent:DC?",
        range_cmd=":MEASure:CURRent:DC",
        ranges=_DCI_RANGES,
        rate_cmd=":RATE:CURRent:DC",
        filter_cmd=":MEASure:CURRent:DC:FILTer",
        dual_cmd=":FUNCtion2:CURRent:DC",
        notes="可选交流滤波；10A 量程注意发热",
    ),
    FunctionDef(
        key="ACI", label="交流电流", unit="A",
        func_cmd=":FUNCtion:CURRent:AC",
        measure_cmd=":MEASure:CURRent:AC?",
        range_cmd=":MEASure:CURRent:AC",
        ranges=_ACI_RANGES,
        rate_cmd=":RATE:CURRent:AC",
        dual_cmd=":FUNCtion2:CURRent:AC",
    ),
    FunctionDef(
        key="2WR", label="二线电阻", unit="Ω",
        func_cmd=":FUNCtion:RESistance",
        measure_cmd=":MEASure:RESistance?",
        range_cmd=":MEASure:RESistance",
        ranges=_RES_RANGES,
        rate_cmd=":RATE:RESistance",
        dual_cmd=":FUNCtion2:RESistance",
    ),
    FunctionDef(
        key="4WR", label="四线电阻", unit="Ω",
        func_cmd=":FUNCtion:FRESistance",
        measure_cmd=":MEASure:FRESistance?",
        range_cmd=":MEASure:FRESistance",
        ranges=_RES_RANGES,
        rate_cmd=":RATE:FRESistance",
        dual_cmd=":FUNCtion2:FRESistance",
    ),
    FunctionDef(
        key="FREQ", label="频率", unit="Hz",
        func_cmd=":FUNCtion:FREQuency",
        measure_cmd=":MEASure:FREQuency?",
        range_cmd=":MEASure:FREQuency",
        ranges=_ACV_RANGES,   # 量程为输入信号的交流电压量程
        dual_cmd=":FUNCtion2:FREQuency",
        notes="测量范围 20Hz ~ 1MHz；量程即交流电压量程",
    ),
    FunctionDef(
        key="PERI", label="周期", unit="s",
        func_cmd=":FUNCtion:PERiod",
        measure_cmd=":MEASure:PERiod?",
        range_cmd=":MEASure:PERiod",
        ranges=_ACV_RANGES,
        dual_cmd=":FUNCtion2:PERiod",
        notes="测量范围 1µs ~ 50ms；量程即交流电压量程",
    ),
    FunctionDef(
        key="CONT", label="通断", unit="Ω",
        func_cmd=":FUNCtion:CONTinuity",
        measure_cmd=":MEASure:CONTinuity?",
        range_cmd=":MEASure:CONTinuity",  # 参数为极限电阻 1~2000Ω
        ranges=((0, "默认 10 Ω"),),
        dual_cmd=":FUNCtion2:CONTinuity",
        supports_dual=False,
        notes="可设极限电阻 1~2000Ω（默认 10Ω）",
    ),
    FunctionDef(
        key="DIODE", label="二极管", unit="V",
        func_cmd=":FUNCtion:DIODe",
        measure_cmd=":MEASure:DIODe?",
        range_cmd=None,
        dual_cmd=":FUNCtion2:DIODe",
        supports_dual=False,
    ),
    FunctionDef(
        key="CAP", label="电容", unit="F",
        func_cmd=":FUNCtion:CAPacitance",
        measure_cmd=":MEASure:CAPacitance?",
        range_cmd=":MEASure:CAPacitance",
        ranges=_CAP_RANGES,
        dual_cmd=":FUNCtion2:CAPacitance",
    ),
]

FUNC_BY_KEY = {f.key: f for f in FUNCTIONS}

# :FUNCtion? 返回值 → 功能 key（手册正文与范例两种写法都兼容）
FUNC_QUERY_MAP = {
    "DCV": "DCV", "ACV": "ACV", "DCI": "DCI", "ACI": "ACI",
    "2WR": "2WR", "RESISTANCE": "2WR",
    "4WR": "4WR", "FRESISTANCE": "4WR",
    "FREQ": "FREQ", "FREQUENCY": "FREQ",
    "PERI": "PERI", "PERIOD": "PERI",
    "CONT": "CONT", "CONTINUITY": "CONT",
    "DIODE": "DIODE",
    "CAP": "CAP", "CAPACITANCE": "CAP",
}

RATE_CHOICES = (("F", "快速 (~123 次/秒)"), ("M", "中速 (~20 次/秒)"), ("S", "慢速 (~2.5 次/秒)"))

MATH_CHOICES = (
    ("NONE", "关闭"),
    ("REL", "相对 (REL)"),
    ("DB", "dB"),
    ("DBM", "dBm"),
    ("MIN", "最小值"),
    ("MAX", "最大值"),
    ("AVERAGE", "平均值"),
    ("TOTAL", "累计"),
    ("PF", "P/F 判定"),
)

DUAL_SECONDARY_KEYS = ("DCV", "ACV", "DCI", "ACI", "2WR", "4WR", "FREQ", "PERI", "CAP")


def format_value(v: float, unit: str) -> str:
    """按仪表习惯格式化科学计数返回值"""
    a = abs(v)
    if a == 0:
        text = "0.000000"
    elif a >= 1e7 or a < 1e-4:
        text = f"{v:.6e}"
    else:
        text = f"{v:.6f}"
    return f"{text} {unit}"
