# -*- coding: utf-8 -*-
"""传输层：Serial（RS232/RS485）与 TCP 两种，统一接口 exchange()。

设计要点（遵循 modbus-instrument-hmi 技能）：
- 不在工作线程里碰 tkinter；本模块纯 IO，无 GUI 依赖。
- 写用 write_timeout，不调 flush()（Windows 上 flush 可能在 USB 转换器异常时无限阻塞）。
- 收用「累计读到空闲(150ms)或上限」的循环，兼容 ACK/NAK/单行数据/多行数据。
- 串口对象可注入（tests 里塞 FakeSerial），方便离线自测。
"""

import time
import socket


def parse_parity(text: str) -> str:
    t = [c for c in (text or "N").strip().upper() if c in ("N", "E", "O", "M", "S")]
    return t[0] if t else "N"


class TransportError(Exception):
    pass


class SerialTransport:
    def __init__(self, port, baud=9600, parity="N", databits=8, stopbits=1,
                 timeout=2.0, ser=None):
        self.port = port
        self.baud = int(baud)
        self.parity = parse_parity(parity)
        self.databits = int(databits)
        self.stopbits = int(stopbits)
        self.timeout = float(timeout)
        self._ser = ser          # 可选注入
        self._is_open = False

    def open(self):
        if self._ser is not None:
            self._is_open = True
            return
        try:
            import serial  # pyserial
        except ImportError:
            raise TransportError(
                "未安装 pyserial，请先 pip install pyserial\n"
                "（或运行本目录下的 run.bat，它会尝试自动安装）")
        try:
            self._ser = serial.Serial(
                port=self.port, baudrate=self.baud, parity=self.parity,
                bytesize=self.databits, stopbits=self.stopbits,
                timeout=0.05, write_timeout=2.0)
        except Exception as e:
            raise TransportError("打开串口 %s 失败: %s" % (self.port, e))
        self._is_open = True

    def close(self):
        self._is_open = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    @property
    def is_open(self):
        return self._is_open

    def exchange(self, text: str, term: bytes = b"\r\n", timeout: float = None) -> bytes:
        if self._ser is None:
            raise TransportError("传输层未打开")
        tmo = self.timeout if timeout is None else timeout
        frame = (text + "\r\n").encode("ascii") if term is None else \
            (text.encode("ascii") + term)
        try:
            self._ser.write(frame)
        except Exception as e:
            raise TransportError("发送失败: %s" % e)
        return self._read_response(tmo)

    def read_reply(self, timeout: float = None) -> bytes:
        """不再发送，只等待并读取一段应答（用于跳过回显后取真实应答）。"""
        return self._read_response(self.timeout if timeout is None else timeout)

    def _read_response(self, timeout: float) -> bytes:
        buf = bytearray()
        t0 = time.time()
        last = time.time()
        while time.time() - t0 < timeout:
            try:
                n = self._ser.in_waiting
            except Exception:
                n = 0
            if n:
                try:
                    chunk = self._ser.read(n)
                except Exception as e:
                    raise TransportError("读取失败: %s" % e)
                if chunk:
                    buf += chunk
                    last = time.time()
            elif buf and (time.time() - last) > 0.15:
                break
            elif not buf and (time.time() - t0) > timeout:
                break
        # 注意：**空应答不在这里报错**。SCPI 协议的设置命令本来就不回任何东西，
        # 是不是"错误"取决于当前协议方言（见 dialects.classify），所以这里只如实返回。
        return bytes(buf)


class TcpTransport:
    """用于连接 simulator（离线自测）。SE 协议字符流，按行分割。"""

    def __init__(self, host="127.0.0.1", port=5020, timeout=2.0):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self._sock = None
        self._is_open = False

    def open(self):
        try:
            self._sock = socket.create_connection((self.host, self.port),
                                                  timeout=self.timeout)
            self._sock.settimeout(0.05)
        except Exception as e:
            raise TransportError("连接 %s:%s 失败: %s" % (self.host, self.port, e))
        self._is_open = True

    def close(self):
        self._is_open = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    @property
    def is_open(self):
        return self._is_open

    def read_reply(self, timeout: float = None) -> bytes:
        """不再发送，只等待并读取一段应答（用于跳过回显后取真实应答）。"""
        if self._sock is None:
            raise TransportError("传输层未打开")
        tmo = self.timeout if timeout is None else timeout
        buf = bytearray()
        t0 = time.time()
        last = time.time()
        while time.time() - t0 < tmo:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                chunk = b""
            except Exception as e:
                raise TransportError("读取失败: %s" % e)
            if chunk:
                buf += chunk
                last = time.time()
                if b"\n" in buf and (time.time() - last) > 0.15:
                    break
            elif buf and (time.time() - last) > 0.15:
                break
        return bytes(buf)

    def exchange(self, text: str, term: bytes = b"\r\n", timeout: float = None) -> bytes:
        if self._sock is None:
            raise TransportError("传输层未打开")
        frame = (text + "\r\n").encode("ascii") if term is None else \
            (text.encode("ascii") + term)
        try:
            self._sock.sendall(frame)
        except Exception as e:
            raise TransportError("发送失败: %s" % e)
        tmo = self.timeout if timeout is None else timeout
        buf = bytearray()
        t0 = time.time()
        last = time.time()
        while time.time() - t0 < tmo:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                chunk = b""
            except Exception as e:
                raise TransportError("读取失败: %s" % e)
            if chunk:
                buf += chunk
                last = time.time()
                if b"\n" in buf:
                    # 数据/ACK 通常一行即结束；再多等 150ms 看是否还有
                    if (time.time() - last) > 0.15:
                        break
            elif buf and (time.time() - last) > 0.15:
                break
        # 空应答交给协议方言判定（SCPI 的设置命令不回执是正常的），不在此报错
        return bytes(buf)
