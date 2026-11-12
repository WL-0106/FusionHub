# -*- coding: utf-8 -*-
"""JT6321A 电子负载上位机 · FusionHub 风格 PyQt5 界面（逻辑层零改动复用）。"""
from __future__ import annotations

import queue
import threading

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFrame,
                             QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMainWindow, QPlainTextEdit,
                             QPushButton, QRadioButton, QScrollArea,
                             QSpinBox, QSplitter, QTabWidget, QVBoxLayout,
                             QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog

from .jt6321a import protocol as P
from .jt6321a.device import LoadDevice
from .jt6321a.transport import SerialTransport, SimTransport, list_ports


class Worker(threading.Thread):
    """单工作线程串行执行通讯任务（与原工程线程模型一致）。"""

    def __init__(self, out: queue.Queue):
        super().__init__(daemon=True)
        self._jobs: queue.Queue = queue.Queue()
        self._out = out
        self._busy = False
        self._stop = False

    @property
    def busy(self) -> bool:
        return self._busy

    def submit(self, job) -> None:
        self._jobs.put(job)

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        while not self._stop:
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            self._busy = True
            try:
                job(self._out)
            except Exception as e:  # noqa: BLE001
                self._out.put(("log", f"任务异常：{e}"))
            self._busy = False


class JT6321APage(QMainWindow):
    """基本控制 / 动态保护 / OCP / 量程说明 + 右侧实时监测 + 底部通讯日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JT6321A 电子负载上位机（Jartul JT632xA · SCPI）")
        self.dev: LoadDevice = None
        self._poll_inflight = False
        self._poll_fail = 0            # 连续轮询失败计数（成功清零）
        self._poll_lost = False        # 掉线标记：True 时降为 2s 低频探测
        self._show_frames = False
        self._q: queue.Queue = queue.Queue()
        self.worker = Worker(self._q)
        self.worker.start()
        self._build_ui()
        self._pump = QTimer(self)
        self._pump.setInterval(40)
        self._pump.timeout.connect(self._drain)
        self._pump.start()
        self._poll = QTimer(self)
        self._poll.setInterval(1000)      # 轮询 1s：不高于串口吞吐
        self._poll.timeout.connect(self._submit_poll)
        self._poll.start()

    # ================================================================ UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_conn_bar())
        root.addWidget(self._build_action_bar())

        # 上：左实时测量 + 右页签（水平可拖）；下：通讯日志（垂直可拖）
        h_split = QSplitter(Qt.Horizontal)
        h_split.setChildrenCollapsible(False)
        h_split.addWidget(self._flat_scroll(self._build_monitor()))
        h_split.addWidget(self._flat_scroll(self._build_tabs()))
        h_split.setStretchFactor(0, 0)
        h_split.setStretchFactor(1, 1)
        h_split.setCollapsible(0, False)
        h_split.setSizes([360, 900])

        log_card = QGroupBox("通讯日志（TX/RX 报文，拖动上方手柄缩放）")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(8, 10, 8, 8)
        log_lay.setSpacing(6)
        bar = QHBoxLayout()
        self.chk_frames = QCheckBox("显示报文")
        self.chk_frames.toggled.connect(self._on_frames_toggled)
        bar.addWidget(self.chk_frames)
        bar.addStretch(1)
        btn_clear = QPushButton("清空")
        btn_clear.setFixedWidth(70)
        btn_clear.clicked.connect(lambda: self.log.clear())
        bar.addWidget(btn_clear)
        log_lay.addLayout(bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(110)
        self.log.setMaximumBlockCount(3000)
        log_lay.addWidget(self.log)

        main_split = QSplitter(Qt.Vertical)
        main_split.setHandleWidth(14)
        main_split.setChildrenCollapsible(False)
        main_split.addWidget(h_split)
        main_split.addWidget(log_card)
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 0)
        main_split.setSizes([520, 170])
        h_split.setMinimumHeight(120)
        root.addWidget(main_split)
        self.setCentralWidget(central)

    @staticmethod
    def _flat_scroll(w: QWidget) -> QScrollArea:
        """包滚动区：解除 minimumSizeHint 顶死分割条。"""
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setFrameShape(QFrame.NoFrame)
        s.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        s.setWidget(w)
        return s

    def _build_conn_bar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(8)
        h.addWidget(QLabel("串口"))
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setStyleSheet("QComboBox{min-width:120px;}")   # 控件级定宽防全局 QSS 覆盖
        self.refresh_ports()
        h.addWidget(self.cmb_port)
        btn_ref = QPushButton("刷新")
        btn_ref.clicked.connect(self.refresh_ports)
        h.addWidget(btn_ref)

        h.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["2400", "4800", "9600", "19200", "38400",
                                "57600", "115200"])
        self.cmb_baud.setCurrentText("9600")
        self.cmb_baud.setStyleSheet("QComboBox{min-width:90px;}")
        h.addWidget(self.cmb_baud)

        h.addWidget(QLabel("校验位"))
        self.cmb_parity = QComboBox()
        self.cmb_parity.addItems(["N", "E", "O"])
        self.cmb_parity.setStyleSheet("QComboBox{min-width:60px;}")
        h.addWidget(self.cmb_parity)

        self.chk_sim = QCheckBox("模拟设备")
        self.chk_sim.setToolTip("无硬件联调：内置模拟负载，全部功能离线可用")
        h.addWidget(self.chk_sim)

        self.btn_conn = QPushButton("连接")
        self.btn_conn.setProperty("selfStyled", True)   # 自绘配色，框架不按文字刷色
        self.btn_conn.setStyleSheet(
            "QPushButton{background:#4F46E5; color:white; border:2px solid #4338CA;"
            "border-radius:10px; font-weight:700; padding:3px 14px;}"
            "QPushButton:pressed{background:#4338CA;}")
        self.btn_conn.clicked.connect(self.toggle_conn)
        h.addWidget(self.btn_conn)
        h.addStretch(1)
        self.lbl_idn = QLabel("未连接")
        self.lbl_idn.setObjectName("Muted")
        h.addWidget(self.lbl_idn)
        return bar

    def _build_action_bar(self) -> QWidget:
        box = QGroupBox("负载动作")
        h = QHBoxLayout(box)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(8)
        self.btn_input_on = QPushButton("开启负载")
        self.btn_input_on.setProperty("selfStyled", True)   # 自绘配色，框架不按文字刷色
        self.btn_input_on.setStyleSheet(
            "QPushButton{background:#D1FAE5; color:#047857; border:2px solid #6EE7B7;"
            "border-radius:10px; font-weight:700; padding:3px 14px;}"
            "QPushButton:pressed{background:#6EE7B7;}")
        self.btn_input_on.clicked.connect(lambda: self.on_input(True))
        h.addWidget(self.btn_input_on)
        btn_off = QPushButton("关闭负载")
        btn_off.setProperty("selfStyled", True)   # 自绘配色，框架不按文字刷色
        btn_off.setStyleSheet(
            "QPushButton{background:#FFF1F2; color:#D20A34; border:2px solid #FDA4AF;"
            "border-radius:10px; font-weight:700; padding:3px 14px;}"
            "QPushButton:pressed{background:#FDA4AF;}")
        btn_off.clicked.connect(lambda: self.on_input(False))
        h.addWidget(btn_off)
        btn_sh_on = QPushButton("短路 ON")
        btn_sh_on.setProperty("selfStyled", True)   # 自绘配色，框架不按文字刷色
        btn_sh_on.setStyleSheet(
            "QPushButton{background:#FEF3C7; color:#B45309; border:2px solid #FCD34D;"
            "border-radius:10px; font-weight:700; padding:3px 12px;}"
            "QPushButton:pressed{background:#FCD34D;}")
        btn_sh_on.clicked.connect(lambda: self.on_short(True))
        h.addWidget(btn_sh_on)
        btn_sh_off = QPushButton("短路 OFF")
        btn_sh_off.clicked.connect(lambda: self.on_short(False))
        h.addWidget(btn_sh_off)
        btn_rst = QPushButton("复位 *RST")
        btn_rst.clicked.connect(self.on_reset)
        h.addWidget(btn_rst)
        btn_err = QPushButton("读错误")
        btn_err.clicked.connect(self.on_read_error)
        h.addWidget(btn_err)
        btn_all = QPushButton("读回设定值")
        btn_all.clicked.connect(self.on_read_all)
        h.addWidget(btn_all)
        h.addStretch(1)
        return box

    def _build_tabs(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic(), "基本控制")
        self.tabs.addTab(self._build_dyn(), "动态 / 保护")
        self.tabs.addTab(self._build_ocp(), "OCP 测试")
        self.tabs.addTab(self._build_limits(), "量程 / 说明")
        lay.addWidget(self.tabs)
        return wrap

    @staticmethod
    def _spin(lo: float, hi: float, dec: int = 4) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(dec)
        sp.setStyleSheet("QDoubleSpinBox{min-width:110px;}")
        return sp

    def _build_basic(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        g1 = QGroupBox("工作模式")
        l1 = QVBoxLayout(g1)
        row = QHBoxLayout()
        self.mode_group = []
        for key, name in (("CC", "定电流 CC"), ("CV", "定电压 CV"), ("CP", "定功率 CP"),
                          ("CR", "定电阻 CR"), ("DYNA", "动态 DYNA"), ("LED", "LED 模拟")):
            rb = QRadioButton(name)
            rb.toggled.connect(self._on_mode_change)
            row.addWidget(rb)
            self.mode_group.append((key, rb))
        l1.addLayout(row)
        btn_mode = QPushButton("下发模式")
        btn_mode.clicked.connect(self.on_set_mode)
        l1.addWidget(btn_mode, 0, Qt.AlignLeft)
        lay.addWidget(g1)

        g2 = QGroupBox("设定值")
        l2 = QGridLayout(g2)
        self.lbl_value = QLabel("当前模式 CC：设定拉载电流")
        l2.addWidget(self.lbl_value, 0, 0, 1, 3)
        self.sp_value = self._spin(0, 1e6, 6)
        self.lbl_value_unit = QLabel("A")
        btn_set_val = QPushButton("设定")
        btn_set_val.clicked.connect(self.on_set_value)
        l2.addWidget(QLabel("拉载值"), 1, 0)
        l2.addWidget(self.sp_value, 1, 1)
        l2.addWidget(self.lbl_value_unit, 1, 2)
        l2.addWidget(btn_set_val, 1, 3)
        lay.addWidget(g2)
        self.mode_group[0][1].setChecked(True)   # 控件齐备后再触发模式联动

        g3 = QGroupBox("保护与系统参数")
        l3 = QGridLayout(g3)
        self.sp_prot_i = self._spin(0, 1e6, 4)
        self.sp_prot_p = self._spin(0, 1e6, 4)
        self.sp_von = self._spin(0, 1e6, 4)
        self.sp_voff = self._spin(0, 1e6, 4)
        self.sp_slew = self._spin(0, 1e6, 4)
        btn_prot = QPushButton("设定保护")
        btn_prot.clicked.connect(self.on_set_protection)
        btn_vonoff = QPushButton("设定 Von/Voff")
        btn_vonoff.clicked.connect(self.on_set_vonoff)
        btn_slew = QPushButton("设定斜率")
        btn_slew.clicked.connect(self.on_set_slew)
        l3.addWidget(QLabel("保护电流"), 0, 0)
        l3.addWidget(self.sp_prot_i, 0, 1)
        l3.addWidget(QLabel("A"), 0, 2)
        l3.addWidget(btn_prot, 0, 3)
        l3.addWidget(QLabel("保护功率"), 1, 0)
        l3.addWidget(self.sp_prot_p, 1, 1)
        l3.addWidget(QLabel("W"), 1, 2)
        l3.addWidget(QLabel("Von 开启"), 2, 0)
        l3.addWidget(self.sp_von, 2, 1)
        l3.addWidget(QLabel("V"), 2, 2)
        l3.addWidget(btn_vonoff, 2, 3)
        l3.addWidget(QLabel("Voff 关断"), 3, 0)
        l3.addWidget(self.sp_voff, 3, 1)
        l3.addWidget(QLabel("V"), 3, 2)
        l3.addWidget(QLabel("电流斜率"), 4, 0)
        l3.addWidget(self.sp_slew, 4, 1)
        l3.addWidget(QLabel("A/uS"), 4, 2)
        l3.addWidget(btn_slew, 4, 3)
        lay.addWidget(g3)
        lay.addStretch(1)
        return w

    def _build_dyn(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        g1 = QGroupBox("动态模式 DYNA")
        l1 = QGridLayout(g1)
        self.sp_dyn_low = self._spin(0, 1e6, 4)
        self.sp_dyn_high = self._spin(0, 1e6, 4)
        self.sp_dyn_tl = self._spin(0, 1e6, 4)
        self.sp_dyn_th = self._spin(0, 1e6, 4)
        btn_dyn = QPushButton("下发动态参数")
        btn_dyn.clicked.connect(self.on_set_dyn)
        for r, (lab, sp, unit) in enumerate((
                ("低准位 Ia", self.sp_dyn_low, "A"), ("高准位 Ib", self.sp_dyn_high, "A"),
                ("Ta 低准位时间", self.sp_dyn_tl, "S"), ("Tb 高准位时间", self.sp_dyn_th, "S"))):
            l1.addWidget(QLabel(lab), r, 0)
            l1.addWidget(sp, r, 1)
            l1.addWidget(QLabel(unit), r, 2)
            if r == 0:
                l1.addWidget(btn_dyn, r, 3)
        tip = QLabel("下发后需把模式切到 DYNA 才会按动态带载")
        tip.setObjectName("Muted")
        l1.addWidget(tip, 4, 0, 1, 4)
        lay.addWidget(g1)

        g2 = QGroupBox("输入控制")
        l2 = QHBoxLayout(g2)
        b1 = QPushButton("开启负载")
        b1.clicked.connect(lambda: self.on_input(True))
        b2 = QPushButton("关闭负载")
        b2.clicked.connect(lambda: self.on_input(False))
        l2.addWidget(b1)
        l2.addWidget(b2)
        l2.addStretch(1)
        lay.addWidget(g2)
        lay.addStretch(1)
        return w

    def _build_ocp(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        g1 = QGroupBox("OCP 过流保护测试")
        l1 = QGridLayout(g1)
        self.sp_ocp_is = self._spin(0, 1e6, 4)
        self.sp_ocp_ie = self._spin(0, 1e6, 4)
        self.sp_ocp_step = QSpinBox()
        self.sp_ocp_step.setRange(1, 999)
        self.sp_ocp_dwell = self._spin(0, 1e6, 3)
        self.sp_ocp_vtrig = self._spin(0, 1e6, 4)
        btn_setup = QPushButton("下发参数")
        btn_setup.clicked.connect(self.on_ocp_setup)
        for r, (lab, sp, unit) in enumerate((
                ("起始电流", self.sp_ocp_is, "A"), ("截止电流", self.sp_ocp_ie, "A"),
                ("步数", self.sp_ocp_step, ""), ("单步驻留", self.sp_ocp_dwell, "S"),
                ("触发电平", self.sp_ocp_vtrig, "V"))):
            l1.addWidget(QLabel(lab), r, 0)
            l1.addWidget(sp, r, 1)
            l1.addWidget(QLabel(unit), r, 2)
            if r == 0:
                l1.addWidget(btn_setup, r, 3)
        row = QHBoxLayout()
        b_start = QPushButton("启动 OCP")
        b_start.setProperty("selfStyled", True)   # 自绘配色，框架不按文字刷色
        b_start.setStyleSheet(
            "QPushButton{background:#D1FAE5; color:#047857; border:2px solid #6EE7B7;"
            "border-radius:10px; font-weight:700; padding:3px 14px;}")
        b_start.clicked.connect(lambda: self.on_ocp(True))
        b_stop = QPushButton("停止 OCP")
        b_stop.setProperty("selfStyled", True)   # 自绘配色，框架不按文字刷色
        b_stop.setStyleSheet(
            "QPushButton{background:#FFF1F2; color:#D20A34; border:2px solid #FDA4AF;"
            "border-radius:10px; font-weight:700; padding:3px 14px;}")
        b_stop.clicked.connect(lambda: self.on_ocp(False))
        b_res = QPushButton("读结果")
        b_res.clicked.connect(self.on_ocp_result)
        row.addWidget(b_start)
        row.addWidget(b_stop)
        row.addWidget(b_res)
        row.addStretch(1)
        l1.addLayout(row, 5, 0, 1, 4)
        lay.addWidget(g1)

        g2 = QGroupBox("测试结果")
        l2 = QGridLayout(g2)
        self.lbl_ocp_res = QLabel("-")
        self.lbl_ocp_res.setStyleSheet("color:#4F46E5; font-weight:700;")
        self.lbl_ocp_pmax = QLabel("-")
        self.lbl_ocp_pmax.setStyleSheet("color:#4F46E5; font-weight:700;")
        l2.addWidget(QLabel("OCP 点"), 0, 0)
        l2.addWidget(self.lbl_ocp_res, 0, 1)
        l2.addWidget(QLabel("Pmax 点"), 1, 0)
        l2.addWidget(self.lbl_ocp_pmax, 1, 1)
        lay.addWidget(g2)
        lay.addStretch(1)
        return w

    def _build_limits(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        g1 = QGroupBox("本机量程上限（本地拦截用）")
        l1 = QGridLayout(g1)
        tip = QLabel("按面板铭牌填写；0 = 不限制。超过上限的值会被本地拦下，一条报文都不发。\n"
                     "注意：JT6321A 老批次为 150V/30A/300W，与现行手册 600W/120A 不同，务必按铭牌核对。")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        l1.addWidget(tip, 0, 0, 1, 4)
        self.sp_lim_i = self._spin(0, 1e6, 4)
        self.sp_lim_v = self._spin(0, 1e6, 4)
        self.sp_lim_p = self._spin(0, 1e6, 4)
        self.sp_lim_r = self._spin(0, 1e6, 4)
        self.sp_lim_i.setValue(P.DEFAULT_LIMITS["current"])
        self.sp_lim_v.setValue(P.DEFAULT_LIMITS["voltage"])
        self.sp_lim_p.setValue(P.DEFAULT_LIMITS["power"])
        self.sp_lim_r.setValue(P.DEFAULT_LIMITS["resistance"])
        btn_apply = QPushButton("应用量程")
        btn_apply.clicked.connect(self.on_apply_limits)
        for r, (lab, sp, unit) in enumerate((
                ("额定电流", self.sp_lim_i, "A"), ("额定电压", self.sp_lim_v, "V"),
                ("额定功率", self.sp_lim_p, "W"), ("额定电阻", self.sp_lim_r, "ohm"))):
            l1.addWidget(QLabel(lab), r + 1, 0)
            l1.addWidget(sp, r + 1, 1)
            l1.addWidget(QLabel(unit), r + 1, 2)
            if r == 0:
                l1.addWidget(btn_apply, r + 1, 3)
        lay.addWidget(g1)

        g2 = QGroupBox("接线排查速查")
        l2 = QVBoxLayout(g2)
        for t in ("RS232 用交叉线（DB9 2↔3 交叉）；连不上先做环回自检（短接转换器 TX-RX）",
                  "仪器若开了 Multi-Point 多点通讯，RS232 单机场景请关掉，否则可能收不到应答",
                  "波特率现场被改过时：本机支持 2400~115200，逐档试或查仪器面板 Menu→Communication",
                  "串口参数改动后必须重新连接才生效",
                  "无硬件时勾选「模拟设备」，全部功能离线可用（理想负载模型，故障位锁存与真机可能不同）"):
            lb = QLabel("· " + t)
            lb.setWordWrap(True)
            l2.addWidget(lb)
        lay.addWidget(g2)
        lay.addStretch(1)
        return w

    def _build_monitor(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        g1 = QGroupBox("实时测量")
        l1 = QGridLayout(g1)
        self.lbl_meas = {}
        for c, (key, name, unit) in enumerate((
                ("V", "电压 V", "V"), ("I", "电流 I", "A"),
                ("P", "功率 P", "W"), ("R", "电阻 R", "ohm"))):
            box = QGroupBox(name)
            lb = QVBoxLayout(box)
            val = QLabel("--")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet("font-size:20px; font-weight:800; color:#4F46E5;")
            u = QLabel(unit)
            u.setAlignment(Qt.AlignCenter)
            u.setObjectName("Muted")
            lb.addWidget(val)
            lb.addWidget(u)
            l1.addWidget(box, c // 2, c % 2)   # 2 列：窄宽下不裁切
            self.lbl_meas[key] = val
        lay.addWidget(g1)

        g2 = QGroupBox("纹波峰谷")
        l2 = QGridLayout(g2)
        self.lbl_ripple = {}
        for c, (key, name) in enumerate((
                ("VPP", "Vpp"), ("IPP", "IPP"), ("VP+", "VP+"), ("VP-", "VP-"))):
            lb = QLabel(f"{name}: --")
            lb.setStyleSheet("font-family:Consolas; font-weight:700;")
            l2.addWidget(lb, c // 2, c % 2)
            self.lbl_ripple[key] = lb
        lay.addWidget(g2)

        g3 = QGroupBox("保护状态位（STAT:QUES:COND）")
        l3 = QGridLayout(g3)
        self.lbl_bits = {}
        for i, (bit, name, cn) in enumerate(P.QUESTIONABLE_BITS):
            lb = QLabel(f"{name} ●")
            lb.setToolTip(f"bit{bit} {cn}")
            lb.setStyleSheet("color:#C9C6E4; font-family:Consolas;")
            l3.addWidget(lb, i // 2, i % 2)
            self.lbl_bits[name] = lb
        lay.addWidget(g3)
        lay.addStretch(1)
        return w

    # ================================================================ 动作
    def refresh_ports(self) -> None:
        cur = self.cmb_port.currentText()
        self.cmb_port.clear()
        self.cmb_port.addItems(list_ports() or ["COM3"])
        if cur:
            self.cmb_port.setCurrentText(cur)

    def toggle_conn(self) -> None:
        if self.dev is not None:
            self._disconnect("用户断开")
            return
        try:
            if self.chk_sim.isChecked():
                tr = SimTransport()
            else:
                tr = SerialTransport(self.cmb_port.currentText().strip(),
                                     baudrate=int(self.cmb_baud.currentText()),
                                     parity=self.cmb_parity.currentText())
            tr.open()
            dev = LoadDevice(tr, limits=self._limits())
            dev.trace_hook = self._on_trace
            info = dev.identify()
            self.dev = dev
            self.btn_conn.setText("已连接")
            self.btn_conn.setObjectName("btnConnected")
            self.lbl_idn.setText(f"已连接：{info['manufacturer']} {info['model']}"
                                 f" · {info['serial']} · {info['version']}")
            self._log(f"连接成功：{info['raw']}")
        except Exception as e:  # noqa: BLE001
            self._disconnect(f"连接失败：{e}", keep_text=True)

    def _disconnect(self, reason: str, keep_text: bool = False) -> None:
        self._poll_fail = 0
        self._poll_lost = False
        self._poll.setInterval(1000)   # 复位掉线低频探测，重连后按正常周期轮询
        if self.dev is not None:
            try:
                self.dev.t.close()
            except Exception:
                pass
            self.dev = None
        if not keep_text:
            self.btn_conn.setText("连接")
            self.btn_conn.setObjectName("btnConnect")
            self.lbl_idn.setText("未连接")
        self._log(reason)

    def _limits(self) -> dict:
        return {"current": self.sp_lim_i.value(), "voltage": self.sp_lim_v.value(),
                "power": self.sp_lim_p.value(), "resistance": self.sp_lim_r.value()}

    def _ensure(self) -> bool:
        if self.dev is None:
            self._log("请先连接设备（或勾选模拟设备）")
            return False
        return True

    def _mode(self) -> str:
        for key, rb in self.mode_group:
            if rb.isChecked():
                return key
        return "CC"

    def _on_mode_change(self) -> None:
        key = self._mode()
        unit = P.SET_UNIT.get(key, "")
        label = P.SET_LABEL.get(key, "设定值")
        self.lbl_value.setText(f"当前模式 {key}：{label}")
        self.lbl_value_unit.setText(unit)
        self.sp_value.setEnabled(key in P.SET_CMD)
        # 切换模式自动回读该模式当前设定值并回填输入框（DYNA/LED 无设定值命令）
        if self.dev is not None and key in P.SET_CMD:
            def _job(out, k=key):
                try:
                    out.put(("mode_val", (k, self.dev.read_value(k))))
                except Exception as e:  # noqa: BLE001
                    out.put(("log", f"模式 {k} 设定值回读失败：{e}"))
            self.worker.submit(_job)

    # ---- 基本控制
    def on_set_mode(self) -> None:
        key = self._mode()
        self._submit(lambda out: self.dev.set_mode(key), f"下发模式 {key}")

    def on_set_value(self) -> None:
        key = self._mode()
        val = self.sp_value.value()
        if key not in P.SET_CMD:
            self._log(f"模式 {key} 无设定值命令")
            return
        self._submit(lambda out: self.dev.set_value(key, val),
                     f"设定 {P.SET_LABEL.get(key, key)} {val:.6g} {P.SET_UNIT.get(key, '')}")

    def on_set_protection(self) -> None:
        i, p = self.sp_prot_i.value(), self.sp_prot_p.value()
        self._submit(lambda out: self.dev.set_protection(current=i, power=p),
                     f"设定保护 I={i:.6g}A P={p:.6g}W")

    def on_set_vonoff(self) -> None:
        von, voff = self.sp_von.value(), self.sp_voff.value()
        self._submit(lambda out: self.dev.set_von_voff(von=von, voff=voff),
                     f"设定 Von={von:.6g}V Voff={voff:.6g}V")

    def on_set_slew(self) -> None:
        v = self.sp_slew.value()
        self._submit(lambda out: self.dev.set_slew(v), f"设定电流斜率 {v:.6g}A/uS")

    # ---- 动态 / 输入
    def on_set_dyn(self) -> None:
        lo, hi = self.sp_dyn_low.value(), self.sp_dyn_high.value()
        tl, th = self.sp_dyn_tl.value(), self.sp_dyn_th.value()
        self._submit(lambda out: self.dev.set_dynamic(lo, hi, tl, th),
                     f"下发动态 Ia={lo:.6g}A Ib={hi:.6g}A Ta={tl:.6g}s Tb={th:.6g}s")

    def on_input(self, on: bool) -> None:
        if not self._ensure():
            return
        if on:
            dlg = ConfirmOutputDialog("JT6321A 电子负载", "开启负载（输入 ON）",
                                      "开启后将按当前模式拉载，被测体将承受负载电流！"
                                      "确认接线/量程/散热无误后再开启。",
                                      f"模式 {self._mode()}　拉载 {self.sp_value.value():.6g}"
                                      f"{self.lbl_value_unit.text()}", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        self._submit(lambda out: self._input_job(on), f"{'开启' if on else '关闭'}负载")

    def _input_job(self, on: bool) -> None:
        ok, last = self.dev.set_input(on)
        self._q.put(("log", f"负载{'开启' if on else '关闭'}"
                            f"{'成功' if ok else '未确认（回读 ' + str(last) + '）'}"))

    def on_short(self, on: bool) -> None:
        if not self._ensure():
            return
        if on:
            dlg = ConfirmOutputDialog("JT6321A 电子负载", "短路模拟 ON",
                                      "短路模拟将把输入端强制短接，被测体可能承受极大电流！"
                                      "仅限专用测试场景，确认安全后再执行。", "INP:SHOR ON", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        self._submit(lambda out: self._short_job(on), f"短路 {'ON' if on else 'OFF'}")

    def _short_job(self, on: bool) -> None:
        ok, last = self.dev.set_short(on)
        self._q.put(("log", f"短路{'开启' if on else '关闭'}"
                            f"{'成功' if ok else '未确认（回读 ' + str(last) + '）'}"))

    def on_reset(self) -> None:
        self._submit(lambda out: self.dev.reset(), "复位 *RST")

    def on_read_error(self) -> None:
        self._submit(lambda out: self._q.put(("log", f"错误码：{self.dev.clear_error()}")),
                     "读错误码")

    def on_read_all(self) -> None:
        def _job(_out):
            mode = self.dev.read_mode()
            lines = [f"模式={mode}"]
            for key in ("CC", "CV", "CP", "CR"):
                try:
                    lines.append(f"{P.SET_LABEL[key]}={self.dev.read_value(key):.6g}"
                                 f"{P.SET_UNIT[key]}")
                except Exception:
                    pass
            prot = self.dev.read_protection()
            if prot:
                lines.append("保护 " + " ".join(f"{k}={v:.6g}" for k, v in prot.items()))
            self._q.put(("log", "读回设定值：" + "；".join(lines)))
        self._submit(_job, "读回设定值")

    # ---- OCP
    def on_ocp_setup(self) -> None:
        i_s, i_e = self.sp_ocp_is.value(), self.sp_ocp_ie.value()
        st, dw, vt = (self.sp_ocp_step.value(), self.sp_ocp_dwell.value(),
                      self.sp_ocp_vtrig.value())
        self._submit(lambda out: self.dev.ocp_setup(i_s, i_e, st, dw, vt),
                     f"下发 OCP 参数 I={i_s:.6g}~{i_e:.6g}A 步数 {st}")

    def on_ocp(self, on: bool) -> None:
        if on:
            if not self._ensure():
                return
            dlg = ConfirmOutputDialog("JT6321A 电子负载", "启动 OCP 测试",
                                      "OCP 测试会逐级拉载直到被测体过流保护，"
                                      "被测体将经历大电流冲击！确认安全后再启动。",
                                      f"I={self.sp_ocp_is.value():.6g}~"
                                      f"{self.sp_ocp_ie.value():.6g}A", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        self._submit(lambda out: self.dev.ocp_start(on), f"{'启动' if on else '停止'} OCP")

    def on_ocp_result(self) -> None:
        def _job(_out):
            res = self.dev.ocp_result()
            self._q.put(("ocp_res", res))
            pmax = self.dev.ocp_pmax()
            self._q.put(("ocp_pmax", pmax))
        self._submit(_job, "读 OCP 结果")

    def on_apply_limits(self) -> None:
        limits = self._limits()
        if self.dev is not None:
            self.dev.limits.update(limits)
        self._log("量程上限已应用："
                  + " ".join(f"{P.LIMIT_LABEL[k]}={v:.6g}{P.LIMIT_UNIT[k]}"
                             for k, v in limits.items()))

    # ================================================================ 线程/事件
    def _submit(self, fn, label: str) -> None:
        if self.dev is None:
            self._log("请先连接设备（或勾选模拟设备）")
            return

        def _job(out):
            try:
                fn(out)
                out.put(("log", f"{label} ✓"))
            except Exception as e:  # noqa: BLE001
                out.put(("log", f"{label} 失败：{e}"))
        self.worker.submit(_job)

    def _submit_poll(self) -> None:
        if self.dev is None or self._poll_inflight or self.worker.busy:
            return
        self._poll_inflight = True

        def _job(out):
            try:
                meas = self.dev.read_measure(("V", "I", "P", "R", "VPP", "IPP", "VP+", "VP-"))
                out.put(("meas", meas))
                out.put(("status", self.dev.read_status()))
            except Exception as e:  # noqa: BLE001
                out.put(("poll_fail", str(e)))   # 由 UI 侧计数感知掉线
            finally:
                out.put(("poll_done",))
        self.worker.submit(_job)

    def _on_trace(self, cmd: str, resp: str) -> None:
        self._q.put(("trace", (cmd, resp)))

    def _on_frames_toggled(self, on: bool) -> None:
        self._show_frames = on

    def _log(self, text: str) -> None:
        self.log.appendPlainText(str(text))

    def _drain(self) -> None:
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "log":
                self._log(item[1])
            elif kind == "trace":
                if self._show_frames:
                    cmd, resp = item[1]
                    self._log(f"TX {cmd}" + (f"\nRX {resp}" if resp else ""))
            elif kind == "meas":
                from instrument_hub.comm_state import mark_ok
                mark_ok(self)   # 测量数据更新 = 通讯真正建立
                if self._poll_lost:   # 掉线后恢复应答：自动恢复在线 + 回到原轮询周期
                    self._poll_lost = False
                    self._poll.setInterval(1000)
                    self._log("设备恢复应答，自动恢复在线")
                self._poll_fail = 0
                for k, v in item[1].items():
                    if k in self.lbl_meas:
                        self.lbl_meas[k].setText("--" if v is None else f"{v:.4f}")
                    if k in self.lbl_ripple:
                        self.lbl_ripple[k].setText(
                            f"{self.lbl_ripple[k].text().split(':')[0]}: "
                            + ("--" if v is None else f"{v:.4f}"))
            elif kind == "status":
                st = item[1]
                for name, lb in self.lbl_bits.items():
                    on = bool(st.get(name))
                    lb.setStyleSheet(
                        f"color:{'#EF4444' if on else '#C9C6E4'}; font-family:Consolas;"
                        f" font-weight:700;")
            elif kind == "ocp_res":
                res = item[1]
                self.lbl_ocp_res.setText(res["text"] if res else "-")
            elif kind == "mode_val":
                k, v = item[1]
                if k == self._mode():   # 防快速切换：只回填仍选中模式的值
                    self.sp_value.setValue(float(v))
                    self._log(f"模式 {k} 当前设定值已回读：{v:.6g}"
                              f"{P.SET_UNIT.get(k, '')}")
            elif kind == "ocp_pmax":
                pm = item[1]
                self.lbl_ocp_pmax.setText(
                    f"P={pm['power']:.4f}W V={pm['voltage']:.4f}V I={pm['current']:.4f}A"
                    if pm else "-")
            elif kind == "poll_fail":
                self._poll_fail += 1
                self._log(f"轮询失败：{item[1]}")
                if self._poll_fail >= 3 and not self._poll_lost:
                    from instrument_hub.comm_state import mark_lost
                    mark_lost(self)   # 连续无应答 = 通讯中断
                    self._poll_lost = True
                    self._poll.setInterval(2000)   # 降为低频探测，恢复可自动上线
                    self._log(f"设备连续 {self._poll_fail} 次无响应，"
                              "标记离线（降为 2s 低频探测，恢复应答后自动上线）")
            elif kind == "poll_done":
                self._poll_inflight = False

    # ================================================================ 清理
    def shutdown(self) -> None:
        """退出：关闭负载（防拉载保持）→ 断开 → 回收线程。"""
        try:
            self._poll.stop()
            self._pump.stop()
            if self.dev is not None:
                try:
                    self.dev.set_input(False, tries=1)
                except Exception:
                    pass
                try:
                    self.dev.t.close()
                except Exception:
                    pass
                self.dev = None
            self.worker.stop()
        except Exception:
            pass
