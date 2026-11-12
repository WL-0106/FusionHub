"""
宇泰 UT-6502 以太网-CAN 转换器通讯驱动
TCP连接, 固定格式传输(每帧13字节)
"""

import socket
import threading
import time
import struct
from PyQt5.QtCore import QObject, pyqtSignal, QThread

from . import can_protocol as cp


class UT6502Receiver(QThread):
    frame_received = pyqtSignal(int, list, bool)
    connection_lost = pyqtSignal(str)
    log_message = pyqtSignal(str, bool)

    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self._running = True
        self._buffer = bytearray()

    def run(self):
        self._running = True
        while self._running:
            try:
                self.sock.settimeout(0.5)
                chunk = self.sock.recv(4096)
                if not chunk:
                    self.connection_lost.emit("连接已断开")
                    break
                self._buffer.extend(chunk)
                while len(self._buffer) >= 13:
                    frame = self._buffer[:13]
                    del self._buffer[:13]
                    parsed = cp.parse_ut6502_frame(bytes(frame))
                    if parsed:
                        self.frame_received.emit(
                            parsed['id'],
                            parsed['data'],
                            parsed['remote'],
                        )
            except socket.timeout:
                continue
            except ConnectionResetError:
                self.connection_lost.emit("连接被重置")
                break
            except OSError as e:
                if self._running:
                    self.connection_lost.emit(f"socket错误: {e}")
                break

    def stop(self):
        self._running = False
        self.wait(2000)


class UT6502Driver(QObject):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    frame_received = pyqtSignal(int, list, bool)
    frame_sent = pyqtSignal(int, list)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__()
        self.sock = None
        self.receiver = None
        self._is_connected = False

    @property
    def is_connected(self):
        return self._is_connected

    def connect(self, ip, port):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(3)
            self.sock.connect((ip, port))
            self.sock.settimeout(0.5)
            self._is_connected = True
            self.receiver = UT6502Receiver(self.sock)
            self.receiver.frame_received.connect(self._on_frame_received)
            self.receiver.connection_lost.connect(self._on_conn_lost)
            self.receiver.start()
            self.connected.emit()
            self.log_message.emit(f"已连接到 UT-6502 ({ip}:{port})", False)
            return True
        except Exception as e:
            self.error_occurred.emit(f"连接失败: {e}")
            self.log_message.emit(f"连接失败: {e}", True)
            return False

    def disconnect(self):
        self._is_connected = False
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.disconnected.emit()
        self.log_message.emit("已断开连接", False)

    def _on_frame_received(self, can_id, data, remote):
        self.frame_received.emit(can_id, data, remote)

    def _on_conn_lost(self, reason):
        self._is_connected = False
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.disconnected.emit()
        self.error_occurred.emit(reason)
        self.log_message.emit(f"连接丢失: {reason}", True)

    def send_can_frame(self, can_id, data, extended=True, remote=False):
        if not self._is_connected or not self.sock:
            self.log_message.emit("发送失败: 未连接", True)
            return False
        frame = cp.build_ut6502_frame(can_id, data, extended=extended, remote=remote)
        try:
            self.sock.sendall(frame)
            self.frame_sent.emit(can_id, data)
            return True
        except Exception as e:
            self.log_message.emit(f"发送失败: {e}", True)
            return False

    def send_command(self, can_id, data):
        dlc = len(data)
        if dlc == 0:
            return self.send_can_frame(can_id, [], extended=True, remote=True)
        else:
            return self.send_can_frame(can_id, data, extended=True, remote=False)
