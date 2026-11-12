"""
CAN盒驱动适配层
- 抽象基类 BaseCANInterface
- 宇泰 UT-6502 适配器
- ZLG CANFDNET-200U 适配器
"""
import socket
import struct
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from PyQt5.QtCore import QObject, pyqtSignal

from .protocol import CANFrame


class BaseCANInterface(QObject):
    """CAN设备接口基类"""

    # 信号
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    frame_received = pyqtSignal(CANFrame)
    log_message = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._socket: Optional[socket.socket] = None
        self._host = ""
        self._port = 0
        self._channel = 0
        self._connected = False
        self._recv_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        # 用于解析的内部缓冲区
        self._rx_buffer = b""

    # ---------- 公共API ----------

    def is_connected(self) -> bool:
        return self._connected

    def get_channel(self) -> int:
        """返回当前CAN通道号(0-based)"""
        return getattr(self, '_channel', 0)

    @abstractmethod
    def connect(self, host: str, port: int) -> bool:
        ...

    def disconnect(self):
        """断开连接(通用)"""
        self._running = False
        self._connected = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        self.disconnected.emit()
        self.log_message.emit("已断开连接", "SYS")

    @abstractmethod
    def send_frame(self, frame: CANFrame) -> bool:
        ...

    def send_raw(self, data: bytes) -> bool:
        if not self._socket or not self._connected:
            return False
        try:
            with self._lock:
                self._socket.sendall(data)
            return True
        except Exception as e:
            self.error_occurred.emit(f"发送失败: {str(e)}")
            return False

    # ---------- 通用接收循环 ----------

    def _start_recv_thread(self):
        self._rx_buffer = b""
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def _receive_loop(self):
        while self._running:
            try:
                if not self._socket:
                    break
                try:
                    data = self._socket.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    time.sleep(0.005)
                    continue
                self._rx_buffer += data
                self._process_rx_buffer()
            except Exception as e:
                if self._running:
                    self.error_occurred.emit(f"接收错误: {str(e)}")
                    time.sleep(0.05)
                else:
                    break
        if self._running:
            self._connected = False
            self.disconnected.emit()

    @abstractmethod
    def _process_rx_buffer(self):
        """子类实现具体帧解析逻辑"""
        ...


# =============================================================
# 宇泰UT-6502 适配器
# =============================================================

class UT6502Interface(BaseCANInterface):
    """宇泰UT-6502 以太网-CAN转换器

    线上格式 = 13 字节固定帧（与 asby/hbtw 真机联调版 ut6502_client 一致）：
        Byte0:    帧信息 = 0x80(扩展帧) | DLC
        Byte1-4:  CAN ID（大端）
        Byte5-12: 数据（8 字节，不足补 0）
    旧实现发 AA 55 起始帧并按包头扫描解析（“常见格式”猜测），与盒子实际模式不符：
    发出去的帧盒子不认、应答帧被逐字节跳过误解析 —— 表现为“只发不收、扫不到模块”。
    默认 TCP 端口 5001（与协议说明及兄弟模块一致）。
    """

    FRAME_LEN = 13

    def __init__(self, parent=None, can_channel: int = 0):
        super().__init__(parent)
        self._channel = can_channel  # 记录通道号(UT-6502为单通道, 仅用于统一接口)

    def connect(self, host: str, port: int) -> bool:
        self._host = host
        self._port = port
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5.0)
            self._socket.connect((host, port))
            self._socket.settimeout(0.5)
            self._connected = True
            self._running = True
            self._start_recv_thread()
            self.connected.emit()
            self.log_message.emit(f"[UT-6502] 已连接 {host}:{port}", "SYS")
            return True
        except Exception as e:
            self.error_occurred.emit(f"连接失败: {str(e)}")
            return False

    @classmethod
    def encode_frame(cls, frame: CANFrame) -> bytes:
        """构建 UT-6502 固定 13 字节帧（真机联调版格式）。"""
        data = bytes(frame.data or b"")[:8]
        dlc = len(data)
        data = data.ljust(8, b"\x00")
        frame_info = 0x80 | (dlc & 0x0F)   # 扩展帧 | DLC
        return (bytes([frame_info])
                + struct.pack(">I", frame.arbitration_id & 0x1FFFFFFF)
                + data)

    def send_frame(self, frame: CANFrame) -> bool:
        if not self._socket or not self._connected:
            self.error_occurred.emit("未连接，无法发送")
            return False
        try:
            payload = self.encode_frame(frame)
            with self._lock:
                self._socket.sendall(payload)
            self.log_message.emit(str(frame), "TX")
            return True
        except Exception as e:
            self.error_occurred.emit(f"发送失败: {str(e)}")
            return False

    def _process_rx_buffer(self):
        while True:
            frame, consumed = self._parse_frame(self._rx_buffer)
            if frame and consumed > 0:
                self._rx_buffer = self._rx_buffer[consumed:]
                frame.timestamp = time.time()
                self.frame_received.emit(frame)
                self.log_message.emit(str(frame), "RX")
            elif consumed > 0:
                self._rx_buffer = self._rx_buffer[consumed:]
            else:
                break

    def _parse_frame(self, data: bytes) -> Tuple[Optional[CANFrame], int]:
        """定长 13 字节解析：不按包头扫描（旧式跳字节会把合法应答拆成杂帧）。"""
        if len(data) < self.FRAME_LEN:
            return None, 0
        frame_info = data[0]
        dlc = frame_info & 0x0F
        if dlc > 8 or (frame_info & 0x70):
            # 帧信息非法（高半字节仅扩展位 0x8/标准 0x0 合法）→ 跳一字节重同步
            return None, 1
        extended = bool(frame_info & 0x80)
        can_id = struct.unpack(">I", data[1:5])[0]
        can_data = data[5:5 + dlc]
        return CANFrame(can_id, can_data, is_extended_id=extended), self.FRAME_LEN


# =============================================================
# ZLG CANFDNET-200U 适配器
# =============================================================

class ZLG_CANFDNETInterface(BaseCANInterface):
    """ZLG CANFDNET-200U 以太网-CAN(FD)转换器
    网络包格式:
      [SOF=0x55][包类型=0x00][类型参数][保留=0][数据长度(2B大端)][数据区][BCC校验=1B]
    单帧CAN报文格式(20字节):
      [时间戳8B][ID 4B][报文信息 2B][通道 1B][数据长度 1B][数据 8B]
    报文信息(2B小端) bit定义:
      bit6 EXT=1 (扩展帧29位ID)
      bit4 FD=1
      bit5 RTR
      bit3 ECHO
    默认TCP端口: 4001
    """

    SOF = 0x55
    PKT_TYPE_CAN = 0x00
    PKT_TYPE_CANFD = 0x01

    def __init__(self, parent=None, can_channel: int = 0):
        super().__init__(parent)
        self._channel = can_channel  # CAN通道号

    def connect(self, host: str, port: int) -> bool:
        self._host = host
        self._port = port
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5.0)
            self._socket.connect((host, port))
            self._socket.settimeout(0.5)
            self._connected = True
            self._running = True
            self._start_recv_thread()
            self.connected.emit()
            self.log_message.emit(f"[ZLG CANFDNET-200U] 已连接 {host}:{port}", "SYS")
            return True
        except Exception as e:
            self.error_occurred.emit(f"连接失败: {str(e)}")
            return False

    def send_frame(self, frame: CANFrame) -> bool:
        """发送CAN报文
        英飞源REG使用29位扩展ID(bit6 EXT=1), 数据<=8字节
        """
        if not self._socket or not self._connected:
            self.error_occurred.emit("未连接，无法发送")
            return False
        try:
            dlc = min(8, len(frame.data) if frame.data else 8)
            # 单帧报文(20字节): 时间戳(8B=0)+ ID(4B大端)+ 信息(2B大端)+ 通道(1B)+ 长度(1B)+ 数据(8B)
            # ZLG协议: 所有多字节字段一律大端
            can_frame = bytearray(20)
            # 报文ID - 大端(高字节在前), 29位ID存于Bit0~28
            struct.pack_into('>I', can_frame, 8, frame.arbitration_id & 0xFFFFFFFF)
            # 报文信息 - 大端, bit6 EXT=1 表示扩展帧 (0x0040)
            struct.pack_into('>H', can_frame, 12, 0x0040)
            # 通道
            can_frame[14] = self._channel & 0xFF
            # 数据长度
            can_frame[15] = dlc & 0xFF
            # 数据
            if frame.data and len(frame.data) > 0:
                can_frame[16:16+dlc] = frame.data[:dlc]

            # 包装网络包
            pkt = bytearray()
            pkt.append(self.SOF)
            pkt.append(self.PKT_TYPE_CAN)
            pkt.append(0x00)             # 类型参数
            pkt.append(0x00)             # 保留
            pkt.extend(struct.pack('>H', len(can_frame)))  # 数据长度
            pkt.extend(can_frame)
            # BCC校验: 异或 从起始标识到校验前一个字节
            csum = 0
            for b in pkt:
                csum ^= b
            pkt.append(csum & 0xFF)

            with self._lock:
                self._socket.sendall(bytes(pkt))
            self.log_message.emit(str(frame), "TX")
            return True
        except Exception as e:
            self.error_occurred.emit(f"发送失败: {str(e)}")
            return False

    def _process_rx_buffer(self):
        """解析ZLG网络包 -> CAN帧列表"""
        while len(self._rx_buffer) >= 6:
            # SOF必须是0x55
            if self._rx_buffer[0] != self.SOF:
                # 寻找下一个0x55
                idx = self._rx_buffer.find(b'\x55', 1)
                if idx < 0:
                    self._rx_buffer = b""
                    return
                self._rx_buffer = self._rx_buffer[idx:]
                continue

            # 数据长度
            data_len = (self._rx_buffer[4] << 8) | self._rx_buffer[5]
            total_len = 6 + data_len + 1  # 包头(6) + 数据 + 校验(1)
            if len(self._rx_buffer) < total_len:
                return  # 等待更多数据

            pkt_type = self._rx_buffer[1]
            pkt = bytes(self._rx_buffer[:total_len])

            # 校验BCC
            csum_calc = 0
            for b in pkt[:-1]:
                csum_calc ^= b
            if (csum_calc & 0xFF) != pkt[-1]:
                # 校验失败, 跳过此包
                self.log_message.emit("[ZLG] 包校验错误, 已跳过", "SYS")
                self._rx_buffer = self._rx_buffer[total_len:]
                continue

            # 处理包
            if pkt_type == self.PKT_TYPE_CAN:
                # CAN数据包, 数据区每个CAN帧为20字节
                data_area = self._rx_buffer[6:6+data_len]
                for i in range(0, len(data_area), 20):
                    frame = self._parse_can_frame(data_area[i:i+20])
                    if frame:
                        frame.timestamp = time.time()
                        self.frame_received.emit(frame)
                        self.log_message.emit(str(frame), "RX")
            elif pkt_type == self.PKT_TYPE_CANFD:
                # CANFD帧每帧长度不固定 (简化按20处理 + 64字节数据)
                data_area = self._rx_buffer[6:6+data_len]
                i = 0
                while i < len(data_area):
                    if i + 16 > len(data_area):
                        break
                    dlc = data_area[i+15]
                    frame_len = 16 + dlc  # 帧头16字节 + 数据
                    frame = self._parse_canfd_frame(data_area[i:i+frame_len])
                    if frame:
                        frame.timestamp = time.time()
                        self.frame_received.emit(frame)
                        self.log_message.emit(str(frame), "RX")
                    i += frame_len

            self._rx_buffer = self._rx_buffer[total_len:]

    def _parse_can_frame(self, raw: bytes) -> Optional[CANFrame]:
        """解析20字节CAN帧 (大端)"""
        if len(raw) < 20:
            return None
        can_id = struct.unpack('>I', raw[8:12])[0]  # 大端
        info = struct.unpack('>H', raw[12:14])[0]   # 大端
        dlc = raw[15]
        # 只保留29位ID
        can_id &= 0x1FFFFFFF
        dlc = min(8, dlc)
        can_data = raw[16:16+dlc]
        return CANFrame(can_id, can_data)

    def _parse_canfd_frame(self, raw: bytes) -> Optional[CANFrame]:
        """解析CANFD帧(简化, 取前16字节头+数据)"""
        if len(raw) < 16:
            return None
        can_id = struct.unpack('>I', raw[8:12])[0]  # 大端
        can_id &= 0x1FFFFFFF
        dlc = min(8, raw[15])  # 简化处理, 仅取前8字节
        can_data = raw[16:16+dlc] if len(raw) >= 16+dlc else b'\x00'*dlc
        return CANFrame(can_id, can_data)


# =============================================================
# 工厂方法
# =============================================================

def create_can_interface(can_box_type: str, parent=None, channel: int = 0) -> BaseCANInterface:
    """根据CAN盒类型创建适配器
    can_box_type: 'UT6502' | 'ZLG_CANFDNET'
    channel: 0-based CAN通道号 (UI显示为1/2, 内部转0/1)
    """
    if can_box_type == 'ZLG_CANFDNET':
        return ZLG_CANFDNETInterface(parent, can_channel=channel)
    return UT6502Interface(parent, can_channel=channel)