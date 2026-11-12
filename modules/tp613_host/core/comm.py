# -*- coding: utf-8 -*-
"""TP613 通讯工作线程（对应原 CommThread）：命令队列 + 轮询 + 日志信号。

单线程串行收发（Modbus 半双工），命令与轮询互斥；UI 只消费 Qt 信号，
保持界面与协议解耦。
"""
from __future__ import annotations

import datetime
import queue
import threading

from PyQt5.QtCore import QThread, pyqtSignal

from .protocol import (BASIC_PARAMS, ENERGY_PARAMS, EXCEPTION_TEXT,
                       POLL_BLOCK_BASIC, POLL_BLOCK_ENERGY, ModbusRTU,
                       frame_text)


class CommThread(QThread):
    """设备通讯线程。命令：custom / read_param / write_param；可选周期轮询。"""

    sig_tx = pyqtSignal(str)          # 原始帧发送日志
    sig_rx = pyqtSignal(str)          # 原始帧接收日志
    sig_info = pyqtSignal(str)
    sig_error = pyqtSignal(str)
    sig_data = pyqtSignal(dict)       # 采集数据 {key: value}
    sig_comm_ok = pyqtSignal()
    sig_comm_fail = pyqtSignal(str)
    sig_custom_resp = pyqtSignal(bytes)
    sig_param_result = pyqtSignal(str, object, bool)   # name, value, ok

    def __init__(self, parent=None):
        super().__init__(parent)
        self._conn = None
        self._slave = 1
        self._poll_interval = 1.0
        self._polling = False
        self._running = False
        self._q = queue.Queue()
        self._lock = threading.Lock()

    # ---------------------------------------------------------- 配置
    def set_connection(self, conn):
        self._conn = conn

    def set_slave_addr(self, addr: int):
        self._slave = int(addr)

    def set_poll_interval(self, interval: float):
        self._poll_interval = max(0.05, float(interval))

    def start_polling(self):
        self._polling = True

    def stop_polling(self):
        self._polling = False

    # ---------------------------------------------------------- 命令入队
    def queue_custom(self, data: bytes, append_crc: bool):
        self._q.put(('custom', data, append_crc))

    def queue_read_param(self, name: str, addr: int, count: int):
        self._q.put(('read_param', name, addr, count))

    def queue_write_param(self, name: str, addr: int, value,
                          use_func10: bool, as_float: bool):
        self._q.put(('write_param', name, addr, value, use_func10, as_float))

    def stop(self):
        self._running = False
        self._polling = False
        self.wait(3000)

    # ---------------------------------------------------------- 线程体
    def run(self):
        self._running = True
        last_poll = 0.0
        while self._running:
            try:
                cmd = self._q.get(timeout=0.05)
            except queue.Empty:
                cmd = None
            if cmd is not None:
                try:
                    self._process_cmd(cmd)
                except Exception as e:
                    self.sig_error.emit(f'命令执行异常: {e}')
                continue
            if self._polling and self._conn is not None:
                now = time_now()
                if now - last_poll >= self._poll_interval:
                    last_poll = now
                    try:
                        self._poll_data()
                    except Exception as e:
                        self.sig_comm_fail.emit(str(e))

    def _send_recv(self, frame: bytes, timeout: float = 1.5) -> bytes:
        self.sig_tx.emit(f'[{_ts()}] TX: {frame_text(frame)}')
        self._conn.send(frame)
        resp = self._conn.receive(timeout)
        if not resp:
            self.sig_comm_fail.emit('接收超时')
            raise TimeoutError('接收超时')
        self.sig_rx.emit(f'[{_ts()}] RX: {frame_text(resp)}')
        self.sig_comm_ok.emit()
        return resp

    def _poll_data(self):
        """轮询电量块：0x0064 起 60 寄存器（30 FLOAT）+ 0x00A0 起 24 寄存器（12 FLOAT）。"""
        data = {}
        for block, params in ((POLL_BLOCK_BASIC, BASIC_PARAMS),
                              (POLL_BLOCK_ENERGY, ENERGY_PARAMS)):
            start, count = block
            frame = ModbusRTU.build_read(self._slave, start, count)
            try:
                resp = self._send_recv(frame)
                regs = ModbusRTU.parse_read_response(resp)
            except ValueError as e:
                self.sig_error.emit(f'解析电参数失败: {e}')
                raise
            for key, _n, _u, _f, addr in params:
                off = (addr - start) // 2
                if 0 <= off * 2 + 1 < len(regs):
                    data[key] = ModbusRTU.regs_to_float(
                        [regs[off * 2], regs[off * 2 + 1]])
        self.sig_data.emit(data)

    def _process_cmd(self, cmd):
        kind = cmd[0]
        if kind == 'custom':
            self._do_custom(cmd[1], cmd[2])
        elif kind == 'read_param':
            self._do_read_param(cmd[1], cmd[2], cmd[3])
        elif kind == 'write_param':
            self._do_write_param(*cmd[1:])

    def _do_custom(self, data: bytes, append_crc: bool):
        frame = data + (crc_bytes(data) if append_crc else b'')
        try:
            resp = self._send_recv(frame, 2.0)
            self.sig_custom_resp.emit(resp)
        except Exception:
            self.sig_custom_resp.emit(b'')

    def _do_read_param(self, name: str, addr: int, count: int):
        frame = ModbusRTU.build_read(self._slave, addr, count)
        try:
            resp = self._send_recv(frame)
            regs = ModbusRTU.parse_read_response(resp)
        except Exception as e:
            self.sig_error.emit(f'读取参数失败({name}): {e}')
            self.sig_param_result.emit(name, None, False)
            return
        if count >= 2:
            value = ModbusRTU.regs_to_float([regs[0], regs[1]])
        else:
            value = regs[0] if regs else 0
        self.sig_param_result.emit(name, value, True)

    def _do_write_param(self, name: str, addr: int, value,
                        use_func10: bool, as_float: bool):
        if as_float:
            regs = list(ModbusRTU.float_to_regs(float(value)))
        else:
            regs = [int(value) & 0xFFFF]
        if use_func10 or len(regs) > 1:
            frame = ModbusRTU.build_write_multi(self._slave, addr, regs)
        else:
            frame = ModbusRTU.build_write_single(self._slave, addr, regs[0])
        try:
            resp = self._send_recv(frame)
            ok, code = ModbusRTU.parse_write_response(resp)
        except Exception as e:
            self.sig_error.emit(f'写入参数失败({name}): {e}')
            self.sig_param_result.emit(name, None, False)
            return
        if ok:
            self.sig_param_result.emit(name, value, True)
        else:
            text = EXCEPTION_TEXT.get(code, f'未知错误码0x{code:02X}')
            self.sig_error.emit(f'写入参数失败({name}): 异常码0x{code:02X} ({text})')
            self.sig_param_result.emit(name, None, False)


def crc_bytes(data: bytes) -> bytes:
    from .protocol import crc16_modbus
    return crc16_modbus(data).to_bytes(2, 'little')


def time_now() -> float:
    import time
    return time.time()


def _ts() -> str:
    now = datetime.datetime.now()
    return f'{now:%H:%M:%S}.{now.microsecond // 1000:03d}'
