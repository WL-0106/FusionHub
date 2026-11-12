# -*- coding: utf-8 -*-
"""HSPY 可编程直流电源（多机型融合）· 融合版界面（FusionHub 风格）。

Modbus-RTU 协议栈 / 串口驱动 / 内置仿真 / 机型预设复用原上位机 core 包
（HspyProtocol / HspyDevice / HspySim / HspyModels，零改动），
界面按整体 UI 风格重建：运行监控 / 参数设置 / 量程设置 / 寄存器表 + 底部通讯日志。

安全闭环：开启输出二次确认；退出/卸载自动停记录、关输出、断开、停工作线程。
"""
import csv
import datetime
import json
import math
import os
import queue
import threading
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QScrollArea, QSpinBox, QSplitter, QStackedWidget,
                             QTabWidget, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog
from instrument_hub.widgets import Card, WaveformWidget

from .core.HspyDevice import (HspyDevice, SIM_PORT_NAME, available_ports,
                              probe_com_ports)
from .core.HspyModels import (CUSTOM, DEFAULT_MODEL, HSPY_1000_01, MODELS,
                              detect_by_ranges, get_model, model_names)
from .core.HspyProtocol import (REGISTERS, decimals_of, format_frame, reg,
                                reset_decimals, set_decimals)

CFG_FILE = os.path.join(os.path.expanduser("~"), ".hspy_unified.json")
CFG_PARITY = {"无 (None)": "N", "偶 (Even)": "E", "奇 (Odd)": "O"}
DEC_CHOICES = ["0", "1", "2", "3", "4"]


def _to_float(text, default: float) -> float:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return default


def _to_int(text, default: int) -> int:
    try:
        return int(float(str(text).strip()))
    except (TypeError, ValueError):
        return default


class HspyPage(QWidget):
    """HSPY 电源上位机：连接 → 机型预设 → 设定/输出 → 轮询监控 → 参数/量程/寄存器调试。"""

    PARAM_KEYS = ["ovp", "ocp", "mode", "up_start", "auto_err",
                  "key_lock", "down_save", "rs_addr", "rs_bt", "rs_stop", "set_out"]
    OPTIONS = {
        "mode": ["0", "1", "2"], "up_start": ["0", "1"], "auto_err": ["0", "1"],
        "key_lock": ["0", "1"], "down_save": ["0", "1"], "rs_bt": ["0", "3"],
        "rs_stop": ["1", "2"], "set_out": ["0", "1"],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dev: HspyDevice = None
        self.connected = False
        self._model = DEFAULT_MODEL

        # ---- 后台工作线程（沿用原工程单线程命令队列模型） ---- #
        self.cmd_q = queue.Queue()
        self.ui_q = queue.Queue()
        self.log_q = queue.Queue()
        self.stop_evt = threading.Event()
        self.worker = None
        self._poll_enabled = True
        self._poll_period = 0.5
        self._settle_sec = 0.2
        self._last_poll = 0.0
        self._poll_fail = 0              # 连续轮询失败计数（成功清零）
        self._poll_lost = False          # 掉线标记：True 时降为 2s 低频探测
        self._pending_verify = None      # 输出前校验：期望原始值 {set_u/set_i: raw}
        self._verify_seen = {}           # 输出前校验：回读到的原始值
        self._written = {}               # 写后回读比对基准 {key: 期望原始值}
        self._rb_raw = {"set_u": None, "set_i": None}   # 回读框缓存的设备原始值
        self._out_on = False             # 输出开关按钮当前态（跟随设备状态）
        self._out_buttons = []           # 各面板电流设定行末的单键输出开关
        self._link_confirmed = False     # 设备应答过才标「已连接」
        self._port_name = ""
        self._conn_timer = QTimer(self)   # 握手超时：连接后无应答自动断开
        self._conn_timer.setSingleShot(True)
        self._conn_timer.setInterval(6000)
        self._conn_timer.timeout.connect(self._on_conn_timeout)

        # ---- CSV 记录 ---- #
        self.recording = False
        self.rec_file = None
        self.rec_writer = None
        self._rec_count = 0
        self._rec_path = ""

        self._build_ui()
        self._load_cfg()
        self._start_worker()
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._drain_ui)
        self._timer.start()

    # ================================================================ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        root.addWidget(self._build_conn_card())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_run_tab(), "运行监控")
        self.tabs.addTab(self._build_param_tab(), "参数设置")
        self.tabs.addTab(self._build_cfg_tab(), "量程设置")
        self.tabs.addTab(self._build_map_tab(), "寄存器表")
        self._tab_pages = [self.tabs.widget(i) for i in range(4)]
        self._TAB_TITLES = ["运行监控", "参数设置", "量程设置", "寄存器表"]
        root.addWidget(self.tabs, 1)

        root.addWidget(self._build_log_group())
        self._refresh_ports()

    # ---------------------------------------------------------- 连接栏
    def _build_conn_card(self) -> Card:
        card = Card("通讯连接",
                    "RS232/RS485 串口直连 · Modbus-RTU（FC03/FC06/FC10，CRC16 低字节在前）· "
                    "默认 9600-8-N-2；连不上可先试停止位 1")
        h = QHBoxLayout()
        h.setSpacing(8)

        h.addWidget(QLabel("端口"))
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setFixedWidth(240)   # 完整显示「COMx + 设备描述」
        self.cmb_port.currentTextChanged.connect(lambda t: self.cmb_port.setToolTip(t))
        h.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(lambda: self._refresh_ports(True))
        h.addWidget(self.btn_refresh)

        h.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.cmb_baud.setFixedWidth(90)
        h.addWidget(self.cmb_baud)

        h.addWidget(QLabel("校验"))
        self.cmb_parity = QComboBox()
        self.cmb_parity.addItems(list(CFG_PARITY))
        self.cmb_parity.setFixedWidth(104)
        h.addWidget(self.cmb_parity)

        h.addWidget(QLabel("停止位"))
        self.cmb_stop = QComboBox()
        self.cmb_stop.addItems(["2", "1"])
        self.cmb_stop.setFixedWidth(60)
        h.addWidget(self.cmb_stop)

        h.addWidget(QLabel("地址"))
        self.sp_slave = QSpinBox()
        self.sp_slave.setRange(0, 255)
        self.sp_slave.setValue(1)
        self.sp_slave.setFixedWidth(64)
        h.addWidget(self.sp_slave)

        h.addWidget(QLabel("机型"))
        self.cmb_model = QComboBox()
        self.cmb_model.addItems(model_names())
        self.cmb_model.setMinimumWidth(210)
        self.cmb_model.currentTextChanged.connect(self.on_model_change)
        h.addWidget(self.cmb_model)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.toggle_connect)
        h.addWidget(self.btn_connect)
        h.addStretch(1)

        self.lbl_stats = QLabel("TX 0 / RX 0 / ERR 0")
        self.lbl_stats.setObjectName("Muted")
        h.addWidget(self.lbl_stats)
        self.lbl_state = QLabel("未连接")
        self.lbl_state.setObjectName("Muted")
        h.addWidget(self.lbl_state)
        card.body_lay.addLayout(h)
        return card

    # ---------------------------------------------------------- 运行监控
    def _build_run_tab(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        # 左：输出控制（双布局：30 系列/通用面板 ↔ HSPY-1000-01 专属面板，随机型切换）
        left = Card("输出控制", "设定 → 下发 → 开启输出（二次确认）")
        self._set_rows_a = {}
        self._set_rows_b = {}
        self._set_rows = self._set_rows_a
        self._limit_spins = {}
        self.ctl_stack = QStackedWidget()
        self.ctl_stack.addWidget(self._build_panel_30())
        self.ctl_stack.addWidget(self._build_panel_1000())
        left.body_lay.addWidget(self.ctl_stack)

        # 回读框 + 回读按钮（输出前安全闭环：设定值 vs 回读值比对）
        rb = QHBoxLayout()
        rb.setSpacing(6)
        rb.addWidget(QLabel("回读"))
        self.ent_rb_u = QLineEdit("—")
        self.ent_rb_u.setReadOnly(True)
        self.ent_rb_u.setFixedWidth(150)
        self.ent_rb_u.setStyleSheet("font-family:Consolas;")
        self.ent_rb_u.setToolTip("设备回读的电压设定值（物理量 + 寄存器原始值，原始值可与仪器面板对表）")
        rb.addWidget(self.ent_rb_u)
        rb.addWidget(QLabel("V"))
        self.ent_rb_i = QLineEdit("—")
        self.ent_rb_i.setReadOnly(True)
        self.ent_rb_i.setFixedWidth(150)
        self.ent_rb_i.setStyleSheet("font-family:Consolas;")
        self.ent_rb_i.setToolTip("设备回读的电流设定值（物理量 + 寄存器原始值，原始值可与仪器面板对表）")
        rb.addWidget(self.ent_rb_i)
        rb.addWidget(QLabel("A"))
        b_rb = QPushButton("回读")
        b_rb.setToolTip("读回电压/电流设定寄存器并显示在此（设定值下发后也会自动回读）")
        b_rb.clicked.connect(self._read_setpoints)
        rb.addWidget(b_rb)
        rb.addStretch(1)
        left.body_lay.addLayout(rb)

        # 输出开关极性（放输出区全系列可见：1000-01 无量程设置页签，藏那里会改不回来）
        pol = QHBoxLayout()
        pol.setSpacing(6)
        pol.addWidget(QLabel("输出开关极性"))
        self.cmb_polarity = QComboBox()
        self.cmb_polarity.addItems(["0=停止, 1=输出（协议默认）", "反相：0=输出, 1=停止"])
        self.cmb_polarity.setFixedWidth(220)
        self.cmb_polarity.setToolTip(
            "设备输出寄存器方向与协议相反时才改反相；极性不一致会导致"
            "「界面显示输出中但电源实际未输出/关不掉」")
        pol.addWidget(self.cmb_polarity)
        n = QLabel("关不掉 / 不输出时改反相")
        n.setObjectName("Muted")
        pol.addWidget(n)
        pol.addStretch(1)
        left.body_lay.addLayout(pol)

        # 开/关输出合并为单键开关，放在各面板「电流设定」行末（绿色开启 ↔ 红色关闭）
        self.lbl_out = QLabel("输出状态：—")
        self.lbl_cccv = QLabel("工作模式：—")
        self.lbl_lock = QLabel("按键锁定：—")
        for lb in (self.lbl_out, self.lbl_cccv, self.lbl_lock):
            lb.setObjectName("Muted")
            left.body_lay.addWidget(lb)
        self.lbl_conv = QLabel("")
        self.lbl_conv.setObjectName("Muted")
        self.lbl_conv.setWordWrap(True)
        left.body_lay.addWidget(self.lbl_conv)
        left.body_lay.addStretch(1)

        # 左右分割条：输出控制 | 大数+曲线，手柄可拖拉缩放
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(14)
        split.setChildrenCollapsible(False)
        lw = QScrollArea()
        lw.setWidgetResizable(True)
        lw.setFrameShape(QScrollArea.NoFrame)
        lw.setWidget(left)
        lw.setMinimumWidth(300)
        split.addWidget(lw)
        self._run_split = split

        # 右：大数 + 曲线
        right = QWidget()
        v = QVBoxLayout(right)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        cards = QHBoxLayout()
        cards.setSpacing(8)
        self.cards = {}
        for key, title, unit, color in (("u", "电压 U", "V", "#0d9b6c"),
                                        ("i", "电流 I", "A", "#1f7ae0"),
                                        ("p", "功率 P", "W", "#c98a00")):
            c = Card(title)
            big = QLabel("--.--")
            big.setStyleSheet(f"font-size:26px; font-weight:700; color:{color};")
            c.body_lay.addWidget(big)
            u = QLabel(unit)
            u.setObjectName("Muted")
            c.body_lay.addWidget(u)
            cards.addWidget(c, 1)
            self.cards[key] = big
        v.addLayout(cards)

        head = QHBoxLayout()
        head.addWidget(QLabel("实时曲线"))
        tip = QLabel("电压(绿) / 电流(蓝) / 功率(琥珀)")
        tip.setObjectName("Muted")
        head.addWidget(tip)
        head.addStretch(1)
        self.btn_rec = QPushButton("● 记录CSV")
        self.btn_rec.clicked.connect(self.toggle_record)
        head.addWidget(self.btn_rec)
        self.btn_read_all = QPushButton("一键读取")
        self.btn_read_all.clicked.connect(lambda: self.submit("read_all"))
        head.addWidget(self.btn_read_all)
        self.btn_poll = QPushButton("暂停轮询")
        self.btn_poll.clicked.connect(self.toggle_polling)
        head.addWidget(self.btn_poll)
        self.btn_clear_chart = QPushButton("清空曲线")
        self.btn_clear_chart.clicked.connect(lambda: self.chart.clear())
        head.addWidget(self.btn_clear_chart)
        v.addLayout(head)

        self.chart = WaveformWidget()
        self.chart.add_channel("u", "U", "V", "#34d399", (0.0, 60.0))
        self.chart.add_channel("i", "I", "A", "#60a5fa", (0.0, 10.0))
        self.chart.add_channel("p", "P", "W", "#fbbf24", (0.0, 600.0))
        v.addWidget(self.chart, 1)

        self.lbl_last = QLabel("最近报文：—")
        self.lbl_last.setObjectName("Muted")
        v.addWidget(self.lbl_last)
        self.lbl_rec = QLabel("数据记录：未开始（点「● 记录CSV」按轮询写入 CSV）")
        self.lbl_rec.setObjectName("Muted")
        v.addWidget(self.lbl_rec)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([380, 900])
        h.addWidget(split, 1)
        return wrap

    # ---------------------------------------------------------- 输出控制双布局
    def _build_panel_30(self) -> QWidget:
        """HSPY-30 系列/通用面板：电压/电流/功率设定，行内 设定/读回（原多合一 30 系列界面）。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for key, title, unit, readback in (
                ("set_u", "电压设定", "V", True),
                ("set_i", "电流设定", "A", True),
                ("set_p", "功率设定", "W", False)):
            row = QWidget()
            g = QGridLayout(row)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(4)
            g.addWidget(QLabel(title), 0, 0, 1, 3)
            spn = QDoubleSpinBox()
            spn.setDecimals(3 if key == "set_i" else 2)
            spn.setRange(0, 65535)
            spn.setValue(0)
            spn.setFixedWidth(110)
            spn.valueChanged.connect(lambda _v, k=key: self._mark_dirty(k))
            g.addWidget(spn, 1, 0)
            g.addWidget(QLabel(unit), 1, 1)
            btns = QWidget()
            bh = QHBoxLayout(btns)
            bh.setContentsMargins(0, 0, 0, 0)
            bh.setSpacing(4)
            b_set = QPushButton("设定")
            b_set.clicked.connect(lambda _c, k=key, s=spn: self.on_set_key(k, s.value()))
            bh.addWidget(b_set)
            if readback:
                b_rd = QPushButton("读回")
                b_rd.clicked.connect(lambda _c, k=key: self.submit("read_key", k))
                bh.addWidget(b_rd)
            if key == "set_i":
                self._make_out_toggle(bh)   # 开/关输出单键开关（电流设定行末）
            g.addWidget(btns, 1, 2)
            hint = QLabel("")
            hint.setStyleSheet("color:#B45309; font-size:11px;")
            g.addWidget(hint, 2, 0, 1, 3)
            raw = QLabel("")
            raw.setObjectName("Muted")
            raw.setStyleSheet("font-family:Consolas; font-size:11px;")
            g.addWidget(raw, 3, 0, 1, 3)
            lay.addWidget(row)
            self._set_rows_a[key] = (spn, hint, raw)
        lay.addStretch(1)
        return w

    def _build_panel_1000(self) -> QWidget:
        """HSPY-1000-01 专属面板（对齐原版多合一 1000-01 界面）：
        电压设定 + 上限 / 电流设定（限流）+ 上限、换算系数（×10 / ×10000 + 校核）、
        写入设定 / 读回设定、原始寄存器快捷读写、高压提示。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        def _limit_spin(maximum: float, tip: str) -> QDoubleSpinBox:
            sp = QDoubleSpinBox()
            sp.setDecimals(4)
            sp.setRange(0.0, maximum)
            sp.setValue(maximum)          # 默认满量程=不额外限幅
            sp.setSpecialValueText("不限")   # 0 = 不限幅，消除「上限 0.0000」误读
            sp.setFixedWidth(96)
            sp.setToolTip(tip)
            return sp

        def _set_block(key: str, title: str, unit: str,
                       decimals: int, srange: float) -> None:
            # 整行布局（垂直堆叠）：两列并排在窄面板会叠字裁切，整行保证任何宽度可读
            box = QWidget()
            g = QGridLayout(box)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(4)
            g.addWidget(QLabel(title), 0, 0, 1, 5)
            spn = QDoubleSpinBox()
            spn.setDecimals(decimals)
            spn.setRange(0, 65535)
            spn.setValue(0)
            spn.setFixedWidth(110)
            spn.valueChanged.connect(lambda _v, k=key: self._mark_dirty(k))
            g.addWidget(spn, 1, 0)
            g.addWidget(QLabel(unit), 1, 1)
            g.addWidget(QLabel("上限"), 1, 2)
            lim = _limit_spin(srange,
                              "设定值输入上限：仅限制本软件可输入的最大值（本地限幅，不写入电源），"
                              "防 1000 V 机型误输。保护门限请到「参数设置」OVP/OCP。")
            lim.valueChanged.connect(self._apply_spin_limits)
            g.addWidget(lim, 1, 3)
            g.setColumnStretch(4, 1)
            self._limit_spins["ovp" if key == "set_u" else "ocp"] = lim
            if key == "set_i":
                self._make_out_toggle(g, (1, 4))   # 开/关输出单键开关（电流设定行末）
            hint = QLabel("")
            hint.setStyleSheet("color:#B45309; font-size:11px;")
            g.addWidget(hint, 2, 0, 1, 5)
            raw = QLabel("")
            raw.setObjectName("Muted")
            raw.setStyleSheet("font-family:Consolas; font-size:11px;")
            g.addWidget(raw, 3, 0, 1, 5)
            self._set_rows_b[key] = (spn, hint, raw)
            lay.addWidget(box)

        _set_block("set_u", "电压设定", "V", 1, 6553.5)
        _set_block("set_i", "电流设定（限流）", "A", 4, 6.5535)
        # 功率设定在本面板不暴露（原版 1000-01 无该行）；隐藏行供换算/提示机制统一使用
        self._set_rows_b["set_p"] = (QDoubleSpinBox(), QLabel(), QLabel())

        # 换算系数（与「量程设置」小数位同一配置源）
        conv = QHBoxLayout()
        conv.setSpacing(6)
        conv.addWidget(QLabel("换算系数"))
        self.conv_v = QComboBox()
        self.conv_i = QComboBox()
        for cb, key in ((self.conv_v, "vdec"), (self.conv_i, "idec")):
            cb.blockSignals(True)   # 构建期不触发 _conv_scale_changed
            for dec in range(5):
                cb.addItem(f"×{10 ** dec:g}", dec)
            cb.blockSignals(False)
            cb.setFixedWidth(76)
            cb.currentIndexChanged.connect(
                lambda _i, k=key, c=cb: self._conv_scale_changed(k, c.currentData()))
        conv.addWidget(QLabel("电压"))
        conv.addWidget(self.conv_v)
        conv.addWidget(QLabel("电流"))
        conv.addWidget(self.conv_i)
        b_check = QPushButton("校核")
        b_check.setToolTip("换算校核：读回设定寄存器，在日志对照「原始值 ↔ 物理量」核对换算系数")
        b_check.clicked.connect(self._scale_check)
        conv.addWidget(b_check)
        conv.addStretch(1)
        lay.addLayout(conv)
        self.lbl_range_tip = QLabel("")
        self.lbl_range_tip.setObjectName("Muted")
        self.lbl_range_tip.setWordWrap(True)   # 窄面板换行不裁切
        lay.addWidget(self.lbl_range_tip)

        wr = QHBoxLayout()
        wr.setSpacing(6)
        b_wr = QPushButton("写入设定")
        b_wr.clicked.connect(self._write_setpoints)
        wr.addWidget(b_wr)
        b_rd = QPushButton("读回设定")
        b_rd.clicked.connect(self._read_setpoints)
        wr.addWidget(b_rd)
        wr.addStretch(1)
        lay.addLayout(wr)

        # 原始寄存器快捷读写（与「寄存器表」同一命令路径）
        rw = QHBoxLayout()
        rw.setSpacing(6)
        rw.addWidget(QLabel("原始寄存器"))
        self.ent_qaddr = QLineEdit("0x1000")
        self.ent_qaddr.setFixedWidth(72)
        rw.addWidget(self.ent_qaddr)
        self.ent_qval = QLineEdit("0")
        self.ent_qval.setFixedWidth(72)
        rw.addWidget(self.ent_qval)
        b_qr = QPushButton("读")
        b_qr.clicked.connect(self._quick_raw_read)
        rw.addWidget(b_qr)
        b_qw = QPushButton("写")
        b_qw.clicked.connect(self._quick_raw_write)
        rw.addWidget(b_qw)
        n = QLabel("hex")
        n.setObjectName("Muted")
        n.setToolTip("地址/数值：0x 十六进制或十进制整数，范围 0~65535")
        rw.addWidget(n)
        rw.addStretch(1)
        lay.addLayout(rw)

        warn = QLabel("⚠ 高压输出，上电前确认负载与散热")
        warn.setStyleSheet("color:#B45309; font-size:11px;")
        lay.addWidget(warn)
        lay.addStretch(1)
        return w

    def _switch_panel(self, is_1000: bool) -> None:
        """输出控制双布局切换：携带设定值，活动行集随之切换（后端处理器不变）。"""
        if not hasattr(self, "ctl_stack"):
            return
        idx = 1 if is_1000 else 0
        if self.ctl_stack.currentIndex() == idx:
            return
        src = self._set_rows
        dst = self._set_rows_b if is_1000 else self._set_rows_a
        vals = {k: src[k][0].value() for k in ("set_u", "set_i", "set_p") if k in src}
        self._set_rows = dst
        for k, v in vals.items():
            if k in dst:
                self._sync_setter(k, v)
        self.ctl_stack.setCurrentIndex(idx)
        self._apply_cfg(None, False)
        self._append_log(
            "info",
            "输出控制已切换为 HSPY-1000-01 专属面板（电压/电流设定+输入上限+换算系数）"
            if is_1000 else
            "输出控制已切换为 30 系列/通用面板（电压/电流/功率设定）")

    def _sync_series_ui(self, name=None) -> None:
        """按机型同步系列专属 UI：1000-01 专属输出面板 + 仅运行监控页签；其余系列恢复四页签。"""
        is_1000 = (self._model if name is None else name) == HSPY_1000_01
        self._apply_tab_visibility(is_1000)
        self._switch_panel(is_1000)

    def _apply_tab_visibility(self, is_1000: bool) -> None:
        """HSPY-1000-01 对齐原版多合一：无「参数设置/量程设置/寄存器表」页签，只留运行监控
        （换算系数/原始寄存器已折叠在 1000-01 专属面板内）；运行监控标题附电压系数备注。"""
        order = (0,) if is_1000 else (0, 1, 2, 3)
        titles = list(self._TAB_TITLES)
        if is_1000:
            titles[0] = "运行监控（注：HSPY-1000-01 电压系数为 1）"
        cur_order = tuple(self._tab_pages.index(self.tabs.widget(i))
                          for i in range(self.tabs.count()))
        if cur_order == order and self.tabs.tabText(0) == titles[0]:
            return
        cur = self.tabs.currentWidget()
        while self.tabs.count():
            self.tabs.removeTab(0)
        for i in order:
            self.tabs.addTab(self._tab_pages[i], titles[i])
        self.tabs.setCurrentWidget(cur if cur in (self._tab_pages[i] for i in order)
                                   else self._tab_pages[0])

    def _apply_spin_limits(self, *_args) -> None:
        """按「上限」钳位活动面板设定值输入范围（本地限幅，不写入电源）。

        「上限」旋钮只存在于 1000-01 专属面板——限幅仅在该面板激活时生效；
        30 系列等面板按机型量程放开，避免历史上限值把输入框封死。
        """
        if not getattr(self, "cfg_w", None) or not self._set_rows:
            return   # 构建期信号防护（cfg/行集尚未就绪）
        cfg = self._cfg_snapshot()
        vmax, imax = cfg["vmax"], cfg["imax"]
        on_1000 = (getattr(self, "ctl_stack", None) is not None
                   and self.ctl_stack.currentIndex() == 1)
        if on_1000 and self._limit_spins:
            lu = self._limit_spins["ovp"].value()
            li = self._limit_spins["ocp"].value()
            if lu > 0:
                vmax = min(vmax, lu)
            if li > 0:
                imax = min(imax, li)
        self._set_rows["set_u"][0].setMaximum(vmax)
        self._set_rows["set_i"][0].setMaximum(imax)
        self._set_rows["set_p"][0].setMaximum(cfg["pmax"])

    def _conv_scale_changed(self, key: str, dec: int) -> None:
        """换算系数下拉 ↔ 「量程设置」小数位同一配置源。"""
        if dec is None or not getattr(self, "cfg_w", None):
            return
        self.cfg_w[key].setCurrentText(str(int(dec)))
        self._apply_cfg(None, False)
        self._append_log("info", f"换算系数已更新：{('电压' if key == 'vdec' else '电流')} ×{10 ** int(dec):g}")

    def _write_setpoints(self) -> None:
        self.on_set_key("set_u", self._set_rows["set_u"][0].value())
        self.on_set_key("set_i", self._set_rows["set_i"][0].value())

    def _read_setpoints(self) -> None:
        self.submit("read_key", "set_u")
        self.submit("read_key", "set_i")

    def _scale_check(self) -> None:
        """换算校核：日志给出「原始值 ↔ 物理量」对照并读回设定，核对换算系数。"""
        for key in ("set_u", "set_i"):
            r = reg(key)
            spn = self._set_rows[key][0]
            self._append_log(
                "info",
                f"换算校核 {r.name}：{spn.value():g} {r.unit} → 原始值 "
                f"{r.to_raw(spn.value())}（×{r.scale:g}，{r.d} 位小数）")
        self._read_setpoints()
        self._append_log("info", "已下发读回——若面板读数与此不符，到「量程设置」修正小数位")

    def _quick_raw_read(self) -> None:
        addr = self._parse_int(self.ent_qaddr.text(), "地址")
        if addr is None or not 0 <= addr <= 0xFFFF:
            QMessageBox.warning(self, "地址超范围", "寄存器地址须在 0x0000 ~ 0xFFFF 之间")
            return
        self.submit("raw_read", addr)

    def _quick_raw_write(self) -> None:
        addr = self._parse_int(self.ent_qaddr.text(), "地址")
        value = self._parse_int(self.ent_qval.text(), "数值")
        if addr is None or not 0 <= addr <= 0xFFFF or \
                value is None or not 0 <= value <= 0xFFFF:
            QMessageBox.warning(self, "格式/范围",
                                "地址 / 数值用 0x 十六进制或十进制，范围 0~65535")
            return
        self.submit("raw_write", addr, value)

    # ---------------------------------------------------------- 参数设置
    def _build_param_tab(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(QLabel("参数设置"))
        tip = QLabel("（修改通讯地址 / 波特率 / 停止位后需重新连接）")
        tip.setObjectName("Muted")
        head.addWidget(tip)
        head.addStretch(1)
        self.btn_scan = QPushButton("扫描从机地址")
        self.btn_scan.clicked.connect(lambda: self.submit("scan"))
        head.addWidget(self.btn_scan)
        b_all = QPushButton("一键读取全部")
        b_all.clicked.connect(lambda: self.submit("read_all"))
        head.addWidget(b_all)
        v.addLayout(head)

        self.p_var, self.p_cur, self.p_widget = {}, {}, {}
        grid = QGridLayout()
        grid.setSpacing(8)
        for c, t in enumerate(("参数名称", "通讯地址", "设定值", "", "当前值")):
            lb = QLabel(t)
            lb.setObjectName("Muted")
            grid.addWidget(lb, 0, c)
        for r, key in enumerate(self.PARAM_KEYS, start=1):
            rg = reg(key)
            grid.addWidget(QLabel(f"{rg.name}（{rg.key}）"), r, 0)
            addr = QLabel(f"0x{rg.addr:04X}")
            addr.setStyleSheet("font-family:Consolas;")
            grid.addWidget(addr, r, 1)
            if key in self.OPTIONS:
                w = QComboBox()
                w.addItems(self.OPTIONS[key])
                w.setFixedWidth(90)
            else:
                w = QLineEdit()
                w.setFixedWidth(110)
            self.p_var[key] = w
            cell = QHBoxLayout()
            cell.setSpacing(4)
            cell.addWidget(w)
            if rg.unit:
                u = QLabel(rg.unit)
                u.setObjectName("Muted")
                cell.addWidget(u)
            if rg.note:
                n = QLabel(rg.note)
                n.setObjectName("Muted")
                cell.addWidget(n)
            cell.addStretch(1)
            grid.addLayout(cell, r, 2)
            bw = QWidget()
            bh = QHBoxLayout(bw)
            bh.setContentsMargins(0, 0, 0, 0)
            bh.setSpacing(4)
            b_wr = QPushButton("写入")
            b_wr.clicked.connect(lambda _c, k=key: self.on_set_key(k, self._param_text(k)))
            bh.addWidget(b_wr)
            b_rd = QPushButton("读取")
            b_rd.clicked.connect(lambda _c, k=key: self.submit("read_key", k))
            bh.addWidget(b_rd)
            grid.addWidget(bw, r, 3)
            cur = QLabel("—")
            cur.setStyleSheet("font-family:Consolas; color:#1f7ae0;")
            grid.addWidget(cur, r, 4)
            self.p_cur[key] = cur
        v.addLayout(grid)
        v.addStretch(1)
        return wrap

    # ---------------------------------------------------------- 量程设置
    def _build_cfg_tab(self) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)

        left = Card("量程与小数位",
                    "只影响本软件换算与显示，不写入电源；机型预设一键套用后可微调")
        tip = QLabel("小数位对不上表现为「设 1 A 实出 10 A」：\n"
                     "· 实出约 10 倍 → 设定小数位减 1　· 实出约 0.1 倍 → 设定小数位加 1\n"
                     "换算关系：原始值 = 物理量 × 10^小数位；拿不准用「自动换算标定」。")
        tip.setWordWrap(True)
        tip.setStyleSheet("background:#FFF7E6; color:#8A5A00; border:1px solid #F0C36D;"
                          "border-radius:8px; padding:8px;")
        left.body_lay.addWidget(tip)

        grid = QGridLayout()
        grid.setSpacing(6)
        for c, t in enumerate(("物理量", "量程上限", "设定小数位", "显示小数位", "说明")):
            lb = QLabel(t)
            lb.setObjectName("Muted")
            grid.addWidget(lb, 0, c)
        self.cfg_w = {}

        def dec_combo():
            cb = QComboBox()
            cb.addItems(DEC_CHOICES)
            cb.setFixedWidth(60)
            return cb

        rows = [("电压 U", "vmax", "V", "vdec", "vshow", "设定 / 显示"),
                ("电流 I", "imax", "A", "idec", "ishow", "←「差 10 倍」改这里"),
                ("功率 P", "pmax", "W", "pdec", "pshow", "设定 / 显示"),
                ("过压保护 OVP", None, "", "ovpdec", None, "仅保护门限"),
                ("过流保护 OCP", None, "", "ocpdec", None, "仅保护门限")]
        for r, (name, mx, unit, setdec, showdec, note) in enumerate(rows, start=1):
            grid.addWidget(QLabel(name), r, 0)
            if mx:
                ed = QLineEdit()
                ed.setFixedWidth(80)
                cell = QHBoxLayout()
                cell.setSpacing(4)
                cell.addWidget(ed)
                u = QLabel(unit)
                u.setObjectName("Muted")
                cell.addWidget(u)
                cell.addStretch(1)
                grid.addLayout(cell, r, 1)
                self.cfg_w[mx] = ed
            else:
                dash = QLabel("—")
                dash.setObjectName("Muted")
                grid.addWidget(dash, r, 1)
            for col, key in ((2, setdec), (3, showdec)):
                if key:
                    cb = dec_combo()
                    grid.addWidget(cb, r, col)
                    self.cfg_w[key] = cb
                else:
                    dash = QLabel("—")
                    dash.setObjectName("Muted")
                    grid.addWidget(dash, r, col)
            n = QLabel(note)
            n.setObjectName("Muted")
            grid.addWidget(n, r, 4)
        left.body_lay.addLayout(grid)

        tmg = QGroupBox("通信时序（命令不生效 / 丢帧时加大）")
        tg = QGridLayout(tmg)
        tg.setSpacing(6)
        ttip = QLabel("半双工总线轮询太密时写入帧会被丢掉（表现为「点了没反应」）；"
                      "加大「写入前静默」和「命令后暂停轮询」可自动解决。")
        ttip.setWordWrap(True)
        ttip.setObjectName("Muted")
        tg.addWidget(ttip, 0, 0, 1, 5)
        self.cfg_tm = {}
        for c, (label, key, unit, dflt) in enumerate((
                ("帧间静默", "gap_ms", "ms", "4"), ("写入前静默", "quiet_ms", "ms", "25"),
                ("命令后暂停轮询", "settle_ms", "ms", "200"),
                ("轮询块大小", "poll_chunk", "个", "8"), ("失败重试", "retries", "次", "2"))):
            cell = QVBoxLayout()
            lb = QLabel(label)
            lb.setObjectName("Muted")
            cell.addWidget(lb)
            sub = QHBoxLayout()
            ed = QLineEdit(dflt)
            ed.setFixedWidth(64)
            sub.addWidget(ed)
            u = QLabel(unit)
            u.setObjectName("Muted")
            sub.addWidget(u)
            sub.addStretch(1)
            cell.addLayout(sub)
            tg.addLayout(cell, 1, c)
            self.cfg_tm[key] = ed
        left.body_lay.addWidget(tmg)

        btns = QHBoxLayout()
        b_apply = QPushButton("应用")
        b_apply.clicked.connect(lambda: self._apply_cfg(None, True))
        btns.addWidget(b_apply)
        b_reset = QPushButton("恢复默认")
        b_reset.clicked.connect(self._reset_cfg)
        btns.addWidget(b_reset)
        btns.addStretch(1)
        left.body_lay.addLayout(btns)
        left.body_lay.addStretch(1)

        lw = QScrollArea()
        lw.setWidgetResizable(True)
        lw.setFrameShape(QScrollArea.NoFrame)
        lw.setWidget(left)
        h.addWidget(lw, 3)

        # 右：自动换算标定 + 换算关系
        right = QWidget()
        v = QVBoxLayout(right)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        cal = Card("自动换算标定",
                   "按当前设置下发一个值，填入电源面板实际读数，自动推算正确小数位")
        row = QHBoxLayout()
        row.addWidget(QLabel("物理量"))
        self.cal_target = QComboBox()
        self.cal_target.addItems(["电流", "电压", "功率"])
        self.cal_target.setFixedWidth(80)
        row.addWidget(self.cal_target)
        row.addWidget(QLabel("设定值"))
        self.cal_want = QLineEdit("1.000")
        self.cal_want.setFixedWidth(90)
        row.addWidget(self.cal_want)
        row.addWidget(QLabel("电源实际显示"))
        self.cal_actual = QLineEdit()
        self.cal_actual.setFixedWidth(90)
        row.addWidget(self.cal_actual)
        b_cal = QPushButton("自动修正小数位")
        b_cal.clicked.connect(self._auto_calib)
        row.addWidget(b_cal)
        row.addStretch(1)
        cal.body_lay.addLayout(row)
        self.lbl_cal = QLabel("")
        self.lbl_cal.setWordWrap(True)
        self.lbl_cal.setObjectName("Muted")
        cal.body_lay.addWidget(self.lbl_cal)
        v.addWidget(cal)

        conv = Card("当前生效的换算关系")
        self.txt_cfg = QPlainTextEdit()
        self.txt_cfg.setReadOnly(True)
        self.txt_cfg.setStyleSheet("font-family:Consolas;")
        conv.body_lay.addWidget(self.txt_cfg)
        v.addWidget(conv, 1)
        h.addWidget(right, 2)
        return wrap

    # ---------------------------------------------------------- 寄存器表
    def _build_map_tab(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.tv_map = QTableWidget(len(REGISTERS), 6)
        self.tv_map.setHorizontalHeaderLabels(
            ["键名", "名称", "地址", "小数位", "属性", "说明"])
        self.tv_map.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tv_map.setSelectionBehavior(QTableWidget.SelectRows)
        for r, rg in enumerate(REGISTERS):
            for c, txt in enumerate((
                    rg.key, rg.name, f"0x{rg.addr:04X}", str(rg.decimals),
                    {"r": "只读", "w": "只写", "rw": "读写"}[rg.access],
                    rg.note or f"{rg.lo}~{rg.hi} {rg.unit}".strip())):
                self.tv_map.setItem(r, c, QTableWidgetItem(txt))
        self.tv_map.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tv_map.cellDoubleClicked.connect(self._map_row_to_raw)
        v.addWidget(self.tv_map, 1)

        raw = QHBoxLayout()
        raw.addWidget(QLabel("原始寄存器读写："))
        raw.addWidget(QLabel("地址"))
        self.ent_reg = QLineEdit("0x1000")
        self.ent_reg.setFixedWidth(110)
        raw.addWidget(self.ent_reg)
        raw.addWidget(QLabel("数值"))
        self.ent_raw = QLineEdit("0x0000")
        self.ent_raw.setFixedWidth(110)
        raw.addWidget(self.ent_raw)
        b_rd = QPushButton("读取")
        b_rd.clicked.connect(self.on_raw_read)
        raw.addWidget(b_rd)
        b_wr = QPushButton("写入")
        b_wr.clicked.connect(self.on_raw_write)
        raw.addWidget(b_wr)
        self.lbl_raw_result = QLabel("—")
        self.lbl_raw_result.setObjectName("Muted")
        raw.addWidget(self.lbl_raw_result)
        tip = QLabel("双击上表行自动填地址；写入走 FC06，失败自动回退 FC10")
        tip.setObjectName("Muted")
        raw.addWidget(tip)
        raw.addStretch(1)
        v.addLayout(raw)
        return wrap

    # ---------------------------------------------------------- 日志
    def _build_log_group(self) -> QWidget:
        box = QGroupBox("通讯日志（TX/RX/RAW 原始 HEX 报文）")
        v = QVBoxLayout(box)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(QLabel("轮询周期(ms)"))
        self.sp_period = QSpinBox()
        self.sp_period.setRange(50, 10000)
        self.sp_period.setValue(500)
        self.sp_period.setFixedWidth(80)
        self.sp_period.valueChanged.connect(self._on_period_changed)
        head.addWidget(self.sp_period)
        self.btn_autopoll = QPushButton("自动轮询：开")
        self.btn_autopoll.clicked.connect(self.toggle_polling)
        head.addWidget(self.btn_autopoll)
        head.addStretch(1)
        b_save = QPushButton("保存日志")
        b_save.clicked.connect(self.save_log)
        head.addWidget(b_save)
        b_clear = QPushButton("清空")
        b_clear.clicked.connect(self.clear_log)
        head.addWidget(b_clear)
        v.addLayout(head)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("font-family:Consolas;")
        self.txt_log.setMinimumHeight(110)
        v.addWidget(self.txt_log)
        return box

    # ================================================================ 连接
    def _refresh_ports(self, user: bool = False):
        cur_name = self._selected_port()
        self.cmb_port.clear()
        kinds = {}
        for name, desc, kind in available_ports():
            self.cmb_port.addItem(f"{name}  {desc}".strip(), name)
            kinds[name] = kind
        self._port_kinds = kinds
        idx_cur = self.cmb_port.findData(cur_name) if cur_name else -1
        idx_det = next((i for i in range(self.cmb_port.count())
                        if kinds.get(self.cmb_port.itemData(i)) == "detected"), -1)
        if idx_cur >= 0 and kinds.get(cur_name) in ("sim", "detected"):
            self.cmb_port.setCurrentIndex(idx_cur)   # 仿真/已检测口：尊重用户选择
        elif idx_det >= 0:
            # 当前只是「未检测到」占位：刷新发现真实口 → 自动进端口框
            self.cmb_port.setCurrentIndex(idx_det)
            self._append_log("info", f"已自动选中检测到的串口：{self.cmb_port.itemText(idx_det)}")
        elif idx_cur >= 0:
            self.cmb_port.setCurrentIndex(idx_cur)   # 尚无真实口：保持占位选择
        else:
            for i in range(self.cmb_port.count()):
                if self.cmb_port.itemData(i) != SIM_PORT_NAME:
                    self.cmb_port.setCurrentIndex(i)   # 兜底：首个非仿真项
                    break
        if user and idx_det < 0:
            found = probe_com_ports()
            if found:
                self._refresh_ports(False)
                self._append_log("info", f"深度扫描发现串口：{'、'.join(found)}")

    def _selected_port(self) -> str:
        data = self.cmb_port.currentData()
        if isinstance(data, str) and data:
            return data
        text = self.cmb_port.currentText().strip()
        return text.split()[0] if text else ""

    def toggle_connect(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self._selected_port()
        if not port:
            QMessageBox.warning(self, "连接", "请先选择串口（或『仿真设备』）")
            return
        slave = self.sp_slave.value()
        try:
            if port == SIM_PORT_NAME:
                p = MODELS.get(self._model)
                rated = (p.vmax, p.imax, p.pmax) if p else None
                self.dev = HspyDevice.open_simulator(
                    slave=slave, logger=self._device_log, rated=rated)
            else:
                self.dev = HspyDevice.open_serial(
                    port, slave=slave,
                    baudrate=int(self.cmb_baud.currentText()),
                    parity=CFG_PARITY.get(self.cmb_parity.currentText(), "N"),
                    stopbits=int(self.cmb_stop.currentText()),
                    logger=self._device_log)
        except Exception as e:
            self.dev = None
            QMessageBox.critical(self, "连接失败", f"打开 {port} 失败：\n{e}")
            return

        cfg = self._cfg_snapshot()
        self.dev.set_run_polarity(cfg["inverted"])
        self.dev.set_timing(frame_gap_ms=cfg["gap_ms"],
                            write_quiet_ms=cfg["quiet_ms"],
                            settle_ms=cfg["settle_ms"],
                            poll_chunk=cfg["poll_chunk"])
        self.dev.retries = max(0, cfg["retries"])
        self.connected = True
        self._link_confirmed = False      # 设备应答过才叫「已连接」（此前只是串口打开）
        self._port_name = port
        self._last_poll = time.time()
        self.btn_connect.setText("连接中…")
        self.btn_connect.setObjectName("btnConnecting")
        self.btn_connect.setProperty("connecting", True)   # 框架回写放行握手态
        self.lbl_state.setText(f"连接中… 等待设备应答（{port}）")
        self._append_log("info", f"已打开 {port}（从机 {slave}），等待设备应答…")
        # 轻量握手探测先行：1 个寄存器即确认链路——read_all 里若有固件缺失寄存器
        # 会拖十几秒，不能让整包读阻塞握手（曾因此被看门狗误杀）
        self.submit("read_key", "rs_addr")
        self.submit("read_all")
        self._conn_timer.start()          # 握手超时：无应答自动断开

    def _confirm_link(self) -> None:
        """任一有效应答到达：握手完成，按钮/状态行升级为「已连接」。"""
        if self._link_confirmed:
            return
        self._link_confirmed = True
        self._conn_timer.stop()
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 应答即通讯成立——框架看门狗/显示与模块握手统一状态源
        self.btn_connect.setText("已连接")
        self.btn_connect.setObjectName("btnConnected")
        self.btn_connect.setProperty("connecting", False)
        self.lbl_state.setText(f"已连接 {self._port_name}")
        self._append_log("info", f"设备已应答，连接建立（{self._port_name}）")

    def _on_conn_timeout(self) -> None:
        """握手超时：设备全程无应答 → 判定连接失败并自动断开。"""
        if self._link_confirmed or not self.connected:
            return
        self._append_log("err", "连接超时：设备无任何应答，已自动断开")
        QMessageBox.warning(
            self, "连接超时",
            "设备在超时时间内无任何应答，已自动断开。\n\n"
            "排查：\n  · 串口号是否选对、设备是否开机\n"
            "  · 波特率 / 停止位 / 从机地址是否与设备面板一致\n"
            "  · RS485 接线 A/B 是否接反、终端电阻")
        self.disconnect("连接超时")

    def disconnect(self, reason: str = "手动断开"):
        self.connected = False
        self._link_confirmed = False
        self._conn_timer.stop()
        self._poll_fail = 0
        self._poll_lost = False
        self.btn_connect.setProperty("connecting", False)
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.lbl_state.setText("未连接")
        self._append_log("info", f"已断开（{reason}）")

    # ================================================================ 命令下发
    def submit(self, cmd, *args):
        if self.dev is None:
            self._append_log("err", "请先连接电源")
            return False
        self.cmd_q.put((cmd, args))
        return True

    def on_set_key(self, key, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            QMessageBox.warning(self, "数值格式", f"「{reg(key).name}」请输入数字")
            return
        if self.submit("set_key", key, v):
            self._clear_dirty(key)
            self._written[key] = reg(key).to_raw(v)   # 写后回读比对基准
            self.submit("read_key", key)   # 下发后自动回读一次（队列顺序保证写后读）

    def on_output(self, on: bool):
        if self.dev is None:
            self._append_log("err", "请先连接电源")
            return
        if on:
            self._verify_then_output()   # 输出前先回读比对，不一致禁止开机
            return
        self.submit("output", False)

    def _make_out_toggle(self, layout, grid_pos=None) -> QPushButton:
        """开/关输出单键开关：绿色「开启输出」↔ 红色「关闭输出」（颜色沿用原双键配色）。"""
        b = QPushButton("开启输出")
        b.setProperty("selfStyled", True)   # 双态自绘，框架不按文字刷色
        b.setFixedHeight(30)
        b.setMinimumWidth(110)
        b.clicked.connect(lambda _=False: self.on_output(not self._out_on))
        if grid_pos is not None:
            layout.addWidget(b, *grid_pos)
        else:
            layout.addWidget(b)
        self._out_buttons.append(b)
        self._apply_out_toggle(b, False)
        return b

    def _apply_out_toggle(self, b, on: bool) -> None:
        text = "关闭输出" if on else "开启输出"
        bg, fg, bd = (("#FFF1F2", "#D20A34", "#FDA4AF") if on
                      else ("#D1FAE5", "#047857", "#6EE7B7"))
        b.setText(text)
        b.setStyleSheet(
            f"QPushButton{{background:{bg}; color:{fg}; border:2px solid {bd};"
            f" border-radius:10px; font-weight:700; padding:6px 14px;}}"
            f"QPushButton:pressed{{background:{bd};}}")

    def _verify_then_output(self):
        """输出前安全闭环：回读设定值并与设定比对，一致才进入开机二次确认。"""
        self._pending_verify = {
            "set_u": reg("set_u").to_raw(self._set_rows["set_u"][0].value()),
            "set_i": reg("set_i").to_raw(self._set_rows["set_i"][0].value()),
        }
        self._verify_seen = {}
        self._append_log("info", "输出前校验：正在回读设定值与设定比对…")
        self.submit("read_key", "set_u")
        self.submit("read_key", "set_i")

    def _finish_output_verify(self):
        exp, seen = self._pending_verify, self._verify_seen
        self._pending_verify = None
        bad = []
        for k in ("set_u", "set_i"):
            if exp.get(k) != seen.get(k):
                r = reg(k)
                bad.append(f"{r.name}：设定 {r.to_physical(exp[k]):g} {r.unit}"
                           f"（原始 {exp[k]}）≠ 回读 {r.to_physical(seen[k]):g} {r.unit}"
                           f"（原始 {seen[k]}）")
        if bad:
            QMessageBox.warning(
                self, "设定值与回读值不一致，已禁止开启输出",
                "设备里的设定值与上位机设定不一致，为安全起见不允许开机输出：\n\n"
                + "\n".join(bad)
                + self._verify_coef_hint()
                + "\n\n请重新「写入设定」并确认回读一致后再开启输出。")
            self._append_log("err", "输出前校验不一致，已禁止开启输出：" + "；".join(bad))
            return
        self._append_log("info", "输出前校验通过：设定值与回读值一致")
        spn_u, _, _ = self._set_rows["set_u"]
        spn_i, _, _ = self._set_rows["set_i"]
        dlg = ConfirmOutputDialog(
            "HSPY 可编程直流电源", "开启输出",
            "输出端将带电！首次连接实物前请确认 OVP/OCP 门限合理，"
            "带载操作前先空载验证读数与输出方向。"
            "（HSPY-1000-01 为 1000V 高压机型，设定电流勿超 1.0 A）",
            f"设定 {spn_u.value()}V / {spn_i.value()}A", self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return
        if self.cmb_polarity.currentIndex() == 1:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("输出开关极性为「反相」")
            box.setText("当前极性=反相：开机会向输出寄存器写 0，"
                        "正相设备会保持关闭——这就是「显示输出中但电源不输出」。")
            box.setInformativeText("建议改回「0=停止, 1=输出（协议默认）」再开机。")
            btn_fix = box.addButton("改回正常并开机", QMessageBox.AcceptRole)
            btn_keep = box.addButton("仍按反相开机", QMessageBox.DestructiveRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is btn_fix:
                self.cmb_polarity.setCurrentIndex(0)
                self._apply_cfg(None, False)   # 立即生效并持久化
                self._append_log("info", "输出开关极性已改回「0=停止, 1=输出」，按正常极性开机")
            elif clicked is btn_keep:
                self._append_log("warn", "用户选择按反相极性开机")
            else:
                return
        self.submit("output", True)

    def _verify_coef_hint(self) -> str:
        try:
            return (f"\n\n当前换算系数：电压 ×{10 ** reg('set_u').d:g} / "
                    f"电流 ×{10 ** reg('set_i').d:g}——"
                    "若与仪器面板不一致，请先校准系数。")
        except Exception:
            return ""

    def _update_readback_box(self, key, raw):
        # 定显 + 原始值同框：与设定框同小数位，且可直接与仪器面板对表定位系数
        self._rb_raw[key] = raw
        if key in ("set_u", "set_i"):
            phys = reg(key).to_physical(raw)
            getattr(self, "ent_rb_u" if key == "set_u" else "ent_rb_i").setText(
                f"{phys:.{reg(key).d}f} (raw {raw})")

    def _rerender_readback_boxes(self):
        """换算系数/小数位改动后，用缓存的设备原始值立即按新系数重折算显示。"""
        if not hasattr(self, "ent_rb_u"):
            return
        for key, raw in self._rb_raw.items():
            if raw is not None:
                self._update_readback_box(key, raw)

    def _refresh_run_tab_title(self):
        """页签注记与实际系数一致：1000-01 面板附当前系数，避免注记与系数打架。"""
        if not hasattr(self, "tabs") or not hasattr(self, "ctl_stack"):
            return
        if self.ctl_stack.currentIndex() != 1:
            return   # 30 系列/通用四页签保持纯「运行监控」
        try:
            vd = reg("set_u").d
            t = (f"运行监控（注：HSPY-1000-01 电压系数为 1；当前 ×{10 ** vd:g}）")
        except Exception:
            t = "运行监控"
        self.tabs.setTabText(0, t)

    def on_raw_read(self):
        addr = self._parse_int(self.ent_reg.text(), "地址")
        if addr is None or not 0 <= addr <= 0xFFFF:
            QMessageBox.warning(self, "地址超范围", "寄存器地址须在 0x0000 ~ 0xFFFF 之间")
            return
        self.submit("raw_read", addr)

    def on_raw_write(self):
        addr = self._parse_int(self.ent_reg.text(), "地址")
        value = self._parse_int(self.ent_raw.text(), "数值")
        if addr is None or not 0 <= addr <= 0xFFFF or \
                value is None or not 0 <= value <= 0xFFFF:
            QMessageBox.warning(self, "格式/范围",
                                "地址 / 数值用 0x 十六进制或十进制，范围 0~65535")
            return
        self.submit("raw_write", addr, value)

    def _parse_int(self, text, name):
        try:
            return int(str(text).strip(), 0)
        except (TypeError, ValueError):
            QMessageBox.warning(self, "格式错误", f"{name}请用 0x 十六进制或十进制整数")
            return None

    def toggle_polling(self):
        self._poll_enabled = not self._poll_enabled
        self.btn_poll.setText("暂停轮询" if self._poll_enabled else "恢复轮询")
        self.btn_autopoll.setText("自动轮询：开" if self._poll_enabled else "自动轮询：关")

    def _on_period_changed(self, val):
        self._poll_period = max(0.05, val / 1000.0)

    # ================================================================ CSV 记录
    def toggle_record(self):
        if not self.recording:
            path = os.path.join(
                os.environ.get("TEMP", "."),
                f"hspy_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv")
            try:
                self.rec_file = open(path, "w", newline="", encoding="utf-8-sig")
            except Exception as e:
                QMessageBox.critical(self, "无法写入", f"打不开文件：\n{e}")
                return
            self.rec_writer = csv.writer(self.rec_file)
            self.rec_writer.writerow(["时间", "机型", "设定电压(V)", "设定电流(A)",
                                      "回读电压(V)", "回读电流(A)", "功率(W)",
                                      "输出状态", "工作模式"])
            self.recording = True
            self._rec_count = 0
            self._rec_path = path
            self.btn_rec.setText("■ 停止记录")
            self.lbl_rec.setText(f"数据记录：{os.path.basename(path)}（0 行）")
            self._append_log("info", f"开始记录数据 → {path}")
        else:
            self._stop_record()

    def _stop_record(self):
        if not self.recording:
            return
        self.recording = False
        try:
            if self.rec_file:
                self.rec_file.flush()
                self.rec_file.close()
        except Exception:
            pass
        self.rec_file = self.rec_writer = None
        self.btn_rec.setText("● 记录CSV")
        self.lbl_rec.setText(
            f"数据记录：已停止（共 {self._rec_count} 行）→ {self._rec_path}")
        self._append_log("info", f"数据记录已停止，共 {self._rec_count} 行：{self._rec_path}")

    def _record_row(self, u, i, p, running, cc):
        if not self.recording or self.rec_writer is None:
            return
        spn_u, _, _ = self._set_rows["set_u"]
        spn_i, _, _ = self._set_rows["set_i"]
        self.rec_writer.writerow([
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            self._model, spn_u.value(), spn_i.value(), u, i, p,
            "输出" if running else "停止", "CC" if cc else "CV"])
        self._rec_count += 1
        if self._rec_count % 10 == 0:
            self.lbl_rec.setText(
                f"数据记录：{os.path.basename(self._rec_path)}（{self._rec_count} 行）")

    # ================================================================ 工作线程
    def _start_worker(self):
        self.worker = threading.Thread(target=self._worker_loop, daemon=True,
                                       name="hspy-worker")
        self.worker.start()

    def _worker_loop(self):
        while not self.stop_evt.is_set():
            try:
                cmd, args = self.cmd_q.get(timeout=0.05)
            except queue.Empty:
                cmd = None
            if cmd:
                try:
                    result = self._exec_command(cmd, args)
                    self.ui_q.put(("cmd_ok", cmd, result, None))
                except Exception as e:
                    self.ui_q.put(("cmd_err", cmd, None, e))
                finally:
                    # 命令后暂停轮询：半双工总线防撞车（原工程同款时序）
                    self._last_poll = time.time() + self._settle_sec
                continue
            if self.connected and self.dev is not None and self._poll_enabled:
                now = time.time()
                # 掉线后降为 2s 低频探测：既能自动发现恢复，又不持续高频发帧
                period = 2.0 if self._poll_lost else self._poll_period
                if now - self._last_poll >= period:
                    self._last_poll = now
                    try:
                        self.ui_q.put(("poll", self.dev.read_poll_block(), None, None))
                    except Exception as e:
                        self.ui_q.put(("poll_err", None, None, e))

    def _exec_command(self, cmd, args):
        dev = self.dev
        if dev is None:
            raise RuntimeError("设备已断开")
        if cmd == "set_key":
            key, value = args
            return ("set_key", dev.write_key(key, value))
        if cmd == "read_key":
            return ("read_key", args[0], dev.read_key(args[0]))
        if cmd == "read_all":
            return ("read_all",) + dev.read_all()
        if cmd == "output":
            return ("output", args[0], dev.output(args[0]))
        if cmd == "scan":
            return ("scan", dev.scan_slaves(1, 15))
        if cmd == "raw_read":
            addr = args[0]
            return ("raw_read", addr, dev.read_raw(addr))
        if cmd == "raw_write":
            addr, value = args
            method, _resp = dev.write_raw(addr, value)
            return ("raw_write", addr, value, method)
        raise RuntimeError(f"未知命令：{cmd}")

    def _device_log(self, direction, frame, note=""):
        self.log_q.put((direction, format_frame(frame) + (f"   {note}" if note else "")))

    # ================================================================ UI 泵
    def _drain_ui(self):
        try:
            while True:
                direction, text = self.log_q.get_nowait()
                tag = {"tx": "#0F766E", "rx": "#1D4ED8"}.get(direction, "#6B7280")
                self.txt_log.appendHtml(
                    f'<span style="color:{tag}; font-family:Consolas;">'
                    f'[{direction.upper()}] {text}</span>')
        except queue.Empty:
            pass
        try:
            while True:
                kind, a, b, c = self.ui_q.get_nowait()
                self._handle_ui(kind, a, b, c)
        except queue.Empty:
            pass
        if self.dev is not None:
            s = self.dev.stats
            self.lbl_stats.setText(f"TX {s['tx']} / RX {s['rx']} / ERR {s['err']}")

    def _handle_ui(self, kind, a, b, c):
        if kind == "poll":
            self._apply_poll(a)
            return
        if kind == "poll_err":
            self._poll_fail += 1
            self._append_log("err", f"轮询失败：{c}")
            if self._poll_fail >= 3 and not self._poll_lost:
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)   # 连续无应答 = 通讯中断
                self._poll_lost = True
                self._append_log("warn", f"设备连续 {self._poll_fail} 次无响应，"
                                         "标记离线（降为 2s 低频探测，恢复应答后自动上线）")
            return
        if kind == "cmd_err":
            self._append_log("err", f"{a} 失败：{c}")
            return
        cmd, result = a, b
        self._confirm_link()   # 任一命令完成往返 = 设备有应答，握手完成
        if cmd == "set_key":
            self._apply_write_result(result)
        elif cmd == "read_key":
            _, key, raw = result
            self._clear_dirty(key)
            self._update_param_value(key, raw)
            expect = self._written.pop(key, None)
            if expect is not None and expect != raw:
                # 写后回读不一致：警示且不覆写设定框（防止把错误值写回设备）
                r = reg(key)
                QMessageBox.warning(
                    self, "写入后回读不一致",
                    f"{r.name}：写入原始 {expect} ≠ 回读原始 {raw}"
                    f"（设备内为 {r.to_physical(raw):g} {r.unit}）。\n"
                    "可能原因：电压/电流系数（换算系数）与电源面板不一致。\n"
                    "已保留输入框数值未按回读覆盖，请核对系数后重新「写入设定」。")
                self._append_log("err", f"{r.name} 写入后回读不一致：写入 {expect} ≠ 回读 {raw}")
            else:
                if key in ("set_u", "set_i", "set_p"):
                    self._sync_setter(key, reg(key).to_physical(raw))
            self._update_readback_box(key, raw)
            self._append_log("info", f"已读取 {reg(key).name}")
            if self._pending_verify is not None and key in ("set_u", "set_i"):
                self._verify_seen[key] = raw
                if all(k in self._verify_seen for k in self._pending_verify):
                    self._finish_output_verify()
        elif cmd == "read_all":
            values, failures = result[1], result[2]
            self._apply_all(values)
            if failures:
                names = "、".join(f[1] for f in failures)
                self._append_log("warn", f"已读取 {len(values)} 项；"
                                         f"{len(failures)} 项未读到:{names}")
            else:
                self._append_log("info", f"已读取全部参数（{len(values)} 项）")
        elif cmd == "output":
            _, on, info = result
            want = "开启" if on else "关闭"
            ok = (not isinstance(info, dict)) or info.get("ok")
            if ok:
                self._append_log("info", f"输出已{want}")
                self._refresh_output_label(on)
            else:
                rb = info.get("readback")
                self._append_log("err", f"输出{want}未生效：设备回读 Run-Stop = "
                                        f"{rb if rb is not None else '无响应'}。"
                                        f"{info.get('note', '')}")
                for e in (info.get("errors") or []):
                    self._append_log("err", f"  · {e}")
                self._append_log("info", "  · 排查：原始寄存器 0x1004 写 1/0 直接试命令；"
                                         "加大「写入前静默/命令后暂停轮询」（半双工丢写）；"
                                         "检查 OVP/OCP 门限是否低于设定值（保护会秒断输出）")
                QMessageBox.warning(
                    self, f"输出{want}未生效",
                    f"命令已发出且设备有应答，但 Run-Stop（0x1004）寄存器没有变化。\n\n"
                    f"排查建议：\n"
                    f"  · 原始寄存器行试写 0x1004 = 1（开）/ 0（关），看设备反应\n"
                    f"  · 半双工 485 丢写：「量程设置」加大 写入前静默 / 命令后暂停轮询\n"
                    f"  · 检查 OVP/OCP 门限是否低于电压/电流设定（保护会立即切断输出）\n"
                    f"  · 确认面板按键锁定（Key_Lock）未锁、输出开关极性与设备一致\n"
                    f"  · 「通讯日志」查看本命令的 TX/RX 原始报文")
        elif cmd == "scan":
            found = result[1]
            msg = ("在线从机地址：" + "、".join(map(str, found))) \
                if found else "未扫描到任何从机"
            self._append_log("info", msg)
            QMessageBox.information(self, "扫描结果", msg)
        elif cmd == "raw_read":
            _, addr, value = result
            text = f"0x{addr:04X} = {value} (0x{value:04X})"
            self.lbl_raw_result.setText(text)
            self._append_log("info", f"原始读取 {text}")
        elif cmd == "raw_write":
            _, addr, value, method = result
            text = f"0x{addr:04X} ← {value} (0x{value:04X}) · {method}"
            self.lbl_raw_result.setText(text)
            self._append_log("info", f"原始写入 {text} 成功")

    # ================================================================ 数据刷新
    def _apply_poll(self, data):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 轮询数据更新 = 通讯真正建立
        self._confirm_link()
        if self._poll_lost:   # 掉线后恢复应答：自动恢复在线（worker 随之回到原周期）
            self._poll_lost = False
            self._append_log("info", "设备恢复应答，自动恢复在线")
        self._poll_fail = 0
        def g(off):
            return data[off] if 0 <= off < len(data) else 0

        u = reg("u").to_physical(g(0x02))
        i = reg("i").to_physical(g(0x03))
        p = reg("p").to_physical(g(0x08))
        # 设定回读框跟随轮询块里的设定寄存器原始值（设备真值，改系数立即反映）
        self._update_readback_box("set_u", g(0x00))
        self._update_readback_box("set_i", g(0x01))
        self.cards["u"].setText(f"{u:.{reg('u').d}f}")
        self.cards["i"].setText(f"{i:.{reg('i').d}f}")
        self.cards["p"].setText(f"{p:.{reg('p').d}f}")
        self.chart.push("u", u)
        self.chart.push("i", i)
        self.chart.push("p", p)

        running = bool(g(0x04) if not (self.dev and self.dev.run_stop_inverted)
                       else 1 - g(0x04))
        cc = bool(g(0x0E))
        self._refresh_output_label(running, g(0x04))   # 带寄存器原始值，极性解读可见
        self.lbl_cccv.setText(f"工作模式：{'CC 恒流' if cc else 'CV 恒压'}")
        self.lbl_lock.setText(f"按键锁定：{'已锁定' if g(0x06) else '未锁定'}")
        self._record_row(u, i, p, running, cc)
        self.lbl_last.setText("最近报文：轮询块 0x1000 起 15 寄存器已刷新")

    def _apply_write_result(self, info):
        name = info.get("name", "")
        if info.get("ok"):
            self._append_log("info", f"{name} 已写入（{info.get('method')}，回读一致）")
        else:
            self._append_log("err", f"{name} 写入未生效：{info.get('note', '')}")

    def _update_param_value(self, key, raw):
        r = reg(key)
        if key in self.p_cur:
            self.p_cur[key].setText(r.format(raw))
        if key == "run_stop":
            self._refresh_output_label(bool(raw))
        if key == "key_lock":
            self.lbl_lock.setText(f"按键锁定：{'已锁定' if raw else '未锁定'}")
        if key == "cc_cv":
            self.lbl_cccv.setText(f"工作模式：{'CC 恒流' if raw else 'CV 恒压'}")

    def _apply_all(self, values):
        for key, (raw, _phys, _text) in values.items():
            self._update_param_value(key, raw)
            if key in ("set_u", "set_i", "set_p"):
                self._sync_setter(key, reg(key).to_physical(raw))
            self._update_readback_box(key, raw)
            if key in self.p_var:
                w = self.p_var[key]
                text = str(raw)
                if isinstance(w, QComboBox):
                    idx = w.findText(text)
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                else:
                    w.setText(text)
        for key in ("set_u", "set_i", "set_p"):
            self._clear_dirty(key)

    def _sync_setter(self, key, value):
        spn, _hint, _raw = self._set_rows[key]
        spn.blockSignals(True)
        spn.setValue(value)
        spn.blockSignals(False)
        self._refresh_raw_hint(key)

    def _refresh_output_label(self, on: bool, raw=None):
        raw_txt = ""
        if raw is not None:
            pol = "，按反相解读" if (self.dev is not None and self.dev.run_stop_inverted) else ""
            raw_txt = f"（寄存器 0x1004={raw}{pol}）"
        self.lbl_out.setText(f"输出状态：{'输出中' if on else '已停止'}{raw_txt}")
        self.lbl_out.setStyleSheet(
            "font-weight:700; color:" + ("#B01030" if on else "#047857"))
        self._out_on = on
        for b in self._out_buttons:
            self._apply_out_toggle(b, on)

    def _mark_dirty(self, key):
        if key in self._set_rows:
            _spn, hint, raw = self._set_rows[key]
            hint.setText("未下发（点「设定」写入设备）")
            self._refresh_raw_hint(key)

    def _clear_dirty(self, key):
        if key in self._set_rows:
            _spn, hint, _raw = self._set_rows[key]
            hint.setText("")

    def _refresh_raw_hint(self, key):
        if key not in self._set_rows:
            return
        spn, _hint, raw = self._set_rows[key]
        r = reg(key)
        raw.setText(f"原始值 {r.to_raw(spn.value())}（{r.d} 位小数）")

    def _param_text(self, key) -> str:
        w = self.p_var[key]
        return w.currentText() if isinstance(w, QComboBox) else w.text()

    # ================================================================ 机型 / 量程
    def on_model_change(self, name=None):
        name = self.cmb_model.currentText() if name is None else name
        self._model = name
        if name == CUSTOM:
            self._sync_series_ui(name)
            self._append_log("info", "机型切换为「自定义」——量程与小数位以「量程设置」为准")
            return
        p = get_model(name)
        self.cfg_w["vmax"].setText(f"{p.vmax:g}")
        self.cfg_w["imax"].setText(f"{p.imax:g}")
        self.cfg_w["pmax"].setText(f"{p.pmax:g}")
        for key, val in (("vdec", p.vdec), ("vshow", p.vshow), ("idec", p.idec),
                         ("ishow", p.ishow), ("pdec", p.pdec), ("pshow", p.pshow),
                         ("ovpdec", p.ovpdec), ("ocpdec", p.ocpdec)):
            self.cfg_w[key].setCurrentText(str(val))
        if self._limit_spins:
            # 先抬最大值再设值：否则新机型量程小于旧值时 setValue 被钳位残留
            self._limit_spins["ovp"].setMaximum(p.vmax)
            self._limit_spins["ocp"].setMaximum(p.imax)
            self._limit_spins["ovp"].setValue(p.vmax)
            self._limit_spins["ocp"].setValue(p.imax)
        self._sync_series_ui(name)   # 输出控制双布局 + 页签可见性（1000-01 专属）
        self._apply_cfg(None, False)
        sim_note = ""
        if self.dev is not None and name in MODELS:
            if self.dev.set_sim_rating(p.vmax, p.imax, p.pmax):
                sim_note = f"仿真设备额定值已切换为 {p.vmax:g} V / {p.imax:g} A / {p.pmax:g} W"
        self._append_log("info", f"已套用机型预设 —— {p.summary()}")
        if p.note:
            self._append_log("info", f"  依据:{p.note}（{p.source}）")
        if sim_note:
            self._append_log("info", "  " + sim_note)

    def _cfg_snapshot(self):
        return {
            "vmax": _to_float(self.cfg_w["vmax"].text(), 60.0),
            "imax": _to_float(self.cfg_w["imax"].text(), 10.0),
            "pmax": _to_float(self.cfg_w["pmax"].text(), 600.0),
            "vdec": _to_int(self.cfg_w["vdec"].currentText(), 2),
            "vshow": _to_int(self.cfg_w["vshow"].currentText(), 2),
            "idec": _to_int(self.cfg_w["idec"].currentText(), 3),
            "ishow": _to_int(self.cfg_w["ishow"].currentText(), 3),
            "pdec": _to_int(self.cfg_w["pdec"].currentText(), 1),
            "pshow": _to_int(self.cfg_w["pshow"].currentText(), 1),
            "ovpdec": _to_int(self.cfg_w["ovpdec"].currentText(), 3),
            "ocpdec": _to_int(self.cfg_w["ocpdec"].currentText(), 3),
            "inverted": self.cmb_polarity.currentText().startswith("反相"),
            "gap_ms": _to_float(self.cfg_tm["gap_ms"].text(), 4.0),
            "quiet_ms": _to_float(self.cfg_tm["quiet_ms"].text(), 25.0),
            "settle_ms": _to_float(self.cfg_tm["settle_ms"].text(), 200.0),
            "poll_chunk": _to_int(self.cfg_tm["poll_chunk"].text(), 8),
            "retries": _to_int(self.cfg_tm["retries"].text(), 2),
            "model": self._model,
        }

    def _apply_cfg(self, snapshot=None, announce=True):
        cfg = snapshot or self._cfg_snapshot()
        set_decimals("set_u", cfg["vdec"])
        set_decimals("u", cfg["vshow"])
        set_decimals("set_i", cfg["idec"])
        set_decimals("i", cfg["ishow"])
        set_decimals("set_p", cfg["pdec"])
        set_decimals("p", cfg["pshow"])
        set_decimals("ovp", cfg["ovpdec"])
        set_decimals("ocp", cfg["ocpdec"])

        if getattr(self, "conv_v", None):
            for cb, key in ((self.conv_v, "vdec"), (self.conv_i, "idec")):
                cb.blockSignals(True)
                cb.setCurrentIndex(max(0, min(4, int(cfg[key]))))
                cb.blockSignals(False)
        # 设定框小数位跟随系数（消除 5.0 vs 5.00 对表误读）；可设范围/页签注记随系数动态刷新
        for key, dec in (("set_u", cfg["vdec"]), ("set_i", cfg["idec"]), ("set_p", cfg["pdec"])):
            try:
                self._set_rows[key][0].setDecimals(int(dec))
            except Exception:
                pass
        if getattr(self, "lbl_range_tip", None):
            self.lbl_range_tip.setText(
                f"可设范围：电压 0~{65535 / (10 ** cfg['vdec']):g} V，"
                f"电流 0~{65535 / (10 ** cfg['idec']):g} A（16 位寄存器 ×系数）")
        self._rerender_readback_boxes()   # 系数/小数位改动 → 回读框立即按新系数重折算
        self._refresh_run_tab_title()

        if self._limit_spins:
            self._limit_spins["ovp"].setMaximum(cfg["vmax"])
            self._limit_spins["ocp"].setMaximum(cfg["imax"])
        self._apply_spin_limits()
        self._settle_sec = max(0.0, cfg["settle_ms"] / 1000.0)
        if self.dev is not None:
            self.dev.set_run_polarity(cfg["inverted"])
            self.dev.set_timing(frame_gap_ms=cfg["gap_ms"],
                                write_quiet_ms=cfg["quiet_ms"],
                                settle_ms=cfg["settle_ms"],
                                poll_chunk=cfg["poll_chunk"])
            self.dev.retries = max(0, cfg["retries"])

        for key in ("set_u", "set_i", "set_p"):
            self._refresh_raw_hint(key)

        detected = detect_by_ranges(cfg["vmax"], cfg["imax"], cfg["vdec"], cfg["idec"])
        if detected != self._model:
            self._model = detected
            self.cmb_model.blockSignals(True)
            self.cmb_model.setCurrentText(detected)
            self.cmb_model.blockSignals(False)
        self._refresh_conv_label()
        self._render_cfg_table()
        self._save_cfg(cfg)
        if announce:
            self._append_log("info",
                             f"量程与小数位已应用：电压 {cfg['vdec']}/{cfg['vshow']} 位、"
                             f"电流 {cfg['idec']}/{cfg['ishow']} 位、"
                             f"功率 {cfg['pdec']}/{cfg['pshow']} 位小数（设定/显示）")

    def _reset_cfg(self):
        reset_decimals()
        self.cfg_w["vmax"].setText("60")
        self.cfg_w["imax"].setText("10")
        self.cfg_w["pmax"].setText("600")
        for key, val in (("vdec", "2"), ("vshow", "2"), ("idec", "3"), ("ishow", "3"),
                         ("pdec", "1"), ("pshow", "1"), ("ovpdec", "3"), ("ocpdec", "3")):
            self.cfg_w[key].setCurrentText(val)
        for key, val in (("gap_ms", "4"), ("quiet_ms", "25"), ("settle_ms", "200"),
                         ("poll_chunk", "8"), ("retries", "2")):
            self.cfg_tm[key].setText(val)
        self.cmb_polarity.setCurrentIndex(0)
        self._model = DEFAULT_MODEL
        self.cmb_model.blockSignals(True)
        self.cmb_model.setCurrentText(DEFAULT_MODEL)
        self.cmb_model.blockSignals(False)
        if self.dev is not None:
            self.dev.set_run_polarity(False)
        self._apply_cfg(None, False)
        self.on_model_change(DEFAULT_MODEL)
        self._append_log("info", f"已恢复默认：机型「{DEFAULT_MODEL}」")

    def _refresh_conv_label(self):
        try:
            self.lbl_conv.setText(
                "换算关系：物理量 = 寄存器原始值 ÷ 10^小数位\n"
                f"电压 {reg('u').d} 位 · 电流 {reg('i').d} 位 · "
                f"功率 {reg('p').d} 位小数（显示）")
        except Exception:
            pass

    def _render_cfg_table(self):
        lines = []
        for key in ("set_u", "u", "set_i", "i", "set_p", "p", "ovp", "ocp"):
            r = reg(key)
            lines.append(f"0x{r.addr:04X}  {r.name:<8} ×10^{r.d}  "
                         f"1 LSB = {1.0 / r.scale:g} {r.unit}")
        lines.append("")
        for key in ("set_u", "set_i", "set_p"):
            r = reg(key)
            spn = self._set_rows[key][0]
            lines.append(f"{r.name}当前设定 {spn.value():g} "
                         f"→ 原始值 {r.to_raw(spn.value())}（{r.d} 位小数）")
        self.txt_cfg.setPlainText("\n".join(lines))

    def _auto_calib(self):
        key_map = {"电压": ("voltage", "set_u"), "电流": ("current", "set_i"),
                   "功率": ("power", "set_p")}
        name = self.cal_target.currentText()
        quantity, set_key = key_map[name]
        want = _to_float(self.cal_want.text(), 0.0)
        actual = _to_float(self.cal_actual.text(), 0.0)
        if want <= 0 or actual <= 0:
            QMessageBox.warning(self, "无法标定",
                                "请先填写「设定值」和「电源实际显示」，且都要大于 0")
            return
        factor = actual / want
        n = math.log10(factor)
        if abs(n - round(n)) > 0.03:
            self.lbl_cal.setText(f"比值 {factor:.4g} 不是 10 的整数次幂")
            QMessageBox.information(
                self, "不是小数位问题",
                f"实际 / 设定 = {factor:.4g}，不是 10 的整数次幂。\n\n"
                f"小数位只能解释 10 倍、100 倍、0.1 倍这类偏差。\n"
                f"建议检查：负载是否进入限流（CC）、输出线压降、"
                f"量程设置、采样接线。")
            return
        n = int(round(n))
        cur = decimals_of(set_key)
        new = cur - n
        if not 0 <= new <= 6:
            QMessageBox.warning(self, "无法修正",
                                f"推算得到 {new} 位小数，超出可设范围 0~6")
            return
        key_map2 = {"voltage": ("vdec", "vshow"), "current": ("idec", "ishow"),
                    "power": ("pdec", "pshow")}
        sk, hk = key_map2[quantity]
        self.cfg_w[sk].setCurrentText(str(new))
        self.cfg_w[hk].setCurrentText(str(new))
        self._apply_cfg(None, True)
        tip = f"{name}：设定 {want:g}、实际 {actual:g}，比值 {factor:g} 倍 → 小数位 {cur} 改成 {new}"
        self.lbl_cal.setText(tip)
        self._append_log("info", "自动标定：" + tip)

    # ================================================================ 配置持久化
    def _save_cfg(self, cfg):
        try:
            with open(CFG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _load_cfg(self):
        cfg = None
        try:
            with open(CFG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = None
        if not isinstance(cfg, dict):
            self._apply_cfg(None, False)
            self._sync_series_ui()   # 配置缺失也按默认机型同步面板/页签
            return
        self.cfg_w["vmax"].setText(f"{_to_float(cfg.get('vmax'), 60.0):g}")
        self.cfg_w["imax"].setText(f"{_to_float(cfg.get('imax'), 10.0):g}")
        self.cfg_w["pmax"].setText(f"{_to_float(cfg.get('pmax'), 600.0):g}")
        for key in ("vdec", "vshow", "idec", "ishow", "pdec", "pshow",
                    "ovpdec", "ocpdec"):
            self.cfg_w[key].setCurrentText(str(_to_int(cfg.get(key), 2)))
        for key, dflt in (("gap_ms", 4.0), ("quiet_ms", 25.0), ("settle_ms", 200.0),
                          ("poll_chunk", 8), ("retries", 2)):
            self.cfg_tm[key].setText(str(_to_int(cfg.get(key), dflt)))
        if cfg.get("inverted"):
            self.cmb_polarity.setCurrentIndex(1)
        model = cfg.get("model", DEFAULT_MODEL)
        self._model = model
        self.cmb_model.blockSignals(True)
        self.cmb_model.setCurrentText(model)
        self.cmb_model.blockSignals(False)
        self._apply_cfg(None, False)
        self._sync_series_ui()   # 启动恢复机型后同步 1000-01 专属面板/页签可见性

    # ================================================================ 寄存器表
    def _map_row_to_raw(self, row, _col):
        item = self.tv_map.item(row, 2)
        if item is not None:
            self.ent_reg.setText(item.text())
            self._append_log("info", f"已把地址 {item.text()} 填入原始寄存器读写框")

    # ================================================================ 日志
    def _append_log(self, kind, text):
        colors = {"err": "#D20A34", "warn": "#B45309", "info": "#111827"}
        self.txt_log.appendHtml(
            f'<span style="color:{colors.get(kind, "#111827")}">{text}</span>')
        self.txt_log.verticalScrollBar().setValue(
            self.txt_log.verticalScrollBar().maximum())

    def clear_log(self):
        self.txt_log.clear()

    def save_log(self):
        path = os.path.join(os.environ.get("TEMP", "."),
                            f"hspy_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_log.toPlainText())
            self._append_log("info", f"日志已保存 → {path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ================================================================ 清理
    def shutdown(self):
        """退出闭环：停记录 → 关输出 → 断开 → 停线程。"""
        try:
            self._timer.stop()
        except Exception:
            pass
        self._stop_record()
        if self.dev is not None:
            try:
                self.dev.output(False)
            except Exception:
                pass
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None
        self.connected = False
        self.stop_evt.set()
        if self.worker is not None:
            self.worker.join(timeout=1.0)
            self.worker = None
