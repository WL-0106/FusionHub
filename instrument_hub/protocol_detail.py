# -*- coding: utf-8 -*-
"""模块协议详情结构化数据 —— 「协议与调试规范」页的协议详情单一事实源。

与 module_page.CHARGE_MODULES / PROTO_NOTES 同源维护：
- 未在 PROTO_DETAILS 登记的模块，详情面板回退到 proto_note 纯文本展示；
- 在此登记的模块，详情面板按结构化区块（通信参数/功能码/寄存器/报文举例/故障码）展示。

约定：字段未确认的一律留空或标「待真机确认」，禁止猜测后当事实。

CAN 通信模块报文举例格式规范（硬性）：
    CAN 报文 = 29 位扩展 ID + 8 字节数据，缺一不可——只有 ID 才能寻址、只有数据才是载荷，
    所以报文举例必须同时给出「ID + 8 字节数据」，不能只写命令号或只写 ID 基址。
    统一写法（FrameExample.req / .resp 用换行分行，等宽字体下对齐）：
        "ID  0x028301F0\nDATA 00 00 00 00 00 00 00 00"
    未拿到真实协议文档的 CAN 模块，frames 留空，notes 里注明「待真机/协议文档补齐后按 EN+ 样板填写」，
    禁止凭空编造 ID 和字节。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class CommParam:
    """一条通信参数（键值对）。"""
    key: str
    value: str


@dataclass
class FuncCode:
    """一个功能码/命令。"""
    code: str        # 功能码（如 0x03）或命令（如 *IDN?）
    name: str        # 名称（读保持寄存器 / 写单寄存器…）
    desc: str = ""   # 说明


@dataclass
class Reg:
    """一个寄存器。"""
    addr: str        # 地址（0x0000）
    name: str        # 名称
    rw: str = "RO"   # RO / RW / WO
    note: str = ""   # 换算/说明


@dataclass
class FrameExample:
    """一条报文举例。"""
    title: str       # 说明（读 12 路电压…）
    req: str         # 请求报文（HEX）
    resp: str        # 返回报文（HEX）


@dataclass
class ErrorCode:
    """一条故障码。"""
    code: str        # 代码（0x01 / 异常码）
    name: str        # 含义
    fix: str = ""    # 建议处理


@dataclass
class ProtocolDetail:
    """一个模块的完整协议详情。"""
    module_id: str
    # 通信参数（右侧表格 + 详情头部共用）
    comm: List[CommParam] = field(default_factory=list)
    # 功能码 / 命令
    func_codes: List[FuncCode] = field(default_factory=list)
    # 寄存器表
    registers: List[Reg] = field(default_factory=list)
    # 报文举例（请求 + 返回）
    frames: List[FrameExample] = field(default_factory=list)
    # 故障信息表
    errors: List[ErrorCode] = field(default_factory=list)
    # 补充说明（自由文本，可选）
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 各模块协议详情（样例数据，后续逐个补齐）
# ---------------------------------------------------------------------------

PROTO_DETAILS: dict = {}


def _detail(mod_id: str, **kw) -> ProtocolDetail:
    d = ProtocolDetail(module_id=mod_id)
    for k, v in kw.items():
        setattr(d, k, v)
    return d


# ---- PK9015F 交流电压测量模块（Modbus RTU，已真机纠偏量程语义） ----
PROTO_DETAILS["pk9015f_host"] = _detail(
    "pk9015f_host",
    comm=[
        CommParam("通信口", "RS-485（D+/D-，二线制）"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（支持 1200/2400/4800/9600/19200，8-N-1）"),
        CommParam("默认地址", "1（1~255，出厂默认 1）"),
        CommParam("默认IP/端口", "无（现场无真机可走 TCP 串口服务器）"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读电压测量值 / 量程 / 修正值"),
        FuncCode("0x06", "写单寄存器", "写地址 / 波特率 / 修正值"),
    ],
    registers=[
        Reg("0x0000", "模块地址", "WO", "1~255，写后需重新上电"),
        Reg("0x0001", "波特率码", "WO", "03H=1200 ~ 07H=19200"),
        Reg("0x0002", "量程", "RO", "值×100 = 实际量程（250V 存 25000）"),
        Reg("0x0003~", "电压测量值", "RO", "每路 16 位有符号补码，raw×量程/10000 = V"),
        Reg("0x000F~", "电压修正值", "RW", "12 个，值/100 = V"),
    ],
    frames=[
        FrameExample("读 12 路电压", "01 03 00 03 00 0C 44 09",
                     "01 03 18 [24 字节数据] [CRC]"),
        FrameExample("读量程", "01 03 00 02 00 01 25 CA",
                     "01 03 02 61 A8 [CRC]（0x61A8=25000 → 250V）"),
        FrameExample("写修正值(CH0=+0.50V)", "01 06 00 0F 00 32 [CRC]",
                     "01 06 00 0F 00 32 [CRC]（原样回显）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x06"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址范围"),
        ErrorCode("0x03", "非法数据值", "量程/修正值超出范围"),
    ],
    notes=[
        "量程寄存器存的是「量程×100」（250V→25000），读回后需 ÷100，勿再按整数直接当 V 用。",
        "电压测量值为 16 位补码，raw>32767 时减 65536 才是负数。",
        "修正值正值增大读数、负值减小读数。",
    ],
)


# ---- PK9018B-8 热电阻温度模块（Modbus RTU，符号-绝对值） ----
PROTO_DETAILS["pk9018b_host"] = _detail(
    "pk9018b_host",
    comm=[
        CommParam("通信口", "RS-485（二线制）"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（支持 1200~19200，8-N-1）"),
        CommParam("默认地址", "1（1~255）"),
        CommParam("默认IP/端口", "无（现场走 TCP 串口服务器）"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读 8 路温度测量值 / 修正值"),
        FuncCode("0x10", "写多寄存器", "写温度修正值 / 地址波特率"),
    ],
    registers=[
        Reg("0x0000", "地址+波特率", "WO", "高 8 位=地址，低 8 位=波特率码"),
        Reg("0x0001~0x0008", "温度修正值", "RW", "8 路，16 位符号-绝对值，值/100 = ℃"),
        Reg("0x0009~0x0010", "温度测量值", "RO", "8 路，BIT15 符号位 + 低15位绝对值，值/100 = ℃"),
    ],
    frames=[
        FrameExample("读 8 路温度", "01 03 00 09 00 08 55 C8",
                     "01 03 10 [16 字节数据] [CRC]"),
        FrameExample("写 8 路修正值", "01 10 00 01 00 08 10 [16 字节] [CRC]",
                     "01 10 00 01 00 08 [CRC]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x10"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址 0x0000~0x0010"),
        ErrorCode("0x03", "非法数据值", "修正值超出量程"),
    ],
    notes=[
        "温度用「符号-绝对值」编码：BIT15=1 表示负数，低 15 位是绝对值（不是补码！）。",
        "0x8FA0 按符号-绝对值 = -40℃；若误用补码会得 -287.68℃。",
    ],
)


# ---- RU 灵巧系列电源（Modbus RTU） ----
PROTO_DETAILS["ru_power"] = _detail(
    "ru_power",
    comm=[
        CommParam("通信口", "RS-232 / RS-485"),
        CommParam("通信协议", "Modbus-RTU / Modbus-TCP"),
        CommParam("默认波特率", "9600（支持 1200~115200）"),
        CommParam("默认地址", "1"),
        CommParam("默认IP/端口", "TCP 默认 502"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读电压/电流/功率/状态"),
        FuncCode("0x06", "写单寄存器", "写电压/电流设定、输出开关"),
        FuncCode("0x10", "写多寄存器", "批量写设定"),
    ],
    registers=[
        Reg("0x0000", "电压设定", "RW", "单位 0.1V"),
        Reg("0x0001", "电流设定", "RW", "单位 0.01A"),
        Reg("0x0002", "输出开关", "RW", "1=开 / 0=关（二次确认）"),
        Reg("0x0003", "状态寄存器", "RO", "故障位，见故障信息表"),
    ],
    frames=[
        FrameExample("读电压设定", "01 03 00 00 00 01 84 0A",
                     "01 03 02 01 F4 [CRC]（0x01F4=500 → 50.0V）"),
        FrameExample("写输出开", "01 06 00 02 00 01 [CRC]",
                     "01 06 00 02 00 01 [CRC]（原样回显）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x06/0x10"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址"),
        ErrorCode("0x03", "非法数据值", "设定值超出量程"),
    ],
    notes=[
        "开启输出为高危动作，界面有二次确认，退出自动关输出。",
    ],
)


# ---- 继电器板卡（Modbus RTU/TCP，线圈类） ----
PROTO_DETAILS["relay"] = _detail(
    "relay",
    comm=[
        CommParam("通信口", "RS-485 / 以太网（RTU over TCP）"),
        CommParam("通信协议", "Modbus-RTU / Modbus-TCP"),
        CommParam("默认波特率", "9600"),
        CommParam("默认地址", "1"),
        CommParam("默认IP/端口", "TCP 默认 502"),
    ],
    func_codes=[
        FuncCode("0x01", "读线圈", "读继电器闭合状态"),
        FuncCode("0x02", "读离散输入", "读 16 路开入状态"),
        FuncCode("0x05", "写单线圈", "单路继电器闭合/断开"),
        FuncCode("0x0F", "写多线圈", "全开/全关/广播"),
    ],
    registers=[
        Reg("0x0000~0x000B", "继电器线圈", "RW", "12 路，1=闭合 / 0=断开"),
        Reg("0x1000~0x100F", "开入状态", "RO", "16 路开入，1=导通"),
        Reg("版本寄存器", "软硬件版本", "RO", "回读软硬件版本号"),
    ],
    frames=[
        FrameExample("读 12 路继电器状态", "01 01 00 00 00 0C [CRC]",
                     "01 01 02 0F 00 [CRC]（0x0F 表示 0~3 路闭合）"),
        FrameExample("闭合第 1 路", "01 05 00 00 FF 00 [CRC]",
                     "01 05 00 00 FF 00 [CRC]（原样回显）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x01/0x02/0x05/0x0F"),
        ErrorCode("0x02", "非法数据地址", "核对线圈地址范围"),
    ],
    notes=[
        "闭合继电器为高危动作，界面有二次确认；退出自动断开。",
    ],
)


# ---- PK6011R 单相电参数采集模块（Modbus RTU） ----
PROTO_DETAILS["pk6011r_host"] = _detail(
    "pk6011r_host",
    comm=[
        CommParam("通信口", "RS-485（二线制）"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（支持 1200/2400/4800/9600/19200，8-N-1）"),
        CommParam("默认地址", "1（1~247）"),
        CommParam("默认IP/端口", "无（现场走 TCP 串口服务器）"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读电压/电流/功率/功率因数/频率/电能（17 寄存器）"),
        FuncCode("0x06", "写单寄存器", "写地址+波特率 / 电压变比+电流变比"),
    ],
    registers=[
        Reg("0x0000", "量程 U0/I0", "RO", "高字节=电压量程(×2 V)、低字节=电流量程(A)"),
        Reg("0x0001", "变比 UBB/IBB", "RW", "高字节=电压变比、低字节=电流变比，默认 1"),
        Reg("0x0002", "电压 U", "RO", "raw/10×UBB = V"),
        Reg("0x0003", "电流 I", "RO", "raw/1000×IBB = A"),
        Reg("0x0004", "有功功率 P", "RO", "raw/10×UBB×IBB = W（int16）"),
        Reg("0x0005", "无功功率 Q", "RO", "raw/10×UBB×IBB = var（int16）"),
        Reg("0x0006", "功率因数 PF", "RO", "raw/10000（int16）"),
        Reg("0x0007", "视在功率 S", "RO", "raw/10×UBB×IBB = VA"),
        Reg("0x0008", "频率 F", "RO", "raw/100 = Hz"),
        Reg("0x0009~0x0010", "电能(4组)", "RO", "正/反向有功、正/反向无功，各 32 位，raw/100×UBB×IBB"),
    ],
    frames=[
        FrameExample("读 17 寄存器(全量)", "01 03 00 00 00 11 [CRC]",
                     "01 03 22 [34 字节数据] [CRC]"),
        FrameExample("写地址+波特率", "01 06 00 00 [新地址][波特率码] [CRC]",
                     "01 06 00 00 [原样回显] [CRC]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x06"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器 0x0000~0x0010"),
        ErrorCode("0x03", "非法数据值", "变比/地址超出范围"),
    ],
    notes=[
        "电流量程基准 5A：100A 量程 → IBB=20，电流/功率/电能都要 ×UBB×IBB。",
        "寄存器 0x0000 为地址+波特率只写寄存器，改后需按新参数重新连接。",
    ],
)


# ---- PK9015 12 路电流采集模块（Modbus RTU） ----
PROTO_DETAILS["pk9015_host"] = _detail(
    "pk9015_host",
    comm=[
        CommParam("通信口", "RS-485（二线制）"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（支持 1200~19200，8-N-1）"),
        CommParam("默认地址", "1（1~247）"),
        CommParam("默认IP/端口", "无（现场走 TCP 串口服务器）"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读 12 路电流 / 量程"),
        FuncCode("0x06", "写单寄存器", "写量程 / 地址波特率"),
    ],
    registers=[
        Reg("0x0000", "地址+波特率", "RW", "高 8 位=地址、低 8 位=波特率码(03~07H)"),
        Reg("0x0003~0x000E", "12 路电流", "RO", "每路 16 位无符号，raw/10000×量程"),
        Reg("0x02BE", "量程设置", "RW", "0=0-20mA、1=4-20mA、2=0-10V"),
    ],
    frames=[
        FrameExample("读 12 路电流", "01 03 00 03 00 0C [CRC]",
                     "01 03 18 [24 字节数据] [CRC]"),
        FrameExample("写量程 4-20mA", "01 06 02 BE 00 01 [CRC]",
                     "01 06 02 BE 00 01 [CRC]（原样回显）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x06"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址"),
        ErrorCode("0x03", "非法数据值", "量程取值超出 0~2"),
    ],
    notes=[
        "raw 为量程万分比：raw=0~10000 对应 0~100% 量程。",
        "0-20mA：实际=raw/10000×20；4-20mA：实际=4+raw/10000×16 (mA)。",
    ],
)


# ---- PK9015-32 32 通道模拟量输入模块（Modbus RTU） ----
PROTO_DETAILS["pk9015_32_host"] = _detail(
    "pk9015_32_host",
    comm=[
        CommParam("通信口", "RS-485（二线制）"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（支持 1200~19200，8-N-1）"),
        CommParam("默认地址", "1（1~247）"),
        CommParam("默认IP/端口", "无（现场走 TCP 串口服务器）"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读 32 通道数据 / 类型 / 量程"),
        FuncCode("0x06", "写单寄存器", "写地址+波特率 / 修正值"),
    ],
    registers=[
        Reg("0x0000", "地址+波特率", "RW", "高 8 位=地址、低 8 位=波特率码"),
        Reg("0x0001", "类型", "RO", "1=电流、其他=电压"),
        Reg("0x0002", "量程", "RO", "值×100=实际量程（50mA 存 5000）"),
        Reg("0x0003~0x0022", "32 通道数据", "RO", "每路 16 位无符号"),
        Reg("0x0023~", "修正值", "RW", "32 路修正值"),
    ],
    frames=[
        FrameExample("读 32 通道", "01 03 00 03 00 20 [CRC]",
                     "01 03 40 [64 字节数据] [CRC]"),
        FrameExample("读类型+量程", "01 03 00 01 00 02 [CRC]",
                     "01 03 04 [类型][量程高][量程低] [CRC]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x06"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器 0x0000~0x0022"),
        ErrorCode("0x03", "非法数据值", "修正值超出范围"),
    ],
    notes=[
        "电流：二次侧 mA = raw×量程/10000，一次侧 A = 二次侧×CT一次/CT二次/1000。",
        "量程寄存器值 ×100 = 实际量程，读回后需 ÷100。",
    ],
)


# ---- 中创智合采集卡（温度/电压/电流/混合四系列共用 Modbus） ----
PROTO_DETAILS["zczh_host"] = _detail(
    "zczh_host",
    comm=[
        CommParam("通信口", "RS-485 / 以太网（RJ45）"),
        CommParam("通信协议", "Modbus-RTU / Modbus-TCP（可软件切换）"),
        CommParam("默认波特率", "9600（可选 4800~115200）"),
        CommParam("默认地址", "1（1~247）"),
        CommParam("默认IP/端口", "TCP 默认 502（以太网版）"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读各通道数据 / 配置"),
        FuncCode("0x04", "读输入寄存器", "读只读数据区"),
        FuncCode("0x06", "写单寄存器", "写地址/波特率/校验/协议切换"),
        FuncCode("0x10", "写多寄存器", "批量写配置"),
    ],
    registers=[
        Reg("0x0000~0x000F", "温度数据（16 路）", "RO", "有符号 16 位 ÷10 = ℃；0x7FFF=断线/过温、0x8000=短路/超低温"),
        Reg("0x0000 起", "电压/电流数据", "RO", "无符号 16 位 ×量程÷10000 = V/A"),
        Reg("0x0050", "从站地址", "RW", "1~247"),
        Reg("0x0051", "波特率", "RW", "00=115200 01=9600 02=19200 03=38400…"),
        Reg("0x0052", "校验/停止位", "RW", "0=N,1 1=O,1 2=E,1 3=N,2 4=O,2 5=E,2"),
        Reg("0x0060", "协议切换（电压电流系列）", "RW", "0=RTU/TCP 兼容，1=指定 TCP"),
        Reg("0x01FA", "协议切换（温度系列）", "RW", "每 4 位对应一个通讯口"),
        Reg("0x0081", "采样速率（温度系列）", "RW", "数据刷新速率"),
        Reg("0x0053", "量程系数（电压电流系列）", "RW", "仅对 32 位寄存器数据有效"),
    ],
    frames=[
        FrameExample("读温度 16 路", "01 03 00 00 00 10 [CRC]",
                     "01 03 20 [32 字节数据] [CRC]"),
        FrameExample("读电压/电流 4 路", "01 03 00 00 00 04 [CRC]",
                     "01 03 08 [8 字节数据] [CRC]"),
        FrameExample("写协议切换", "01 06 00 60 00 01 [CRC]",
                     "01 06 00 60 00 01 [CRC]（原样回显）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x04/0x06/0x10"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址范围"),
        ErrorCode("0x03", "非法数据值", "设定值超出量程/范围"),
        ErrorCode("0x04", "从站设备故障", "设备内部故障，重启后重试"),
    ],
    notes=[
        "四大系列共用同一套 Modbus 协议，差异仅在寄存器映射表（series.py），新增型号 = 加一条配置。",
        "温度 ÷10（0.1℃）；电压/电流 ×量程÷10000，量程写产品铭牌上，务必在界面填入铭牌量程，否则读数错 10 倍、100 倍。",
        "电压电流系列协议切换用 0x0060H，温度系列用 0x01FAH，切换系列时自动选用对应寄存器与取值表。",
        "电压电流系列量程系数寄存器（0x0053H/0x0054H）只对 32 位寄存器数据有效，16 位数据用铭牌量程手动换算。",
    ],
)



# ---- 美恩斯 MSP65/MSP62 直流电源（Modbus RTU） ----
PROTO_DETAILS["msp_host"] = _detail(
    "msp_host",
    comm=[
        CommParam("通信口", "RS-232 / RS-485 / LAN（寄存器 2013 可切）"),
        CommParam("通信协议", "Modbus-RTU / SCPI（寄存器 2012/2020 可切）"),
        CommParam("默认波特率", "MSP65=115200、MSP62=9600（可切 9600~115200）"),
        CommParam("默认地址", "1（有效 1~100，0 为广播探测）"),
        CommParam("默认IP/端口", "LAN 时 TCP 默认 502"),
    ],
    func_codes=[
        FuncCode("0x04", "读只读寄存器", "读输出电压/电流/功率/状态"),
        FuncCode("0x03", "读可写寄存器", "读设定值/保护值"),
        FuncCode("0x06", "写单寄存器", "写设定值/保护值/输出开关"),
        FuncCode("0x10", "写多寄存器", "批量写设定，单帧 1~20 寄存器"),
    ],
    registers=[
        Reg("1000", "输出电压", "RO", "小数位按额定值推导"),
        Reg("1001", "输出电流", "RO", "小数位按额定值推导"),
        Reg("1002", "输出功率", "RO", "倍率按额定功率推导"),
        Reg("1003/1007", "设备状态", "RO", "位定义：输出/CC/CV/OV/OC/过热/故障"),
        Reg("2000", "设备地址", "RW", "1~100"),
        Reg("2001", "预置电压", "RW", "小数位同输出电压"),
        Reg("2002", "预置电流", "RW", "小数位同输出电流"),
        Reg("2003", "过压值 OVP", "RW", "小数位同输出电压"),
        Reg("2005", "过流值 OCP", "RW", "小数位同输出电流"),
        Reg("2009/2016", "输出控制", "RW", "0=停止、非0=启动（二次确认）"),
        Reg("2012/2020", "协议类型", "RW", "0=RTU、65=SCPI"),
    ],
    frames=[
        FrameExample("读输出电压电流功率状态", "01 04 03 E8 00 04 [CRC]",
                     "01 04 08 [8 字节数据] [CRC]"),
        FrameExample("写电压设定", "01 06 07 D1 [高][低] [CRC]",
                     "01 06 07 D1 [原样回显] [CRC]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "只读区用 0x04、可写区用 0x03"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址范围"),
        ErrorCode("0x03", "非法数据值", "设定值超出量程"),
    ],
    notes=[
        "开启输出为高危动作，界面有二次确认，退出自动关输出。",
        "MSP62 电压/电流小数位按电源规格生成，无统一换算式，由上位机配置。",
        "16 位无符号定点数，CRC-16/MODBUS 低字节在前。",
    ],
)


# ---- HSPY 大功率直流电源（Modbus RTU） ----
PROTO_DETAILS["hspy_host"] = _detail(
    "hspy_host",
    comm=[
        CommParam("通信口", "RS-232 / RS-485"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（8-N-2，可配置）"),
        CommParam("默认地址", "0（文档 0x1000 与 0x0000 两种基址均支持）"),
        CommParam("默认IP/端口", "无"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读电压/电流/功率设定与显示、状态"),
        FuncCode("0x06", "写单寄存器", "写输出开关/地址/波特率"),
        FuncCode("0x10", "写多寄存器", "批量写设定"),
    ],
    registers=[
        Reg("0x1000", "电压设定值", "RW", "2 位小数"),
        Reg("0x1001", "电流设定值", "RW", "3 位小数（可运行时覆盖）"),
        Reg("0x1002", "电压显示值", "RO", "2 位小数"),
        Reg("0x1003", "电流显示值", "RO", "3 位小数"),
        Reg("0x1004", "输出开关", "RW", "0=停止、1=输出"),
        Reg("0x1005", "通讯地址", "RW", "0~255"),
        Reg("0x1007", "功率设定值", "RW", "1 位小数"),
        Reg("0x1014", "过压保护 OVP", "RW", "3 位小数"),
        Reg("0x1015", "过流保护 OCP", "RW", "3 位小数"),
        Reg("0x1016", "输出状态测量", "RO", "0~1"),
    ],
    frames=[
        FrameExample("读电压设定+电流设定", "00 03 10 00 00 02 C1 1A",
                     "00 03 04 0E 10 0B B8 [CRC]"),
        FrameExample("写输出开", "00 06 10 04 00 01 [CRC]",
                     "00 06 10 04 00 01 [CRC]（原样回显）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x06/0x10"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器基址 0x1000"),
        ErrorCode("0x03", "非法数据值", "设定值超出量程"),
    ],
    notes=[
        "小数位因批次/功率段可能不一致（典型电流 3 位 vs 2 位），界面可运行时覆盖对齐实物。",
        "开启输出为高危动作，有二次确认。",
    ],
)


# ---- TP613 三相电量仪（Modbus RTU） ----
PROTO_DETAILS["tp613_host"] = _detail(
    "tp613_host",
    comm=[
        CommParam("通信口", "RS-485 / TCP 网口透传"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（0~5 对应 2400~115200）"),
        CommParam("默认地址", "1"),
        CommParam("默认IP/端口", "TCP 默认 502"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读三相电量参数（FLOAT 占 2 寄存器）"),
        FuncCode("0x06", "写单寄存器", "清需量/清电能/4-20mA 输出"),
        FuncCode("0x10", "写多寄存器", "批量写"),
    ],
    registers=[
        Reg("0x0064", "线电压 Uab", "RO", "IEEE754 FLOAT(ABCD)，占 2 寄存器"),
        Reg("0x006A", "线电压平均", "RO", "FLOAT"),
        Reg("0x006C", "相电压 Uan", "RO", "FLOAT"),
        Reg("0x0074", "电流 Ia", "RO", "FLOAT"),
        Reg("0x007E", "频率", "RO", "FLOAT"),
        Reg("0x0080", "功率因数", "RO", "FLOAT"),
        Reg("0x0082", "有功功率", "RO", "FLOAT"),
        Reg("0x00A0", "有功电能", "RO", "FLOAT"),
        Reg("0xEA5E", "4-20mA 输出", "RW", "FLOAT"),
        Reg("0xEA60", "清需量", "WO", "写 1"),
        Reg("0xEA62", "清电能", "WO", "写 1"),
    ],
    frames=[
        FrameExample("读 30 个电量参数", "01 03 00 64 00 3C [CRC]",
                     "01 03 78 [120 字节 FLOAT] [CRC]"),
        FrameExample("清累积电能", "01 06 EA 62 00 01 [CRC]",
                     "01 06 EA 62 00 01 [CRC]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x06/0x10"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址"),
        ErrorCode("0x03", "非法数据值", "数据值超范围"),
        ErrorCode("0x04", "从机故障", "从机内部错误"),
    ],
    notes=[
        "电量参数为 IEEE754 FLOAT（ABCD 大端），每值占 2 个寄存器。",
        "设备地址/波特率/PT/CT 变比只能面板或 TP 助手设置，Modbus 不提供读写接口。",
    ],
)


# ---- 电阻变送器（Modbus RTU） ----
PROTO_DETAILS["res_tx_host"] = _detail(
    "res_tx_host",
    comm=[
        CommParam("通信口", "RS-485"),
        CommParam("通信协议", "Modbus-RTU"),
        CommParam("默认波特率", "9600（2400~115200，8-N-1）"),
        CommParam("默认地址", "1（1~247）"),
        CommParam("默认IP/端口", "无（串口）"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "读电阻值 / RS485 参数"),
        FuncCode("0x04", "读输入寄存器", "读量值（只读区）"),
        FuncCode("0x06", "写单寄存器", "写许可开关 / 地址 / 波特率 / 数据格式"),
        FuncCode("0x10", "写多寄存器", "批量写参数"),
    ],
    registers=[
        Reg("0x0000", "电阻值（整数）", "RO", "UShort 无符号整数，单位 Ω"),
        Reg("0x0800~0x0801", "电阻值（Float）", "RO", "IEEE754 ABCD 高字在前，占 2 寄存器"),
        Reg("0x1BFE(7166)", "通信参数修改允许", "RW", "写 0xCCAA 才允许修改通信参数，写其它值关闭"),
        Reg("0x1BFF(7167)", "RS485 地址", "RW", "范围 1~247"),
        Reg("0x1C00(7168)", "RS485 波特率", "RW", "0=2400 1=4800 2=9600 3=19200 4=38400 5=57600 6=115200"),
        Reg("0x1C01(7169)", "RS485 数据格式", "RW", "0=8N1 1=8O1 2=8E1 3=8N2"),
    ],
    frames=[
        FrameExample("读整数电阻", "01 03 00 00 00 01 84 0A",
                     "01 03 02 12 C0 [CRC]（0x12C0=4800Ω）"),
        FrameExample("读浮点电阻", "01 03 08 00 00 02 C6 6B",
                     "01 03 04 43 F0 00 00 EF 84（43F00000=480.0Ω）"),
        FrameExample("写许可+写地址", "01 06 1B FE CC AA [CRC] → 01 06 1B FF 00 05 [CRC]",
                     "01 06 1B FF 00 05 [CRC]（原样回显）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认只发 0x03/0x04/0x06/0x10"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址"),
        ErrorCode("0x03", "非法数据值", "数据值超范围"),
        ErrorCode("0x04", "从站设备故障", "从机内部错误"),
    ],
    notes=[
        "修改 RS485 参数前必须先写寄存器 7166=0xCCAA 打开许可，写其它值关闭许可。",
        "Float 寄存器为 IEEE754 大端（ABCD 高字在前），占 2048~2049 两个寄存器。",
        "说明书中例 2 回帧原文 CRC（2F 87）为印刷错误，正确值应为 EF 84，已按核算值记录。",
    ],
)


# ---- RIGOL DM3058/DM3058E 万用表（SCPI） ----
PROTO_DETAILS["dm3058_host"] = _detail(
    "dm3058_host",
    comm=[
        CommParam("通信口", "RS-232 / USB-TMC / LAN"),
        CommParam("通信协议", "SCPI"),
        CommParam("默认波特率", "9600（串口）"),
        CommParam("默认地址", "—（SCPI 无需从机地址）"),
        CommParam("默认IP/端口", "LAN 走 TCP 默认 5025"),
    ],
    func_codes=[
        FuncCode("*IDN?", "标识查询", "返回制造商/型号/序列号/版本"),
        FuncCode(":FUNCtion:...", "功能切换", "DCV/ACV/DCI/ACI/2WR/4WR/FREQ/PERI/CONT/DIODE/CAP"),
        FuncCode(":MEASure:...?", "单次测量", "切换功能并读数"),
        FuncCode(":RATE:...", "速率设置", "F/M/S 快中慢"),
    ],
    registers=[],
    frames=[
        FrameExample("标识查询", "*IDN?", "RIGOL TECHNOLOGIES,DM3058,..."),
        FrameExample("测直流电压", ":MEASure:VOLTage:DC?", "+1.234500 V"),
        FrameExample("切直流电压量程", ":MEASure:VOLTage:DC 2", "（无应答，靠回读确认）"),
    ],
    errors=[
        ErrorCode("-113", "未定义头", "检查命令拼写"),
        ErrorCode("-222", "数据越界", "参数超出量程"),
        ErrorCode("+9.9E37", "无数据/超量程", "开路或量程过小"),
    ],
    notes=[
        "11 种测量功能：DCV/ACV/DCI/ACI/2WR/4WR/FREQ/PERI/CONT/DIODE/CAP。",
        "查询命令以 ? 结尾回一行，设置命令无应答。",
    ],
)


# ---- Keysight Truevolt 系列 DMM（SCPI） ----
PROTO_DETAILS["keysight_dmm_host"] = _detail(
    "keysight_dmm_host",
    comm=[
        CommParam("通信口", "RS-232 / LAN"),
        CommParam("通信协议", "SCPI-1999（IEEE 488.2 兼容，帧尾 LF 终结）"),
        CommParam("默认波特率", "9600（串口，可选至 115200）"),
        CommParam("默认地址", "—（SCPI 无需从机地址）"),
        CommParam("默认IP/端口", "LAN 走 TCP 默认 5025"),
    ],
    func_codes=[
        FuncCode("*IDN?", "标识查询", "返回制造商/型号/序列号/版本"),
        FuncCode("MEASure:<功能>?", "单次测量", "切换功能+触发+读数一步完成"),
        FuncCode("CONFigure:<功能>", "配置测量功能", "只配置不触发"),
        FuncCode("READ?/INITiate/FETCh?", "触发采集组", "触发后取数"),
        FuncCode("SENSe:VOLTage:DC:NPLCycles", "积分时间", "0.02~100 PLC（34461A 上限）"),
        FuncCode("TRIGger:SOURce", "触发源", "BUS/IMMediate/EXTernal/INTernal"),
        FuncCode("DISPlay:TEXT[:DATA]", "仪器显示文本", "最多 32 字符，可清除"),
        FuncCode("SYSTem:ERRor?", "错误队列查询", "逐条读出直至 0,\"No error\""),
        FuncCode("*RST", "复位", "恢复出厂默认状态"),
    ],
    registers=[],
    frames=[
        FrameExample("标识查询", "*IDN?",
                     "KEYSIGHT TECHNOLOGIES,34465A,MY12345678,1.2.3-1.0.3"),
        FrameExample("测直流电压", "MEASure:VOLTage:DC?", "+1.23456789E+00"),
        FrameExample("设积分时间", "SENSe:VOLTage:DC:NPLCycles 5.000", "（无应答，靠回读确认）"),
        FrameExample("读错误队列", "SYSTem:ERRor?", "-105,\"Parameter out of range\""),
    ],
    errors=[
        ErrorCode("-100", "命令语法错误", "检查命令拼写"),
        ErrorCode("-105", "参数越界", "量程/范围非法（如 NPLC 超上限）"),
        ErrorCode("-110", "数据溢出", "检查数值格式与单位"),
        ErrorCode("-221", "设置冲突", "与当前功能/状态不兼容"),
        ErrorCode("0,\"No error\"", "无错误", "队列已读空"),
    ],
    notes=[
        "12 种测量功能：直流/交流电压电流、2线/4线电阻、电容、频率、周期、温度、通断、二极管。",
        "命令表 44 条为单一事实源（key/SCPI/单位/范围/读写权限），界面控件与回归测试同源派生。",
        "半包/粘包按 LF 行重组，错帧剔除杂散控制字符后重同步。",
        "查询超时重发上限 2 次后报错退出——从站掉线不卡死上位机。",
        "34465A/34470A 的 NPLC 上限可到 200，写入前按型号确认（不猜测）。",
    ],
)


# ---- Jartul JT632xA 电子负载（SCPI） ----
PROTO_DETAILS["jt6321a_host"] = _detail(
    "jt6321a_host",
    comm=[
        CommParam("通信口", "RS-232（隔离，须直连线）"),
        CommParam("通信协议", "SCPI（全 ASCII，帧尾 NL）"),
        CommParam("默认波特率", "9600（支持 2400~115200）"),
        CommParam("默认地址", "—（多点通讯需关闭）"),
        CommParam("默认IP/端口", "无"),
    ],
    func_codes=[
        FuncCode("MODE", "负载模式", "CC/CV/CP/CR/DYNA/LED"),
        FuncCode("INP", "输入开关", "ON/OFF（拉载，二次确认）"),
        FuncCode("CURR/VOLT/POW/RES", "拉载设定", "各模式设定值"),
        FuncCode("MEAS:VOLT?/CURR?/POW?/RES?", "测量回读", "V/I/P/R 平均值"),
        FuncCode("STAT:QUES:COND?", "状态字", "8 保护位"),
    ],
    registers=[],
    frames=[
        FrameExample("切恒流模式", "MODE CURR", "（无应答，靠回读确认）"),
        FrameExample("设拉载电流 5A", "CURR 5", "（无应答）"),
        FrameExample("读电流", "MEAS:CURR?", "5.000"),
        FrameExample("读状态字", "STAT:QUES:COND?", "0"),
    ],
    errors=[
        ErrorCode("VF", "电压故障", "检查电压输入"),
        ErrorCode("OC", "过电流保护", "减小拉载电流"),
        ErrorCode("OP", "过功率保护", "减小拉载功率"),
        ErrorCode("OT", "过热保护", "散热后重试"),
        ErrorCode("OV", "过电压保护", "降低输入电压"),
        ErrorCode("RRV/LRV", "极性反接", "检查远端/本地输入极性"),
    ],
    notes=[
        "查询命令带 ? 回一行，设置命令无应答靠回读确认。",
        "拉载/短路为高危动作，有二次确认。",
    ],
)


# ---- 华源交流回馈式负载（Modbus RTU，协议 V1.4） ----
PROTO_DETAILS["huayuan_acload_host"] = _detail(
    "huayuan_acload_host",
    comm=[
        CommParam("通信口", "RS-232 / RS-485 / 网口（RTU-over-TCP / Modbus TCP / UDP）"),
        CommParam("通信协议", "华源交流回馈式负载 MODBUS RTU V1.4（2024-10-30 手册）"),
        CommParam("默认波特率", "9600-8-N-1（8 数据位、无校验、1 停止位）"),
        CommParam("默认地址", "1（0 为广播）"),
        CommParam("默认IP/端口", "TCP 透传/模拟从站默认 127.0.0.1:7000，MBAP 不勾=裸 RTU 帧透传"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "状态块 0x60~0x80、通道明细 0x90~0xDD"),
        FuncCode("0x06", "写单寄存器", "输出控制/清故障/模式/手动调试"),
        FuncCode("0x10", "写多寄存器", "32 位设定与通道批量（单帧最多 123 个寄存器）"),
    ],
    registers=[
        Reg("0x20", "输出控制", "RW", "0 关闭 / 1 输出（开启须二次确认）"),
        Reg("0x28", "清除故障", "RW", "写 1 清除，完成后设备自动复位为 0"),
        Reg("0x38/0x39", "设置总功率", "RW", "u32，单位 0.1W（1000W 写 10000）"),
        Reg("0x3C", "操作模式", "RW", "0 三相统调 / 1 三相独立 / 2 单相并联"),
        Reg("0x3D", "控制模式", "RW", "0 功率模式 / 1 电流模式"),
        Reg("0x3E/0x3F", "设置总电流", "RW", "u32，单位 0.001A（5A 写 5000）"),
        Reg("0x40~0x5D", "通道 1~15 设定功率", "RW", "u32，通道 n=0x40+2(n-1)，单位 0.1W"),
        Reg("0xE0/0xE2/0xE4", "A/B/C 相设定电流", "RW", "u32，单位 0.001A，仅三相通道有效"),
        Reg("0x60/0x62", "输出状态低/高字", "RO", "合成 32 位：bit0 运行、bit16 故障、"
                                                  "bit17 控制模式、bit19:18 操作模式"),
        Reg("0x61", "版本号", "RO", "104 → V1.4"),
        Reg("0x63~0x6E", "A/B/C 相输出电压/电流", "RO", "u32，单位 0.001"),
        Reg("0x7C", "输出总功率", "RO", "u32，单位 0.1W"),
        Reg("0x7E/0x7F/0x80", "故障状态 1/2/3", "RO", "bit47~32 / bit31~16 / bit15~0"),
        Reg("0x86", "序列号", "RO", "u32，高位在前"),
        Reg("0x90~0xDD", "4~15 通道输出 V/I/P", "RO", "u32，0.001 / 0.001 / 0.1"),
    ],
    frames=[
        FrameExample("读版本号", "01 03 00 61 00 01 [CRC]",
                     "01 03 02 00 68 [CRC] ← 104（V1.4）"),
        FrameExample("读状态块 0x60 起 33 个", "01 03 00 60 00 21 [CRC]",
                     "01 03 42 [33×2 字节数据] [CRC]"),
        FrameExample("写总功率 1000W", "01 10 00 38 00 02 04 00 00 27 10 [CRC]",
                     "01 10 00 38 00 02 [CRC]（10000=1000.0W）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "只用 0x03/0x06/0x10"),
        ErrorCode("0x02", "非法数据地址", "核对地址；差 1 时试高级设置「地址偏移 -1」"),
        ErrorCode("0x03", "非法数据值", "值超量程或单位错（功率 0.1W、电流电压 0.001）"),
    ],
    notes=[
        "手册两处印刷笔误已按地址连续性修正：10 通道电流为 0xAE（非 0xAC，0xAC 是 9 通道）；"
        "13/14/15 通道电流地址 0xD2/0xD4/0xD6 的通道名整体错位一格。",
        "参数下发顺序必须：关闭输出 → 操作模式 → 控制模式 → 总功率/总电流 → 各通道设定 → 开启输出；"
        "顺序错设备可能拒写或写入不生效（「一键下发」已内置该顺序）。",
        "所有寄存器按无符号整数读取，32 位量占 2 个寄存器、默认高位字在前（高级设置可切字序）。",
        "模块持续约 10s 未收到监控命令会报通讯中断并关机；通讯恢复后按中断前状态自动开机。",
        "手册只定义故障 bit0~bit7（电流过流/IGBT 过流/母线过压/波形数据错误/功率过载/输出过流/"
        "过温保护/超过额定电压），其余位预留。",
    ],
)


# ---- 新胜负载箱（Modbus RTU） ----
PROTO_DETAILS["xinsheng_load_host"] = _detail(
    "xinsheng_load_host",
    comm=[
        CommParam("通信口", "RS-485 串口 / 网口（RTU-over-TCP，串口服务器/透传模块）"),
        CommParam("通信协议", "Modbus RTU（CRC 低字节在前），FC03 读 / FC06 写"),
        CommParam("默认波特率", "9600-8-N-1（1 起始/8 数据/1 停止，无校验）"),
        CommParam("默认地址", "1（有效 1~247）"),
        CommParam("默认IP/端口", "RTU over TCP 为裸 RTU 帧（无 MBAP 头），端口按透传模块配置"),
    ],
    func_codes=[
        FuncCode("0x03", "读保持寄存器", "只读量与回读（状态/档位/延时）"),
        FuncCode("0x06", "写单寄存器", "全部写入（手册未给 FC10/05/16 示例，一律单点写）"),
    ],
    registers=[
        Reg("1", "风机开关", "RW", "1=开 0=关；写后按状态寄存器 2 确认（1 回显≠已切到位）"),
        Reg("2", "风机状态指示灯", "RO", "0=关 1=开（风机确认的判据）"),
        Reg("3", "高温报警", "RO", "0=正常 1=报警"),
        Reg("5", "急停开关", "RW", "★1=正常 0=急停（语义反直觉）"),
        Reg("10", "风机延时开启设定", "RW", "0~32765（秒）"),
        Reg("20", "风机延时关闭设定", "RW", "0~32765（秒）"),
        Reg("35/36/37", "A/B/C 相卸载", "W", "上升沿触发，写 1，不回读；35 兼同步卸载"),
        Reg("38", "一键卸载(复位)", "W", "上升沿触发，写 1，不回读"),
        Reg("51/53/55", "A/B/C 相输入功率档", "RW", "★10 倍输入（10Ω 写 100）；0~65535"),
        Reg("50/52/54", "功率档·手册示例地址", "RW", "与寄存器表差 1 的歧义方案（0x32H），可切换"),
        Reg("200", "同步/独立切换", "RW", "0=独立 1=同步（同步模式下 A 相即三相）"),
    ],
    frames=[
        FrameExample("读风机状态（手册示例）", "01 03 00 02 00 01 25 CA",
                     "01 03 02 00 01 79 84 ← 风机开"),
        FrameExample("写功率档（手册示例 0x32H=50）", "01 06 00 32 00 64 29 EE",
                     "（原样回显；本软件默认按表地址 51=0x33H 发 01 06 00 33 00 64）"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能", "只用 0x03/0x06"),
        ErrorCode("0x02", "非法地址", "核对寄存器号（地址无偏移）；功率档可切 50/52/54 试"),
        ErrorCode("0x03", "非法数据值", "值超量程（延时 0~32765、功率档 0~65535）"),
        ErrorCode("0x04", "设备故障", "设备内部故障"),
    ],
    notes=[
        "★急停寄存器（地址 5）语义反直觉：1=正常、0=急停；界面对应「急停（写0）/解除急停（写1）」，"
        "解除急停属保护复位类，二次确认后下发。",
        "★功率档地址歧义：手册示例帧写 0x32H(=50) 与寄存器表 51 不一致，两帧 CRC 均自洽无法裁决；"
        "默认按寄存器表 51/53/55，现场「加载写入」无响应或无效时在高级设置切换「手册示例 50/52/54」。",
        "风机开关写后必须按状态寄存器 2 循环确认（输出回路切换有延时，寄存器 1 回显≠已切到位）；"
        "功率档/急停等同理写后回读确认，未确认如实上报，由轮询兜底。",
        "功率档为 10 倍输入：加载 10Ω 时协议输入 100；同步模式（200=1）下 A 相功率档即三相统一档。",
        "卸载为上升沿触发量（35~38 写 1），按手册不回读；轮询项某地址无响应时自动跳过并提示一次。",
    ],
)


# ---- IT8500 系列电子负载（FRAME 帧协议） ----
PROTO_DETAILS["it8500_host"] = _detail(
    "it8500_host",
    comm=[
        CommParam("通信口", "RS-232（须直连线，经 IT-E121 转接）"),
        CommParam("通信协议", "IT8500 FRAME 帧协议（SCPI 模式不可用）"),
        CommParam("默认波特率", "9600（可选 4800/19200/38400）"),
        CommParam("默认地址", "0~31"),
        CommParam("默认IP/端口", "无"),
    ],
    func_codes=[
        FuncCode("0x21", "输入开关", "0 OFF / 1 ON（拉载）"),
        FuncCode("0x28/0x29", "负载模式", "0CC 1CV 2CW 3CR"),
        FuncCode("0x2A~0x31", "CC/CV/CW/CR 设定", "各模式拉载设定"),
        FuncCode("0x5F", "测量", "回 V/I/P + 操作/查询状态寄存器"),
        FuncCode("0x6A", "设备信息", "型号/序列号/版本"),
    ],
    registers=[
        Reg("命令 0x20", "控制模式", "WO", "0 面板 / 1 远程"),
        Reg("命令 0x21", "输入开关", "RW", "0 OFF / 1 ON"),
        Reg("命令 0x22~0x27", "OVP/OCP/OPP", "RW", "过压/过流/过功率保护"),
        Reg("命令 0x2A~0x31", "CC/CV/CW/CR", "RW", "拉载设定值"),
        Reg("命令 0x32~0x39", "动态参数", "RW", "DYN CC/CV/CW/CR"),
        Reg("命令 0x3A~0x4D", "LIST 列表", "RW", "步进/循环/文件"),
    ],
    frames=[
        FrameExample("远程模式+开输入", "AA 01 20 ... 01 [校验]", "AA 01 12 80 ... [校验]"),
        FrameExample("测 量", "AA 01 5F [22 字节] [校验]", "AA 01 5F [V][I][P][状态] [校验]"),
    ],
    errors=[
        ErrorCode("0x80", "执行成功", "正常应答"),
        ErrorCode("0x90", "校验和错误", "检查帧校验"),
        ErrorCode("0xA0", "参数错误/溢出", "检查设定值范围"),
        ErrorCode("0xB0", "命令不能执行", "需先 0x20 进入远程模式"),
        ErrorCode("0xC0", "命令无效", "检查命令字"),
    ],
    notes=[
        "帧长固定 26 字节：[AA][地址][命令字][22 字节数据][校验]，校验=前 25 字节累加和低 8 位。",
        "多字节数据一律低字节在前；电压 1=1mV、电流 1=0.1mA、功率 1=1mW、电阻 1=1mΩ。",
        "拉载为高危动作，有二次确认，退出自动卸载。",
    ],
)


# ---- GPP 可编程直流电源（SCPI） ----
PROTO_DETAILS["gpp_host"] = _detail(
    "gpp_host",
    comm=[
        CommParam("通信口", "RS-232 / USB / LAN"),
        CommParam("通信协议", "SCPI"),
        CommParam("默认波特率", "115200（串口）"),
        CommParam("默认地址", "—"),
        CommParam("默认IP/端口", "LAN 走 TCP"),
    ],
    func_codes=[
        FuncCode("*IDN?", "标识查询", "返回制造商/型号/序列号"),
        FuncCode(":SOURce{n}:VOLTage", "电压设定", "CH1~CHn 设定"),
        FuncCode(":SOURce{n}:CURRent", "电流设定", "CH1~CHn 设定"),
        FuncCode(":OUTPut{n}", "输出开关", "ON/OFF（二次确认）"),
        FuncCode(":MEASure{n}:ALL?", "测量回读", "电压/电流/功率"),
        FuncCode(":OUTPut{n}:OVP/OCP", "保护设定", "过压/过流"),
    ],
    registers=[],
    frames=[
        FrameExample("设 CH1 电压", ":SOURce1:VOLTage 12.0000", "（无应答）"),
        FrameExample("CH1 输出开", ":OUTPut1 ON", "（无应答）"),
        FrameExample("读 CH1 测量", ":MEASure1:ALL?", "12.000,1.500,18.000"),
    ],
    errors=[
        ErrorCode("-113", "未定义头", "检查命令拼写"),
        ErrorCode("-222", "数据越界", "参数超出量程"),
        ErrorCode("0x00", "SYST:ERR? 无错", "正常"),
    ],
    notes=[
        "多通道 CH1~CHn，支持串并联跟踪（:OUTPut:SERies/PARallel）。",
        "开启输出为高危动作，有二次确认。",
    ],
)


# ---- FLUKE 8808A 万用表（ASCII 命令集） ----
PROTO_DETAILS["fluke8808a_host"] = _detail(
    "fluke8808a_host",
    comm=[
        CommParam("通信口", "RS-232"),
        CommParam("通信协议", "FLUKE 8808A ASCII 命令集（非 SCPI）"),
        CommParam("默认波特率", "9600（面板可选 300~19200）"),
        CommParam("默认地址", "—"),
        CommParam("默认IP/端口", "无"),
    ],
    func_codes=[
        FuncCode("*IDN?", "标识查询", "返回制造商/型号/序列号/版本"),
        FuncCode("VDC/VAC/ADC/AAC/OHMS/FREQ", "功能切换", "主屏功能选择"),
        FuncCode("MEAS1?/VAL1?", "读数", "触发并读主屏"),
        FuncCode("RANGE", "量程设置", "自动/手动量程"),
        FuncCode("RATE", "速率设置", "S/M/F"),
    ],
    registers=[],
    frames=[
        FrameExample("标识查询", "*IDN?", "FLUKE,8808A,..."),
        FrameExample("测直流电压", "MEAS1?", "+1.2345E+0"),
        FrameExample("设量程", "RANGE 4", "（无应答，提示符 => 收尾）"),
    ],
    errors=[
        ErrorCode("=>", "无错误提示符", "可发下一条"),
        ErrorCode("?>", "命令错误", "命令解析失败"),
        ErrorCode("!>", "执行错误", "设备相关错误"),
        ErrorCode("1.0E9", "过载", "量程过小或开路"),
    ],
    notes=[
        "查询命令带 ? 与 SET 命令成对；助记符 MAX/MIN 待厂家确认。",
        "回显开启时逐字符回显并返回提示符，同步策略据此设计。",
    ],
)


# ---- GW Instek GDM-9060/9061 万用表（SCPI） ----
PROTO_DETAILS["gdm906x_host"] = _detail(
    "gdm906x_host",
    comm=[
        CommParam("通信口", "RS-232 / USB-CDC / LAN"),
        CommParam("通信协议", "SCPI"),
        CommParam("默认波特率", "115200-8-N-1（串口）"),
        CommParam("默认地址", "—"),
        CommParam("默认IP/端口", "SCPI 走 TCP 3001，Telnet 3000"),
    ],
    func_codes=[
        FuncCode("*IDN?", "标识查询", "返回制造商/型号/序列号"),
        FuncCode("CONFigure:...", "功能配置", "DCV/ACV/DCI/ACI/RES/FREQ/CAP/TEMP 等 12 种"),
        FuncCode("READ?", "触发测量", "返回值"),
        FuncCode("DATA:LAST?", "查最近值", "返回 \"值 单位\""),
        FuncCode("SENS:...:NPLC", "积分时间", "0.006~12 PLC"),
    ],
    registers=[],
    frames=[
        FrameExample("配直流电压", "CONF:VOLT:DC", "（无应答）"),
        FrameExample("触发测量", "READ?", "1.2345"),
        FrameExample("查最近值", "DATA:LAST?", "1.2345 V"),
    ],
    errors=[
        ErrorCode("+9.9E37", "无数据哨兵", "超量程/开路/未完成，非通信故障"),
        ErrorCode("-113", "未定义头", "检查命令拼写"),
        ErrorCode("-222", "数据越界", "参数超范围"),
    ],
    notes=[
        "指令长/短格式均可（CONFigure:VOLTage:DC == CONF:VOLT:DC）。",
        "自动量程时禁止附带分辨率参数。",
    ],
)


# ---- GW INSTEK MFG-2000 信号源（SCPI） ----
PROTO_DETAILS["mfg2000_host"] = _detail(
    "mfg2000_host",
    comm=[
        CommParam("通信口", "RS-232 / USB / LAN"),
        CommParam("通信协议", "SCPI 1994 / IEEE 488.2-1992"),
        CommParam("默认波特率", "115200（串口）"),
        CommParam("默认地址", "—"),
        CommParam("默认IP/端口", "LAN 走 TCP"),
    ],
    func_codes=[
        FuncCode("*IDN?", "标识查询", "返回制造商/型号"),
        FuncCode(":SOURce1:FUNCtion", "波形选择", "SIN/SQU/RAMP/ARB"),
        FuncCode(":SOURce1:FREQuency", "频率设置", "Hz"),
        FuncCode(":SOURce1:AMPLitude", "幅值设置", "Vpp"),
        FuncCode(":SOURce1:MOD", "调制", "AM/FM/PM"),
        FuncCode(":SOURce1:SWEep", "扫描", "频率扫描"),
    ],
    registers=[],
    frames=[
        FrameExample("设波形", ":SOURce1:FUNCtion SIN", "（无应答）"),
        FrameExample("设频率 1kHz", ":SOURce1:FREQuency 1000", "（无应答）"),
        FrameExample("读错误队列", ":SYSTem:ERRor?", "0,\"No error\""),
    ],
    errors=[
        ErrorCode("-113", "未定义头", "检查命令拼写"),
        ErrorCode("-222", "数据越界", "参数超范围"),
        ErrorCode("0", "无错误", "正常"),
    ],
    notes=[
        "命令表驱动（49 命令 8 组），参数校验/SCPI 生成/回读解析由命令表派生。",
        "双系列可选 MFG-2000 / AFG-2000，SCPI 同源。",
    ],
)


# ---- 汇川 EASY300/EASY500 PLC（Modbus RTU/TCP） ----
PROTO_DETAILS["easy_plc_host"] = _detail(
    "easy_plc_host",
    comm=[
        CommParam("通信口", "RS-485 / 以太网"),
        CommParam("通信协议", "Modbus-RTU / Modbus-TCP"),
        CommParam("默认波特率", "EASY300=9600、EASY500=19200"),
        CommParam("默认地址", "1"),
        CommParam("默认IP/端口", "TCP 默认 502"),
    ],
    func_codes=[
        FuncCode("0x01", "读线圈", "读 X/Y/M 位状态"),
        FuncCode("0x02", "读离散输入", "读 X 输入状态"),
        FuncCode("0x03", "读保持寄存器", "读 D 数据寄存器"),
        FuncCode("0x05", "写单线圈", "强制 Y/M 输出"),
        FuncCode("0x06", "写单寄存器", "写 D 数据"),
        FuncCode("0x0F/0x10", "写多线圈/寄存器", "批量写"),
    ],
    registers=[
        Reg("0xF800", "X 输入", "RO", "八进制编号，X0~X77"),
        Reg("0xFC00", "Y 输出", "RW", "八进制编号，Y0~Y77"),
        Reg("0x0000", "M 辅助继电器", "RW", "十进制编号"),
        Reg("0x0000", "D 数据寄存器", "RW", "十进制编号，03/06/10 访问"),
    ],
    frames=[
        FrameExample("读 X0~X7 状态", "01 02 F8 00 00 08 [CRC]",
                     "01 02 01 [位字节] [CRC]"),
        FrameExample("强制 Y0 输出", "01 05 FC 00 FF 00 [CRC]",
                     "01 05 FC 00 FF 00 [CRC]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认功能码"),
        ErrorCode("0x02", "非法数据地址", "核对软元件基址"),
        ErrorCode("0x03", "非法数据值", "数据超范围"),
    ],
    notes=[
        "X/Y 八进制编号，M/D 十进制编号；也可用 RAW 原始地址模式。",
        "强制 Y 输出为高危动作，带回读校验。",
    ],
)


# ---- 信捷 XD/XL 系列 PLC（Modbus RTU/TCP） ----
PROTO_DETAILS["xinje_plc_host"] = _detail(
    "xinje_plc_host",
    comm=[
        CommParam("通信口", "RS-485 / 以太网"),
        CommParam("通信协议", "Modbus-RTU / Modbus-TCP"),
        CommParam("默认波特率", "9600（RS-485）"),
        CommParam("默认地址", "1"),
        CommParam("默认IP/端口", "TCP 默认 502"),
    ],
    func_codes=[
        FuncCode("0x01", "读线圈", "读 X/Y/M/S/T/C 位"),
        FuncCode("0x02", "读离散输入", "读输入位"),
        FuncCode("0x03", "读保持寄存器", "读 D/HD/SD/TD 等字"),
        FuncCode("0x04", "读输入寄存器", "读 ID"),
        FuncCode("0x05", "写单线圈", "强制 Y/M 输出"),
        FuncCode("0x06/0x10", "写寄存器", "写 D/HD 等"),
    ],
    registers=[
        Reg("0x5000", "X 输入", "RO", "八进制，X0~X77"),
        Reg("0x6000", "Y 输出", "RW", "八进制，Y10=0x6008"),
        Reg("0x7000", "S 状态", "RW", "S0~"),
        Reg("0xA080", "HD 保持寄存器", "RW", "HD0=0xA080"),
        Reg("0x0000", "D 数据寄存器", "RW", "D0~"),
        Reg("0x9000", "SM 特殊继电器", "RW", "SM0~"),
    ],
    frames=[
        FrameExample("读 Y10 状态", "01 01 60 08 00 01 [CRC]",
                     "01 01 01 [位] [CRC]"),
        FrameExample("强制 Y10 输出", "01 05 60 08 FF 00 [CRC]",
                     "01 05 60 08 FF 00 [CRC]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认功能码"),
        ErrorCode("0x02", "非法数据地址", "核对软元件基址"),
        ErrorCode("0x03", "非法数据值", "数据超范围"),
    ],
    notes=[
        "X/Y 八进制编号（Y10=0x6008），HD 基址 0xA080，软元件映射见 devices.py。",
        "强制输出带回读校验，不一致自动持续强制。",
    ],
)


# ---- 艾诺 AN9637HC 安规综合分析仪（SE 协议） ----
PROTO_DETAILS["an96hc"] = _detail(
    "an96hc",
    comm=[
        CommParam("通信口", "RS-232 / RS-485"),
        CommParam("通信协议", "SE 报文 / Ainuo ASCII / SCPI（三方言可切）"),
        CommParam("默认波特率", "9600（0~3 对应 9600~57600）"),
        CommParam("默认地址", "—"),
        CommParam("默认IP/端口", "无"),
    ],
    func_codes=[
        FuncCode("SAA/SAD/SAI/SAG", "追加测试步", "ACW/DCW/IR/GND"),
        FuncCode("EV/EH/EL/ERU/ERD/EDW", "测试参数", "电压/电流上限/下限/缓升/缓降/时间"),
        FuncCode("TEST", "启动测试", "跑整个档案"),
        FuncCode("TD?/RD nn?", "查结果", "读测试结果"),
    ],
    registers=[
        Reg("EV", "测试电压", "RW", "ACW 100~5000V / DCW 100~6000V"),
        Reg("EH/EHT", "电流上限", "RW", "mA/uA 按模式"),
        Reg("EL/ELT", "电流下限", "RW", "mA/uA"),
        Reg("EDW", "测试时间", "RW", "0 或 0.5~999.9s"),
        Reg("EA", "电弧灵敏度", "RW", "0~9"),
        Reg("EF", "输出频率", "RW", "50/60 Hz"),
    ],
    frames=[
        FrameExample("建档案", "FN 1,test", "ACK(0x06)+LF"),
        FrameExample("设 ACW 电压 1000V", "EV 1000", "ACK(0x06)+LF"),
        FrameExample("启动测试", "TEST", "ACK(0x06)+LF"),
        FrameExample("查结果", "TD?", "数据字符串+LF"),
    ],
    errors=[
        ErrorCode("ACK(0x06)", "正确无需回传", "命令已接受"),
        ErrorCode("NAK(0x15)", "错误", "命令被拒，检查参数"),
        ErrorCode("DATA", "正确需回传", "返回数据字符串"),
    ],
    notes=[
        "启动耐压为高危动作，有二次确认。",
        "指令结束码手册存在 LF 与 CRLF 出入，可在 Transport 层切换。",
    ],
)


# ---- 联明 CAN 充电模块（CAN 2.0B · UT-6502） ----
PROTO_DETAILS["lm_can"] = _detail(
    "lm_can",
    comm=[
        CommParam("通信口", "CAN 2.0B 29 位扩展帧（经 UT-6502 以太网-CAN 转换器）"),
        CommParam("通信协议", "联明电源数字电源模块 CAN 协议 V1.0"),
        CommParam("默认波特率", "CAN 125 kbps"),
        CommParam("默认地址", "1~60（ID 低 7 位）"),
        CommParam("默认IP/端口", "UT-6502 默认 TCP 5001"),
    ],
    func_codes=[
        FuncCode("CMD 0", "设输出", "设电压/电流（电压 4 字节 mV，电流 3 字节 mA）"),
        FuncCode("CMD 1", "读状态", "读输出电压/电流/故障状态"),
        FuncCode("CMD 2", "开关电源", "0x55 开 / 0xAA 关"),
        FuncCode("CMD 3", "读设定电压", "回读设定电压"),
        FuncCode("CMD 4", "读设定电流", "回读设定电流"),
        FuncCode("CMD 5", "读输入电压", "回读三相输入电压"),
        FuncCode("CMD 6", "读温度", "回读模块温度"),
    ],
    registers=[
        Reg("0x1907C080", "设输出/读状态/开关机 ID", "RW", "低 7 位=模块地址"),
        Reg("0x19010080", "读设定电压 ID", "RO", "读设定电压"),
        Reg("0x19010880", "读设定电流 ID", "RO", "读设定电流"),
        Reg("0x1907A080", "读输入电压 ID", "RO", "读三相输入电压"),
        Reg("0x19008080", "读温度 ID", "RO", "读模块温度"),
        Reg("0x19C21880", "均流 ID", "RW", "0xAA 使能 / 0x55 禁止"),
        Reg("0x19C22880", "找模块 ID", "WO", "广播发现模块"),
    ],
    frames=[
        FrameExample("读状态 (问模块1)",
                     "ID  0x1907C001\nDATA 01 00 00 00 00 00 00 00",
                     "ID  0x1807C001\nDATA 00 00 [电流] [电压] [状态高] [状态低]"),
        FrameExample("设输出 500V/15A (模块1)",
                     "ID  0x1907C001\nDATA 00 [电流3字节] [电压4字节]",
                     "（状态帧 0x1807C0xx 回读确认）"),
        FrameExample("开电源 (模块1)",
                     "ID  0x1907C001\nDATA 02 00 00 00 00 00 00 55",
                     "（状态帧回读，bit0 清表示已开）"),
        FrameExample("读温度 (问模块1)",
                     "ID  0x19008001\nDATA [空]",
                     "ID  0x18008001\nDATA 00 00 00 00 [温度高] [温度低]"),
    ],
    errors=[
        ErrorCode("状态字 bit0", "输出关闭", "检查开关电源命令"),
        ErrorCode("状态字 bit1", "模块故障", "检查模块"),
        ErrorCode("状态字 bit2", "风扇故障", "检查散热"),
        ErrorCode("状态字 bit4/5", "输入过/欠压", "检查输入电源"),
        ErrorCode("状态字 bit6/7", "输出过/欠压", "检查负载"),
    ],
    notes=[
        "CAN 2.0B 扩展帧，波特率 125kbps；UT-6502 链路层每帧 13 字节（1 帧信息 + 4 字节 ID 大端 + 8 字节数据）。",
        "报文举例一律「ID + 8 字节数据」，低 7 位为模块地址（1~60）。",
        "电压 1=0.1V（mV 计）、电流 1=0.1A（mA 计）。",
    ],
)


# ---- 联明 485 充电模块（Modbus RTU） ----
# 协议：《联明标准 ModBus 通信协议 V02》。RS-485 总线，9600bps，8 数据位 1 停止位无校验。
# 数值高字节在前；功能码 0x03 读寄存器 / 0x05 写单线圈 / 0x06 写单寄存器；CRC16 校验（先高后低）。
PROTO_DETAILS["lm_485"] = _detail(
    "lm_485",
    comm=[
        CommParam("通信口", "RS-485（1 起始位 + 8 数据位 + 1 停止位，无校验）"),
        CommParam("通信协议", "联明标准 Modbus RTU V02"),
        CommParam("默认波特率", "9600 bps"),
        CommParam("默认地址", "0x01~0xF7（0x00 广播）"),
        CommParam("默认IP/端口", "无（串口）"),
    ],
    func_codes=[
        FuncCode("0x03", "读数据寄存器", "读状态/电压/电流/温度/地址"),
        FuncCode("0x05", "写单个线圈寄存器", "电源开关机（0xFF00 开机 / 0x0000 关机）"),
        FuncCode("0x06", "写单个数据寄存器", "写设定电压/模块地址/默认电压"),
    ],
    registers=[
        Reg("0x0001", "电源状态", "RO", "16 位状态位（见故障/状态定义）"),
        Reg("0x0002", "输出电压", "RO", "Uint16，实际值×100"),
        Reg("0x0003", "输出电流", "RO", "Uint16，实际值×100"),
        Reg("0x0004", "温度", "RO", "Uint16，实际值"),
        Reg("0x0005", "电源开关机", "WO", "0xFF00=开机，0x0000=关机（0x05 写线圈）"),
        Reg("0x0006", "设定输出电压", "WO", "Uint16，设定实际值×100"),
        Reg("0x0007", "模块地址", "RW", "Uint16，读/写从机地址"),
        Reg("0x0010", "默认输出电压", "WO", "Uint16，单位 0.01V"),
    ],
    frames=[
        FrameExample("读电源状态（0x0001）",
                     "01 03 00 01 00 01 D5 CA",
                     "01 03 02 [状态H] [状态L] [CRC_lo] [CRC_hi]"),
        FrameExample("读输出电压（0x0002）",
                     "01 03 00 02 00 01 25 CA",
                     "01 03 02 [V_H] [V_L] [CRC_lo] [CRC_hi]"),
        FrameExample("读输出电流（0x0003）",
                     "01 03 00 03 00 01 74 0A",
                     "01 03 02 [I_H] [I_L] [CRC_lo] [CRC_hi]"),
        FrameExample("读温度（0x0004）",
                     "01 03 00 04 00 01 C5 CB",
                     "01 03 02 [T_H] [T_L] [CRC_lo] [CRC_hi]"),
        FrameExample("电源开机（0x0005 写线圈 0xFF00）",
                     "01 05 00 05 FF 00 9C 3B",
                     "01 05 00 05 FF 00 9C 3B"),
        FrameExample("设输出电压（0x0006，如 50V=5000）",
                     "01 06 00 06 13 88 [CRC_lo] [CRC_hi]",
                     "01 06 00 06 13 88 [CRC_lo] [CRC_hi]"),
    ],
    errors=[
        ErrorCode("0x01", "非法功能码", "确认功能码为 03/05/06"),
        ErrorCode("0x02", "非法数据地址", "核对寄存器地址"),
        ErrorCode("0x03", "非法数据值", "数据超范围"),
        ErrorCode("Bit0", "电源开关机状态", "1=开机 0=关机"),
        ErrorCode("Bit1/Bit2", "输出/输入正常", "1=正常 0=异常"),
        ErrorCode("Bit3/Bit4", "风扇 1/2 异常", "1=异常 0=正常"),
        ErrorCode("Bit5/Bit6", "输出过流/过压", "1=异常 0=正常"),
        ErrorCode("Bit7/Bit8", "前级故障 / EEP 故障", "1=异常 0=正常"),
        ErrorCode("Bit9", "过温故障", "1=异常 0=正常"),
    ],
    notes=[
        "输出电压/电流 = 寄存器值 / 100；温度 = 寄存器值（直接）。",
        "Modbus 异常响应：功能码 = 请求功能码 + 0x80，后接异常码。",
        "地址 0 为广播地址；所有数值高字节在前、低字节在后。",
    ],
)


# ---- 英飞源 REG 模块（REG · CAN 2.0B 扩展帧） ----
# 协议：充电模块 CAN 通讯协议 V1.09（2024-05-10）。CAN 2.0B 扩展帧，波特率 125kbps。
# ID 位域（29 位）：错误码(3bit) + 设备号(4bit，0x0A 监控↔单模块/0x0B 监控↔整组) + 命令号(6bit) + 目的地址(8bit) + 源地址(8bit)。
# 监控地址 0xF0~0xF8 默认 0xF0；模块 0x00~0x3B、MPPT 0x80~0xDF、0x3F 广播。
# 数据 8 字节先传高位；浮点 IEEE754 大端，定点数电压 mV/电流 mA。
PROTO_DETAILS["infy"] = _detail(
    "infy",
    comm=[
        CommParam("通信口", "CAN 2.0B 29 位扩展标识符"),
        CommParam("通信协议", "英飞源充电模块 CAN 通讯协议 V1.09"),
        CommParam("默认波特率", "CAN 125 kbps（终端电阻 120Ω，发帧间隔 50~200ms）"),
        CommParam("默认地址", "监控 0xF0~0xF8(默认 0xF0)；模块 0x00~0x3B、MPPT 0x80~0xDF、0x3F 广播"),
        CommParam("默认IP/端口", "以太网-CAN / UT-6502（TCP 5001）或 ZLG USB-CAN"),
    ],
    func_codes=[
        FuncCode("0x01", "读系统电压/总电流", "浮点，设备号 0x0A 回源地址 0x3F，0x0B 回组号"),
        FuncCode("0x02", "读模块数", "回模块数量"),
        FuncCode("0x03", "读模块 N 电压/电流", "浮点，N 体现在 ID 目标地址；定点格式用 0x09"),
        FuncCode("0x04", "读模块 N 状态", "回组号/状态表3/环温/状态表2/状态表1/状态表0"),
        FuncCode("0x06", "读模块 N 输入电压", "VAB/VBC/VCA，单位 0.1V"),
        FuncCode("0x08", "读系统电压/电流（定点）", "电压 mV、电流 mA，定点数"),
        FuncCode("0x09", "读模块 N 电压/电流（定点）", "电压 mV、电流 mA，定点数"),
        FuncCode("0x0A", "读模块 N 限值", "最大/最小电压(V)、最大电流(0.1A)、额定功率(10W)"),
        FuncCode("0x0B", "读模块 N 条码", "条码 ACSII/HEX"),
        FuncCode("0x0C", "读外部电压/允许电流", "电压 0.1V、电流 0.1A"),
        FuncCode("0x13", "设 WALK-IN 软起", "1 使能 / 0 禁止"),
        FuncCode("0x16", "设模块组号", "组号从 1 开始，改分组 4s 后再发 0x1B"),
        FuncCode("0x19", "设模块休眠", "1 休眠 / 0 不休眠"),
        FuncCode("0x1A", "开关机", "1 关机 / 0 开机，广播命令"),
        FuncCode("0x1B", "设输出电压/总电流", "电压 mV、总电流 mA（均分给所有模块）"),
        FuncCode("0x1C", "设输出电压/电流", "电压 mV、电流 mA（单模块/组）"),
        FuncCode("0x1F", "设地址分配方式", "1 拨码 / 0 自动分配"),
    ],
    registers=[
        Reg("ID[28:26] 错误码", "错误码", "RO", "0x00 正常 / 0x02 命令号异常 / 0x03 数据异常 / 0x07 启动中"),
        Reg("ID[25:22] 设备号", "设备号", "-", "0x0A 监控↔单模块 / 0x0B 监控↔整组"),
        Reg("ID[21:16] 命令号", "命令号", "-", "6 位，见命令列表"),
        Reg("ID[15:8] 目的地址", "目的地址", "-", "模块 0x00~0x3B / MPPT 0x80~0xDF / 0x3F 广播"),
        Reg("ID[7:0] 源地址", "源地址", "-", "监控 0xF0~0xF8(默认 0xF0)"),
    ],
    frames=[
        FrameExample(
            "读系统电压/总电流（0x01）",
            "ID  0x02813FF0\nDATA 00 00 00 00 00 00 00 00",
            "ID  0x0281F03F\nDATA 43 FA 00 00 42 48 00 00  ← 500V / 50A",
        ),
        FrameExample(
            "读模块 0 电压/电流（0x03）",
            "ID  0x028300F0\nDATA 00 00 00 00 00 00 00 00",
            "ID  0x0283F000\nDATA 43 FA 00 00 40 60 00 00  ← 500V / 3.5A",
        ),
        FrameExample(
            "读模块 0 状态（0x04）",
            "ID  0x028400F0\nDATA 00 00 00 00 00 00 00 00",
            "ID  0x0284F000\nDATA 00 00 02 00 1B 00 40 00  ← 组2/27℃/walkin",
        ),
        FrameExample(
            "读模块 0 输入电压（0x06）",
            "ID  0x028600F0\nDATA 00 00 00 00 00 00 00 00",
            "ID  0x0286F000\nDATA 0F B4 0F A5 0F A0 00 00  ← 402/400.5/400V",
        ),
        FrameExample(
            "设所有模块电压/电流（0x1C，750V 15A）",
            "ID  0x029C3FF0\nDATA 00 0B 71 B0 00 00 3A 98",
            "（广播无回复）",
        ),
        FrameExample(
            "设所有模块关机（0x1A）",
            "ID  0x029A3FF0\nDATA 01 00 00 00 00 00 00 00",
            "（广播无回复）",
        ),
        FrameExample(
            "设 0# 模块开机（0x1A）",
            "ID  0x029A00F0\nDATA 00 00 00 00 00 00 00 00",
            "ID  0x029AF000\nDATA 00 00 00 00 00 00 00 00  ← 当前为开机",
        ),
    ],
    errors=[
        ErrorCode("0x00", "正常", "-"),
        ErrorCode("0x02", "命令号异常", "核对命令号"),
        ErrorCode("0x03", "数据信息异常", "数据超范围"),
        ErrorCode("0x07", "启动过程中", "模块启动中，稍后重试"),
        ErrorCode("状态表0 bit0", "输出短路", "检查输出侧"),
        ErrorCode("状态表0 bit1", "模块故障告警", "读 0x04 查详情"),
        ErrorCode("状态表1 bit3", "输入或母线异常", "检查输入电源/PFC 母线"),
        ErrorCode("状态表1 bit4", "模块休眠", "0x19 解除休眠"),
        ErrorCode("状态表2 bit0", "风道不畅", "清理风道"),
        ErrorCode("状态表3 bit1", "模块通信中断告警", "检查 CAN 接线，模块持续 10s 无命令会关机"),
    ],
    notes=[
        "模块持续约 10s 未收到监控命令会报通讯中断并关机；通讯恢复后按中断前状态自动开机。",
        "WALK-IN 软起默认使能（5s），出厂即开启；也可监控自己缓慢放开电流给定实现软起。",
        "超出模块电压/电流设置范围的值不被接收；系统有模块故障告警时，故障模块不参与均流。",
        "0x1B 为总电流（均分给所有模块），0x1C 为单模块/组电流，按需选用。",
        "0x1F 设拨码方式后需用 0x16 设组号、0x04 确认组号。以 0x0757F8XX 为帧头的报文为模块间通讯，监控可忽略。",
    ],
)


# ---- 永联 UXR100040 充电模块（NXR 系列 · CAN 2.0B · UT-6502） ----
# 协议：NXR 系列充电模块通信协议 VER1.48。CAN 2.0B 只走 29 位扩展帧，波特率 125kbps 可配。
# ID 位域（29 位）：PROTNO(bit28~20,默认0x060) + PTP(bit19,1点对点/0广播) + DST(bit18~11) + SRC(bit10~3) + Group(bit2~0)。
# 数据域 8 字节：设置帧 Byte0=0x03/读取帧 Byte0=0x10，Byte2~3=REG_H/L，Byte4~7=DATA；应答 Byte0=TYPE(0x41浮点/0x42整型) Byte1=ERR(0xF0正常)。
PROTO_DETAILS["yonglian"] = _detail(
    "yonglian",
    comm=[
        CommParam("通信口", "CAN 2.0B 29 位扩展帧（USB-CAN 或网口 CAN 转换器 UT-6502）"),
        CommParam("通信协议", "永联 NXR 系列充电模块通信协议 VER1.48"),
        CommParam("默认波特率", "CAN 125 kbps（可配 10k ~ 1000k）"),
        CommParam("默认地址", "模块 0x00~0x3F，监控 0xF0；0xFF 全局广播 / 0xFE 组内广播"),
        CommParam("默认IP/端口", "UT-6502 默认 TCP 192.168.1.125:5000"),
    ],
    func_codes=[
        FuncCode("0x10 读取帧", "读寄存器", "Byte0=0x10，Byte2~3=寄存器，应答 TYPE 0x41浮点/0x42整型"),
        FuncCode("0x03 设置帧", "写寄存器", "Byte0=0x03，Byte2~3=寄存器，Byte4~7=数据"),
        FuncCode("0x41/0x42 应答", "应答帧", "TYPE 0x41=IEEE754 浮点 / 0x42=4 字节整型；ERR 0xF0=成功"),
    ],
    registers=[
        Reg("0x0001", "模块输出电压", "RO", "浮点 V，实际输出"),
        Reg("0x0002", "模块输出电流", "RO", "浮点 A，实际输出"),
        Reg("0x0003", "模块限流点", "RO", "浮点 0~1，读回乘 100 显示百分比"),
        Reg("0x0004", "DC 板温度", "RO", "浮点 ℃"),
        Reg("0x000C/0D/0E", "交流 A/B/C 相电压", "RO", "浮点 V"),
        Reg("0x0012", "额定输出电流", "RO", "浮点 A，设电流前先读此值算百分比"),
        Reg("0x0040", "告警/状态字", "RO", "整型 32 位，见故障位定义"),
        Reg("0x0043", "拨码地址", "RO", "整型，硬件拨码决定，用于扫描探活"),
        Reg("0x001B", "设输出电流", "WO", "整型 = 电流(A)×1024，例 10A→10240"),
        Reg("0x0020", "设输出功率", "WO", "浮点 0.1~1.0，相对额定功率比例"),
        Reg("0x0021", "设输出电压", "WO", "浮点 V"),
        Reg("0x0022", "设限流点", "WO", "浮点 0~1.0，相对额定电流百分比"),
        Reg("0x0030", "开关机", "WO", "整型 0x00000000 开机 / 0x00010000 关机"),
        Reg("0x001E", "设组号", "WO", "整型 0~7，有效值在 Byte7 低 3 位"),
        Reg("0x001F", "设地址分配方式", "WO", "整型 0x00000000 自动 / 0x00010000 拨码(默认)"),
        Reg("0x0046", "设输入模式", "WO", "整型 1 交流/2 直流，设置后需断电重启生效"),
    ],
    frames=[
        FrameExample(
            "读模块电压（问 1 号模块）",
            "ID  0x06080F80\nDATA 10 00 00 01 00 00 00 00",
            "ID  0x060F8008\nDATA 41 F0 00 01 44 2F 00 00  ← 700.0V",
        ),
        FrameExample(
            "读告警状态（0x0040）",
            "ID  0x06080F80\nDATA 10 00 00 40 00 00 00 00",
            "ID  0x060F8008\nDATA 42 F0 00 40 00 00 01 00  ← bit8 PFC 电压异常",
        ),
        FrameExample(
            "设输出电压 700V（0x0021）",
            "ID  0x06080F80\nDATA 03 00 00 21 44 2F 00 00",
            "ID  0x060F8008\nDATA 42 F0 00 21 00 00 00 00  ← ERR 0xF0 成功",
        ),
        FrameExample(
            "设输出电流 10A（0x001B）",
            "ID  0x06080F80\nDATA 03 00 00 1B 00 00 28 00",
            "ID  0x060F8008\nDATA 42 F0 00 1B 00 00 28 00  ← 10240=10A×1024",
        ),
        FrameExample(
            "关机（0x0030）",
            "ID  0x06080F80\nDATA 03 00 00 30 00 01 00 00",
            "ID  0x060F8008\nDATA 42 F0 00 30 00 01 00 00  ← 0x00010000 关机",
        ),
        FrameExample(
            "设置失败（自动分配模式下改组号）",
            "ID  0x06080F80\nDATA 03 00 00 1E 00 00 00 05",
            "ID  0x060F8008\nDATA 42 F2 00 1E 00 00 00 00  ← ERR 0xF2 失败",
        ),
    ],
    errors=[
        ErrorCode("0xF0", "应答正常", "ERR=0xF0 表示设置成功/读回有效"),
        ErrorCode("0xF2", "设置失败", "如自动分配模式下写组号，需先切拨码方式"),
        ErrorCode("状态字 bit0", "模块故障（红灯）", "检查模块"),
        ErrorCode("状态字 bit7", "DCDC 过压", "检查负载/输出"),
        ErrorCode("状态字 bit8", "PFC 电压异常", "不平衡/过压/欠压"),
        ErrorCode("状态字 bit16", "CAN 通信故障", "检查 CAN 接线与终端电阻"),
        ErrorCode("状态字 bit27", "风扇故障", "检查散热风扇"),
        ErrorCode("状态字 bit30", "DCDC 过温", "检查散热/降载"),
        ErrorCode("状态字 bit31", "DCDC 输出过压", "检查输出侧"),
    ],
    notes=[
        "0x003E（输出过压保护关联）语义与其它寄存器相反：0x00000000=允许、0x00010000=禁止。",
        "0x0046 设输入模式后必须断电重启模块才生效；0x0023（输出过压点）无特殊需求不要设置。",
        "拨码地址 0x0043 只读，不能远程分配；可远程设置的只有组号 0x001E 和地址分配方式 0x001F。",
        "网口 CAN 转换器 13 字节固定格式帧：Byte0=帧信息(bit7=扩展帧，DLC=8 即 0x88)，Byte1~4=ID，Byte5~12=数据。",
        "广播命令只下发不等待应答；广播不能用于读取。应答匹配键为 (SRCADDR, REG)。",
    ],
)


# ---- 优优绿能双向模块（CAN 2.0B 扩展帧） ----
# 协议：《双向模块与监控单元 CAN 通讯开发指导书》V41(2024-10-30)。CAN 2.0B 扩展帧 29 位 ID，
# 波特率 125kbps，所有电压单位 mV、电流单位 mA。
# ID 域：Protocol(4b 0x01) + MonitorAddress(4b) + ModuleAddress(7b) + ProductionDay(5b) + SerialNumberLowPart(9b)。
# 数据域 8 字节：Byte0=组地址(高4b 0x01~0x0F/0x00广播)+信息类型(低4b 0x00设置/0x01设置应答/0x02读/0x03读应答/0x04读序列号应答)；
#   Byte1=命令类型，Byte2~3=CommandSup，Byte4~7=CommandData(4字节整数)。
PROTO_DETAILS["youyou"] = _detail(
    "youyou",
    comm=[
        CommParam("通信口", "CAN 2.0B 扩展帧 29 位 ID（经 UT-6502 透传）"),
        CommParam("通信协议", "优优绿能双向模块 CAN 通讯协议 V41"),
        CommParam("默认波特率", "CAN 125 kbps"),
        CommParam("默认地址", "模块地址 0x01~0x7F（0x00 广播），监控地址 0x01~0x0F"),
        CommParam("默认IP/端口", "UT-6502 默认 TCP 5001"),
    ],
    func_codes=[
        FuncCode("Byte1=0", "DC 侧电压", "mV，读命令 Byte0 低 4 位=0x02，应答=0x03"),
        FuncCode("Byte1=1", "充电电流", "mA，读回 Iout"),
        FuncCode("Byte1=2", "DC 侧电压设定值", "mV，R/W"),
        FuncCode("Byte1=3", "充电限流点设定值", "mA，R/W"),
        FuncCode("Byte1=4", "DCDC 开关机", "0=开机，1=关机"),
        FuncCode("Byte1=5", "读模块序列号", "应答 Byte2~3=高16位型号/默认电压，Byte4~7=低32位"),
        FuncCode("Byte1=8", "模块状态标志位", "32 位逐位故障/状态"),
        FuncCode("Byte1=20/21/22", "线电压 AB/BC/CA", "mV"),
        FuncCode("Byte1=30/31/34", "进风口/PFC 热点/DCDC 热点温度", "毫度"),
        FuncCode("Byte1=61", "DC 侧电池电压", "mV"),
        FuncCode("Byte1=89", "组号", "1~15 组，R/W"),
        FuncCode("Byte1=95/96", "高低压模式设置/状态", "1=1000V 高压，2=500V 低压（仅关机可设）"),
        FuncCode("Byte1=127", "拓展类型命令", "CommandSup：51/52 双向模式、66/67/68 放电限流/电流、73 离网并机使能"),
    ],
    registers=[
        Reg("Byte0[3:0]", "信息类型", "RW", "0x00 设置 / 0x01 设置应答 / 0x02 读 / 0x03 读应答 / 0x04 读序列号应答"),
        Reg("Byte0[7:4]", "组地址", "RW", "0x01~0x0F，0x00 广播"),
        Reg("Byte1", "命令类型", "RW", "0~127，见功能码表"),
        Reg("Byte2~3", "CommandSup", "RW", "拓展类型命令 127 时的子命令；读序列号时为高 16 位"),
        Reg("Byte4~7", "CommandData", "RW", "4 字节整数（电压 mV / 电流 mA / 温度毫度）"),
    ],
    frames=[
        FrameExample("读充放电工作模式",
                     "ID  0x18FF5101\nDATA 01 02 7F 00 34 00 00 00 00",
                     "ID  0x18FF5101\nDATA 01 03 7F 00 34 00 00 00 00"),
        FrameExample("设输出电压 505V（505000mV）",
                     "ID  0x18FF5101\nDATA 01 00 02 00 00 00 07 B4 A8",
                     "ID  0x18FF5101\nDATA 01 01 02 00 00 00 07 B4 A8"),
        FrameExample("设充电限流 10.5A（10500mA）",
                     "ID  0x18FF5101\nDATA 01 00 03 00 00 00 00 29 04",
                     "ID  0x18FF5101\nDATA 01 01 03 00 00 00 00 29 04"),
        FrameExample("模块开机（关机则末字节=01）",
                     "ID  0x18FF5101\nDATA 01 00 04 00 00 00 00 00 00",
                     "ID  0x18FF5101\nDATA 01 01 04 00 00 00 00 00 00"),
        FrameExample("读输出电压（回读 505V）",
                     "ID  0x18FF5101\nDATA 01 02 00 00 00 00 00 00 00",
                     "ID  0x18FF5101\nDATA 01 03 00 00 00 00 07 B4 A8"),
        FrameExample("读状态标志位（回读 03 08 00 00）",
                     "ID  0x18FF5101\nDATA 01 02 08 00 00 00 00 00 00",
                     "ID  0x18FF5101\nDATA 01 03 08 00 00 03 08 00 00"),
        FrameExample("读 DC 侧电池电压（回读 499.476V）",
                     "ID  0x18FF5101\nDATA 01 02 3D 00 00 00 00 00 00",
                     "ID  0x18FF5101\nDATA 01 03 3D 00 00 00 07 9F 14"),
    ],
    errors=[
        ErrorCode("Byte4~7 bit0", "交流输入过压/欠压", "检查交流输入"),
        ErrorCode("Byte4~7 bit2", "交流过压脱离(关机)", "检查交流侧"),
        ErrorCode("Byte4~7 bit3/4", "PFC 母线过压/欠压", "检查 PFC 母线"),
        ErrorCode("Byte4~7 bit6/7", "直流输出过压/过压关机", "检查直流输出"),
        ErrorCode("Byte4~7 bit8", "直流输出欠压", "检查直流输出"),
        ErrorCode("Byte4~7 bit9/11", "风扇故障/风扇驱动电路损坏", "检查风扇"),
        ErrorCode("Byte4~7 bit12/13/14/16", "环境过温/过低温/PFC 过温/DC 过温", "检查散热"),
        ErrorCode("Byte4~7 bit18/20/21", "PFC 与 DCDC 通信故障 / PFC 故障 / DCDC 故障", "检查模块内部"),
        ErrorCode("Byte4~7 bit22/23", "输入电压降额 / 温度降额", "降额运行"),
        ErrorCode("Byte4~7 bit31", "泄放电路异常", "检查泄放电路"),
    ],
    notes=[
        "所有电压单位 mV、电流单位 mA、温度单位毫度（0.001℃）。",
        "高低压模式：1=1000V 高压、2=500V 低压，仅关机状态下可设置成功。",
        "ID 域 = Protocol(4b)+监控地址(4b)+模块地址(7b)+生产日期(5b)+序列号低位(9b)。",
        "信息类型：0x00 设置 / 0x01 设置应答 / 0x02 读 / 0x03 读应答 / 0x04 读序列号应答。",
    ],
)


# ---- EN+ 模块（EN+ · CAN 2.0B 扩展帧） ----
# 报文格式：CAN 2.0B 扩展帧，29 位 ID = 通讯错误码 + 设备号 + 命令号 + 目的地址 + 源地址，
# 数据段固定 8 字节（Byte0 先传，先高后低）。波特率 125kbps，配 120Ω 终端电阻。
# 报文举例一律「ID + 8 字节数据」，可直接用于发送/比对。
PROTO_DETAILS["en"] = _detail(
    "en",
    comm=[
        CommParam("通信口", "CAN 2.0B 扩展帧（29 位 ID，经 ZLG CAN-2E-U USB-CAN 卡）"),
        CommParam("通信协议", "EN+ 充电模块 CAN 协议 V2.7.1"),
        CommParam("默认波特率", "125 kbps（固定，配 120Ω 终端电阻）"),
        CommParam("默认地址", "模块 0x01~0x3F（0x3F 广播），监控单元 0xF0~0xF8"),
        CommParam("默认IP/端口", "USB-CAN 卡（无 IP/端口）"),
    ],
    func_codes=[
        FuncCode("0x01", "读系统电压/总电流", "IEEE754 浮点 Udc(V)/Idc(A)，主模块回复"),
        FuncCode("0x02", "读在线模块数/组号", "Byte2=Num 在线个数"),
        FuncCode("0x03", "读单模块电压/电流", "IEEE754 浮点，实际值，不支持广播"),
        FuncCode("0x04", "读风扇/温度/错误码", "Byte0=风扇 0~100%、Byte1=温度(有符号℃)、Byte2~7=64 位错误码"),
        FuncCode("0x05", "读温度系列", "Tmos/Tdiod/Ttsf/Tcpu/Trad，有符号℃"),
        FuncCode("0x06", "读输入电压/模块状态", "Uab/Ubc/Uca(0.1V) + State1 状态 + State2 并机"),
        FuncCode("0x1A", "开关机", "0x01 关机 / 0x00 开机，可广播"),
        FuncCode("0x1C", "设输出电压/电流", "32 位整型：Byte0~3=Udc(1mV)、Byte4~7=Idc(1mA)"),
        FuncCode("0x1F", "设地址模式", "1=拨码设定 / 0=自动分配，须最先初始化"),
        FuncCode("0x21", "设并机模式", "1=智能并机 / 0=正常并机"),
        FuncCode("0x24", "设 MPPT/恒压", "Byte2~3=Upv、Byte4~5=UpvMpp(0.1V)、Byte6~7=IpvMpp(0.01A)"),
    ],
    registers=[],
    frames=[
        FrameExample("读系统电压/总电流 (0x01，广播询问)",
                     "ID  0x02813FF0\nDATA 00 00 00 00 00 00 00 00",
                     "ID  0x0281F001\nDATA 43 47 F3 33 00 00 00 00   ← 199.95V / 0A（主模块回复）"),
        FrameExample("读单模块电压/电流 (0x03，问模块1)",
                     "ID  0x028301F0\nDATA 00 00 00 00 00 00 00 00",
                     "ID  0x0283F001\nDATA 43 47 F3 33 00 00 00 00   ← 199.95V / 0A"),
        FrameExample("读温度/错误码 (0x04，问模块1)",
                     "ID  0x028401F0\nDATA 00 00 00 00 00 00 00 00",
                     "ID  0x0284F001\nDATA 00 D8 00 00 00 00 00 00   ← -40℃（0xD8 有符号）"),
        FrameExample("读输入电压/状态 (0x06，问模块1)",
                     "ID  0x028601F0\nDATA 00 00 00 00 00 00 00 00",
                     "ID  0x0286F001\nDATA 0F EB 0F DE 0F E5 03 00   ← 407.5/406.2/406.9V，Normal，正常并机"),
        FrameExample("设输出电压/电流 (0x1C，设模块1 = 500V/15A)",
                     "ID  0x029C01F0\nDATA 00 07 A1 20 00 00 3A 98",
                     "ID  0x029CF001\nDATA 00 07 A1 20 00 00 3A 98   ← 原样确认"),
        FrameExample("开关机 (0x1A，模块1 开机)",
                     "ID  0x029A01F0\nDATA 00 00 00 00 00 00 00 00",
                     "ID  0x029AF001\nDATA 00 00 00 00 00 00 00 00   ← 确认"),
        FrameExample("设 MPPT (0x24，开路300V/MPP200V/50A)",
                     "ID  0x02A43FF0\nDATA 00 00 0B B8 07 D0 13 88",
                     "ID  0x02A4F0XX\nDATA 0B B8 07 D0 13 88 00 00   ← XX=某模块地址"),
    ],
    errors=[
        ErrorCode("0x000000000001", "PFC 控制板温度过高", "检查散热/风道"),
        ErrorCode("0x000000000002", "PFC 散热器温度过高", "检查散热"),
        ErrorCode("0x000000000004", "bus 硬件过压", "检查输入/母线"),
        ErrorCode("0x000000010000", "风扇错误", "检查风扇接线/更换"),
        ErrorCode("0x000000020000", "地址异常", "检查拨码/地址分配"),
        ErrorCode("0x000000040000", "CAN 通讯中断", "检查 CAN 线/终端电阻/心跳"),
        ErrorCode("0x000100000000", "谐振槽电流软件过流", "降低负载/检查谐振"),
        ErrorCode("0x000200000000", "谐振槽电流硬件过流", "检查谐振电路"),
        ErrorCode("0x000400000000", "输出电压 Udc 软件过压", "降低设定/检查反馈"),
        ErrorCode("0x000800000000", "输出电压 Udc 硬件过压", "检查输出保护"),
        ErrorCode("0x001000000000", "输出电流 Idc 软件过流", "降低负载"),
        ErrorCode("0x002000000000", "输出电流 Idc 硬件过流", "检查输出/负载短路"),
        ErrorCode("0x200000000000", "CAN 通讯时间间隔太大告警", "6s 未收读取命令，加快轮询"),
        ErrorCode("0x400000000000", "放电失败告警", "检查放电回路"),
    ],
    notes=[
        "CAN 2.0B 扩展帧：29 位 ID = 通讯错误码 + 设备号(0x1模块/0xA监控-单模块/0xB监控-组) + 命令号(6位) + 目的地址 + 源地址。",
        "数据段 8 字节先高后低，Byte0 先传；浮点用 IEEE754，多字节先左移再拼接。",
        "模块上电后约 1.5s 内不响应指令（地址分配中），期间只发测试报文。",
        "0x1F 地址模式必须最先初始化（一般设拨码），否则模块不开机并在 State3 标注未初始化项。",
        "输出电压/电流设定不存储，断电失效，默认 200V/限流 50A；0x13 walk-in 存 eeprom。",
        "错误码为 64 位（Byte2 最高 → Byte7 最低），每个 bit 对应一个故障，见故障信息表。",
    ],
)


# ---- 安世博模块（UAB-1K030B-E · CAN 2.0B 扩展帧） ----
# 协议：UAB-1K030B-E CAN 通信协议 S5（2025-3-7）。CAN 2.0B 扩展帧 29 位，波特率 125kbps，电压 mV、电流 mA。
# ID 位域（29 位）：Protocol(bit28~25,0x01) + MonitorAddress(bit24~21,0x01~0x0F) + ModuleAddress(bit20~14,0x01~0x7F) + Reserved(bit13~9) + SerialNumberLowPart(bit8~0)。
# 数据域 8 字节：Byte0=GroupAddress(高4) + MessageType(低4，0设置/1设答/2读/3读答/4序列号答)，Byte1=CommandType，Byte2~3=CommandSup，Byte4~7=CommandData。
PROTO_DETAILS["asby"] = _detail(
    "asby",
    comm=[
        CommParam("通信口", "CAN 2.0B 扩展帧 29 位 ID"),
        CommParam("通信协议", "安世博 UAB-1K030B-E CAN 通信协议 S5"),
        CommParam("默认波特率", "CAN 125 kbps"),
        CommParam("默认地址", "监控 0x01~0x0F(默认 0x01)；模块 0x01~0x7F；0x00 广播"),
        CommParam("默认IP/端口", "以太网-CAN / UT-6502"),
    ],
    func_codes=[
        FuncCode("0x02", "输出电压设定值", "R/W，单位 mV"),
        FuncCode("0x03", "输出限流点设定值", "R/W，单位 mA，模式 1/4"),
        FuncCode("0x04", "开关机", "W，0 开机 / 1 关机"),
        FuncCode("0x09", "AC 电压设定值", "R/W，模式 2，单位 mV"),
        FuncCode("0x0A", "AC 频率设定值", "R/W，模式 2，单位 mHz"),
        FuncCode("0x0B", "有功功率设定值", "R/W，模式 3/4，单位 W"),
        FuncCode("0x0C", "无功功率设定值", "R/W，模式 3，单位 Var"),
        FuncCode("0x08", "模块状态标志位", "R，0初始化~11测试"),
        FuncCode("0x11", "告警信息 1", "R，32 位告警位"),
        FuncCode("0x12", "告警信息 2", "R，32 位告警位"),
        FuncCode("0x20/21/22", "线电压 AB/BC/CA", "R，单位 mV"),
        FuncCode("0x30/31/32/33", "进风口/PFC/DCDC1/DCDC2 温度", "R，单位毫度"),
        FuncCode("0x5F", "模块运行模式", "R/W，1 充电/2 离网放电/3 并网/4 恒压恒流恒功率"),
        FuncCode("0x59", "组地址", "R/W，1~15，存 EEPROM"),
        FuncCode("0x7F", "拓展命令", "子命令 23 待机时长/24 运行时长/30 通信超时"),
    ],
    registers=[
        Reg("ID[28:25]", "Protocol 协议号", "-", "0x01 双向模块与监控通讯协议号"),
        Reg("ID[24:21]", "MonitorAddress 监控地址", "-", "0x01~0x0F 默认 0x01，0x00 广播"),
        Reg("ID[20:14]", "ModuleAddress 模块地址", "-", "0x01~0x7F，0x00 广播"),
        Reg("ID[8:0]", "SerialNumberLowPart 序列号低位", "-", "生产阶段 P/E/D/0"),
        Reg("Byte0[7:4]", "GroupAddress 组地址", "-", "0x01~0x0F，0x00 广播，默认 1"),
        Reg("Byte0[3:0]", "MessageType 信息类型", "-", "0 设置/1 设答/2 读/3 读答/4 序列号答"),
    ],
    frames=[
        FrameExample(
            "设模块 1 运行模式为 3（并网）",
            "ID  0x02240101\nDATA 01 00 5F 00 00 00 00 03",
            "ID  0x02240101\nDATA 01 01 5F 00 00 00 00 03",
        ),
        FrameExample(
            "设模块 1 输出电压 475.55V（0x02）",
            "ID  0x02240101\nDATA 01 00 02 00 00 07 41 9E",
            "ID  0x02240101\nDATA 01 01 02 00 00 07 41 9E  ← 0x7419E=475550mV",
        ),
        FrameExample(
            "设模块 1 限流点 10.5A（0x03）",
            "ID  0x02240101\nDATA 01 00 03 00 00 00 29 04",
            "ID  0x02240101\nDATA 01 01 03 00 00 00 29 04  ← 0x2904=10500mA",
        ),
        FrameExample(
            "设模块 1 开机（0x04）",
            "ID  0x02240101\nDATA 01 00 04 00 00 00 00 00",
            "ID  0x02240101\nDATA 01 01 04 00 00 00 00 00  ← 0 开机",
        ),
        FrameExample(
            "读模块 1 输出电压（0x00）",
            "ID  0x02240101\nDATA 01 02 00 00 00 00 00 00",
            "ID  0x02240101\nDATA 01 03 00 00 <电压 mV>  ← 得到当前电压",
        ),
        FrameExample(
            "读模块 1 状态标志位（0x08）",
            "ID  0x02240101\nDATA 01 02 08 00 00 00 00 00",
            "ID  0x02240101\nDATA 01 03 08 00 <状态值>  ← 4 充电正常等",
        ),
        FrameExample(
            "读模块 1 序列号（0x05）",
            "ID  0x02240144\nDATA 14 05 17 08 0C 30 07 57",
            "ID  0x02240144\nDATA 01 04 05 17 08 0C 30 07 57  ← SN 230812487WD",
        ),
    ],
    errors=[
        ErrorCode("告警1 bit0", "电网过压 GridOverVolt", "检查电网"),
        ErrorCode("告警1 bit1", "电网欠压 GridUnderVolt", "检查电网"),
        ErrorCode("告警1 bit11", "PFC 母线过压 BusOverVolt", "检查 PFC 母线"),
        ErrorCode("告警1 bit20", "直流输出过压 VoutOverVolt", "检查输出侧"),
        ErrorCode("告警1 bit22", "电池过压 BatOverVolt", "检查电池"),
        ErrorCode("告警1 bit24", "直流输出过流 DcChargeOverCurr", "检查负载"),
        ErrorCode("告警1 bit30", "环境温度过高 AmbOTP", "检查散热"),
        ErrorCode("告警2 bit3", "外部通信丢失 ExternalComLoss", "检查 CAN 接线"),
        ErrorCode("告警2 bit13", "地址重复 PhyAddrConflict", "检查模块拨码地址"),
        ErrorCode("告警2 bit29/30/31", "风扇 1/2/3 故障 FanFail", "检查风扇"),
    ],
    notes=[
        "模块状态标志位：0 初始化 / 1 待机 / 2 准备完毕 / 3 充电软启动 / 4 充电正常 / 5 放电软启动 / 6 放电正常 / 7 并网软启动 / 8 并网正常 / 9 故障 / 10 更新 / 11 测试。",
        "四种运行模式步骤：模式 1(0x5F→0x02 电压→0x03 限流→0x04 开机)、模式 2(0x5F→0x09 AC电压→0x0A 频率→0x04)、模式 3(0x5F→0x0B 有功→0x0C 无功→0x04)、模式 4(0x5F→0x0B 功率→0x02 电压→0x03 限流→0x04)。",
        "序列号 7 字节：年(0~127,0=2000)+周(1~54)+流水号(1~99999)+生产地(S上海/W吴江)+生产阶段(P/E/D/0)。",
        "广播设置命令（ModuleAddress=0x00）模块不做应答；点对点命令做数据应答。",
        "功率/电流方向按模式定义：模式 1 网侧→电池为正；模式 3 四象限；模式 4 DC 侧输出为正功率、充电为正电流。",
    ],
)


# ---- 禾享源模块（HBTW · CAN 2.0B 扩展帧） ----
# 协议：HBTW 模块通信协议 V1.2-20250607。CAN 2.0B 标准扩展帧，波特率 1Mkbps。
# 帧 ID：0x08e0C111 单机命令 / 0x08e07f11 并机广播；回读 0x18c1ffC1(1号ID) 0x18c4ffC1 0x18c2ffC1 0x10b0ffc1；
# 生命帧广播 0x0850ff11（数据需递增发送，间隔 1000ms）。
# 型号：HBTW60160(10~60V±160A) / 80100(10~80V±110A) / 12075(30~120V±75A) / 20070(80~200V±70A)。
PROTO_DETAILS["hbtw"] = _detail(
    "hbtw",
    comm=[
        CommParam("通信口", "CAN 2.0B 扩展帧 29 位 ID（经 UT-6502 透传）"),
        CommParam("通信协议", "禾享源 HBTW 模块通信协议 V1.2"),
        CommParam("默认波特率", "CAN 1 Mbps"),
        CommParam("默认地址", "模块 ID 1~N（默认 1# 为主机），回读 ID 0x18cXffC1 末字节 C1/C2…标识 ID 号"),
        CommParam("默认IP/端口", "UT-6502 默认 TCP 5001"),
    ],
    func_codes=[
        FuncCode("D8 00 00", "单机开机", "Data[0]=D8 命令头，恒压 50V=5000=0x1388"),
        FuncCode("D8 00 01", "恒压限流设定", "Data: D8 00 01 00 88 13 F4 01（限压 0x1388=5000=50V，限流 0x01F4=500=50A）"),
        FuncCode("D8 00 02", "恒流模式设定", "Data: D8 00 02 00 F4 01 00 00（恒流 0x01F4=500=50A）"),
        FuncCode("D8 00 02", "限功率设定", "Data: D8 00 02 00 0C FE 00 00（2500W=0x09C4，充电 50A=0x01F4，放电 50A=65036=0xFE0C）"),
        FuncCode("D8 00 03", "停机命令", "Data: D8 00 03 00 00 00 00 00"),
        FuncCode("D9 00 03", "更改 ID 号", "设定 ID 地址（当前 ID=1 需设为 3 时用）"),
        FuncCode("D3 00 1B", "母线电压校准", "标幺值 4096，如设 4123=0x101B"),
        FuncCode("D4 00 36", "直流电压校准", "标幺值 4096，如设 4150=0x1036"),
        FuncCode("D5 00 6E", "直流电流校准", "标幺值 4096，如设 3950=0x0F6E"),
        FuncCode("e0 00 01", "故障清除", "单机故障清除 / 并机故障清除(广播)"),
    ],
    registers=[
        Reg("0x08e0C111", "单机命令帧 ID", "W", "发给单台模块（ID=1）"),
        Reg("0x08e07f11", "并机广播命令帧 ID", "W", "并机关机/故障清除等广播"),
        Reg("0x0850ff11", "生命帧广播 ID", "W", "数据需递增发送，间隔 1000ms；读模块信息用"),
        Reg("0x18c1ffC1", "回读帧 ID", "RO", "C1=1号ID，C2=2号ID…以此类推"),
        Reg("0x18c4ffC1", "并机状态显示 ID", "RO", "0x0001=并机模式 / 0x0000=单机模式"),
        Reg("0x18c2ffC1", "直流电流显示 ID", "RO", "有符号 ×10，0xFDF5=65503=-52.3A"),
        Reg("0x10b0ffc1", "故障显示 ID", "RO", "8 字节位图，逐位故障标志"),
    ],
    frames=[
        FrameExample("单机开机",
                     "ID  0x08e0C111\nDATA D8 00 00 00 00 00 00 00",
                     "ID  0x08e07f11\nDATA 0E 00 01 00 00 00 00 00"),
        FrameExample("并机故障清除（广播）",
                     "ID  0x08e0C111\nDATA e0 00 01 00 00 00 00 00",
                     "ID  0x08e07f11\nDATA 0F 00 01 00 00 00 00 00"),
        FrameExample("恒压限流设定（50V/50A）",
                     "ID  0x08e0C111\nDATA D8 00 01 00 88 13 F4 01",
                     "ID  0x08e0C111\nDATA D8 00 01 00 88 13 F4 01"),
        FrameExample("限功率设定（2500W/充电50A）",
                     "ID  0x08e0C111\nDATA D8 00 02 00 0C FE 00 00",
                     "ID  0x08e0C111\nDATA D8 00 02 00 0C FE 00 00"),
        FrameExample("直流电流显示（回读 -52.3A）",
                     "ID  0x18c2ffC1\nDATA 0B 02 00 00 00 00 00 00",
                     "ID  0x18c2ffC1\nDATA F5 FD 00 00 00 00 00 00"),
        FrameExample("母线电压显示（回读 762.4V）",
                     "ID  0x18c1ffC1\nDATA 00 00 00 00 B2 04 C8 1D",
                     "ID  0x18c1ffC1\nDATA 00 00 00 00 B2 04 00 00"),
        FrameExample("故障显示（回读）",
                     "ID  0x10b0ffc1\nDATA 00 00 40 00 00 00 BD 78",
                     "ID  0x10b0ffc1\nDATA 00 00 40 00 00 00 00 00"),
    ],
    errors=[
        ErrorCode("bite1 bit5", "母线过压故障", "检查母线电压"),
        ErrorCode("bite1 bit6", "直流输出过压快检", "检查直流输出"),
        ErrorCode("bite2 bit3", "母线过压快检故障", "检查母线"),
        ErrorCode("bite2 bit4", "母线欠压快检故障", "检查母线"),
        ErrorCode("bite2 bit5", "过温故障", "检查散热/环境温度"),
        ErrorCode("bite3 bit2", "直流输出电压异常", "检查输出回路"),
        ErrorCode("bite3 bit4", "过流故障", "检查负载"),
        ErrorCode("bite3 bit6", "母线欠压", "检查母线电压"),
        ErrorCode("—", "1#DCDC 母线欠/过压、输出过流、输出电压异常、母线过/欠压快检", "见故障位逐条对照"),
    ],
    notes=[
        "恒压 50V=5000=0x1388；限流 50A=500=0x01F4；放电 50A=65536-500=65036=0xFE0C（有符号补码）。",
        "直流电流/电压显示均 ×10 倍系数，母线电压 0x1DC8=7624=762.4V。",
        "生命帧为读模块信息用，不发生命帧模块也能正常工作；帧数据需递增发送、间隔 1000ms。",
        "C 类、三模式，可多台并联、可两台串联。",
    ],
)


# ---- 网段 Ping 扫描助手（ICMP/ARP） ----
PROTO_DETAILS["ping_scan"] = _detail(
    "ping_scan",
    comm=[
        CommParam("通信口", "以太网"),
        CommParam("通信协议", "ICMP Ping / ARP 并发探活（网络层，无波特率）"),
        CommParam("默认波特率", "—"),
        CommParam("默认地址", "—"),
        CommParam("默认IP/端口", "目标 IP 由用户输入"),
    ],
    func_codes=[
        FuncCode("ICMP Echo", "Ping 探活", "检测主机在线"),
        FuncCode("ARP", "ARP 解析", "MAC 地址回填"),
    ],
    registers=[],
    frames=[],
    errors=[],
    notes=["目标混写解析（IP/范围/网段）+ 在线统计 + MAC 回填 + 结果导出。"],
)


# ---- 串口调试助手（串口/TCP/UDP/Modbus） ----
PROTO_DETAILS["serial_debug_host"] = _detail(
    "serial_debug_host",
    comm=[
        CommParam("通信口", "RS-232 / USB-CDC / TCP Client/Server / UDP"),
        CommParam("通信协议", "串口透传 / Modbus-RTU / TCP·UDP"),
        CommParam("默认波特率", "115200-8-N-1（1200~921600）"),
        CommParam("默认地址", "Modbus 从机地址可设"),
        CommParam("默认IP/端口", "TCP/UDP 地址端口用户设定"),
    ],
    func_codes=[
        FuncCode("0x01~0x06/0x10", "Modbus 读写", "自动组帧 + CRC16"),
        FuncCode("任意指令", "任意指令", "手动组帧"),
        FuncCode("HEX/ASCII", "编码切换", "HEX 收发/编码选择"),
    ],
    registers=[],
    frames=[
        FrameExample("Modbus 读寄存器", "[从机] 03 [起始] [数量] [CRC]",
                     "[从机] 03 [字节数] [数据] [CRC]"),
    ],
    errors=[
        ErrorCode("异常码 01~04", "Modbus 异常", "映射人话提示"),
        ErrorCode("900ms", "响应超时", "检查从机"),
        ErrorCode("CRC", "校验失败", "检查线路"),
    ],
    notes=[
        "串口与 TCP 二选一自动切换，勾双向转发可并存互转数据。",
        "两页独立串口可同时连接；驱动不接受的 5/6 位数据位/1.5 停止位自动降级 8-1。",
    ],
)


def get_detail(module_id: str) -> Optional[ProtocolDetail]:
    """返回某模块的结构化协议详情，未登记返回 None（界面回退到 proto_note 文本）。"""
    return PROTO_DETAILS.get(module_id)


# ---------------------------------------------------------------------------
# 通信参数表格行：为「协议与调试规范」页右侧总览表格派生一行
# （波特率 / 通信口 / 协议 / 默认IP / 默认端口）
# ---------------------------------------------------------------------------

def _first_match(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else "-"


def build_table_row(module: dict) -> dict:
    """从模块注册表 + 协议详情派生右侧表格的一行字段。

    返回 {"id","name","proto","iface","baud","ip","port"}，未识别为 "-"。
    优先取结构化 ProtocolDetail.comm；未登记则从 proto_note 文本正则提取。
    """
    mid = module["id"]
    proto = module.get("proto", "-")
    note = module.get("proto_note", "") or module.get("summary", "")
    detail = get_detail(mid)

    if detail:
        # 从结构化 comm 里按 key 取值
        m = {c.key: c.value for c in detail.comm}
        iface = m.get("通信口", "-")
        baud = m.get("默认波特率", "-")
        ip_port = m.get("默认IP/端口", "-")
    else:
        # 从 proto_note 文本正则提取（尽力而为，未识别标 -）
        iface = _first_match(r"(RS[- ]?\d+|CAN[ .0-9]*B?|USB[- ]?CDC|LAN|以太网)", note)
        # 波特率：优先带「波特率/bps/kbps」上下文的数值；CAN 类取 kbps
        if "CAN" in note or "CAN" in proto:
            baud = _first_match(r"(\d+\s*kbps)", note)
            baud = baud if baud != "-" else _first_match(r"波特率\s*([\d.]+[kM]?)", note)
        else:
            baud = _first_match(r"波特率[^\d]{0,4}(\d{4,6})", note)
            if baud == "-":
                baud = _first_match(r"默认\s*(\d{4,6})", note)
        ip = _first_match(r"(\d{1,3}(?:\.\d{1,3}){3})", note)
        port = _first_match(r"(?:TCP|端口)\s*(\d{2,5})", note)
        ip_port = ("IP " + ip if ip != "-" else "-") + (" : " + port if port != "-" else "")

    # 协议字段：优先 proto（徽章短名），保留 note 里的协议描述作为补充
    return {
        "id": mid,
        "name": module.get("name", mid),
        "vendor": module.get("vendor", "-"),
        "proto": proto,
        "iface": iface if iface != "-" else _first_match(r"(RS[- ]?\d+|CAN|USB|LAN|以太网)", proto),
        "baud": baud if baud != "-" else "-",
        "ip_port": ip_port,
    }
