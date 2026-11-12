"""通信层：统一的 Transport 接口 + 两种实现。

- TcpTransport : QTcpSocket 异步收发，按 UT-6502 13 字节固定格式封包/解包。
- SimTransport : 进程内直连 SimBus，无硬件即可演示与自测。

两者对上层暴露一致的信号与 send() 方法，便于在真实链路与模拟链路间切换。
"""

from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from PyQt5.QtNetwork import QTcpSocket

from . import protocol as P
from .simulator import SimBus

CONNECT_TIMEOUT_MS = 5000   # TCP 连接超时：不可达时不再无限等待


class Transport(QObject):
    """传输层基类。"""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)
    frame_tx = pyqtSignal(int, bytes)   # 上位机 -> 总线
    frame_rx = pyqtSignal(int, bytes)   # 总线 -> 上位机

    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def is_open(self) -> bool:
        raise NotImplementedError

    def send(self, can_id: int, data: bytes):
        raise NotImplementedError


class TcpTransport(Transport):
    """经 UT-6502 转换器的 TCP 通道收发 CAN 报文。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sock = QTcpSocket(self)
        self._parser = P.Ut6502StreamParser()
        self._host = ""
        self._port = 0
        self._suppress_error = False
        self._sock.connected.connect(self._on_connected)
        self._sock.disconnected.connect(self._on_disconnected)
        self._sock.readyRead.connect(self._on_ready_read)
        self._sock.errorOccurred.connect(self._on_error)
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._on_connect_timeout)

    def open(self):
        raise RuntimeError("TcpTransport 请调用 open_host(ip, port)")

    def open_host(self, ip: str, port: int):
        self._parser.reset()
        self._host = ip
        self._port = int(port)
        self._suppress_error = False
        self._sock.connectToHost(ip, int(port))
        self._connect_timer.start(CONNECT_TIMEOUT_MS)

    def close(self):
        self._connect_timer.stop()
        if self._sock.state() != QTcpSocket.UnconnectedState:
            self._sock.abort()
        self._sock.close()
        self._parser.reset()

    def is_open(self) -> bool:
        return self._sock.state() == QTcpSocket.ConnectedState

    def send(self, can_id: int, data: bytes):
        if not self.is_open():
            return
        frame = P.ut6502_encode(can_id, data)
        self._sock.write(frame)
        self.frame_tx.emit(can_id, bytes(data))

    # ------------------------------------------------------------ 内部回调
    def _on_connected(self):
        self._connect_timer.stop()
        self.connected.emit()

    def _on_disconnected(self):
        self.disconnected.emit()

    def _on_ready_read(self):
        chunk = bytes(self._sock.readAll())
        for can_id, data, _info in self._parser.feed(chunk):
            self.frame_rx.emit(can_id, data)

    def _on_connect_timeout(self):
        if self._sock.state() == QTcpSocket.ConnectedState:
            return
        self._suppress_error = True
        self.error.emit(
            f"连接超时：{self._host}:{self._port} 无响应 "
            f"（请检查 IP、端口、网线及设备是否工作在 TCP Server 模式）")
        self._sock.abort()

    def _on_error(self, _err):
        self._connect_timer.stop()
        if self._suppress_error:
            self._suppress_error = False
            return
        self.error.emit(
            f"连接失败：{self._sock.errorString()}（{self._host}:{self._port}）")


class SimTransport(Transport):
    """进程内模拟传输：直接把报文交给 SimBus，并把应答异步回灌。

    用 QTimer 制造少量延时，模拟真实总线往返时序，避免界面在同步回调里重入。
    """

    def __init__(self, addrs=None, parent=None):
        super().__init__(parent)
        self.bus = SimBus(addrs)
        self._open = False

    def open(self):
        self._open = True
        QTimer.singleShot(0, self.connected.emit)

    def close(self):
        if self._open:
            self._open = False
            self.disconnected.emit()

    def is_open(self) -> bool:
        return self._open

    def send(self, can_id: int, data: bytes):
        if not self._open:
            return
        self.frame_tx.emit(can_id, bytes(data))
        replies = self.bus.dispatch(can_id, data)
        for resp_id, resp_data in replies:
            QTimer.singleShot(3, lambda i=resp_id, d=resp_data: self.frame_rx.emit(i, d))


def create_transport(mode: str, parent=None) -> Transport:
    """mode: 'tcp' | 'sim'"""
    if mode == "sim":
        return SimTransport(parent=parent)
    return TcpTransport(parent=parent)