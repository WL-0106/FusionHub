# -*- coding: utf-8 -*-
"""JT632xA 电子负载 SCPI 协议层：命令构造 + 应答解析。

协议要点（官方手册 V2.8 第五章《通信协议(SCPI)》）：
  * 全部 ASCII 字符，一帧以换行符 NL(0x0A) 结束
  * 查询命令以 ? 结尾，仪器回一行数据；设置命令无应答，靠回读确认
  * 数值支持 NR1/NR2/NR3 及 MIN/MAX 关键字；单位可带在数值后（A/V/W/ohm/S/mS）

本模块是纯函数，不碰 IO，方便单测。
"""
from __future__ import annotations

import re

TERM = "\n"

# ---------------------------------------------------------------- 模式
# 界面用的短名 -> 手册里的 SCPI 关键字
MODES = {
    "CC": "CURRent",
    "CV": "VOLTage",
    "CP": "POWer",
    "CR": "RESistance",
    "DYNA": "DYNamic",
    "LED": "LED",
}
# SCPI 关键字(大写去尾) -> 短名
MODE_BY_SCPI = {
    "CURRENT": "CC", "CURR": "CC",
    "VOLTAGE": "CV", "VOLT": "CV",
    "POWER": "CP", "POW": "CP",
    "RESISTANCE": "CR", "RES": "CR",
    "DYNAMIC": "DYNA", "DYN": "DYNA",
    "LED": "LED",
}

# 各模式对应的设定值命令 / 单位 / 界面标签
SET_CMD = {"CC": "CURR", "CV": "VOLT", "CP": "POW", "CR": "RES"}
SET_UNIT = {"CC": "A", "CV": "V", "CP": "W", "CR": "ohm"}
SET_LABEL = {"CC": "拉载电流", "CV": "拉载电压", "CP": "拉载功率", "CR": "拉载电阻"}

# 本地量程上限的键名（英文，UI 标签单独映射，避免中英文键不匹配导致拦截失效）
LIMIT_KEYS = ("current", "voltage", "power", "resistance")
LIMIT_LABEL = {"current": "电流", "voltage": "电压", "power": "功率", "resistance": "电阻"}
LIMIT_UNIT = {"current": "A", "voltage": "V", "power": "W", "resistance": "ohm"}

# 手册默认（面板 JT6321A 老批次：150V/30A/300W）
DEFAULT_LIMITS = {
    "current": 30.0,
    "voltage": 150.0,
    "power": 300.0,
    "resistance": 50000.0,
}

# 可查询状态寄存器（Questionable Status）位定义：手册 5.2
QUESTIONABLE_BITS = [
    (0,  "VF",  "电压故障"),
    (1,  "OC",  "过电流保护"),
    (3,  "OP",  "过功率保护"),
    (4,  "OT",  "过热保护"),
    (9,  "RRV", "远端输入极性反接"),
    (10, "UNR", "测量未就绪"),
    (11, "LRV", "本地输入极性反接"),
    (12, "OV",  "过电压保护"),
]


# ---------------------------------------------------------------- 构造
def build(cmd: str, *args) -> str:
    """把命令头和参数拼成一帧（不含换行符）。"""
    parts = [cmd]
    for a in args:
        if a is None or a == "":
            continue
        if isinstance(a, bool):
            parts.append("ON" if a else "OFF")
        else:
            parts.append(str(a))
    return " ".join(parts)


def cmd_mode(mode_key: str) -> str:
    return build("MODE", MODES[mode_key])


def q_mode() -> str:
    return "MODE?"


def cmd_input(on: bool) -> str:
    return build("INP", "ON" if on else "OFF")


def q_input() -> str:
    return "INP?"


def cmd_short(on: bool) -> str:
    return build("INP:SHOR", "ON" if on else "OFF")


def q_short() -> str:
    return "INP:SHOR?"


def cmd_set_value(mode_key: str, value: float) -> str:
    return build(SET_CMD[mode_key], "%.6g" % value)


def q_set_value(mode_key: str) -> str:
    return SET_CMD[mode_key] + "?"


def cmd_prot_current(value: float) -> str:
    return build("CURR:PROT", "%.6g" % value)


def q_prot_current() -> str:
    return "CURR:PROT?"


def cmd_prot_power(value: float) -> str:
    return build("POW:PROT", "%.6g" % value)


def q_prot_power() -> str:
    return "POW:PROT?"


def cmd_von(value: float) -> str:
    return build("VOLT:ON", "%.6g" % value)


def cmd_voff(value: float) -> str:
    return build("VOLT:OFF", "%.6g" % value)


def cmd_slew(value: float) -> str:
    return build("CURR:SLEW", "%.6g" % value)


def q_slew() -> str:
    return "CURR:SLEW?"


def cmd_dyn(low: float, high: float, t_low: float, t_high: float) -> list:
    """动态模式参数：低准位/高准位电流 + 各自持续时间(秒)。"""
    return [
        build("DYN:LOW", "%.6g" % low),
        build("DYN:HIGH", "%.6g" % high),
        build("DYN:LOW:DWEL", "%.6g" % t_low),
        build("DYN:HIGH:DWEL", "%.6g" % t_high),
    ]


# 测量项：短名 -> (SCPI 查询, 单位, 中文)
MEAS_ITEMS = {
    "V":    ("MEAS:VOLT?", "V", "电压平均值"),
    "I":    ("MEAS:CURR?", "A", "电流平均值"),
    "P":    ("MEAS:POW?",  "W", "功率平均值"),
    "R":    ("MEAS:RES?",  "ohm", "等效电阻"),
    "VPP":  ("MEAS:VOLT:PTP?", "V", "电压峰峰值"),
    "IPP":  ("MEAS:CURR:PTP?", "A", "电流峰峰值"),
    "VP+":  ("MEAS:VOLT:MAX?", "V", "电压峰值"),
    "VP-":  ("MEAS:VOLT:MIN?", "V", "电压谷值"),
}


def q_measure(item: str) -> str:
    return MEAS_ITEMS[item][0]


def q_status() -> str:
    return "STAT:QUES:COND?"


def cmd_ocp(on: bool) -> str:
    return build("OCP", "ON" if on else "OFF")


def cmd_ocp_param(i_start=None, i_end=None, steps=None, dwell=None, vtrig=None) -> list:
    out = []
    if i_start is not None:
        out.append(build("OCP:IST", "%.6g" % i_start))
    if i_end is not None:
        out.append(build("OCP:IEND", "%.6g" % i_end))
    if steps is not None:
        out.append(build("OCP:STEP", int(steps)))
    if dwell is not None:
        out.append(build("OCP:DWEL", "%.6g" % dwell))
    if vtrig is not None:
        out.append(build("OCP:VTR", "%.6g" % vtrig))
    return out


def q_ocp_result() -> str:
    return "OCP:RES?"


def q_ocp_pmax() -> str:
    return "OCP:RES:PMAX?"


# ---------------------------------------------------------------- 解析
def parse_float(text) -> float:
    """把仪器回的一行文本转成 float；失败抛 ValueError。"""
    if text is None:
        raise ValueError("无应答")
    s = str(text).strip()
    if not s:
        raise ValueError("应答为空")
    # 只取第一个数值字段（有的仪器会回 "1.234A" 这种带单位的）
    m = _NUM_RE.search(s)
    if not m:
        raise ValueError("应答不是数值: %r" % s)
    return float(m.group(0))


_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_bool(text) -> bool:
    """仪器回 0/1（也可能 OFF/ON）。"""
    s = str(text).strip().upper()
    if s.startswith("1") or s.startswith("ON"):
        return True
    return False


def parse_idn(text):
    """*IDN? -> dict(manufacturer, model, serial, version)"""
    s = (text or "").strip()
    seg = [x.strip() for x in s.split(",")]
    seg += [""] * (4 - len(seg))
    return {
        "manufacturer": seg[0],
        "model": seg[1],
        "serial": seg[2],
        "version": seg[3],
        "raw": s,
    }


def parse_mode(text) -> str:
    """把仪器回的模式关键字翻成短名（CC/CV/CP/CR/DYNA/LED）。"""
    s = str(text or "").strip().upper()
    if s in MODE_BY_SCPI:
        return MODE_BY_SCPI[s]
    for k, v in MODE_BY_SCPI.items():
        if s.startswith(k):
            return v
    raise ValueError("未知模式: %r" % text)


def parse_status(text) -> dict:
    """STAT:QUES:COND? 的 16 位状态字 -> {名称: bool}"""
    try:
        val = int(float(str(text).strip()))
    except Exception:
        raise ValueError("状态字解析失败: %r" % text)
    out = {"raw": val}
    for bit, name, _cn in QUESTIONABLE_BITS:
        out[name] = bool(val & (1 << bit))
    return out


def check_limit(kind: str, value: float, limits: dict):
    """本地量程拦截：越界抛 ValueError，一条报文都不发。

    kind 用英文键（current/voltage/power/resistance），与 DEFAULT_LIMITS 对齐。
    上限 <= 0 表示该项不限制。
    """
    if kind not in LIMIT_KEYS:
        raise ValueError("未知量限类型: %s" % kind)
    lim = float(limits.get(kind, 0.0) or 0.0)
    if lim <= 0:
        return
    if value > lim + 1e-9:
        raise ValueError(
            "%s %.6g %s 超过本机上限 %.6g %s（已本地拦截，未下发）"
            % (LIMIT_LABEL[kind], value, LIMIT_UNIT[kind], lim, LIMIT_UNIT[kind])
        )
    if value < -1e-9:
        raise ValueError("%s 不能为负值" % LIMIT_LABEL[kind])
