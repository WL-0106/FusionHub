# -*- coding: utf-8 -*-
"""
继电器板卡 (12CH) 模拟从站
================================================================
在没有真实板卡时，用它把上位机软件先跑通、验证协议与界面。

严格按说明书实现：
  · 02H 读输入状态（16 路开入，位打包）
  · 03H 读保持寄存器（2000H~2007H，寄存器值为单字节，字节对齐）
  · 05H 写单个线圈（0000H=断开 / FF00H=闭合；0755H 为模块重启）
  · 0FH 写多个线圈（支持广播 0xFF，广播不回复）
  · 线圈 0000H~000BH 对应 继电器1~继电器12

用法：
  python tools/simulator.py                          # 默认 TCP 监听 127.0.0.1:10502，带界面
  python tools/simulator.py --tcp 10502 --host 0.0.0.0
  python tools/simulator.py --serial COM7 --baud 9600   # 需 pyserial
  python tools/simulator.py --serial COM7 --data 7 --parity E --stop 2   # 自定义帧格式
  python tools/simulator.py --headless --tcp 10502      # 无界面，供自动化测试
"""

import os
import sys
import time
import argparse
import threading

# 保证能从任意目录导入同目录的 relay_hmi（协议实现单一来源）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from relay_hmi import (                                     # noqa: E402
    crc16, append_crc, check_crc, fmt_hex,
    FC_READ_DISCRETE, FC_READ_HOLDING, FC_WRITE_COIL, FC_WRITE_COILS,
    REG_BASE, RELAY_COUNT, INPUT_COUNT,
    BROADCAST_ADDR, REBOOT_COIL_ADDR, REBOOT_VALUE,
    HAS_SERIAL, SerialTransport,
)


# ================================================================ 从站模型
class RelaySlave:
    """继电器板卡从站模型（协议与状态）。"""

    HW_MAJOR, HW_MINOR = 1, 0        # 硬件版本 V1.0
    SW_MAJOR, SW_MINOR = 2, 2        # 软件版本 V2.2（说明书示例）

    def __init__(self, slave_id=1, byte_aligned=True, accept_broadcast=True, log=None,
                 extra_ids=()):
        self.slave_id = int(slave_id)
        # 一个服务端可同时响应多个从站地址（--ids 1,2,3），方便联调多从站扫描
        self.respond_ids = {self.slave_id} | {int(i) for i in extra_ids}
        self.byte_aligned = byte_aligned      # True：03H 每个寄存器回 1 字节（按说明书）
        self.accept_broadcast = accept_broadcast
        self.log = log or (lambda *a, **k: None)

        self.coils = [False] * 16             # 继电器 1~16（状态字 2006H/2007H 可回读 0~15）
        self.inputs = [False] * INPUT_COUNT   # 开入 1~16
        self.holding = bytearray(0x10000)     # 保持寄存器（单字节值）
        self._sync_version()
        self.reboot_count = 0
        self.tx_count = 0
        self.rx_count = 0
        self.err_count = 0

    # ---- 内部 ----
    def _sync_version(self):
        self.holding[REG_BASE + 0] = self.HW_MAJOR
        self.holding[REG_BASE + 1] = self.HW_MINOR
        self.holding[REG_BASE + 2] = self.SW_MAJOR
        self.holding[REG_BASE + 3] = self.SW_MINOR
        self._sync_io()

    def _sync_io(self):
        in_word = 0
        for i in range(INPUT_COUNT):
            if self.inputs[i]:
                in_word |= (1 << i)
        out_word = 0
        for i in range(len(self.coils)):
            if self.coils[i]:
                out_word |= (1 << i)
        # 状态字节「低字节在前」：2004H=开入1~8、2005H=开入9~16、
        # 2006H=继电器1~8、2007H=继电器9~16（真机实测行为，与说明书表格标注相反）
        self.holding[REG_BASE + 4] = in_word & 0xFF
        self.holding[REG_BASE + 5] = (in_word >> 8) & 0xFF
        self.holding[REG_BASE + 6] = out_word & 0xFF
        self.holding[REG_BASE + 7] = (out_word >> 8) & 0xFF

    def set_coil(self, index, on):
        """外部（模拟界面）改变输出状态。"""
        if 0 <= index < len(self.coils):
            self.coils[index] = bool(on)
            self._sync_io()
        return self.coils[index]

    def set_input(self, index, on):
        if 0 <= index < len(self.inputs):
            self.inputs[index] = bool(on)
            self._sync_io()
        return self.inputs[index]

    @staticmethod
    def _exception(sid, fc, code):
        return append_crc(bytes((sid, fc | 0x80, code)))

    # ---- 帧处理 ----
    def handle_frame(self, frame: bytes):
        """处理一帧请求，返回响应帧；广播或无需回复时返回 None。"""
        self.rx_count += 1
        self.log("RX", frame)

        if len(frame) < 4 or not check_crc(frame):
            self.err_count += 1
            self.log("!!", b"", "CRC 校验失败，丢弃：%s" % fmt_hex(frame))
            return None

        sid, fc = frame[0], frame[1]
        broadcast = (sid == BROADCAST_ADDR) or (sid == 0x00)
        if broadcast and not self.accept_broadcast:
            return None
        if not broadcast and sid not in self.respond_ids:
            return None                                  # 不是给我的，静默

        body = frame[:-2]
        try:
            if fc == FC_READ_DISCRETE:
                return self._fc02(sid, body)
            if fc == FC_READ_HOLDING:
                return self._fc03(sid, body)
            if fc == FC_WRITE_COIL:
                return self._fc05(sid, body, broadcast)
            if fc == FC_WRITE_COILS:
                return self._fc0f(sid, body, broadcast)
            self.err_count += 1
            self.log("!!", b"", "不支持的功能码 0x%02X" % fc)
            if broadcast:
                return None
            return self._exception(sid, fc, 0x01)
        except Exception as e:                            # noqa: BLE001
            self.err_count += 1
            self.log("!!", b"", "处理异常：%r" % (e,))
            if broadcast:
                return None
            return self._exception(sid, fc, 0x04)

    def _reply(self, frame):
        if frame is not None:
            self.tx_count += 1
            self.log("TX", frame)
        return frame

    def _fc02(self, sid, body):
        start = (body[2] << 8) | body[3]
        qty = (body[4] << 8) | body[5]
        if qty < 1 or start + qty > INPUT_COUNT:
            return self._reply(self._exception(sid, FC_READ_DISCRETE, 0x02))
        nbytes = (qty + 7) // 8
        data = bytearray(nbytes)
        for i in range(qty):
            if self.inputs[start + i]:
                data[i // 8] |= 1 << (i % 8)
        return self._reply(append_crc(bytes((sid, FC_READ_DISCRETE, nbytes)) + bytes(data)))

    def _fc03(self, sid, body):
        start = (body[2] << 8) | body[3]
        qty = (body[4] << 8) | body[5]
        if qty < 1 or start + qty > 0x10000:
            return self._reply(self._exception(sid, FC_READ_HOLDING, 0x02))
        if self.byte_aligned:
            data = bytes(self.holding[start:start + qty])
        else:
            out = bytearray()
            for i in range(qty):
                v = self.holding[start + i] & 0xFF
                out += bytes((v & 0xFF, (v >> 8) & 0xFF))   # 小端序
            data = bytes(out)
        return self._reply(append_crc(bytes((sid, FC_READ_HOLDING, len(data))) + data))

    def _fc05(self, sid, body, broadcast):
        addr = (body[2] << 8) | body[3]
        val = (body[4] << 8) | body[5]
        # 重启指令优先判定：其数值为魔数 2345，不属于常规 0000/FF00
        if addr == REBOOT_COIL_ADDR and val == REBOOT_VALUE:
            self.reboot_count += 1
            self.log("**", b"", "收到模块重启指令（第 %d 次）" % self.reboot_count)
            if broadcast:
                return None
            # 说明书：重启回显 FF00（01 05 07 55 FF 00 9D 5E）
            return self._reply(append_crc(bytes((sid, FC_WRITE_COIL, 0x07, 0x55, 0xFF, 0x00))))
        if val not in (0x0000, 0xFF00):
            if broadcast:
                return None
            return self._reply(self._exception(sid, FC_WRITE_COIL, 0x03))
        if addr >= len(self.coils):
            if broadcast:
                return None
            return self._reply(self._exception(sid, FC_WRITE_COIL, 0x02))
        self.set_coil(addr, val == 0xFF00)
        self.log("**", b"", "继电器 %d → %s" % (addr + 1, "闭合" if val == 0xFF00 else "断开"))
        if broadcast:
            return None
        return self._reply(append_crc(bytes((sid, FC_WRITE_COIL)) + body[2:6]))

    def _fc0f(self, sid, body, broadcast):
        start = (body[2] << 8) | body[3]
        qty = (body[4] << 8) | body[5]
        nbytes = body[6]
        if nbytes != (qty + 7) // 8:
            if broadcast:
                return None
            return self._reply(self._exception(sid, FC_WRITE_COILS, 0x03))
        if qty < 1 or start + qty > len(self.coils):
            if broadcast:
                return None
            return self._reply(self._exception(sid, FC_WRITE_COILS, 0x02))
        data = body[7:7 + nbytes]
        for i in range(qty):
            self.set_coil(start + i, bool((data[i // 8] >> (i % 8)) & 1))
        self.log("**", b"", "0FH 写出口 %d~%d：%s" % (
            start + 1, start + qty,
            "".join("1" if (data[i // 8] >> (i % 8)) & 1 else "0" for i in range(qty))))
        if broadcast:
            return None
        return self._reply(append_crc(bytes((sid, FC_WRITE_COILS)) + body[2:6]))


# ================================================================ 帧切分
def extract_frame(buf: bytearray):
    """从缓冲区中切出一帧完整 RTU 请求；不足则返回 None。

    RTU 无长度前缀，按功能码推算长度：
      02/03/05 -> 固定 8 字节；0F -> 9 + 字节数。
    CRC 不符时丢弃首字节继续尝试。
    """
    while len(buf) >= 2:
        fc = buf[1]
        if fc in (FC_READ_DISCRETE, FC_READ_HOLDING, FC_WRITE_COIL):
            need = 8
        elif fc == FC_WRITE_COILS:
            if len(buf) < 7:
                return None
            need = 9 + buf[6]
        else:
            del buf[0]
            continue
        if len(buf) < need:
            return None
        candidate = bytes(buf[:need])
        if check_crc(candidate):
            del buf[:need]
            return candidate
        del buf[0]                                  # CRC 不符，滑动一字节重试
    return None


# ================================================================ 链路
class TcpSlaveServer:
    """RTU over TCP 从站服务端（裸 RTU 帧，无 MBAP 头）。"""

    def __init__(self, slave, host="127.0.0.1", port=10502, log=None):
        self.slave = slave
        self.host = host
        self.port = int(port)
        self.log = log or (lambda *a, **k: None)
        self._sock = None
        self._stop = threading.Event()
        self.clients = 0

    def start(self):
        import socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(2)
        self._sock.settimeout(0.3)
        t = threading.Thread(target=self._accept_loop, daemon=True, name="tcp-accept")
        t.start()
        self.log("**", b"", "TCP 从站已启动：%s:%d（RTU over TCP）" % (self.host, self.port))

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except Exception:                            # noqa: BLE001
                continue
            self.clients += 1
            self.log("**", b"", "客户端接入：%s:%d" % addr)
            threading.Thread(target=self._serve, args=(conn, addr),
                             daemon=True, name="tcp-conn").start()

    def _serve(self, conn, addr):
        conn.settimeout(0.05)
        buf = bytearray()
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except Exception:                        # noqa: BLE001
                    chunk = b""
                if chunk:
                    buf += chunk
                    while True:
                        frame = extract_frame(buf)
                        if frame is None:
                            break
                        resp = self.slave.handle_frame(frame)
                        if resp:
                            conn.sendall(resp)
                else:
                    # 无数据时也尝试解析（可能残留半帧）
                    frame = extract_frame(buf)
                    if frame is not None:
                        resp = self.slave.handle_frame(frame)
                        if resp:
                            conn.sendall(resp)
        except Exception as e:                            # noqa: BLE001
            self.log("!!", b"", "连接异常：%r" % (e,))
        finally:
            try:
                conn.close()
            except Exception:                             # noqa: BLE001
                pass
            self.log("**", b"", "客户端断开：%s:%d" % addr)

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:                             # noqa: BLE001
                pass


class SerialSlaveServer:
    """串口从站服务端（需 pyserial）。"""

    def __init__(self, slave, port, baudrate=9600, bytesize=8, parity="N",
                 stopbits=1, log=None):
        self.slave = slave
        self.port = port
        self.baudrate = int(baudrate)
        self.log = log or (lambda *a, **k: None)
        self.tr = SerialTransport(port, baudrate=baudrate, bytesize=bytesize,
                                  parity=parity, stopbits=stopbits, timeout=0.05)
        self._stop = threading.Event()

    def start(self):
        self.tr.open()
        threading.Thread(target=self._loop, daemon=True, name="serial-slave").start()
        self.log("**", b"", "串口从站已启动：%s @%d %s" % (
            self.port, self.baudrate, self.tr.frame_desc()))

    def _loop(self):
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self.tr._ser.read(256)
            except Exception:                             # noqa: BLE001
                chunk = b""
            if chunk:
                buf += chunk
                while True:
                    frame = extract_frame(buf)
                    if frame is None:
                        break
                    resp = self.slave.handle_frame(frame)
                    if resp:
                        try:
                            self.tr.write(resp)
                        except Exception:                  # noqa: BLE001
                            pass
            else:
                time.sleep(0.01)

    def stop(self):
        self._stop.set()
        self.tr.close()


# ================================================================ 界面
C_BG = "#f4f6f8"
C_PANEL = "#ffffff"
C_BORDER = "#d5dbe2"
C_TEXT = "#1f2933"
C_MUTED = "#6b7a8d"
C_ACCENT = "#1668dc"
C_ON = "#16a34a"
C_ON_DIM = "#86d3a8"
C_OFF = "#c8d0d9"
C_OFF_DIM = "#e2e7ec"


class SimulatorGui:
    """模拟从站界面：观察被写入的输出、手动触发开入。"""

    def __init__(self, slave, transport_desc):
        import tkinter as tk
        from tkinter import scrolledtext
        self.tk = tk
        self.slave = slave
        self._log_lines = 0

        self.root = tk.Tk()
        self.root.title("继电器板卡(12CH) 模拟从站  ·  %s" % transport_desc)
        self.root.geometry("900x680")
        self.root.configure(bg=C_BG)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 9))

        head = tk.Frame(self.root, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        head.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(head, text="模拟从站  ·  %s" % transport_desc, bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side="left", padx=12, pady=8)
        self.counter_var = tk.StringVar(value="接收 0 / 发送 0 / 错误 0")
        tk.Label(head, textvariable=self.counter_var, bg=C_PANEL, fg=C_MUTED,
                 font=("Consolas", 10)).pack(side="right", padx=12)

        mid = tk.Frame(self.root, bg=C_BG)
        mid.pack(fill="both", expand=True, padx=10)

        left, lb = self._card(mid, "出口（上位机写入后点亮，点击可手工改变）")
        left.pack(side="left", fill="both", expand=True)
        self.coil_widgets = []
        for i in range(RELAY_COUNT):
            holder = tk.Frame(lb, bg=C_PANEL)
            holder.grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="nsew")
            tk.Label(holder, text="出口 %d" % (i + 1), bg=C_PANEL, fg=C_TEXT,
                     font=("Microsoft YaHei UI", 9, "bold")).pack()
            cv = tk.Canvas(holder, width=46, height=46, bg=C_PANEL,
                           highlightthickness=0, cursor="hand2")
            cv.pack()
            ring = cv.create_oval(5, 5, 41, 41, fill=C_OFF, outline=C_BORDER, width=2)
            core = cv.create_oval(15, 15, 31, 31, fill=C_OFF_DIM, outline="")
            lab = cv.create_text(23, 23, text="断", fill="#ffffff",
                                 font=("Microsoft YaHei UI", 10, "bold"))
            cv.bind("<Button-1>", lambda _e, k=i: self._toggle_coil(k))
            self.coil_widgets.append((cv, ring, core, lab))
        for r in range(4):
            lb.rowconfigure(r, weight=1, minsize=84)
        for c in range(3):
            lb.columnconfigure(c, weight=1, minsize=110)

        right = tk.Frame(mid, bg=C_BG, width=290)
        right.pack(side="left", fill="y", padx=(10, 0))
        right.pack_propagate(False)
        rbox, rb = self._card(right, "开入（点击切换）")
        rbox.pack(fill="x")
        self.input_widgets = []
        for i in range(INPUT_COUNT):
            holder = tk.Frame(rb, bg=C_PANEL)
            holder.grid(row=i // 4, column=i % 4, padx=4, pady=3)
            cv = tk.Canvas(holder, width=26, height=26, bg=C_PANEL,
                           highlightthickness=0, cursor="hand2")
            cv.pack()
            circle = cv.create_oval(4, 4, 22, 22, fill=C_OFF, outline=C_BORDER)
            tk.Label(holder, text=str(i + 1), bg=C_PANEL, fg=C_MUTED,
                     font=("Microsoft YaHei UI", 7)).pack()
            cv.bind("<Button-1>", lambda _e, k=i: self._toggle_input(k))
            self.input_widgets.append((cv, circle))

        tk.Label(rb, text="提示：出口由上位机 05H/0FH 指令驱动；\n开入是本侧模拟量，供 02H 读取。",
                 bg=C_PANEL, fg=C_MUTED, justify="left", wraplength=250).grid(
            row=4, column=0, columnspan=4, pady=(10, 2), sticky="w")

        log_box, log_body = self._card(self.root, "报文日志")
        log_box.pack(fill="both", expand=False, padx=10, pady=(6, 10))
        bar = tk.Frame(log_body, bg=C_PANEL)
        bar.pack(fill="x")
        tk.Button(bar, text="清空", relief="flat", bg=C_PANEL, fg=C_ACCENT, bd=0,
                  command=self._clear_log).pack(side="right")
        self.text = scrolledtext.ScrolledText(log_body, height=12, state="disabled",
                                              bg="#0f172a", fg="#cbd5e1",
                                              font=("Consolas", 9), relief="flat")
        self.text.pack(fill="both", expand=True)
        self.text.tag_config("RX", foreground="#7dd3fc")
        self.text.tag_config("TX", foreground="#86efac")
        self.text.tag_config("!!", foreground="#f87171")
        self.text.tag_config("**", foreground="#fbbf24")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self._refresh)

    def _card(self, parent, title):
        tk = self.tk
        outer = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        tk.Label(outer, text=title, bg=C_PANEL, fg=C_TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        body = tk.Frame(outer, bg=C_PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        return outer, body

    def _toggle_coil(self, i):
        self.slave.set_coil(i, not self.slave.coils[i])
        self._sync_coils()

    def _toggle_input(self, i):
        self.slave.set_input(i, not self.slave.inputs[i])
        self._sync_inputs()

    def _sync_coils(self):
        for i, (cv, ring, core, lab) in enumerate(self.coil_widgets):
            on = self.slave.coils[i]
            cv.itemconfig(ring, fill=C_ON if on else C_OFF,
                          outline="#0f8a3d" if on else C_BORDER)
            cv.itemconfig(core, fill=C_ON_DIM if on else C_OFF_DIM)
            cv.itemconfig(lab, text="合" if on else "断")

    def _sync_inputs(self):
        for i, (cv, circle) in enumerate(self.input_widgets):
            cv.itemconfig(circle, fill=C_ACCENT if self.slave.inputs[i] else C_OFF)

    def _refresh(self):
        self._sync_coils()
        self._sync_inputs()
        self.counter_var.set("接收 %d / 发送 %d / 错误 %d / 重启 %d" % (
            self.slave.rx_count, self.slave.tx_count,
            self.slave.err_count, self.slave.reboot_count))
        self.root.after(200, self._refresh)

    def _clear_log(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self._log_lines = 0

    def log(self, direction, data, extra=""):
        """线程安全：所有界面操作都排到主线程执行。"""
        def do():
            try:
                self.text.config(state="normal")
                if direction == "**":
                    line = "**  %s" % extra
                elif direction == "!!":
                    line = "!!  %s" % extra
                else:
                    line = "%-3s %s%s" % (direction, fmt_hex(data),
                                          ("   (%s)" % extra) if extra else "")
                self.text.insert("end", line + "\n", direction)
                self._log_lines += 1
                if self._log_lines > 3000:
                    self.text.delete("1.0", "1000.0")
                    self._log_lines -= 999
                self.text.see("end")
                self.text.config(state="disabled")
            except Exception:                              # noqa: BLE001
                pass
        try:
            self.root.after(0, do)
        except Exception:                                  # noqa: BLE001
            pass

    def run(self):
        self.root.mainloop()

    def on_close(self):
        self.root.destroy()


# ================================================================ 入口
def main():
    ap = argparse.ArgumentParser(description="继电器板卡(12CH) 模拟从站")
    ap.add_argument("--tcp", type=int, default=10502, help="TCP 监听端口（默认 10502）")
    ap.add_argument("--host", default="127.0.0.1", help="TCP 监听地址（默认 127.0.0.1）")
    ap.add_argument("--no-tcp", action="store_true", help="不启动 TCP 服务")
    ap.add_argument("--serial", default=None, help="串口设备名，如 COM7")
    ap.add_argument("--baud", type=int, default=9600, help="串口波特率（默认 9600）")
    ap.add_argument("--data", type=int, default=8, choices=(5, 6, 7, 8),
                    help="数据位（默认 8）")
    ap.add_argument("--parity", default="N", choices=("N", "E", "O", "M", "S"),
                    help="校验：N/O/E/M/S（默认 N 无校验）")
    ap.add_argument("--stop", dest="stopbits", default="1",
                    choices=("1", "1.5", "2"), help="停止位（默认 1）")
    ap.add_argument("--id", type=int, default=1, help="从站地址（默认 1）")
    ap.add_argument("--ids", default=None,
                    help="额外从站地址，逗号分隔（如 --ids 2,3），一个服务端同时响应多台")
    ap.add_argument("--word-aligned", action="store_true",
                    help="03H 按 16 位小端返回（默认按说明书的单字节对齐）")
    ap.add_argument("--headless", action="store_true", help="不显示界面（自动化测试用）")
    args = ap.parse_args()

    gui_holder = {}
    logger = (lambda d, data, extra="": gui_holder["gui"].log(d, data, extra)) if not args.headless \
        else (lambda d, data, extra="": None)

    extra = tuple(int(x) for x in args.ids.split(",") if x.strip()) if args.ids else ()
    slave = RelaySlave(slave_id=args.id, byte_aligned=not args.word_aligned, log=logger,
                       extra_ids=extra)

    servers = []
    descs = []
    if not args.no_tcp:
        srv = TcpSlaveServer(slave, host=args.host, port=args.tcp, log=logger)
        srv.start()
        servers.append(srv)
        descs.append("TCP %s:%d" % (args.host, args.tcp))
    if args.serial:
        if not HAS_SERIAL:
            print("未安装 pyserial，无法启动串口从站。请先 pip install pyserial", file=sys.stderr)
            return 2
        ssrv = SerialSlaveServer(slave, args.serial, baudrate=args.baud,
                                 bytesize=args.data, parity=args.parity,
                                 stopbits=args.stopbits, log=logger)
        ssrv.start()
        servers.append(ssrv)
        descs.append("串口 %s @%d %s" % (args.serial, args.baud, ssrv.tr.frame_desc()))

    desc = "  |  ".join(descs) if descs else "（未启动任何链路）"
    print("继电器板卡模拟从站已启动：%s" % desc)
    print("从站地址：%s，保持寄存器模式：%s" % (
        ",".join(str(i) for i in sorted(slave.respond_ids)),
        "单字节对齐（说明书）" if slave.byte_aligned else "16位小端"))
    print("在上位机中：链路选「网络 (RTU over TCP)」，地址端口填上面的 TCP 地址即可联调。")

    if args.headless:
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n已停止。")
        for s in servers:
            s.stop()
        return 0

    gui = SimulatorGui(slave, desc)
    gui_holder["gui"] = gui
    try:
        gui.run()
    finally:
        for s in servers:
            s.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
