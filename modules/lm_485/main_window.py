"""
联明485通讯控制上位机 - 主窗口

基于联明标准ModBus通信协议V02的RS485通讯控制软件。
界面参考工业控制上位机风格, 统一浅色主题。
新增功能: 更改模块源地址(寄存器0x0007)。
"""

from dataclasses import dataclass, field
from datetime import datetime

from modules.theme_util import expand_qss
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QTextEdit, QGroupBox, QSplitter, QFrame,
    QDialog, QDialogButtonBox, QMessageBox, QFileDialog,
    QProgressBar, QApplication, QButtonGroup, QRadioButton,
)

from . import modbus_rtu
from .serial_thread import SerialWorker, PollingManager, ScanManager, list_available_ports
from .network_thread import NetworkWorker


DARK_STYLESHEET = """
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


@dataclass
class ModuleData:
    """模块数据模型"""
    addr: int
    online: bool = False
    power_on: bool = False
    voltage: float = 0.0
    current: float = 0.0
    set_voltage: float = 0.0
    temperature: int = 0
    status: int = 0
    fault: str = ""
    last_seen: float = 0.0


class ChangeAddrDialog(QDialog):
    """更改模块地址对话框"""

    def __init__(self, parent, old_addr: int):
        super().__init__(parent)
        self.setWindowTitle("更改模块地址")
        self.setMinimumWidth(380)
        self.old_addr = old_addr
        self.new_addr = old_addr
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(f"当前模块地址: 0x{self.old_addr:02X} ({self.old_addr})")
        info.setStyleSheet("font-size: 15px; font-weight: bold; color: #4F46E5;")
        layout.addWidget(info)

        layout.addSpacing(10)

        hint = QLabel("请输入新地址 (范围: 0x01 ~ 0xF7, 十进制 1~247)")
        hint.setStyleSheet("color: #6B7280;")
        layout.addWidget(hint)

        input_layout = QHBoxLayout()

        self.spin_dec = QSpinBox()
        self.spin_dec.setRange(1, 247)
        self.spin_dec.setValue(self.old_addr)
        self.spin_dec.setSuffix(" (十进制)")
        self.spin_dec.valueChanged.connect(self._on_dec_changed)
        input_layout.addWidget(self.spin_dec)

        self.spin_hex = QSpinBox()
        self.spin_hex.setRange(1, 247)
        self.spin_hex.setValue(self.old_addr)
        self.spin_hex.setDisplayIntegerBase(16)
        self.spin_hex.setPrefix("0x")
        self.spin_hex.valueChanged.connect(self._on_hex_changed)
        input_layout.addWidget(self.spin_hex)

        layout.addLayout(input_layout)

        layout.addSpacing(10)

        warn = QLabel("注意: 更改地址后, 原地址将变为离线, 新地址变为在线。\n"
                       "请确保新地址在总线上未被占用。")
        warn.setStyleSheet("color: #B45309; font-size: 12px;")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        layout.addSpacing(10)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("更改地址")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_dec_changed(self, val):
        self.spin_hex.blockSignals(True)
        self.spin_hex.setValue(val)
        self.spin_hex.blockSignals(False)

    def _on_hex_changed(self, val):
        self.spin_dec.blockSignals(True)
        self.spin_dec.setValue(val)
        self.spin_dec.blockSignals(False)

    def _on_accept(self):
        self.new_addr = self.spin_dec.value()
        if self.new_addr == self.old_addr:
            QMessageBox.warning(self, "提示", "新地址与当前地址相同!")
            return
        msgbox = QMessageBox(self)
        msgbox.setWindowTitle("确认更改")
        msgbox.setText(f"确定将模块地址从 0x{self.old_addr:02X} 更改为 0x{self.new_addr:02X}?")
        msgbox.setIcon(QMessageBox.Question)
        btn_yes = msgbox.addButton("是", QMessageBox.AcceptRole)
        msgbox.addButton("否", QMessageBox.RejectRole)
        msgbox.exec_()
        if msgbox.clickedButton() is btn_yes:
            self.accept()

    def get_new_addr(self) -> int:
        return self.new_addr


class MainWindow(QMainWindow):
    """主窗口"""

    # 表格列定义
    COL_CHECK = 0
    COL_ADDR = 1
    COL_ONLINE = 2
    COL_POWER = 3
    COL_VOLTAGE = 4
    COL_CURRENT = 5
    COL_SET_VOLTAGE = 6
    COL_TEMP = 7
    COL_FAULT = 8
    COL_BTN_ON = 9
    COL_BTN_OFF = 10
    COL_BTN_SET = 11
    COL_BTN_ADDR = 12

    COL_COUNT = 13
    MAX_ADDR = 0xF7  # 247

    def __init__(self):
        super().__init__()
        self.setWindowTitle("联明485通讯控制上位机 V1.0")
        self.setMinimumSize(1400, 900)
        self.resize(1500, 950)
        self.setStyleSheet(expand_qss(DARK_STYLESHEET))

        self.modules = {}  # {addr: ModuleData}
        for addr in range(1, self.MAX_ADDR + 1):
            self.modules[addr] = ModuleData(addr=addr)

        self.current_addr = 1
        self.online_set = set()
        self._timeout_counters = {}  # {addr: consecutive_timeout_count}

        # 双工作线程: 串口直连 和 网络TCP(UT-6816串口服务器)
        self._serial_worker = SerialWorker()
        self._network_worker = NetworkWorker()
        self.serial_worker = self._serial_worker  # 当前激活的worker
        self.polling = PollingManager(self.serial_worker)
        self.scanner = ScanManager(self.serial_worker)

        self._init_ui()
        self._connect_signals()
        self._refresh_port_list()

        self._serial_worker.start()
        self._network_worker.start()

        self._status_check_timer = QTimer()
        self._status_check_timer.timeout.connect(self._check_online_status)
        self._status_check_timer.start(3000)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(8, 8, 8, 8)

        main_layout.addWidget(self._create_connection_bar())
        main_layout.addWidget(self._create_batch_ops())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._create_monitor_table())
        splitter.addWidget(self._create_right_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([950, 400])
        main_layout.addWidget(splitter, stretch=1)

        main_layout.addWidget(self._create_log_panel())

    def _create_connection_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("connBar")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)
        layout = QHBoxLayout()   # 行1：链路参数（串口/网络模式），分行保证内容可自适应收缩
        outer.addLayout(layout)

        # ====== 连接模式切换: 串口直连 / 网络TCP(UT-6816) ======
        self.rb_serial = QRadioButton("串口直连")
        self.rb_serial.setChecked(True)
        self.rb_serial.toggled.connect(self._on_conn_mode_changed)
        layout.addWidget(self.rb_serial)

        self.rb_network = QRadioButton("网络TCP(UT-6816)")
        self.rb_network.toggled.connect(self._on_conn_mode_changed)
        layout.addWidget(self.rb_network)

        self._conn_mode_group = QButtonGroup(self)
        self._conn_mode_group.addButton(self.rb_serial)
        self._conn_mode_group.addButton(self.rb_network)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #D0D5DD;")
        layout.addWidget(sep1)
        layout.addSpacing(5)

        # ====== 串口直连控件 ======
        self.lbl_port = QLabel("串口:")
        layout.addWidget(self.lbl_port)
        self.combo_port = QComboBox()
        self.combo_port.setMinimumWidth(140)
        layout.addWidget(self.combo_port)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setMaximumWidth(60)
        self.btn_refresh.clicked.connect(self._refresh_port_list)
        layout.addWidget(self.btn_refresh)

        layout.addSpacing(10)
        self.lbl_baud = QLabel("波特率:")
        layout.addWidget(self.lbl_baud)
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.combo_baud.setCurrentText("9600")
        self.combo_baud.setMaximumWidth(90)
        layout.addWidget(self.combo_baud)

        layout.addSpacing(5)
        format_label = QLabel("格式: 8-N-1")
        format_label.setStyleSheet("color: #6B7280;")
        layout.addWidget(format_label)

        layout.addSpacing(5)
        self.chk_rts = QCheckBox("RS485 RTS控制")
        self.chk_rts.setToolTip("部分USB转RS485适配器需要RTS信号控制收发方向\n"
                                 "如果扫描不到模块, 请尝试勾选此项")
        layout.addWidget(self.chk_rts)

        self.combo_rts_polarity = QComboBox()
        self.combo_rts_polarity.addItem("RTS高发送", True)
        self.combo_rts_polarity.addItem("RTS低发送", False)
        self.combo_rts_polarity.setToolTip("RTS信号的有效电平极性\n不同适配器可能不同, 扫描不到时尝试切换")
        self.combo_rts_polarity.setMaximumWidth(100)
        layout.addWidget(self.combo_rts_polarity)

        # ====== 行2：网络参数 / 连接 / 轮询 / 状态 ======
        layout = QHBoxLayout()
        outer.addLayout(layout)

        # 网络TCP控件 (UT-6816串口服务器)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #D0D5DD;")
        layout.addWidget(sep2)
        layout.addSpacing(5)

        self.lbl_net_ip = QLabel("服务器IP:")
        layout.addWidget(self.lbl_net_ip)
        self.edit_net_ip = QLineEdit("192.168.1.125")
        self.edit_net_ip.setFixedWidth(160)
        self.edit_net_ip.setPlaceholderText("如 192.168.1.125")
        self.edit_net_ip.setToolTip("UT-6816串口服务器IP地址\n默认: 192.168.1.125")
        layout.addWidget(self.edit_net_ip)

        self.lbl_net_port = QLabel("端口:")
        layout.addWidget(self.lbl_net_port)
        self.spin_net_port = QSpinBox()
        self.spin_net_port.setRange(1, 65535)
        self.spin_net_port.setValue(10010)
        self.spin_net_port.setFixedWidth(90)
        self.spin_net_port.setToolTip("UT-6816串口服务器TCP端口\n串口1默认: 10010\n串口N: 10009+N")
        layout.addWidget(self.spin_net_port)

        layout.addSpacing(5)
        self.chk_byte_order = QCheckBox("低字节在前(小端)")
        self.chk_byte_order.setToolTip("寄存器数据字节序切换\n标准Modbus为高字节在前(大端)\n部分模块使用低字节在前(小端)\n电压值不对时尝试切换")
        layout.addWidget(self.chk_byte_order)

        layout.addSpacing(15)
        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.clicked.connect(self._on_connect)
        layout.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setObjectName("btnDisconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        layout.addWidget(self.btn_disconnect)

        layout.addSpacing(20)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #D0D5DD;")
        layout.addWidget(sep)
        layout.addSpacing(10)

        self.chk_poll = QCheckBox("自动轮询在线模块")
        self.chk_poll.toggled.connect(self._on_poll_toggled)
        layout.addWidget(self.chk_poll)

        layout.addWidget(QLabel("间隔:"))
        self.spin_poll_interval = QSpinBox()
        self.spin_poll_interval.setRange(100, 10000)
        self.spin_poll_interval.setValue(500)
        self.spin_poll_interval.setSuffix(" ms")
        self.spin_poll_interval.setMaximumWidth(100)
        self.spin_poll_interval.valueChanged.connect(self._on_poll_interval_changed)
        layout.addWidget(self.spin_poll_interval)

        layout.addStretch()

        self.lbl_online_count = QLabel("在线: 0")
        self.lbl_online_count.setObjectName("lblOnline")
        layout.addWidget(self.lbl_online_count)

        layout.addSpacing(15)
        self.lbl_conn_status = QLabel("未连接")
        self.lbl_conn_status.setObjectName("lblOffline")
        layout.addWidget(self.lbl_conn_status)

        return frame

    def _create_batch_ops(self) -> QWidget:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 4, 10, 4)

        self.btn_all_on = QPushButton("全部开机")
        self.btn_all_on.setObjectName("btnPowerOn")
        self.btn_all_on.clicked.connect(self._on_all_power_on)
        layout.addWidget(self.btn_all_on)

        self.btn_all_off = QPushButton("全部关机")
        self.btn_all_off.setObjectName("btnPowerOff")
        self.btn_all_off.clicked.connect(self._on_all_power_off)
        layout.addWidget(self.btn_all_off)

        layout.addSpacing(20)

        layout.addWidget(QLabel("批量电压(V):"))
        self.spin_batch_voltage = QDoubleSpinBox()
        self.spin_batch_voltage.setRange(0.0, 9999.9)
        self.spin_batch_voltage.setDecimals(1)
        self.spin_batch_voltage.setValue(500.0)
        self.spin_batch_voltage.setMaximumWidth(100)
        layout.addWidget(self.spin_batch_voltage)

        self.btn_batch_set = QPushButton("批量设置电压")
        self.btn_batch_set.setObjectName("btnSetVI")
        self.btn_batch_set.clicked.connect(self._on_batch_set_voltage)
        layout.addWidget(self.btn_batch_set)

        layout.addStretch()

        self.btn_test = QPushButton("测试通信")
        self.btn_test.setObjectName("btnScan")
        self.btn_test.clicked.connect(self._on_test_comm)
        layout.addWidget(self.btn_test)

        self.btn_reg_debug = QPushButton("寄存器调试")
        self.btn_reg_debug.setObjectName("btnScan")
        self.btn_reg_debug.clicked.connect(self._on_reg_debug)
        layout.addWidget(self.btn_reg_debug)

        self.btn_init = QPushButton("一键初始化")
        self.btn_init.setObjectName("btnInit")
        self.btn_init.clicked.connect(self._on_init)
        layout.addWidget(self.btn_init)

        layout.addWidget(QLabel("扫描范围:"))
        self.spin_scan_start = QSpinBox()
        self.spin_scan_start.setRange(1, 247)
        self.spin_scan_start.setValue(1)
        self.spin_scan_start.setPrefix("0x")
        self.spin_scan_start.setDisplayIntegerBase(16)
        self.spin_scan_start.setMaximumWidth(75)
        layout.addWidget(self.spin_scan_start)

        layout.addWidget(QLabel("~"))
        self.spin_scan_end = QSpinBox()
        self.spin_scan_end.setRange(1, 247)
        self.spin_scan_end.setValue(0x3F)
        self.spin_scan_end.setPrefix("0x")
        self.spin_scan_end.setDisplayIntegerBase(16)
        self.spin_scan_end.setMaximumWidth(75)
        layout.addWidget(self.spin_scan_end)

        self.btn_scan = QPushButton("扫描在线模块")
        self.btn_scan.setObjectName("btnScan")
        self.btn_scan.clicked.connect(self._on_scan)
        layout.addWidget(self.btn_scan)

        self.btn_fault_codes = QPushButton("故障代码查询")
        self.btn_fault_codes.clicked.connect(self._on_show_fault_codes)
        layout.addWidget(self.btn_fault_codes)

        return frame

    def _create_monitor_table(self) -> QWidget:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        title_bar = QHBoxLayout()
        title = QLabel("模块实时监控（地址 0x01~0xF7）")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #aaaacc;")
        title_bar.addWidget(title)
        title_bar.addStretch()

        self.lbl_current_module = QLabel("当前模块: 无")
        self.lbl_current_module.setStyleSheet("color: #6B7280;")
        title_bar.addWidget(self.lbl_current_module)

        self.lbl_selected = QLabel("已选: 0")
        self.lbl_selected.setStyleSheet("color: #6B7280;")
        title_bar.addWidget(self.lbl_selected)
        layout.addLayout(title_bar)

        btn_bar = QHBoxLayout()
        for text, slot in [
            ("全选", self._select_all),
            ("清空", self._clear_selection),
            ("仅在线", self._select_online_only),
        ]:
            btn = QPushButton(text)
            btn.setMaximumWidth(80)
            btn.clicked.connect(slot)
            btn_bar.addWidget(btn)

        self.btn_sel_on = QPushButton("选中开机")
        self.btn_sel_on.setObjectName("btnPowerOn")
        self.btn_sel_on.setMaximumWidth(90)
        self.btn_sel_on.clicked.connect(self._on_selected_power_on)
        btn_bar.addWidget(self.btn_sel_on)

        self.btn_sel_off = QPushButton("选中关机")
        self.btn_sel_off.setObjectName("btnPowerOff")
        self.btn_sel_off.setMaximumWidth(90)
        self.btn_sel_off.clicked.connect(self._on_selected_power_off)
        btn_bar.addWidget(self.btn_sel_off)

        self.btn_sel_set = QPushButton("选中设置电压")
        self.btn_sel_set.setObjectName("btnSetVI")
        self.btn_sel_set.setMaximumWidth(110)
        self.btn_sel_set.clicked.connect(self._on_selected_set_voltage)
        btn_bar.addWidget(self.btn_sel_set)

        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        self.table = QTableWidget(self.MAX_ADDR, self.COL_COUNT)
        self.table.setHorizontalHeaderLabels([
            "选", "地址", "在线", "电源", "电压(V)", "电流(A)",
            "设置电压(V)", "温度(°C)", "故障",
            "开机", "关机", "设置", "改地址",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        widths = [45, 60, 55, 55, 75, 75, 85, 65, 110, 55, 55, 55, 65]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        header.setSectionResizeMode(self.COL_FAULT, QHeaderView.Stretch)

        self.table.cellClicked.connect(self._on_table_cell_clicked)

        self._populate_table()
        layout.addWidget(self.table)

        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        self.scan_progress.setMaximumHeight(16)
        layout.addWidget(self.scan_progress)

        return frame

    def _populate_table(self):
        """填充表格初始数据"""
        self._sv_spins = {}
        for i in range(self.MAX_ADDR):
            addr = i + 1

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Unchecked)
            chk_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, self.COL_CHECK, chk_item)

            addr_item = QTableWidgetItem(f"0x{addr:02X}")
            addr_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, self.COL_ADDR, addr_item)

            for col in [self.COL_ONLINE, self.COL_POWER, self.COL_VOLTAGE,
                        self.COL_CURRENT, self.COL_TEMP, self.COL_FAULT]:
                item = QTableWidgetItem("---")
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, col, item)

            # 设置电压：行内可编辑输入框（485 协议仅支持电压设定）
            sv = QDoubleSpinBox()
            sv.setRange(0, 1200)
            sv.setDecimals(1)
            sv.setSingleStep(0.5)
            sv.setMinimumWidth(78)
            sv.valueChanged.connect(lambda _v, w=sv: setattr(w, "_user_edited", True))
            self.table.setCellWidget(i, self.COL_SET_VOLTAGE, sv)
            self._sv_spins[addr] = sv

            btn_on = QPushButton("开")
            btn_on.setObjectName("btnPowerOn")
            btn_on.setFixedWidth(45)
            btn_on.clicked.connect(lambda _, a=addr: self._on_module_power_on(a))
            self.table.setCellWidget(i, self.COL_BTN_ON, btn_on)

            btn_off = QPushButton("关")
            btn_off.setObjectName("btnPowerOff")
            btn_off.setFixedWidth(45)
            btn_off.clicked.connect(lambda _, a=addr: self._on_module_power_off(a))
            self.table.setCellWidget(i, self.COL_BTN_OFF, btn_off)

            btn_set = QPushButton("设置")
            btn_set.setObjectName("btnSetVI")
            btn_set.setFixedWidth(50)
            btn_set.clicked.connect(lambda _, a=addr: self._on_module_set_voltage(a))
            self.table.setCellWidget(i, self.COL_BTN_SET, btn_set)

            btn_addr = QPushButton("改地址")
            btn_addr.setObjectName("btnChangeAddr")
            btn_addr.setFixedWidth(60)
            btn_addr.clicked.connect(lambda _, a=addr: self._on_change_addr(a))
            self.table.setCellWidget(i, self.COL_BTN_ADDR, btn_addr)

    def _create_right_panel(self) -> QWidget:
        container = QWidget()
        container.setMaximumWidth(420)
        container.setMinimumWidth(350)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()

        self.tab_widget.addTab(self._create_module_control_tab(), "模块控制")
        self.tab_widget.addTab(self._create_addr_change_tab(), "地址更改")
        self.tab_widget.addTab(self._create_init_tab(), "初始化配置")
        self.tab_widget.addTab(self._create_info_tab(), "模块信息")

        layout.addWidget(self.tab_widget)
        return container

    def _create_module_control_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # 输出电压设定
        grp_vi = QGroupBox("输出电压设定 (寄存器 0x0006)")
        vi_layout = QVBoxLayout(grp_vi)

        row = QHBoxLayout()
        row.addWidget(QLabel("设定电压(V):"))
        self.spin_set_voltage = QDoubleSpinBox()
        self.spin_set_voltage.setRange(0.0, 9999.9)
        self.spin_set_voltage.setDecimals(1)
        self.spin_set_voltage.setValue(500.0)
        self.spin_set_voltage.setMaximumWidth(120)
        row.addWidget(self.spin_set_voltage)
        row.addStretch()
        vi_layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.btn_set_vi = QPushButton("设定电压")
        self.btn_set_vi.setObjectName("btnSetVI")
        self.btn_set_vi.clicked.connect(self._on_set_voltage_current)
        btn_row.addWidget(self.btn_set_vi)

        self.btn_set_vi_all = QPushButton("应用到全部模块(广播)")
        self.btn_set_vi_all.setObjectName("btnSetVI")
        self.btn_set_vi_all.clicked.connect(self._on_set_voltage_broadcast)
        btn_row.addWidget(self.btn_set_vi_all)
        vi_layout.addLayout(btn_row)

        layout.addWidget(grp_vi)

        # 开关控制
        grp_sw = QGroupBox("开关控制 (线圈 0x0005)")
        sw_layout = QGridLayout(grp_sw)

        self.btn_sw_on = QPushButton("开机")
        self.btn_sw_on.setObjectName("btnPowerOn")
        self.btn_sw_on.clicked.connect(lambda: self._on_module_power_on(self.current_addr))
        sw_layout.addWidget(self.btn_sw_on, 0, 0)

        self.btn_sw_off = QPushButton("关机")
        self.btn_sw_off.setObjectName("btnPowerOff")
        self.btn_sw_off.clicked.connect(lambda: self._on_module_power_off(self.current_addr))
        sw_layout.addWidget(self.btn_sw_off, 0, 1)

        self.btn_sw_all_on = QPushButton("全部开机")
        self.btn_sw_all_on.setObjectName("btnPowerOn")
        self.btn_sw_all_on.clicked.connect(self._on_all_power_on)
        sw_layout.addWidget(self.btn_sw_all_on, 1, 0)

        self.btn_sw_all_off = QPushButton("全部关机")
        self.btn_sw_all_off.setObjectName("btnPowerOff")
        self.btn_sw_all_off.clicked.connect(self._on_all_power_off)
        sw_layout.addWidget(self.btn_sw_all_off, 1, 1)

        layout.addWidget(grp_sw)

        # 实时数据
        grp_rt = QGroupBox("选中模块实时数据")
        rt_layout = QGridLayout(grp_rt)

        self.lbl_rt_addr = self._make_data_label("地址: ---")
        self.lbl_rt_voltage = self._make_data_label("电压: --- V")
        self.lbl_rt_current = self._make_data_label("电流: --- A")
        self.lbl_rt_temp = self._make_data_label("温度: --- ℃")
        self.lbl_rt_power = self._make_data_label("电源: ---")
        self.lbl_rt_fault = self._make_data_label("故障: ---")

        rt_layout.addWidget(self.lbl_rt_addr, 0, 0)
        rt_layout.addWidget(self.lbl_rt_voltage, 0, 1)
        rt_layout.addWidget(self.lbl_rt_current, 1, 0)
        rt_layout.addWidget(self.lbl_rt_temp, 1, 1)
        rt_layout.addWidget(self.lbl_rt_power, 2, 0)
        rt_layout.addWidget(self.lbl_rt_fault, 2, 1)

        layout.addWidget(grp_rt)

        # 电压校准
        grp_cal = QGroupBox("电压校准")
        cal_layout = QHBoxLayout(grp_cal)
        cal_layout.addWidget(QLabel("增益:"))
        self.spin_v_gain = QDoubleSpinBox()
        self.spin_v_gain.setRange(0.500, 2.000)
        self.spin_v_gain.setDecimals(3)
        self.spin_v_gain.setSingleStep(0.001)
        self.spin_v_gain.setValue(1.000)
        cal_layout.addWidget(self.spin_v_gain)
        cal_layout.addWidget(QLabel("偏移:"))
        self.spin_v_offset = QDoubleSpinBox()
        self.spin_v_offset.setRange(-50.0, 50.0)
        self.spin_v_offset.setDecimals(2)
        self.spin_v_offset.setSingleStep(0.01)
        self.spin_v_offset.setValue(0.00)
        cal_layout.addWidget(self.spin_v_offset)
        cal_layout.addStretch()
        layout.addWidget(grp_cal)

        layout.addStretch()

        return tab

    def _create_addr_change_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("更改模块源地址")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #B45309;")
        layout.addWidget(title)

        desc = QLabel("通过寄存器 0x0007 (功能码 0x06) 修改模块的通信地址。\n"
                      "新地址范围: 0x01 ~ 0xF7 (十进制 1~247)")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6B7280; font-size: 12px;")
        layout.addWidget(desc)

        layout.addSpacing(10)

        # 当前地址显示
        grp_current = QGroupBox("当前模块")
        cur_layout = QGridLayout(grp_current)
        cur_layout.addWidget(QLabel("选中地址:"), 0, 0)
        self.lbl_cur_addr = QLabel("0x01")
        self.lbl_cur_addr.setStyleSheet("font-size: 16px; font-weight: bold; color: #4F46E5;")
        cur_layout.addWidget(self.lbl_cur_addr, 0, 1)

        self.btn_read_addr = QPushButton("读取当前地址")
        self.btn_read_addr.setObjectName("btnSetVI")
        self.btn_read_addr.clicked.connect(self._on_read_current_addr)
        cur_layout.addWidget(self.btn_read_addr, 1, 0, 1, 2)

        self.lbl_read_addr_result = QLabel("读取结果: ---")
        self.lbl_read_addr_result.setStyleSheet("color: #6B7280;")
        cur_layout.addWidget(self.lbl_read_addr_result, 2, 0, 1, 2)

        layout.addWidget(grp_current)

        # 新地址输入
        grp_new = QGroupBox("设置新地址")
        new_layout = QGridLayout(grp_new)

        new_layout.addWidget(QLabel("新地址(十进制):"), 0, 0)
        self.spin_new_addr_dec = QSpinBox()
        self.spin_new_addr_dec.setRange(1, 247)
        self.spin_new_addr_dec.setValue(2)
        self.spin_new_addr_dec.valueChanged.connect(self._on_new_addr_dec_changed)
        new_layout.addWidget(self.spin_new_addr_dec, 0, 1)

        new_layout.addWidget(QLabel("新地址(十六进制):"), 1, 0)
        self.spin_new_addr_hex = QSpinBox()
        self.spin_new_addr_hex.setRange(1, 247)
        self.spin_new_addr_hex.setValue(2)
        self.spin_new_addr_hex.setDisplayIntegerBase(16)
        self.spin_new_addr_hex.setPrefix("0x")
        self.spin_new_addr_hex.valueChanged.connect(self._on_new_addr_hex_changed)
        new_layout.addWidget(self.spin_new_addr_hex, 1, 1)

        self.btn_change_addr = QPushButton("确认更改地址")
        self.btn_change_addr.setObjectName("btnChangeAddr")
        self.btn_change_addr.setMinimumHeight(36)
        self.btn_change_addr.clicked.connect(self._on_change_addr_current)
        new_layout.addWidget(self.btn_change_addr, 2, 0, 1, 2)

        self.lbl_change_result = QLabel("")
        self.lbl_change_result.setWordWrap(True)
        new_layout.addWidget(self.lbl_change_result, 3, 0, 1, 2)

        layout.addWidget(grp_new)

        layout.addStretch()

        return tab

    def _create_init_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        grp = QGroupBox("默认输出电压设定 (寄存器 0x0010)")
        grp_layout = QVBoxLayout(grp)

        row = QHBoxLayout()
        row.addWidget(QLabel("默认电压(V):"))
        self.spin_default_voltage = QDoubleSpinBox()
        self.spin_default_voltage.setRange(0.0, 9999.9)
        self.spin_default_voltage.setDecimals(1)
        self.spin_default_voltage.setValue(500.0)
        self.spin_default_voltage.setMaximumWidth(120)
        row.addWidget(self.spin_default_voltage)
        row.addStretch()
        grp_layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.btn_set_default = QPushButton("设定默认电压")
        self.btn_set_default.setObjectName("btnSetVI")
        self.btn_set_default.clicked.connect(self._on_set_default_voltage)
        btn_row.addWidget(self.btn_set_default)

        self.btn_set_default_all = QPushButton("广播设定")
        self.btn_set_default_all.setObjectName("btnSetVI")
        self.btn_set_default_all.clicked.connect(self._on_set_default_voltage_broadcast)
        btn_row.addWidget(self.btn_set_default_all)
        grp_layout.addLayout(btn_row)

        layout.addWidget(grp)

        # 一键初始化
        grp2 = QGroupBox("一键初始化")
        g2_layout = QVBoxLayout(grp2)
        hint = QLabel("对当前选中的模块执行初始化操作:\n"
                      "1. 关机  2. 设定默认电压  3. 开机")
        hint.setStyleSheet("color: #6B7280; font-size: 12px;")
        hint.setWordWrap(True)
        g2_layout.addWidget(hint)

        self.btn_init_current = QPushButton("初始化当前模块")
        self.btn_init_current.setObjectName("btnInit")
        self.btn_init_current.setMinimumHeight(36)
        self.btn_init_current.clicked.connect(self._on_init_current)
        g2_layout.addWidget(self.btn_init_current)
        layout.addWidget(grp2)

        layout.addStretch()
        return tab

    def _create_info_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("模块详细信息")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #aaaacc;")
        layout.addWidget(title)

        self.info_labels = {}
        info_items = [
            ("地址", "---"),
            ("在线状态", "---"),
            ("电源状态", "---"),
            ("输出电压", "--- V"),
            ("输出电流", "--- A"),
            ("设定电压", "--- V"),
            ("温度", "--- ℃"),
            ("电源开关位", "---"),
            ("输出正常", "---"),
            ("输入正常", "---"),
            ("风扇1", "---"),
            ("风扇2", "---"),
            ("输出过流", "---"),
            ("输出过压", "---"),
            ("前级故障", "---"),
            ("EEP故障", "---"),
            ("过温故障", "---"),
            ("硬件开关机", "---"),
            ("通信使能开关", "---"),
        ]
        for name, default in info_items:
            row = QHBoxLayout()
            lbl_name = QLabel(name + ":")
            lbl_name.setMinimumWidth(100)
            lbl_name.setStyleSheet("color: #6B7280;")
            lbl_val = QLabel(default)
            lbl_val.setStyleSheet("color: #2A3340; font-weight: bold;")
            row.addWidget(lbl_name)
            row.addWidget(lbl_val)
            row.addStretch()
            layout.addLayout(row)
            self.info_labels[name] = lbl_val

        layout.addStretch()
        return tab

    def _create_log_panel(self) -> QWidget:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        title_bar = QHBoxLayout()
        title = QLabel("通信日志 (RS485 Modbus RTU)")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #aaaacc;")
        title_bar.addWidget(title)
        title_bar.addStretch()

        self.chk_show_tx = QCheckBox("显示发送")
        self.chk_show_tx.setChecked(True)
        title_bar.addWidget(self.chk_show_tx)

        self.chk_show_rx = QCheckBox("显示接收")
        self.chk_show_rx.setChecked(True)
        title_bar.addWidget(self.chk_show_rx)

        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        title_bar.addWidget(self.chk_auto_scroll)

        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.setMaximumWidth(60)
        self.btn_clear_log.clicked.connect(self._clear_log)
        title_bar.addWidget(self.btn_clear_log)

        self.btn_save_log = QPushButton("保存")
        self.btn_save_log.setMaximumWidth(60)
        self.btn_save_log.clicked.connect(self._save_log)
        title_bar.addWidget(self.btn_save_log)
        layout.addLayout(title_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(140)
        self.log_text.setMaximumHeight(220)
        layout.addWidget(self.log_text)

        return frame

    @staticmethod
    def _make_data_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #2A3340; padding: 2px;")
        return lbl

    def _connect_signals(self):
        # 两个worker都连接信号, 切换时自动生效
        for worker in (self._serial_worker, self._network_worker):
            worker.response_received.connect(self._on_response)
            worker.timeout_occurred.connect(self._on_timeout)
            worker.broadcast_sent.connect(self._on_broadcast_sent)
            worker.log_message.connect(self._on_log_message)
            worker.connection_changed.connect(self._on_connection_changed)
            worker.comm_error.connect(self._on_comm_error)
            worker.scan_progress.connect(self._on_scan_progress)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)

        self._scan_check_timer = QTimer()
        self._scan_check_timer.timeout.connect(self._check_scan_done)
        self._scan_check_timer.start(200)

    def _refresh_port_list(self):
        self.combo_port.clear()
        ports = list_available_ports()
        for device, desc in ports:
            self.combo_port.addItem(f"{device} - {desc}", device)
        if ports:
            self.combo_port.setCurrentIndex(0)

    # ===================== 连接管理 =====================

    def _on_conn_mode_changed(self):
        """切换连接模式: 串口直连 / 网络TCP"""
        is_serial = self.rb_serial.isChecked()
        # 串口控件可见性
        self.lbl_port.setVisible(is_serial)
        self.combo_port.setVisible(is_serial)
        self.btn_refresh.setVisible(is_serial)
        self.lbl_baud.setVisible(is_serial)
        self.combo_baud.setVisible(is_serial)
        self.chk_rts.setVisible(is_serial)
        self.combo_rts_polarity.setVisible(is_serial)
        # 网络控件可见性
        self.lbl_net_ip.setVisible(not is_serial)
        self.edit_net_ip.setVisible(not is_serial)
        self.lbl_net_port.setVisible(not is_serial)
        self.spin_net_port.setVisible(not is_serial)
        # 波特率在两种模式都需要(决定帧间延时)
        if not is_serial:
            self.lbl_baud.setVisible(True)
            self.combo_baud.setVisible(True)

    def _is_network_mode(self) -> bool:
        return self.rb_network.isChecked()

    def _on_connect(self):
        baud = int(self.combo_baud.currentText())

        if self._is_network_mode():
            # 网络TCP模式
            host = self.edit_net_ip.text().strip().rstrip("_")
            if not host or "." not in host:
                QMessageBox.warning(self, "警告", "请输入有效的服务器IP地址!")
                return
            port = self.spin_net_port.value()
            # 切换到网络worker
            self.serial_worker = self._network_worker
            self.polling.worker = self._network_worker
            self.scanner.worker = self._network_worker
            if self.serial_worker.connect_port(host, port, baudrate=baud):
                self.btn_connect.setEnabled(False)
                self.btn_connect.setText("已连接")
                self.btn_connect.setObjectName("btnConnected")
                self.btn_disconnect.setEnabled(True)
                self.rb_serial.setEnabled(False)
                self.rb_network.setEnabled(False)
                self.edit_net_ip.setEnabled(False)
                self.spin_net_port.setEnabled(False)
                self.combo_baud.setEnabled(False)
        else:
            # 串口直连模式
            port_data = self.combo_port.currentData()
            if not port_data:
                QMessageBox.warning(self, "警告", "请先选择串口!")
                return
            rts = self.chk_rts.isChecked()
            polarity = self.combo_rts_polarity.currentData()
            # 切换到串口worker
            self.serial_worker = self._serial_worker
            self.polling.worker = self._serial_worker
            self.scanner.worker = self._serial_worker
            if self.serial_worker.connect_port(port_data, baud, rts_control=rts,
                                               rts_polarity=polarity):
                self.btn_connect.setEnabled(False)
                self.btn_connect.setText("已连接")
                self.btn_connect.setObjectName("btnConnected")
                self.btn_disconnect.setEnabled(True)
                self.rb_serial.setEnabled(False)
                self.rb_network.setEnabled(False)
                self.combo_port.setEnabled(False)
                self.btn_refresh.setEnabled(False)
                self.combo_baud.setEnabled(False)
                self.chk_rts.setEnabled(False)
                self.combo_rts_polarity.setEnabled(False)

    def _on_disconnect(self):
        self.polling.stop()
        self.chk_poll.setChecked(False)
        try:
            self.serial_worker.disconnect_port()
        except Exception as e:
            # 断开异常不能阻断状态复位, 否则按钮卡「已连接」、轮询不停
            self._append_log("ERROR", f"断开时异常(已忽略): {e}")
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_disconnect.setEnabled(False)
        self.rb_serial.setEnabled(True)
        self.rb_network.setEnabled(True)
        self.combo_port.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self.combo_baud.setEnabled(True)
        self.chk_rts.setEnabled(True)
        self.combo_rts_polarity.setEnabled(True)
        self.edit_net_ip.setEnabled(True)
        self.spin_net_port.setEnabled(True)

        for addr in list(self.online_set):
            self._set_module_offline(addr)
        self.online_set.clear()
        self._update_online_count()

    def _on_connection_changed(self, connected: bool, message: str):
        if connected:
            self.lbl_conn_status.setText("已连接")
            self.lbl_conn_status.setObjectName("lblOnline")
            self.btn_connect.setText("已连接")
            self.btn_connect.setObjectName("btnConnected")
        else:
            self.lbl_conn_status.setText(message if message else "未连接")
            self.lbl_conn_status.setObjectName("lblOffline")
            self.btn_connect.setText("连接")
            self.btn_connect.setObjectName("btnConnect")
            # 连接断开时恢复UI按钮状态
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            self.combo_port.setEnabled(True)
            self.combo_baud.setEnabled(True)
            self.chk_rts.setEnabled(True)
            self.combo_rts_polarity.setEnabled(True)
        self.lbl_conn_status.setStyleSheet(
            f"color: {'#2a8b4a' if connected else '#ab3a4a'}; "
            f"font-weight: bold; font-size: 14px;"
        )

    def _on_comm_error(self, error_msg: str):
        """通信持续错误时自动处理断开"""
        self.polling.stop()
        self.chk_poll.setChecked(False)
        for addr in list(self.online_set):
            self._set_module_offline(addr)
        self.online_set.clear()
        self._update_online_count()
        QMessageBox.warning(self, "通信错误", error_msg)

    def _on_poll_toggled(self, checked: bool):
        if checked:
            if not self.serial_worker.is_connected():
                QMessageBox.warning(self, "警告", "请先连接串口!")
                self.chk_poll.setChecked(False)
                return
            self.polling.set_online_set(self.online_set)
            self.polling.start(self.spin_poll_interval.value())
        else:
            self.polling.stop()

    def _on_poll_interval_changed(self, val: int):
        if self.polling.is_active():
            self.polling.set_interval(val)

    # ===================== 批量操作 =====================

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
        """显示 LM-485 电源状态字/故障位说明"""
        lines = ["LM-485 电源状态字故障位定义 (REG_STATUS 0x0001)", ""]
        for bit in sorted(modbus_rtu.STATUS_BITS.keys()):
            name, desc = modbus_rtu.STATUS_BITS[bit]
            lines.append(f"  bit{bit:02d}: {name}  ({desc})")
        lines += ["", "说明：状态字 bit 置 1 含义见上；故障摘要可参考「故障」列。"]
        QMessageBox.information(self, "故障代码查询", "\n".join(lines))

    def _on_all_power_on(self):
        if not self._check_connected():
            return
        if not self._confirm_power_on(None, True, "确认全部开机"):
            return
        frame = modbus_rtu.build_power_on(modbus_rtu.BROADCAST_ADDR)
        self.serial_worker.enqueue_request(modbus_rtu.BROADCAST_ADDR, frame, "广播开机")
        for addr in self.online_set:
            self.modules[addr].power_on = True
            self._update_module_row(addr)
            self._refresh_module(addr, 300)

    def _on_all_power_off(self):
        if not self._check_connected():
            return
        frame = modbus_rtu.build_power_off(modbus_rtu.BROADCAST_ADDR)
        self.serial_worker.enqueue_request(modbus_rtu.BROADCAST_ADDR, frame, "广播关机")
        for addr in self.online_set:
            self.modules[addr].power_on = False
            self._update_module_row(addr)
            self._refresh_module(addr, 300)

    def _on_batch_set_voltage(self):
        if not self._check_connected():
            return
        voltage = self.spin_batch_voltage.value()
        frame = modbus_rtu.build_set_voltage(modbus_rtu.BROADCAST_ADDR, voltage, self._is_little_endian())
        self.serial_worker.enqueue_request(
            modbus_rtu.BROADCAST_ADDR, frame, f"广播设定电压 {voltage}V")
        for addr in self.online_set:
            self.modules[addr].set_voltage = voltage
            self._update_module_row(addr)
            self._refresh_module(addr, 300)
        self._append_log("INFO", f"广播设定电压为 {voltage}V")

    def _on_scan(self):
        if not self._check_connected():
            return
        if self.scanner.is_scanning():
            self.scanner.stop_scan()
            self.btn_scan.setText("扫描在线模块")
            self.scan_progress.setVisible(False)
            return

        start_addr = self.spin_scan_start.value()
        end_addr = self.spin_scan_end.value()
        if start_addr > end_addr:
            start_addr, end_addr = end_addr, start_addr

        for addr in list(self.online_set):
            self._set_module_offline(addr)
        self.online_set.clear()
        self._update_online_count()

        self.btn_scan.setText("停止扫描")
        self.scan_progress.setVisible(True)
        self.scan_progress.setRange(0, end_addr - start_addr + 1)
        self.scan_progress.setFormat("扫描中... 0/%d")
        self.scan_progress.setValue(0)

        self._append_log("INFO", f"开始扫描 0x{start_addr:02X}~0x{end_addr:02X}...")
        self.scanner.start_scan(start_addr, end_addr)

    def _on_scan_progress(self, current: int, total: int, found: int):
        self.scan_progress.setMaximum(total)
        self.scan_progress.setValue(current)
        self.scan_progress.setFormat(f"扫描中... {current}/{total} (在线: {found})")

    def _on_scan_finished(self):
        self.btn_scan.setText("扫描在线模块")
        self.scan_progress.setVisible(False)
        count = len(self.online_set)
        self._append_log("INFO", f"扫描完成, 在线 {count} 个模块")
        if count == 0:
            self._append_log("WARN", "未发现在线模块! 请检查:\n"
                                 "  1. 串口是否正确连接\n"
                                 "  2. 波特率是否为9600\n"
                                 "  3. 尝试勾选'RS485 RTS控制'后重新连接\n"
                                 "  4. 尝试切换RTS极性(高/低)后重新连接\n"
                                 "  5. 模块地址是否在扫描范围内\n"
                                 "  6. RS485总线A/B是否接反")
        else:
            self.current_addr = min(self.online_set)
            self._select_table_row(self.current_addr)
            if self.chk_poll.isChecked():
                self.polling.set_online_set(self.online_set)
            else:
                self._append_log("INFO", "提示: 开启'自动轮询'可实时刷新模块数据")
            # 扫描完成后立即读取所有在线模块的完整数据
            for addr in sorted(self.online_set):
                self.serial_worker.enqueue_request(
                    addr, modbus_rtu.build_read_all(addr), f"读取 0x{addr:02X} 全量数据")

    def _on_test_comm(self):
        """测试与当前选中地址的通信"""
        if not self._check_connected():
            return
        addr = self.current_addr
        self._append_log("INFO", f"测试通信: 向地址 0x{addr:02X} 发送全量读取请求...")
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_all(addr), "测试通信-全量读取")

    def _on_reg_debug(self):
        """寄存器调试: 逐个读取0x0000~0x0010寄存器并显示原始值"""
        if not self._check_connected():
            return
        addr = self.current_addr
        if addr not in self.online_set:
            QMessageBox.warning(self, "警告", f"模块 0x{addr:02X} 不在线!")
            return
        self._append_log("INFO", f"=== 寄存器调试 0x{addr:02X} 开始 ===")
        self._append_log("INFO", f"字节序: {'小端(低字节在前)' if self._is_little_endian() else '大端(高字节在前)'}")
        for reg_addr in range(0x0000, 0x0011):
            frame = modbus_rtu.build_read_registers(addr, reg_addr, 1)
            desc = self._reg_description(reg_addr)
            self.serial_worker.enqueue_request(
                addr, frame, f"调试-寄存器0x{reg_addr:04X}({desc})")

    @staticmethod
    def _reg_description(reg: int) -> str:
        names = {
            0x0000: "未知/保留",
            0x0001: "状态",
            0x0002: "电压",
            0x0003: "电流",
            0x0004: "温度",
            0x0005: "电源开关",
            0x0006: "设定电压",
            0x0007: "模块地址",
            0x0008: "保留",
            0x0009: "保留",
            0x000A: "保留",
            0x000B: "保留",
            0x000C: "保留",
            0x000D: "保留",
            0x000E: "保留",
            0x000F: "保留",
            0x0010: "默认电压",
        }
        return names.get(reg, "未知")

    def _check_scan_done(self):
        """检测扫描是否完成"""
        if not hasattr(self, '_was_scanning'):
            self._was_scanning = False
        is_scanning = self.scanner.is_scanning()
        if self._was_scanning and not is_scanning:
            self._on_scan_finished()
        self._was_scanning = is_scanning

    def _on_init(self):
        self._on_init_current()

    def _on_init_current(self):
        if not self._check_connected():
            return
        addr = self.current_addr
        if addr not in self.online_set:
            QMessageBox.warning(self, "警告", f"模块 0x{addr:02X} 不在线!")
            return
        voltage = self.spin_default_voltage.value()
        self._append_log("INFO", f"开始初始化模块 0x{addr:02X}")
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_power_off(addr), "初始化-关机")
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_set_voltage(addr, voltage, self._is_little_endian()), "初始化-设定电压")
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_power_on(addr), "初始化-开机")
        self._refresh_module(addr, 500)
        self._append_log("INFO", f"初始化指令已发送: 关机→设定电压{voltage}V→开机")

    # ===================== 模块操作 =====================

    def _refresh_module(self, addr: int, delay_ms: int = 200):
        """延迟刷新模块数据 (等模块处理完上一步操作)"""
        QTimer.singleShot(delay_ms, lambda: (
            self.serial_worker.enqueue_request(
                addr, modbus_rtu.build_read_all(addr), "刷新-全量读取")
            if self.serial_worker.is_connected() else None))

    def _on_module_power_on(self, addr: int):
        if not self._check_connected():
            return
        if not self._confirm_power_on([addr], False, "确认开机"):
            return
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_power_on(addr), "开机")
        self._refresh_module(addr)

    def _on_module_power_off(self, addr: int):
        if not self._check_connected():
            return
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_power_off(addr), "关机")
        self._refresh_module(addr)

    def _on_module_set_voltage(self, addr: int):
        if not self._check_connected():
            return
        # 优先读取该行输入框；无则退回右侧公共输入框
        spins = getattr(self, "_sv_spins", {})
        sv_w = spins.get(addr)
        voltage = sv_w.value() if sv_w is not None else self.spin_set_voltage.value()
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_set_voltage(addr, voltage, self._is_little_endian()), f"设定电压 {voltage}V")
        self._refresh_module(addr)

    def _on_set_voltage_current(self):
        self._on_module_set_voltage(self.current_addr)

    def _on_set_voltage_broadcast(self):
        if not self._check_connected():
            return
        voltage = self.spin_set_voltage.value()
        frame = modbus_rtu.build_set_voltage(modbus_rtu.BROADCAST_ADDR, voltage, self._is_little_endian())
        self.serial_worker.enqueue_request(modbus_rtu.BROADCAST_ADDR, frame, "广播设定电压")
        for addr in self.online_set:
            self.modules[addr].set_voltage = voltage
            self._update_module_row(addr)

    def _on_set_default_voltage(self):
        if not self._check_connected():
            return
        voltage = self.spin_default_voltage.value()
        self.serial_worker.enqueue_request(
            self.current_addr,
            modbus_rtu.build_set_default_voltage(self.current_addr, voltage, self._is_little_endian()),
            f"设定默认电压 {voltage}V")

    def _on_set_default_voltage_broadcast(self):
        if not self._check_connected():
            return
        voltage = self.spin_default_voltage.value()
        frame = modbus_rtu.build_set_default_voltage(modbus_rtu.BROADCAST_ADDR, voltage, self._is_little_endian())
        self.serial_worker.enqueue_request(modbus_rtu.BROADCAST_ADDR, frame, f"广播设定默认电压 {voltage}V")

    # ===================== 地址更改 =====================

    def _on_new_addr_dec_changed(self, val):
        self.spin_new_addr_hex.blockSignals(True)
        self.spin_new_addr_hex.setValue(val)
        self.spin_new_addr_hex.blockSignals(False)

    def _on_new_addr_hex_changed(self, val):
        self.spin_new_addr_dec.blockSignals(True)
        self.spin_new_addr_dec.setValue(val)
        self.spin_new_addr_dec.blockSignals(False)

    def _on_read_current_addr(self):
        if not self._check_connected():
            return
        addr = self.current_addr
        self.lbl_read_addr_result.setText("正在读取...")
        self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_module_addr(addr), "读取模块地址")

    def _on_change_addr(self, addr: int):
        if not self._check_connected():
            return
        dlg = ChangeAddrDialog(self, addr)
        if dlg.exec_() == QDialog.Accepted:
            new_addr = dlg.get_new_addr()
            self._do_change_addr(addr, new_addr)

    def _on_change_addr_current(self):
        old_addr = self.current_addr
        new_addr = self.spin_new_addr_dec.value()
        if old_addr == new_addr:
            self.lbl_change_result.setText("新地址与当前地址相同!")
            self.lbl_change_result.setStyleSheet("color: #ab3a4a;")
            return
        msgbox = QMessageBox(self)
        msgbox.setWindowTitle("确认更改")
        msgbox.setText(f"确定将模块地址从 0x{old_addr:02X} 更改为 0x{new_addr:02X}?")
        msgbox.setIcon(QMessageBox.Question)
        btn_yes = msgbox.addButton("是", QMessageBox.AcceptRole)
        msgbox.addButton("否", QMessageBox.RejectRole)
        msgbox.exec_()
        if msgbox.clickedButton() is btn_yes:
            self._do_change_addr(old_addr, new_addr)

    def _do_change_addr(self, old_addr: int, new_addr: int):
        if not self._check_connected():
            return
        if new_addr < 1 or new_addr > 247:
            self.lbl_change_result.setText("地址超出范围 (1~247)!")
            self.lbl_change_result.setStyleSheet("color: #ab3a4a;")
            return

        self.lbl_change_result.setText(f"正在更改 0x{old_addr:02X} -> 0x{new_addr:02X}...")
        self.lbl_change_result.setStyleSheet("color: #B45309;")

        frame = modbus_rtu.build_write_module_addr(old_addr, new_addr, self._is_little_endian())
        self.serial_worker.enqueue_request(old_addr, frame, f"更改地址 0x{old_addr:02X}→0x{new_addr:02X}")

        self._pending_addr_change = (old_addr, new_addr)
        self._addr_verify_timer = QTimer()
        self._addr_verify_timer.setSingleShot(True)
        self._addr_verify_timer.timeout.connect(lambda: self._verify_addr_change(new_addr))
        self._addr_verify_timer.start(300)

    def _verify_addr_change(self, new_addr: int):
        self.serial_worker.enqueue_request(
            new_addr, modbus_rtu.build_read_module_addr(new_addr), "验证新地址")

    # ===================== 响应处理 =====================

    def _on_response(self, addr: int, response: bytes, sent_frame: bytes):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到有效应答 = 通讯真正建立
        if len(sent_frame) < 2:
            return
        fc = sent_frame[1]
        reg = (sent_frame[2] << 8) | sent_frame[3] if len(sent_frame) >= 4 else 0

        if addr == modbus_rtu.BROADCAST_ADDR:
            return

        self._append_log("RX", f"0x{addr:02X} <- {modbus_rtu.format_bytes(response)}")

        if fc == modbus_rtu.FC_READ_HOLDING:
            ok, r_addr, r_fc, values = modbus_rtu.parse_read_response(response, little_endian=self._is_little_endian())
            if ok and values:
                self._handle_read_response(addr, reg, values)
            elif not ok and isinstance(values, int):
                self._append_log("ERROR", f"0x{addr:02X} 异常响应: 错误码 {values}")
                if addr not in self.online_set:
                    self._mark_module_online(addr)
                # 批量读取异常时自动回退到逐个寄存器读取
                if reg == modbus_rtu.REG_STATUS and len(sent_frame) >= 6:
                    qty = (sent_frame[4] << 8) | sent_frame[5]
                    if qty == 4:
                        self._append_log("INFO", f"0x{addr:02X} 不支持批量读取, 回退到逐个读取")
                        self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_status(addr), "回退-状态")
                        self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_voltage(addr), "回退-电压")
                        self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_current(addr), "回退-电流")
                        self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_temperature(addr), "回退-温度")
        elif fc in (modbus_rtu.FC_WRITE_COIL, modbus_rtu.FC_WRITE_REG):
            ok, r_addr, r_fc, r_reg, r_val = modbus_rtu.parse_write_response(response, little_endian=self._is_little_endian())
            if ok:
                self._handle_write_response(addr, fc, reg, r_val)
            elif isinstance(r_val, int) and r_val != 0:
                self._append_log("ERROR", f"0x{addr:02X} 写入异常: 错误码 {r_val}")
                if addr not in self.online_set:
                    self._mark_module_online(addr)

        self._update_module_row(addr)
        if addr == self.current_addr:
            self._update_right_panel()

    def _mark_module_online(self, addr: int):
        """标记模块为在线状态 (收到任何响应即证明模块存在)"""
        mod = self.modules[addr]
        mod.last_seen = datetime.now().timestamp()
        if not mod.online:
            mod.online = True
            self.online_set.add(addr)
            self._update_online_count()
            if self.polling.is_active():
                self.polling.set_online_set(self.online_set)
            self._append_log("INFO", f"发现模块 0x{addr:02X} 在线")
        self._timeout_counters.pop(addr, None)

    def _handle_read_response(self, addr: int, reg: int, values: list):
        mod = self.modules[addr]
        self._mark_module_online(addr)

        # 批量读取: 状态+电压+电流+温度 (寄存器0x0001~0x0004)
        if reg == modbus_rtu.REG_STATUS and len(values) >= 2:
            mod.status = values[0]
            mod.power_on = bool(values[0] & 0x0001)
            mod.fault = modbus_rtu.get_fault_summary(values[0])
            mod.voltage = values[1] / 100.0
            if len(values) >= 3:
                mod.current = values[2] / 100.0
            if len(values) >= 4:
                mod.temperature = values[3]
            status_bits = bin(values[0])
            cal_v = self._calibrated_voltage(mod.voltage)
            self._append_log("INFO",
                f"0x{addr:02X} 批量读取: "
                f"[0x0001]=0x{values[0]:04X}({values[0]}) 状态位={status_bits} "
                f"[0x0002]=0x{values[1]:04X}({values[1]})→原始{mod.voltage:.2f}V→校准{cal_v:.2f}V "
                f"[0x0003]=0x{values[2] if len(values)>=3 else 0:04X}→{mod.current:.2f}A "
                f"[0x0004]=0x{values[3] if len(values)>=4 else 0:04X}({values[3] if len(values)>=4 else '?'})")
        elif reg == modbus_rtu.REG_STATUS:
            value = values[0] if values else 0
            mod.status = value
            mod.power_on = bool(value & 0x0001)
            mod.fault = modbus_rtu.get_fault_summary(value)
        elif reg == modbus_rtu.REG_VOLTAGE:
            value = values[0] if values else 0
            mod.voltage = value / 100.0
            byte_mode = '小端' if self._is_little_endian() else '大端'
            self._append_log("INFO", f"0x{addr:02X} 电压: 原始值=0x{value:04X}({value}) /100 = {mod.voltage:.2f}V [{byte_mode}]")
        elif reg == modbus_rtu.REG_CURRENT:
            value = values[0] if values else 0
            mod.current = value / 100.0
            self._append_log("INFO", f"0x{addr:02X} 电流: 原始值=0x{value:04X}({value}) /100 = {mod.current:.2f}A")
        elif reg == modbus_rtu.REG_TEMPERATURE:
            value = values[0] if values else 0
            mod.temperature = value
            self._append_log("INFO", f"0x{addr:02X} 温度: 原始值=0x{value:04X}({value})")
        elif reg == modbus_rtu.REG_MODULE_ADDR:
            value = values[0] if values else 0
            if hasattr(self, '_pending_addr_change'):
                old_addr, expected = self._pending_addr_change
                if addr == expected and value == expected:
                    self._on_addr_change_success(old_addr, expected)
                    del self._pending_addr_change
        else:
            value = values[0] if values else 0
            self._append_log("INFO",
                f"0x{addr:02X} 寄存器0x{reg:04X}: 原始值=0x{value:04X}({value}) "
                f"/100={value/100.0:.2f} /10={value/10.0:.1f} /1000={value/1000.0:.3f}")

    def _handle_write_response(self, addr: int, fc: int, reg: int, value: int):
        mod = self.modules[addr]

        if fc == modbus_rtu.FC_WRITE_COIL and reg == modbus_rtu.REG_POWER_SWITCH:
            mod.power_on = bool(value & 0xFF00)
            self._append_log("INFO", f"0x{addr:02X} {'开机' if mod.power_on else '关机'}成功")
        elif fc == modbus_rtu.FC_WRITE_REG and reg == modbus_rtu.REG_SET_VOLTAGE:
            mod.set_voltage = value / 100.0
            self._append_log("INFO", f"0x{addr:02X} 设定电压 {mod.set_voltage}V 成功")
        elif fc == modbus_rtu.FC_WRITE_REG and reg == modbus_rtu.REG_MODULE_ADDR:
            if hasattr(self, '_pending_addr_change'):
                old_addr, new_addr = self._pending_addr_change
                if value == new_addr:
                    self._append_log("INFO", f"0x{old_addr:02X} 地址更改指令已确认, 等待验证...")
        elif fc == modbus_rtu.FC_WRITE_REG and reg == modbus_rtu.REG_DEFAULT_VOLTAGE:
            self._append_log("INFO", f"0x{addr:02X} 设定默认电压 {value/100.0}V 成功")

    def _on_addr_change_success(self, old_addr: int, new_addr: int):
        self._set_module_offline(old_addr)
        self.online_set.discard(old_addr)

        new_mod = self.modules[new_addr]
        new_mod.online = True
        new_mod.last_seen = datetime.now().timestamp()
        self.online_set.add(new_addr)
        self._update_online_count()

        if self.polling.is_active():
            self.polling.set_online_set(self.online_set)

        self.current_addr = new_addr
        self._select_table_row(new_addr)

        self.lbl_change_result.setText(
            f"地址更改成功! 0x{old_addr:02X} → 0x{new_addr:02X}")
        self.lbl_change_result.setStyleSheet("color: #2a8b4a; font-weight: bold;")
        self.lbl_read_addr_result.setText(f"读取结果: 0x{new_addr:02X} ({new_addr})")

        self._update_module_row(old_addr)
        self._update_module_row(new_addr)
        self._update_right_panel()

    def _on_timeout(self, addr: int, sent_frame: bytes):
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 响应超时 = 通讯中断
        if addr == modbus_rtu.BROADCAST_ADDR:
            return

        # 地址更改验证超时
        if hasattr(self, '_pending_addr_change'):
            old_addr, expected = self._pending_addr_change
            if addr == expected:
                self.lbl_change_result.setText(
                    f"地址更改验证失败: 新地址 0x{expected:02X} 无响应")
                self.lbl_change_result.setStyleSheet("color: #ab3a4a; font-weight: bold;")
                del self._pending_addr_change
                return

        if len(sent_frame) >= 2:
            fc = sent_frame[1]
            reg = (sent_frame[2] << 8) | sent_frame[3] if len(sent_frame) >= 4 else 0
            if fc == modbus_rtu.FC_READ_HOLDING:
                if self.scanner.is_scanning():
                    self.scan_result_handle(addr, False)
                elif addr in self.online_set:
                    # 批量读取超时: 不计为失联, 回退到逐个读取
                    if len(sent_frame) >= 6:
                        qty = (sent_frame[4] << 8) | sent_frame[5]
                        if qty == 4 and reg == modbus_rtu.REG_STATUS:
                            self._append_log("WARN", f"0x{addr:02X} 批量读取超时, 回退到逐个读取")
                            self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_status(addr), "回退-状态")
                            self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_voltage(addr), "回退-电压")
                            self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_current(addr), "回退-电流")
                            self.serial_worker.enqueue_request(addr, modbus_rtu.build_read_temperature(addr), "回退-温度")
                            return
                    count = self._timeout_counters.get(addr, 0) + 1
                    self._timeout_counters[addr] = count
                    if count >= 10:
                        self._set_module_offline(addr)
                        self.online_set.discard(addr)
                        self._update_online_count()
                        if self.polling.is_active():
                            self.polling.set_online_set(self.online_set)
                        self._timeout_counters.pop(addr, None)
                        self._append_log("WARN", f"0x{addr:02X} 连续10次无响应, 标记为离线")

    def scan_result_handle(self, addr: int, online: bool):
        if online:
            if addr not in self.online_set:
                mod = self.modules[addr]
                mod.online = True
                self.online_set.add(addr)
                self._update_online_count()
                self._update_module_row(addr)
        else:
            if addr in self.online_set:
                self._set_module_offline(addr)
                self.online_set.discard(addr)
                self._update_online_count()

    def _on_broadcast_sent(self, frame: bytes):
        pass

    def _on_timeout_check(self, addr: int):
        if addr in self.online_set:
            self._set_module_offline(addr)
            self.online_set.discard(addr)
            self._update_online_count()

    def _check_online_status(self):
        # 仅在自动轮询开启时检测模块是否失联
        # 没有轮询时, 模块数据不会自动刷新, 不应因超时清除在线状态
        if not self.polling.is_active():
            return
        now = datetime.now().timestamp()
        stale = []
        for addr in list(self.online_set):
            mod = self.modules[addr]
            if mod.last_seen and (now - mod.last_seen) > 30:
                stale.append(addr)
        for addr in stale:
            self._set_module_offline(addr)
            self.online_set.discard(addr)
            self._update_online_count()
            if self.polling.is_active():
                self.polling.set_online_set(self.online_set)

    # ===================== 表格更新 =====================

    def _update_module_row(self, addr: int):
        row = addr - 1
        if row < 0 or row >= self.MAX_ADDR:
            return
        mod = self.modules[addr]

        _ol = self.table.item(row, self.COL_ONLINE)
        _ol.setTextAlignment(Qt.AlignCenter)
        _ol.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        _ol.setText("●" if mod.online else "○")
        self.table.item(row, self.COL_ONLINE).setForeground(
            QColor("#047857") if mod.online else QColor("#9AA2AA"))

        power_text = "开机" if mod.power_on else ("关机" if mod.online else "---")
        self.table.item(row, self.COL_POWER).setText(power_text)
        self.table.item(row, self.COL_POWER).setForeground(
            QColor("#2a8b4a") if mod.power_on else
            (QColor("#ab3a4a") if mod.online else QColor("#555555")))

        self.table.item(row, self.COL_VOLTAGE).setText(
            f"{self._calibrated_voltage(mod.voltage):.1f}" if mod.online else "---")
        self.table.item(row, self.COL_CURRENT).setText(
            f"{mod.current:.1f}" if mod.online else "---")
        # 设置电压回填行内输入框（编辑中不覆盖）
        sv_w = getattr(self, "_sv_spins", {}).get(addr)
        if (sv_w is not None and mod.set_voltage > 0 and not sv_w.hasFocus()
                and not getattr(sv_w, "_user_edited", False)):
            sv_w.blockSignals(True)
            sv_w.setValue(mod.set_voltage)
            sv_w.blockSignals(False)
        self.table.item(row, self.COL_TEMP).setText(
            str(mod.temperature) if mod.online else "---")
        self.table.item(row, self.COL_FAULT).setText(
            mod.fault if mod.online and mod.fault else ("无" if mod.online else "---"))
        self.table.item(row, self.COL_FAULT).setForeground(
            QColor("#ab3a4a") if mod.fault and mod.fault != "无" else QColor("#6B7280888"))

        for col in [self.COL_BTN_ON, self.COL_BTN_OFF, self.COL_BTN_SET, self.COL_BTN_ADDR]:
            widget = self.table.cellWidget(row, col)
            if widget:
                widget.setEnabled(mod.online)

    def _set_module_offline(self, addr: int):
        mod = self.modules[addr]
        mod.online = False
        mod.power_on = False
        mod.voltage = 0.0
        mod.current = 0.0
        mod.temperature = 0
        mod.fault = ""
        self._update_module_row(addr)

    def _update_online_count(self):
        count = len(self.online_set)
        self.lbl_online_count.setText(f"在线: {count}")
        color = "#2a8b4a" if count > 0 else "#ab3a4a"
        self.lbl_online_count.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 14px;")

    # ===================== 表格选择 =====================

    def _on_table_cell_clicked(self, row, col):
        # 模块地址选中固定在勾选列（选择区域），其余列点击不可选中（规范）
        if col != self.COL_CHECK:
            return
        self.current_addr = row + 1
        self._update_right_panel()

    def _on_table_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        # 模块地址选中固定在勾选列（选择区域），其余列不可选中（规范）
        if rows and self.table.currentColumn() == self.COL_CHECK:
            self.current_addr = rows[0].row() + 1
        self._update_right_panel()
        self._update_selected_count()

    def _select_table_row(self, addr: int):
        row = addr - 1
        if 0 <= row < self.MAX_ADDR:
            self.table.selectRow(row)
            self.current_addr = addr
            self._update_right_panel()

    def _update_selected_count(self):
        count = 0
        for i in range(self.MAX_ADDR):
            item = self.table.item(i, self.COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                count += 1
        self.lbl_selected.setText(f"已选: {count}")

    def _get_selected_addresses(self) -> list:
        addrs = []
        for i in range(self.MAX_ADDR):
            item = self.table.item(i, self.COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                addrs.append(i + 1)
        return addrs

    def _select_all(self):
        for i in range(self.MAX_ADDR):
            item = self.table.item(i, self.COL_CHECK)
            if item:
                item.setCheckState(Qt.Checked)
        self._update_selected_count()

    def _clear_selection(self):
        for i in range(self.MAX_ADDR):
            item = self.table.item(i, self.COL_CHECK)
            if item:
                item.setCheckState(Qt.Unchecked)
        self._update_selected_count()

    def _select_online_only(self):
        for i in range(self.MAX_ADDR):
            item = self.table.item(i, self.COL_CHECK)
            if item:
                item.setCheckState(Qt.Checked if (i + 1) in self.online_set else Qt.Unchecked)
        self._update_selected_count()

    def _on_selected_power_on(self):
        if not self._check_connected():
            return
        addrs = self._get_selected_addresses()
        if not addrs:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        if not self._confirm_power_on(addrs, False, "确认选中开机"):
            return
        for addr in addrs:
            self.serial_worker.enqueue_request(addr, modbus_rtu.build_power_on(addr), "选中-开机")

    def _on_selected_power_off(self):
        if not self._check_connected():
            return
        for addr in self._get_selected_addresses():
            self.serial_worker.enqueue_request(addr, modbus_rtu.build_power_off(addr), "选中-关机")

    def _on_selected_set_voltage(self):
        if not self._check_connected():
            return
        voltage = self.spin_set_voltage.value()
        for addr in self._get_selected_addresses():
            self.serial_worker.enqueue_request(addr, modbus_rtu.build_set_voltage(addr, voltage, self._is_little_endian()), f"选中-设定电压 {voltage}V")

    # ===================== 右侧面板更新 =====================

    def _update_right_panel(self):
        addr = self.current_addr
        mod = self.modules[addr]

        self.lbl_current_module.setText(f"当前模块: 0x{addr:02X} ({addr})")
        self.lbl_cur_addr.setText(f"0x{addr:02X}")

        self.lbl_rt_addr.setText(f"地址: 0x{addr:02X}")
        self.lbl_rt_voltage.setText(f"电压: {self._calibrated_voltage(mod.voltage):.1f} V" if mod.online else "电压: --- V")
        self.lbl_rt_current.setText(f"电流: {mod.current:.1f} A" if mod.online else "电流: --- A")
        self.lbl_rt_temp.setText(f"温度: {mod.temperature} ℃" if mod.online else "温度: --- ℃")
        self.lbl_rt_power.setText(f"电源: {'开机' if mod.power_on else '关机'}" if mod.online else "电源: ---")
        self.lbl_rt_fault.setText(f"故障: {mod.fault}" if mod.online else "故障: ---")

        self._update_info_tab(mod)

    def _update_info_tab(self, mod: ModuleData):
        addr = mod.addr
        st = mod.status
        self.info_labels["地址"].setText(f"0x{addr:02X} ({addr})")
        self.info_labels["在线状态"].setText("在线" if mod.online else "离线")
        self.info_labels["电源状态"].setText("开机" if mod.power_on else "关机")
        self.info_labels["输出电压"].setText(f"{self._calibrated_voltage(mod.voltage):.2f} V")
        self.info_labels["输出电流"].setText(f"{mod.current:.2f} A")
        self.info_labels["设定电压"].setText(f"{mod.set_voltage:.2f} V")
        self.info_labels["温度"].setText(f"{mod.temperature} ℃")
        self.info_labels["电源开关位"].setText(str(st & 1))
        self.info_labels["输出正常"].setText("正常" if (st >> 1) & 1 else "异常")
        self.info_labels["输入正常"].setText("正常" if (st >> 2) & 1 else "异常")
        self.info_labels["风扇1"].setText("异常" if (st >> 3) & 1 else "正常")
        self.info_labels["风扇2"].setText("异常" if (st >> 4) & 1 else "正常")
        self.info_labels["输出过流"].setText("异常" if (st >> 5) & 1 else "正常")
        self.info_labels["输出过压"].setText("异常" if (st >> 6) & 1 else "正常")
        self.info_labels["前级故障"].setText("异常" if (st >> 7) & 1 else "正常")
        self.info_labels["EEP故障"].setText("异常" if (st >> 8) & 1 else "正常")
        self.info_labels["过温故障"].setText("异常" if (st >> 9) & 1 else "正常")
        self.info_labels["硬件开关机"].setText("开机" if (st >> 10) & 1 else "关机")
        self.info_labels["通信使能开关"].setText("开机" if (st >> 11) & 1 else "关机")

    # ===================== 日志 =====================

    def _on_log_message(self, log_type: str, message: str):
        if log_type == "TX" and not self.chk_show_tx.isChecked():
            return
        if log_type == "RX" and not self.chk_show_rx.isChecked():
            return
        self._append_log(log_type, message)

    def _append_log(self, log_type: str, message: str):
        if log_type == "TX" and not self.chk_show_tx.isChecked():
            return
        if log_type == "RX" and not self.chk_show_rx.isChecked():
            return

        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color_map = {
            "TX": "#0E7490",
            "RX": "#047857",
            "INFO": "#AAAAAA",
            "WARN": "#F0E68C",
            "ERROR": "#FFB6C1",
        }
        color = color_map.get(log_type, "#FFFFFF")
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(f"[{timestamp}] {log_type}: {message}\n", fmt)

        if self.chk_auto_scroll.isChecked():
            self.log_text.ensureCursorVisible()

    def _clear_log(self):
        self.log_text.clear()

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", "", "文本文件 (*.txt);;所有文件 (*.*)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toPlainText())
            self._append_log("INFO", f"日志已保存到 {path}")

    # ===================== 辅助方法 =====================

    def _check_connected(self) -> bool:
        if not self.serial_worker.is_connected():
            QMessageBox.warning(self, "警告", "请先连接串口!")
            return False
        return True

    def _is_little_endian(self) -> bool:
        return self.chk_byte_order.isChecked() if hasattr(self, 'chk_byte_order') else False

    def _calibrated_voltage(self, raw_voltage: float) -> float:
        gain = self.spin_v_gain.value() if hasattr(self, 'spin_v_gain') else 1.0
        offset = self.spin_v_offset.value() if hasattr(self, 'spin_v_offset') else 0.0
        return raw_voltage * gain + offset

    def closeEvent(self, event):
        try:
            self.polling.stop()
            self.scanner.stop_scan()
            # 停止状态检查与扫描检查定时器，避免卸载后仍在后台跑
            for attr in ("_status_check_timer", "_scan_check_timer"):
                t = getattr(self, attr, None)
                if t is not None:
                    try:
                        t.stop()
                    except Exception:
                        pass
            # 停止两个worker
            for worker in (self._serial_worker, self._network_worker):
                worker.clear_queue()
                worker._running = False
                try:
                    worker.disconnect_port()
                except Exception:
                    pass
                worker.wait(500)
            event.accept()
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass
