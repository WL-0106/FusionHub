"""
EN+ 充电模块上位机软件 V2.0 - 主界面
基于 PyQt5, 通过 UT-6502 CAN-Ethernet 转换器与 EN+ 充电模块通信

V2.0 新特性:
  - 多模块实时监控表格 (地址 0x01~0x3F 全部显示)
  - 每个模块独立开关机控制 (表格内嵌按钮)
  - 选中模块独立设置电压电流
  - 批量操作 (全部开机/关机/设置电压电流)
  - 自动轮询在线模块地址
"""

import time
from datetime import datetime

from modules.theme_util import expand_qss
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox,
    QDoubleSpinBox, QTextEdit, QCheckBox, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QMessageBox, QTabWidget, QAbstractItemView,
    QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QItemSelectionModel
from PyQt5.QtGui import QTextCursor, QColor, QBrush, QFont

from . import can_protocol as cp
from .ut6502_driver import UT6502Driver
from .zlg_usbcan import ZLGUsbCanDriver


# ============================================================
# 样式表
# ============================================================

STYLE_SHEET = """
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


# ============================================================
# 模块数据存储
# ============================================================

class ModuleData:
    """单个模块的实时数据"""
    def __init__(self, addr):
        self.addr = addr
        self.online = False
        self.last_seen = 0  # timestamp of last response
        self.voltage = 0.0
        self.current = 0.0
        self.temperature = 0
        self.fan_speed = 0
        self.fault_code = 0
        self.state1 = -1  # -1=未知
        self.state2 = 0
        self.uab = 0.0
        self.ubc = 0.0
        self.uca = 0.0
        self.power_on = None  # None=未知, True=开机, False=关机
        self.set_voltage = 500.0  # 用户设定的电压
        self.set_current = 50.0   # 用户设定的电流
        self.set_voltage_actual = 0.0  # 模块返回的实际设定电压
        self.set_current_actual = 0.0  # 模块返回的实际设定电流
        self.model_name = ""           # 型号名称
        self.sn = ""                   # 序列号
        self.sw_version = ""           # 软件版本号


# ============================================================
# CAN 接收线程
# ============================================================

class CanReceiver(QThread):
    message_received = pyqtSignal(int, bytes, bool, bool, int)

    def __init__(self, driver):
        super().__init__()
        self.driver = driver
        self._running = True

    def run(self):
        while self._running:
            msg = self.driver.get_rx_message()
            if msg:
                can_id, can_data, is_ext, is_rtr, dlc = msg
                self.message_received.emit(can_id, can_data, is_ext, is_rtr, dlc)
            else:
                self.msleep(10)

    def stop(self):
        self._running = False


# ============================================================
# 主窗口
# ============================================================

class MainWindow(QMainWindow):
    MAX_MODULES = 63  # 0x01 ~ 0x3F

    # 表格列定义（勾选列在地址左侧）
    COL_CHECK = 0
    COL_ADDR = 1
    COL_ONLINE = 2
    COL_STATE = 3
    COL_VOLTAGE = 4
    COL_CURRENT = 5
    COL_SET_VOLTAGE = 6
    COL_SET_CURRENT = 7
    COL_TEMP = 8
    COL_FAN = 9
    COL_FAULT = 10
    COL_POWER = 11
    COL_BTN_ON = 12
    COL_BTN_OFF = 13
    COL_BTN_VI = 14
    COL_COUNT = 15

    def __init__(self):
        super().__init__()
        self.driver = UT6502Driver()
        self.driver.add_rx_callback(self._on_rx_callback)
        self.recv_thread = None
        self._scan_busy = False
        self._scan_cancelled = False

        # 模块数据
        self.modules = {addr: ModuleData(addr) for addr in range(1, 64)}

        # 轮询
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_tick)
        self._poll_addr_idx = 0  # 当前轮询的模块索引 (0~62)
        self._poll_cmd_idx = 0   # 当前轮询的命令索引 (0~2)

        # 选中模块快速轮询 (实时读取电压/电流/温度/风扇)
        self.single_poll_timer = QTimer()
        self.single_poll_timer.timeout.connect(self._single_poll_tick)
        self._single_poll_cmd = 0  # 0=读V/I, 1=读温度风扇

        # 当前选中模块
        self._selected_addr = 1

        # 批量设置值
        self._batch_voltage = 500.0
        self._batch_current = 50.0

        self.init_ui()
        self.apply_style()
        self.update_connection_state(False)

    # ============================================================
    # UI 构建
    # ============================================================

    def init_ui(self):
        self.setWindowTitle("EN+ 充电模块上位机软件 V2.0  (UT-6502 CAN-Ethernet)")
        self.resize(1400, 900)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # 顶部连接栏
        main_layout.addWidget(self._create_connection_bar())

        # 批量操作栏
        main_layout.addWidget(self._create_batch_bar())

        # 主体: 左右分割
        splitter = QSplitter(Qt.Horizontal)

        # 左侧: 模块监控表格
        left = self._create_monitor_table()
        splitter.addWidget(left)

        # 右侧: 控制面板 (Tab)
        right = self._create_right_panel()
        splitter.addWidget(right)

        splitter.setSizes([900, 460])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        main_layout.addWidget(splitter, 1)

        # 底部日志
        main_layout.addWidget(self._create_log_panel(), 0)

    def _create_connection_bar(self):
        group = QGroupBox("连接配置")
        layout = QHBoxLayout(group)
        layout.setSpacing(8)

        layout.addWidget(QLabel("CAN盒:"))
        self.can_box_combo = QComboBox()
        self.can_box_combo.addItems(["UT-6502 (以太网)", "ZLG USB CAN 盒 (2E-U / CANalyst-II+)"])
        self.can_box_combo.setFixedWidth(170)
        self.can_box_combo.currentIndexChanged.connect(self._on_can_box_changed)
        layout.addWidget(self.can_box_combo)

        # UT-6502 参数
        self.lbl_ip = QLabel("UT-6502 IP:")
        layout.addWidget(self.lbl_ip)
        self.ip_edit = QLineEdit("192.168.1.125")
        self.ip_edit.setFixedWidth(130)
        layout.addWidget(self.ip_edit)

        self.lbl_port = QLabel("端口:")
        layout.addWidget(self.lbl_port)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5001)
        self.port_spin.setFixedWidth(65)
        layout.addWidget(self.port_spin)

        # ZLG USBCAN-2E-U 参数
        self.lbl_dev = QLabel("设备:")
        self.lbl_dev.setVisible(False)
        layout.addWidget(self.lbl_dev)
        self.dev_combo = QComboBox()
        self.dev_combo.addItems(["设备0 (第1块卡)", "设备1 (第2块卡)"])
        self.dev_combo.setFixedWidth(130)
        self.dev_combo.setVisible(False)
        layout.addWidget(self.dev_combo)

        self.lbl_ch = QLabel("通道:")
        self.lbl_ch.setVisible(False)
        layout.addWidget(self.lbl_ch)
        self.chan_combo = QComboBox()
        self.chan_combo.addItems(["通道0", "通道1"])
        self.chan_combo.setFixedWidth(70)
        self.chan_combo.setVisible(False)
        layout.addWidget(self.chan_combo)

        self.lbl_baud = QLabel("波特率:")
        self.lbl_baud.setVisible(False)
        layout.addWidget(self.lbl_baud)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["125k", "250k", "500k", "1M"])
        self.baud_combo.setCurrentText("125k")
        self.baud_combo.setFixedWidth(70)
        self.baud_combo.setVisible(False)
        layout.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("btnConnect")
        self.connect_btn.clicked.connect(self._on_connect)
        layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setObjectName("danger")
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        layout.addWidget(self.disconnect_btn)

        layout.addSpacing(20)

        self.auto_poll_check = QCheckBox("自动轮询在线模块")
        self.auto_poll_check.stateChanged.connect(self._on_auto_poll_changed)
        layout.addWidget(self.auto_poll_check)

        layout.addWidget(QLabel("间隔(ms):"))
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(50, 5000)
        self.poll_interval_spin.setValue(100)
        self.poll_interval_spin.setSingleStep(50)
        self.poll_interval_spin.setFixedWidth(70)
        layout.addWidget(self.poll_interval_spin)

        layout.addStretch()

        self.online_count_label = QLabel("在线: 0")
        self.online_count_label.setStyleSheet("color: #0B7A76; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.online_count_label)

        self.conn_status_label = QLabel("● 未连接")
        self.conn_status_label.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.conn_status_label)

        return group

    def _create_batch_bar(self):
        group = QGroupBox("批量操作")
        layout = QHBoxLayout(group)
        layout.setSpacing(6)

        btn_all_on = QPushButton("全部开机")
        btn_all_on.setObjectName("success")
        btn_all_on.clicked.connect(lambda: self._batch_power(True))
        layout.addWidget(btn_all_on)

        btn_all_off = QPushButton("全部关机")
        btn_all_off.setObjectName("danger")
        btn_all_off.clicked.connect(lambda: self._batch_power(False))
        layout.addWidget(btn_all_off)

        layout.addSpacing(16)

        layout.addWidget(QLabel("批量电压(V):"))
        self.batch_v_spin = QDoubleSpinBox()
        self.batch_v_spin.setRange(0, 1000)
        self.batch_v_spin.setDecimals(1)
        self.batch_v_spin.setSingleStep(0.5)
        self.batch_v_spin.setValue(500.0)
        self.batch_v_spin.setFixedWidth(90)
        layout.addWidget(self.batch_v_spin)

        layout.addWidget(QLabel("批量电流(A):"))
        self.batch_i_spin = QDoubleSpinBox()
        self.batch_i_spin.setRange(0, 200)
        self.batch_i_spin.setDecimals(1)
        self.batch_i_spin.setSingleStep(0.5)
        self.batch_i_spin.setValue(50.0)
        self.batch_i_spin.setFixedWidth(90)
        layout.addWidget(self.batch_i_spin)

        btn_batch_vi = QPushButton("批量设置电压电流 (广播)")
        btn_batch_vi.clicked.connect(self._batch_set_vi)
        layout.addWidget(btn_batch_vi)

        layout.addSpacing(16)

        btn_sel_on = QPushButton("选中开机")
        btn_sel_on.setObjectName("success")
        btn_sel_on.clicked.connect(lambda: self._selected_power(True))
        layout.addWidget(btn_sel_on)

        btn_sel_off = QPushButton("选中关机")
        btn_sel_off.setObjectName("danger")
        btn_sel_off.clicked.connect(lambda: self._selected_power(False))
        layout.addWidget(btn_sel_off)

        btn_sel_vi = QPushButton("选中设置V/I")
        btn_sel_vi.clicked.connect(self._selected_set_vi)
        layout.addWidget(btn_sel_vi)

        layout.addStretch()

        btn_init = QPushButton("一键初始化 (0x1F+0x21 广播)")
        btn_init.setObjectName("warning")
        btn_init.clicked.connect(self._on_init_all)
        layout.addWidget(btn_init)

        btn_scan = QPushButton("扫描在线模块")
        btn_scan.clicked.connect(self._scan_modules)
        self.btn_scan = btn_scan
        layout.addWidget(btn_scan)

        btn_fault = QPushButton("故障代码查询")
        btn_fault.clicked.connect(self._on_show_fault_codes)
        layout.addWidget(btn_fault)

        return group

    def _create_monitor_table(self):
        group = QGroupBox("模块实时监控 (地址 0x01~0x3F)")
        layout = QVBoxLayout(group)

        self.table = QTableWidget(self.MAX_MODULES, self.COL_COUNT)
        self.table.setHorizontalHeaderLabels([
            "选", "地址", "在线", "状态", "电压(V)", "电流(A)",
            "设定电压(V)", "设定电流(A)",
            "温度(℃)", "风扇(%)", "故障", "电源", "开机", "关机", "设置V/I"
        ])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        widths = [42, 55, 50, 100, 75, 75, 85, 85, 65, 60, 95, 50, 50, 50, 60]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)

        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_check_changed)
        self.table.itemClicked.connect(self._on_row_click_select)

        # 初始化表格行
        self._sv_spins = {}
        self._si_spins = {}
        self.table.blockSignals(True)
        for i in range(self.MAX_MODULES):
            addr = i + 1
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            self.table.setItem(i, self.COL_CHECK, chk)
            self.table.setItem(i, self.COL_ADDR, QTableWidgetItem(f"0x{addr:02X}"))
            self.table.setItem(i, self.COL_ONLINE, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_STATE, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_VOLTAGE, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_CURRENT, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_TEMP, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_FAN, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_FAULT, QTableWidgetItem(""))
            self.table.setItem(i, self.COL_POWER, QTableWidgetItem(""))

            # 设置电压/电流：行内可编辑输入框
            sv = QDoubleSpinBox()
            sv.setRange(0, 1000)
            sv.setDecimals(1)
            sv.setSingleStep(0.5)
            sv.setMinimumWidth(70)
            # 用户改过之后轮询不再覆盖，避免“关机时输入被旧值顶掉”
            sv.valueChanged.connect(lambda _v, w=sv: setattr(w, "_user_edited", True))
            self.table.setCellWidget(i, self.COL_SET_VOLTAGE, sv)
            self._sv_spins[addr] = sv

            si = QDoubleSpinBox()
            si.setRange(0, 200)
            si.setDecimals(1)
            si.setSingleStep(0.5)
            si.setMinimumWidth(70)
            si.valueChanged.connect(lambda _v, w=si: setattr(w, "_user_edited", True))
            self.table.setCellWidget(i, self.COL_SET_CURRENT, si)
            self._si_spins[addr] = si

            btn_on = QPushButton("开")
            btn_on.setObjectName("small_success")
            btn_on.setFixedWidth(48)
            btn_on.clicked.connect(lambda checked, a=addr: self._single_power(a, True))
            self.table.setCellWidget(i, self.COL_BTN_ON, btn_on)

            btn_off = QPushButton("关")
            btn_off.setObjectName("small_danger")
            btn_off.setFixedWidth(48)
            btn_off.clicked.connect(lambda checked, a=addr: self._single_power(a, False))
            self.table.setCellWidget(i, self.COL_BTN_OFF, btn_off)

            btn_vi = QPushButton("设置")
            btn_vi.setObjectName("small")
            btn_vi.setFixedWidth(58)
            btn_vi.clicked.connect(lambda checked, a=addr: self._single_set_vi_from_table(a))
            self.table.setCellWidget(i, self.COL_BTN_VI, btn_vi)

        self.table.blockSignals(False)
        layout.addWidget(self.table)
        return group

    def _create_right_panel(self):
        tab_widget = QTabWidget()

        tab_widget.addTab(self._create_control_tab(), "模块控制")
        tab_widget.addTab(self._create_config_tab(), "初始化配置")
        tab_widget.addTab(self._create_info_tab(), "模块信息")

        return tab_widget

    def _create_control_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # 选中模块 — 多选列表
        sel_group = QGroupBox("选中模块 (可多选)")
        sel_layout = QVBoxLayout(sel_group)

        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_sel_all = QPushButton("全选")
        btn_sel_all.setObjectName("small")
        btn_sel_all.clicked.connect(self._select_all_modules)
        btn_row.addWidget(btn_sel_all)

        btn_sel_none = QPushButton("清空")
        btn_sel_none.setObjectName("small")
        btn_sel_none.clicked.connect(self._clear_module_selection)
        btn_row.addWidget(btn_sel_none)

        btn_sel_online = QPushButton("仅在线")
        btn_sel_online.setObjectName("small")
        btn_sel_online.clicked.connect(self._select_online_modules)
        btn_row.addWidget(btn_sel_online)

        btn_row.addStretch()

        self.sel_count_label = QLabel("已选: 0")
        self.sel_count_label.setStyleSheet("color: #89b4fa; font-weight: bold;")
        btn_row.addWidget(self.sel_count_label)
        sel_layout.addLayout(btn_row)

        # 多选列表
        self.module_list = QListWidget()
        self.module_list.setMaximumHeight(120)
        for i in range(1, 64):
            item = QListWidgetItem(f"0x{i:02X}  (地址 {i})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, i)
            self.module_list.addItem(item)
        self.module_list.itemChanged.connect(self._on_module_list_item_changed)
        self.module_list.currentItemChanged.connect(self._on_module_list_current_changed)
        sel_layout.addWidget(self.module_list)

        # 选中模块列表逻辑保留（表格勾选驱动），但不再展示此栏
        sel_group.setVisible(False)
        layout.addWidget(sel_group)

        # 电压电流设置
        vi_group = QGroupBox("输出电压电流设置 (0x1C)")
        vi_layout = QGridLayout(vi_group)
        vi_layout.setSpacing(6)

        vi_layout.addWidget(QLabel("电压 (V):"), 0, 0)
        self.voltage_spin = QDoubleSpinBox()
        self.voltage_spin.setRange(0, 1000)
        self.voltage_spin.setDecimals(1)
        self.voltage_spin.setSingleStep(0.5)
        self.voltage_spin.setValue(500.0)
        vi_layout.addWidget(self.voltage_spin, 0, 1)

        vi_layout.addWidget(QLabel("电流 (A):"), 0, 2)
        self.current_spin = QDoubleSpinBox()
        self.current_spin.setRange(0, 200)
        self.current_spin.setDecimals(1)
        self.current_spin.setSingleStep(0.5)
        self.current_spin.setValue(50.0)
        vi_layout.addWidget(self.current_spin, 0, 3)

        btn_set_vi = QPushButton("设置选中模块电压电流")
        btn_set_vi.setObjectName("success")
        btn_set_vi.clicked.connect(self._on_set_vi_selected)
        vi_layout.addWidget(btn_set_vi, 1, 0, 1, 4)

        # 应用到全部
        btn_apply_all_vi = QPushButton("此值应用到全部模块 (广播)")
        btn_apply_all_vi.clicked.connect(self._on_apply_all_vi)
        vi_layout.addWidget(btn_apply_all_vi, 2, 0, 1, 4)

        layout.addWidget(vi_group)

        # 开关机控制
        power_group = QGroupBox("开关机控制 (0x1A)")
        power_layout = QHBoxLayout(power_group)

        btn_on = QPushButton("选中开机")
        btn_on.setObjectName("success")
        btn_on.clicked.connect(lambda: self._selected_power(True))
        power_layout.addWidget(btn_on)

        btn_off = QPushButton("选中关机")
        btn_off.setObjectName("danger")
        btn_off.clicked.connect(lambda: self._selected_power(False))
        power_layout.addWidget(btn_off)

        btn_all_on = QPushButton("全部开机")
        btn_all_on.setObjectName("success")
        btn_all_on.clicked.connect(lambda: self._batch_power(True))
        power_layout.addWidget(btn_all_on)

        btn_all_off = QPushButton("全部关机")
        btn_all_off.setObjectName("danger")
        btn_all_off.clicked.connect(lambda: self._batch_power(False))
        power_layout.addWidget(btn_all_off)

        layout.addWidget(power_group)
        layout.addStretch()

        # 选中模块实时数据
        data_group = QGroupBox("选中模块实时数据")
        data_layout = QGridLayout(data_group)
        data_layout.setSpacing(4)

        data_layout.addWidget(QLabel("电压:"), 0, 0)
        self.sel_voltage = QLabel("--- V")
        self.sel_voltage.setStyleSheet("font-size: 18px; font-weight: bold; color: #0B7A76;")
        data_layout.addWidget(self.sel_voltage, 0, 1)

        data_layout.addWidget(QLabel("电流:"), 0, 2)
        self.sel_current = QLabel("--- A")
        self.sel_current.setStyleSheet("font-size: 18px; font-weight: bold; color: #f9e2af;")
        data_layout.addWidget(self.sel_current, 0, 3)

        data_layout.addWidget(QLabel("温度:"), 1, 0)
        self.sel_temp = QLabel("--- ℃")
        self.sel_temp.setStyleSheet("font-size: 14px; color: #f38ba8;")
        data_layout.addWidget(self.sel_temp, 1, 1)

        data_layout.addWidget(QLabel("风扇:"), 1, 2)
        self.sel_fan = QLabel("--- %")
        self.sel_fan.setStyleSheet("font-size: 14px; color: #89b4fa;")
        data_layout.addWidget(self.sel_fan, 1, 3)

        data_layout.addWidget(QLabel("状态:"), 2, 0)
        self.sel_state = QLabel("---")
        self.sel_state.setStyleSheet("font-size: 14px; color: #89b4fa;")
        data_layout.addWidget(self.sel_state, 2, 1)

        data_layout.addWidget(QLabel("设定V/I:"), 2, 2)
        self.sel_set_vi = QLabel("--- V / --- A")
        self.sel_set_vi.setStyleSheet("font-size: 14px; color: #b4befe;")
        data_layout.addWidget(self.sel_set_vi, 2, 3)

        data_layout.addWidget(QLabel("故障:"), 3, 0)
        self.sel_fault = QLabel("无")
        self.sel_fault.setStyleSheet("font-size: 14px; color: #0B7A76;")
        data_layout.addWidget(self.sel_fault, 3, 1, 1, 3)

        layout.addWidget(data_group)

        return widget

    def _create_config_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setSpacing(6)

        # 地址模式
        layout.addWidget(QLabel("地址模式:"), 0, 0)
        self.addr_mode_combo = QComboBox()
        self.addr_mode_combo.addItem("拨码设定", 1)
        self.addr_mode_combo.addItem("自动分配", 0)
        layout.addWidget(self.addr_mode_combo, 0, 1)
        btn = QPushButton("设置 (0x1F)")
        btn.clicked.connect(self._on_set_addr_mode)
        layout.addWidget(btn, 0, 2)

        # 并机模式
        layout.addWidget(QLabel("并机模式:"), 1, 0)
        self.parallel_mode_combo = QComboBox()
        self.parallel_mode_combo.addItem("正常并机", 0)
        self.parallel_mode_combo.addItem("智能并机", 1)
        layout.addWidget(self.parallel_mode_combo, 1, 1)
        btn = QPushButton("设置 (0x21)")
        btn.clicked.connect(self._on_set_parallel_mode)
        layout.addWidget(btn, 1, 2)

        # CAN广播
        layout.addWidget(QLabel("CAN广播:"), 2, 0)
        self.broadcast_combo = QComboBox()
        self.broadcast_combo.addItem("使能广播", 1)
        self.broadcast_combo.addItem("禁止广播", 0)
        layout.addWidget(self.broadcast_combo, 2, 1)
        btn = QPushButton("设置 (0x22)")
        btn.clicked.connect(self._on_set_broadcast)
        layout.addWidget(btn, 2, 2)

        # 高低压模式
        layout.addWidget(QLabel("高低压模式:"), 3, 0)
        self.voltage_mode_combo = QComboBox()
        self.voltage_mode_combo.addItem("低压模式", 1)
        self.voltage_mode_combo.addItem("高压模式", 2)
        layout.addWidget(self.voltage_mode_combo, 3, 1)
        btn = QPushButton("设置 (0x23)")
        btn.clicked.connect(self._on_set_voltage_mode)
        layout.addWidget(btn, 3, 2)

        # 一键初始化
        btn_init = QPushButton("一键初始化 (广播 0x1F + 0x21)")
        btn_init.setObjectName("success")
        btn_init.clicked.connect(self._on_init_all)
        layout.addWidget(btn_init, 4, 0, 1, 3)

        # 分组
        layout.addWidget(QLabel("分组号:"), 5, 0)
        self.group_spin = QSpinBox()
        self.group_spin.setRange(0, 255)
        self.group_spin.setValue(0)
        layout.addWidget(self.group_spin, 5, 1)
        btn = QPushButton("设置分组 (0x16)")
        btn.clicked.connect(self._on_set_group)
        layout.addWidget(btn, 5, 2)

        # 电压变化率
        layout.addWidget(QLabel("电压变化率(V/s):"), 6, 0)
        self.v_rate_spin = QSpinBox()
        self.v_rate_spin.setRange(1, 1000)
        self.v_rate_spin.setValue(50)
        layout.addWidget(self.v_rate_spin, 6, 1)
        btn = QPushButton("设置 (0x28)")
        btn.clicked.connect(self._on_set_v_rate)
        layout.addWidget(btn, 6, 2)

        # MPPT
        layout.addWidget(QLabel("MPPT开路电压(V):"), 7, 0)
        self.mppt_vopen = QDoubleSpinBox()
        self.mppt_vopen.setRange(0, 1000)
        self.mppt_vopen.setDecimals(1)
        self.mppt_vopen.setValue(600.0)
        layout.addWidget(self.mppt_vopen, 7, 1)

        layout.addWidget(QLabel("MPPT工作电压(V):"), 8, 0)
        self.mppt_vmpp = QDoubleSpinBox()
        self.mppt_vmpp.setRange(0, 1000)
        self.mppt_vmpp.setDecimals(1)
        self.mppt_vmpp.setValue(500.0)
        layout.addWidget(self.mppt_vmpp, 8, 1)

        layout.addWidget(QLabel("MPPT电流(A):"), 9, 0)
        self.mppt_i = QDoubleSpinBox()
        self.mppt_i.setRange(0, 200)
        self.mppt_i.setDecimals(2)
        self.mppt_i.setValue(20.0)
        layout.addWidget(self.mppt_i, 9, 1)

        btn_mppt = QPushButton("设置MPPT (0x24)")
        btn_mppt.clicked.connect(self._on_set_mppt)
        layout.addWidget(btn_mppt, 9, 2)

        layout.setRowStretch(10, 1)
        return widget

    def _create_info_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        btn_layout = QHBoxLayout()
        btn_read_info = QPushButton("读取选中模块全部信息")
        btn_read_info.setObjectName("success")
        btn_read_info.clicked.connect(self._on_read_all_info)
        btn_layout.addWidget(btn_read_info)

        btn_read_sn = QPushButton("读取所有在线模块信息")
        btn_read_sn.clicked.connect(self._on_read_sn)
        btn_layout.addWidget(btn_read_sn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 模块信息表格: 地址 / 型号 / SN / 版本号
        self.info_table = QTableWidget(0, 4)
        self.info_table.setHorizontalHeaderLabels(["模块地址", "型号", "SN", "版本号"])
        info_header = self.info_table.horizontalHeader()
        info_header.setSectionResizeMode(QHeaderView.Stretch)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.info_table)
        return widget

    def _create_log_panel(self):
        group = QGroupBox("CAN 报文日志")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 18, 8, 8)

        btn_layout = QHBoxLayout()
        self.log_tx_check = QCheckBox("显示发送")
        self.log_tx_check.setChecked(True)
        btn_layout.addWidget(self.log_tx_check)

        self.log_rx_check = QCheckBox("显示接收")
        self.log_rx_check.setChecked(True)
        btn_layout.addWidget(self.log_rx_check)

        self.log_auto_check = QCheckBox("自动滚动")
        self.log_auto_check.setChecked(True)
        btn_layout.addWidget(self.log_auto_check)

        btn_layout.addStretch()

        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(lambda: self.log_text.clear())
        btn_layout.addWidget(btn_clear)

        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self._save_log)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(160)
        layout.addWidget(self.log_text)
        return group

    # ============================================================
    # 样式 & 辅助
    # ============================================================

    def apply_style(self):
        self.setStyleSheet(expand_qss(STYLE_SHEET))

    def _log(self, msg, color="#0B7A76"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        html = f'<span style="color:#6B7280;">[{timestamp}]</span> <span style="color:{color};">{msg}</span>'
        self.log_text.append(html)
        if self.log_auto_check.isChecked():
            self.log_text.moveCursor(QTextCursor.End)

    def _log_tx(self, can_id, data):
        if self.log_tx_check.isChecked():
            self._log(cp.format_can_message(can_id, data, "TX"), "#89b4fa")

    def _log_rx(self, can_id, data):
        if self.log_rx_check.isChecked():
            self._log(cp.format_can_message(can_id, data, "RX"), "#0B7A76")

    def _send_cmd(self, can_id, data, wait=False, timeout=1.0):
        if not self.driver.connected:
            return None
        self._log_tx(can_id, data)
        if wait:
            result = self.driver.send_and_wait(can_id, data, timeout=timeout)
            if result:
                self._log_rx(result[0], result[1])
                self._process_response(result[0], result[1])
                return result
            else:
                self._log("响应超时", "#f38ba8")
            return None
        else:
            self.driver.send_can_frame(can_id, data)
            return None

    def _is_tx_echo(self, can_id):
        return cp.parse_can_id(can_id)['src'] == cp.ADDR_MONITOR

    # ============================================================
    # 表格更新
    # ============================================================

    def _update_table_row(self, addr):
        """更新表格中指定地址的行"""
        if addr < 1 or addr > 63:
            return
        row = addr - 1
        md = self.modules[addr]

        # 在线状态
        online_item = self.table.item(row, self.COL_ONLINE)
        online_item.setTextAlignment(Qt.AlignCenter)
        online_item.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        if md.online:
            online_item.setText("●")
            online_item.setForeground(QBrush(QColor("#047857")))
        else:
            online_item.setText("○")
            online_item.setForeground(QBrush(QColor("#9AA2AA")))

        # 状态
        state_item = self.table.item(row, self.COL_STATE)
        if md.state1 >= 0:
            state_text = cp.MODULE_STATES.get(md.state1, f"未知({md.state1})")
            state_item.setText(state_text)
            if md.state1 == 3:
                state_item.setForeground(QBrush(QColor("#0B7A76")))
            elif md.state1 == 4:
                state_item.setForeground(QBrush(QColor("#f38ba8")))
            else:
                state_item.setForeground(QBrush(QColor("#f9e2af")))
        else:
            state_item.setText("")

        # 电压
        self.table.item(row, self.COL_VOLTAGE).setText(f"{md.voltage:.1f}" if md.online else "")

        # 电流
        self.table.item(row, self.COL_CURRENT).setText(f"{md.current:.1f}" if md.online else "")

        # 设定电压/电流：仅在用户未手动改过时回填
        sv_w = getattr(self, "_sv_spins", {}).get(addr)
        if sv_w is not None and md.online:
            val = md.set_voltage_actual if md.set_voltage_actual > 0 else md.set_voltage
            self._sync_vi_spin(sv_w, val if val > 0 else None)
        si_w = getattr(self, "_si_spins", {}).get(addr)
        if si_w is not None and md.online:
            val = md.set_current_actual if md.set_current_actual > 0 else md.set_current
            self._sync_vi_spin(si_w, val if val > 0 else None)

        # 温度
        temp_item = self.table.item(row, self.COL_TEMP)
        if md.online:
            temp_item.setText(f"{md.temperature}")
            if md.temperature > 80:
                temp_item.setForeground(QBrush(QColor("#f38ba8")))
            elif md.temperature > 60:
                temp_item.setForeground(QBrush(QColor("#f9e2af")))
            else:
                temp_item.setForeground(QBrush(QColor("#0B7A76")))
        else:
            temp_item.setText("")

        # 风扇
        self.table.item(row, self.COL_FAN).setText(f"{md.fan_speed}" if md.online else "")

        # 故障
        fault_item = self.table.item(row, self.COL_FAULT)
        if md.online and md.fault_code != 0:
            fault_item.setText(f"0x{md.fault_code:012X}")
            fault_item.setForeground(QBrush(QColor("#f38ba8")))
        elif md.online:
            fault_item.setText("无")
            fault_item.setForeground(QBrush(QColor("#0B7A76")))
        else:
            fault_item.setText("")

        # 电源状态
        power_item = self.table.item(row, self.COL_POWER)
        if md.power_on is True:
            power_item.setText("ON")
            power_item.setForeground(QBrush(QColor("#0B7A76")))
        elif md.power_on is False:
            power_item.setText("OFF")
            power_item.setForeground(QBrush(QColor("#f38ba8")))
        else:
            power_item.setText("")

    def _update_online_count(self):
        count = sum(1 for m in self.modules.values() if m.online)
        self.online_count_label.setText(f"在线: {count}")

    def _update_selected_panel(self):
        """更新右侧选中模块的数据显示"""
        md = self.modules[self._selected_addr]
        self.sel_voltage.setText(f"{md.voltage:.2f} V" if md.online else "--- V")
        self.sel_current.setText(f"{md.current:.2f} A" if md.online else "--- A")
        self.sel_temp.setText(f"{md.temperature} ℃" if md.online else "--- ℃")
        self.sel_fan.setText(f"{md.fan_speed} %" if md.online else "--- %")

        if md.set_voltage_actual > 0 or md.set_current_actual > 0:
            self.sel_set_vi.setText(f"{md.set_voltage_actual:.1f}V / {md.set_current_actual:.1f}A")
        else:
            self.sel_set_vi.setText(f"{md.set_voltage:.1f}V / {md.set_current:.1f}A")

        if md.state1 >= 0:
            self.sel_state.setText(cp.MODULE_STATES.get(md.state1, "---"))
            if md.state1 == 3:
                self.sel_state.setStyleSheet("font-size: 14px; color: #0B7A76;")
            elif md.state1 == 4:
                self.sel_state.setStyleSheet("font-size: 14px; color: #f38ba8;")
            else:
                self.sel_state.setStyleSheet("font-size: 14px; color: #f9e2af;")
        else:
            self.sel_state.setText("---")

        if md.fault_code != 0:
            self.sel_fault.setText(f"0x{md.fault_code:012X}")
            self.sel_fault.setStyleSheet("font-size: 14px; color: #f38ba8;")
        else:
            self.sel_fault.setText("无")
            self.sel_fault.setStyleSheet("font-size: 14px; color: #0B7A76;")

    # ============================================================
    # 响应处理
    # ============================================================

    def _on_rx_callback(self, can_id, can_data, is_ext, is_rtr, dlc):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到设备 CAN 帧 = 通讯真正建立
        pass

    def _on_message_received(self, can_id, can_data, is_ext, is_rtr, dlc):
        if self._is_tx_echo(can_id):
            return
        self._log_rx(can_id, can_data)
        self._process_response(can_id, can_data)

    def _process_response(self, can_id, rx_data):
        info = cp.parse_can_id(can_id)
        if info['dest'] != cp.ADDR_MONITOR:
            return

        src_addr = info['src']
        cmd = info['cmd']

        if src_addr < 1 or src_addr > 63:
            return

        md = self.modules[src_addr]
        md.online = True
        md.last_seen = time.time()

        try:
            if cmd in (cp.CMD_READ_VI, cp.CMD_READ_SYS_VI):
                md.voltage, md.current = cp.parse_vi_response(rx_data)

            elif cmd == cp.CMD_READ_MODULE_NUM:
                num = cp.parse_module_num_response(rx_data)
                self._log(f"在线模块数: {num}", "#89b4fa")

            elif cmd == cp.CMD_READ_FAN_TEMP_ERR:
                md.fan_speed, md.temperature, md.fault_code = cp.parse_fan_temp_err_response(rx_data)
                if md.fault_code != 0:
                    faults = cp.decode_fault_code(md.fault_code)
                    for f in faults:
                        self._log(f"  [0x{src_addr:02X}] {f}", "#f38ba8")

            elif cmd == cp.CMD_READ_INPUT_VI:
                md.uab, md.ubc, md.uca, md.state1, md.state2 = cp.parse_input_vi_response(rx_data)

            elif cmd == cp.CMD_SET_VI:
                md.set_voltage_actual, md.set_current_actual = cp.parse_set_vi_response(rx_data)

            elif cmd == cp.CMD_READ_RUNTIME:
                total_h, boot_s = cp.parse_runtime_response(rx_data)
                self._log(f"[0x{src_addr:02X}] 运行时间: {total_h:.1f}h, 开机: {boot_s}s", "#1B2430")

            elif cmd == cp.CMD_CTRL_POWER:
                state3 = cp.parse_power_response(rx_data)
                if not state3.get('addr_mode_init', True):
                    self._log(f"[0x{src_addr:02X}] 警告: 地址模式未初始化!", "#f9e2af")

        except Exception as e:
            self._log(f"解析异常: {e}", "#f38ba8")

        self._update_table_row(src_addr)
        self._update_online_count()
        if src_addr == self._selected_addr:
            self._update_selected_panel()

    # ============================================================
    # 连接管理
    # ============================================================

    def _sync_vi_spin(self, spin, val):
        """从模块回填行内输入框；用户手动改过则永不覆盖。"""
        if spin is None or val is None:
            return
        if spin.hasFocus() or getattr(spin, "_user_edited", False):
            return
        if abs(spin.value() - float(val)) < 0.05:
            return
        spin.blockSignals(True)
        spin.setValue(float(val))
        spin.blockSignals(False)

    def _reset_vi_user_edited(self):
        for d in (getattr(self, "_sv_spins", {}), getattr(self, "_si_spins", {})):
            for w in d.values():
                w._user_edited = False

    def _on_can_box_changed(self, idx):
        is_ut = (idx == 0)
        self.lbl_ip.setVisible(is_ut)
        self.ip_edit.setVisible(is_ut)
        self.lbl_port.setVisible(is_ut)
        self.port_spin.setVisible(is_ut)
        self.lbl_dev.setVisible(not is_ut)
        self.dev_combo.setVisible(not is_ut)
        self.lbl_ch.setVisible(not is_ut)
        self.chan_combo.setVisible(not is_ut)
        self.lbl_baud.setVisible(not is_ut)
        self.baud_combo.setVisible(not is_ut)

    def _make_driver(self):
        """按 CAN盒 选择创建驱动并挂接收回调。"""
        if self.can_box_combo.currentIndex() == 1:
            baud_map = {"125k": 125, "250k": 250, "500k": 500, "1M": 1000}
            baud = baud_map.get(self.baud_combo.currentText(), 125)
            drv = ZLGUsbCanDriver(
                device_index=self.dev_combo.currentIndex(),
                channel=self.chan_combo.currentIndex(),
                baud_kbps=baud)
        else:
            drv = UT6502Driver()
        drv.add_rx_callback(self._on_rx_callback)
        return drv

    def _on_connect(self):
        self._reset_vi_user_edited()
        if self.can_box_combo.currentIndex() == 0:
            ip = self.ip_edit.text().strip()
            port = self.port_spin.value()
            if not ip:
                QMessageBox.warning(self, "警告", "请输入 IP 地址!")
                return
        else:
            ip, port = "", 0
        try:
            # 停掉旧驱动（若有）
            try:
                self.driver.disconnect()
            except Exception:
                pass
            self.driver = self._make_driver()
            if self.can_box_combo.currentIndex() == 0:
                self.driver.connect(ip, port, timeout=3.0)
                self._log(f"已连接 UT-6502 ({ip}:{port})", "#0B7A76")
            else:
                self.driver.connect()
                self._log("已连接 ZLG USBCAN-2E-U (USB)", "#0B7A76")
            self.update_connection_state(True)
            self.recv_thread = CanReceiver(self.driver)
            self.recv_thread.message_received.connect(self._on_message_received)
            self.recv_thread.start()
            self._log("提示: 上电后等待1.5s, 先执行一键初始化", "#f9e2af")
            # 启动选中模块快速轮询 (200ms 交替读取 V/I 和 温度/风扇)
            self.single_poll_timer.start(200)
        except Exception as e:
            QMessageBox.critical(self, "连接失败", str(e))
            self._log(f"连接失败: {e}", "#f38ba8")
            for line in getattr(self.driver, "attempts", [])[-12:]:
                self._log(f"  [排查] {line}", "#f9e2af")

    def _on_disconnect(self):
        self._reset_vi_user_edited()
        if self.recv_thread:
            self.recv_thread.stop()
            self.recv_thread = None
        self.single_poll_timer.stop()
        try:
            self.driver.disconnect()
        except Exception as e:
            # 驱动断开异常不能阻断状态复位，否则按钮卡在「已连接」、轮询不停
            self._log(f"断开时驱动异常(已忽略): {e}", "#f9e2af")
        self.update_connection_state(False)
        if self.auto_poll_check.isChecked():
            self.auto_poll_check.setChecked(False)
        # 清除所有在线状态
        for md in self.modules.values():
            md.online = False
        for addr in range(1, 64):
            self._update_table_row(addr)
        self._update_online_count()
        self._log("已断开连接", "#f9e2af")

    def update_connection_state(self, connected):
        self.connect_btn.setEnabled(not connected)
        self.connect_btn.setText("已连接" if connected else "连接")
        self.connect_btn.setObjectName("btnConnected" if connected else "btnConnect")
        self.disconnect_btn.setEnabled(connected)
        if connected:
            self.conn_status_label.setText("● 已连接")
            self.conn_status_label.setStyleSheet("color: #0B7A76; font-weight: bold; font-size: 13px;")
        else:
            self.conn_status_label.setText("● 未连接")
            self.conn_status_label.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 13px;")

    # ============================================================
    # 自动轮询 — 只轮询在线模块
    # ============================================================

    def _on_auto_poll_changed(self, state):
        if state:
            if not self.driver.connected:
                self.auto_poll_check.setChecked(False)
                QMessageBox.warning(self, "警告", "请先连接 UT-6502!")
                return
            interval = self.poll_interval_spin.value()
            self.poll_timer.start(interval)
            self._log(f"启动自动轮询, 间隔 {interval}ms", "#89b4fa")
        else:
            self.poll_timer.stop()
            self._log("停止自动轮询", "#f9e2af")

    def _poll_tick(self):
        """轮询一个模块的一个命令"""
        if not self.driver.connected:
            self.auto_poll_check.setChecked(False)
            return

        # 检查离线模块 (超过5秒未响应)
        self._check_offline_modules()

        # 轮询命令: 0x03 -> 0x04 -> 0x06 循环（只轮询在线模块）
        online_addrs = [a for a in range(1, 64) if self.modules[a].online]
        if not online_addrs:
            return
        cmds = [cp.CMD_READ_VI, cp.CMD_READ_FAN_TEMP_ERR, cp.CMD_READ_INPUT_VI]
        addr = online_addrs[self._poll_addr_idx % len(online_addrs)]

        cmd = cmds[self._poll_cmd_idx]

        if cmd == cp.CMD_READ_VI:
            can_id, data = cp.cmd_read_vi(addr, cp.ADDR_MONITOR)
        elif cmd == cp.CMD_READ_FAN_TEMP_ERR:
            can_id, data = cp.cmd_read_fan_temp_err(addr, cp.ADDR_MONITOR)
        elif cmd == cp.CMD_READ_INPUT_VI:
            can_id, data = cp.cmd_read_input_vi(addr, cp.ADDR_MONITOR)

        self._log_tx(can_id, data)
        self.driver.send_can_frame(can_id, data)

        # 推进索引
        self._poll_cmd_idx += 1
        if self._poll_cmd_idx >= len(cmds):
            self._poll_cmd_idx = 0
            self._poll_addr_idx = (self._poll_addr_idx + 1) % len(online_addrs)

    def _check_offline_modules(self, timeout=5.0):
        """模块掉线检测：超过 timeout 秒无响应 → 标记离线并刷新表格/计数。

        独立于「自动轮询」开关——快速轮询(200ms)同样调用，
        保证模块断开后无论何种轮询配置都能及时感知、停发无效帧。
        """
        now = time.time()
        changed = False
        for addr in range(1, 64):
            md = self.modules[addr]
            if md.online and (now - md.last_seen) > timeout:
                md.online = False
                md.state1 = -1
                self._update_table_row(addr)
                changed = True
                self._log(f"模块 0x{addr:02X} 超过{int(timeout)}秒无响应, 标记离线", "#f9e2af")
        if changed:
            self._update_online_count()
        # 通讯状态：全部模块离线（无任何在线模块）= 通讯中断，右上角指示灯回灰
        if not any(m.online for m in self.modules.values()):
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)

    def _single_poll_tick(self):
        """选中模块快速轮询: 交替读取 0x03(V/I) 和 0x04(温度/风扇/故障)"""
        if not self.driver.connected:
            self.single_poll_timer.stop()
            return
        # 模块掉线检测：不依赖「自动轮询」开关，保证及时感知设备断开
        self._check_offline_modules()
        addr = self._selected_addr
        if not self.modules[addr].online:
            return   # 选中模块已离线：不再发无效帧（重新扫描/重新上线后自动恢复）
        if self._single_poll_cmd == 0:
            can_id, data = cp.cmd_read_vi(addr, cp.ADDR_MONITOR)
        else:
            can_id, data = cp.cmd_read_fan_temp_err(addr, cp.ADDR_MONITOR)
        self._log_tx(can_id, data)
        self.driver.send_can_frame(can_id, data)
        self._single_poll_cmd = 1 - self._single_poll_cmd

    def _scan_modules(self):
        """扫描在线模块; 扫描中再点此按钮=中断扫描"""
        if getattr(self, "_scan_busy", False):
            self._scan_cancelled = True
            self._scan_timer.stop()
            self._scan_finish()
            self._log("已中断扫描", "#f9e2af")
            return
        if not self.driver.connected:
            QMessageBox.warning(self, "警告", "请先连接!")
            return
        self._scan_busy = True
        self._scan_cancelled = False
        self._scan_addrs = list(range(1, 64))
        self._scan_index = 0
        self.btn_scan.setText("停止扫描")
        self._log("开始扫描所有模块...", "#89b4fa")
        if not hasattr(self, "_scan_timer"):
            self._scan_timer = QTimer(self)
            self._scan_timer.timeout.connect(self._scan_tick)
        self._scan_timer.start(20)

    def _scan_tick(self):
        """逐地址发一帧, 帧间隔 20ms, 可中断"""
        if self._scan_cancelled or not self.driver.connected:
            self._scan_timer.stop()
            self._scan_finish()
            return
        if self._scan_index >= len(self._scan_addrs):
            self._scan_timer.stop()
            self._scan_finish()
            return
        addr = self._scan_addrs[self._scan_index]
        self._scan_index += 1
        can_id, data = cp.cmd_read_vi(addr, cp.ADDR_MONITOR)
        self._log_tx(can_id, data)
        self.driver.send_can_frame(can_id, data)

    def _scan_finish(self):
        self._scan_busy = False
        self.btn_scan.setText("扫描在线模块")
        self._log("扫描指令已发送, 等待响应...", "#f9e2af")

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
        """显示 EN+ 故障/告警位定义"""
        lines = ["EN+ 模块故障码定义 (64位 Bit0~Bit63)", ""]
        for bit in sorted(cp.FAULT_CODES.keys()):
            lines.append(f"  Bit{bit:02d}: {cp.FAULT_CODES[bit]}")
        lines += [
            "",
            "说明：故障字为 64 位，对应位置 1 表示该故障/告警。",
            "常见：Bit0~19 多为硬件/软件故障，Bit40+ 多为过温降载与通信告警。",
        ]
        QMessageBox.information(self, "故障代码查询", "\n".join(lines))

    # ============================================================
    # 单模块控制
    # ============================================================

    def _on_table_selection_changed(self):
        """表格选择变化: 同步到右侧模块列表（模块地址选中固定在勾选列，其余列不可选中）"""
        if self.table.currentColumn() != self.COL_CHECK:
            return
        rows = self.table.selectionModel().selectedRows()
        current_row = self.table.currentRow()
        if current_row >= 0:
            self._selected_addr = current_row + 1
            self._update_selected_panel()
            md = self.modules[self._selected_addr]
            self.voltage_spin.setValue(md.set_voltage)
            self.current_spin.setValue(md.set_current)
            # 同步模块列表当前项
            self.module_list.blockSignals(True)
            self.module_list.setCurrentRow(current_row)
            self.module_list.blockSignals(False)

    def _on_module_list_item_changed(self, item):
        """模块列表勾选状态变化（镜像显示：选中只能在表格勾选列操作，此处不可选中）"""
        return

    def _on_module_list_current_changed(self, current, previous):
        """模块列表当前项变化（镜像显示：模块地址选中固定在表格勾选列，此处不可选中）"""
        return

    def _update_sel_count(self):
        """更新已选数量显示"""
        count = len(self._get_selected_addrs())
        self.sel_count_label.setText(f"已选: {count}")

    def _sync_table_selection(self):
        """将模块列表的勾选状态同步到表格高亮与勾选框"""
        addrs = self._get_selected_addrs()
        self.table.blockSignals(True)
        self.table.clearSelection()
        for i in range(self.MAX_MODULES):
            addr = i + 1
            chk = self.table.item(i, self.COL_CHECK)
            if chk is not None:
                chk.setCheckState(Qt.Checked if addr in addrs else Qt.Unchecked)
        for addr in addrs:
            row = addr - 1
            idx = self.table.model().index(row, 0)
            self.table.selectionModel().select(idx, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.table.blockSignals(False)
        if addrs:
            self.table.setCurrentCell(addrs[0] - 1, 0)

    def _on_row_click_select(self, item):
        """模块地址选中固定在勾选列，其余列点击不可选中（规范）"""
        return

    def _on_table_check_changed(self, item):
        """表格勾选框变化 -> 同步到右侧「选中模块」列表"""
        if item is None or item.column() != self.COL_CHECK:
            return
        module_list = getattr(self, "module_list", None)
        if module_list is None:
            return
        li = module_list.item(item.row())
        if li is None:
            return
        want = Qt.Checked if item.checkState() == Qt.Checked else Qt.Unchecked
        module_list.blockSignals(True)
        li.setCheckState(want)
        module_list.blockSignals(False)
        self._update_sel_count()
        if want == Qt.Checked:
            module_list.setCurrentRow(item.row())
        self._sync_table_selection()

    def _get_selected_addrs(self):
        """获取模块列表中所有勾选的模块地址"""
        addrs = []
        for i in range(self.module_list.count()):
            item = self.module_list.item(i)
            if item.checkState() == Qt.Checked:
                addrs.append(item.data(Qt.UserRole))
        return sorted(addrs)

    def _select_all_modules(self):
        """全选模块"""
        self.module_list.blockSignals(True)
        for i in range(self.module_list.count()):
            self.module_list.item(i).setCheckState(Qt.Checked)
        self.module_list.blockSignals(False)
        self._update_sel_count()
        self._sync_table_selection()

    def _clear_module_selection(self):
        """清空选择"""
        self.module_list.blockSignals(True)
        for i in range(self.module_list.count()):
            self.module_list.item(i).setCheckState(Qt.Unchecked)
        self.module_list.blockSignals(False)
        self._update_sel_count()
        self._sync_table_selection()

    def _select_online_modules(self):
        """仅选在线模块"""
        self.module_list.blockSignals(True)
        for i in range(self.module_list.count()):
            addr = self.module_list.item(i).data(Qt.UserRole)
            state = Qt.Checked if self.modules[addr].online else Qt.Unchecked
            self.module_list.item(i).setCheckState(state)
        self.module_list.blockSignals(False)
        self._update_sel_count()
        self._sync_table_selection()

    def _single_power(self, addr, power_on):
        """单个模块开关机"""
        if power_on and not self._confirm_power_on([addr], False, "确认开机"):
            return
        can_id, data = cp.cmd_ctrl_power(power_on, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)
        self.modules[addr].power_on = power_on
        self._update_table_row(addr)
        self._log(f"[0x{addr:02X}] {'开机' if power_on else '关机'}", "#89b4fa")

    def _single_sleep(self, addr, sleep):
        can_id, data = cp.cmd_ctrl_sleep(sleep, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=False)
        self._log(f"[0x{addr:02X}] {'休眠' if sleep else '唤醒'}", "#89b4fa")

    def _on_set_vi_selected(self):
        """设置所有勾选模块的电压电流"""
        addrs = self._get_selected_addrs()
        if not addrs:
            QMessageBox.warning(self, "提示", "请先在模块列表中勾选模块!")
            return
        v = self.voltage_spin.value()
        i = self.current_spin.value()
        for addr in addrs:
            can_id, data = cp.cmd_set_vi(int(v * 1000), int(i * 1000), addr, cp.ADDR_MONITOR)
            self._send_cmd(can_id, data, wait=False)
            self.modules[addr].set_voltage = v
            self.modules[addr].set_current = i
            self._update_table_row(addr)
            time.sleep(0.02)
        addrs_str = ", ".join(f"0x{a:02X}" for a in addrs)
        self._log(f"选中模块 ({len(addrs)}个) 设置: {v:.1f}V / {i:.1f}A: {addrs_str}", "#89b4fa")

    def _single_set_vi_from_table(self, addr):
        """从表格点击设置按钮: 读取该行输入的电压电流并下发"""
        # 勾选该模块
        self.module_list.item(addr - 1).setCheckState(Qt.Checked)
        self._selected_addr = addr
        sv_w = getattr(self, "_sv_spins", {}).get(addr)
        si_w = getattr(self, "_si_spins", {}).get(addr)
        v = sv_w.value() if sv_w is not None else self.voltage_spin.value()
        i = si_w.value() if si_w is not None else self.current_spin.value()
        if sv_w is not None:
            self.voltage_spin.setValue(v)
        if si_w is not None:
            self.current_spin.setValue(i)
        can_id, data = cp.cmd_set_vi(int(v * 1000), int(i * 1000), addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)
        md = self.modules[addr]
        md.set_voltage = v
        md.set_current = i
        self._update_table_row(addr)
        self._log(f"[0x{addr:02X}] 设置: {v:.1f}V / {i:.1f}A", "#89b4fa")

    # ============================================================
    # 批量操作
    # ============================================================

    def _batch_power(self, power_on):
        """广播开关机"""
        if power_on and not self._confirm_power_on(None, True, "确认全部开机"):
            return
        can_id, data = cp.cmd_ctrl_power(power_on, cp.ADDR_BROADCAST, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=False)
        for addr in range(1, 64):
            self.modules[addr].power_on = power_on
            self._update_table_row(addr)
        self._log(f"广播{'开机' if power_on else '关机'}已发送", "#89b4fa")

    def _batch_set_vi(self):
        """广播设置电压电流"""
        v = self.batch_v_spin.value()
        i = self.batch_i_spin.value()
        can_id, data = cp.cmd_set_vi(int(v * 1000), int(i * 1000), cp.ADDR_BROADCAST, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=False)
        for addr in range(1, 64):
            self.modules[addr].set_voltage = v
            self.modules[addr].set_current = i
        self._log(f"广播设置: {v:.1f}V / {i:.1f}A", "#89b4fa")

    def _on_apply_all_vi(self):
        """将当前选中模块的V/I应用到全部"""
        v = self.voltage_spin.value()
        i = self.current_spin.value()
        can_id, data = cp.cmd_set_vi(int(v * 1000), int(i * 1000), cp.ADDR_BROADCAST, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=False)
        for addr in range(1, 64):
            self.modules[addr].set_voltage = v
            self.modules[addr].set_current = i
        self._log(f"广播设置: {v:.1f}V / {i:.1f}A", "#89b4fa")

    def _selected_power(self, power_on):
        """对表格中选中的模块逐个发送开关机命令"""
        addrs = self._get_selected_addrs()
        if not addrs:
            QMessageBox.warning(self, "提示", "请先在表格中选择模块!")
            return
        if power_on and not self._confirm_power_on(addrs, False, "确认选中开机"):
            return
        for addr in addrs:
            can_id, data = cp.cmd_ctrl_power(power_on, addr, cp.ADDR_MONITOR)
            self._send_cmd(can_id, data, wait=False)
            self.modules[addr].power_on = power_on
            self._update_table_row(addr)
            time.sleep(0.02)
        addrs_str = ", ".join(f"0x{a:02X}" for a in addrs)
        self._log(f"选中模块 ({len(addrs)}个) {'开机' if power_on else '关机'}: {addrs_str}", "#89b4fa")

    def _selected_set_vi(self):
        """对表格中选中的模块逐个设置电压电流"""
        addrs = self._get_selected_addrs()
        if not addrs:
            QMessageBox.warning(self, "提示", "请先在表格中选择模块!")
            return
        v = self.batch_v_spin.value()
        i = self.batch_i_spin.value()
        for addr in addrs:
            can_id, data = cp.cmd_set_vi(int(v * 1000), int(i * 1000), addr, cp.ADDR_MONITOR)
            self._send_cmd(can_id, data, wait=False)
            self.modules[addr].set_voltage = v
            self.modules[addr].set_current = i
            self._update_table_row(addr)
            time.sleep(0.02)
        addrs_str = ", ".join(f"0x{a:02X}" for a in addrs)
        self._log(f"选中模块 ({len(addrs)}个) 设置: {v:.1f}V / {i:.1f}A: {addrs_str}", "#89b4fa")

    # ============================================================
    # 配置命令
    # ============================================================

    def _on_set_addr_mode(self):
        mode = self.addr_mode_combo.currentData()
        addr = self._selected_addr
        can_id, data = cp.cmd_set_addr_mode(mode == 1, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)
        self._log(f"[0x{addr:02X}] 地址模式: {'拨码' if mode == 1 else '自动'}", "#89b4fa")

    def _on_set_parallel_mode(self):
        mode = self.parallel_mode_combo.currentData()
        addr = self._selected_addr
        can_id, data = cp.cmd_set_parallel_mode(mode == 1, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)
        self._log(f"[0x{addr:02X}] 并机模式: {'智能' if mode == 1 else '正常'}", "#89b4fa")

    def _on_set_broadcast(self):
        enable = self.broadcast_combo.currentData() == 1
        addr = self._selected_addr
        can_id, data = cp.cmd_set_can_broadcast(enable, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)

    def _on_set_voltage_mode(self):
        mode = self.voltage_mode_combo.currentData()
        addr = self._selected_addr
        can_id, data = cp.cmd_set_voltage_mode(mode, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)

    def _on_init_all(self):
        self._log("一键初始化...", "#f9e2af")
        dial = self.addr_mode_combo.currentData() == 1
        can_id, data = cp.cmd_set_addr_mode(dial, cp.ADDR_BROADCAST, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=False)
        time.sleep(0.1)
        smart = self.parallel_mode_combo.currentData() == 1
        can_id, data = cp.cmd_set_parallel_mode(smart, cp.ADDR_BROADCAST, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=False)
        self._log("一键初始化完成 (0x1F + 0x21 已广播)", "#0B7A76")

    def _on_set_group(self):
        group = self.group_spin.value()
        addr = self._selected_addr
        can_id, data = cp.cmd_set_group(addr, group, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)

    def _on_set_v_rate(self):
        rate = self.v_rate_spin.value()
        addr = self._selected_addr
        can_id, data = cp.cmd_set_voltage_rate(rate, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)

    def _on_set_mppt(self):
        v_open = int(self.mppt_vopen.value() * 10)
        v_mpp = int(self.mppt_vmpp.value() * 10)
        i_mpp = int(self.mppt_i.value() * 100)
        addr = self._selected_addr
        can_id, data = cp.cmd_set_mppt(v_open, v_mpp, i_mpp, addr, cp.ADDR_MONITOR)
        self._send_cmd(can_id, data, wait=True)

    # ============================================================
    # 模块信息
    # ============================================================

    def _read_module_info(self, addr):
        """读取单个模块的型号、SN、版本号, 存入 ModuleData 并返回"""
        md = self.modules[addr]

        # 型号名称 (0x34-0x35)
        model_name = ""
        for cmd in [cp.CMD_READ_INFO_5, cp.CMD_READ_INFO_6]:
            can_id, data = cp.cmd_read_info(cmd, addr, cp.ADDR_MONITOR)
            r = self._send_cmd(can_id, data, wait=True, timeout=1.0)
            if r:
                model_name += cp.parse_sn_response(r[1])
            time.sleep(0.05)
        md.model_name = model_name

        # 序列号 (0x32-0x33)
        sn = ""
        for cmd in [cp.CMD_READ_INFO_3, cp.CMD_READ_INFO_4]:
            can_id, data = cp.cmd_read_info(cmd, addr, cp.ADDR_MONITOR)
            r = self._send_cmd(can_id, data, wait=True, timeout=1.0)
            if r:
                sn += cp.parse_sn_response(r[1])
            time.sleep(0.05)
        md.sn = sn

        # 软件版本号 (0x38-0x39)
        sw_version = ""
        for cmd in [cp.CMD_READ_INFO_9, cp.CMD_READ_INFO_A]:
            can_id, data = cp.cmd_read_info(cmd, addr, cp.ADDR_MONITOR)
            r = self._send_cmd(can_id, data, wait=True, timeout=1.0)
            if r:
                sw_version += cp.parse_sn_response(r[1])
            time.sleep(0.05)
        md.sw_version = sw_version

        return model_name, sn, sw_version

    def _refresh_info_table(self, addrs):
        """根据地址列表刷新模块信息表格"""
        self.info_table.setRowCount(len(addrs))
        for row, addr in enumerate(addrs):
            md = self.modules[addr]
            self.info_table.setItem(row, 0, QTableWidgetItem(f"0x{addr:02X}"))
            self.info_table.setItem(row, 1, QTableWidgetItem(md.model_name))
            self.info_table.setItem(row, 2, QTableWidgetItem(md.sn))
            self.info_table.setItem(row, 3, QTableWidgetItem(md.sw_version))

    def _on_read_all_info(self):
        addr = self._selected_addr
        self._log(f"读取 [0x{addr:02X}] 模块信息...", "#89b4fa")

        # 暂停轮询, 防止响应干扰
        self.poll_timer.stop()
        self.single_poll_timer.stop()

        # 0x30: 软件物料号, 匹配码, 机型
        can_id, data = cp.cmd_read_info(cp.CMD_READ_INFO_1, addr, cp.ADDR_MONITOR)
        r = self._send_cmd(can_id, data, wait=True, timeout=1.0)
        if r:
            sw, match, model = cp.parse_info1_response(r[1])
            self._log(f"  软件物料号: {sw}  匹配码: {match}  机型编码: {model}", "#1B2430")
        time.sleep(0.05)

        # 型号/SN/版本号
        model_name, sn, sw_version = self._read_module_info(addr)
        self._log(f"  型号: {model_name}  SN: {sn}  版本: {sw_version}", "#1B2430")
        self._refresh_info_table([addr])

        time.sleep(0.05)

        # 0x31: 模块特征字
        can_id, data = cp.cmd_read_info(cp.CMD_READ_INFO_2, addr, cp.ADDR_MONITOR)
        r = self._send_cmd(can_id, data, wait=True, timeout=1.0)
        if r:
            feat = cp.parse_info2_response(r[1])
            if feat:
                self._log(f"  特征字: {feat.get('raw', '')}  供电: {feat.get('power_supply', '')}  "
                          f"相数: {feat.get('ac_phase', '')}  额定电流: {feat.get('rated_current', '')}", "#1B2430")

        time.sleep(0.05)

        # 0x36-0x37: 制造商ID
        mfr_id = ""
        for cmd in [cp.CMD_READ_INFO_7, cp.CMD_READ_INFO_8]:
            can_id, data = cp.cmd_read_info(cmd, addr, cp.ADDR_MONITOR)
            r = self._send_cmd(can_id, data, wait=True, timeout=1.0)
            if r:
                mfr_id += cp.parse_sn_response(r[1])
            time.sleep(0.05)
        if mfr_id:
            self._log(f"  制造商ID: {mfr_id}", "#1B2430")

        self._log("模块信息读取完成", "#0B7A76")

        # 恢复轮询
        if self.auto_poll_check.isChecked():
            self.poll_timer.start(self.poll_interval_spin.value())
        self.single_poll_timer.start(200)

    def _on_read_sn(self):
        """读取所有在线模块的型号、SN和版本号, 显示在表格中"""
        online_addrs = [a for a in range(1, 64) if self.modules[a].online]
        if not online_addrs:
            QMessageBox.warning(self, "提示", "没有在线模块, 请先连接并扫描!")
            return

        self._log(f"读取 {len(online_addrs)} 个在线模块信息...", "#89b4fa")

        # 暂停轮询, 防止响应干扰
        self.poll_timer.stop()
        self.single_poll_timer.stop()

        for addr in online_addrs:
            model_name, sn, sw_version = self._read_module_info(addr)
            self._log(f"  [0x{addr:02X}] 型号: {model_name}  SN: {sn}  版本: {sw_version}", "#1B2430")

        self._refresh_info_table(online_addrs)
        self._log(f"信息读取完成, 共 {len(online_addrs)} 个模块", "#0B7A76")

        # 恢复轮询
        if self.auto_poll_check.isChecked():
            self.poll_timer.start(self.poll_interval_spin.value())
        self.single_poll_timer.start(200)

    # ============================================================
    # 日志 & 关闭
    # ============================================================

    def _save_log(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", "", "Text Files (*.txt);;All Files (*)")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toPlainText())
            self._log(f"日志已保存: {path}", "#0B7A76")

    def closeEvent(self, event):
        try:
            self.single_poll_timer.stop()
            self.poll_timer.stop()
            # 停止扫描定时器
            scan_t = getattr(self, "_scan_timer", None)
            if scan_t is not None:
                try:
                    scan_t.stop()
                except Exception:
                    pass
            if self.recv_thread:
                self.recv_thread.stop()
                self.recv_thread.wait(500)   # 等待接收线程退出，避免残留
            self.driver.disconnect()
            event.accept()
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass


