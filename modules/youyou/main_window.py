"""
优优绿能双向模块监控上位机 v1.0 (UT-6502 以太网-CAN)
主窗口 - 深色工业风UI
"""
from modules.theme_util import expand_qss
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QPlainTextEdit,
    QSplitter, QFrame, QGroupBox, QComboBox, QMessageBox, QProgressBar,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QDateTime
from PyQt5.QtGui import QColor, QFont, QTextCursor, QPixmap

from .module_worker import CANWorker
from .can_protocol import mode_to_str, hilo_to_str, build_can_id

MAX_MODULES = 63
COL_CHECK, COL_ADDR, COL_ONLINE, COL_POWER, COL_VOLT, COL_CURR, \
    COL_BUS, COL_SET_V, COL_SET_I, COL_MODE, COL_FAULT, \
    COL_BTN_ON, COL_BTN_OFF, COL_SET_VI = range(14)

STYLE_SHEET = """
/* 统一浅色主题 v2.5 —— 以永联风格为基调 */
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

/* ---------- 永联 style 按钮类 ---------- */
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


class ModuleTableWidget(QTableWidget):
    def __init__(self):
        super().__init__(MAX_MODULES, 14)
        self._host = None  # 宿主 MainWindow（单体嵌入后 window() 不可靠）
        self._sv = {}      # addr -> 设置电压 spinbox
        self._si = {}      # addr -> 设置电流 spinbox
        headers = ["", "地址", "在线", "电源", "电压(V)", "电流(A)",
                    "母线电压(V)", "设置电压(V)", "设置电流(A)", "模式", "故障",
                    "开机", "关机", "设置V/I"]
        self.setHorizontalHeaderLabels(headers)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        widths = [30, 55, 50, 50, 75, 75, 80, 88, 88, 70, 120, 55, 55, 60]
        for i, w in enumerate(widths):
            self.setColumnWidth(i, w)
        self.verticalHeader().setDefaultSectionSize(30)
        self.verticalHeader().hide()
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.itemClicked.connect(self._on_row_click_select)
        self.init_rows()

    def init_rows(self):
        for i in range(MAX_MODULES):
            addr = i + 1
            self.setRowHeight(i, 30)
            self.setItem(i, COL_CHECK, QTableWidgetItem())
            self.item(i, COL_CHECK).setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            self.item(i, COL_CHECK).setCheckState(Qt.Unchecked)

            self.setItem(i, COL_ADDR, QTableWidgetItem(f"0x{addr:02X}"))
            self.item(i, COL_ADDR).setTextAlignment(Qt.AlignCenter)
            _oli = QTableWidgetItem("○ 离线")
            _oli.setTextAlignment(Qt.AlignCenter)
            _oli.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
            _oli.setForeground(QColor("#9AA2AA"))
            self.setItem(i, COL_ONLINE, _oli)
            self.setItem(i, COL_POWER, QTableWidgetItem("○ 关机"))
            for col in [COL_VOLT, COL_CURR, COL_BUS, COL_MODE, COL_FAULT]:
                self.setItem(i, col, QTableWidgetItem("---"))

            # 设置电压/电流：行内可编辑输入框
            sv = QDoubleSpinBox()
            sv.setRange(0, 1200)
            sv.setDecimals(1)
            sv.setSingleStep(0.5)
            sv.setValue(0)
            sv.setMinimumWidth(80)
            self.setCellWidget(i, COL_SET_V, sv)
            self._sv[addr] = sv

            si = QDoubleSpinBox()
            si.setRange(0, 300)
            si.setDecimals(1)
            si.setSingleStep(0.5)
            si.setValue(0)
            si.setMinimumWidth(80)
            self.setCellWidget(i, COL_SET_I, si)
            self._si[addr] = si

            # 行内 开机/关机/设置 按钮
            btn_on = QPushButton("开")
            btn_on.setObjectName("btnGreen")
            btn_on.setFixedWidth(48)
            btn_on.clicked.connect(lambda _, a=addr: self._row_power(a, True))
            self.setCellWidget(i, COL_BTN_ON, btn_on)

            btn_off = QPushButton("关")
            btn_off.setObjectName("btnPink")
            btn_off.setFixedWidth(48)
            btn_off.clicked.connect(lambda _, a=addr: self._row_power(a, False))
            self.setCellWidget(i, COL_BTN_OFF, btn_off)

            btn_set = QPushButton("设置")
            btn_set.setObjectName("btnBlue")
            btn_set.setFixedWidth(54)
            btn_set.clicked.connect(lambda _, a=addr: self._row_set_vi(a))
            self.setCellWidget(i, COL_SET_VI, btn_set)

    def _on_row_click_select(self, item):
        """模块地址选中固定在勾选列，其余列点击不可选中（规范）"""
        return

    def _row_power(self, addr, on):
        if self._host is not None:
            self._host._row_power(addr, on)

    def _row_set_vi(self, addr):
        if self._host is None:
            return
        v = self._sv[addr].value() if addr in self._sv else 0.0
        i = self._si[addr].value() if addr in self._si else 0.0
        self._host._row_set_vi(addr, v, i)

    def update_module(self, addr, data):
        row = addr - 1
        if row < 0 or row >= MAX_MODULES:
            return
        self.blockSignals(True)
        online = data.get("online", False)
        _oli = QTableWidgetItem("● 在线" if online else "○ 离线")
        _oli.setTextAlignment(Qt.AlignCenter)
        _oli.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        _oli.setForeground(QColor("#047857") if online else QColor("#9AA2AA"))
        self.setItem(row, COL_ONLINE, _oli)

        power = data.get("power_on", False)
        self.setItem(row, COL_POWER, QTableWidgetItem("● 开机" if power else "○ 关机"))
        self.item(row, COL_POWER).setForeground(QColor("#047857") if power else QColor("#6B7280"))

        volt = data.get("voltage")
        self.setItem(row, COL_VOLT, QTableWidgetItem(f"{volt:.3f}" if (online and volt is not None) else "---"))
        curr = data.get("current")
        self.setItem(row, COL_CURR, QTableWidgetItem(f"{curr:.3f}" if (online and curr is not None) else "---"))
        bus = data.get("bus_voltage")
        self.setItem(row, COL_BUS, QTableWidgetItem(f"{bus:.3f}" if (online and bus is not None) else "---"))
        # 设置电压/电流：回填行内输入框（用户正在编辑时不覆盖）
        sv = data.get("set_voltage")
        sv_w = self._sv.get(addr)
        if (sv_w is not None and sv is not None
                and not sv_w.hasFocus() and not getattr(sv_w, "_user_edited", False)):
            sv_w.blockSignals(True)
            sv_w.setValue(float(sv))
            sv_w.blockSignals(False)
        si = data.get("set_current")
        si_w = self._si.get(addr)
        if (si_w is not None and si is not None
                and not si_w.hasFocus() and not getattr(si_w, "_user_edited", False)):
            si_w.blockSignals(True)
            si_w.setValue(float(si))
            si_w.blockSignals(False)

        mode = data.get("mode")
        self.setItem(row, COL_MODE, QTableWidgetItem(mode_to_str(mode) if (online and mode is not None) else "---"))

        faults = data.get("faults", [])
        indicators = data.get("indicators", [])
        if not online:
            # 离线模块: 故障栏保持 "---", 灰色, 不显示任何"正常"或故障字样
            self.setItem(row, COL_FAULT, QTableWidgetItem("---"))
            self.item(row, COL_FAULT).setForeground(QColor("#6B7280"))
        else:
            parts = []
            if faults:
                parts.append("故障: " + "; ".join(faults))
            if indicators:
                parts.append("; ".join(indicators))
            fault_text = "; ".join(parts) if parts else "正常"
            self.setItem(row, COL_FAULT, QTableWidgetItem(fault_text[:40]))
            if faults:
                self.item(row, COL_FAULT).setForeground(QColor("#F48FB1"))
            elif indicators:
                self.item(row, COL_FAULT).setForeground(QColor("#B45309"))
            else:
                self.item(row, COL_FAULT).setForeground(QColor("#047857"))
        self.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = CANWorker()
        self.worker.sig_log.connect(self.on_can_log)
        self.worker.sig_module_updated.connect(self.on_module_updated)
        self.worker.sig_connection.connect(self.on_connection)
        self.worker.sig_scan_progress.connect(self.on_scan_progress)
        self.worker.sig_scan_done.connect(self.on_scan_done)
        self.worker.sig_scan_found.connect(self.on_scan_found)
        self.worker.sig_cmd_done.connect(self.on_cmd_done)
        self.worker.start()

        self.selected_addr = None
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        self.setWindowTitle("优优绿能 双向模块监控上位机 v1.0 (UT-6502 以太网-CAN)")
        self.resize(1280, 800)
        self.setStyleSheet(expand_qss(STYLE_SHEET))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(6, 6, 6, 6)

        main_layout.addLayout(self._build_conn_bar())
        main_layout.addLayout(self._build_batch_bar())

        splitter = QSplitter(Qt.Horizontal)

        table_group = QGroupBox("模块实时监控")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(4, 12, 4, 4)

        ctrl_bar = QHBoxLayout()
        self.label_addr_range = QLabel("地址 0x01~0x3F  当前模块: --  已选: 0")
        ctrl_bar.addWidget(self.label_addr_range)
        ctrl_bar.addStretch()
        self.btn_select_all = QPushButton("全选"); self.btn_select_all.setObjectName("btnGray")
        self.btn_clear_all = QPushButton("清空"); self.btn_clear_all.setObjectName("btnGray")
        self.btn_online_only = QPushButton("仅在线"); self.btn_online_only.setObjectName("btnGray")
        self.btn_sel_on = QPushButton("选中开机"); self.btn_sel_on.setObjectName("btnGreen")
        self.btn_sel_off = QPushButton("选中关机"); self.btn_sel_off.setObjectName("btnPink")
        self.btn_sel_vi = QPushButton("选中设置V/I"); self.btn_sel_vi.setObjectName("btnBlue")
        for b in [self.btn_select_all, self.btn_clear_all, self.btn_online_only,
                   self.btn_sel_on, self.btn_sel_off, self.btn_sel_vi]:
            ctrl_bar.addWidget(b)
        table_layout.addLayout(ctrl_bar)

        self.table = ModuleTableWidget()
        self.table._host = self
        self.table.cellClicked.connect(self.on_table_click)
        self.table.itemChanged.connect(self.on_table_item_changed)
        table_layout.addWidget(self.table)

        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        table_layout.addWidget(self.scan_progress)

        splitter.addWidget(table_group)
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([850, 350])

        main_layout.addWidget(splitter, stretch=1)

        log_frame = QFrame()
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_ctrl = QHBoxLayout()
        log_title = QLabel("CAN 报文日志")
        log_title.setStyleSheet("color: #6B7280; font-weight: bold;")
        log_ctrl.addWidget(log_title)
        log_ctrl.addStretch()
        self.chk_show_tx = QCheckBox("显示发送")
        self.chk_show_tx.setChecked(True)
        self.chk_show_rx = QCheckBox("显示接收")
        self.chk_show_rx.setChecked(True)
        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        self.btn_clear_log = QPushButton("清空日志"); self.btn_clear_log.setObjectName("btnGray")
        for w in [self.chk_show_tx, self.chk_show_rx, self.chk_auto_scroll, self.btn_clear_log]:
            log_ctrl.addWidget(w)
        log_layout.addLayout(log_ctrl)
        self.log_text = QPlainTextEdit()
        self.log_text.setMaximumBlockCount(2000)
        self.log_text.setMinimumHeight(100)
        self.log_text.setMaximumHeight(180)
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_frame)

    def _build_conn_bar(self):
        layout = QHBoxLayout()
        layout.setSpacing(8)
        title = QLabel("优优绿能 双向模块监控 v1.0")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        layout.addSpacing(20)

        layout.addWidget(QLabel("UT-6502 IP:"))
        self.ip_input = QLineEdit("192.168.1.125")
        self.ip_input.setFixedWidth(120)
        layout.addWidget(self.ip_input)

        layout.addWidget(QLabel("端口:"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(5001)
        self.port_input.setFixedWidth(70)
        layout.addWidget(self.port_input)

        self.btn_connect = QPushButton("连接"); self.btn_connect.setObjectName("btnGreen")
        self.btn_disconnect = QPushButton("断开"); self.btn_disconnect.setObjectName("btnRed")
        self.btn_disconnect.setEnabled(False)
        layout.addWidget(self.btn_connect)
        layout.addWidget(self.btn_disconnect)

        layout.addSpacing(20)
        self.chk_auto_poll = QCheckBox("自动轮询在线模块")
        layout.addWidget(self.chk_auto_poll)
        layout.addWidget(QLabel("间隔(ms):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(100, 10000)
        self.spin_interval.setValue(1000)
        self.spin_interval.setFixedWidth(70)
        layout.addWidget(self.spin_interval)
        layout.addStretch()

        self.label_scan_result = QLabel("未扫描")
        self.label_scan_result.setStyleSheet(
            "color: #6B7280; font-size: 12px; padding: 2px 8px;"
            "background: #FFFFFF; border: 1px solid #3a3a5e; border-radius: 3px;"
        )
        layout.addWidget(self.label_scan_result)

        self.btn_scan_toggle = QPushButton("扫描模块")
        self.btn_scan_toggle.setObjectName("btnBlue")
        self.btn_scan_toggle.setCheckable(True)
        self.btn_scan_toggle.setMinimumWidth(90)
        layout.addWidget(self.btn_scan_toggle)

        layout.addSpacing(10)
        self.status_label = QLabel("● 未连接")
        self.status_label.setStyleSheet("color: #6B7280; font-weight: bold;")
        layout.addWidget(self.status_label)
        return layout

    def _build_batch_bar(self):
        layout = QHBoxLayout()
        layout.setSpacing(6)
        self.btn_all_on = QPushButton("全部开机"); self.btn_all_on.setObjectName("btnGreen")
        self.btn_all_off = QPushButton("全部关机"); self.btn_all_off.setObjectName("btnPink")
        self.btn_fault_codes = QPushButton("故障代码查询"); self.btn_fault_codes.setObjectName("btnBlue")
        layout.addWidget(self.btn_all_on)
        layout.addWidget(self.btn_all_off)
        layout.addWidget(self.btn_fault_codes)
        layout.addSpacing(10)

        layout.addWidget(QLabel("批量电压(V):"))
        self.spin_batch_v = QDoubleSpinBox()
        self.spin_batch_v.setRange(0, 1000)
        self.spin_batch_v.setValue(50.0)
        self.spin_batch_v.setDecimals(1)
        self.spin_batch_v.setFixedWidth(80)
        layout.addWidget(self.spin_batch_v)

        layout.addWidget(QLabel("批量电流(A):"))
        self.spin_batch_i = QDoubleSpinBox()
        self.spin_batch_i.setRange(0, 100)
        self.spin_batch_i.setValue(50.0)
        self.spin_batch_i.setDecimals(1)
        self.spin_batch_i.setFixedWidth(80)
        layout.addWidget(self.spin_batch_i)

        self.btn_batch_vi = QPushButton("批量设置电压电流"); self.btn_batch_vi.setObjectName("btnBlue")
        layout.addWidget(self.btn_batch_vi)

        self.btn_init = QPushButton("一键初始化"); self.btn_init.setObjectName("btnYellow")
        layout.addWidget(self.btn_init)
        layout.addStretch()
        return layout

    def _build_right_panel(self):
        panel = QTabWidget()
        panel.setMinimumWidth(320)

        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setSpacing(6)

        info_label = QLabel(
            "模块控制\n\n"
            "通过CAN总线对指定模块进行控制操作。\n"
            "CAN ID格式: Protocol(0x01) << 25\n"
            "  | MonitorAddr << 21\n"
            "  | ModuleAddr << 14\n"
            "  | ProductionDay << 9\n"
            "  | SerialLow\n\n"
            "示例 (地址0x01, 监控0x01):\n"
            f"  ID = 0x{build_can_id(0x01):08X}\n\n"
            "选择表格中的模块行后操作。"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #6B7280; font-size: 12px;")
        ctrl_layout.addWidget(info_label)

        ctrl_layout.addWidget(QLabel("监控地址:"))
        self.spin_monitor = QSpinBox()
        self.spin_monitor.setRange(1, 15)
        self.spin_monitor.setValue(1)
        ctrl_layout.addWidget(self.spin_monitor)

        ctrl_layout.addWidget(QLabel("组地址:"))
        self.spin_group = QSpinBox()
        self.spin_group.setRange(0, 15)
        self.spin_group.setValue(1)
        ctrl_layout.addWidget(self.spin_group)

        ctrl_layout.addWidget(QLabel("当前选中模块:"))
        self.label_sel_module = QLabel("--")
        self.label_sel_module.setStyleSheet("color: #4F46E5; font-size: 14px; font-weight: bold;")
        ctrl_layout.addWidget(self.label_sel_module)

        ctrl_layout.addWidget(QLabel("模块电压(V):"))
        self.spin_mod_v = QDoubleSpinBox()
        self.spin_mod_v.setRange(0, 1000)
        self.spin_mod_v.setValue(50.0)
        self.spin_mod_v.setDecimals(1)
        ctrl_layout.addWidget(self.spin_mod_v)

        ctrl_layout.addWidget(QLabel("模块电流(A):"))
        self.spin_mod_i = QDoubleSpinBox()
        self.spin_mod_i.setRange(0, 100)
        self.spin_mod_i.setValue(50.0)
        self.spin_mod_i.setDecimals(1)
        ctrl_layout.addWidget(self.spin_mod_i)

        btn_row = QHBoxLayout()
        self.btn_mod_on = QPushButton("开机"); self.btn_mod_on.setObjectName("btnGreen")
        self.btn_mod_off = QPushButton("关机"); self.btn_mod_off.setObjectName("btnPink")
        btn_row.addWidget(self.btn_mod_on)
        btn_row.addWidget(self.btn_mod_off)
        ctrl_layout.addLayout(btn_row)

        self.btn_mod_vi = QPushButton("设置电压电流"); self.btn_mod_vi.setObjectName("btnBlue")
        ctrl_layout.addWidget(self.btn_mod_vi)

        self.btn_mod_read_sn = QPushButton("读取序列号"); self.btn_mod_read_sn.setObjectName("btnGray")
        ctrl_layout.addWidget(self.btn_mod_read_sn)

        self.btn_mod_init = QPushButton("初始化模块(充电模式)"); self.btn_mod_init.setObjectName("btnYellow")
        ctrl_layout.addWidget(self.btn_mod_init)

        ctrl_layout.addStretch()
        panel.addTab(ctrl_widget, "模块控制")

        id_widget = QWidget()
        id_layout = QVBoxLayout(id_widget)
        id_layout.setSpacing(8)

        id_layout.addWidget(QLabel("修改模块组号"))
        id_layout.addWidget(QLabel("当前模块地址:"))
        self.spin_id_addr = QSpinBox()
        self.spin_id_addr.setRange(1, 127)
        self.spin_id_addr.setValue(1)
        id_layout.addWidget(self.spin_id_addr)

        id_layout.addWidget(QLabel("新组号 (1~15):"))
        self.spin_new_group = QSpinBox()
        self.spin_new_group.setRange(1, 15)
        self.spin_new_group.setValue(1)
        id_layout.addWidget(self.spin_new_group)

        self.btn_set_group = QPushButton("修改组号"); self.btn_set_group.setObjectName("btnBlue")
        id_layout.addWidget(self.btn_set_group)

        warn = QLabel("注意: 修改组号后模块将以新组号响应，一次只修改一台模块。")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #B45309; background: #FEF3C7; padding: 6px; border-radius: 3px; font-size: 12px;")
        id_layout.addWidget(warn)

        id_layout.addWidget(QLabel("读取模块序列号"))
        self.btn_read_sn = QPushButton("读取序列号"); self.btn_read_sn.setObjectName("btnBlue")
        id_layout.addWidget(self.btn_read_sn)
        self.label_sn = QLabel("--")
        self.label_sn.setStyleSheet("color: #047857; font-family: Consolas; font-size: 13px;")
        id_layout.addWidget(self.label_sn)

        id_layout.addWidget(QLabel("高低压模式设置"))
        self.btn_set_hi = QPushButton("设置高压(1000V)"); self.btn_set_hi.setObjectName("btnBlue")
        self.btn_set_lo = QPushButton("设置低压(500V)"); self.btn_set_lo.setObjectName("btnBlue")
        id_layout.addWidget(self.btn_set_hi)
        id_layout.addWidget(self.btn_set_lo)

        id_layout.addWidget(QLabel("工作模式设置"))
        self.btn_set_charge = QPushButton("充电模式"); self.btn_set_charge.setObjectName("btnGreen")
        self.btn_set_discharge = QPushButton("放电模式"); self.btn_set_discharge.setObjectName("btnPink")
        id_layout.addWidget(self.btn_set_charge)
        id_layout.addWidget(self.btn_set_discharge)

        id_layout.addStretch()
        panel.addTab(id_widget, "ID 管理")

        return panel

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self.on_connect)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        self.chk_auto_poll.stateChanged.connect(self.on_auto_poll_changed)
        self.spin_interval.valueChanged.connect(self.on_interval_changed)

        self.btn_all_on.clicked.connect(lambda: self.batch_action("on"))
        self.btn_all_off.clicked.connect(lambda: self.batch_action("off"))
        self.btn_fault_codes.clicked.connect(self._on_show_fault_codes)
        self.btn_batch_vi.clicked.connect(self.on_batch_vi)
        self.btn_init.clicked.connect(self.on_init_all)
        self.btn_scan_toggle.toggled.connect(self.on_scan_toggled)

        self.btn_select_all.clicked.connect(self.select_all)
        self.btn_clear_all.clicked.connect(self.clear_selection)
        self.btn_online_only.clicked.connect(self.filter_online)
        self.btn_sel_on.clicked.connect(lambda: self.selected_action("on"))
        self.btn_sel_off.clicked.connect(lambda: self.selected_action("off"))
        self.btn_sel_vi.clicked.connect(self.on_sel_vi)

        self.btn_mod_on.clicked.connect(lambda: self.single_action("on"))
        self.btn_mod_off.clicked.connect(lambda: self.single_action("off"))
        self.btn_mod_vi.clicked.connect(self.on_mod_vi)
        self.btn_mod_read_sn.clicked.connect(self.on_mod_read_sn)
        self.btn_mod_init.clicked.connect(self.on_mod_init)

        self.btn_set_group.clicked.connect(self.on_set_group)
        self.btn_read_sn.clicked.connect(self.on_read_sn_id)
        self.btn_set_hi.clicked.connect(lambda: self.set_hilo(True))
        self.btn_set_lo.clicked.connect(lambda: self.set_hilo(False))
        self.btn_set_charge.clicked.connect(lambda: self.set_work_mode(0))
        self.btn_set_discharge.clicked.connect(lambda: self.set_work_mode(1))

        self.btn_clear_log.clicked.connect(self.log_text.clear)

    def on_connect(self):
        ip = self.ip_input.text().strip()
        port = self.port_input.value()
        self.btn_connect.setEnabled(False)
        ok = self.worker.connect_device(ip, port)
        if ok:
            self.btn_disconnect.setEnabled(True)
            self.btn_connect.setText("已连接")
            self.btn_connect.setObjectName("btnConnected")
            self.btn_connect.style().unpolish(self.btn_connect)
            self.btn_connect.style().polish(self.btn_connect)
            self.ip_input.setEnabled(False)
            self.port_input.setEnabled(False)
        else:
            self.btn_connect.setEnabled(True)

    def on_disconnect(self):
        try:
            self.worker.disconnect_device()
        except Exception as e:
            # 驱动断开异常不能阻断状态复位, 否则按钮卡在「已连接」、轮询不停
            self.log_text.appendPlainText(
                f"[{QDateTime.currentDateTime().toString('hh:mm:ss')}] 断开时异常(已忽略): {e}")
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnGreen")
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)
        self.btn_disconnect.setEnabled(False)
        self.ip_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.chk_auto_poll.setChecked(False)
        self.btn_scan_toggle.setChecked(False)
        self.label_scan_result.setText("未扫描")
        self.label_scan_result.setStyleSheet(
            "color: #6B7280; font-size: 12px; padding: 2px 8px;"
            "background: #FFFFFF; border: 1px solid #3a3a5e; border-radius: 3px;"
        )
        self.scan_progress.setVisible(False)
        for i in range(MAX_MODULES):
            self.table.setItem(i, COL_ONLINE, QTableWidgetItem("○ 离线"))
            self.table.item(i, COL_ONLINE).setForeground(QColor("#6B7280"))
            self.table.setItem(i, COL_POWER, QTableWidgetItem("○ 关机"))
            self.table.item(i, COL_POWER).setForeground(QColor("#6B7280"))

    def on_connection(self, connected, msg):
        if connected:
            self.status_label.setText("● 已连接")
            self.status_label.setStyleSheet(
                "color: #7CF0B8; font-size: 14px; font-weight: bold;"
                "background: #14532d; border: 1px solid #2e5e2e; padding: 3px 10px; border-radius: 3px;"
            )
        else:
            self.status_label.setText("● 未连接")
            self.status_label.setStyleSheet(
                "color: #FF8A80; font-size: 14px; font-weight: bold;"
                "background: #3a1e1e; border: 1px solid #6e2e2e; padding: 3px 10px; border-radius: 3px;"
            )
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("连接")
            self.btn_connect.setObjectName("btnGreen")
            self.btn_connect.style().unpolish(self.btn_connect)
            self.btn_connect.style().polish(self.btn_connect)
            self.btn_disconnect.setEnabled(False)
            self.ip_input.setEnabled(True)
            self.port_input.setEnabled(True)
        self.log_text.appendPlainText(f"[{QDateTime.currentDateTime().toString('hh:mm:ss')}] {msg}")

    def on_auto_poll_changed(self, state):
        enabled = state == Qt.Checked
        interval = self.spin_interval.value()
        self.worker.set_auto_poll(enabled, interval)

    def on_cmd_done(self, msg):
        self.statusBar().showMessage(msg, 5000)

    def on_interval_changed(self, value):
        self.worker.set_auto_poll(self.chk_auto_poll.isChecked(), value)

    def on_can_log(self, direction, text):
        if direction == "TX" and not self.chk_show_tx.isChecked():
            return
        if direction == "RX" and not self.chk_show_rx.isChecked():
            return
        ts = QDateTime.currentDateTime().toString('hh:mm:ss.zzz')
        color = "#3730A3" if direction == "TX" else "#1B5E20"
        self.log_text.appendHtml(
            f'<span style="color:#4B5563;">[{ts}]</span> '
            f'<span style="color:{color};font-weight:bold;">{direction}</span> '
            f'<span style="color:#1B2430;">{text}</span>'
        )
        if self.chk_auto_scroll.isChecked():
            self.log_text.moveCursor(QTextCursor.End)

    def on_module_updated(self, addr, data):
        from instrument_hub.comm_state import mark_ok, mark_lost
        if data.get("online"):
            mark_ok(self)   # 模块数据更新 = 通讯真正建立
        elif not self.worker.get_online_addrs():
            mark_lost(self)   # 全部模块离线 = 通讯中断（离线通知不得点绿灯）
        self.table.update_module(addr, data)
        if data.get("serial_number"):
            self.label_sn.setText(data["serial_number"])

    def on_table_click(self, row, col):
        # 模块地址选中固定在勾选列（选择区域），其余列点击不可选中（规范）
        if col != COL_CHECK:
            return
        addr = row + 1
        self.selected_addr = addr
        self.label_sel_module.setText(f"0x{addr:02X} ({addr}#)")
        self.spin_id_addr.setValue(addr)
        self.label_addr_range.setText(f"地址 0x01~0x3F  当前模块: 0x{addr:02X}  已选: {self.count_selected()}")

    def _on_row_click_select(self, item):
        """模块地址选中固定在勾选列，其余列点击不可选中（规范）"""
        return

    def _row_power(self, addr, on):
        """表格行内 开机/关机 按钮"""
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        if on and not self._confirm_power_on([addr], False, "确认开机"):
            return
        if on:
            self.worker.power_on(addr)
            word = "开机"
        else:
            self.worker.power_off(addr)
            word = "关机"
        self.statusBar().showMessage(f"已下发 0x{addr:02X} {word} 命令", 3000)

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
        """显示优优模块状态字/故障位定义"""
        from .can_protocol import STATUS_BITS
        lines = ["优优模块状态字故障位定义", ""]
        for bit in sorted(STATUS_BITS.keys()):
            lines.append(f"  bit{bit:02d}: {STATUS_BITS[bit]}")
        lines += ["", "说明：状态字对应位置 1 表示该故障/告警。"]
        QMessageBox.information(self, "故障代码查询", "\n".join(lines))

    def _row_set_vi(self, addr, v, i):
        """表格行内 设置 按钮：把该行输入的电压电流下发给模块"""
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        self.worker.set_voltage_current(addr, v, i)
        self.statusBar().showMessage(
            f"已下发 0x{addr:02X} 设置 {v:.1f}V / {i:.1f}A", 4000)

    def on_table_item_changed(self, item):
        if item.column() == COL_CHECK:
            sel = f"0x{self.selected_addr:02X}" if self.selected_addr else "--"
            self.label_addr_range.setText(
                f"地址 0x01~0x3F  当前模块: {sel}  已选: {self.count_selected()}"
            )

    def count_selected(self):
        count = 0
        for i in range(MAX_MODULES):
            item = self.table.item(i, COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                count += 1
        return count

    def get_selected_addrs(self):
        addrs = []
        for i in range(MAX_MODULES):
            item = self.table.item(i, COL_CHECK)
            if item and item.checkState() == Qt.Checked:
                addrs.append(i + 1)
        return addrs

    def select_all(self):
        for i in range(MAX_MODULES):
            self.table.item(i, COL_CHECK).setCheckState(Qt.Checked)

    def clear_selection(self):
        for i in range(MAX_MODULES):
            self.table.item(i, COL_CHECK).setCheckState(Qt.Unchecked)

    def filter_online(self):
        for i in range(MAX_MODULES):
            item = self.table.item(i, COL_ONLINE)
            if item and "在线" in item.text():
                self.table.item(i, COL_CHECK).setCheckState(Qt.Checked)
            else:
                self.table.item(i, COL_CHECK).setCheckState(Qt.Unchecked)

    def batch_action(self, action):
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        addrs = self.worker.get_online_addrs()
        if not addrs:
            QMessageBox.warning(self, "警告", "当前无在线模块, 请先扫描")
            return
        if action == "on" and not self._confirm_power_on(addrs, False, "确认全部开机"):
            return
        for addr in addrs:
            if action == "on":
                self.worker.power_on(addr)
            else:
                self.worker.power_off(addr)
        word = "开机" if action == "on" else "关机"
        self.statusBar().showMessage(f"已将 {len(addrs)} 台在线模块的{word}命令加入执行队列", 5000)

    def on_batch_vi(self):
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        v = self.spin_batch_v.value()
        i = self.spin_batch_i.value()
        addrs = self.worker.get_online_addrs()
        if not addrs:
            QMessageBox.warning(self, "警告", "当前无在线模块, 请先扫描")
            return
        for addr in addrs:
            self.worker.set_voltage_current(addr, v, i)
        self.statusBar().showMessage(f"已将 {len(addrs)} 台在线模块设置 {v}V/{i}A 加入执行队列", 5000)

    def on_init_all(self):
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        reply = QMessageBox.question(self, "确认", "确定要一键初始化所有在线模块为充电模式吗?")
        if reply != QMessageBox.Yes:
            return
        addrs = self.worker.get_online_addrs()
        if not addrs:
            QMessageBox.warning(self, "警告", "当前无在线模块, 请先扫描")
            return
        for addr in addrs:
            self.worker.initialize_module(addr)
        self.statusBar().showMessage(f"已将 {len(addrs)} 台在线模块的初始化命令加入执行队列", 5000)

    def on_scan_toggled(self, checked):
        if checked:
            if not self.worker.connected:
                QMessageBox.warning(self, "警告", "请先连接设备")
                self.btn_scan_toggle.setChecked(False)
                return
            self.btn_scan_toggle.setText("停止扫描")
            self.btn_scan_toggle.setObjectName("btnPink")
            self.btn_scan_toggle.style().unpolish(self.btn_scan_toggle)
            self.btn_scan_toggle.style().polish(self.btn_scan_toggle)
            self.label_scan_result.setText("扫描中...")
            self.label_scan_result.setStyleSheet(
                "color: #B45309; font-size: 12px; padding: 2px 8px;"
                "background: #FFFFFF; border: 1px solid #3a3a5e; border-radius: 3px;"
            )
            self.worker.start_scan()
            self.scan_progress.setVisible(True)
            self.scan_progress.setValue(0)
        else:
            self.btn_scan_toggle.setText("扫描模块")
            self.btn_scan_toggle.setObjectName("btnBlue")
            self.btn_scan_toggle.style().unpolish(self.btn_scan_toggle)
            self.btn_scan_toggle.style().polish(self.btn_scan_toggle)
            self.worker.stop_scan()
            self.scan_progress.setVisible(False)

    def on_scan_progress(self, current, total):
        self.scan_progress.setMaximum(total)
        self.scan_progress.setValue(current)

    def on_scan_found(self, addr):
        count = sum(1 for i in range(MAX_MODULES)
                     if self.table.item(i, COL_ONLINE) and "在线" in self.table.item(i, COL_ONLINE).text())
        self.label_scan_result.setText(f"扫描中... 已发现 {count} 台")

    def on_scan_done(self, online_addrs):
        self.btn_scan_toggle.blockSignals(True)
        self.btn_scan_toggle.setChecked(False)
        self.btn_scan_toggle.blockSignals(False)
        self.btn_scan_toggle.setText("扫描模块")
        self.btn_scan_toggle.setObjectName("btnBlue")
        self.btn_scan_toggle.style().unpolish(self.btn_scan_toggle)
        self.btn_scan_toggle.style().polish(self.btn_scan_toggle)
        self.scan_progress.setVisible(False)
        if not online_addrs:
            self.label_scan_result.setText("未发现在线模块")
            self.label_scan_result.setStyleSheet(
                "color: #6B7280; font-size: 12px; padding: 2px 8px;"
                "background: #FFFFFF; border: 1px solid #3a3a5e; border-radius: 3px;"
            )
            return
        addr_str = ", ".join(f"0x{a:02X}" for a in online_addrs)
        self.label_scan_result.setText(f"在线 {len(online_addrs)}台: {addr_str}")
        self.label_scan_result.setStyleSheet(
            "color: #7CF0B8; font-size: 12px; padding: 2px 8px;"
            "background: #14532d; border: 1px solid #2e5e2e; border-radius: 3px;"
        )

    def selected_action(self, action):
        addrs = self.get_selected_addrs()
        if not addrs:
            QMessageBox.warning(self, "警告", "请先选择模块")
            return
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        if action == "on" and not self._confirm_power_on(addrs, False, "确认选中开机"):
            return
        for addr in addrs:
            if action == "on":
                self.worker.power_on(addr)
            else:
                self.worker.power_off(addr)

    def on_sel_vi(self):
        addrs = self.get_selected_addrs()
        if not addrs:
            QMessageBox.warning(self, "警告", "请先选择模块")
            return
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        v = self.spin_batch_v.value()
        i = self.spin_batch_i.value()
        for addr in addrs:
            self.worker.set_voltage_current(addr, v, i)

    def single_action(self, action):
        if not self.selected_addr:
            QMessageBox.warning(self, "警告", "请先在表格中选择模块")
            return
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        if action == "on" and not self._confirm_power_on([self.selected_addr], False, "确认开机"):
            return
        if action == "on":
            self.worker.power_on(self.selected_addr)
        else:
            self.worker.power_off(self.selected_addr)

    def on_mod_vi(self):
        if not self.selected_addr:
            QMessageBox.warning(self, "警告", "请先在表格中选择模块")
            return
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        self.worker.set_voltage_current(self.selected_addr, self.spin_mod_v.value(), self.spin_mod_i.value())

    def on_mod_read_sn(self):
        if not self.selected_addr:
            QMessageBox.warning(self, "警告", "请先在表格中选择模块")
            return
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        self.worker.read_serial_number(self.selected_addr)

    def on_mod_init(self):
        if not self.selected_addr:
            QMessageBox.warning(self, "警告", "请先在表格中选择模块")
            return
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        self.worker.initialize_module(self.selected_addr)

    def on_set_group(self):
        addr = self.spin_id_addr.value()
        new_group = self.spin_new_group.value()
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        reply = QMessageBox.question(self, "确认",
            f"确定将模块 0x{addr:02X} 的组号修改为 {new_group} 吗?\n一次只修改一台模块!")
        if reply != QMessageBox.Yes:
            return
        self.worker.set_group(addr, new_group)

    def on_read_sn_id(self):
        addr = self.spin_id_addr.value()
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        self.worker.read_serial_number(addr)

    def set_hilo(self, high):
        addr = self.spin_id_addr.value()
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        self.worker.set_addr_config(self._get_monitor(), self._get_group())
        self.worker.set_hilo_mode(addr, high)

    def set_work_mode(self, mode):
        addr = self.spin_id_addr.value()
        if not self.worker.connected:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return
        self.worker.set_addr_config(self._get_monitor(), self._get_group())
        self.worker.set_work_mode(addr, mode)

    def _get_monitor(self):
        return self.spin_monitor.value()

    def _get_group(self):
        return self.spin_group.value()

    def closeEvent(self, event):
        try:
            self.worker.stop()
            if self.worker.connected:
                self.worker.disconnect_device()
            event.accept()
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass
