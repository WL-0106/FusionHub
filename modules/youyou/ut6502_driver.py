"""
宇泰 UT-6502 以太网-CAN 转换器驱动
固定格式模式: 每帧13字节 = 1字节帧信息 + 4字节CAN ID + 8字节数据
帧信息: bit7=FF(1=扩展帧), bit6=RTR(0=数据帧), bit3:0=DLC(数据长度)
"""
import socket
import select
import threading
import time

FRAME_SIZE = 13
EXTENDED_DATA_FRAME_8B = 0x88


def build_ut6502_frame(can_id, data):
    if len(data) < 8:
        data = data + b'\x00' * (8 - len(data))
    elif len(data) > 8:
        data = data[:8]
    frame_info = EXTENDED_DATA_FRAME_8B
    id_bytes = can_id.to_bytes(4, 'big')
    return bytes([frame_info]) + id_bytes + data


def parse_ut6502_frame(frame):
    if len(frame) < FRAME_SIZE:
        return None
    frame_info = frame[0]
    ff = (frame_info >> 7) & 1
    rtr = (frame_info >> 6) & 1
    dlc = frame_info & 0x0F
    can_id = int.from_bytes(frame[1:5], 'big')
    data = frame[5:5 + dlc] if dlc > 0 else b''
    return {
        "extended": bool(ff),
        "rtr": bool(rtr),
        "dlc": dlc,
        "can_id": can_id,
        "data": data,
    }


class UT6502Driver:
    def __init__(self):
        self.sock = None
        self._connected = False
        self._lock = threading.Lock()
        self._recv_buffer = b''

    @property
    def connected(self):
        return self._connected

    def connect(self, ip, port=5001, timeout=3.0):
        if self._connected:
            self.disconnect()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((ip, port))
        self.sock.settimeout(0.2)
        self._connected = True
        self._recv_buffer = b''

    def disconnect(self):
        self._connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def send_can(self, can_id, data):
        if not self._connected or not self.sock:
            return False
        frame = build_ut6502_frame(can_id, data)
        try:
            with self._lock:
                self.sock.sendall(frame)
            return True
        except Exception:
            self._connected = False
            return False

    def recv_can(self, timeout=0.1):
        if not self._connected or not self.sock:
            return None
        frames = []
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                rlist, _, _ = select.select([self.sock], [], [], remaining)
                if not rlist:
                    break
                with self._lock:
                    chunk = self.sock.recv(4096)
                if chunk:
                    self._recv_buffer += chunk
                else:
                    self._connected = False
                    break
            except socket.timeout:
                break
            except Exception:
                self._connected = False
                break
            while len(self._recv_buffer) >= FRAME_SIZE:
                frame_data = self._recv_buffer[:FRAME_SIZE]
                self._recv_buffer = self._recv_buffer[FRAME_SIZE:]
                parsed = parse_ut6502_frame(frame_data)
                if parsed:
                    frames.append(parsed)
        while len(self._recv_buffer) >= FRAME_SIZE:
            frame_data = self._recv_buffer[:FRAME_SIZE]
            self._recv_buffer = self._recv_buffer[FRAME_SIZE:]
            parsed = parse_ut6502_frame(frame_data)
            if parsed:
                frames.append(parsed)
        return frames if frames else None
