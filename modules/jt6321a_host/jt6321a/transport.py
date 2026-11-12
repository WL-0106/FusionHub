# -*- coding: utf-8 -*-
"""传输层：串口 + 内存模拟器。

统一接口：
    open() / close() / is_open
    write(cmd)          # 只发不收（设置类命令无应答）
    query(cmd, timeout) # 发一帧，读到换行为止，返回去掉换行的字符串

注意：Windows 上不要调 serial.Serial.flush()（USB 转换器异常时会无限期阻塞），
      发送前用 reset_input_buffer() 清掉上一帧残留即可。
"""
from __future__ import annotations

import time

from .protocol import TERM


class TransportError(Exception):
    pass


class SerialTransport:
    def __init__(self, port, baudrate=9600, parity="N", bytesize=8,
                 stopbits=1, timeout=0.5, rts=False):
        self.port = port
        self.baudrate = int(baudrate)
        self.parity = parity
        self.bytesize = int(bytesize)
        self.stopbits = float(stopbits)
        self.timeout = float(timeout)
        self.rts = bool(rts)
        self._ser = None

    def open(self):
        import serial  # pyserial
        pmap = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
                "O": serial.PARITY_ODD, "M": serial.PARITY_MARK,
                "S": serial.PARITY_SPACE}
        self._ser = serial.Serial(
            port=self.port, baudrate=self.baudrate,
            bytesize=self.bytesize, parity=pmap.get(self.parity, serial.PARITY_NONE),
            stopbits=self.stopbits, timeout=self.timeout,
            write_timeout=1.0, rtscts=False, dsrdtr=False,
        )
        try:
            self._ser.setRTS(self.rts)
            self._ser.setDTR(False)
        except Exception:
            pass
        return self

    @property
    def is_open(self) -> bool:
        return bool(self._ser is not None and self._ser.is_open)

    def close(self):
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass
        self._ser = None

    def write(self, cmd: str):
        if not self.is_open:
            raise TransportError("串口未打开")
        data = (cmd + TERM).encode("ascii", "ignore")
        self._ser.reset_input_buffer()
        self._ser.write(data)

    def query(self, cmd: str, timeout=None) -> str:
        """写一帧并读到换行为止。SCPI 可能无应答，超时返回空串而不是抛错。"""
        if not self.is_open:
            raise TransportError("串口未打开")
        tmo = self.timeout if timeout is None else float(timeout)
        self.write(cmd)
        buf = bytearray()
        deadline = time.time() + tmo
        while time.time() < deadline:
            n = self._ser.in_waiting
            if n:
                buf += self._ser.read(n)
                if b"\n" in buf or b"\r" in buf:
                    break
            else:
                time.sleep(0.02)
        text = bytes(buf).decode("ascii", "ignore")
        for ch in ("\r", "\n"):
            text = text.replace(ch, "")
        return text.strip()


class SimTransport:
    """内存模拟器：把命令直接交给一个 SimLoad 对象，不需要任何硬件。"""

    def __init__(self, sim=None):
        from .simulator import SimLoad
        self.sim = sim if sim is not None else SimLoad()
        self._open = False
        self.trace = []          # 记录所有下发帧，供自测断言

    def open(self):
        self._open = True
        return self

    @property
    def is_open(self) -> bool:
        return self._open

    def close(self):
        self._open = False

    def write(self, cmd: str):
        if not self._open:
            raise TransportError("模拟器未打开")
        self.trace.append(cmd)
        self.sim.handle(cmd)

    def query(self, cmd: str, timeout=None) -> str:
        if not self._open:
            raise TransportError("模拟器未打开")
        self.trace.append(cmd)
        return self.sim.handle(cmd)


def list_ports():
    """列出可用串口；pyserial 不可用时返回空表。"""
    try:
        from serial.tools import list_ports as lp
        return [p.device for p in lp.comports()]
    except Exception:
        return []
