# -*- coding: utf-8 -*-
"""FLUKE 8808A 上位机主窗口。

界面与协议解耦：所有仪器交互只调 Instrument 语义接口，不接触帧字节
（唯一例外：SCPI 控制台，用户显式输入原始命令，仍经协议栈队列保护）。
"""
import threading
import time
from collections import deque

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QStatusBar, QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout,
    QWidget,
)

from .commands import VERSIONS
from .instrument import Instrument, Reading
from .simulator import build_sim_pair
from .stack import ProtocolStack, StackConfig
from .transport import SerialTransport

# 轮询周期选项（毫秒）。9600 波特下默认 500ms，防界面刷新高于串口吞吐。
POLL_PERIODS = (200, 500, 1000, 2000)

# 掉线感知：连续 N 次轮询失败 → 标记离线并降为低频探测（恢复应答自动上线）
POLL_LOST_FAILS = 3
POLL_LOST_MS = 2000

# 功能按钮配色分组（电压蓝 / 电流橙 / 电阻绿 / 频率紫 / 通断·二极管青）
FUNC_ACCENT = {
    "VDC": "blue", "VAC": "blue",
    "ADC": "amber", "AAC": "amber", "AACDC": "amber",
    "OHMS": "green",
    "FREQ": "violet",
    "CONT": "teal", "DIODE": "teal",
    "VACDC": "blue",
}

# 现代化主题：靛蓝主色 + 圆角卡片 + 渐变按钮
THEME_QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #f3f5fb; color: #2b3452; }

/* ---- 卡片式分组框 ---- */
QGroupBox {
    background: #ffffff; border: 1px solid #e5eaf6; border-radius: 14px;
    margin-top: 16px; padding: 14px 12px 10px 12px; font-weight: 600; color: #46507a;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 16px; top: 3px; padding: 0 8px;
    color: #6366f1; background: #f3f5fb;
}
QGroupBox QGroupBox { background: #f8f9fe; border-color: #e8ecf9; margin-top: 13px; }
QGroupBox QGroupBox::title { color: #7c85b8; background: #f8f9fe; }

/* ---- 按钮 ---- */
QPushButton {
    background: #ffffff; border: 1px solid #d8dff2; border-radius: 9px;
    padding: 7px 16px; color: #3b4468; font-weight: 600;
}
QPushButton:hover { background: #eef1fe; border-color: #a5b4fc; }
QPushButton:pressed { background: #dfe4fc; }
QPushButton:disabled { color: #a9b1cc; background: #f1f3fa; border-color: #e3e8f4; }
QPushButton:checked { background: #6366f1; border-color: #6366f1; color: #ffffff; }

QPushButton[accent="blue"]:checked  { background: #3b82f6; border-color: #3b82f6; }
QPushButton[accent="amber"]:checked { background: #f59e0b; border-color: #f59e0b; }
QPushButton[accent="green"]:checked { background: #10b981; border-color: #10b981; }
QPushButton[accent="violet"]:checked{ background: #8b5cf6; border-color: #8b5cf6; }
QPushButton[accent="teal"]:checked  { background: #14b8a6; border-color: #14b8a6; }

QPushButton#btnConnect {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22c55e, stop:1 #16a34a);
    border: none; color: #ffffff; font-weight: 700; padding: 8px 22px;
}
QPushButton#btnConnect:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2dd36a, stop:1 #18b254); }
QPushButton#btnDisconnect {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f87171, stop:1 #ef4444);
    border: none; color: #ffffff; font-weight: 700; padding: 8px 22px;
}
QPushButton#btnDisconnect:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fa8787, stop:1 #f35c5c); }
QPushButton#btnComp {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fb923c, stop:1 #f97316);
    border: none; color: #ffffff; font-weight: 700;
}
QPushButton#btnComp:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fca45a, stop:1 #fb8532); }

/* ---- 输入控件 ---- */
QComboBox, QLineEdit {
    background: #ffffff; border: 1px solid #d8dff2; border-radius: 8px;
    padding: 6px 10px; color: #2b3452; selection-background-color: #6366f1;
}
QComboBox:hover, QLineEdit:hover { border-color: #a5b4fc; }
QComboBox:focus, QLineEdit:focus { border: 2px solid #6366f1; padding: 5px 9px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #6366f1; margin-right: 10px; }
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #d8dff2; border-radius: 8px;
    selection-background-color: #eef1fe; selection-color: #2b3452; outline: none;
    padding: 4px;
}
QCheckBox { spacing: 8px; color: #46507a; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 2px solid #c3cbe6; background: #ffffff; }
QCheckBox::indicator:checked { background: #6366f1; border-color: #6366f1; image: none; }
QCheckBox::indicator:hover { border-color: #818cf8; }

/* ---- 测量大字显示 ---- */
QLabel#lblValue {
    color: #1e293b; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f6f8ff);
    border: 2px solid #e5eaf6; border-radius: 16px; padding: 10px;
}
QLabel#lblComp { border-radius: 12px; padding: 6px; }
QLabel#lblFunc { color: #6366f1; }

/* ---- Tab ---- */
QTabWidget::pane { background: #ffffff; border: 1px solid #e5eaf6; border-radius: 12px; top: -1px; }
QTabBar::tab {
    background: #e7ebf8; border: 1px solid #dfe5f4; border-bottom: none;
    border-radius: 9px 9px 0 0; padding: 8px 22px; margin-right: 6px; color: #6a739c; font-weight: 600;
}
QTabBar::tab:selected { background: #ffffff; color: #6366f1; }
QTabBar::tab:hover:!selected { background: #eef1fe; color: #6366f1; }

/* ---- 日志控制台 ---- */
QTextEdit#logView {
    background: #151b2e; color: #dbe4ff; border-radius: 10px; border: 1px solid #232c4a;
    font-family: Consolas, "Courier New", monospace; font-size: 12px; padding: 8px;
}
QTextBrowser { background: #ffffff; border: 1px solid #e5eaf6; border-radius: 10px; padding: 12px; }

/* ---- 状态栏 ---- */
QStatusBar { background: #ffffff; border-top: 1px solid #e5eaf6; color: #5a648c; }
QStatusBar::item { border: none; }

/* ---- 滚动条 ---- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #c7cfea; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #818cf8; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #c7cfea; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QSplitter::handle { background: #e5eaf6; width: 6px; border-radius: 3px; }
"""


class TrendWidget(QWidget):
    """自绘实时趋势（最近 300 点），不用 matplotlib。"""

    MAX_POINTS = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = deque(maxlen=self.MAX_POINTS)   # (时间戳, 读数)
        self._paused = False
        self.setMinimumHeight(150)

    def add_point(self, value):
        """追加一个读数点（暂停或读数无效时不追加）。"""
        if self._paused or value is None:
            return
        self._points.append((time.monotonic(), float(value)))
        self.update()

    def clear(self):
        self._points.clear()
        self.update()

    def set_paused(self, paused: bool):
        self._paused = paused

    @staticmethod
    def _fmt(v: float) -> str:
        return f"{v:.6g}"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # 深靛蓝画布（与控制台呼应的年轻化配色）
        p.fillRect(0, 0, w, h, QColor(24, 30, 54))
        p.setPen(QColor(46, 56, 96))
        for i in range(1, 4):
            y = int(h * i / 4)
            p.drawLine(0, y, w, y)

        pts = list(self._points)
        if len(pts) < 2:
            p.setPen(QColor(120, 135, 190))
            p.drawText(self.rect(), Qt.AlignCenter, "等待数据…")
            return

        vals = [v for _, v in pts]
        vmin, vmax = min(vals), max(vals)
        if vmax - vmin < 1e-12:                      # 全部相同值时留出上下边距
            pad = max(abs(vmax) * 0.01, 1e-9)
            vmin, vmax = vmin - pad, vmax + pad
        else:
            pad = (vmax - vmin) * 0.08
            vmin, vmax = vmin - pad, vmax + pad
        t0, t1 = pts[0][0], pts[-1][0]
        span = t1 - t0 if t1 > t0 else 1.0

        def xy(t, v):
            x = (t - t0) / span * (w - 60) + 52
            y = h - 20 - (v - vmin) / (vmax - vmin) * (h - 40)
            return x, y

        # 面积渐变填充（曲线到基线）
        from PyQt5.QtGui import QLinearGradient, QPolygonF, QBrush
        from PyQt5.QtCore import QPointF
        poly = QPolygonF()
        poly.append(QPointF(*xy(*pts[0])))
        for t, v in pts[1:]:
            poly.append(QPointF(*xy(t, v)))
        base_y = h - 20
        poly.append(QPointF(poly.last().x(), base_y))
        poly.append(QPointF(poly.first().x(), base_y))
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(99, 102, 241, 120))
        grad.setColorAt(1.0, QColor(99, 102, 241, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawPolygon(poly)

        # 主曲线（亮青蓝）
        p.setPen(QPen(QColor(96, 165, 250), 2.2))
        prev = xy(*pts[0])
        for t, v in pts[1:]:
            cur = xy(t, v)
            p.drawLine(int(prev[0]), int(prev[1]), int(cur[0]), int(cur[1]))
            prev = cur

        # 最新点高亮圆点
        lx, ly = xy(*pts[-1])
        p.setBrush(QColor(250, 250, 255))
        p.setPen(QPen(QColor(96, 165, 250), 2))
        p.drawEllipse(int(lx) - 4, int(ly) - 4, 8, 8)

        p.setPen(QColor(140, 155, 210))
        p.drawText(8, 16, self._fmt(vmax))
        p.drawText(8, h - 26, self._fmt(vmin))
        p.drawText(w - 190, h - 6, f"最近 {len(pts)} 点 / {span:.0f} s（横轴时间 纵轴读数）")
        p.end()


class MainWindow(QMainWindow):
    """FLUKE 8808A 上位机主窗口。"""

    # 跨线程信号（协议栈/轮询线程 -> GUI 线程）
    sig_frame = pyqtSignal(str, str)        # (方向, 帧文本)
    sig_reading = pyqtSignal(object)        # Reading

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instrument: Instrument = None
        self._label_helper = Instrument(None)   # 仅用于生成量程文字，不发帧
        self._transport = None
        self._stack: ProtocolStack = None
        self._sim = None                  # 模拟从站（自测用）
        self._connected = False
        self._poll_busy = False           # 上一条读数是否未完成
        self._poll_fail = 0              # 连续轮询失败计数（成功清零）
        self._poll_lost = False          # 掉线标记：True 时降为低频探测
        self._updating_ui = False         # 防控件互刷递归
        self._current_func_label = "直流电压"

        self.setWindowTitle(f"FLUKE 8808A 上位机  v{VERSIONS['software']}")
        self.resize(1180, 780)
        self.setStyleSheet(THEME_QSS)   # 应用现代化主题
        self.sig_frame.connect(self._append_log)
        self.sig_reading.connect(self._on_reading)

        self._build_ui()
        self._build_timers()
        self._refresh_ports()
        self._refresh_range_combo()      # 未连接时先按默认功能填充量程下拉
        self._set_connected_state(False)

    # ================================================================ 界面搭建
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_conn_bar())

        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)

        def _flat_scroll(wd):
            # 面板包滚动区解除 minimumSizeHint 顶死：日志区(下方 tabs)免滚动露出
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QScrollArea.NoFrame)
            sc.setStyleSheet("QScrollArea{background:transparent; border:none;}")
            sc.setWidget(wd)
            return sc

        # 测量显示在左；右侧按钮切换共用区（测量功能 / 应用数学功能，默认测量功能）
        mid.addWidget(_flat_scroll(self._build_display_panel()))
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(6)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_tab_measure = QPushButton("测量功能")
        self.btn_tab_math = QPushButton("应用数学功能")
        for b in (self.btn_tab_measure, self.btn_tab_math):
            b.setCheckable(True)
            b.setFixedWidth(120)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        sv.addLayout(btn_row)
        self.side_stack = QStackedWidget()
        self.side_stack.addWidget(self._build_measure_panel())
        self.side_stack.addWidget(self._build_math_panel())
        sv.addWidget(self.side_stack, 1)
        self.btn_tab_measure.setChecked(True)
        self.btn_tab_measure.clicked.connect(lambda: self._switch_side(0))
        self.btn_tab_math.clicked.connect(lambda: self._switch_side(1))
        mid.addWidget(_flat_scroll(side))
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 1)
        mid.setSizes([560, 640])
        root.addWidget(mid, stretch=1)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_console_tab(), "SCPI 控制台")
        self.tabs.addTab(self._build_help_tab(), "使用说明")
        self.tabs.setMinimumHeight(160)   # 日志区常驻可见（趋势缩小后免滚动露出）
        root.addWidget(self.tabs)

        self.setCentralWidget(central)

        # 状态栏：连接状态 / 队列长度 / 最近错误人话
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_conn = QLabel("未连接")
        self.lbl_queue = QLabel("队列 0")
        self.lbl_msg = QLabel("就绪")
        sb.addWidget(self.lbl_conn)
        sb.addPermanentWidget(self.lbl_queue)
        sb.addPermanentWidget(self.lbl_msg)

    def _switch_side(self, idx):
        """右侧共用区切换：0=测量功能，1=应用数学功能。"""
        self.side_stack.setCurrentIndex(idx)
        self.btn_tab_measure.setChecked(idx == 0)
        self.btn_tab_math.setChecked(idx == 1)

    def _build_conn_bar(self) -> QGroupBox:
        box = QGroupBox("连接")
        lay = QHBoxLayout(box)

        lay.addWidget(QLabel("接口:"))
        self.iface_combo = QComboBox()
        self.iface_combo.addItems(["RS-232 串口", "模拟从站(自测)"])
        self.iface_combo.currentIndexChanged.connect(self._on_iface_changed)
        lay.addWidget(self.iface_combo)

        lay.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(110)
        lay.addWidget(self.port_combo)

        lay.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["300", "600", "1200", "2400", "4800", "9600",
                                  "19200"])
        self.baud_combo.setCurrentText("9600")
        lay.addWidget(self.baud_combo)

        lay.addWidget(QLabel("校验:"))
        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N（8位）", "E（8位）", "O（8位）"])
        lay.addWidget(self.parity_combo)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_ports)
        lay.addWidget(self.btn_refresh)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.clicked.connect(self._on_connect)
        lay.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setObjectName("btnDisconnect")
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        lay.addWidget(self.btn_disconnect)

        self.btn_reset = QPushButton("复位 (*RST)")
        self.btn_reset.clicked.connect(self._on_reset)
        lay.addWidget(self.btn_reset)

        self.btn_cls = QPushButton("清错误 (*CLS)")
        self.btn_cls.clicked.connect(self._on_clear_errors)
        lay.addWidget(self.btn_cls)

        lay.addStretch(1)
        return box

    def _build_measure_panel(self) -> QGroupBox:
        box = QGroupBox("测量功能")
        lay = QVBoxLayout(box)

        self._func_group = QButtonGroup(self)
        self._func_group.setExclusive(True)
        self._func_buttons = {}
        grid = QHBoxLayout()
        grid.setSpacing(6)
        col_box = QVBoxLayout()
        for i, (label, mnemonic) in enumerate(Instrument.ui_function_list()):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(34)
            btn.setProperty("accent", FUNC_ACCENT.get(mnemonic, "blue"))
            btn.clicked.connect(
                lambda _checked=False, lb=label, mn=mnemonic: self._on_function(lb, mn))
            self._func_group.addButton(btn)
            self._func_buttons[label] = btn
            col_box.addWidget(btn)
            if i == 4:            # 每 5 个一列，共两列
                grid.addLayout(col_box)
                col_box = QVBoxLayout()
        grid.addLayout(col_box)
        lay.addLayout(grid)
        self._func_buttons[self._current_func_label].setChecked(True)

        row = QHBoxLayout()
        row.addWidget(QLabel("量程:"))
        self.range_combo = QComboBox()
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        row.addWidget(self.range_combo, stretch=1)
        lay.addLayout(row)

        self.chk_auto_range = QCheckBox("自动量程")
        self.chk_auto_range.setChecked(True)
        self.chk_auto_range.toggled.connect(self._on_auto_range_toggled)
        lay.addWidget(self.chk_auto_range)

        row = QHBoxLayout()
        row.addWidget(QLabel("速率:"))
        self.rate_combo = QComboBox()
        self.rate_index = {}
        for k, rps in Instrument.rate_table().items():
            self.rate_combo.addItem(f"{k}（{rps:g} 读数/秒）")
            self.rate_index[self.rate_combo.count() - 1] = k
        self.rate_combo.setCurrentText("M（20 读数/秒）")
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        row.addWidget(self.rate_combo, stretch=1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("触发类型:"))
        self.trig_combo = QComboBox()
        self.trig_index = {}
        for t, (src, rear, delay) in Instrument.trigger_table().items():
            self.trig_combo.addItem(f"类型{t}：{src}触发，后面板{rear}，稳定延迟{delay}")
            self.trig_index[self.trig_combo.count() - 1] = t
        self.trig_combo.currentIndexChanged.connect(self._on_trigger_changed)
        row.addWidget(self.trig_combo, stretch=1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("轮询周期:"))
        self.poll_combo = QComboBox()
        for ms in POLL_PERIODS:
            self.poll_combo.addItem(f"{ms} ms")
        self.poll_combo.setCurrentText("500 ms")
        self.poll_combo.currentIndexChanged.connect(self._on_poll_period_changed)
        row.addWidget(self.poll_combo, stretch=1)
        lay.addLayout(row)

        lay.addStretch(1)
        return box

    def _build_display_panel(self) -> QGroupBox:
        box = QGroupBox("测量显示")
        lay = QVBoxLayout(box)

        head = QHBoxLayout()
        self.lbl_func = QLabel(self._current_func_label)
        self.lbl_func.setObjectName("lblFunc")
        self.lbl_func.setStyleSheet("font-size:17px;font-weight:700;")
        self.lbl_range = QLabel("—")
        self.lbl_range_mode = QLabel("自动量程")
        self.lbl_range_mode.setStyleSheet("color:#10b981;font-weight:600;")
        head.addWidget(self.lbl_func)
        head.addSpacing(12)
        head.addWidget(self.lbl_range)
        head.addSpacing(12)
        head.addWidget(self.lbl_range_mode)
        head.addStretch(1)
        lay.addLayout(head)

        self.lbl_value = QLabel("--")
        self.lbl_value.setObjectName("lblValue")
        self.lbl_value.setAlignment(Qt.AlignCenter)
        font = QFont("Consolas", 52, QFont.Bold)
        font.setStyleHint(QFont.Monospace)
        self.lbl_value.setFont(font)
        self.lbl_value.setMinimumHeight(90)
        self.lbl_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.lbl_value)

        trend_head = QHBoxLayout()
        trend_head.addWidget(QLabel("实时趋势"))
        self.btn_trend_pause = QPushButton("暂停")
        self.btn_trend_pause.setCheckable(True)
        self.btn_trend_pause.clicked.connect(self._on_trend_pause)
        self.btn_trend_clear = QPushButton("清空")
        self.btn_trend_clear.clicked.connect(self._on_trend_clear)
        trend_head.addStretch(1)
        trend_head.addWidget(self.btn_trend_pause)
        trend_head.addWidget(self.btn_trend_clear)
        lay.addLayout(trend_head)

        self.trend = TrendWidget()
        self.trend.setFixedHeight(180)   # 趋势缩小：让日志区（SCPI 控制台）免滚动露出
        lay.addWidget(self.trend, stretch=1)
        return box

    def _build_math_panel(self) -> QGroupBox:
        box = QGroupBox("应用数学功能")
        lay = QVBoxLayout(box)

        # ---- REL 基准 ----
        grp_rel = QGroupBox("REL 相对读数")
        l1 = QVBoxLayout(grp_rel)
        self.chk_rel = QCheckBox("启用 REL")
        l1.addWidget(self.chk_rel)
        row = QHBoxLayout()
        row.addWidget(QLabel("基值:"))
        self.ed_rel = QLineEdit()
        self.ed_rel.setPlaceholderText("留空=当前读数为基值")
        row.addWidget(self.ed_rel, stretch=1)
        l1.addLayout(row)
        row = QHBoxLayout()
        self.btn_rel_apply = QPushButton("应用")
        self.btn_rel_apply.clicked.connect(self._on_rel_apply)
        self.btn_rel_clear = QPushButton("清除")
        self.btn_rel_clear.clicked.connect(self._on_rel_clear)
        row.addWidget(self.btn_rel_apply)
        row.addWidget(self.btn_rel_clear)
        l1.addLayout(row)
        lay.addWidget(grp_rel)

        # ---- dB ----
        grp_db = QGroupBox("dB 调节器")
        l2 = QVBoxLayout(grp_db)
        self.chk_db = QCheckBox("启用 dB")
        l2.addWidget(self.chk_db)
        row = QHBoxLayout()
        row.addWidget(QLabel("参考阻抗:"))
        self.dbref_combo = QComboBox()
        self.dbref_index = {}
        for idx, ohms in Instrument.dbref_table().items():
            self.dbref_combo.addItem(f"编号{idx}：{ohms} Ω")
            self.dbref_index[self.dbref_combo.count() - 1] = idx
        self.dbref_combo.setCurrentText("编号19：1000 Ω")
        row.addWidget(self.dbref_combo, stretch=1)
        l2.addLayout(row)
        row = QHBoxLayout()
        self.btn_db_apply = QPushButton("应用")
        self.btn_db_apply.clicked.connect(self._on_db_apply)
        self.btn_db_clear = QPushButton("清除")
        self.btn_db_clear.clicked.connect(self._on_db_clear)
        row.addWidget(self.btn_db_apply)
        row.addWidget(self.btn_db_clear)
        l2.addLayout(row)
        lay.addWidget(grp_db)

        # ---- P/F 比对 ----
        grp_comp = QGroupBox("P/F 比对")
        l3 = QVBoxLayout(grp_comp)
        row = QHBoxLayout()
        row.addWidget(QLabel("下限:"))
        self.ed_comp_lo = QLineEdit("0")
        row.addWidget(self.ed_comp_lo, stretch=1)
        l3.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("上限:"))
        self.ed_comp_hi = QLineEdit("1")
        row.addWidget(self.ed_comp_hi, stretch=1)
        l3.addLayout(row)
        self.btn_comp = QPushButton("P/F 判定")
        self.btn_comp.setObjectName("btnComp")
        self.btn_comp.clicked.connect(self._on_comp_judge)
        l3.addWidget(self.btn_comp)
        self.lbl_comp = QLabel("--")
        self.lbl_comp.setObjectName("lblComp")
        self.lbl_comp.setAlignment(Qt.AlignCenter)
        f = QFont("Consolas", 30, QFont.Bold)
        f.setStyleHint(QFont.Monospace)
        self.lbl_comp.setFont(f)
        l3.addWidget(self.lbl_comp)
        row = QHBoxLayout()
        self.btn_comp_off = QPushButton("退出比对")
        self.btn_comp_off.clicked.connect(self._on_comp_off)
        row.addWidget(self.btn_comp_off)
        l3.addLayout(row)
        lay.addWidget(grp_comp)

        lay.addStretch(1)
        return box

    def _build_console_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.log = QTextEdit()
        self.log.setObjectName("logView")   # 深色控制台样式由主题提供
        self.log.setReadOnly(True)
        lay.addWidget(self.log, stretch=1)

        row = QHBoxLayout()
        self.ed_cmd = QLineEdit()
        self.ed_cmd.setPlaceholderText("输入 SCPI 命令，如 *IDN? / VDC / RANGE 3（查询命令以 ? 结尾）")
        self.ed_cmd.returnPressed.connect(self._on_cmd_query)
        row.addWidget(self.ed_cmd, stretch=1)
        self.btn_query = QPushButton("查询")
        self.btn_query.clicked.connect(self._on_cmd_query)
        self.btn_send = QPushButton("发送")
        self.btn_send.clicked.connect(self._on_cmd_send)
        self.btn_log_clear = QPushButton("清空日志")
        self.btn_log_clear.clicked.connect(self.log.clear)
        row.addWidget(self.btn_query)
        row.addWidget(self.btn_send)
        row.addWidget(self.btn_log_clear)
        lay.addLayout(row)
        return w

    def _build_help_tab(self) -> QWidget:
        browser = QTextBrowser()
        browser.setHtml(HELP_HTML)
        return browser

    def _build_timers(self):
        # 轮询定时器：按周期触发读数（内部再走后台线程，不阻塞界面）
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_tick)
        # 界面刷新定时器：周期 >= 轮询周期（防刷新快于串口吞吐导致队列堆积）
        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._ui_refresh)

    # ================================================================ 连接管理
    def _refresh_ports(self):
        self.port_combo.clear()
        try:
            from serial.tools import list_ports
            ports = sorted(p.device for p in list_ports.comports())
        except Exception:
            ports = []
        self.port_combo.addItems(ports or ["(未检测到串口)"])

    def _on_iface_changed(self):
        serial_mode = "串口" in self.iface_combo.currentText()
        for w in (self.port_combo, self.baud_combo, self.parity_combo,
                  self.btn_refresh):
            w.setEnabled(serial_mode)

    def _on_connect(self):
        if self._connected:
            return
        iface = self.iface_combo.currentText()
        try:
            if "模拟" in iface:
                host_end, sim = build_sim_pair()
                sim.start()
                self._sim = sim
                self._transport = host_end
            else:
                port = self.port_combo.currentText()
                if not port or port.startswith("(未"):
                    self._report(False, "未选择串口，请点“刷新”后选择可用串口")
                    return
                parity_map = {"N（8位）": "N", "E（8位）": "E", "O（8位）": "O"}
                self._transport = SerialTransport(
                    port, int(self.baud_combo.currentText()),
                    parity=parity_map[self.parity_combo.currentText()])
                self._sim = None
        except Exception as e:
            self._report(False, f"连接失败：{e}")
            return

        self._stack = ProtocolStack(self._transport, StackConfig(),
                                    on_frame=self._on_frame)
        self._stack.start()
        self.instrument = Instrument(self._stack)
        self._connected = True
        self._set_connected_state(True)

        try:
            ok, info, msg = self.instrument.identity()
        except Exception as e:
            ok, info, msg = False, None, f"识别仪器失败：{e}"
        if ok:
            self.lbl_conn.setText(
                f"已连接：{info.manufacturer} {info.model}  序列号 {info.serial}  "
                f"固件 {info.firmware}")
            self._report(True, f"连接成功，{msg}")
        else:
            self.lbl_conn.setText(f"已连接（{iface}），仪器识别失败")
            self._report(False, msg)

    def _on_disconnect(self):
        if not self._connected:
            return
        self._poll_timer.stop()
        self._ui_timer.stop()
        self._poll_busy = False
        self._poll_fail = 0
        self._poll_lost = False
        try:
            if self._stack:
                self._stack.stop()
        except Exception:
            pass
        try:
            if self._transport:
                self._transport.close()
        except Exception:
            pass
        try:
            if self._sim:
                self._sim.stop()
        except Exception:
            pass
        self._stack = None
        self._transport = None
        self._sim = None
        self._connected = False
        self._set_connected_state(False)
        self.lbl_conn.setText("未连接")
        self.lbl_queue.setText("队列 0")
        self._report(True, "已断开连接")

    def _set_connected_state(self, connected: bool):
        self.btn_connect.setEnabled(not connected)
        self.btn_connect.setText("已连接" if connected else "连接")
        self.btn_connect.setObjectName("btnConnected" if connected else "btnConnect")
        self.btn_disconnect.setEnabled(connected)
        self.iface_combo.setEnabled(not connected)
        for w in (self.btn_reset, self.btn_cls, self.range_combo,
                  self.chk_auto_range, self.rate_combo, self.trig_combo,
                  self.btn_rel_apply, self.btn_rel_clear, self.btn_db_apply,
                  self.btn_db_clear, self.btn_comp, self.btn_comp_off,
                  self.btn_query, self.btn_send):
            w.setEnabled(connected)
        for btn in self._func_buttons.values():
            btn.setEnabled(connected)
        self._on_iface_changed() if not connected else None
        if connected:
            interval = POLL_PERIODS[self.poll_combo.currentIndex()]
            self._poll_timer.start(interval)
            self._ui_timer.start(interval)   # 界面刷新周期 == 轮询周期

    def _on_reset(self):
        self._ask(lambda: self.instrument.reset())

    def _on_clear_errors(self):
        self._ask(lambda: self.instrument.clear_status())
        try:
            ok, msg = self.instrument.esr_summary()
        except Exception as e:
            ok, msg = False, f"读取 ESR 失败：{e}"
        self._report(ok, msg)

    def _ask(self, fn):
        """执行一条语义接口调用，异常转人话，不弹裸 traceback。"""
        if not self._connected:
            self._report(False, "未连接，请先连接仪器")
            return
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"操作失败：{e}"
        self._report(ok, msg)

    # ================================================================ 测量设置
    def _on_function(self, label: str, mnemonic: str):
        if not self._connected:
            return
        try:
            ok, msg = self.instrument.set_function(mnemonic)
            if ok and "4线" in label:
                ok, msg = self.instrument.set_wire(True)
            elif ok and "2线" in label:
                ok, msg = self.instrument.set_wire(False)
        except Exception as e:
            ok, msg = False, f"切换功能失败：{e}"
        if not ok:
            self._report(False, msg)
            self._func_buttons[self._current_func_label].setChecked(True)  # 回退高亮
            return
        self._current_func_label = label
        self.lbl_func.setText(label)
        self._refresh_range_combo()
        self._report(True, msg)

    def _refresh_range_combo(self):
        """按当前功能过滤不适用量程（单一事实源派生文字）。"""
        self._updating_ui = True
        try:
            mnemonic = dict(Instrument.ui_function_list())[self._current_func_label]
            helper = self.instrument or self._label_helper
            self.range_combo.clear()
            self.range_combo.addItem("自动")
            for n in range(1, 8):
                label = helper.range_label(mnemonic, n)
                if "不适用" in label:
                    continue
                self.range_combo.addItem(label)
            self.range_combo.setCurrentIndex(0 if self.chk_auto_range.isChecked()
                                             else 1)
        finally:
            self._updating_ui = False

    def _on_range_changed(self, index: int):
        if self._updating_ui or not self._connected:
            return
        text = self.range_combo.currentText()
        self._updating_ui = True
        try:
            auto = (text == "自动")
            self.chk_auto_range.setChecked(auto)
            self.lbl_range_mode.setText("自动量程" if auto else "手动量程")
            self.lbl_range.setText("自动" if auto else text)
        finally:
            self._updating_ui = False
        if auto:
            self._ask(lambda: self.instrument.set_auto_range())
        else:
            n = int(text.split("号")[0].strip())
            self._ask(lambda: self.instrument.set_manual_range(n))

    def _on_auto_range_toggled(self, checked: bool):
        if self._updating_ui or not self._connected:
            return
        self._updating_ui = True
        try:
            self.range_combo.setCurrentIndex(0 if checked else 1)
        finally:
            self._updating_ui = False
        self._on_range_changed(self.range_combo.currentIndex())

    def _on_rate_changed(self, index: int):
        if not self._connected:
            return
        rate = self.rate_index.get(index, "M")
        self._ask(lambda: self.instrument.set_rate(rate))

    def _on_trigger_changed(self, index: int):
        if not self._connected:
            return
        t = self.trig_index.get(index, 1)
        self._ask(lambda: self.instrument.set_trigger_type(t))

    def _on_poll_period_changed(self, index: int):
        ms = POLL_PERIODS[index]
        if self._connected:
            self._poll_timer.start(ms)
            self._ui_timer.start(ms)     # 界面刷新周期不低于轮询周期
        self._report(True, f"轮询周期已设为 {ms} ms")

    # ================================================================ 轮询与显示
    def _poll_tick(self):
        """定时触发读数；上一条未完成或队列积压时跳过本次（防堆积假死）。"""
        if not self._connected or self._poll_busy or self.instrument is None:
            return
        if self._stack.queue_size > 1:
            return
        self._poll_busy = True
        threading.Thread(target=self._poll_worker, daemon=True).start()

    def _poll_worker(self):
        # 后台线程执行阻塞读取，结果经信号回 GUI 线程
        try:
            if self.trig_index.get(self.trig_combo.currentIndex(), 1) >= 2:
                reading = self.instrument.read_fast()     # 外触发：VAL1?
            else:
                reading = self.instrument.read_primary()  # 内触发：MEAS1?
        except Exception as e:
            reading = Reading(None, "", "", False, f"读取失败：{e}")
        self.sig_reading.emit(reading)

    def _on_reading(self, reading: Reading):
        self._poll_busy = False
        if reading.ok:
            from instrument_hub.comm_state import mark_ok
            mark_ok(self)   # 收到仪器读数 = 通讯真正建立
            if self._poll_lost:   # 掉线后恢复应答：自动恢复在线 + 回到原轮询周期
                self._poll_lost = False
                self._poll_timer.start(POLL_PERIODS[self.poll_combo.currentIndex()])
                self._report(True, "设备恢复应答，自动恢复在线")
            self._poll_fail = 0
            if reading.value is not None:
                unit = f" {reading.unit}" if reading.unit else ""
                self.lbl_value.setText(f"{reading.value:.6g}{unit}")
                self.trend.add_point(reading.value)
            else:
                self.lbl_value.setText("0L")        # 过载（屏显 0L）
        else:
            self.lbl_value.setText("--")
            self._poll_fail += 1
            if self._poll_fail >= POLL_LOST_FAILS:
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)   # 连续无应答 = 通讯中断
                if not self._poll_lost:
                    self._poll_lost = True
                    self._poll_timer.start(POLL_LOST_MS)   # 降为低频探测，恢复可自动上线
                self._report(False, f"设备连续 {self._poll_fail} 次无响应，"
                                    "标记离线（低频探测中，恢复应答后自动上线）")
            else:
                self._report(False, reading.message)

    def _ui_refresh(self):
        if self._connected and self._stack:
            self.lbl_queue.setText(f"队列 {self._stack.queue_size}")

    def _on_trend_pause(self):
        paused = self.btn_trend_pause.isChecked()
        self.trend.set_paused(paused)
        self.btn_trend_pause.setText("继续" if paused else "暂停")

    def _on_trend_clear(self):
        self.trend.clear()

    # ================================================================ 应用数学
    def _on_rel_apply(self):
        if not self._connected:
            self._report(False, "未连接，请先连接仪器")
            return
        text = self.ed_rel.text().strip()
        try:
            if text:
                base = float(text)
                ok, msg = self.instrument.rel_on(base)
            else:
                ok, msg = self.instrument.rel_on()
        except ValueError:
            ok, msg = False, "REL 基值不是有效数字，未发送"
        except Exception as e:
            ok, msg = False, f"REL 设置失败：{e}"
        self.chk_rel.setChecked(ok)
        self._report(ok, msg)

    def _on_rel_clear(self):
        self._ask(lambda: self.instrument.rel_off())
        self.chk_rel.setChecked(False)

    def _on_db_apply(self):
        if not self._connected:
            self._report(False, "未连接，请先连接仪器")
            return
        idx = self.dbref_index.get(self.dbref_combo.currentIndex(), 19)
        try:
            ok, msg = self.instrument.set_dbref(idx)
            if ok:
                ok, msg = self.instrument.db_on()
        except Exception as e:
            ok, msg = False, f"dB 设置失败：{e}"
        self.chk_db.setChecked(ok)
        self._report(ok, msg)

    def _on_db_clear(self):
        self._ask(lambda: self.instrument.db_off())
        self.chk_db.setChecked(False)

    def _on_comp_judge(self):
        if not self._connected:
            self._report(False, "未连接，请先连接仪器")
            return
        try:
            lo = float(self.ed_comp_lo.text().strip())
            hi = float(self.ed_comp_hi.text().strip())
        except ValueError:
            self._report(False, "比对上下限不是有效数字，未发送")
            return
        try:
            ok, msg = self.instrument.comp_setup(lo, hi)
            if ok:
                ok, msg = self.instrument.comp_on()
            if ok:
                ok, msg = self.instrument.comp_result()
        except Exception as e:
            ok, msg = False, f"比对判定失败：{e}"
        self.lbl_comp.setText(self._short_comp(msg) if ok else "--")
        self._report(ok, msg)

    @staticmethod
    def _short_comp(human: str) -> str:
        """人话判定结果 -> 大字短语 PASS/HI/LO。"""
        if "PASS" in human:
            return "PASS"
        if "HI" in human:
            return "HI"
        if "LO" in human:
            return "LO"
        return human

    def _on_comp_off(self):
        self._ask(lambda: self.instrument.comp_off())

    # ================================================================ SCPI 控制台
    def _on_cmd_query(self):
        self._run_cmd(show_payload=True)

    def _on_cmd_send(self):
        self._run_cmd(show_payload=False)

    def _run_cmd(self, show_payload: bool):
        if not self._connected:
            self._report(False, "未连接，请先连接仪器")
            return
        cmd = self.ed_cmd.text().strip()
        if not cmd:
            self._report(False, "命令为空，请输入 SCPI 命令")
            return
        try:
            r = self.instrument.query(cmd)      # 用户显式输入，仍经协议栈队列/超时保护
        except Exception as e:
            self._append_log("ERR", f"命令执行失败: {e}")
            self._report(False, f"命令执行失败：{e}")
            return
        if r.ok:
            if show_payload:
                self._append_log("INFO", f"响应: {r.payload}")
            else:
                self._append_log("INFO", r.message)
            self._report(True, r.message)
        else:
            self._append_log("ERR", r.message)
            self._report(False, r.message)

    # ================================================================ 日志与提示
    def _on_frame(self, direction: str, text: str):
        """协议栈收发帧回调（worker 线程）-> 信号转发 GUI 线程。"""
        self.sig_frame.emit(direction, text)

    def _append_log(self, direction: str, text: str):
        ts = time.strftime("%H:%M:%S")
        colors = {"TX": "#4ec96b", "RX": "#eaeaea", "ERR": "#ff6b6b",
                  "INFO": "#9cdcfe"}
        color = colors.get(direction, "#eaeaea")
        tag = {"TX": "TX", "RX": "RX", "ERR": "错误", "INFO": "提示"}.get(direction, direction)
        self.log.append(f'<span style="color:#888">[{ts}]</span> '
                        f'<span style="color:{color}">{tag}: '
                        f'{text.replace("&", "&amp;").replace("<", "&lt;")}</span>')
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _report(self, ok: bool, message: str):
        """统一人话提示：状态栏 + 控制台日志（异常不弹裸 traceback）。"""
        self.lbl_msg.setText(message)
        self.lbl_msg.setStyleSheet("color:#c0392b;" if not ok else "color:#2e7d32;")
        self._append_log("INFO" if ok else "ERR", message)

    # ================================================================ 关闭
    def closeEvent(self, event):
        try:
            self._on_disconnect()
        except Exception:
            pass
        super().closeEvent(event)


# ---------------------------------------------------------------- 使用说明
HELP_HTML = """
<h2>FLUKE 8808A 上位机 使用说明</h2>

<h3>一、连接步骤</h3>
<ol>
<li>接口选 <b>RS-232 串口</b>，点 <b>刷新</b> 选择串口；无真机自测时选
    <b>模拟从站(自测)</b>（无需串口）。</li>
<li>按仪器面板设置选择波特率（300~19200，默认 9600）与校验
    （N/E/O，均为 8 数据位），须与仪器一致。</li>
<li>点 <b>连接</b>。连接成功后状态栏显示型号/序列号/固件版本。</li>
<li>点 <b>复位 (*RST)</b> 可恢复上电状态；点 <b>清错误 (*CLS)</b> 清状态寄存器，
    并以人话显示 *ESR? 结果。</li>
<li>点 <b>断开</b> 结束会话。</li>
</ol>

<h3>二、测量功能按钮</h3>
<p>左侧按功能切换主屏测量：直流电压 / 交流电压 / 直流电流 / 交流电流 /
电阻(2线) / 电阻(4线) / 频率 / 通断性 / 二极管。按钮高亮表示当前功能。
量程下拉只列当前功能适用的量程编号（自动 + 1~7 号）；勾选
<b>自动量程</b> 进入自动量程，取消则按所选编号手动锁定。
速率 S=2.5 / M=20 / F=100 读数每秒；触发类型 1 为内部触发，
类型 2~5 为外部触发（此时轮询改读显示值 VAL1?）。</p>

<h3>三、模拟从站自测</h3>
<p>接口选 <b>模拟从站(自测)</b> 后点连接，即可在无真机环境下走真实收发路径，
用于开发回归与异常路径验证。模拟从站忠实实现手册第 4 章命令语义，
支持故障注入（超时、错帧、断线、半包/粘包）。</p>

<h3>四、实时趋势与轮询</h3>
<p>连接后按轮询周期自动读数（默认 500 ms，可选 200/500/1000/2000 ms）。
趋势图保留最近 300 点，横轴时间、纵轴读数，可暂停/清空。
界面刷新周期不低于轮询周期，且上一条读数未完成时自动跳过本次轮询，
防止收发队列堆积导致界面假死。</p>

<h3>五、异常提示含义（人话对照）</h3>
<table border="1" cellpadding="5" cellspacing="0">
<tr><th>提示符/现象</th><th>含义</th></tr>
<tr><td><b>=&gt;</b></td><td>正常：命令执行成功，可发下一条</td></tr>
<tr><td><b>?&gt;</b></td><td>命令错误：仪器无法解析该命令（语法错误），命令未执行</td></tr>
<tr><td><b>!&gt;</b></td><td>执行错误：命令可解析但无法执行（参数越界或当前功能不允许）</td></tr>
<tr><td>超时</td><td>仪器未在限定时间内返回提示符（已达到重发上限后退出，不会卡死）</td></tr>
<tr><td>链路断开</td><td>串口连接丢失或从站无响应，请检查连线/电源后重新连接</td></tr>
<tr><td>显示 0L</td><td>过载：被测量超出当前量程，可增大量程或确认接线</td></tr>
<tr><td>显示 --</td><td>读数失败（错误详情见状态栏与 SCPI 控制台）</td></tr>
</table>

<h3>六、SCPI 控制台</h3>
<p>可直接输入手册命令调试：以 <b>?</b> 结尾的查询命令点 <b>查询</b> 显示响应，
设置命令点 <b>发送</b>。日志中 TX（绿）为发送帧、RX（白）为响应帧、
错误（红）为异常人话提示，均带时间戳。</p>
"""
