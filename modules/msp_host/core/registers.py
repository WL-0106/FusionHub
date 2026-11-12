# -*- coding: utf-8 -*-
"""寄存器表 —— 全流程单一事实源。

来源：
  - MSP65 说明书 V2.3 §8.1「寄存器列表」/「状态寄存器」
  - 升级版 MSP62 直流电源说明书 V1.3 §「寄存器地址及功能列表」/「状态、模式寄存器」
派生物：`python registers.py --export` 导出 exports/寄存器表_MSP65.csv、exports/寄存器表_MSP62.csv
代码、界面、自动化验证、文档均从本表派生，禁止在别处硬编码地址。

澄清项（手册未写清，不猜测，见交付说明「遗留问题清单」）：
  1. MSP65 状态寄存器 1003 手册仅列出 bit0~2，其余位手册表格缺失 → 只解释已知位，其余显示原始值。
  2. MSP62 电压/电流小数位「根据电源规格生成」，无统一换算式 → 小数位由上位机配置。
  3. MSP62 同时列出 2001/2002 与 2021/2022 均为「基准电压/基准电流」，
     手册范例写入的是 2001/2002 → 默认使用 2001/2002，2021/2022 保留可见。
  4. 手册未给出 Modbus 异常码表 → 按标准 Modbus 异常码映射人话提示。
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# ----------------------------------------------------------------------------
# 基础定义
# ----------------------------------------------------------------------------

ACCESS_R = "R"      # 只读（用 0x04 读）
ACCESS_RW = "RW"    # 可写（用 0x03 读，0x06/0x10 写）

# 量纲类型 → 物理换算方式
KIND_VOLTAGE = "voltage"    # raw / 10**v_dec
KIND_CURRENT = "current"    # raw / 10**i_dec
KIND_POWER = "power"        # raw * p_mult (W)
KIND_RAW = "raw"            # 原样显示
KIND_ENUM = "enum"          # 枚举值
KIND_BITFIELD = "bitfield"  # 状态/模式位
KIND_ADDR = "address"       # 设备地址


@dataclass(frozen=True)
class BitDef:
    """状态/模式寄存器位定义。mean0/mean1 为 None 表示手册未给出（不猜测）。"""
    bit: int
    name: str
    mean0: Optional[str]
    mean1: Optional[str]


@dataclass(frozen=True)
class RegisterDef:
    addr: int
    access: str
    name: str
    kind: str
    desc: str
    notes: str = ""
    enum: Tuple[Tuple[int, str], ...] = ()      # KIND_ENUM 时有效
    bits: Tuple[BitDef, ...] = ()               # KIND_BITFIELD 时有效
    raw_min: int = 0
    raw_max: int = 0xFFFF

    @property
    def readable(self) -> bool:
        return True

    @property
    def writable(self) -> bool:
        return self.access == ACCESS_RW


# ----------------------------------------------------------------------------
# 量纲换算（按手册规则派生，MSP62 小数位可配置）
# ----------------------------------------------------------------------------

@dataclass
class ScaleConfig:
    """物理量换算配置。

    MSP65：由额定值按手册规则自动推导小数位（可手动覆盖）。
    MSP62：手册说明小数位依电源规格/面板显示生成 → 直接配置小数位。
    """
    rated_voltage: float = 60.0    # 额定电压 (V)
    rated_current: float = 10.0    # 额定电流 (A)
    rated_power: float = 65000.0   # 额定功率 (W)
    voltage_decimals: Optional[int] = None   # 覆盖，None=自动推导
    current_decimals: Optional[int] = None
    power_multiplier: Optional[float] = None  # 每个 raw 对应多少 W，None=自动推导


def msp65_voltage_decimals(rated_v: float) -> int:
    """MSP65 手册：≤60V→3位(mV)；≤600V→2位；≤6000V→1位；>6000V→0位。"""
    if rated_v <= 60:
        return 3
    if rated_v <= 600:
        return 2
    if rated_v <= 6000:
        return 1
    return 0


def msp65_current_decimals(rated_a: float) -> int:
    """MSP65 手册：≤60A→3位(mA)；≤600A→2位；≤6000A→1位；>6000A→0位。"""
    if rated_a <= 60:
        return 3
    if rated_a <= 600:
        return 2
    if rated_a <= 6000:
        return 1
    return 0


def msp65_power_multiplier(rated_w: float) -> float:
    """MSP65 手册：≤65000W→1W；≤650000W→10W；≤6500000W→100W；>6500000W→1000W。"""
    if rated_w <= 65000:
        return 1.0
    if rated_w <= 650000:
        return 10.0
    if rated_w <= 6500000:
        return 100.0
    return 1000.0


def resolve_scale(profile: "DeviceProfile", cfg: ScaleConfig) -> Dict[str, float]:
    """返回 {'voltage_decimals','current_decimals','power_multiplier'}。"""
    if profile.model == "MSP65":
        v_dec = cfg.voltage_decimals if cfg.voltage_decimals is not None \
            else msp65_voltage_decimals(cfg.rated_voltage)
        i_dec = cfg.current_decimals if cfg.current_decimals is not None \
            else msp65_current_decimals(cfg.rated_current)
        p_mult = cfg.power_multiplier if cfg.power_multiplier is not None \
            else msp65_power_multiplier(cfg.rated_power)
    else:  # MSP62：小数位按面板显示配置（手册无统一换算式）
        # 兜底默认值取本系列在役机型档位：电压 1 位、电流 3 位（如 1500V/1A、1000V/10A 款）
        v_dec = cfg.voltage_decimals if cfg.voltage_decimals is not None else 1
        i_dec = cfg.current_decimals if cfg.current_decimals is not None else 3
        p_mult = cfg.power_multiplier if cfg.power_multiplier is not None else 1.0
    return {"voltage_decimals": v_dec, "current_decimals": i_dec, "power_multiplier": p_mult}


def raw_to_physical(kind: str, raw: int, scale: Dict[str, float]) -> float:
    if kind == KIND_VOLTAGE:
        return raw / (10 ** scale["voltage_decimals"])
    if kind == KIND_CURRENT:
        return raw / (10 ** scale["current_decimals"])
    if kind == KIND_POWER:
        return raw * scale["power_multiplier"]
    return float(raw)


def physical_to_raw(kind: str, phys: float, scale: Dict[str, float]) -> int:
    if kind == KIND_VOLTAGE:
        return int(round(phys * (10 ** scale["voltage_decimals"])))
    if kind == KIND_CURRENT:
        return int(round(phys * (10 ** scale["current_decimals"])))
    if kind == KIND_POWER:
        return int(round(phys / scale["power_multiplier"]))
    return int(round(phys))


# ----------------------------------------------------------------------------
# MSP65 寄存器表（说明书 V2.3 §8.1）
# ----------------------------------------------------------------------------

_MSP65_STATUS_BITS = (
    BitDef(0, "输出状态", "输出关闭", "输出启动"),
    BitDef(1, "工作模式", "非恒流模式", "恒流模式"),
    BitDef(2, "工作模式", "非恒压模式", "恒压模式"),
    # bit3 及以后：手册表格缺失（澄清项 1），不做解释
)

MSP65_REGISTERS: Tuple[RegisterDef, ...] = (
    RegisterDef(1000, ACCESS_R, "输出电压", KIND_VOLTAGE, "实际输出电压",
                notes="小数位按额定值推导：≤60V 3位 / ≤600V 2位 / ≤6000V 1位 / >6000V 0位"),
    RegisterDef(1001, ACCESS_R, "输出电流", KIND_CURRENT, "实际输出电流",
                notes="小数位按额定值推导：≤60A 3位 / ≤600A 2位 / ≤6000A 1位 / >6000A 0位"),
    RegisterDef(1002, ACCESS_R, "输出功率", KIND_POWER, "实际输出功率",
                notes="单位倍率按额定功率推导：≤65kW W / ≤650kW 10W / ≤6.5MW 100W / >6.5MW 1000W"),
    RegisterDef(1003, ACCESS_R, "设备状态", KIND_BITFIELD, "工作状态",
                notes="手册仅定义 bit0~2，其余位手册未给出（澄清项 1）", bits=_MSP65_STATUS_BITS),
    RegisterDef(2000, ACCESS_RW, "设备地址", KIND_ADDR, "设备地址", notes="有效值 1~100，0 为广播探测", raw_min=1, raw_max=100),
    RegisterDef(2001, ACCESS_RW, "预置电压", KIND_VOLTAGE, "电压设定值", notes="小数位同输出电压"),
    RegisterDef(2002, ACCESS_RW, "预置电流", KIND_CURRENT, "电流设定值", notes="小数位同输出电流"),
    RegisterDef(2003, ACCESS_RW, "过压值", KIND_VOLTAGE, "OVP 设定值", notes="小数位同输出电压"),
    RegisterDef(2004, ACCESS_RW, "欠压值", KIND_VOLTAGE, "UVP 设定值", notes="小数位同输出电压"),
    RegisterDef(2005, ACCESS_RW, "过流值", KIND_CURRENT, "OCP 设定值", notes="小数位同输出电流"),
    RegisterDef(2006, ACCESS_RW, "欠流值", KIND_CURRENT, "UCP 设定值", notes="小数位同输出电流"),
    RegisterDef(2007, ACCESS_RW, "过功率", KIND_POWER, "OPP 设定值", notes="单位倍率同输出功率"),
    RegisterDef(2008, ACCESS_RW, "欠功率", KIND_POWER, "欠功率设定值", notes="单位倍率同输出功率"),
    RegisterDef(2009, ACCESS_RW, "输出控制", KIND_ENUM, "输出开关",
                notes="0 停止输出，非 0 启动输出", enum=((0, "停止输出"), (1, "启动输出"))),
    RegisterDef(2010, ACCESS_RW, "数据保存", KIND_ENUM, "参数保存",
                notes="写 1 保存全部参数，重启不丢失；单次有效",
                enum=((0, "无操作"), (1, "保存参数"))),
    RegisterDef(2011, ACCESS_RW, "LOCK设置", KIND_ENUM, "LOCK 状态设置",
                notes="非 0 进入 LOCK；写 0 解除", enum=((0, "解除 LOCK"), (1, "进入 LOCK"))),
    RegisterDef(2012, ACCESS_RW, "协议类型", KIND_ENUM, "通讯协议选择",
                notes="", enum=((0, "Modbus RTU"), (65, "SCPI"))),
    RegisterDef(2013, ACCESS_RW, "远程接口", KIND_ENUM, "通讯接口选择",
                notes="", enum=((1, "RS232"), (3, "LAN"), (4, "RS485"))),
    RegisterDef(2014, ACCESS_RW, "RS232波特率", KIND_ENUM, "RS232 波特率", notes="",
                enum=((0, "9600"), (1, "19200"), (2, "38400"), (3, "57600"), (4, "115200"))),
    RegisterDef(2015, ACCESS_RW, "RS485波特率", KIND_ENUM, "RS485 波特率", notes="",
                enum=((0, "9600"), (1, "19200"), (2, "38400"), (3, "57600"), (4, "115200"))),
)

# ----------------------------------------------------------------------------
# MSP62 寄存器表（说明书 V1.3「寄存器地址及功能列表」）
# ----------------------------------------------------------------------------

_MSP62_STATUS_BITS = (
    BitDef(0, "输出状态", "输出关闭", "输出启动"),
    BitDef(1, "工作模式", "非恒流模式", "恒流模式"),
    BitDef(2, "工作模式", "非恒压模式", "恒压模式"),
    BitDef(3, "控制方式", "内控模式", "外控模式"),
    BitDef(4, "温度状态", "未过热", "过热"),
    BitDef(5, "过流状态", "未过流", "过流"),
    BitDef(6, "过压状态", "未过压", "过压"),
    BitDef(12, "预留", "预留", "预留"),
    BitDef(15, "故障", "无故障", "故障"),
)

_MSP62_MODE_BITS = (
    BitDef(0, "过压保护", "禁止过压保护", "允许过压保护"),
    BitDef(2, "过流保护", "禁止过流保护", "允许过流保护"),
    BitDef(10, "量程", "高量程", "低量程(定制)"),
    BitDef(11, "蜂鸣器", "蜂鸣器响(异常状态)", "蜂鸣器不响"),
    BitDef(12, "启动输出", "启动不输出", "与 bit13 全 1 时启动后直接输出"),
    BitDef(13, "启动输出", "启动不输出", "与 bit12 全 1 时启动后直接输出"),
)

MSP62_REGISTERS: Tuple[RegisterDef, ...] = (
    RegisterDef(1000, ACCESS_R, "输出电压", KIND_VOLTAGE, "实际输出电压",
                notes="小数位按电源规格/面板显示（澄清项 2，上位机可配置）"),
    RegisterDef(1001, ACCESS_R, "输出电流", KIND_CURRENT, "实际输出电流",
                notes="小数位按电源规格/面板显示（澄清项 2，上位机可配置）"),
    RegisterDef(1007, ACCESS_R, "设备状态", KIND_BITFIELD, "工作状态",
                notes="见手册状态位表", bits=_MSP62_STATUS_BITS),
    RegisterDef(2000, ACCESS_RW, "设备地址", KIND_ADDR, "设备地址", notes="有效值 1~100，0 为广播探测", raw_min=1, raw_max=100),
    RegisterDef(2001, ACCESS_RW, "基准电压", KIND_VOLTAGE, "电压设定值",
                notes="手册范例写入此地址；与 2021 同名（澄清项 3）"),
    RegisterDef(2002, ACCESS_RW, "基准电流", KIND_CURRENT, "电流设定值",
                notes="手册范例写入此地址；与 2022 同名（澄清项 3）"),
    RegisterDef(2003, ACCESS_RW, "过压值", KIND_VOLTAGE, "OVP 设定值", notes="小数位同基准电压"),
    RegisterDef(2005, ACCESS_RW, "过流值", KIND_CURRENT, "OCP 设定值", notes="小数位同基准电流"),
    RegisterDef(2007, ACCESS_RW, "波特率", KIND_ENUM, "串口波特率", notes="",
                enum=((0, "9600"), (1, "19200"), (2, "57600"), (3, "115200"))),
    RegisterDef(2014, ACCESS_RW, "工作模式", KIND_BITFIELD, "保护/量程/蜂鸣器/上电输出模式",
                notes="bit12、bit13 全 1 时启动后直接输出", bits=_MSP62_MODE_BITS),
    RegisterDef(2015, ACCESS_RW, "预留", KIND_RAW, "预留", notes="手册标注预留"),
    RegisterDef(2016, ACCESS_RW, "输出控制", KIND_ENUM, "输出开关",
                notes="0 停止输出，非 0 启动输出", enum=((0, "停止输出"), (1, "启动输出"))),
    RegisterDef(2017, ACCESS_RW, "预留", KIND_RAW, "预留", notes="手册标注预留"),
    RegisterDef(2020, ACCESS_RW, "协议类型", KIND_ENUM, "通讯协议选择",
                notes="0:RTU 默认值；65:SCPI", enum=((0, "Modbus RTU"), (65, "SCPI"))),
    RegisterDef(2021, ACCESS_RW, "基准电压", KIND_VOLTAGE, "电压设定值(第二组)",
                notes="与 2001 同名（澄清项 3），默认使用 2001"),
    RegisterDef(2022, ACCESS_RW, "基准电流", KIND_CURRENT, "电流设定值(第二组)",
                notes="与 2002 同名（澄清项 3），默认使用 2002"),
)


# ----------------------------------------------------------------------------
# 设备档案
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceProfile:
    model: str
    title: str
    default_baud: int
    read_only_fc: int            # 读只读区功能码（手册：0x04）
    read_writable_fc: int        # 读可写区功能码（手册：0x03）
    registers: Tuple[RegisterDef, ...]
    status_reg: int              # 状态寄存器地址
    output_ctrl_reg: int         # 输出控制寄存器地址
    setpoint_v_reg: int          # 电压设定寄存器地址
    setpoint_i_reg: int          # 电流设定寄存器地址
    ovp_reg: int
    ocp_reg: int
    has_power_meter: bool = True
    # 一次批量读测量值的连续区间（地址必须连续，单帧 ≤20 寄存器）
    measure_block: Tuple[int, int] = (1000, 1003)   # (起始地址, 数量)
    status_is_contiguous: bool = True               # 状态寄存器是否在批量块内

    def reg(self, addr: int) -> RegisterDef:
        for r in self.registers:
            if r.addr == addr:
                return r
        raise KeyError(f"{self.model} 不存在寄存器 {addr}")

    def find(self, name: str) -> RegisterDef:
        for r in self.registers:
            if r.name == name:
                return r
        raise KeyError(f"{self.model} 不存在寄存器 {name}")


MSP65 = DeviceProfile(
    model="MSP65",
    title="美恩斯 MSP65 直流电源",
    default_baud=115200,
    read_only_fc=0x04,
    read_writable_fc=0x03,
    registers=MSP65_REGISTERS,
    status_reg=1003,
    output_ctrl_reg=2009,
    setpoint_v_reg=2001,
    setpoint_i_reg=2002,
    ovp_reg=2003,
    ocp_reg=2005,
    has_power_meter=True,
    measure_block=(1000, 4),     # 1000~1003 含功率与状态
    status_is_contiguous=True,
)

MSP62 = DeviceProfile(
    model="MSP62",
    title="美恩斯 MSP62 直流电源（升级版）",
    default_baud=9600,
    read_only_fc=0x04,
    read_writable_fc=0x03,
    registers=MSP62_REGISTERS,
    status_reg=1007,
    output_ctrl_reg=2016,
    setpoint_v_reg=2001,
    setpoint_i_reg=2002,
    ovp_reg=2003,
    ocp_reg=2005,
    has_power_meter=False,
    measure_block=(1000, 2),     # 1000~1001；1007 不连续，单独读
    status_is_contiguous=False,
)

PROFILES: Dict[str, DeviceProfile] = {"MSP65": MSP65, "MSP62": MSP62}


# ----------------------------------------------------------------------------
# CSV 导出（单一事实源派生）
# ----------------------------------------------------------------------------

def export_csv(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for model, profile in PROFILES.items():
        path = os.path.join(out_dir, f"寄存器表_{model}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["寄存器地址", "属性", "名称", "量纲", "含义", "量程(raw)", "枚举/位定义", "附注"])
            for r in profile.registers:
                if r.enum:
                    extra = "；".join(f"{v}={label}" for v, label in r.enum)
                elif r.bits:
                    extra = "；".join(f"bit{b.bit} {b.name}(0={b.mean0 or '?'}/1={b.mean1 or '?'})" for b in r.bits)
                else:
                    extra = ""
                w.writerow([
                    r.addr, r.access, r.name, r.kind, r.desc,
                    f"{r.raw_min}~{r.raw_max}" if r.writable else "—",
                    extra, r.notes,
                ])
        print(f"已导出 {path}")


if __name__ == "__main__":
    import sys
    if "--export" in sys.argv:
        export_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports"))
    else:
        print(__doc__)
