# -*- coding: utf-8 -*-
"""三种传输通道：串口（RS232 / USB-CDC）、TCP（LAN）、内置演示模拟器。

手册依据（GDM-9060/9061 使用手册 P205~P240）：
  * RS232：D-sub 9pin，115200/57600/38400/19200/9600，8 数据位，无校验，1 停止位
  * USB：Type-B device 口，可配置为 USBTMC 或 USBCDC（CDC 在 PC 上表现为虚拟串口）
  * LAN：以太网口，SCPI 走 TCP，默认 TCP Port 3001（Telnet 端口 3000）
  * EOL：LF / CR / CR+LF 均可
"""
from __future__ import annotations

import random
import socket
import threading
import time
from collections import deque

try:                      # pyserial 为可选依赖：没有它也能用 TCP/演示模式
    import serial
    from serial.tools import list_ports
    HAS_SERIAL = True
except Exception:         # pragma: no cover
    serial = None
    list_ports = None
    HAS_SERIAL = False


class TransportError(Exception):
    """传输层异常（端口占用、连接失败、超时等）。"""


def list_serial_ports():
    """返回 [(设备名, 描述), ...]。"""
    if not HAS_SERIAL:
        return []
    out = []
    try:
        for p in list_ports.comports():
            desc = p.description or ""
            if desc and desc != "n/a":
                out.append((p.device, f"{p.device} · {desc}"))
            else:
                out.append((p.device, p.device))
    except Exception:
        pass
    return out


class Transport:
    """传输基类。"""

    kind = "base"
    name = "未连接"

    def __init__(self):
        self._lock = threading.Lock()

    # -- 需要子类实现 --------------------------------------------------
    def _open(self):
        raise NotImplementedError

    def _close(self):
        raise NotImplementedError

    def _write(self, text: str):
        raise NotImplementedError

    def _read_line(self, timeout: float) -> str:
        raise NotImplementedError

    def _read_raw(self, n: int, timeout: float) -> bytes:
        raise NotImplementedError

    # -- 对外接口 ------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return getattr(self, "_open_flag", False)

    def open(self):
        with self._lock:
            self._open()
            self._open_flag = True

    def close(self):
        with self._lock:
            try:
                self._close()
            finally:
                self._open_flag = False

    def write(self, text: str):
        if not self.is_open:
            raise TransportError("通道未打开")
        with self._lock:
            self._write(text)

    def readline(self, timeout: float = 1.5) -> str:
        if not self.is_open:
            raise TransportError("通道未打开")
        with self._lock:
            return self._read_line(timeout)

    def read_raw(self, n: int, timeout: float = 3.0) -> bytes:
        if not self.is_open:
            raise TransportError("通道未打开")
        with self._lock:
            return self._read_raw(n, timeout)


# --------------------------------------------------------------------------
# 串口（RS232 / USB-CDC 虚拟串口）
# --------------------------------------------------------------------------
class SerialTransport(Transport):
    kind = "serial"

    def __init__(self, port: str, baud: int = 115200, eol: str = "\r\n"):
        super().__init__()
        if not HAS_SERIAL:
            raise TransportError("缺少 pyserial 库，无法使用串口（可改用 TCP 或演示模式）")
        self.port = port
        self.baud = int(baud)
        self.eol = eol
        self._ser = None
        self.name = f"{port} @ {baud}"

    def _open(self):
        try:
            self._ser = serial.Serial(self.port, self.baud, bytesize=8,
                                      parity="N", stopbits=1,
                                      timeout=0.05, write_timeout=2.0)
        except Exception as exc:
            raise TransportError(f"打开串口失败：{exc}") from exc
        # 部分 USB-CDC 需要一点时间稳定
        time.sleep(0.05)
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass

    def _close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def _write(self, text: str):
        self._ser.write((text + self.eol).encode("ascii", "replace"))
        self._ser.flush()

    def _read_line(self, timeout: float) -> str:
        ser = self._ser
        end = time.time() + timeout
        buf = bytearray()
        while time.time() < end:
            chunk = ser.read(1)
            if chunk:
                if chunk in (b"\n", b"\r"):
                    if buf:
                        break
                    continue
                buf.extend(chunk)
                if len(buf) > 65536:
                    break
            elif buf:
                break
        return buf.decode("ascii", "replace").strip()

    def _read_raw(self, n: int, timeout: float) -> bytes:
        ser = self._ser
        end = time.time() + timeout
        buf = bytearray()
        while len(buf) < n and time.time() < end:
            chunk = ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
        return bytes(buf)


# --------------------------------------------------------------------------
# TCP（LAN，默认端口 3001）
# --------------------------------------------------------------------------
class TcpTransport(Transport):
    kind = "tcp"

    def __init__(self, host: str, port: int = 3001, eol: str = "\n", timeout: float = 3.0):
        super().__init__()
        self.host = host
        self.port = int(port)
        self.eol = eol
        self.timeout = timeout
        self._sock = None
        self._buf = bytearray()
        self.name = f"{host}:{port}"

    def _open(self):
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._sock.settimeout(0.1)
        except Exception as exc:
            raise TransportError(f"连接 {self.host}:{self.port} 失败：{exc}") from exc
        self._buf = bytearray()

    def _close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _write(self, text: str):
        self._sock.sendall((text + self.eol).encode("ascii", "replace"))

    def _fill(self, deadline: float):
        while time.time() < deadline:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                continue
            except Exception as exc:
                raise TransportError(f"网络读取失败：{exc}") from exc
            if not chunk:
                raise TransportError("连接已被仪器关闭")
            self._buf.extend(chunk)
            return True
        return False

    def _read_line(self, timeout: float) -> str:
        end = time.time() + timeout
        while b"\n" not in self._buf:
            if not self._fill(end):
                break
        idx = self._buf.find(b"\n")
        if idx >= 0:
            line = bytes(self._buf[:idx])
            del self._buf[:idx + 1]
        else:
            line = bytes(self._buf)
            self._buf.clear()
        return line.decode("ascii", "replace").strip()

    def _read_raw(self, n: int, timeout: float) -> bytes:
        end = time.time() + timeout
        while len(self._buf) < n and time.time() < end:
            self._fill(end)
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data


# --------------------------------------------------------------------------
# 演示模拟器：没有真机也能把界面完整跑起来
# --------------------------------------------------------------------------
_ALIAS = {
    "CONF": "CONFIGURE", "SENS": "SENSE", "FUNC": "FUNCTION", "RANG": "RANGE",
    "FUNC1": "FUNCTION1", "FUNC2": "FUNCTION2", "CONF2": "CONFIGURE2",
    "NPLC": "NPLCYCLES", "VOLT": "VOLTAGE", "CURR": "CURRENT", "RES": "RESISTANCE",
    "FRES": "FRESISTANCE", "FREQ": "FREQUENCY", "PER": "PERIOD", "CAP": "CAPACITANCE",
    "CONT": "CONTINUITY", "DIOD": "DIODE", "TEMP": "TEMPERATURE", "STAT": "STATE",
    "VAL": "VALUE", "SYST": "SYSTEM", "ERR": "ERROR", "DISP": "DISPLAY",
    "BEEP": "BEEPER", "IMM": "IMMEDIATE", "REM": "REMOTE", "LOC": "LOCAL",
    "SAMP": "SAMPLE", "COUN": "COUNT", "TRIG": "TRIGGER", "SOUR": "SOURCE",
    "MEAS": "MEASURE", "CALC": "CALCULATE",
}

_SIM_BASE = {
    "VOLTAGE:DC": 1.2345678, "VOLTAGE:AC": 2.3451200,
    "CURRENT:DC": 0.0123456, "CURRENT:AC": 0.0045600,
    "RESISTANCE": 1000.5432, "FRESISTANCE": 1000.2100,
    "FREQUENCY": 50000.12, "PERIOD": 2.0e-5,
    "CAPACITANCE": 1.2345e-8, "CONTINUITY": 0.0512,
    "DIODE": 0.6123, "TEMPERATURE": 25.43,
}

_SIM_UNIT = {
    "VOLTAGE:DC": "VDC", "VOLTAGE:AC": "VAC", "CURRENT:DC": "ADC",
    "CURRENT:AC": "AAC", "RESISTANCE": "OHM", "FRESISTANCE": "OHM",
    "FREQUENCY": "HZ", "PERIOD": "S", "CAPACITANCE": "F",
    "CONTINUITY": "OHM", "DIODE": "VDC", "TEMPERATURE": "C",
}


class SimTransport(Transport):
    """模拟一台 GDM-9061：实现手册里上位机常用的指令子集。"""

    kind = "sim"
    name = "演示模拟器"

    def __init__(self, model: str = "GDM9061"):
        super().__init__()
        self.model = model
        self._reset_state()

    # -- 生命周期 ------------------------------------------------------
    def _reset_state(self):
        self._out = deque()
        self._pending = b""
        self.func = "VOLTAGE:DC"
        self.second = "NON"
        self.nplc = 1.0
        self.rng = None            # None = 自动量程
        self.rel_on = False
        self.rel_val = 0.0
        self.temp_type = "K"
        self.temp_unit = "C"
        self.text = ""
        self.disp_on = True
        self.errors = deque(maxlen=16)
        self.sent = deque(maxlen=200)      # 收到的指令流水，便于自检/排查
        self.remote = False                # SYST:REM / SYST:LOC 状态
        self.nodata = False                # True 时 READ? 返回 +9.9E37（模拟超量程/开路）
        self.t0 = time.time()
        self.phase = random.uniform(0, 6.283)
        self._sn = "GEU193027"

    def _open(self):
        time.sleep(0.15)           # 模拟连接握手耗时

    def _close(self):
        pass

    def _write(self, text: str):
        for part in text.replace("\r", "").replace("\n", "").split(";"):
            part = part.strip()
            if part:
                self.sent.append(part)
                try:
                    self._exec(part)
                except Exception as exc:      # 模拟器不应崩
                    self.errors.append(f'-113,"{exc}"')

    def _read_line(self, timeout: float) -> str:
        if self._out:
            return self._out.popleft()
        return ""

    def _read_raw(self, n: int, timeout: float) -> bytes:
        data, self._pending = self._pending[:n], self._pending[n:]
        return data

    # -- 数值生成 ------------------------------------------------------
    def _value(self) -> float:
        t = time.time() - self.t0
        base = _SIM_BASE.get(self.func, 1.0)
        drift = 1.0 + 0.00035 * math_sin(t / 1.7 + self.phase)
        noise = random.gauss(0.0, abs(base) * 0.00006 + 1e-12)
        v = base * drift + noise
        if self.rng:
            v = max(-self.rng * 0.99, min(self.rng * 0.99, v))
        if self.rel_on:
            v -= self.rel_val
        return v

    def _value_text(self, value: float, func: str) -> str:
        if self.nodata:                    # 模拟超量程 / 开路：仪器给哨兵值
            return "+9.90000000E+37 "
        unit = _SIM_UNIT.get(func, "")
        return f"{value:+.8E} {unit}"

    # -- 指令分发 ------------------------------------------------------
    def _exec(self, cmd: str):
        head, _, arg = cmd.partition(" ")
        H = head.upper()
        arg = arg.strip()

        if H.startswith("*"):
            self._exec_star(H, arg)
            return

        is_q = H.endswith("?")
        base = H[:-1] if is_q else H

        # 真机的行为：收到任何远程指令都会进入远程状态（面板锁定），
        # 只有 SYST:LOC 例外。模拟器必须照做，否则测不出「返回本地被轮询顶回去」。
        if not (H.startswith("SYST:LOC") or H.startswith("SYSTEM:LOC")):
            self.remote = True
        key = ":".join(_ALIAS.get(t, t) for t in base.split(":"))

        # ---- 查询类 ----
        if is_q:
            if key.startswith("HCOP") or key.startswith("HCOPY"):
                self._pending = _make_bmp(self.model)
                return
            self._query(key, arg)
            return

        # ---- 设置类 ----
        if key == "SENSE:FUNCTION2":
            fn = arg.strip().strip('"').upper()
            self.second = "NON" if fn in ("NON", "OFF") else self._map_func(fn)
            return
        if key.startswith("CONFIGURE2"):
            if key.endswith("OFF"):
                self.second = "NON"
            else:
                fn = key[len("CONFIGURE2"):].lstrip(":")
                self.second = self._map_func(fn)
                self._set_range_from_arg(arg)
            return
        if key.startswith("CONFIGURE"):
            fn = key[len("CONFIGURE"):].lstrip(":")
            self.func = self._map_func(fn)
            self._set_range_from_arg(arg)
            return
        if key.startswith("MEASURE"):
            fn = key[len("MEASURE"):].lstrip(":")
            self.func = self._map_func(fn)
            return
        if key == "SENSE:FUNCTION" or key == "SENSE:FUNCTION1":
            self.func = self._map_func(arg.strip('"'))
            return
        if key.startswith("SENSE:"):
            self._sense(key, arg)
            return
        if key.startswith("DISPLAY:TEXT"):
            self.text = arg.strip('"')
            return
        if key == "DISPLAY:STATE":
            self.disp_on = arg.upper() not in ("0", "OFF")
            return
        if key.startswith("SYSTEM:BEEPER"):
            return
        if key == "SYSTEM:REMOTE":
            self.remote = True
            return
        if key == "SYSTEM:RWLOCK":
            self.remote = True
            return
        if key in ("SYSTEM:LOCAL", "SYSTEM:PRESET"):
            self.remote = False
            return
        if key.startswith("SAMPLE:COUNT") or key.startswith("TRIGGER:"):
            return
        if key.startswith("CALCULATE"):
            return
        if key == "ABORT" or key == "INITIALIZE":
            return
        self.errors.append('-113,"Undefined header"')

    def _exec_star(self, H: str, arg: str):
        if H == "*IDN?":
            self._out.append(f"GWInstek,{self.model},{self._sn},M0.70_S0.25B")
        elif H == "*RST":
            keep = self.model
            self._reset_state()
            self.model = keep
        elif H == "*OPC?":
            self._out.append("1")
        elif H == "*CLS":
            self.errors.clear()
        else:
            self._out.append("")

    def _map_func(self, fn: str) -> str:
        fn = fn.strip().upper()
        if fn in ("", "OFF", "NON"):
            return self.func
        table = {
            "VOLTAGE": "VOLTAGE:DC", "VOLTAGE:DC": "VOLTAGE:DC", "VOLTAGE:AC": "VOLTAGE:AC",
            "CURRENT": "CURRENT:DC", "CURRENT:DC": "CURRENT:DC", "CURRENT:AC": "CURRENT:AC",
            "RESISTANCE": "RESISTANCE", "FRESISTANCE": "FRESISTANCE",
            "FREQUENCY": "FREQUENCY", "PERIOD": "PERIOD", "CAPACITANCE": "CAPACITANCE",
            "CONTINUITY": "CONTINUITY", "DIODE": "DIODE",
            "TEMPERATURE": "TEMPERATURE", "TEMP:TCO": "TEMPERATURE",
        }
        if fn.startswith("TEMP"):
            return "TEMPERATURE"
        return table.get(fn, self.func)

    def _set_range_from_arg(self, arg: str):
        if not arg:
            self.rng = None
            return
        first = arg.split(",")[0].strip().upper()
        if first in ("AUTO", "DEF", "DEFAULT", "MIN", "MAX", ""):
            self.rng = None
            return
        try:
            self.rng = abs(float(first))
        except ValueError:
            self.rng = None

    def _sense(self, key: str, arg: str):
        toks = key.split(":")
        # SENSE:VOLTAGE:DC:NPLCYCLES / SENSE:RESISTANCE:RANGE ...
        tail = toks[-1]
        if tail == "NPLCYCLES":
            try:
                self.nplc = float(arg)
            except ValueError:
                pass
        elif tail == "RANGE" and len(toks) >= 2:
            self._set_range_from_arg(arg)
        elif key.endswith("RANGE:AUTO"):
            self.rng = None if arg.upper() in ("1", "ON", "TRUE") else self.rng
            if arg.upper() in ("0", "OFF"):
                self.rng = self.rng or 10.0
        elif key.endswith("NULL:STATE"):
            self.rel_on = arg.upper() in ("1", "ON")
        elif key.endswith("NULL:VALUE"):
            try:
                self.rel_val = float(arg)
            except ValueError:
                pass
        elif key.endswith("NULL:VALUE:AUTO"):
            if arg.upper() in ("1", "ON"):
                self.rel_val = self._value()
        elif tail == "UNIT":
            self.temp_unit = arg.upper()[:1] or "C"

    def _query(self, key: str, arg: str):
        if key in ("DATA:LAST", "DATA1:LAST", "MEASURE", "VAL", "VAL1", "FETCH"):
            self._out.append(self._value_text(self._value(), self.func))
        elif key == "DATA2:LAST" or key == "VAL2":
            if self.second == "NON":
                self._out.append("+9.91000000E+37")
            else:
                self._out.append(self._value_text(self._value() * 0.5, self.second))
        elif key in ("READ", "MEASURE2") or key.startswith("MEASURE"):
            self._out.append("+9.90000000E+37" if self.nodata
                             else f"{self._value():+.8E}")
        elif key in ("SYSTEM:ERROR", "SYSTEM:ERROR:NEXT"):
            self._out.append(self.errors.popleft() if self.errors else '+0,"No error"')
        elif key == "CONFIGURE":
            self._out.append(f"\"{self.func.split(':')[0]} {self.rng or 10.0:+.8E},+1.00000000E-05\"")
        elif key == "SYSTEM:VERSION":
            self._out.append("1994.0")
        elif key == "SENSE:FUNCTION" or key == "SENSE:FUNCTION1":
            self._out.append(f'"{self.func}"')
        elif key == "DISPLAY:TEXT":
            self._out.append(f'"{self.text}"')
        elif key == "SAMPLE:COUNT" or key == "TRIGGER:COUNT":
            self._out.append("+1")
        elif key == "DATA:POINTS":
            self._out.append("+0")
        elif key.startswith("CALCULATE:AVERAGE"):
            self._out.append("+0")
        elif key == "READING":
            self._out.append(f"{self._value():+.8E}")
        else:
            self._out.append("+0")


def math_sin(x: float) -> float:      # 避免在类里再 import math 名字冲突
    import math
    return math.sin(x)


def _make_bmp(model: str = "GDM9061", width: int = 240, height: int = 140) -> bytes:
    """演示模式下的假「屏幕截图」：生成一张带边框的灰度渐变 BMP。"""
    import struct
    row_bytes = ((width * 3 + 3) // 4) * 4
    pixels = bytearray()
    for y in range(height):                 # BMP 自下而上
        for x in range(width):
            v = 26 + int(200 * (1 - y / height)) + int(18 * (x / width))
            v = max(0, min(255, v))
            if x < 3 or x >= width - 3 or y < 3 or y >= height - 3:
                v = 70
            pixels += bytes((v, v + 6, v + 12 if v < 240 else 255))
        pixels += b"\x00" * (row_bytes - width * 3)
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0,
                      row_bytes * height, 2835, 2835, 0, 0)
    data = header + dib + bytes(pixels)
    return b"#" + str(len(str(len(data)))).encode() + str(len(data)).encode() + data
