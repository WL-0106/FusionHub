"""物理传输层：RS-232/USB 串口、LAN(TCP socket)、内置模拟设备。"""
from __future__ import annotations

import math
import re
import socket
import threading
import time
from abc import ABC, abstractmethod


class TransportError(Exception):
    pass


class Transport(ABC):
    """SCPI 字节流通道。行终止符统一为 \\n。"""

    name: str = ""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read_line(self, timeout: float) -> bytes:
        """读取一行(含终止符剥离)，超时抛 TransportError。"""

    def discard(self) -> None:
        """丢弃接收缓冲(读超时后用于丢弃迟到/错位的数据，重新同步)。"""


class SerialTransport(Transport):
    """RS-232 与 USB(CDC 虚拟串口) 共用，参数 8N1 无流控(说明书默认 115200)。"""

    def __init__(self, port: str, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.name = f"SERIAL {port}"
        self._ser = None

    def open(self) -> None:
        import serial
        try:
            self._ser = serial.Serial(
                port=self.port, baudrate=self.baud,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=0.05, write_timeout=1.0,
            )
        except Exception as e:
            raise TransportError(f"打开串口 {self.port} 失败: {e}") from e

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def write(self, data: bytes) -> None:
        if self._ser is None:
            raise TransportError("串口未打开")
        try:
            self._ser.write(data)
            self._ser.flush()
        except Exception as e:
            raise TransportError(f"串口写入失败: {e}") from e

    def read_line(self, timeout: float) -> bytes:
        if self._ser is None:
            raise TransportError("串口未打开")
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            try:
                chunk = self._ser.read(1)
            except Exception as e:
                raise TransportError(f"串口读取失败: {e}") from e
            if chunk:
                buf += chunk
                if buf.endswith(b"\n"):
                    return bytes(buf).strip()
            else:
                time.sleep(0.005)
        raise TransportError(f"读取超时({timeout}s): {bytes(buf)!r}")

    def discard(self) -> None:
        if self._ser is not None:
            try:
                self._ser.reset_input_buffer()
            except Exception:
                pass


class LanTransport(Transport):
    """LAN 远控：原始 TCP socket，仪器端口默认 1026(见说明书 VISA 资源名)。"""

    def __init__(self, host: str, port: int = 1026, connect_timeout: float = 3.0):
        self.host = host
        self.port = port
        self.name = f"LAN {host}:{port}"
        self._connect_timeout = connect_timeout
        self._sock: socket.socket | None = None
        self._buf = bytearray()

    def open(self) -> None:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self._connect_timeout)
            sock.settimeout(0.05)
            self._sock = sock
            self._buf.clear()
        except OSError as e:
            raise TransportError(f"连接 {self.host}:{self.port} 失败: {e}") from e

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise TransportError("LAN 未连接")
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise TransportError(f"LAN 发送失败: {e}") from e

    def read_line(self, timeout: float) -> bytes:
        if self._sock is None:
            raise TransportError("LAN 未连接")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if b"\n" in self._buf:
                idx = self._buf.index(b"\n")
                line = bytes(self._buf[:idx])
                del self._buf[:idx + 1]
                return line.strip()
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as e:
                raise TransportError(f"LAN 接收失败: {e}") from e
            if not chunk:
                raise TransportError("LAN 连接被对端关闭")
            self._buf += chunk
        raise TransportError(f"读取超时({timeout}s)")

    def discard(self) -> None:
        self._buf.clear()


class SimTransport(Transport):
    """内置 GPP 模拟器：无硬件时用于自检与界面试用(--sim / 勾选模拟设备)。"""

    _IDN = "GW INSTEK, GPP-4323, SN:SIM0001, V1.05"

    def __init__(self, model: str = "GPP-4323"):
        self.name = f"SIM {model}"
        self._idn = self._IDN.replace("GPP-4323", model)
        self._open = False
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        # 每通道状态: v_set, i_set, out, ovp, ocp, ovp_en, ocp_en, mode
        self._st: dict[int, dict] = {
            n: {"v": 0.0, "i": 0.1, "out": False, "ovp": 33.0, "ocp": 3.2,
                "ovp_en": False, "ocp_en": False, "mode": "Independent", "r": 100.0}
            for n in range(1, 5)
        }

    def open(self) -> None:
        time.sleep(0.05)
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, data: bytes) -> None:
        if not self._open:
            raise TransportError("模拟器未打开")
        text = data.decode("ascii", errors="ignore").strip()
        if not text:
            return
        with self._lock:
            resp = self._handle(text)
        if resp is not None:
            self._pending = getattr(self, "_pending", bytearray())
            self._pending += (resp + "\n").encode("ascii")

    def read_line(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending = getattr(self, "_pending", bytearray())
            if pending:
                idx = pending.index(b"\n")
                line = bytes(pending[:idx])
                del pending[:idx + 1]
                return line.strip()
            time.sleep(0.005)
        raise TransportError("模拟器读取超时")

    # ---- 命令处理(容忍 SCPI 全称/缩写、大小写与空格) ----
    def _handle(self, cmd: str) -> str | None:
        c = cmd.upper().replace(" ", "")
        is_query = c.endswith("?")
        body = c[:-1] if is_query else c
        num_in = lambda s: re.search(r"[-+]?\d*\.?\d+", s or "")

        if body == "*IDN":
            return self._idn
        if body.startswith("*"):
            return "1" if is_query else None

        if re.match(r"^:SYST(?:EM)?:ERR(?:OR)?$", body):
            return '+0,"No error"'
        if re.match(r"^(?:SYST(?:EM)?:)?(?:REM(?:OTE)?|LOC(?:AL)?)$", body):
            return None
        if body == "ALLOUTON":
            for n in self._st:
                self._st[n]["out"] = True
            return None
        if body == "ALLOUTOFF":
            for n in self._st:
                self._st[n]["out"] = False
            return None
        if re.match(r"^:OUT(?:PUT)?:SER(?:IES)?(?:ON|OFF)?$", body):
            on = "OFF" not in body
            for n in (1, 2):
                self._st[n]["mode"] = "Series" if on else "Independent"
            return ("ON" if on else "OFF") if is_query else None
        if re.match(r"^:OUT(?:PUT)?:PAR(?:ALLEL)?(?:ON|OFF)?$", body):
            on = "OFF" not in body
            for n in (1, 2):
                self._st[n]["mode"] = "Parallel" if on else "Independent"
            return ("ON" if on else "OFF") if is_query else None

        m = re.match(r"^:OUT(?:PUT)?(\d+)(.*)$", body)
        if m:
            n, rest = int(m.group(1)), m.group(2)
            st = self._st.get(n)
            if st is None:
                return '+1,"Channel out of range"'
            m2 = re.match(r"^:(OVP|OCP)(:STAT(?:E)?)?(.*)$", rest)
            if m2:
                kind = m2.group(1).lower()
                tail = m2.group(3) or ""
                if m2.group(2):          # 显式 :STATe → 开关
                    if is_query:
                        return "ON" if st[kind + "_en"] else "OFF"
                    st[kind + "_en"] = tail in ("ON", "1") or "ON" in rest
                    return None
                if is_query:             # :OVP? → 数值
                    return f"{st[kind]:.3f}"
                hit = num_in(tail)
                if hit:
                    st[kind] = float(hit.group(0))
                elif "ON" in tail or "OFF" in tail:
                    st[kind + "_en"] = "ON" in tail
                return None
            # 输出开关：:OUTPut1 ON / :OUTPut1 / :OUTPut1:STATe ON
            if rest in ("", ":STAT", "ON", "OFF", "1", "0") or rest.startswith(":STAT"):
                if is_query:
                    return "ON" if st["out"] else "OFF"
                st["out"] = rest in ("1", "ON") or rest.endswith("ON")
                return None
            return None

        m = re.match(r"^:SOUR(?:CE)?(\d+):(.+)$", body)
        if m:
            n, rest = int(m.group(1)), m.group(2)
            st = self._st.get(n)
            if st is None:
                return '+1,"Channel out of range"'
            if rest.startswith("VOLT"):
                if is_query:
                    return f"{st['v']:.3f}"
                hit = num_in(rest)
                if hit:
                    st["v"] = float(hit.group(0))
                return None
            if rest.startswith("CURR"):
                if "STAT" in rest:      # 限流状态查询
                    return "0" if is_query else None
                if is_query:
                    return f"{st['i']:.4f}"
                hit = num_in(rest)
                if hit:
                    st["i"] = float(hit.group(0))
                return None
            if rest.startswith("RES"):
                if is_query:
                    return f"{st['r']:.3f}"
                hit = num_in(rest)
                if hit:
                    st["r"] = float(hit.group(0))
                return None

        if re.match(r"^:SOUR(?:CE)?:VOLT(?:AGE)?:ALL$", body):
            vals = ",".join(f"{self._st[n]['v']:.3f}" for n in sorted(self._st))
            return vals
        if re.match(r"^:SOUR(?:CE)?:CURR(?:ENT)?:ALL$", body):
            return ",".join(f"{self._st[n]['i']:.4f}" for n in sorted(self._st))

        m = re.match(r"^:MEAS(?:URE)?(\d+):ALL$", body)
        if m:
            n = int(m.group(1))
            st = self._st.get(n)
            if st is None:
                return "0,0,0"
            return self._measure(n, st)

        m = re.match(r"^:MODE(\d+)$", body)
        if m:
            return self._st.get(int(m.group(1)), {}).get("mode", "Independent")

        m = re.match(r"^:LOAD(\d+):(CV|CC|CR)(.*)$", body)
        if m:
            n, kind, tail = int(m.group(1)), m.group(2), m.group(3)
            st = self._st.get(n)
            if st is None:
                return None
            if is_query:
                return "ON" if st["mode"] == f"{kind} Load" else "OFF"
            st["mode"] = f"{kind} Load" if "ON" in tail else "Independent"
            return None

        m = re.match(r"^:LOAD(\d+):RES(?:ISTOR)?(.*)$", body)
        if m:
            n = int(m.group(1))
            if is_query:
                return f"{self._st[n]['r']:.3f}"
            hit = num_in(m.group(2) or "")
            if hit:
                self._st[n]["r"] = float(hit.group(0))
            return None

        if is_query:
            return "0"
        return None

    def _measure(self, n: int, st: dict) -> str:
        t = time.monotonic() - self._t0
        if not st["out"]:
            return "0.00000,0.000000,0.0000"
        # 输出打开时给一点带负载感的波动
        v = st["v"] * (1 + 0.004 * math.sin(t * 2.1 + n))
        i = min(st["i"], st["i"] * (0.92 + 0.05 * math.sin(t * 1.3 + n * 0.7)))
        p = v * i
        return f"{v:.5f},{i:.6f},{p:.4f}"
