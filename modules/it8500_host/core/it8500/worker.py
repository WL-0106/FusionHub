"""设备工作线程: 串口收发/轮询全部在此线程执行, 结果经 Qt 信号回 UI。"""
from __future__ import annotations

import queue
import time

from PyQt5.QtCore import QThread, pyqtSignal as Signal

from .device import Device
from .protocol import DeviceError, hexdump
from .transport import Transport, TransportError


class DeviceWorker(QThread):
    """命令队列 + 测量轮询。

    - submit(): 任意线程投递任务, 完成后发出 result(seq, name, ok, payload)
    - 轮询: 连接成功后每 poll_interval 秒读一次 5FH, 发出 measured(payload)
    - 日志: tx/rx 原始帧十六进制, 发出 raw_log(direction, text)
    - state: 连接状态变化, 发出 conn_state(connected, message)
    """

    result = Signal(int, str, bool, object)     # seq, 任务名, 是否成功, 结果/错误
    measured = Signal(object)                   # protocol.Measurement
    raw_log = Signal(str, str)                  # "TX"/"RX"/"ERR", hex 文本
    conn_state = Signal(bool, str)              # 已连接?, 提示
    busy = Signal(bool)                         # 是否有任务在执行

    MAX_POLL_FAILS = 5  # 轮询连续失败上限, 达到后停止轮询(设备离线保护)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._stop = False
        self._poll_interval = 0.35
        self._polling = False
        self._poll_fails = 0
        self._last_poll = 0.0
        self._seq = 0
        self.device: Device | None = None

    # ---------------------------------------------------------- 对外接口
    def submit(self, name: str, fn, *args, **kwargs) -> int:
        """投递任务; fn 在工作线程中执行, 返回值/异常经 result 信号返回。"""
        self._seq += 1
        seq = self._seq
        self._queue.put((seq, name, fn, args, kwargs))
        return seq

    def stop(self, wait_ms: int = 3000) -> None:
        # 退出前先关拉载（电子负载安全闭环：避免断开后负载仍拉载）
        if self.device is not None and self.device.connected:
            try:
                self.device.set_input(False)
            except Exception:  # noqa: BLE001 —— 设备已掉线/无响应时静默跳过
                pass
        self._stop = True
        self.wait(wait_ms)
        # 线程已退出, 此时可安全释放设备
        if self.device is not None:
            try:
                self.device.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.device = None

    def set_polling(self, enabled: bool) -> None:
        self._polling = enabled

    # ---------------------------------------------------------- 线程主体
    def run(self) -> None:
        while not self._stop:
            did_work = False
            try:
                item = self._queue.get(timeout=0.02)
            except queue.Empty:
                item = None
            if item is not None:
                did_work = True
                self._run_task(item)
            if (self._polling and self.device and self.device.connected
                    and not did_work
                    and time.monotonic() - self._last_poll >= self._poll_interval):
                self._last_poll = time.monotonic()
                did_work = True
                self._run_task((0, "poll", self.device.read_measurement, (), {}))
            if not did_work:
                time.sleep(0.005)

    def _run_task(self, item) -> None:
        seq, name, fn, args, kwargs = item
        self.busy.emit(True)
        try:
            payload = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            text = str(e) or e.__class__.__name__
            self.raw_log.emit("ERR", text)
            self.result.emit(seq, name, False, text)
            if name == "poll":
                self._poll_fails += 1
                if self._poll_fails >= 3:
                    self._poll_interval = 2.0   # 失败降频, 恢复后自动复位
                if self._poll_fails >= self.MAX_POLL_FAILS:
                    # 设备掉线保护: 停止轮询, 经 conn_state 通知界面离线复位
                    self._polling = False
                    msg = (f"设备连续 {self._poll_fails} 次无响应, "
                           f"已停止轮询, 请检查连接")
                    self.raw_log.emit("ERR", msg)
                    self.conn_state.emit(False, msg)
            if name == "connect" and self.device is not None:
                try:
                    self.device.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                self._polling = False
                self.conn_state.emit(False, f"连接失败: {text}")
            self.busy.emit(False)
            return
        if name == "poll":
            self.measured.emit(payload)
            # 连续失败自动降频, 避免真机无应答时日志刷屏
            if self._poll_fails:
                self._poll_fails = 0
                self._poll_interval = 0.35
        elif name == "connect" and self.device is not None:
            self._polling = True
            self._poll_fails = 0
            self._last_poll = 0.0
            self.conn_state.emit(True, f"已连接 {self.device.transport.name}")
        elif name == "disconnect":
            self._polling = False
            self.conn_state.emit(False, "已断开")
        self.result.emit(seq, name, True, payload)
        self.busy.emit(False)

    # ---------------------------------------------------------- 连接管理
    def do_connect(self, transport: Transport, addr: int,
                   on_tx, on_rx) -> str:
        """在工作线程中打开传输并创建 Device。"""
        if self.device is not None:
            try:
                self.device.disconnect()
            except Exception:  # noqa: BLE001
                pass
        dev = Device(transport, addr=addr, on_tx=on_tx, on_rx=on_rx)
        dev.connect()
        self.device = dev
        return transport.name

    def do_disconnect(self) -> None:
        if self.device is not None:
            try:
                self.device.disconnect()
            except Exception:  # noqa: BLE001 —— 掉线时disconnect()可能抛异常, 不阻断conn_state发出
                pass
            self.device = None

    def device_or_raise(self) -> Device:
        if self.device is None or not self.device.connected:
            raise TransportError("尚未连接设备")
        return self.device


def fmt_log(direction: str, data: bytes) -> str:
    stamp = time.strftime("%H:%M:%S")
    return f"[{stamp}] {direction:<3} {hexdump(data)}"
