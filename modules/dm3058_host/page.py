# -*- coding: utf-8 -*-
"""RIGOL DM3058/DM3058E 万用表 · 融合版界面（FusionHub 风格，功能面对齐原版 tkinter 上位机）。

测量控制逻辑复用原上位机 dm3058 包（Dm3058Controller 事件式协议栈、
defs 功能/量程定义、Serial/TCP/USB-TMC(VISA+pyusb)/模拟器传输），界面按整体 UI 风格重建，
功能面对照 legacy/ui_app.py 逐项迁移：双显、滤波/阻抗/通断极限、采样间隔、数学运算
（REL/dB/dBm/P-F）、统计、实时趋势、CSV 记录、SCPI 控制台、仪器自检、使用说明。
"""
import csv
import html
import os
import re
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QRadioButton, QScrollArea, QSizePolicy,
                             QSpinBox, QSplitter, QTabWidget, QTextEdit,
                             QVBoxLayout, QWidget)

from instrument_hub.widgets import Card

from .core import defs
from .core.instrument import Dm3058Controller
from .core.transport import (MockTransport, SerialTransport, TcpTransport,
                             UsbTmcTransport, VisaTransport,
                             list_serial_ports, list_usb_tmc_devices,
                             list_visa_resources, pyusb_status)

# 功能键分类着色（与统一上位机 UI 规范一致）：电压蓝/电流橙/电阻绿/频率紫/通断青/电容粉
_FUNC_COLORS = {
    "DCV": "#3b82f6", "ACV": "#3b82f6",
    "DCI": "#f97316", "ACI": "#f97316",
    "2WR": "#10b981", "4WR": "#10b981",
    "FREQ": "#8b5cf6", "PERI": "#8b5cf6",
    "CONT": "#14b8a6", "DIODE": "#14b8a6",
    "CAP": "#ec4899",
}


def _func_btn_qss(color: str, selected: bool) -> str:
    """未选中=白底彩色描边+彩色字；选中=实心彩色+白字（档位一眼可辨）。"""
    if selected:
        return (f"QPushButton{{background:{color}; border:2px solid {color}; color:#FFFFFF;"
                f" border-radius:8px; font-weight:700; padding:6px 8px;}}"
                f"QPushButton:hover{{background:{color};}}"
                f"QPushButton:pressed{{border-color:#1F2937;}}")
    return (f"QPushButton{{background:#FFFFFF; border:2px solid {color}; color:{color};"
            f" border-radius:8px; font-weight:700; padding:6px 8px;}}"
            f"QPushButton:hover{{background:{color}22;}}"
            f"QPushButton:pressed{{background:{color}33;}}")


class _TrendChart(QWidget):
    """实时趋势曲线：白底网格 + 自适应纵轴（与原版 TrendChart 语义一致）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vals = []          # [(ts, value)]
        self._max_points = 300
        self._unit = ""
        self._formatter = None

    def set_unit(self, unit: str) -> None:
        self._unit = unit

    def set_formatter(self, fn) -> None:
        """轴标签格式化函数 value -> (数值串, 单位串)；跟随面板档位口径。"""
        self._formatter = fn

    def set_max_points(self, n: int) -> None:
        self._max_points = n
        self._vals = self._vals[-n:]
        self.update()

    def add(self, value: float, ts: float) -> None:
        self._vals.append((ts, value))
        if len(self._vals) > self._max_points:
            self._vals.pop(0)
        self.update()

    def clear(self) -> None:
        self._vals.clear()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#FFFFFF"))
        grid = QPen(QColor("#E8EDF3"), 1)
        p.setPen(grid)
        for i in range(1, 10):
            x = int(w * i / 10.0)
            p.drawLine(x, 8, x, h - 8)
        for i in range(1, 5):
            y = int(h * i / 5.0)
            p.drawLine(8, y, w - 8, y)
        # 空数据守卫：先判空再画（max()/min() 空序列会崩进程，见项目踩坑清单）
        if not self._vals:
            p.setPen(QColor("#9CA3AF"))
            p.drawText(self.rect(), Qt.AlignCenter, "暂无数据")
            return
        vals = [v for _, v in self._vals]
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-12:
            pad = abs(hi) * 0.02 or 1.0
        else:
            pad = (hi - lo) * 0.08
        lo -= pad
        hi += pad
        span = (hi - lo) or 1.0

        def _y(v: float) -> float:
            return h - 10 - (v - lo) / span * (h - 20)

        n = len(vals)
        pen = QPen(QColor("#3b82f6"), 2)
        p.setPen(pen)
        if n == 1:
            p.drawPoint(int(w / 2), int(_y(vals[0])))
        else:
            for i in range(1, n):
                x0 = 8 + (w - 16) * (i - 1) / (n - 1)
                x1 = 8 + (w - 16) * i / (n - 1)
                p.drawLine(int(x0), int(_y(vals[i - 1])), int(x1), int(_y(vals[i])))
        def _fmt(v: float) -> str:
            if self._formatter is not None:
                num, unit = self._formatter(v)
                return f"{num} {unit}"
            return f"{v:.6g} {self._unit}"

        p.setPen(QColor("#6B7280"))
        p.drawText(12, 20, _fmt(hi))
        p.drawText(12, h - 8, _fmt(lo))
        p.drawText(w - 160, h - 8, f"最新 {_fmt(vals[-1])}  点数 {n}")


class Dm3058Page(QWidget):
    """DM3058 控制：连接 → 功能/量程/速率/滤波/双显 → 实时读数 + 数学/统计/趋势/CSV/SCPI。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ctl = Dm3058Controller()
        self.ctl.start()
        self.current_key = "DCV"
        self.last_value = None
        self._reading_count = 0
        self.connected = False
        self.chart_on = True
        self._stats_on = False
        self._last_stats_ts = 0.0
        self._log_fp = None
        self._log_writer = None
        self._log_count = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_conn_card())

        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        ll.addWidget(self._build_disp_card())
        ll.addWidget(self._build_trend_card(), 1)
        mid.addWidget(left)
        mid.addWidget(self._build_right_panel())
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 0)
        mid.setSizes([860, 360])
        root.addWidget(mid, 1)
        root.addWidget(self._build_bottom())
        # 趋势图轴标签跟随当前功能的面板档位口径（电流 mA/µA、电容 nF/µF…）
        self.chart.set_formatter(
            lambda v: self._format_reading(
                v, defs.FUNC_BY_KEY[self.current_key].unit,
                defs.FUNC_BY_KEY[self.current_key]))

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    # ------------------------------------------------------------ 连接
    def _build_conn_card(self) -> Card:
        card = Card("通讯连接", "串口 / 网口 / USB-TMC(VISA) / 模拟器（演示模式无硬件也能跑通）")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(QLabel("连接方式"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["串口", "网络 (TCP)", "USB-TMC", "模拟器（演示）"])
        self.cmb_link.setFixedWidth(130)
        self.cmb_link.currentIndexChanged.connect(self._sync_conn_fields)
        h.addWidget(self.cmb_link)

        self.lbl_port = QLabel("端口/地址")
        h.addWidget(self.lbl_port)
        self.ed_port = QComboBox()
        self.ed_port.setEditable(False)
        ports = list_serial_ports()
        self.ed_port.addItems([str(p) for p in ports] or ["COM3"])
        self.ed_port.setCurrentText(ports[0] if ports else "COM3")
        self.ed_port.setFixedWidth(150)
        h.addWidget(self.ed_port)

        self.lbl_baud = QLabel("波特率")
        h.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"])
        self.cmb_baud.setCurrentText("9600")
        self.cmb_baud.setFixedWidth(86)
        h.addWidget(self.cmb_baud)

        self.lbl_parity = QLabel("校验")
        h.addWidget(self.lbl_parity)
        self.cmb_parity = QComboBox()
        self.cmb_parity.addItems(["N（8 位）", "O（7 位）", "E（7 位）"])
        self.cmb_parity.setFixedWidth(96)
        h.addWidget(self.cmb_parity)

        # USB-TMC：设备下拉 + 扫描（VISA 资源优先，pyusb 设备备选，与原版扫描逻辑一致）
        self.lbl_usb = QLabel("设备")
        h.addWidget(self.lbl_usb)
        self.cmb_usb = QComboBox()
        self.cmb_usb.setFixedWidth(300)
        h.addWidget(self.cmb_usb)
        self.btn_scan = QPushButton("扫描")
        self.btn_scan.setToolTip("扫描 VISA 资源与 pyusb USB-TMC 设备（自动匹配优先 VISA）")
        self.btn_scan.clicked.connect(self._refresh_usb)
        h.addWidget(self.btn_scan)
        self._usb_targets = {}   # 设备标签 -> ("visa", 资源) | ("pyusb", vid, pid)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.toggle_conn)
        h.addWidget(self.btn_connect)
        h.addStretch(1)
        self.lbl_info = QLabel("未连接")
        self.lbl_info.setObjectName("Muted")
        h.addWidget(self.lbl_info)
        card.body_lay.addLayout(h)

        # 仪器自检/状态工具（与原版工具条一致）
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(QLabel("仪器操作"))
        for text, slot in (("复位 *RST", lambda: self.ctl.write("*RST")),
                           ("清状态 *CLS", lambda: self.ctl.write("*CLS")),
                           ("查询错误", self._poll_errors),
                           ("蜂鸣测试", lambda: self.ctl.write("SYSTem:BEEPer"))):
            b = QPushButton(text)
            b.setProperty("selfStyled", True)
            b.setStyleSheet("QPushButton{background:#FFFFFF; border:2px solid #DAD7F0;"
                            " border-radius:8px; padding:4px 12px; font-weight:600; color:#4B4A73;}"
                            "QPushButton:hover{background:#EEF0FF; border-color:#4F46E5;}")
            b.clicked.connect(slot)
            tools.addWidget(b)
        tools.addStretch(1)
        card.body_lay.addLayout(tools)
        self._sync_conn_fields()
        return card

    def _sync_conn_fields(self) -> None:
        """按连接方式显隐参数行：串口=端口/波特率/校验，网口=地址，USB=设备+扫描，模拟器无参数。"""
        mode = self.cmb_link.currentIndex()
        serial, lan, usb = mode == 0, mode == 1, mode == 2
        self.lbl_port.setText("端口" if serial else "地址")
        self.lbl_port.setVisible(serial or lan)
        self.ed_port.setVisible(serial or lan)
        self.lbl_baud.setVisible(serial)
        self.cmb_baud.setVisible(serial)
        self.lbl_parity.setVisible(serial)
        self.cmb_parity.setVisible(serial)
        self.lbl_usb.setVisible(usb)
        self.cmb_usb.setVisible(usb)
        self.btn_scan.setVisible(usb)
        if usb:
            self._refresh_usb()

    def _refresh_usb(self) -> None:
        """扫描 VISA 资源 + pyusb 设备，结果写入设备下拉与通讯日志（与原版扫描逻辑一致）。"""
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
        self.cmb_usb.clear()
        self.cmb_usb.addItems(labels or [default])
        self.cmb_usb.setCurrentText(default)
        self._append_console(f"USB 扫描: VISA 资源 {len(visa_res)} 个, pyusb 设备 {len(pyusb_devs)} 个", "sys")
        self._append_console(f"pyusb 状态: {usb_stat}", "sys")
        if not labels and "正常" not in usb_stat:
            self._append_console(
                "提示: pyusb 无法枚举时请用 NI-VISA（仪器面板可查 USB0::VID::PID::SN 资源），"
                "或用 Zadig 将设备换绑 WinUSB", "sys")
        if visa_res and not pyusb_devs:
            self._append_console("已发现 VISA 资源，选择后点「连接」即可", "sys")

    def _auto_usb_factory(self):
        """自动匹配：VISA 优先，其次 pyusb（与原版一致）。"""
        visa_res = list_visa_resources()
        if visa_res:
            return lambda: VisaTransport(visa_res[0])
        return lambda: UsbTmcTransport(None, None)

    def toggle_conn(self) -> None:
        if self.ctl.connected:
            self.ctl.set_monitor(False)
            self.ctl.disconnect()
            return
        mode = self.cmb_link.currentIndex()
        text = self.ed_port.currentText().strip()
        baud = int(self.cmb_baud.currentText())
        if mode == 0:
            parity = self.cmb_parity.currentText()[:1] or "N"
            factory = lambda: SerialTransport(text, baud=baud, parity=parity)  # noqa: E731
        elif mode == 1:
            host, _, port = text.partition(":")
            factory = lambda: TcpTransport(host or "127.0.0.1", int(port or 5025))  # noqa: E731
        elif mode == 2:
            label = self.cmb_usb.currentText()
            target = self._usb_targets.get(label)
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
        self.ctl.connect(factory)

    # ------------------------------------------------------------ 显示/趋势
    def _build_disp_card(self) -> Card:
        card = Card("测量显示", "实时读数（事件队列驱动）")
        top = QHBoxLayout()
        self.lbl_func_name = QLabel("直流电压")
        self.lbl_func_name.setStyleSheet("font-size:15px; font-weight:800; color:#3b82f6;")
        top.addWidget(self.lbl_func_name)
        top.addStretch(1)
        self.lbl_range = QLabel("自动量程")
        self.lbl_range.setObjectName("Muted")
        top.addWidget(self.lbl_range)
        card.body_lay.addLayout(top)

        h = QHBoxLayout()
        h.setSpacing(18)
        self.lbl_value = QLabel("--")
        self.lbl_value.setStyleSheet("font-size:34px; font-weight:800; color:#2563eb;")
        h.addWidget(self.lbl_value)
        self.lbl_unit = QLabel("")
        self.lbl_unit.setStyleSheet("font-size:18px; font-weight:700; color:#7C3AED;")
        h.addWidget(self.lbl_unit)
        h.addStretch(1)
        self.lbl_time = QLabel("")
        self.lbl_time.setObjectName("Muted")
        h.addWidget(self.lbl_time)
        card.body_lay.addLayout(h)

        self.lbl_secondary = QLabel("")
        self.lbl_secondary.setStyleSheet("font-size:14px; color:#6B7280;")
        card.body_lay.addWidget(self.lbl_secondary)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_status)
        return card

    def _build_trend_card(self) -> Card:
        card = Card("实时趋势", "自动纵轴 · 切换功能自动清空防坐标轴撑爆")
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_chart = QPushButton("暂停曲线")
        self.btn_chart.setProperty("selfStyled", True)
        self.btn_chart.setStyleSheet("QPushButton{background:#FFFFFF; border:2px solid #DAD7F0;"
                                     " border-radius:8px; padding:4px 12px; font-weight:600; color:#4B4A73;}")
        self.btn_chart.clicked.connect(self._toggle_chart)
        bar.addWidget(self.btn_chart)
        b_clear = QPushButton("清空")
        b_clear.clicked.connect(self._chart_clear)
        bar.addWidget(b_clear)
        bar.addWidget(QLabel("点数:"))
        self.cmb_points = QComboBox()
        self.cmb_points.addItems(["100", "200", "300", "500", "1000"])
        self.cmb_points.setCurrentText("300")
        self.cmb_points.setFixedWidth(70)
        self.cmb_points.currentTextChanged.connect(
            lambda t: self.chart.set_max_points(int(t)))
        bar.addWidget(self.cmb_points)
        self.chk_csv = QCheckBox("记录到CSV")
        self.chk_csv.setChecked(True)
        bar.addWidget(self.chk_csv)
        bar.addStretch(1)
        card.body_lay.addLayout(bar)
        self.chart = _TrendChart()
        card.body_lay.addWidget(self.chart, 1)
        return card

    # ------------------------------------------------------------ 右侧栏（可滚动）
    def _build_right_panel(self) -> QScrollArea:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self._build_func_card())
        lay.addWidget(self._build_math_card())
        lay.addWidget(self._build_stats_card())
        lay.addWidget(self._build_csv_card())
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        scroll.setWidget(host)
        scroll.setMinimumWidth(330)
        scroll.setFixedWidth(380)
        return scroll

    def _build_func_card(self) -> Card:
        card = Card("测量功能", "功能/量程/速率由协议定义表驱动生成（单一事实源）")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        self.func_buttons = {}
        for i, f in enumerate(defs.FUNCTIONS):
            b = QPushButton(f.label)
            b.setProperty("selfStyled", True)   # 分类着色两态按钮，框架不统一上色
            b.clicked.connect(lambda _=False, key=f.key: self._select_function(key))
            g.addWidget(b, i // 2, i % 2)
            self.func_buttons[f.key] = b
        card.body_lay.addLayout(g)

        row = QGridLayout()
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(6)
        row.addWidget(QLabel("量程"), 0, 0)
        self.cmb_range = QComboBox()
        self.cmb_range.setFixedWidth(150)
        row.addWidget(self.cmb_range, 0, 1)
        self.btn_apply_range = QPushButton("应用量程")
        self.btn_apply_range.clicked.connect(self._apply_range)
        row.addWidget(self.btn_apply_range, 0, 2)

        row.addWidget(QLabel("速率"), 1, 0)
        self.cmb_rate = QComboBox()
        for code, desc in defs.RATE_CHOICES:
            self.cmb_rate.addItem(desc, code)
        self.cmb_rate.setFixedWidth(150)
        row.addWidget(self.cmb_rate, 1, 1)
        self.btn_apply_rate = QPushButton("应用速率")
        self.btn_apply_rate.clicked.connect(self._apply_rate)
        row.addWidget(self.btn_apply_rate, 1, 2)

        self.chk_filter = QCheckBox("交流滤波")
        self.chk_filter.stateChanged.connect(self._apply_filter)
        row.addWidget(self.chk_filter, 2, 0, 1, 3)

        row.addWidget(QLabel("DC 输入阻抗"), 3, 0)
        imp = QWidget()
        il = QHBoxLayout(imp)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(10)
        self.imp_10m = QRadioButton("10MΩ")
        self.imp_10g = QRadioButton(">10GΩ")
        self.imp_10m.setChecked(True)
        self.imp_10m.toggled.connect(self._apply_impedance)
        self.imp_10g.toggled.connect(self._apply_impedance)
        il.addWidget(self.imp_10m)
        il.addWidget(self.imp_10g)
        il.addStretch(1)
        row.addWidget(imp, 3, 1, 1, 2)

        row.addWidget(QLabel("通断极限(Ω)"), 4, 0)
        self.spn_cont = QSpinBox()
        self.spn_cont.setRange(1, 2000)
        self.spn_cont.setValue(10)
        self.spn_cont.setFixedWidth(150)
        row.addWidget(self.spn_cont, 4, 1)
        card.body_lay.addLayout(row)

        dual = QGridLayout()
        dual.setHorizontalSpacing(8)
        dual.setVerticalSpacing(6)
        self.chk_dual = QCheckBox("启用双显 (FUNCtion2)")
        dual.addWidget(self.chk_dual, 0, 0, 1, 2)
        dual.addWidget(QLabel("副显示"), 1, 0)
        self.cmb_dual = QComboBox()
        for key in defs.DUAL_SECONDARY_KEYS:
            self.cmb_dual.addItem(defs.FUNC_BY_KEY[key].label, key)
        self.cmb_dual.setFixedWidth(150)
        dual.addWidget(self.cmb_dual, 1, 1)
        b_dual = QPushButton("应用双显")
        b_dual.clicked.connect(self._apply_dual)
        dual.addWidget(b_dual, 2, 0, 1, 2)
        card.body_lay.addLayout(dual)

        samp = QHBoxLayout()
        samp.setSpacing(8)
        samp.addWidget(QLabel("采样间隔(s)"))
        self.spn_interval = QDoubleSpinBox()
        self.spn_interval.setRange(0.05, 10.0)
        self.spn_interval.setSingleStep(0.05)
        self.spn_interval.setValue(0.2)
        self.spn_interval.setFixedWidth(90)
        samp.addWidget(self.spn_interval)
        b_restart = QPushButton("应用并重启监测")
        b_restart.clicked.connect(self._restart_monitor)
        samp.addWidget(b_restart)
        samp.addStretch(1)
        card.body_lay.addLayout(samp)

        self.lbl_notes = QLabel("")
        self.lbl_notes.setObjectName("Muted")
        self.lbl_notes.setWordWrap(True)
        card.body_lay.addWidget(self.lbl_notes)
        self._init_func_styles()
        self._fill_ranges(defs.FUNC_BY_KEY[self.current_key])
        return card

    def _init_func_styles(self) -> None:
        for key, b in self.func_buttons.items():
            b.setStyleSheet(_func_btn_qss(_FUNC_COLORS[key], key == self.current_key))

    def _build_math_card(self) -> Card:
        card = Card("数学运算", "RIGOL CALCulate 命令集（与原版一致）")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        g.addWidget(QLabel("功能"), 0, 0)
        self.cmb_math = QComboBox()
        for _code, lab in defs.MATH_CHOICES:
            self.cmb_math.addItem(lab)
        g.addWidget(self.cmb_math, 0, 1, 1, 2)
        b_apply_math = QPushButton("应用所选数学功能")
        b_apply_math.setObjectName("Primary")
        b_apply_math.setProperty("selfStyled", True)
        b_apply_math.clicked.connect(self._apply_math)
        g.addWidget(b_apply_math, 1, 0, 1, 3)

        b_rel = QPushButton("以当前读数为 REL 基准")
        b_rel.clicked.connect(self._apply_rel)
        g.addWidget(b_rel, 2, 0, 1, 3)

        g.addWidget(QLabel("dB 参考"), 3, 0)
        self.ed_db_ref = QLineEdit("1.0")
        self.ed_db_ref.setFixedWidth(90)
        g.addWidget(self.ed_db_ref, 3, 1)
        b_db = QPushButton("dB")
        b_db.setProperty("selfStyled", True)
        b_db.setStyleSheet(_btn_flat("#8b5cf6", "#8b5cf6"))
        b_db.clicked.connect(self._apply_db)
        g.addWidget(b_db, 3, 2)

        g.addWidget(QLabel("dBm 参考R"), 4, 0)
        self.ed_dbm_ref = QLineEdit("50")
        self.ed_dbm_ref.setFixedWidth(90)
        g.addWidget(self.ed_dbm_ref, 4, 1)
        b_dbm = QPushButton("dBm")
        b_dbm.setProperty("selfStyled", True)
        b_dbm.setStyleSheet(_btn_flat("#8b5cf6", "#8b5cf6"))
        b_dbm.clicked.connect(self._apply_dbm)
        g.addWidget(b_dbm, 4, 2)

        g.addWidget(QLabel("P/F 下限"), 5, 0)
        self.ed_pf_low = QLineEdit("0")
        self.ed_pf_low.setFixedWidth(90)
        g.addWidget(self.ed_pf_low, 5, 1, 1, 2)
        g.addWidget(QLabel("P/F 上限"), 6, 0)
        self.ed_pf_high = QLineEdit("1")
        self.ed_pf_high.setFixedWidth(90)
        g.addWidget(self.ed_pf_high, 6, 1)
        b_pf = QPushButton("P/F 判定")
        b_pf.setProperty("selfStyled", True)
        b_pf.setStyleSheet(_btn_flat("#f97316", "#f97316"))
        b_pf.clicked.connect(self._apply_pf)
        g.addWidget(b_pf, 6, 2)
        card.body_lay.addLayout(g)
        return card

    def _build_stats_card(self) -> Card:
        card = Card("统计", "MIN / MAX / AVG / COUNT（仪器统计器）")
        self.chk_stats = QCheckBox("启用统计 (MIN/MAX/AVG/COUNT)")
        self.chk_stats.stateChanged.connect(self._toggle_stats)
        card.body_lay.addWidget(self.chk_stats)
        self.stat_labels = {}
        for key, text in (("min", "MIN  —"), ("max", "MAX  —"),
                          ("avg", "AVG  —"), ("cnt", "CNT  —")):
            lb = QLabel(text)
            lb.setStyleSheet("font-family:Consolas,monospace; font-size:12px;")
            card.body_lay.addWidget(lb)
            self.stat_labels[key] = lb
        return card

    def _build_csv_card(self) -> Card:
        card = Card("CSV 数据记录", "时间戳/功能/读数/单位/副读数")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.ed_csv_path = QLineEdit()
        self.ed_csv_path.setPlaceholderText("留空自动存到模块 logs/ 目录")
        row.addWidget(self.ed_csv_path, 1)
        b_browse = QPushButton("浏览…")
        b_browse.clicked.connect(self._browse_csv)
        row.addWidget(b_browse)
        card.body_lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        b_start = QPushButton("开始记录")
        b_start.setProperty("selfStyled", True)
        b_start.setStyleSheet(_btn_flat("#10b981", "#10b981"))
        b_start.clicked.connect(self._start_log)
        row2.addWidget(b_start)
        b_stop = QPushButton("停止")
        b_stop.setProperty("selfStyled", True)
        b_stop.setStyleSheet(_btn_flat("#ef4444", "#ef4444"))
        b_stop.clicked.connect(self._stop_log)
        row2.addWidget(b_stop)
        row2.addStretch(1)
        card.body_lay.addLayout(row2)
        self.lbl_log_count = QLabel("已记录 0 条")
        self.lbl_log_count.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_log_count)
        return card

    # ------------------------------------------------------------ 底部（SCPI 控制台 / 使用说明）
    def _build_bottom(self) -> QTabWidget:
        tabs = QTabWidget()
        console = QWidget()
        cl = QVBoxLayout(console)
        cl.setContentsMargins(0, 4, 0, 0)
        cl.setSpacing(6)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(120)
        self.console.setStyleSheet(
            "QTextEdit{background:#1e293b; color:#e2e8f0; border:1px solid #E9E7F5;"
            " border-radius:10px; padding:6px 8px; font-family:Consolas,monospace;"
            " font-size:12px;}")
        cl.addWidget(self.console, 1)
        entry = QHBoxLayout()
        entry.setSpacing(8)
        self.ed_cmd = QLineEdit()
        self.ed_cmd.setPlaceholderText("输入 SCPI 指令，回车=查询…")
        self.ed_cmd.returnPressed.connect(self._send_query)
        entry.addWidget(self.ed_cmd, 1)
        b_query = QPushButton("查询")
        b_query.clicked.connect(self._send_query)
        entry.addWidget(b_query)
        b_send = QPushButton("发送")
        b_send.clicked.connect(self._send_write)
        entry.addWidget(b_send)
        b_clear = QPushButton("清空日志")
        b_clear.clicked.connect(self._clear_console)
        entry.addWidget(b_clear)
        cl.addLayout(entry)
        tabs.addTab(console, "  SCPI 控制台  ")

        help_txt = (
            "快速上手\n"
            "1. 用 USB 线 / RS-232 串口线 / 网线连接 DM3058，仪器开机。\n"
            "2. 选择接口后点「连接」；连接成功会显示仪器 *IDN? 信息。\n"
            "3. 点左侧功能按钮切换测量功能（按钮按类别着色，选中项实心高亮）；可设量程、速率、滤波、输入阻抗。\n"
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
        help_page = QPlainTextEdit()
        help_page.setReadOnly(True)
        help_page.setPlainText(help_txt)
        help_page.setStyleSheet("font-size:12px;")
        tabs.addTab(help_page, "  使用说明  ")
        tabs.setFixedHeight(220)
        return tabs

    def _chart_clear(self) -> None:
        self.chart.clear()

    # ------------------------------------------------------------ 功能/设置（对齐原版）
    def _select_function(self, key: str) -> None:
        # 先停旧监测，防止“UI 已切档、后台仍用旧指令采样”的过期读数串档
        self.ctl.set_monitor(False, 0.2, [], key=self.current_key)
        self.current_key = key
        fdef = defs.FUNC_BY_KEY[key]
        self.chart.set_unit(fdef.unit)
        self.chart.clear()   # 切功能清空曲线，避免旧功能数据撑爆坐标轴
        for k, b in self.func_buttons.items():
            b.setStyleSheet(_func_btn_qss(_FUNC_COLORS[k], k == key))
        self._fill_ranges(fdef)
        self.lbl_func_name.setText(fdef.label)
        self.lbl_notes.setText(fdef.notes)
        # 能力开关
        self.chk_filter.setEnabled(bool(fdef.filter_cmd))
        if not fdef.filter_cmd:
            self.chk_filter.blockSignals(True)
            self.chk_filter.setChecked(False)
            self.chk_filter.blockSignals(False)
        rate_ok = fdef.rate_cmd is not None
        self.cmb_rate.setEnabled(rate_ok)
        self.btn_apply_rate.setEnabled(rate_ok)
        self.lbl_status.setText("速率可用" if rate_ok else "该功能无速率设置")
        # 发送指令
        self.ctl.write(fdef.func_cmd)
        self._apply_range()
        self._apply_rate()
        if fdef.filter_cmd:
            self._apply_filter()
        if key == "DCV":
            self._apply_impedance()
        if self.chk_dual.isChecked():
            self._apply_dual()
        self._restart_monitor()

    def _fill_ranges(self, fdef) -> None:
        self.cmb_range.blockSignals(True)
        self.cmb_range.clear()
        if fdef.range_cmd is None:
            self.cmb_range.addItem("固定")
            self.cmb_range.setEnabled(False)
            self.btn_apply_range.setEnabled(False)
            self.lbl_range.setText("固定")
        elif fdef.key == "CONT":
            self.cmb_range.addItem("极限电阻")
            self.cmb_range.setEnabled(False)
            self.btn_apply_range.setEnabled(True)
            self.lbl_range.setText("极限电阻")
        else:
            self.cmb_range.addItem("自动量程", None)
            for idx, name in fdef.ranges:
                self.cmb_range.addItem(f"{idx} · {name}", idx)
            self.cmb_range.setEnabled(True)
            self.btn_apply_range.setEnabled(True)
            self.lbl_range.setText("自动量程")
        self.cmb_range.blockSignals(False)

    def _apply_range(self) -> None:
        fdef = defs.FUNC_BY_KEY[self.current_key]
        if fdef.range_cmd is None:
            return
        if self.current_key == "CONT":
            lim = self.spn_cont.value()
            self.ctl.write(f"{fdef.range_cmd} {lim}")
            self.lbl_range.setText(f"极限 {lim} Ω")
            return
        idx = self.cmb_range.currentData()
        if idx is None:
            self.ctl.write(":MEASure AUTO")
            self.lbl_range.setText("自动量程")
        else:
            self.ctl.write(f"{fdef.range_cmd} {idx}")
            self.lbl_range.setText(dict(fdef.ranges).get(idx, str(idx)))
        self._restart_monitor()

    def _apply_rate(self) -> None:
        fdef = defs.FUNC_BY_KEY[self.current_key]
        if not fdef.rate_cmd:
            return
        code = self.cmb_rate.currentData() or "M"
        self.ctl.write(f"{fdef.rate_cmd} {code}")
        self._restart_monitor()

    def _apply_filter(self, *_args) -> None:
        fdef = defs.FUNC_BY_KEY[self.current_key]
        if not fdef.filter_cmd:
            return
        self.ctl.write(f"{fdef.filter_cmd} {'ON' if self.chk_filter.isChecked() else 'OFF'}")

    def _apply_impedance(self, *_args) -> None:
        if self.current_key != "DCV":
            return
        imp = "10G" if self.imp_10g.isChecked() else "10M"
        self.ctl.write(f":MEASure:VOLTage:DC:IMPEdance {imp}")

    def _apply_dual(self) -> None:
        if not self.chk_dual.isChecked():
            self.ctl.write(":FUNCtion2:CLEAR")
            self.lbl_secondary.setText("")
            self._restart_monitor()
            return
        key = self.cmb_dual.currentData() or "ACV"
        fdef = defs.FUNC_BY_KEY[key]
        self.ctl.write(fdef.dual_cmd)
        self.lbl_secondary.setText(f"双显: {fdef.label}")
        self._restart_monitor()

    def _monitor_cmds(self) -> list:
        if self.chk_dual.isChecked():
            return [":FUNCtion2:VALUe1?", ":FUNCtion2:VALUe2?"]
        return [defs.FUNC_BY_KEY[self.current_key].measure_cmd]

    def _restart_monitor(self, *_args) -> None:
        self.ctl.set_monitor(self.connected, float(self.spn_interval.value()),
                             self._monitor_cmds() if self.connected else [],
                             key=self.current_key)

    def _poll_errors(self) -> None:
        self.ctl.query("SYSTem:ERR?", token="error_queue")
        self.ctl.query("SYSTem:ERR?", token="error_queue2")

    # ------------------------------------------------------------ 数学/统计（对齐原版）
    def _apply_math(self) -> None:
        label = self.cmb_math.currentText()
        key = next((k for k, lab in defs.MATH_CHOICES if lab == label), "NONE")
        self.ctl.write(f":CALCulate:FUNCtion {key}")
        if key in ("MIN", "MAX", "AVERAGE", "TOTAL"):
            self.ctl.write(":CALCulate:STATistic:STATe ON")
            self.chk_stats.blockSignals(True)
            self.chk_stats.setChecked(True)
            self.chk_stats.blockSignals(False)
            self._stats_on = True
        if key == "NONE":
            self.ctl.write(":CALCulate:REL:STATe OFF")
            self.ctl.write(":CALCulate:DB:STATe OFF")
            self.ctl.write(":CALCulate:DBM:STATe OFF")
            self.ctl.write(":CALCulate:PF:STATe OFF")

    def _apply_rel(self) -> None:
        if self.last_value is None:
            QMessageBox.information(self, "REL", "尚无读数，请先连接并开始测量")
            return
        self.ctl.write(f":CALCulate:REL:OFFSet {self.last_value!r}")
        self.ctl.write(":CALCulate:REL:STATe ON")
        self.ctl.write(":CALCulate:FUNCtion REL")
        self.cmb_math.setCurrentText("相对 (REL)")
        self.lbl_status.setText(f"REL 基准 = {self.last_value:.6g}")

    def _apply_db(self) -> None:
        try:
            ref = float(self.ed_db_ref.text())
        except ValueError:
            QMessageBox.warning(self, "dB", "参考值无效")
            return
        self.ctl.write(f":CALCulate:DB:REFErence {ref!r}")
        self.ctl.write(":CALCulate:DB:STATe ON")
        self.ctl.write(":CALCulate:FUNCtion DB")
        self.cmb_math.setCurrentText("dB")

    def _apply_dbm(self) -> None:
        try:
            ref = float(self.ed_dbm_ref.text())
        except ValueError:
            QMessageBox.warning(self, "dBm", "参考电阻无效")
            return
        self.ctl.write(f":CALCulate:DBM:REFErence {ref!r}")
        self.ctl.write(":CALCulate:DBM:STATe ON")
        self.ctl.write(":CALCulate:FUNCtion DBM")
        self.cmb_math.setCurrentText("dBm")

    def _apply_pf(self) -> None:
        try:
            lo = float(self.ed_pf_low.text())
            hi = float(self.ed_pf_high.text())
        except ValueError:
            QMessageBox.warning(self, "P/F", "上下限无效")
            return
        if hi <= lo:
            QMessageBox.warning(self, "P/F", "上限必须大于下限")
            return
        self.ctl.write(f":CALCulate:PF:LOWEr {lo!r}")
        self.ctl.write(f":CALCulate:PF:UPPEr {hi!r}")
        self.ctl.write(":CALCulate:PF:STATe ON")
        self.ctl.write(":CALCulate:FUNCtion PF")
        self.cmb_math.setCurrentText("P/F 判定")

    def _toggle_stats(self, *_args) -> None:
        self._stats_on = self.chk_stats.isChecked()
        self.ctl.write(f":CALCulate:STATistic:STATe {'ON' if self._stats_on else 'OFF'}")
        if self._stats_on:
            self.ctl.write(":CALCulate:FUNCtion AVERAGE")
            self.cmb_math.setCurrentText("平均值")

    def _refresh_stats(self) -> None:
        if not (self.connected and self._stats_on):
            return
        self.ctl.query(":CALCulate:STATistic:MIN?", token="stat_min")
        self.ctl.query(":CALCulate:STATistic:MAX?", token="stat_max")
        self.ctl.query(":CALCulate:STATistic:AVERage?", token="stat_avg")
        self.ctl.query(":CALCulate:STATistic:COUNt?", token="stat_cnt")

    # ------------------------------------------------------------ 曲线/CSV（对齐原版）
    def _toggle_chart(self) -> None:
        self.chart_on = not self.chart_on
        self.btn_chart.setText("暂停曲线" if self.chart_on else "继续曲线")

    def _browse_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "选择 CSV 保存位置",
            f"dm3058_{time.strftime('%Y%m%d_%H%M%S')}.csv", "CSV 文件 (*.csv)")
        if path:
            self.ed_csv_path.setText(path)

    def _start_log(self) -> None:
        if self._log_fp:
            return
        path = self.ed_csv_path.text().strip()
        if not path:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, f"dm3058_{time.strftime('%Y%m%d_%H%M%S')}.csv")
            self.ed_csv_path.setText(path)
        try:
            self._log_fp = open(path, "w", newline="", encoding="utf-8-sig")
            self._log_writer = csv.writer(self._log_fp)
            self._log_writer.writerow(["时间戳", "功能", "读数", "单位", "副读数"])
            self._log_count = 0
            self.lbl_log_count.setText(f"记录中 → {os.path.basename(path)}")
            self._append_console(f"CSV 记录开始: {path}", "sys")
        except OSError as e:
            QMessageBox.warning(self, "CSV", f"无法写入文件: {e}")

    def _stop_log(self) -> None:
        if self._log_fp:
            try:
                self._log_fp.close()
            except OSError:
                pass
            self._log_fp = None
            self._log_writer = None
            self.lbl_log_count.setText(f"已停止，共 {self._log_count} 条")
            self._append_console(f"CSV 记录停止，共 {self._log_count} 条", "sys")

    def _write_csv(self, value: float, ts: float, secondary) -> None:
        if not self._log_writer:
            return
        fdef = defs.FUNC_BY_KEY[self.current_key]
        self._log_writer.writerow([
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + f".{int(ts % 1 * 1000):03d}",
            fdef.label, f"{value:.6e}", fdef.unit,
            "" if secondary is None else f"{secondary:.6e}",
        ])
        self._log_count += 1
        if self._log_count % 20 == 0 and self._log_fp:
            self._log_fp.flush()
        self.lbl_log_count.setText(f"已记录 {self._log_count} 条")

    # ------------------------------------------------------------ SCPI 控制台
    def _send_write(self) -> None:
        cmd = self.ed_cmd.text().strip()
        if cmd:
            self.ctl.write(cmd)

    def _send_query(self) -> None:
        cmd = self.ed_cmd.text().strip()
        if cmd:
            self.ctl.query(cmd, token="console")

    def _clear_console(self) -> None:
        self.console.clear()

    _CONSOLE_COLORS = {"tx": "#7dd3fc", "rx": "#6ee7b7", "err": "#fca5a5", "sys": "#fcd34d"}

    def _append_console(self, text: str, tag: str = "sys") -> None:
        color = self._CONSOLE_COLORS.get(tag, "#e2e8f0")
        stamp = time.strftime("%H:%M:%S")
        self.console.append(
            f'<span style="color:{color}">[{stamp}] {html.escape(str(text))}</span>')
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------ 读数显示
    _SI = ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""),
           (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p"))
    # 仪器面板按量程档位定显示单位的功能（DCI：200µA 档显 µA、2~200mA 档显 mA、2A/10A 档显 A；
    # ACI：20mA/200mA 档显 mA、2A/10A 档显 A），档位表取自 defs 量程单一事实源
    _RANGE_UNIT_KEYS = ("DCI", "ACI")
    _UNIT_SCALE = {"T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "m": 1e-3,
                   "µ": 1e-6, "u": 1e-6, "n": 1e-9, "p": 1e-12, "": 1.0}

    @classmethod
    def _parse_range_label(cls, label: str):
        """量程标签 → (满量程基准值, 显示单位除数, 显示单位)；解析不出返回 None。"""
        m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([TGMkmµunp]?)\s*([A-Za-zΩ]+)\s*$", label)
        if not m:
            return None
        num, pfx, base = float(m.group(1)), m.group(2), m.group(3)
        divisor = cls._UNIT_SCALE.get(pfx)
        if divisor is None:
            return None
        return num * divisor, divisor, f"{pfx}{base}"

    @classmethod
    def _format_reading(cls, value: float, unit: str, fdef=None):
        """读数人性化：面板档位口径优先（电流按量程档位），其余工程量级 SI 词头。

        科学计数法 e-06 极易被误读成"很高的电压"；悬空输入的微伏级噪声
        用 µV 显示一眼即知是噪声。非量纲单位原样显示。
        """
        if value != value:   # NaN
            return "--", unit
        if fdef is not None and fdef.key in cls._RANGE_UNIT_KEYS and fdef.ranges:
            a = abs(value)
            last = None
            for _idx, label in fdef.ranges:
                parsed = cls._parse_range_label(label)
                if parsed is None:
                    continue
                full_scale, divisor, dunit = parsed
                last = (divisor, dunit)
                if a <= full_scale:
                    return f"{value / divisor:.6g}", dunit
            if last is not None:
                return f"{value / last[0]:.6g}", last[1]
        if unit == "F":
            # 电容跟随仪器面板档位习惯：nF/µF 双档显示（2nF~10000µF 量程域），不跳 pF
            if abs(value) >= 1e-6:
                return f"{value * 1e6:.6g}", "µF"
            return f"{value * 1e9:.6g}", "nF"
        if unit not in ("V", "A", "Ω", "Hz", "s", "W"):
            return f"{value:.6g}", unit
        v = abs(value)
        for scale, pfx in cls._SI:
            if v >= scale:
                return f"{value / scale:.6g}", f"{pfx}{unit}"
        return f"{value:.6g}", unit

    # ------------------------------------------------------------ 事件泵（对齐原版）
    def _set_value_text(self, text: str, unit: str, color: str = "#2563eb") -> None:
        self.lbl_value.setText(text)
        self.lbl_value.setStyleSheet(f"font-size:34px; font-weight:800; color:{color};")
        self.lbl_unit.setText(unit)

    def _drain(self) -> None:
        for ev in self.ctl.events():
            kind = ev[0]
            if kind == "log":
                self._append_console(f"{'→' if ev[1] == 'TX' else '←'} {ev[2]}",
                                     "tx" if ev[1] == "TX" else "rx")
            elif kind == "connected":
                self.connected = True
                self.btn_connect.setText("已连接")
                self.btn_connect.setObjectName("btnConnected")
                self.lbl_info.setText(f"已连接　{ev[1]}")
                self.lbl_status.setText(f"已连接 | SCPI {ev[2]}")
                self._append_console(f"连接成功: {ev[1]}", "sys")
                self._restart_monitor()
            elif kind == "disconnected":
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)
                self.connected = False
                self.btn_connect.setText("连接")
                self.btn_connect.setObjectName("btnConnect")
                self.lbl_info.setText("未连接")
                self.lbl_value.setText("--")
                self.lbl_unit.setText("")
                self.lbl_secondary.setText("")
                self._append_console("已断开连接", "sys")
            elif kind == "error":
                msg = ev[1]
                if "查询超时" in msg:
                    self.lbl_status.setText(msg)
                self._append_console(f"✗ {msg}", "err")
            elif kind == "func":
                key = defs.FUNC_QUERY_MAP.get(str(ev[1]).strip().upper())
                if key and key in self.func_buttons and key != self.current_key:
                    self._select_function(key)
            elif kind == "reading":
                self._on_reading(ev)
            elif kind == "reading_str":
                text, ts, secondary = ev[1], ev[2], ev[3]
                rkey = ev[4] if len(ev) > 4 else self.current_key
                if rkey != self.current_key:
                    continue
                self._set_value_text(str(text), "", "#f59e0b")
                self.lbl_time.setText(time.strftime("%H:%M:%S"))
                if self._log_writer:
                    self._log_writer.writerow([
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                        defs.FUNC_BY_KEY[self.current_key].label, str(text), "",
                        secondary or ""])
                    self._log_count += 1
            elif kind == "query":
                token, resp = ev[1], ev[2]
                if token == "console":
                    self._append_console(f"← {resp}", "rx")
                elif token in ("error_queue", "error_queue2"):
                    if resp and not str(resp).startswith("0,"):
                        self._append_console(f"仪器错误: {resp}", "err")
                        QMessageBox.warning(self, "仪器错误队列", str(resp))
                    else:
                        self._append_console("错误队列为空", "sys")
                elif token == "stat_min":
                    self.stat_labels["min"].setText(f"MIN  {resp}")
                elif token == "stat_max":
                    self.stat_labels["max"].setText(f"MAX  {resp}")
                elif token == "stat_avg":
                    self.stat_labels["avg"].setText(f"AVG  {resp}")
                elif token == "stat_cnt":
                    self.stat_labels["cnt"].setText(f"CNT  {resp}")
            elif kind == "device_lost":
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)
                self.lbl_status.setText(f"[离线] {ev[1]}")
                self._append_console(f"[离线] {ev[1]}", "err")
            elif kind == "device_recovered":
                from instrument_hub.comm_state import mark_ok
                mark_ok(self)
                self.lbl_status.setText("DM3058 已恢复响应")
                self._append_console("DM3058 已恢复响应", "sys")
        now = time.time()
        if now - self._last_stats_ts >= 1.0:
            self._last_stats_ts = now
            self._refresh_stats()

    def _on_reading(self, ev) -> None:
        from instrument_hub.comm_state import mark_ok
        value, ts, secondary = ev[1], ev[2], ev[3]
        rkey = ev[4] if len(ev) > 4 else self.current_key
        if rkey != self.current_key:
            return   # 切功能过程中的过期读数，丢弃（与原版一致）
        mark_ok(self)
        self.last_value = value
        self._reading_count += 1
        fdef = defs.FUNC_BY_KEY[self.current_key]
        plot_it = True
        if self.current_key == "CONT":
            limit = self.spn_cont.value()
            if value > limit:
                # 与面板一致：超过极限显示 OPEN，不画曲线（9e15 会撑爆坐标轴）
                self._set_value_text("OPEN", "", "#f59e0b")
                self.lbl_status.setText(f"读数 #{self._reading_count}  开路（> 极限 {limit} Ω）")
                plot_it = False
            else:
                num, unit = self._format_reading(value, "Ω")
                self._set_value_text(num, f"{unit}  导通", "#10b981")
                self.lbl_status.setText(
                    f"读数 #{self._reading_count}  ≤ 极限 {limit} Ω，蜂鸣导通")
        elif value != value or abs(value) >= 1e12:
            # 超量程/开路哨兵（如二极管开路 ~9e15、阻抗 OL）：与仪器面板一致显示 OPEN
            self._set_value_text("OPEN", "", "#f59e0b")
            self.lbl_status.setText(f"读数 #{self._reading_count}  开路/超量程（仪器面板显示 OPEN）")
            plot_it = False
        else:
            num, unit = self._format_reading(value, fdef.unit, fdef)
            self._set_value_text(num, unit)
            self.lbl_status.setText(f"读数 #{self._reading_count}   {self.lbl_range.text()}")
        if secondary is not None:
            if secondary != secondary or abs(secondary) >= 1e12:
                self.lbl_secondary.setText("副: OPEN")
            else:
                snum, sunit = self._format_reading(secondary, fdef.unit, fdef)
                self.lbl_secondary.setText(f"副: {snum} {sunit}")
        self.lbl_time.setText(time.strftime("%H:%M:%S"))
        if self.chart_on and plot_it:
            self.chart.add(value, ts)
        if self.chk_csv.isChecked() and self._log_writer:
            self._write_csv(value, ts, secondary)

    def shutdown(self) -> None:
        """退出保护：停监测、断开连接、关 CSV、回收工作线程。"""
        self._timer.stop()
        try:
            self.ctl.set_monitor(False)
            self.ctl.disconnect()
        except Exception:
            pass
        try:
            self._stop_log()
        except Exception:
            pass
        try:
            self.ctl.stop()
        except Exception:
            pass


def _btn_flat(fg: str, border: str) -> str:
    """小操作按钮统一样式（dB/dBm 紫、P/F 橙、开始绿、停止红）。"""
    return (f"QPushButton{{background:#FFFFFF; border:2px solid {border}; color:{fg};"
            f" border-radius:8px; font-weight:700; padding:4px 12px;}}"
            f"QPushButton:hover{{background:{border}22;}}"
            f"QPushButton:pressed{{background:{border}33;}}")
