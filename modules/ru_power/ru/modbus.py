# -*- coding: utf-8 -*-
"""零依赖 Modbus RTU 帧编解码 + 可替换传输层。

支持功能码：
  01 读线圈  02 读离散输入  03 读保持寄存器  04 读输入寄存器
  05 写单个线圈  06 写单个保持寄存器  0F 写多个线圈  10 写多个保持寄存器

传输层：
  SerialTransport  —— 串口（RS-232 / RS-485），需 pyserial
  TcpTransport     —— 裸 RTU over TCP（RS485 转以太网模块 / 本地模拟从站）
"""

import socket
import struct
import time

from .crc import append_crc, check_crc, crc16

# ---------------- 功能码 ----------------
FC_READ_COILS = 0x01
FC_READ_DISCRETE = 0x02
FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04
FC_WRITE_COIL = 0x05
FC_WRITE_REG = 0x06
FC_WRITE_COILS = 0x0F
FC_WRITE_REGS = 0x10

EXCEPTION_TEXT = {
    0x01: "非法功能码",
    0x02: "非法数据地址",
    0x03: "非法数据值",
    0x04: "从站设备故障",
    0x05: "确认（命令处理中）",
    0x06: "从站设备忙",
    0x08: "存储奇偶性差错",
    0x0A: "网关路径不可用",
    0x0B: "网关目标设备响应失败",
}


class ModbusError(Exception):
    """异常响应或协议层错误。"""

    def __init__(self, msg, code=None, frame=None):
        super().__init__(msg)
        self.code = code
        self.frame = frame


class TransportError(Exception):
    """传输层错误。

    fatal=True 表示链路本身已经不可用（串口句柄失效、被其它程序抢走等），
    重试没有意义，上层应当直接回到「未连接」状态让用户重连。
    """

    def __init__(self, msg, fatal=False):
        super().__init__(msg)
        self.fatal = fatal


def describe_serial_error(exc) -> str:
    """把 pyserial / Windows 的英文报错翻译成现场能直接照做的中文提示。"""
    s = str(exc)
    low = s.lower()
    # 先判具体错误码，再判笼统的「Cannot configure port」：
    # winerror 6 = ERROR_INVALID_HANDLE（设备被拔），
    # winerror 87 = ERROR_INVALID_PARAMETER（参数被驱动拒绝）。
    if ("invalid handle" in low or "the handle is invalid" in low
            or "句柄无效" in s or "无效的句柄" in s or ", none, 6)" in low):
        return ("串口句柄已失效：设备被拔出，或换到了另一个 USB 口，"
                "原端口号已不存在。请点「断开」→「刷新」→ 选择新的端口重新连接。"
                "（原始信息：%s）" % s)
    if ("access is denied" in low or "拒绝访问" in s or "permissionerror" in low):
        return ("串口被其它程序占用：请关掉串口助手 / 厂家调试软件 / 另一个本程序窗口，"
                "再重新连接。（原始信息：%s）" % s)
    if ("could not open port" in low or "系统找不到" in s
            or "file not found" in low or "the system cannot find" in low
            or "找不到指定的文件" in s):
        return ("打不开该串口：端口不存在或适配器已被拔出。"
                "请点「刷新」重新扫描端口。（原始信息：%s）" % s)
    if ("the parameter is incorrect" in low or "参数错误" in s
            or "参数不正确" in s or "winerror 87" in low):
        return ("串口参数被驱动拒绝：请确认波特率与设备一致（默认 9600），"
                "或换一根 USB 转串口线。（原始信息：%s）" % s)
    if "cannot configure port" in low:
        return ("串口初始化失败：驱动拒绝按 8-N-1 配置该端口，"
                "多半是这根 USB 转串口线的驱动有问题，换一根线或重装驱动后再试。"
                "（原始信息：%s）" % s)
    if "semaphore" in low or "timed out" in low:
        return ("串口通讯超时：适配器可能已掉线，请「刷新」后重连。"
                "（原始信息：%s）" % s)
    return "串口访问失败：%s" % s


def hexs(data) -> str:
    return " ".join("%02X" % b for b in bytes(data))


# ---------------- CRC 自检（手册样例） ----------------
MANUAL_FRAMES = [
    # (payload_without_crc, 手册给出的 CRC 两字节「低字节在前」显示)
    ("01 05 00 85 FF 00", "9D D3"),   # 开机
    ("01 05 00 85 00 00", "DC 23"),   # 关机
    ("01 01 00 85 00 01", "EC 23"),   # 读输出状态（发）
    ("01 01 01 01", "90 48"),         # 读输出状态（返回 ON）
    ("01 01 01 00", "51 88"),         # 读输出状态（返回 OFF）
    ("01 04 00 64 00 01", "70 15"),   # 读电压回读（发）
    ("01 04 02 02 83", "F9 F1"),      # 读电压回读（返回 64.3V）
    ("01 04 00 64 00 02", "30 14"),   # 读电压+电流（发）
    ("01 04 04 02 83 00 01", "CA 14"),  # 读电压+电流（返回）
    ("01 04 00 67 00 01", "80 15"),   # 读额定电压（发）
    ("01 04 02 03 E8", "B9 8E"),      # 读额定电压（返回 100.0V）
    ("01 06 00 95 01 F4", "99 F1"),   # 设定电压 50.0V
]


def verify_manual_examples():
    """返回 (通过数, 失败列表)。用于自测。"""
    fails = []
    ok = 0
    for payload_s, crc_s in MANUAL_FRAMES:
        payload = bytes.fromhex(payload_s.replace(" ", ""))
        want = bytes.fromhex(crc_s.replace(" ", ""))
        got = append_crc(payload)[-2:]
        if got == want:
            ok += 1
        else:
            fails.append((payload_s, want.hex(" ").upper(), got.hex(" ").upper()))
    return ok, fails


# ---------------- 传输层 ----------------
class BaseTransport:
    name = "base"

    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def is_open(self) -> bool:
        raise NotImplementedError

    def exchange(self, frame: bytes, expected_len: int, timeout: float) -> bytes:
        """发送 frame，累计读取直到 expected_len 或超时；返回已收到的字节。"""
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


class SerialTransport(BaseTransport):
    name = "serial"

    # 单次底层 read 的阻塞上限。固定值，运行期不再改 self._ser.timeout——
    # 在 Windows 上给 pyserial 赋 timeout 会连带调用 SetCommState，
    # 设备掉线后该调用会抛「Cannot configure port … 句柄无效」，
    # 把一次普通读超时变成链路级异常。
    READ_TIMEOUT = 0.02

    def __init__(self, port, baudrate=9600, bytesize=8, parity="N", stopbits=1,
                 timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self._ser = None

    def open(self):
        try:
            import serial  # pyserial
        except ImportError as e:
            raise TransportError("缺少 pyserial，请先执行：pip install pyserial") from e

        try:
            self._ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=self.READ_TIMEOUT,
                write_timeout=self.timeout,
            )
        except Exception as e:  # pyserial 会抛 SerialException / OSError
            self._ser = None
            raise TransportError(describe_serial_error(e), fatal=True) from e
        try:
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except Exception:
            pass

    def close(self):
        if self._ser is not None:
            ser, self._ser = self._ser, None
            try:
                ser.close()
            except Exception:
                pass

    def is_open(self) -> bool:
        try:
            return bool(self._ser is not None and self._ser.is_open)
        except Exception:
            return False

    def exchange(self, frame, expected_len, timeout):
        try:
            import serial
        except ImportError:
            serial = None
        if not self.is_open():
            raise TransportError("串口未打开（可能已断开）", fatal=True)

        try:
            if self._ser.in_waiting:
                self._ser.reset_input_buffer()
            # 不调 flush()：Windows 上 FlushFileBuffers 在 USB 转换器异常时可能
            # 无限期阻塞，把整个工作线程卡死。write 带 write_timeout 已足够。
            self._ser.write(frame)
        except Exception as e:
            if serial is not None and isinstance(e, serial.SerialException):
                raise TransportError(describe_serial_error(e), fatal=True) from e
            if isinstance(e, OSError):
                raise TransportError(describe_serial_error(e), fatal=True) from e
            raise TransportError("串口发送失败：%s" % e, fatal=True) from e

        buf = bytearray()
        deadline = time.time() + timeout
        while len(buf) < expected_len:
            remain = deadline - time.time()
            if remain <= 0:
                break
            try:
                chunk = self._ser.read(min(expected_len - len(buf), 64))
            except Exception as e:
                if isinstance(e, OSError):
                    raise TransportError(describe_serial_error(e), fatal=True) from e
                if serial is not None and isinstance(e, serial.SerialException):
                    raise TransportError(describe_serial_error(e), fatal=True) from e
                raise TransportError("串口接收失败：%s" % e, fatal=True) from e
            if chunk:
                buf.extend(chunk)
                # 收到部分数据后缩短收尾等待窗口，避免拖满整个超时
                deadline = time.time() + max(remain * 0.4, 0.15)
            else:
                time.sleep(0.002)
        return bytes(buf)

    def describe(self):
        return "%s @%d %d%s%d" % (self.port, self.baudrate, self.bytesize,
                                  self.parity, self.stopbits)


class TcpTransport(BaseTransport):
    """裸 RTU over TCP：TCP 承载，无 MBAP 头（仅一个 RTU 帧）。"""

    name = "tcp"

    def __init__(self, host, port, timeout=1.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._sock = None

    def open(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(0.05)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def is_open(self) -> bool:
        return self._sock is not None

    def exchange(self, frame, expected_len, timeout):
        if not self.is_open():
            raise TransportError("TCP 未连接")
        try:
            # 清掉可能残留的数据
            self._sock.setblocking(False)
            try:
                while True:
                    if not self._sock.recv(4096):
                        break
            except (BlockingIOError, socket.error):
                pass
            self._sock.setblocking(True)
            self._sock.settimeout(self.timeout)
            self._sock.sendall(frame)
        except OSError as e:
            raise TransportError("发送失败：%s" % e) from e

        buf = bytearray()
        deadline = time.time() + timeout
        while len(buf) < expected_len:
            remain = deadline - time.time()
            if remain <= 0:
                break
            self._sock.settimeout(min(0.05, max(remain, 0.001)))
            try:
                chunk = self._sock.recv(expected_len - len(buf))
            except socket.timeout:
                continue
            except OSError as e:
                raise TransportError("接收失败：%s" % e) from e
            if not chunk:
                break
            buf.extend(chunk)
            deadline = time.time() + max((deadline - time.time()) * 0.3, 0.1)
        return bytes(buf)

    def describe(self):
        return "%s:%d (RTU over TCP)" % (self.host, self.port)


# ---------------- 客户端 ----------------
class ModbusClient:
    def __init__(self, transport: BaseTransport, unit_id=1, timeout=1.0, logger=None):
        self.transport = transport
        self.unit_id = int(unit_id)
        self.timeout = float(timeout)
        self.logger = logger  # callable(str) 用于打印报文，可传 None

    # --- 内部 ---
    def _log(self, text):
        if self.logger:
            self.logger(text)

    def _pdu_exchange(self, pdu: bytes, expected_len: int, label: str) -> bytes:
        frame = append_crc(bytes([self.unit_id]) + pdu)
        self._log("TX  [%s] %s" % (label, hexs(frame)))
        resp = self.transport.exchange(frame, expected_len, self.timeout)
        if not resp:
            # 现场串口偶发丢帧：无响应时重试一次（设定/回读均为幂等操作）
            self._log("--  [%s] 无响应，重试一次" % label)
            resp = self.transport.exchange(frame, expected_len, self.timeout)
        if not resp:
            raise ModbusError("无响应（超时 %.1fs）：%s" % (self.timeout, label),
                              frame=frame)
        self._log("RX  [%s] %s" % (label, hexs(resp)))
        if len(resp) < 5:
            raise ModbusError("响应长度不足：%s" % hexs(resp), frame=resp)
        if not check_crc(resp):
            raise ModbusError("CRC 校验失败：%s" % hexs(resp), frame=resp)
        if resp[0] != self.unit_id and resp[0] != 0:
            raise ModbusError("从站地址不匹配（期望 %d，收到 %d）"
                              % (self.unit_id, resp[0]), frame=resp)
        if resp[1] & 0x80:
            code = resp[2]
            raise ModbusError("异常响应 0x%02X %s"
                              % (code, EXCEPTION_TEXT.get(code, "未知异常")),
                              code=code, frame=resp)
        if resp[1] != pdu[0]:
            raise ModbusError("功能码不匹配（期望 0x%02X，收到 0x%02X）"
                              % (pdu[0], resp[1]), frame=resp)
        return resp

    @staticmethod
    def _expect_read_len(count_bytes: bool, count: int) -> int:
        # ID + FC + ByteCount + 数据 + CRC
        return 1 + 1 + 1 + count_bytes + 2

    # --- 读 ---
    def _read_bits(self, fc, addr, count):
        if not 1 <= count <= 2000:
            raise ModbusError("位读取数量非法：%d（应为 1~2000）" % count)
        pdu = struct.pack(">BHH", fc, addr, count)
        data_bytes = (count + 7) // 8
        resp = self._pdu_exchange(pdu, self._expect_read_len(data_bytes, count),
                                  "读位 FC%02X @%d x%d" % (fc, addr, count))
        bc = resp[2]
        if bc != data_bytes:
            raise ModbusError("字节数不符：期望 %d，收到 %d" % (data_bytes, bc), frame=resp)
        payload = resp[3:3 + bc]
        out = []
        for i in range(count):
            out.append(bool(payload[i // 8] & (1 << (i % 8))))
        return out

    def _read_words(self, fc, addr, count):
        if not 1 <= count <= 125:
            raise ModbusError("寄存器读取数量非法：%d（应为 1~125）" % count)
        pdu = struct.pack(">BHH", fc, addr, count)
        resp = self._pdu_exchange(pdu, self._expect_read_len(count * 2, count),
                                  "读寄存器 FC%02X @%d x%d" % (fc, addr, count))
        bc = resp[2]
        if bc != count * 2:
            raise ModbusError("字节数不符：期望 %d，收到 %d" % (count * 2, bc), frame=resp)
        return list(struct.unpack(">" + "H" * count, resp[3:3 + bc]))

    def read_coils(self, addr, count=1):
        return self._read_bits(FC_READ_COILS, addr, count)

    def read_discrete_inputs(self, addr, count=1):
        return self._read_bits(FC_READ_DISCRETE, addr, count)

    def read_holding_registers(self, addr, count=1):
        return self._read_words(FC_READ_HOLDING, addr, count)

    def read_input_registers(self, addr, count=1):
        return self._read_words(FC_READ_INPUT, addr, count)

    # --- 写 ---
    def write_single_coil(self, addr, on: bool):
        val = 0xFF00 if on else 0x0000
        pdu = struct.pack(">BHH", FC_WRITE_COIL, addr, val)
        resp = self._pdu_exchange(pdu, 8, "写线圈 @%d = %s" % (addr, "ON" if on else "OFF"))
        return resp[4] == 0xFF

    def write_single_register(self, addr, value: int):
        if not 0 <= value <= 0xFFFF:
            raise ModbusError("寄存器值越界：%d（应为 0~65535）" % value)
        pdu = struct.pack(">BHH", FC_WRITE_REG, addr, value)
        resp = self._pdu_exchange(pdu, 8, "写寄存器 @%d = %d" % (addr, value))
        return struct.unpack(">H", resp[4:6])[0]

    def write_multiple_coils(self, addr, values):
        values = [bool(v) for v in values]
        n = len(values)
        if not 1 <= n <= 1968:
            raise ModbusError("位写入数量非法：%d" % n)
        byte_count = (n + 7) // 8
        packed = bytearray(byte_count)
        for i, v in enumerate(values):
            if v:
                packed[i // 8] |= 1 << (i % 8)
        pdu = struct.pack(">BHHB", FC_WRITE_COILS, addr, n, byte_count) + bytes(packed)
        resp = self._pdu_exchange(pdu, 8, "写多线圈 @%d x%d" % (addr, n))
        return struct.unpack(">H", resp[4:6])[0]

    def write_multiple_registers(self, addr, values):
        values = [int(v) & 0xFFFF for v in values]
        n = len(values)
        if not 1 <= n <= 123:
            raise ModbusError("寄存器写入数量非法：%d" % n)
        payload = struct.pack(">" + "H" * n, *values)
        pdu = struct.pack(">BHHB", FC_WRITE_REGS, addr, n, n * 2) + payload
        resp = self._pdu_exchange(pdu, 8, "写多寄存器 @%d x%d" % (addr, n))
        return struct.unpack(">H", resp[4:6])[0]
