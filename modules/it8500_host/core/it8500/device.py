"""设备高层 API: 请求/应答编排 + 各功能函数。"""
from __future__ import annotations

import time
from typing import Callable

from . import protocol as P
from .transport import Transport, TransportError


class Device:
    """线程不安全: 只应在设备工作线程中调用 (见 worker.py)。"""

    def __init__(self, transport: Transport, addr: int = 0,
                 timeout: float = 0.4, retries: int = 2,
                 on_tx: Callable[[bytes], None] | None = None,
                 on_rx: Callable[[bytes], None] | None = None):
        self.transport = transport
        self.addr = addr
        self.timeout = timeout
        self.retries = retries
        self.on_tx = on_tx
        self.on_rx = on_rx
        self._remote = False      # 已确认进入远程模式 (20H) 的缓存标志

    # ---------------------------------------------------------- 连接
    @property
    def connected(self) -> bool:
        return self.transport.is_open

    def connect(self) -> None:
        self.transport.open()

    def disconnect(self) -> None:
        self.transport.close()

    # ---------------------------------------------------------- 收发核心
    def _transact(self, cmd: int, data: bytes = b"",
                  accept: tuple[int, ...] | None = None) -> P.Frame:
        """发送一帧并等待匹配应答, 返回应答帧。"""
        frame = P.build_frame(self.addr, cmd, data)
        last_err: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                if self.on_tx:
                    self.on_tx(frame)
                self.transport.write_frame(frame)
                accept_cmds = accept or (cmd, P.Cmd.CHECK)
                deadline = time.monotonic() + self.timeout
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TransportError("等待应答超时")
                    resp = self.transport.read_frame(remaining)
                    if self.on_rx:
                        raw = P.build_frame(resp.addr, resp.cmd, resp.data)
                        self.on_rx(raw)
                    # 地址改写命令的应答可能来自新地址, 单独放行
                    if frame[2] == P.Cmd.ADDR_SET or resp.addr in (self.addr, 0xFE, frame[1]):
                        if resp.cmd in accept_cmds:
                            return resp
                    # 不匹配的帧(例如上一次超时后的迟到应答)直接丢弃
            except TransportError as e:
                last_err = e
        raise TransportError(f"命令 {cmd:02X}H 失败: {last_err}")

    def ensure_remote(self) -> None:
        """首次写参数前自动下发 20H 进入远程模式。

        手册: "若要通过 PC 控制负载, 必须首先设置负载为 PC 控制状态 (20H)";
        面板模式下设备对所有设置命令回 B0H。
        """
        if self._remote:
            return
        resp = self._transact(P.Cmd.CTRL_MODE_SET, bytes([1]),
                              accept=(P.Cmd.CHECK, P.Cmd.CTRL_MODE_SET))
        if resp.cmd == P.Cmd.CHECK and resp.status != P.STATUS_OK:
            raise P.DeviceError(resp.status)
        self._remote = True

    def set_param(self, cmd: int, data: bytes = b"") -> None:
        """发送设置命令并校验 12H 应答状态码。"""
        if cmd != P.Cmd.CTRL_MODE_SET:
            self.ensure_remote()
        # 应答可能为 12H 状态帧, 也可能回显原命令 (兼容两种写法)
        resp = self._transact(cmd, data, accept=(P.Cmd.CHECK, cmd))
        if resp.cmd == P.Cmd.CHECK:
            if resp.status != P.STATUS_OK:
                raise P.DeviceError(resp.status)
        if cmd == P.Cmd.CTRL_MODE_SET:
            self._remote = bool(data and data[0])

    def read_param(self, cmd: int, data: bytes = b"") -> bytes:
        accept = (cmd, P.Cmd.CHECK)
        if cmd == P.Cmd.IDENTITY:
            # 手册 3.3.22 示例中 6AH 应答的命令字为 31H, 一并接受
            accept = (cmd, P.Cmd.CHECK, 0x31)
        resp = self._transact(cmd, data, accept=accept)
        if resp.cmd == P.Cmd.CHECK:
            raise P.DeviceError(resp.status)
        return resp.data

    # ---------------------------------------------------------- 常规控制
    def set_remote(self, remote: bool = True) -> None:
        self.set_param(P.Cmd.CTRL_MODE_SET, bytes([1 if remote else 0]))

    def set_input(self, on: bool) -> None:
        self.set_param(0x21, bytes([1 if on else 0]))

    def set_load_mode(self, mode: int | str) -> None:
        self.set_param(0x28, P.encode_load_mode(mode))

    def get_load_mode(self) -> str:
        return P.decode_load_mode(self.read_param(0x29))

    def _rw_u32(self, set_cmd: int, get_cmd: int, value: float | None,
                unit: str) -> float:
        if value is not None:
            self.set_param(set_cmd, P.u32le(P.value_to_raw(value, unit)))
        return P.raw_to_value(P.u32_from(self.read_param(get_cmd)), unit)

    # 定值 (None = 只读)
    def set_cc(self, amps: float | None = None) -> float:
        return self._rw_u32(0x2A, 0x2B, amps, "A")

    def set_cv(self, volts: float | None = None) -> float:
        return self._rw_u32(0x2C, 0x2D, volts, "V")

    def set_cw(self, watts: float | None = None) -> float:
        return self._rw_u32(0x2E, 0x2F, watts, "W")

    def set_cr(self, ohms: float | None = None) -> float:
        return self._rw_u32(0x30, 0x31, ohms, "Ω")

    # 保护限值
    def set_ovp(self, volts: float | None = None) -> float:
        return self._rw_u32(0x22, 0x23, volts, "V")

    def set_ocp(self, amps: float | None = None) -> float:
        return self._rw_u32(0x24, 0x25, amps, "A")

    def set_opp(self, watts: float | None = None) -> float:
        return self._rw_u32(0x26, 0x27, watts, "W")

    # 拉载/卸载/电池
    def set_pullon(self, volts: float | None = None) -> float:
        return self._rw_u32(0x10, 0x11, volts, "V")

    def set_release(self, volts: float | None = None) -> float:
        return self._rw_u32(0x12, 0x13, volts, "V")

    def set_bat_min(self, volts: float | None = None) -> float:
        return self._rw_u32(0x4E, 0x4F, volts, "V")

    # ---------------------------------------------------------- 动态
    def set_dynamic(self, mode: str,
                    params: P.DynamicParams | None = None) -> P.DynamicParams:
        unit = {"CC": "A", "CV": "V", "CW": "W", "CR": "Ω"}[mode.upper()]
        set_cmd, get_cmd = P.DYN_CMDS[mode.upper()]
        if params is not None:
            self.set_param(set_cmd, P.encode_dynamic(params, unit))
        return P.decode_dynamic(self.read_param(get_cmd), unit)

    # ---------------------------------------------------------- LIST
    def set_list_mode(self, mode: int | str) -> None:
        self.set_param(0x3A, P.encode_load_mode(mode))

    def get_list_mode(self) -> str:
        return P.decode_load_mode(self.read_param(0x3B))

    def set_list_loop(self, repeat: bool) -> None:
        self.set_param(0x3C, bytes([1 if repeat else 0]))

    def get_list_loop(self) -> bool:
        return bool(self.read_param(0x3D)[0])

    def set_list_steps(self, count: int) -> None:
        self.set_param(0x3E, P.u16le(count))

    def get_list_steps(self) -> int:
        return int.from_bytes(self.read_param(0x3F)[0:2], "little")

    def set_list_step(self, mode: str, step: P.ListStep) -> None:
        unit = {"CC": "A", "CV": "V", "CW": "W", "CR": "Ω"}[mode.upper()]
        set_cmd, _ = P.LIST_STEP_CMDS[mode.upper()]
        self.set_param(set_cmd, P.encode_list_step(step, unit))

    def get_list_step(self, mode: str, index: int) -> P.ListStep:
        unit = {"CC": "A", "CV": "V", "CW": "W", "CR": "Ω"}[mode.upper()]
        _, get_cmd = P.LIST_STEP_CMDS[mode.upper()]
        data = P.u16le(index) + b"\x00" * (P.DATA_LEN - 2)
        return P.decode_list_step(self.read_param(get_cmd, data), unit)

    def set_list_filename(self, name: str) -> None:
        raw = name.encode("ascii", errors="ignore")[:10].ljust(10, b"\x00")
        self.set_param(0x48, raw)

    def get_list_filename(self) -> str:
        return self.read_param(0x49)[0:10].decode("ascii", errors="ignore").strip("\x00 ")

    def set_list_partition(self, mode: int) -> None:
        if mode not in (1, 2, 4, 8):
            raise P.DeviceError(0xA0)
        self.set_param(0x4A, bytes([mode]))

    def get_list_partition(self) -> int:
        return self.read_param(0x4B)[0]

    def save_list_file(self, area: int) -> None:
        self.set_param(0x4C, bytes([area]))

    def recall_list_file(self, area: int) -> None:
        self.set_param(0x4D, bytes([area]))

    # ---------------------------------------------------------- 系统
    def set_work_mode(self, mode: int | str) -> None:
        if isinstance(mode, str):
            rev = {v: k for k, v in P.WORK_MODES.items()}
            mode = rev[mode.upper()]
        self.set_param(0x5D, bytes([mode]))

    def get_work_mode(self) -> str:
        return P.WORK_MODES.get(self.read_param(0x5E)[0], "未知")

    def set_address(self, new_addr: int) -> None:
        self.set_param(0x54, bytes([new_addr]))
        self.addr = new_addr

    def set_local_key(self, enabled: bool) -> None:
        self.set_param(0x55, bytes([1 if enabled else 0]))

    def set_sense(self, enabled: bool) -> None:
        self.set_param(0x56, bytes([1 if enabled else 0]))

    def get_sense(self) -> bool:
        return bool(self.read_param(0x57)[0])

    def set_trigger_mode(self, mode: int) -> None:
        if mode not in (0, 1, 2):
            raise P.DeviceError(0xA0)
        self.set_param(0x58, bytes([mode]))

    def get_trigger_mode(self) -> int:
        return self.read_param(0x59)[0]

    def trigger_bus(self) -> None:
        self.set_param(0x5A)

    def set_timer(self, seconds: int | None = None) -> int:
        if seconds is not None:
            self.set_param(0x50, P.u16le(seconds))
        return int.from_bytes(self.read_param(0x51)[0:2], "little")

    def set_timer_enabled(self, enabled: bool) -> None:
        self.set_param(0x52, bytes([1 if enabled else 0]))

    def get_timer_enabled(self) -> bool:
        return bool(self.read_param(0x53)[0])

    def save_setup(self, area: int) -> None:
        self.set_param(0x5B, bytes([area]))

    def recall_setup(self, area: int) -> None:
        self.set_param(0x5C, bytes([area]))

    # ---------------------------------------------------------- 测量与信息
    def read_measurement(self) -> P.Measurement:
        return P.parse_measurement(self.read_param(0x5F))

    def read_identity(self) -> P.Identity:
        return P.parse_identity(self.read_param(P.Cmd.IDENTITY))

    def read_barcode(self) -> str:
        return P.parse_barcode(self.read_param(P.Cmd.BARCODE))
