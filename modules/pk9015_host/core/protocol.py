# -*- coding: utf-8 -*-
"""Modbus RTU 协议栈（零第三方依赖，手写实现）。

依据：锐测 RISE / 上海域信 PK 系列模拟量输入模块通讯规约（从测试软件反推）。
    · CRC16 多项式 0xA001，低字节在前
    · 功能码 03 读保持寄存器、06 写单寄存器
    · PK9015 12 路电流：读 0x0003~0x000E；量程写 0x02BE；地址波特率写 0x0000

协议栈与 modules.pk6011r_host.core.protocol 同源（同族 PK 系列设备），
设备对象改为 PK9015 的语义。
"""

from __future__ import annotations

import struct
import threading
import time


# ---------------------------------------------------------------- 异常

class ProtocolError(Exception):
    """链路或协议层错误。UI 一律只显示这个类，避免英文系统错误漏到用户眼前。"""


class ModbusException(ProtocolError):
    """从站返回的 Modbus 异常响应。"""

    CODES = {
        0x01: "非法功能码",
        0x02: "非法数据地址",
        0x03: "非法数据值（写入值超量程，或前置寄存器未设置）",
        0x04: "从站设备故障",
        0x05: "确认（处理中）",
        0x06: "从站忙",
        0x08: "存储奇偶校验错",
        0x0A: "网关路径不可用",
        0x0B: "网关目标设备无响应",
    }

    def __init__(self, func: int, code: int):
        self.func, self.code = func, code
        super().__init__("Modbus 异常 %02X：%s" % (code, self.CODES.get(code, "未知异常码")))


# ---------------------------------------------------------------- CRC

def crc16(data: bytes) -> int:
    """Modbus CRC16（0xA001），返回整型；线上传输时低字节在前。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def append_crc(body: bytes) -> bytes:
    return body + struct.pack("<H", crc16(body))


def hexs(data: bytes) -> str:
    return " ".join("%02X" % b for b in data)


# ---------------------------------------------------------------- 报文编解码

def build_read(slave: int, start: int, count: int) -> bytes:
    if not 1 <= count <= 125:
        raise ProtocolError("读取数量 %d 非法（Modbus 允许 1~125）" % count)
    if not 0 <= start <= 0xFFFF:
        raise ProtocolError("起始地址 %d 越界" % start)
    return append_crc(struct.pack(">BBHH", slave & 0xFF, 0x03, start, count))


def build_write_single(slave: int, addr: int, value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ProtocolError("写入值 %d 超出 16 位范围" % value)
    return append_crc(struct.pack(">BBHH", slave & 0xFF, 0x06, addr & 0xFFFF, value))


def expect_len_for_read(reg_count: int) -> int:
    """RTU 读响应长度：1(ID)+1(FC)+1(ByteCount)+2*N+2(CRC)。"""
    return 5 + 2 * reg_count


def parse_read_response(frame: bytes, reg_count: int) -> list:
    """解析读响应，返回寄存器整数列表。"""
    if len(frame) < 3:
        raise ProtocolError("响应过短（%d 字节）" % len(frame))
    if frame[1] & 0x80:
        raise ModbusException(frame[1] & 0x7F, frame[2] if len(frame) > 2 else 0)
    if frame[1] != 0x03:
        raise ProtocolError("功能码不匹配：期望 03H，收到 %02XH" % frame[1])
    bc = frame[2]
    want = reg_count * 2
    if bc != want:
        if bc == reg_count:
            want = reg_count
        else:
            raise ProtocolError("字节计数 %d 与请求的 %d 个寄存器不符" % (bc, reg_count))
    if len(frame) < 3 + want + 2:
        raise ProtocolError("响应长度不足：需要 %d 字节，实收 %d 字节" % (3 + want + 2, len(frame)))
    body, got = frame[:-2], struct.unpack("<H", frame[-2:])[0]
    if crc16(body) != got:
        raise ProtocolError("CRC 校验失败：收到 %04X，算得 %04X" % (got, crc16(body)))
    data = frame[3:3 + want]
    if want == reg_count:  # 单字节寄存器
        return list(data)
    return list(struct.unpack(">%dH" % reg_count, data))


def parse_echo_response(frame: bytes, sent: bytes) -> int:
    """解析 FC06 回显，返回写回的值。"""
    if len(frame) < 3:
        raise ProtocolError("写响应过短（%d 字节）" % len(frame))
    if frame[1] & 0x80:
        raise ModbusException(frame[1] & 0x7F, frame[2] if len(frame) > 2 else 0)
    if frame[1] != 0x06:
        raise ProtocolError("写响应功能码不匹配：期望 06H，收到 %02XH" % frame[1])
    body, got = frame[:-2], struct.unpack("<H", frame[-2:])[0]
    if crc16(body) != got:
        raise ProtocolError("写响应 CRC 校验失败")
    if frame[:6] != sent[:6]:
        raise ProtocolError("写响应回显与请求不一致：%s" % hexs(frame[:6]))
    return struct.unpack(">H", frame[4:6])[0]


# ---------------------------------------------------------------- 传输层

class SerialTransport:
    """RS-485 串口传输。依赖 pyserial。"""

    def __init__(self, port: str, baudrate: int = 9600, bytesize: int = 8,
                 parity: str = "N", stopbits: float = 1, timeout: float = 0.6):
        try:
            import serial
        except ImportError as e:
            raise ProtocolError("缺少 pyserial 库，无法打开串口：%s\n"
                                "请用 pip install pyserial 安装，或改用「模拟从站」。" % e)
        self.port_name, self.baudrate = port, baudrate
        # Windows 上部分 USB-RS485 转换器把 RTS 接在方向控制上，拉高会关掉接收器。
        self._s = serial.Serial(
            port=port, baudrate=baudrate, bytesize=bytesize, parity=parity,
            stopbits=stopbits, timeout=timeout, write_timeout=timeout,
            rtscts=False, dsrdtr=False, xonxoff=False,
        )
        try:
            self._s.rts = False
            self._s.dtr = False
        except Exception:
            pass
        self.timeout = timeout
        self._closing = False

    def write(self, data: bytes) -> None:
        if self._closing:
            raise ProtocolError("串口已关闭")
        self._s.write(data)

    def read_exact(self, want: int, timeout: float = None) -> bytes:
        tmo = self.timeout if timeout is None else timeout
        deadline = time.time() + tmo
        buf = bytearray()
        while len(buf) < want:
            if self._closing:
                raise ProtocolError("串口已关闭")
            remain = deadline - time.time()
            if remain <= 0:
                break
            chunk = self._s.read(min(want - len(buf), max(1, int(remain * 1000))))
            if chunk:
                buf += chunk
                deadline = min(deadline, time.time() + max(0.12, tmo * 0.35))
        return bytes(buf)

    def exchange(self, frame: bytes, want: int, timeout: float = None) -> bytes:
        try:
            self.write(frame)
        except ProtocolError:
            raise
        except Exception as e:
            raise ProtocolError("串口发送失败：%s" % e)
        rx = self.read_exact(want, timeout)
        if not rx:
            raise ProtocolError("无有效响应（收到 0 字节）")
        return rx

    def close(self) -> None:
        self._closing = True
        try:
            if self._s.is_open:
                self._s.close()
        except Exception:
            pass

    def is_open(self) -> bool:
        try:
            return self._s.is_open
        except Exception:
            return False


class TcpTransport:
    """RTU over TCP / TCP 串口服务器。"""

    def __init__(self, host: str, port: int, timeout: float = 0.6):
        import socket
        self.s = socket.create_connection((host, int(port)), timeout=timeout)
        self.s.settimeout(timeout)
        self.timeout = timeout
        self._closing = False

    def exchange(self, frame: bytes, want: int, timeout: float = None) -> bytes:
        tmo = self.timeout if timeout is None else timeout
        try:
            self.s.sendall(frame)
        except Exception as e:
            raise ProtocolError("网络发送失败：%s" % e)
        buf = bytearray()
        deadline = time.time() + tmo
        while len(buf) < want:
            if self._closing:
                raise ProtocolError("连接已关闭")
            remain = deadline - time.time()
            if remain <= 0:
                break
            try:
                chunk = self.s.recv(want - len(buf))
            except socket.timeout:
                break
            except Exception as e:
                raise ProtocolError("网络接收失败：%s" % e)
            if not chunk:
                break
            buf += chunk
            deadline = min(deadline, time.time() + max(0.12, tmo * 0.35))
        if not buf:
            raise ProtocolError("无有效响应（收到 0 字节）")
        return bytes(buf)

    def close(self) -> None:
        self._closing = True
        try:
            self.s.close()
        except Exception:
            pass

    def is_open(self) -> bool:
        return not self._closing


# ---------------------------------------------------------------- 设备对象

from . import registers as R  # noqa: E402

BAUD_CODES = R.BAUD_CODES
BAUD_BY_CODE = R.BAUD_BY_CODE


class PK9015:
    """锐测 PK9015 12 路电流采集模块。

    寄存器表（功能码 03H 读取）：
        0x0000  地址+波特率（高 8 位地址，低 8 位波特率码）
        0x0003~0x000E  12 路电流 I0~I11（16 位无符号，raw/10000）
        0x02BE  量程设置（0=0-20mA、1=4-20mA、2=0-10V）
    功能码 06H：
        写 0x0000 = 新地址(高字节) + 波特率码(低字节)
        写 0x02BE = 量程选择

    注意：地址/波特率写后模块立即切换，需按新参数重新连接。
    """

    def __init__(self, transport, slave: int = 1, trace=None):
        self.t = transport
        self.slave = int(slave)
        self.trace = trace
        self._lock = threading.Lock()

    # ---------------- 底层 ----------------

    def _exchange(self, frame: bytes, want: int, timeout: float = None, retry: int = 1):
        last = None
        for attempt in range(retry + 1):
            try:
                rx = self.t.exchange(frame, want, timeout)
                if self.trace:
                    self.trace(frame, rx)
                return rx
            except ProtocolError as e:
                last = e
                if "CRC" in str(e) and attempt < retry:
                    continue
                if "0 字节" in str(e) and attempt < retry:
                    time.sleep(0.05)
                    continue
                raise
        raise last

    def read_registers(self, start: int, count: int, timeout: float = None) -> list:
        with self._lock:
            frame = build_read(self.slave, start, count)
            rx = self._exchange(frame, expect_len_for_read(count), timeout)
        return parse_read_response(rx, count)

    def write_register(self, addr: int, value: int, timeout: float = None) -> int:
        with self._lock:
            frame = build_write_single(self.slave, addr, value)
            rx = self._exchange(frame, 8, timeout)
        return parse_echo_response(rx, frame)

    def ping(self, timeout: float = 0.35) -> bool:
        """探测在位：读 0x0003 起 1 个寄存器，任何异常都吞掉。"""
        try:
            self.read_registers(R.REG_I0, 1, timeout=timeout)
            return True
        except Exception:
            return False

    # ---------------- 高层 ----------------

    def read_currents(self, timeout: float = None) -> list:
        """读 12 路电流原始值（16 位无符号列表，长度 12）。"""
        return self.read_registers(R.REG_I0, R.CHANNEL_COUNT, timeout=timeout)

    def read_config(self, timeout: float = None) -> dict:
        """读 0x0000（地址+波特率）与 0x02BE（量程）。"""
        r0 = self.read_registers(R.REG_ADDR_BPS, 1, timeout=timeout)
        addr_word = r0[0]
        addr = (addr_word >> 8) & 0xFF
        baud_code = addr_word & 0xFF
        range_code = self._read_range(timeout=timeout)
        return {
            "addr": addr,
            "baud_code": baud_code,
            "baud": BAUD_BY_CODE.get(baud_code, 9600),
            "range_code": range_code,
            "range_label": R.RANGE_LABELS.get(range_code, "未知"),
        }

    def _read_range(self, timeout: float = None) -> int:
        try:
            r = self.read_registers(R.REG_RANGE, 1, timeout=timeout)
            return r[0] & 0xFF
        except Exception:
            return R.RANGE_0_20MA

    def read_range(self, timeout: float = None) -> int:
        """读量程设置，返回量程码（0/1/2）。"""
        return self._read_range(timeout=timeout)

    def save_range(self, range_code: int) -> int:
        """功能码 06H 写 0x02BE：设置量程。"""
        if range_code not in R.RANGE_LABELS:
            raise ProtocolError("量程码 %d 非法（0=0-20mA、1=4-20mA、2=0-10V）" % range_code)
        got = self.write_register(R.REG_RANGE, range_code)
        return got

    def save_address_baud(self, addr: int, baud: int) -> int:
        """功能码 06H 写 0x0000：高字节=新地址，低字节=波特率码。"""
        if not 1 <= addr <= 0xF7:
            raise ProtocolError("模块地址必须在 1~247（01H~F7H）")
        if baud not in BAUD_CODES:
            raise ProtocolError("波特率 %s 不在设备支持列表（1200/2400/4800/9600/19200）" % baud)
        value = (addr << 8) | BAUD_CODES[baud]
        got = self.write_register(R.REG_ADDR_BPS, value)
        if got != value:
            raise ProtocolError("写回读值 %04X 与预置值 %04X 不一致，模块可能拒绝本次修改" % (got, value))
        return got

    def set_slave(self, slave: int) -> None:
        self.slave = int(slave)

    def close(self) -> None:
        self.t.close()


def search_slaves(transport_factory, start: int, end: int, on_hit=None, should_stop=None) -> dict:
    """按地址区间扫描模块。transport_factory(slave) -> PK9015。"""
    found, tested = [], 0
    lo, hi = sorted((int(start), int(end)))
    for slave in range(max(1, lo), min(247, hi) + 1):
        if should_stop is not None and should_stop():
            break
        tested += 1
        dev = None
        try:
            dev = transport_factory(slave)
            if dev.ping(timeout=0.30):
                item = {"slave": slave}
                found.append(item)
                if on_hit:
                    on_hit(item)
        except Exception:
            pass
        finally:
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass
    return {"found": found, "tested": tested}
