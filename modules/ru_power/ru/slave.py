# -*- coding: utf-8 -*-
"""RU 灵巧系列电源 —— 从站模拟器核心。

用途：没有真实设备时把上位机跑通、做回归测试。
维护真实的寄存器映射，Uint32 不需要（本设备寄存器全是 16 位），
但线圈、离散输入、保持寄存器、输入寄存器四个地址空间彼此独立，必须分开存。
"""

import struct
import threading

from .crc import append_crc, check_crc
from .modbus import (
    EXCEPTION_TEXT,
    FC_READ_COILS,
    FC_READ_DISCRETE,
    FC_READ_HOLDING,
    FC_READ_INPUT,
    FC_WRITE_COIL,
    FC_WRITE_COILS,
    FC_WRITE_REG,
    FC_WRITE_REGS,
    hexs,
)

EX_ILLEGAL_FUNCTION = 0x01
EX_ILLEGAL_ADDRESS = 0x02
EX_ILLEGAL_VALUE = 0x03
EX_SLAVE_FAILURE = 0x04


class RegisterSpace:
    def __init__(self, init=None):
        self._d = dict(init or {})

    def has(self, addr):
        return addr in self._d

    def get(self, addr, default=0):
        return self._d.get(addr, default)

    def set(self, addr, value):
        self._d[addr] = int(value) & 0xFFFF

    def defadd(self, addr, value):
        self._d.setdefault(addr, int(value) & 0xFFFF)


class RUSlave:
    """一个模拟的 RU 电源从站（单机，地址可配）。"""

    def __init__(self, unit_id=1, v_decimals=1, i_decimals=2,
                 rated_v=100.0, rated_i=5.0, load_ohm=100.0):
        self.unit_id = unit_id
        self.v_decimals = v_decimals
        self.i_decimals = i_decimals
        self.rated_v = rated_v
        self.rated_i = rated_i
        self.load_ohm = load_ohm

        self.discrete = RegisterSpace({
            116: 0, 117: 1, 120: 0, 121: 0, 122: 0,
        })
        self.coils = RegisterSpace({
            133: 0, 134: 0, 136: 1, 137: 1, 141: 0,
            142: 0, 144: 0, 145: 0, 146: 0, 147: 0,
        })
        self.holding = RegisterSpace({
            148: unit_id,
            149: 0, 150: 0,
            156: 0, 157: 0, 158: 0, 186: 0,
        })
        self.input = RegisterSpace({
            100: 0, 101: 0,
            103: self._enc(rated_v, v_decimals),
            104: self._enc(rated_i, i_decimals),
            106: v_decimals, 107: i_decimals,
            144: 0x0100,
        })
        self.exchange_log = []
        self._ovp_latch = False
        self._ocp_latch = False
        self._lock = threading.Lock()
        self._refresh()

    # ---------- 内部 ----------
    def _enc(self, value, dec):
        return int(round(value * (10 ** dec))) & 0xFFFF

    def _dec(self, raw, dec):
        return raw / (10.0 ** dec)

    def _signed(self, raw):
        raw &= 0xFFFF
        return raw - 0x10000 if raw >= 0x8000 else raw

    def _refresh(self):
        """根据输出开关 / 设定值 / 负载，算出回读值与状态位。

        保护状态是锁存的：一旦触发就保持置位并切断输出，
        直到主机显式关闭输出（写线圈 133 = 0）才清除。
        """
        on = bool(self.coils.get(133))
        if self._ovp_latch or self._ocp_latch:
            on = False
            self.coils.set(133, 0)

        if not on:
            v_out, i_out = 0.0, 0.0
            cc, cv = 0, 0
        else:
            v_set = self._dec(self.holding.get(149), self.v_decimals)
            i_set = self._signed(self.holding.get(150)) / (10.0 ** self.i_decimals)
            polarity = -1.0 if i_set < 0 else 1.0
            limit = abs(i_set)
            want = v_set * polarity
            load_i = abs(want) / self.load_ohm if self.load_ohm > 0 else 0.0
            if load_i >= limit:
                i_out = limit * polarity
                v_out = (limit * self.load_ohm) * polarity
                cc, cv = 1, 0
            else:
                i_out = load_i * polarity
                v_out = want
                cc, cv = 0, 1

        # 保护判定（触发后锁存并切断输出）
        if on:
            ovp_val = self._dec(self.holding.get(157), self.v_decimals)
            ocp_val = self._dec(self.holding.get(158), self.i_decimals)
            if self.coils.get(136) and ovp_val > 0 and abs(v_out) > ovp_val:
                self._ovp_latch = True
            if self.coils.get(137) and ocp_val > 0 and abs(i_out) > ocp_val:
                self._ocp_latch = True
            if self._ovp_latch or self._ocp_latch:
                v_out, i_out, cc, cv = 0.0, 0.0, 0, 0
                self.coils.set(133, 0)

        self.input.set(100, self._enc(abs(v_out), self.v_decimals))
        self.input.set(101, self._enc(abs(i_out), self.i_decimals))
        self.discrete.set(116, cc)
        self.discrete.set(117, cv)
        self.discrete.set(120, 1 if self._ovp_latch else 0)
        self.discrete.set(121, 1 if self._ocp_latch else 0)
        self.discrete.set(122, 0)

    def _clear_latches(self):
        self._ovp_latch = False
        self._ocp_latch = False

    # ---------- 协议 ----------
    def _exc(self, fc, code):
        return bytes([fc | 0x80, code])

    def handle_pdu(self, pdu: bytes) -> bytes:
        if len(pdu) < 1:
            return b""
        fc = pdu[0]
        with self._lock:
            self._refresh()
            try:
                return self._dispatch(fc, pdu)
            except Exception:
                return self._exc(fc, EX_SLAVE_FAILURE)

    def _dispatch(self, fc, pdu):
        if fc in (FC_READ_COILS, FC_READ_DISCRETE):
            if len(pdu) != 5:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            addr, count = struct.unpack(">HH", pdu[1:5])
            if not 1 <= count <= 2000:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            space = self.coils if fc == FC_READ_COILS else self.discrete
            bits = []
            for i in range(count):
                a = addr + i
                if not space.has(a):
                    return self._exc(fc, EX_ILLEGAL_ADDRESS)
                bits.append(bool(space.get(a)))
            nbytes = (count + 7) // 8
            packed = bytearray(nbytes)
            for i, b in enumerate(bits):
                if b:
                    packed[i // 8] |= 1 << (i % 8)
            return bytes([fc, nbytes]) + bytes(packed)

        if fc in (FC_READ_HOLDING, FC_READ_INPUT):
            if len(pdu) != 5:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            addr, count = struct.unpack(">HH", pdu[1:5])
            if not 1 <= count <= 125:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            space = self.holding if fc == FC_READ_HOLDING else self.input
            vals = []
            for i in range(count):
                a = addr + i
                if not space.has(a):
                    return self._exc(fc, EX_ILLEGAL_ADDRESS)
                vals.append(space.get(a))
            return bytes([fc, count * 2]) + struct.pack(">" + "H" * count, *vals)

        if fc == FC_WRITE_COIL:
            if len(pdu) != 5:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            addr, val = struct.unpack(">HH", pdu[1:5])
            if val not in (0x0000, 0xFF00):
                return self._exc(fc, EX_ILLEGAL_VALUE)
            if not self.coils.has(addr):
                return self._exc(fc, EX_ILLEGAL_ADDRESS)
            self.coils.set(addr, 1 if val == 0xFF00 else 0)
            if addr == 133 and val == 0x0000:
                self._clear_latches()
            self._refresh()
            return pdu[:5]

        if fc == FC_WRITE_REG:
            if len(pdu) != 5:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            addr, val = struct.unpack(">HH", pdu[1:5])
            if not self.holding.has(addr):
                return self._exc(fc, EX_ILLEGAL_ADDRESS)
            if addr == 148 and not 1 <= val <= 255:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            self.holding.set(addr, val)
            if addr == 148:
                self.unit_id = val
            self._refresh()
            return pdu[:5]

        if fc == FC_WRITE_COILS:
            if len(pdu) < 6:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            addr, count, bc = struct.unpack(">HHB", pdu[1:6])
            if bc != (count + 7) // 8 or len(pdu) != 6 + bc:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            data = pdu[6:]
            for i in range(count):
                a = addr + i
                if not self.coils.has(a):
                    return self._exc(fc, EX_ILLEGAL_ADDRESS)
                self.coils.set(a, 1 if data[i // 8] & (1 << (i % 8)) else 0)
            if addr <= 133 < addr + count and not self.coils.get(133):
                self._clear_latches()
            self._refresh()
            return struct.pack(">BHH", fc, addr, count)

        if fc == FC_WRITE_REGS:
            if len(pdu) < 6:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            addr, count, bc = struct.unpack(">HHB", pdu[1:6])
            if bc != count * 2 or len(pdu) != 6 + bc:
                return self._exc(fc, EX_ILLEGAL_VALUE)
            vals = struct.unpack(">" + "H" * count, pdu[6:])
            for i, v in enumerate(vals):
                a = addr + i
                if not self.holding.has(a):
                    return self._exc(fc, EX_ILLEGAL_ADDRESS)
                if a == 148 and not 1 <= v <= 255:
                    return self._exc(fc, EX_ILLEGAL_VALUE)
            for i, v in enumerate(vals):
                self.holding.set(addr + i, v)
            self._refresh()
            return struct.pack(">BHH", fc, addr, count)

        return self._exc(fc, EX_ILLEGAL_FUNCTION)

    def handle_frame(self, frame: bytes):
        """处理整帧（含 CRC），返回响应帧 bytes 或 None（广播/无效帧不响应）。"""
        self.exchange_log.append(("RX", hexs(frame)))
        if len(frame) < 4 or not check_crc(frame):
            return None
        unit = frame[0]
        if unit == 0:
            # 广播：执行但不占用总线应答（与标准 Modbus 从站行为一致）
            self.handle_pdu(frame[1:-2])
            return None
        if unit != self.unit_id:
            return None
        resp_pdu = self.handle_pdu(frame[1:-2])
        if not resp_pdu:
            return None
        resp = append_crc(bytes([self.unit_id]) + resp_pdu)
        self.exchange_log.append(("TX", hexs(resp)))
        return resp
