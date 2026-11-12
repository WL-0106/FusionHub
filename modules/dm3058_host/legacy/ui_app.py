# -*- coding: utf-8 -*-
"""DM3058/DM3058E 上位机主窗口"""

import csv
import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .defs import (
    DUAL_SECONDARY_KEYS, FUNC_BY_KEY, FUNCTIONS, MATH_CHOICES, RATE_CHOICES,
)
from .instrument import Dm3058Controller
from .transport import (
    MockTransport, SerialTransport, TcpTransport, UsbTmcTransport, VisaTransport,
    list_serial_ports, list_usb_tmc_devices, list_visa_resources, pyusb_status,
)
from .ui_chart import TrendChart


IFACE_SERIAL = "RS-232 串口"
IFACE_LAN = "LAN 网口"
IFACE_USB = "USB-TMC"
IFACE_MOCK = "模拟器（无硬件演示）"

# ---- 年轻明快浅色配色 ----
UI_FONT = "Microsoft YaHei UI"
MONO = "Consolas"
BG = "#f3f5f8"        # 窗口底色（浅灰）
CARD = "#ffffff"      # 卡片
FIELD = "#eef1f5"     # 输入框
BORDER = "#dfe4ea"
FG = "#1f2937"
DIM = "#6b7280"
BTN = "#ffffff"
BTN_H = "#e8ecf1"
ACCENT = "#3b82f6"
ACCENT_H = "#2563eb"
LCD_BG = "#ffffff"    # 读数卡（白底大数字）
LCD_FG = "#2563eb"
LCD_DIM = "#64748b"
ERR = "#ef4444"
WARN = "#f59e0b"
GREEN = "#10b981"
PURPLE = "#8b5cf6"
PINK = "#ec4899"
TEAL = "#14b8a6"
ORANGE = "#f97316"
CONSOLE_BG = "#1e293b"
CONSOLE_FG = "#e2e8f0"

# 功能键配色（年轻化分类色）
FUNC_COLORS = {
    "DCV": "#3b82f6", "ACV": "#60a5fa",
    "DCI": "#f97316", "ACI": "#fb923c",
    "2WR": "#10b981", "4WR": "#34d399",
    "FREQ": "#8b5cf6", "PERI": "#a78bfa",
    "CONT": "#14b8a6", "DIODE": "#06b6d4",
    "CAP": "#ec4899",
}
FUNC_COLORS_ON = {
    "DCV": "#2563eb", "ACV": "#3b82f6",
    "DCI": "#ea580c", "ACI": "#f97316",
    "2WR": "#059669", "4WR": "#10b981",
    "FREQ": "#7c3aed", "PERI": "#8b5cf6",
    "CONT": "#0d9488", "DIODE": "#0891b2",
    "CAP": "#db2777",
}

_dpi_done = False


def _enable_dpi_awareness() -> None:
    """声明进程 DPI 感知，避免 Windows 位图拉伸导致字体模糊"""
    global _dpi_done
    if _dpi_done or sys.platform != "win32":
        return
    _dpi_done = True
    import ctypes
    try:
        # PER_MONITOR_AWARE_V2 (Win10 1703+)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self, demo: bool = False):
        _enable_dpi_awareness()
        super().__init__()
        self.title("RIGOL DM3058 / DM3058E 上位机")
        self.geometry("1360x900")
        self.minsize(1160, 780)
        self.configure(bg=BG)
        self._demo = demo

        self.ctrl = Dm3058Controller()
        self.ctrl.start()

        self.current_key = "DCV"
        self.connected = False
        self.last_value = None
        self.last_unit = "V"
        self.chart_on = True
        self._log_fp = None
        self._log_writer = None
        self._log_count = 0
        self._stats_on = False
        self._reading_count = 0

        self._apply_style()
        self._build_ui()
        self._sync_interface_fields()
        if demo:
            self.iface_var.set(IFACE_MOCK)
            self._sync_interface_fields()
        self.after(50, self._pump)

    # ------------------------------------------------------------ 样式
    def _apply_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base_font = (UI_FONT, 10)
        style.configure(".", font=base_font, background=BG, foreground=FG,
                        fieldbackground=CARD, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, troughcolor=FIELD,
                        insertcolor=FG, selectbackground=ACCENT, selectforeground="#ffffff",
                        arrowcolor=DIM)
        # 基础容器
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Card.TLabel", background=CARD, foreground=FG)
        style.configure("Dim.TLabel", background=BG, foreground=DIM, font=(UI_FONT, 9))
        style.configure("CardDim.TLabel", background=CARD, foreground=DIM,
                        font=(UI_FONT, 9))
        # 分组卡片：白底细边框
        style.configure("TLabelframe", background=CARD, foreground=DIM,
                        bordercolor=BORDER, relief="solid", borderwidth=1,
                        padding=10)
        style.configure("TLabelframe.Label", background=CARD, foreground=ACCENT,
                        font=(UI_FONT, 10, "bold"))
        # 通用按钮：白底描边
        style.configure("TButton", background=BTN, foreground=FG, borderwidth=1,
                        bordercolor=BORDER, focusthickness=0, focuscolor=BTN,
                        padding=(12, 6), font=(UI_FONT, 10))
        style.map("TButton",
                  background=[("active", BTN_H), ("pressed", "#dde3ea"),
                              ("disabled", FIELD)],
                  foreground=[("disabled", "#9ca3af")],
                  bordercolor=[("active", "#c5ccd6"), ("disabled", BORDER)])
        # 强调按钮（连接 / 开始记录等）
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        borderwidth=0, focusthickness=0, focuscolor=ACCENT,
                        padding=(16, 6), font=(UI_FONT, 10, "bold"))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_H), ("pressed", "#1d4ed8"),
                              ("disabled", "#93c5fd")],
                  foreground=[("disabled", "#eff6ff")])
        # 绿色主操作（连接）
        style.configure("Green.TButton", background=GREEN, foreground="#ffffff",
                        borderwidth=0, focusthickness=0, focuscolor=GREEN,
                        padding=(16, 6), font=(UI_FONT, 10, "bold"))
        style.map("Green.TButton",
                  background=[("active", "#0d9488"), ("pressed", "#047857"),
                              ("disabled", "#a7f3d0")],
                  foreground=[("disabled", "#ecfdf5")])
        # 红色（断开）
        style.configure("Red.TButton", background=ERR, foreground="#ffffff",
                        borderwidth=0, focusthickness=0, focuscolor=ERR,
                        padding=(14, 6), font=(UI_FONT, 10, "bold"))
        style.map("Red.TButton",
                  background=[("active", "#dc2626"), ("pressed", "#b91c1c"),
                              ("disabled", "#fecaca")],
                  foreground=[("disabled", "#fef2f2")])
        # 功能键：按类别彩色（未选中=白底彩边彩字，选中=实心彩色）
        for key, color in FUNC_COLORS.items():
            on = FUNC_COLORS_ON[key]
            style.configure(f"Func.{key}.TButton", background=CARD, foreground=color,
                            borderwidth=1, bordercolor=color, focusthickness=0,
                            focuscolor=CARD, padding=(6, 10), font=(UI_FONT, 10, "bold"))
            style.map(f"Func.{key}.TButton",
                      background=[("active", on), ("pressed", on)],
                      foreground=[("active", "#ffffff")],
                      bordercolor=[("active", on)])
            style.configure(f"FuncOn.{key}.TButton", background=on, foreground="#ffffff",
                            borderwidth=0, focusthickness=0, focuscolor=on,
                            padding=(6, 10), font=(UI_FONT, 10, "bold"))
            style.map(f"FuncOn.{key}.TButton",
                      background=[("active", on), ("pressed", on)])
        # 小彩色动作按钮（dB / dBm / P/F 等）
        style.configure("Purple.TButton", background=PURPLE, foreground="#ffffff",
                        borderwidth=0, padding=(8, 5), font=(UI_FONT, 9, "bold"))
        style.map("Purple.TButton", background=[("active", "#7c3aed")])
        style.configure("Orange.TButton", background=ORANGE, foreground="#ffffff",
                        borderwidth=0, padding=(8, 5), font=(UI_FONT, 9, "bold"))
        style.map("Orange.TButton", background=[("active", "#ea580c")])
        style.configure("Teal.TButton", background=TEAL, foreground="#ffffff",
                        borderwidth=0, padding=(8, 5), font=(UI_FONT, 9, "bold"))
        style.map("Teal.TButton", background=[("active", "#0d9488")])
        # 选择类控件
        style.configure("TCheckbutton", background=CARD, foreground=FG,
                        focuscolor=CARD, borderwidth=0, padding=(2, 3))
        style.map("TCheckbutton", background=[("active", CARD)],
                  foreground=[("active", FG), ("disabled", "#9ca3af")])
        style.configure("TRadiobutton", background=CARD, foreground=FG,
                        focuscolor=CARD, borderwidth=0, padding=(2, 3))
        style.map("TRadiobutton", background=[("active", CARD)])
        style.configure("TRadiobutton.Panel.TLabel", background=CARD)
        # 下拉 / 输入
        style.configure("TCombobox", fieldbackground=CARD, background=BTN,
                        foreground=FG, arrowcolor=DIM, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, borderwidth=1,
                        padding=5, font=(UI_FONT, 10))
        style.map("TCombobox",
                  fieldbackground=[("readonly", CARD), ("disabled", FIELD)],
                  foreground=[("readonly", FG), ("disabled", "#9ca3af")],
                  selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", FG)],
                  arrowcolor=[("disabled", "#9ca3af")])
        style.configure("TEntry", fieldbackground=CARD, foreground=FG,
                        insertcolor=FG, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, borderwidth=1, padding=5)
        style.map("TEntry", bordercolor=[("focus", ACCENT)],
                  lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
        style.configure("TSpinbox", fieldbackground=CARD, foreground=FG,
                        arrowcolor=DIM, bordercolor=BORDER, borderwidth=1, padding=5)
        style.map("TSpinbox", bordercolor=[("focus", ACCENT)],
                  background=[("active", BTN_H)])
        # Notebook 页签
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(6, 6, 6, 0))
        style.configure("TNotebook.Tab", background=FIELD, foreground=DIM,
                        borderwidth=0, padding=(18, 9), font=(UI_FONT, 10))
        style.map("TNotebook.Tab",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        # 滚动条
        style.configure("Vertical.TScrollbar", background=FIELD, troughcolor=BG,
                        bordercolor=BG, arrowcolor=DIM, borderwidth=0)
        style.map("Vertical.TScrollbar", background=[("active", "#cfd6de")])

    # ------------------------------------------------------------ UI 构建
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0, minsize=330)  # 右栏保底宽度，防内容被挤成色条
        self.rowconfigure(1, weight=1)

        self._build_conn_bar()
        self._build_left_panel()
        self._build_center()
        self._build_right_panel()
        self._build_bottom()

    def _build_conn_bar(self) -> None:
        bar = ttk.LabelFrame(self, text="连接")
        bar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(6, 2))
        for i in range(20):
            bar.columnconfigure(i, weight=0)
        bar.columnconfigure(8, weight=1)

        ttk.Label(bar, text="接口:", style="Card.TLabel").grid(row=0, column=0, padx=(8, 2), pady=4)
        self.iface_var = tk.StringVar(value=IFACE_SERIAL)
        self.iface_box = ttk.Combobox(bar, textvariable=self.iface_var, values=[
            IFACE_SERIAL, IFACE_LAN, IFACE_USB, IFACE_MOCK], width=18, state="readonly")
        self.iface_box.grid(row=0, column=1, padx=2)
        self.iface_box.bind("<<ComboboxSelected>>", lambda e: self._sync_interface_fields())

        # 串口参数
        self.serial_fr = ttk.Frame(bar)
        self.serial_fr.grid(row=0, column=2, columnspan=4, sticky="w")
        ttk.Label(self.serial_fr, text="端口:", style="Card.TLabel").pack(side="left", padx=(6, 2))
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(self.serial_fr, textvariable=self.port_var, width=12)
        self.port_box.pack(side="left")
        ttk.Button(self.serial_fr, text="刷新", width=5,
                   command=self._refresh_ports).pack(side="left", padx=2)
        ttk.Label(self.serial_fr, text="波特率:", style="Card.TLabel").pack(side="left", padx=(6, 2))
        self.baud_var = tk.StringVar(value="9600")
        ttk.Combobox(self.serial_fr, textvariable=self.baud_var, width=7, state="readonly",
                     values=["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]
                     ).pack(side="left")
        ttk.Label(self.serial_fr, text="校验:", style="Card.TLabel").pack(side="left", padx=(6, 2))
        self.parity_var = tk.StringVar(value="N（8 位）")
        ttk.Combobox(self.serial_fr, textvariable=self.parity_var, width=10, state="readonly",
                     values=["N（8 位）", "O（7 位）", "E（7 位）"]).pack(side="left")

        # LAN 参数
        self.lan_fr = ttk.Frame(bar)
        self.lan_fr.grid(row=0, column=2, columnspan=4, sticky="w")
        ttk.Label(self.lan_fr, text="IP:", style="Card.TLabel").pack(side="left", padx=(6, 2))
        self.ip_var = tk.StringVar(value="192.168.1.100")
        ttk.Entry(self.lan_fr, textvariable=self.ip_var, width=14).pack(side="left")
        ttk.Label(self.lan_fr, text="端口:", style="Card.TLabel").pack(side="left", padx=(6, 2))
        self.tcp_port_var = tk.StringVar(value="5025")
        ttk.Entry(self.lan_fr, textvariable=self.tcp_port_var, width=6).pack(side="left")

        # USB 参数（VISA 资源优先，pyusb 设备备选）
        self.usb_fr = ttk.Frame(bar)
        self.usb_fr.grid(row=0, column=2, columnspan=4, sticky="w")
        ttk.Label(self.usb_fr, text="设备:", style="Card.TLabel").pack(side="left", padx=(6, 2))
        self.usb_var = tk.StringVar(value="扫描中…")
        self.usb_box = ttk.Combobox(self.usb_fr, textvariable=self.usb_var, width=44)
        self.usb_box.pack(side="left")
        ttk.Button(self.usb_fr, text="扫描", width=5,
                   command=self._refresh_usb).pack(side="left", padx=2)
        self._usb_targets = {}  # label -> ("visa", res) | ("pyusb", vid, pid)

        self.mock_fr = ttk.Frame(bar)
        self.mock_fr.grid(row=0, column=2, columnspan=4, sticky="w")
        ttk.Label(self.mock_fr, text="软件模拟器：无硬件时演示界面与指令流程",
                  foreground=DIM, style="CardDim.TLabel").pack(side="left", padx=8)

        self.btn_connect = ttk.Button(bar, text="连接", style="Green.TButton",
                                      command=self._on_connect)
        self.btn_connect.grid(row=0, column=6, padx=6)
        self.btn_disconnect = ttk.Button(bar, text="断开", style="Red.TButton",
                                         command=self._on_disconnect, state="disabled")
        self.btn_disconnect.grid(row=0, column=7, padx=2)

        self.idn_var = tk.StringVar(value="未连接")
        idn = ttk.Label(bar, textvariable=self.idn_var, foreground=ACCENT,
                        style="Card.TLabel", font=(UI_FONT, 10, "bold"))
        idn.grid(row=0, column=8, sticky="w", padx=10)

        tools = ttk.Frame(bar)
        tools.grid(row=0, column=9, columnspan=4, sticky="e", padx=6)
        ttk.Button(tools, text="复位 *RST", command=lambda: self.ctrl.write("*RST")).pack(side="left", padx=2)
        ttk.Button(tools, text="清状态 *CLS", command=lambda: self.ctrl.write("*CLS")).pack(side="left", padx=2)
        ttk.Button(tools, text="查询错误", command=self._poll_errors).pack(side="left", padx=2)
        ttk.Button(tools, text="蜂鸣测试", command=lambda: self.ctrl.write("SYSTem:BEEPer")).pack(side="left", padx=2)
        self._refresh_ports()

    def _build_left_panel(self) -> None:
        left = ttk.LabelFrame(self, text="测量设置")
        left.grid(row=1, column=0, sticky="nsw", padx=6, pady=4)

        ttk.Label(left, text="测量功能", font=(UI_FONT, 10, "bold"),
                  style="Card.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))
        self.func_buttons = {}
        for i, f in enumerate(FUNCTIONS):
            b = ttk.Button(left, text=f.label, width=10,
                           style=f"Func.{f.key}.TButton",
                           command=lambda k=f.key: self._select_function(k))
            b.grid(row=1 + i // 2, column=i % 2, padx=4, pady=3, sticky="ew")
            self.func_buttons[f.key] = b

        fr = ttk.LabelFrame(left, text="量程 / 速率")
        fr.grid(row=7, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        ttk.Label(fr, text="量程:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.range_var = tk.StringVar(value="自动量程")
        self.range_box = ttk.Combobox(fr, textvariable=self.range_var, width=14, state="readonly")
        self.range_box.grid(row=0, column=1, padx=6, pady=4)
        self.btn_apply_range = ttk.Button(fr, text="应用量程", command=self._apply_range)
        self.btn_apply_range.grid(row=0, column=2, padx=4, pady=4)

        ttk.Label(fr, text="速率:", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.rate_var = tk.StringVar(value="M")
        rate_fr = ttk.Frame(fr)
        rate_fr.grid(row=1, column=1, columnspan=2, sticky="w", padx=4)
        for val, label in RATE_CHOICES:
            ttk.Radiobutton(rate_fr, text=label, value=val, variable=self.rate_var,
                            command=self._apply_rate).pack(side="left", padx=2)

        self.filter_var = tk.BooleanVar(value=False)
        self.chk_filter = ttk.Checkbutton(fr, text="交流滤波", variable=self.filter_var,
                                          command=self._apply_filter)
        self.chk_filter.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        ttk.Label(fr, text="DC 输入阻抗:", style="Card.TLabel").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.imp_var = tk.StringVar(value="10M")
        imp_fr = ttk.Frame(fr)
        imp_fr.grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(imp_fr, text="10MΩ", value="10M", variable=self.imp_var,
                        command=self._apply_impedance).pack(side="left")
        ttk.Radiobutton(imp_fr, text=">10GΩ", value="10G", variable=self.imp_var,
                        command=self._apply_impedance).pack(side="left", padx=4)

        ttk.Label(fr, text="通断极限(Ω):", style="Card.TLabel").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        self.cont_var = tk.StringVar(value="10")
        self.cont_spin = ttk.Spinbox(fr, from_=1, to=2000, textvariable=self.cont_var, width=8)
        self.cont_spin.grid(row=4, column=1, sticky="w", padx=6, pady=4)

        # 双显
        dual = ttk.LabelFrame(left, text="双显 (FUNCtion2)")
        dual.grid(row=8, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
        self.dual_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dual, text="启用双显", variable=self.dual_var,
                        command=self._apply_dual).pack(anchor="w", padx=6, pady=3)
        ttk.Label(dual, text="副显示:", style="Card.TLabel").pack(anchor="w", padx=6)
        self.dual_func_var = tk.StringVar(value="交流电压")
        dual_keys = [FUNC_BY_KEY[k].label for k in DUAL_SECONDARY_KEYS]
        self.dual_box = ttk.Combobox(dual, textvariable=self.dual_func_var,
                                     values=dual_keys, state="readonly", width=10)
        self.dual_box.pack(anchor="w", padx=6, pady=2)
        ttk.Button(dual, text="应用双显", command=self._apply_dual).pack(anchor="w", padx=6, pady=3)

        # 采样
        opts = ttk.LabelFrame(left, text="采样")
        opts.grid(row=9, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
        ttk.Label(opts, text="间隔(秒):", style="Card.TLabel").grid(row=0, column=0, padx=6, pady=4)
        self.interval_var = tk.StringVar(value="0.2")
        self.interval_spin = ttk.Spinbox(opts, from_=0.05, to=10, increment=0.05,
                                         textvariable=self.interval_var, width=6)
        self.interval_spin.grid(row=0, column=1, sticky="w")
        ttk.Button(opts, text="应用并重启监测", command=self._restart_monitor).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=4)

        self.notes_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.notes_var, wraplength=200,
                  foreground=DIM, justify="left", style="Dim.TLabel").grid(
            row=10, column=0, columnspan=2, sticky="ew", padx=8, pady=(6, 8))

    def _build_center(self) -> None:
        mid = ttk.Frame(self)
        mid.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        mid.rowconfigure(1, weight=1)
        mid.columnconfigure(0, weight=1)

        readout = tk.Frame(mid, bg=CARD, bd=0, highlightthickness=1,
                           highlightbackground=BORDER)
        readout.grid(row=0, column=0, sticky="ew")
        readout.columnconfigure(1, weight=1)

        self.func_disp = tk.Label(readout, text="直流电压", font=(UI_FONT, 14, "bold"),
                                  fg=ACCENT, bg=CARD)
        self.func_disp.grid(row=0, column=0, sticky="w", padx=18, pady=(12, 0))
        self.range_disp = tk.Label(readout, text="自动量程", font=(UI_FONT, 11),
                                   fg=DIM, bg=CARD)
        self.range_disp.grid(row=0, column=1, sticky="e", padx=18, pady=(12, 0))
        self.value_disp = tk.Label(readout, text="----", font=(MONO, 42, "bold"),
                                   fg=LCD_FG, bg=CARD)
        self.value_disp.grid(row=1, column=0, columnspan=2, sticky="w", padx=18, pady=(4, 0))
        self.secondary_disp = tk.Label(readout, text="", font=(MONO, 15),
                                       fg=DIM, bg=CARD)
        self.secondary_disp.grid(row=2, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 4))
        self.status_disp = tk.Label(readout, text="", font=(UI_FONT, 10),
                                    fg=DIM, bg=CARD)
        self.status_disp.grid(row=3, column=0, columnspan=2, sticky="w", padx=18, pady=(0, 10))

        chart_fr = ttk.Frame(mid)
        chart_fr.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        chart_bar = ttk.Frame(chart_fr)
        chart_bar.pack(fill="x")
        ttk.Label(chart_bar, text="实时趋势").pack(side="left", padx=6)
        self.btn_chart = ttk.Button(chart_bar, text="暂停曲线",
                                    command=self._toggle_chart)
        self.btn_chart.pack(side="left", padx=2)
        ttk.Button(chart_bar, text="清空", command=lambda: self.chart.clear()).pack(side="left", padx=2)
        ttk.Label(chart_bar, text="点数:").pack(side="left", padx=(10, 2))
        self.pts_var = tk.StringVar(value="300")
        pts = ttk.Combobox(chart_bar, textvariable=self.pts_var, width=6, state="readonly",
                           values=["100", "200", "300", "500", "1000"])
        pts.pack(side="left")
        pts.bind("<<ComboboxSelected>>",
                 lambda e: self.chart.set_max_points(int(self.pts_var.get())))
        self.chk_log_disp = tk.BooleanVar(value=True)
        ttk.Checkbutton(chart_bar, text="记录到CSV", variable=self.chk_log_disp).pack(
            side="left", padx=10)

        self.chart = TrendChart(chart_fr, max_points=300)
        self.chart.pack(fill="both", expand=True, pady=4)

    def _build_right_panel(self) -> None:
        # 可滚动右栏，避免矮窗口下文字被裁切
        right = ttk.Frame(self)
        right.grid(row=1, column=2, sticky="nsew", padx=6, pady=4)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        canvas = tk.Canvas(right, bg=BG, highlightthickness=0, width=280)
        sb = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        canvas.grid(row=0, column=0, sticky="nsew")
        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_width(event):
            canvas.itemconfigure(win_id, width=event.width)
        canvas.bind("<Configure>", _sync_width)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        # 鼠标滚轮
        def _on_wheel(event):
            if event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel, add="+")

        math = ttk.LabelFrame(inner, text="数学运算")
        math.pack(fill="x", pady=(0, 6), padx=2)
        math.columnconfigure(1, weight=1)   # 输入列吃掉多余宽度，按钮列不被挤压

        ttk.Label(math, text="功能:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        self.math_var = tk.StringVar(value="关闭")
        self.math_box = ttk.Combobox(math, textvariable=self.math_var,
                                     values=[lab for _, lab in MATH_CHOICES],
                                     state="readonly", width=11)
        self.math_box.grid(row=0, column=1, columnspan=2, sticky="ew",
                           padx=4, pady=4)
        ttk.Button(math, text="应用所选数学功能", style="Accent.TButton",
                   command=self._apply_math).grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 4))

        ttk.Button(math, text="以当前读数为 REL 基准",
                   command=self._apply_rel).grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=6, pady=4)

        ttk.Label(math, text="dB 参考:", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", padx=6, pady=3)
        self.db_ref_var = tk.StringVar(value="1.0")
        ttk.Entry(math, textvariable=self.db_ref_var, width=8).grid(
            row=3, column=1, sticky="ew", padx=4)
        ttk.Button(math, text="dB", width=4, style="Purple.TButton",
                   command=self._apply_db).grid(row=3, column=2, padx=4)

        ttk.Label(math, text="dBm 参考R:", style="Card.TLabel").grid(
            row=4, column=0, sticky="w", padx=6, pady=3)
        self.dbm_ref_var = tk.StringVar(value="50")
        ttk.Entry(math, textvariable=self.dbm_ref_var, width=8).grid(
            row=4, column=1, sticky="ew", padx=4)
        ttk.Button(math, text="dBm", width=4, style="Purple.TButton",
                   command=self._apply_dbm).grid(row=4, column=2, padx=4)

        ttk.Label(math, text="P/F 下限:", style="Card.TLabel").grid(
            row=5, column=0, sticky="w", padx=6, pady=3)
        self.pf_low_var = tk.StringVar(value="0")
        ttk.Entry(math, textvariable=self.pf_low_var, width=8).grid(
            row=5, column=1, columnspan=2, sticky="ew", padx=4)
        ttk.Label(math, text="P/F 上限:", style="Card.TLabel").grid(
            row=6, column=0, sticky="w", padx=6, pady=3)
        self.pf_high_var = tk.StringVar(value="1")
        ttk.Entry(math, textvariable=self.pf_high_var, width=8).grid(
            row=6, column=1, sticky="ew", padx=4)
        ttk.Button(math, text="P/F 判定", style="Orange.TButton",
                   command=self._apply_pf).grid(row=6, column=2, padx=4, pady=3)

        stats = ttk.LabelFrame(inner, text="统计")
        stats.pack(fill="x", pady=(0, 6), padx=2)
        self.stats_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(stats, text="启用统计 (MIN/MAX/AVG/COUNT)",
                        variable=self.stats_var,
                        command=self._toggle_stats).pack(anchor="w", padx=8, pady=4)
        self.stat_min_var = tk.StringVar(value="MIN  —")
        self.stat_max_var = tk.StringVar(value="MAX  —")
        self.stat_avg_var = tk.StringVar(value="AVG  —")
        self.stat_cnt_var = tk.StringVar(value="CNT  —")
        for var in (self.stat_min_var, self.stat_max_var,
                    self.stat_avg_var, self.stat_cnt_var):
            ttk.Label(stats, textvariable=var, font=(MONO, 10),
                      style="Card.TLabel").pack(anchor="w", padx=12, pady=2)

        logf = ttk.LabelFrame(inner, text="CSV 数据记录")
        logf.pack(fill="x", pady=(0, 8), padx=2)
        self.csv_path_var = tk.StringVar()
        ttk.Entry(logf, textvariable=self.csv_path_var, width=26).grid(
            row=0, column=0, columnspan=2, padx=6, pady=4)
        ttk.Button(logf, text="浏览…", command=self._browse_csv).grid(row=0, column=2, padx=4)
        btns = ttk.Frame(logf, style="Card.TFrame")
        btns.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6, pady=4)
        ttk.Button(btns, text="开始记录", style="Green.TButton",
                   command=self._start_log).pack(side="left", padx=2)
        ttk.Button(btns, text="停止", style="Red.TButton",
                   command=self._stop_log).pack(side="left", padx=2)
        self.log_count_var = tk.StringVar(value="已记录 0 条")
        ttk.Label(logf, textvariable=self.log_count_var, foreground=DIM,
                  style="CardDim.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 4))

    def _build_bottom(self) -> None:
        nb = ttk.Notebook(self)
        nb.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=6, pady=(2, 6))
        self.rowconfigure(2, weight=0)

        console = ttk.Frame(nb)
        nb.add(console, text="SCPI 控制台")
        console.rowconfigure(0, weight=1)
        console.columnconfigure(0, weight=1)

        self.console = tk.Text(console, height=7, wrap="word",
                               font=(MONO, 10), state="disabled",
                               bg=CONSOLE_BG, fg=CONSOLE_FG,
                               insertbackground=CONSOLE_FG, relief="flat",
                               highlightthickness=1, highlightbackground=BORDER,
                               selectbackground=ACCENT, selectforeground="#ffffff",
                               padx=8, pady=6)
        self.console.tag_configure("tx", foreground="#7dd3fc")
        self.console.tag_configure("rx", foreground="#6ee7b7")
        self.console.tag_configure("err", foreground="#fca5a5")
        self.console.tag_configure("sys", foreground="#fcd34d")
        self.console.grid(row=0, column=0, sticky="nsew", padx=(6, 2), pady=6)
        sb = ttk.Scrollbar(console, command=self.console.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self.console.configure(yscrollcommand=sb.set)

        entry_fr = ttk.Frame(console)
        entry_fr.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 4))
        self.cmd_var = tk.StringVar()
        e = ttk.Entry(entry_fr, textvariable=self.cmd_var, font=(MONO, 10))
        e.pack(side="left", fill="x", expand=True, padx=(6, 4), pady=4)
        e.bind("<Return>", lambda ev: self._send_query())
        ttk.Button(entry_fr, text="查询", command=self._send_query).pack(side="left", padx=2, pady=4)
        ttk.Button(entry_fr, text="发送", command=self._send_write).pack(side="left", padx=2, pady=4)
        ttk.Button(entry_fr, text="清空日志", command=self._clear_console).pack(side="left", padx=2, pady=4)

        help_fr = ttk.Frame(nb)
        nb.add(help_fr, text="使用说明")
        txt = (
            "快速上手\n"
            "1. 用 USB 线 / RS-232 串口线 / 网线连接 DM3058，仪器开机。\n"
            "2. 选择接口后点「连接」；连接成功会显示仪器 *IDN? 信息。\n"
            "3. 点左侧功能按钮切换测量功能；可设量程、速率、滤波等。\n"
            "4. 大读数区实时刷新；趋势曲线自动跟随；「记录到CSV」勾选后可导出。\n"
            "5. 数学运算区支持 REL / 统计 / dB / dBm / P-F 判定（RIGOL 命令集）。\n"
            "6. 底部 SCPI 控制台可手发任意指令；查询按钮自动读取响应。\n\n"
            "接口参数\n"
            "· RS-232：默认 9600 波特；选择 O/E 校验时仪器侧为 7 数据位（手册规定）。\n"
            "· LAN：SCPI Socket 默认端口 5025（在仪器 System→Interface 中确认 LAN 设置）。\n"
            "· USB-TMC：Windows 下建议用 Zadig 把设备绑定为 WinUSB 或 libusbK 驱动。\n\n"
            "常用指令（RIGOL 命令集，连接时已自动 CMDSET RIGOL）\n"
            "  *IDN?  :FUNCtion?  :MEASure:VOLTage:DC?  :MEASure AUTO\n"
            "  :RATE:VOLTage:DC M   :CALCulate:FUNCtion AVERAGE\n"
            "  :CALCulate:STATistic:AVERage?   SYSTem:ERR?\n"
        )
        tk.Label(help_fr, text=txt, justify="left", font=(UI_FONT, 10),
                 anchor="w", bg=BG, fg=FG).pack(fill="both", expand=True, padx=12, pady=10)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status_var, anchor="w",
                  background=CARD, foreground=DIM, padding=(12, 6),
                  font=(UI_FONT, 9)).grid(
            row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=(2, 6))

    # ------------------------------------------------------------ 连接
    def _refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.port_box["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _refresh_usb(self) -> None:
        """扫描 VISA 资源 + pyusb 设备，结果写入下拉与控制台"""
        targets = {}
        labels = []

        visa_res = list_visa_resources()
        for res in visa_res:
            label = f"[VISA] {res}"
            targets[label] = ("visa", res)
            labels.append(label)

        usb_stat = pyusb_status()
        pyusb_devs = list_usb_tmc_devices()
        for name, vid, pid in pyusb_devs:
            label = f"[pyusb] {name}"
            targets[label] = ("pyusb", vid, pid)
            labels.append(label)

        if labels:
            labels.insert(0, "自动匹配（优先 VISA）")
            default = labels[0]
        else:
            default = "（未发现设备）"
        self._usb_targets = targets
        self.usb_box["values"] = labels or [default]
        self.usb_var.set(default)

        # 诊断信息写进控制台，便于排查
        self._console_sys(f"USB 扫描: VISA 资源 {len(visa_res)} 个, pyusb 设备 {len(pyusb_devs)} 个")
        self._console_sys(f"pyusb 状态: {usb_stat}")
        if not labels and "正常" not in usb_stat:
            self._console_sys(
                "提示: pyusb 无法枚举时请用 NI-VISA（仪器面板可查 USB0::VID::PID::SN 资源），"
                "或用 Zadig 将设备换绑 WinUSB")
        if visa_res and not pyusb_devs:
            self._console_sys("已发现 VISA 资源，选择后点「连接」即可")

    def _auto_usb_factory(self):
        """自动匹配：VISA 优先，其次 pyusb"""
        visa_res = list_visa_resources()
        if visa_res:
            return lambda: VisaTransport(visa_res[0])
        return lambda: UsbTmcTransport(None, None)

    def _sync_interface_fields(self) -> None:
        for fr in (self.serial_fr, self.lan_fr, self.usb_fr, self.mock_fr):
            fr.grid_remove()
        iface = self.iface_var.get()
        if iface == IFACE_SERIAL:
            self.serial_fr.grid()
        elif iface == IFACE_LAN:
            self.lan_fr.grid()
        elif iface == IFACE_USB:
            self.usb_fr.grid()
            self._refresh_usb()
        else:
            self.mock_fr.grid()

    def _on_connect(self) -> None:
        iface = self.iface_var.get()
        try:
            if iface == IFACE_SERIAL:
                parity = "N" if self.parity_var.get().startswith("N") else (
                    "O" if self.parity_var.get().startswith("O") else "E")
                port = self.port_var.get()
                if not port:
                    raise ValueError("请选择串口")
                baud = int(self.baud_var.get())
                factory = lambda: SerialTransport(port, baud, parity)  # noqa: E731
            elif iface == IFACE_LAN:
                host = self.ip_var.get().strip()
                port = int(self.tcp_port_var.get())
                if not host:
                    raise ValueError("请填写 IP")
                factory = lambda: TcpTransport(host, port)  # noqa: E731
            elif iface == IFACE_USB:
                label = self.usb_var.get()
                target = getattr(self, "_usb_targets", {}).get(label)
                if target is not None and target[0] == "visa":
                    res = target[1]
                    factory = lambda: VisaTransport(res)  # noqa: E731
                elif target is not None and target[0] == "pyusb":
                    _, vid, pid = target
                    factory = lambda: UsbTmcTransport(vid, pid)  # noqa: E731
                else:
                    factory = self._auto_usb_factory()
            else:
                factory = MockTransport
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("连接参数错误", str(e))
            return
        self.btn_connect.configure(state="disabled")
        self.status_var.set("正在连接…")
        self.ctrl.connect(factory)

    def _on_disconnect(self) -> None:
        self._restart_monitor(enable=False)
        self.ctrl.disconnect()

    def _poll_errors(self) -> None:
        self.ctrl.query("SYSTem:ERR?", token="error_queue")
        self.ctrl.query("SYSTem:ERR?", token="error_queue2")

    # ------------------------------------------------------------ 功能/设置
    def _select_function(self, key: str) -> None:
        # 先停旧监测，防止“UI 已切档、后台仍用旧指令采样”的竞态
        # （否则会出现旧量程电压值按电流单位显示的假尖峰）
        self.ctrl.set_monitor(False, 0.2, [], key=self.current_key)
        self.current_key = key
        fdef = FUNC_BY_KEY[key]
        self.last_unit = fdef.unit
        self.chart.set_unit(fdef.unit)
        self.chart.clear()   # 切功能清空曲线，避免旧功能数据撑爆坐标轴
        for k, b in self.func_buttons.items():
            b.configure(style=f"FuncOn.{key}.TButton" if k == key else f"Func.{k}.TButton")
        # 量程下拉
        if fdef.range_cmd is None:
            self.range_box.configure(state="disabled")
            self.range_var.set("固定")
            self.btn_apply_range.configure(state="disabled")
        elif key == "CONT":
            self.range_box.configure(state="disabled")
            self.range_var.set("极限电阻")
            self.btn_apply_range.configure(state="normal")
        else:
            self.range_box.configure(state="readonly")
            values = ["自动量程"] + [f"{i} · {lab}" for i, lab in fdef.ranges]
            self.range_box["values"] = values
            self.range_var.set("自动量程")
            self.btn_apply_range.configure(state="normal")
        self.range_disp.configure(text="自动量程")
        self.func_disp.configure(text=fdef.label)
        self.notes_var.set(fdef.notes)
        # 能力开关
        self.chk_filter.configure(state="normal" if fdef.filter_cmd else "disabled")
        if not fdef.filter_cmd:
            self.filter_var.set(False)
        rate_ok = fdef.rate_cmd is not None
        self.status_disp.configure(
            text=("速率可用" if rate_ok else "该功能无速率设置"))
        # 发送指令
        self.ctrl.write(fdef.func_cmd)
        self._apply_range()
        self._apply_rate()
        if fdef.filter_cmd:
            self._apply_filter()
        if key == "DCV":
            self._apply_impedance()
        if self.dual_var.get():
            self._apply_dual()
        self._restart_monitor()

    def _range_index(self) -> int | None:
        text = self.range_var.get()
        if not text or text.startswith("自动") or text in ("固定", "极限电阻"):
            return None
        try:
            return int(text.split("·")[0].strip())
        except ValueError:
            return None

    def _apply_range(self) -> None:
        fdef = FUNC_BY_KEY[self.current_key]
        if fdef.range_cmd is None:
            return
        if self.current_key == "CONT":
            try:
                lim = max(1, min(2000, int(float(self.cont_var.get()))))
            except ValueError:
                lim = 10
            self.ctrl.write(f"{fdef.range_cmd} {lim}")
            self.range_disp.configure(text=f"极限 {lim} Ω")
            return
        idx = self._range_index()
        if idx is None:
            self.ctrl.write(":MEASure AUTO")
            self.range_disp.configure(text="自动量程")
        else:
            self.ctrl.write(f"{fdef.range_cmd} {idx}")
            label = dict(fdef.ranges).get(idx, str(idx))
            self.range_disp.configure(text=label)
        self._restart_monitor()

    def _apply_rate(self) -> None:
        fdef = FUNC_BY_KEY[self.current_key]
        if not fdef.rate_cmd:
            return
        self.ctrl.write(f"{fdef.rate_cmd} {self.rate_var.get()}")
        self._restart_monitor()

    def _apply_filter(self) -> None:
        fdef = FUNC_BY_KEY[self.current_key]
        if not fdef.filter_cmd:
            return
        self.ctrl.write(f"{fdef.filter_cmd} {'ON' if self.filter_var.get() else 'OFF'}")

    def _apply_impedance(self) -> None:
        if self.current_key != "DCV":
            return
        self.ctrl.write(f":MEASure:VOLTage:DC:IMPEdance {self.imp_var.get()}")

    def _apply_dual(self) -> None:
        if not self.dual_var.get():
            self.ctrl.write(":FUNCtion2:CLEAR")
            self.secondary_disp.configure(text="")
            self._restart_monitor()
            return
        label = self.dual_func_var.get()
        key = next((k for k in DUAL_SECONDARY_KEYS if FUNC_BY_KEY[k].label == label), "ACV")
        self.ctrl.write(FUNC_BY_KEY[key].dual_cmd)
        self.secondary_disp.configure(text=f"双显: {FUNC_BY_KEY[key].label}")
        self._restart_monitor()

    def _monitor_cmds(self) -> list:
        if self.dual_var.get():
            return [":FUNCtion2:VALUe1?", ":FUNCtion2:VALUe2?"]
        return [FUNC_BY_KEY[self.current_key].measure_cmd]

    def _restart_monitor(self, enable: bool | None = None) -> None:
        if enable is None:
            enable = self.connected
        try:
            interval = float(self.interval_var.get())
        except ValueError:
            interval = 0.2
        self.ctrl.set_monitor(enable, interval,
                              self._monitor_cmds() if enable else [],
                              key=self.current_key)

    # ------------------------------------------------------------ 数学/统计
    def _apply_math(self) -> None:
        label = self.math_var.get()
        key = next((k for k, lab in MATH_CHOICES if lab == label), "NONE")
        self.ctrl.write(f":CALCulate:FUNCtion {key}")
        if key in ("MIN", "MAX", "AVERAGE", "TOTAL"):
            self.ctrl.write(":CALCulate:STATistic:STATe ON")
            self.stats_var.set(True)
            self._stats_on = True
        if key == "NONE":
            self.ctrl.write(":CALCulate:REL:STATe OFF")
            self.ctrl.write(":CALCulate:DB:STATe OFF")
            self.ctrl.write(":CALCulate:DBM:STATe OFF")
            self.ctrl.write(":CALCulate:PF:STATe OFF")

    def _apply_rel(self) -> None:
        if self.last_value is None:
            messagebox.showinfo("REL", "尚无读数，请先连接并开始测量")
            return
        self.ctrl.write(f":CALCulate:REL:OFFSet {self.last_value!r}")
        self.ctrl.write(":CALCulate:REL:STATe ON")
        self.ctrl.write(":CALCulate:FUNCtion REL")
        self.math_var.set("相对 (REL)")
        self.status_disp.configure(text=f"REL 基准 = {self.last_value:.6g}")

    def _apply_db(self) -> None:
        try:
            ref = float(self.db_ref_var.get())
        except ValueError:
            messagebox.showerror("dB", "参考值无效")
            return
        self.ctrl.write(f":CALCulate:DB:REFErence {ref!r}")
        self.ctrl.write(":CALCulate:DB:STATe ON")
        self.ctrl.write(":CALCulate:FUNCtion DB")
        self.math_var.set("dB")

    def _apply_dbm(self) -> None:
        try:
            ref = float(self.dbm_ref_var.get())
        except ValueError:
            messagebox.showerror("dBm", "参考电阻无效")
            return
        self.ctrl.write(f":CALCulate:DBM:REFErence {ref!r}")
        self.ctrl.write(":CALCulate:DBM:STATe ON")
        self.ctrl.write(":CALCulate:FUNCtion DBM")
        self.math_var.set("dBm")

    def _apply_pf(self) -> None:
        try:
            lo = float(self.pf_low_var.get())
            hi = float(self.pf_high_var.get())
        except ValueError:
            messagebox.showerror("P/F", "上下限无效")
            return
        if hi <= lo:
            messagebox.showerror("P/F", "上限必须大于下限")
            return
        self.ctrl.write(f":CALCulate:PF:LOWEr {lo!r}")
        self.ctrl.write(f":CALCulate:PF:UPPEr {hi!r}")
        self.ctrl.write(":CALCulate:PF:STATe ON")
        self.ctrl.write(":CALCulate:FUNCtion PF")
        self.math_var.set("P/F 判定")

    def _toggle_stats(self) -> None:
        self._stats_on = self.stats_var.get()
        self.ctrl.write(f":CALCulate:STATistic:STATe {'ON' if self._stats_on else 'OFF'}")
        if self._stats_on:
            self.ctrl.write(":CALCulate:FUNCtion AVERAGE")
            self.math_var.set("平均值")

    def _refresh_stats(self) -> None:
        if not (self.connected and self._stats_on):
            return
        self.ctrl.query(":CALCulate:STATistic:MIN?", token="stat_min")
        self.ctrl.query(":CALCulate:STATistic:MAX?", token="stat_max")
        self.ctrl.query(":CALCulate:STATistic:AVERage?", token="stat_avg")
        self.ctrl.query(":CALCulate:STATistic:COUNt?", token="stat_cnt")

    # ------------------------------------------------------------ 曲线/CSV
    def _toggle_chart(self) -> None:
        self.chart_on = not self.chart_on
        self.btn_chart.configure(text="暂停曲线" if self.chart_on else "继续曲线")

    def _browse_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"dm3058_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            filetypes=[("CSV 文件", "*.csv")])
        if path:
            self.csv_path_var.set(path)

    def _start_log(self) -> None:
        if self._log_fp:
            return
        path = self.csv_path_var.get().strip()
        if not path:
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "logs")
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, f"dm3058_{time.strftime('%Y%m%d_%H%M%S')}.csv")
            self.csv_path_var.set(path)
        try:
            self._log_fp = open(path, "w", newline="", encoding="utf-8-sig")
            self._log_writer = csv.writer(self._log_fp)
            self._log_writer.writerow(["时间戳", "功能", "读数", "单位", "副读数"])
            self._log_count = 0
            self.log_count_var.set(f"记录中 → {os.path.basename(path)}")
            self._console_sys(f"CSV 记录开始: {path}")
        except OSError as e:
            messagebox.showerror("CSV", f"无法写入文件: {e}")

    def _stop_log(self) -> None:
        if self._log_fp:
            try:
                self._log_fp.close()
            except OSError:
                pass
            self._log_fp = None
            self._log_writer = None
            self.log_count_var.set(f"已停止，共 {self._log_count} 条")
            self._console_sys(f"CSV 记录停止，共 {self._log_count} 条")

    def _write_csv(self, value: float, ts: float, secondary) -> None:
        if not self._log_writer:
            return
        fdef = FUNC_BY_KEY[self.current_key]
        self._log_writer.writerow([
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + f".{int(ts % 1 * 1000):03d}",
            fdef.label, f"{value:.6e}", fdef.unit,
            "" if secondary is None else f"{secondary:.6e}",
        ])
        self._log_count += 1
        if self._log_count % 20 == 0 and self._log_fp:
            self._log_fp.flush()
        self.log_count_var.set(f"已记录 {self._log_count} 条")

    # ------------------------------------------------------------ 控制台
    def _send_write(self) -> None:
        cmd = self.cmd_var.get().strip()
        if cmd:
            self.ctrl.write(cmd)

    def _send_query(self) -> None:
        cmd = self.cmd_var.get().strip()
        if cmd:
            self.ctrl.query(cmd, token="console")

    def _clear_console(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _console_line(self, text: str, tag: str = "") -> None:
        self.console.configure(state="normal")
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {text}\n"
        self.console.insert("end", line, tag or ())
        self.console.see("end")
        self.console.configure(state="disabled")

    def _console_sys(self, text: str) -> None:
        self._console_line(text, "sys")

    # ------------------------------------------------------------ 事件泵
    def _pump(self) -> None:
        try:
            for ev in self.ctrl.events():
                self._handle_event(ev)
            now = time.time()
            if now - getattr(self, "_last_stats_ts", 0) >= 1.0:
                self._last_stats_ts = now
                self._refresh_stats()
        finally:
            self.after(100, self._pump)

    def _handle_event(self, ev) -> None:
        kind = ev[0]
        if kind == "log":
            tag = "tx" if ev[1] == "TX" else "rx"
            prefix = "→" if ev[1] == "TX" else "←"
            self._console_line(f"{prefix} {ev[2]}", tag)
        elif kind == "connected":
            self.connected = True
            self.idn_var.set(ev[1])
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
            self.status_var.set(f"已连接 | SCPI {ev[2]}")
            self._console_sys(f"连接成功: {ev[1]}")
            self._restart_monitor()
        elif kind == "disconnected":
            self.connected = False
            self.btn_connect.configure(state="normal")
            self.btn_disconnect.configure(state="disabled")
            self.idn_var.set("未连接")
            self.status_var.set("已断开")
            self.value_disp.configure(text="----", fg=LCD_FG)
            self._console_sys("已断开连接")
        elif kind == "error":
            msg = ev[1]
            if "查询超时" in msg:
                self.status_var.set(msg)
            self._console_line(f"✗ {msg}", "err")
        elif kind == "func":
            from .defs import FUNC_QUERY_MAP
            key = FUNC_QUERY_MAP.get(ev[1])
            if key and key in self.func_buttons and key != self.current_key:
                self._select_function(key)
        elif kind == "reading":
            value, ts, secondary = ev[1], ev[2], ev[3]
            rkey = ev[4] if len(ev) > 4 else self.current_key
            if rkey != self.current_key:
                return  # 切功能过程中的过期读数，丢弃
            self.last_value = value
            self._reading_count += 1
            fdef = FUNC_BY_KEY[self.current_key]
            plot_it = True
            if self.current_key == "CONT":
                try:
                    limit = max(1, min(2000, int(float(self.cont_var.get()))))
                except ValueError:
                    limit = 10
                if value > limit:
                    # 与面板一致：超过极限显示 OPEN，不画曲线（9e15 会撑爆坐标）
                    self.value_disp.configure(text="OPEN", fg=WARN)
                    self.status_disp.configure(
                        text=f"读数 #{self._reading_count}  "
                             f"开路（> 极限 {limit} Ω）")
                    plot_it = False
                else:
                    self.value_disp.configure(
                        text=f"{self._sci(value)} Ω  导通", fg=GREEN)
                    self.status_disp.configure(
                        text=f"读数 #{self._reading_count}  "
                             f"≤ 极限 {limit} Ω，蜂鸣导通")
            else:
                self.value_disp.configure(
                    text=f"{self._sci(value)} {fdef.unit}", fg=LCD_FG)
                self.status_disp.configure(
                    text=f"读数 #{self._reading_count}   "
                         f"{self.range_disp.cget('text')}")
            if secondary is not None:
                self.secondary_disp.configure(
                    text=f"副: {self._sci(secondary)} {fdef.unit}")
            if self.chart_on and plot_it:
                self.chart.add(value, ts)
            if self.chk_log_disp.get() and self._log_writer:
                self._write_csv(value, ts, secondary)
        elif kind == "reading_str":
            text, ts, secondary = ev[1], ev[2], ev[3]
            rkey = ev[4] if len(ev) > 4 else self.current_key
            if rkey != self.current_key:
                return
            self.value_disp.configure(text=text, fg=WARN)
            self.after(800, lambda: self.value_disp.configure(fg=LCD_FG))
            if self._log_writer:
                self._log_writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                    FUNC_BY_KEY[self.current_key].label, text, "",
                    secondary or "",
                ])
                self._log_count += 1
        elif kind == "query":
            token, resp = ev[1], ev[2]
            if token == "console":
                self._console_line(f"← {resp}", "rx")
            elif token == "error_queue" or token == "error_queue2":
                if resp and not resp.startswith("0,"):
                    self._console_line(f"仪器错误: {resp}", "err")
                    messagebox.showwarning("仪器错误队列", resp)
                else:
                    self._console_sys("错误队列为空")
            elif token == "stat_min":
                self.stat_min_var.set(f"MIN  {resp}")
            elif token == "stat_max":
                self.stat_max_var.set(f"MAX  {resp}")
            elif token == "stat_avg":
                self.stat_avg_var.set(f"AVG  {resp}")
            elif token == "stat_cnt":
                self.stat_cnt_var.set(f"CNT  {resp}")

    @staticmethod
    def _sci(v: float) -> str:
        a = abs(v)
        if a == 0:
            return "0.000000"
        if a >= 1e7 or a < 1e-4:
            return f"{v:.6e}"
        return f"{v:.6f}"

    def destroy(self) -> None:
        self._stop_log()
        self.ctrl.stop()
        super().destroy()


def run_app(demo: bool = False) -> None:
    app = App(demo=demo)
    app.mainloop()
