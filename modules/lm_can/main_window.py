"""
联明电源 CAN通讯控制上位机 v1.0
UT-6502 以太网-CAN 通讯
PyQt5 实现, 统一浅色主题, 表格列宽可拖拽调整
"""

import sys
import time
from collections import OrderedDict

from modules.theme_util import expand_qss
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QTabWidget, QTextEdit, QGroupBox,
    QComboBox, QDoubleSpinBox, QMessageBox, QSplitter, QFrame, QAbstractItemView,
    QStyledItemDelegate
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QFont, QIcon, QBrush, QTextCursor, QPixmap

from . import can_protocol as cp
from .ut6502_driver import UT6502Driver

DARK_STYLE = """
/* 统一浅色主题 v2.5 */
QMainWindow { background: #F0F2F5; }
QWidget { color: #1B2430; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 12px; }
QWidget#central, QMainWindow#central { background: #F0F2F5; }

/* ---------- 分组框 ---------- */
QGroupBox {
    background: #FFFFFF; border: 1px solid #D8DEE6; border-radius: 6px;
    margin-top: 10px; padding: 10px 8px 8px 8px;
    color: #1B2430; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #1B2430; }

/* ---------- 标签 ---------- */
QLabel { color: #1B2430; background: transparent; }
QLabel#titleLabel, QLabel#title, QLabel#monitorTitle, QLabel#logTitle {
    font-size: 14px; font-weight: bold; color: #1B2430;
}
QLabel#monitorStat, QLabel#logCount, QLabel#detailKey, QLabel#detailNote {
    color: #6B7280;
}
QLabel#detailVal { color: #0B7A76; font-weight: 600; }
QLabel#lblOnline, QLabel#lblOnline[online="1"] { color: #0B7A76; font-weight: 600; }
QLabel#lblOffline { color: #8B95A5; }
QLabel#connDot { color: #8B95A5; font-size: 13px; }

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
    background: #FFFFFF; color: #1B2430;
    border: 1px solid #C9D1DB; border-radius: 4px;
    padding: 2px 6px; min-height: 20px;
    selection-background-color: #2F80ED; selection-color: #FFFFFF;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #2F80ED;
}
QComboBox QAbstractItemView {
    background: #FFFFFF; color: #1B2430;
    border: 1px solid #C9D1DB; border-radius: 4px;
    selection-background-color: #2F80ED; selection-color: #FFFFFF;
    outline: none; padding: 2px;
}
QComboBox QAbstractItemView::item { padding: 5px 8px; min-height: 22px; }

/* ---------- 按钮（默认） ---------- */
QPushButton {
    background: #FFFFFF; color: #1B2430;
    border: 1px solid #C9D1DB; border-radius: 4px;
    padding: 5px 14px; min-height: 24px; font-weight: 600;
}
QPushButton:hover { background: #F7F9FB; border-color: #A9B6C5; }
QPushButton:pressed { background: #E8ECF1; }
QPushButton:disabled { background: #E8ECF1; color: #9AA2AA; border-color: #D8DEE6; }

/* 绿：开机/成功 */
QPushButton#success, QPushButton#btnGreen, QPushButton#btnPowerOn,
QPushButton#btnOn, QPushButton#btnBatchOn, QPushButton#greenBtn {
    background: #047857; color: #FFFFFF; border: 1px solid #249040;
}
QPushButton#success:hover, QPushButton#btnGreen:hover, QPushButton#btnPowerOn:hover,
QPushButton#btnOn:hover, QPushButton#btnBatchOn:hover, QPushButton#greenBtn:hover {
    background: #3CB85C;
}
QPushButton#small_success { background: #047857; color: #FFFFFF; border: 1px solid #249040; }

/* 红：关机/危险 */
QPushButton#danger, QPushButton#btnPink, QPushButton#btnPowerOff,
QPushButton#btnOff, QPushButton#btnBatchOff, QPushButton#redBtn,
QPushButton#btnDisconnect, QPushButton#btnRed {
    background: #D9534F; color: #FFFFFF; border: 1px solid #C44340;
}
QPushButton#danger:hover, QPushButton#btnPink:hover, QPushButton#btnPowerOff:hover,
QPushButton#btnOff:hover, QPushButton#btnBatchOff:hover, QPushButton#redBtn:hover,
QPushButton#btnDisconnect:hover, QPushButton#btnRed:hover {
    background: #E46661;
}
QPushButton#small_danger { background: #D9534F; color: #FFFFFF; border: 1px solid #C44340; }

/* 蓝：设置/连接/主操作 */
QPushButton#btnBlue, QPushButton#btnSet, QPushButton#btnSetVI, QPushButton#btnBatchSet,
QPushButton#btnScan, QPushButton#accentBtn, QPushButton#btnConnect,
QPushButton#btnConnected, QPushButton#blueBtn {
    background: #2F80ED; color: #FFFFFF; border: 1px solid #2568C4;
}
QPushButton#btnBlue:hover, QPushButton#btnSet:hover, QPushButton#btnSetVI:hover,
QPushButton#btnBatchSet:hover, QPushButton#btnScan:hover, QPushButton#accentBtn:hover,
QPushButton#btnConnect:hover, QPushButton#btnConnected:hover, QPushButton#blueBtn:hover {
    background: #4A93F2;
}

/* 黄/橙：初始化/警告 */
QPushButton#warning, QPushButton#btnYellow, QPushButton#btnInit, QPushButton#yellowBtn {
    background: #E8A317; color: #FFFFFF; border: 1px solid #D18A12;
}
QPushButton#warning:hover, QPushButton#btnYellow:hover, QPushButton#btnInit:hover,
QPushButton#yellowBtn:hover { background: #F0B22F; }

/* 灰：次要 */
QPushButton#btnGray, QPushButton#btnChangeAddr, QPushButton#logBtn {
    background: #E8ECF1; color: #1B2430; border: 1px solid #C9D1DB;
}
QPushButton#btnGray:hover, QPushButton#btnChangeAddr:hover, QPushButton#logBtn:hover {
    background: #DDE3EA;
}

/* 小按钮 */
QPushButton#small { padding: 3px 8px; min-height: 20px; font-size: 11px; }
QPushButton#small_success, QPushButton#small_danger {
    padding: 3px 8px; min-height: 20px; font-size: 11px;
}

/* ---------- 表格 ---------- */
QTableWidget, QTableView {
    background: #FFFFFF; alternate-background-color: #F7F9FB;
    color: #1B2430; gridline-color: #E4E9EF;
    border: 1px solid #D8DEE6; border-radius: 4px;
    selection-background-color: #D6E8FF; selection-color: #1B2430;
}
QTableWidget::item { padding: 3px; }
QTableWidget::item:selected { background: #D6E8FF; }
QHeaderView::section {
    background: #E8ECF1; color: #1B2430;
    border: none; border-right: 1px solid #D0D5DD; border-bottom: 1px solid #D0D5DD;
    padding: 6px; font-weight: 600;
}
QTableCornerButton::section { background: #E8ECF1; border: 1px solid #D0D5DD; }

/* ---------- 勾选/单选 ---------- */
QCheckBox, QRadioButton { color: #1B2430; spacing: 6px; background: transparent; }
QCheckBox::indicator, QTableWidget::indicator, QListWidget::indicator {
    width: 18px; height: 18px;
    border: 2px solid #8FA8CC; border-radius: 4px;
    background: #FFFFFF;
}
QCheckBox::indicator:checked, QTableWidget::indicator:checked, QListWidget::indicator:checked {
    background: #4A9DFF; border-color: #2F80ED;
}
QCheckBox::indicator:hover, QTableWidget::indicator:hover, QListWidget::indicator:hover {
    border-color: #2F80ED;
}
QRadioButton::indicator { width: 16px; height: 16px; border: 2px solid #8FA8CC; border-radius: 9px; background: #FFFFFF; }
QRadioButton::indicator:checked { border: 4px solid #2F80ED; background: #FFFFFF; }

/* ---------- 页签 ---------- */
QTabWidget::pane { border: 1px solid #D8DEE6; border-radius: 4px; background: #FFFFFF; }
QTabBar::tab {
    background: #E8ECF1; color: #6B7280;
    border: 1px solid #D0D5DD; border-bottom: none;
    padding: 6px 16px; font-size: 12px;
}
QTabBar::tab:selected { background: #FFFFFF; color: #2F80ED; border-bottom: 2px solid #2F80ED; font-weight: 600; }
QTabBar::tab:hover { color: #1B2430; }

/* ---------- 日志/监控框 ---------- */
QTextEdit, QPlainTextEdit {
    background: #FAFBFC; color: #1B2430;
    border: 1px solid #D8DEE6; border-radius: 4px;
    font-family: "Consolas", "Courier New", monospace;
}
QFrame#monitor, QWidget#monitor, QFrame#monitorPanel {
    background: #FFFFFF; border: 1px solid #D8DEE6; border-radius: 4px;
}
QWidget#monitorBar, QFrame#logBar {
    background: #EEF1F5; border: 1px solid #D8DEE6; border-radius: 4px;
}
QFrame#logPanel { background: #FFFFFF; border: 1px solid #D8DEE6; border-radius: 4px; }
QWidget#connBar { background: #FFFFFF; border: 1px solid #D8DEE6; border-radius: 6px; }
QGroupBox#panelGroup { background: #FFFFFF; }
QWidget#overlayBox {
    background: rgba(240, 242, 245, 0.92);
    border: 1px dashed #A9B6C5; border-radius: 8px;
}

/* ---------- 滚动条 ---------- */
QScrollBar:horizontal {
    background: #E8ECF1; height: 14px; margin: 0 14px 0 14px;
}
QScrollBar::handle:horizontal {
    background: #A9B6C5; min-width: 32px; border-radius: 6px;
}
QScrollBar::handle:horizontal:hover { background: #2F80ED; }
QScrollBar:vertical {
    background: #E8ECF1; width: 14px; margin: 14px 0 14px 0;
}
QScrollBar::handle:vertical {
    background: #A9B6C5; min-height: 32px; border-radius: 6px;
}
QScrollBar::handle:vertical:hover { background: #2F80ED; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    background: #D0D5DD; border: none;
}
QScrollBar::add-line:horizontal { width: 14px; subcontrol-origin: margin; subcontrol-position: right; }
QScrollBar::sub-line:horizontal { width: 14px; subcontrol-origin: margin; subcontrol-position: left; }
QScrollBar::add-line:vertical { height: 14px; subcontrol-origin: margin; subcontrol-position: bottom; }
QScrollBar::sub-line:vertical { height: 14px; subcontrol-origin: margin; subcontrol-position: top; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* ---------- 分割条 / 进度条 / 消息框 ---------- */
QSplitter::handle { background: #D0D5DD; width: 2px; height: 2px; }
QSplitter::handle:hover { background: #2F80ED; }
QProgressBar {
    background: #E8ECF1; border: 1px solid #C9D1DB; border-radius: 4px;
    text-align: center; color: #1B2430; height: 16px;
}
QProgressBar::chunk { background: #2F80ED; border-radius: 3px; }
QMessageBox { background: #F0F2F5; }
QMenu { background: #FFFFFF; color: #1B2430; border: 1px solid #D8DEE6; }
QMenu::item:selected { background: #D6E8FF; }
QToolTip { background: #1B2430; color: #FFFFFF; border: none; padding: 4px; }

/* ---------- 语义化按钮类 ---------- */
QPushButton#btnPrimary { background: #2F80ED; color: #FFFFFF; border: 1px solid #2568C4; }
QPushButton#btnPrimary:hover { background: #4A93F2; }
QPushButton#btnDanger { background: #D9534F; color: #FFFFFF; border: 1px solid #C44340; }
QPushButton#btnDanger:hover { background: #E46661; }
QPushButton#btnSuccess { background: #047857; color: #FFFFFF; border: 1px solid #249040; }
QPushButton#btnSuccess:hover { background: #3CB85C; }
QPushButton#btnWarn { background: #E8A317; color: #FFFFFF; border: 1px solid #D18A12; }
QPushButton#btnWarn:hover { background: #F0B22F; }

/* ---------- 禾享 style=property 按钮 ---------- */
QPushButton[cls="green"] { background: #047857; color: #FFFFFF; border: 1px solid #249040; }
QPushButton[cls="green"]:hover { background: #3CB85C; }
QPushButton[cls="pink"] { background: #D9534F; color: #FFFFFF; border: 1px solid #C44340; }
QPushButton[cls="pink"]:hover { background: #E46661; }
QPushButton[cls="blue"] { background: #2F80ED; color: #FFFFFF; border: 1px solid #2568C4; }
QPushButton[cls="blue"]:hover { background: #4A93F2; }
QPushButton[cls="cream"] { background: #E8A317; color: #FFFFFF; border: 1px solid #D18A12; }
QPushButton[cls="cream"]:hover { background: #F0B22F; }

/* ---------- 数字加减键：彩色三角箭头（高度各半，随行高自适应） ---------- */
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; height: 15px;
    border-left: 1px solid #C9D1DB;
    border-top-right-radius: 3px;
    background: #DCE3EC;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; height: 15px;
    border-left: 1px solid #C9D1DB;
    border-bottom-right-radius: 3px;
    background: #DCE3EC;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: #C3D2E3;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(%%ASSETS%%/arrow_up.png);
    width: 9px; height: 9px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(%%ASSETS%%/arrow_down.png);
    width: 9px; height: 9px;
}

/* ---------- 下拉箭头：彩色三角 ---------- */
QComboBox::drop-down {
    border: none; width: 22px;
    background: #DCE3EC; border-left: 1px solid #C9D1DB;
    border-top-right-radius: 3px; border-bottom-right-radius: 3px;
}
QComboBox::down-arrow {
    image: url(%%ASSETS%%/arrow_drop.png);
    width: 11px; height: 11px;
}

/* 表格内行按钮：紧凑，不随单元格拉伸 */
QTableWidget QPushButton {
    padding: 2px 8px; min-height: 22px; max-height: 26px;
    max-width: 72px; font-size: 11px;
}
"""

STYLE_ONLINE = QColor("#4ade80")
STYLE_OFFLINE = QColor("#71717a")
STYLE_POWER_ON = QColor("#4ade80")
STYLE_POWER_OFF = QColor("#71717a")
STYLE_FAULT = QColor("#f87171")
STYLE_NORMAL = QColor("#a5b4fc")
STYLE_HEADER = QColor("#E4E9EF")
STYLE_ALT_ROW = QColor("#252530")
STYLE_ROW = QColor("#1e1e2a")

NUM_MODULES = 60
COL_CHECK = 0
COL_ADDR = 1
COL_ONLINE = 2
COL_POWER = 3
COL_VOLTAGE = 4
COL_CURRENT = 5
COL_BUS_VOLT = 6
COL_SET_VOLT = 7
COL_SET_CURR = 8
COL_MODE = 9
COL_FAULT = 10
COL_BTN_ON = 11
COL_BTN_OFF = 12
COL_BTN_SET = 13
COLUMN_HEADERS = [
    "选择", "地址", "在线", "电源",
    "电压(V)", "电流(A)", "母线电压(V)",
    "设置电压(V)", "设置电流(A)",
    "模式", "故障",
    "开机", "关机", "设置V/I"
]
COLUMN_WIDTHS = [40, 55, 55, 55, 80, 80, 90, 90, 90, 55, 120, 50, 50, 60]


class ModuleData:
    def __init__(self, addr):
        self.addr = addr
        self.online = False
        self.power_on = False
        self.output_voltage = 0.0
        self.output_current = 0.0
        self.bus_voltage = 0.0
        self.set_voltage = 0.0
        self.set_current = 0.0
        self.mode = "---"
        self.fault = "---"
        self.has_fault = False
        self.last_seen = 0.0
        self.status_hi = 0
        self.status_lo = 0

    def reset_offline(self):
        self.online = False
        self.power_on = False
        self.output_voltage = 0.0
        self.output_current = 0.0
        self.bus_voltage = 0.0
        self.mode = "---"
        self.fault = "---"
        self.has_fault = False


class CenterAlignDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignCenter


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("联明电源 CAN通讯控制上位机 v1.0 (UT-6502 以太网-CAN)")
        self.resize(1400, 850)
        self.setMinimumSize(1100, 700)

        self.driver = UT6502Driver()
        self.modules = OrderedDict()
        self._scan_busy = False
        self._scan_cancelled = False
        for i in range(1, NUM_MODULES + 1):
            self.modules[i] = ModuleData(i)

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_next)
        self.poll_index = 0
        self.poll_sub_step = 0
        self.POLL_STEPS = 4
        self._discovery_counter = 0
        self._discovery_interval = 5
        self._discovery_scan = False
        self._discovery_probe_idx = 0

        self.fast_timer = QTimer()
        self.fast_timer.timeout.connect(self._fast_refresh)
        self.fast_index = 0
        self.fast_probe_idx = 0

        self.response_timer = QTimer()
        self.response_timer.timeout.connect(self._check_timeouts)

        self.log_show_send = True
        self.log_show_recv = True
        self.log_auto_scroll = True
        self.max_log_lines = 2000

        self._init_ui()
        self.setStyleSheet(expand_qss(DARK_STYLE))

        self.driver.connected.connect(self._on_connected)
        self.driver.disconnected.connect(self._on_disconnected)
        self.driver.frame_received.connect(self._on_frame_received)
        self.driver.frame_sent.connect(self._on_frame_sent)
        self.driver.error_occurred.connect(self._on_error)
        self.driver.log_message.connect(self._on_log)

        self.response_timer.start(2000)

        self.current_module_addr = 1

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        title_label = QLabel("联明电源 CAN通讯控制上位机 v1.0 (UT-6502 以太网-CAN)")
        title_label.setObjectName("title")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # 顶行：连接配置整行（IP/端口/连接/断开/自动轮询/间隔）
        conn_row = self._create_connection_panel()
        main_layout.addWidget(conn_row)

        # 第二行：批量操作（左）+ 扫描等功能按钮（右上角，与其他上位机一致）
        batch_row = self._create_batch_panel()
        main_layout.addWidget(batch_row)

        center_splitter = QSplitter(Qt.Horizontal)

        table_group = self._create_table_panel()
        right_group = self._create_right_panel()
        center_splitter.addWidget(table_group)
        center_splitter.addWidget(right_group)
        center_splitter.setStretchFactor(0, 3)
        center_splitter.setStretchFactor(1, 1)
        center_splitter.setSizes([850, 350])
        main_layout.addWidget(center_splitter, stretch=1)

        log_group = self._create_log_panel()
        main_layout.addWidget(log_group)

    def _create_connection_panel(self):
        """连接配置：界面顶上一行（IP/端口/连接/断开/自动轮询/间隔）。"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        title = QLabel("连接配置")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        layout.addWidget(QLabel("UT-6502 IP:"))
        self.ip_input = QLineEdit("192.168.1.125")
        self.ip_input.setFixedWidth(140)
        layout.addWidget(self.ip_input)

        layout.addWidget(QLabel("端口:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(5001)
        self.port_input.setFixedWidth(84)
        layout.addWidget(self.port_input)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setObjectName("btnDisconnect")
        self.btn_disconnect.setEnabled(False)
        layout.addWidget(self.btn_connect)
        layout.addWidget(self.btn_disconnect)

        self.chk_poll = QCheckBox("自动轮询在线模块")
        self.chk_poll.setChecked(False)
        layout.addWidget(self.chk_poll)

        layout.addWidget(QLabel("间隔(ms):"))
        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(100, 60000)
        self.poll_interval.setValue(1000)
        self.poll_interval.setSingleStep(100)
        self.poll_interval.setFixedWidth(88)
        layout.addWidget(self.poll_interval)
        layout.addStretch(1)

        self.btn_connect.clicked.connect(self._do_connect)
        self.btn_disconnect.clicked.connect(self._do_disconnect)
        self.chk_poll.toggled.connect(self._on_poll_toggled)

        return row

    def _create_batch_panel(self):
        """批量操作一行（左）+ 一键初始化/扫描在线模块/故障代码查询（右上角）。"""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        self.btn_all_on = QPushButton("全部开机")
        self.btn_all_on.setObjectName("btnBatchOn")
        self.btn_all_off = QPushButton("全部关机")
        self.btn_all_off.setObjectName("btnBatchOff")
        layout.addWidget(self.btn_all_on)
        layout.addWidget(self.btn_all_off)

        layout.addWidget(QLabel("批量电压(V):"))
        self.batch_voltage = QDoubleSpinBox()
        self.batch_voltage.setRange(0, 1000)
        self.batch_voltage.setDecimals(1)
        self.batch_voltage.setValue(50.0)
        self.batch_voltage.setFixedWidth(96)
        layout.addWidget(self.batch_voltage)

        layout.addWidget(QLabel("批量电流(A):"))
        self.batch_current = QDoubleSpinBox()
        self.batch_current.setRange(0, 1000)
        self.batch_current.setDecimals(1)
        self.batch_current.setValue(50.0)
        self.batch_current.setFixedWidth(96)
        layout.addWidget(self.batch_current)

        self.btn_batch_set = QPushButton("批量设置电压电流")
        self.btn_batch_set.setObjectName("btnBatchSet")
        layout.addWidget(self.btn_batch_set)
        layout.addStretch(1)

        # 右上角功能按钮（扫描在线模块等功能，与其他上位机一致）
        self.btn_init = QPushButton("一键初始化")
        self.btn_init.setObjectName("btnInit")
        self.btn_scan = QPushButton("扫描在线模块")
        self.btn_scan.setObjectName("btnScan")
        self.btn_fault_codes = QPushButton("故障代码查询")
        self.btn_fault_codes.clicked.connect(self._on_show_fault_codes)
        layout.addWidget(self.btn_init)
        layout.addWidget(self.btn_scan)
        layout.addWidget(self.btn_fault_codes)

        self.btn_all_on.clicked.connect(lambda: self._batch_power(True))
        self.btn_all_off.clicked.connect(lambda: self._batch_power(False))
        self.btn_batch_set.clicked.connect(self._batch_set_vi)
        self.btn_init.clicked.connect(self._init_all)
        self.btn_scan.clicked.connect(self._scan_modules)

        return row

    def _create_table_panel(self):
        group = QGroupBox("模块实时监控")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        self.lbl_range = QLabel(f"地址 0x01~0x{NUM_MODULES:02X}")
        self.lbl_current = QLabel("当前模块: ---")
        self.lbl_selected = QLabel("已选: 0")
        header_layout.addWidget(self.lbl_range)
        header_layout.addStretch()
        header_layout.addWidget(self.lbl_current)
        header_layout.addWidget(QLabel("  "))
        header_layout.addWidget(self.lbl_selected)
        layout.addLayout(header_layout)

        btn_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_clear_sel = QPushButton("清空")
        self.btn_online_only = QPushButton("仅在线")
        self.btn_sel_on = QPushButton("选中开机")
        self.btn_sel_off = QPushButton("选中关机")
        self.btn_sel_set = QPushButton("选中设置V/I")
        btn_layout.addWidget(self.btn_select_all)
        btn_layout.addWidget(self.btn_clear_sel)
        btn_layout.addWidget(self.btn_online_only)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_sel_on)
        btn_layout.addWidget(self.btn_sel_off)
        btn_layout.addWidget(self.btn_sel_set)
        layout.addLayout(btn_layout)

        self.table = QTableWidget(NUM_MODULES, len(COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for i, w in enumerate(COLUMN_WIDTHS):
            self.table.setColumnWidth(i, w)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)

        vheader = self.table.verticalHeader()
        vheader.setDefaultSectionSize(26)
        vheader.setMinimumSectionSize(20)

        delegate = CenterAlignDelegate(self.table)
        for i in range(len(COLUMN_HEADERS)):
            self.table.setItemDelegateForColumn(i, delegate)

        self.table.cellClicked.connect(self._on_table_click)

        self._populate_table()

        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        self.btn_online_only.clicked.connect(self._select_online_only)
        self.btn_sel_on.clicked.connect(lambda: self._selected_power(True))
        self.btn_sel_off.clicked.connect(lambda: self._selected_power(False))
        self.btn_sel_set.clicked.connect(self._selected_set_vi)

        table_container = QWidget()
        table_layout = QHBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.table)
        layout.addWidget(table_container)

        return group

    def _populate_table(self):
        self._sv_spins = {}
        self._si_spins = {}
        for row in range(NUM_MODULES):
            addr = row + 1

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Unchecked)
            chk_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, COL_CHECK, chk_item)

            addr_item = QTableWidgetItem(f"0x{addr:02X}")
            self.table.setItem(row, COL_ADDR, addr_item)

            self.table.setItem(row, COL_ONLINE, QTableWidgetItem("○离线"))
            self.table.setItem(row, COL_POWER, QTableWidgetItem("○关机"))
            for col in [COL_VOLTAGE, COL_CURRENT, COL_BUS_VOLT]:
                self.table.setItem(row, col, QTableWidgetItem("---"))
            self.table.setItem(row, COL_MODE, QTableWidgetItem("---"))
            self.table.setItem(row, COL_FAULT, QTableWidgetItem("---"))

            # 设置电压/电流：行内可编辑输入框
            sv = QDoubleSpinBox()
            sv.setRange(0, 1200)
            sv.setDecimals(1)
            sv.setSingleStep(0.5)
            sv.setMinimumWidth(70)
            sv.valueChanged.connect(lambda _v, w=sv: setattr(w, "_user_edited", True))
            self.table.setCellWidget(row, COL_SET_VOLT, sv)
            self._sv_spins[addr] = sv

            si = QDoubleSpinBox()
            si.setRange(0, 300)
            si.setDecimals(1)
            si.setSingleStep(0.5)
            si.setMinimumWidth(70)
            si.valueChanged.connect(lambda _v, w=si: setattr(w, "_user_edited", True))
            self.table.setCellWidget(row, COL_SET_CURR, si)
            self._si_spins[addr] = si

            btn_on = QPushButton("开")
            btn_on.setObjectName("btnOn")
            btn_off = QPushButton("关")
            btn_off.setObjectName("btnOff")
            btn_set = QPushButton("设置")
            btn_set.setObjectName("btnSet")

            btn_on.clicked.connect(lambda _, a=addr: self._module_power(a, True))
            btn_off.clicked.connect(lambda _, a=addr: self._module_power(a, False))
            btn_set.clicked.connect(lambda _, a=addr: self._row_set_vi(a))

            self.table.setCellWidget(row, COL_BTN_ON, btn_on)
            self.table.setCellWidget(row, COL_BTN_OFF, btn_off)
            self.table.setCellWidget(row, COL_BTN_SET, btn_set)

            self._update_row_colors(row)

    def _row_set_vi(self, addr):
        """行内设置按钮：读取该行输入的电压电流并下发"""
        v = self._sv_spins[addr].value()
        i = self._si_spins[addr].value()
        self._module_set_vi_value(addr, v, i)

    def _update_row_colors(self, row):
        addr = row + 1
        mod = self.modules[addr]

        online_item = self.table.item(row, COL_ONLINE)
        online_item.setTextAlignment(Qt.AlignCenter)
        online_item.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        if mod.online:
            online_item.setText("● 在线")
            online_item.setForeground(QBrush(QColor("#047857")))
        else:
            online_item.setText("○离线")
            online_item.setForeground(STYLE_OFFLINE)

        power_item = self.table.item(row, COL_POWER)
        if mod.online and mod.power_on:
            power_item.setText("●开机")
            power_item.setForeground(STYLE_POWER_ON)
        else:
            power_item.setText("○关机")
            power_item.setForeground(STYLE_POWER_OFF)

        for col, val in [
            (COL_VOLTAGE, mod.output_voltage),
            (COL_CURRENT, mod.output_current),
            (COL_BUS_VOLT, mod.bus_voltage),
        ]:
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            if mod.online:
                item.setText(f"{val:.1f}")
            else:
                item.setText("---")

        # 设置电压/电流回填行内输入框（编辑中不覆盖）
        spins_v = getattr(self, "_sv_spins", {})
        spins_i = getattr(self, "_si_spins", {})
        sv_w = spins_v.get(addr)
        if (sv_w is not None and mod.online and not sv_w.hasFocus()
                and not getattr(sv_w, "_user_edited", False)):
            sv_w.blockSignals(True)
            sv_w.setValue(mod.set_voltage)
            sv_w.blockSignals(False)
        si_w = spins_i.get(addr)
        if (si_w is not None and mod.online and not si_w.hasFocus()
                and not getattr(si_w, "_user_edited", False)):
            si_w.blockSignals(True)
            si_w.setValue(mod.set_current)
            si_w.blockSignals(False)

        mode_item = self.table.item(row, COL_MODE)
        if mod.online:
            mode_item.setText(mod.mode)
        else:
            mode_item.setText("---")

        fault_item = self.table.item(row, COL_FAULT)
        if mod.online:
            fault_item.setText(mod.fault)
            if mod.has_fault:
                fault_item.setForeground(STYLE_FAULT)
            else:
                fault_item.setForeground(STYLE_NORMAL)
        else:
            fault_item.setText("---")
            fault_item.setForeground(STYLE_OFFLINE)

    def _update_all_rows(self):
        for row in range(NUM_MODULES):
            self._update_row_colors(row)

    def _on_table_click(self, row, col):
        # 模块地址选中固定在勾选列（选择区域），其余列点击不可选中（规范）
        if col != COL_CHECK:
            return
        addr = row + 1
        self.current_module_addr = addr
        self.lbl_current.setText(f"当前模块: 0x{addr:02X} ({addr}#)")
        self._update_selected_count()
        # 选中即用该模块的最近一次数据刷新实时面板（不必等下一轮轮询）
        if addr in self.modules:
            self._update_realtime_display(self.modules[addr])

    def _update_selected_count(self):
        count = 0
        for row in range(NUM_MODULES):
            item = self.table.item(row, COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                count += 1
        self.lbl_selected.setText(f"已选: {count}")

    def _create_right_panel(self):
        group = QGroupBox()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.tab_widget = QTabWidget()
        tab_control = self._create_module_control_tab()
        tab_id = self._create_id_management_tab()
        self.tab_widget.addTab(tab_control, "模块控制")
        self.tab_widget.addTab(tab_id, "ID 管理")
        layout.addWidget(self.tab_widget)

        return group

    def _create_module_control_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("模块地址:"), 0, 0)
        self.ctrl_addr = QSpinBox()
        self.ctrl_addr.setRange(1, NUM_MODULES)
        self.ctrl_addr.setValue(1)
        layout.addWidget(self.ctrl_addr, 0, 1)

        read_btn = QPushButton("读取状态")
        layout.addWidget(read_btn, 0, 2)
        read_btn.clicked.connect(lambda: self._read_full_status(self.ctrl_addr.value()))

        layout.addWidget(QLabel("设置电压(V):"), 1, 0)
        self.ctrl_voltage = QDoubleSpinBox()
        self.ctrl_voltage.setRange(0, 1000)
        self.ctrl_voltage.setDecimals(1)
        self.ctrl_voltage.setValue(50.0)
        layout.addWidget(self.ctrl_voltage, 1, 1, 1, 2)

        layout.addWidget(QLabel("设置电流(A):"), 2, 0)
        self.ctrl_current = QDoubleSpinBox()
        self.ctrl_current.setRange(0, 1000)
        self.ctrl_current.setDecimals(1)
        self.ctrl_current.setValue(50.0)
        layout.addWidget(self.ctrl_current, 2, 1, 1, 2)

        set_btn = QPushButton("设置电压电流")
        set_btn.setObjectName("btnSet")
        layout.addWidget(set_btn, 3, 0, 1, 3)
        set_btn.clicked.connect(lambda: self._module_set_vi_value(
            self.ctrl_addr.value(),
            self.ctrl_voltage.value(),
            self.ctrl_current.value()
        ))

        btn_layout = QHBoxLayout()
        on_btn = QPushButton("开机")
        on_btn.setObjectName("btnOn")
        off_btn = QPushButton("关机")
        off_btn.setObjectName("btnOff")
        btn_layout.addWidget(on_btn)
        btn_layout.addWidget(off_btn)
        layout.addLayout(btn_layout, 4, 0, 1, 3)
        on_btn.clicked.connect(lambda: self._module_power(self.ctrl_addr.value(), True))
        off_btn.clicked.connect(lambda: self._module_power(self.ctrl_addr.value(), False))

        layout.addWidget(QLabel("--- 实时数据 ---"), 5, 0, 1, 3)

        self.lbl_rt_voltage = QLabel("输出电压: --- V")
        self.lbl_rt_current = QLabel("输出电流: --- A")
        self.lbl_rt_bus = QLabel("母线电压: --- V")
        self.lbl_rt_set_v = QLabel("设置电压: --- V")
        self.lbl_rt_set_i = QLabel("设置电流: --- A")
        self.lbl_rt_temp = QLabel("环境温度: --- ℃")
        self.lbl_rt_mode = QLabel("运行模式: ---")
        self.lbl_rt_fault = QLabel("故障状态: ---")

        for i, lbl in enumerate([self.lbl_rt_voltage, self.lbl_rt_current,
                                  self.lbl_rt_bus, self.lbl_rt_set_v,
                                  self.lbl_rt_set_i, self.lbl_rt_temp,
                                  self.lbl_rt_mode, self.lbl_rt_fault]):
            layout.addWidget(lbl, 6 + i, 0, 1, 3)

        layout.setRowStretch(6 + 8, 1)

        return widget

    def _create_id_management_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        info_label = QLabel(
            "模块ID通过生命帧触发\n"
            "示例帧ID格式: 0x18C1FFC1\n\n"
            "当前模块ID信息:"
        )
        layout.addWidget(info_label)

        read_id_btn = QPushButton("读取模块ID")
        read_id_btn.setObjectName("btnSet")
        layout.addWidget(read_id_btn)

        self.lbl_module_id = QLabel("模块ID: ---")
        layout.addWidget(self.lbl_module_id)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        layout.addWidget(QLabel("修改模块ID (0xD9)"))

        mod_layout = QGridLayout()
        mod_layout.addWidget(QLabel("当前模块ID:"), 0, 0)
        self.id_current = QLineEdit()
        self.id_current.setPlaceholderText("0x18C1FFC1")
        mod_layout.addWidget(self.id_current, 0, 1)

        mod_layout.addWidget(QLabel("新模块ID:"), 1, 0)
        self.id_new = QLineEdit()
        self.id_new.setPlaceholderText("0x18C1FFC2")
        mod_layout.addWidget(self.id_new, 1, 1)
        layout.addLayout(mod_layout)

        modify_btn = QPushButton("修改模块ID")
        modify_btn.setObjectName("btnSet")
        layout.addWidget(modify_btn)

        warning = QLabel(
            "⚠ 注意: 修改后模块将以新ID通讯,\n"
            "一次只修改一台模块!"
        )
        warning.setStyleSheet("color: #f9a825; font-size: 12px;")
        layout.addWidget(warning)

        layout.addStretch()

        return widget

    def _create_log_panel(self):
        group = QGroupBox("CAN 报文日志")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(4)

        ctrl_layout = QHBoxLayout()
        self.chk_log_send = QCheckBox("显示发送")
        self.chk_log_recv = QCheckBox("显示接收")
        self.chk_log_scroll = QCheckBox("自动滚动")
        self.chk_log_send.setChecked(True)
        self.chk_log_recv.setChecked(True)
        self.chk_log_scroll.setChecked(True)

        self.chk_log_send.toggled.connect(self._on_log_filter_changed)
        self.chk_log_recv.toggled.connect(self._on_log_filter_changed)
        self.chk_log_scroll.toggled.connect(self._on_log_filter_changed)

        ctrl_layout.addWidget(self.chk_log_send)
        ctrl_layout.addWidget(self.chk_log_recv)
        ctrl_layout.addWidget(self.chk_log_scroll)
        ctrl_layout.addStretch()

        self.lbl_tx_count = QLabel("TX: 0")
        self.lbl_rx_count = QLabel("RX: 0")
        ctrl_layout.addWidget(self.lbl_tx_count)
        ctrl_layout.addWidget(self.lbl_rx_count)

        btn_clear_log = QPushButton("清空日志")
        ctrl_layout.addWidget(btn_clear_log)
        btn_clear_log.clicked.connect(lambda: self.log_text.clear())

        layout.addLayout(ctrl_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)

        self.tx_count = 0
        self.rx_count = 0

        return group

    def _on_log_filter_changed(self):
        self.log_show_send = self.chk_log_send.isChecked()
        self.log_show_recv = self.chk_log_recv.isChecked()
        self.log_auto_scroll = self.chk_log_scroll.isChecked()

    def _append_log(self, msg, is_send=True):
        ts = time.strftime("%H:%M:%S") + f".{int(time.time()*1000)%1000:03d}"
        prefix = "[TX]" if is_send else "[RX]"
        color = "#3730A3" if is_send else "#1B5E20"
        if is_send and not self.log_show_send:
            return
        if not is_send and not self.log_show_recv:
            return
        line = f'<span style="color:{color}">{ts} {prefix}</span> {msg}'
        self.log_text.append(line)
        if self.log_auto_scroll:
            self.log_text.moveCursor(QTextCursor.End)
        doc = self.log_text.document()
        if doc.blockCount() > self.max_log_lines:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.Start)
            cursor.select(QTextCursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _do_connect(self):
        ip = self.ip_input.text().strip()
        port = self.port_input.value()
        self.driver.connect(ip, port)

    def _do_disconnect(self):
        self.driver.disconnect()

    def _on_connected(self):
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("已连接")
        self.btn_connect.setObjectName("btnConnected")
        self.btn_disconnect.setEnabled(True)
        self.ip_input.setEnabled(False)
        self.port_input.setEnabled(False)

    def _on_disconnected(self):
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_disconnect.setEnabled(False)
        self.ip_input.setEnabled(True)
        self.port_input.setEnabled(True)
        if self.poll_timer.isActive():
            self.poll_timer.stop()
        if self.fast_timer.isActive():
            self.fast_timer.stop()
        self._scan_cancelled = True
        self.btn_scan.setText("扫描在线模块")
        self.chk_poll.setChecked(False)
        for mod in self.modules.values():
            mod.reset_offline()
        self._update_all_rows()

    def _on_error(self, msg):
        QMessageBox.warning(self, "错误", msg)

    def _on_log(self, msg, is_error):
        self._append_log(msg, is_send=not is_error)

    def _on_frame_sent(self, can_id, data):
        self.tx_count += 1
        self.lbl_tx_count.setText(f"TX: {self.tx_count}")
        id_str = cp.format_can_id(can_id)
        data_str = cp.format_data_hex(data) if data else "(空)"
        self._append_log(f"ID={id_str} Data={data_str}", is_send=True)

    def _on_frame_received(self, can_id, data, remote):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到设备 CAN 帧 = 通讯真正建立
        self.rx_count += 1
        self.lbl_rx_count.setText(f"RX: {self.rx_count}")
        id_str = cp.format_can_id(can_id)
        data_str = cp.format_data_hex(data) if data else "(空)"
        rmt = " [RTR]" if remote else ""
        self._append_log(f"ID={id_str} Data={data_str}{rmt}", is_send=False)
        self._process_response(can_id, data)

    def _process_response(self, can_id, data):
        resp_type = cp.get_response_type(can_id)
        if resp_type is None:
            return

        addr = cp.extract_addr(can_id)
        if addr < 1 or addr > NUM_MODULES:
            return

        mod = self.modules[addr]
        mod.online = True
        mod.last_seen = time.time()

        row = addr - 1

        if resp_type == "status":
            if len(data) >= 8 and data[0] == cp.CMD_READ_STATUS:
                result = cp.parse_status_response(data)
                if result:
                    mod.output_voltage = result['output_voltage']
                    mod.output_current = result['output_current']
                    mod.mode = result['mode']
                    mod.power_on = result['power_on']
                    mod.fault = result['fault']
                    mod.has_fault = result['has_fault']
                    mod.status_hi = result['status_hi']
                    mod.status_lo = result['status_lo']
                    self._update_row_colors(row)
                    if addr == self.current_module_addr:
                        self._update_realtime_display(mod)
            elif len(data) >= 8 and data[0] == cp.CMD_SET_OUTPUT:
                pass
            elif len(data) >= 8 and data[0] == cp.CMD_SET_POWER:
                pass

        elif resp_type == "set_voltage":
            v = cp.parse_set_voltage_response(data)
            if v is not None:
                mod.set_voltage = v
                self._update_row_colors(row)
                if addr == self.current_module_addr:
                    self.lbl_rt_set_v.setText(f"设置电压: {v:.1f} V")

        elif resp_type == "set_current":
            i = cp.parse_set_current_response(data)
            if i is not None:
                mod.set_current = i
                self._update_row_colors(row)
                if addr == self.current_module_addr:
                    self.lbl_rt_set_i.setText(f"设置电流: {i:.1f} A")

        elif resp_type == "input_voltage":
            result = cp.parse_input_voltage_response(data)
            if result:
                mod.bus_voltage = result['avg']
                self._update_row_colors(row)
                if addr == self.current_module_addr:
                    self.lbl_rt_bus.setText(
                        f"母线电压: {result['avg']:.1f} V "
                        f"(Vab={result['vab']:.1f} Vbc={result['vbc']:.1f} Vca={result['vca']:.1f})"
                    )

        elif resp_type == "temperature":
            t = cp.parse_temperature_response(data)
            if t is not None and addr == self.current_module_addr:
                self.lbl_rt_temp.setText(f"环境温度: {t:.1f} ℃")

        elif resp_type == "current_share":
            pass

    def _update_realtime_display(self, mod):
        self.lbl_rt_voltage.setText(f"输出电压: {mod.output_voltage:.1f} V")
        self.lbl_rt_current.setText(f"输出电流: {mod.output_current:.1f} A")
        self.lbl_rt_set_v.setText(f"设置电压: {mod.set_voltage:.1f} V")
        self.lbl_rt_set_i.setText(f"设置电流: {mod.set_current:.1f} A")
        self.lbl_rt_mode.setText(f"运行模式: {mod.mode}")
        fault_color = "#f87171" if mod.has_fault else "#4ade80"
        self.lbl_rt_fault.setText(f"故障状态: {mod.fault}")
        self.lbl_rt_fault.setStyleSheet(f"color: {fault_color};")

    def _read_full_status(self, addr):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return

        can_id, data = cp.build_read_status(addr)
        self.driver.send_command(can_id, data)

        QTimer.singleShot(50, lambda: self._send_read_set_v(addr))
        QTimer.singleShot(100, lambda: self._send_read_set_i(addr))
        QTimer.singleShot(150, lambda: self._send_read_input_v(addr))
        QTimer.singleShot(200, lambda: self._send_read_temp(addr))

    def _send_read_set_v(self, addr):
        can_id, data = cp.build_read_set_voltage(addr)
        self.driver.send_command(can_id, data)

    def _send_read_set_i(self, addr):
        can_id, data = cp.build_read_set_current(addr)
        self.driver.send_command(can_id, data)

    def _send_read_input_v(self, addr):
        can_id, data = cp.build_read_input_voltage(addr)
        self.driver.send_command(can_id, data)

    def _send_read_temp(self, addr):
        can_id, data = cp.build_read_temperature(addr)
        self.driver.send_command(can_id, data)

    def _on_poll_toggled(self, checked):
        if checked:
            if not self.driver.is_connected:
                self.chk_poll.setChecked(False)
                QMessageBox.warning(self, "提示", "请先连接UT-6502")
                return
            interval = self.poll_interval.value()
            self.poll_timer.start(interval)
            self.fast_timer.start(300)
        else:
            self.poll_timer.stop()
            self.fast_timer.stop()

    def _fast_refresh(self):
        if not self.driver.is_connected:
            self.fast_timer.stop()
            return

        online_addrs = [a for a, m in self.modules.items() if m.online]

        if not online_addrs:
            probe_addr = self.fast_probe_idx + 1
            if probe_addr > NUM_MODULES:
                self.fast_probe_idx = 0
                probe_addr = 1
            can_id, data = cp.build_read_status(probe_addr)
            self.driver.send_command(can_id, data)
            self.fast_probe_idx += 1
            return

        if self.fast_index >= len(online_addrs):
            self.fast_index = 0

        addr = online_addrs[self.fast_index]
        can_id, data = cp.build_read_status(addr)
        self.driver.send_command(can_id, data)
        # 注意：轮询只刷新各自行数据，不得改写 current_module_addr/「当前模块」——
        # 选中由用户点击决定；改写会让实时数据跟着轮询在多台模块间乱跳（2026-11-11 用户报）
        self.fast_index += 1

    def _poll_next(self):
        if not self.driver.is_connected:
            self.poll_timer.stop()
            self.chk_poll.setChecked(False)
            return

        online_addrs = [a for a, m in self.modules.items() if m.online]

        if not online_addrs:
            return

        if self.poll_index >= len(online_addrs):
            self.poll_index = 0
            self.poll_sub_step = 0

        addr = online_addrs[self.poll_index]
        step = self.poll_sub_step

        if step == 0:
            can_id, data = cp.build_read_set_voltage(addr)
        elif step == 1:
            can_id, data = cp.build_read_set_current(addr)
        elif step == 2:
            can_id, data = cp.build_read_input_voltage(addr)
        elif step == 3:
            can_id, data = cp.build_read_temperature(addr)
        else:
            can_id, data = cp.build_read_set_voltage(addr)

        self.driver.send_command(can_id, data)

        self.poll_sub_step += 1
        if self.poll_sub_step >= self.POLL_STEPS:
            self.poll_sub_step = 0
            self.poll_index += 1

    def _check_timeouts(self):
        now = time.time()
        changed = False
        for addr, mod in self.modules.items():
            if mod.online and (now - mod.last_seen) > 5.0:
                mod.reset_offline()
                changed = True
        if changed:
            self._update_all_rows()
        # 通讯状态：全部模块离线 = 通讯中断，右上角指示灯回灰
        if self.driver.is_connected and not any(m.online for m in self.modules.values()):
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)

    def _module_power(self, addr, power_on):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        if power_on and not self._confirm_power_on([addr], False, "确认开机"):
            return
        can_id, data = cp.build_set_power(addr, power_on)
        self.driver.send_command(can_id, data)

    def _module_set_vi(self, addr):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        v = self.batch_voltage.value()
        i = self.batch_current.value()
        can_id, data = cp.build_set_output(addr, v, i)
        self.driver.send_command(can_id, data)
        mod = self.modules.get(addr)
        if mod:
            mod.set_voltage = v
            mod.set_current = i
            self._update_row_colors(addr - 1)
            if addr == self.current_module_addr:
                self.lbl_rt_set_v.setText(f"设置电压: {v:.1f} V")
                self.lbl_rt_set_i.setText(f"设置电流: {i:.1f} A")

    def _module_set_vi_value(self, addr, v, i):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        can_id, data = cp.build_set_output(addr, v, i)
        self.driver.send_command(can_id, data)
        mod = self.modules.get(addr)
        if mod:
            mod.set_voltage = v
            mod.set_current = i
            self._update_row_colors(addr - 1)
            if addr == self.current_module_addr:
                self.lbl_rt_set_v.setText(f"设置电压: {v:.1f} V")
                self.lbl_rt_set_i.setText(f"设置电流: {i:.1f} A")

    def _confirm_power_on(self, addrs, broadcast=False, title="确认开机"):
        """开机二次确认, 弹窗列出目标模块"""
        if broadcast:
            addr_txt = "全部模块(广播)"
        elif not addrs:
            QMessageBox.information(self, "提示", "请先选择模块")
            return False
        elif len(addrs) > 30:
            addr_txt = ", ".join(f"0x{a:02X}" for a in addrs[:30]) + f" … 共 {len(addrs)} 台"
        else:
            addr_txt = ", ".join(f"0x{a:02X}" for a in addrs)
        return QMessageBox.question(
            self, title,
            f"将对以下模块执行开机：\n\n{addr_txt}\n\n确认继续?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def _on_show_fault_codes(self):
        """显示 LM-CAN 模块状态字/故障位说明"""
        lines = ["LM-CAN 模块状态字与故障位定义", ""]
        lines.append("状态低字节 status_lo:")
        for mask, name in [(0x01, "关机状态"), (0x02, "模块故障"), (0x04, "恒流模式"),
                           (0x08, "风扇故障"), (0x10, "输入过压"), (0x20, "输入欠压"),
                           (0x40, "输出过压"), (0x80, "输出欠压")]:
            lines.append(f"  bit(mask 0x{mask:02X}): {name}")
        lines.append("")
        lines.append("状态高字节 status_hi:")
        for mask, name in [(0x01, "过流保护"), (0x02, "过温保护"), (0x04, "关机状态")]:
            lines.append(f"  bit(mask 0x{mask:02X}): {name}")
        lines += ["", "说明：对应位置 1 表示该故障/状态。"]
        QMessageBox.information(self, "故障代码查询", "\n".join(lines))

    def _batch_power(self, power_on):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        if power_on and not self._confirm_power_on(None, True, "确认全部开机"):
            return
        can_id, data = cp.build_set_power(0, power_on)
        self.driver.send_command(can_id, data)

    def _batch_set_vi(self):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        v = self.batch_voltage.value()
        i = self.batch_current.value()
        can_id, data = cp.build_set_output(0, v, i)
        self.driver.send_command(can_id, data)
        for addr, mod in self.modules.items():
            if mod.online:
                mod.set_voltage = v
                mod.set_current = i
        self._update_all_rows()
        if self.current_module_addr in self.modules:
            mod = self.modules[self.current_module_addr]
            self.lbl_rt_set_v.setText(f"设置电压: {mod.set_voltage:.1f} V")
            self.lbl_rt_set_i.setText(f"设置电流: {mod.set_current:.1f} A")

    def _init_all(self):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        reply = QMessageBox.question(
            self, "确认", "确定要一键初始化所有模块吗?\n(关机 → 设置0V/0A)")
        if reply != QMessageBox.Yes:
            return
        can_id, data = cp.build_set_power(0, False)
        self.driver.send_command(can_id, data)
        QTimer.singleShot(100, lambda: self._init_set_vi())

    def _init_set_vi(self):
        can_id, data = cp.build_set_output(0, 0.0, 0.0)
        self.driver.send_command(can_id, data)
        for addr, mod in self.modules.items():
            if mod.online:
                mod.set_voltage = 0.0
                mod.set_current = 0.0
        self._update_all_rows()

    def _scan_modules(self):
        """扫描在线模块; 扫描中再点此按钮=中断扫描"""
        if getattr(self, "_scan_busy", False):
            self._scan_cancelled = True
            self._scan_finish()
            self._append_log("已中断扫描", is_send=False)
            return
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        for mod in self.modules.values():
            mod.reset_offline()
        self._update_all_rows()
        self._scan_busy = True
        self._scan_cancelled = False
        self.btn_scan.setText("停止扫描")
        self._append_log("开始扫描在线模块...", is_send=True)
        self._scan_addrs = list(range(1, NUM_MODULES + 1))
        self._scan_index = 0
        if not hasattr(self, "_scan_timer"):
            self._scan_timer = QTimer(self)
            self._scan_timer.timeout.connect(self._scan_tick)
        self._scan_timer.start(30)

    def _scan_tick(self):
        """逐地址发一帧, 帧间隔 30ms, 可中断"""
        if self._scan_cancelled or not self.driver.is_connected:
            self._scan_timer.stop()
            self._scan_finish()
            return
        if self._scan_index >= len(self._scan_addrs):
            self._scan_timer.stop()
            self._scan_finish()
            return
        addr = self._scan_addrs[self._scan_index]
        self._scan_index += 1
        can_id, data = cp.build_read_status(addr)
        self.driver.send_command(can_id, data)

    def _scan_finish(self):
        self._scan_busy = False
        self.btn_scan.setText("扫描在线模块")
        QTimer.singleShot(2000, self._scan_summary)

    def _scan_summary(self):
        online_list = [a for a, m in self.modules.items() if m.online]
        self._update_all_rows()
        if online_list:
            addrs = ", ".join(f"0x{a:02X}" for a in online_list)
            self._append_log(f"扫描完成: 在线模块 {len(online_list)} 台: {addrs}", is_send=True)
        else:
            self._append_log("扫描完成: 未发现在线模块", is_send=True)

    def _select_all(self):
        for row in range(NUM_MODULES):
            item = self.table.item(row, COL_CHECK)
            if item:
                item.setCheckState(Qt.Checked)
        self._update_selected_count()

    def _clear_selection(self):
        for row in range(NUM_MODULES):
            item = self.table.item(row, COL_CHECK)
            if item:
                item.setCheckState(Qt.Unchecked)
        self._update_selected_count()

    def _select_online_only(self):
        for row in range(NUM_MODULES):
            item = self.table.item(row, COL_CHECK)
            mod = self.modules[row + 1]
            if item:
                item.setCheckState(Qt.Checked if mod.online else Qt.Unchecked)
        self._update_selected_count()

    def _get_selected_addrs(self):
        addrs = []
        for row in range(NUM_MODULES):
            item = self.table.item(row, COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                addrs.append(row + 1)
        return addrs

    def _selected_power(self, power_on):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        addrs = self._get_selected_addrs()
        if not addrs:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        if power_on and not self._confirm_power_on(addrs, False, "确认选中开机"):
            return
        for addr in addrs:
            can_id, data = cp.build_set_power(addr, power_on)
            self.driver.send_command(can_id, data)

    def _selected_set_vi(self):
        if not self.driver.is_connected:
            QMessageBox.warning(self, "提示", "请先连接UT-6502")
            return
        addrs = self._get_selected_addrs()
        if not addrs:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        v = self.batch_voltage.value()
        i = self.batch_current.value()
        for addr in addrs:
            can_id, data = cp.build_set_output(addr, v, i)
            self.driver.send_command(can_id, data)
            mod = self.modules.get(addr)
            if mod:
                mod.set_voltage = v
                mod.set_current = i
                self._update_row_colors(addr - 1)
        if self.current_module_addr in self.modules:
            mod = self.modules[self.current_module_addr]
            self.lbl_rt_set_v.setText(f"设置电压: {mod.set_voltage:.1f} V")
            self.lbl_rt_set_i.setText(f"设置电流: {mod.set_current:.1f} A")

    def closeEvent(self, event):
        try:
            if self.poll_timer.isActive():
                self.poll_timer.stop()
            if self.fast_timer.isActive():
                self.fast_timer.stop()
            if self.response_timer.isActive():
                self.response_timer.stop()
            if self.driver.is_connected:
                self.driver.disconnect()
            event.accept()
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass


