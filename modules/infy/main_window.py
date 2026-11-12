"""
英飞源REG系列充电模块监控上位机 - 主界面
"""
import time
from typing import List, Optional

from modules.theme_util import expand_qss
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QGroupBox, QHeaderView, QAbstractItemView,
    QTextEdit, QSplitter, QMessageBox, QTabWidget, QComboBox,
    QGridLayout, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QColor, QBrush, QFont

from .protocol import InfyCANProtocol, CANFrame, CommandCode
from .can_interface import create_can_interface, BaseCANInterface
from .module_model import ModuleManager, ChargingModule


class StyleSheet:
    """样式表"""
    MAIN = """
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


class ModuleTableWidget(QTableWidget):
    """模块监控表格"""

    module_on = pyqtSlot(int)   # 开机信号
    module_off = pyqtSlot(int)  # 关机信号
    module_set_vi = pyqtSlot(int)  # 设置VI信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = None  # 宿主 MainWindow 引用（嵌入单体后 window() 不可靠）
        self.setup_ui()
        self._btn_on_map = {}
        self._btn_off_map = {}
        self._btn_set_map = {}
        self._set_v_spins = {}
        self._set_i_spins = {}

    def setup_ui(self):
        """设置表格UI"""
        headers = [
            "选择", "地址", "在线", "电源", "电压(V)", "电流(A)",
            "输入AB(V)", "设置电压(V)", "设置电流(A)", "组号", "故障",
            "开机", "关机", "设置V/I"
        ]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # 设置列宽
        self.setColumnWidth(0, 40)   # 选择
        self.setColumnWidth(1, 60)   # 地址
        self.setColumnWidth(2, 55)   # 在线
        self.setColumnWidth(3, 55)   # 电源
        self.setColumnWidth(4, 70)   # 电压
        self.setColumnWidth(5, 70)   # 电流
        self.setColumnWidth(6, 90)   # 母线电压
        self.setColumnWidth(7, 80)   # 设置电压
        self.setColumnWidth(8, 80)   # 设置电流
        self.setColumnWidth(9, 55)   # 组号
        self.setColumnWidth(10, 120) # 故障
        self.setColumnWidth(11, 50)  # 开机
        self.setColumnWidth(12, 50)  # 关机
        self.setColumnWidth(13, 55)  # 设置V/I

        # 水平头可缩放
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        # 故障列可拖拽; 开机/关机/设置V/I 按钮列固定窄宽、可拖动缩放
        self.horizontalHeader().setSectionResizeMode(10, QHeaderView.Interactive)
        self.horizontalHeader().setSectionResizeMode(11, QHeaderView.Interactive)
        self.horizontalHeader().setSectionResizeMode(12, QHeaderView.Interactive)
        self.horizontalHeader().setSectionResizeMode(13, QHeaderView.Interactive)

    def init_rows(self, count: int):
        """初始化行"""
        self.setRowCount(count)
        self._btn_on_map.clear()
        self._btn_off_map.clear()
        self._btn_set_map.clear()
        self._set_v_spins.clear()
        self._set_i_spins.clear()

        for i in range(count):
            addr = i  # 地址 = 行索引 = 真实CAN(拨码)地址(0-based), 与发送命令的目的地址严格一致

            # 选择复选框
            chk = QCheckBox()
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.setCellWidget(i, 0, chk_widget)

            # 地址
            self.setItem(i, 1, QTableWidgetItem(f"0x{addr:02X}"))

            # 在线/电源/电压/电流/母线/组号/故障 (文本列)
            for col in (2, 3, 4, 5, 6, 9, 10):
                item = QTableWidgetItem("---")
                item.setTextAlignment(Qt.AlignCenter)
                self.setItem(i, col, item)

            # 设置电压 (col7) - 可编辑输入框
            sv_spin = QDoubleSpinBox()
            sv_spin.setRange(0.0, 800.0)
            sv_spin.setSingleStep(0.5)
            sv_spin.setDecimals(2)
            sv_spin.setSuffix(" V")
            sv_spin.setAlignment(Qt.AlignCenter)
            sv_spin.setProperty("row", i)
            sv_spin.editingFinished.connect(self._on_set_vi_finished)
            sv_spin.valueChanged.connect(lambda _v, w=sv_spin: setattr(w, "_user_edited", True))
            sv_spin.setKeyboardTracking(False)
            self._set_v_spins[i] = sv_spin
            sv_w = QWidget()
            sv_ly = QHBoxLayout(sv_w)
            sv_ly.setContentsMargins(2, 0, 2, 0)
            sv_ly.addWidget(sv_spin)
            self.setCellWidget(i, 7, sv_w)

            # 设置电流 (col8) - 可编辑输入框
            si_spin = QDoubleSpinBox()
            si_spin.setRange(0.0, 220.0)
            si_spin.setSingleStep(0.1)
            si_spin.setDecimals(2)
            si_spin.setSuffix(" A")
            si_spin.setAlignment(Qt.AlignCenter)
            si_spin.setProperty("row", i)
            si_spin.editingFinished.connect(self._on_set_vi_finished)
            si_spin.valueChanged.connect(lambda _v, w=si_spin: setattr(w, "_user_edited", True))
            si_spin.setKeyboardTracking(False)
            self._set_i_spins[i] = si_spin
            si_w = QWidget()
            si_ly = QHBoxLayout(si_w)
            si_ly.setContentsMargins(2, 0, 2, 0)
            si_ly.addWidget(si_spin)
            self.setCellWidget(i, 8, si_w)

            # 开机按钮
            btn_on = QPushButton("开")
            btn_on.setObjectName("greenBtn")
            btn_on.setFixedSize(40, 24)
            btn_on.setProperty("addr", i)
            btn_on.clicked.connect(self._on_module_on)
            self._btn_on_map[i] = btn_on
            self.setCellWidget(i, 11, btn_on)

            # 关机按钮
            btn_off = QPushButton("关")
            btn_off.setObjectName("redBtn")
            btn_off.setFixedSize(40, 24)
            btn_off.setProperty("addr", i)
            btn_off.clicked.connect(self._on_module_off)
            self._btn_off_map[i] = btn_off
            self.setCellWidget(i, 12, btn_off)

            # 设置V/I按钮
            btn_set = QPushButton("设置")
            btn_set.setFixedSize(50, 24)
            btn_set.setProperty("addr", i)
            btn_set.clicked.connect(self._on_module_set_vi)
            self._btn_set_map[i] = btn_set
            self.setCellWidget(i, 13, btn_set)

            # 设置行高
            self.setRowHeight(i, 30)

    def _on_module_on(self):
        btn = self.sender()
        addr = btn.property("addr")
        (self._host or self.window()).on_module_on(addr)

    def _on_module_off(self):
        btn = self.sender()
        addr = btn.property("addr")
        (self._host or self.window()).on_module_off(addr)

    def _on_module_set_vi(self):
        btn = self.sender()
        addr = btn.property("addr")
        # 优先读取该行输入框的电压电流并下发
        vV, iV = self.get_set_vi(addr)
        host = self._host or self.window()
        if hasattr(host, "apply_module_set_vi"):
            host.apply_module_set_vi(addr, vV, iV)
        else:
            host.on_module_set_vi(addr)

    def _on_set_vi_finished(self):
        """设置电压/电流编辑完成 -> 发送"""
        spin = self.sender()
        row = spin.property("row")
        vV, iV = self.get_set_vi(row)
        (self._host or self.window()).apply_module_set_vi(row, vV, iV)

    def get_set_vi(self, row: int):
        """获取某行当前设置的电压(V)和电流(A)"""
        vV = self._set_v_spins.get(row).value() if row in self._set_v_spins else 0.0
        iV = self._set_i_spins.get(row).value() if row in self._set_i_spins else 0.0
        return vV, iV

    def set_set_vi_display(self, row: int, vV: float, iV: float):
        """回显模块设置的电压/电流(不触发发送；用户改过则不覆盖)"""
        if row in self._set_v_spins:
            s = self._set_v_spins[row]
            if not s.hasFocus() and not getattr(s, "_user_edited", False):
                s.blockSignals(True)
                s.setValue(vV)
                s.blockSignals(False)
        if row in self._set_i_spins:
            s = self._set_i_spins[row]
            if not s.hasFocus() and not getattr(s, "_user_edited", False):
                s.blockSignals(True)
                s.setValue(iV)
                s.blockSignals(False)

    def update_module(self, module: ChargingModule, row: int):
        """更新模块显示"""
        if row < 0 or row >= self.rowCount():
            return

        # 在线状态
        online_item = self.item(row, 2)
        online_item.setTextAlignment(Qt.AlignCenter)
        online_item.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        if module.online:
            online_item.setText("● 在线")
            online_item.setForeground(QBrush(QColor("#047857")))
        else:
            online_item.setText("○ 离线")
            online_item.setForeground(QBrush(QColor("#9AA2AA")))

        # 电源状态 (三态: 开机/待机/关机)
        power_item = self.item(row, 3)
        if not module.online:
            power_item.setText("关机")
            power_item.setForeground(QBrush(QColor("#6B7280")))
        else:
            power_item.setText(module.power_text)
            if module.power_text == "开机":
                power_item.setForeground(QBrush(QColor("#047857")))
            elif module.power_text == "待机":
                power_item.setForeground(QBrush(QColor("#e8bf6a")))
            else:
                power_item.setForeground(QBrush(QColor("#c75450")))

        # 电压
        v_item = self.item(row, 4)
        v_item.setText(f"{module.voltage_v:.2f}" if module.online else "---")

        # 电流
        i_item = self.item(row, 5)
        i_item.setText(f"{module.current_a:.2f}" if module.online else "---")

        # 母线电压
        bus_item = self.item(row, 6)
        bus_item.setText(f"{module.bus_voltage_vab:.1f}" if module.online else "---")

        # 设置电压/设置电流 (可编辑输入框, 回显模块设置值)
        self.set_set_vi_display(row, module.set_voltage_v, module.set_current_a)

        # 组号 (协议 0x04 应答 Byte2=模块组号, 非运行模式)
        mode_item = self.item(row, 9)
        mode_item.setText(f"组{module.group}" if module.online else "---")

        # 故障 (悬停显示状态位原文+运行状态, 便于现场诊断)
        fault_item = self.item(row, 10)
        if not module.online:
            fault_item.setText("---")
            fault_item.setForeground(QBrush(QColor("#6B7280")))
        else:
            tip = (f"地址0x{module.addr:02X}  温度{module.temperature}℃  "
                   f"输入AB {module.bus_voltage_vab:.1f}V\n"
                   f"状态表3=0x{module.status3:02X}  状态表2=0x{module.status2:02X}  "
                   f"状态表1=0x{module.status1:02X}  状态表0=0x{module.status0:02X}")
            if module.states:
                tip += "\n状态: " + ", ".join(module.states)
            fault_item.setToolTip(tip)
            if module.faults:
                fault_item.setText(module.fault_text)
                fault_item.setForeground(QBrush(QColor("#B01030")))
            else:
                fault_item.setText("正常")
                fault_item.setForeground(QBrush(QColor("#047857")))

    def get_selected_rows(self) -> List[int]:
        """获取选中的行地址"""
        selected = []
        for row in range(self.rowCount()):
            chk_widget = self.cellWidget(row, 0)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk and chk.isChecked():
                    selected.append(row)
        return selected

    def set_all_checked(self, checked: bool):
        """全选/取消全选"""
        for row in range(self.rowCount()):
            chk_widget = self.cellWidget(row, 0)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk:
                    chk.setChecked(checked)

    def select_online_only(self, modules: List[ChargingModule]):
        """仅选中在线模块"""
        for row in range(self.rowCount()):
            chk_widget = self.cellWidget(row, 0)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk:
                    chk.setChecked(row < len(modules) and modules[row].online)


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("英飞源 REG系列模块监控上位机 v1.0 (以太网-CAN)")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)

        # CAN接口
        self.can: BaseCANInterface = create_can_interface('UT6502', self)
        self.modules = ModuleManager(63)  # 与表格63行保持一致
        self._current_can_box = 'UT6502'

        # 轮询定时器
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.on_poll_timeout)
        self.poll_index = 0
        self.auto_poll = False

        # 扫描状态
        self._scanning = False
        self._scan_index = 0
        self._scan_timer: Optional[QTimer] = None

        # 离线检测定时器
        self.offline_timer = QTimer(self)
        self.offline_timer.timeout.connect(self.on_check_offline)
        self.offline_timer.start(2000)  # 每2秒检查一次

        # 连接状态
        self.connected = False

        # 等待回复的模块地址
        self._pending_addr: Optional[int] = None
        self._pending_cmd: Optional[int] = None

        self.setup_ui()
        self.setup_signals()
        self.apply_styles()

    def setup_ui(self):
        """设置UI"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # === 连接配置 ===
        conn_group = QGroupBox("连接配置")
        conn_layout = QHBoxLayout(conn_group)
        conn_layout.setSpacing(10)

        conn_layout.addWidget(QLabel("CAN盒:"))
        self.can_box_combo = QComboBox()
        self.can_box_combo.addItem("宇泰 UT-6502", "UT6502")
        self.can_box_combo.addItem("ZLG CANFDNET-200U", "ZLG_CANFDNET")
        self.can_box_combo.setFixedWidth(180)
        self.can_box_combo.currentIndexChanged.connect(self.on_can_box_changed)
        conn_layout.addWidget(self.can_box_combo)

        conn_layout.addWidget(QLabel("IP:"))
        self.ip_edit = QLineEdit("192.168.1.125")
        self.ip_edit.setFixedWidth(130)
        conn_layout.addWidget(self.ip_edit)

        conn_layout.addWidget(QLabel("端口:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5001)
        self.port_spin.setFixedWidth(70)
        conn_layout.addWidget(self.port_spin)

        self.lbl_channel = QLabel("通道:")
        conn_layout.addWidget(self.lbl_channel)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("通道1", 0)
        self.channel_combo.addItem("通道2", 1)
        self.channel_combo.setFixedWidth(80)
        conn_layout.addWidget(self.channel_combo)
        # 通道仅 ZLG CANFDNET 有（其协议帧含通道字节）；宇泰 UT-6502 单通道无此概念，
        # 默认选中宇泰时隐藏，避免误导
        self.lbl_channel.setVisible(False)
        self.channel_combo.setVisible(False)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.setFixedWidth(70)
        self.btn_connect.clicked.connect(self.on_connect)
        conn_layout.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setObjectName("redBtn")
        self.btn_disconnect.setFixedWidth(70)
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.on_disconnect)
        conn_layout.addWidget(self.btn_disconnect)

        conn_layout.addSpacing(20)

        self.chk_auto_poll = QCheckBox("自动轮询在线模块")
        self.chk_auto_poll.setChecked(True)
        self.chk_auto_poll.stateChanged.connect(self.on_auto_poll_changed)
        conn_layout.addWidget(self.chk_auto_poll)

        conn_layout.addWidget(QLabel("间隔(ms):"))
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(50, 5000)
        self.poll_interval_spin.setValue(1000)
        self.poll_interval_spin.setSingleStep(100)
        self.poll_interval_spin.setFixedWidth(70)
        conn_layout.addWidget(self.poll_interval_spin)

        conn_layout.addStretch()
        main_layout.addWidget(conn_group)

        # === 批量操作 ===
        batch_group = QGroupBox("批量操作")
        batch_layout = QHBoxLayout(batch_group)
        batch_layout.setSpacing(10)

        self.btn_all_on = QPushButton("全部开机")
        self.btn_all_on.setObjectName("greenBtn")
        self.btn_all_on.clicked.connect(self.on_all_on)
        batch_layout.addWidget(self.btn_all_on)

        self.btn_all_off = QPushButton("全部关机")
        self.btn_all_off.setObjectName("redBtn")
        self.btn_all_off.clicked.connect(self.on_all_off)
        batch_layout.addWidget(self.btn_all_off)

        batch_layout.addWidget(QLabel("批量电压(V):"))
        self.batch_v_spin = QDoubleSpinBox()
        self.batch_v_spin.setRange(50, 750)
        self.batch_v_spin.setValue(50.0)
        self.batch_v_spin.setDecimals(1)
        self.batch_v_spin.setFixedWidth(80)
        batch_layout.addWidget(self.batch_v_spin)

        batch_layout.addWidget(QLabel("批量电流(A):"))
        self.batch_i_spin = QDoubleSpinBox()
        self.batch_i_spin.setRange(0, 60)
        self.batch_i_spin.setValue(50.0)
        self.batch_i_spin.setDecimals(1)
        self.batch_i_spin.setFixedWidth(80)
        batch_layout.addWidget(self.batch_i_spin)

        self.btn_batch_set_vi = QPushButton("批量设置电压电流")
        self.btn_batch_set_vi.clicked.connect(self.on_batch_set_vi)
        batch_layout.addWidget(self.btn_batch_set_vi)

        self.btn_init = QPushButton("一键初始化")
        self.btn_init.setObjectName("yellowBtn")
        self.btn_init.clicked.connect(self.on_one_key_init)
        batch_layout.addWidget(self.btn_init)

        self.btn_scan = QPushButton("扫描在线模块")
        self.btn_scan.clicked.connect(self.on_scan_modules)
        batch_layout.addWidget(self.btn_scan)

        self.btn_fault_codes = QPushButton("故障代码查询")
        self.btn_fault_codes.clicked.connect(self._on_show_fault_codes)
        batch_layout.addWidget(self.btn_fault_codes)

        batch_layout.addStretch()
        main_layout.addWidget(batch_group)

        # === 中间分割区域 ===
        splitter = QSplitter(Qt.Horizontal)

        # === 模块监控表格 ===
        table_group = QGroupBox("模块实时监控")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(4, 4, 4, 4)

        # 表格工具栏
        table_tool_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.clicked.connect(self.on_select_all)
        table_tool_layout.addWidget(self.btn_select_all)

        self.btn_clear_sel = QPushButton("清空")
        self.btn_clear_sel.clicked.connect(self.on_clear_selection)
        table_tool_layout.addWidget(self.btn_clear_sel)

        self.btn_sel_online = QPushButton("仅在线")
        self.btn_sel_online.clicked.connect(self.on_select_online)
        table_tool_layout.addWidget(self.btn_sel_online)

        table_tool_layout.addSpacing(20)

        self.btn_sel_on = QPushButton("选中开机")
        self.btn_sel_on.setObjectName("greenBtn")
        self.btn_sel_on.clicked.connect(self.on_selected_on)
        table_tool_layout.addWidget(self.btn_sel_on)

        self.btn_sel_off = QPushButton("选中关机")
        self.btn_sel_off.setObjectName("redBtn")
        self.btn_sel_off.clicked.connect(self.on_selected_off)
        table_tool_layout.addWidget(self.btn_sel_off)

        self.btn_sel_set_vi = QPushButton("选中设置V/I")
        self.btn_sel_set_vi.clicked.connect(self.on_selected_set_vi)
        table_tool_layout.addWidget(self.btn_sel_set_vi)

        table_tool_layout.addStretch()
        table_layout.addLayout(table_tool_layout)

        # 表格 - 63个模块地址 (0x01~0x3F)
        self.table = ModuleTableWidget()
        self.table._host = self
        self.table.itemClicked.connect(self._on_row_click_select)
        self.table.init_rows(63)
        table_layout.addWidget(self.table)

        splitter.addWidget(table_group)

        # === 右侧控制面板 ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 模块控制
        ctrl_group = QGroupBox("模块控制")
        ctrl_layout = QVBoxLayout(ctrl_group)

        ctrl_tabs = QTabWidget()
        ctrl_tabs.setMaximumHeight(300)

        # ID管理标签页
        id_tab = QWidget()
        id_layout = QVBoxLayout(id_tab)
        id_info = QLabel("模块ID通过生命帧触发分配\n(如0x18C1FFC1表示分配\n至模块当前ID)")
        id_info.setWordWrap(True)
        id_layout.addWidget(id_info)

        id_layout.addWidget(QLabel("当前模块ID:"))
        self.current_id_edit = QLineEdit()
        id_layout.addWidget(self.current_id_edit)

        id_layout.addWidget(QLabel("新模块ID:"))
        self.new_id_edit = QLineEdit()
        id_layout.addWidget(self.new_id_edit)

        self.btn_change_id = QPushButton("修改模块ID")
        self.btn_change_id.setObjectName("accentBtn")
        self.btn_change_id.clicked.connect(self.on_change_module_id)
        id_layout.addWidget(self.btn_change_id)

        id_layout.addStretch()
        ctrl_tabs.addTab(id_tab, "ID管理")

        # 高级设置标签页
        adv_tab = QWidget()
        adv_layout = QVBoxLayout(adv_tab)
        adv_layout.addWidget(QLabel("Walk-in使能:"))
        self.walkin_combo = QComboBox()
        self.walkin_combo.addItems(["保持", "使能", "禁止"])
        adv_layout.addWidget(self.walkin_combo)

        adv_layout.addWidget(QLabel("设置组号:"))
        self.group_spin = QSpinBox()
        self.group_spin.setRange(0, 255)
        adv_layout.addWidget(self.group_spin)

        self.btn_set_group = QPushButton("设置组号")
        self.btn_set_group.setObjectName("accentBtn")
        self.btn_set_group.clicked.connect(self.on_set_group)
        adv_layout.addWidget(self.btn_set_group)

        # 地址分配方式 (0x1F)
        adv_layout.addWidget(QLabel("地址分配方式(广播):"))
        addr_mode_row = QHBoxLayout()
        self.btn_dial_mode = QPushButton("设为拨码方式")
        self.btn_dial_mode.setObjectName("accentBtn")
        self.btn_dial_mode.clicked.connect(self.on_set_dial_mode)
        self.btn_auto_mode = QPushButton("设为自动分配")
        self.btn_auto_mode.setObjectName("accentBtn")
        self.btn_auto_mode.clicked.connect(self.on_set_auto_mode)
        addr_mode_row.addWidget(self.btn_dial_mode)
        addr_mode_row.addWidget(self.btn_auto_mode)
        adv_layout.addLayout(addr_mode_row)
        addr_hint = QLabel("拨码方式: 模块地址=面板拨码值; 设为拨码后需重新扫描, 如组号也需要另行设置")
        addr_hint.setWordWrap(True)
        addr_hint.setStyleSheet("color:#8b8b8b; font-size:11px;")
        adv_layout.addWidget(addr_hint)

        adv_layout.addStretch()
        ctrl_tabs.addTab(adv_tab, "高级设置")

        ctrl_layout.addWidget(ctrl_tabs)
        right_layout.addWidget(ctrl_group)

        # 信息面板
        info_group = QGroupBox("模块信息")
        info_layout = QVBoxLayout(info_group)
        self.info_label = QLabel("请选择模块查看详细信息")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)
        right_layout.addWidget(info_group)

        right_layout.addStretch()
        splitter.addWidget(right_panel)
        splitter.setSizes([1200, 300])

        main_layout.addWidget(splitter, 1)

        # === CAN报文日志 ===
        log_group = QGroupBox("CAN报文日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(4, 4, 4, 4)

        log_tool_layout = QHBoxLayout()
        self.chk_show_tx = QCheckBox("显示发送")
        self.chk_show_tx.setChecked(True)
        log_tool_layout.addWidget(self.chk_show_tx)

        self.chk_show_rx = QCheckBox("显示接收")
        self.chk_show_rx.setChecked(True)
        log_tool_layout.addWidget(self.chk_show_rx)

        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        log_tool_layout.addWidget(self.chk_auto_scroll)

        self.btn_clear_log = QPushButton("清空日志")
        self.btn_clear_log.clicked.connect(self.on_clear_log)
        log_tool_layout.addWidget(self.btn_clear_log)

        log_tool_layout.addStretch()
        log_layout.addLayout(log_tool_layout)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        log_layout.addWidget(self.log_edit)

        main_layout.addWidget(log_group, 0)

    def setup_signals(self):
        """设置信号连接"""
        self.can.connected.connect(self.on_can_connected)
        self.can.disconnected.connect(self.on_can_disconnected)
        self.can.frame_received.connect(self.on_can_frame_received)
        self.can.log_message.connect(self.on_can_log)
        self.can.error_occurred.connect(self.on_can_error)

    def apply_styles(self):
        """应用样式"""
        self.setStyleSheet(expand_qss(StyleSheet.MAIN))

    # ========== 槽函数 ==========

    @pyqtSlot()
    def on_connect(self):
        """连接按钮"""
        ip = self.ip_edit.text()
        port = self.port_spin.value()

        # 检查CAN盒类型是否需要切换
        box_type = self.can_box_combo.currentData()
        if box_type != self._current_can_box or self.can.get_channel() != self.channel_combo.currentData():
            self._switch_can_box(box_type, self.channel_combo.currentData())

        if self.can.connect(ip, port):
            self.connected = True
            self.btn_connect.setEnabled(False)
            self.btn_connect.setText("已连接")
            self.btn_connect.setObjectName("btnConnected")
            self.btn_disconnect.setEnabled(True)
            self.auto_poll = self.chk_auto_poll.isChecked()
            if self.auto_poll:
                self.start_polling()

    def _sync_channel_visibility(self, box_type: str) -> None:
        """通道下拉仅 ZLG 有实际含义（协议帧含通道字节）；宇泰单通道，隐藏避免误导。"""
        show = (box_type == "ZLG_CANFDNET")
        self.lbl_channel.setVisible(show)
        self.channel_combo.setVisible(show)

    def _switch_can_box(self, box_type: str, channel: int = 0):
        """切换CAN盒适配器"""
        # 断开旧适配器的信号
        try:
            self.can.connected.disconnect(self.on_can_connected)
            self.can.disconnected.disconnect(self.on_can_disconnected)
            self.can.frame_received.disconnect(self.on_can_frame_received)
            self.can.log_message.disconnect(self.on_can_log)
            self.can.error_occurred.disconnect(self.on_can_error)
        except Exception:
            pass

        # 创建新适配器
        new_can = create_can_interface(box_type, self, channel=channel)
        self.can = new_can
        self._current_can_box = box_type
        # 重新连接信号
        self.setup_signals()
        ch_str = f"通道{channel + 1}" if box_type == 'ZLG_CANFDNET' else "通道1"
        self.log_edit.append(
            f'<span style="color:#6B7280">[系统] 已切换CAN盒适配器为: {box_type} ({ch_str})</span>'
        )

    @pyqtSlot(int)
    def on_can_box_changed(self, index: int):
        """CAN盒类型变更"""
        box_type = self.can_box_combo.currentData()
        if self.connected:
            QMessageBox.warning(self, "提示", "请先断开当前连接再切换CAN盒")
            # 恢复选择
            for i in range(self.can_box_combo.count()):
                if self.can_box_combo.itemData(i) == self._current_can_box:
                    self.can_box_combo.blockSignals(True)
                    self.can_box_combo.setCurrentIndex(i)
                    self.can_box_combo.blockSignals(False)
                    break
            return

        # 根据类型更新默认端口
        self._sync_channel_visibility(box_type)
        if box_type == 'ZLG_CANFDNET':
            self.port_spin.setValue(4001)  # ZLG默认4001
        else:
            self.port_spin.setValue(5001)  # UT-6502默认5001

    @pyqtSlot()
    def on_disconnect(self):
        """断开按钮"""
        self.stop_polling()
        self._stop_scan()
        self.can.disconnect()
        self.connected = False
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_disconnect.setEnabled(False)

    @pyqtSlot()
    def on_can_connected(self):
        """CAN已连接"""
        pass

    @pyqtSlot()
    def on_can_disconnected(self):
        """CAN已断开"""
        self.connected = False
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_disconnect.setEnabled(False)
        self._stop_scan()
        self.stop_polling()

    @pyqtSlot(CANFrame)
    def on_can_frame_received(self, frame: CANFrame):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到设备 CAN 帧 = 通讯真正建立
        """收到CAN帧"""
        cmd = frame.command
        src = frame.src_addr

        # 解析回复数据: 电压电流(0x03浮点, 部分固件用)/定点(0x09)
        if cmd == CommandCode.READ_MODULE_VOLTAGE_CURRENT:
            # 0x03 浮点电压电流回复: data[0:4]=电压V(float), data[4:8]=电流A(float)
            if 0 <= src < 63:
                v, i = InfyCANProtocol.parse_float_voltage_current(frame.data)
                self.log_edit.append(
                    f'<span style="color:#CC7832">[0x03] 源0x{src:02X} '
                    f'data={frame.data.hex(" ").upper()} -> {v:.2f}V / {i:.3f}A</span>'
                )
                module = self.modules.get_module(src)
                if module:
                    module.update_voltage_current(int(v * 1000), int(i * 1000))
                    module.resp_count += 1
                    module.online = module.resp_count >= 2
                    self.table.update_module(module, src)

        elif cmd == CommandCode.READ_MODULE_VOLTAGE_CURRENT_FIXED:
            # 0x09 定点电压电流回复
            if 0 <= src < 63:
                v, i = InfyCANProtocol.parse_fixed_voltage_current(frame.data)
                module = self.modules.get_module(src)
                if module:
                    module.update_voltage_current(v, i)
                    module.resp_count += 1
                    module.online = module.resp_count >= 2
                    self.table.update_module(module, src)

        elif cmd == CommandCode.READ_MODULE_STATUS:
            # 0x04 状态回复
            if 0 <= src < 63:
                status = InfyCANProtocol.parse_module_status(frame.data)
                module = self.modules.get_module(src)
                if module:
                    module.update_status(status)
                    module.resp_count += 1
                    module.online = module.resp_count >= 2
                    self.table.update_module(module, src)

        elif cmd == CommandCode.READ_MODULE_INPUT_VOLTAGE:
            # 0x06 输入电压回复
            if 0 <= src < 63:
                voltages = InfyCANProtocol.parse_input_voltage(frame.data)
                module = self.modules.get_module(src)
                if module:
                    module.update_input_voltage(
                        voltages.get('Vab', 0),
                        voltages.get('Vbc', 0),
                        voltages.get('Vca', 0)
                    )
                    module.resp_count += 1
                    module.online = module.resp_count >= 2
                    self.table.update_module(module, src)

        elif cmd == CommandCode.READ_MODULE_INFO:
            # 0x0A 模块信息回复
            if 0 <= src < 63:
                info = InfyCANProtocol.parse_module_info(frame.data)
                module = self.modules.get_module(src)
                if module:
                    module.update_module_info(info)
                    module.resp_count += 1
                    module.online = module.resp_count >= 2
                    self.table.update_module(module, src)

        elif cmd == CommandCode.READ_EXTERNAL_VOLTAGE_CURRENT:
            # 0x0C 外部电压/允许电流回复
            if 0 <= src < 63:
                v, i = InfyCANProtocol.parse_external_voltage_current(frame.data)
                module = self.modules.get_module(src)
                if module:
                    module.update_external(v, i)
                    self.table.update_module(module, src)

        elif cmd == CommandCode.READ_MODULE_BARCODE:
            # 0x0B 条码回复
            if 0 <= src < 63:
                barcode = InfyCANProtocol.parse_barcode(frame.data)
                module = self.modules.get_module(src)
                if module:
                    module.barcode = barcode
                    self.table.update_module(module, src)

        # 收到任何合法帧 -> 刷新该模块的最后更新时间
        if 0 <= src < 63:
            module = self.modules.get_module(src)
            if module:
                import time as _t
                module.last_update_time = _t.time()

    @pyqtSlot()
    def on_check_offline(self):
        """定时检查离线模块: 超过离线超时无数据更新则判定离线"""
        if not self.connected:
            return
        changed = self.modules.check_offline(timeout_sec=6.0)
        for addr in changed:
            module = self.modules.get_module(addr)
            if module:
                self.table.update_module(module, addr)
        # 通讯状态：全部模块离线（无任何在线模块）时，视为通讯中断
        from instrument_hub.comm_state import mark_lost
        if not any(m.online for m in self.modules.modules):
            mark_lost(self)

    @pyqtSlot(str, str)
    def on_can_log(self, message: str, direction: str):
        """CAN日志"""
        if direction == "TX" and not self.chk_show_tx.isChecked():
            return
        if direction == "RX" and not self.chk_show_rx.isChecked():
            return

        color_map = {"TX": "#6A8759", "RX": "#CC7832", "SYS": "#808080"}
        color = color_map.get(direction, "#BBBBBB")
        timestamp = time.strftime("%H:%M:%S")
        html = f'<span style="color:#6B7280">[{timestamp}]</span> '
        html += f'<span style="color:{color}">{direction}</span> {message}'
        self.log_edit.append(html)

        if self.chk_auto_scroll.isChecked():
            scrollbar = self.log_edit.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    @pyqtSlot(str)
    def on_can_error(self, error: str):
        """CAN错误"""
        self.log_edit.append(f'<span style="color:#B01030">[错误] {error}</span>')

    @pyqtSlot()
    def on_poll_timeout(self):
        """轮询定时器 — 只轮询在线模块（不再全地址空探测，发现新模块请重扫）。

        在线模块约 400ms 刷一遍，保证电压/状态实时跟手。
        """
        if not self.can.is_connected():
            return

        online = [m.addr for m in self.modules.modules
                  if m.online and m.addr < 63]
        online.sort()

        # 每tick最多刷这么多在线模块(在线少时一次全刷)
        MAX_ONLINE_PER_TICK = 18
        n = len(online)
        if n:
            idx = getattr(self, '_poll_online_idx', 0) % n
            for k in range(min(n, MAX_ONLINE_PER_TICK)):
                addr = online[(idx + k) % n]
                self._send_module_queries(addr)
            self._poll_online_idx = (idx + MAX_ONLINE_PER_TICK) % n

    def _send_module_queries(self, addr: int):
        """对单个地址下发 电压电流(0x03) + 状态(0x04) + 输入电压(0x06)"""
        if addr < 0 or addr >= 63:
            return
        self.can.send_frame(InfyCANProtocol.read_module_voltage_current_float(addr))
        self.can.send_frame(InfyCANProtocol.read_module_status(addr))
        self.can.send_frame(InfyCANProtocol.read_module_input_voltage(addr))

    def start_polling(self):
        """开始轮询"""
        self.poll_timer.start(400)
        self.log_edit.append('<span style="color:#047857">[系统] 开始自动轮询模块</span>')

    def stop_polling(self):
        """停止轮询"""
        self.poll_timer.stop()

    def on_auto_poll_changed(self, state):
        """自动轮询状态改变"""
        self.auto_poll = (state == Qt.Checked)
        if self.auto_poll and self.connected:
            self.start_polling()
        else:
            self.stop_polling()

    # ========== 批量操作 ==========

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
        """显示 INFY 模块状态字/告警位说明(位定义以协议 V1.09 0x04 状态表原文为准)"""
        lines = ["INFY 模块状态字与告警位定义", ""]
        lines.append("状态表0 (告警):")
        for name in ["bit0 输出短路", "bit1 模块故障", "bit2 内部通信故障",
                     "bit3 输入/母线异常", "bit5 放电异常", "bit6 风道不畅",
                     "bit7 通信中断"]:
            lines.append(f"  - {name}")
        lines.append("  - bit4 模块休眠 (状态位, 不计故障)")
        lines.append("")
        lines.append("状态表1 (告警):")
        for name in ["bit1 ID重复", "bit2 保护告警", "bit3 风扇故障",
                     "bit4 过温告警", "bit5 输出过压"]:
            lines.append(f"  - {name}")
        lines.append("  - bit0 DC侧关机 (状态位)  bit6 Walkin使能 (状态位)")
        lines.append("")
        lines.append("状态表2 (告警):")
        for name in ["bit2 严重不均流", "bit3 三相缺相", "bit4 三相不平衡",
                     "bit5 输入欠压", "bit6 输入过压"]:
            lines.append(f"  - {name}")
        lines.append("  - bit0 限功率 (状态位)  bit7 PFC侧关机 (状态位)")
        lines.append("")
        lines.append("状态表3 高低压模式: bit[2:1] 1=高低压自动 2=低压 3=高压")
        lines.append("")
        lines.append("组号: 0x04 应答 Byte2 (面板拨码设置, 出厂默认组0)")
        QMessageBox.information(self, "故障代码查询", "\n".join(lines))

    def on_all_on(self):
        """全部开机"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        if not self._confirm_power_on(None, True, "确认全部开机"):
            return
        frame = InfyCANProtocol.set_onoff(True)
        self.can.send_frame(frame)
        self.log_edit.append('<span style="color:#047857">[操作] 发送全部开机命令</span>')

    def on_all_off(self):
        """全部关机"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        frame = InfyCANProtocol.set_onoff(False)
        self.can.send_frame(frame)
        self.log_edit.append('<span style="color:#B01030">[操作] 发送全部关机命令</span>')

    def on_batch_set_vi(self):
        """批量设置电压电流"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        voltage = int(self.batch_v_spin.value() * 1000)
        current = int(self.batch_i_spin.value() * 1000)
        frame = InfyCANProtocol.set_voltage_total_current(voltage, current)
        self.can.send_frame(frame)
        self.log_edit.append(
            f'<span style="color:#6A8759">[操作] 批量设置电压:{voltage/1000:.1f}V 电流:{current/1000:.1f}A</span>'
        )

    def on_one_key_init(self):
        """一键初始化"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        # 设置地址为自动分配
        frame = InfyCANProtocol.set_address_mode(False)
        self.can.send_frame(frame)
        self.log_edit.append('<span style="color:#6A8759">[操作] 一键初始化: 设置自动分配地址</span>')

    def on_scan_modules(self):
        """扫描在线模块; 扫描中再点此按钮=中断扫描"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return

        if self._scanning:
            self._stop_scan()
            self.log_edit.append('<span style="color:#f9e2af">[系统] 已中断扫描</span>')
            return

        self._scanning = True
        self.btn_scan.setText("停止扫描")
        self.log_edit.append('<span style="color:#6A8759">[操作] 开始扫描在线模块...</span>')

        # 先清空所有模块的在线状态
        self.modules.reset_all()
        for row in range(63):
            self.table.update_module(self.modules.modules[row], row)

        # 启动定时器逐个扫描
        self._scan_index = 0
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._do_scan_next)
        self._scan_timer.start(30)  # 30ms间隔, 63个约2秒扫描完

    def _do_scan_next(self):
        """扫描下一个地址"""
        if not self._scanning or not self.can.is_connected():
            self._stop_scan()
            return

        addr = self._scan_index
        if addr >= 63:
            # 扫描完成
            self._stop_scan()
            # 本轮有应答即判在线（容错：部分固件只应答其中一种命令，
            # 单轮 1 次应答不足以跨过 resp_count>=2 的轮询防抖阈值）
            for row, m in enumerate(self.modules.modules):
                if m.resp_count > 0 and not m.online:
                    m.online = True
                self.table.update_module(m, row)
            online_count = sum(1 for m in self.modules.modules if m.online)
            self.log_edit.append(
                f'<span style="color:#047857">[扫描完成] 共发现 {online_count} 个在线模块</span>'
            )
            # 确保持续轮询, 避免模块因无数据流被误判离线
            if self.can.is_connected() and not self.poll_timer.isActive():
                self.start_polling()
                self.log_edit.append(
                    '<span style="color:#047857">[系统] 已开启持续轮询刷新</span>'
                )
            return

        # 发送查询: 浮点(0x03) + 定点(0x09) + 状态(0x04)——
        # 部分固件只认 0x03 浮点、部分只认 0x09 定点，两种都发才扫得全
        self.can.send_frame(InfyCANProtocol.read_module_voltage_current_float(addr))
        self.can.send_frame(InfyCANProtocol.read_module_voltage_current(addr))
        self.can.send_frame(InfyCANProtocol.read_module_status(addr))

        self._scan_index += 1

    def _stop_scan(self):
        """停止扫描"""
        self._scanning = False
        self.btn_scan.setText("扫描在线模块")
        if hasattr(self, '_scan_timer') and self._scan_timer:
            self._scan_timer.stop()
            self._scan_timer = None

    # ========== 表格操作 ==========

    def on_select_all(self):
        """全选"""
        self.table.set_all_checked(True)

    def on_clear_selection(self):
        """清空选择"""
        self.table.set_all_checked(False)

    def on_select_online(self):
        """仅选中在线"""
        self.table.select_online_only(self.modules.modules)

    def on_selected_on(self):
        """选中开机"""
        selected = self.table.get_selected_rows()
        if not selected:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        if not self._confirm_power_on(selected, False, "确认选中开机"):
            return
        for addr in selected:
            frame = InfyCANProtocol.set_onoff(True, addr=addr)
            self.can.send_frame(frame)
        self.log_edit.append(f'<span style="color:#047857">[操作] 选中模块开机: {len(selected)}个</span>')

    def on_selected_off(self):
        """选中关机"""
        selected = self.table.get_selected_rows()
        if not selected:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        for addr in selected:
            frame = InfyCANProtocol.set_onoff(False, addr=addr)
            self.can.send_frame(frame)
        self.log_edit.append(f'<span style="color:#B01030">[操作] 选中模块关机: {len(selected)}个</span>')

    def on_selected_set_vi(self):
        """选中设置V/I"""
        selected = self.table.get_selected_rows()
        if not selected:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        voltage = int(self.batch_v_spin.value() * 1000)
        current = int(self.batch_i_spin.value() * 1000)
        for addr in selected:
            frame = InfyCANProtocol.set_voltage_current(voltage, current, addr=addr)
            self.can.send_frame(frame)
        self.log_edit.append(
            f'<span style="color:#6A8759">[操作] 选中模块设置V/I: {len(selected)}个, '
            f'{voltage/1000:.1f}V/{current/1000:.1f}A</span>'
        )

    # ========== 单行操作 ==========

    def on_module_on(self, addr: int):
        """模块开机 (协议推荐时序: 先设置输出电压电流(0x1C), 再开机(0x1A))"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        if not self._confirm_power_on([addr], False, "确认开机"):
            return
        # 开机前先下发一次输出电压/电流, 确保模块按设定值输出
        module = self.modules.get_module(addr) if self.modules else None
        sv = module.set_voltage if module and module.set_voltage > 0 else 0
        sc = module.set_current if module and module.set_current > 0 else 0
        if sv <= 0 or sc <= 0:
            # 模块无设置值则用主面板批量V/I
            sv = int(self.batch_v_spin.value() * 1000)
            sc = int(self.batch_i_spin.value() * 1000)
        if sv > 0 and sc > 0:
            self.can.send_frame(
                InfyCANProtocol.set_voltage_current(sv, sc, addr=addr)
            )
            self.log_edit.append(
                f'<span style="color:#6A8759">[操作] 模块0x{addr:02X} 先设置 '
                f'{sv/1000:.1f}V/{sc/1000:.1f}A</span>'
            )
        frame = InfyCANProtocol.set_onoff(True, addr=addr)
        self.can.send_frame(frame)
        self.log_edit.append(f'<span style="color:#047857">[操作] 模块0x{addr:02X} 开机</span>')

    def on_module_off(self, addr: int):
        """模块关机"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        frame = InfyCANProtocol.set_onoff(False, addr=addr)
        self.can.send_frame(frame)
        self.log_edit.append(f'<span style="color:#B01030">[操作] 模块0x{addr:02X} 关机</span>')

    def _on_row_click_select(self, item):
        """模块地址选中固定在勾选列，其余列点击不可选中（规范）"""
        return

    def on_module_set_vi(self, addr: int):
        """模块设置V/I"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        voltage = int(self.batch_v_spin.value() * 1000)
        current = int(self.batch_i_spin.value() * 1000)
        frame = InfyCANProtocol.set_voltage_current(voltage, current, addr=addr)
        self.can.send_frame(frame)
        self.log_edit.append(
            f'<span style="color:#6A8759">[操作] 模块0x{addr:02X} 设置 {voltage/1000:.1f}V/{current/1000:.1f}A</span>'
        )

    def apply_module_set_vi(self, row: int, vV: float, iV: float):
        """从表格设置列输入电压/电流并下发 (0x1C 设置输出电压和电流)
        row: 0-based模块地址; vV: 电压(V); iV: 电流(A)
        """
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        voltage_mv = int(vV * 1000)
        current_ma = int(iV * 1000)
        frame = InfyCANProtocol.set_voltage_current(voltage_mv, current_ma, addr=row)
        self.can.send_frame(frame)

        # 本地回显设置值
        module = self.modules.get_module(row)
        if module:
            module.set_voltage = voltage_mv
            module.set_current = current_ma
            self.table.update_module(module, row)

        self.log_edit.append(
            f'<span style="color:#6A8759">[操作] 模块0x{row:02X} 下发设置 {vV:.1f}V / {iV:.1f}A</span>'
        )

    def on_set_group(self):
        """设置组号"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        selected = self.table.get_selected_rows()
        if not selected:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        group = self.group_spin.value()
        for addr in selected:
            frame = InfyCANProtocol.set_group_id(group, addr)
            self.can.send_frame(frame)
        self.log_edit.append(f'<span style="color:#6A8759">[操作] 设置组号 {group}: {len(selected)}个模块</span>')

    def on_set_dial_mode(self):
        """设置所有模块地址为拨码方式 (0x1F, 广播, 无回复)"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        frame = InfyCANProtocol.set_address_mode(dial_mode=True)
        self.can.send_frame(frame)
        self.log_edit.append(
            '<span style="color:#047857">[操作] 已下发: 全部模块设为【地址拨码方式】(0x1F=01)。'
            '请重新扫描以按拨码地址识别模块; 如需组号请另行设置(0x16)</span>'
        )
        QMessageBox.information(
            self, "拨码方式",
            "已下发(0x1F=1,广播)将全部模块设为地址拨码方式。\n\n"
            "设置后每个模块的地址=其面板拨码值。\n"
            "请点击【扫描在线模块】重新扫描，并按拨码值确认各模块行。\n\n"
            "注意: 设为地址拨码后，组号已不由拨码决定，如需分组请另行设置组号(0x16)。"
        )

    def on_set_auto_mode(self):
        """设置所有模块地址为自动分配方式 (0x1F, 广播)"""
        if not self.can.is_connected():
            QMessageBox.warning(self, "警告", "请先连接CAN设备")
            return
        frame = InfyCANProtocol.set_address_mode(dial_mode=False)
        self.can.send_frame(frame)
        self.log_edit.append(
            '<span style="color:#047857">[操作] 已下发: 全部模块设为【地址自动分配方式】。请重新扫描</span>'
        )

    def on_clear_log(self):
        """清空日志"""
        self.log_edit.clear()

    def on_change_module_id(self):
        """修改模块ID"""
        QMessageBox.information(
            self, "模块ID修改",
            "模块地址修改方式:\n"
            "1. 自动分配: 使用[一键初始化]设置自动分配地址\n"
            "2. 拨码方式: 使用[设置地址分配方式]为拨码方式，"
            "通过模块面板拨码开关设置地址\n\n"
            "注意: 拨码方式下组号需通过0x16命令设置"
        )

    def closeEvent(self, event):
        try:
            """关闭事件"""
            self.stop_polling()
            self._stop_scan()
            # 停止离线检测定时器，避免卸载后仍在后台跑
            if self.offline_timer.isActive():
                self.offline_timer.stop()
            self.can.disconnect()
            event.accept()
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass
