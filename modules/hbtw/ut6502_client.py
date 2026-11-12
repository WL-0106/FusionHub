# -*- coding: utf-8 -*-
"""
UT-6502 以太网(光纤)-CAN 转换器 TCP 客户端
传输模式: 固定格式传输, 13 字节串行帧对应一个 CAN 报文:
  字节0   : 帧信息  bit7=FF(1扩展帧/0标准帧) bit6=RTR bit5-4保留(0) bit3-0=DLC
  字节1-4 : CAN 帧 ID, 大端 32 位
  字节5-12: 帧数据, 不足 8 字节补 0

设备需在 Web 页面配置为: TCP Server / 端口 5001 / CAN 波特率 1Mbps /
封包模式=固定格式传输 / 帧格式=扩展帧
"""

from PyQt5.QtCore import QObject, pyqtSignal, QByteArray
from PyQt5.QtNetwork import QAbstractSocket, QTcpSocket

FRAME_LEN = 13


def pack_frame(can_id, data):
    """CAN 帧 -> 13 字节串行帧"""
    data = bytes(data)[:8].ljust(8, b"\x00")
    info = 0x80 | len(data)          # bit7=1 扩展帧, RTR=0 数据帧, DLC=8
    return bytes([info]) + can_id.to_bytes(4, "big") + data


def unpack_frame(chunk):
    """13 字节串行帧 -> (can_id, data) 或 None(格式非法)"""
    if len(chunk) != FRAME_LEN:
        return None
    info = chunk[0]
    if info & 0x30:                  # 保留位必须为 0
        return None
    dlc = info & 0x0F
    if dlc > 8:
        return None
    can_id = int.from_bytes(chunk[1:5], "big")
    extended = bool(info & 0x80)
    if extended and can_id > 0x1FFFFFFF:
        return None
    if not extended and can_id > 0x7FF:
        return None
    return can_id, bytes(chunk[5:5 + dlc]).ljust(8, b"\x00")


class Ut6502Client(QObject):
    """QTcpSocket 异步客户端, 信号驱动, 无需额外线程"""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error_occurred = pyqtSignal(str)
    frame_received = pyqtSignal(int, bytes)      # can_id, 8字节数据
    stats_changed = pyqtSignal(int, int)         # tx_count, rx_count

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sock = QTcpSocket(self)
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.error.connect(self._on_error)
        self.sock.readyRead.connect(self._on_ready_read)
        self._rx_buf = bytearray()
        self._tx_count = 0
        self._rx_count = 0

    # ---------- 连接管理 ----------
    @property
    def is_connected(self):
        return self.sock.state() == QAbstractSocket.ConnectedState

    def connect_to(self, host, port):
        if self.is_connected:
            return
        self._rx_buf.clear()
        self.sock.connectToHost(host, int(port))

    def disconnect(self):
        if self.is_connected:
            self.sock.disconnectFromHost()

    def _on_connected(self):
        self.connected.emit()

    def _on_disconnected(self):
        self.disconnected.emit()

    def _on_error(self, err):
        self.error_occurred.emit(self.sock.errorString())

    # ---------- 收发 ----------
    def send_can(self, can_id, data):
        """发送一帧 CAN 报文, 返回是否成功"""
        if not self.is_connected:
            return False
        pkt = pack_frame(can_id, data)
        self.sock.write(QByteArray(pkt))
        self._tx_count += 1
        self.stats_changed.emit(self._tx_count, self._rx_count)
        return True

    def _on_ready_read(self):
        while self.sock.bytesAvailable() > 0:
            self._rx_buf.extend(bytes(self.sock.readAll()))
            while len(self._rx_buf) >= FRAME_LEN:
                chunk = bytes(self._rx_buf[:FRAME_LEN])
                parsed = unpack_frame(chunk)
                if parsed is None:
                    # 非 13 字节对齐或格式非法: 丢 1 字节重新同步
                    del self._rx_buf[0]
                    continue
                del self._rx_buf[:FRAME_LEN]
                can_id, data = parsed
                self._rx_count += 1
                self.frame_received.emit(can_id, data)
            self.stats_changed.emit(self._tx_count, self._rx_count)
