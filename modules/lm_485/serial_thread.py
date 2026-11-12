"""
串口通信线程管理 - RS485 Modbus RTU 通信

使用QThread在后台处理串口收发, 避免阻塞UI主线程。
支持: 请求-响应模式、广播模式、自动轮询、RS485方向控制(RTS)。
"""

import time
import threading
from collections import deque

from PyQt5.QtCore import QThread, pyqtSignal, QTimer
import serial
import serial.tools.list_ports

from . import modbus_rtu


class SerialWorker(QThread):
    """串口通信工作线程"""

    response_received = pyqtSignal(int, bytes, bytes)
    broadcast_sent = pyqtSignal(bytes)
    timeout_occurred = pyqtSignal(int, bytes)
    log_message = pyqtSignal(str, str)
    connection_changed = pyqtSignal(bool, str)
    scan_result = pyqtSignal(int, bool)
    scan_progress = pyqtSignal(int, int, int)  # (current, total, found)
    comm_error = pyqtSignal(str)  # 通信持续错误信号

    MAX_CONSECUTIVE_ERRORS = 5  # 连续错误上限, 超过自动断开

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self._running = False
        self._connected = False
        self._request_queue = deque()
        self._queue_lock = threading.Lock()
        self._response_timeout = 0.3  # 响应超时 300ms
        self._inter_frame_delay = 0.005  # 帧间延时 5ms (9600bps下3.5字符时间约4ms)
        self._rts_control = False  # RS485 RTS方向控制
        self._rts_polarity = True  # True=高电平发送, False=低电平发送
        self._scan_mode = False  # 扫描模式(使用更短的超时)
        self._baudrate = 9600
        self._consecutive_errors = 0  # 连续错误计数

    def connect_port(self, port_name: str, baudrate: int = 9600,
                     rts_control: bool = False, rts_polarity: bool = True) -> bool:
        """连接串口"""
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
            self._baudrate = baudrate
            self._rts_control = rts_control
            self._rts_polarity = rts_polarity
            self._consecutive_errors = 0
            # Modbus 3.5字符帧间延时: 3.5 * 11 bits / baud, 最小2ms
            self._inter_frame_delay = max(0.002, 3.5 * 11.0 / baudrate)
            self.serial_port = serial.Serial(
                port=port_name,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
                write_timeout=1.0,
            )
            self.serial_port.rtscts = False
            self.serial_port.dsrdtr = False
            if self._rts_control:
                self.serial_port.rts = not self._rts_polarity
            self._connected = True
            self.connection_changed.emit(True, f"已连接 {port_name}@{baudrate}bps")
            self.log_message.emit("INFO", f"串口连接成功: {port_name}, 波特率: {baudrate}")
            if self._rts_control:
                self.log_message.emit("INFO", "RS485 RTS方向控制已启用")
            return True
        except Exception as e:
            self._connected = False
            self.connection_changed.emit(False, f"连接失败: {e}")
            self.log_message.emit("ERROR", f"串口连接失败: {e}")
            return False

    def disconnect_port(self):
        """断开串口"""
        self.clear_queue()
        if self.serial_port:
            port_name = self.serial_port.portstr
            try:
                if self.serial_port.is_open:
                    self.serial_port.close()
            except Exception as e:
                # USB拔出/句柄失效时close()可能抛异常, 不阻断状态复位
                self.log_message.emit("ERROR", f"串口断开异常(已忽略): {e}")
            self._connected = False
            self.connection_changed.emit(False, "已断开")
            self.log_message.emit("INFO", f"串口已断开: {port_name}")

    def is_connected(self) -> bool:
        return self._connected and self.serial_port and self.serial_port.is_open

    def set_rts_control(self, enabled: bool):
        self._rts_control = enabled
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.rtscts = False
            if not enabled:
                self.serial_port.rts = False

    def clear_queue(self):
        """清空请求队列"""
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
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
        except Exception:
            pass
        self._connected = False
        self.comm_error.emit(err_msg)
        self.connection_changed.emit(False, "通信错误, 已自动断开")

    def _send_and_receive(self, addr: int, frame: bytes, desc: str):
        """发送请求并接收响应"""
        # 帧间静默: 确保总线空闲
        time.sleep(self._inter_frame_delay)

        # 清空输入缓冲区中的残留数据
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.reset_input_buffer()
            except Exception:
                self._consecutive_errors += 1
                return

        # RTS控制: 启用发送方向
        if self._rts_control and self.serial_port:
            self.serial_port.rts = self._rts_polarity
            time.sleep(0.001)

        # 发送
        try:
            self.serial_port.write(frame)
            self.serial_port.flush()
            self._consecutive_errors = 0  # 发送成功, 重置错误计数
            self.log_message.emit("TX", modbus_rtu.format_bytes(frame))
            if desc:
                self.log_message.emit("INFO", f"发送: {desc} (地址 0x{addr:02X})")
        except Exception as e:
            self._consecutive_errors += 1
            # 首次错误完整记录, 后续只计数避免日志洪泛
            if self._consecutive_errors <= 2:
                self.log_message.emit("ERROR", f"发送失败: {e}")
            if self._rts_control and self.serial_port:
                try:
                    self.serial_port.rts = not self._rts_polarity
                except Exception:
                    pass
            return

        # RTS控制: 等待发送完成后切换到接收方向
        if self._rts_control and self.serial_port:
            # 等待最后一个字节完全发送到线上
            time.sleep(len(frame) * 11.0 / self._baudrate + 0.002)
            self.serial_port.rts = not self._rts_polarity

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
        """读取从机响应 - 等到超时或检测到帧结束(帧间静默)"""
        deadline = time.time() + timeout
        response = bytearray()
        last_byte_time = 0
        inter_byte_timeout = 0.015  # 帧间静默15ms认为帧结束

        try:
            while time.time() < deadline:
                n = self.serial_port.in_waiting
                if n > 0:
                    chunk = self.serial_port.read(n)
                    response.extend(chunk)
                    last_byte_time = time.time()
                    continue
                if response and last_byte_time and (time.time() - last_byte_time) > inter_byte_timeout:
                    break
                time.sleep(0.002)
        except Exception:
            # 串口异常(如USB拔出), 返回空, 由上层处理错误计数
            return b""

        return bytes(response) if len(response) >= 5 else b""

    def set_scan_mode(self, enabled: bool):
        self._scan_mode = enabled

    def stop(self):
        """停止线程 - 非阻塞方式, 避免UI卡死"""
        self._running = False
        self.clear_queue()
        # 不使用wait()阻塞UI线程, 线程会在下一次循环检查_running时退出
        # 最多等待500ms, 超时后强制返回(线程会在后台自行退出)
        self.wait(500)


class PollingManager:
    """自动轮询管理器 - 周期性读取所有模块状态"""

    def __init__(self, worker: SerialWorker):
        self.worker = worker
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll_cycle)
        self._interval = 500
        self._online_set = set()
        self._poll_index = 0
        self._active = False

    def start(self, interval_ms: int = 500):
        self._interval = interval_ms
        self._timer.start(interval_ms)
        self._active = True

    def stop(self):
        self._timer.stop()
        self._active = False

    def is_active(self) -> bool:
        return self._active

    def set_interval(self, interval_ms: int):
        self._interval = interval_ms
        if self._active:
            self._timer.start(interval_ms)

    def set_online_set(self, online: set):
        self._online_set = online

    def _poll_cycle(self):
        if not self.worker.is_connected():
            return

        online_list = sorted(self._online_set)
        if not online_list:
            return

        if self._poll_index >= len(online_list):
            self._poll_index = 0

        addr = online_list[self._poll_index]
        self._poll_index += 1

        # 批量读取: 状态+电压+电流+温度, 一条请求读4个寄存器
        self.worker.enqueue_request(addr, modbus_rtu.build_read_all(addr), "轮询-全量读取")


class ScanManager:
    """扫描在线模块管理器 - 逐个地址探测"""

    def __init__(self, worker: SerialWorker):
        self.worker = worker
        self._scanning = False
        self._total = 0
        self._current = 0
        self._found = 0
        worker.scan_result.connect(self._on_scan_result)

    def _on_scan_result(self, addr: int, found: bool):
        if not self._scanning:
            return
        if found:
            self._found += 1
        self.worker.scan_progress.emit(self._current, self._total, self._found)

    def start_scan(self, start_addr: int = 1, end_addr: int = 247):
        """开始扫描指定范围内的地址"""
        if self._scanning:
            return
        self._scanning = True
        self._total = end_addr - start_addr + 1
        self._current = 0
        self._found = 0
        self.worker.set_scan_mode(True)
        self.worker.clear_queue()
        threading.Thread(
            target=self._scan_thread,
            args=(start_addr, end_addr),
            daemon=True,
        ).start()

    def _scan_thread(self, start_addr: int, end_addr: int):
        """逐个地址发送扫描请求"""
        for addr in range(start_addr, end_addr + 1):
            if not self._scanning or not self.worker.is_connected():
                break

            self._current = addr - start_addr + 1
            self.worker.scan_progress.emit(self._current, self._total, self._found)

            frame = modbus_rtu.build_read_status(addr)
            self.worker.enqueue_request(addr, frame, f"扫描 0x{addr:02X}")

            # 等待这个地址处理完成, 再发下一个
            while self._scanning and self.worker.is_connected():
                with self.worker._queue_lock:
                    queue_len = len(self.worker._request_queue)
                if queue_len == 0:
                    break
                time.sleep(0.01)

        self._scanning = False
        self.worker.set_scan_mode(False)
        self.worker.scan_progress.emit(self._total, self._total, self._found)

    def is_scanning(self) -> bool:
        return self._scanning

    def stop_scan(self):
        self._scanning = False
        self.worker.set_scan_mode(False)
        self.worker.clear_queue()

    def increment_found(self):
        self._found += 1


def list_available_ports() -> list:
    ports = serial.tools.list_ports.comports()
    return [(p.device, p.description) for p in ports]
