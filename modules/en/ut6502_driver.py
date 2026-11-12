"""
UT-6502 CAN-Ethernet 转换器通信驱动
深圳市宇泰科技有限公司

通过 TCP 连接 UT-6502, 使用固定格式传输(13字节/帧)收发 CAN 报文

固定格式帧结构 (13 字节):
  Byte 0:  帧信息 (FF RTR x x D3 D2 D1 D0)
           FF=1:扩展帧, FF=0:标准帧
           RTR=1:远程帧, RTR=0:数据帧
           D3-D0: 数据长度(1-8)
  Byte 1-4: 帧ID (大端, 4字节)
  Byte 5-12: 帧数据 (8字节, 不足补0)

默认参数:
  IP: 192.168.1.125
  端口: 5001
  CAN波特率: 125kbps (需在Web界面配置)
  传输模式: 固定格式传输 (需在Web界面配置)
  帧格式: 扩展帧 (需在Web界面配置)
"""

import socket
import struct
import threading
import time
from collections import deque


class UT6502Driver:
    """UT-6502 CAN-Ethernet 转换器驱动"""

    # 固定格式帧长度
    FRAME_SIZE = 13

    def __init__(self):
        self._sock = None
        self._connected = False
        self._lock = threading.Lock()
        self._recv_thread = None
        self._running = False
        self._rx_queue = deque(maxlen=500)
        self._rx_callbacks = []

        # send_and_wait 同步响应机制 (独立于 _rx_queue, 避免与 CanReceiver 竞争)
        self._wait_lock = threading.Lock()
        self._pending_match = None       # (tx_cmd, tx_dest) 或 None
        self._pending_response = None    # (can_id, can_data) 或 None
        self._pending_event = threading.Event()

    @property
    def connected(self):
        return self._connected

    def connect(self, ip, port=5001, timeout=3.0):
        """
        连接 UT-6502 转换器
        :param ip: UT-6502 的 IP 地址
        :param port: 端口号, 默认 5001
        :param timeout: 连接超时(秒)
        :return: True 成功, False 失败
        """
        try:
            self.disconnect()
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(timeout)
            self._sock.connect((ip, port))
            self._sock.settimeout(None)  # 阻塞模式, 由接收线程处理
            self._connected = True
            self._running = True
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            return True
        except Exception as e:
            self._connected = False
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            raise

    def disconnect(self):
        """断开连接"""
        self._running = False
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=1.0)
        self._recv_thread = None

    def _recv_loop(self):
        """接收线程主循环"""
        recv_buf = b''
        while self._running and self._connected:
            try:
                data = self._sock.recv(256)
                if not data:
                    break
                recv_buf += data
                while len(recv_buf) >= self.FRAME_SIZE:
                    frame = recv_buf[:self.FRAME_SIZE]
                    recv_buf = recv_buf[self.FRAME_SIZE:]
                    self._process_frame(frame)
            except socket.timeout:
                continue
            except ConnectionResetError:
                break
            except OSError:
                break
        self._connected = False

    def _process_frame(self, frame):
        """
        处理接收到的13字节固定格式帧
        :param frame: 13字节数据
        """
        if len(frame) < self.FRAME_SIZE:
            return

        frame_info = frame[0]
        is_extended = (frame_info >> 7) & 0x01
        is_rtr = (frame_info >> 6) & 0x01
        dlc = frame_info & 0x0F

        # 帧ID: 4字节大端
        can_id = struct.unpack('>I', frame[1:5])[0]
        if not is_extended:
            can_id &= 0x7FF  # 标准帧11位

        # 数据: 8字节
        can_data = frame[5:13]

        # 优先检查是否有 send_and_wait 在等待响应
        with self._wait_lock:
            if self._pending_match is not None:
                tx_cmd, tx_dest = self._pending_match
                rx_cmd = (can_id >> 16) & 0x3F
                rx_src = can_id & 0xFF
                rx_dest = (can_id >> 8) & 0xFF
                if rx_cmd == tx_cmd and rx_src == tx_dest and rx_dest == 0xF0:
                    self._pending_response = (can_id, can_data)
                    self._pending_event.set()
                    self._pending_match = None
                    return  # 响应已被 send_and_wait 消费, 不入队列

        # 存入队列 (供 CanReceiver 线程处理)
        self._rx_queue.append((can_id, can_data, is_extended, is_rtr, dlc))

        # 触发回调
        for cb in self._rx_callbacks:
            try:
                cb(can_id, can_data, is_extended, is_rtr, dlc)
            except Exception:
                pass

    def add_rx_callback(self, callback):
        """
        注册接收回调函数
        callback(can_id, can_data, is_extended, is_rtr, dlc)
        """
        self._rx_callbacks.append(callback)

    def remove_rx_callback(self, callback):
        """移除接收回调函数"""
        if callback in self._rx_callbacks:
            self._rx_callbacks.remove(callback)

    def get_rx_message(self):
        """
        从队列获取一条接收消息
        :return: (can_id, can_data, is_extended, is_rtr, dlc) 或 None
        """
        if self._rx_queue:
            return self._rx_queue.popleft()
        return None

    def send_can_frame(self, can_id, data, is_extended=True, is_rtr=False):
        """
        发送 CAN 帧 (通过 UT-6502 转换为 CAN 报文)
        :param can_id: CAN ID (29位扩展帧 或 11位标准帧)
        :param data: 数据 (bytes, 长度1-8)
        :param is_extended: True=扩展帧, False=标准帧
        :param is_rtr: True=远程帧, False=数据帧
        :return: True 成功, False 失败
        """
        if not self._connected or not self._sock:
            return False

        dlc = len(data)
        if dlc > 8:
            data = data[:8]
            dlc = 8

        # 填充数据到8字节
        padded_data = data + b'\x00' * (8 - dlc)

        # 构建帧信息字节
        frame_info = ((0x80 if is_extended else 0x00) |
                      (0x40 if is_rtr else 0x00) |
                      (dlc & 0x0F))

        # 构建13字节固定格式帧
        frame = bytes([frame_info]) + struct.pack('>I', can_id) + padded_data

        try:
            with self._lock:
                self._sock.sendall(frame)
            return True
        except Exception:
            self._connected = False
            return False

    def send_and_wait(self, can_id, data, timeout=2.0, is_extended=True):
        """
        发送 CAN 帧并等待匹配的响应
        匹配规则: 响应帧的cmd字段与发送帧相同, 且src=发送帧的dest, 且dest=0xF0
        使用 Event 机制直接在接收线程中路由响应, 避免与 CanReceiver 竞争 _rx_queue
        :param can_id: 要发送的 CAN ID
        :param data: 数据
        :param timeout: 等待超时(秒)
        :return: (rx_can_id, rx_data) 或 None
        """
        tx_cmd = (can_id >> 16) & 0x3F
        tx_dest = (can_id >> 8) & 0xFF  # 目标模块地址

        # 设置等待匹配条件
        with self._wait_lock:
            self._pending_response = None
            self._pending_event.clear()
            self._pending_match = (tx_cmd, tx_dest)

        if not self.send_can_frame(can_id, data, is_extended):
            with self._wait_lock:
                self._pending_match = None
            return None

        # 等待接收线程路由响应
        got = self._pending_event.wait(timeout=timeout)

        with self._wait_lock:
            self._pending_match = None
            response = self._pending_response
            self._pending_response = None

        return response if got else None
