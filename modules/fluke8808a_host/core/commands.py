# -*- coding: utf-8 -*-
"""FLUKE 8808A 命令表 —— 全流程单一事实源。

派生方向：协议栈(compose/parse)、模拟从站(execute)、界面(功能/量程/速率下拉)
均从本表派生，禁止在别处硬编码命令字面量。

来源：福禄克 8808A 用户手册 第4章"通过计算机接口操作万用表"（手册版本对应见 VERSIONS）。
手册未写清处一律进 CLARIFICATIONS，不猜测。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


# ---------------------------------------------------------------- 版本对应关系
VERSIONS = {
    "software": "1.0.0",        # 上位机版本
    "protocol": "8808A-RS232-CMD v1 (手册第4章)",  # 协议版本
    "command_table": "1.0.0",   # 命令表版本
    "manual": "福禄克8808A用户手册 (中文版)",
}

# ---------------------------------------------------------------- 澄清项（不猜测）
CLARIFICATIONS = [
    ("MAX/MIN 助记符", "手册表4-10译为'最大值/最小值'，按 MAXSET/MINSET 对称暂定 MAX/MIN，待厂家确认"),
    ("*ERR?", "正文提及但命令表未列，不依赖；错误判定用提示符 + *ESR?"),
    ("HOLDTHRESH 门限", "表3-7(5/7/8%量程) 与 表4-10(0.01/0.1/1/10%) 不一致，按命令表 1-4 暂定"),
    ("*TST", "命令表描述为查询但未带'?'，按 *TST? 暂定"),
    ("流控", "手册未写明 XON/XOFF，RS-232 默认无流控"),
    ("回显", "回显开启时逐字符回显且返回提示符；回显关闭时无提示符，同步策略据此设计"),
    ("MEAS? 外触发", "手册注明外触发(类型2-5)下 MEAS? 结果不可预期；轮询用 VAL1?"),
]


class CmdKind(Enum):
    SET = "set"          # 只写，无响应体（提示符收尾）
    QUERY = "query"      # 读，返回数据 + 提示符


@dataclass(frozen=True)
class CommandSpec:
    mnemonic: str              # 命令助记符（不含参数、不含问号）
    kind: CmdKind
    desc: str                  # 中文说明（界面提示/文档）
    params: Tuple[str, ...] = ()   # 参数占位名，空元组=无参数
    responses: Tuple[str, ...] = ()  # 查询响应字段说明
    page: str = ""             # 手册出处（表号）

    @property
    def is_query(self) -> bool:
        return self.kind is CmdKind.QUERY

    def template(self) -> str:
        """命令模板串，如 'RANGE <n>' / 'MEAS1?'。"""
        base = self.mnemonic + ("?" if self.is_query else "")
        if self.params:
            return base + " " + " ".join(f"<{p}>" for p in self.params)
        return base


def _c(m, k, d, params=(), resp=(), page=""):
    return CommandSpec(m, k, d, tuple(params), tuple(resp), page)


# ---------------------------------------------------------------- 通用命令 表4-8
GENERAL = [
    _c("*CLS",  CmdKind.SET,   "清除状态（事件寄存器）", page="表4-8"),
    _c("*ESE",  CmdKind.SET,   "设置事件状态使能寄存器", params=("value",), page="表4-8"),
    _c("*ESE?", CmdKind.QUERY, "查询事件状态使能寄存器", resp=("value 0-255",), page="表4-8"),
    _c("*ESR?", CmdKind.QUERY, "读事件状态寄存器并清零", resp=("value 0-255",), page="表4-8"),
    _c("*IDN?", CmdKind.QUERY, "标识码查询", resp=("制造商,型号,序列号,版本",), page="表4-8"),
    _c("*OPC",  CmdKind.SET,   "操作完成（置ESR.0）", page="表4-8"),
    _c("*OPC?", CmdKind.QUERY, "操作完成查询", resp=("1",), page="表4-8"),
    _c("*RST",  CmdKind.SET,   "上电复位", page="表4-8"),
    _c("*SRE",  CmdKind.SET,   "设置服务请求使能寄存器", params=("value",), page="表4-8"),
    _c("*SRE?", CmdKind.QUERY, "查询服务请求使能寄存器", resp=("value 0-255",), page="表4-8"),
    _c("*STB?", CmdKind.QUERY, "读状态字节", resp=("value 0-255",), page="表4-8"),
    _c("*TRG",  CmdKind.SET,   "触发一次测量", page="表4-8"),
    _c("*TST?", CmdKind.QUERY, "自检查询", resp=("0",), page="表4-8"),
    _c("*WAI",  CmdKind.SET,   "等待继续（无动作）", page="表4-8"),
]

# ---------------------------------------------------------------- 功能命令 表4-9
FUNCTIONS = [
    _c("VDC",   CmdKind.SET, "直流电压（主屏）", page="表4-9"),
    _c("VAC",   CmdKind.SET, "交流电压（主屏）", page="表4-9"),
    _c("VACDC", CmdKind.SET, "交流+直流 RMS 电压（主屏）", page="表4-9"),
    _c("ADC",   CmdKind.SET, "直流电流（主屏）", page="表4-9"),
    _c("AAC",   CmdKind.SET, "交流电流（主屏）", page="表4-9"),
    _c("AACDC", CmdKind.SET, "交流+直流 RMS 电流（主屏）", page="表4-9"),
    _c("OHMS",  CmdKind.SET, "电阻（主屏）", page="表4-9"),
    _c("FREQ",  CmdKind.SET, "频率（主屏）", page="表4-9"),
    _c("CONT",  CmdKind.SET, "通断性测试", page="表4-9"),
    _c("DIODE", CmdKind.SET, "二极管测试", page="表4-9"),
    _c("WIRE2", CmdKind.SET, "电阻 2 线测量", page="表4-9"),
    _c("WIRE4", CmdKind.SET, "电阻 4 线测量", page="表4-9"),
    _c("VDC2",  CmdKind.SET, "直流电压（副屏）", page="表4-9"),
    _c("VAC2",  CmdKind.SET, "交流电压（副屏）", page="表4-9"),
    _c("ADC2",  CmdKind.SET, "直流电流（副屏）", page="表4-9"),
    _c("AAC2",  CmdKind.SET, "交流电流（副屏）", page="表4-9"),
    _c("OHMS2", CmdKind.SET, "电阻（副屏）", page="表4-9"),
    _c("FREQ2", CmdKind.SET, "频率（副屏）", page="表4-9"),
    _c("CLR2",  CmdKind.SET, "清除副屏测量值", page="表4-9"),
    _c("FUNC1?", CmdKind.QUERY, "查询主屏所选功能助记符", resp=("mnemonic",), page="表4-9"),
    _c("FUNC2?", CmdKind.QUERY, "查询副屏所选功能助记符", resp=("mnemonic",), page="表4-9"),
]

# ---------------------------------------------------------------- 功能调节器 表4-10
MODIFIERS = [
    _c("DB",         CmdKind.SET,   "进入 dB 调节器", page="表4-10"),
    _c("DBCLR",      CmdKind.SET,   "退出 dB 调节器并清除 dB功/REL/MINMAX", page="表4-10"),
    _c("DBPOWER",    CmdKind.SET,   "dB 功率调节器（参考阻抗 2/4/8/16Ω）", page="表4-10"),
    _c("DBREF",      CmdKind.SET,   "设置 dB 参考阻抗编号", params=("index",), page="表4-10"),
    _c("DBREF?",     CmdKind.QUERY, "查询 dB 参考阻抗编号", resp=("index 1-21",), page="表4-10"),
    _c("HOLD",       CmdKind.SET,   "进入/强制接触保持", page="表4-10"),
    _c("HOLDCLR",    CmdKind.SET,   "退出接触保持", page="表4-10"),
    _c("HOLDTHRESH", CmdKind.SET,   "设置 HOLD 门限", params=("threshold",), page="表4-10"),
    _c("HOLDTHRESH?", CmdKind.QUERY, "查询 HOLD 门限", resp=("1-4",), page="表4-10"),
    _c("MAX",        CmdKind.SET,   "进入 MAX 调节器（助记符待厂家确认）", page="表4-10"),
    _c("MAXSET",     CmdKind.SET,   "进入 MAX 并设定最大值", params=("value",), page="表4-10"),
    _c("MIN",        CmdKind.SET,   "进入 MIN 调节器（助记符待厂家确认）", page="表4-10"),
    _c("MINSET",     CmdKind.SET,   "进入 MIN 并设定最小值", params=("value",), page="表4-10"),
    _c("MNMX",       CmdKind.SET,   "进入 MIN MAX 调节器", page="表4-10"),
    _c("MNMXSET",    CmdKind.SET,   "进入 MIN MAX 并设定最小/最大值", params=("min", "max"), page="表4-10"),
    _c("MMCLR",      CmdKind.SET,   "退出 MIN MAX 调节器", page="表4-10"),
    _c("MOD?",       CmdKind.QUERY, "查询所选调节器（位或）", resp=("bitmask",), page="表4-10"),
    _c("REL",        CmdKind.SET,   "REL 相对读数（当前读数为基值）", page="表4-10"),
    _c("RELCLR",     CmdKind.SET,   "退出 REL", page="表4-10"),
    _c("RELSET",     CmdKind.SET,   "REL 并设定相对基值", params=("base",), page="表4-10"),
    _c("RELSET?",    CmdKind.QUERY, "查询相对基值", resp=("base",), page="表4-10"),
]

# ---------------------------------------------------------------- 量程/速率 表4-11
RANGE_RATE = [
    _c("AUTO",    CmdKind.SET,   "主屏自动量程", page="表4-11"),
    _c("AUTO?",   CmdKind.QUERY, "查询自动量程", resp=("1|0",), page="表4-11"),
    _c("FIXED",   CmdKind.SET,   "主屏手动量程（锁定当前量程）", page="表4-11"),
    _c("RANGE",   CmdKind.SET,   "设置主屏量程编号", params=("n",), page="表4-11"),
    _c("RANGE1?", CmdKind.QUERY, "查询主屏量程编号", resp=("n",), page="表4-11"),
    _c("RANGE2?", CmdKind.QUERY, "查询副屏量程编号", resp=("n",), page="表4-11"),
    _c("RATE",    CmdKind.SET,   "设置测量速度 S/M/F", params=("speed",), page="表4-11"),
    _c("RATE?",   CmdKind.QUERY, "查询测量速度", resp=("S|M|F",), page="表4-11"),
]

# ---------------------------------------------------------------- 测量查询 表4-12
MEASURE = [
    _c("MEAS?",  CmdKind.QUERY, "触发并读主/副屏（内触发限定）", resp=("v1[,v2]",), page="表4-12"),
    _c("MEAS1?", CmdKind.QUERY, "触发并读主屏", resp=("value",), page="表4-12"),
    _c("MEAS2?", CmdKind.QUERY, "触发并读副屏", resp=("value",), page="表4-12"),
    _c("VAL?",   CmdKind.QUERY, "读主/副屏显示值", resp=("v1[,v2]",), page="表4-12"),
    _c("VAL1?",  CmdKind.QUERY, "读主屏显示值", resp=("value",), page="表4-12"),
    _c("VAL2?",  CmdKind.QUERY, "读副屏显示值", resp=("value",), page="表4-12"),
]

# ---------------------------------------------------------------- 比对 表4-13
COMPARE = [
    _c("COMP",     CmdKind.SET,   "进入比对模式（自动开 HOLD）", page="表4-13"),
    _c("COMP?",    CmdKind.QUERY, "查询比对结果", resp=("HI|LO|PASS|-",), page="表4-13"),
    _c("COMPCLR",  CmdKind.SET,   "退出比对模式", page="表4-13"),
    _c("COMPHI",   CmdKind.SET,   "设置比对上限", params=("value",), page="表4-13"),
    _c("COMPLO",   CmdKind.SET,   "设置比对下限", params=("value",), page="表4-13"),
]

# ---------------------------------------------------------------- 触发 表4-14 / 表4-3
TRIGGER = [
    _c("TRIGGER",  CmdKind.SET,   "设置触发类型 1-5", params=("type",), page="表4-14"),
    _c("TRIGGER?", CmdKind.QUERY, "查询触发类型", resp=("1-5",), page="表4-14"),
]

# ---------------------------------------------------------------- 其它 表4-15
MISC = [
    _c("FORMAT",  CmdKind.SET,   "输出格式 1|2", params=("fmt",), page="表4-15"),
    _c("FORMAT?", CmdKind.QUERY, "查询输出格式", resp=("1|2",), page="表4-15"),
    _c("PRINT",   CmdKind.SET,   "设置打印模式速率", params=("rate",), page="表4-15"),
    _c("SERIAL?", CmdKind.QUERY, "查询序列号", resp=("serial",), page="表4-15"),
]

# ---------------------------------------------------------------- 远程/本地 表4-17 / 存取 表4-18
REMOTE = [
    _c("REMS", CmdKind.SET, "远程状态（不锁面板）", page="表4-17"),
    _c("RWLS", CmdKind.SET, "远程锁定（锁面板）", page="表4-17"),
    _c("LOCS", CmdKind.SET, "本地状态", page="表4-17"),
    _c("LWLS", CmdKind.SET, "本地锁定", page="表4-17"),
    _c("SAVE", CmdKind.SET, "保存工作状态到位置", params=("position",), page="表4-18"),
    _c("CALL", CmdKind.SET, "从位置调用工作状态", params=("position",), page="表4-18"),
]

ALL_COMMANDS = GENERAL + FUNCTIONS + MODIFIERS + RANGE_RATE + MEASURE + COMPARE + TRIGGER + MISC + REMOTE

# 助记符 -> CommandSpec（统一查表入口）
COMMAND_MAP = {c.mnemonic: c for c in ALL_COMMANDS}
assert len(COMMAND_MAP) == len(ALL_COMMANDS), "命令助记符重复"


# ---------------------------------------------------------------- 值域（单一事实源）
# 量程编号表（手册 表4-11A）。None = 该功能无此量程编号。
RANGE_TABLE = {
    # 量程编号: (VDC/VAC量程, OHMS量程, AAC量程, FREQ量程, ADC量程)
    1: ("200 mV", "200 Ω",  "20 mA",  "2 kHz",   "200 µA"),
    2: ("2 V",    "2 kΩ",   "200 mA", "20 kHz",  "2000 µA"),
    3: ("20 V",   "20 kΩ",  "2 A",    "200 kHz", "20 mA"),
    4: ("200 V",  "200 kΩ", "10 A",   "1000 kHz","200 mA"),
    5: ("1000 V", "2 MΩ",   None,     None,      "2 A"),
    6: (None,     "20 MΩ",  None,     None,      "10 A"),
    7: (None,     "100 MΩ", None,     None,      None),
}

RATE_TABLE = {  # 手册 表4-11 / 表4-4
    "S": 2.5,   # 读数/秒
    "M": 20.0,
    "F": 100.0,
}

TRIGGER_TYPES = {  # 手册 表4-3: 类型 -> (触发源, 后面板触发, 稳定延迟)
    1: ("内部",   "停用", "—"),
    2: ("外部",   "停用", "关闭"),
    3: ("外部",   "停用", "开启"),
    4: ("外部",   "启用", "关闭"),
    5: ("外部",   "启用", "开启"),
}

DBREF_TABLE = {  # 手册 表4-10A: 编号 -> 参考阻抗(Ω)
    1: 2, 2: 4, 3: 8, 4: 16, 5: 50, 6: 75, 7: 93, 8: 110, 9: 124,
    10: 125, 11: 135, 12: 150, 13: 250, 14: 300, 15: 500,
    16: 600, 17: 800, 18: 900, 19: 1000, 20: 1200, 21: 8000,
}

HOLD_THRESHOLDS = (1, 2, 3, 4)   # 手册表4-10 暂定 0.01/0.1/1/10%
COMPARE_RESULTS = ("HI", "LO", "PASS", "-")

# 界面主功能按钮 -> 功能命令（界面按此绑定，不写死命令字面量）
UI_FUNCTIONS = [
    ("直流电压", "VDC"),
    ("交流电压", "VAC"),
    ("直流电流", "ADC"),
    ("交流电流", "AAC"),
    ("电阻(2线)", "OHMS"),
    ("电阻(4线)", "OHMS"),   # 附加 WIRE4，见 instrument 层语义
    ("频率", "FREQ"),
    ("通断性", "CONT"),
    ("二极管", "DIODE"),
]

# ---------------------------------------------------------------- 数值格式（手册 4-7 节）
# 仪器输出: +1.2345E+0 / +12.345E+6 OHM（格式2） / +/- 1.0E+9 表示过载
OVERLOAD_VALUE = 1.0e9
NUMERIC_PATTERN = r"[+-]?\d+(?:\.\d+)?(?:E[+-]?\d+)?"


# ---------------------------------------------------------------- 提示符协议
PROMPT_OK = "=>"      # 无错误，可发下一条
PROMPT_CMD_ERR = "?>" # 命令错误（解析失败）
PROMPT_EXE_ERR = "!>" # 执行/设备相关错误
ALL_PROMPTS = (PROMPT_OK, PROMPT_CMD_ERR, PROMPT_EXE_ERR)


@dataclass
class RegisterTable:
    """命令表元信息（交付文档用）。"""
    version: str = VERSIONS["command_table"]
    commands: tuple = field(default_factory=lambda: tuple(ALL_COMMANDS))
