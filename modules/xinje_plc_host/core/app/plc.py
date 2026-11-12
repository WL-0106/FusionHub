# -*- coding: utf-8 -*-
"""信捷 PLC 高层客户端：软元件名 → 读写。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .devices import DataType, ResolvedDevice, parse_device
from .modbus import (
    ModbusClient,
    ModbusConfig,
    ModbusError,
    ModbusTimeout,
)


@dataclass
class TagValue:
    """一个软元件的当前值。"""
    device: ResolvedDevice
    value: UnionBoolWord
    timestamp: float = field(default_factory=time.time)
    error: str = ""


# 值类型
UnionBoolWord = object  # bool | int


@dataclass
class PlcStatus:
    connected: bool = False
    series: str = "XD3"
    last_error: str = ""
    tx: int = 0
    rx: int = 0
    err: int = 0


class PlcClient:
    """面向软元件名（Y10 / D100）的读写封装。"""

    def __init__(self, series: str = "XD3"):
        self.modbus = ModbusClient()
        self.series = series
        self._resolve_cache: dict[str, ResolvedDevice] = {}
        self._lock = threading.RLock()

    # -- 连接 ------------------------------------------------------------
    def connect(self, config: ModbusConfig, series: Optional[str] = None) -> None:
        if series:
            self.series = series
        self.modbus.config = config
        self.modbus.connect()

    def disconnect(self) -> None:
        self.modbus.disconnect()

    @property
    def connected(self) -> bool:
        return self.modbus.connected

    def status(self) -> PlcStatus:
        s = self.modbus.stats
        return PlcStatus(
            connected=self.connected,
            series=self.series,
            last_error=s.last_err_msg,
            tx=s.tx, rx=s.rx, err=s.err,
        )

    # -- 解析 ------------------------------------------------------------
    def resolve(self, name: str) -> ResolvedDevice:
        key = name.strip().upper()
        with self._lock:
            if key not in self._resolve_cache:
                self._resolve_cache[key] = parse_device(name, self.series)
            return self._resolve_cache[key]

    def clear_cache(self) -> None:
        with self._lock:
            self._resolve_cache.clear()

    # -- 单点读写 --------------------------------------------------------
    def read_bit(self, name: str) -> bool:
        d = self.resolve(name)
        if d.kind != DataType.COIL and d.kind != DataType.DISCRETE_INPUT:
            raise ValueError(f"{name} 不是位元件")
        return self.read_bit_addr(d.modbus_addr, prefer_discrete=(d.prefix == "X"))

    def read_bit_addr(self, addr: int, prefer_discrete: bool = False) -> bool:
        """读单点。X 优先 02H 离散输入，失败/全灭再试 01H。"""
        if prefer_discrete:
            try:
                return self.modbus.read_discrete(addr, 1)[0]
            except Exception:
                return self.modbus.read_coils(addr, 1)[0]
        return self.modbus.read_coils(addr, 1)[0]

    def read_bits_block(self, start_addr: int, count: int,
                        prefer_discrete: bool = False) -> list[bool]:
        """读一段位。X 用 02H，其他用 01H；失败自动切换。"""
        if prefer_discrete:
            try:
                return self.modbus.read_discrete(start_addr, count)
            except Exception:
                return self.modbus.read_coils(start_addr, count)
        try:
            return self.modbus.read_coils(start_addr, count)
        except Exception:
            return self.modbus.read_discrete(start_addr, count)

    def write_bit(self, name: str, value: bool) -> None:
        d = self.resolve(name)
        if not d.writable:
            raise ValueError(f"{name} 只读")
        self.modbus.write_coil(d.modbus_addr, bool(value))

    def force_bit(self, name: str, value: bool) -> tuple[bool, str]:
        """强制写位并回读校验。

        策略：
        1. FC05 单线圈写
        2. FC0F 多线圈写（1 点，真正 0FH）
        3. 回读 01H/02H 校验
        返回 (是否成功, 日志详情)。
        """
        d = self.resolve(name)
        if not d.writable:
            raise ValueError(f"{name} 只读")
        addr = d.modbus_addr
        target = bool(value)
        attempts: list[str] = []

        ok05 = False
        try:
            self.modbus.write_coil(addr, target)
            attempts.append("FC05 OK")
            ok05 = True
        except Exception as e:
            attempts.append(f"FC05 失败: {e}")

        ok0f = False
        try:
            self.modbus.write_coils(addr, [target])
            attempts.append("FC0F OK")
            ok0f = True
        except Exception as e:
            attempts.append(f"FC0F 失败: {e}")

        if not ok05 and not ok0f:
            return False, f"{name} 强制失败 | " + " | ".join(attempts)

        # 回读校验（多次，给 PLC 扫描时间）
        prefer_disc = (d.prefix == "X")
        for i in range(4):
            try:
                actual = self.read_bit_addr(addr, prefer_discrete=prefer_disc)
                attempts.append(f"回读#{i+1}={actual}")
                if actual == target:
                    return True, (
                        f"{name} 强制成功 = {'ON' if target else 'OFF'} | "
                        + " | ".join(attempts)
                    )
            except Exception as e:
                attempts.append(f"回读#{i+1} 失败: {e}")
            import time
            time.sleep(0.03)

        return False, (
            f"{name} 写入后读回不一致（目标 {'ON' if target else 'OFF'}）| "
            + " | ".join(attempts)
            + " | 若确认程序未驱动该点，请试持续强制或 STOP 后再写"
        )

    def force_word(self, name: str, value: int) -> tuple[bool, str]:
        """写字并回读校验。"""
        d = self.resolve(name)
        if not d.writable:
            raise ValueError(f"{name} 只读")
        target = int(value) & 0xFFFF
        try:
            self.modbus.write_register(d.modbus_addr, target)
        except Exception as e:
            try:
                self.modbus.write_registers(d.modbus_addr, [target])
            except Exception as e2:
                return False, f"{name} 写入失败: {e} / {e2}"
        import time
        time.sleep(0.02)
        try:
            actual = self.modbus.read_holding(d.modbus_addr, 1)[0]
            ok = (actual == target)
            return ok, (
                f"{name} {'写入成功' if ok else '写入后读回不一致'} "
                f"目标={target} (0x{target:04X}) 读回={actual} (0x{actual:04X})"
            )
        except Exception as e:
            return True, f"{name} 已写入 {target}，回读失败: {e}"

    def toggle_bit(self, name: str) -> bool:
        cur = self.read_bit(name)
        self.write_bit(name, not cur)
        return not cur

    def read_word(self, name: str) -> int:
        d = self.resolve(name)
        if d.kind == DataType.INPUT_REGISTER:
            regs = self.modbus.read_input_regs(d.modbus_addr, 1)
        else:
            regs = self.modbus.read_holding(d.modbus_addr, 1)
        return regs[0]

    def write_word(self, name: str, value: int) -> None:
        d = self.resolve(name)
        if not d.writable:
            raise ValueError(f"{name} 只读")
        self.modbus.write_register(d.modbus_addr, int(value) & 0xFFFF)

    def read_dword(self, name: str) -> int:
        """读 32 位（Dn+Dn+1，低字在前）。"""
        d = self.resolve(name)
        regs = self.modbus.read_holding(d.modbus_addr, 2)
        return (regs[1] << 16) | regs[0]

    def write_dword(self, name: str, value: int) -> None:
        d = self.resolve(name)
        if not d.writable:
            raise ValueError(f"{name} 只读")
        value &= 0xFFFFFFFF
        lo = value & 0xFFFF
        hi = (value >> 16) & 0xFFFF
        self.modbus.write_registers(d.modbus_addr, [lo, hi])

    def read_float(self, name: str) -> float:
        """读 32 位 IEEE754 浮点（低字在前）。"""
        import struct
        d = self.resolve(name)
        regs = self.modbus.read_holding(d.modbus_addr, 2)
        raw = struct.pack("<HH", regs[0], regs[1])
        return struct.unpack("<f", raw)[0]

    def write_float(self, name: str, value: float) -> None:
        import struct
        d = self.resolve(name)
        if not d.writable:
            raise ValueError(f"{name} 只读")
        raw = struct.pack("<f", float(value))
        lo, hi = struct.unpack("<HH", raw)
        self.modbus.write_registers(d.modbus_addr, [lo, hi])

    # -- 批量读 ----------------------------------------------------------
    def read_many_bits(self, names: Sequence[str]) -> list[bool]:
        if not names:
            return []
        addrs = [self.resolve(n).modbus_addr for n in names]
        return self.modbus.read_device_bits(addrs)

    def diagnose(self) -> str:
        """通讯诊断：对关键地址做多种功能码探测，返回可读报告。"""
        lines: list[str] = ["=== 通讯诊断 ==="]
        probes = [
            ("M0-15 FC01", lambda: self.modbus.read_coils(0, 16)),
            ("X0-15 FC01", lambda: self.modbus.read_coils(0x5000, 16)),
            ("X0-15 FC02", lambda: self.modbus.read_discrete(0x5000, 16)),
            ("Y0-15 FC01", lambda: self.modbus.read_coils(0x6000, 16)),
            ("Y0-15 FC02", lambda: self.modbus.read_discrete(0x6000, 16)),
            ("D0-3 FC03", lambda: self.modbus.read_holding(0, 4)),
            ("D1000 FC03", lambda: self.modbus.read_holding(1000, 2)),
            ("QD0 FC03@6000", lambda: self.modbus.read_holding(0x6000, 2)),
            ("ID0 FC04@5000", lambda: self.modbus.read_input_regs(0x5000, 2)),
            ("HD0 FC03@A080", lambda: self.modbus.read_holding(0xA080, 2)),
        ]
        for title, fn in probes:
            try:
                val = fn()
                if val and isinstance(val[0], bool):
                    on = sum(1 for v in val if v)
                    bits = "".join("1" if v else "0" for v in val[:16])
                    lines.append(f"OK   {title:18s} ON={on}/16  [{bits}]")
                else:
                    lines.append(f"OK   {title:18s} {val}")
            except Exception as e:
                lines.append(f"FAIL {title:18s} {e}")
        return "\n".join(lines)

    def read_many_words(self, names: Sequence[str]) -> list[int]:
        if not names:
            return []
        addrs = [self.resolve(n).modbus_addr for n in names]
        return self.modbus.read_device_words(addrs)

    def read_range_bits(self, name: str, count: int) -> list[bool]:
        d = self.resolve(name)
        return self.read_bits_block(d.modbus_addr, count,
                                    prefer_discrete=(d.prefix == "X"))

    def read_range_words(self, name: str, count: int) -> list[int]:
        d = self.resolve(name)
        return self.modbus.read_holding(d.modbus_addr, count)

    def write_range_bits(self, name: str, values: Sequence[bool]) -> None:
        d = self.resolve(name)
        self.modbus.write_coils(d.modbus_addr, values)

    def write_range_words(self, name: str, values: Sequence[int]) -> None:
        d = self.resolve(name)
        self.modbus.write_registers(d.modbus_addr, values)
