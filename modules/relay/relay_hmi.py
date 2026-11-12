# -*- coding: utf-8 -*-
"""
测控机箱(AXI1018) 继电器板卡 (12CH) 上位机控制软件
================================================================
适配手册：《测控机箱(AXI1018)继电器板卡(12CH) 说明书》

协议要点（摘自说明书，并已用其示例报文逐字节验证）：
  · RS485 / 9600 / 8 数据位 / 1 停止位 / 无校验 / Modbus-RTU
  · 02H  读输入状态（离散输入，首地址 0000H，开入 1~16）
  · 03H  读保持寄存器（首地址 2000H，寄存器值为单字节，字节对齐）
  · 05H  写单个线圈（0000H=断开，FF00H=闭合）
  · 0FH  写多个线圈（支持广播地址 0xFF，模块不回复）
  · 线圈地址 0000H~000BH 对应 继电器1~继电器12
  · 保持寄存器 2000H~2007H：硬件版本高/低、软件版本高/低、输入状态高/低、输出状态高/低

设计说明：
  · 协议栈自研，零第三方依赖（pyserial 仅在使用串口时需要）
  · tkinter 界面 + 单工作线程串行执行所有 Modbus 操作（保证帧不交错）
  · 支持 RTU over TCP，便于用自带模拟从站（tools/simulator.py）在无硬件时联调

运行：python relay_hmi.py     （需带 tkinter 的 Python，如 C:\\Program Files\\Python311\\python.exe）
"""

import sys
import os
import time
import queue
import struct
import socket
import base64
import zlib
import threading
import datetime

# ---------------------------------------------------------------- 可选依赖
try:
    import serial  # pyserial
    from serial.tools import list_ports as _list_ports
    HAS_SERIAL = True
except Exception:                                    # noqa: BLE001
    serial = None
    _list_ports = None
    HAS_SERIAL = False

# ---------------------------------------------------------------- 常量
APP_TITLE = "继电器板卡(12CH) 上位机  ·  测控机箱 AXI1018"
APP_VERSION = "1.0.2"

RELAY_COUNT = 12                 # 默认 / 最大继电器路数（线圈 0000H~000BH）
INPUT_COUNT = 16                 # 开入数（说明书附录输入地址表）
BOARD_RELAY_COUNTS = (8, 12)     # 可选板型：同一套协议，只是路数不同


def relay_no_of(addr, count, reverse):
    """线圈地址 → 继电器编号（1 基）。

    正序（默认）：继电器 N = 线圈 (N-1)H，按说明书直排。
    倒序：部分 8 路板丝印从反方向编，物理 1 号接的是最高位线圈——
    继电器 1 = 线圈 (count-1)，继电器 count = 线圈 0000H。
    超出本板路数的地址不参与倒序，按直排编号（自检扫超范围地址时展示用）。
    纯函数、不碰 tkinter——工作线程里也可用。
    """
    if reverse and 0 <= addr < count:
        return count - addr
    return addr + 1

FC_READ_DISCRETE = 0x02
FC_READ_HOLDING = 0x03
FC_WRITE_COIL = 0x05
FC_WRITE_COILS = 0x0F

REG_BASE = 0x2000                # 保持寄存器首地址
HOLDING_COUNT = 8                # 2000H~2007H，一次读完

MAX_COILS_PER_WRITE = 8          # 说明书功能码表：写多个线圈寄存器数量上限 08H
MAX_DISCRETE_PER_READ = 0x50     # 读输入状态上限 50H
MAX_HOLDING_PER_READ = 0x9F      # 读保持寄存器上限 9FH

BROADCAST_ADDR = 0xFF            # 说明书：支持广播地址(0xFF)，已由示例 CRC 反推确认
REBOOT_COIL_ADDR = 0x0755        # 模块重启：05H 写线圈 0755H
REBOOT_VALUE = 0x2345            # 模块重启魔数（V2.3 及以上支持）

DEFAULT_BAUD = 9600
DEFAULT_TIMEOUT = 0.30
DEFAULT_RETRY = 1

# 串口帧格式：说明书标称 9600 / 8 数据位 / 无校验 / 1 停止位，
# 但现场偶有 7 位、偶校验等情况，故做成可切换。
DEFAULT_BYTESIZE = 8
DEFAULT_PARITY = "N"
DEFAULT_STOPBITS = 1

DATABITS_CHOICES = ("5", "6", "7", "8")
PARITY_CHOICES = ("N 无校验", "E 偶校验", "O 奇校验", "M 标记 Mark", "S 空格 Space")
STOPBITS_CHOICES = ("1", "1.5", "2")

# 卡片排列：列数越少、行数越多，越容易把底部日志挤出可视区
CARD_LAYOUTS = (("每行 3 个（4 行）", 3), ("每行 4 个（3 行）", 4), ("每行 6 个（2 行）", 6))
CARD_LAYOUT_DEFAULT = "每行 4 个（3 行）"

# 灯就是按键：左半圆 = 闭合、右半圆 = 断开，点击区域就是灯本身，没有第二排小按钮。
# 卡片因此只有「标题 + 灯」两层，比原来「灯 + 下方两枚按钮」矮一大截。
#
# 卡片压缩档位（由大到小）。每档：灯直径 / 圆环内缩 / 半圆字号 /
# 标题字号 / 是否用「闭合·断开」双字标签（否则用「合·断」）/ 灯的上下留白。
# 行数多或窗口矮时自动降档，保证全部卡片都塞得进可视区，而不是被裁掉。
# 灯面是居中的单行文字（「闭合」/「断开」），整个直径都可用，48px 也放得下两个字。
CARD_LEVELS = (
    (80, 1, 10, 9, 3),
    (68, 1, 9, 9, 2),
    (64, 1, 8, 8, 2),
    (48, 1, 9, 8, 1),
)
CARD_ROW_GAP = 6                 # 卡片在网格中的上下外边距合计（pady=3）
WINDOW_GEOMETRY = "1180x820"     # 默认窗口尺寸（高度需容得下 4 行卡片 + 日志区）
LOG_DEFAULT_HEIGHT = 132         # 日志区初始高度
LOG_MIN_HEIGHT = 88              # 日志区被拖到最小的高度（仍能看到表头 + 2 行）


def parse_parity(text):
    """把下拉框文字转成 pyserial 的校验码（N/E/O/M/S），无法识别时回退 N。"""
    t = [c for c in (text or "N").strip().upper() if c in ("N", "E", "O", "M", "S")]
    return t[0] if t else "N"


def fmt_stopbits(value):
    """1.0 → '1'，1.5 → '1.5'，2.0 → '2'。"""
    try:
        return "%g" % float(value)
    except (TypeError, ValueError):
        return "1"

EXC_TEXT = {
    0x01: "非法功能码",
    0x02: "非法数据地址",
    0x03: "非法数据值",
    0x04: "从站设备故障",
    0x05: "确认（从站正在处理）",
    0x06: "从站设备忙",
    0x08: "存储奇偶校验错",
    0x0A: "网关路径不可用",
    0x0B: "网关目标设备无响应",
}


# ================================================================ 异常
class ModbusError(Exception):
    """协议层错误基类。"""


class TransportError(ModbusError):
    """链路层错误（端口打不开、连接断开等）。"""


class TransportTimeout(ModbusError):
    """等待响应超时。"""


class ModbusException(ModbusError):
    """从站返回异常响应（功能码最高位置 1）。"""

    def __init__(self, code, fc):
        self.code = code
        self.fc = fc
        text = EXC_TEXT.get(code, "未知异常")
        super().__init__("从站异常响应：功能码 0x%02X，异常码 0x%02X（%s）" % (fc, code, text))


class FrameError(ModbusError):
    """帧结构或 CRC 校验错误。"""


# ================================================================ CRC16
_CRC_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xA001 if _c & 1 else _c >> 1
    _CRC_TABLE.append(_c)


def crc16(data: bytes) -> bytes:
    """Modbus CRC16（多项式 0xA001），返回低字节在前的 2 字节。"""
    crc = 0xFFFF
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def append_crc(frame: bytes) -> bytes:
    """在帧尾追加 CRC。"""
    return frame + crc16(frame)


def check_crc(frame: bytes) -> bool:
    """校验整帧 CRC（含末尾 2 字节）。"""
    if len(frame) < 4:
        return False
    return crc16(frame[:-2]) == frame[-2:]


def fmt_hex(data) -> str:
    """字节串格式化为大写的空格分隔十六进制。"""
    if not data:
        return ""
    return " ".join("%02X" % b for b in bytes(data))


# ================================================================ 传输层
class Transport:
    """传输层统一接口：打开 / 写入 / 精确读取 n 字节 / 关闭。"""

    label = "TRANSPORT"

    def open(self):                                        # pragma: no cover
        raise NotImplementedError

    def close(self):                                       # pragma: no cover
        raise NotImplementedError

    def is_open(self) -> bool:                             # pragma: no cover
        raise NotImplementedError

    def write(self, data: bytes):                          # pragma: no cover
        raise NotImplementedError

    def read_exact(self, n: int, timeout: float) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def flush_input(self) -> None:                          # pragma: no cover
        """丢弃接收缓冲里可能残留的旧字节（RTU 一问一答，发送前缓冲内必是残渣）。"""
        raise NotImplementedError


class TcpTransport(Transport):
    """裸 RTU 帧透传（RTU over TCP），无 MBAP 头。"""

    def __init__(self, host, port, timeout=DEFAULT_TIMEOUT, mbap=False):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.mbap = mbap
        self._sock = None
        self.label = "TCP"

    def open(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:                              # noqa: BLE001
                pass
            self._sock = None

    def is_open(self):
        return self._sock is not None

    def write(self, data: bytes):
        if not self._sock:
            raise TransportError("TCP 连接未建立")
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise TransportError("TCP 发送失败：%s" % e)

    def flush_input(self):
        """非阻塞清空 TCP 接收缓冲（RTU over TCP 一般用不到，兜底无害）。"""
        if not self._sock:
            return
        try:
            self._sock.settimeout(0)
            while self._sock.recv(4096):
                pass
        except socket.timeout:
            pass
        except OSError:
            pass

    def read_exact(self, n, timeout):
        if not self._sock:
            raise TransportError("TCP 连接未建立")
        buf = bytearray()
        deadline = time.time() + timeout
        while len(buf) < n:
            remain = deadline - time.time()
            if remain <= 0:
                raise TransportTimeout("接收超时（已收 %d/%d 字节）" % (len(buf), n))
            self._sock.settimeout(remain)
            try:
                chunk = self._sock.recv(n - len(buf))
            except socket.timeout:
                raise TransportTimeout("接收超时（已收 %d/%d 字节）" % (len(buf), n))
            except OSError as e:
                raise TransportError("TCP 接收失败：%s" % e)
            if not chunk:
                raise TransportError("TCP 连接已被对端关闭")
            buf += chunk
        return bytes(buf)


class SerialTransport(Transport):
    """RS485 串口传输（需 pyserial）。"""

    def __init__(self, port, baudrate=DEFAULT_BAUD, bytesize=DEFAULT_BYTESIZE,
                 parity=DEFAULT_PARITY, stopbits=DEFAULT_STOPBITS,
                 timeout=DEFAULT_TIMEOUT):
        self.port = port
        self.baudrate = int(baudrate)
        try:
            self.bytesize = int(bytesize)
        except (TypeError, ValueError):
            self.bytesize = DEFAULT_BYTESIZE
        self.parity = parse_parity(str(parity))
        try:
            self.stopbits = float(stopbits)
        except (TypeError, ValueError):
            self.stopbits = float(DEFAULT_STOPBITS)
        self.timeout = timeout
        self._ser = None
        self._closing = False                 # 置位后读循环快速退出，保证跨线程关闭安全
        self.label = "SER"

    def frame_desc(self):
        """帧格式速记，如 8N1 / 8E1 / 7O2。"""
        return "%d%s%s" % (self.bytesize, self.parity, fmt_stopbits(self.stopbits))

    def open(self):
        if not HAS_SERIAL:
            raise TransportError("未安装 pyserial，无法使用串口。请执行：python -m pip install pyserial")
        try:
            self._ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
        except Exception as e:                             # noqa: BLE001
            # Windows 占用串口时报 PermissionError(13)（pyserial 包在 SerialException 里）
            text = "%s" % e
            if isinstance(e, PermissionError) or "PermissionError(13" in text \
                    or "拒绝访问" in text:
                raise TransportError(
                    "打开串口 %s 失败：串口被其他程序占用。\n"
                    "请关闭其它打开该串口的软件（串口调试助手、厂家上位机、本软件的另一个窗口等），"
                    "或在任务管理器结束残留进程后重试。" % self.port)
            if isinstance(e, FileNotFoundError) or "FileNotFoundError" in text \
                    or "系统找不到" in text:
                raise TransportError(
                    "打开串口 %s 失败：该串口不存在（设备未接好或已拔出）。\n"
                    "可在「串口」下拉框刷新后重新选择。" % self.port)
            raise TransportError("打开串口 %s 失败：%s" % (self.port, e))
        try:
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except Exception:                                  # noqa: BLE001
            pass
        self._closing = False

    def close(self):
        self._closing = True
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:                              # noqa: BLE001
                pass
            self._ser = None

    def is_open(self):
        return bool(self._ser and self._ser.is_open)

    def _friendly_err(self, e):
        """把运行中的串口异常翻译成可执行的恢复指引；非占位/掉线类返回 None。"""
        text = "%s" % e
        if isinstance(e, PermissionError) or "PermissionError(13" in text \
                or "拒绝访问" in text:
            return ("串口已被其他程序占用或设备已重新枚举"
                    "（USB 被拔插/驱动重置/另一程序打开了该口）。\n"
                    "恢复：点「断开」→ 重新插拔 USB 转 485 → "
                    "下拉框旁「刷新」重选串口 → 再「连接」。")
        if isinstance(e, FileNotFoundError) or "FileNotFoundError" in text \
                or "系统找不到" in text:
            return ("串口设备已消失（USB 被拔出或驱动重置）。\n"
                    "请重新插拔 USB 转 485，下拉框旁「刷新」后重新连接。")
        return None

    def write(self, data: bytes):
        if not self._ser or not self._ser.is_open:
            raise TransportError("串口未打开")
        try:
            self._ser.write(data)
            self._ser.flush()
        except Exception as e:                             # noqa: BLE001
            hint = self._friendly_err(e)
            if hint:
                raise TransportError(hint)
            raise TransportError("串口发送失败：%s" % e)

    def flush_input(self):
        """丢弃串口接收缓冲中的残字节（迟到响应/上一帧尾巴）。"""
        if self._ser is not None and self._ser.is_open:
            try:
                self._ser.reset_input_buffer()
            except Exception:                              # noqa: BLE001
                pass

    def read_exact(self, n, timeout):
        if not self._ser or not self._ser.is_open:
            raise TransportError("串口未打开")
        buf = bytearray()
        deadline = time.time() + timeout
        while len(buf) < n:
            if self._closing:
                raise TransportError("链路正在关闭")
            remain = deadline - time.time()
            if remain <= 0:
                raise TransportTimeout("接收超时（已收 %d/%d 字节）" % (len(buf), n))
            # 分小片读：单次最多阻塞 0.1s。Windows 下从另一线程 close 一个
            # 正阻塞在长 read 里的串口会挂起（关窗卡死的根源），
            # 分片后 close 最多等 0.1s 就能拿到控制权。
            self._ser.timeout = min(0.1, max(0.01, remain))
            try:
                chunk = self._ser.read(n - len(buf))
            except Exception as e:                         # noqa: BLE001
                if self._closing:
                    raise TransportError("链路正在关闭")
                hint = self._friendly_err(e)
                if hint:
                    raise TransportError(hint)
                raise TransportError("串口接收失败：%s" % e)
            if chunk:
                buf += chunk
            # 串口无数据时 read 会按超时返回空，继续循环直到总超时
        return bytes(buf)


def list_serial_ports():
    """枚举本机串口，返回 [(设备名, 描述), ...]。"""
    if not HAS_SERIAL:
        return []
    out = []
    for p in _list_ports.comports():
        desc = p.description or ""
        if desc in ("n/a", ""):
            desc = "串口设备"
        out.append((p.device, desc))
    out.sort(key=lambda x: x[0])
    return out


# ================================================================ 协议客户端
class StatusResult:
    """一次状态读取的结果。"""

    def __init__(self, hw_version, sw_version, inputs, outputs):
        self.hw_version = hw_version        # 字符串，如 "V1.0"
        self.sw_version = sw_version        # 字符串，如 "V2.2"
        self.inputs = inputs                # [bool] * 16
        self.outputs = outputs              # [bool] * 16（只用前 12 位）

    def __repr__(self):
        return "<Status hw=%s sw=%s out=%s>" % (
            self.hw_version, self.sw_version,
            "".join("1" if b else "0" for b in self.outputs[:RELAY_COUNT]))


def _ver_str(hi, lo):
    return "V%d.%d" % (hi & 0xFF, lo & 0xFF)


class RelayClient:
    """继电器板卡 Modbus-RTU 客户端。

    所有方法均为阻塞调用，必须运行在工作线程中。
    """

    def __init__(self, transport, slave_id=1, timeout=DEFAULT_TIMEOUT,
                 retry=DEFAULT_RETRY, trace=None):
        self.tr = transport
        self.slave_id = int(slave_id)
        self.timeout = float(timeout)
        self.retry = int(retry)
        self.trace = trace                 # 可选回调：trace(direction, bytes, extra)
        self.stats = {"tx": 0, "rx": 0, "err": 0, "last_rtt": 0.0}

    # ---------------- 底层 ----------------
    def _trace(self, direction, data, extra=""):
        if self.trace:
            try:
                self.trace(direction, data, extra)
            except Exception:                              # noqa: BLE001
                pass

    def _build(self, fc, payload, slave=None):
        sid = self.slave_id if slave is None else int(slave)
        frame = bytes((sid, fc)) + payload
        return append_crc(frame)

    @staticmethod
    def _response_kind(fc):
        """响应帧的收包形态：EXC / FIXED8 / BYTECOUNT。"""
        if fc & 0x80:
            return "EXC"
        if fc in (FC_READ_DISCRETE, FC_READ_HOLDING):
            return "BYTECOUNT"
        if fc in (FC_WRITE_COIL, FC_WRITE_COILS):
            return "FIXED8"
        return None

    def _exchange(self, frame, expect_response=True, timeout=None, slave=None):
        """发送一帧并接收响应。expect_response=False 时仅发送（广播）。"""
        timeout = self.timeout if timeout is None else timeout
        sid = self.slave_id if slave is None else int(slave)

        # 发送前冲掉接收缓冲：RTU 一问一答，此时缓冲里若有字节，
        # 必是上一次迟到的响应或残尾——不清掉会让本次从错位处开始读，
        # 且重试也读到同一批残字节，一次失配后整个自检全崩。
        self.tr.flush_input()
        self.tr.write(frame)
        self.stats["tx"] += 1
        self._trace("TX", frame)
        if not expect_response:
            return b""

        t0 = time.time()
        head = self.tr.read_exact(2, timeout)
        if head[0] != sid and sid not in (0x00, BROADCAST_ADDR):
            raise FrameError("响应设备地址不匹配：期望 %d，收到 %d（收到的头两字节 %s，"
                             "通常是上一帧响应迟到/残尾干扰）" % (sid, head[0], fmt_hex(head)))
        fc = head[1]
        kind = self._response_kind(fc)
        if kind is None:
            raise FrameError("无法识别的响应功能码 0x%02X" % fc)
        if kind == "EXC":
            resp = head + self.tr.read_exact(3, timeout)          # 异常码 + CRC2
        elif kind == "FIXED8":
            resp = head + self.tr.read_exact(6, timeout)          # 地址2 + 数值2 + CRC2
        else:
            bc = self.tr.read_exact(1, timeout)                   # 字节数
            resp = head + bc + self.tr.read_exact(bc[0] + 2, timeout)

        rtt = (time.time() - t0) * 1000.0
        self.stats["rx"] += 1
        self.stats["last_rtt"] = rtt
        self._trace("RX", resp, "%.0fms" % rtt)

        if not check_crc(resp):
            raise FrameError("CRC 校验失败：%s" % fmt_hex(resp))
        if resp[1] & 0x80:
            raise ModbusException(resp[2], resp[1] & 0x7F)
        if resp[1] != frame[1]:
            raise FrameError("响应功能码不符：期望 0x%02X，收到 0x%02X" % (frame[1], resp[1]))
        return resp

    def _request(self, frame, expect_response=True, timeout=None, slave=None, retry=None):
        """带重试的请求。"""
        tries = self.retry if retry is None else retry
        last = None
        for attempt in range(tries + 1):
            try:
                return self._exchange(frame, expect_response, timeout, slave)
            except ModbusException:
                self.stats["err"] += 1
                raise                                       # 从站明确拒绝，重试无意义
            except (TransportTimeout, FrameError) as e:
                last = e
                self.stats["err"] += 1
                if attempt < tries:
                    self._trace("!! ", b"", "第 %d 次重试：%s" % (attempt + 1, e))
                    time.sleep(0.05)
                    # 迟到的响应这时可能才到，重发前再冲一次，别让它污染重试
                    self.tr.flush_input()
            except TransportError as e:
                self.stats["err"] += 1
                raise TransportError(str(e))
        raise last

    # ---------------- 业务 ----------------
    def read_discrete_inputs(self, start=0, count=INPUT_COUNT, slave=None):
        """02H 读输入状态，返回 [bool] * count（bit i 对应开入 i+1）。"""
        if count < 1 or count > MAX_DISCRETE_PER_READ:
            raise ModbusError("读输入状态数量越界：%d（允许 1~%d）" % (count, MAX_DISCRETE_PER_READ))
        frame = self._build(FC_READ_DISCRETE, struct.pack(">HH", start, count), slave)
        resp = self._request(frame, True, None, slave)
        bc = resp[2]
        data = resp[3:3 + bc]
        return [bool((data[i // 8] >> (i % 8)) & 1) for i in range(count)]

    def read_holding_raw(self, start=REG_BASE, count=HOLDING_COUNT, slave=None):
        """03H 读保持寄存器，返回每个寄存器的整数值。

        说明书注明「寄存器值为单字节，字节对齐，低字节在前」，其示例
        01 03 20 00 00 04 -> 01 03 04 01 00 02 02（4 个寄存器只回 4 字节）。
        此处按返回的字节数自动判定：bc==count 为单字节模式，
        bc==2*count 为 16 位小端模式。
        """
        if count < 1 or count > MAX_HOLDING_PER_READ:
            raise ModbusError("读保持寄存器数量越界：%d（允许 1~%d）" % (count, MAX_HOLDING_PER_READ))
        if start < 0 or start + count > 0x10000:
            raise ModbusError("保持寄存器地址越界：0x%04X + %d" % (start, count))
        frame = self._build(FC_READ_HOLDING, struct.pack(">HH", start, count), slave)
        resp = self._request(frame, True, None, slave)
        bc = resp[2]
        data = resp[3:3 + bc]
        if bc == count:
            return list(data)
        if bc == 2 * count:
            return [data[i] | (data[i + 1] << 8) for i in range(0, bc, 2)]
        raise FrameError("保持寄存器响应字节数异常：%d（寄存器 %d 个，期望 %d 或 %d）"
                         % (bc, count, count, 2 * count))

    def read_status(self, slave=None):
        """一次读取 2000H~2007H，返回 StatusResult。

        开入/输出状态的两个字节按「低字节在前」拼装：
        2004H=开入 1~8、2005H=开入 9~16、2006H=继电器 1~8、2007H=继电器 9~16。
        注意：说明书寄存器表把 2004H/2006H 标成「高字节」，与它自己写的
        「低字节在前」矛盾；真机实测闭合继电器 1 时 2006H=0x01，故按低字节在前。
        """
        v = self.read_holding_raw(REG_BASE, HOLDING_COUNT, slave)
        hw = _ver_str(v[0], v[1])
        sw = _ver_str(v[2], v[3])
        in_word = ((v[5] & 0xFF) << 8) | (v[4] & 0xFF)
        out_word = ((v[7] & 0xFF) << 8) | (v[6] & 0xFF)
        inputs = [bool((in_word >> i) & 1) for i in range(INPUT_COUNT)]
        outputs = [bool((out_word >> i) & 1) for i in range(INPUT_COUNT)]
        return StatusResult(hw, sw, inputs, outputs)

    def write_single_coil(self, addr, on, slave=None, retry=None):
        """05H 写单个线圈。返回从站回显帧。retry 可覆盖默认重试次数（收尾清理用 0）。"""
        if addr < 0 or addr > 0xFFFF:
            raise ModbusError("线圈地址越界：%d" % addr)
        val = 0xFF00 if on else 0x0000
        frame = self._build(FC_WRITE_COIL, struct.pack(">HH", addr, val), slave)
        broadcast = (slave is not None and int(slave) == BROADCAST_ADDR) or \
                    (slave is None and self.slave_id == BROADCAST_ADDR)
        return self._request(frame, not broadcast, None, slave, retry=retry)

    def write_coils(self, start, values, slave=None):
        """0FH 写多个线圈，自动按 MAX_COILS_PER_WRITE 分块。

        values: 可迭代的 bool 序列。返回发送的分块数量。
        """
        values = [bool(v) for v in values]
        if not values:
            return 0
        broadcast = (slave is not None and int(slave) == BROADCAST_ADDR) or \
                    (slave is None and self.slave_id == BROADCAST_ADDR)
        chunks = 0
        for offset in range(0, len(values), MAX_COILS_PER_WRITE):
            block = values[offset:offset + MAX_COILS_PER_WRITE]
            qty = len(block)
            nbytes = (qty + 7) // 8
            payload = bytearray(struct.pack(">HHB", start + offset, qty, nbytes))
            data = bytearray(nbytes)
            for i, v in enumerate(block):
                if v:
                    data[i // 8] |= 1 << (i % 8)
            payload += data
            frame = self._build(FC_WRITE_COILS, bytes(payload), slave)
            self._request(frame, not broadcast, None, slave)
            chunks += 1
        return chunks

    def reboot(self, slave=None):
        """模块重启（V2.3 及以上）。重启时可能收不到响应，超时视为已下发。

        说明书示例写的是 01 05 07 55 23 45 DD FA，其中 DD FA 实为上一行
        「继电器1打开」的 CRC（复制粘贴笔误），正确 CRC 应为 04 6D，此处自行计算。
        """
        frame = self._build(FC_WRITE_COIL, struct.pack(">HH", REBOOT_COIL_ADDR, REBOOT_VALUE), slave)
        try:
            return self._request(frame, True, timeout=0.6, slave=slave, retry=0)
        except TransportTimeout:
            return b""                                     # 模块已重启，属正常

    def send_custom(self, frame_hex, auto_crc=True, expect_response=True):
        """发送自定义报文（十六进制字符串）。auto_crc=True 时自动追加 CRC。"""
        clean = "".join(ch for ch in frame_hex if ch not in " \t\r\n-_")
        try:
            raw = bytes.fromhex(clean)
        except ValueError as e:
            raise ModbusError("十六进制报文解析失败：%s" % e)
        if auto_crc:
            raw = append_crc(raw)
        if expect_response:
            return self._request(raw, True, timeout=max(1.0, self.timeout), retry=0)
        self.tr.write(raw)
        self.stats["tx"] += 1
        self._trace("TX", raw)
        return b""

    # ---------------- 生命周期 ----------------
    def connect(self):
        self.tr.open()

    def close(self):
        self.tr.close()

    def is_connected(self):
        return self.tr.is_open()


# ================================================================ 工作线程
class Worker(threading.Thread):
    """单工作线程串行执行所有 Modbus 操作，天然避免多帧交错。"""

    def __init__(self):
        super().__init__(daemon=True, name="modbus-worker")
        self.jobs = queue.Queue()
        self._halt = threading.Event()   # 不能叫 _stop：会覆盖 Thread 内部的 _stop()，join() 直接崩

    def submit(self, fn):
        if not self._halt.is_set():
            self.jobs.put(fn)

    def stop(self):
        self._halt.set()
        self.jobs.put(None)

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            try:
                job()
            except Exception as e:                          # noqa: BLE001
                # 任务自身应已捕获异常；此处兜底，避免线程意外退出后界面永远无响应
                print("worker 未捕获异常：%r" % (e,), file=sys.stderr)
                import traceback
                traceback.print_exc()


# ================================================================ 界面
def _enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:                                  # noqa: BLE001
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:                              # noqa: BLE001
                pass


def _build_ui():
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox, simpledialog
    return tk, ttk, scrolledtext, messagebox, simpledialog


# 颜色（浅色主题）
C_BG = "#f4f6f8"
C_PANEL = "#ffffff"
C_BORDER = "#d5dbe2"
C_TEXT = "#1f2933"
C_MUTED = "#6b7a8d"
C_ACCENT = "#1668dc"
C_ON = "#16a34a"
C_ON_DIM = "#86d3a8"
C_OFF = "#c8d0d9"
C_OFF_DIM = "#e2e7ec"
C_ERR = "#cf1322"
C_WARN = "#d48806"
C_OK = "#16a34a"


class LogPanel:
    """底部日志区：带「显示通讯报文」开关与行数上限。"""

    MAX_LINES = 3000
    TRIM_TO = 2000

    def __init__(self, tk, scrolledtext, parent, on_toggle):
        self.tk = tk
        bar = tk.Frame(parent, bg=C_BG)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(bar, text="运行日志", bg=C_BG, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")

        self.show_trace = tk.BooleanVar(value=True)
        # 原生 Checkbutton：clam 主题下 ttk 的选中标记会画成叉号
        tk.Checkbutton(
            bar, text="显示通讯报文", variable=self.show_trace,
            bg=C_BG, fg=C_TEXT, activebackground=C_BG, activeforeground=C_TEXT,
            selectcolor=C_PANEL, highlightthickness=0, bd=0,
            font=("Microsoft YaHei UI", 9), command=on_toggle,
        ).pack(side="left", padx=(14, 0))

        tk.Button(bar, text="清空", relief="flat", bg=C_PANEL, fg=C_TEXT,
                  activebackground="#e8edf2", bd=0, padx=10, pady=2,
                  font=("Microsoft YaHei UI", 9), command=self.clear).pack(side="right")

        wrap = tk.Frame(parent, bg=C_BG)
        wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.text = scrolledtext.ScrolledText(
            wrap, height=6, state="disabled", wrap="none",
            bg="#0f172a", fg="#cbd5e1", insertbackground="#cbd5e1",
            font=("Consolas", 9), relief="flat", borderwidth=1,
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_config("tx", foreground="#7dd3fc")
        self.text.tag_config("rx", foreground="#86efac")
        self.text.tag_config("info", foreground="#cbd5e1")
        self.text.tag_config("warn", foreground="#fbbf24")
        self.text.tag_config("err", foreground="#f87171")

    def clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")

    def append(self, msg, tag="info"):
        try:
            self.text.config(state="normal")
            self.text.insert("end", msg + "\n", tag)
            total = int(self.text.index("end-1c").split(".")[0])
            if total > self.MAX_LINES:
                self.text.delete("1.0", "%d.0" % (total - self.TRIM_TO + 1))
            self.text.see("end")
            self.text.config(state="disabled")
        except Exception:                                  # noqa: BLE001
            pass


# 卡片配色：整颗灯按状态整体着色——闭合时全绿、断开时全灰，不做双色拼接。
# 闭合/断开融合为整颗灯的单个按键：点一下闭合，再点一下断开（toggle）。
CARD_COLORS = {
    True: ("#16a34a", "#ffffff"),                # 已闭合 → 整颗全绿 + 白字
    False: ("#c8d0d9", "#3f4c5a"),               # 已断开 → 整颗全灰 + 深灰字
}
CARD_HOVER = {                                   # 鼠标悬停时在同色系里微亮/微暗
    True: "#25b25c",
    False: "#b6c0ca",
}
CARD_RING = {                                    # 外环（同一色系的深色）
    True: "#0f8a3d",
    False: "#a5b0bc",
}
CARD_DISABLED_FILL = "#f1f3f6"
CARD_DISABLED_TEXT = "#b9c0ca"


# ================================================================ 抗锯齿圆形
# tkinter Canvas 的 oval / arc 不做抗锯齿，圆形越大毛边越明显（截图里尤其糊）。
# 这里改为「超采样 + 手写 PNG」把圆渲染成 PhotoImage 再贴到 Canvas：
# 每个像素取 ss×ss 个子样点算覆盖率，再与背景色按覆盖率混色，边缘自然过渡。
# 只用标准库（zlib + base64），不引入 Pillow；结果按参数缓存，一次生成反复复用。
_AA_CACHE = {}
_AA_SAMPLES = 4                         # 每像素每方向的采样数（4 → 16 子样点）
LED_SIZE = 26                           # 状态灯画布边长
LED_INSET = 4                           # 状态灯圆的外边距
LED_RING = 1                            # 状态灯外环宽度


def _hex_rgb(color):
    """'#16a34a' → (22, 163, 74)。"""
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _png_bytes(w, h, raw_rgb_rows):
    """把「逐行 filter 字节 + RGB 像素」打包成 PNG（用于 tk.PhotoImage）。"""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8bit / 真彩 RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw_rgb_rows, 9))
            + chunk(b"IEND", b""))


def aa_circle_photo(tk, size, fill, ring, bg, ring_w=2, inset=0):
    """渲染一个带外环的抗锯齿实心圆，返回 tk.PhotoImage（按参数缓存）。

    size   画布边长（正方形）；fill 内部填充色；ring 外环色；bg 背景色
    ring_w 外环宽度；inset  圆外沿到画布边的像素余量（给抗锯齿留出过渡）。
    """
    key = (size, fill, ring, bg, ring_w, inset)
    img = _AA_CACHE.get(key)
    if img is not None:
        return img

    fr, fg, fb = _hex_rgb(fill)
    rr, rg, rb = _hex_rgb(ring)
    br, bgb, bb = _hex_rgb(bg)
    c = size / 2.0
    r_out = max(1.0, (size - 2.0 * inset) / 2.0)
    r_in_sq = max(0.0, r_out - ring_w) ** 2
    r_out_sq = r_out * r_out
    ss = _AA_SAMPLES
    n = ss * ss
    offs = [(i + 0.5) / ss for i in range(ss)]

    # 逐行拼 PNG 原始像素：每行先写 filter=0，再写 RGB
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        dy2 = [(y + o - c) ** 2 for o in offs]
        for x in range(size):
            dx = [x + o - c for o in offs]
            hit_fill = hit_ring = 0
            for sy in range(ss):
                base = dy2[sy]
                for sx in range(ss):
                    d2 = dx[sx] * dx[sx] + base
                    if d2 <= r_in_sq:
                        hit_fill += 1
                    elif d2 <= r_out_sq:
                        hit_ring += 1
            # 外环先按覆盖率混在背景上，内部填充再叠上去
            a_r = hit_ring / n
            a_f = hit_fill / n
            pr = br + (rr - br) * a_r
            pg = bgb + (rg - bgb) * a_r
            pb = bb + (rb - bb) * a_r
            pr += (fr - pr) * a_f
            pg += (fg - pg) * a_f
            pb += (fb - pb) * a_f
            rows += bytes((int(pr + 0.5), int(pg + 0.5), int(pb + 0.5)))

    import tkinter as _tkmod
    img = _tkmod.PhotoImage(data=base64.b64encode(_png_bytes(size, size, bytes(rows))),
                            format="png")
    _AA_CACHE[key] = img
    return img


def paint_led(led, color):
    """把状态灯（画布 + 图片项）刷成指定颜色的抗锯齿圆。

    led 是 (画布, 图片项, 编号标签) 三元组——标签可选，只取前两项。
    """
    cv, item = led[0], led[1]
    if getattr(cv, "_led_fill", None) == color:
        return
    cv._led_fill = color
    cv.itemconfig(item, image=aa_circle_photo(cv, LED_SIZE, color, C_BORDER,
                                              C_PANEL, LED_RING, LED_INSET))


class RelayCard:
    """单个继电器控制卡片：一颗「按键灯」。

    闭合、断开融合成整颗灯的一个按键：灯灭时点一下闭合，灯亮时再点一下断开。
    灯的颜色整体指示当前状态：闭合时全绿、断开时全灰；
    灯面文字提示下一次点击将执行的动作（灭显「闭合」、亮显「断开」）。

    支持通过 `set_level()` 切换压缩档位，使 12 张卡片在任意行数下都能完整显示。
    """

    def __init__(self, tk, parent, index, on_set):
        self.index = index
        self.on_set = on_set
        self.state = False
        self.enabled = False            # 未连接时不可点，点击直接忽略
        self.level = None
        self.size = 0
        self._hover = False

        self.frame = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER,
                              highlightthickness=1, bd=0)
        self.title = tk.Label(self.frame, text="继电器 %d" % (index + 1), bg=C_PANEL,
                              fg=C_TEXT, font=("Microsoft YaHei UI", 9, "bold"))
        self.title.pack(side="top", pady=(3, 0))

        self.canvas = tk.Canvas(self.frame, width=68, height=68, bg=C_PANEL,
                                highlightthickness=0, cursor="arrow")
        self.canvas.pack(side="top", pady=3)
        # 整颗灯就是一个按键：抗锯齿圆形贴图 + 居中的动作文字（文字在图片之上）
        self.lamp = self.canvas.create_image(0, 0)
        self.label = self.canvas.create_text(0, 0, text="闭合",
                                             font=("Microsoft YaHei UI", 8, "bold"))
        self.inset = 0
        self.fill_color = ""            # 当前填充色（测试用，避免去解析图片）
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.set_level(0)

    def set_number(self, n):
        """改卡片标题里的继电器编号（编号倒序切换时用）。"""
        self.title.config(text="继电器 %d" % n)

    # ------------------------------------------------------------- 交互
    def _on_click(self, _event):
        if not self.enabled:
            return
        # 乐观翻转：连点也能正确交替，写失败/偏差由回读状态纠正
        self.state = not self.state
        self._paint()
        self.on_set(self.index, self.state)

    def _on_motion(self, _event):
        h = self.enabled
        if h != self._hover:
            self._hover = h
            self._paint()

    def _on_leave(self, _event):
        if self._hover:
            self._hover = False
            self._paint()

    # ------------------------------------------------------------- 绘制
    def _paint(self):
        """按「状态 + 是否可用 + 悬停」重绘整颗灯。"""
        if not self.enabled:
            self._apply_photo(CARD_DISABLED_FILL, C_BORDER)
            self.canvas.itemconfig(self.label, fill=CARD_DISABLED_TEXT)
            self.canvas.config(cursor="arrow")
            return

        # 整颗灯同色：闭合全绿、断开全灰；悬停时整颗在同一色系里微亮/微暗
        self.canvas.config(cursor="hand2")
        fill, fg = CARD_COLORS[self.state]
        if self._hover:
            fill = CARD_HOVER[self.state]
        self._apply_photo(fill, CARD_RING[self.state])
        self.canvas.itemconfig(self.label, text="断开" if self.state else "闭合", fill=fg)

    def _apply_photo(self, fill, ring):
        """换上对应配色的抗锯齿圆（同色同尺寸直接复用缓存里的图）。"""
        self.fill_color = fill
        self.canvas.itemconfig(
            self.lamp,
            image=aa_circle_photo(self.canvas, self.size, fill, ring, C_PANEL,
                                  ring_w=2, inset=self.inset))

    def set_level(self, idx):
        """切换到第 idx 档压缩级别（0 最大）。"""
        idx = max(0, min(len(CARD_LEVELS) - 1, int(idx)))
        if idx == self.level:
            return
        self.level = idx
        size, inset, label_fs, title_fs, pad_y = CARD_LEVELS[idx]
        self.size = size
        half = size / 2.0

        self.title.config(font=("Microsoft YaHei UI", title_fs, "bold"))
        self.title.pack_configure(pady=(0 if idx >= 2 else 3, 0))

        self.canvas.config(width=size, height=size)
        self.canvas.pack_configure(pady=pad_y)
        self.inset = inset
        self.canvas.coords(self.lamp, half, half)
        self.canvas.coords(self.label, half, half)
        self.canvas.itemconfig(self.label,
                               font=("Microsoft YaHei UI", label_fs, "bold"))
        self._paint()

    def grid(self, **kw):
        self.frame.grid(**kw)

    def set_state(self, on):
        on = bool(on)
        if on == self.state:
            return
        self.state = on
        self._paint()

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if not enabled:
            self._hover = None
        self._paint()


class RelayHmiApp:
    """上位机主窗口。"""

    POLL_TICK_MS = 40                # 事件轮询周期

    def __init__(self):
        _enable_dpi_awareness()
        self.tk, self.ttk, self.scrolledtext, self.messagebox, self.simpledialog = _build_ui()
        tk, ttk = self.tk, self.ttk

        self.root = tk.Tk()
        self.root.title("%s   v%s" % (APP_TITLE, APP_VERSION))
        self.root.geometry(WINDOW_GEOMETRY)
        self.root.minsize(1040, 680)
        self.root.configure(bg=C_BG)
        try:
            ttk.Style().theme_use("clam")
        except Exception:                                  # noqa: BLE001
            pass
        self.root.option_add("*Font", ("Microsoft YaHei UI", 9))

        # ---- 状态 ----
        self.client = None
        self.worker = Worker()
        self.events = queue.Queue()
        self.busy = 0
        self._closing = False
        self._poll_after_id = None
        self._drain_after_id = None
        self.auto_poll = tk.BooleanVar(value=True)
        self.poll_interval_ms = 500
        self.poll_fails = 0
        self.poll_enabled_runtime = True
        self.show_trace = True
        # 板型：8 路 / 12 路板卡共用一套界面，切换时重建卡片与输出指示灯
        self.relay_count = RELAY_COUNT
        self.reverse_num_var = tk.BooleanVar(value=False)   # 继电器编号倒序（板子丝印反向时勾上）
        self.last_outputs = [False] * self.relay_count
        self.stat_vars = {}
        self.card_cols = 4
        self.left_body = None
        self.card_level = -1
        self._level_h = None              # 各压缩档位的实测卡片高度，首次装配时生成
        self._fit_pending = False
        self._building_levels = False
        self._last_target = None
        self._fit_after_id = None
        self.scan_running = False          # 自检进行中（禁用「开始自检」、显示「自检中」）
        self._last_scan = None             # 最近一次自检结果，供测试/排查读取

        # 连接栏固定在上、状态条固定在下，中间（卡片区 + 日志区）交给可拖动分隔条，
        # 卡片区还会按剩余高度自动压缩档位，两者配合保证「不丢卡片、也看得见日志」。
        self._build_connect_bar()
        self._build_statusbar()
        self._build_split()

        self.worker.start()
        self._refresh_ports()
        self._update_conn_ui(False, "未连接")
        self.log("软件已启动。默认 9600/8/N/1，Modbus-RTU。", "info")
        if not HAS_SERIAL:
            self.log("未检测到 pyserial，串口功能不可用（网络方式仍可用）。"
                     "安装：python -m pip install pyserial", "warn")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(self.POLL_TICK_MS, self._drain_events)
        self.root.after(600, self._poll_tick)

    # ------------------------------------------------------------ 布局
    def _card(self, parent, title=None, head_hook=None):
        """建一张带标题的卡片。head_hook(header_frame) 可在标题行右侧追加控件。"""
        tk = self.tk
        outer = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER,
                         highlightthickness=1, bd=0)
        body = outer
        if title:
            head = tk.Frame(outer, bg=C_PANEL)
            head.pack(fill="x", padx=10, pady=(8, 2))
            tk.Label(head, text=title, bg=C_PANEL, fg=C_TEXT,
                     font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
            if head_hook is not None:
                head_hook(head)
            body = tk.Frame(outer, bg=C_PANEL)
            body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        return outer, body

    def _build_connect_bar(self):
        tk, ttk = self.tk, self.ttk
        bar = tk.Frame(self.root, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        bar.pack(fill="x", padx=10, pady=(8, 5))
        inner = tk.Frame(bar, bg=C_PANEL)
        inner.pack(fill="x", padx=10, pady=6)

        # ---- 第一行：链路类型 + 连接动作 ----
        top = tk.Frame(inner, bg=C_PANEL)
        top.pack(fill="x")

        tk.Label(top, text="链路", bg=C_PANEL, fg=C_TEXT).pack(side="left", padx=(0, 6))
        self.link_mode = tk.StringVar(value="serial")
        for val, txt in (("serial", "RS485 串口"), ("tcp", "网络 (RTU over TCP)")):
            tk.Radiobutton(top, text=txt, value=val, variable=self.link_mode,
                           bg=C_PANEL, fg=C_TEXT, activebackground=C_PANEL,
                           selectcolor=C_PANEL, highlightthickness=0, bd=0,
                           command=self._on_link_mode_change).pack(side="left", padx=(0, 10))

        right = tk.Frame(top, bg=C_PANEL)
        right.pack(side="right")
        self.btn_disconnect = tk.Button(right, text="断开", relief="flat", bd=0,
                                        bg="#eef1f5", fg=C_TEXT, activebackground="#e0e5eb",
                                        padx=14, pady=2, state="disabled",
                                        command=self.on_disconnect)
        self.btn_disconnect.pack(side="right")
        self.btn_connect = tk.Button(right, text="连接", relief="flat", bd=0,
                                     bg=C_ACCENT, fg="#ffffff", activebackground="#0d55b8",
                                     activeforeground="#ffffff", padx=18, pady=2,
                                     font=("Microsoft YaHei UI", 9, "bold"),
                                     command=self.on_connect)
        self.btn_connect.pack(side="right", padx=(0, 6))
        # side="right" 时先 pack 的靠最右，故按「断开 → 连接 → 输入框 → 标签」逆序入栈，
        # 最终视觉顺序为：从站地址 [输入框] [连接] [断开]
        self.slave_var = tk.StringVar(value="1")
        tk.Spinbox(right, from_=0, to=255, width=4, textvariable=self.slave_var,
                   justify="center").pack(side="right")
        tk.Label(right, text="从站地址", bg=C_PANEL, fg=C_TEXT).pack(side="right", padx=(14, 6))

        # ---- 第二行：链路参数（串口 / 网络 二选一） ----
        param = tk.Frame(inner, bg=C_PANEL)
        param.pack(fill="x", pady=(4, 0))

        self.serial_row = tk.Frame(param, bg=C_PANEL)
        self.serial_row.pack(side="left")
        tk.Label(self.serial_row, text="串口", bg=C_PANEL, fg=C_TEXT).pack(side="left", padx=(0, 4))
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(self.serial_row, textvariable=self.port_var, width=24,
                                       state="readonly")
        self.port_combo.pack(side="left")
        tk.Button(self.serial_row, text="刷新", relief="flat", bg=C_PANEL, fg=C_ACCENT,
                  activebackground="#eaf2fd", bd=0, padx=8,
                  command=self._refresh_ports).pack(side="left", padx=(4, 12))
        tk.Label(self.serial_row, text="波特率", bg=C_PANEL, fg=C_TEXT).pack(side="left")
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        ttk.Combobox(self.serial_row, textvariable=self.baud_var, width=7, state="readonly",
                     values=("1200", "2400", "4800", "9600", "19200", "38400",
                             "57600", "115200")).pack(side="left", padx=(4, 12))
        # 帧格式三项均可调（说明书标称 8/N/1）
        tk.Label(self.serial_row, text="数据位", bg=C_PANEL, fg=C_TEXT).pack(
            side="left", padx=(0, 4))
        self.databits_var = tk.StringVar(value=str(DEFAULT_BYTESIZE))
        ttk.Combobox(self.serial_row, textvariable=self.databits_var, width=3,
                     state="readonly", values=DATABITS_CHOICES).pack(
            side="left", padx=(0, 12))
        tk.Label(self.serial_row, text="校验", bg=C_PANEL, fg=C_TEXT).pack(
            side="left", padx=(0, 4))
        self.parity_var = tk.StringVar(value=PARITY_CHOICES[0])
        ttk.Combobox(self.serial_row, textvariable=self.parity_var, width=11,
                     state="readonly", values=PARITY_CHOICES).pack(
            side="left", padx=(0, 12))
        tk.Label(self.serial_row, text="停止位", bg=C_PANEL, fg=C_TEXT).pack(
            side="left", padx=(0, 4))
        self.stopbits_var = tk.StringVar(value=fmt_stopbits(DEFAULT_STOPBITS))
        ttk.Combobox(self.serial_row, textvariable=self.stopbits_var, width=3,
                     state="readonly", values=STOPBITS_CHOICES).pack(
            side="left", padx=(0, 10))

        self.tcp_row = tk.Frame(param, bg=C_PANEL)
        self.tcp_row.pack(side="left")
        tk.Label(self.tcp_row, text="地址", bg=C_PANEL, fg=C_TEXT).pack(side="left", padx=(0, 4))
        self.host_var = tk.StringVar(value="127.0.0.1")
        tk.Entry(self.tcp_row, textvariable=self.host_var, width=16).pack(side="left")
        tk.Label(self.tcp_row, text="端口", bg=C_PANEL, fg=C_TEXT).pack(side="left", padx=(10, 4))
        self.tcpport_var = tk.StringVar(value="10502")
        tk.Entry(self.tcp_row, textvariable=self.tcpport_var, width=7).pack(side="left")
        tk.Label(self.tcp_row, text="（裸 RTU 帧透传，无 MBAP 头）", bg=C_PANEL,
                 fg=C_MUTED).pack(side="left", padx=(10, 0))
        self.tcp_row.pack_forget()

    def _build_split(self):
        """中下部用可拖动的分隔条：卡片区与日志区的高度现场可调。

        固定高度写死不可能同时满足「4 行卡片都要在」和「日志要看得见」，
        所以把决定权交给分隔条：默认偏向卡片区，需要看日志时往上拖。
        """
        tk = self.tk
        self.split = tk.PanedWindow(self.root, orient="vertical", sashwidth=6,
                                    sashrelief="raised", handlesize=0,
                                    bd=0, bg=C_BG)
        self.split.pack(fill="both", expand=True)
        self._build_work_area(self.split)
        self._build_log(self.split)

    def _build_work_area(self, parent):
        """上半容器：中间为「卡片 + 状态监控」，底部为全控条。"""
        tk = self.tk
        area = tk.Frame(parent, bg=C_BG)
        self.work_area = area
        self.split.add(area, stretch="always", minsize=170)
        self._build_action_bar(area)      # 先占住容器底部
        self._build_middle(area)          # 其余空间给卡片与状态监控

    def _build_middle(self, parent):
        tk, ttk = self.tk, self.ttk
        mid = tk.Frame(parent, bg=C_BG)
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # ---- 左：继电器控制（放在可滚动容器里，窗口再矮也不会丢卡片） ----
        left, left_holder = self._card(
            mid, "继电器控制  ·  点灯即切换：点一下闭合，再点一下断开",
            head_hook=self._build_layout_picker)
        left.pack(side="left", fill="both", expand=True)

        self.card_canvas = tk.Canvas(left_holder, bg=C_PANEL, highlightthickness=0)
        self.card_vbar = tk.Scrollbar(left_holder, orient="vertical",
                                      command=self.card_canvas.yview)
        self.card_canvas.configure(yscrollcommand=self.card_vbar.set)
        self.card_canvas.pack(side="left", fill="both", expand=True)
        self._vbar_shown = False

        self.left_body = tk.Frame(self.card_canvas, bg=C_PANEL)
        self._card_win = self.card_canvas.create_window((0, 0), window=self.left_body,
                                                        anchor="nw")
        self.card_canvas.bind("<Configure>", self._on_card_canvas_configure)
        self.left_body.bind("<Configure>", self._on_card_body_configure)

        self.cards = []
        self._build_cards()                 # 按当前板型（8/12 路）生成卡片
        self._apply_card_layout(dict(CARD_LAYOUTS)[CARD_LAYOUT_DEFAULT])

        # ---- 右：状态监控（可滚动） ----
        right = tk.Frame(mid, bg=C_BG, width=330)
        right.pack(side="left", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        canvas = tk.Canvas(right, bg=C_BG, highlightthickness=0, width=320)
        vbar = tk.Scrollbar(right, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        holder = tk.Frame(canvas, bg=C_BG)
        canvas.create_window((0, 0), window=holder, anchor="nw", width=306)
        holder.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        self.right_canvas = canvas
        # 滚轮按指针位置分派，否则鼠标停在卡片上会去滚右侧面板（原来 bind_all 的副作用）
        self.root.bind_all("<MouseWheel>", self._on_mouse_wheel)

        # 版本
        box, body = self._card(holder, "版本信息")
        box.pack(fill="x")
        self._kv_row(body, 0, "硬件版本", "hw_version", "—")
        self._kv_row(body, 1, "软件版本", "sw_version", "—")

        # 输出状态
        box, body = self._card(holder, "输出状态（回读）")
        box.pack(fill="x", pady=(8, 0))
        self.out_led_body = body            # 切板型时整块重建
        self.out_leds = self._led_grid(body, self.relay_count, 6)

        # 开入状态
        box, body = self._card(holder, "开入状态（02H 读输入）")
        box.pack(fill="x", pady=(8, 0))
        self.in_leds = self._led_grid(body, INPUT_COUNT, 8)

        # 通讯统计
        box, body = self._card(holder, "通讯统计")
        box.pack(fill="x", pady=(8, 0))
        self._kv_row(body, 0, "发送帧", "tx", "0")
        self._kv_row(body, 1, "接收帧", "rx", "0")
        self._kv_row(body, 2, "错误数", "err", "0")
        self._kv_row(body, 3, "末帧耗时", "rtt", "—")

        # 继电器自检：跑任意地址段，逐路点亮并回读确认
        box, body = self._card(holder, "继电器自检")
        box.pack(fill="x", pady=(8, 0))
        self._build_scan_controls(body)

        # 自检问题点位：跑完后在此罗列具体问题，方便排查
        box, body = self._card(holder, "自检问题点位")
        box.pack(fill="x", pady=(8, 0))
        self._build_scan_list(body)

    def _build_layout_picker(self, head):
        """卡片标题行右侧：「排列」选择器 + 「8 路 / 12 路」板型切换按钮。"""
        tk, ttk = self.tk, self.ttk
        self.card_layout_cb = ttk.Combobox(head, width=14, state="readonly",
                                           values=tuple(self._layout_labels()))
        self.card_cols_var = tk.StringVar(value=CARD_LAYOUT_DEFAULT)
        self.card_layout_cb.config(textvariable=self.card_cols_var)
        self.card_layout_cb.pack(side="right")
        self.card_layout_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_card_layout())
        tk.Label(head, text="排列", bg=C_PANEL, fg=C_MUTED).pack(side="right", padx=(0, 6))

        # 板型：两个互斥按钮，选中的那个高亮（同厂 8 路板也用同一套协议，只是路数少）
        self.board_buttons = {}
        wrap = tk.Frame(head, bg=C_PANEL)
        wrap.pack(side="right", padx=(0, 14))
        for n in BOARD_RELAY_COUNTS:
            b = tk.Button(wrap, text="%d 路" % n, relief="flat", bd=0, padx=8, pady=1,
                          font=("Microsoft YaHei UI", 9, "bold"),
                          command=lambda n=n: self._set_board(n))
            b.pack(side="left", padx=(2, 0))
            self.board_buttons[n] = b
        tk.Label(head, text="板型", bg=C_PANEL, fg=C_MUTED).pack(side="right", padx=(0, 6))
        # 编号倒序：部分 8 路板丝印反向（物理 1 号 = 最高位线圈），勾上后界面编号跟丝印对齐
        tk.Checkbutton(head, text="编号倒序", variable=self.reverse_num_var,
                       command=self._on_reverse_num, bg=C_PANEL, fg=C_TEXT,
                       activebackground=C_PANEL, selectcolor=C_PANEL,
                       highlightthickness=0, bd=0).pack(side="right", padx=(0, 12))
        self._paint_board_buttons()

    def _layout_labels(self):
        """按当前路数生成排列选项文案（如 12 路 → 「每行 3 个（4 行）」）。"""
        return tuple("每行 %d 个（%d 行）" % (cols, -(-self.relay_count // cols))
                     for _lbl, cols in CARD_LAYOUTS)

    def _paint_board_buttons(self):
        for n, b in self.board_buttons.items():
            if n == self.relay_count:
                b.config(bg=C_ACCENT, fg="#ffffff", activebackground=C_ACCENT,
                         activeforeground="#ffffff")
            else:
                b.config(bg="#e8edf2", fg=C_TEXT, activebackground="#dbe3ec",
                         activeforeground=C_TEXT)

    def _apply_relay_numbers(self):
        """按当前编号方向刷新卡片标题与输出指示灯下的编号（主线程）。"""
        rev = bool(self.reverse_num_var.get())
        n = self.relay_count
        for i, card in enumerate(self.cards):
            card.set_number(relay_no_of(i, n, rev))
        for i, led in enumerate(getattr(self, "out_leds", [])):
            if len(led) > 2:
                led[2].config(text=str(relay_no_of(i, n, rev)))

    def _on_reverse_num(self):
        self._apply_relay_numbers()
        self.log("继电器编号已切换为%s。"
                 % ("倒序（物理 1 号 = 最高位线圈 0007H/000BH）"
                    if self.reverse_num_var.get() else "正序（继电器 N = 线圈 N-1）"),
                 "info")

    def _set_board(self, n):
        """切换 8 路 / 12 路板型：重建卡片与输出指示灯，并同步自检默认数量。"""
        n = int(n)
        if n == self.relay_count:
            return
        self.relay_count = n
        self._rebuild_cards()
        self._rebuild_out_leds()
        self.last_outputs = [False] * n
        if getattr(self, "scan_count_var", None) is not None:
            self.scan_count_var.set(str(n))
        self._paint_board_buttons()
        # 排列选项里写着「几行」，路数变了文案要跟着变
        self.card_layout_cb["values"] = tuple(self._layout_labels())
        self.card_cols_var.set("每行 %d 个（%d 行）"
                               % (self.card_cols, -(-n // self.card_cols)))
        self.log("板型已切换为 %d 路继电器。" % n, "info")
        if getattr(self, "client", None) and self.client.is_connected():
            self._submit_status_read(first=True)     # 立刻按新路数刷新状态

    def _build_cards(self):
        for c in self.cards:
            c.frame.destroy()
        self.cards = []
        rev = bool(self.reverse_num_var.get())
        for i in range(self.relay_count):
            c = RelayCard(self.tk, self.left_body, i, self.cmd_set_relay)
            c.set_number(relay_no_of(i, self.relay_count, rev))
            self.cards.append(c)

    def _rebuild_cards(self):
        """切板型时重建卡片，并重排 + 重新选压缩档位。"""
        self._level_h = None                # 卡片换了，档位高度重新实测
        self.card_level = -1
        self._build_cards()
        connected = getattr(self, "client", None) is not None \
            and self.client.is_connected()
        self._set_channel_buttons(connected)
        self._apply_card_layout(self.card_cols)   # 内部会排一次自适应装配
        self._schedule_card_fit()

    def _rebuild_out_leds(self):
        """切板型时重建右侧「输出状态」的指示灯。"""
        body = getattr(self, "out_led_body", None)
        if body is None:
            return
        for w in body.winfo_children():
            w.destroy()
        self.out_leds = self._led_grid(body, self.relay_count, 6)

    def _on_card_layout(self):
        cols = dict(CARD_LAYOUTS).get(self.card_cols_var.get())
        if cols:
            self._apply_card_layout(cols)
            self.log("卡片排列已切换为「%s」。" % self.card_cols_var.get(), "info")

    def _apply_card_layout(self, cols):
        """按「每行 cols 个」重排 12 张卡片，并复位旧的行列配置。

        行高/档位交给 `_fit_cards()` 统一决定，这里只负责摆放位置。
        """
        cols = max(1, min(self.relay_count, int(cols)))
        self.card_cols = cols
        for c in self.cards:
            c.grid(row=c.index // cols, column=c.index % cols,
                   padx=4, pady=CARD_ROW_GAP // 2, sticky="nsew")
        if getattr(self, "left_body", None) is None:
            return
        for i in range(RELAY_COUNT):                       # 清掉上一次的残留配置（按最大路数清）
            self.left_body.rowconfigure(i, weight=0, minsize=0)
            self.left_body.columnconfigure(i, weight=0, minsize=0)
        self._last_target = None
        self._schedule_card_fit()

    # ------------------------------------------------- 卡片区自适应装配
    def _on_card_canvas_configure(self, event):
        self.card_canvas.itemconfigure(self._card_win, width=event.width)
        self._schedule_card_fit()

    def _on_card_body_configure(self, _event):
        self._schedule_card_fit()

    def _schedule_card_fit(self):
        if self._closing or self._building_levels or self._fit_pending:
            return
        self._fit_pending = True
        self._fit_after_id = self.root.after_idle(self._fit_cards)

    def _measure_card_levels(self):
        """实测每一档的真实卡片高度（字体在不同机器上略有差异，不写死数字）。"""
        self._building_levels = True
        try:
            heights = []
            for i in range(len(CARD_LEVELS)):
                for c in self.cards:
                    c.level = -1                       # 强制重设，否则同一档会被跳过
                    c.set_level(i)
                self.left_body.update_idletasks()
                heights.append(self.cards[0].frame.winfo_reqheight())
        finally:
            self._building_levels = False
        return heights

    def _fit_cards(self):
        """按可视高度挑压缩档位并重设行高——保证 12 张卡片全部落在可视区内。

        能放下就用最大档位平铺；放不下就用最小档位并让容器出现滚动条，
        绝不再出现「第 4 行被渲染到可视区外」的情况。
        """
        self._fit_pending = False
        if self._closing or getattr(self, "left_body", None) is None or not self.cards:
            return
        rows = -(-self.relay_count // self.card_cols)
        if self._level_h is None:
            self._level_h = self._measure_card_levels()
        vp_h = self.card_canvas.winfo_height()
        vp_w = self.card_canvas.winfo_width()
        if vp_h <= 1 or vp_w <= 1:
            return

        per_row = vp_h / float(rows)
        idx = len(CARD_LEVELS) - 1
        for i, h in enumerate(self._level_h):
            if h + CARD_ROW_GAP <= per_row:
                idx = i
                break
        # 每一档都套一遍：set_level 自身对同档会早退，代价极低；
        # 这样即使外部把卡片档位改乱（如测量流程结束时停在最后一档），也能自愈。
        for c in self.cards:
            c.set_level(idx)
        self.card_level = idx

        row_h = self._level_h[idx] + CARD_ROW_GAP
        for r in range(rows):
            self.left_body.rowconfigure(r, weight=1, minsize=row_h)
        min_w = 108 if self.card_cols <= 4 else 84
        for cidx in range(self.card_cols):
            self.left_body.columnconfigure(cidx, weight=1, minsize=min_w)

        need = rows * row_h                                # 内容所需高度（解析式，避免再触发重排）
        target = max(need, vp_h)
        if self._last_target != target:
            self._last_target = target
            self.card_canvas.itemconfigure(self._card_win, height=target)
            self.card_canvas.configure(scrollregion=(0, 0, vp_w, target))
        overflow = need > vp_h
        if overflow and not self._vbar_shown:
            self.card_vbar.pack(side="right", fill="y")
            self._vbar_shown = True
        elif not overflow and self._vbar_shown:
            self.card_vbar.pack_forget()
            self._vbar_shown = False

    @staticmethod
    def _inside(widget, ancestor):
        """widget 是否在 ancestor 之内（用于按指针位置分派滚轮）。"""
        while widget is not None:
            if widget is ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_mouse_wheel(self, event):
        step = int(-event.delta / 120) or int(-event.delta)
        if self._inside(event.widget, self.card_canvas):
            self.card_canvas.yview_scroll(step, "units")
        elif self._inside(event.widget, self.right_canvas):
            self.right_canvas.yview_scroll(step, "units")

    def _kv_row(self, parent, row, label, key, default):
        tk = self.tk
        tk.Label(parent, text=label, bg=C_PANEL, fg=C_MUTED).grid(
            row=row, column=0, sticky="w", pady=2)
        var = self.tk.StringVar(value=default)
        tk.Label(parent, textvariable=var, bg=C_PANEL, fg=C_TEXT,
                 font=("Consolas", 10, "bold")).grid(row=row, column=1, sticky="e", pady=2)
        parent.columnconfigure(1, weight=1)
        self.stat_vars[key] = var
        return var

    def _led_grid(self, parent, count, per_row):
        tk = self.tk
        leds = []
        grid = tk.Frame(parent, bg=C_PANEL)
        grid.pack(anchor="w")
        for i in range(count):
            wrap = tk.Frame(grid, bg=C_PANEL)
            wrap.grid(row=i // per_row, column=i % per_row, padx=3, pady=2)
            cv = tk.Canvas(wrap, width=LED_SIZE, height=LED_SIZE, bg=C_PANEL,
                           highlightthickness=0)
            cv.pack()
            # 与卡片灯同理：贴抗锯齿圆，而不是 Canvas 的锯齿椭圆
            circle = cv.create_image(LED_SIZE // 2, LED_SIZE // 2)
            cv.itemconfig(circle, image=aa_circle_photo(cv, LED_SIZE, C_OFF, C_BORDER,
                                                        C_PANEL, LED_RING, LED_INSET))
            cv._led_fill = C_OFF
            num_label = tk.Label(wrap, text=str(i + 1), bg=C_PANEL, fg=C_MUTED,
                                 font=("Microsoft YaHei UI", 7))
            num_label.pack()
            leds.append((cv, circle, num_label))
        return leds

    def _build_action_bar(self, parent):
        """全控条。分两行排——单行实测要 1369px，在 1180 宽窗口下
        「模块重启 / 自定义报文」会被压成 1px 宽，等于功能不可达。"""
        tk = self.tk
        bar = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        bar.pack(side="bottom", fill="x", padx=10, pady=(0, 6))
        inner = tk.Frame(bar, bg=C_PANEL)
        inner.pack(fill="x", padx=10, pady=5)

        row1 = tk.Frame(inner, bg=C_PANEL)
        row1.pack(fill="x")
        row2 = tk.Frame(inner, bg=C_PANEL)
        row2.pack(fill="x", pady=(4, 0))

        tk.Label(row1, text="全控", bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", padx=(0, 10))

        def mk(text, bg, fg, cmd, width=9, row=None):
            b = tk.Button(row if row is not None else row1, text=text, relief="flat", bd=0,
                          bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                          width=width, pady=2, font=("Microsoft YaHei UI", 9), command=cmd)
            b.pack(side="left", padx=3)
            return b

        self.btn_all_on = mk("全部闭合", "#e8f5ee", "#12703c", lambda: self.cmd_all(True))
        self.btn_all_off = mk("全部断开", "#eef1f5", "#495867", lambda: self.cmd_all(False))
        self.btn_all_inv = mk("全部取反", "#eaf2fd", "#1668dc", self.cmd_invert)
        self.btn_bc_on = mk("广播闭合", "#fff4e6", "#ad4e00", lambda: self.cmd_all(True, broadcast=True))
        self.btn_bc_off = mk("广播断开", "#fff4e6", "#ad4e00", lambda: self.cmd_all(False, broadcast=True))
        self.all_buttons = [self.btn_all_on, self.btn_all_off, self.btn_all_inv,
                            self.btn_bc_on, self.btn_bc_off]

        self.bulk_var = tk.BooleanVar(value=True)
        tk.Checkbutton(row1, text="全控用 0FH 批量写（每帧≤8路）", variable=self.bulk_var,
                       bg=C_PANEL, fg=C_TEXT, activebackground=C_PANEL, selectcolor=C_PANEL,
                       highlightthickness=0, bd=0).pack(side="left", padx=(12, 0))

        # ---- 第二行：轮询与工具 ----
        tk.Checkbutton(row2, text="自动轮询", variable=self.auto_poll,
                       bg=C_PANEL, fg=C_TEXT, activebackground=C_PANEL, selectcolor=C_PANEL,
                       highlightthickness=0, bd=0,
                       command=self._on_auto_poll).pack(side="left")
        tk.Label(row2, text="周期(ms)", bg=C_PANEL, fg=C_MUTED).pack(side="left", padx=(8, 4))
        self.interval_var = tk.StringVar(value=str(self.poll_interval_ms))
        self.tk.Spinbox(row2, from_=100, to=10000, increment=100, width=6,
                        textvariable=self.interval_var, justify="center",
                        command=self._on_interval, ).pack(side="left")
        mk("读取状态", "#eaf2fd", "#1668dc", self.cmd_read_status, width=9, row=row2)

        tk.Label(row2, text="│", bg=C_PANEL, fg=C_BORDER).pack(side="left", padx=10)
        mk("模块重启", "#fdeceb", "#cf1322", self.cmd_reboot, width=9, row=row2)
        mk("自定义报文", "#f2f4f7", "#495867", self.cmd_custom, width=10, row=row2)

    # ------------------------------------------------------------ 继电器自检
    def _build_scan_controls(self, parent):
        """继电器自检控制区：地址段 + 从站地址范围 + 速度 + 反检 + 开始/清除。

        跑「任意地址段 × 任意从站段」——逐站逐路下发闭合、再回读确认；
        勾选「反检」后在闭合确认通过后紧接着断开并回读复测（揪出粘死的继电器）。
        全部通过的弹窗提示无误，有问题的弹窗列出问题点并在右侧
        「自检问题点位」面板里罗列具体点位（从站 + 继电器 + 线圈地址 + 原因）。
        """
        tk = self.tk

        row1 = tk.Frame(parent, bg=C_PANEL)
        row1.pack(fill="x", pady=2)
        tk.Label(row1, text="起始地址", bg=C_PANEL, fg=C_TEXT).pack(side="left")
        self.scan_start_var = tk.StringVar(value="0")
        tk.Spinbox(row1, from_=0, to=65535, width=7, textvariable=self.scan_start_var,
                   justify="center").pack(side="left", padx=(4, 12))
        tk.Label(row1, text="数量", bg=C_PANEL, fg=C_TEXT).pack(side="left")
        # 状态字只有 16 位（2006H/2007H），可回读验证的地址上限为 15；
        # 超出部分仍会下发，但回读无法确认，会作为「未验证」问题点列出。
        self.scan_count_var = tk.StringVar(value=str(self.relay_count))
        tk.Spinbox(row1, from_=1, to=16, width=5, textvariable=self.scan_count_var,
                   justify="center").pack(side="left", padx=(4, 0))

        # 从站地址范围：可一次扫多台板卡（1~247）
        row2 = tk.Frame(parent, bg=C_PANEL)
        row2.pack(fill="x", pady=(4, 0))
        tk.Label(row2, text="从站地址", bg=C_PANEL, fg=C_TEXT).pack(side="left")
        self.scan_slave_from_var = tk.StringVar(value="1")
        tk.Spinbox(row2, from_=1, to=247, width=4, textvariable=self.scan_slave_from_var,
                   justify="center", state="readonly").pack(side="left", padx=(4, 2))
        tk.Label(row2, text="~", bg=C_PANEL, fg=C_TEXT).pack(side="left")
        self.scan_slave_to_var = tk.StringVar(value="1")
        tk.Spinbox(row2, from_=1, to=247, width=4, textvariable=self.scan_slave_to_var,
                   justify="center", state="readonly").pack(side="left", padx=(2, 0))
        tk.Label(row2, text="（起 ~ 止，可扫多台）", bg=C_PANEL, fg=C_MUTED,
                 font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(6, 0))

        # 速度（每路写入后等待再回读的间隔）与反检开关
        row3 = tk.Frame(parent, bg=C_PANEL)
        row3.pack(fill="x", pady=(4, 0))
        tk.Label(row3, text="速度", bg=C_PANEL, fg=C_TEXT).pack(side="left")
        self.scan_interval_var = tk.StringVar(value="50")
        tk.Spinbox(row3, from_=0, to=2000, increment=10, width=5,
                   textvariable=self.scan_interval_var,
                   justify="center").pack(side="left", padx=(4, 2))
        tk.Label(row3, text="ms/路", bg=C_PANEL, fg=C_MUTED,
                 font=("Microsoft YaHei UI", 8)).pack(side="left")
        self.scan_reverse_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row3, text="反检", variable=self.scan_reverse_var,
                       bg=C_PANEL, fg=C_TEXT, activebackground=C_PANEL,
                       selectcolor=C_PANEL, highlightthickness=0, bd=0).pack(
            side="left", padx=(14, 0))

        row4 = tk.Frame(parent, bg=C_PANEL)
        row4.pack(fill="x", pady=(6, 0))
        self.btn_scan = tk.Button(row4, text="开始自检", relief="flat", bd=0,
                                  bg=C_ACCENT, fg="#ffffff", activebackground="#0d55b8",
                                  activeforeground="#ffffff", padx=14, pady=2,
                                  font=("Microsoft YaHei UI", 9, "bold"),
                                  command=self.cmd_scan)
        self.btn_scan.pack(side="left")
        tk.Button(row4, text="清除结果", relief="flat", bg=C_PANEL, fg=C_TEXT,
                  activebackground="#e8edf2", bd=0, padx=10, pady=2,
                  font=("Microsoft YaHei UI", 9),
                  command=self._clear_scan_list).pack(side="left", padx=(8, 0))
        tk.Label(row4, text="逐站逐路点亮并回读确认", bg=C_PANEL, fg=C_MUTED,
                 font=("Microsoft YaHei UI", 8)).pack(side="right")

    def _build_scan_list(self, parent):
        """自检问题点位列表（只读文本框，自带滚动条）。"""
        self.scan_list = self.scrolledtext.ScrolledText(
            parent, height=5, state="disabled", wrap="word",
            bg="#0f172a", fg="#cbd5e1", insertbackground="#cbd5e1",
            font=("Consolas", 9), relief="flat", borderwidth=1)
        self.scan_list.pack(fill="both", expand=True)

    def _clear_scan_list(self):
        self.scan_list.config(state="normal")
        self.scan_list.delete("1.0", "end")
        self.scan_list.config(state="disabled")
        self.log("已清除自检问题点位列表。", "info")

    def _fill_scan_list(self, r):
        """把自检结果写进右侧「自检问题点位」面板。"""
        self.scan_list.config(state="normal")
        self.scan_list.delete("1.0", "end")
        scope = "从站 %d~%d × %d 路（线圈 %04XH 起）" % (
            r.get("slave_from", 1), r.get("slave_to", 1), r["count"], r["start"])
        if r["failed"] == 0:
            self.scan_list.insert("end", "自检结果：%s，共 %d 点位，全部通过 ✓\n"
                                  % (scope, r["total"]))
            if r.get("reverse"):
                self.scan_list.insert("end", "（反检已开启：闭合与断开均回读确认）\n")
        else:
            self.scan_list.insert("end", "%s，共 %d 点位，问题 %d 点：\n"
                                  % (scope, r["total"], r["failed"]))
            for f in r["failures"]:
                self.scan_list.insert(
                    "end", "• 从站 %d 继电器 %d（线圈 %04XH）— %s\n"
                           % (f.get("slave", 1), f["relay"], f["addr"], f["reason"]))
        self.scan_list.config(state="disabled")

    def _show_scan_dialog(self, r):
        """问题弹窗：列出所有问题点位，方便逐一排查。"""
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title("自检结果 — 存在问题")
        win.configure(bg=C_PANEL)
        win.transient(self.root)
        win.resizable(True, True)

        tk.Label(win,
                 text="自检完成（从站 %d~%d，线圈 %04XH 起 %d 路%s）：\n"
                      "共 %d 点位，%d 点通过，%d 点存在问题，下列点位需排查："
                      % (r.get("slave_from", 1), r.get("slave_to", 1), r["start"],
                         r["count"],
                         "，反检开" if r.get("reverse") else "",
                         r["total"], r["passed"], r["failed"]),
                 bg=C_PANEL, fg=C_TEXT, justify="left", wraplength=440,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=16, pady=(14, 6))

        box = self.scrolledtext.ScrolledText(
            win, width=62, height=10, state="disabled", wrap="word",
            bg="#0f172a", fg="#fca5a5", insertbackground="#fca5a5",
            font=("Consolas", 9), relief="flat", borderwidth=1)
        box.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        box.config(state="normal")
        for f in r["failures"]:
            box.insert("end", "• 从站 %d 继电器 %d（线圈 %04XH）：%s\n"
                       % (f.get("slave", 1), f["relay"], f["addr"], f["reason"]))
        box.config(state="disabled")

        row = tk.Frame(win, bg=C_PANEL)
        row.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(row, text="确定", relief="flat", bg=C_ACCENT, fg="#ffffff", bd=0,
                  padx=22, pady=3, font=("Microsoft YaHei UI", 9, "bold"),
                  command=win.destroy).pack(side="right")
        try:
            win.grab_set()
        except Exception:                                  # noqa: BLE001
            pass

    def _build_log(self, parent):
        """日志区。minsize 直接钉住高度：窗口变大时涨的是卡片区，日志保持可读尺寸。"""
        # pane 的初始高度 = 内部控件的自然请求高度（由日志文本框的 height 行数决定），
        # 用户可再往小拖到 LOG_MIN_HEIGHT 给卡片区让地方。
        wrap = self.tk.Frame(parent, bg=C_BG)
        self.split.add(wrap, stretch="never", minsize=LOG_MIN_HEIGHT)
        self.log_panel = LogPanel(self.tk, self.scrolledtext, wrap, self._on_trace_toggle)

    def _build_statusbar(self):
        tk = self.tk
        bar = tk.Frame(self.root, bg=C_BG)
        bar.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        self.conn_dot = tk.Canvas(bar, width=14, height=14, bg=C_BG, highlightthickness=0)
        self.conn_dot.pack(side="left")
        self._dot = self.conn_dot.create_image(7, 7)
        self.conn_dot.itemconfig(self._dot,
                                 image=aa_circle_photo(tk, 14, C_OFF, C_BORDER, C_BG,
                                                       ring_w=1, inset=2))
        self._dot_fill = C_OFF
        self.conn_text = tk.StringVar(value="未连接")
        tk.Label(bar, textvariable=self.conn_text, bg=C_BG, fg=C_MUTED).pack(side="left", padx=6)
        self.busy_text = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.busy_text, bg=C_BG, fg=C_ACCENT).pack(side="right")

    # ------------------------------------------------------------ 日志
    def log(self, msg, tag="info"):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_panel.append("[%s] %s" % (ts, msg), tag)

    def trace(self, direction, data, extra=""):
        """由工作线程调用——只入队，不触碰界面。"""
        self.events.put(("trace", direction, bytes(data), extra))

    # ------------------------------------------------------------ 事件泵
    def _drain_events(self):
        if self._closing:
            return
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(ev)
            except Exception as e:                          # noqa: BLE001
                self.log("事件处理异常：%r" % (e,), "err")
        self._drain_after_id = self.root.after(self.POLL_TICK_MS, self._drain_events)

    def _handle_event(self, ev):
        kind = ev[0]
        if kind == "trace":
            _, direction, data, extra = ev
            if self.show_trace and data:
                tag = "tx" if direction == "TX" else "rx"
                suffix = ("   (%s)" % extra) if extra else ""
                self.log_panel.append("  %-3s %s%s" % (direction, fmt_hex(data), suffix), tag)
            elif direction == "!! ":
                self.log_panel.append("  !!  %s" % extra, "warn")

        elif kind == "log":
            self.log(ev[1], ev[2])
            # 运行中串口被其他程序抢走 / USB 被拔插（设备重新枚举）：
            # 链路已不可用，自动断开，避免界面停在「已连接」的假态
            if self.client and ("重新枚举" in ev[1] or "设备已消失" in ev[1]):
                self.log("检测到串口不可用，已自动断开链路。"
                         "按上方指引恢复硬件后再「连接」。", "warn")
                self.on_disconnect()

        elif kind == "status":
            st = ev[1]
            self.stat_vars["hw_version"].set(st.hw_version)
            self.stat_vars["sw_version"].set(st.sw_version)
            for i, led in enumerate(self.out_leds):
                on = st.outputs[i] if i < len(st.outputs) else False
                paint_led(led, C_ON if on else C_OFF)
            for i, led in enumerate(self.in_leds):
                on = st.inputs[i] if i < len(st.inputs) else False
                paint_led(led, C_ACCENT if on else C_OFF)
            self.last_outputs = list(st.outputs[:self.relay_count])
            for i, card in enumerate(self.cards):
                card.set_state(st.outputs[i] if i < len(st.outputs) else False)
            self.poll_fails = 0

        elif kind == "relay":
            _, idx, on = ev
            self.cards[idx].set_state(on)

        elif kind == "all":
            _, states = ev
            for i, card in enumerate(self.cards):
                card.set_state(states[i])
            self.last_outputs = list(states)

        elif kind == "stats":
            s = ev[1]
            self.stat_vars["tx"].set(str(s["tx"]))
            self.stat_vars["rx"].set(str(s["rx"]))
            self.stat_vars["err"].set(str(s["err"]))
            self.stat_vars["rtt"].set("%.0f ms" % s["last_rtt"] if s["last_rtt"] else "—")

        elif kind == "conn":
            self._update_conn_ui(ev[1], ev[2])

        elif kind == "busy":
            if ev[1]:
                self.busy += 1
            else:
                self.busy = max(0, self.busy - 1)
            self.busy_text.set("● 通讯中…" if self.busy else "")

        elif kind == "poll_error":
            self.poll_fails = ev[1]
            if ev[1] >= 5 and self.auto_poll.get():
                self.auto_poll.set(False)
                self.poll_enabled_runtime = False
                self.log("连续 %d 次轮询失败，已自动暂停轮询。请检查链路后手动恢复。" % ev[1], "err")

        elif kind == "msgbox":
            self.messagebox.showinfo(ev[1], ev[2])

        elif kind == "scan_state":
            running = ev[1]
            self.scan_running = running
            if getattr(self, "btn_scan", None) is not None:
                self.btn_scan.config(state="disabled" if running else
                                     ("normal" if self.client and self.client.is_connected() else "disabled"))
            self.busy_text.set("● 自检中…" if running else "")

        elif kind == "scan_done":
            self._on_scan_done(ev[1])

        elif kind == "clear_relay_states":
            for card in self.cards:
                card.set_state(False)
            self.last_outputs = [False] * self.relay_count
            for led in self.out_leds:
                paint_led(led, C_OFF)
            for led in self.in_leds:
                paint_led(led, C_OFF)
            for k in ("hw_version", "sw_version"):
                self.stat_vars[k].set("—")

    # ------------------------------------------------------------ 连接
    def _refresh_ports(self):
        ports = list_serial_ports()
        values = ["%s  —  %s" % (d, desc) for d, desc in ports]
        self._port_devices = [d for d, _ in ports]
        self.port_combo["values"] = values
        if values and not self.port_var.get():
            self.port_combo.current(0)
        elif not values:
            self.port_combo["values"] = ["（未发现串口）"]
            self.port_var.set("")

    def _on_link_mode_change(self):
        if self.link_mode.get() == "serial":
            self.tcp_row.pack_forget()
            self.serial_row.pack(side="left")
        else:
            self.serial_row.pack_forget()
            self.tcp_row.pack(side="left")

    def current_frame_desc(self):
        """当前串口帧格式速记（如 8N1），与传输层 frame_desc() 同一口径。"""
        return "%s%s%s" % (self.databits_var.get(),
                           parse_parity(self.parity_var.get()),
                           self.stopbits_var.get())

    def _update_conn_ui(self, connected, text):
        self.conn_text.set(text)
        color = C_OK if connected else C_OFF
        if color != self._dot_fill:
            self._dot_fill = color
            self.conn_dot.itemconfig(
                self._dot, image=aa_circle_photo(self.tk, 14, color, C_BORDER, C_BG,
                                                 ring_w=1, inset=2))
        # 连接/断开按钮用颜色+文字明确表达当前状态：
        # 未连接 → 「连接」蓝色可点、「断开」灰禁用；已连接 → 反过来，且「连接」变灰字
        if connected:
            self.btn_connect.config(text="已连接", state="disabled",
                                    bg="#e8edf2", fg=C_MUTED,
                                    disabledforeground=C_MUTED)
            self.btn_disconnect.config(state="normal", bg="#fdecec", fg="#d92d20",
                                       activebackground="#f9d6d6",
                                       activeforeground="#d92d20",
                                       disabledforeground="#c4cbd4")
        else:
            self.btn_connect.config(text="连接", state="normal",
                                    bg=C_ACCENT, fg="#ffffff",
                                    disabledforeground="#c4cbd4")
            self.btn_disconnect.config(state="disabled", bg="#eef1f5", fg=C_MUTED,
                                       activebackground="#e0e5eb",
                                       activeforeground=C_TEXT,
                                       disabledforeground="#c4cbd4")
        state_conn = "disabled" if connected else "normal"
        state_disc = "normal" if connected else "disabled"
        self.btn_connect.config(state=state_conn)
        self.btn_disconnect.config(state=state_disc)
        for b in self.all_buttons:
            b.config(state="normal" if connected else "disabled")
        if getattr(self, "btn_scan", None) is not None:
            self.btn_scan.config(state="normal" if connected else "disabled")
        self._set_channel_buttons(connected)

    def _set_channel_buttons(self, enabled):
        """连接/断开链路时统一切换 12 张卡片灯的可点状态。"""
        for c in self.cards:
            c.set_enabled(enabled)

    def _submit(self, fn):
        """把任务提交给工作线程。

        忙碌计数与状态提示一律经事件队列交给主线程处理——工作线程绝不触碰
        任何 tkinter 对象（含 StringVar / BooleanVar 的 get/set）。
        """
        self.events.put(("busy", True))

        def wrapper():
            try:
                fn()
            finally:
                self.events.put(("busy", False))

        self.worker.submit(wrapper)

    def on_connect(self):
        if self.client and self.client.is_connected():
            return
        try:
            slave = int(self.slave_var.get())
        except ValueError:
            self.messagebox.showerror("参数错误", "从站地址必须是 0~255 的整数。")
            return
        if not 0 <= slave <= 255:
            self.messagebox.showerror("参数错误", "从站地址必须是 0~255 的整数。")
            return

        mode = self.link_mode.get()
        try:
            if mode == "serial":
                if not HAS_SERIAL:
                    raise TransportError("未安装 pyserial，无法使用串口。\n"
                                         "请在命令行执行：python -m pip install pyserial")
                idx = self.port_combo.current()
                if idx < 0 or idx >= len(getattr(self, "_port_devices", [])):
                    raise TransportError("请先选择一个可用串口。")
                device = self._port_devices[idx]
                tr = SerialTransport(device, baudrate=int(self.baud_var.get()),
                                     bytesize=int(self.databits_var.get()),
                                     parity=parse_parity(self.parity_var.get()),
                                     stopbits=float(self.stopbits_var.get()))
                label = "%s @%s/%s" % (device, self.baud_var.get(), tr.frame_desc())
            else:
                host = self.host_var.get().strip()
                port = int(self.tcpport_var.get())
                tr = TcpTransport(host, port)
                label = "%s:%d" % (host, port)
        except Exception as e:                              # noqa: BLE001
            self.messagebox.showerror("连接失败", str(e))
            return

        # 兜底：上一个 client 若残留（连接失败/断开异常），先尝试释放它握着的链路，
        # 避免「自己占自己」导致重连报串口被占用
        old = getattr(self, "client", None)
        if old is not None and not old.is_connected():
            try:
                old.close()
            except Exception:                               # noqa: BLE001
                pass
        self.client = RelayClient(tr, slave_id=slave, timeout=DEFAULT_TIMEOUT,
                                  retry=DEFAULT_RETRY, trace=self.trace)
        self.conn_text.set("连接中…")
        self.btn_connect.config(text="连接中…", state="disabled",
                                bg="#e8edf2", fg=C_MUTED,
                                disabledforeground=C_MUTED)
        cli = self.client                   # 工作线程里用局部引用，别读 self.client（可能已被置 None/换新）

        def job():
            try:
                cli.connect()
            except Exception as e:                          # noqa: BLE001
                self.events.put(("conn", False, "连接失败：%s" % e))
                self.events.put(("log", "连接失败：%s" % e, "err"))
                return
            self.events.put(("conn", True, "已连接  %s  ·  从站 %d" % (label, slave)))
            self.events.put(("log", "链路建立：%s，从站地址 %d" % (label, slave), "info"))
            self._submit_status_read(first=True)

        self._submit(job)

    def on_disconnect(self):
        if not self.client:
            return

        cli = self.client                   # 关键：先抓住引用。job 在工作线程里执行时
        # self.client 已被主线程置 None，再读 self.client.close() 等于 None.close()，
        # 异常被吞、串口从不关闭——重连时就「自己占自己」报串口被占用。

        def job():
            try:
                cli.close()
            except Exception:                               # noqa: BLE001
                pass
            self.events.put(("conn", False, "未连接"))
            self.events.put(("log", "链路已断开。", "info"))
            self.events.put(("clear_relay_states",))

        self._submit(job)
        self.client = None
        self.poll_fails = 0

    def _require_client(self):
        if not self.client or not self.client.is_connected():
            self.messagebox.showwarning("未连接", "请先连接设备或模拟从站。")
            return None
        return self.client

    # ------------------------------------------------------------ 业务命令
    def _submit_status_read(self, first=False):
        cli = self.client
        if not cli:
            return

        def job():
            try:
                st = cli.read_status()
                self.events.put(("status", st))
                if first:
                    self.events.put(("log", "读取成功：硬件 %s / 软件 %s" % (st.hw_version, st.sw_version), "info"))
            except Exception as e:                          # noqa: BLE001
                if first:
                    self.events.put(("log", "首次读取失败：%s" % e, "err"))
                else:
                    self.events.put(("poll_error", self.poll_fails + 1))
            finally:
                self.events.put(("stats", dict(cli.stats)))

        self._submit(job)

    def _read_outputs_now(self, cli):
        """在工作线程内同步读一次输出状态，返回 bool 列表。"""
        st = cli.read_status()
        self.events.put(("status", st))
        return list(st.outputs[:self.relay_count])

    def cmd_set_relay(self, index, on):
        cli = self._require_client()
        if not cli:
            return
        # 编号在主线程算好再带进工作线程（tk BooleanVar 不能在线程里读）
        no = relay_no_of(index, self.relay_count, bool(self.reverse_num_var.get()))

        def job():
            try:
                cli.write_single_coil(index, on)
                self.events.put(("relay", index, on))
                self.events.put(("log", "继电器 %d → %s" % (no, "闭合" if on else "断开"), "info"))
                # 写后立即回读，保证界面与设备一致
                st = cli.read_status()
                self.events.put(("status", st))
            except ModbusException as e:
                self.events.put(("log", "继电器 %d 操作被拒绝：%s" % (no, e), "err"))
            except Exception as e:                          # noqa: BLE001
                self.events.put(("log", "继电器 %d 操作失败：%s" % (no, e), "err"))
                self.events.put(("poll_error", self.poll_fails + 1))
            finally:
                self.events.put(("stats", dict(cli.stats)))

        self._submit(job)

    def cmd_all(self, target, broadcast=False):
        cli = self._require_client()
        if not cli:
            return
        if broadcast:
            action = "闭合" if target else "断开"
            if not self.messagebox.askyesno(
                    "确认广播",
                    "广播指令将作用于总线上所有模块（地址 0x%02X），且模块不回复。\n\n继续？" % BROADCAST_ADDR):
                return
            if not self.messagebox.askyesno(
                    "二次确认",
                    "即将下发广播%s指令：总线上所有模块的全部继电器将同时%s，\n"
                    "模块不回复、无法逐台核对，请确认负载侧允许此操作。\n\n确认执行？" % (action, action)):
                return
        # 关键：tkinter 变量必须在主线程取值后再带进工作线程
        use_bulk = bool(self.bulk_var.get())
        states = [bool(target)] * self.relay_count

        def job():
            used_bulk = False
            try:
                if use_bulk:
                    try:
                        cli.write_coils(0, states, slave=BROADCAST_ADDR if broadcast else None)
                        used_bulk = True
                    except ModbusException as e:
                        self.events.put(("log", "0FH 批量写被拒绝（%s），改用逐路 05H 写入。" % e, "warn"))
                    except (TransportTimeout, FrameError) as e:
                        self.events.put(("log", "0FH 批量写无有效响应（%s），改用逐路 05H 写入。" % e, "warn"))
                if not used_bulk:
                    for i, s in enumerate(states):
                        cli.write_single_coil(i, s,
                                              slave=BROADCAST_ADDR if broadcast else None)
                self.events.put(("all", states))
                self.events.put(("log", "%s：全部%s（%s）" % (
                    "广播" if broadcast else "全控",
                    "闭合" if target else "断开",
                    "0FH 批量写" if used_bulk else "逐路 05H"), "info"))
                if broadcast:
                    time.sleep(0.2)
                st = cli.read_status()
                self.events.put(("status", st))
            except Exception as e:                          # noqa: BLE001
                self.events.put(("log", "全控失败：%s" % e, "err"))
                self.events.put(("poll_error", self.poll_fails + 1))
            finally:
                self.events.put(("stats", dict(cli.stats)))

        self._submit(job)

    def cmd_invert(self):
        cli = self._require_client()
        if not cli:
            return

        def job():
            try:
                cur = self._read_outputs_now(cli)
                target = [not b for b in cur]
                for i, s in enumerate(target):
                    cli.write_single_coil(i, s)
                self.events.put(("all", target))
                self.events.put(("log", "全部取反完成。", "info"))
                st = cli.read_status()
                self.events.put(("status", st))
            except Exception as e:                          # noqa: BLE001
                self.events.put(("log", "全部取反失败：%s" % e, "err"))
                self.events.put(("poll_error", self.poll_fails + 1))
            finally:
                self.events.put(("stats", dict(cli.stats)))

        self._submit(job)

    def cmd_read_status(self):
        if not self._require_client():
            return
        self._submit_status_read(first=True)
        self.log("手动读取状态。", "info")

    def cmd_scan(self):
        """继电器自检：跑 [从站起~从站止] × [起始地址, 起始地址+数量) 的所有点位。

        每个点位：下发闭合 → 等待「间隔」ms → 回读输出状态确认；
        勾选「反检」后闭合确认通过再断开并回读复测（粘死不放的继电器会被揪出）。
        反检模式下闭合已下发的点位无论回读成功与否都会断开（含异常时立即补发
        断开 + 收尾兜底），保证自检跑完后继电器全部处于断开态。
        全部点亮且有回读确认 → 弹窗提示无误；
        有未点亮 / 未复位 / 未验证 / 出错的点位 → 弹窗列出问题点，
        并在右侧面板罗列具体点位（从站 + 继电器 + 线圈地址 + 原因）。
        """
        cli = self._require_client()
        if not cli:
            return
        if self.scan_running:
            self.messagebox.showinfo("自检进行中", "上一次自检尚未结束，请稍候。")
            return

        # tkinter 变量必须在主线程取值后带进工作线程
        try:
            start = int(self.scan_start_var.get())
            count = int(self.scan_count_var.get())
            slave_from = int(self.scan_slave_from_var.get())
            slave_to = int(self.scan_slave_to_var.get())
            interval = int(self.scan_interval_var.get())
        except ValueError:
            self.messagebox.showerror("参数错误", "起始地址 / 数量 / 从站地址 / 间隔必须为整数。")
            return
        reverse = bool(self.scan_reverse_var.get())
        if not 0 <= start <= 0xFFFF:
            self.messagebox.showerror("参数错误", "起始地址需在 0 ~ 65535 之间。")
            return
        if count < 1:
            self.messagebox.showerror("参数错误", "数量至少为 1。")
            return
        if start + count > 0x10000:
            self.messagebox.showerror(
                "参数错误", "起始地址 + 数量 超出线圈地址范围（0 ~ 65535）。")
            return
        if not 1 <= slave_from <= 247 or not 1 <= slave_to <= 247:
            self.messagebox.showerror("参数错误", "从站地址需在 1 ~ 247 之间（0/255 为广播，不可回读）。")
            return
        if slave_from > slave_to:
            slave_from, slave_to = slave_to, slave_from
        if not 0 <= interval <= 5000:
            self.messagebox.showerror("参数错误", "每路间隔需在 0 ~ 5000 ms 之间。")
            return

        delay = interval / 1000.0
        cli_ref = cli
        # 编号映射参数在主线程取好再带进工作线程（tk BooleanVar 不能在线程里读）
        rev = bool(self.reverse_num_var.get())
        n_total = self.relay_count

        def job():
            self.scan_running = True
            self.events.put(("scan_state", True))
            failures = []
            passed = 0
            left_on = set()   # （反检模式）已下发闭合、尚未确认断开的点位 (slave, addr)
            total = count * (slave_to - slave_from + 1)
            self.events.put((
                "log",
                "==== 继电器自检开始：从站 %d~%d，线圈 %04XH 起共 %d 路，"
                "间隔 %d ms，反检 %s ===="
                % (slave_from, slave_to, start, count, interval,
                   "开（闭合后断开复测）" if reverse else "关"), "info"))
            try:
                for slave in range(slave_from, slave_to + 1):
                    for i in range(count):
                        addr = start + i
                        relay = relay_no_of(addr, n_total, rev)
                        point = "从站 %d 继电器 %d（线圈 %04XH）" % (slave, relay, addr)
                        wrote_on = False
                        try:
                            ok = True
                            # ---- 正检：闭合 + 回读确认 ----
                            cli_ref.write_single_coil(addr, True, slave=slave)
                            wrote_on = True
                            if reverse:
                                left_on.add((slave, addr))
                            if delay:
                                time.sleep(delay)
                            st = cli_ref.read_status(slave)
                            self.events.put(("status", st))  # 实时点亮对应卡片/指示灯
                            if addr < len(st.outputs):
                                if st.outputs[addr]:
                                    self.events.put((
                                        "log", "自检 %s：写入闭合，回读确认 ✓"
                                        % point, "info"))
                                else:
                                    ok = False
                                    failures.append({
                                        "slave": slave, "addr": addr, "relay": relay,
                                        "kind": "unlit",
                                        "reason": "写入闭合后回读未置位（输出状态位为 0）"})
                                    self.events.put((
                                        "log", "自检 %s：回读未置位 ✗" % point, "err"))
                            else:
                                # 状态字只有 16 位，超出范围的地址无法回读确认
                                ok = False
                                failures.append({
                                    "slave": slave, "addr": addr, "relay": relay,
                                    "kind": "unverifiable",
                                    "reason": "超出输出状态可回读范围（0–15），已下发但无法确认"})
                                self.events.put((
                                    "log", "自检 %s：已下发，超出回读范围未验证 ⚠"
                                    % point, "warn"))
                            # ---- 反检：断开 + 回读复测 ----
                            # 正检未通过也要断开：闭合已下发，跳过断开会让继电器留在闭合态
                            if reverse and wrote_on:
                                cli_ref.write_single_coil(addr, False, slave=slave)
                                wrote_on = False
                                left_on.discard((slave, addr))
                                if delay:
                                    time.sleep(delay)
                                st = cli_ref.read_status(slave)
                                self.events.put(("status", st))
                                if addr < len(st.outputs):
                                    if not st.outputs[addr]:
                                        self.events.put((
                                            "log", "自检 %s：反检断开，回读复位 ✓"
                                            % point, "info"))
                                    else:
                                        ok = False
                                        failures.append({
                                            "slave": slave, "addr": addr, "relay": relay,
                                            "kind": "stuck",
                                            "reason": "反检：下发断开后回读仍为闭合"
                                                      "（继电器可能粘死/触点粘连）"})
                                        self.events.put((
                                            "log", "自检 %s：反检断开后回读仍闭合 ✗"
                                            % point, "err"))
                                else:
                                    ok = False
                                    failures.append({
                                        "slave": slave, "addr": addr, "relay": relay,
                                        "kind": "unverifiable",
                                        "reason": "反检：超出输出状态可回读范围（0–15），"
                                                  "断开已下发但无法确认"})
                                    self.events.put((
                                        "log", "自检 %s：反检已下发，超出回读范围未验证 ⚠"
                                        % point, "warn"))
                            if ok:
                                passed += 1
                        except Exception as e:                  # noqa: BLE001
                            failures.append({
                                "slave": slave, "addr": addr, "relay": relay,
                                "kind": "error", "reason": str(e)})
                            self.events.put((
                                "log", "自检 %s：操作失败 %s" % (point, e), "err"))
                            # 反检模式下该点的闭合可能已下发：立即补发断开（单次不重试），
                            # 避免回读失败/异常后继电器一直留在闭合态
                            if reverse and wrote_on:
                                try:
                                    cli_ref.write_single_coil(addr, False, slave=slave, retry=0)
                                    left_on.discard((slave, addr))
                                except Exception:               # noqa: BLE001
                                    pass                        # 留给收尾兜底
            finally:
                self.scan_running = False
                # 反检收尾兜底：把仍处闭合态的点位全部补发断开，保证「跑完即全断开」
                if reverse and left_on:
                    cleaned = 0
                    for s, a in sorted(left_on):
                        try:
                            cli_ref.write_single_coil(a, False, slave=s, retry=0)
                            cleaned += 1
                        except Exception:                       # noqa: BLE001
                            pass
                    self.events.put((
                        "log", "自检收尾：对 %d 个残留闭合点位补发了断开命令。"
                        % cleaned, "warn"))
                    left_on.clear()
                self.events.put(("scan_state", False))
                self.events.put(("scan_done", {
                    "start": start, "count": count, "total": total,
                    "slave_from": slave_from, "slave_to": slave_to,
                    "interval": interval, "reverse": reverse,
                    "passed": passed, "failed": len(failures), "failures": failures}))

        self._submit(job)

    def _on_scan_done(self, r):
        """自检结束：成功弹窗提示无误；有问题则弹窗列出并同步到侧栏面板。"""
        self._last_scan = r
        scope = "从站 %d~%d，线圈 %04XH 起 %d 路%s" % (
            r.get("slave_from", 1), r.get("slave_to", 1), r["start"], r["count"],
            "，反检开" if r.get("reverse") else "")
        if r["failed"] == 0:
            self.messagebox.showinfo(
                "自检通过",
                "继电器自检完成：%s，共 %d 点位，全部点亮且回读确认，无误。"
                % (scope, r["total"]))
            self.log("自检完成：%d 点位全部通过，无误。" % r["total"], "info")
        else:
            self._show_scan_dialog(r)
            self.log("自检完成：%d 点位通过，%d 点位存在问题。"
                     % (r["passed"], r["failed"]), "err")
        # 无论成败，侧栏都列出结论/问题点位，便于反复排查
        self._fill_scan_list(r)
        # 自动把右侧面板滚到自检区域，问题点位立即可见（无需手动翻找）
        try:
            self.right_canvas.update_idletasks()
            self.right_canvas.yview_moveto(1.0)
        except Exception:                                  # noqa: BLE001
            pass

    def cmd_reboot(self):
        cli = self._require_client()
        if not cli:
            return
        if not self.messagebox.askyesno("确认重启", "将向模块下发重启指令（V2.3 及以上支持）。\n\n继续？"):
            return

        def job():
            try:
                resp = cli.reboot()
                if resp:
                    self.events.put(("log", "模块重启指令已下发，模块回复：%s" % fmt_hex(resp), "info"))
                else:
                    self.events.put(("log", "模块重启指令已下发（无响应，符合重启预期）。", "info"))
                time.sleep(0.8)
                try:
                    st = cli.read_status()
                    self.events.put(("status", st))
                    self.events.put(("log", "重启后通讯恢复正常。", "info"))
                except Exception as e:                      # noqa: BLE001
                    self.events.put(("log", "重启后暂时无法通讯：%s" % e, "warn"))
            except Exception as e:                          # noqa: BLE001
                self.events.put(("log", "重启指令失败：%s" % e, "err"))
            finally:
                self.events.put(("stats", dict(cli.stats)))

        self._submit(job)

    def cmd_custom(self):
        cli = self._require_client()
        if not cli:
            return
        tk = self.tk
        win = tk.Toplevel(self.root)
        win.title("发送自定义报文")
        win.configure(bg=C_PANEL)
        win.transient(self.root)
        win.resizable(False, False)

        tk.Label(win, text="十六进制报文（可含空格）", bg=C_PANEL, fg=C_TEXT).pack(
            anchor="w", padx=14, pady=(12, 4))
        entry = tk.Entry(win, width=54, font=("Consolas", 10))
        entry.pack(padx=14)
        entry.insert(0, "01 03 20 00 00 08")
        auto_crc = tk.BooleanVar(value=True)
        expect = tk.BooleanVar(value=True)
        tk.Checkbutton(win, text="自动追加 CRC（否则报文需自带 CRC）", variable=auto_crc,
                       bg=C_PANEL, fg=C_TEXT, activebackground=C_PANEL, selectcolor=C_PANEL,
                       highlightthickness=0, bd=0).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Checkbutton(win, text="等待响应（广播类指令请取消勾选）", variable=expect,
                       bg=C_PANEL, fg=C_TEXT, activebackground=C_PANEL, selectcolor=C_PANEL,
                       highlightthickness=0, bd=0).pack(anchor="w", padx=12, pady=(2, 0))

        hint = tk.Label(win, text="", bg=C_PANEL, fg=C_MUTED, justify="left", anchor="w")
        hint.pack(fill="x", padx=14, pady=(8, 0))

        def do_send():
            text = entry.get().strip()
            add_crc = bool(auto_crc.get())
            want_resp = bool(expect.get())
            if not add_crc:
                try:
                    raw = bytes.fromhex("".join(c for c in text if c not in " \t"))
                    if not check_crc(raw):
                        hint.config(text="警告：报文 CRC 校验不通过，请核对。", fg=C_ERR)
                except ValueError as e:
                    hint.config(text="报文解析失败：%s" % e, fg=C_ERR)
                    return

            def job():
                try:
                    resp = cli.send_custom(text, add_crc, want_resp)
                    if resp:
                        self.events.put(("log", "自定义报文响应：%s" % fmt_hex(resp), "info"))
                        self.events.put(("msgbox", "发送成功", "响应帧：\n%s" % fmt_hex(resp)))
                    else:
                        self.events.put(("log", "自定义报文已发送。", "info"))
                except Exception as e:                      # noqa: BLE001
                    self.events.put(("log", "自定义报文失败：%s" % e, "err"))
                finally:
                    self.events.put(("stats", dict(cli.stats)))

            self._submit(job)
            win.destroy()

        row = tk.Frame(win, bg=C_PANEL)
        row.pack(fill="x", padx=14, pady=12)
        tk.Button(row, text="发送", relief="flat", bg=C_ACCENT, fg="#ffffff", bd=0,
                  padx=20, pady=3, command=do_send).pack(side="right")
        tk.Button(row, text="取消", relief="flat", bg="#eef1f5", fg=C_TEXT, bd=0,
                  padx=14, pady=3, command=win.destroy).pack(side="right", padx=(0, 8))
        win.grab_set()

    # ------------------------------------------------------------ 轮询
    def _on_auto_poll(self):
        if self.auto_poll.get():
            self.poll_fails = 0
            self.log("自动轮询已开启。", "info")
        else:
            self.log("自动轮询已暂停。", "info")

    def _on_interval(self):
        try:
            v = int(self.interval_var.get())
            self.poll_interval_ms = max(100, min(10000, v))
        except ValueError:
            self.interval_var.set(str(self.poll_interval_ms))

    def _on_trace_toggle(self):
        self.show_trace = self.log_panel.show_trace.get()

    def _poll_tick(self):
        if self._closing:
            return
        try:
            if (self.auto_poll.get() and self.client and self.client.is_connected()
                    and self.busy == 0):
                self._submit_status_read(first=False)
        finally:
            try:
                self.poll_interval_ms = max(100, min(10000, int(self.interval_var.get())))
            except Exception:                              # noqa: BLE001
                pass
            self._poll_after_id = self.root.after(self.poll_interval_ms, self._poll_tick)

    # ------------------------------------------------------------ 退出
    def on_close(self):
        self._closing = True
        # 关闭看门狗（仅打包 EXE）：USB 驱动僵死（设备拔出后句柄卡死）会把
        # 收尾线程卡死在内核调用里——窗口点了没反应、任务管理器也杀不掉。
        # 3 秒后无条件终止进程，保证一定关得掉；正常关闭时收尾早已完成，
        # 主线程退出会先于看门狗，不受影响（Timer 为 daemon，不拖慢退出）。
        if getattr(sys, "frozen", False):
            threading.Timer(3.0, lambda: os._exit(0)).start()
        for attr in ("_poll_after_id", "_drain_after_id", "_fit_after_id"):
            aid = getattr(self, attr, None)
            if aid:
                try:
                    self.root.after_cancel(aid)
                except Exception:                          # noqa: BLE001
                    pass
        try:
            # 顺序很重要：先通知传输层「正在关闭」（读循环分片后 ≤0.1s 退出），
            # 再等工作线程收尾，最后才关串口——否则主线程关串口会撞上
            # 工作线程进行中的 read，Windows 下直接挂起（关窗卡死）。
            tr = getattr(self.client, "tr", None) if self.client else None
            if tr is not None and hasattr(tr, "_closing"):
                tr._closing = True
            self.worker.stop()
            self.worker.join(timeout=2.0)
            if self.client:
                try:
                    self.client.close()
                except Exception:                          # noqa: BLE001
                    pass
        finally:
            try:
                self.root.destroy()
            except Exception:                              # noqa: BLE001
                pass
        # 最后的保险：USB 驱动异常（如设备拔出后句柄僵死）可能把某个线程
        # 卡死在内核调用里，进程会退不出去（任务管理器都难结束）。
        # 上面启动的看门狗会在 3 秒时无条件终止进程，正常关闭走不到这里。
        if getattr(sys, "frozen", False):
            os._exit(0)

    def run(self):
        self.root.mainloop()


def main():
    app = RelayHmiApp()
    # 打包 EXE 后由 PyInstaller 注入 pyi_splash：主窗口就绪即关闭启动画面
    try:
        import pyi_splash                                     # noqa: F401  (PyInstaller runtime)
        pyi_splash.close()
    except Exception:                                         # noqa: BLE001
        pass  # 源码方式运行（run.bat）没有启动画面模块
    app.run()


if __name__ == "__main__":
    main()
