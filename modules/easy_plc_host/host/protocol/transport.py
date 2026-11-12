"""Transport layer: Modbus TCP (socket) and Modbus RTU (Windows COM via ctypes)."""
from __future__ import annotations

import ctypes
import socket
import struct
import time
from abc import ABC, abstractmethod
from typing import Optional

from .crc16 import append_crc, verify_crc


class TransportError(Exception):
    pass


class Transport(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def exchange(self, request: bytes, timeout: float = 1.0) -> bytes:
        """Send request bytes, return raw response (RTU frame or TCP MBAP+PDU)."""

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    @property
    @abstractmethod
    def describe(self) -> str: ...


# ---------------------------------------------------------------------------
# Modbus TCP
# ---------------------------------------------------------------------------


class TcpTransport(Transport):
    def __init__(self, host: str, port: int = 502, unit_id: int = 1):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._sock: Optional[socket.socket] = None
        self._tid = 0

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    @property
    def describe(self) -> str:
        return f"TCP {self.host}:{self.port} / 站号 {self.unit_id}"

    def open(self) -> None:
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)  # 连接超时 3s
        try:
            sock.connect((self.host, self.port))
        except OSError as exc:
            sock.close()
            raise TransportError(f"TCP 连接失败 {self.host}:{self.port} — {exc}") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def exchange(self, request: bytes, timeout: float = 1.0) -> bytes:
        """request is RTU-style: [slave, fc, ...] without CRC.

        Returns full TCP response: MBAP(7) + PDU.
        """
        if self._sock is None:
            raise TransportError("TCP 未连接")
        self._tid = (self._tid + 1) & 0xFFFF
        # MBAP: tid, pid=0, length, unit
        unit = request[0]
        pdu = request[1:]
        length = 1 + len(pdu)  # unit + pdu
        mbap = struct.pack(">HHHB", self._tid, 0, length, unit)
        frame = mbap + pdu

        self._sock.settimeout(timeout)
        try:
            self._sock.sendall(frame)
        except OSError as exc:
            raise TransportError(f"TCP 发送失败 — {exc}") from exc

        # read MBAP header (7 bytes) then body
        try:
            header = self._recv_exact(7)
            tid, pid, length, unit_rx = struct.unpack(">HHHB", header)
            body = self._recv_exact(length - 1)  # length includes unit
            return header + body
        except OSError as exc:
            raise TransportError(f"TCP 接收失败 — {exc}") from exc

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise TransportError("TCP 连接被关闭")
            buf += chunk
        return buf


# ---------------------------------------------------------------------------
# Modbus RTU over Windows serial port (ctypes, no pyserial)
# ---------------------------------------------------------------------------

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PURGE_TXABORT = 0x0002
PURGE_RXABORT = 0x0008
PURGE_TXCLEAR = 0x0004
PURGE_RXCLEAR = 0x0001

# no parity / odd / even
PARITY_NONE = 0
PARITY_ODD = 1
PARITY_EVEN = 2


class DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", ctypes.c_uint32),
        ("BaudRate", ctypes.c_uint32),
        ("fBinary", ctypes.c_uint32, 1),
        ("fParity", ctypes.c_uint32, 1),
        ("fOutxCtsFlow", ctypes.c_uint32, 1),
        ("fOutxDsrFlow", ctypes.c_uint32, 1),
        ("fDtrControl", ctypes.c_uint32, 2),
        ("fDsrSensitivity", ctypes.c_uint32, 1),
        ("fTXContinueOnXoff", ctypes.c_uint32, 1),
        ("fOutX", ctypes.c_uint32, 1),
        ("fInX", ctypes.c_uint32, 1),
        ("fErrorChar", ctypes.c_uint32, 1),
        ("fNull", ctypes.c_uint32, 1),
        ("fRtsControl", ctypes.c_uint32, 2),
        ("fAbortOnError", ctypes.c_uint32, 1),
        ("fDummy2", ctypes.c_uint32, 17),
        ("wReserved", ctypes.c_uint16),
        ("XonLim", ctypes.c_uint16),
        ("XoffLim", ctypes.c_uint16),
        ("ByteSize", ctypes.c_uint8),
        ("Parity", ctypes.c_uint8),
        ("StopBits", ctypes.c_uint8),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", ctypes.c_uint16),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", ctypes.c_uint32),
        ("ReadTotalTimeoutMultiplier", ctypes.c_uint32),
        ("ReadTotalTimeoutConstant", ctypes.c_uint32),
        ("WriteTotalTimeoutMultiplier", ctypes.c_uint32),
        ("WriteTotalTimeoutConstant", ctypes.c_uint32),
    ]


class SerialTransport(Transport):
    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
        slave: int = 1,
    ):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity.upper()
        self.stopbits = stopbits
        self.slave = slave
        self._handle = None
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    @property
    def describe(self) -> str:
        p = {"N": "无", "E": "偶", "O": "奇"}.get(self.parity, self.parity)
        return f"RTU {self.port} {self.baudrate} {self.bytesize}{p}{self.stopbits} / 站号 {self.slave}"

    def open(self) -> None:
        self.close()
        k32 = self._kernel32
        path = f"\\\\.\\{self.port}" if not self.port.startswith("\\\\.\\") else self.port
        handle = k32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle == INVALID_HANDLE_VALUE or handle is None:
            err = ctypes.get_last_error()
            raise TransportError(f"打开串口 {self.port} 失败 (错误码 {err})")
        self._handle = handle

        # setup
        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        if not k32.GetCommState(handle, ctypes.byref(dcb)):
            self.close()
            raise TransportError("GetCommState 失败")

        dcb.BaudRate = int(self.baudrate)
        dcb.ByteSize = int(self.bytesize)
        dcb.fBinary = 1
        dcb.fParity = 1 if self.parity != "N" else 0
        parity_map = {"N": PARITY_NONE, "O": PARITY_ODD, "E": PARITY_EVEN}
        dcb.Parity = parity_map.get(self.parity, PARITY_NONE)
        if self.stopbits == 2:
            dcb.StopBits = 2  # ONESTOPBIT=0, ONE5=1, TWO=2
        else:
            dcb.StopBits = 0
        dcb.fOutxCtsFlow = 0
        dcb.fOutxDsrFlow = 0
        dcb.fDtrControl = 0
        dcb.fRtsControl = 0
        dcb.fOutX = 0
        dcb.fInX = 0
        dcb.fAbortOnError = 0

        if not k32.SetCommState(handle, ctypes.byref(dcb)):
            self.close()
            raise TransportError("SetCommState 失败（波特率/校验不被支持？）")

        timeouts = COMMTIMEOUTS()
        # return as soon as a byte arrives; overall capped per-exchange
        timeouts.ReadIntervalTimeout = 50
        timeouts.ReadTotalTimeoutMultiplier = 0
        timeouts.ReadTotalTimeoutConstant = 200
        timeouts.WriteTotalTimeoutMultiplier = 0
        timeouts.WriteTotalTimeoutConstant = 200
        k32.SetCommTimeouts(handle, ctypes.byref(timeouts))
        k32.PurgeComm(handle, PURGE_RXCLEAR | PURGE_TXCLEAR)

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._kernel32.CloseHandle(self._handle)
            except OSError:
                pass
            self._handle = None

    def exchange(self, request: bytes, timeout: float = 1.0) -> bytes:
        """request: [slave, fc, ...] without CRC. Returns full RTU frame with CRC."""
        if self._handle is None:
            raise TransportError("串口未打开")
        frame = append_crc(request)
        k32 = self._kernel32

        written = ctypes.c_uint32(0)
        ok = k32.WriteFile(
            self._handle,
            frame,
            len(frame),
            ctypes.byref(written),
            None,
        )
        if not ok or written.value != len(frame):
            raise TransportError("串口写入失败")
        # flush to ensure transmission
        k32.FlushFileBuffers(self._handle)

        # receive: Modbus RTU frame is either exception (5 bytes) or normal
        # We read greedily until idle gap or expected length reached.
        deadline = time.monotonic() + timeout
        buf = bytearray()

        # first byte with short timeout already set on port
        while time.monotonic() < deadline:
            chunk = self._read_some(1 if not buf else 64, max(0.05, deadline - time.monotonic()))
            if chunk:
                buf.extend(chunk)
                if len(buf) >= 4:
                    # try CRC verify — frame complete when CRC ok and length sane
                    if verify_crc(bytes(buf)) and self._looks_complete(bytes(buf), request):
                        return bytes(buf)
                    # exception: slave+fc|80+code+crc = 5
                    if len(buf) >= 5 and (buf[1] & 0x80) and verify_crc(bytes(buf[:5])):
                        return bytes(buf[:5])
            else:
                if buf and verify_crc(bytes(buf)) and self._looks_complete(bytes(buf), request):
                    return bytes(buf)
                # idle gap after some data — if CRC matches, done
                if buf and len(buf) >= 4 and verify_crc(bytes(buf)):
                    return bytes(buf)
                time.sleep(0.01)

        if buf and verify_crc(bytes(buf)):
            return bytes(buf)
        raise TransportError(
            f"串口响应超时/校验失败 (收到 {len(buf)} 字节: {bytes(buf).hex(' ')})"
        )

    def _looks_complete(self, frame: bytes, request: bytes) -> bool:
        if len(frame) < 4:
            return False
        if frame[1] & 0x80:
            return len(frame) >= 5
        fc = request[1]
        if fc in (0x01, 0x02, 0x03, 0x04):
            if len(frame) < 3:
                return False
            need = 3 + frame[2] + 2  # slave+fc+bc+data+crc
            return len(frame) >= need
        return len(frame) >= 8

    def _read_some(self, max_bytes: int, timeout: float) -> bytes:
        k32 = self._kernel32
        # temporarily adjust timeout
        timeouts = COMMTIMEOUTS()
        timeouts.ReadIntervalTimeout = 20
        timeouts.ReadTotalTimeoutMultiplier = 0
        timeouts.ReadTotalTimeoutConstant = max(1, int(timeout * 1000))
        timeouts.WriteTotalTimeoutMultiplier = 0
        timeouts.WriteTotalTimeoutConstant = 200
        k32.SetCommTimeouts(self._handle, ctypes.byref(timeouts))

        buf = ctypes.create_string_buffer(max_bytes)
        read = ctypes.c_uint32(0)
        ok = k32.ReadFile(self._handle, buf, max_bytes, ctypes.byref(read), None)
        if not ok:
            return b""
        return buf.raw[: read.value]


def list_serial_ports() -> list[str]:
    """Enumerate COM ports via registry (best-effort)."""
    ports = []
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, i)
                if value and value not in ports:
                    ports.append(str(value))
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
    except OSError:
        pass
    # also probe COM1..COM32 quickly
    for n in range(1, 33):
        name = f"COM{n}"
        if name not in ports:
            # don't open; just keep common ones in list as fallback UI options
            pass
    return ports
