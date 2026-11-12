# -*- coding: utf-8 -*-
"""传输层：RS-232 串口 / LAN(TCP) / USB-TMC / 模拟器"""

import socket
import time
from typing import Optional


class TransportError(Exception):
    pass


class Transport:
    """所有传输的统一接口"""

    name = "?"

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def read_some(self, max_bytes: int = 4096) -> bytes:
        """阻塞读取一段数据（受底层超时限制），可能返回空"""
        raise NotImplementedError

    def close(self) -> None:
        pass


# ---------------------------------------------------------------- 串口
class SerialTransport(Transport):
    def __init__(self, port: str, baud: int = 9600, parity: str = "N"):
        try:
            import serial
        except ImportError as e:
            raise TransportError("缺少 pyserial，请先执行: pip install pyserial") from e
        # 手册：NONE=8 数据位，ODD/EVEN=7 数据位
        bytesize = serial.SEVENBITS if parity in ("O", "E") else serial.EIGHTBITS
        parity_map = {"N": serial.PARITY_NONE, "O": serial.PARITY_ODD, "E": serial.PARITY_EVEN}
        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=bytesize,
                parity=parity_map.get(parity, serial.PARITY_NONE),
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
                write_timeout=2.0,
            )
        except Exception as e:
            raise TransportError(f"打开串口 {port} 失败: {e}") from e
        self.name = f"串口 {port} @ {baud}"

    def write(self, data: bytes) -> None:
        try:
            self._ser.write(data)
            self._ser.flush()
        except Exception as e:
            raise TransportError(f"串口写入失败: {e}") from e

    def read_some(self, max_bytes: int = 4096) -> bytes:
        try:
            n = self._ser.in_waiting
            if n:
                return self._ser.read(min(n, max_bytes))
            return self._ser.read(1)
        except Exception as e:
            raise TransportError(f"串口读取失败: {e}") from e

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


def list_serial_ports() -> list:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


# ---------------------------------------------------------------- LAN
class TcpTransport(Transport):
    def __init__(self, host: str, port: int = 5025, timeout: float = 2.0):
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as e:
            raise TransportError(f"连接 {host}:{port} 失败: {e}") from e
        self._sock.settimeout(0.15)
        self.name = f"LAN {host}:{port}"

    def write(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise TransportError(f"网络写入失败: {e}") from e

    def read_some(self, max_bytes: int = 4096) -> bytes:
        try:
            return self._sock.recv(max_bytes)
        except socket.timeout:
            return b""
        except OSError as e:
            raise TransportError(f"网络读取失败: {e}") from e

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------- USB-TMC
class VisaTransport(Transport):
    """NI-VISA / 系统 VISA 资源（USB0::xxx::yyy::serial::0::INSTR 等）

    Windows 装有 NI-VISA（设备管理器显示 IVI 驱动）时优先走这条路，
    不需要 Zadig 换驱动。
    """

    def __init__(self, resource: str):
        try:
            import pyvisa
        except ImportError as e:
            raise TransportError("缺少 pyvisa，请执行: pip install pyvisa") from e
        try:
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(resource)
        except Exception as e:
            raise TransportError(f"VISA 打开失败 {resource}: {e}") from e
        try:
            self._inst.timeout = 8000
            self._inst.write_termination = "\n"
            self._inst.read_termination = "\n"
        except Exception:
            pass
        self.name = f"VISA {resource}"

    def write(self, data: bytes) -> None:
        try:
            self._inst.write(data.decode("ascii", errors="ignore").strip("\r\n"))
        except Exception as e:
            raise TransportError(f"VISA 写入失败: {e}") from e

    def read_some(self, max_bytes: int = 4096) -> bytes:
        try:
            raw = bytes(self._inst.read_raw())
        except Exception:
            return b""
        if raw and not raw.endswith((b"\n", b"\r")):
            raw += b"\n"
        return raw[:max_bytes]

    def close(self) -> None:
        try:
            self._inst.close()
        except Exception:
            pass
        try:
            self._rm.close()
        except Exception:
            pass


def pyusb_status() -> str:
    """pyusb/libusb 可用性自检（用于界面提示）"""
    try:
        import usb.core  # noqa: F401
    except ImportError:
        return "pyusb 未安装"
    try:
        import usb.backend.libusb1 as backend
    except ImportError:
        return "libusb 后端模块缺失"
    if backend.get_backend() is None:
        return "libusb-1.0.dll 缺失，无法枚举（请改用 VISA 或安装 libusb）"
    return "正常"


def list_visa_resources() -> list:
    """列出系统 VISA 资源（含 USB0::...）"""
    try:
        import pyvisa
    except ImportError:
        return []
    try:
        rm = pyvisa.ResourceManager()
        return list(rm.list_resources())
    except Exception:
        return []


class UsbTmcTransport(Transport):
    """USBTMC (USB488) 简易实现：DEV_DEP_MSG_OUT / DEV_DEP_MSG_IN

    Windows 下需将设备驱动绑定为 WinUSB / libusbK（可用 Zadig），
    或使用系统已安装的 USBTMC 兼容驱动。
    """

    USBTMC_CLASS = 0xFE
    USBTMC_SUBCLASS = 0x03
    DEV_DEP_MSG_OUT = 0x01
    DEV_DEP_MSG_IN = 0x02
    HEADER = 12

    def __init__(self, vid: Optional[int] = None, pid: Optional[int] = None):
        try:
            import usb.core
            import usb.util
        except ImportError as e:
            raise TransportError("缺少 pyusb，请先执行: pip install pyusb") from e
        self._usb_core = usb.core
        self._usb_util = usb.util
        self._tag = 0
        dev, intf = self._find(vid, pid)
        self._dev = dev
        self._intf = int(intf.bInterfaceNumber)
        try:
            if dev.is_kernel_driver_active(self._intf):
                dev.detach_kernel_driver(self._intf)
        except (usb.core.USBError, NotImplementedError):
            pass
        try:
            dev.set_configuration()
        except usb.core.USBError:
            pass
        self._ep_out = None
        self._ep_in = None
        for ep in intf:
            addr = ep.bEndpointAddress
            if ep.bmAttributes & 0x03 == 0x02:  # bulk
                if addr & 0x80:
                    self._ep_in = addr
                else:
                    self._ep_out = addr
        if self._ep_out is None or self._ep_in is None:
            raise TransportError("USB 设备缺少 Bulk 端点，可能驱动未正确绑定")
        self.name = f"USB-TMC vid=0x{dev.idVendor:04X} pid=0x{dev.idProduct:04X}"
        self._try_clear()

    def _find(self, vid, pid):
        usb = self._usb_core
        kwargs = {}
        if vid is not None:
            kwargs["idVendor"] = vid
        if pid is not None:
            kwargs["idProduct"] = pid
        candidates = list(usb.find(find_all=True, **kwargs))
        if not candidates and (vid is not None or pid is not None):
            raise TransportError("未找到指定 VID/PID 的 USB 设备")
        # 优先匹配 USBTMC 接口
        for dev in candidates:
            for cfg in dev:
                for intf in cfg:
                    if intf.bInterfaceClass == self.USBTMC_CLASS and intf.bInterfaceSubClass == self.USBTMC_SUBCLASS:
                        return dev, intf
        # 退而求其次：RIGOL VID 的任意设备（部分型号接口描述不标准）
        for dev in candidates:
            for cfg in dev:
                for intf in cfg:
                    if dev.idVendor == 0x1AB1:
                        return dev, intf
        if not candidates:
            raise TransportError("未发现 USB 设备，请检查连线与驱动（Zadig 绑定 WinUSB/libusbK）")
        raise TransportError("发现 USB 设备但没有 USBTMC 接口（class FE/03），请检查驱动")

    def _next_tag(self) -> int:
        self._tag = self._tag % 255 + 1
        return self._tag

    def _try_clear(self):
        """尽力而为地 INITIATE_CLEAR + CHECK_CLEAR，失败可忽略"""
        import struct
        try:
            tag = self._next_tag()
            self._dev.ctrl_transfer(0x41, 0x05, tag, 0, b"", timeout=1000)  # INITIATE_CLEAR
            time.sleep(0.05)
            for _ in range(10):
                data = self._dev.ctrl_transfer(0xC1, 0x06, tag, 0, 1, timeout=1000)
                if data and data[0] == 0x00:
                    return
                time.sleep(0.05)
        except Exception:
            pass

    def write(self, data: bytes) -> None:
        import struct
        tag = self._next_tag()
        header = struct.pack("<BBBBIHH", self.DEV_DEP_MSG_OUT, tag, (~tag) & 0xFF, 0, len(data), 0, 0)
        try:
            self._dev.write(self._ep_out, header + data, timeout=3000)
        except Exception as e:
            raise TransportError(f"USB 写入失败: {e}") from e

    def read_some(self, max_bytes: int = 4096) -> bytes:
        import struct
        size = max(self.HEADER + 512, max_bytes)
        try:
            raw = bytes(self._dev.read(self._ep_in, size, timeout=1000))
        except Exception:
            return b""
        if len(raw) < self.HEADER:
            return b""
        # 解析 bulk-IN 头
        xfer_size = struct.unpack_from("<I", raw, 4)[0]
        payload = raw[self.HEADER:self.HEADER + xfer_size]
        return payload[:max_bytes] if payload else raw[self.HEADER:]

    def close(self) -> None:
        try:
            self._usb_util.dispose_resources(self._dev)
        except Exception:
            pass


def list_usb_tmc_devices() -> list:
    """返回 [(label, vid, pid), ...]；pyusb 后端不可用时返回 []"""
    try:
        import usb.core
        import usb.backend.libusb1 as backend
    except ImportError:
        return []
    if backend.get_backend() is None:
        return []
    out = []
    try:
        for dev in usb.core.find(find_all=True):
            matched = False
            for cfg in dev:
                for intf in cfg:
                    if intf.bInterfaceClass == 0xFE and intf.bInterfaceSubClass == 0x03:
                        matched = True
                        break
                if matched:
                    break
            if matched or dev.idVendor in (0x1AB1, 0x6833):
                out.append((f"VID=0x{dev.idVendor:04X} PID=0x{dev.idProduct:04X}", dev.idVendor, dev.idProduct))
    except Exception:
        return out
    return out


# ---------------------------------------------------------------- 模拟器（无硬件演示/自测）
class MockTransport(Transport):
    """按 RIGOL 语法应答的软件模拟器，便于无硬件调试界面"""

    name = "模拟器"

    def __init__(self):
        self._buf = b""
        self._func = "DCV"
        self._t0 = time.time()
        self._rel = 0.0
        self._rel_on = False
        self._math = "NONE"
        self._pf_low, self._pf_high = -1.0, 1.0
        self._count = 0
        self._min = None
        self._max = None
        self._sum = 0.0
        self._beep_on = True

    def _value(self) -> float:
        t = time.time() - self._t0
        base = {
            "DCV": 1.25, "ACV": 0.311, "DCI": 0.012, "ACI": 0.008,
            "2WR": 100.2, "4WR": 100.0, "FREQ": 50.0, "PERI": 0.02,
            "CONT": 0.35, "DIODE": 0.62, "CAP": 1e-6,
        }.get(self._func, 1.0)
        import math
        v = base * (1 + 0.03 * math.sin(t * 1.7)) + base * 0.002 * math.sin(t * 23.0)
        if self._func == "FREQ":
            v = base * (1 + 0.01 * math.sin(t * 0.4))
        return v

    def write(self, data: bytes) -> None:
        text = data.decode("ascii", errors="ignore").strip()
        if not text:
            return
        upper = text.upper()
        reply = None
        if upper == "*IDN?":
            reply = "RIGOL TECHNOLOGIES,DM3058,MOCK000000001,1.0.0.0"
        elif upper in ("SYST:VERS?", "SYSTEM:VERSION?"):
            reply = "1999.0"
        elif upper in ("*CLS", "*RST", "*OPC"):
            reply = None
        elif upper == "CMDSET?":
            reply = "RIGOL"
        elif upper.startswith("CMDSET"):
            reply = None
        elif upper.startswith(":FUNCTION?"):
            reply = self._func
        elif upper.startswith(":FUNCTION2?"):
            reply = "DCV"
        elif upper.startswith(":FUNCTION2:CLEAR"):
            reply = None
        elif upper.startswith(":FUNCTION:"):
            direct = {"VOLTAGE:DC": "DCV", "VOLTAGE:AC": "ACV", "CURRENT:DC": "DCI",
                      "CURRENT:AC": "ACI", "RESISTANCE": "2WR", "FRESISTANCE": "4WR",
                      "FREQUENCY": "FREQ", "PERIOD": "PERI", "CONTINUITY": "CONT",
                      "DIODE": "DIODE", "CAPACITANCE": "CAP"}
            path = upper[len(":FUNCTION:"):]
            if path in direct:
                self._func = direct[path]
        elif upper.startswith(":MEASURE?"):
            reply = "TRUE"
        elif upper in (":MEASURE AUTO", ":MEASURE MANU"):
            reply = None
        elif upper.startswith(":MEASURE:") and upper.endswith("?"):
            reply = f"{self._value():.6e}"
            self._count += 1
            v = self._value()
            self._min = v if self._min is None else min(self._min, v)
            self._max = v if self._max is None else max(self._max, v)
            self._sum += v
        elif upper.startswith(":FUNCTION2:VALUE"):
            # 双显读数：VALUe1 主 / VALUe2 副
            reply = f"{self._value():.6e}"
            self._count += 1
        elif upper.startswith(":FUNCTION2:"):
            reply = None
        elif upper.startswith(":RATE:"):
            reply = "M" if upper.endswith("?") else None
        elif upper.startswith(":MEASURE:VOLTAGE:DC:FIL"):
            reply = "0" if upper.endswith("?") else None
        elif upper.startswith(":MEASURE:VOLTAGE:DC:IMPED"):
            reply = "10M" if upper.endswith("?") else None
        elif upper.startswith(":CALC:PF?") or upper.startswith(":CALCULATE:PF?"):
            v = self._value()
            reply = "PASS" if self._pf_low <= v <= self._pf_high else "FAIL"
        elif upper.startswith(":CALCULATE:PF:LOWER"):
            if not upper.endswith("?"):
                try:
                    self._pf_low = float(text.split()[-1])
                except Exception:
                    pass
        elif upper.startswith(":CALCULATE:PF:UPPER"):
            if not upper.endswith("?"):
                try:
                    self._pf_high = float(text.split()[-1])
                except Exception:
                    pass
        elif upper.startswith(":CALCULATE:STATISTIC:MIN?"):
            reply = f"{(self._min if self._min is not None else 0.0):.6e}"
        elif upper.startswith(":CALCULATE:STATISTIC:MAX?"):
            reply = f"{(self._max if self._max is not None else 0.0):.6e}"
        elif upper.startswith(":CALCULATE:STATISTIC:AVERAGE?"):
            n = max(self._count, 1)
            reply = f"{(self._sum / n):.6e}"
        elif upper.startswith(":CALCULATE:STATISTIC:COUNT?"):
            reply = str(self._count)
        elif upper.startswith(":CALC:STATISTIC:MIN?"):
            reply = f"{(self._min if self._min is not None else 0.0):.6e}"
        elif upper.startswith(":CALC:STATISTIC:MAX?"):
            reply = f"{(self._max if self._max is not None else 0.0):.6e}"
        elif upper.startswith(":CALC:STATISTIC:AVERAGE?"):
            n = max(self._count, 1)
            reply = f"{(self._sum / n):.6e}"
        elif upper.startswith(":CALC:STATISTIC:COUNT?"):
            reply = str(self._count)
        elif upper.startswith(":CALCULATE:STATISTIC:STATE"):
            reply = "1" if upper.endswith("?") else None
        elif upper.startswith(":CALC:STATISTIC:STATE"):
            reply = "1" if upper.endswith("?") else None
        elif upper.startswith(":CALCULATE:FUNCTION"):
            if upper.endswith("?"):
                reply = self._math
            else:
                self._math = text.split()[-1].upper() if len(text.split()) > 1 else "NONE"
        elif upper.startswith(":CALC:FUNCTION"):
            if upper.endswith("?"):
                reply = self._math
            else:
                self._math = text.split()[-1].upper() if len(text.split()) > 1 else "NONE"
        elif upper.startswith(":CALCULATE:REL:STATE") or upper.startswith(":CALC:REL:STATE"):
            if upper.endswith("?"):
                reply = "1" if self._rel_on else "0"
            else:
                self._rel_on = upper.endswith("ON") or upper.endswith("1")
        elif upper.startswith(":CALCULATE:REL:OFFSET") or upper.startswith(":CALC:REL:OFFSET"):
            if upper.endswith("?"):
                reply = f"{self._rel:.6e}"
            elif not upper.endswith("?"):
                try:
                    self._rel = float(text.split()[-1])
                except Exception:
                    pass
        elif upper.startswith(":CALCULATE:DBM:REFERENCE") or upper.startswith(":CALC:DBM:REF"):
            reply = "50" if upper.endswith("?") else None
        elif upper.startswith(":CALCULATE:DB:REFERENCE") or upper.startswith(":CALC:DB:REF"):
            reply = "1" if upper.endswith("?") else None
        elif upper.startswith("SYST:ERR") or upper.startswith("SYSTEM:ERR"):
            reply = '0,"No error"'
        elif upper.startswith("SYST:BEEP") or upper.startswith("SYSTEM:BEEP"):
            reply = None
        elif upper.startswith(":TRIGGER:AUTO:HOLD"):
            reply = "0" if upper.endswith("?") else None
        elif upper.startswith(":TRIGGER:SOUR"):
            reply = "AUTO" if upper.endswith("?") else None
        else:
            reply = None  # 静默接受其它设置命令

        if reply is not None:
            self._buf += (reply + "\n").encode("ascii")

    def read_some(self, max_bytes: int = 4096) -> bytes:
        if not self._buf:
            time.sleep(0.005)
            return b""
        out, self._buf = self._buf[:max_bytes], self._buf[max_bytes:]
        return out

    def close(self) -> None:
        pass
