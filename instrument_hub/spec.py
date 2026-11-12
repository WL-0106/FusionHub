# -*- coding: utf-8 -*-
"""仪器描述数据结构 —— 全流程"单一事实源"。

新增一台仪器 = 写一个 instruments/xxx.py，构造 InstrumentSpec 并 register(spec)，
界面/协议速查/通讯日志全部由该结构派生，不需要改框架代码。

注意：verified=False 表示"待真机确认"，界面会打黄色标记。
抽表阶段不确定的字段一律 verified=False，禁止猜测后当作事实。
"""
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class Command:
    cmd: str                 # 命令/功能码
    desc: str                # 功能说明
    params: str = "-"        # 参数
    resp: str = "-"          # 返回
    verified: bool = False   # True=已真机验证；False=待真机确认


@dataclass
class Register:
    addr: str
    name: str
    dtype: str = "u16"
    unit: str = "-"
    span: str = "-"
    rw: str = "RO"
    verified: bool = False


@dataclass
class Caution:
    level: str               # danger / warn / info
    text: str


@dataclass
class Param:
    key: str
    label: str
    unit: str
    value: float
    min: float
    max: float
    step: float = 0.1
    decimals: int = 2


@dataclass
class Readout:
    key: str
    label: str
    unit: str
    color: str               # 波形/数字颜色
    base: float = 0.0        # 模拟量基准
    amp: float = 0.02        # 模拟波动幅度
    decimals: int = 3


@dataclass
class Output:
    key: str
    label: str
    risk: str                # 二次确认弹窗展示的风险提示


@dataclass
class InstrumentSpec:
    id: str                  # 唯一 id，小写英文
    name: str                # 中文名
    model: str               # 型号
    vendor: str              # 厂家
    category: str            # 业务类别（直流电源/万用表/电子负载…）
    group: str = ""          # 二级目录：AC/DC源 / 仪器仪表 / 调试助手 / PLC / 采集卡（留空按 category 自动映射）
    iface: str = "-"         # 接口类型：RS-232 / USB-TMC / LAN…
    ip: str = "-"            # IP 地址（网络型设备，串口设备为 —）
    port_no: str = "-"       # 端口号（TCP 端口 / Modbus 从机地址）
    comm_type: str = "scpi"  # "modbus" / "scpi"（决定模拟帧格式）
    summary: str = ""        # 一句话简介
    basics: List[Tuple[str, str]] = field(default_factory=list)   # 基础参数（量程/精度/供电…），帮助页用
    versions: dict = field(default_factory=dict)   # {"上位机UI": "1.0.0", "协议": "v1.0", "寄存器表": "v1.0"}
    comm_info: List[Tuple[str, str]] = field(default_factory=list)   # 通信接口要点（粗/细共用）
    frame_info: List[Tuple[str, str]] = field(default_factory=list)  # 帧结构与时序要点
    commands: List[Command] = field(default_factory=list)
    registers: List[Register] = field(default_factory=list)
    error_codes: List[List[str]] = field(default_factory=list)       # [代码, 含义, 建议处理]
    cautions: List[Caution] = field(default_factory=list)            # 调试注意/坑位
    params: List[Param] = field(default_factory=list)                # 可设定参数
    readouts: List[Readout] = field(default_factory=list)            # 实时读数
    outputs: List[Output] = field(default_factory=list)              # 输出控制（均需二次确认）
    wave_channels: List[str] = field(default_factory=list)           # 波形通道 = readouts 的 key
    wave_ylim: Tuple[float, float] = (0.0, 1.0)
    poll_cmd: str = ""       # 轮询查询命令示例（SCPI 用）
