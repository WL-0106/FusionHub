# -*- coding: utf-8 -*-
"""从站模拟器的传输服务端（TCP / 串口），供 tools/simulator.py 与自测脚本复用。"""

import socket
import threading

from .slave import RUSlave


class TcpSlaveServer:
    """把 RUSlave 挂到 TCP 端口上，裸 RTU 帧透传。"""

    def __init__(self, slave: RUSlave, host="127.0.0.1", port=7502, verbose=False):
        self.slave = slave
        self.host = host
        self.port = int(port)
        self.verbose = verbose
        self._srv = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def bound_port(self):
        if self._srv is not None:
            return self._srv.getsockname()[1]
        return self.port

    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.host, self.port))
        self._srv.listen(4)
        self._srv.settimeout(0.3)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self.bound_port

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, addr = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client, args=(conn, addr), daemon=True).start()

    def _client(self, conn, addr):
        conn.settimeout(0.2)
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = conn.recv(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf.extend(chunk)
            while len(buf) >= 4:
                # 找出一个完整 RTU 帧：按功能码推算长度
                frame_len = self._frame_length(bytes(buf))
                if frame_len is None or len(buf) < frame_len:
                    break
                frame = bytes(buf[:frame_len])
                del buf[:frame_len]
                resp = self.slave.handle_frame(frame)
                if resp:
                    try:
                        conn.sendall(resp)
                    except OSError:
                        return
        try:
            conn.close()
        except OSError:
            pass

    @staticmethod
    def _frame_length(buf: bytes):
        """按功能码推算 RTU 帧长度，返回 None 表示不确定。"""
        fc = buf[1]
        base = 1 + 1  # ID + FC
        if fc in (0x01, 0x02, 0x03, 0x04):
            if len(buf) < 2:
                return None
            return base + 4 + 2          # addr + count + crc
        if fc in (0x05, 0x06):
            return base + 4 + 2
        if fc in (0x0F, 0x10):
            if len(buf) < 7:
                return None
            bc = buf[6]
            return base + 5 + bc + 2
        if fc & 0x80:
            return base + 1 + 2
        return len(buf)  # 未知功能码：整包交给从站自行判定

    def stop(self):
        self._stop.set()
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
            self._srv = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None


class SerialSlaveServer:
    """把 RUSlave 挂到串口上（需要成对虚拟串口，如 com0com）。"""

    def __init__(self, slave: RUSlave, port, baudrate=9600, verbose=False):
        self.slave = slave
        self.port = port
        self.baudrate = baudrate
        self.verbose = verbose
        self._ser = None
        self._stop = threading.Event()

    def start(self):
        import serial
        self._ser = serial.Serial(self.port, self.baudrate, timeout=0.05)
        threading.Thread(target=self._serve, daemon=True).start()
        return self.port

    def _serve(self):
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(256)
            except Exception:
                break
            if not chunk:
                continue
            buf.extend(chunk)
            while len(buf) >= 4:
                frame_len = TcpSlaveServer._frame_length(bytes(buf))
                if frame_len is None or len(buf) < frame_len:
                    break
                frame = bytes(buf[:frame_len])
                del buf[:frame_len]
                resp = self.slave.handle_frame(frame)
                if resp:
                    self._ser.write(resp)

    def stop(self):
        self._stop.set()
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None
