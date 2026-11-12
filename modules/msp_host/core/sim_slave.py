# -*- coding: utf-8 -*-
"""模拟从站：按 MSP65/MSP62 寄存器表仿真设备应答，支持异常帧注入。

用途：
  - 无真机即可开发/回归协议栈与界面
  - 真机出问题时用相同故障模式复现，定位问题归属（协议栈 / 界面 / 设备）
故障注入模式（FaultMode）：
  NORMAL      正常应答
  BAD_CRC     应答 CRC 错误（协议栈应丢帧重同步并最终超时）
  NO_RESPONSE 不应答（模拟从站掉线 → 协议栈超时重发上限退出）
  DELAY       应答严重延迟（模拟慢从站 → 超时）
  EXCEPTION   返回异常响应（异常码可指定）
  SPLIT       应答拆成多段投递（模拟半包）
  GARBAGE     应答前混入垃圾字节（模拟粘包/错帧，协议栈应重同步）
"""
from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

from .modbus_rtu import (
    EXCEPTION_FLAG, FC_READ_RO, FC_READ_RW, FC_WRITE_MULTI, FC_WRITE_SINGLE,
    append_crc, build_read, build_write_multi, build_write_single, verify_crc,
)
from .registers import PROFILES, DeviceProfile


class FaultMode(enum.Enum):
    NORMAL = "正常"
    BAD_CRC = "CRC错误帧"
    NO_RESPONSE = "无响应(掉线)"
    DELAY = "响应延迟"
    EXCEPTION = "异常响应"
    SPLIT = "半包投递"
    GARBAGE = "粘包/垃圾字节"


@dataclass
class FaultConfig:
    mode: FaultMode = FaultMode.NORMAL
    exception_code: int = 0x02
    delay_s: float = 1.5
    split_chunk: int = 2          # SPLIT 模式每段字节数
    garbage: bytes = b"\x00\xFF\x55"
    apply_times: int = -1         # 生效次数，-1=持续生效；用完自动恢复 NORMAL


class SimulatedSlave:
    """寄存器级模拟从站。线程安全。"""

    def __init__(self, profile: DeviceProfile, addr: int = 1):
        self.profile = profile
        self.addr = addr
        self.regs: Dict[int, int] = {}
        self._lock = threading.Lock()
        self._fault = FaultConfig()
        self.last_fault = FaultConfig()
        self.requests_seen = 0
        self.responses_sent = 0
        self._init_registers()

    def _init_registers(self) -> None:
        # 只读区默认值：电压 30.000V(raw 30000 视小数位)、电流 5.000、功率 150、状态=输出启动|恒压
        defaults = {
            1000: 30000,
            1001: 5000,
            1002: 150,
            1003: 0b101,      # bit0 输出启动 + bit2 恒压
            1007: 0b101,
        }
        for r in self.profile.registers:
            if r.addr in defaults:
                self.regs[r.addr] = defaults[r.addr]
            else:
                self.regs[r.addr] = 0

    # ---------------- 故障注入 ----------------

    def set_fault(self, mode: FaultMode, *, exception_code: int = 0x02,
                  apply_times: int = -1, delay_s: float = 1.5,
                  split_chunk: int = 2, garbage: bytes = b"\x00\xFF\x55") -> None:
        self._fault = FaultConfig(mode=mode, exception_code=exception_code,
                                  apply_times=apply_times, delay_s=delay_s,
                                  split_chunk=split_chunk, garbage=garbage)

    def clear_fault(self) -> None:
        self._fault = FaultConfig()

    def _take_fault(self) -> FaultConfig:
        with self._lock:
            f = self._fault
            if f.apply_times > 0:
                f.apply_times -= 1
                if f.apply_times == 0:
                    self._fault = FaultConfig()
            elif f.apply_times == 0:
                self._fault = FaultConfig()
            return f

    # ---------------- 报文处理 ----------------

    def handle(self, data: bytes) -> Optional[bytes]:
        """主机请求 → 应答（bytes），None=不应答。"""
        fault = self._take_fault()
        self.last_fault = fault
        with self._lock:
            self.requests_seen += 1
        if fault.mode == FaultMode.NO_RESPONSE:
            return None

        # DELAY 故障的延迟由 make_loopback 异步送达实现（不阻塞发送方）
        resp = self._build_response(data)
        if resp is None:
            return None

        if fault.mode == FaultMode.EXCEPTION:
            resp = append_crc(bytes((data[0], data[1] | EXCEPTION_FLAG, fault.exception_code)))

        if fault.mode == FaultMode.BAD_CRC and len(resp) >= 2:
            resp = resp[:-2] + bytes((resp[-2] ^ 0xFF, resp[-1]))

        if fault.mode == FaultMode.GARBAGE:
            resp = fault.garbage + resp

        with self._lock:
            self.responses_sent += 1
        return resp

    def _build_response(self, req: bytes) -> Optional[bytes]:
        if len(req) < 4 or not verify_crc(req):
            return None        # 请求 CRC 错：模拟从站静默（符合 Modbus 惯例）
        addr, fc = req[0], req[1]
        if addr != self.addr and addr != 0:
            return None        # 非本机地址：静默

        if fc in (FC_READ_RW, FC_READ_RO):
            start = req[2] << 8 | req[3]
            count = req[4] << 8 | req[5]
            return self._read_response(addr, fc, start, count)
        if fc == FC_WRITE_SINGLE:
            reg = req[2] << 8 | req[3]
            val = req[4] << 8 | req[5]
            return self._write_response(addr, fc, reg, [val])
        if fc == FC_WRITE_MULTI:
            start = req[2] << 8 | req[3]
            count = req[4] << 8 | req[5]
            byte_count = req[6]
            if byte_count != count * 2:
                return append_crc(bytes((addr, fc | EXCEPTION_FLAG, 0x03)))
            values = [req[7 + i] << 8 | req[8 + i] for i in range(0, byte_count, 2)]
            return self._write_response(addr, fc, start, values)
        return append_crc(bytes((addr, fc | EXCEPTION_FLAG, 0x01)))

    def _read_response(self, addr: int, fc: int, start: int, count: int) -> bytes:
        if not (1 <= count <= 20):
            return append_crc(bytes((addr, fc | EXCEPTION_FLAG, 0x03)))
        # 手册：可读地址范围 1000~2022（按区间校验，未定义地址读回 0）
        if not (1000 <= start and start + count - 1 <= 2022):
            return append_crc(bytes((addr, fc | EXCEPTION_FLAG, 0x02)))
        with self._lock:
            values = [self.regs.get(a, 0) for a in range(start, start + count)]
        payload = bytes((addr, fc, count * 2))
        for v in values:
            payload += bytes(((v >> 8) & 0xFF, v & 0xFF))
        return append_crc(payload)

    def _write_response(self, addr: int, fc: int, start: int, values) -> bytes:
        # 手册：可写地址范围 2000~2022；只读区/越界 → 异常 0x02
        if not (2000 <= start and start + len(values) - 1 <= 2022):
            return append_crc(bytes((addr, fc | EXCEPTION_FLAG, 0x02)))
        with self._lock:
            for i, a in enumerate(range(start, start + len(values))):
                try:
                    rd = self.profile.reg(a)
                except KeyError:
                    rd = None
                if rd is not None and not rd.writable:
                    return append_crc(bytes((addr, fc | EXCEPTION_FLAG, 0x02)))   # 写只读区
                self.regs[a] = values[i]
        if fc == FC_WRITE_SINGLE:
            return append_crc(bytes((addr, fc, (start >> 8) & 0xFF, start & 0xFF,
                                    (values[0] >> 8) & 0xFF, values[0] & 0xFF)))
        return append_crc(bytes((addr, fc, (start >> 8) & 0xFF, start & 0xFF,
                                (len(values) >> 8) & 0xFF, len(values) & 0xFF)))

    # ---------------- 测试辅助 ----------------

    def preload(self, reg_values: Dict[int, int]) -> None:
        with self._lock:
            self.regs.update(reg_values)

    def snapshot(self) -> Dict[int, int]:
        with self._lock:
            return dict(self.regs)


def make_loopback(slave: SimulatedSlave):
    """构造对接模拟从站的 LoopbackTransport（SPLIT 故障时按块投递模拟半包）。"""
    from .transport import LoopbackTransport

    transport = LoopbackTransport(lambda data: None)

    def handler(data: bytes):
        resp = slave.handle(data)
        f = slave.last_fault
        if resp and f.mode == FaultMode.SPLIT:
            transport.chunk_size = max(1, f.split_chunk)
            transport.chunk_delay = 0.01
        else:
            transport.chunk_size = 0
            transport.chunk_delay = 0.0
        if resp and f.mode == FaultMode.DELAY:
            # 慢从站：延迟送达但不阻塞发送方（与真实串口行为一致）
            t = threading.Timer(f.delay_s, transport.feed, args=(resp,))
            t.daemon = True
            t.start()
            return None
        return resp

    transport._handler = handler
    return transport


if __name__ == "__main__":
    # 快速自检：回放手册范例帧
    import time
    from .transport import LoopbackTransport

    slave = SimulatedSlave(PROFILES["MSP65"], addr=1)
    t = LoopbackTransport(slave.handle)
    t.open()

    req = build_read(1, FC_READ_RO, 1000, 1)          # 手册范例 1：01 04 03 E8 00 01 B1 BA
    print("请求:", req.hex(" "))
    t.write(req)
    print("应答:", t.read(256, 0.2).hex(" "))

    req = build_write_multi(1, 2001, [0x8B10])         # 手册范例 2：01 10 07 D1 ...
    print("请求:", req.hex(" "))
    t.write(req)
    print("应答:", t.read(256, 0.2).hex(" "))
