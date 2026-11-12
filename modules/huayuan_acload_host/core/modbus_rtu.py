# -*- coding: utf-8 -*-
"""
零依赖 Modbus 通讯协议栈（RTU / RTU-over-TCP / Modbus-TCP / UDP）。

适用设备：华源交流回馈式负载（协议 V1.4，RS232 / RS485）
功能码：0x03 读保持寄存器、0x06 写单个寄存器、0x10 写多个寄存器

设计要点
    * 不使用 pymodbus —— 只用标准库，拷到任何装了 Python 的机器都能跑。
    * 传输层可替换：SerialTransport / TcpTransport / UdpTransport，
      统一接口 exchange(frame, expected_len, timeout) -> bytes。
    * 一帧发送前做本地合法性校验（数量、范围），避免设备回异常码 03。
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable, List, Optional, Sequence

# --------------------------------------------------------------------------
# CRC16 / Modbus  (多项式 0xA001，初值 0xFFFF，低字节在前)
# --------------------------------------------------------------------------

def _make_crc_table() -> List[int]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        table.append(crc)
    return table


_CRC_TABLE = _make_crc_table()


def crc16(data: bytes) -> int:
    """查表法 CRC16/Modbus。"""
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def crc16_bitwise(data: bytes) -> int:
    """逐位法 CRC16/Modbus —— 仅用于自测交叉验证，速度慢。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def append_crc(pdu: bytes) -> bytes:
    c = crc16(pdu)
    return pdu + bytes((c & 0xFF, (c >> 8) & 0xFF))


def check_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    return crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


def hexs(data: bytes, sep: str = " ") -> str:
    """把字节串格式化成大写十六进制，便于看报文。"""
    return sep.join("%02X" % b for b in data)


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------

class ModbusError(Exception):
    """Modbus 通讯类错误基类。"""


class ModbusTimeout(ModbusError):
    def __init__(self, msg: str = "等待设备响应超时", partial: bytes = b""):
        self.partial = partial
        if partial:
            msg = "%s（收到不完整数据 %s）" % (msg, hexs(partial))
        super().__init__(msg)


class ModbusCRCError(ModbusError):
    def __init__(self, frame: bytes):
        self.frame = frame
        super().__init__("CRC 校验失败：%s" % hexs(frame))


class ModbusFrameError(ModbusError):
    pass


# 异常码中文说明（协议手册虽未列出，但按 Modbus 标准实现便于现场排查）
EXCEPTION_TEXT = {
    0x01: "非法功能码",
    0x02: "非法数据地址",
    0x03: "非法数据值",
    0x04: "从站设备故障",
    0x05: "确认（设备正在处理，需稍后重试）",
    0x06: "从站设备忙",
    0x08: "存储奇偶校验错",
    0x0A: "网关路径不可用",
    0x0B: "网关目标设备无响应",
}


class ModbusExceptionResponse(ModbusError):
    """设备回的异常响应（功能码最高位置 1）。"""

    def __init__(self, func: int, code: int):
        self.func = func
        self.code = code
        text = EXCEPTION_TEXT.get(code, "未知异常")
        super().__init__("设备异常响应：功能码 0x%02X，异常码 0x%02X（%s）" % (func, code, text))


# --------------------------------------------------------------------------
# 帧构造（PDU / ADU）
# --------------------------------------------------------------------------

MAX_READ_REGISTERS = 125
MAX_WRITE_REGISTERS = 123


def build_read_registers(unit: int, start: int, count: int) -> bytes:
    """0x03 读保持寄存器。返回带 CRC 的完整 RTU 帧。"""
    if not 1 <= count <= MAX_READ_REGISTERS:
        raise ValueError("读取数量必须在 1~%d 之间，当前 %d" % (MAX_READ_REGISTERS, count))
    if not 0 <= start <= 0xFFFF:
        raise ValueError("起始地址超出范围：%d" % start)
    if (start + count - 1) > 0xFFFF:
        raise ValueError("起始地址 + 数量超出寄存器空间")
    pdu = bytes((0x03,)) + struct.pack(">HH", start, count)
    return append_crc(bytes((unit,)) + pdu)


def build_write_single(unit: int, reg: int, value: int) -> bytes:
    """0x06 写单个寄存器。"""
    if not 0 <= reg <= 0xFFFF:
        raise ValueError("寄存器地址超出范围：%d" % reg)
    if not 0 <= value <= 0xFFFF:
        raise ValueError("写入值必须在 0~65535 之间，当前 %d" % value)
    pdu = bytes((0x06,)) + struct.pack(">HH", reg, value)
    return append_crc(bytes((unit,)) + pdu)


def build_write_multiple(unit: int, start: int, values: Sequence[int]) -> bytes:
    """0x10 写多个寄存器。"""
    n = len(values)
    if not 1 <= n <= MAX_WRITE_REGISTERS:
        raise ValueError("写入数量必须在 1~%d 之间，当前 %d" % (MAX_WRITE_REGISTERS, n))
    for v in values:
        if not 0 <= v <= 0xFFFF:
            raise ValueError("写入值必须在 0~65535 之间，当前 %d" % v)
    body = struct.pack(">HHB", start, n, n * 2)
    body += b"".join(struct.pack(">H", v) for v in values)
    pdu = bytes((0x10,)) + body
    return append_crc(bytes((unit,)) + pdu)


def read_response_len(count: int, mbap: bool = False) -> int:
    """0x03 正常响应长度。

    RTU  : 地址1 + 功能码1 + 字节数1 + 2N + CRC2        = 5 + 2N
    MBAP : 头7(事务2+协议2+长度2+单元1) + 功能码1 + 字节数1 + 2N = 9 + 2N
    """
    return (9 if mbap else 5) + 2 * count


def write_response_len(mbap: bool = False) -> int:
    """0x06 / 0x10 正常响应长度（功能码 + 地址2 + 值2）。"""
    return 12 if mbap else 8


def exception_response_len(mbap: bool = False) -> int:
    """异常响应长度（功能码 + 异常码）。"""
    return 9 if mbap else 5


def fc_index(mbap: bool = False) -> int:
    """功能码在响应字节流中的下标：RTU 为 1，MBAP 为 7。"""
    return 7 if mbap else 1


# --------------------------------------------------------------------------
# 32 位值拆分 / 合成
# --------------------------------------------------------------------------

def u32_to_words(value: int, word_swap: bool = False) -> List[int]:
    """把 32 位无符号整数拆成两个 16 位寄存器值。

    word_swap=False（默认）：高字在前 —— [高16位, 低16位]
    word_swap=True         ：低字在前 —— [低16位, 高16位]
    """
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("32 位值超出范围：%d" % value)
    hi = (value >> 16) & 0xFFFF
    lo = value & 0xFFFF
    return [lo, hi] if word_swap else [hi, lo]


def words_to_u32(hi: int, lo: int) -> int:
    return ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)


def u16_to_i16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


# --------------------------------------------------------------------------
# 传输层
# --------------------------------------------------------------------------

class Transport:
    """传输层基类：一句话，把 frame 发出去，把响应收回来。"""

    name = "transport"
    mbap = False          # 是否需要 MBAP 头（Modbus TCP）

    def exchange(self, frame: bytes, expected_len: int, timeout: float = 0.6,
                 fc_idx: int = 1, exc_len: int = 5) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        pass

    @property
    def describe(self) -> str:
        return self.name


def _collect(recv_fn: Callable[[float], bytes], expected_len: int,
             timeout: float, fc_idx: int, exc_len: int) -> bytes:
    """按期望长度收包；遇到异常响应（短帧）可提前结束。

    关键点：不要用一次 recv(4096) 了事 —— 串口和 TCP 都可能分包，
    必须"累计读到期望长度或超时"。
    """
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while True:
        if len(buf) >= expected_len:
            break
        if len(buf) >= exc_len and (buf[fc_idx] & 0x80):
            break
        remain = deadline - time.monotonic()
        if remain <= 0:
            break
        chunk = recv_fn(min(remain, 0.25))
        if chunk:
            buf += chunk
        else:
            time.sleep(0.002)
    return bytes(buf)


class SerialTransport(Transport):
    """RS232 / RS485 串口。依赖 pyserial（仅本类需要）。"""

    name = "串口"

    def __init__(self, port: str, baudrate: int = 9600, bytesize: int = 8,
                 parity: str = "N", stopbits: float = 1.0,
                 write_timeout: float = 1.0):
        import serial  # 延迟导入：网口模式下不需要 pyserial
        self._serial_mod = serial
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=0.05,
            write_timeout=write_timeout,
        )
        self._port = port
        self._baud = baudrate
        self.lock = threading.Lock()

    @property
    def describe(self) -> str:
        return "串口 %s @ %d,%d%s%s" % (self._port, self._baud, 8, "N",
                                        "1" if True else "")

    def exchange(self, frame, expected_len, timeout=0.6, fc_idx=1, exc_len=5):
        with self.lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except Exception:
                pass
            self.ser.write(frame)
            self.ser.flush()

            def recv(_remain: float) -> bytes:
                n = self.ser.in_waiting
                if n:
                    return self.ser.read(n)
                return self.ser.read(1)

            return _collect(recv, expected_len, timeout, fc_idx, exc_len)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class TcpTransport(Transport):
    """网口。mbap=True 走标准 Modbus TCP（502）；mbap=False 走裸 RTU 帧透传。"""

    name = "网口"

    def __init__(self, host: str, port: int, connect_timeout: float = 3.0):
        self._host = host
        self._port = port
        self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(0.05)
        self.lock = threading.Lock()

    @property
    def describe(self) -> str:
        return "网口 %s:%d" % (self._host, self._port)

    def exchange(self, frame, expected_len, timeout=0.6, fc_idx=1, exc_len=5):
        with self.lock:
            self.sock.sendall(frame)

            def recv(remain: float) -> bytes:
                self.sock.settimeout(min(remain, 0.05))
                try:
                    return self.sock.recv(4096)
                except socket.timeout:
                    return b""

            return _collect(recv, expected_len, timeout, fc_idx, exc_len)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class UdpTransport(Transport):
    """网口 UDP，用于少量支持 UDP 转串口的网关。"""

    name = "网口(UDP)"

    def __init__(self, host: str, port: int, connect_timeout: float = 3.0):
        self._host = host
        self._port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.05)
        self.sock.connect((host, port))
        self.lock = threading.Lock()

    @property
    def describe(self) -> str:
        return "UDP %s:%d" % (self._host, self._port)

    def exchange(self, frame, expected_len, timeout=0.6, fc_idx=1, exc_len=5):
        with self.lock:
            self.sock.send(frame)

            def recv(_remain: float) -> bytes:
                try:
                    return self.sock.recv(4096)
                except socket.timeout:
                    return b""

            return _collect(recv, expected_len, timeout, fc_idx, exc_len)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# 客户端
# --------------------------------------------------------------------------

class ModbusClient:
    """上层使用的 Modbus 主站客户端。

    参数
        transport   : 上面三种传输层之一
        unit        : 从站地址 1~254（0 = 广播，只写不读）
        offset      : 地址偏移。协议表地址 + offset 才是实际发出的 StartReg。
                      华源手册地址即为 StartReg，默认 0。留这个开关是给
                      现场遇到"地址差 1"的机型兜底。
        word_swap   : 32 位值字序。默认高字在前；置 True 则低字在前。
        align_even  : 起始地址与数量对齐到偶数（部分国产仪器有此硬性要求）。
        on_tx/on_rx : 收发报文回调，用于界面打印通讯日志。
    """

    def __init__(self, transport: Transport, unit: int = 1, offset: int = 0,
                 word_swap: bool = False, align_even: bool = False,
                 timeout: float = 0.6, inter_frame_delay: float = 0.02,
                 on_tx: Optional[Callable[[bytes], None]] = None,
                 on_rx: Optional[Callable[[bytes], None]] = None):
        self.tp = transport
        self.unit = unit
        self.offset = offset
        self.word_swap = word_swap
        self.align_even = align_even
        self.timeout = timeout
        self.inter_frame_delay = inter_frame_delay
        self.on_tx = on_tx
        self.on_rx = on_rx
        self._txn = 0

    # ---------------- 底层 ----------------

    @property
    def mbap(self) -> bool:
        """当前传输层是否使用 MBAP 头（标准 Modbus TCP）。"""
        return bool(getattr(self.tp, "mbap", False))

    def _wire(self, rtu_frame: bytes) -> bytes:
        """按需给 RTU 帧套 MBAP 头（Modbus TCP）。

        RTU 帧 = 地址1 + PDU + CRC2；MBAP = 事务号2 + 协议号2 + 长度2 + 单元号1。
        PDU 是 rtu_frame[1:-2]（必须去掉地址和 CRC）。
        """
        if not getattr(self.tp, "mbap", False):
            return rtu_frame
        self._txn = (self._txn + 1) & 0xFFFF
        pdu = rtu_frame[1:-2]                     # 去掉从站地址 + CRC
        mbap = struct.pack(">HHHB", self._txn, 0, len(pdu) + 1, self.unit)
        return mbap + pdu

    def _unwrap(self, resp: bytes) -> bytes:
        """去掉 MBAP 头并把 CRC 补回来，统一成 RTU 帧形式给上层解析。"""
        if not getattr(self.tp, "mbap", False):
            return resp
        if len(resp) < 8:
            raise ModbusFrameError("MBAP 响应过短：%s" % hexs(resp))
        txn, proto, length, unit = struct.unpack(">HHHB", resp[:7])
        pdu = resp[7:]
        if unit != self.unit and self.unit != 0:
            raise ModbusFrameError("MBAP 响应从站地址不符：期望 %d 收到 %d" % (self.unit, unit))
        return bytes((unit,)) + pdu + b"\x00\x00"   # 占位 CRC，不参与校验

    def _transact(self, rtu_frame: bytes, expected_len: int) -> bytes:
        mbap = self.mbap
        wire = self._wire(rtu_frame)
        if self.on_tx:
            self.on_tx(wire)
        raw = self.tp.exchange(wire, expected_len, self.timeout,
                               fc_index(mbap), exception_response_len(mbap))
        if self.on_rx:
            self.on_rx(raw)
        if not raw:
            raise ModbusTimeout()
        resp = self._unwrap(raw)
        if not mbap:
            if len(resp) < 5:
                raise ModbusFrameError("响应过短：%s" % hexs(resp))
            if not check_crc(resp):
                raise ModbusCRCError(resp)
        if self.inter_frame_delay:
            time.sleep(self.inter_frame_delay)
        return resp

    def _check_exception(self, resp: bytes) -> None:
        if len(resp) >= 3 and (resp[1] & 0x80):
            raise ModbusExceptionResponse(resp[1] & 0x7F, resp[2])
        if resp[0] != self.unit and self.unit != 0:
            raise ModbusFrameError("响应从站地址不符：期望 %d 收到 %d" % (self.unit, resp[0]))

    # ---------------- 公共 API ----------------

    def read_registers(self, start: int, count: int) -> List[int]:
        """读保持寄存器（FC03）。返回长度为 count 的整数列表。"""
        s = start + self.offset
        c = count
        skip = 0
        if self.align_even:
            if s % 2:
                s -= 1
                c += 1
                skip += 1
            if c % 2:
                c += 1
        frame = build_read_registers(self.unit if self.unit != 0 else 1, s, c)
        resp = self._transact(frame, read_response_len(c, self.mbap))
        self._check_exception(resp)
        if resp[1] != 0x03:
            raise ModbusFrameError("功能码不符：期望 03，收到 %02X" % resp[1])
        nbytes = resp[2]
        if nbytes != c * 2:
            raise ModbusFrameError("字节数不符：期望 %d，收到 %d" % (c * 2, nbytes))
        data = struct.unpack(">%dH" % c, resp[3:3 + nbytes])
        return list(data[skip:skip + count])

    def read_u32(self, start: int) -> int:
        w = self.read_registers(start, 2)
        return words_to_u32(w[1], w[0]) if self.word_swap else words_to_u32(w[0], w[1])

    def write_single(self, reg: int, value: int) -> None:
        """写单个寄存器（FC06）。"""
        if self.unit == 0:
            frame = build_write_single(0, reg + self.offset, value)
            self.tp.exchange(self._wire(frame), 0, self.timeout,
                             fc_index(self.mbap), exception_response_len(self.mbap))
            return
        frame = build_write_single(self.unit, reg + self.offset, value)
        resp = self._transact(frame, write_response_len(self.mbap))
        self._check_exception(resp)
        if resp[1] != 0x06:
            raise ModbusFrameError("功能码不符：期望 06，收到 %02X" % resp[1])

    def write_multiple(self, start: int, values: Sequence[int]) -> None:
        """写多个寄存器（FC10）。"""
        if self.unit == 0:
            frame = build_write_multiple(0, start + self.offset, list(values))
            self.tp.exchange(self._wire(frame), 0, self.timeout,
                             fc_index(self.mbap), exception_response_len(self.mbap))
            return
        frame = build_write_multiple(self.unit, start + self.offset, list(values))
        resp = self._transact(frame, write_response_len(self.mbap))
        self._check_exception(resp)
        if resp[1] != 0x10:
            raise ModbusFrameError("功能码不符：期望 10，收到 %02X" % resp[1])

    def write_u32(self, start: int, value: int) -> None:
        """写 32 位值（占 2 个寄存器）。"""
        self.write_multiple(start, u32_to_words(value, self.word_swap))

    def close(self) -> None:
        try:
            self.tp.close()
        except Exception:
            pass
