# -*- coding: utf-8 -*-
"""中创智合采集卡 模拟从站。

真实维护保持寄存器，支持 Modbus RTU（TCP 透传）与 Modbus TCP（MBAP）。
用于无设备时把上位机跑通，也用于自测端到端。

用法：
  python simulator.py --series temperature --port 5020
  python simulator.py --series voltage --port 5020
"""

import argparse
import socket
import struct
import threading

from . import series as S  # noqa
from .modbus import crc16_bytes, parse_rtu_response  # noqa


class SimSlave:
    """一台模拟采集卡。真实维护寄存器，支持功能码 03/04/06/10。"""

    def __init__(self, series_key="temperature", slave=1):
        self.slave = slave
        self.series = S.SERIES[series_key]
        self.regs = [0] * 0x1000  # 保持寄存器空间

        # 填充数据寄存器（模拟一个稳定读数）
        n = self.series.channel_count
        if self.series.scale_mode == "div10":
            # 温度：25.0℃ = 250，26.3℃ = 263 ...
            base = 250
            for i in range(n):
                self.regs[self.series.data_start + i] = (base + i * 13) & 0xFFFF
        else:
            # 电压/电流：额定值 10000（对应满量程）
            for i in range(n):
                self.regs[self.series.data_start + i] = 10000

        # 配置寄存器默认值
        if self.series.addr_reg is not None:
            self.regs[self.series.addr_reg] = slave
        if self.series.baud_reg is not None:
            self.regs[self.series.baud_reg] = 0x01  # 9600
        if self.series.parity_reg is not None:
            self.regs[self.series.parity_reg] = 0

    def handle_rtu(self, frame):
        """处理一帧 RTU，返回应答帧（bytes）。"""
        body, crc = frame[:-2], frame[-2:]
        if crc16_bytes(body) != crc:
            return None  # CRC 错，不响应
        slave, fc = body[0], body[1]
        if slave != self.slave:
            return None

        if fc == 0x03 or fc == 0x04:
            start, count = struct.unpack(">HH", body[2:6])
            if count <= 0 or count > 125 or start + count > len(self.regs):
                return self._err(slave, fc, 0x02)
            data = b""
            for i in range(count):
                data += struct.pack(">H", self.regs[start + i] & 0xFFFF)
            resp = bytes((slave, fc, len(data))) + data
            return resp + crc16_bytes(resp)

        if fc == 0x06:
            addr, value = struct.unpack(">HH", body[2:6])
            if addr >= len(self.regs):
                return self._err(slave, fc, 0x02)
            self.regs[addr] = value
            resp = bytes((slave, fc)) + struct.pack(">HH", addr, value)
            return resp + crc16_bytes(resp)

        if fc == 0x10:
            start, count = struct.unpack(">HH", body[2:6])
            bytecount = body[6]
            if count <= 0 or count > 123 or bytecount != count * 2:
                return self._err(slave, fc, 0x03)
            if start + count > len(self.regs):
                return self._err(slave, fc, 0x02)
            for i in range(count):
                self.regs[start + i] = struct.unpack(
                    ">H", body[7 + i * 2:9 + i * 2])[0]
            resp = bytes((slave, fc)) + struct.pack(">HH", start, count)
            return resp + crc16_bytes(resp)

        return self._err(slave, fc, 0x01)

    @staticmethod
    def _err(slave, fc, code):
        resp = bytes((slave, fc | 0x80, code))
        return resp + crc16_bytes(resp)

    def handle_mbap(self, frame):
        """处理一帧 MBAP，返回应答 MBAP 帧。"""
        if len(frame) < 8:
            return None
        tid, proto, length = struct.unpack(">HHH", frame[:6])
        unit = frame[6]
        pdu = frame[7:6 + length]
        if unit != self.slave:
            return None
        # 转成 RTU 处理（补地址和 CRC 占位）
        rtu = bytes((unit,)) + pdu
        rtu += b"\x00\x00"  # CRC 占位（会被重新算）
        resp_rtu = self.handle_rtu_with_placeholder(rtu)
        if resp_rtu is None:
            return None
        # 去地址去 CRC，得 PDU
        rpdu = resp_rtu[1:-2]
        return struct.pack(">HHH", tid, 0, 1 + len(rpdu)) + bytes((unit,)) + rpdu

    def handle_rtu_with_placeholder(self, frame):
        # 重算 CRC
        body = frame[:-2]
        return self.handle_rtu(body + crc16_bytes(body))


def serve_tcp(host, port, slave):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Windows 下独占端口
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    srv.bind((host, port))
    srv.listen(5)
    print("模拟从站启动：%s:%d 从站号 %d（Ctrl+C 退出）" % (host, port, slave))

    def handle_conn(conn, addr, mode):
        try:
            conn.settimeout(10)
            buf = bytearray()
            while True:
                try:
                    chunk = conn.recv(512)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                # 尝试解帧
                while True:
                    frame, rest = try_unpack(buf, mode)
                    if frame is None:
                        break
                    buf = rest
                    if mode == "tcp":
                        resp = slave.handle_mbap(frame)
                    else:
                        resp = slave.handle_rtu(frame)
                    if resp:
                        conn.sendall(resp)
        except Exception as e:
            print("连接 %s 异常：%s" % (addr, e))
        finally:
            conn.close()

    while True:
        conn, addr = srv.accept()
        # 简单判定：MBAP 首个字节是事务ID高字节，先按 RTU 处理，收到后识别
        threading.Thread(target=handle_conn,
                         args=(conn, addr, "rtu"), daemon=True).start()


def try_unpack(buf, mode):
    """从缓冲里尝试解出完整帧。返回 (frame, rest) 或 (None, buf)。"""
    if mode == "tcp":
        if len(buf) < 6:
            return None, bytes(buf)
        length = struct.unpack(">H", buf[4:6])[0]
        total = 6 + length
        if len(buf) < total:
            return None, bytes(buf)
        return bytes(buf[:total]), bytes(buf[total:])
    else:
        # RTU：至少 8 字节（最小应答），先按功能码推长度
        if len(buf) < 8:
            return None, bytes(buf)
        # 用 CRC 校验确认帧长：从最小长度开始试
        for l in range(8, len(buf) + 1):
            cand = bytes(buf[:l])
            if crc16_bytes(cand[:-2]) == cand[-2:]:
                return cand, bytes(buf[l:])
        # 无合法帧，继续等
        return None, bytes(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="temperature",
                    choices=["temperature", "voltage", "current", "mixed"])
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--slave", type=int, default=1)
    args = ap.parse_args()

    slave = SimSlave(args.series, args.slave)
    serve_tcp(args.host, args.port, slave)


if __name__ == "__main__":
    main()
