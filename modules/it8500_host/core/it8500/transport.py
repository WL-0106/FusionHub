"""传输层: 真实串口 (pyserial) 与内置模拟设备。"""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod

from . import protocol as P


class TransportError(Exception):
    """传输层错误 (断线/超时等)。"""


# 模拟器识别的命令全集: 读命令在面板模式下放行, 写命令需远程模式 (真机行为)
READ_CMDS = {0x11, 0x13, 0x23, 0x25, 0x27, 0x29, 0x2B, 0x2D, 0x2F, 0x31,
             0x33, 0x35, 0x37, 0x39, 0x3B, 0x3D, 0x3F, 0x41, 0x43, 0x45,
             0x47, 0x49, 0x4B, 0x4F, 0x51, 0x53, 0x57, 0x59, 0x5E, 0x5F,
             0x6A, 0x6B}
WRITE_CMDS = {0x10, 0x12, 0x20, 0x21, 0x22, 0x24, 0x26, 0x28, 0x2A, 0x2C,
              0x2E, 0x30, 0x32, 0x34, 0x36, 0x38, 0x3A, 0x3C, 0x3E, 0x40,
              0x42, 0x44, 0x46, 0x48, 0x4A, 0x4C, 0x4D, 0x4E, 0x50, 0x52,
              0x54, 0x55, 0x56, 0x58, 0x5A, 0x5B, 0x5C, 0x5D}
KNOWN_CMDS = READ_CMDS | WRITE_CMDS


class Transport(ABC):
    """统一的帧收发接口。"""

    name: str = ""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @abstractmethod
    def write_frame(self, raw: bytes) -> None: ...

    @abstractmethod
    def read_frame(self, timeout: float) -> P.Frame:
        """读取一个校验通过的完整帧, 超时抛 TransportError。"""


def _extract_frame(buf: bytearray,
                   junk: bytearray | None = None) -> P.Frame | None:
    """从缓冲区中扫描并取出第一个合法帧; 被丢弃的脏字节记入 junk。"""
    def drop(n: int) -> None:
        if junk is not None and n:
            junk.extend(buf[:n])
        del buf[:n]

    while True:
        try:
            idx = buf.index(P.SYNC)
        except ValueError:
            drop(len(buf))
            return None
        if idx:
            drop(idx)                 # 同步头之前的垃圾字节
        if len(buf) < P.FRAME_LEN:
            return None
        candidate = bytes(buf[:P.FRAME_LEN])
        try:
            frame = P.parse_frame(candidate)
        except P.ProtocolError:
            drop(1)                   # 假同步头, 丢弃后继续扫描
            continue
        del buf[:P.FRAME_LEN]         # 合法帧, 不算垃圾
        return frame


class SerialTransport(Transport):
    """真实串口 (IT-E121/122/123 转换后的 COM 口)。"""

    def __init__(self, port: str, baud: int = 9600,
                 on_raw=None):
        self.port = port
        self.baud = baud
        self.name = port
        self.on_raw = on_raw           # Callable[[bytes], None]: 未解析字节回调
        self._ser = None
        self._buf = bytearray()

    def _raw(self, data: bytes) -> None:
        if self.on_raw and data:
            try:
                self.on_raw(bytes(data))
            except Exception:  # noqa: BLE001
                pass

    def open(self) -> None:
        import serial  # 延迟导入, 协议测试不依赖 pyserial
        try:
            self._ser = serial.Serial(
                port=self.port, baudrate=self.baud, bytesize=8,
                parity="N", stopbits=1, timeout=0.02,
            )
        except Exception as e:  # noqa: BLE001
            raise TransportError(f"打开串口 {self.port} 失败: {e}") from e
        self._buf.clear()
        self._ser.reset_input_buffer()

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def write_frame(self, raw: bytes) -> None:
        if not self.is_open:
            raise TransportError("串口未连接")
        try:
            self._ser.write(raw)
            self._ser.flush()
        except Exception as e:  # noqa: BLE001
            raise TransportError(f"串口写入失败: {e}") from e

    def read_frame(self, timeout: float) -> P.Frame:
        if not self.is_open:
            raise TransportError("串口未连接")
        deadline = time.monotonic() + timeout
        junk = bytearray()
        while True:
            frame = _extract_frame(self._buf, junk)
            if frame is not None:
                self._raw(bytes(junk))     # 解析成功, 但把途中的脏字节报出去
                return frame
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # 超时: 缓冲区里未拼成帧的残留也报出去 (波特率错/线路干扰的关键线索)
                junk.extend(self._buf)
                self._buf.clear()
                self._raw(bytes(junk))
                if junk:
                    preview = P.hexdump(bytes(junk[:40]))
                    more = f" …共{len(junk)}字节" if len(junk) > 40 else ""
                    raise TransportError(
                        f"接收超时: 未收到有效应答帧, 但缓冲区收到 {len(junk)} "
                        f"字节(疑似波特率不匹配/线路干扰): {preview}{more}")
                raise TransportError("接收超时: 未收到有效应答帧 (线上无任何字节)")
            try:
                chunk = self._ser.read(max(1, min(64, int(remaining * 1000))))
            except Exception as e:  # noqa: BLE001
                raise TransportError(f"串口读取失败: {e}") from e
            if chunk:
                self._buf.extend(chunk)


class SimulatedLoad:
    """模拟的 IT8500 负载状态机 (无硬件时的联调/自检用)。"""

    def __init__(self, model: str = "8512", serial_no: str = "000045",
                 source_voltage: float = 12.5, remote: bool = False):
        self.addr = 0
        self.source_voltage = source_voltage
        self.model = model
        self.serial_no = serial_no
        self.version = "V2.03"
        self.barcode = "001004152409002010"
        self.remote = remote           # 真机开机即面板模式 (REMOTE=0)
        self.input_on = False
        self.load_mode = 0              # CC
        self.work_mode = 0              # FIXED
        self.sense = 0
        self.local_key = 1
        self.trigger_mode = 0
        self.timer_en = 0
        self.timer_sec = 0
        # 定值
        self.cc = 1.0
        self.cv = 5.0
        self.cw = 10.0
        self.cr = 10.0
        # 保护
        self.ovp = 30.0
        self.ocp = 10.0
        self.opp = 300.0
        # 其它
        self.pullon = 8.0
        self.release = 4.0
        self.bat_min = 3.0
        self.dyn = {m: P.DynamicParams(1.0, 100.0, 2.0, 100.0, 0)
                    for m in ("CC", "CV", "CW", "CR")}
        self.list_mode = 0
        self.list_loop = 1
        self.list_steps = 4
        self.list_file = b"LIST0001".ljust(10, b"\x00")
        self.list_part = 1
        self.list = {m: [P.ListStep(i, float(i + 1), 100.0) for i in range(64)]
                     for m in ("CC", "CV", "CW", "CR")}
        self.setups = {}

    # ---------------------------------------------------------- 仿真测量
    def measure(self) -> P.Measurement:
        # 输出关断时, 输入端仍可测到源电压 (与真实负载一致)
        v = self.source_voltage
        i = 0.0
        op = 0
        q = 0
        if self.remote:
            op |= 1 << 2
        if self.local_key:
            op |= 1 << 4
        if self.sense:
            op |= 1 << 5
        if self.input_on:
            op |= 1 << 3
            v = self.source_voltage
            mode = self.load_mode
            if self.work_mode == 1:            # SHORT
                v, i = 0.02, self.source_voltage / 0.02
                q |= 1 << 6
            elif self.work_mode == 3:          # LIST: 简化为 CC 首步
                step = self.list[LOAD_KEY(mode)][0] if mode in (0, 1, 2, 3) else None
                if isinstance(step, P.ListStep):
                    i = step.value if mode == 0 else 1.0
                if mode == 0:
                    q |= 1 << 6
            elif mode == 0:                    # CC
                i = self.cc
                q |= 1 << 6
            elif mode == 1:                    # CV
                v = min(self.source_voltage, self.cv)
                i = max(0.0, (self.source_voltage - v) / 0.05)
                q |= 1 << 7
            elif mode == 2:                    # CW
                i = min(self.cw / max(v, 0.001), 40.0)
                q |= 1 << 8
            elif mode == 3:                    # CR
                i = v / max(self.cr, 0.001)
                q |= 1 << 9
            # 保护判定
            if v > self.ovp:
                q |= 1 << 1
            if i > self.ocp:
                q |= 1 << 2
            if v * i > self.opp:
                q |= 1 << 3
        # 微小噪声, 便于观察曲线
        v *= 1 + random.uniform(-0.001, 0.001)
        i *= 1 + random.uniform(-0.002, 0.002)
        p = v * i
        if i > 0.001 and q & 0x3C0 == 0:
            q |= 1 << 6
        return P.Measurement(voltage=v, current=i, power=p,
                             op_status=op, query_status=q)

    # ---------------------------------------------------------- 帧处理
    def handle(self, frame: P.Frame) -> P.Frame | None:
        """处理收到的命令帧, 返回应答帧 (无应答返回 None)。"""
        if frame.addr not in (self.addr, 0xFE):
            return None
        cmd, d = frame.cmd, frame.data
        if cmd not in KNOWN_CMDS:
            return self._status(0xC0)
        # 真机行为: 面板模式下除 20H 外的写命令一律回 B0H
        if cmd in WRITE_CMDS and cmd != 0x20 and not self.remote:
            return self._status(0xB0)
        set_pair = {
            0x20: self._set_remote, 0x21: self._set_input,
            0x22: lambda v: self._set_limit("ovp", v),
            0x24: lambda v: self._set_limit("ocp", v),
            0x26: lambda v: self._set_limit("opp", v),
            0x28: self._set_load_mode,
            0x2A: lambda v: self._set_val("cc", v),
            0x2C: lambda v: self._set_val("cv", v),
            0x2E: lambda v: self._set_val("cw", v),
            0x30: lambda v: self._set_val("cr", v),
            0x10: lambda v: self._set_val("pullon", v),
            0x12: lambda v: self._set_val("release", v),
            0x4E: lambda v: self._set_val("bat_min", v),
            0x54: self._set_addr, 0x55: self._set_local_key,
            0x56: self._set_sense, 0x58: self._set_trigger,
            0x5D: self._set_work_mode,
            0x50: self._set_timer_sec, 0x52: self._set_timer_en,
        }
        if cmd in set_pair:
            return self._ack(cmd, set_pair[cmd](d))
        if cmd in (0x32, 0x34, 0x36, 0x38):     # 动态参数设置
            return self._ack(cmd, self._set_dynamic(cmd, d))
        if cmd == 0x3A:                          # LIST 模式
            return self._ack(cmd, self._set_int("list_mode", d, 0, 3))
        if cmd == 0x3C:
            return self._ack(cmd, self._set_int("list_loop", d, 0, 1))
        if cmd == 0x3E:
            return self._ack(cmd, self._set_int("list_steps", d, 1, 65535, u16=True))
        if cmd in (0x40, 0x42, 0x44, 0x46):
            return self._ack(cmd, self._set_list_step(cmd, d))
        if cmd == 0x48:
            self.list_file = bytes(d[0:10])
            return self._ack(cmd, 0x80)
        if cmd == 0x4A:
            if d[0] not in (1, 2, 4, 8):
                return self._status(0xA0)
            self.list_part = d[0]
            return self._ack(cmd, 0x80)
        if cmd == 0x4C:
            return self._ack(cmd, 0x80 if 1 <= d[0] <= 8 else 0xA0)
        if cmd == 0x4D:
            return self._ack(cmd, 0x80 if 1 <= d[0] <= 8 else 0xA0)
        if cmd == 0x5B:
            self.setups[d[0]] = True
            return self._ack(cmd, 0x80)
        if cmd == 0x5C:
            return self._ack(cmd, 0x80 if d[0] in self.setups else 0xA0)
        if cmd == 0x5A:                          # BUS 触发
            return self._ack(cmd, 0x80)

        # ---------------- 读取命令 ----------------
        if cmd == 0x20:
            return self._resp(cmd, bytes([1 if self.remote else 0]))
        if cmd == 0x21:
            return self._resp(cmd, bytes([1 if self.input_on else 0]))
        if cmd in (0x23, 0x25, 0x27):
            key = {0x23: "ovp", 0x25: "ocp", 0x27: "opp"}[cmd]
            unit = {0x23: "V", 0x25: "A", 0x27: "W"}[cmd]
            return self._resp(cmd, P.u32le(P.value_to_raw(getattr(self, key), unit)))
        if cmd == 0x29:
            return self._resp(cmd, bytes([self.load_mode]))
        if cmd in (0x2B, 0x2D, 0x2F, 0x31):
            key, unit = {0x2B: ("cc", "A"), 0x2D: ("cv", "V"),
                         0x2F: ("cw", "W"), 0x31: ("cr", "Ω")}[cmd]
            return self._resp(cmd, P.u32le(P.value_to_raw(getattr(self, key), unit)))
        if cmd in (0x11, 0x13, 0x4F):
            key = {0x11: "pullon", 0x13: "release", 0x4F: "bat_min"}[cmd]
            return self._resp(cmd, P.u32le(P.value_to_raw(getattr(self, key), "V")))
        if cmd in (0x33, 0x35, 0x37, 0x39):
            mode, unit = DYN_KEY[cmd]
            return self._resp(cmd, P.encode_dynamic(self.dyn[mode], unit))
        if cmd == 0x3B:
            return self._resp(cmd, bytes([self.list_mode]))
        if cmd == 0x3D:
            return self._resp(cmd, bytes([self.list_loop]))
        if cmd == 0x3F:
            return self._resp(cmd, P.u16le(self.list_steps))
        if cmd in (0x41, 0x43, 0x45, 0x47):
            mode, unit = STEP_KEY[cmd]
            step = P.ListStep(int.from_bytes(d[0:2], "little"), 0.0, 0.0)
            real = self.list[mode][step.index % len(self.list[mode])]
            return self._resp(cmd, P.encode_list_step(real, unit))
        if cmd == 0x49:
            return self._resp(cmd, self.list_file)
        if cmd == 0x4B:
            return self._resp(cmd, bytes([self.list_part]))
        if cmd == 0x51:
            return self._resp(cmd, P.u16le(self.timer_sec))
        if cmd == 0x53:
            return self._resp(cmd, bytes([self.timer_en]))
        if cmd == 0x57:
            return self._resp(cmd, bytes([self.sense]))
        if cmd == 0x59:
            return self._resp(cmd, bytes([self.trigger_mode]))
        if cmd == 0x5E:
            return self._resp(cmd, bytes([self.work_mode]))
        if cmd == 0x5F:
            m = self.measure()
            data = (P.u32le(P.volts_to_raw(m.voltage))
                    + P.u32le(P.amps_to_raw(m.current))
                    + P.u32le(P.watts_to_raw(m.power))
                    + bytes([m.op_status])
                    + P.u16le(m.query_status))
            return self._resp(cmd, data)
        if cmd == 0x6A:
            data = bytearray(22)
            model = self.model.encode("ascii")[:5].ljust(5, b"\x00")
            data[0:5] = model
            hi, lo = self.version.lstrip("V").split(".")
            data[5] = int(lo, 16) & 0xFF
            data[6] = int(hi, 16) & 0xFF
            data[7:17] = self.serial_no.encode("ascii")[:10].ljust(10, b"\x00")
            return self._resp(cmd, bytes(data))
        if cmd == 0x6B:
            data = bytearray(22)
            raw = self.barcode.encode("ascii")[:19]
            data[0:len(raw)] = raw
            return self._resp(cmd, bytes(data))
        if cmd == 0x12:
            return self._resp(cmd, bytes([0x80]))
        return self._status(0xC0)                 # 无效命令

    # ---------------------------------------------------------- 内部
    def _resp(self, cmd: int, data: bytes) -> P.Frame:
        return P.Frame(self.addr, cmd, bytes(data).ljust(P.DATA_LEN, b"\x00"))

    def _status(self, code: int) -> P.Frame:
        return P.Frame(self.addr, P.Cmd.CHECK, bytes([code]).ljust(P.DATA_LEN, b"\x00"))

    def _ack(self, cmd: int, code: int) -> P.Frame:
        return self._status(code)

    def _set_remote(self, d: bytes) -> int:
        self.remote = bool(d[0])
        return 0x80

    def _set_input(self, d: bytes) -> int:
        if d[0] not in (0, 1):
            return 0xA0
        self.input_on = bool(d[0])
        return 0x80

    def _set_limit(self, key: str, d: bytes) -> int:
        unit = {"ovp": "V", "ocp": "A", "opp": "W"}[key]
        setattr(self, key, P.raw_to_value(P.u32_from(d), unit))
        return 0x80

    def _set_val(self, key: str, d: bytes) -> int:
        unit = {"cc": "A", "cv": "V", "cw": "W", "cr": "Ω",
                "pullon": "V", "release": "V", "bat_min": "V"}[key]
        setattr(self, key, P.raw_to_value(P.u32_from(d), unit))
        return 0x80

    def _set_load_mode(self, d: bytes) -> int:
        if d[0] not in (0, 1, 2, 3):
            return 0xA0
        self.load_mode = d[0]
        return 0x80

    def _set_work_mode(self, d: bytes) -> int:
        if d[0] not in (0, 1, 2, 3, 4):
            return 0xA0
        self.work_mode = d[0]
        return 0x80

    def _set_addr(self, d: bytes) -> int:
        if d[0] > 0xFE:
            return 0xA0
        self.addr = d[0]
        return 0x80

    def _set_local_key(self, d: bytes) -> int:
        self.local_key = d[0]
        return 0x80

    def _set_sense(self, d: bytes) -> int:
        self.sense = d[0]
        return 0x80

    def _set_trigger(self, d: bytes) -> int:
        if d[0] not in (0, 1, 2):
            return 0xA0
        self.trigger_mode = d[0]
        return 0x80

    def _set_timer_sec(self, d: bytes) -> int:
        self.timer_sec = int.from_bytes(d[0:2], "little")
        return 0x80

    def _set_timer_en(self, d: bytes) -> int:
        if d[0] not in (0, 1):
            return 0xA0
        self.timer_en = d[0]
        return 0x80

    def _set_int(self, key: str, d: bytes, lo: int, hi: int,
                 u16: bool = False) -> int:
        val = int.from_bytes(d[0:2], "little") if u16 else d[0]
        if not lo <= val <= hi:
            return 0xA0
        setattr(self, key, val)
        return 0x80

    def _set_dynamic(self, cmd: int, d: bytes) -> int:
        mode = {0x32: "CC", 0x34: "CV", 0x36: "CW", 0x38: "CR"}[cmd]
        unit = {"CC": "A", "CV": "V", "CW": "W", "CR": "Ω"}[mode]
        self.dyn[mode] = P.decode_dynamic(d, unit)
        return 0x80

    def _set_list_step(self, cmd: int, d: bytes) -> int:
        mode, unit = STEP_KEY[cmd + 1]
        step = P.decode_list_step(d, unit)
        if step.index >= len(self.list[mode]):
            return 0xA0
        self.list[mode][step.index] = step
        return 0x80


DYN_KEY = {0x33: ("CC", "A"), 0x35: ("CV", "V"), 0x37: ("CW", "W"), 0x39: ("CR", "Ω")}
STEP_KEY = {0x41: ("CC", "A"), 0x43: ("CV", "V"), 0x45: ("CW", "W"), 0x47: ("CR", "Ω")}


def LOAD_KEY(mode_id: int) -> str:
    return P.LOAD_MODES.get(mode_id, "CC")


class SimTransport(Transport):
    """把帧直接送进 SimulatedLoad 的回环传输。"""

    def __init__(self, load: SimulatedLoad | None = None):
        self.load = load or SimulatedLoad()
        self.name = "模拟设备"
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write_frame(self, raw: bytes) -> None:
        if not self._open:
            raise TransportError("模拟设备未启动")
        try:
            frame = P.parse_frame(raw)
        except P.ProtocolError as e:
            raise TransportError(str(e)) from e
        self._pending = self.load.handle(frame)

    def read_frame(self, timeout: float) -> P.Frame:
        if not self._open:
            raise TransportError("模拟设备未启动")
        resp = getattr(self, "_pending", None)
        if resp is None:
            raise TransportError("接收超时: 未收到有效应答帧")
        self._pending = None
        return resp


def enumerate_ports() -> list[tuple[str, str]]:
    """返回 [(设备名, 描述)], 用于界面下拉框。"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        label = p.device
        if p.description and p.description != "n/a":
            label += f" — {p.description}"
        out.append((p.device, label))
    return out
