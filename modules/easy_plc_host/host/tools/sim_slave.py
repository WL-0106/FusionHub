#!/usr/bin/env python3
"""本地 Modbus TCP 从站仿真器 —— 用于无 PLC 时自测上位机.

用法:
    python tools/sim_slave.py            # 监听 0.0.0.0:502（需管理员）
    python tools/sim_slave.py 15020      # 指定端口

仿真内容:
    - 线圈 63488 起 32 点 = X（自动缓慢变化，便于观察灯）
    - 线圈 64512 起 32 点 = Y（可写）
    - 线圈 0 起 64 点 = M（可写）
    - 保持寄存器 0 起 64 个 = D（可写，D0 每秒自增）
"""
from __future__ import annotations

import socket
import struct
import sys
import threading
import time

X_BASE = 0xF800
Y_BASE = 0xFC00
M_BASE = 0x0000

coils = [False] * 70000
regs = [0] * 70000


def handle(conn: socket.socket) -> None:
    buf = b""
    while True:
        try:
            data = conn.recv(512)
        except OSError:
            break
        if not data:
            break
        buf += data
        while len(buf) >= 7:
            tid, pid, length, unit = struct.unpack(">HHHB", buf[:7])
            if len(buf) < 6 + length:
                break
            pdu = buf[7 : 6 + length]
            buf = buf[6 + length :]
            fc = pdu[0]
            try:
                if fc == 0x03:
                    addr = (pdu[1] << 8) | pdu[2]
                    cnt = (pdu[3] << 8) | pdu[4]
                    body = b"".join(struct.pack(">H", regs[addr + i] & 0xFFFF) for i in range(cnt))
                    resp_pdu = bytes([0x03, len(body)]) + body
                elif fc == 0x01:
                    addr = (pdu[1] << 8) | pdu[2]
                    cnt = (pdu[3] << 8) | pdu[4]
                    packed = bytearray((cnt + 7) // 8)
                    for i in range(cnt):
                        if coils[addr + i]:
                            packed[i // 8] |= 1 << (i % 8)
                    resp_pdu = bytes([0x01, len(packed)]) + bytes(packed)
                elif fc == 0x06:
                    addr = (pdu[1] << 8) | pdu[2]
                    val = (pdu[3] << 8) | pdu[4]
                    regs[addr] = val
                    resp_pdu = pdu[:5]
                elif fc == 0x05:
                    addr = (pdu[1] << 8) | pdu[2]
                    coils[addr] = ((pdu[3] << 8) | pdu[4]) == 0xFF00
                    resp_pdu = pdu[:5]
                elif fc == 0x10:
                    addr = (pdu[1] << 8) | pdu[2]
                    cnt = (pdu[3] << 8) | pdu[4]
                    bc = pdu[5]
                    body = pdu[6 : 6 + bc]
                    for i in range(cnt):
                        regs[addr + i] = (body[i * 2] << 8) | body[i * 2 + 1]
                    resp_pdu = bytes([0x10, (addr >> 8) & 0xFF, addr & 0xFF, (cnt >> 8) & 0xFF, cnt & 0xFF])
                elif fc == 0x0F:
                    addr = (pdu[1] << 8) | pdu[2]
                    cnt = (pdu[3] << 8) | pdu[4]
                    bc = pdu[5]
                    body = pdu[6 : 6 + bc]
                    for i in range(cnt):
                        coils[addr + i] = bool((body[i // 8] >> (i % 8)) & 1)
                    resp_pdu = bytes([0x0F, (addr >> 8) & 0xFF, addr & 0xFF, (cnt >> 8) & 0xFF, cnt & 0xFF])
                else:
                    resp_pdu = bytes([fc | 0x80, 0x01])
            except Exception:
                resp_pdu = bytes([fc | 0x80, 0x03])
            conn.sendall(struct.pack(">HHHB", tid, 0, 1 + len(resp_pdu), unit) + resp_pdu)
    conn.close()


def animate() -> None:
    n = 0
    while True:
        # X 点轮流点亮
        for i in range(32):
            coils[X_BASE + i] = (n % 32) == i
        regs[0] = n & 0xFFFF
        n += 1
        time.sleep(0.25)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 502
    threading.Thread(target=animate, daemon=True).start()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("0.0.0.0", port))
    except PermissionError:
        print(f"端口 {port} 无权限，请改用: python tools/sim_slave.py 15020")
        return
    srv.listen(5)
    print(f"[仿真从站] 监听 0.0.0.0:{port}  —  X0 起 32 点自闪, D0 自增")
    print("上位机连接: 模式=TCP, IP=127.0.0.1, 端口=%d, 站号=1" % port)
    while True:
        conn, addr = srv.accept()
        print(f"[仿真从站] 客户端接入 {addr}")
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
