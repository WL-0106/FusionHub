# -*- coding: utf-8 -*-
"""AN9637HC / AN96HC 系列 电气安全综合分析仪 — SE 协议命令集与解析。

协议来源：艾诺《AN96HC 系列电气安全性能综合分析仪 用户手册》公开版 V1.0，
与用户手上的 v1.4 同系列，命令集一致。（v1.4 文件在本机被透明加密，无法读取。）

SE 协议要点（手册 3.3 节 + 附录 C.3）：
- 指令结束码：3.3 节写「以 LF(0x0A) 结束」；附录 C.3 写「所有通信协议命令最后
  都要加回车换行符 \\r\\n(0x0D 0x0A)」。两者存在出入。本模块默认发送 CRLF，
  结束符可在 Transport 层配置（终端用户现场对不上时改 LF 即可）。
- 设备应答三种：
    * 错误          -> NAK(0x15) + LF
    * 正确无需回传  -> ACK(0x06)  + LF
    * 正确且需回传  -> 数据字符串   + LF
- 本模块只负责「业务参数 <-> 命令字符串」的映射与范围校验，绝不碰串口/线程。

说明：SE 协议编辑的是「当前工作档案(work file)」。流程是
    FN nn,name  建立/选中档案
    SAA/SAD/SAI/SAG  向档案追加一个 ACW/DCW/IR/GND 测试步
    EV/EH/...    设置刚才追加的那一步的参数
    FS           存档
    TEST         跑整个档案；TD? / RD nn? 查结果
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


# --------------------------------------------------------------------------- #
# 参数描述                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class Param:
    key: str                 # 业务键（程序内部用）
    label: str               # 中文标签（界面显示）
    set_cmd: str             # 设置指令（不含值），如 "EV"
    get_cmd: str             # 查询指令，如 "EV?"
    unit: str                # 单位
    kind: str                # 'int' | 'float' | 'enum' | 'scanner'
    rng: tuple               # (min, max)，enum/scanner 可为 None
    enum: Optional[Dict[int, str]]  # kind=='enum' 时的值->显示映射
    default: Any
    note: str = ""           # 补充说明（界面 tooltip）


# 四种模式的参数表。命令名在手册里是「按当前步模式解释」的
# （EV/EH/EL/EDW/ECS/EF/ES 等在四种模式下都出现，作用随当前步而定）。
ACW_PARAMS = [
    Param("voltage", "测试电压", "EV", "EV?", "V", "float", (100, 5000), None, 1000.0,
          "ACW 电压范围 100~5000V（整系列规格 50~5000，命令表为 100~5000）"),
    Param("hi_limit", "电流总和上限", "EHT", "EHT?", "mA", "float", (0.0, 100.00), None, 25.0,
          "AN9637HC 为 40mA 机型，超 40 设不上去；命令表量程 0~100.00mA"),
    Param("lo_limit", "电流总和下限", "ELT", "ELT?", "mA", "float", (0.0, 9.999), None, 0.0),
    Param("ramp_up", "缓升时间", "ERU", "ERU?", "s", "float", (0.1, 999.9), None, 1.0),
    Param("ramp_down", "缓降时间", "ERD", "ERD?", "s", "float", (0.0, 999.9), None, 1.0,
          "0 或 0.5~999.9"),
    Param("dwell", "测试时间", "EDW", "EDW?", "s", "float", (0.0, 999.9), None, 2.0,
          "0 或 0.5~999.9"),
    Param("continuous", "连续测试", "ECS", "ECS?", "", "enum", None, {0: "OFF", 1: "ON"}, 0),
    Param("arc", "电弧灵敏度", "EA", "EA?", "", "int", (0, 9), None, 5),
    Param("freq", "输出频率", "EF", "EF?", "Hz", "enum", None, {0: "50", 1: "60"}, 0),
    Param("scanner", "矩阵扫描器", "ES", "ES?", "", "scanner", (8, 8), None, "OOOOOOOO",
          "8 位 H/L/O，H=高压端 L=回路端 O=不用"),
]

DCW_PARAMS = [
    Param("voltage", "测试电压", "EV", "EV?", "V", "float", (100, 6000), None, 1500.0),
    Param("hi_limit", "电流上限", "EH", "EH?", "uA", "float", (0.0, 20000.0), None, 1000.0),
    Param("lo_limit", "电流下限", "EL", "EL?", "uA", "float", (0.0, 1999.9), None, 0.0),
    Param("offset", "归零设置", "EO", "EO?", "uA", "float", (0.0, 200.0), None, 0.0,
          "只能自动归零(SAO)或手动设为 0"),
    Param("ramp_up", "缓升时间", "ERU", "ERU?", "s", "float", (0.4, 999.9), None, 1.0),
    Param("ramp_down", "缓降时间", "ERD", "ERD?", "s", "float", (0.0, 999.9), None, 1.0,
          "0 或 1.0~999.9"),
    Param("dwell", "测试时间", "EDW", "EDW?", "s", "float", (0.0, 999.9), None, 2.0,
          "0 或 0.5~999.9"),
    Param("continuous", "连续测试", "ECS", "ECS?", "", "enum", None, {0: "OFF", 1: "ON"}, 0),
    Param("arc", "电弧灵敏度", "EA", "EA?", "", "int", (0, 9), None, 5),
    Param("charge_lo", "充电下限", "ECG", "ECG?", "uA", "float", (0.0, 350.0), None, 50.0),
    Param("scanner", "矩阵扫描器", "ES", "ES?", "", "scanner", (8, 8), None, "OOOOOOOO"),
]

IR_PARAMS = [
    Param("voltage", "测试电压", "EV", "EV?", "V", "float", (100, 2500), None, 500.0),
    Param("hi_limit", "阻抗上限", "EH", "EH?", "MΩ", "float", (0.1, 50000.0), None, 2000.0),
    Param("lo_limit", "阻抗下限", "EL", "EL?", "MΩ", "float", (0.1, 50000.0), None, 0.1),
    Param("ramp_up", "缓升时间", "ERU", "ERU?", "s", "float", (0.1, 999.9), None, 1.0),
    Param("ramp_down", "缓降时间", "ERD", "ERD?", "s", "float", (0.0, 999.9), None, 1.0,
          "0 或 1.0~999.9"),
    Param("dwell", "测试时间", "EDW", "EDW?", "s", "float", (0.0, 999.9), None, 2.0,
          "0 或 0.5~999.9"),
    Param("continuous", "连续测试", "ECS", "ECS?", "", "enum", None, {0: "OFF", 1: "ON"}, 0),
    Param("charge_lo", "充电下限", "ECG", "ECG?", "uA", "float", (0.0, 3.500), None, 50.0),
    Param("scanner", "矩阵扫描器", "ES", "ES?", "", "scanner", (8, 8), None, "OOOOOOOO"),
]

GND_PARAMS = [
    Param("current", "输出电流", "EC", "EC?", "A", "float", (1.0, 32.0), None, 25.0),
    Param("voltage", "输出电压", "EV", "EV?", "V", "float", (3.0, 10.0), None, 6.0),
    Param("hi_limit", "阻抗上限", "EH", "EH?", "mΩ", "float", (1.0, 600.0), None, 100.0),
    Param("lo_limit", "阻抗下限", "EL", "EL?", "mΩ", "float", (0.0, 600.0), None, 0.0),
    Param("dwell", "测试时间", "EDW", "EDW?", "s", "float", (0.0, 999.9), None, 10.0,
          "0 或 0.5~999.9"),
    Param("continuous", "连续测试", "ECS", "ECS?", "", "enum", None, {0: "OFF", 1: "ON"}, 0),
    Param("offset", "归零设置", "EO", "EO?", "mΩ", "float", (0.0, 200.0), None, 0.0,
          "只能自动归零(SAO)或手动设为 0"),
    Param("freq", "输出频率", "EF", "EF?", "Hz", "enum", None, {0: "50", 1: "60"}, 0),
    Param("scanner", "矩阵扫描器", "ESN", "ESN?", "", "int", (0, 8), None, 0,
          "0=全部关闭，1~8=对应通道；注意 GND 用 ESN 且单值"),
]

MODES = {
    "ACW": {"name": "交流耐压", "add_cmd": "SAA", "params": ACW_PARAMS,
            "color": "#c0392b"},
    "DCW": {"name": "直流耐压", "add_cmd": "SAD", "params": DCW_PARAMS,
            "color": "#2980b9"},
    "IR":  {"name": "绝缘电阻", "add_cmd": "SAI", "params": IR_PARAMS,
            "color": "#27ae60"},
    "GND": {"name": "接地导通", "add_cmd": "SAG", "params": GND_PARAMS,
            "color": "#8e44ad"},
}

# 系统参数（与具体步无关）
SYSTEM_PARAMS = [
    Param("baud", "波特率", "SBR", "SBR?", "", "enum", None,
          {0: "9600", 1: "19200", 2: "38400", 3: "57600"}, 0, "0~3 对应 9600/19200/38400/57600"),
    Param("language", "语言", "SLA", "SLA?", "", "enum", None, {0: "English", 1: "简体中文"}, 1),
    Param("color", "界面颜色", "SCT", "SCT?", "", "enum", None,
          {0: "CYAN", 1: "GRAY", 2: "BLUE", 3: "WHITE"}, 0),
    Param("alarm", "警报音量", "SAL", "SAL?", "", "int", (0, 9), None, 5),
    Param("fail_stop", "失败停止", "SF", "SF?", "", "enum", None, {0: "OFF", 1: "ON"}, 1),
    Param("remote", "远程控制(PLC)", "SPR", "SPR?", "", "enum", None, {0: "OFF", 1: "ON"}, 0),
]


# --------------------------------------------------------------------------- #
# 命令构建与校验                                                                #
# --------------------------------------------------------------------------- #
class ProtocolError(Exception):
    pass


def _norm_num(text: str) -> float:
    """把命令回读的数值字符串解析成 float（容错空格/单位）。"""
    s = text.strip()
    # 去掉可能的单位尾缀
    for ch in ("V", "mA", "uA", "A", "MΩ", "mΩ", "Ω", "s", "Hz"):
        if s.endswith(ch):
            s = s[: -len(ch)].strip()
    try:
        return float(s)
    except ValueError:
        raise ProtocolError("无法解析数值: %r" % text)


def validate(param: Param, value) -> float:
    """把界面值转成可下发的数值字符串，并做范围校验。越界直接抛 ProtocolError。"""
    if param.kind == "enum":
        if isinstance(value, str):
            # 允许传显示名（如 "ON"）或数字
            inv = {v: k for k, v in param.enum.items()}
            if value in inv:
                value = inv[value]
            else:
                try:
                    value = int(value)
                except ValueError:
                    raise ProtocolError("%s 取值非法: %r" % (param.label, value))
        ival = int(value)
        if ival not in param.enum:
            raise ProtocolError("%s 取值 %s 不在枚举 %s 内"
                                 % (param.label, ival, list(param.enum)))
        return float(ival)

    if param.kind == "int":
        ival = int(round(float(value)))
        lo, hi = param.rng
        if not (lo <= ival <= hi):
            raise ProtocolError("%s 取值 %d 超出范围 [%d, %d]"
                                 % (param.label, ival, lo, hi))
        return float(ival)

    if param.kind == "scanner":
        s = str(value).upper().strip()
        if len(s) != 8 or any(c not in "HLO" for c in s):
            raise ProtocolError("%s 必须是 8 位 H/L/O: %r" % (param.label, value))
        return s

    # float
    fv = float(value)
    lo, hi = param.rng
    if not (lo <= fv <= hi):
        raise ProtocolError("%s 取值 %s 超出范围 [%s, %s]%s"
                             % (param.label, fv, lo, hi,
                                (" (" + param.unit + ")") if param.unit else ""))
    return fv


def build_set(param: Param, value) -> str:
    """构造一条设置命令字符串（不含结束符）。"""
    norm = validate(param, value)
    if param.kind == "scanner":
        return "%s %s" % (param.set_cmd, norm)
    # 数值下发：尽量保留原样；float 用通用格式
    if param.kind in ("enum", "int"):
        return "%s %d" % (param.set_cmd, int(norm))
    return "%s %s" % (param.set_cmd, _fmt_num(norm))


def build_get(param: Param) -> str:
    return param.get_cmd


def _fmt_num(fv: float) -> str:
    """数值转字符串：整数去小数点，否则按精度。"""
    if fv == int(fv):
        return str(int(fv))
    # 最多 4 位小数，去尾零
    s = ("%.4f" % fv).rstrip("0").rstrip(".")
    return s


def build_add_step(mode: str) -> str:
    return MODES[mode]["add_cmd"]


def build_file_new(num: str, name: str) -> str:
    return "FN %s,%s" % (num, name)


def build_file_load(num: str) -> str:
    return "FL %s" % num


def build_file_save() -> str:
    return "FS"


def build_file_delete(num: str = "") -> str:
    return "FD %s" % num if num else "FD"


def build_file_saveas(num: str, name: str) -> str:
    return "FSA %s,%s" % (num, name)


# --------------------------------------------------------------------------- #
# 应答解析                                                                      #
# --------------------------------------------------------------------------- #
ACK = b"\x06"
NAK = b"\x15"


def parse_response(raw: bytes):
    """解析设备原始应答。

    返回 (status, text)
        status: 'ACK' | 'NAK' | 'DATA'
        text:   DATA 时去掉结束符后的字符串；否则 ''
    """
    if not raw:
        raise ProtocolError("无有效响应帧（收到 0 字节）")
    # 去掉首尾空白/结束符
    data = raw.rstrip(b"\r\n")
    if data == ACK:
        return "ACK", ""
    if data == NAK:
        return "NAK", ""
    # 数据：可能带前导 ACK？规范里数据是「直接回传数据」，不带 ACK
    return "DATA", data.decode("utf-8", "replace").strip()


def is_ack(raw: bytes) -> bool:
    return raw.rstrip(b"\r\n") == ACK


def is_nak(raw: bytes) -> bool:
    return raw.rstrip(b"\r\n") == NAK


def strip_echo(raw: bytes, sent: str):
    """从应答里剥离「回显」。

    SE 协议里设备绝不回显命令文本（只回 ACK/NAK/数据）。现场若收到与发送
    内容相同的行，只可能是：RS485 半双工回显 / 接错口 / 仪器开了回显 /
    线缆 TX-RX 短路。此时真实应答可能在回显之后（同一缓冲）或还没到。

    返回：
        None            -> 没检测到回显（正常应答，原样处理）
        b"" (空)        -> 整个应答都是回显，真实应答还没到，需要继续读
        其余 bytes      -> 回显之后剩余的真实应答
    """
    if not raw:
        return None
    lines = raw.split(b"\n")
    kept, hit = [], False
    want = sent.strip().upper()
    for ln in lines:
        t = ln.strip(b"\r\n \t").decode("latin-1").strip().upper()
        if not hit and t == want and want:
            hit = True          # 只吞第一行回显
            continue
        kept.append(ln)
    if not hit:
        return None
    return b"\n".join(kept).strip(b"\r\n")
