"""自测模拟从站：NXR 充电模块行为模型。

同一套逻辑被两处复用：
- SimTransport（进程内直连，供 UI 离线演示 / 自动化测试）
- tools/sim_server.py（独立 TCP 服务器，说 UT-6502 13 字节协议，验证真实 TCP 链路）

行为对齐协议手册 V1.48：
- 读应答 41/42 + F0；写应答回显，被拒绝时回 F2（地址分配互锁、参数越界等）。
- 地址分配方式互锁：自动分配(0x1F=0)时通信设组号(0x1E)返回 F2。
- 输入模式状态机：设置需断电重启生效；不匹配置 Bit5；空余相带电置 Bit4 并强制关机。
- 过压复位(0x31) / 短路复位(0x44) 命令流程。
"""

import math
import random
import time

from . import protocol as P
from .registers import (
    POWER_ON, POWER_OFF, ADDR_MODE_AUTO, ADDR_MODE_DIP,
    INPUT_MODE_AC, INPUT_MODE_DC, LINE_SINGLE_PHASE, LINE_DC, LINE_THREE_PHASE,
    OVP_RESET_VALUE, SHORT_RESET_VALUE, ALTITUDE_MIN, ALTITUDE_MAX,
    STATUS_BIT_DETECT_ERROR, STATUS_BIT_MODE_MISMATCH,
    STATUS_BIT_OVP, STATUS_BIT_SHORT,
)

# 需要"读"的寄存器
READ_REGS = {0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0008, 0x000A, 0x000B,
             0x000C, 0x000D, 0x000E, 0x0010, 0x0011, 0x0012, 0x0040, 0x0043,
             0x0048, 0x004A, 0x004B, 0x0054, 0x0055, 0x0056, 0x0057}

FLOAT_READ = {0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0008, 0x000A, 0x000B,
              0x000C, 0x000D, 0x000E, 0x0010, 0x0011, 0x0012}


class SimModule:
    """单个模拟模块。"""

    def __init__(self, addr: int, group: int = 0):
        self.addr = addr
        self.group = group
        self.rated_power = 20000.0      # 20kW
        self.rated_current = 50.0       # 50A

        self.set_voltage = 500.0
        self.set_ratio = 0.5            # 限流点(0~1)
        self.set_power_ratio = 1.0
        self.ovp_point = 0.0
        self.ovp_related = False        # 0x3E: False=允许, True=禁止
        self.on = False

        # 地址分配
        self.addr_mode = ADDR_MODE_DIP

        # 输入模式状态机
        self.input_mode = INPUT_MODE_AC         # 当前生效模式
        self.pending_input_mode = None          # 已设置、待断电重启生效
        self.line_type = LINE_THREE_PHASE       # 实际接线类型
        self.idle_phase_live = False            # 空余相带电
        self.work_mode = 0x03                   # 0x4B 实际工作模式
        self.mode_mismatch = False              # Bit5
        self.detect_error = False               # Bit4

        # 保护
        self.ovp_tripped = False                # Bit31
        self.short_tripped = False              # Bit28

        self.altitude = 1000
        self.dcdc_ver = 1002
        self.pfc_ver = 607
        self.serial_lo = 0x10203040 + addr
        self.serial_hi = 0x00000001
        self._t0 = time.time()
        self._detect_input()

    # ------------------------------------------------------------ 内部量
    @property
    def allowed_current(self) -> float:
        return self.set_ratio * self.rated_current

    def _measured_voltage(self) -> float:
        if not self.on:
            return 0.0
        return self.set_voltage + random.uniform(-0.4, 0.4)

    def _measured_current(self) -> float:
        if not self.on:
            return 0.0
        base = self.allowed_current * 0.75
        return max(0.0, base + random.uniform(-0.3, 0.3))

    def _temp(self) -> float:
        base = 32.0 + (self.allowed_current * 0.25 if self.on else 0.0)
        return base + random.uniform(-0.5, 0.5)

    def _input_voltage(self) -> float:
        if self.input_mode == INPUT_MODE_DC or self.line_type == LINE_DC:
            return 540.0 + random.uniform(-1.0, 1.0)
        return 220.0 * math.sqrt(3) + random.uniform(-2.0, 2.0)  # 三相线电压

    def _phase_voltage(self, phase: int) -> float:
        """phase: 0=A, 1=B, 2=C。"""
        if self.input_mode == INPUT_MODE_DC or self.line_type == LINE_DC:
            return 0.0
        if self.line_type == LINE_THREE_PHASE:
            return 220.0 + random.uniform(-1.0, 1.0)
        # 单相：A 相带电，B/C 为空余相
        if phase == 0:
            return 220.0 + random.uniform(-1.0, 1.0)
        return 220.0 if self.idle_phase_live else 0.0

    def _input_power(self) -> int:
        if not self.on:
            return 0
        return int(self._measured_voltage() * self._measured_current())

    def status_word(self) -> int:
        s = 0
        if not self.on:
            s |= (1 << 22)
        if self.detect_error:
            s |= (1 << STATUS_BIT_DETECT_ERROR)
        if self.mode_mismatch:
            s |= (1 << STATUS_BIT_MODE_MISMATCH)
        if self.ovp_tripped:
            s |= (1 << STATUS_BIT_OVP)
        if self.short_tripped:
            s |= (1 << STATUS_BIT_SHORT)
        return s

    # ------------------------------------------------------------ 状态机
    def _detect_input(self):
        """上电/重启后检测输入模式与实际接线是否匹配。"""
        if self.input_mode == INPUT_MODE_DC:
            self.work_mode = 0x02 if self.line_type == LINE_DC else 0x05
        elif self.line_type == LINE_DC:
            self.work_mode = 0x05
        elif self.line_type == LINE_SINGLE_PHASE:
            self.work_mode = 0x01
        else:
            self.work_mode = 0x03
        self.mode_mismatch = (self.work_mode == 0x05)
        # 单相/直流模式下本应空闲的相带电 -> Bit4
        self.detect_error = bool(
            self.idle_phase_live
            and (self.work_mode == 0x01 or self.input_mode == INPUT_MODE_DC))
        if self.mode_mismatch or self.detect_error:
            self.on = False

    def power_cycle(self):
        """断电重启：应用待生效输入模式并重新检测输入。"""
        if self.pending_input_mode is not None:
            self.input_mode = self.pending_input_mode
            self.pending_input_mode = None
        self._detect_input()
        self.on = False

    def can_power_on(self) -> bool:
        return not (self.mode_mismatch or self.detect_error
                    or self.ovp_tripped or self.short_tripped)

    def trip_ovp(self):
        self.ovp_tripped = True
        self.on = False

    def trip_short(self):
        self.short_tripped = True
        self.on = False

    # ------------------------------------------------------------ 请求处理
    def handle(self, can_id: int, data: bytes):
        """处理一条来自监控的请求，返回 (resp_can_id, resp_data) 或 None。"""
        cid = P.parse_id(can_id)
        if not self._addressed(cid):
            return None
        if len(data) < 4:
            return None
        func = data[0]
        reg = (data[2] << 8) | data[3]
        payload = bytes(data[4:8]).ljust(4, b"\x00")

        if func == P.FUNC_READ:
            if reg not in READ_REGS:
                return self._reply(reg, P.RESP_INT, payload)
            if reg in FLOAT_READ:
                val = float(self._read_float(reg))
                return self._reply(reg, P.RESP_FLOAT, struct_pack_f(val))
            val = int(self._read_int(reg))
            return self._reply(reg, P.RESP_INT, struct_pack_i(val))

        if func == P.FUNC_SET:
            err = self._write(reg, payload)
            return self._reply(reg, P.RESP_INT, payload, err=err)

        return None

    # ------------------------------------------------------------ 寻址判断
    def _addressed(self, cid: P.CanId) -> bool:
        if cid.dst == P.ADDR_BROADCAST:
            return True
        if cid.dst == P.ADDR_GROUP_BROADCAST and self.group <= P.GROUP_MAX \
                and cid.group == self.group:
            return True
        if self.group > P.GROUP_MAX and cid.dst == P.ADDR_GROUP_EXT_BASE - self.group:
            return True
        return cid.dst == self.addr

    def _reply(self, reg: int, resp_type: int, raw4: bytes, err: int = P.ERR_OK):
        resp_id = P.make_id(P.PTP_POINT, P.ADDR_MONITOR, self.addr, self.group & 0x07)
        data = bytes([resp_type, err]) + bytes([(reg >> 8) & 0xFF, reg & 0xFF]) + raw4
        return resp_id, data

    # ------------------------------------------------------------ 读
    def _read_float(self, reg: int) -> float:
        return {
            0x0001: self._measured_voltage(),
            0x0002: self._measured_current(),
            0x0003: self.set_ratio,
            0x0004: self._temp(),
            0x0005: self._input_voltage(),
            0x0008: self.set_voltage * 0.5 if self.on else 0.0,
            0x000A: self.set_voltage * 0.5 if self.on else 0.0,
            0x000B: self._temp() - 3.0,
            0x000C: self._phase_voltage(0),
            0x000D: self._phase_voltage(1),
            0x000E: self._phase_voltage(2),
            0x0010: self._temp() + 2.0,
            0x0011: self.rated_power,
            0x0012: self.rated_current,
        }.get(reg, 0.0)

    def _read_int(self, reg: int) -> int:
        return {
            0x0040: self.status_word(),
            0x0043: self.addr,                    # 拨码地址
            0x0048: self._input_power(),
            0x004A: self.altitude,
            0x004B: self.work_mode,
            0x0054: self.serial_lo,
            0x0055: self.serial_hi,
            0x0056: self.dcdc_ver,
            0x0057: self.pfc_ver,
        }.get(reg, 0)

    # ------------------------------------------------------------ 写（返回错误码）
    def _write(self, reg: int, payload: bytes) -> int:
        if reg == 0x0021:
            self.set_voltage = struct_unpack_f(payload)
        elif reg == 0x0022:
            self.set_ratio = max(0.0, min(1.0, struct_unpack_f(payload)))
        elif reg == 0x0020:
            self.set_power_ratio = struct_unpack_f(payload)
        elif reg == 0x0023:
            self.ovp_point = struct_unpack_f(payload)
        elif reg == 0x001B:
            amps = struct_unpack_i(payload) / 1024.0
            self.set_ratio = max(0.0, min(1.0, amps / self.rated_current))
        elif reg == 0x0030:
            want_on = (struct_unpack_i(payload) == POWER_ON)
            if want_on and not self.can_power_on():
                return P.ERR_FAIL
            self.on = want_on
        elif reg == 0x001E:
            # 地址分配方式互锁：自动分配时通信设组号无效
            if self.addr_mode == ADDR_MODE_AUTO:
                return P.ERR_FAIL
            self.group = struct_unpack_i(payload) & 0x07
        elif reg == 0x001F:
            v = struct_unpack_i(payload)
            if v not in (ADDR_MODE_AUTO, ADDR_MODE_DIP):
                return P.ERR_FAIL
            self.addr_mode = v
        elif reg == 0x0017:
            v = struct_unpack_i(payload)
            if not (ALTITUDE_MIN <= v <= ALTITUDE_MAX):
                return P.ERR_FAIL
            self.altitude = v
        elif reg == 0x0046:
            v = struct_unpack_i(payload)
            if v not in (INPUT_MODE_AC, INPUT_MODE_DC):
                return P.ERR_FAIL
            self.pending_input_mode = v       # 断电重启后生效
        elif reg == 0x003E:
            self.ovp_related = (struct_unpack_i(payload) != 0)
        elif reg == 0x0031:
            if struct_unpack_i(payload) == OVP_RESET_VALUE:
                self.ovp_tripped = False
        elif reg == 0x0044:
            if struct_unpack_i(payload) == SHORT_RESET_VALUE:
                self.short_tripped = False
        # 其它寄存器按手册为只读/保留，忽略
        return P.ERR_OK


def struct_pack_f(v: float) -> bytes:
    import struct
    return struct.pack(">f", float(v))


def struct_pack_i(v: int) -> bytes:
    import struct
    return struct.pack(">I", int(v) & 0xFFFFFFFF)


def struct_unpack_f(b: bytes) -> float:
    import struct
    return struct.unpack(">f", bytes(b[:4]))[0]


def struct_unpack_i(b: bytes) -> int:
    import struct
    return struct.unpack(">I", bytes(b[:4]))[0]


class SimBus:
    """一组模拟模块，模拟总线上"广播会引发多模块应答"的行为。"""

    def __init__(self, addrs=None):
        addrs = addrs if addrs is not None else [1, 2, 3]
        self.modules = {a: SimModule(a) for a in addrs}

    def add(self, addr: int, group: int = 0):
        self.modules[addr] = SimModule(addr, group)

    def remove(self, addr: int):
        self.modules.pop(addr, None)

    def dispatch(self, can_id: int, data: bytes):
        """返回该请求对应的所有应答 [(can_id, data), ...]。"""
        out = []
        for m in list(self.modules.values()):
            r = m.handle(can_id, data)
            if r:
                out.append(r)
        return out