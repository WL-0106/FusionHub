# -*- coding: utf-8 -*-
"""
二合一调试助手 V2.1
  分页 1  串口调试      —— 布局仿 SSCOM 5.13.1（HEX/时间戳/定时/快捷指令/*IDN?，内含 TCP/UDP 接口）
  分页 2  MODBUS RTU   —— 布局仿 MODBUS调试助手（01H~10H 指令面板 + CRC16）

两个分页各自持有独立串口，可以同时连接不同端口，互不影响。
串口页的 TCP 接口与串口二选一自动切换（勾双向转发时可并存）。
"""

import os
import sys
import json
import time
import queue
import ctypes
import socket
import datetime
import threading

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import serial
    from serial.tools import list_ports
    HAS_SERIAL = True
    _SERIAL_ERR = ""
except Exception as _e:
    HAS_SERIAL = False
    _SERIAL_ERR = str(_e)


APP_NAME = "二合一调试助手"
APP_VER = "V2.1"

UI_FONT = ("Microsoft YaHei UI", 9)
UI_FONT_B = ("Microsoft YaHei UI", 9, "bold")
UI_FONT_S = ("Microsoft YaHei UI", 8)
MONO_FONT = ("Consolas", 10)
CLR_BG = "#F0F0F0"
CLR_EDIT = "#FFFFFF"
CLR_HL = "#FFF3B0"


# ==========================================================================
# 通用工具
# ==========================================================================
def enable_dpi():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def parse_hex(text):
    s = text.replace("0x", "").replace("0X", "")
    for ch in " ,;\r\n\t-|:":
        s = s.replace(ch, "")
    if not s:
        return b""
    if len(s) % 2:
        raise ValueError("HEX 字符个数必须为偶数")
    return bytes.fromhex(s)


def hex_str(data, sep=" "):
    return sep.join("%02X" % b for b in data)


def mb_crc16(data):
    crc = 0xFFFF
    for ch in data:
        crc ^= ch
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def mb_append_crc(body):
    crc = mb_crc16(body)
    return bytes(body) + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


def mb_crc_ok(frame):
    if len(frame) < 4:
        return False
    return mb_crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


def local_ips():
    ips = ["0.0.0.0", "127.0.0.1"]
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None):
            ip = info[4][0]
            if ":" not in ip and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def unescape(text):
    """把 \\r \\n \\t \\xNN 解析成真实字符。"""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "r":
                out.append("\r"); i += 2; continue
            if nxt == "n":
                out.append("\n"); i += 2; continue
            if nxt == "t":
                out.append("\t"); i += 2; continue
            if nxt == "\\":
                out.append("\\"); i += 2; continue
            if nxt == "x":
                try:
                    out.append(chr(int(text[i + 2:i + 4], 16))); i += 4; continue
                except Exception:
                    pass
        out.append(ch)
        i += 1
    return "".join(out)


def reg_ports():
    names = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
            i = 0
            while True:
                try:
                    _n, val, _t = winreg.EnumValue(k, i)
                    names.append(str(val)); i += 1
                except OSError:
                    break
    except Exception:
        pass
    return names


def intval(text, default=0):
    """支持 0x 前缀 / 十进制 / 空值。"""
    t = (text or "").strip()
    if not t:
        return default
    try:
        if t.lower().startswith("0x"):
            return int(t, 16)
        return int(t, 10)
    except Exception:
        raise ValueError("数值格式不对：%s" % text)


# ==========================================================================
# 串口核心（多页共享）
# ==========================================================================
def port_param_error(err):
    """判断是不是 SetCommState 参数不被驱动接受（Windows errno 87）。"""
    t = (err or "").lower()
    if "cannot configure port" in t:
        return True
    return "87" in t and ("参数错误" in (err or "") or "parameter" in t)


def port_param_hint(err):
    """把英文的参数错误翻译成能看懂的中文提示。"""
    if not port_param_error(err):
        return err
    return ("%s\n\n这个错误说明串口参数驱动不接受，最常见两种：\n"
            "· 数据位选了 5 或 6 —— 多数 USB 转串口（FTDI / CH340 / CP210x）只支持 7、8 位\n"
            "· 停止位选了 1.5 —— Windows 只支持 1 或 2\n"
            "把「数据位」改成 8、「停止位」改成 1 再打开即可。" % err)


def downshift_params(bytesize, stopbits):
    """参数不受支持时降级：8 数据位 / 1 停止位（其余不变）。"""
    b = "8" if str(bytesize) in ("5", "6") else str(bytesize)
    s = "1" if str(stopbits) == "1.5" else str(stopbits)
    return b, s


class SerialCore(object):
    def __init__(self):
        self.flow = "none"
        self.auto_answer = ""
        self._lock = threading.RLock()
        self._ser = None
        self._stop = threading.Event()
        self._th = None
        self._q = queue.Queue()

    @staticmethod
    def port_list():
        found = {}
        if HAS_SERIAL:
            try:
                for p in sorted(list_ports.comports(), key=lambda x: x.device):
                    found[p.device] = (p.description or "").strip()
            except Exception:
                pass
        for name in reg_ports():
            found.setdefault(name, "")
        items = []
        for dev in sorted(found, key=lambda d: (len(d), d)):
            desc = found[dev]
            if desc and desc not in ("n/a", dev):
                items.append("%s  %s" % (dev, desc))
            else:
                items.append(dev)
        if not items:
            items = ["(未检测到串口，点刷新)"]
        return items

    @staticmethod
    def port_name(raw):
        raw = (raw or "").strip()
        if not raw or raw.startswith("("):
            return ""
        if raw.upper().startswith("COM"):
            out = ""
            for ch in raw.upper():
                if ch.isdigit() or ch in "COM":
                    out += ch
                else:
                    break
            return out
        return raw.split()[0].split("(")[0].strip()

    @property
    def is_open(self):
        ser = self._ser
        return ser is not None and getattr(ser, "is_open", False)

    @property
    def port(self):
        return getattr(self._ser, "port", "") or ""

    def open(self, port, baud, bytesize=8, parity="N", stopbits=1,
             flow="none", auto_answer="", rx_buf=0, tx_buf=0):
        self.close()
        if not HAS_SERIAL:
            return False, "缺少 pyserial：%s" % _SERIAL_ERR
        if not port:
            return False, "没有选择串口"
        try:
            self._ser = serial.Serial(port=port, baudrate=int(baud),
                                      bytesize=int(bytesize), parity=parity,
                                      stopbits=float(stopbits), timeout=0.05,
                                      write_timeout=1.0,
                                      rtscts=(flow == "rtscts"),
                                      xonxoff=(flow == "xonxoff"))
        except Exception as e:
            self._ser = None
            return False, str(e)
        # 收发缓存（Windows 驱动支持时才生效，失败不影响通讯）
        try:
            if int(rx_buf or 0) > 0 or int(tx_buf or 0) > 0:
                self._ser.set_buffer_size(rx_size=max(64, int(rx_buf or 4096)),
                                          tx_size=max(64, int(tx_buf or 4096)))
        except Exception:
            pass
        self.flow = flow
        self.auto_answer = (auto_answer or "").strip()
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, name="serial-rx", daemon=True)
        self._th.start()
        return True, ""

    def close(self):
        self._stop.set()
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def write(self, data):
        ser = self._ser
        if ser is None or not getattr(ser, "is_open", False):
            return False, "串口未打开"
        try:
            with self._lock:
                ser.write(data)
                ser.flush()
            return True, ""
        except Exception as e:
            return False, str(e)

    def _loop(self):
        while not self._stop.is_set():
            ser = self._ser
            if ser is None:
                break
            try:
                n = ser.in_waiting
                data = ser.read(n if n else 1)
            except Exception as e:
                if not self._stop.is_set():
                    self._q.put(("err", e))
                break
            if data:
                # 调制解调器自动应答：收到 RING 回预设字符串
                if self.auto_answer and b"RING" in data.upper():
                    try:
                        with self._lock:
                            ser.write((self.auto_answer + "\r\n").encode("ascii", "ignore"))
                            ser.flush()
                    except Exception:
                        pass
                self._q.put(("data", data))

    def drain(self):
        packs, err = [], None
        try:
            while True:
                kind, val = self._q.get_nowait()
                if kind == "data":
                    packs.append(val)
                else:
                    err = val
        except queue.Empty:
            pass
        return packs, err


# ==========================================================================
# 串口口设置对话框（三个分页共用，各自保存一份参数）
# ==========================================================================
class SerialSetupDialog(object):
    """复刻「串口口设置」：串行口选项 / 调制解调器选项 / 缓存容量。"""

    PARITIES = (("No parity (无)", "N"), ("Odd parity (奇)", "O"),
                ("Even parity (偶)", "E"), ("Mark parity (标记)", "M"),
                ("Space parity (空格)", "S"))
    FLOWS = (("None (无)", "none"), ("RTS/CTS 硬件", "rtscts"),
             ("XON/XOFF 软件", "xonxoff"))

    def __init__(self, master, cfg, title="串口口设置"):
        self.result = None
        self._cfg = dict(cfg or {})
        px = getattr(master, "_px", None) or (lambda n: n)
        self._px = px

        top = tk.Toplevel(master)
        self.top = top
        top.title(title)
        top.configure(bg=CLR_BG)
        top.resizable(False, False)
        try:
            top.transient(master.winfo_toplevel())
        except Exception:
            pass

        body = tk.Frame(top, bg=CLR_BG)
        body.pack(fill="both", expand=True, padx=px(8), pady=px(8))

        # ---- 左：串行口选项
        lb = ttk.LabelFrame(body, text="串行口选项", padding=(8, 6))
        lb.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, px(8)))
        body.columnconfigure(0, weight=1)

        ports = [SerialCore.port_name(x) for x in SerialCore.port_list()]
        ports = [x for x in ports if x] or ["COM1"]
        self.var_port = tk.StringVar(value=self._cfg.get("port") or ports[0])
        self._row(lb, 0, "串行口", ttk.Combobox(
            lb, textvariable=self.var_port, width=14, font=UI_FONT,
            state="readonly", values=ports))

        self.var_baud = tk.StringVar(value=str(self._cfg.get("baud") or "115200"))
        self._row(lb, 1, "波特率", ttk.Combobox(
            lb, textvariable=self.var_baud, width=14, font=UI_FONT,
            values=("1200", "2400", "4800", "9600", "19200", "38400",
                    "57600", "115200", "230400", "460800", "921600")))

        self.var_parity = tk.StringVar(value=self._parity_label(self._cfg.get("parity", "N")))
        self._row(lb, 2, "奇偶校验", ttk.Combobox(
            lb, textvariable=self.var_parity, width=14, font=UI_FONT,
            state="readonly", values=[x[0] for x in self.PARITIES]))

        self.var_data = tk.StringVar(value=str(self._cfg.get("bytesize") or "8"))
        self._row(lb, 3, "数据位", ttk.Combobox(
            lb, textvariable=self.var_data, width=14, font=UI_FONT,
            state="readonly", values=("5", "6", "7", "8")))

        self.var_stop = tk.StringVar(value=str(self._cfg.get("stopbits") or "1"))
        self._row(lb, 4, "停止位", ttk.Combobox(
            lb, textvariable=self.var_stop, width=14, font=UI_FONT,
            state="readonly", values=("1", "1.5", "2")))

        # ---- 右上：调制解调器选项
        md = ttk.LabelFrame(body, text="调制解调器选项", padding=(8, 6))
        md.grid(row=0, column=1, sticky="new")
        body.columnconfigure(1, weight=1)

        self.var_flow = tk.StringVar(value=self._flow_label(self._cfg.get("flow", "none")))
        self._row(md, 0, "数据流控", ttk.Combobox(
            md, textvariable=self.var_flow, width=14, font=UI_FONT,
            state="readonly", values=[x[0] for x in self.FLOWS]))

        self.var_answer = tk.StringVar(value=str(self._cfg.get("auto_answer") or ""))
        self._row(md, 1, "自动应答", ttk.Entry(
            md, textvariable=self.var_answer, width=16, font=UI_FONT))
        tk.Label(md, text="收到 RING 时自动回复，留空关闭", font=UI_FONT_S,
                 bg=CLR_BG, fg="#666666").grid(row=2, column=0, columnspan=2,
                                               sticky="w", pady=(2, 0))

        # ---- 右下：缓存容量
        bf = ttk.LabelFrame(body, text="缓存容量", padding=(8, 6))
        bf.grid(row=1, column=1, sticky="new", pady=(px(8), 0))

        self.var_inbuf = tk.StringVar(value=str(self._cfg.get("rx_buf") or "8192"))
        self._row(bf, 0, "输入缓存", ttk.Entry(
            bf, textvariable=self.var_inbuf, width=16, font=UI_FONT))
        self.var_outbuf = tk.StringVar(value=str(self._cfg.get("tx_buf") or "8192"))
        self._row(bf, 1, "输出缓存", ttk.Entry(
            bf, textvariable=self.var_outbuf, width=16, font=UI_FONT))

        # ---- 按钮
        bar = tk.Frame(body, bg=CLR_BG)
        bar.grid(row=2, column=0, columnspan=2, pady=(px(10), 0))
        tk.Button(bar, text="✔ 确定", width=9, font=UI_FONT, bd=1, relief="raised",
                  bg=CLR_BG, activebackground="#E0E0E0",
                  command=self._ok).pack(side="left", padx=px(8))
        tk.Button(bar, text="✘ 取消", width=9, font=UI_FONT, bd=1, relief="raised",
                  bg=CLR_BG, activebackground="#E0E0E0",
                  command=self._cancel).pack(side="left", padx=px(8))

        top.bind("<Return>", lambda e: self._ok())
        top.bind("<Escape>", lambda e: self._cancel())
        top.update_idletasks()
        self._center()
        try:
            top.grab_set()
        except Exception:
            pass
        self.top.wait_window()

    # ---------------- 内部
    def _row(self, parent, row, label, widget):
        tk.Label(parent, text=label, font=UI_FONT, bg=CLR_BG,
                 anchor="w").grid(row=row, column=0, sticky="w",
                                  padx=(0, self._px(8)), pady=self._px(3))
        widget.grid(row=row, column=1, sticky="ew", pady=self._px(3))

    def _center(self):
        try:
            pw = self.top.master.winfo_toplevel()
            x = pw.winfo_rootx() + (pw.winfo_width() - self.top.winfo_width()) // 2
            y = pw.winfo_rooty() + (pw.winfo_height() - self.top.winfo_height()) // 3
            self.top.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass

    def _parity_label(self, code):
        for label, val in self.PARITIES:
            if val == code:
                return label
        return self.PARITIES[0][0]

    def _parity_code(self):
        for label, val in self.PARITIES:
            if label == self.var_parity.get():
                return val
        return "N"

    def _flow_label(self, code):
        for label, val in self.FLOWS:
            if val == code:
                return label
        return self.FLOWS[0][0]

    def _flow_code(self):
        for label, val in self.FLOWS:
            if label == self.var_flow.get():
                return val
        return "none"

    def _ok(self):
        port = SerialCore.port_name(self.var_port.get())
        if not port:
            messagebox.showwarning("参数错误", "请选择串行口。", parent=self.top)
            return
        try:
            baud = int(self.var_baud.get())
            if baud <= 0:
                raise ValueError
        except Exception:
            messagebox.showwarning("参数错误", "波特率必须是正整数。", parent=self.top)
            return
        for name, var in (("输入缓存", self.var_inbuf), ("输出缓存", self.var_outbuf)):
            try:
                v = int(var.get())
                if v < 0:
                    raise ValueError
            except Exception:
                messagebox.showwarning("参数错误", "%s 必须是 0 或正整数。" % name,
                                       parent=self.top)
                return
        self.result = dict(
            port=port, baud=self.var_baud.get(),
            parity=self._parity_code(), bytesize=self.var_data.get(),
            stopbits=self.var_stop.get(), flow=self._flow_code(),
            auto_answer=self.var_answer.get().strip(),
            rx_buf=self.var_inbuf.get(), tx_buf=self.var_outbuf.get())
        self.top.destroy()

    def _cancel(self):
        self.result = None
        self.top.destroy()


# ==========================================================================
# 网络核心
# ==========================================================================
class NetCore(object):
    def __init__(self):
        self._sock = None
        self._srv = None
        self._clients = []
        self._peer = None
        self._stop = threading.Event()
        self._th = None
        self._q = queue.Queue()
        self._lock = threading.RLock()
        self.mode = ""
        self.info = ""

    @property
    def is_open(self):
        return self._srv is not None or self._sock is not None

    def open(self, mode, local_ip, local_port, remote_ip="", remote_port=0):
        self.close()
        self.mode = mode
        self.info = ""
        try:
            if mode == "TCP Server":
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind((local_ip, int(local_port)))
                srv.listen(4)
                srv.settimeout(0.2)
                self._srv = srv
                self.info = "%s:%s" % (local_ip, local_port)
            elif mode == "TCP Client":
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect((remote_ip, int(remote_port)))
                sock.settimeout(0.2)
                self._sock = sock
                self.info = "-> %s:%s" % (remote_ip, remote_port)
            elif mode == "UDP":
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind((local_ip, int(local_port)))
                sock.settimeout(0.2)
                self._sock = sock
                self.info = "%s:%s (UDP)" % (local_ip, local_port)
            else:
                return False, "未知协议类型"
        except Exception as e:
            self.close()
            return False, str(e)

        self._stop.clear()
        self._th = threading.Thread(target=self._loop, name="net-rx", daemon=True)
        self._th.start()
        return True, ""

    def close(self):
        self._stop.set()
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except Exception:
                    pass
            self._clients = []
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
            self._sock = None
            if self._srv is not None:
                try:
                    self._srv.close()
                except Exception:
                    pass
            self._srv = None
            self._peer = None

    def write(self, data):
        with self._lock:
            try:
                if self.mode == "UDP":
                    if self._sock is None:
                        return False, "网络未打开"
                    if self._peer is None:
                        return False, "还没有目标地址（先等待对方发来一次数据）"
                    self._sock.sendto(data, self._peer)
                    return True, ""
                targets = list(self._clients)
                if self._sock is not None:
                    targets.append(self._sock)
                if not targets:
                    return False, "没有已连接的客户端"
                for t in targets:
                    t.sendall(data)
                return True, ""
            except Exception as e:
                return False, str(e)

    def _loop(self):
        import select
        while not self._stop.is_set():
            try:
                if self.mode == "TCP Server":
                    rl = [self._srv]
                    with self._lock:
                        rl += list(self._clients)
                    rl = [s for s in rl if s is not None]
                    if not rl:
                        break
                    rs, _w, _e = select.select(rl, [], [], 0.1)
                    for s in rs:
                        if s is self._srv:
                            try:
                                conn, addr = self._srv.accept()
                                conn.settimeout(0.2)
                                with self._lock:
                                    self._clients.append(conn)
                                self._q.put(("log", "客户端接入 %s:%s" % addr))
                            except Exception:
                                pass
                        else:
                            try:
                                d = s.recv(4096)
                            except Exception:
                                d = b""
                            if not d:
                                with self._lock:
                                    if s in self._clients:
                                        self._clients.remove(s)
                                try:
                                    s.close()
                                except Exception:
                                    pass
                                self._q.put(("log", "客户端断开"))
                            else:
                                self._q.put(("data", d))
                else:
                    sock = self._sock
                    if sock is None:
                        break
                    rs, _w, _e = select.select([sock], [], [], 0.1)
                    if rs:
                        if self.mode == "UDP":
                            d, addr = sock.recvfrom(4096)
                            self._peer = addr
                            self._q.put(("data", d))
                        else:
                            d = sock.recv(4096)
                            if not d:
                                self._q.put(("log", "对方已断开连接"))
                                break
                            self._q.put(("data", d))
            except Exception as e:
                if not self._stop.is_set():
                    self._q.put(("log", "网络异常：%s" % e))
                break

    def drain(self):
        packs, logs = [], []
        try:
            while True:
                kind, val = self._q.get_nowait()
                if kind == "data":
                    packs.append(val)
                else:
                    logs.append(val)
        except queue.Empty:
            pass
        return packs, logs


# ==========================================================================
# 分页 1：串口调试（SSCOM 风格）
# ==========================================================================
class SerialPage(ttk.Frame):
    def __init__(self, master, app):
        ttk.Frame.__init__(self, master)
        self._ap = app
        self._px = app.px
        self._sd_rx_bytes = 0
        self._sd_tx_bytes = 0
        self._sd_timer_id = None
        self._sd_raw_fp = None
        self._sd_txt_fp = None
        self._sd_port_touch = 0.0
        self._sd_autoref_id = None
        self.core = SerialCore()
        self.net = NetCore()          # 本页自带的 TCP/UDP 接口
        self._sd_net_rx_bytes = 0
        self._sd_net_tx_bytes = 0
        self.cfg = {"port": "", "baud": "115200", "parity": "N", "bytesize": "8",
                    "stopbits": "1", "flow": "none", "auto_answer": "",
                    "rx_buf": "8192", "tx_buf": "8192"}

        self._sd_build_vars()
        self._sd_build_status()
        self._sd_build_body()

        self._sd_refresh_ports()
        self._sd_autoref_id = self.after(3000, self._sd_auto_refresh)

    def _sd_build_vars(self):
        self.var_port = tk.StringVar()
        self.var_baud = tk.StringVar(value="115200")
        self.var_data = tk.StringVar(value="8")
        self.var_stop = tk.StringVar(value="1")
        self.var_parity = tk.StringVar(value="无 None")
        self.var_enc = tk.StringVar(value="GBK")
        self.var_interval = tk.StringVar(value="1000")
        self.var_timeout = tk.StringVar(value="20")
        self.var_hex_show = tk.BooleanVar(value=False)
        self.var_save_data = tk.BooleanVar(value=False)
        self.var_rx_file = tk.BooleanVar(value=False)
        self.var_hex_send = tk.BooleanVar(value=False)
        self.var_timed = tk.BooleanVar(value=False)
        self.var_crlf = tk.BooleanVar(value=True)
        self.var_ts = tk.BooleanVar(value=False)
        self.var_autoscroll = tk.BooleanVar(value=True)
        self.var_topmost = tk.BooleanVar(value=False)
        # ---- TCP / UDP 接口
        _ips = local_ips()
        self.var_net_mode = tk.StringVar(value="TCP Server")
        self.var_net_ip = tk.StringVar(value=_ips[-1] if _ips else "0.0.0.0")
        self.var_net_port = tk.StringVar(value="8080")
        self.var_send_serial = tk.BooleanVar(value=True)
        self.var_send_net = tk.BooleanVar(value=False)
        self.var_bridge = tk.BooleanVar(value=False)

    def _btn(self, parent, text, cmd, width=8, bg=None, font=UI_FONT, **kw):
        return tk.Button(parent, text=text, command=cmd, width=width, font=font,
                         relief="raised", bd=1, bg=bg or CLR_BG,
                         activebackground="#E0E0E0", **kw)

    def _sd_build_status(self):
        px = self._px
        bar = tk.Frame(self, bg=CLR_BG, bd=1, relief="sunken")
        bar.pack(side="bottom", fill="x")
        self.lbl_state = tk.Label(bar, text="未连接", font=UI_FONT, bg=CLR_BG,
                                  anchor="w", padx=px(4))
        self.lbl_state.pack(side="left")
        self.lbl_param = tk.Label(bar, text="--", font=UI_FONT, bg=CLR_BG,
                                  anchor="w", padx=px(8))
        self.lbl_param.pack(side="left")
        self.lbl_count = tk.Label(bar, text="S:0  R:0", font=UI_FONT, bg=CLR_BG,
                                  anchor="e", padx=px(6))
        self.lbl_count.pack(side="right")

    def _sd_build_body(self):
        px = self._px
        self.ctrl = tk.Frame(self, bg=CLR_BG)
        # 控制区整体抬起：底部留白，别贴着状态栏
        self.ctrl.pack(side="bottom", fill="x", padx=px(4), pady=(px(6), px(18)))

        self._sd_build_toolbar()
        self._sd_build_port_row()
        self._sd_build_tcp_row()
        self._sd_build_opt_rows()
        self._sd_build_send_row()

        rx_wrap = tk.Frame(self, bg=CLR_BG)
        rx_wrap.pack(side="top", fill="both", expand=True, padx=px(4), pady=(px(4), px(2)))
        self.txt_rx = tk.Text(rx_wrap, wrap="char", bg=CLR_EDIT, fg="#101010",
                              font=MONO_FONT, relief="sunken", bd=1, padx=px(4),
                              pady=px(3), insertwidth=1, highlightthickness=0)
        sb = tk.Scrollbar(rx_wrap, orient="vertical", command=self.txt_rx.yview)
        self.txt_rx.configure(yscrollcommand=sb.set)
        self.txt_rx.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.txt_rx.configure(state="disabled")
        self.txt_rx.tag_configure("tx", foreground="#0A6C2F")
        self.txt_rx.tag_configure("sys", foreground="#1A4FA0")
        self.txt_rx.tag_configure("net", foreground="#8A3FB0")
        self.txt_rx.tag_configure("nettx", foreground="#B0603A")

    def _sd_build_toolbar(self):
        px = self._px
        row = tk.Frame(self.ctrl, bg=CLR_BG)
        row.pack(fill="x", pady=(px(2), px(4)))
        self._btn(row, "清除窗口", self._sd_clear_rx, 9).pack(side="left", padx=(0, px(2)))
        self._btn(row, "打开文件", self._sd_send_file, 9).pack(side="left", padx=(0, px(2)))
        self._btn(row, "扩展", self._sd_ext, 7).pack(side="right", padx=(px(2), 0))
        self._btn(row, "保存参数", self._ap.save_params, 9).pack(side="right", padx=(px(2), 0))
        tk.Checkbutton(row, text="最前", variable=self.var_topmost, font=UI_FONT,
                       bg=CLR_BG, activebackground=CLR_BG, bd=0,
                       command=self._sd_apply_topmost).pack(side="right", padx=(px(4), px(2)))
        self._btn(row, "清发送区", self._sd_clear_tx, 9).pack(side="right", padx=(px(2), 0))
        self._btn(row, "停止", self._sd_stop_timed, 6).pack(side="right", padx=(px(2), 0))
        self._btn(row, "发送文件", self._sd_send_file, 9).pack(side="right", padx=(px(2), 0))

    def _sd_build_port_row(self):
        px = self._px
        row = tk.Frame(self.ctrl, bg=CLR_BG)
        row.pack(fill="x", pady=(px(2), px(6)))
        tk.Label(row, text="端口号", font=UI_FONT, bg=CLR_BG).pack(side="left")
        self.cb_port = ttk.Combobox(row, textvariable=self.var_port, width=32,
                                    font=UI_FONT, state="readonly")
        self.cb_port.pack(side="left", padx=(px(3), px(3)))
        self.cb_port.bind("<Button-1>", self._sd_touch_port, add="+")
        self._btn(row, "刷新", self._sd_refresh_ports, 5, font=UI_FONT_S).pack(side="left")
        self.btn_open = self._btn(row, "打开串口", self._sd_toggle_port, 10, font=UI_FONT_B)
        self.btn_open.pack(side="left", padx=(px(8), px(10)))

        tk.Label(row, text="波特率", font=UI_FONT, bg=CLR_BG).pack(side="left")
        ttk.Combobox(row, textvariable=self.var_baud, width=8, font=UI_FONT,
                     values=("1200", "2400", "4800", "9600", "19200", "38400",
                             "57600", "115200", "230400", "460800", "921600")
                     ).pack(side="left", padx=(px(3), px(8)))

        tk.Label(row, text="数据位", font=UI_FONT, bg=CLR_BG).pack(side="left")
        ttk.Combobox(row, textvariable=self.var_data, width=3, font=UI_FONT,
                     state="readonly", values=("5", "6", "7", "8")
                     ).pack(side="left", padx=(px(3), px(6)))

        tk.Label(row, text="停止位", font=UI_FONT, bg=CLR_BG).pack(side="left")
        ttk.Combobox(row, textvariable=self.var_stop, width=3, font=UI_FONT,
                     state="readonly", values=("1", "1.5", "2")
                     ).pack(side="left", padx=(px(3), px(6)))

        tk.Label(row, text="校验位", font=UI_FONT, bg=CLR_BG).pack(side="left")
        ttk.Combobox(row, textvariable=self.var_parity, width=9, font=UI_FONT,
                     state="readonly",
                     values=("无 None", "奇 Odd", "偶 Even", "标记 Mark", "空格 Space")
                     ).pack(side="left", padx=(px(3), px(6)))

    def _sd_build_tcp_row(self):
        """TCP/UDP 接口：与串口同一窗口、同一接收区，发送时可选目标。"""
        px = self._px
        row = tk.Frame(self.ctrl, bg=CLR_BG)
        row.pack(fill="x", pady=(px(1), px(5)))

        tk.Label(row, text="TCP接口", font=UI_FONT_B, fg="#8A3FB0",
                 bg=CLR_BG).pack(side="left")
        self.cb_netmode = ttk.Combobox(row, textvariable=self.var_net_mode, width=10,
                                       font=UI_FONT, state="readonly",
                                       values=("TCP Client", "TCP Server", "UDP"))
        self.cb_netmode.pack(side="left", padx=(px(4), px(6)))
        self.cb_netmode.bind("<<ComboboxSelected>>", lambda e: self._sd_sync_net_mode())

        self.lbl_net_ip = tk.Label(row, text="远程IP", font=UI_FONT, bg=CLR_BG)
        self.lbl_net_ip.pack(side="left")
        self.cb_netip = ttk.Combobox(row, textvariable=self.var_net_ip, width=15,
                                     font=UI_FONT, values=local_ips())
        self.cb_netip.pack(side="left", padx=(px(3), px(6)))

        self.lbl_net_port = tk.Label(row, text="远程端口", font=UI_FONT, bg=CLR_BG)
        self.lbl_net_port.pack(side="left")
        self.ent_netport = tk.Entry(row, textvariable=self.var_net_port, width=7,
                                    font=UI_FONT, relief="sunken", bd=1,
                                    justify="center")
        self.ent_netport.pack(side="left", padx=(px(3), px(6)))

        self.btn_netopen = self._btn(row, "连接 TCP", self._sd_toggle_net, 9, font=UI_FONT_B)
        self.btn_netopen.pack(side="left", padx=(0, px(8)))

        self.lbl_net_state2 = tk.Label(row, text="未连接", font=UI_FONT, fg="#555555",
                                       bg=CLR_BG)
        self.lbl_net_state2.pack(side="left")

        tk.Checkbutton(row, text="串口 ↔ TCP 双向转发", variable=self.var_bridge,
                       font=UI_FONT, bg=CLR_BG, activebackground=CLR_BG, bd=0,
                       command=self._sd_bridge_hint).pack(side="right", padx=(px(6), 0))

        self._sd_sync_net_mode()

    def _sd_sync_net_mode(self):
        """TCP Client 连远端；Server/UDP 绑定本地地址，标签随模式变化。"""
        mode = self.var_net_mode.get()
        if mode == "TCP Client":
            self.lbl_net_ip.configure(text="远程IP")
            self.lbl_net_port.configure(text="远程端口")
        elif mode == "UDP":
            self.lbl_net_ip.configure(text="本地IP")
            self.lbl_net_port.configure(text="本地端口")
        else:
            self.lbl_net_ip.configure(text="本地IP")
            self.lbl_net_port.configure(text="本地端口")
        try:
            self.cb_netip.configure(values=local_ips())
        except Exception:
            pass

    def _sd_build_opt_rows(self):
        px = self._px
        kw = dict(font=UI_FONT, bg=CLR_BG, activebackground=CLR_BG, bd=0)
        row = tk.Frame(self.ctrl, bg=CLR_BG)
        row.pack(fill="x", pady=(0, px(4)))
        tk.Checkbutton(row, text="HEX显示", variable=self.var_hex_show, **kw).pack(side="left")
        tk.Checkbutton(row, text="保存数据", variable=self.var_save_data,
                       command=self._sd_toggle_save_data, **kw).pack(side="left", padx=(px(6), 0))
        tk.Checkbutton(row, text="接收数据到文件", variable=self.var_rx_file,
                       command=self._sd_toggle_rx_file, **kw).pack(side="left", padx=(px(6), 0))
        tk.Checkbutton(row, text="HEX发送", variable=self.var_hex_send, **kw).pack(side="left", padx=(px(6), 0))
        tk.Checkbutton(row, text="定时发送", variable=self.var_timed,
                       command=self._sd_apply_timed, **kw).pack(side="left", padx=(px(6), 0))
        tk.Entry(row, textvariable=self.var_interval, width=6, font=UI_FONT,
                 relief="sunken", bd=1, justify="center").pack(side="left", padx=(px(3), px(3)))
        tk.Label(row, text="ms/次", font=UI_FONT, bg=CLR_BG).pack(side="left")
        tk.Checkbutton(row, text="加回车换行", variable=self.var_crlf, **kw).pack(side="left", padx=(px(10), 0))
        tk.Checkbutton(row, text="加时间戳和分包显示", variable=self.var_ts, **kw).pack(side="left", padx=(px(10), 0))

        row2 = tk.Frame(self.ctrl, bg=CLR_BG)
        row2.pack(fill="x", pady=(0, px(3)))
        tk.Label(row2, text="超时时间", font=UI_FONT, bg=CLR_BG).pack(side="left")
        tk.Entry(row2, textvariable=self.var_timeout, width=4, font=UI_FONT,
                 relief="sunken", bd=1, justify="center").pack(side="left", padx=(px(3), px(3)))
        tk.Label(row2, text="ms", font=UI_FONT, bg=CLR_BG).pack(side="left")
        tk.Label(row2, text="   编码", font=UI_FONT, bg=CLR_BG).pack(side="left")
        ttk.Combobox(row2, textvariable=self.var_enc, width=8, font=UI_FONT,
                     state="readonly", values=("GBK", "UTF-8", "ASCII", "GB18030")
                     ).pack(side="left", padx=(px(3), 0))
        tk.Checkbutton(row2, text="自动滚动", variable=self.var_autoscroll, **kw).pack(side="left", padx=(px(12), 0))
        tk.Label(row2, text="   提示：*IDN? 按钮 一键读取设备标识（自动加 CRLF）",
                 font=UI_FONT_S, fg="#666666", bg=CLR_BG).pack(side="left")

    def _sd_build_send_row(self):
        px = self._px
        row = tk.Frame(self.ctrl, bg=CLR_BG)
        row.pack(fill="x", pady=(px(2), px(3)))

        col = tk.Frame(row, bg=CLR_BG)
        col.pack(side="left", fill="y")
        tk.Button(col, text="发 送", command=self._sd_send_current, width=8,
                  font=("Microsoft YaHei UI", 12, "bold"), relief="raised", bd=2,
                  bg="#E8E8E8", activebackground="#D8D8D8"
                  ).pack(fill="both", expand=True, pady=(0, px(2)))
        tgt = tk.Frame(col, bg=CLR_BG)
        tgt.pack(fill="x")
        tk.Checkbutton(tgt, text="串口", variable=self.var_send_serial, font=UI_FONT_S,
                       bg=CLR_BG, activebackground=CLR_BG, bd=0
                       ).pack(side="left")
        tk.Checkbutton(tgt, text="TCP", variable=self.var_send_net, font=UI_FONT_S,
                       fg="#8A3FB0", bg=CLR_BG, activebackground=CLR_BG, bd=0
                       ).pack(side="left")

        wrap = tk.Frame(row, bg=CLR_BG)
        wrap.pack(side="left", fill="both", expand=True, padx=(px(4), px(4)))
        self.txt_tx = tk.Text(wrap, height=5, wrap="char", bg=CLR_EDIT, fg="#101010",
                              font=MONO_FONT, relief="sunken", bd=1, padx=px(4),
                              pady=px(3), insertwidth=2, highlightthickness=0)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.txt_tx.yview)
        self.txt_tx.configure(yscrollcommand=sb.set)
        self.txt_tx.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        quick = tk.Frame(row, bg=CLR_BG)
        quick.pack(side="right", fill="y")
        idn = tk.Button(quick, text="*IDN?  发送", command=lambda: self._sd_send_quick("*IDN?"),
                        width=11, font=UI_FONT_B, relief="raised", bd=2,
                        bg=CLR_HL, activebackground="#FFE477")
        idn.pack(fill="x", pady=(0, px(2)))
        idn.bind("<Enter>", lambda e: idn.configure(bg="#FFE477"))
        idn.bind("<Leave>", lambda e: idn.configure(bg=CLR_HL))

        mini = tk.Frame(quick, bg=CLR_BG)
        mini.pack(fill="x")
        for i, (txt, cmd) in enumerate((("*RST", "*RST"), ("AT", "AT"),
                                        ("ATI", "ATI"), ("清空", None))):
            if cmd is None:
                b = self._btn(mini, txt, self._sd_clear_tx, 5, font=UI_FONT_S)
            else:
                b = self._btn(mini, txt, lambda v=cmd: self._sd_send_quick(v), 5, font=UI_FONT_S)
            b.grid(row=i // 2, column=i % 2, padx=px(1), pady=px(1), sticky="ew")
        mini.grid_columnconfigure(0, weight=1)
        mini.grid_columnconfigure(1, weight=1)

    # ---------------- 显示
    def _sd_clear_rx(self):
        self.txt_rx.configure(state="normal")
        self.txt_rx.delete("1.0", "end")
        self.txt_rx.configure(state="disabled")

    def _sd_clear_tx(self):
        self.txt_tx.delete("1.0", "end")

    def _sd_write(self, widget, text, tag=None):
        widget.configure(state="normal")
        widget.insert("end", text, tag or ())
        if self.var_autoscroll.get():
            widget.see("end")
        widget.configure(state="disabled")

    def sys_msg(self, text):
        self._sd_write(self.txt_rx, "[%s] %s\n" % (
            datetime.datetime.now().strftime("%H:%M:%S"), text), "sys")

    def _sd_update_count(self):
        self.lbl_count.configure(
            text="S:%d  R:%d   TCP发:%d  收:%d" % (
                self._sd_tx_bytes, self._sd_rx_bytes,
                self._sd_net_tx_bytes, self._sd_net_rx_bytes))

    # ---------------- 串口控制
    def _sd_refresh_ports(self):
        items = SerialCore.port_list()
        self.cb_port["values"] = items
        if self.var_port.get() not in items:
            self.var_port.set(items[0])

    def _sd_touch_port(self, _evt=None):
        self._sd_port_touch = time.time()

    def _sd_auto_refresh(self):
        try:
            if not self.core.is_open and (time.time() - self._sd_port_touch) > 4.0:
                self._sd_refresh_ports()
        except Exception:
            pass
        self._sd_autoref_id = self.after(3000, self._sd_auto_refresh)

    def _sd_parity(self):
        p = self.var_parity.get()
        if not HAS_SERIAL:
            return p[0]
        return {"无": serial.PARITY_NONE, "奇": serial.PARITY_ODD,
                "偶": serial.PARITY_EVEN, "标": serial.PARITY_MARK,
                "空": serial.PARITY_SPACE}.get(p[0], serial.PARITY_NONE)

    def _sd_stopbits(self):
        s = self.var_stop.get()
        if not HAS_SERIAL:
            return s
        return {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE,
                "2": serial.STOPBITS_TWO}.get(s, serial.STOPBITS_ONE)

    def _sd_toggle_port(self):
        if self.core.is_open:
            self.close_port()
        else:
            ok, err = self.open_with_current()
            if not ok:
                messagebox.showwarning("打开失败", port_param_hint(err), parent=self)

    def open_with_current(self):
        port = SerialCore.port_name(self.var_port.get())
        if not port:
            return False, "没有可用的串口，请插入设备后点“刷新”。"
        owner = self._ap.port_owner(port, self)
        if owner:
            return False, ("端口 %s 正被本程序「%s」页占用。\n"
                           "三个分页各自使用独立串口，请在那一页先关闭，或换一个端口。"
                           % (port, owner))
        c = self.current_cfg()
        ok, err = self._sd_try_open(port, c)
        if not ok and port_param_error(err):
            # 驱动不接受 5/6 位数据位或 1.5 位停止位：自动退到 8 位数据位、1 位停止位
            bs, sb = downshift_params(c["bytesize"], c["stopbits"])
            if (bs, sb) != (str(c["bytesize"]), str(c["stopbits"])):
                c2 = dict(c, bytesize=bs, stopbits=sb)
                ok2, err2 = self._sd_try_open(port, c2)
                if ok2:
                    self.cfg.update(bytesize=bs, stopbits=sb)
                    self.var_data.set(bs)
                    self.var_stop.set(sb)
                    self.sys_msg("该串口驱动不支持 %s 位数据位 / %s 位停止位，"
                                 "已自动改用 %s 数据位、%s 停止位"
                                 % (c["bytesize"], c["stopbits"], bs, sb))
                    ok, err = True, ""
                else:
                    err = err2 or err
        if ok:
            self.sys_msg("已打开 %s  %s" % (port, self.param_text()))
            self._sd_auto_off_net()
            self._ap.sync_status()
        return ok, err

    def _sd_try_open(self, port, c):
        return self.core.open(port, c["baud"], c["bytesize"], c["parity"],
                              c["stopbits"], flow=c["flow"],
                              auto_answer=c["auto_answer"],
                              rx_buf=c["rx_buf"], tx_buf=c["tx_buf"])

    # ---------------- 串口口设置（对话框：由菜单「串口通讯 → 串口口设置…」打开）
    def current_cfg(self):
        c = dict(self.cfg)
        c.update(port=SerialCore.port_name(self.var_port.get()),
                 baud=self.var_baud.get(), parity=self._sd_parity(),
                 bytesize=self.var_data.get(), stopbits=self.var_stop.get())
        return c

    def apply_cfg(self, r):
        self.cfg.update(r)
        self.var_port.set(r["port"])
        self.var_baud.set(r["baud"])
        self.var_data.set(r["bytesize"])
        self.var_stop.set(r["stopbits"])
        self.var_parity.set({"N": "无 None", "O": "奇 Odd", "E": "偶 Even",
                             "M": "标记 Mark", "S": "空格 Space"
                             }.get(r["parity"], "无 None"))
        if self.core.is_open:
            self.sys_msg("串口设置已更新，关闭后重新打开生效")

    def _sd_open_setup(self):
        dlg = SerialSetupDialog(self, self.current_cfg(), "串口口设置")
        if not dlg.result:
            return
        self.apply_cfg(dlg.result)
        self.cb_port["values"] = SerialCore.port_list()
        if self.var_port.get() not in self.cb_port["values"]:
            self.cb_port["values"] = list(self.cb_port["values"]) + [self.var_port.get()]

    # ---------------- TCP / UDP 接口
    def _sd_net_sys(self, text):
        self._sd_write(self.txt_rx, "[%s] %s\n" % (
            datetime.datetime.now().strftime("%H:%M:%S"), text), "net")

    def _sd_toggle_net(self):
        if self.net.is_open:
            self._sd_close_net()
        else:
            self._sd_open_net()

    def _sd_open_net(self):
        mode = self.var_net_mode.get()
        ip = (self.var_net_ip.get() or "").strip()
        if not ip:
            ip = "0.0.0.0"
        try:
            port = int((self.var_net_port.get() or "").strip())
        except Exception:
            messagebox.showwarning("参数错误", "端口号必须是数字。", parent=self)
            return False
        if not (0 < port < 65536):
            messagebox.showwarning("参数错误", "端口号应在 1~65535 之间。", parent=self)
            return False
        if mode == "TCP Client":
            ok, err = self.net.open(mode, "", 0, ip, port)
        else:
            ok, err = self.net.open(mode, ip, port)
        if not ok:
            messagebox.showwarning("TCP 打开失败", err, parent=self)
            return False
        self._sd_sync_net_ui()
        self._sd_net_sys("TCP 已打开：%s  %s" % (mode, self.net.info))
        self._sd_auto_off_serial()
        self._ap.sync_status()
        return True

    def _sd_close_net(self):
        was = self.net.is_open
        self.net.close()
        self._sd_sync_net_ui()
        if was:
            self._sd_net_sys("TCP 已关闭")
            self.var_send_net.set(False)
            if self.core.is_open:
                self.var_send_serial.set(True)
        self._ap.sync_status()

    # ---------------- 串口 / TCP 自动切换（二选一）
    def auto_switch_on(self):
        """默认串口与 TCP 二选一；勾了「双向转发」才允许两路同时在线。"""
        return not self.var_bridge.get()

    def _sd_auto_off_net(self):
        """串口刚打开：自动断开 TCP，并把发送目标切到串口。"""
        if not self.net.is_open:
            return
        if not self.auto_switch_on():
            self.sys_msg("串口与 TCP 同时在线（已勾选双向转发）")
            return
        self._sd_close_net()
        self.var_send_net.set(False)
        self.var_send_serial.set(True)
        self.sys_msg("已自动断开 TCP：串口 / TCP 二选一，点「连接 TCP」可切过去")

    def _sd_auto_off_serial(self):
        """TCP 刚连上：自动关闭串口，并把发送目标切到 TCP。"""
        if not self.core.is_open:
            return
        if not self.auto_switch_on():
            self._sd_net_sys("串口与 TCP 同时在线（已勾选双向转发）")
            return
        self.close_port()
        self.var_send_serial.set(False)
        self.var_send_net.set(True)
        self._sd_net_sys("已自动关闭串口：串口 / TCP 二选一，点「打开串口」可切回去")

    def _sd_sync_net_ui(self):
        if self.net.is_open:
            self.btn_netopen.configure(text="断开 TCP")
            self.lbl_net_state2.configure(text="已连接 %s" % self.net.info, fg="#0A7A2F")
            for w in (self.cb_netmode, self.cb_netip, self.ent_netport):
                try:
                    w.configure(state="disabled")
                except Exception:
                    pass
        else:
            self.btn_netopen.configure(text="连接 TCP")
            self.lbl_net_state2.configure(text="未连接", fg="#555555")
            try:
                self.cb_netmode.configure(state="readonly")
                self.cb_netip.configure(state="normal")
                self.ent_netport.configure(state="normal")
            except Exception:
                pass

    def _sd_bridge_hint(self):
        on = self.var_bridge.get()
        self._sd_net_sys("已开启 串口 ↔ TCP 双向转发" if on else "已关闭 双向转发")
        if on:
            self._sd_net_sys("双向转发期间串口和 TCP 同时在线，不再自动切换")
        elif self.core.is_open and self.net.is_open:
            self._sd_net_sys("双向转发已关闭：两路仍同时在线，可手动断开其中一个")

    def on_net_rx(self, data):
        """TCP/UDP 收到的数据：显示在同一个接收区，并可选转发到串口。"""
        if not data:
            return
        self._sd_net_rx_bytes += len(data)
        if self.var_hex_show.get():
            body = hex_str(data)
        else:
            try:
                body = data.decode(self.var_enc.get(), errors="replace")
            except Exception:
                body = repr(data)
        if self.var_ts.get():
            body = datetime.datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] " + body
        self._sd_write(self.txt_rx, body, "net")
        if self._sd_txt_fp:
            try:
                self._sd_txt_fp.write(body)
                self._sd_txt_fp.flush()
            except Exception:
                pass
        self._sd_update_count()
        if self.var_bridge.get() and self.core.is_open:
            self.core.write(data)

    def net_drain(self):
        """由主循环调用：取网络数据与连接日志。"""
        packs, logs = self.net.drain()
        for msg in logs:
            self._sd_net_sys(msg)
        for d in packs:
            self.on_net_rx(d)

    def close_port(self):
        was = self.core.is_open
        self.core.close()
        self.on_closed()
        if not was:
            self.lbl_state.configure(text="未连接", fg="#000000")
        elif self.net.is_open:
            self.var_send_serial.set(False)
            self.var_send_net.set(True)
        self._ap.sync_status()

    def param_text(self):
        txt = "%s  %s %s-%s-%s" % (self.core.port or "-", self.var_baud.get(),
                                   self.var_data.get(), self.var_parity.get()[0],
                                   self.var_stop.get())
        if (self.cfg.get("flow") or "none") != "none":
            txt += "  " + ("RTS/CTS" if self.cfg["flow"] == "rtscts" else "XON/XOFF")
        return txt

    def on_opened(self):
        self.btn_open.configure(text="关闭串口")
        self.lbl_state.configure(text="已连接 %s" % self.core.port, fg="#0A7A2F")
        self.lbl_param.configure(text=self.param_text())
        self.cb_port.configure(state="disabled")

    def on_closed(self):
        self._sd_stop_timed()
        self.btn_open.configure(text="打开串口")
        self.lbl_state.configure(text="未连接", fg="#000000")
        self.lbl_param.configure(text="--")
        self.cb_port.configure(state="readonly")

    # ---------------- 接收
    def on_serial_rx(self, data):
        if not data:
            return
        self._sd_rx_bytes += len(data)
        if self._sd_raw_fp:
            try:
                self._sd_raw_fp.write(data)
                self._sd_raw_fp.flush()
            except Exception:
                pass
        if self.var_hex_show.get():
            body = hex_str(data)
        else:
            try:
                body = data.decode(self.var_enc.get(), errors="replace")
            except Exception:
                body = repr(data)
        if self.var_ts.get():
            body = datetime.datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] " + body
        self._sd_write(self.txt_rx, body)
        if self._sd_txt_fp:
            try:
                self._sd_txt_fp.write(body)
                self._sd_txt_fp.flush()
            except Exception:
                pass
        self._sd_update_count()
        if self.var_bridge.get() and self.net.is_open:
            self.net.write(data)

    # ---------------- 发送
    def _sd_send_current(self):
        text = self.txt_tx.get("1.0", "end-1c")
        if not text.strip():
            return
        self.send_text(text, self.var_crlf.get())

    def _sd_send_quick(self, s):
        self.send_text(s, True, force_ascii=True)

    def send_targets(self):
        """当前勾选的发送目标：('serial' 和/或 'net')。"""
        out = []
        if self.var_send_serial.get():
            out.append("serial")
        if self.var_send_net.get():
            out.append("net")
        return out

    def send_text(self, text, crlf, force_ascii=False):
        targets = self.send_targets()
        if not targets:
            messagebox.showwarning("提示", "请先勾选发送目标：「串口」或「TCP」。", parent=self)
            return False
        if "serial" in targets and not self.core.is_open:
            messagebox.showwarning("提示", "串口未打开，请先选择端口并点击“打开串口”。", parent=self)
            return False
        if "net" in targets and not self.net.is_open:
            messagebox.showwarning("提示", "TCP 未连接，请先点“连接 TCP”，或取消勾选 TCP。", parent=self)
            return False
        try:
            if self.var_hex_send.get() and not force_ascii:
                data = parse_hex(text)
            else:
                data = text.encode(self.var_enc.get(), errors="replace")
            if crlf:
                data += b"\r\n"
        except Exception as e:
            messagebox.showwarning("格式错误", "发送内容解析失败：\n%s" % e, parent=self)
            return False
        if not data:
            return False

        as_hex = self.var_hex_send.get() and not force_ascii
        body = hex_str(data) if as_hex else data.decode(
            self.var_enc.get(), errors="replace").rstrip("\r\n")
        failed = []
        if "serial" in targets:
            ok, err = self.core.write(data)
            if ok:
                self._sd_tx_bytes += len(data)
                self._sd_write(self.txt_rx, "-> %s\n" % body, "tx")
            else:
                failed.append("串口：%s" % err)
        if "net" in targets:
            ok, err = self.net.write(data)
            if ok:
                self._sd_net_tx_bytes += len(data)
                self._sd_update_count()
                self._sd_write(self.txt_rx, "TCP-> %s\n" % body, "nettx")
            else:
                failed.append("TCP：%s" % err)
        self._sd_update_count()
        if failed:
            messagebox.showwarning("发送失败", "\n".join(failed), parent=self)
            return False
        return True

    def _sd_send_file(self):
        path = filedialog.askopenfilename(title="选择要发送的文件", parent=self)
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except Exception as e:
            messagebox.showwarning("读取失败", str(e), parent=self)
            return
        ok, err = self.core.write(data)
        if not ok:
            messagebox.showwarning("发送失败", err, parent=self)
            return
        self._sd_tx_bytes += len(data)
        self._sd_update_count()
        self.sys_msg("已发送文件 %s（%d 字节）" % (os.path.basename(path), len(data)))

    # ---------------- 定时
    def _sd_apply_timed(self):
        if self._sd_timer_id:
            self.after_cancel(self._sd_timer_id)
            self._sd_timer_id = None
        if self.var_timed.get():
            self._sd_tick_timed()

    def _sd_tick_timed(self):
        if not self.var_timed.get():
            self._sd_timer_id = None
            return
        self._sd_send_current()
        try:
            ms = max(20, int(self.var_interval.get()))
        except Exception:
            ms = 1000
        self._sd_timer_id = self.after(ms, self._sd_tick_timed)

    def _sd_stop_timed(self):
        if self._sd_timer_id:
            try:
                self.after_cancel(self._sd_timer_id)
            except Exception:
                pass
            self._sd_timer_id = None
        self.var_timed.set(False)

    # ---------------- 文件
    def _sd_toggle_save_data(self):
        if self.var_save_data.get():
            path = filedialog.asksaveasfilename(
                title="保存接收数据（原始字节，追加写入）", parent=self,
                defaultextension=".bin",
                initialfile="rx_%s.bin" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
            if not path:
                self.var_save_data.set(False)
                return
            try:
                self._sd_raw_fp = open(path, "ab")
                self.sys_msg("开始保存原始数据到 %s" % path)
            except Exception as e:
                self.var_save_data.set(False)
                messagebox.showwarning("无法写入", str(e), parent=self)
        elif self._sd_raw_fp:
            try:
                self._sd_raw_fp.close()
            except Exception:
                pass
            self._sd_raw_fp = None
            self.sys_msg("已停止保存原始数据")

    def _sd_toggle_rx_file(self):
        if self.var_rx_file.get():
            path = filedialog.asksaveasfilename(
                title="接收数据到文件（按显示文本写入）", parent=self,
                defaultextension=".txt",
                initialfile="rx_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
            if not path:
                self.var_rx_file.set(False)
                return
            try:
                self._sd_txt_fp = open(path, "a", encoding="utf-8", errors="replace")
                self.sys_msg("开始写入文本日志 %s" % path)
            except Exception as e:
                self.var_rx_file.set(False)
                messagebox.showwarning("无法写入", str(e), parent=self)
        elif self._sd_txt_fp:
            try:
                self._sd_txt_fp.close()
            except Exception:
                pass
            self._sd_txt_fp = None

    def save_rx_view(self):
        path = filedialog.asksaveasfilename(title="保存接收窗口内容", parent=self,
                                            defaultextension=".txt", initialfile="rx_view.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_rx.get("1.0", "end-1c"))
            self.sys_msg("接收窗口内容已保存到 %s" % path)
        except Exception as e:
            messagebox.showwarning("保存失败", str(e), parent=self)

    def _sd_apply_topmost(self):
        try:
            self.winfo_toplevel().attributes("-topmost", bool(self.var_topmost.get()))
        except Exception:
            pass

    def _sd_ext(self):
        messagebox.showinfo("扩展功能", "可在此嵌入脚本/协议解析，当前版本未启用。", parent=self)

    # ---------------- 参数
    def dump_params(self):
        return dict(port=self.var_port.get(), baud=self.var_baud.get(),
                    data=self.var_data.get(), stop=self.var_stop.get(),
                    parity=self.var_parity.get(), enc=self.var_enc.get(),
                    interval=self.var_interval.get(), timeout=self.var_timeout.get(),
                    hex_show=self.var_hex_show.get(), hex_send=self.var_hex_send.get(),
                    crlf=self.var_crlf.get(), ts=self.var_ts.get())

    def load_params(self, d):
        for key, var in (("port", self.var_port), ("baud", self.var_baud),
                         ("data", self.var_data), ("stop", self.var_stop),
                         ("parity", self.var_parity), ("enc", self.var_enc),
                         ("interval", self.var_interval), ("timeout", self.var_timeout),
                         ("hex_show", self.var_hex_show), ("hex_send", self.var_hex_send),
                         ("crlf", self.var_crlf), ("ts", self.var_ts)):
            if key in d:
                try:
                    var.set(d[key])
                except Exception:
                    pass

    def shutdown(self):
        self._sd_stop_timed()
        if self._sd_autoref_id:
            try:
                self.after_cancel(self._sd_autoref_id)
            except Exception:
                pass
            self._sd_autoref_id = None
        for fp in (self._sd_raw_fp, self._sd_txt_fp):
            if fp:
                try:
                    fp.close()
                except Exception:
                    pass
        self._sd_raw_fp = None
        self._sd_txt_fp = None
        try:
            self.net.close()
        except Exception:
            pass


# ==========================================================================
# 分页 2：MODBUS RTU
# ==========================================================================
class ModbusPage(ttk.Frame):
    def __init__(self, master, app):
        ttk.Frame.__init__(self, master)
        self._ap = app
        self._px = app.px
        self._mb_buf = b""
        self._mb_pending = None
        self._mb_timer = None
        self._mb_tx_bytes = 0
        self._mb_rx_bytes = 0
        self.core = SerialCore()
        self.cfg = {"port": "", "baud": "9600", "parity": "N", "bytesize": "8",
                    "stopbits": "1", "flow": "none", "auto_answer": "",
                    "rx_buf": "8192", "tx_buf": "8192"}

        self._mb_build()
        self._mb_set_state_label()

    # ---------------- 组
    def _mb_label_entry(self, parent, text, col, default, width=8):
        ttk.Label(parent, text=text, font=UI_FONT).grid(row=0, column=col, sticky="w", padx=(2, 4))
        var = tk.StringVar(value=default)
        ent = ttk.Entry(parent, textvariable=var, width=width, font=UI_FONT)
        ent.grid(row=1, column=col, sticky="w", padx=(2, 8), pady=(0, 2))
        return var, ent

    def _mb_read_group(self, parent, title, func, row):
        lf = ttk.LabelFrame(parent, text=title, padding=(4, 2))
        lf.grid(row=row, column=0, sticky="ew", padx=4, pady=3)
        v_slave, _ = self._mb_label_entry(lf, "485地址", 0, "1")
        v_addr, _ = self._mb_label_entry(lf, "寄存器地址", 1, "0")
        v_qty, _ = self._mb_label_entry(lf, "寄存器个数", 2, "1")
        v_out = tk.StringVar()
        ttk.Button(lf, text="读取", width=7, style="MB.TButton",
                   command=lambda: self._mb_do_read(func, v_slave, v_addr, v_qty, v_out)
                   ).grid(row=1, column=3, padx=(2, 2), pady=(0, 2))
        ttk.Label(lf, text="寄存器值", font=UI_FONT).grid(row=2, column=0, sticky="w")
        ttk.Entry(lf, textvariable=v_out, font=MONO_FONT, state="readonly"
                  ).grid(row=2, column=1, columnspan=3, sticky="ew", padx=(2, 2), pady=(0, 2))
        lf.grid_columnconfigure(1, weight=1)
        lf.grid_columnconfigure(2, weight=1)
        return lf

    def _mb_write_group(self, parent, title, func, row, single=True):
        lf = ttk.LabelFrame(parent, text=title, padding=(4, 2))
        lf.grid(row=row, column=0, sticky="ew", padx=4, pady=3)
        v_slave, _ = self._mb_label_entry(lf, "485地址", 0, "1")
        v_addr, _ = self._mb_label_entry(lf, "寄存器地址", 1, "0")
        v_val, v_ent = self._mb_label_entry(lf, "寄存器值", 2, "0", 8 if single else 24)
        ttk.Button(lf, text="发送", width=7, style="MB.TButton",
                   command=lambda: self._mb_do_write(func, v_slave, v_addr, v_val, single)
                   ).grid(row=1, column=3, padx=(2, 2), pady=(0, 2))
        lf.grid_columnconfigure(2, weight=1)
        return lf

    def _mb_build(self):
        px = self._px
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=px(2), pady=(px(4), 0))
        left = ttk.Frame(top)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(top)
        right.pack(side="left", fill="both", expand=True)

        sp = ttk.LabelFrame(left, text="串口设置", padding=(4, 3))
        sp.grid(row=0, column=0, sticky="ew", padx=4, pady=3)
        ttk.Button(sp, text="设置串口", width=9, command=self._mb_setup).pack(side="left", padx=(0, 4))
        ttk.Button(sp, text="打开串口", width=9, command=self._mb_open_serial).pack(side="left", padx=(0, 4))
        ttk.Button(sp, text="关闭串口", width=9, command=self._mb_close_serial).pack(side="left")
        self.lbl_port = ttk.Label(sp, text="当前串口: 未连接", font=UI_FONT)
        self.lbl_port.pack(side="left", padx=(10, 0))

        self._mb_read_group(left, "01H指令 （读线圈寄存器）", func=1, row=1)
        self._mb_read_group(left, "02H指令 （读离散输入寄存器）", func=2, row=2)
        self._mb_read_group(left, "03H指令 （读保持寄存器）", func=3, row=3)

        self._mb_read_group(right, "04H指令 （读输入寄存器）", func=4, row=0)
        self._mb_write_group(right, "05H指令 （写单个线圈寄存器）", func=5, row=1)
        self._mb_write_group(right, "06H指令 （写单个保持寄存器）", func=6, row=2)
        self._mb_write_group(right, "10H指令 （写多个保持寄存器）", func=16, row=3, single=False)

        anyf = ttk.LabelFrame(right, text="任意指令", padding=(4, 3))
        anyf.grid(row=4, column=0, sticky="ew", padx=4, pady=3)
        self.var_any = tk.StringVar()
        self.ent_any = ttk.Entry(anyf, textvariable=self.var_any, font=MONO_FONT)
        self.ent_any.pack(side="left", fill="x", expand=True, padx=(2, 6))
        self.ent_any.bind("<Return>", lambda e: self._mb_send_any(False))
        ttk.Button(anyf, text="发送", width=7,
                   command=lambda: self._mb_send_any(False)).pack(side="left", padx=2)
        ttk.Button(anyf, text="带CRC发送", width=10,
                   command=lambda: self._mb_send_any(True)).pack(side="left", padx=2)

        bottom = ttk.Frame(self)
        bottom.pack(side="top", fill="both", expand=True, padx=px(2), pady=(px(4), px(2)))

        head_tx = ttk.Frame(bottom)
        head_tx.grid(row=0, column=0, sticky="ew", padx=4)
        ttk.Label(head_tx, text="发送缓冲区", font=UI_FONT).pack(side="left")
        ttk.Button(head_tx, text="清空数据", width=9,
                   command=lambda: self._mb_clear(self.txt_tx)).pack(side="right")

        head_rx = ttk.Frame(bottom)
        head_rx.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(head_rx, text="接收缓冲区", font=UI_FONT).pack(side="left")
        ttk.Button(head_rx, text="清空数据", width=9,
                   command=lambda: self._mb_clear(self.txt_rx)).pack(side="right")

        self.txt_tx = tk.Text(bottom, height=8, wrap="char", bg=CLR_EDIT, font=MONO_FONT,
                              relief="sunken", bd=1, padx=4, pady=3, highlightthickness=0)
        self.txt_rx = tk.Text(bottom, height=8, wrap="char", bg=CLR_EDIT, font=MONO_FONT,
                              relief="sunken", bd=1, padx=4, pady=3, highlightthickness=0)
        sb1 = tk.Scrollbar(bottom, orient="vertical", command=self.txt_tx.yview)
        sb2 = tk.Scrollbar(bottom, orient="vertical", command=self.txt_rx.yview)
        self.txt_tx.configure(yscrollcommand=sb1.set)
        self.txt_rx.configure(yscrollcommand=sb2.set)
        self.txt_tx.grid(row=1, column=0, sticky="nsew", padx=(4, 0), pady=(0, 4))
        sb1.grid(row=1, column=0, sticky="nse", pady=(0, 4), padx=(0, 4))
        self.txt_rx.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(0, 4))
        sb2.grid(row=1, column=1, sticky="nse", pady=(0, 4), padx=(0, 4))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        bottom.grid_rowconfigure(1, weight=1)

        self.txt_tx.configure(state="disabled")
        self.txt_rx.configure(state="disabled")
        self.txt_rx.tag_configure("ok", foreground="#0A6C2F")
        self.txt_rx.tag_configure("err", foreground="#B00020")
        self.txt_rx.tag_configure("tx", foreground="#1A4FA0")

    def _mb_set_state_label(self):
        if self.core.is_open:
            extra = ""
            if (self.cfg.get("flow") or "none") != "none":
                extra = "  " + ("RTS/CTS" if self.cfg["flow"] == "rtscts" else "XON/XOFF")
            self.lbl_port.configure(
                text="当前串口:%s 波特率: %s%s" % (self.core.port, self.cfg.get("baud"), extra),
                foreground="#0A7A2F")
        else:
            self.lbl_port.configure(text="当前串口: 未连接", foreground="#000000")

    def _mb_setup(self):
        dlg = SerialSetupDialog(self, self.cfg, "串口口设置 - MODBUS")
        if not dlg.result:
            return
        self.cfg.update(dlg.result)
        if self.core.is_open:
            self._mb_log(self.txt_rx, "串口设置已更新，关闭后重新打开生效")
        self._mb_set_state_label()

    def _mb_open_serial(self):
        if self.core.is_open:
            return
        port = SerialCore.port_name(self.cfg.get("port") or "")
        if not port:
            items = SerialCore.port_list()
            port = SerialCore.port_name(items[0]) if items else ""
        if not port:
            messagebox.showwarning("提示", "没有可用串口，请插入设备后重试。", parent=self)
            return
        owner = self._ap.port_owner(port, self)
        if owner:
            messagebox.showwarning(
                "端口被占用",
                "端口 %s 正被本程序「%s」页占用。\n"
                "三个分页各自使用独立串口，请在那一页先关闭，或换一个端口。"
                % (port, owner), parent=self)
            return
        c = self.cfg
        ok, err = self.core.open(port, c["baud"], c["bytesize"], c["parity"],
                                 c["stopbits"], flow=c["flow"],
                                 auto_answer=c["auto_answer"],
                                 rx_buf=c["rx_buf"], tx_buf=c["tx_buf"])
        fixed = ""
        if not ok and port_param_error(err):
            bs, sb = downshift_params(c["bytesize"], c["stopbits"])
            if (bs, sb) != (str(c["bytesize"]), str(c["stopbits"])):
                ok2, err2 = self.core.open(port, c["baud"], bs, c["parity"], sb,
                                           flow=c["flow"],
                                           auto_answer=c["auto_answer"],
                                           rx_buf=c["rx_buf"], tx_buf=c["tx_buf"])
                if ok2:
                    fixed = ("驱动不支持 %s 位数据位 / %s 位停止位，"
                             "已自动改用 %s-%s" % (c["bytesize"], c["stopbits"], bs, sb))
                    self.cfg.update(bytesize=bs, stopbits=sb)
                    c = self.cfg
                    ok = True
                else:
                    err = err2 or err
        if not ok:
            messagebox.showwarning("打开失败", port_param_hint(err), parent=self)
            return
        if fixed:
            self._mb_log(self.txt_rx, fixed, "err")
        self._mb_log(self.txt_rx, "串口已打开 %s  %s %s-%s-%s" % (
            port, c["baud"], c["bytesize"], c["parity"], c["stopbits"]))
        self._mb_set_state_label()
        self._ap.sync_status()

    def _mb_close_serial(self):
        self.close_port()

    def close_port(self):
        was = self.core.is_open
        self.core.close()
        self._mb_set_state_label()
        if was:
            self._mb_log(self.txt_rx, "串口已关闭")
        self._ap.sync_status()

    # ---------------- 输出
    def _mb_log(self, widget, text, tag=None):
        widget.configure(state="normal")
        widget.insert("end", text + "\n", tag or ())
        widget.see("end")
        widget.configure(state="disabled")

    def _mb_clear(self, widget):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.configure(state="disabled")

    # ---------------- 发送
    def _mb_send(self, frame, desc):
        if not self.core.is_open:
            messagebox.showwarning("提示", "串口未打开，请先点“打开串口”。", parent=self)
            return False
        ok, err = self.core.write(frame)
        if not ok:
            messagebox.showwarning("发送失败", err, parent=self)
            return False
        self._mb_tx_bytes += len(frame)
        self._mb_log(self.txt_tx, "%s %s" % (time.strftime("%H:%M:%S"), hex_str(frame)), "tx")
        self._mb_log(self.txt_rx, "→ %s  [%s]" % (hex_str(frame), desc), "tx")
        return True

    def _mb_do_read(self, func, v_slave, v_addr, v_qty, v_out):
        try:
            slave = intval(v_slave.get(), 1)
            addr = intval(v_addr.get(), 0)
            qty = intval(v_qty.get(), 1)
            if not 0 <= slave <= 247:
                raise ValueError("485地址应在 0~247")
            if not 1 <= qty <= 125:
                raise ValueError("寄存器个数应在 1~125")
        except Exception as e:
            messagebox.showwarning("参数错误", str(e), parent=self)
            return
        body = bytes((slave, func, (addr >> 8) & 0xFF, addr & 0xFF,
                      (qty >> 8) & 0xFF, qty & 0xFF))
        frame = mb_append_crc(body)
        if not self._mb_send(frame, "%02XH 读 %d 个 @%d" % (func, qty, addr)):
            return
        self._mb_pending = dict(func=func, slave=slave, qty=qty, out=v_out,
                                title="%02XH" % func)
        self._mb_buf = b""
        self._mb_start_timeout()

    def _mb_do_write(self, func, v_slave, v_addr, v_val, single):
        try:
            slave = intval(v_slave.get(), 1)
            addr = intval(v_addr.get(), 0)
            val = intval(v_val.get(), 0) if single else None
        except Exception as e:
            messagebox.showwarning("参数错误", str(e), parent=self)
            return

        if func == 5:
            body = bytes((slave, 5, (addr >> 8) & 0xFF, addr & 0xFF)) + \
                   (b"\xFF\x00" if val else b"\x00\x00")
        elif func == 6:
            body = bytes((slave, 6, (addr >> 8) & 0xFF, addr & 0xFF,
                          (val >> 8) & 0xFF, val & 0xFF))
        else:
            try:
                text = v_val.get().replace(",", " ").replace("，", " ").split()
                regs = [intval(t, 0) for t in text]
            except Exception as e:
                messagebox.showwarning("参数错误",
                                       "寄存器值应填多个数值，用空格或逗号分隔：\n%s" % e,
                                       parent=self)
                return
            if not 1 <= len(regs) <= 123:
                messagebox.showwarning("参数错误", "寄存器个数应为 1~123 个", parent=self)
                return
            body = bytes((slave, 16, (addr >> 8) & 0xFF, addr & 0xFF,
                          (len(regs) >> 8) & 0xFF, len(regs) & 0xFF, len(regs) * 2))
            for r in regs:
                body += bytes(((r >> 8) & 0xFF, r & 0xFF))

        frame = mb_append_crc(body)
        if not self._mb_send(frame, "%02XH 写 @%d" % (func, addr)):
            return
        self._mb_pending = dict(func=func, slave=slave, qty=0, out=None,
                                title="%02XH" % func)
        self._mb_buf = b""
        self._mb_start_timeout()

    def _mb_send_any(self, with_crc):
        text = self.var_any.get().strip()
        if not text:
            return
        try:
            body = parse_hex(text)
        except Exception as e:
            messagebox.showwarning("格式错误",
                                   "请按十六进制输入，例如 01 03 00 00 00 01：\n%s" % e,
                                   parent=self)
            return
        if not body:
            return
        frame = mb_append_crc(body) if with_crc else body
        if self._mb_send(frame, "任意指令%s" % ("+CRC" if with_crc else "")):
            self._mb_pending = dict(func=frame[1] if len(frame) > 1 else 0,
                                    slave=frame[0], qty=0, out=None, title="任意")
            self._mb_buf = b""
            self._mb_start_timeout()

    # ---------------- 接收解析
    def _mb_start_timeout(self):
        if self._mb_timer:
            try:
                self.after_cancel(self._mb_timer)
            except Exception:
                pass
        self._mb_timer = self.after(900, self._mb_on_timeout)

    def _mb_on_timeout(self):
        self._mb_timer = None
        p = self._mb_pending
        self._mb_pending = None
        if p:
            self._mb_log(self.txt_rx, "✗ %s 响应超时（900ms）" % p.get("title", ""), "err")
            if p.get("out") is not None:
                p["out"].set("超时")

    def on_serial_rx(self, data):
        if not data:
            return
        self._mb_rx_bytes += len(data)
        self._mb_buf += data
        self._mb_log(self.txt_rx, "← %s" % hex_str(data))
        self._mb_parse()

    def _mb_parse(self):
        while len(self._mb_buf) >= 5:
            func = self._mb_buf[1]
            if func & 0x80:
                total = 5
            elif func in (1, 2, 3, 4):
                total = 3 + self._mb_buf[2] + 2
            else:
                total = 8
            if len(self._mb_buf) < total:
                break
            frame = self._mb_buf[:total]
            self._mb_buf = self._mb_buf[total:]
            self._mb_handle(frame)

    def _mb_handle(self, frame):
        if self._mb_timer:
            try:
                self.after_cancel(self._mb_timer)
            except Exception:
                pass
            self._mb_timer = None
        p = self._mb_pending
        self._mb_pending = None

        if not mb_crc_ok(frame):
            self._mb_log(self.txt_rx, "✗ CRC 校验错误：%s" % hex_str(frame), "err")
            if p and p.get("out") is not None:
                p["out"].set("CRC错误")
            return

        func = frame[1]
        slave = frame[0]
        if func & 0x80:
            code = frame[2]
            names = {1: "非法功能码", 2: "非法数据地址", 3: "非法数据值",
                     4: "从站设备故障", 5: "确认", 6: "从站设备忙"}
            self._mb_log(self.txt_rx, "✗ 从站 %d 异常响应 %02XH：%s" % (
                slave, code, names.get(code, "未知")), "err")
            if p and p.get("out") is not None:
                p["out"].set("异常 %02XH" % code)
            return

        if func in (1, 2):
            n = frame[2]
            bits = []
            for i in range(n):
                b = frame[3 + i]
                for k in range(8):
                    bits.append((b >> k) & 1)
            qty = (p or {}).get("qty") or len(bits)
            vals = bits[:qty]
            disp = " ".join(str(v) for v in vals)
            if p and p.get("out") is not None:
                p["out"].set(disp)
            self._mb_log(self.txt_rx, "✓ %02XH 从站%d 读回 %d 位：%s" % (
                func, slave, len(vals), disp), "ok")
        elif func in (3, 4):
            n = frame[2] // 2
            regs = [(frame[3 + i * 2] << 8) | frame[4 + i * 2] for i in range(n)]
            disp = " ".join("0x%04X" % r for r in regs)
            if p and p.get("out") is not None:
                p["out"].set(disp)
            self._mb_log(self.txt_rx, "✓ %02XH 从站%d 读回 %d 个寄存器：%s" % (
                func, slave, n, disp), "ok")
            self._mb_log(self.txt_rx, "   十进制：%s" % ", ".join(str(r) for r in regs))
        else:
            self._mb_log(self.txt_rx, "✓ %02XH 从站%d 写入成功（回显一致）" % (func, slave), "ok")

    def shutdown(self):
        if self._mb_timer:
            try:
                self.after_cancel(self._mb_timer)
            except Exception:
                pass
            self._mb_timer = None


# ==========================================================================
# 主程序
# ==========================================================================
class App(object):
    def __init__(self):
        enable_dpi()
        self.root = tk.Tk()
        dpi = self.root.winfo_fpixels("1i") or 96.0
        self.scale = dpi / 96.0
        try:
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        self.root.title("%s %s  串口 / MODBUS" % (APP_NAME, APP_VER))
        self.root.configure(bg=CLR_BG)
        self._ap_apply_icon()

        self._ap_poll_id = None

        self._ap_style()
        self._ap_build()
        self._ap_geometry()
        self._ap_load_params()

        self.root.protocol("WM_DELETE_WINDOW", self._ap_close)
        self.root.bind("<F5>", lambda e: self.page_serial._sd_toggle_port())
        self.root.bind("<Control-Return>", self._ap_ctrl_enter)
        self._ap_poll_id = self.root.after(25, self._ap_pump)

    def px(self, n):
        return int(round(n * self.scale))

    def _ap_apply_icon(self):
        cands = []
        if getattr(sys, "_MEIPASS", None):
            cands.append(os.path.join(sys._MEIPASS, "app.ico"))
        cands.append(os.path.join(base_dir(), "app.ico"))
        for p in cands:
            if os.path.isfile(p):
                try:
                    self.root.iconbitmap(default=p)
                    return
                except Exception:
                    pass

    def _ap_style(self):
        st = ttk.Style()
        try:
            st.theme_use("vista")
        except Exception:
            try:
                st.theme_use("clam")
            except Exception:
                pass
        st.configure("TLabel", font=UI_FONT)
        st.configure("TLabelframe.Label", font=UI_FONT)
        st.configure("TCheckbutton", font=UI_FONT)
        st.configure("TRadiobutton", font=UI_FONT)
        st.configure("TNotebook.Tab", font=UI_FONT, padding=(16, 5))
        st.configure("MB.TButton", font=UI_FONT)
        st.configure("Net.TButton", font=UI_FONT_B)

    def _ap_build(self):
        px = self.px
        status = tk.Frame(self.root, bg=CLR_BG, bd=1, relief="sunken")
        status.pack(side="bottom", fill="x")
        self.lbl_serial = tk.Label(status, text="串口页: 未连接", font=UI_FONT_S,
                                   bg=CLR_BG, padx=px(6))
        self.lbl_serial.pack(side="left")
        self.lbl_mb = tk.Label(status, text="MODBUS: 未连接", font=UI_FONT_S,
                               bg=CLR_BG, padx=px(6))
        self.lbl_mb.pack(side="left")
        self.lbl_network = tk.Label(status, text="TCP: 未连接", font=UI_FONT_S,
                                    bg=CLR_BG, padx=px(6))
        self.lbl_network.pack(side="left")
        tk.Label(status, text="%s %s" % (APP_NAME, APP_VER), font=UI_FONT,
                 bg=CLR_BG, padx=px(6)).pack(side="right")

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True)

        self.page_serial = SerialPage(self.nb, self)
        self.page_modbus = ModbusPage(self.nb, self)
        self.nb.add(self.page_serial, text="  串口调试（含 TCP）  ")
        self.nb.add(self.page_modbus, text="  MODBUS RTU  ")

        self._ap_build_menu()

    def _ap_build_menu(self):
        mb = tk.Menu(self.root, tearoff=0)
        m_file = tk.Menu(mb, tearoff=0)
        m_file.add_command(label="保存接收数据...", command=self.page_serial.save_rx_view)
        m_file.add_separator()
        m_file.add_command(label="保存当前参数", command=self.save_params)
        m_file.add_command(label="重新载入参数", command=self._ap_load_params)
        m_file.add_separator()
        m_file.add_command(label="退出", command=self._ap_close)
        mb.add_cascade(label="文件", menu=m_file)

        m_port = tk.Menu(mb, tearoff=0)
        m_port.add_command(label="刷新端口列表", command=self.page_serial._sd_refresh_ports)
        m_port.add_command(label="打开/关闭串口  (F5)", command=self.page_serial._sd_toggle_port)
        m_port.add_separator()
        m_port.add_command(label="串口口设置…", command=self.page_serial._sd_open_setup)
        mb.add_cascade(label="通讯端口", menu=m_port)

        m_net = tk.Menu(mb, tearoff=0)
        m_net.add_command(label="连接 / 断开 TCP", command=self.page_serial._sd_toggle_net)
        m_net.add_separator()
        for label, mode in (("TCP Client", "TCP Client"),
                            ("TCP Server", "TCP Server"),
                            ("UDP", "UDP")):
            m_net.add_command(
                label=label,
                command=lambda m=mode: (self.page_serial.var_net_mode.set(m),
                                        self.page_serial._sd_sync_net_mode()))
        m_net.add_separator()
        m_net.add_checkbutton(label="串口 ↔ TCP 双向转发",
                              variable=self.page_serial.var_bridge)
        mb.add_cascade(label="TCP 接口", menu=m_net)

        m_view = tk.Menu(mb, tearoff=0)
        m_view.add_command(label="串口调试", command=lambda: self.nb.select(0))
        m_view.add_command(label="MODBUS RTU", command=lambda: self.nb.select(1))
        mb.add_cascade(label="视图", menu=m_view)

        m_help = tk.Menu(mb, tearoff=0)
        m_help.add_command(label="使用说明", command=self._ap_help)
        m_help.add_command(label="关于", command=self._ap_about)
        mb.add_cascade(label="帮助", menu=m_help)
        self.root.configure(menu=mb)

    def _ap_geometry(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 默认窗口按参考截图的宽高比（约 1.54）收紧，再小会裁掉端口行
        w = min(self.px(1200), sw - self.px(40))
        h = min(self.px(770), sh - self.px(80))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - self.px(16))
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.root.minsize(self.px(1190), self.px(745))

    def _ap_ctrl_enter(self, _e=None):
        try:
            idx = self.nb.index(self.nb.select())
        except Exception:
            return
        if idx == 0:
            self.page_serial._sd_send_current()

    # ---------------- 串口状态同步（三个分页各自独立）
    def pages(self):
        return (("串口调试", self.page_serial),
                ("MODBUS", self.page_modbus))

    def port_owner(self, port, me):
        """检查该端口是否已被本程序其它分页占用（同一端口不能被两页同时打开）。"""
        port = (port or "").upper()
        if not port:
            return ""
        for name, pg in self.pages():
            if pg is me:
                continue
            if pg.core.is_open and (pg.core.port or "").upper() == port:
                return name
        return ""

    def sync_status(self):
        # 各页自己的串口状态控件
        try:
            if self.page_serial.core.is_open:
                self.page_serial.on_opened()
            else:
                self.page_serial.on_closed()
        except Exception:
            pass
        try:
            self.page_modbus._mb_set_state_label()
        except Exception:
            pass
        try:
            self.page_serial._sd_sync_net_ui()
        except Exception:
            pass
        # 底部状态栏
        for lbl, name, pg in ((self.lbl_serial, "串口页", self.page_serial),
                              (self.lbl_mb, "MODBUS", self.page_modbus)):
            if pg.core.is_open:
                lbl.configure(text="%s: %s 已连接" % (name, pg.core.port), fg="#0A7A2F")
            else:
                lbl.configure(text="%s: 未连接" % name, fg="#000000")
        net = self.page_serial.net
        self.lbl_network.configure(
            text="TCP: %s" % (net.info if net.is_open else "未连接"),
            fg="#0A7A2F" if net.is_open else "#000000")

    # ---------------- 轮询
    def _ap_pump(self):
        # 两个分页各有自己的串口，各自取数据，互不串流
        for pg in (self.page_serial, self.page_modbus):
            packs, err = pg.core.drain()
            for p in packs:
                try:
                    pg.on_serial_rx(p)
                except Exception:
                    pass
            if err is not None:
                try:
                    if pg is self.page_serial:
                        pg.sys_msg("串口读取异常：%s" % err)
                    pg.close_port()
                except Exception:
                    pass

        # 串口页自带的 TCP 接口
        try:
            self.page_serial.net_drain()
        except Exception:
            pass

        self._ap_poll_id = self.root.after(25, self._ap_pump)

    # ---------------- 参数
    def _ap_cfg_path(self):
        return os.path.join(base_dir(), "serial_assistant.ini")

    def save_params(self):
        data = self.page_serial.dump_params()
        data["cfg_serial"] = dict(self.page_serial.cfg)
        data["cfg_modbus"] = dict(self.page_modbus.cfg)
        sp = self.page_serial
        data["net"] = dict(mode=sp.var_net_mode.get(),
                           ip=sp.var_net_ip.get(),
                           port=sp.var_net_port.get(),
                           send_serial=sp.var_send_serial.get(),
                           send_net=sp.var_send_net.get(),
                           bridge=sp.var_bridge.get())
        try:
            with open(self._ap_cfg_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.page_serial.sys_msg("参数已保存")
        except Exception as e:
            messagebox.showwarning("保存失败", str(e), parent=self.root)

    def _ap_load_params(self):
        path = self._ap_cfg_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return
        self.page_serial.load_params(d)
        for key, pg in (("cfg_serial", self.page_serial),
                        ("cfg_modbus", self.page_modbus)):
            cfg = d.get(key) or {}
            if isinstance(cfg, dict):
                pg.cfg.update({k: v for k, v in cfg.items() if k in pg.cfg})
        try:
            self.page_modbus._mb_set_state_label()
        except Exception:
            pass
        net = d.get("net") or {}
        try:
            sp = self.page_serial
            if net.get("mode"):
                sp.var_net_mode.set(net["mode"])
                sp._sd_sync_net_mode()
            for k, var in (("ip", sp.var_net_ip), ("port", sp.var_net_port),
                           ("send_serial", sp.var_send_serial),
                           ("send_net", sp.var_send_net),
                           ("bridge", sp.var_bridge)):
                if k in net:
                    var.set(net[k])
        except Exception:
            pass
        # 参数里的串口可能已拔掉：刷新列表，找不到就退回第一个可用口
        try:
            self.page_serial._sd_refresh_ports()
        except Exception:
            pass

    # ---------------- 帮助
    def _ap_help(self):
        messagebox.showinfo(
            "使用说明",
            "【串口调试】\n"
            "选端口 → 选波特率 → 打开串口；下方输入内容点“发 送”。\n"
            "“*IDN? 发送”固定发 *IDN?\\r\\n，即使勾了 HEX 发送也按 ASCII 走。\n\n"
            "【MODBUS RTU】\n"
            "01H/02H/03H/04H 填 485地址、寄存器地址、寄存器个数后点“读取”，"
            "读回的寄存器值直接填在下面。\n"
            "05H/06H 写单个；10H 写多个（寄存器值用空格或逗号分隔多个数）。\n"
            "任意指令填十六进制，可勾“带CRC发送”自动补 CRC16。\n"
            "从站 900ms 内无响应会提示超时；CRC 错误、异常码都会标红。\n\n"
            "【TCP 接口（串口页内）】\n"
            "在“TCP接口”那一行选协议、填地址和端口，点“连接 TCP”：\n"
            "  TCP Client — 填远程IP/远程端口，主动连服务器\n"
            "  TCP Server — 填本地IP/本地端口，等待客户端接入（可多个）\n"
            "  UDP — 绑本地端口，收到对方一次数据后才有回发目标\n"
            "发送按钮下方可勾选发送目标：「串口」「TCP」可同时勾，实现串口和网络同发。\n"
            "TCP 收到的数据用紫色显示在同一个接收区，发送回显是棕色，串口是绿色。\n"
            "勾选「串口 ↔ TCP 双向转发」后，串口收到的数据原样发到 TCP，反之亦然（透明网关）。\n\n"
            "【串口 / TCP 自动切换】\n"
            "默认二选一：点“打开串口”会自动断开 TCP，点“连接 TCP”会自动关闭串口，\n"
            "发送目标也会跟着切到刚连上的那一路，接收区会留一行提示。\n"
            "需要两路同时在线（收发转发、串口数据转网络）时，勾上「串口 ↔ TCP 双向转发」，\n"
            "此时不再自动切换，串口和 TCP 可以并存。\n\n"
            "【两个分页的串口互相独立】\n"
            "串口调试页和 MODBUS 页各自持有串口连接，可以一个开 COM12、一个开 COM13，互不影响。\n"
            "同一个端口不能被两页同时打开（硬件限制），遇到时会提示是哪一页占用了。\n\n"
            "【串口口设置】\n"
            "串口页常用的端口号/波特率/数据位/停止位/校验位都在同一行直接选。\n"
            "串口页要改数据流控、自动应答、输入输出缓存，用菜单「通讯端口 → 串口口设置…」；\n"
            "MODBUS 页的“设置串口”按钮打开的是同一个对话框。\n"
            "数据位 5/6、停止位 1.5 很多 USB 转串口（FTDI/CH340/CP210x）驱动不支持，\n"
            "遇到时会自动降成 8 数据位、1 停止位并在接收区提示，不会打开失败。\n"
            "自动应答：收到 RING 时自动回复该内容，留空则关闭。",
            parent=self.root)

    def _ap_about(self):
        messagebox.showinfo(
            "关于",
            "%s %s\n\n"
            "分页 1  串口调试（布局仿 SSCOM，内含 TCP/UDP 接口）\n"
            "分页 2  MODBUS RTU（布局仿 MODBUS调试助手）\n"
            "两个分页各自持有独立串口，可同时连接不同端口\n"
            "串口页的 TCP 接口支持 Client/Server/UDP 与串口↔TCP 双向转发\n\n"
            "Python 3 + tkinter + pyserial" % (APP_NAME, APP_VER),
            parent=self.root)

    # ---------------- 收尾
    def _ap_close(self):
        try:
            self.save_params()
        except Exception:
            pass
        if self._ap_poll_id:
            try:
                self.root.after_cancel(self._ap_poll_id)
            except Exception:
                pass
            self._ap_poll_id = None
        self.page_serial.shutdown()
        self.page_modbus.shutdown()
        for pg in (self.page_serial, self.page_modbus):
            try:
                pg.core.close()
            except Exception:
                pass
        try:
            self.page_serial.net.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


def main():
    App().run()


if __name__ == "__main__":
    main()
