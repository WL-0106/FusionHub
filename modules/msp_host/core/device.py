# -*- coding: utf-8 -*-
"""设备语义层：界面唯一依赖的接口。

界面只调用「读电压 / 写设定值 / 启停输出」等语义方法，不接触帧字节；
所有寄存器地址、量纲换算均从 registers.py（单一事实源）派生。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .modbus_rtu import build_read, build_write_multi, build_write_single
from .protocol_stack import Command, CommandFailed, ModbusRTUStack, StackState
from .registers import (
    KIND_BITFIELD, KIND_ENUM, DeviceProfile, ScaleConfig,
    physical_to_raw, raw_to_physical, resolve_scale,
)
from .transport import ITransport


@dataclass
class Measurement:
    voltage: Optional[float] = None       # V
    current: Optional[float] = None       # A
    power: Optional[float] = None         # W
    status_raw: Optional[int] = None
    status_text: List[str] = field(default_factory=list)
    timestamp: float = 0.0


def decode_bits(bits_def, raw: int) -> List[str]:
    """按寄存器表位定义解码状态字；手册未定义的位不猜测。"""
    out = []
    for b in bits_def:
        val = (raw >> b.bit) & 1
        meaning = b.mean1 if val else b.mean0
        if meaning and meaning != "预留":
            out.append(f"{b.name}: {meaning}")
    return out


class PowerSupplyDevice:
    """直流电源语义接口（MSP65 / MSP62 通用，按 DeviceProfile 区分映射）。"""

    def __init__(self, stack: ModbusRTUStack, profile: DeviceProfile, *,
                 addr: int = 1, scale_cfg: Optional[ScaleConfig] = None):
        self.stack = stack
        self.profile = profile
        self.addr = addr
        self.scale_cfg = scale_cfg or ScaleConfig()
        # 设定值寄存器对：默认 2001/2002；MSP62 存在同名的 2021/2022（遗留问题 3），可切换
        self.setpoint_regs: Tuple[int, int] = (profile.setpoint_v_reg, profile.setpoint_i_reg)
        self.measurement = Measurement()

    @property
    def scale(self) -> Dict[str, float]:
        """换算档位实时从 scale_cfg 推导——配置改动立即生效，无需重连。"""
        return resolve_scale(self.profile, self.scale_cfg)

    def set_scale_cfg(self, cfg: ScaleConfig) -> None:
        self.scale_cfg = cfg

    # ---------------- 底层收发（内部） ----------------

    def _read_regs(self, name: str, start: int, count: int, use_ro_fc: bool) -> List[int]:
        fc = self.profile.read_only_fc if use_ro_fc else self.profile.read_writable_fc
        cmd = Command(name, build_read(self.addr, fc, start, count), self.addr, fc)
        resp = self.stack.transact(cmd)
        return resp.values

    def _write_regs(self, name: str, start: int, values: List[int]) -> None:
        req = (build_write_single(self.addr, start, values[0]) if len(values) == 1
               else build_write_multi(self.addr, start, values))
        cmd = Command(name, req, self.addr, req[1])
        self.stack.transact(cmd)

    # ---------------- 语义接口：测量 ----------------

    def read_measurement(self) -> Measurement:
        """一次批量读测量块（≤20 寄存器，地址连续），必要时补读状态寄存器。"""
        p = self.profile
        start, count = p.measure_block
        values = self._read_regs(f"读测量值({start}~{start + count - 1})", start, count,
                                use_ro_fc=True)
        regs = {start + i: v for i, v in enumerate(values)}

        m = Measurement(timestamp=time.time())
        m.voltage = raw_to_physical("voltage", regs[1000], self.scale)
        m.current = raw_to_physical("current", regs[1001], self.scale)
        if p.has_power_meter and 1002 in regs:
            m.power = raw_to_physical("power", regs[1002], self.scale)

        if p.status_is_contiguous and p.status_reg in regs:
            m.status_raw = regs[p.status_reg]
        else:
            st = self._read_regs("读设备状态", p.status_reg, 1, use_ro_fc=True)
            m.status_raw = st[0]
        m.status_text = decode_bits(p.reg(p.status_reg).bits, m.status_raw)

        self.measurement = m
        return m

    def read_status_text(self) -> List[str]:
        raw = self._read_regs("读设备状态", self.profile.status_reg, 1, use_ro_fc=True)[0]
        return decode_bits(self.profile.reg(self.profile.status_reg).bits, raw)

    # ---------------- 语义接口：设定 ----------------

    def set_setpoint(self, voltage: Optional[float] = None,
                     current: Optional[float] = None) -> None:
        """写电压/电流设定值（物理量，自动按小数位换算）。两寄存器连续则合并一帧。"""
        v_reg, i_reg = self.setpoint_regs
        start = min(v_reg, i_reg)
        cur = self._read_regs("读当前设定值", start, 2, use_ro_fc=False)
        raws = list(cur)
        if voltage is not None:
            raws[v_reg - start] = self._to_raw("voltage", voltage)
        if current is not None:
            raws[i_reg - start] = self._to_raw("current", current)
        s = self.scale
        self._write_regs(
            f"写设定值 V={voltage} I={current} → 寄存器{v_reg}/{i_reg} "
            f"raw={raws}（换算 V×10^{s['voltage_decimals']} I×10^{s['current_decimals']}）",
            start, raws)

    def set_ovp(self, voltage: float) -> None:
        self._write_regs(f"写过压值 {voltage}V", self.profile.ovp_reg,
                         [self._to_raw("voltage", voltage)])

    def set_ocp(self, current: float) -> None:
        self._write_regs(f"写过流值 {current}A", self.profile.ocp_reg,
                         [self._to_raw("current", current)])

    def output_on(self) -> None:
        self._write_regs("启动输出", self.profile.output_ctrl_reg, [1])

    def output_off(self) -> None:
        self._write_regs("停止输出", self.profile.output_ctrl_reg, [0])

    # ---------------- 语义接口：寄存器（表驱动，供调试/验证） ----------------

    def read_register(self, addr: int) -> int:
        rd = self.profile.reg(addr)
        fc = self.profile.read_only_fc if rd.access == "R" else self.profile.read_writable_fc
        return self._read_regs(f"读寄存器 {addr}({rd.name})", addr, 1,
                              use_ro_fc=(rd.access == "R"))[0]

    def read_register_physical(self, addr: int) -> float:
        rd = self.profile.reg(addr)
        return raw_to_physical(rd.kind, self.read_register(addr), self.scale)

    def write_register(self, addr: int, value: int) -> None:
        rd = self.profile.reg(addr)
        if not rd.writable:
            raise CommandFailed(f"寄存器 {addr}({rd.name}) 为只读，禁止写入")
        self._write_regs(f"写寄存器 {addr}({rd.name})={value}", addr, [value])

    def write_register_physical(self, addr: int, phys: float) -> None:
        rd = self.profile.reg(addr)
        self.write_register(addr, self._to_raw(rd.kind, phys))

    def _to_raw(self, kind: str, phys: float) -> int:
        raw = physical_to_raw(kind, phys, self.scale)
        if not (0 <= raw <= 0xFFFF):
            raise CommandFailed(f"设定值 {phys} 换算后 {raw} 超出寄存器范围 0~65535，请检查小数位配置")
        return raw


# ----------------------------------------------------------------------------
# 轮询器：界面刷新频率不高于串口吞吐，防止队列堆积假死
# ----------------------------------------------------------------------------

class Poller:
    """定时批量读测量值；上一周期未完成则跳过本轮（不堆积命令）。"""

    def __init__(self, device: PowerSupplyDevice, interval_s: float = 0.5,
                 on_measurement: Optional[Callable[[Measurement], None]] = None,
                 on_error: Optional[Callable[[Exception], None]] = None):
        self.device = device
        self.interval_s = max(0.2, interval_s)   # 刷新周期下限 200ms
        self.on_measurement = on_measurement
        self.on_error = on_error
        self._timer: Optional[threading.Timer] = None
        self._busy = False
        self._running = False

    def start(self) -> None:
        self._running = True
        self._schedule(0.05)

    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule(self, delay: float) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(delay, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
        if not self._running:
            return
        if self._busy or self.device.stack.pending > 0:
            self._schedule(self.interval_s)     # 跳过本轮，防止队列堆积
            return
        self._busy = True

        def work():
            try:
                m = self.device.read_measurement()
                if self.on_measurement:
                    self.on_measurement(m)
            except Exception as e:  # noqa: BLE001
                if self.on_error:
                    self.on_error(e)
            finally:
                self._busy = False
                self._schedule(self.interval_s)

        threading.Thread(target=work, name="poller", daemon=True).start()
