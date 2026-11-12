"""GPP 系列机型规格与共享数据模型。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class LinkType(Enum):
    SERIAL = "serial"   # RS-232 / USB(CDC 虚拟串口)
    LAN = "lan"


@dataclass(frozen=True)
class ChannelSpec:
    index: int          # 1 基通道号
    label: str
    v_max: float
    i_max: float
    color: str
    load_capable: bool = False       # CH1/CH2 支持负载模式
    v_choices: Optional[tuple] = None  # 固定电压档位(如 GPP-3323 CH3)
    i_settable: bool = True
    ovp_settable: bool = True
    ocp_settable: bool = True
    note: str = ""


# 面板通道颜色(说明书: CH1 黄 / CH2 蓝 / CH3 粉 / CH4 绿)，白底下取可读的深色变体
_CH_COLORS = {1: "#C8860D", 2: "#2563EB", 3: "#DB2777", 4: "#16A34A"}


def _ch12() -> ChannelSpec:
    return ChannelSpec(1, "CH1", 32.0, 3.0, _CH_COLORS[1], load_capable=True)


def _ch4323_ch3() -> ChannelSpec:
    return ChannelSpec(3, "CH3", 5.0, 1.0, _CH_COLORS[3])


def _ch4323_ch4() -> ChannelSpec:
    return ChannelSpec(4, "CH4", 15.0, 1.0, _CH_COLORS[4])


def _ch3323_ch3() -> ChannelSpec:
    return ChannelSpec(
        3, "CH3", 5.0, 5.0, _CH_COLORS[3],
        v_choices=(1.8, 2.5, 3.3, 5.0),
        i_settable=False, ovp_settable=False, ocp_settable=False,
        note="电流固定 5A，OVP 固定 5.5V",
    )


MODEL_SPECS: dict[str, list[ChannelSpec]] = {
    "GPP-1326": [ChannelSpec(1, "CH1", 32.0, 6.0, _CH_COLORS[1])],
    "GPP-2323": [_ch12(), ChannelSpec(2, "CH2", 32.0, 3.0, _CH_COLORS[2], load_capable=True)],
    "GPP-3323": [_ch12(), ChannelSpec(2, "CH2", 32.0, 3.0, _CH_COLORS[2], load_capable=True), _ch3323_ch3()],
    "GPP-4323": [_ch12(), ChannelSpec(2, "CH2", 32.0, 3.0, _CH_COLORS[2], load_capable=True),
                 _ch4323_ch3(), _ch4323_ch4()],
}

MODEL_ORDER = ["GPP-1326", "GPP-2323", "GPP-3323", "GPP-4323"]


@dataclass
class MeasSample:
    """单通道一次测量快照。"""
    channel: int
    t: float                 # 单调时钟秒
    v: float = 0.0
    i: float = 0.0
    p: float = 0.0
    v_set: float = 0.0
    i_set: float = 0.0
    output_on: bool = False
    cc: bool = False         # 限流状态


@dataclass
class ConnectionState:
    connected: bool = False
    idn: str = ""
    model: str = ""
    detail: str = ""


def detect_model(idn: str) -> Optional[str]:
    up = (idn or "").upper()
    for m in MODEL_ORDER:
        if m in up:
            return m
    return None


def specs_for(model: str) -> list[ChannelSpec]:
    return list(MODEL_SPECS.get(model, MODEL_SPECS["GPP-2323"]))


def generic_specs(n_channels: int) -> list[ChannelSpec]:
    """机型未知时按通道数生成的通用规格(0-32V/3A，CH1/CH2 带负载)。"""
    n = max(1, min(4, n_channels))
    out = []
    for i in range(1, n + 1):
        out.append(ChannelSpec(i, f"CH{i}", 32.0, 3.0, _CH_COLORS[i], load_capable=(i <= 2)))
    return out
