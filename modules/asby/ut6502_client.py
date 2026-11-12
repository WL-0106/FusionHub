# -*- coding: utf-8 -*-
"""
宇泰UT-6502 以太网-CAN转换器 TCP客户端
"""

import socket
import struct
import threading
import time
from collections import deque
from .can_protocol import parse_ut6502_frame, build_ut6502_frame


class UT6502Client:
    """UT-6502 TCP客户端"""
    
    def __init__(self):
        self.sock = None
        self.connected = False
        self.ip = ""
        self.port = 0
        self.recv_thread = None
        self.send_lock = threading.Lock()
        self.recv_buffer = b''
        self.message_callbacks = []
        self.connect_callbacks = []
        self.disconnect_callbacks = []
        self.running = False
        self.send_queue = deque()
        self._disconnect_notified = True
        self._connect_notified = False
        self.rx_total_bytes = 0
        self.rx_frame_count = 0
        self.rx_raw_log = []  # 最近的原始收包片段，便于诊断“有字节但帧不对”

    def connect(self, ip, port=5001, timeout=3):
        """连接到UT-6502"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect((ip, port))
            self.sock.settimeout(None)  # 设为阻塞模式
            self.ip = ip
            self.port = port
            self.connected = True
            self.running = True
            self.recv_buffer = b''
            self._disconnect_notified = False
            self._connect_notified = False
            self.rx_total_bytes = 0
            self.rx_frame_count = 0
            self.rx_raw_log = []

            # 启动接收线程
            self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self.recv_thread.start()

            self._notify_connected()
            return True
        except Exception as e:
            pass  # 连接失败由上层信号处理
            self.sock = None
            self.connected = False
            return False
    
    def _notify_connected(self):
        """连接成功回调（只触发一次）"""
        if self._connect_notified:
            return
        self._connect_notified = True
        for cb in self.connect_callbacks:
            try:
                cb()
            except Exception:
                pass

    def _notify_disconnected(self):
        """断开连接回调（只触发一次，避免手动断开+接收线程双报）"""
        if self._disconnect_notified:
            return
        self._disconnect_notified = True
        for cb in self.disconnect_callbacks:
            try:
                cb()
            except Exception:
                pass

    def disconnect(self):
        """断开连接"""
        self.running = False
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        self._notify_disconnected()

    def _recv_loop(self):
        """接收数据循环"""
        while self.running and self.connected:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                self.rx_total_bytes += len(data)
                self.recv_buffer += data
                self._parse_buffer()
            except Exception:
                break

        # 连接断开（与手动 disconnect 共用同一防重入口）
        self.connected = False
        self._notify_disconnected()

    def _parse_buffer(self):
        """解析接收缓冲区中的数据"""
        # UT-6502固定格式为13字节一帧
        while len(self.recv_buffer) >= 13:
            # 尝试解析一帧
            frame = parse_ut6502_frame(self.recv_buffer[:13])
            if frame:
                self.recv_buffer = self.recv_buffer[13:]
                self.rx_frame_count += 1
                # 通知回调
                for cb in self.message_callbacks:
                    try:
                        cb(frame)
                    except Exception:
                        pass
            else:
                # 无法解析，移除一个字节再试
                self._note_raw(self.recv_buffer[:16])
                self.recv_buffer = self.recv_buffer[1:]

    def _note_raw(self, chunk):
        """记录疑似异常原始字节，便于区分「没回包」和「回包帧不对」"""
        try:
            self.rx_raw_log.append(chunk.hex(' ').upper())
            if len(self.rx_raw_log) > 20:
                self.rx_raw_log = self.rx_raw_log[-20:]
        except Exception:
            pass
    
    def send_frame(self, frame_bytes):
        """发送CAN帧数据"""
        if not self.connected or not self.sock:
            return False
        try:
            with self.send_lock:
                self.sock.sendall(frame_bytes)
            return True
        except Exception as e:
            pass  # 发送失败由上层信号处理
            return False
    
    def send_can_message(self, can_id, data_bytes, extended=True):
        """发送CAN消息"""
        frame = build_ut6502_frame(can_id, data_bytes, extended)
        return self.send_frame(frame)
    
    def add_message_callback(self, callback):
        """添加消息接收回调"""
        self.message_callbacks.append(callback)
    
    def add_connect_callback(self, callback):
        """添加连接成功回调"""
        self.connect_callbacks.append(callback)
    
    def add_disconnect_callback(self, callback):
        """添加断开连接回调"""
        self.disconnect_callbacks.append(callback)
    
    def is_connected(self):
        """检查是否已连接"""
        return self.connected
