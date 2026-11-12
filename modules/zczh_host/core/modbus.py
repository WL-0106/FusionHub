# -*- coding: utf-8 -*-
"""中创智合采集卡 Modbus 协议栈（零依赖，全系列共用）

协议层与型号无关：温度系列、电压系列、电流系列共用同一套帧编解码。
差异只在寄存器映射表（见 series.py）。

覆盖功能码：
  - 0x03 读保持寄存器
  - 0x04 读输入寄存器
  - 0x06 写单个寄存器
  - 0x10 写多个寄存器
异常响应识别：func & 0x80，异常码 01/02/03/04。

传输层：RTU（串口/裸 TCP 透传）与 Modbus TCP（MBAP 头，无 CRC）两种。
"""

import struct
import time

# ---------------------------------------------------------------------------
# CRC16（Modbus，多项式 0xA001，低字节在前）
# ---------------------------------------------------------------------------
_CRC_TAB = []


def _build_crc_tab():
    global _CRC_TAB
    if _CRC_TAB:
        return
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        _CRC_TAB.append(crc)


def crc16(data: bytes) -> int:
    """返回 16 位 CRC 值（整数）。"""
    _build_crc_tab()
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC_TAB[(crc ^ b) & 0xFF]
    return crc


def crc16_bytes(data: bytes) -> bytes:
    """返回 CRC 两字节，低字节在前。"""
    c = crc16(data)
    return bytes((c & 0xFF, (c >> 8) & 0xFF))


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class ModbusError(Exception):
    """Modbus 异常响应。"""

    CODES = {
        0x01: "非法功能码",
        0x02: "非法数据地址",
        0x03: "非法数据值",
        0x04: "从站设备故障",
    }

    def __init__(self, code, addr=None, detail=""):
        self.code = code
        self.addr = addr
        self.detail = detail
        name = self.CODES.get(code, "未知异常(0x%02X)" % code)
        msg = "Modbus 异常 0x%02X：%s" % (code, name)
        if addr is not None:
            msg += "（地址 %d/0x%04X）" % (addr, addr)
        if detail:
            msg += "；" + detail
        super().__init__(msg)


class ProtocolError(Exception):
    """链路/协议错误（超时、无响应、CRC 错等）。"""


# ---------------------------------------------------------------------------
# 帧编解码
# ---------------------------------------------------------------------------
def build_read(slave, fc, start_addr, count):
    """构造读寄存器请求帧（RTU，含地址+CRC）。"""
    if count <= 0 or count > 125:
        raise ValueError("读取寄存器数量必须 1~125")
    body = bytes((slave, fc)) + struct.pack(">HH", start_addr, count)
    return body + crc16_bytes(body)


def build_write_single(slave, addr, value):
    """构造写单寄存器请求帧（FC06，RTU）。"""
    if not 0 <= value <= 0xFFFF:
        raise ValueError("写入值超出 16 位范围：%d" % value)
    body = bytes((slave, 0x06)) + struct.pack(">HH", addr, value)
    return body + crc16_bytes(body)


def build_write_multi(slave, start_addr, values):
    """构造写多寄存器请求帧（FC10，RTU）。values 为 int 列表。"""
    n = len(values)
    if n <= 0 or n > 123:
        raise ValueError("写寄存器数量必须 1~123")
    body = bytes((slave, 0x10)) + struct.pack(">HH", start_addr, n)
    body += bytes((n * 2,))
    for v in values:
        if not 0 <= v <= 0xFFFF:
            raise ValueError("写入值超出 16 位范围：%d" % v)
        body += struct.pack(">H", v)
    return body + crc16_bytes(body)


def parse_rtu_response(frame, expect_fc=None, expect_count=None):
    """解析 RTU 响应帧，返回数据区字节（不含地址/FC/ByteCount/CRC）。

    异常响应会抛 ModbusError。若 expect_fc 给定时会校验功能码。
    """
    if len(frame) < 4:
        raise ProtocolError("响应帧过短：%d 字节" % len(frame))
    # CRC 校验
    body, crc = frame[:-2], frame[-2:]
    if crc16_bytes(body) != crc:
        raise ProtocolError("CRC 校验失败（帧=%s）" % frame.hex(" "))

    fc = frame[1]
    if fc & 0x80:
        code = frame[2] if len(frame) >= 3 else 0x04
        raise ModbusError(code)

    if expect_fc is not None and fc != expect_fc:
        raise ProtocolError("功能码不符：期望 0x%02X 实得 0x%02X" % (expect_fc, fc))

    if fc in (0x03, 0x04):
        bytecount = frame[2]
        data = frame[3:3 + bytecount]
        if expect_count is not None and len(data) != expect_count * 2:
            raise ProtocolError(
                "数据长度不符：期望 %d 字节实得 %d" % (expect_count * 2, len(data)))
        return data
    if fc == 0x06:
        return frame[2:6]
    if fc == 0x10:
        return frame[2:6]  # 起始地址 + 数量
    raise ProtocolError("不支持的功能码 0x%02X" % fc)


def parse_read_words(data):
    """把读响应的数据字节解析为 16 位无符号整数列表。"""
    return [struct.unpack(">H", data[i:i + 2])[0] for i in range(0, len(data), 2)]


# ---------------------------------------------------------------------------
# MBAP（Modbus TCP）
# ---------------------------------------------------------------------------
def build_mbap_request(slave, pdu, tid):
    """pdu = 功能码 + 数据（不含地址、不含 CRC）。返回完整 MBAP 帧。"""
    # 数据长度 = 单元号(1) + PDU 长度
    length = 1 + len(pdu)
    return struct.pack(">HHHB", tid, 0x0000, length, slave) + pdu


def parse_mbap_response(frame, tid=None):
    """解析 MBAP 响应帧，返回 (事务ID, PDU 数据字节)。

    异常响应抛 ModbusError。
    """
    if len(frame) < 9:
        raise ProtocolError("MBAP 响应帧过短：%d 字节" % len(frame))
    tid_r, proto, length = struct.unpack(">HHH", frame[:6])
    if proto != 0:
        raise ProtocolError("MBAP 协议标识非 0：0x%04X" % proto)
    unit = frame[6]
    pdu = frame[7:6 + length]  # 去掉 unit 后剩余 = PDU（length 含 unit 1 字节）
    if len(pdu) < 1:
        raise ProtocolError("MBAP 响应 PDU 为空")
    fc = pdu[0]
    if fc & 0x80:
        code = pdu[1] if len(pdu) > 1 else 0x04
        raise ModbusError(code)
    return tid_r, pdu


# ---------------------------------------------------------------------------
# 传输层
# ---------------------------------------------------------------------------
class BaseTransport:
    def exchange(self, frame, want, timeout):
        raise NotImplementedError


class SerialTransport(BaseTransport):
    """串口 RTU。"""

    def __init__(self, port, baudrate=9600, parity="N", stopbits=1,
                 bytesize=8, timeout=1.0):
        import serial
        self._ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
            write_timeout=timeout,
        )
        # 不 flush：Windows 上 USB 转串口异常时 FlushFileBuffers 可能卡死

    def exchange(self, frame, want, timeout):
        self._ser.write(frame)
        return self._read_until(want, timeout)

    def _read_until(self, want, timeout):
        """累计读取直到达到 want 字节或超时；want=-1 表示读到首帧判长。"""
        buf = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline and len(buf) < want:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self._ser.timeout = max(0.05, min(remaining, 0.2))
            chunk = self._ser.read(128)
            if chunk:
                buf += chunk
        return bytes(buf)

    def close(self):
        try:
            if getattr(self, "_ser", None) and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass


class TcpTransport(BaseTransport):
    """TCP。mode='rtu' 裸 RTU 透传，mode='tcp' 标准 Modbus TCP（MBAP）。"""

    def __init__(self, host, port, timeout=1.5, mode="tcp"):
        import socket
        self._mode = mode
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._tid = 0

    def _next_tid(self):
        self._tid = (self._tid + 1) & 0xFFFF
        return self._tid

    def exchange(self, frame, want, timeout):
        self._sock.settimeout(timeout)
        if self._mode == "tcp":
            # frame 是 RTU 帧，需要转成 MBAP
            pdu = frame[1:-2]  # 去地址 + 去 CRC
            mbap = build_mbap_request(frame[0], pdu, self._next_tid())
            self._sock.sendall(mbap)
            return self._read_mbap(want, timeout)
        else:
            self._sock.sendall(frame)
            return self._read_until(want, timeout)

    def _read_until(self, want, timeout):
        buf = bytearray()
        deadline = time.time() + timeout
        while time.time() < deadline and len(buf) < want:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self._sock.settimeout(max(0.05, min(remaining, 0.2)))
            try:
                chunk = self._sock.recv(512)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
        return bytes(buf)

    def _read_mbap(self, want, timeout):
        # MBAP 响应长度 = 6 头 + length；want 参数在此给的是数据字节数
        buf = bytearray()
        deadline = time.time() + timeout
        # 先读 6 字节头
        while time.time() < deadline and len(buf) < 6:
            remaining = deadline - time.time()
            self._sock.settimeout(max(0.05, min(remaining, 0.2)))
            try:
                c = self._sock.recv(6 - len(buf))
            except Exception:
                break
            if not c:
                break
            buf += c
        if len(buf) < 6:
            return bytes(buf)
        length = struct.unpack(">H", buf[4:6])[0]
        total = 6 + length
        while time.time() < deadline and len(buf) < total:
            remaining = deadline - time.time()
            self._sock.settimeout(max(0.05, min(remaining, 0.2)))
            try:
                c = self._sock.recv(total - len(buf))
            except Exception:
                break
            if not c:
                break
            buf += c
        return bytes(buf)

    def close(self):
        try:
            if getattr(self, "_sock", None):
                self._sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 设备对象（封装高层读写）
# ---------------------------------------------------------------------------
class Device:
    """一个采集卡设备。绑定传输层 + 协议模式，提供高层读写接口。"""

    def __init__(self, transport, mode="rtu", slave=1):
        self.t = transport
        self.mode = mode  # 'rtu' 或 'tcp'
        self.slave = slave

    # -- 读寄存器 --
    def read_registers(self, start, count, fc=0x03):
        frame = build_read(self.slave, fc, start, count)
        rx = self._exchange(frame, want=self._resp_len_read(count))
        if self.mode == "tcp":
            _, pdu = parse_mbap_response(rx)
            if pdu[0] != fc:
                raise ProtocolError("功能码不符")
            bytecount = pdu[1]
            data = pdu[2:2 + bytecount]
            if len(data) != count * 2:
                raise ProtocolError("数据长度不符")
            return parse_read_words(data)
        data = parse_rtu_response(rx, expect_fc=fc, expect_count=count)
        return parse_read_words(data)

    # -- 写单个寄存器 --
    def write_single(self, addr, value):
        frame = build_write_single(self.slave, addr, value)
        rx = self._exchange(frame, want=self._resp_len_write_single())
        if self.mode == "tcp":
            _, pdu = parse_mbap_response(rx)
            return
        parse_rtu_response(rx, expect_fc=0x06)

    # -- 写多个寄存器 --
    def write_multi(self, start, values):
        frame = build_write_multi(self.slave, start, values)
        rx = self._exchange(frame, want=self._resp_len_write_multi())
        if self.mode == "tcp":
            _, pdu = parse_mbap_response(rx)
            return
        parse_rtu_response(rx, expect_fc=0x10)

    # -- 内部 --
    def _exchange(self, frame, want):
        try:
            return self.t.exchange(frame, want, timeout=1.5)
        except ModbusError:
            raise
        except Exception as e:
            raise ProtocolError("链路错误：%s" % e)

    def _exchange_raw_rtu(self, frame):
        """直接发一帧 RTU 报文，读回原始响应（用于调试/发报文）。"""
        try:
            return self.t.exchange(frame, want=64, timeout=1.5)
        except Exception as e:
            raise ProtocolError("链路错误：%s" % e)

    def _exchange_raw_mbap(self, slave, pdu):
        """把 slave+pdu 打包成 MBAP 帧发出，读回原始 MBAP 响应。"""
        import struct
        tid = 1
        mbap = build_mbap_request(slave, pdu, tid)
        try:
            rx = self.t.exchange(mbap, want=64, timeout=1.5)
        except Exception as e:
            raise ProtocolError("链路错误：%s" % e)
        return rx

    @staticmethod
    def _resp_len_read(count):
        # RTU: 1+1+1+2*count+2 ；MBAP 由 transport 内部按头处理
        return 5 + 2 * count

    @staticmethod
    def _resp_len_write_single():
        return 8

    @staticmethod
    def _resp_len_write_multi():
        return 8

    def close(self):
        self.t.close()
