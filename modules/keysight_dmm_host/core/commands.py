# -*- coding: utf-8 -*-
"""
SCPI 命令表（单一事实源）
=========================
来源：Keysight Truevolt 系列(34461A/34465A/34470A) 操作和维修指南 9018-03876
      "SCPI 编程参考" 章节（印刷页 183 起）。

用法：
    代码、界面控件绑定、自动化测试用例均从本表派生，禁止在别处硬编码命令字串。
    verify 字段标注了"抽表阶段需与厂家/手册核实"的条目（七步流程第1步质量卡点：
    不确定处先标注澄清，不猜测）。

字段说明：
    key     语义键（界面/协议栈统一使用）
    scpi    SCPI 命令模板，{v} 为参数占位；query 类以 ? 结尾
    kind    query=只读查询 / set=只写 / set_query=可读可写 / system=系统控制
    unit    物理单位
    vtype   参数类型 float/int/bool/str
    rng     取值范围 (min, max) 或枚举集合，None=手册未限定
    access  R/W/RW
    desc    中文说明（人话）
    verify  待澄清项（非空表示需厂家/手册复核，禁止当作已确认）
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, Union


@dataclass(frozen=True)
class CommandDef:
    key: str
    scpi: str
    kind: str
    unit: str = ""
    vtype: str = "float"
    rng: Optional[Union[Tuple[float, float], frozenset]] = None
    access: str = "R"
    desc: str = ""
    verify: str = ""
    timeout_s: float = 1.0
    retries: int = 2

    @property
    def is_query(self) -> bool:
        """存在查询形态（下发后有响应）：纯查询 / system查询 / 可读可写。"""
        return self.scpi.rstrip().endswith("?") or self.kind == "set_query"

    @property
    def is_set(self) -> bool:
        """存在写形态（可带参下发）：set / set_query / system写。"""
        return not self.scpi.rstrip().endswith("?")

    @property
    def is_set_query(self) -> bool:
        return self.kind == "set_query"

    @property
    def query_form(self) -> str:
        """查询形态 SCPI：查询类原样；可读可写类去掉参数并追加 '?'。"""
        if self.scpi.rstrip().endswith("?"):
            return self.scpi.rstrip()
        return self.scpi.split(" ", 1)[0] + "?"


# ---------------------------------------------------------------------------
# 命令表 —— 单一事实源
# ---------------------------------------------------------------------------
COMMANDS: Tuple[CommandDef, ...] = (
    # ===== 系统 / IEEE488.2 公共命令（手册印刷页 249 IEEE 488.2 命令） =====
    CommandDef("idn_query", "*IDN?", "system", vtype="str", access="R",
               desc="读取厂商/型号/序列号/固件版本", timeout_s=2.0),
    CommandDef("reset", "*RST", "system", access="W", desc="复位仪器到默认状态"),
    CommandDef("clear_status", "*CLS", "system", access="W", desc="清除状态寄存器与错误队列"),
    CommandDef("self_test", "*TST?", "system", vtype="int", access="R",
               desc="自检，返回 0=通过", timeout_s=10.0,
               verify="自检最长耗时以手册为准，需复核超时上限"),
    CommandDef("opc_query", "*OPC?", "system", vtype="int", access="R",
               desc="查询操作完成标志", timeout_s=5.0),
    CommandDef("error_query", "SYSTem:ERRor?", "system", vtype="str", access="R",
               desc="读取错误队列一条记录，格式: <错误码>,\"<信息>\""),

    # ===== 识别 / 校准 =====
    CommandDef("cal_query", "CALibration:COUNt?", "query", vtype="int", access="R",
               desc="读取校准计数"),
    CommandDef("cal_secure_code", "CALibration:SECure:CODE", "set", vtype="str",
               access="W", desc="设置校准安全码",
               verify="安全码格式限制未在已读页确认，需查手册印刷页 495"),

    # ===== 测量类（手册印刷页 266 MEASure 子系统 / 195 READ?/FETCh?） =====
    CommandDef("read_dc_volt", "MEASure:VOLTage:DC?", "query", unit="V",
               access="R", desc="测量直流电压", timeout_s=2.0),
    CommandDef("read_ac_volt", "MEASure:VOLTage:AC?", "query", unit="V",
               access="R", desc="测量交流电压", timeout_s=2.0),
    CommandDef("read_dc_curr", "MEASure:CURRent:DC?", "query", unit="A",
               access="R", desc="测量直流电流", timeout_s=2.0),
    CommandDef("read_ac_curr", "MEASure:CURRent:AC?", "query", unit="A",
               access="R", desc="测量交流电流", timeout_s=2.0),
    CommandDef("read_res", "MEASure:RESistance?", "query", unit="Ohm",
               access="R", desc="测量电阻(2线)", timeout_s=2.0),
    CommandDef("read_fres", "MEASure:FRESistance?", "query", unit="Ohm",
               access="R", desc="测量电阻(4线)", timeout_s=2.0),
    CommandDef("read_cap", "MEASure:CAPacitance?", "query", unit="F",
               access="R", desc="测量电容", timeout_s=2.0,
               verify="34461A 是否支持电容档需按型号确认"),
    CommandDef("read_freq", "MEASure:FREQuency?", "query", unit="Hz",
               access="R", desc="测量频率", timeout_s=2.0),
    CommandDef("read_period", "MEASure:PERiod?", "query", unit="s",
               access="R", desc="测量周期", timeout_s=2.0),
    CommandDef("read_temp", "MEASure:TEMPerature?", "query", unit="C",
               access="R", desc="测量温度", timeout_s=3.0,
               verify="热电偶/RTD 传感器类型选择命令需查手册印刷页 298 UNIT/TEMP"),
    CommandDef("read_diode", "MEASure:DIODe?", "query", unit="V",
               access="R", desc="二极管测量", timeout_s=2.0),
    CommandDef("read_cont", "MEASure:CONTinuity?", "query", unit="Ohm",
               access="R", desc="通断测量", timeout_s=2.0),

    # ===== 配置类（手册印刷页 230 CONFigure 子系统） =====
    CommandDef("conf_dc_volt", "CONFigure:VOLTage:DC {v},{r}", "set", unit="V",
               vtype="str", access="W", desc="配置直流电压档位/分辨率，v=量程 r=分辨率",
               verify="量程与分辨率合法组合列表见手册印刷页 230，需抽表复核"),
    CommandDef("conf_ac_volt", "CONFigure:VOLTage:AC {v},{r}", "set", unit="V",
               vtype="str", access="W", desc="配置交流电压档位/分辨率"),
    CommandDef("conf_dc_curr", "CONFigure:CURRent:DC {v},{r}", "set", unit="A",
               vtype="str", access="W", desc="配置直流电流档位/分辨率"),
    CommandDef("conf_ac_curr", "CONFigure:CURRent:AC {v},{r}", "set", unit="A",
               vtype="str", access="W", desc="配置交流电流档位/分辨率"),
    CommandDef("conf_res", "CONFigure:RESistance {v},{r}", "set", unit="Ohm",
               vtype="str", access="W", desc="配置 2 线电阻档位/分辨率"),
    CommandDef("conf_fres", "CONFigure:FRESistance {v},{r}", "set", unit="Ohm",
               vtype="str", access="W", desc="配置 4 线电阻档位/分辨率"),
    CommandDef("conf_cap", "CONFigure:CAPacitance {v},{r}", "set", unit="F",
               vtype="str", access="W", desc="配置电容档位/分辨率",
               verify="34461A 电容档支持性需确认"),
    CommandDef("conf_freq", "CONFigure:FREQuency {v}", "set", unit="Hz",
               vtype="str", access="W", desc="配置频率测量量程"),
    CommandDef("conf_temp", "CONFigure:TEMPerature {v},{r}", "set", unit="C",
               vtype="str", access="W", desc="配置温度测量（传感器类型,量程）",
               verify="传感器类型参数枚举需查手册印刷页 230 温度节"),

    # ===== 量程 / 积分 / 触发（手册印刷页 294 SENSe 子系统 / 308 TRIGger） =====
    CommandDef("sense_range_volt", "SENSe:VOLTage:DC:RANGe {v}", "set_query",
               unit="V", access="RW", desc="直流电压量程(可读可写)",
               verify="量程边界 0.1/1/10/100 V 及 AUTO 需按手册复核"),
    CommandDef("sense_nplc", "SENSe:VOLTage:DC:NPLCycles {v}", "set_query",
               unit="PLC", rng=(0.02, 100.0), access="RW",
               desc="积分时间(NPLC)。34461A 上限 100；34465A/34470A 可到 200",
               verify="NPLC 上限与型号相关：34461A=100，34465A/34470A=200，需按型号分支"),
    CommandDef("sense_zero_auto", "SENSe:VOLTage:DC:ZERO:AUTO {v}", "set_query",
               vtype="str", rng=frozenset({"ON", "OFF", "ONCE", "AUTO"}),
               access="RW", desc="自动归零开关"),
    CommandDef("trig_source", "TRIGger:SOURce {v}", "set_query", vtype="str",
               rng=frozenset({"BUS", "IMMediate", "EXTernal", "INTernal"}),
               access="RW", desc="触发源"),
    CommandDef("trig_delay", "TRIGger:DELay {v}", "set_query", unit="s",
               rng=(0.0, 3600.0), access="RW", desc="触发延迟",
               verify="延迟上限以手册印刷页 308 为准"),
    CommandDef("trig_count", "TRIGger:COUNt {v}", "set_query", unit="次",
               vtype="int", rng=(1, 1000000), access="RW", desc="触发次数",
               verify="次数上限需查手册印刷页 308"),
    CommandDef("sample_count", "SAMPle:COUNt {v}", "set_query", unit="次",
               vtype="int", rng=(1, 1000000), access="RW", desc="每次触发采样数",
               verify="次数上限需查手册印刷页 288"),

    # ===== 流程控制（手册印刷页 191/195 INITiate/READ?/FETCh?） =====
    CommandDef("init_immed", "INITiate[:IMMediate]", "set", access="W",
               desc="启动一次测量"),
    CommandDef("init_cont", "INITiate:CONTinuous {v}", "set_query", vtype="str",
               rng=frozenset({"ON", "OFF", "0", "1"}), access="RW",
               desc="连续采集开关"),
    CommandDef("read_trigger", "READ?", "query", access="R",
               desc="触发并读取一个读数", timeout_s=2.0),
    CommandDef("fetch", "FETCh?", "query", access="R",
               desc="取回已触发的读数(不重新触发)", timeout_s=2.0),
    CommandDef("abort", "ABORt", "set", access="W", desc="中止测量"),

    # ===== 显示 / 系统（手册印刷页 244 DISPlay / 304 SYSTem） =====
    CommandDef("disp_text", "DISPlay:TEXT \"{v}\"", "set", vtype="str",
               access="W", desc="在仪器显示区显示文本",
               verify="文本长度上限与字符集需查手册印刷页 244"),
    CommandDef("disp_clear", "DISPlay:TEXT:CLEar", "set", access="W",
               desc="清除显示文本"),
    CommandDef("disp_state", "DISPlay:STATe {v}", "set_query", vtype="str",
               rng=frozenset({"ON", "OFF", "0", "1"}), access="RW",
               desc="显示开关"),
    CommandDef("sys_remote", "SYSTem:REMote", "set", access="W",
               desc="切换到远程模式"),
    CommandDef("sys_local", "SYSTem:LOCal", "set", access="W",
               desc="切换回本地模式"),
    CommandDef("sys_rwlock", "SYSTem:RWLock", "set", access="W",
               desc="远程锁定面板"),

    # ===== 格式（手册印刷页 246 FORMat） =====
    CommandDef("fmt_data", "FORMat:DATA {v}", "set_query", vtype="str",
               rng=frozenset({"ASCii", "REAL,64"}), access="RW",
               desc="读数数据格式(ASCII 或 REAL,64)"),

    # ===== 状态（手册印刷页 299 STATus） =====
    CommandDef("stat_oper", "STATus:OPERation?", "query", vtype="int",
               access="R", desc="操作状态寄存器"),
    CommandDef("stat_ques", "STATus:QUEStionable?", "query", vtype="int",
               access="R", desc="可疑状态寄存器"),
    CommandDef("stat_preset", "STATus:PRESet", "set", access="W",
               desc="复位状态子系统"),

    # ===== 扫描（仅 34465A/34470A 选件，手册印刷页 286 ROUTe） =====
    CommandDef("route_scan", "ROUTe:SCAN:FUNC {v}", "set_query", vtype="str",
               rng=frozenset({"ON", "OFF", "0", "1"}), access="RW",
               desc="扫描功能开关",
               verify="仅 34465A/34470A 多路复用选件支持，34461A 不支持"),
)


# 语义键 -> CommandDef 索引
CMD_MAP = {c.key: c for c in COMMANDS}


def get(key: str) -> CommandDef:
    """按语义键取命令定义。"""
    try:
        return CMD_MAP[key]
    except KeyError:
        raise KeyError(f"命令表中不存在语义键: {key}") from None


def queries():
    return [c for c in COMMANDS if c.is_query]


def sets():
    return [c for c in COMMANDS if not c.is_query]


def need_verify():
    """返回所有待澄清条目，供交付遗留问题清单引用。"""
    return [c for c in COMMANDS if c.verify]
