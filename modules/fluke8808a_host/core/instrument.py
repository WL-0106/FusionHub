# -*- coding: utf-8 -*-
"""语义化仪器接口 —— 界面唯一入口（读电压/切功能/设定量程...），不暴露帧字节。

界面与协议解耦：UI 只调本层方法拿 (ok, value, message)，不接触命令字面量。
命令字面量全部从 commands.py 单一事实源派生。
"""
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .commands import (
    DBREF_TABLE, RANGE_TABLE, RATE_TABLE, TRIGGER_TYPES,
    UI_FUNCTIONS, OVERLOAD_VALUE,
)
from .stack import CommandResult, ProtocolStack, ResultCode, StackConfig, explain_esr
from .transport import Transport


@dataclass
class Reading:
    value: Optional[float]
    raw: str
    unit: str
    ok: bool
    message: str = ""


@dataclass
class DeviceInfo:
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    firmware: str = ""
    raw: str = ""


class Instrument:
    """8808A 语义接口。所有方法线程安全（内部走协议栈队列）。"""

    # 功能 -> 单位（界面显示用）
    UNITS = {
        "VDC": "VDC", "VAC": "VAC", "VACDC": "VAC RMS",
        "ADC": "ADC", "AAC": "AAC", "AACDC": "AAC RMS",
        "OHMS": "Ω", "FREQ": "Hz", "CONT": "Ω", "DIODE": "VDC",
    }

    def __init__(self, stack: ProtocolStack):
        self._stack = stack
        self._current_func = "VDC"

    # ------------------------------------------------------------ 连接管理
    @property
    def stack(self) -> ProtocolStack:
        return self._stack

    def identity(self) -> Tuple[bool, DeviceInfo, str]:
        r = self._stack.execute("*IDN?")
        if not r.ok:
            return False, DeviceInfo(raw=r.raw), r.message
        parts = [p.strip() for p in r.payload.split(",")]
        info = DeviceInfo(
            manufacturer=parts[0] if len(parts) > 0 else "",
            model=parts[1] if len(parts) > 1 else "",
            serial=parts[2] if len(parts) > 2 else "",
            firmware=parts[3] if len(parts) > 3 else "",
            raw=r.payload,
        )
        return True, info, "已识别仪器"

    def reset(self) -> Tuple[bool, str]:
        r = self._stack.execute("*RST")
        return r.ok, r.message if not r.ok else "已复位（上电复位）"

    def clear_status(self) -> Tuple[bool, str]:
        r = self._stack.execute("*CLS")
        return r.ok, r.message if not r.ok else "状态寄存器已清除"

    def esr_summary(self) -> Tuple[bool, str]:
        """读 ESR 并转成人话（异常定位用）。"""
        r = self._stack.execute("*ESR?")
        if not r.ok:
            return False, r.message
        try:
            val = int(r.payload.strip())
        except ValueError:
            return False, f"ESR 解析失败: {r.payload!r}"
        bits = explain_esr(val)
        return True, f"ESR=0x{val:02X}：" + ("；".join(bits) if bits else "无异常事件")

    def ping(self) -> bool:
        return self._stack.execute("*IDN?").ok

    # ------------------------------------------------------------ 测量功能
    def set_function(self, mnemonic: str) -> Tuple[bool, str]:
        """切换主屏测量功能（VDC/VAC/ADC/AAC/OHMS/FREQ/CONT/DIODE）。"""
        r = self._stack.execute(mnemonic)
        if r.ok:
            self._current_func = mnemonic
            return True, f"功能已切换为 {mnemonic}"
        return False, r.message

    def set_wire(self, wire4: bool) -> Tuple[bool, str]:
        """电阻 2线/4线切换（仅 OHMS 功能有效）。"""
        r = self._stack.execute("WIRE4" if wire4 else "WIRE2")
        return r.ok, r.message if not r.ok else ("已切换 4 线测量" if wire4 else "已切换 2 线测量")

    def read_primary(self) -> Reading:
        """读主屏测量值（自动触发，内触发模式）。过载返回 1e9 标记。"""
        return self._read("MEAS1?")

    def read_fast(self) -> Reading:
        """读显示值（VAL1?，不重新触发）——外触发模式轮询用。"""
        return self._read("VAL1?")

    def read_dual(self) -> Tuple[Reading, Optional[Reading]]:
        """读主/副屏。副屏未开时第二项为 None。"""
        r = self._stack.execute("VAL?")
        if not r.ok:
            return Reading(None, r.raw, "", False, r.message), None
        parts = r.payload.split(",")
        r1 = self._to_reading(parts[0])
        r2 = self._to_reading(parts[1]) if len(parts) > 1 else None
        return r1, r2

    def _read(self, cmd: str) -> Reading:
        r = self._stack.execute(cmd)
        return self._to_reading(r.payload, ok=r.ok, msg=r.message, raw=r.raw)

    def _to_reading(self, payload: str, ok=True, msg="", raw="") -> Reading:
        unit = self.UNITS.get(self._current_func, "")
        if not ok:
            return Reading(None, raw, unit, False, msg)
        p = payload.strip()
        # 手册：+/- 1.0E+9 表示过载（屏显 0L）
        p_clean = p.replace("+", "", 1) if p[:1] == "+" else p
        try:
            v = float(p_clean)
        except ValueError:
            # 格式2可能带单位（如 "1.2345E+0 VDC"）
            token = p.split()[0] if p.split() else ""
            try:
                v = float(token.replace("+", "", 1) if token[:1] == "+" else token)
            except ValueError:
                return Reading(None, raw or p, unit, False, f"数值解析失败: {p!r}")
        overloaded = abs(v) >= OVERLOAD_VALUE * 0.999
        return Reading(None if overloaded else v, p, unit, True,
                       "过载 (0L)" if overloaded else "")

    # ------------------------------------------------------------ 量程 / 速率
    def set_auto_range(self) -> Tuple[bool, str]:
        r = self._stack.execute("AUTO")
        return r.ok, r.message if not r.ok else "已进入自动量程"

    def set_manual_range(self, range_n: int) -> Tuple[bool, str]:
        if range_n not in RANGE_TABLE:
            return False, f"量程编号越界: {range_n}（有效 1-7）"
        r = self._stack.execute(f"RANGE {range_n}")
        return r.ok, r.message if not r.ok else f"手动量程已设为 {range_n} 号"

    def set_rate(self, rate: str) -> Tuple[bool, str]:
        rate = rate.upper()
        if rate not in RATE_TABLE:
            return False, f"速率越界: {rate}（有效 S/M/F）"
        r = self._stack.execute(f"RATE {rate}")
        return r.ok, r.message if not r.ok else f"测量速度已设为 {rate}（{RATE_TABLE[rate]} 读数/秒）"

    def range_label(self, func: str, range_n: int) -> str:
        """按功能与量程编号返回量程文字（界面下拉显示）。"""
        cols = {"VDC": 0, "VAC": 0, "VACDC": 0, "ADC": 4, "AAC": 2,
                "AACDC": 2, "OHMS": 1, "FREQ": 3, "CONT": 1, "DIODE": 0}
        col = cols.get(func)
        if col is None or range_n not in RANGE_TABLE:
            return f"{range_n} 号"
        v = RANGE_TABLE[range_n][col]
        return f"{range_n} 号（{v}）" if v else f"{range_n} 号（不适用）"

    # ------------------------------------------------------------ 触发
    def set_trigger_type(self, t: int) -> Tuple[bool, str]:
        if t not in TRIGGER_TYPES:
            return False, f"触发类型越界: {t}（有效 1-5）"
        r = self._stack.execute(f"TRIGGER {t}")
        src, rear, delay = TRIGGER_TYPES[t]
        return r.ok, r.message if not r.ok else \
            f"触发类型 {t}：{src}触发，后面板{rear}，稳定延迟{delay}"

    def trigger_once(self) -> Tuple[bool, str]:
        r = self._stack.execute("*TRG")
        return r.ok, r.message if not r.ok else "已触发一次测量"

    def set_format(self, fmt: int) -> Tuple[bool, str]:
        if fmt not in (1, 2):
            return False, f"格式越界: {fmt}（有效 1/2）"
        r = self._stack.execute(f"FORMAT {fmt}")
        return r.ok, r.message if not r.ok else f"输出格式已设为 {fmt}"

    # ------------------------------------------------------------ 调节器（REL/dB/比对）
    def rel_on(self, base: Optional[float] = None) -> Tuple[bool, str]:
        if base is None:
            r = self._stack.execute("REL")
            return r.ok, r.message if not r.ok else "REL 已开启（当前读数为基值，自动量程已禁用）"
        r = self._stack.execute(f"RELSET {base:.6g}")
        return r.ok, r.message if not r.ok else f"REL 已开启，基值={base:.6g}"

    def rel_off(self) -> Tuple[bool, str]:
        r = self._stack.execute("RELCLR")
        return r.ok, r.message if not r.ok else "REL 已关闭"

    def db_on(self) -> Tuple[bool, str]:
        r = self._stack.execute("DB")
        return r.ok, r.message if not r.ok else "dB 调节器已开启（需处于电压功能）"

    def db_off(self) -> Tuple[bool, str]:
        r = self._stack.execute("DBCLR")
        return r.ok, r.message if not r.ok else "dB 调节器已关闭"

    def set_dbref(self, index: int) -> Tuple[bool, str]:
        if index not in DBREF_TABLE:
            return False, f"dB 参考阻抗编号越界: {index}（有效 1-21）"
        r = self._stack.execute(f"DBREF {index}")
        return r.ok, r.message if not r.ok else \
            f"dB 参考阻抗已设为 {DBREF_TABLE[index]} Ω（编号 {index}）"

    def comp_setup(self, lo: float, hi: float) -> Tuple[bool, str]:
        if lo > hi:
            return False, f"比对下限 {lo} 大于上限 {hi}，未发送"
        r1 = self._stack.execute(f"COMPLO {lo:.6g}")
        if not r1.ok:
            return False, r1.message
        r2 = self._stack.execute(f"COMPHI {hi:.6g}")
        return r2.ok, r2.message if not r2.ok else f"比对范围已设为 [{lo:.6g}, {hi:.6g}]"

    def comp_on(self) -> Tuple[bool, str]:
        r = self._stack.execute("COMP")
        return r.ok, r.message if not r.ok else "比对模式已开启（自动开启接触保持）"

    def comp_off(self) -> Tuple[bool, str]:
        r = self._stack.execute("COMPCLR")
        return r.ok, r.message if not r.ok else "比对模式已关闭"

    def comp_result(self) -> Tuple[bool, str]:
        r = self._stack.execute("COMP?")
        if not r.ok:
            return False, r.message
        v = r.payload.strip()
        human = {"HI": "超上限 (HI)", "LO": "低于下限 (LO)",
                 "PASS": "合格 (PASS)", "-": "尚未完成测量"}.get(v, v)
        return True, human

    # ------------------------------------------------------------ 远程/本地 与 存取
    def set_remote(self, lock: bool) -> Tuple[bool, str]:
        r = self._stack.execute("RWLS" if lock else "REMS")
        return r.ok, r.message if not r.ok else ("远程锁定（面板已锁）" if lock else "远程状态（面板未锁）")

    def set_local(self) -> Tuple[bool, str]:
        r = self._stack.execute("LOCS")
        return r.ok, r.message if not r.ok else "已回到本地状态"

    def save_state(self, pos: int) -> Tuple[bool, str]:
        if not 1 <= pos <= 6:
            return False, f"存储位置越界: {pos}（有效 1-6）"
        r = self._stack.execute(f"SAVE {pos}")
        return r.ok, r.message if not r.ok else f"工作状态已保存到位置 {pos}"

    def call_state(self, pos: int) -> Tuple[bool, str]:
        if not 1 <= pos <= 6:
            return False, f"存储位置越界: {pos}（有效 1-6）"
        r = self._stack.execute(f"CALL {pos}")
        return r.ok, r.message if not r.ok else f"已调用位置 {pos} 的工作状态"

    # ------------------------------------------------------------ 通用查询
    def query(self, command: str) -> CommandResult:
        """SCPI 控制台入口：原始命令（仍经协议栈队列/超时/重发保护）。"""
        return self._stack.execute(command)

    @staticmethod
    def ui_function_list():
        """界面功能按钮表（单一事实源派生）。"""
        return UI_FUNCTIONS

    @staticmethod
    def rate_table():
        return RATE_TABLE

    @staticmethod
    def trigger_table():
        return TRIGGER_TYPES

    @staticmethod
    def dbref_table():
        return DBREF_TABLE
