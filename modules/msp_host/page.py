# -*- coding: utf-8 -*-
"""美恩斯 MSP65/MSP62 直流电源上位机 · 融合版界面（FusionHub 风格）。

Modbus-RTU 帧层 / 状态机协议栈 / 传输 / 模拟从站 / 寄存器表 / 设备语义层
零改动复用原上位机 core 包，界面按整体 UI 风格重建：
连接配置 → 量程/参数配置 → 实时测量+波形 → 设定与控制 → 寄存器表调试 + 底部通讯日志。

界面只消费 device.PowerSupplyDevice 语义接口，不接触帧字节；
寄存器地址全部来自 registers.py 单一事实源；轮询频率 ≥200ms 且队列忙时跳过。
"""
import threading
from collections import deque

from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QScrollArea, QSpinBox, QSplitter, QStackedWidget,
                             QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog
from instrument_hub.widgets import Card

from .core.device import Measurement, Poller, PowerSupplyDevice
from .core.protocol_stack import CommandFailed, ModbusRTUStack
from .core.registers import PROFILES, ScaleConfig, physical_to_raw, raw_to_physical
from .core.sim_slave import SimulatedSlave, make_loopback
from .core.transport import SerialTransport, TransportError


class WaveWidget(QWidget):
    """示波屏风格波形区：深色底 + 网格 + 亮色双曲线（V 青 / I 黄）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wave_v = deque(maxlen=300)
        self.wave_i = deque(maxlen=300)
        self.setMinimumHeight(170)

    def push(self, v, i):
        if v is not None:
            self.wave_v.append(v)
        if i is not None:
            self.wave_i.append(i)
        self.update()

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#0F172A"))
        grid = QPen(QColor("#1E293B"))
        p.setPen(grid)
        for i in range(1, 6):
            y = h * i / 6
            p.drawLine(0, int(y), w, int(y))
        for i in range(1, 8):
            x = w * i / 8
            p.drawLine(int(x), 0, int(x), h)
        for data, color in ((self.wave_v, "#22D3EE"), (self.wave_i, "#FACC15")):
            if len(data) < 2:
                continue
            lo, hi = min(data), max(data)
            span = (hi - lo) or 1.0
            pts = QPolygonF()
            n = len(data)
            for k, val in enumerate(data):
                x = w * k / max(1, n - 1)
                y = h - 10 - (val - lo) / span * (h - 24)
                pts.append(QPointF(x, y))
            p.setPen(QPen(QColor(color), 2))
            p.drawPolyline(pts)
        p.end()


class MspPage(QWidget):
    """美恩斯直流电源控制：连接 → 量程配置 → 监控/设定 → 寄存器调试。"""

    sig_log = pyqtSignal(str, str)      # (方向, 文本) 工作线程 → 主线程
    sig_meas = pyqtSignal(object)       # Measurement 轮询回调 → 主线程
    sig_rb = pyqtSignal(object)         # 设定值回读 {v,i,exp} → 主线程（输出前校验/回读框）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stack = None
        self.device = None
        self.transport = None
        self.poller = None
        self.sim_slave = None
        self._link_saved = {"真实串口": None, "模拟从站": None}

        self.sig_log.connect(self._append_log)
        self.sig_meas.connect(self._show_measurement)
        self.sig_rb.connect(self._on_readback)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        page_lay = QVBoxLayout()   # 嵌套布局：框架日志分割条跳过本页（自管分割条）
        page_lay.setSpacing(8)

        # 功能键切换：监控 / 寄存器表（寄存器表独立页，主界面紧凑免下拉）
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_page_mon = QPushButton("监控")
        self.btn_page_reg = QPushButton("寄存器表")
        for b in (self.btn_page_mon, self.btn_page_reg):
            b.setCheckable(True)
            b.setFixedWidth(120)
            bar.addWidget(b)
        bar.addStretch(1)
        page_lay.addLayout(bar)

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self._build_monitor_page())
        self.page_stack.addWidget(self._build_reg_page())
        page_lay.addWidget(self.page_stack, 1)
        root.addLayout(page_lay)
        self.btn_page_mon.setChecked(True)
        self.btn_page_mon.clicked.connect(lambda: self._switch_page(0))
        self.btn_page_reg.clicked.connect(lambda: self._switch_page(1))

        self._fill_register_table()
        self._refresh_ports()
        self._on_model_change()   # 按初始型号落定默认波特率 / MSP62 专属控件可见性

    def _switch_page(self, idx):
        self.page_stack.setCurrentIndex(idx)
        self.btn_page_mon.setChecked(idx == 0)
        self.btn_page_reg.setChecked(idx == 1)

    def _build_monitor_page(self) -> QWidget:
        """监控主页：连接/量程 + （实时测量 | 设定控制）+ 日志，免下拉看全。"""
        w = QWidget()
        tv = QVBoxLayout(w)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(8)
        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        bv.addWidget(self._build_conn_scale_card())
        # 实时测量 | 设定与控制 左右分布（分界线可拖拉）
        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_measure_card())
        mid.addWidget(self._build_ctrl_card())
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 1)
        mid.setSizes([560, 560])
        bv.addWidget(mid, 1)
        bv.addStretch(1)
        split.addWidget(body)
        split.addWidget(self._build_log_group())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([430, 150])
        tv.addWidget(split, 1)
        return w

    def _build_reg_page(self) -> QWidget:
        """寄存器表独立页（功能键切换）。"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._build_reg_card())
        return w

    # ---------------------------------------------------------- 连接 + 量程（紧凑合并）
    def _build_conn_scale_card(self) -> Card:
        card = Card("连接 / 量程配置",
                    "Modbus-RTU · 8N1 · 默认波特率 MSP65=115200、MSP62=9600；"
                    "MSP65 小数位按额定值推导、MSP62 按面板配置（务必一致，否则差 10 倍）")
        g = QGridLayout()
        g.setSpacing(6)
        g.setVerticalSpacing(10)

        # 第一行：链路（型号/链路/串口/刷新/波特率/连接/断开）
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("型号"))
        self.cmb_model = QComboBox()
        self.cmb_model.addItems(list(PROFILES))
        self.cmb_model.currentIndexChanged.connect(self._on_model_change)
        top.addWidget(self.cmb_model)

        top.addWidget(QLabel("链路"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["真实串口", "模拟从站"])
        self.cmb_link.currentIndexChanged.connect(self._on_link_changed)
        top.addWidget(self.cmb_link)

        self.lbl_port = QLabel("串口")
        top.addWidget(self.lbl_port)
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setStyleSheet("QComboBox{min-width:130px;}")
        top.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_baud = QLabel("波特率")
        top.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["4800", "9600", "19200", "38400", "57600", "115200"])
        top.addWidget(self.cmb_baud)

        top.addSpacing(8)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.clicked.connect(self._on_connect)
        top.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("断开")
        self.btn_disc.clicked.connect(self._on_disconnect)
        self.btn_disc.setEnabled(False)
        top.addWidget(self.btn_disc)
        top.addStretch(1)
        g.addLayout(top, 0, 0)

        # 第二行：地址/超时/状态/小数位
        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(QLabel("地址"))
        self.sp_addr = QSpinBox()
        self.sp_addr.setRange(1, 100)   # 手册：有效值 1~100
        self.sp_addr.setValue(1)
        self.sp_addr.setFixedWidth(90)
        mid.addWidget(self.sp_addr)

        mid.addWidget(QLabel("超时(ms)"))
        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(100, 5000)
        self.sp_timeout.setValue(500)
        self.sp_timeout.setFixedWidth(90)
        mid.addWidget(self.sp_timeout)

        self.lbl_state = QLabel("未连接")
        self.lbl_state.setObjectName("Muted")
        mid.addWidget(self.lbl_state)

        mid.addSpacing(8)
        mid.addWidget(QLabel("电压小数位"))
        self.cmb_vdec = QComboBox()
        self.cmb_vdec.addItems(["自动", "0", "1", "2", "3"])
        self.cmb_vdec.setCurrentText("1")
        mid.addWidget(self.cmb_vdec)

        mid.addWidget(QLabel("电流小数位"))
        self.cmb_idec = QComboBox()
        self.cmb_idec.addItems(["自动", "0", "1", "2", "3"])
        self.cmb_idec.setCurrentText("3")
        mid.addWidget(self.cmb_idec)
        mid.addStretch(1)
        g.addLayout(mid, 1, 0)

        # 第三行：轮询/设定寄存器
        low = QHBoxLayout()
        low.setSpacing(8)
        low.addWidget(QLabel("刷新(ms)"))
        self.sp_poll = QSpinBox()
        self.sp_poll.setRange(200, 60000)   # 轮询下限 200ms：防队列堆积假死
        self.sp_poll.setValue(500)
        self.sp_poll.setFixedWidth(90)
        low.addWidget(self.sp_poll)

        self.lbl_sp_pair = QLabel("设定寄存器(MSP62)")
        low.addWidget(self.lbl_sp_pair)
        self.cmb_sp_pair = QComboBox()
        self.cmb_sp_pair.addItems(["2001/2002（默认）", "2021/2022"])
        low.addWidget(self.cmb_sp_pair)
        low.addStretch(1)
        g.addLayout(low, 2, 0)

        self.lbl_scale = QLabel("换算档位：连接后显示（电压 raw = V × 10^n，电流 raw = A × 10^n）")
        self.lbl_scale.setObjectName("Muted")
        self.lbl_scale.setWordWrap(True)
        g.addWidget(self.lbl_scale, 3, 0)
        card.body_lay.addLayout(g)
        return card

    # ---------------------------------------------------------- 实时测量 + 波形
    def _build_measure_card(self) -> Card:
        card = Card("实时测量", "轮询批量读测量块（≤20 寄存器）；上一周期未完成自动跳过，不堆积命令")
        g = QGridLayout()
        g.setSpacing(8)
        self.lbl_v = QLabel("----")
        self.lbl_v.setStyleSheet("font-size:22px; font-weight:800; color:#0E7490;")
        self.lbl_i = QLabel("----")
        self.lbl_i.setStyleSheet("font-size:22px; font-weight:800; color:#7C3AED;")
        self.lbl_p = QLabel("----")
        self.lbl_p.setStyleSheet("font-size:22px; font-weight:800; color:#B45309;")
        for col, (cap, lab, unit) in enumerate((
                ("输出电压", self.lbl_v, "V"), ("输出电流", self.lbl_i, "A"),
                ("输出功率", self.lbl_p, "W"))):
            c = QLabel(cap)
            c.setObjectName("Muted")
            g.addWidget(c, 0, col)
            row = QHBoxLayout()
            row.addWidget(lab)
            u = QLabel(unit)
            u.setStyleSheet("font-weight:700; color:#6B7280;")
            row.addWidget(u)
            row.addStretch(1)
            g.addLayout(row, 1, col)
        self.lst_status = QListWidget()
        self.lst_status.setMinimumHeight(88)
        g.addWidget(self.lst_status, 2, 0, 1, 3)
        card.body_lay.addLayout(g)
        return card

    # ---------------------------------------------------------- 设定与控制
    def _build_ctrl_card(self) -> Card:
        card = Card("设定与控制",
                    "写设定值/保护值 → 启动输出（二次确认）；小数位/设定寄存器配置改动即时生效")
        g = QGridLayout()
        g.setSpacing(8)

        g.addWidget(QLabel("设定电压(V)"), 0, 0)
        self.sp_set_v = QDoubleSpinBox()
        self.sp_set_v.setRange(0, 10000)
        self.sp_set_v.setDecimals(3)
        self.sp_set_v.setValue(30.0)
        g.addWidget(self.sp_set_v, 0, 1)

        g.addWidget(QLabel("设定电流(A)"), 0, 2)
        self.sp_set_i = QDoubleSpinBox()
        self.sp_set_i.setRange(0, 10000)
        self.sp_set_i.setDecimals(3)
        self.sp_set_i.setValue(5.0)
        g.addWidget(self.sp_set_i, 0, 3)

        self.btn_set = QPushButton("写入设定值")
        self.btn_set.clicked.connect(self._on_set_setpoint)
        g.addWidget(self.btn_set, 0, 4)

        # 回读框 + 回读按钮（输出前安全闭环：设定值 vs 回读值比对）
        g.addWidget(QLabel("回读电压(V)"), 2, 0)
        self.ed_rb_v = QLineEdit("—")
        self.ed_rb_v.setReadOnly(True)
        self.ed_rb_v.setStyleSheet("font-family:Consolas;")
        g.addWidget(self.ed_rb_v, 2, 1)
        g.addWidget(QLabel("回读电流(A)"), 2, 2)
        self.ed_rb_i = QLineEdit("—")
        self.ed_rb_i.setReadOnly(True)
        self.ed_rb_i.setStyleSheet("font-family:Consolas;")
        g.addWidget(self.ed_rb_i, 2, 3)
        self.btn_rb = QPushButton("回读设定值")
        self.btn_rb.setToolTip("读回设定寄存器并显示（设定值下发后也会自动回读）")
        self.btn_rb.clicked.connect(self._on_readback_clicked)
        g.addWidget(self.btn_rb, 2, 4)

        g.addWidget(QLabel("过压值(V)"), 1, 0)
        self.sp_ovp = QDoubleSpinBox()
        self.sp_ovp.setRange(0, 10000)
        self.sp_ovp.setDecimals(1)
        self.sp_ovp.setValue(60.0)
        g.addWidget(self.sp_ovp, 1, 1)

        g.addWidget(QLabel("过流值(A)"), 1, 2)
        self.sp_ocp = QDoubleSpinBox()
        self.sp_ocp.setRange(0, 10000)
        self.sp_ocp.setDecimals(3)
        self.sp_ocp.setValue(10.0)
        g.addWidget(self.sp_ocp, 1, 3)

        self.btn_prot = QPushButton("写入过压 / 过流")
        self.btn_prot.clicked.connect(self._on_set_protection)
        g.addWidget(self.btn_prot, 1, 4)
        card.body_lay.addLayout(g)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_on = QPushButton("启动输出")
        self.btn_on.clicked.connect(lambda: self._on_output(True))
        bar.addWidget(self.btn_on)
        self.btn_off = QPushButton("停止输出")
        self.btn_off.clicked.connect(lambda: self._on_output(False))
        bar.addWidget(self.btn_off)
        self.btn_save = QPushButton("保存参数 (MSP65)")
        self.btn_save.clicked.connect(self._on_save_params)
        bar.addWidget(self.btn_save)
        bar.addStretch(1)
        card.body_lay.addLayout(bar)
        return card

    # ---------------------------------------------------------- 寄存器表
    def _build_reg_card(self) -> Card:
        card = Card("寄存器表（单一事实源 registers.py 派生）",
                    "选中行 → 读/写调试；写入前二次确认；手册未定义位不做解释")
        self.tbl = QTableWidget()
        self.tbl.setColumnCount(6)
        self.tbl.setHorizontalHeaderLabels(["地址", "属性", "名称", "量纲", "含义", "当前值"])
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setMinimumHeight(180)
        card.body_lay.addWidget(self.tbl)

        h = QHBoxLayout()
        h.setSpacing(8)
        self.btn_read = QPushButton("读选中寄存器")
        self.btn_read.clicked.connect(self._on_read_reg)
        h.addWidget(self.btn_read)
        h.addWidget(QLabel("写入值"))
        self.ed_wr = QLineEdit("0")
        self.ed_wr.setStyleSheet("font-family:Consolas;")
        h.addWidget(self.ed_wr)
        self.btn_write = QPushButton("写选中寄存器")
        self.btn_write.clicked.connect(self._on_write_reg)
        h.addWidget(self.btn_write)
        h.addStretch(1)
        card.body_lay.addLayout(h)
        return card

    # ---------------------------------------------------------- 日志
    def _build_log_group(self) -> QGroupBox:
        box = QGroupBox("通讯日志")
        v = QVBoxLayout(box)
        v.setSpacing(6)
        h = QHBoxLayout()
        h.addWidget(QLabel("TX/RX 帧 + 语义事件"))
        h.addStretch(1)
        b_save = QPushButton("保存日志")
        b_save.clicked.connect(self._save_log)
        h.addWidget(b_save)
        b_clr = QPushButton("清空")
        b_clr.clicked.connect(lambda: self.txt_log.clear())
        h.addWidget(b_clr)
        v.addLayout(h)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("font-family:Consolas;")
        self.txt_log.setMinimumHeight(110)
        self.txt_log.setMaximumBlockCount(3000)   # 防日志无限增长
        v.addWidget(self.txt_log)
        return box

    # ---------------------------------------------------------- 配置联动
    def _on_model_change(self):
        profile = PROFILES[self.cmb_model.currentText()]
        self.cmb_baud.setCurrentText(str(profile.default_baud))
        self.lbl_sp_pair.setVisible(profile.model == "MSP62")
        self.cmb_sp_pair.setVisible(profile.model == "MSP62")
        self._fill_register_table()
        self._log("INFO", f"切换型号 {profile.model}（默认波特率 {profile.default_baud} 8N1）")

    def _on_link_changed(self):
        """链路三联动：输入框可见性 + 下拉候选重建 + 各模式输入互相记忆。"""
        sim = self.cmb_link.currentText() == "模拟从站"
        self.lbl_port.setVisible(not sim)
        self.cmb_port.setVisible(not sim)
        self.btn_refresh.setVisible(not sim)
        self.lbl_baud.setVisible(not sim)
        self.cmb_baud.setVisible(not sim)
        self.lbl_state.setText("模拟从站（无真机开发/演示）" if sim else "未连接")

    def _refresh_ports(self):
        try:
            from serial.tools import list_ports
            ports = sorted((p.device for p in list_ports.comports()),
                           key=lambda s: (len(s), s))
        except Exception:  # noqa: BLE001
            ports = []
        cur = self.cmb_port.currentText().strip()
        self.cmb_port.clear()
        self.cmb_port.addItems(ports or ["COM1"])
        if cur in ports:
            self.cmb_port.setCurrentText(cur)
        else:
            self.cmb_port.setCurrentText(ports[0] if ports else cur or "COM1")

    def _make_scale_cfg(self) -> ScaleConfig:
        def dec(text):
            return None if text == "自动" else int(text)
        return ScaleConfig(
            # 额定值取在役 MSP62 机型 1500V/1A 款固定档（界面不再暴露该参数）
            rated_voltage=1500.0,
            rated_current=1.0,
            voltage_decimals=dec(self.cmb_vdec.currentText()),
            current_decimals=dec(self.cmb_idec.currentText()),
        )

    def _pair_from_ui(self):
        return (2021, 2022) if "2021" in self.cmb_sp_pair.currentText() else (2001, 2002)

    def _show_scale_info(self):
        """换算档位亮出来——与面板小数位不一致时肉眼可辨（差 10 倍的根源）。"""
        if self.device is None:
            return
        s = self.device.scale
        v_reg, i_reg = self.device.setpoint_regs
        txt = (f"换算档位：电压 raw = V × 10^{s['voltage_decimals']}，"
               f"电流 raw = A × 10^{s['current_decimals']}，"
               f"设定寄存器 {v_reg}/{i_reg}（须与面板小数位一致，否则差 10 倍）")
        self.lbl_scale.setText(txt)
        self._log("INFO", txt)

    def _fill_register_table(self):
        profile = PROFILES[self.cmb_model.currentText()]
        self.tbl.setRowCount(len(profile.registers))
        for r, rd in enumerate(profile.registers):
            for c, text in enumerate((str(rd.addr), rd.access, rd.name,
                                      rd.kind, rd.desc, "—")):
                self.tbl.setItem(r, c, QTableWidgetItem(text))
        self.tbl.resizeColumnsToContents()

    # ---------------------------------------------------------- 连接
    def _on_connect(self):
        if self.stack is not None:
            return
        try:
            addr = self.sp_addr.value()
            profile = PROFILES[self.cmb_model.currentText()]
            if self.cmb_link.currentText() == "模拟从站":
                self.sim_slave = SimulatedSlave(profile, addr=addr)
                self.transport = make_loopback(self.sim_slave)
                self._log("INFO", f"已启动模拟从站（{profile.model}，地址 {addr}），"
                                  "用于无真机开发/演示")
            else:
                self.transport = SerialTransport(self.cmb_port.currentText().strip(),
                                                 int(self.cmb_baud.currentText()))
            self.transport.open()
            self.stack = ModbusRTUStack(
                self.transport,
                timeout=self.sp_timeout.value() / 1000.0,
                max_retries=2,   # 超时重发上限固定（界面不再暴露）
                on_log=lambda d, t: self.sig_log.emit(d, t),
                on_state=lambda s: self.sig_log.emit("STATE", f"状态机 → {s.value}"))
            self.stack.start()
            self.device = PowerSupplyDevice(self.stack, profile, addr=addr,
                                            scale_cfg=self._make_scale_cfg())
            self.device.setpoint_regs = self._pair_from_ui()
            self._show_scale_info()
            self.poller = Poller(
                self.device, interval_s=self.sp_poll.value() / 1000.0,
                on_measurement=lambda m: self.sig_meas.emit(m),
                on_error=self._on_poll_error)
            self.poller.start()
        except (ValueError, TransportError, OSError) as e:
            self._teardown()
            QMessageBox.critical(self, "连接失败", str(e))
            return
        self.btn_conn.setText("已连接")
        self.btn_conn.setObjectName("btnConnected")
        self.btn_conn.setEnabled(True)   # 保持可按：框架统一交互「已连接」再按=断开
        self.btn_disc.setEnabled(True)
        self.lbl_state.setText(f"已连接 {profile.model}")
        self._log("INFO", f"已连接 {profile.title}（{self.cmb_link.currentText()}，"
                          f"{self.cmb_baud.currentText()} 8N1，地址 {addr}）")

    def _on_disconnect(self):
        self._teardown()
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_disc.setEnabled(False)
        self.lbl_state.setText("未连接")
        self._log("INFO", "已断开连接")

    def _teardown(self):
        if self.poller:
            self.poller.stop()
            self.poller = None
        if self.stack:
            self.stack.stop()
            self.stack = None
        if self.transport:
            try:
                self.transport.close()
            except Exception:  # noqa: BLE001
                pass
            self.transport = None
        self.device = None
        self.sim_slave = None

    # ---------------------------------------------------------- 语义操作
    def _require_device(self):
        if self.device is None:
            QMessageBox.warning(self, "提示", "请先连接设备")
            return None
        return self.device

    def _run_op(self, fn, ok_text: str):
        dev = self._require_device()
        if dev is None:
            return
        # 小数位/设定寄存器配置改动即时生效（不需断开重连）
        dev.set_scale_cfg(self._make_scale_cfg())
        dev.setpoint_regs = self._pair_from_ui()
        self._show_scale_info()

        def work():
            try:
                fn(dev)
                self.sig_log.emit("INFO", ok_text)
            except CommandFailed as e:
                self.sig_log.emit("ERR", f"{ok_text} 失败：{e}")
            except Exception as e:  # noqa: BLE001
                self.sig_log.emit("ERR", f"{ok_text} 异常：{e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_set_setpoint(self):
        v, i = self.sp_set_v.value(), self.sp_set_i.value()
        def op(d):
            d.set_setpoint(voltage=v, current=i)
            self._worker_readback(d)   # 下发后自动回读一次（同线程顺序保证写后读）
        self._run_op(op, f"设定值已写入：{v}V / {i}A")

    def _on_readback_clicked(self):
        self._run_op(self._worker_readback, "已回读设定值")

    def _worker_readback(self, dev, expected=None):
        """工作线程：读回设定寄存器原始值，带 expected 时用于输出前校验。"""
        v_reg, i_reg = dev.setpoint_regs
        raw_v = dev.read_register(v_reg)
        raw_i = dev.read_register(i_reg)
        self.sig_rb.emit({"v": raw_v, "i": raw_i, "exp": expected})

    def _on_readback(self, payload):
        """主线程：刷新回读框；带期望值时做输出前一致性校验。"""
        raw_v, raw_i, exp = payload["v"], payload["i"], payload.get("exp")
        try:
            s = self.device.scale if self.device is not None else None
        except Exception:
            s = None
        if s:
            # 定显 + raw 同框：与设定框同小数位，原始值可与面板对表
            self.ed_rb_v.setText(f"{raw_to_physical('voltage', raw_v, s):.{int(s['voltage_decimals'])}f} (raw {raw_v})")
            self.ed_rb_i.setText(f"{raw_to_physical('current', raw_i, s):.{int(s['current_decimals'])}f} (raw {raw_i})")
        else:
            self.ed_rb_v.setText(str(raw_v))
            self.ed_rb_i.setText(str(raw_i))
        self.sig_log.emit("INFO", f"回读设定：V 原始 {raw_v} / I 原始 {raw_i}")
        if exp is None:
            return
        bad = []
        if exp.get("v") != raw_v:
            bad.append(f"电压：设定原始 {exp['v']} ≠ 回读原始 {raw_v}")
        if exp.get("i") != raw_i:
            bad.append(f"电流：设定原始 {exp['i']} ≠ 回读原始 {raw_i}")
        if bad:
            QMessageBox.warning(
                self, "设定值与回读值不一致，已禁止启动输出",
                "设备里的设定值和上位机设定不一致，为安全起见不允许启动输出：\n\n"
                + "\n".join(bad)
                + "\n\n请重新「写入设定值」并确认回读一致后再启动输出。")
            self.sig_log.emit("ERR", "输出前校验不一致，已禁止启动输出：" + "；".join(bad))
            return
        self.sig_log.emit("INFO", "输出前校验通过：设定值与回读值一致")
        dev_name = self.device.profile.model if self.device is not None else "MSP"
        dlg = ConfirmOutputDialog(
            f"美恩斯 {dev_name} 直流电源", "启动输出",
            "输出端将带电！确认接线与量程无误、负载连接可靠后再开启。",
            f"设定 {self.sp_set_v.value()}V / {self.sp_set_i.value()}A", self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return
        self._run_op(lambda d: d.output_on(), "已发送【启动输出】")

    def _on_set_protection(self):
        ovp, ocp = self.sp_ovp.value(), self.sp_ocp.value()
        self._run_op(lambda d: (d.set_ovp(ovp), d.set_ocp(ocp)),
                     f"保护值已写入：OVP {ovp}V / OCP {ocp}A")

    def _on_output(self, on: bool):
        if on and self._require_device() is not None:
            # 输出前安全闭环：先回读设定值与设定比对，不一致禁止启动
            v, i = self.sp_set_v.value(), self.sp_set_i.value()
            def op(d):
                exp = {"v": physical_to_raw("voltage", v, d.scale),
                       "i": physical_to_raw("current", i, d.scale)}
                self._worker_readback(d, exp)
            self._run_op(op, "输出前校验：已回读设定值")
            return
        self._run_op(lambda d: d.output_on() if on else d.output_off(),
                     "已发送【启动输出】" if on else "已发送【停止输出】")

    def _on_save_params(self):
        dev = self._require_device()
        if dev is None:
            return
        if dev.profile.model != "MSP65":
            QMessageBox.information(self, "提示", "数据保存寄存器(2010)仅 MSP65 提供")
            return
        self._run_op(lambda d: d.write_register(2010, 1), "参数已保存（重启不丢失）")

    def _on_read_reg(self):
        dev = self._require_device()
        if dev is None:
            return
        row = self.tbl.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在寄存器表中选中一行")
            return
        addr = int(self.tbl.item(row, 0).text())

        def work(d):
            raw = d.read_register(addr)
            rd = d.profile.reg(addr)
            phys = raw_to_physical(rd.kind, raw, d.scale)
            self.sig_log.emit("INFO", f"读寄存器 {addr}({rd.name}) = {raw}（{phys:g}）")
            self.sig_log.emit("REG", f"{addr}|{raw}（{phys:g}）")
        self._run_op(work, f"读寄存器 {addr} 完成")

    def _on_write_reg(self):
        dev = self._require_device()
        if dev is None:
            return
        row = self.tbl.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在寄存器表中选中一行")
            return
        addr = int(self.tbl.item(row, 0).text())
        try:
            val = int(self.ed_wr.text().strip(), 0)
        except ValueError:
            QMessageBox.warning(self, "提示", "写入值必须是整数")
            return
        rd = dev.profile.reg(addr)
        if (QMessageBox.question(
                self, "确认写入",
                f"确认写入寄存器？\n\n地址：{addr}（{rd.name}）\n值：{val}\n"
                f"属性：{rd.access}\n含义：{rd.desc}")
                != QMessageBox.Yes):
            return

        def work(d):
            d.write_register(addr, val)
            self.sig_log.emit("REG", f"{addr}|{val}")
        self._run_op(work, f"写寄存器 {addr} = {val}")

    # ---------------------------------------------------------- 显示/日志
    def _show_measurement(self, m: Measurement):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 轮询收到测量值 = 通讯真正建立
        fmt = lambda x, d=3: "----" if x is None else f"{x:.{d}f}"  # noqa: E731
        self.lbl_v.setText(fmt(m.voltage))
        self.lbl_i.setText(fmt(m.current))
        self.lbl_p.setText(fmt(m.power, 1))

        self.lst_status.clear()
        if m.status_raw is not None:
            self.lst_status.addItem(
                f"状态寄存器原始值：0x{m.status_raw:04X}（{m.status_raw}）")
            for line in m.status_text:
                self.lst_status.addItem("  • " + line)
            if not m.status_text:
                self.lst_status.addItem(
                    "  （手册未定义位不做解释，见交付说明遗留问题清单）")

    def _on_poll_error(self, e):
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 轮询失败 = 通讯中断
        self.sig_log.emit("ERR", f"轮询失败：{e}")

    def _append_log(self, direction: str, text: str):
        if direction == "REG":
            # 寄存器读写结果回填表格当前值列
            try:
                addr_s, _, val = text.partition("|")
                addr = int(addr_s)
                for r in range(self.tbl.rowCount()):
                    if self.tbl.item(r, 0).text() == str(addr):
                        self.tbl.setItem(r, 5, QTableWidgetItem(val))
                        break
            except Exception:  # noqa: BLE001
                pass
            return
        colors = {"TX": "#4F46E5", "RX": "#059669", "WARN": "#B45309",
                  "ERR": "#DC2626", "INFO": "#6B7280", "STATE": "#7C3AED"}
        color = colors.get(direction, "#6B7280")
        self.txt_log.appendHtml(
            f'<span style="color:{color}">[{direction}] {text}</span>')
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _log(self, direction: str, text: str):
        self.sig_log.emit(direction, text)

    def _save_log(self):
        import datetime
        import os
        path = os.path.join(
            os.environ.get("TEMP", "."),
            f"msp_host_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_log.toPlainText())
            self._log("INFO", f"日志已保存 → {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))

    # ---------------------------------------------------------- 退出闭环
    def shutdown(self):
        """退出保护：停轮询 → 关输出 → 停协议栈 → 断链（电源安全闭环）。"""
        if self.poller:
            self.poller.stop()
            self.poller = None
        if self.device is not None:
            try:
                self.device.output_off()
            except Exception:  # noqa: BLE001
                pass
        if self.stack:
            self.stack.stop()
            self.stack = None
        if self.transport:
            try:
                self.transport.close()
            except Exception:  # noqa: BLE001
                pass
            self.transport = None
        self.device = None
        self.sim_slave = None
