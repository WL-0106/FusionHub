# -*- coding: utf-8 -*-
"""Modbus RTU 协议栈（零第三方依赖，手写实现）。

依据：锐测 RISE / 上海域信 PK 系列模拟量输入模块通讯规约。
    · CRC16 多项式 0xA001，低字节在前
    · 功能码 03 读保持寄存器、06 写单寄存器
    · 手册报文样例已固化为 tests/selftest.py 的断言
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
    # 兼容「寄存器值为单字节、非 16 位对齐」的非标准从站：按响应里的字节数判定长度
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
    """RS-485 串口传输。依赖 pyserial（Windows 自带 Python 需 pip install pyserial）。"""

    def __init__(self, port: str, baudrate: int = 9600, bytesize: int = 8,
                 parity: str = "N", stopbits: float = 1, timeout: float = 0.6):
        try:
            import serial  # 延迟导入：没装 pyserial 时也能 import 本模块跑测试
        except ImportError as e:
            raise ProtocolError("缺少 pyserial 库，无法打开串口：%s\n"
                                "请用 pip install pyserial 安装，或改用「模块搜索」以外的 TCP 方式。" % e)
        self.port_name, self.baudrate = port, baudrate
        # Windows 上部分 USB-RS485 转换器把 RTS 接在方向控制上，拉高会关掉接收器。
        # 默认关闭 RTS/DTR 是国内 RS485 转换器最稳的默认做法。
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
        # 不调 flush()：Windows 上 FlushFileBuffers 在 USB 转换器异常时可能无限期阻塞
        self._s.write(data)

    def read_exact(self, want: int, timeout: float = None) -> bytes:
        """累计读取直到达到期望长度或超时；收到部分数据后缩短等待窗口。"""
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
            except socket_timeout_types() as e:
                if "timed out" in str(e).lower():
                    break
                raise ProtocolError("网络接收失败：%s" % e)
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


def socket_timeout_types():
    import socket
    return (socket.timeout, TimeoutError)


# ---------------------------------------------------------------- 设备对象

# 波特率码：手册 0000H 低 8 位，03H~07H 对应 1200~19200
BAUD_CODES = {1200: 0x03, 2400: 0x04, 4800: 0x05, 9600: 0x06, 19200: 0x07}
BAUD_BY_CODE = {v: k for k, v in BAUD_CODES.items()}


class PK60xx:
    """锐测 PK6011R 单相电参数采集模块。

    寄存器表（功能码 03H 读取，地址无偏移）：
        0x0000  量程       高 8 位=电压量程(×2 V)，低 8 位=电流量程(A)
        0x0001  变比       高 8 位=电压变比 UBB，低 8 位=电流变比 IBB（默认 1）
        0x0002  电压 U     raw/10×UBB  V
        0x0003  电流 I     raw/1000×IBB  A
        0x0004  有功功率 P  raw/10×UBB×IBB  W（int16）
        0x0005  无功功率 Q  同上 var
        0x0006  功率因数 PF raw/10000（int16）
        0x0007  视在功率 S  raw/10×UBB×IBB  VA
        0x0008  频率 F     raw/100  Hz
        0x0009~0x0010  电能（4 个 32 位：正/反向有功、正/反向无功）
    功能码 06H：
        写 0x0000 = 新地址(高字节) + 波特率码(低字节，3~7)
        写 0x0001 = 电压变比(高字节) + 电流变比(低字节)

    注意：地址/波特率是「只写」，FC03 读 0x0000 返回的是量程，不是地址波特率。
    """

    def __init__(self, transport, slave: int = 1, trace=None):
        self.t = transport
        self.slave = int(slave)
        self.trace = trace
        self._lock = threading.Lock()
        # 能力探测：某些机型对未公开寄存器静默不答，探测一次失败就永久跳过
        self._capability = {}

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
        """探测在位：只读 1 个寄存器（0000H），任何异常都吞掉。"""
        try:
            self.read_registers(0, 1, timeout=timeout)
            return True
        except Exception:
            return False

    # ---------------- 高层 ----------------

    def read_all(self, timeout: float = None) -> dict:
        """一条报文读完 0x0000~0x0010（17 个寄存器）：量程/变比/电参数/电能。

        PK6011R 是单相电参数模块，寄存器 0~16 一次读完比逐项读快得多。
        """
        regs = self.read_registers(0, 17, timeout=timeout)
        range_word = regs[0]
        ratio_word = regs[1]
        u_range = ((range_word >> 8) & 0xFF) * 2          # 电压量程 V
        i_range = range_word & 0xFF                       # 电流量程 A
        ubb = (ratio_word >> 8) & 0xFF or 1               # 电压变比
        ibb = ratio_word & 0xFF or 1                      # 电流变比
        return {
            "u_range": u_range,
            "i_range": i_range,
            "ubb": ubb,
            "ibb": ibb,
            "raw": regs,
        }

    def read_measurement(self, timeout: float = None) -> dict:
        """读 0x0002~0x0010 电参数，返回原始值列表（15 个）。"""
        return self.read_registers(2, 15, timeout=timeout)

    def read_config(self, timeout: float = None) -> dict:
        """读 0x0000~0x0001 量程与变比。"""
        r = self.read_registers(0, 2, timeout=timeout)
        return {
            "u_range": ((r[0] >> 8) & 0xFF) * 2,
            "i_range": r[0] & 0xFF,
            "ubb": (r[1] >> 8) & 0xFF,
            "ibb": r[1] & 0xFF,
        }

    def read_address_baud(self) -> tuple:
        """PK6011R 地址波特率是只写寄存器（FC06 写 0x0000），FC03 读 0x0000
        返回的是「电压量程/电流量程」，不是地址波特率。

        因此无法直接读回地址波特率；此处用读到的量程反推不靠谱，改由
        搜索时记录「能响应的从站地址」作为地址。此方法保留但语义改为：
        返回 (None, None)，调用方应改用搜索/记录地址。
        """
        return None, None

    def save_address_baud(self, addr: int, baud: int) -> int:
        """功能码 06H 写 0x0000：高字节=新地址，低字节=波特率码。

        改完模块会切到新参数，必须重新连接才能继续通讯——这是设备行为，不是软件 bug。
        """
        if not 1 <= addr <= 0xF7:
            raise ProtocolError("模块地址必须在 1~247（01H~F7H）")
        if baud not in BAUD_CODES:
            raise ProtocolError("波特率 %s 不在设备支持列表（1200/2400/4800/9600/19200）" % baud)
        value = (addr << 8) | BAUD_CODES[baud]
        got = self.write_register(0x0000, value)
        if got != value:
            raise ProtocolError("写回读值 %04X 与预置值 %04X 不一致，模块可能拒绝本次修改" % (got, value))
        return got

    def save_ratio(self, ubb: int, ibb: int) -> int:
        """功能码 06H 写 0x0001：高字节=电压变比，低字节=电流变比。"""
        if not (0 < ubb <= 0xFF and 0 < ibb <= 0xFF):
            raise ProtocolError("变比必须在 1~255 之间")
        value = (ubb << 8) | ibb
        got = self.write_register(0x0001, value)
        if got != value:
            raise ProtocolError("写回读值 %04X 与预置值 %04X 不一致" % (got, value))
        return got

    def set_slave(self, slave: int) -> None:
        self.slave = int(slave)

    def close(self) -> None:
        self.t.close()


def search_slaves(transport_factory, start: int, end: int, on_hit=None, should_stop=None) -> list:
    """按地址区间扫描模块。transport_factory(slave) -> PK60xx。

    0 与 255 是广播地址，从站不会回读，扫到也没意义，这里直接排除。
    PK6011R 地址波特率不可读回，命中即记录该从站地址。
    """
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
