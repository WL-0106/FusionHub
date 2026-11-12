# -*- coding: utf-8 -*-
"""
交流回馈式负载设备门面层。

把"读哪些寄存器、怎么拼 32 位、怎么换算单位、按什么顺序下发"这些业务规则
全部收在这一层，界面只管调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import modbus_rtu as mb
from . import registers as rg


class RangeError(ValueError):
    """本地量程校验不通过 —— 拦在发报文之前，避免设备回异常码 03。"""


@dataclass
class ChannelMeasure:
    ch: int
    voltage: float = 0.0     # V
    current: float = 0.0     # A
    power: float = 0.0       # W


@dataclass
class Snapshot:
    """一次轮询得到的设备快照。"""
    online: bool = False
    running: bool = False
    has_fault: bool = False
    mode_op: int = 0
    mode_ctrl: int = 0
    version_raw: int = 0
    status_raw: int = 0
    voltage: Tuple[float, float, float] = (0.0, 0.0, 0.0)   # A/B/C 相电压 V
    current: Tuple[float, float, float] = (0.0, 0.0, 0.0)   # A/B/C 相电流 A
    power_total: float = 0.0                                # 输出总功率 W
    fault_bits: int = 0
    channels: Dict[int, ChannelMeasure] = field(default_factory=dict)
    serial: Optional[int] = None

    @property
    def mode_op_name(self) -> str:
        return rg.MODE_OP_NAMES.get(self.mode_op, "未知(%d)" % self.mode_op)

    @property
    def mode_ctrl_name(self) -> str:
        return rg.MODE_CTRL_NAMES.get(self.mode_ctrl, "未知(%d)" % self.mode_ctrl)

    @property
    def version_name(self) -> str:
        return rg.decode_version(self.version_raw)

    def active_faults(self) -> List[str]:
        out = []
        for bit in sorted(rg.FAULT_BITS):
            if self.fault_bits & (1 << bit):
                out.append(rg.FAULT_BITS[bit])
        return out


class ACFeedbackLoad:
    """交流回馈式负载（华源，协议 V1.4）。

    通道约定
        1~3   → A/B/C 相，可设功率 + 可设电流
        4~15  → 扩展通道，仅可设功率
    """

    LIMIT_KEYS = {"power": "功率", "current": "电流", "voltage": "电压"}

    def __init__(self, client: mb.ModbusClient,
                 limits: Optional[Dict[str, float]] = None):
        self.c = client
        # 用户正向限值，用于本地预校验（填 0 表示不校验）
        self.limits = dict(limits or {})
        for k in self.LIMIT_KEYS:
            self.limits.setdefault(k, 0.0)

    # ------------------------------------------------------------------
    # 量程校验
    # ------------------------------------------------------------------

    def _check(self, kind: str, value: float) -> None:
        """kind 取 power / current / voltage。越界直接拦在本地，
        不让设备返回异常码 03（ILLEGAL DATA VALUE）。"""
        label = self.LIMIT_KEYS.get(kind, kind)
        if value < 0:
            raise RangeError("%s 不能为负值：%s" % (label, value))
        lim = float(self.limits.get(kind, 0.0) or 0.0)
        if lim > 0 and value > lim:
            raise RangeError("%s %.3f 超过设定上限 %.3f，已本地拦截（避免设备回异常码 03）"
                             % (label, value, lim))

    def set_limits(self, power: float = 0.0, current: float = 0.0, voltage: float = 0.0) -> None:
        self.limits = {"power": float(power or 0.0),
                       "current": float(current or 0.0),
                       "voltage": float(voltage or 0.0)}

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------

    def set_output(self, on: bool) -> None:
        """输出控制 0x20：0 关闭 / 1 输出。"""
        self.c.write_single(rg.ADDR_OUTPUT_CTRL, 1 if on else 0)

    def clear_fault(self) -> None:
        """清除故障 0x28：写 1。"""
        self.c.write_single(rg.ADDR_CLEAR_FAULT, 1)

    def set_mode_op(self, mode: int) -> None:
        if mode not in rg.MODE_OP_NAMES:
            raise RangeError("非法操作模式：%s（可选 0/1/2）" % mode)
        self.c.write_single(rg.ADDR_MODE_OP, mode)

    def set_mode_ctrl(self, mode: int) -> None:
        if mode not in rg.MODE_CTRL_NAMES:
            raise RangeError("非法控制模式：%s（可选 0/1）" % mode)
        self.c.write_single(rg.ADDR_MODE_CTRL, mode)

    def set_total_power(self, watt: float) -> None:
        """设置功率 0x38（32 位，0.1W）。仅用于单相 / 三相统调。"""
        self._check("power", watt)
        self.c.write_u32(rg.ADDR_POWER_TOTAL, rg.p2raw(watt))

    def set_total_current(self, amp: float) -> None:
        """设置电流 0x3E（32 位，0.001A）。仅用于单相 / 三相统调。"""
        self._check("current", amp)
        self.c.write_u32(rg.ADDR_CURRENT_TOTAL, rg.a2raw(amp))

    def set_channel_power(self, ch: int, watt: float) -> None:
        """通道功率，通道 n = 0x40 + 2*(n-1)，0.1W。"""
        if not 1 <= ch <= rg.CHANNEL_COUNT:
            raise RangeError("通道号越界：%s" % ch)
        self._check("power", watt)
        self.c.write_u32(rg.ch_power_addr(ch), rg.p2raw(watt))

    def set_channel_current(self, ch: int, amp: float) -> None:
        """通道 1~3（A/B/C 相）电流，0xE0/0xE2/0xE4，0.001A。"""
        if ch not in rg.PHASE_CHANNELS:
            raise RangeError("电流设定仅支持通道 1~3（A/B/C 相），当前 %s" % ch)
        self._check("current", amp)
        self.c.write_u32(rg.phase_i_set_addr(ch), rg.a2raw(amp))

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def read_status_block(self) -> Dict[str, object]:
        """一条报文读完 0x60~0x80（状态 / 版本 / 三相 V·I / 总功率 / 故障）。"""
        regs = self.c.read_registers(rg.BLOCK_STATUS_START, rg.BLOCK_STATUS_COUNT)

        def r(a: int) -> int:
            return regs[a - rg.BLOCK_STATUS_START]

        def u32(a: int) -> int:
            hi, lo = r(a), r(a + 1)
            return mb.words_to_u32(lo, hi) if self.c.word_swap else mb.words_to_u32(hi, lo)

        status = (r(rg.ADDR_STATUS_HIGH) << 16) | r(rg.ADDR_STATUS_LOW)
        snap = Snapshot()
        snap.online = True
        snap.status_raw = status
        snap.running = bool(status & (1 << rg.ST_RUNNING_BIT))
        snap.has_fault = bool(status & (1 << rg.ST_FAULT_BIT))
        snap.mode_ctrl = (status >> rg.ST_CTRL_MODE_BIT) & 0x01
        snap.mode_op = (status >> rg.ST_OP_MODE_LOW_BIT) & rg.ST_OP_MODE_MASK
        snap.version_raw = r(rg.ADDR_VERSION)
        snap.voltage = (
            u32(rg.ADDR_V_BASE) * rg.SCALE_VOLTAGE,
            u32(rg.ADDR_V_BASE + 2) * rg.SCALE_VOLTAGE,
            u32(rg.ADDR_V_BASE + 4) * rg.SCALE_VOLTAGE,
        )
        snap.current = (
            u32(rg.ADDR_I_BASE) * rg.SCALE_CURRENT,
            u32(rg.ADDR_I_BASE + 2) * rg.SCALE_CURRENT,
            u32(rg.ADDR_I_BASE + 4) * rg.SCALE_CURRENT,
        )
        snap.power_total = u32(rg.ADDR_P_TOTAL) * rg.SCALE_POWER
        snap.fault_bits = (r(rg.ADDR_FAULT_1) << 32) | (r(rg.ADDR_FAULT_2) << 16) | r(rg.ADDR_FAULT_3)

        # 顺手把三相测量填进通道表
        for i, ch in enumerate(rg.PHASE_CHANNELS):
            snap.channels[ch] = ChannelMeasure(ch, snap.voltage[i], snap.current[i], 0.0)
        return {"snapshot": snap, "regs": regs}

    def read_channels_block(self) -> Dict[int, ChannelMeasure]:
        """两条报文读完通道 4~15 明细，并把 1~12 通道功率补齐。"""
        chans: Dict[int, ChannelMeasure] = {}

        a = self.c.read_registers(rg.BLOCK_CH_A_START, rg.BLOCK_CH_A_COUNT)

        def ra(a_addr: int) -> int:
            i = a_addr - rg.BLOCK_CH_A_START
            return mb.words_to_u32(a[i + 1], a[i]) if self.c.word_swap else mb.words_to_u32(a[i], a[i + 1])

        # 4~12 通道电压 / 电流
        for ch in range(4, 13):
            v = ra(rg.ADDR_CH4_V + 2 * (ch - 4)) * rg.SCALE_VOLTAGE
            i = ra(rg.ADDR_CH4_I + 2 * (ch - 4)) * rg.SCALE_CURRENT
            chans[ch] = ChannelMeasure(ch, v, i, 0.0)

        b = self.c.read_registers(rg.BLOCK_CH_B_START, rg.BLOCK_CH_B_COUNT)

        def rb(addr: int) -> int:
            i = addr - rg.BLOCK_CH_B_START
            return mb.words_to_u32(b[i + 1], b[i]) if self.c.word_swap else mb.words_to_u32(b[i], b[i + 1])

        # 1~12 通道功率
        for ch in range(1, 13):
            p = rb(rg.ADDR_CH1_P + 2 * (ch - 1)) * rg.SCALE_POWER
            if ch in chans:
                chans[ch].power = p
            else:
                chans[ch] = ChannelMeasure(ch, 0.0, 0.0, p)

        # 13~15 通道电压 / 电流 / 功率
        for i, ch in enumerate((13, 14, 15)):
            v = rb(rg.ADDR_CH13_V + 2 * i) * rg.SCALE_VOLTAGE
            cur = rb(rg.ADDR_CH13_I + 2 * i) * rg.SCALE_CURRENT
            p = rb(rg.ADDR_CH13_P + 2 * i) * rg.SCALE_POWER
            chans[ch] = ChannelMeasure(ch, v, cur, p)
        return chans

    def read_serial(self) -> int:
        regs = self.c.read_registers(rg.ADDR_SERIAL, 2)
        return mb.words_to_u32(regs[1], regs[0]) if self.c.word_swap else mb.words_to_u32(regs[0], regs[1])

    # ------------------------------------------------------------------
    # 参数下发序列
    # ------------------------------------------------------------------

    def build_apply_ops(self,
                        mode_op: Optional[int] = None,
                        mode_ctrl: Optional[int] = None,
                        total_power: Optional[float] = None,
                        total_current: Optional[float] = None,
                        channel_power: Optional[Dict[int, float]] = None,
                        channel_current: Optional[Dict[int, float]] = None,
                        output_on: bool = True,
                        power_off_first: bool = True) -> List[tuple]:
        """构造"下发参数"的指令序列。

        顺序遵循手册与现场惯例：
            关闭输出 → 设操作模式 → 设控制模式 → 写总功率/总电流 → 写各通道参数 → 开启输出
        顺序错了设备可能拒写，或参数不生效。
        """
        ops: List[tuple] = []
        if power_off_first:
            ops.append(("w16", rg.ADDR_OUTPUT_CTRL, 0))
            ops.append(("sleep", 0.1))
        if mode_op is not None:
            ops.append(("w16", rg.ADDR_MODE_OP, mode_op))
        if mode_ctrl is not None:
            ops.append(("w16", rg.ADDR_MODE_CTRL, mode_ctrl))
        if total_power is not None:
            self._check("power", total_power)
            ops.append(("w32", rg.ADDR_POWER_TOTAL, rg.p2raw(total_power)))
        if total_current is not None:
            self._check("current", total_current)
            ops.append(("w32", rg.ADDR_CURRENT_TOTAL, rg.a2raw(total_current)))
        if channel_power:
            for ch in sorted(channel_power):
                self._check("power", channel_power[ch])
                ops.append(("w32", rg.ch_power_addr(ch), rg.p2raw(channel_power[ch])))
        if channel_current:
            for ch in sorted(channel_current):
                if ch not in rg.PHASE_CHANNELS:
                    raise RangeError("电流设定仅支持通道 1~3，当前 %s" % ch)
                self._check("current", channel_current[ch])
                ops.append(("w32", rg.phase_i_set_addr(ch), rg.a2raw(channel_current[ch])))
        if output_on:
            ops.append(("sleep", 0.1))
            ops.append(("w16", rg.ADDR_OUTPUT_CTRL, 1))
        return ops

    def run_ops(self, ops: List[tuple], on_log=None) -> None:
        """执行指令序列。可被工作线程直接调用。"""
        import time as _t
        for op in ops:
            kind = op[0]
            if kind == "w16":
                self.c.write_single(op[1], op[2])
                if on_log:
                    on_log("写寄存器 0x%02X ← %d" % (op[1], op[2]))
            elif kind == "w32":
                self.c.write_u32(op[1], op[2])
                if on_log:
                    on_log("写寄存器 0x%02X(32位) ← %d" % (op[1], op[2]))
            elif kind == "sleep":
                _t.sleep(op[1])
            elif kind == "clear_fault":
                self.clear_fault()
            else:
                raise ValueError("未知指令：%r" % (op,))
