# -*- coding: utf-8 -*-
"""
HSPY 电源模拟器（无硬件调试用）
================================
实现一个最小可用的 Modbus-RTU 从机，行为与《HSPY大功率通讯协议(2020)》一致，
用于在没有实物电源时联调上位机界面。

对外暴露与 pyserial.Serial 相同的最小接口：write / read / close / is_open，
可直接替换真实串口使用（见 HspyDevice.SimulatedTransport）。
"""

from __future__ import annotations

import random
import threading
import time

from .HspyProtocol import (
    ADDR_BASE,
    FC_READ_HOLDING,
    FC_WRITE_MULTI,
    FC_WRITE_SINGLE,
    append_crc,
    reg,
    verify_crc,
)

# 模拟电源的默认额定值（界面选择机型预设后会自动跟随）
RATED_VOLTAGE = 60.0     # 额定电压 V
RATED_CURRENT = 10.0     # 额定电流 A
RATED_POWER = 600.0      # 额定功率 W
LOAD_OHMS = None         # 模拟负载电阻 Ω；None = 按额定值自动推算
SETTLE_SECONDS = 0.35    # 输出跟随设定值的过渡时间（模拟真实响应）


class HspySimulator:
    """HSPY 电源虚拟从机。

    额定值可现场切换（对应「机型预设」）：不同机型的电压/电流上限不同，
    仿真出来的读数、限流(CC)门限也会跟着变，这样选 HSPY-1000-01 或
    HSPY-30-20 时演示曲线才有意义。
    """

    def __init__(self, slave: int = 1, *, noise: bool = True,
                 rated_voltage: float = RATED_VOLTAGE,
                 rated_current: float = RATED_CURRENT,
                 rated_power: float = RATED_POWER,
                 load_ohms: float = LOAD_OHMS):
        self.slave = slave
        self.noise = noise
        self.set_rating(rated_voltage, rated_current, rated_power, load_ohms)
        self._lock = threading.Lock()
        self._rx = bytearray()      # 收到的请求字节
        self._out = bytearray()     # 待发出的响应字节
        self._created = time.time()
        self.is_open = True

        # 寄存器镜像（原始值）
        self.regs = {ADDR_BASE + i: 0 for i in range(0x18)}
        self.regs[ADDR_BASE + 0x00] = 0        # Set-U 0.00V
        self.regs[ADDR_BASE + 0x01] = 0        # Set-I 0.000A
        self.regs[ADDR_BASE + 0x04] = 0        # Run-Stop 停止
        self.regs[ADDR_BASE + 0x05] = slave    # RS-Adder
        self.regs[ADDR_BASE + 0x07] = 0        # Set-P
        self.regs[ADDR_BASE + 0x09] = 0        # MODE
        self.regs[ADDR_BASE + 0x0A] = 0        # Up_Start
        self.regs[ADDR_BASE + 0x0B] = 1        # AUTO_Err
        self.regs[ADDR_BASE + 0x0C] = 0        # RS_BT 9600
        self.regs[ADDR_BASE + 0x0D] = 2        # RS_Stop_Bit
        self.regs[ADDR_BASE + 0x0F] = 1        # DOWN_SAVE
        self.regs[ADDR_BASE + 0x14] = reg('ovp').to_raw(self.rated_voltage)   # OVP
        self.regs[ADDR_BASE + 0x15] = reg('ocp').to_raw(self.rated_current)   # OCP
        self._out_on = False
        self._out_started = 0.0

    # ------------------------------------------------------------------ #
    # 额定值（机型预设）
    # ------------------------------------------------------------------ #
    def set_rating(self, rated_voltage=None, rated_current=None,
                   rated_power=None, load_ohms=None) -> None:
        """切换仿真机型的额定值。负载未指定时按额定值自动推算：
        满载电压下电流约为额定的 30%，即落在恒压(CV)区，曲线好看也好读。
        """
        if rated_voltage is not None and rated_voltage > 0:
            self.rated_voltage = float(rated_voltage)
        else:
            self.rated_voltage = getattr(self, 'rated_voltage', RATED_VOLTAGE)
        if rated_current is not None and rated_current > 0:
            self.rated_current = float(rated_current)
        else:
            self.rated_current = getattr(self, 'rated_current', RATED_CURRENT)
        if rated_power is not None and rated_power > 0:
            self.rated_power = float(rated_power)
        else:
            self.rated_power = getattr(self, 'rated_power', RATED_POWER)

        if load_ohms is not None and load_ohms > 0:
            self.load_ohms = float(load_ohms)
        else:
            self.load_ohms = max(self.rated_voltage /
                                 max(self.rated_current * 0.3, 1e-9), 1e-3)

        # OVP / OCP 门限跟随机型
        try:
            if hasattr(self, 'regs'):
                self.regs[ADDR_BASE + 0x14] = reg('ovp').to_raw(self.rated_voltage)
                self.regs[ADDR_BASE + 0x15] = reg('ocp').to_raw(self.rated_current)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 串口接口
    # ------------------------------------------------------------------ #
    def write(self, data: bytes) -> int:
        with self._lock:
            self._rx.extend(data)
            self._process()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            out = bytes(self._out[:size])
            del self._out[:size]
            return out

    @property
    def in_waiting(self) -> int:
        return len(self._out)

    def close(self) -> None:
        self.is_open = False

    def reset_input_buffer(self) -> None:
        with self._lock:
            self._rx.clear()
            self._out.clear()

    # ------------------------------------------------------------------ #
    # 报文处理
    # ------------------------------------------------------------------ #
    def _process(self) -> None:
        # 逐帧解析（Modbus-RTU 无长度字段，按功能码推断整帧长度）
        while True:
            buf = bytes(self._rx)
            if len(buf) < 4:
                return
            fc = buf[1]
            if fc == FC_READ_HOLDING:
                need = 8
            elif fc in (FC_WRITE_SINGLE,):
                need = 8
            elif fc == FC_WRITE_MULTI:
                need = 9 + buf[6] if len(buf) > 6 else 9
            else:
                need = 8
            if len(buf) < need:
                return
            frame = buf[:need]
            del self._rx[:need]
            if not verify_crc(frame):
                continue                      # CRC 错，丢弃，不响应
            if frame[0] not in (self.slave, 0):
                continue                      # 非本机地址
            resp = self._handle(frame)
            if resp:
                self._out.extend(resp)

    def _handle(self, frame: bytes) -> bytes:
        fc = frame[1]
        addr = (frame[2] << 8) | frame[3]

        if fc == FC_READ_HOLDING:
            count = (frame[4] << 8) | frame[5]
            if not 1 <= count <= 125 or addr + count > 0xFFFF:
                return self._exc(fc, 0x02)
            values = []
            for i in range(count):
                values.append(self._read_reg(addr + i))
            payload = bytearray((self.slave, FC_READ_HOLDING, count * 2))
            for v in values:
                payload.append((v >> 8) & 0xFF)
                payload.append(v & 0xFF)
            return append_crc(bytes(payload))

        if fc == FC_WRITE_SINGLE:
            value = (frame[4] << 8) | frame[5]
            self._write_reg(addr, value)
            return append_crc(bytes((self.slave, FC_WRITE_SINGLE,
                                     frame[2], frame[3], frame[4], frame[5])))

        if fc == FC_WRITE_MULTI:
            count = (frame[4] << 8) | frame[5]
            for i in range(count):
                hi = frame[7 + i * 2]
                lo = frame[8 + i * 2]
                self._write_reg(addr + i, (hi << 8) | lo)
            return append_crc(bytes((self.slave, FC_WRITE_MULTI,
                                     frame[2], frame[3], frame[4], frame[5])))

        return self._exc(fc, 0x01)

    def _exc(self, fc: int, code: int) -> bytes:
        return append_crc(bytes((self.slave, fc | 0x80, code)))

    # ------------------------------------------------------------------ #
    # 寄存器读写（含物理量仿真）
    # ------------------------------------------------------------------ #
    def _read_reg(self, addr: int) -> int:
        if addr in (ADDR_BASE + 0x02, ADDR_BASE + 0x03,
                    ADDR_BASE + 0x08, ADDR_BASE + 0x0E):
            return self._measure(addr)
        return self.regs.get(addr, 0)

    def _write_reg(self, addr: int, value: int) -> None:
        if addr in (ADDR_BASE + 0x05,):        # 改从机地址
            self.slave = value & 0xFF
        self.regs[addr] = value & 0xFFFF
        if addr == ADDR_BASE + 0x04:           # 输出开关
            new_on = bool(value & 1)
            if new_on and not self._out_on:
                self._out_started = time.time()
            self._out_on = new_on

    def _measure(self, addr: int) -> int:
        """根据设定值 + 输出状态，仿真出电压 / 电流 / 功率 / CC-CV 的测量值。

        换算关系直接走协议层的 reg()，因此界面里改了小数位 / 量程后，
        仿真值与显示值依然保持一致，方便联调。
        """
        set_u = reg('set_u').to_physical(self.regs.get(ADDR_BASE + 0x00, 0))   # V
        set_i = reg('set_i').to_physical(self.regs.get(ADDR_BASE + 0x01, 0))   # A

        if not self._out_on:
            return 0

        # 上电软启动过渡
        t = min(1.0, (time.time() - self._out_started) / SETTLE_SECONDS)
        set_u *= t
        set_i *= t

        # 负载模型：恒阻负载 R = load_ohms
        #   需求电流 <= 限流设定 -> CV 恒压
        #   需求电流 >  限流设定 -> CC 恒流，电压被拉低
        i_need = set_u / self.load_ohms if self.load_ohms > 0 else 0.0
        if i_need <= set_i:
            cc = False
            u, i = set_u, i_need
        else:
            cc = True
            i = set_i
            u = i * self.load_ohms

        u = max(0.0, min(self.rated_voltage, u))
        i = max(0.0, min(self.rated_current, i))
        if self.noise:
            u += random.uniform(-0.003, 0.003) * max(1.0, u)
            i += random.uniform(-0.003, 0.003) * max(0.02, i)

        if addr == ADDR_BASE + 0x02:
            return reg('u').to_raw(u)
        if addr == ADDR_BASE + 0x03:
            return reg('i').to_raw(i)
        if addr == ADDR_BASE + 0x08:
            return reg('p').to_raw(u * i)
        if addr == ADDR_BASE + 0x0E:
            return 1 if cc else 0
        return 0
