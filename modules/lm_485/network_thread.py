"""
网络通信线程 - 通过TCP连接UT-6816串口服务器, 透明传输RS-485 Modbus RTU数据

UT-6816-I-E串口服务器工作在TCP Server模式时, 将RS-485串口数据
通过TCP连接透明传输, 上位机作为TCP客户端连接即可收发Modbus RTU帧。
"""

import socket
import time
import threading
from collections import deque

from PyQt5.QtCore import QThread, pyqtSignal

from . import modbus_rtu


class NetworkWorker(QThread):
    """网络(TCP)通信工作线程 - 接口与SerialWorker完全一致"""

    response_received = pyqtSignal(int, bytes, bytes)
    broadcast_sent = pyqtSignal(bytes)
    timeout_occurred = pyqtSignal(int, bytes)
    log_message = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool, str)
    scan_result = pyqtSignal(int, bool)
    scan_progress = pyqtSignal(int, int, int)
    comm_error = pyqtSignal(str)

    MAX_CONSECUTIVE_ERRORS = 5

    def __init__(self):
        super().__init__()
        self._sock = None
        self._running = False
        self._connected = False
        self._request_queue = deque()
        self._queue_lock = threading.Lock()
        self._response_timeout = 0.3
        self._inter_frame_delay = 0.005
        self._scan_mode = False
        self._baudrate = 9600
        self._consecutive_errors = 0
        self._host = ""
        self._port = 10010

    def connect_port(self, host: str, port: int = 10010,
                     baudrate: int = 9600, **kwargs) -> bool:
        """连接TCP串口服务器"""
        try:
            if self._sock:
                self._sock.close()
            self._host = host
            self._port = port
            self._baudrate = baudrate
            self._consecutive_errors = 0
            self._inter_frame_delay = max(0.002, 3.5 * 11.0 / baudrate)

            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(3.0)
            self._sock.connect((host, port))
            self._sock.settimeout(0.05)

            self._connected = True
            self.connection_changed.emit(True, f"已连接 {host}:{port}")
            self.log_message.emit("INFO",
                f"TCP连接成功: {host}:{port} (波特率映射 {baudrate}bps)")
            return True
        except Exception as e:
            self._connected = False
            self.connection_changed.emit(False, f"连接失败: {e}")
            self.log_message.emit("ERROR", f"TCP连接失败: {e}")
            return False

    def disconnect_port(self):
        """断开TCP连接"""
        self.clear_queue()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._connected = False
        self.connection_changed.emit(False, "已断开")
        self.log_message.emit("INFO", f"TCP已断开: {self._host}:{self._port}")

    def is_connected(self) -> bool:
        return self._connected and self._sock is not None

    def set_rts_control(self, enabled: bool):
        pass  # TCP模式无需RTS控制, 串口服务器自动处理RS-485方向

    def clear_queue(self):
        with self._queue_lock:
            count = len(self._request_queue)
            self._request_queue.clear()
        if count:
            self.log_message.emit("INFO", f"已清空 {count} 个待处理请求")

    def enqueue_request(self, addr: int, frame: bytes, description: str = ""):
        with self._queue_lock:
            self._request_queue.append((addr, frame, description))

    def run(self):
        self._running = True
        while self._running:
            if not self.is_connected():
                time.sleep(0.05)
                continue

            if self._request_queue:
                with self._queue_lock:
                    addr, frame, desc = self._request_queue.popleft()

                if not self.is_connected():
                    continue

                try:
                    self._send_and_receive(addr, frame, desc)
                except Exception as e:
                    self._consecutive_errors += 1
                    self.log_message.emit("ERROR", f"通信异常: {e}")
                    if self._consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        self._auto_disconnect()
                    continue
            else:
                time.sleep(0.01)

    def _auto_disconnect(self):
        """连续错误超限, 自动断开连接"""
        err_msg = f"连续 {self._consecutive_errors} 次通信错误, 自动断开连接"
        self.log_message.emit("ERROR", err_msg)
        self._consecutive_errors = 0
        try:
            self.clear_queue()
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._connected = False
        self.comm_error.emit(err_msg)
        self.connection_changed.emit(False, "通信错误, 已自动断开")

    def _send_and_receive(self, addr: int, frame: bytes, desc: str):
        """通过TCP发送请求并接收响应"""
        time.sleep(self._inter_frame_delay)

        # 清空接收缓冲区残留数据
        try:
            self._sock.settimeout(0)
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
        except (BlockingIOError, socket.error):
            pass
        finally:
            self._sock.settimeout(0.05)

        # 发送
        try:
            self._sock.sendall(frame)
            self._consecutive_errors = 0
            self.log_message.emit("TX", modbus_rtu.format_bytes(frame))
            if desc:
                self.log_message.emit("INFO", f"发送: {desc} (地址 0x{addr:02X})")
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 2:
                self.log_message.emit("ERROR", f"TCP发送失败: {e}")
            return

        # 广播请求不需要等待响应
        if addr == modbus_rtu.BROADCAST_ADDR:
            self.broadcast_sent.emit(frame)
            return

        # 等待响应
        timeout = 0.2 if self._scan_mode else self._response_timeout
        response = self._read_response(timeout)

        if response:
            self.response_received.emit(addr, response, frame)
            if self._scan_mode:
                self.scan_result.emit(addr, True)
        else:
            self.timeout_occurred.emit(addr, frame)
            if self._scan_mode:
                self.scan_result.emit(addr, False)
                self.log_message.emit("WARN", f"0x{addr:02X} 无响应")
            else:
                self.log_message.emit("WARN", f"地址 0x{addr:02X} 响应超时")

    def _read_response(self, timeout: float = 0.3) -> bytes:
        """读取TCP响应 - 等到超时或检测到帧结束(帧间静默)"""
        deadline = time.time() + timeout
        response = bytearray()
        last_byte_time = 0
        inter_byte_timeout = 0.015

        try:
            while time.time() < deadline:
                try:
                    self._sock.settimeout(0.002)
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        break
                    response.extend(chunk)
                    last_byte_time = time.time()
                    continue
                except socket.timeout:
                    pass
                except (ConnectionResetError, BrokenPipeError, OSError):
                    return b""

                if response and last_byte_time and (time.time() - last_byte_time) > inter_byte_timeout:
                    break
        except Exception:
            return b""

        return bytes(response) if len(response) >= 5 else b""

    def set_scan_mode(self, enabled: bool):
        self._scan_mode = enabled

    def stop(self):
        """停止线程"""
        self._running = False
        self.clear_queue()
        self.wait(500)
