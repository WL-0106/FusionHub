# -*- coding: utf-8 -*-
"""
交流回馈式负载 **模拟从站** —— 没有真机也能把上位机跑通。

特性
    * 真实维护 16 位寄存器组（32 位量拆两个字存，不是假数据）
    * 支持 RTU-over-TCP（默认，裸 RTU 帧）与标准 Modbus TCP（--mbap）
    * 按协议实现了 0x03 / 0x06 / 0x10 三个功能码
    * 会"真的在输出"：置位输出控制后，按设定功率/电流算出各通道的电压电流功率，
      并带回状态位（运行 / 操作模式 / 控制模式 / 故障）

用法
    python simulator.py                     # 监听 127.0.0.1:7000，从站号 1
    python simulator.py --port 502 --mbap   # 标准 Modbus TCP
    python simulator.py --unit 3 --noise
"""

from __future__ import annotations

import argparse
import random
import socket
import struct
import threading
import time
from typing import Dict, Optional

from . import modbus_rtu as mb
from . import registers as rg

NOMINAL_VOLTAGE = 220.0     # 模拟的相电压 V


class SlaveSimulator:
    def __init__(self, unit: int = 1, mbap: bool = False,
                 host: str = "127.0.0.1", port: int = 7000,
                 noise: bool = False):
        self.unit = unit
        self.mbap = mbap
        self.host = host
        self.port = port
        self.noise = noise
        self.regs: Dict[int, int] = {}
        self.fault_bits = 0
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._init_regs()

    # ---------------- 寄存器存取 ----------------

    def _init_regs(self) -> None:
        self.regs = {}
        self.regs[rg.ADDR_VERSION] = 104                 # V1.4
        self.setu32(rg.ADDR_SERIAL, 20241030)            # 序列号
        self.regs[rg.ADDR_MODE_OP] = 0
        self.regs[rg.ADDR_MODE_CTRL] = 0
        self.regs[rg.ADDR_OUTPUT_CTRL] = 0
        for ch in range(1, rg.CHANNEL_COUNT + 1):
            self.setu32(rg.ch_power_addr(ch), 0)
        for ch in rg.PHASE_CHANNELS:
            self.setu32(rg.phase_i_set_addr(ch), 0)
        self.setu32(rg.ADDR_POWER_TOTAL, 0)
        self.setu32(rg.ADDR_CURRENT_TOTAL, 0)

    def get(self, addr: int, default: int = 0) -> int:
        return self.regs.get(addr, default) & 0xFFFF

    def set(self, addr: int, value: int) -> None:
        self.regs[addr] = value & 0xFFFF

    def getu32(self, addr: int) -> int:
        return ((self.get(addr) & 0xFFFF) << 16) | (self.get(addr + 1) & 0xFFFF)

    def setu32(self, addr: int, value: int) -> None:
        value &= 0xFFFFFFFF
        self.set(addr, (value >> 16) & 0xFFFF)
        self.set(addr + 1, value & 0xFFFF)

    # ---------------- 输出仿真 ----------------

    def _update_output(self) -> None:
        """根据设定值刷新各通道的电压/电流/功率测量寄存器。"""
        running = self.get(rg.ADDR_OUTPUT_CTRL) == 1
        mode_op = self.get(rg.ADDR_MODE_OP) & 0x03
        mode_ctrl = self.get(rg.ADDR_MODE_CTRL) & 0x01
        total_p = self.getu32(rg.ADDR_POWER_TOTAL) * rg.SCALE_POWER

        def nz(x: float) -> float:
            if not self.noise:
                return x
            return x * random.uniform(0.997, 1.003)

        pset = {ch: self.getu32(rg.ch_power_addr(ch)) * rg.SCALE_POWER
                for ch in range(1, rg.CHANNEL_COUNT + 1)}
        iset = {ch: self.getu32(rg.phase_i_set_addr(ch)) * rg.SCALE_CURRENT
                for ch in rg.PHASE_CHANNELS}

        ch_p: Dict[int, float] = {}
        ch_v: Dict[int, float] = {}
        ch_i: Dict[int, float] = {}

        for ch in range(1, rg.CHANNEL_COUNT + 1):
            if not running:
                ch_p[ch] = ch_v[ch] = ch_i[ch] = 0.0
                continue
            if mode_op == 1:                      # 三相独立：各通道用自身设定
                p = pset[ch]
            elif mode_op == 0:                    # 三相统调：总功率平均分给 A/B/C
                p = total_p / 3.0 if ch in rg.PHASE_CHANNELS else 0.0
                if p == 0.0 and ch in rg.PHASE_CHANNELS:
                    p = pset[ch]
            else:                                 # 单相并联：总功率平均分给所有通道
                p = total_p / rg.CHANNEL_COUNT
            if mode_ctrl == 1 and ch in rg.PHASE_CHANNELS:
                v = NOMINAL_VOLTAGE
                i = iset.get(ch, 0.0)
                p = v * i
            else:
                v = NOMINAL_VOLTAGE if p > 0 else 0.0
                i = (p / v) if v else 0.0
            ch_v[ch], ch_i[ch], ch_p[ch] = nz(v), nz(i), nz(p)

        # A/B/C 相
        for idx, ch in enumerate(rg.PHASE_CHANNELS):
            self.setu32(rg.ADDR_V_BASE + 2 * idx, rg.v2raw(ch_v[ch]))
            self.setu32(rg.ADDR_I_BASE + 2 * idx, rg.a2raw(ch_i[ch]))
        # 总功率
        self.setu32(rg.ADDR_P_TOTAL, rg.p2raw(sum(ch_p.values())))
        # 4~12 通道
        for ch in range(4, 13):
            self.setu32(rg.ADDR_CH4_V + 2 * (ch - 4), rg.v2raw(ch_v[ch]))
            self.setu32(rg.ADDR_CH4_I + 2 * (ch - 4), rg.a2raw(ch_i[ch]))
        # 1~12 通道功率
        for ch in range(1, 13):
            self.setu32(rg.ADDR_CH1_P + 2 * (ch - 1), rg.p2raw(ch_p[ch]))
        # 13~15 通道
        for i, ch in enumerate((13, 14, 15)):
            self.setu32(rg.ADDR_CH13_V + 2 * i, rg.v2raw(ch_v[ch]))
            self.setu32(rg.ADDR_CH13_I + 2 * i, rg.a2raw(ch_i[ch]))
            self.setu32(rg.ADDR_CH13_P + 2 * i, rg.p2raw(ch_p[ch]))

        # 状态位
        status = 0
        status |= 1 if running else 0
        status |= (mode_op & 0x03) << rg.ST_OP_MODE_LOW_BIT
        status |= (mode_ctrl & 0x01) << rg.ST_CTRL_MODE_BIT
        status |= (1 if self.fault_bits else 0) << rg.ST_FAULT_BIT
        self.set(rg.ADDR_STATUS_LOW, status & 0xFFFF)
        self.set(rg.ADDR_STATUS_HIGH, (status >> 16) & 0xFFFF)

        # 故障状态 1/2/3
        self.set(rg.ADDR_FAULT_1, (self.fault_bits >> 32) & 0xFFFF)
        self.set(rg.ADDR_FAULT_2, (self.fault_bits >> 16) & 0xFFFF)
        self.set(rg.ADDR_FAULT_3, self.fault_bits & 0xFFFF)

    # ---------------- 协议处理 ----------------

    def _handle_pdu(self, unit: int, pdu: bytes) -> Optional[bytes]:
        """返回 PDU 响应；None 表示不回复（广播）。"""
        func = pdu[0]
        broadcast = (unit == 0)

        if func == 0x03:
            if len(pdu) < 5:
                return bytes((0x83, 0x03))
            start, count = struct.unpack(">HH", pdu[1:5])
            if not 1 <= count <= 125:
                return bytes((0x83, 0x03))
            self._update_output()
            data = b"".join(struct.pack(">H", self.get(start + i)) for i in range(count))
            return bytes((0x03, len(data))) + data

        if func == 0x06:
            if len(pdu) < 5:
                return bytes((0x86, 0x03))
            reg, val = struct.unpack(">HH", pdu[1:5])
            if reg == rg.ADDR_CLEAR_FAULT and val == 1:
                self.fault_bits = 0
                self.set(rg.ADDR_CLEAR_FAULT, 0)     # 手册：清除完成后自动复位为 0
            else:
                self.set(reg, val)
            return None if broadcast else pdu[:5]

        if func == 0x10:
            if len(pdu) < 6:
                return bytes((0x90, 0x03))
            start, count, nbytes = struct.unpack(">HHB", pdu[1:6])
            if nbytes != count * 2 or len(pdu) < 6 + nbytes:
                return bytes((0x90, 0x03))
            vals = struct.unpack(">%dH" % count, pdu[6:6 + nbytes])
            for i, v in enumerate(vals):
                self.set(start + i, v)
            return None if broadcast else pdu[:5]

        return bytes((func | 0x80, 0x01))     # 非法功能码

    def _process(self, data: bytes) -> Optional[bytes]:
        if self.mbap:
            if len(data) < 8:
                return None
            txn, proto, length, unit = struct.unpack(">HHHB", data[:7])
            pdu = data[7:7 + length - 1]
            with self._lock:
                resp_pdu = self._handle_pdu(unit, pdu)
            if resp_pdu is None:
                return None
            return struct.pack(">HHHB", txn, 0, len(resp_pdu) + 1, unit) + resp_pdu

        # 裸 RTU 帧
        if len(data) < 4 or not mb.check_crc(data):
            return None
        unit = data[0]
        pdu = data[1:-2]
        with self._lock:
            resp_pdu = self._handle_pdu(unit, pdu)
        if resp_pdu is None:
            return None
        return mb.append_crc(bytes((unit,)) + resp_pdu)

    # ---------------- 网络 ----------------

    def start(self) -> "SlaveSimulator":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(4)
        self._sock.settimeout(0.3)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        conn.settimeout(0.3)
        buf = bytearray()
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                for frame in self._split_frames(buf):
                    resp = self._process(frame)
                    if resp:
                        conn.sendall(resp)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _split_frames(self, buf: bytearray):
        """从缓冲区里切出完整请求帧。

        RTU：按功能码推算长度（请求帧都很短，长度可算）
        MBAP：按 6 字节头里的 length 字段切
        """
        while True:
            if self.mbap:
                if len(buf) < 6:
                    return
                length = struct.unpack(">H", bytes(buf[4:6]))[0]
                total = 6 + length
                if not 2 <= length <= 260 or len(buf) < total:
                    return
                yield bytes(buf[:total])
                del buf[:total]
                continue

            if len(buf) < 2:
                return
            func = buf[1]
            if func == 0x10:
                if len(buf) < 7:
                    return
                total = 9 + buf[6]
            else:
                total = 8                    # 0x03 / 0x06 请求帧固定 8 字节
            if len(buf) < total:
                return
            yield bytes(buf[:total])
            del buf[:total]

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=1.5)


def main() -> None:
    ap = argparse.ArgumentParser(description="交流回馈式负载模拟从站")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--unit", type=int, default=1, help="从站地址 1~254")
    ap.add_argument("--mbap", action="store_true", help="使用标准 Modbus TCP 的 MBAP 头")
    ap.add_argument("--noise", action="store_true", help="给测量值加轻微抖动，更像真机")
    args = ap.parse_args()

    sim = SlaveSimulator(unit=args.unit, mbap=args.mbap, host=args.host,
                         port=args.port, noise=args.noise).start()
    mode = "Modbus TCP (MBAP)" if args.mbap else "RTU over TCP (裸 RTU 帧)"
    print("=" * 58)
    print(" 交流回馈式负载 模拟从站 已启动")
    print(" 监听      : %s:%d   %s" % (args.host, args.port, mode))
    print(" 从站地址  : %d" % args.unit)
    print(" 上位机里选「网口」，地址填 %s:%d%s" % (args.host, args.port,
                                                  "，并勾选 MBAP" if args.mbap else ""))
    print(" 按 Ctrl+C 退出")
    print("=" * 58)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
        print("已退出。")


if __name__ == "__main__":
    main()
