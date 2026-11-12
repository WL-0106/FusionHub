# -*- coding: utf-8 -*-
"""新胜负载箱寄存器表与写入校验（单一事实源，地址无偏移=十进制寄存器号）。

手册疑点（保留原版处理）：功率档示例帧写 0x32H(=50) 与寄存器表 51 不一致，
两帧 CRC 均自洽无法裁决 —— 默认按寄存器表 51/53/55，可切「手册示例 50/52/54」。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Register:
    key: str
    name: str
    addr: int
    access: str          # R / W / RW
    vtype: str = "u16"   # bool / delay / edge / gear / u16
    vmin: int = 0
    vmax: int = 0xFFFF
    desc: str = ""


GEAR_ADDR_TABLE = {"A": 51, "B": 53, "C": 55}    # 寄存器表地址（默认）
GEAR_ADDR_EXAMPLE = {"A": 50, "B": 52, "C": 54}  # 手册示例帧地址 0x32H

REGS = [
    Register("fan_sw",      "风机开关",         1,   "RW", "bool",  0, 1,  "1=开 0=关"),
    Register("fan_status",  "风机状态指示灯",   2,   "R",  "bool",  0, 1,  "0=关 1=开"),
    Register("overtemp",    "高温报警",         3,   "R",  "bool",  0, 1,  "0=正常 1=报警"),
    Register("estop",       "急停开关",         5,   "RW", "bool",  0, 1,  "1=正常 0=急停"),
    Register("delay_on",    "风机延时开启设定", 10,  "RW", "delay", 0, 32765),
    Register("delay_off",   "风机延时关闭设定", 20,  "RW", "delay", 0, 32765),
    Register("unload_a",    "A相卸载/同步卸载", 35,  "W",  "edge",  1, 1,  "上升沿触发，写1"),
    Register("unload_b",    "B相卸载",          36,  "W",  "edge",  1, 1,  "上升沿触发，写1"),
    Register("unload_c",    "C相卸载",          37,  "W",  "edge",  1, 1,  "上升沿触发，写1"),
    Register("unload_all",  "一键卸载(复位)",   38,  "W",  "edge",  1, 1,  "上升沿触发，写1"),
    Register("gear_a",      "A相/三相功率档",   51,  "RW", "gear",  0, 0xFFFF, "10倍输入"),
    Register("gear_b",      "B相功率档",        53,  "RW", "gear",  0, 0xFFFF, "10倍输入"),
    Register("gear_c",      "C相功率档",        55,  "RW", "gear",  0, 0xFFFF, "10倍输入"),
    Register("sync_mode",   "同步/独立切换",    200, "RW", "bool",  0, 1,  "0=独立 1=同步"),
]
REG_BY_KEY = {r.key: r for r in REGS}
_GEAR_PHASE = {"gear_a": "A", "gear_b": "B", "gear_c": "C"}


def gear_addr(phase: str, mode: str = "table") -> int:
    return (GEAR_ADDR_TABLE if mode == "table" else GEAR_ADDR_EXAMPLE)[phase]


def validate_write(key: str, raw: int, gear_mode: str = "table") -> int:
    """写入前本地量程/取值校验，非法抛 ValueError（不发报文），合法返回目标地址。

    注意：key 必须与 REGS 定义完全一致，防止键不匹配导致校验静默失效。
    """
    r = REG_BY_KEY.get(key)
    if r is None:
        raise ValueError("未定义的寄存器: %r" % key)
    if r.vtype == "gear":
        addr = gear_addr(_GEAR_PHASE[key], gear_mode)
    else:
        addr = r.addr
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError("%s：写入值必须是整数" % r.name)
    if raw < r.vmin or raw > r.vmax:
        if r.vtype == "delay":
            raise ValueError("%s：超出设定范围 0~32765" % r.name)
        raise ValueError("%s：写入值 %d 超出合法范围 %d~%d" % (r.name, raw, r.vmin, r.vmax))
    return addr
