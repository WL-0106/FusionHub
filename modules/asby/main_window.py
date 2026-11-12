# -*- coding: utf-8 -*-
"""
安世博源 HBTW 模块监控上位机
主窗口
"""

import sys
import time
from modules.theme_util import expand_qss
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter, QTabWidget, QTextEdit, QScrollArea,
    QGroupBox, QFrame, QComboBox, QMessageBox, QAbstractItemView,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt5.QtGui import QColor, QFont, QBrush, QPalette

from .ut6502_client import UT6502Client
from .module_data import ModuleManager
from .can_protocol import (
    parse_ut6502_frame, parse_can_id, parse_data_frame,
    build_set_command, build_read_command, build_power_command,
    build_voltage_set_command, build_current_set_command,
    build_mode_set_command, build_power_set_command,
    MSG_READ_RESP, MSG_SET_RESP, MSG_SN_RESP,
    CMD_VOUT, CMD_IOUT, CMD_VOUT_SET, CMD_IOUT_LIMIT,
    CMD_MODULE_STATUS, CMD_OUTPUT_MODE, CMD_ALARM1, CMD_ALARM2,
    CMD_P_ACTIVE, CMD_P_REACTIVE, CMD_P_APPARENT,
    CMD_P_ACTIVE_SET, CMD_P_REACTIVE_SET,
    CMD_POWER_CTRL, CMD_GROUP_ADDR, CMD_VBAT, CMD_EXTENDED, EXT_COMM_TIMEOUT,
    get_alarm_descriptions, STATUS_NAMES, MODE_NAMES,
    FAULT_CODES, fault_code_text, guess_fault_codes
)


# 统一浅色主题颜色
COLOR_BG_DARK = "#F3F2FA"
COLOR_BG_MID = "#E4E9EF"
COLOR_BG_LIGHT = "#E4E9EF"
COLOR_TEXT = "#2A3340"
COLOR_TEXT_DIM = "#6B7280"
COLOR_ACCENT = "#4F46E5"
COLOR_GREEN = "#047857"
COLOR_RED = "#B01030"
COLOR_YELLOW = "#F59E0B"
COLOR_BLUE = "#4F46E5"
COLOR_BORDER = "#D9D6EE"


class DarkStyle:
    """深色样式表"""
    
    @staticmethod
    def get_style():
        return """
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
    
    COLUMNS = [
        ("", 44),           # 复选框（加宽，避免勾选框被压扁）
        ("地址", 60),       # 地址
        ("在线", 50),       # 在线状态
        ("电源", 50),       # 电源状态
        ("电压(V)", 80),    # 输出电压
        ("电流(A)", 80),    # 输出电流
        ("设置电压(V)", 90), # 设置电压
        ("设置电流(A)", 90), # 设置电流
        ("模式", 100),      # 运行模式
        ("故障", 80),       # 故障
        ("开机", 55),       # 开机按钮
        ("关机", 55),       # 关机按钮
        ("设置V/I", 70),    # 设置V/I按钮
    ]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.COLUMNS))
        self.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        
        # 设置列宽
        for i, (name, width) in enumerate(self.COLUMNS):
            self.setColumnWidth(i, width)
        
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionsMovable(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setStyleSheet(f"""
            QTableWidget {{
                alternate-background-color: #F7F9FB;
                background-color: {COLOR_BG_MID};
            }}
        """)
        self.verticalHeader().setDefaultSectionSize(28)
        self.verticalHeader().setVisible(False)
        
        self.itemClicked.connect(self._on_row_click_select)
        self.module_manager = None
        self.power_on_callback = None
        self.power_off_callback = None
        self.set_vi_callback = None
        self.set_vi_values_callback = None
        self.selection_changed_callback = None
        self._sv = {}
        self._si = {}
    
    def set_module_manager(self, manager):
        """设置模块管理器"""
        self.module_manager = manager
        self._populate_table()
    
    def _populate_table(self):
        """填充表格"""
        if not self.module_manager:
            return
        
        modules = self.module_manager.get_all_modules()
        self.setRowCount(len(modules))
        
        for row, module in enumerate(modules):
            self._set_row(row, module)
    
    def _set_row(self, row, module):
        """设置一行数据"""
        # 复选框列
        checkbox_widget = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignCenter)
        checkbox = QCheckBox()
        checkbox.setChecked(module.selected)
        checkbox.setStyleSheet("QCheckBox { spacing: 0px; }")
        checkbox.stateChanged.connect(lambda state, addr=module.addr: self._on_checkbox_changed(addr, state))
        checkbox_layout.addWidget(checkbox)
        self.setCellWidget(row, 0, checkbox_widget)
        
        # 地址列
        addr_item = QTableWidgetItem(f"0x{module.addr:02X}")
        addr_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 1, addr_item)
        
        # 在线列
        online_text = "在线" if module.online else "离线"
        online_item = QTableWidgetItem("● 在线" if module.online else "○ 离线")
        online_item.setTextAlignment(Qt.AlignCenter)
        online_item.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        if module.online:
            online_item.setForeground(QBrush(QColor("#047857")))
        else:
            online_item.setForeground(QBrush(QColor("#9AA2AA")))
        self.setItem(row, 2, online_item)
        
        # 电源列：开/关以 power_on 为准；故障放故障列（关机时不再误标“故障”）
        power_text = "开机" if module.power_on else "关机"
        power_item = QTableWidgetItem(power_text)
        power_item.setTextAlignment(Qt.AlignCenter)
        if module.power_on:
            power_item.setForeground(QBrush(QColor(COLOR_GREEN)))
        else:
            power_item.setForeground(QBrush(QColor(COLOR_TEXT_DIM)))
        self.setItem(row, 3, power_item)
        
        # 电压列
        v_text = f"{module.voltage:.2f}" if module.online else "---"
        v_item = QTableWidgetItem(v_text)
        v_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 4, v_item)
        
        # 电流列
        i_text = f"{module.current:.2f}" if module.online else "---"
        i_item = QTableWidgetItem(i_text)
        i_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 5, i_item)
        
        # 设置电压列：行内可编辑输入框
        sv_item = QTableWidgetItem(f"{module.set_voltage:.2f}" if module.online else "---")
        sv_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 6, sv_item)
        sv_w = self._sv.get(module.addr)
        if sv_w is None:
            sv_w = QDoubleSpinBox()
            sv_w.setRange(0, 1200)
            sv_w.setDecimals(2)
            sv_w.setSingleStep(0.5)
            sv_w.setMinimumWidth(80)
            # 用户改过之后轮询不再覆盖，避免“点设置后被旧值顶掉”
            sv_w.valueChanged.connect(lambda _v, w=sv_w: setattr(w, "_user_edited", True))
            self.setCellWidget(row, 6, sv_w)
            self._sv[module.addr] = sv_w
        if (module.online and not sv_w.hasFocus()
                and not getattr(sv_w, "_user_edited", False)):
            sv_w.blockSignals(True)
            sv_w.setValue(module.set_voltage)
            sv_w.blockSignals(False)

        # 设置电流列：行内可编辑输入框
        si_item = QTableWidgetItem(f"{module.set_current:.2f}" if module.online else "---")
        si_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 7, si_item)
        si_w = self._si.get(module.addr)
        if si_w is None:
            si_w = QDoubleSpinBox()
            si_w.setRange(0, 300)
            si_w.setDecimals(2)
            si_w.setSingleStep(0.5)
            si_w.setMinimumWidth(80)
            si_w.valueChanged.connect(lambda _v, w=si_w: setattr(w, "_user_edited", True))
            self.setCellWidget(row, 7, si_w)
            self._si[module.addr] = si_w
        if (module.online and not si_w.hasFocus()
                and not getattr(si_w, "_user_edited", False)):
            si_w.blockSignals(True)
            si_w.setValue(module.set_current)
            si_w.blockSignals(False)
        
        # 模式列
        mode_text = module.get_mode_text() if module.online else "---"
        mode_item = QTableWidgetItem(mode_text)
        mode_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 8, mode_item)
        
        # 故障列
        alarm_count = module.get_alarm_count()
        if not module.online:
            fault_text = "---"
        elif alarm_count > 0 or module.status == 9:
            fault_text = self._format_fault(module)
        else:
            fault_text = "正常"
        fault_item = QTableWidgetItem(fault_text)
        fault_item.setTextAlignment(Qt.AlignCenter)
        if (alarm_count > 0 or module.status == 9) and module.online:
            fault_item.setForeground(QBrush(QColor(COLOR_RED)))
        if module.online and (module.alarm1 or module.alarm2 or module.status == 9):
            try:
                fault_item.setToolTip(self._fault_tooltip(module))
            except Exception:
                pass
        self.setItem(row, 9, fault_item)
        
        # 开机按钮
        btn_on = QPushButton("开")
        btn_on.setObjectName("btnPowerOn")
        btn_on.setFixedSize(44, 24)
        btn_on.clicked.connect(lambda checked, addr=module.addr: self._on_power_on_clicked(addr))
        self.setCellWidget(row, 10, btn_on)
        
        # 关机按钮
        btn_off = QPushButton("关")
        btn_off.setObjectName("btnPowerOff")
        btn_off.setFixedSize(44, 24)
        btn_off.clicked.connect(lambda checked, addr=module.addr: self._on_power_off_clicked(addr))
        self.setCellWidget(row, 11, btn_off)
        
        # 设置V/I按钮
        btn_set = QPushButton("设置")
        btn_set.setObjectName("btnSetVI")
        btn_set.setFixedSize(56, 24)
        btn_set.clicked.connect(lambda checked, addr=module.addr: self._on_set_vi_clicked(addr))
        self.setCellWidget(row, 12, btn_set)
        
        # 设置行背景色
        if not module.online:
            for col in range(self.columnCount()):
                item = self.item(row, col)
                if item:
                    item.setBackground(QBrush(QColor("#F2F4F7")))
    
    def _on_row_click_select(self, item):
        """模块地址选中固定在勾选列，其余列点击不可选中（规范）"""
        return

    def _on_checkbox_changed(self, addr, state):
        """复选框状态改变"""
        if self.module_manager:
            self.module_manager.set_selected(addr, state == Qt.Checked)
            if self.selection_changed_callback:
                self.selection_changed_callback()
    
    def _on_power_on_clicked(self, addr):
        """开机按钮点击"""
        if self.power_on_callback:
            self.power_on_callback(addr)
    
    def _on_power_off_clicked(self, addr):
        """关机按钮点击"""
        if self.power_off_callback:
            self.power_off_callback(addr)
    
    def _on_set_vi_clicked(self, addr):
        """设置V/I按钮点击：优先读取该行输入框"""
        sv = self._sv.get(addr)
        si = self._si.get(addr)
        if sv is not None and si is not None and self.set_vi_values_callback:
            self.set_vi_values_callback(addr, sv.value(), si.value())
        elif self.set_vi_callback:
            self.set_vi_callback(addr)
    
    def refresh_all(self):
        """刷新所有数据"""
        if not self.module_manager:
            return
        
        modules = self.module_manager.get_all_modules()
        for row, module in enumerate(modules):
            if row < self.rowCount():
                self._update_row(row, module)
    
    def _format_fault(self, module):
        """故障列：优先告警位，其次 E 码/状态故障"""
        descs = get_alarm_descriptions(module.alarm1, module.alarm2)
        codes = guess_fault_codes(module.alarm1, module.alarm2, module.status)
        if codes:
            e = fault_code_text(codes[0])
            if len(codes) > 1:
                e = f"{FAULT_CODES[codes[0]][0]}等{len(codes)}项"
            if descs:
                return f"{e}/{descs[0]}"
            return e
        if descs:
            head = descs[0]
            if len(descs) > 1:
                return f"{head}等{len(descs)}项"
            return head
        if module.alarm1 or module.alarm2:
            return f"A1=0x{module.alarm1:X} A2=0x{module.alarm2:X}"
        return "正常"

    def _fault_tooltip(self, module):
        """悬停：状态 + 告警位 + E 码说明"""
        lines = [
            f"状态: {module.get_status_text()} ({module.status})",
            f"告警1=0x{module.alarm1:08X}  告警2=0x{module.alarm2:08X}",
        ]
        descs = get_alarm_descriptions(module.alarm1, module.alarm2)
        lines.append("告警位: " + ("；".join(descs) if descs else "无"))
        codes = guess_fault_codes(module.alarm1, module.alarm2, module.status)
        if codes:
            lines.append("故障码:")
            for c in codes:
                lines.append("  " + fault_code_text(c))
        lines.append("（E 码为面板/手册代码，与告警位互为参考）")
        return "\n".join(lines)

    def _update_row(self, row, module):
        """更新一行数据"""
        # 更新复选框（不触发信号）
        checkbox_widget = self.cellWidget(row, 0)
        if checkbox_widget:
            checkbox = checkbox_widget.findChild(QCheckBox)
            if checkbox and checkbox.isChecked() != module.selected:
                checkbox.blockSignals(True)
                checkbox.setChecked(module.selected)
                checkbox.blockSignals(False)
        
        # 更新在线状态（与 _set_row 一致：绿点/灰点、放大、居中）
        ol = self.item(row, 2)
        if ol is not None:
            ol.setTextAlignment(Qt.AlignCenter)
            ol.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
            if module.online:
                ol.setText("● 在线")
                ol.setForeground(QBrush(QColor("#047857")))
            else:
                ol.setText("○ 离线")
                ol.setForeground(QBrush(QColor("#9AA2AA")))
        
        # 更新电源状态
        power_text = "开机" if module.power_on else "关机"
        if self.item(row, 3) is not None:
            self.item(row, 3).setText(power_text)
            if module.power_on:
                self.item(row, 3).setForeground(QBrush(QColor(COLOR_GREEN)))
            else:
                self.item(row, 3).setForeground(QBrush(QColor(COLOR_TEXT_DIM)))
        
        # 更新电压
        self.item(row, 4).setText(f"{module.voltage:.2f}" if module.online else "---")
        
        # 更新电流
        self.item(row, 5).setText(f"{module.current:.2f}" if module.online else "---")
        
        # 更新设置电压/电流：回填行内输入框（用户改过 / 编辑中都不覆盖）
        sv_w = self._sv.get(module.addr)
        if (sv_w is not None and module.online and not sv_w.hasFocus()
                and not getattr(sv_w, "_user_edited", False)):
            sv_w.blockSignals(True)
            sv_w.setValue(module.set_voltage)
            sv_w.blockSignals(False)
        si_w = self._si.get(module.addr)
        if (si_w is not None and module.online and not si_w.hasFocus()
                and not getattr(si_w, "_user_edited", False)):
            si_w.blockSignals(True)
            si_w.setValue(module.set_current)
            si_w.blockSignals(False)
        # 隐藏的 item 保持同步（背景着色仍依赖 item）
        if self.item(row, 6) is not None:
            self.item(row, 6).setText(f"{module.set_voltage:.2f}" if module.online else "---")
        if self.item(row, 7) is not None:
            self.item(row, 7).setText(f"{module.set_current:.2f}" if module.online else "---")
        
        # 更新模式
        self.item(row, 8).setText(module.get_mode_text() if module.online else "---")
        
        # 更新故障
        alarm_count = module.get_alarm_count()
        if not module.online:
            self.item(row, 9).setText("---")
            self.item(row, 9).setForeground(QBrush(QColor(COLOR_TEXT)))
        elif alarm_count > 0 or module.status == 9:
            self.item(row, 9).setText(self._format_fault(module))
            self.item(row, 9).setForeground(QBrush(QColor(COLOR_RED)))
        else:
            self.item(row, 9).setText("正常")
            self.item(row, 9).setForeground(QBrush(QColor(COLOR_TEXT)))
        if module.online and (module.alarm1 or module.alarm2):
            self.item(row, 9).setToolTip(
                f"ALARM1=0x{module.alarm1:08X} ALARM2=0x{module.alarm2:08X}\n"
                + "\n".join(get_alarm_descriptions(module.alarm1, module.alarm2)))
        
        # 更新行背景色
        for col in range(self.columnCount()):
            item = self.item(row, col)
            if item:
                if not module.online:
                    item.setBackground(QBrush(QColor("#F2F4F7")))
                else:
                    # 恢复交替行颜色
                    if row % 2 == 0:
                        item.setBackground(QBrush(QColor(COLOR_BG_MID)))
                    else:
                        item.setBackground(QBrush(QColor("#F7F9FB")))


class MainWindow(QMainWindow):
    """主窗口"""
    
    # 信号定义
    signal_can_received = pyqtSignal(object)  # CAN消息接收信号
    signal_connected = pyqtSignal()
    signal_disconnected = pyqtSignal()
    signal_log = pyqtSignal(str)  # 日志信号
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("安世博源模块监控上位机")
        self.resize(1400, 800)
        
        # 初始化组件
        self.can_client = UT6502Client()
        self.module_manager = ModuleManager(min_addr=0x01, max_addr=0x3F)
        
        # 轮询相关
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._on_poll_timer)
        self.poll_interval = 1000  # ms
        self.poll_index = 0
        self.auto_poll = False

        # 扫描相关（逐地址点对点；广播无应答；协议称点对点设置会应答）
        self._scanning = False
        self._scan_addrs = []
        self._scan_index = 0
        self._scan_phase = 0  # 0=被动监听 1=读group0 2=读group1 3=set0 4=set1 5=收尾
        self._group_addr = 0  # 对照上位机：先组地址 0，无应答再 1
        self._scan_timer = QTimer()
        self._scan_timer.timeout.connect(self._on_scan_tick)
        self._scan_settle_timer = QTimer()
        self._scan_settle_timer.setSingleShot(True)
        self._scan_settle_timer.timeout.connect(self._on_scan_settled)
        # 通信心跳：防止模块超时报面板 E15（默认超时约 10s，这里 3s 发一帧）
        self._ka_timer = QTimer()
        self._ka_timer.timeout.connect(self._on_keepalive)
        self._ka_interval = 3000
        self._ka_index = 0  # 心跳逐台轮转索引
        # 开机喂狗：对已开机模块周期重发设定+开机
        self._powered_addrs = set()
        self._wd_timer = QTimer()
        self._wd_timer.timeout.connect(self._on_watchdog)
        # 模块掉线检测：独立常驻 timer（连接期间运行），不依赖「自动轮询」开关
        self._offline_timer = QTimer()
        self._offline_timer.timeout.connect(self._check_offline_modules)
        self._offline_timeout = 5.0  # 秒，掉线判定的最小超时
        
        # 日志显示控制
        self.show_tx = True
        self.show_rx = True
        self.auto_scroll = True
        
        # 当前选中模块
        self.current_module_addr = 0x01
        
        # 设置回调
        self.can_client.add_message_callback(self._on_can_message)
        self.can_client.add_connect_callback(self._on_connected)
        self.can_client.add_disconnect_callback(self._on_disconnected)
        
        # 连接信号
        self.signal_can_received.connect(self._handle_can_message)
        self.signal_connected.connect(self._handle_connected)
        self.signal_disconnected.connect(self._handle_disconnected)
        self.signal_log.connect(self._append_log)
        
        # 构建UI
        self._build_ui()
        
        # 应用样式
        self.setStyleSheet(expand_qss(DarkStyle.get_style()))
    
    def _build_ui(self):
        """构建UI界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # 1. 连接配置区
        main_layout.addWidget(self._build_connect_group())
        
        # 2. 批量操作区
        main_layout.addWidget(self._build_batch_group())
        
        # 3. 主分割区（左侧表格 + 右侧面板）
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(self._build_monitor_area())
        main_splitter.addWidget(self._build_right_panel())
        main_splitter.setSizes([1000, 350])
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 1)
        main_layout.addWidget(main_splitter, 1)
        
        # 4. CAN报文日志区
        main_layout.addWidget(self._build_log_group())
    
    def _build_connect_group(self):
        """构建连接配置区"""
        group = QGroupBox("连接配置")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(10)
        
        # IP地址
        layout.addWidget(QLabel("UT-6502 IP:"))
        self.ip_edit = QLineEdit("192.168.1.125")
        self.ip_edit.setFixedWidth(120)
        layout.addWidget(self.ip_edit)
        
        # 端口
        layout.addWidget(QLabel("端口:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5001)
        self.port_spin.setFixedWidth(80)
        layout.addWidget(self.port_spin)

        # 组地址（UAB 协议 Byte0 高 4 位，对照上位机先 0 后 1）
        layout.addWidget(QLabel("组地址:"))
        self.group_spin = QSpinBox()
        self.group_spin.setRange(0, 15)
        self.group_spin.setValue(0)
        self.group_spin.setFixedWidth(60)
        self.group_spin.setToolTip("UAB 协议数据域 Byte0 高 4 位。\n扫描自动尝试 0→1；也可手动指定后点扫描/下发。")
        self.group_spin.valueChanged.connect(self._on_group_changed)
        layout.addWidget(self.group_spin)

        # 连接按钮
        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_connect.setFixedWidth(70)
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self.btn_connect)
        
        # 断开按钮
        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setObjectName("btnDisconnect")
        self.btn_disconnect.setFixedWidth(70)
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self._on_disconnect_clicked)
        layout.addWidget(self.btn_disconnect)
        
        # 自动轮询
        self.chk_auto_poll = QCheckBox("自动轮询在线模块")
        self.chk_auto_poll.setChecked(True)
        layout.addWidget(self.chk_auto_poll)
        
        # 轮询间隔
        layout.addWidget(QLabel("间隔(ms):"))
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setRange(100, 10000)
        self.poll_interval_spin.setValue(1000)
        self.poll_interval_spin.setFixedWidth(80)
        self.poll_interval_spin.valueChanged.connect(self._on_poll_interval_changed)
        layout.addWidget(self.poll_interval_spin)
        
        layout.addStretch()
        
        return group
    
    def _build_batch_group(self):
        """构建批量操作区"""
        group = QGroupBox("批量操作")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(10)
        
        # 全部开机
        self.btn_all_on = QPushButton("全部开机")
        self.btn_all_on.setObjectName("btnPowerOn")
        self.btn_all_on.setFixedWidth(100)
        self.btn_all_on.clicked.connect(self._on_all_power_on)
        layout.addWidget(self.btn_all_on)
        
        # 全部关机
        self.btn_all_off = QPushButton("全部关机")
        self.btn_all_off.setObjectName("btnPowerOff")
        self.btn_all_off.setFixedWidth(100)
        self.btn_all_off.clicked.connect(self._on_all_power_off)
        layout.addWidget(self.btn_all_off)
        
        # 批量电压
        layout.addWidget(QLabel("批量电压(V):"))
        self.batch_voltage_spin = QSpinBox()
        self.batch_voltage_spin.setRange(0, 1000)
        self.batch_voltage_spin.setValue(50)
        self.batch_voltage_spin.setFixedWidth(80)
        layout.addWidget(self.batch_voltage_spin)
        
        # 批量电流
        layout.addWidget(QLabel("批量电流(A):"))
        self.batch_current_spin = QSpinBox()
        self.batch_current_spin.setRange(0, 100)
        self.batch_current_spin.setValue(30)
        self.batch_current_spin.setFixedWidth(80)
        layout.addWidget(self.batch_current_spin)
        
        # 批量设置按钮
        self.btn_batch_set = QPushButton("批量设置电压电流")
        self.btn_batch_set.setObjectName("btnSetVI")
        self.btn_batch_set.setFixedWidth(150)
        self.btn_batch_set.clicked.connect(self._on_batch_set_vi)
        layout.addWidget(self.btn_batch_set)
        
        # 一键初始化
        self.btn_init = QPushButton("一键初始化")
        self.btn_init.setStyleSheet(f"background-color: {COLOR_YELLOW}; color: #000; font-weight: bold;")
        self.btn_init.setFixedWidth(120)
        self.btn_init.clicked.connect(self._on_one_key_init)
        layout.addWidget(self.btn_init)
        
        # 扫描在线模块
        self.btn_scan = QPushButton("扫描在线模块")
        self.btn_scan.setStyleSheet(f"background-color: {COLOR_BLUE}; color: #fff; font-weight: bold;")
        self.btn_scan.setFixedWidth(120)
        self.btn_scan.clicked.connect(self._on_scan_modules)
        layout.addWidget(self.btn_scan)

        self.btn_fault_codes = QPushButton("故障代码查询")
        self.btn_fault_codes.setStyleSheet(f"background-color: {COLOR_BLUE}; color: #fff;")
        self.btn_fault_codes.setFixedWidth(110)
        self.btn_fault_codes.clicked.connect(self._on_show_fault_codes)
        layout.addWidget(self.btn_fault_codes)
        
        layout.addStretch()
        
        return group
    
    def _build_monitor_area(self):
        """构建模块监控区域"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        # 标题栏（第一行：标题 + 统计 + 全选/清空/仅在线）
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("模块实时监控"))
        title_layout.addSpacing(12)
        
        # 地址范围
        self.lbl_addr_range = QLabel(f"地址 0x01~0x{0x3F:02X}")
        title_layout.addWidget(self.lbl_addr_range)
        
        title_layout.addSpacing(16)
        
        # 当前模块
        self.lbl_current_module = QLabel(f"当前模块: 0x{self.current_module_addr:02X} (1#)")
        title_layout.addWidget(self.lbl_current_module)
        
        title_layout.addSpacing(16)
        
        # 已选数量
        self.lbl_selected = QLabel("已选: 0")
        title_layout.addWidget(self.lbl_selected)

        title_layout.addSpacing(10)

        # 在线数量
        self.lbl_online = QLabel("在线: 0")
        self.lbl_online.setStyleSheet("color: #047857; font-weight: bold;")
        title_layout.addWidget(self.lbl_online)

        title_layout.addStretch(1)
        
        # 全选/清空/仅在线 按钮
        btn_select_all = QPushButton("全选")
        btn_select_all.setFixedWidth(60)
        btn_select_all.setStyleSheet(f"background-color: {COLOR_BLUE}; color: #fff;")
        btn_select_all.clicked.connect(self._on_select_all)
        title_layout.addWidget(btn_select_all)
        
        btn_clear_sel = QPushButton("清空")
        btn_clear_sel.setFixedWidth(60)
        btn_clear_sel.setStyleSheet(f"background-color: {COLOR_BLUE}; color: #fff;")
        btn_clear_sel.clicked.connect(self._on_clear_selection)
        title_layout.addWidget(btn_clear_sel)
        
        btn_online_only = QPushButton("仅在线")
        btn_online_only.setFixedWidth(70)
        btn_online_only.setStyleSheet(f"background-color: {COLOR_BLUE}; color: #fff;")
        btn_online_only.clicked.connect(self._on_select_online_only)
        title_layout.addWidget(btn_online_only)
        
        layout.addLayout(title_layout)
        
        # 操作栏（第二行：选中批量操作，独立一行避免被标题挤爆）
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        
        btn_sel_on = QPushButton("选中开机")
        btn_sel_on.setObjectName("btnPowerOn")
        btn_sel_on.setFixedWidth(80)
        btn_sel_on.clicked.connect(self._on_selected_power_on)
        action_layout.addWidget(btn_sel_on)
        
        btn_sel_off = QPushButton("选中关机")
        btn_sel_off.setObjectName("btnPowerOff")
        btn_sel_off.setFixedWidth(80)
        btn_sel_off.clicked.connect(self._on_selected_power_off)
        action_layout.addWidget(btn_sel_off)
        
        btn_sel_set = QPushButton("选中设置V/I")
        btn_sel_set.setObjectName("btnSetVI")
        btn_sel_set.setFixedWidth(100)
        btn_sel_set.clicked.connect(self._on_selected_set_vi)
        action_layout.addWidget(btn_sel_set)
        
        action_layout.addStretch(1)
        
        layout.addLayout(action_layout)
        
        # 表格
        self.module_table = ModuleTableWidget()
        self.module_table.set_module_manager(self.module_manager)
        self.module_table.power_on_callback = self._on_module_power_on
        self.module_table.power_off_callback = self._on_module_power_off
        self.module_table.set_vi_callback = self._on_module_set_vi
        self.module_table.set_vi_values_callback = self._on_module_set_vi_values
        self.module_table.selection_changed_callback = self._update_selected_count
        self.module_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self.module_table, 1)
        
        return widget
    
    def _build_right_panel(self):
        """构建右侧面板（内容置入滚动区，避免高度不足时按钮文字被压缩）"""
        self.right_tabs = QTabWidget()

        ctrl = self._build_module_control_tab()
        ctrl.setMinimumHeight(760)   # 按 QSS 分组框铬开销放量，防按钮被压扁裁字
        s1 = QScrollArea()
        s1.setWidgetResizable(True)
        s1.setWidget(ctrl)
        s1.setFrameShape(QFrame.NoFrame)
        self.right_tabs.addTab(s1, "模块控制")

        idm = self._build_id_manage_tab()
        idm.setMinimumHeight(620)   # 同模块控制页：内容放量防压缩裁字
        s2 = QScrollArea()
        s2.setWidgetResizable(True)
        s2.setWidget(idm)
        s2.setFrameShape(QFrame.NoFrame)
        self.right_tabs.addTab(s2, "ID管理")

        return self.right_tabs
    
    def _build_module_control_tab(self):
        """构建模块控制标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 运行模式
        mode_group = QGroupBox("运行模式")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("1 - 充电模式", 1)
        self.mode_combo.addItem("2 - 离网放电模式", 2)
        self.mode_combo.addItem("3 - 并网模式", 3)
        self.mode_combo.addItem("4 - 恒压恒流恒功率模式", 4)
        mode_layout.addWidget(self.mode_combo)
        
        btn_set_mode = QPushButton("设置运行模式")
        btn_set_mode.setObjectName("btnSetVI")
        btn_set_mode.clicked.connect(self._on_set_mode)
        mode_layout.addWidget(btn_set_mode)
        layout.addWidget(mode_group)
        
        # 电压电流设置
        vi_group = QGroupBox("电压电流设置")
        vi_layout = QVBoxLayout(vi_group)
        
        v_layout = QHBoxLayout()
        v_layout.addWidget(QLabel("输出电压(V):"))
        self.set_voltage_spin = QSpinBox()
        self.set_voltage_spin.setRange(0, 1000)
        self.set_voltage_spin.setValue(50)
        self.set_voltage_spin.setSingleStep(1)
        v_layout.addWidget(self.set_voltage_spin)
        vi_layout.addLayout(v_layout)
        
        i_layout = QHBoxLayout()
        i_layout.addWidget(QLabel("输出电流(A):"))
        self.set_current_spin = QSpinBox()
        self.set_current_spin.setRange(0, 100)
        self.set_current_spin.setValue(30)
        self.set_current_spin.setSingleStep(1)
        i_layout.addWidget(self.set_current_spin)
        vi_layout.addLayout(i_layout)
        
        btn_set_vi = QPushButton("设置电压电流")
        btn_set_vi.setObjectName("btnSetVI")
        btn_set_vi.clicked.connect(self._on_set_voltage_current)
        vi_layout.addWidget(btn_set_vi)
        layout.addWidget(vi_group)
        
        # 功率设置
        pwr_group = QGroupBox("功率设置 (模式3/4)")
        pwr_layout = QVBoxLayout(pwr_group)
        
        p_layout = QHBoxLayout()
        p_layout.addWidget(QLabel("有功功率(W):"))
        self.set_power_spin = QSpinBox()
        self.set_power_spin.setRange(-100000, 100000)
        self.set_power_spin.setValue(1000)
        p_layout.addWidget(self.set_power_spin)
        pwr_layout.addLayout(p_layout)
        
        q_layout = QHBoxLayout()
        q_layout.addWidget(QLabel("无功功率(Var):"))
        self.set_reactive_spin = QSpinBox()
        self.set_reactive_spin.setRange(-100000, 100000)
        self.set_reactive_spin.setValue(0)
        q_layout.addWidget(self.set_reactive_spin)
        pwr_layout.addLayout(q_layout)
        
        btn_set_pwr = QPushButton("设置功率")
        btn_set_pwr.setObjectName("btnSetVI")
        btn_set_pwr.clicked.connect(self._on_set_power)
        pwr_layout.addWidget(btn_set_pwr)
        layout.addWidget(pwr_group)
        
        # 读取信息
        read_group = QGroupBox("读取信息")
        read_layout = QVBoxLayout(read_group)
        
        btn_read_status = QPushButton("读取状态")
        btn_read_status.clicked.connect(self._on_read_status)
        read_layout.addWidget(btn_read_status)
        
        btn_read_vi = QPushButton("读取电压电流")
        btn_read_vi.clicked.connect(self._on_read_voltage_current)
        read_layout.addWidget(btn_read_vi)
        
        btn_read_alarm = QPushButton("读取告警信息")
        btn_read_alarm.clicked.connect(self._on_read_alarm)
        read_layout.addWidget(btn_read_alarm)
        
        btn_read_all = QPushButton("读取全部信息")
        btn_read_all.clicked.connect(self._on_read_all)
        read_layout.addWidget(btn_read_all)

        btn_clear_fault = QPushButton("清除故障")
        btn_clear_fault.setObjectName("btnPowerOff")
        btn_clear_fault.setToolTip(
            "E15=通信超时：恢复通信后通常自动清除。\n"
            "本按钮：①恢复心跳/轮询 ②回读状态告警 ③可写长通信超时 ④可断电重启")
        btn_clear_fault.clicked.connect(self._on_clear_fault)
        read_layout.addWidget(btn_clear_fault)

        btn_fault_detail = QPushButton("故障码详情")
        btn_fault_detail.clicked.connect(self._on_show_fault_codes)
        read_layout.addWidget(btn_fault_detail)

        layout.addWidget(read_group)

        layout.addStretch()
        # 防布局压缩裁切按钮文字：全部按钮定高（滚动区存在时也不许压字）
        for b in widget.findChildren(QPushButton):
            b.setMinimumHeight(30)
        return widget
    
    def _build_id_manage_tab(self):
        """构建ID管理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 说明
        desc = QLabel("模块 ID 通过生命帧触发。\n(如 0x18C1FFC1 表示模块当前 ID。)")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        layout.addWidget(desc)
        
        # 读取按钮
        btn_read_id = QPushButton("读取模块ID")
        btn_read_id.setObjectName("btnSetVI")
        btn_read_id.clicked.connect(self._on_read_module_id)
        layout.addWidget(btn_read_id)
        
        # ID显示
        self.id_display = QTextEdit()
        self.id_display.setReadOnly(True)
        self.id_display.setMinimumHeight(150)
        layout.addWidget(self.id_display, 1)
        
        # 修改模块ID
        modify_group = QGroupBox("修改模块 ID (0xD9)")
        modify_layout = QVBoxLayout(modify_group)
        
        self.lbl_current_id = QLabel("当前模块 ID: --")
        modify_layout.addWidget(self.lbl_current_id)
        
        new_id_layout = QHBoxLayout()
        new_id_layout.addWidget(QLabel("新模块 ID:"))
        self.new_id_spin = QSpinBox()
        self.new_id_spin.setRange(1, 127)
        self.new_id_spin.setValue(1)
        new_id_layout.addWidget(self.new_id_spin)
        modify_layout.addLayout(new_id_layout)
        
        btn_change_id = QPushButton("修改模块ID（待协议确认）")
        btn_change_id.setObjectName("btnSetVI")
        btn_change_id.setEnabled(False)   # 真实 ID 修改命令待协议文档确认，禁用防止误操作
        btn_change_id.setToolTip("模块 ID 修改命令尚未在协议文档中确认，暂不可用")
        btn_change_id.clicked.connect(self._on_change_module_id)
        modify_layout.addWidget(btn_change_id)
        
        # 注意
        note = QLabel("注意: 修改后模块将以新ID通信;\n一次只修改一台模块。\n（ID 修改命令待协议文档确认，暂不可用）")
        note.setStyleSheet(f"color: {COLOR_YELLOW};")
        note.setWordWrap(True)
        modify_layout.addWidget(note)
        
        layout.addWidget(modify_group)

        layout.addStretch()
        # 防布局压缩裁切按钮文字：全部按钮定高（滚动区存在时也不许压字）
        for b in widget.findChildren(QPushButton):
            b.setMinimumHeight(30)
        return widget
    
    def _build_log_group(self):
        """构建CAN报文日志区"""
        group = QGroupBox("CAN报文日志")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 15, 10, 10)
        layout.setSpacing(6)
        
        # 控制栏
        ctrl_layout = QHBoxLayout()
        
        self.chk_show_tx = QCheckBox("显示发送")
        self.chk_show_tx.setChecked(True)
        self.chk_show_tx.stateChanged.connect(lambda s: setattr(self, 'show_tx', s == Qt.Checked))
        ctrl_layout.addWidget(self.chk_show_tx)
        
        self.chk_show_rx = QCheckBox("显示接收")
        self.chk_show_rx.setChecked(True)
        self.chk_show_rx.stateChanged.connect(lambda s: setattr(self, 'show_rx', s == Qt.Checked))
        ctrl_layout.addWidget(self.chk_show_rx)
        
        self.chk_auto_scroll = QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        self.chk_auto_scroll.stateChanged.connect(lambda s: setattr(self, 'auto_scroll', s == Qt.Checked))
        ctrl_layout.addWidget(self.chk_auto_scroll)
        
        ctrl_layout.addStretch()
        
        btn_clear_log = QPushButton("清空日志")
        btn_clear_log.setFixedWidth(80)
        btn_clear_log.clicked.connect(self._on_clear_log)
        ctrl_layout.addWidget(btn_clear_log)
        
        layout.addLayout(ctrl_layout)
        
        # 日志文本
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        layout.addWidget(self.log_text)
        
        return group
    
    # ==================== 事件处理 ====================
    
    def _reset_vi_user_edited(self):
        """连接后恢复自动回填（清除用户编辑标记）"""
        for d in (getattr(self.module_table, "_sv", {}),
                  getattr(self.module_table, "_si", {})):
            for w in d.values():
                w._user_edited = False

    def _on_connect_clicked(self):
        """连接按钮点击"""
        self._reset_vi_user_edited()
        ip = self.ip_edit.text().strip()
        port = self.port_spin.value()
        
        if not ip:
            QMessageBox.warning(self, "提示", "请输入IP地址")
            return
        
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("连接中...")
        
        # 在后台线程连接
        import threading
        threading.Thread(target=self._do_connect, args=(ip, port), daemon=True).start()
    
    def _do_connect(self, ip, port):
        """执行连接"""
        result = self.can_client.connect(ip, port)
        if result:
            # 连接成功由 UT6502Client 回调上报，避免双发
            pass
        else:
            self.signal_log.emit(f"[错误] 连接失败: {ip}:{port}")
            self.signal_disconnected.emit()
    
    def _on_disconnect_clicked(self):
        """断开按钮点击"""
        # 断开前先给所有在线模块写长通信超时（120s），避免断开后模块立刻报面板 E15
        self._graceful_disable_e15()
        try:
            self.can_client.disconnect()
        except Exception as e:
            self.signal_log.emit(f"[错误] 断开连接异常: {e}")
            # 异常路径也要保证界面状态复位
            self.signal_disconnected.emit()

    def _graceful_disable_e15(self):
        """断开前把在线模块的通信超时写长（120s），抑制「断开即报 E15」。

        E15 是模块固件的通信看门狗：默认约 10s 收不到上位机报文就报故障。
        断开前逐台写入 120s 超时，让模块在断开后一段时间内不误报，
        给现场重新连接/切换留出从容窗口。
        """
        try:
            online = [m for m in self.module_manager.get_all_modules() if m.online]
        except Exception:
            return
        if not online:
            return
        # 逐台写通信超时 120s（CMD_EXTENDED 子命令 EXT_COMM_TIMEOUT）
        done = 0
        for m in online:
            try:
                if self._send_set_command(m.addr, CMD_EXTENDED, 120, cmd_sup=EXT_COMM_TIMEOUT):
                    done += 1
            except Exception:
                continue
        if done:
            self.signal_log.emit(
                f"[系统] 断开前已将 {done} 台在线模块的通信超时写为 120s，"
                f"避免断开后立刻报面板 E15")
        else:
            self.signal_log.emit("[系统] 提示：模块通信超时默认约 10s，断开后可能报 E15（属固件正常保护，无害）")
    
    def _on_connected(self):
        """连接成功回调（后台线程）"""
        self.signal_connected.emit()
    
    def _on_disconnected(self):
        """断开连接回调（后台线程）"""
        self.signal_disconnected.emit()
    
    def _handle_connected(self):
        """处理连接成功（UI线程）"""
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("已连接")
        self.btn_connect.setObjectName("btnConnected")
        self.btn_disconnect.setEnabled(True)
        self.ip_edit.setEnabled(False)
        self.port_spin.setEnabled(False)

        self.signal_log.emit(
            f"[系统] 已连接到 {self.ip_edit.text()}:{self.port_spin.value()}")
        try:
            from app.registry import APP_VERSION
            self.signal_log.emit(f"[系统] 运行版本 {APP_VERSION}（请确认非旧包）")
        except Exception:
            pass
        # 立即开心跳，防 E15 通信超时
        if not self._ka_timer.isActive():
            self._ka_timer.start(self._ka_interval)
            self.signal_log.emit("[系统] 通信心跳已启动（3s，防面板 E15）")
        # 掉线检测常驻（不依赖「自动轮询」开关）
        if not self._offline_timer.isActive():
            self._offline_timer.start(1000)

        # 启动自动轮询
        if self.chk_auto_poll.isChecked() and not self.auto_poll:
            self._start_polling()

    def _handle_disconnected(self):
        """处理断开连接（UI线程）"""
        already = not self.btn_disconnect.isEnabled() and self.btn_connect.isEnabled()
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_disconnect.setEnabled(False)
        self.ip_edit.setEnabled(True)
        self.port_spin.setEnabled(True)

        self._cancel_scan()
        # 停止轮询
        self._stop_polling()
        try:
            self._ka_timer.stop()
            self._wd_timer.stop()
            self._offline_timer.stop()
            self._powered_addrs.clear()
        except Exception:
            pass

        # 标记所有模块离线
        self.module_manager.mark_all_offline()
        self.module_table.refresh_all()

        if not already:
            self.signal_log.emit("[系统] 连接已断开")
    
    def _set_group(self, value, log=True):
        """更新组地址（同步界面旋钮，避免重复日志）"""
        self._group_addr = int(value)
        if hasattr(self, "group_spin") and self.group_spin.value() != int(value):
            self.group_spin.blockSignals(True)
            self.group_spin.setValue(int(value))
            self.group_spin.blockSignals(False)
        if log:
            self.signal_log.emit(f"[系统] 组地址设为 {value}")

    def _on_group_changed(self, value):
        """手动指定组地址"""
        self._group_addr = int(value)
        self.signal_log.emit(f"[系统] 组地址设为 {value}")

    def _on_poll_interval_changed(self, value):
        """轮询间隔改变"""
        self.poll_interval = value
        if self.poll_timer.isActive():
            self.poll_timer.setInterval(self.poll_interval)
    
    def _start_polling(self):
        """开始轮询"""
        if self.auto_poll and self.poll_timer.isActive():
            return
        self.auto_poll = True
        self.poll_timer.start(self.poll_interval)
        self.signal_log.emit(f"[系统] 开始自动轮询，间隔 {self.poll_interval}ms")
        # 心跳常开，避免模块通信超时 E15
        if not self._ka_timer.isActive():
            self._ka_timer.start(self._ka_interval)

    def _on_keepalive(self):
        """通信心跳：连接期间周期发读命令，防止模块 E15 通信超时。

        逐台轮转读在线模块——掉线检测依赖 last_seen，轮转保证关闭
        自动轮询时每台在线模块仍被周期探测，掉线可感知、不误判。
        """
        if not self.can_client.is_connected() or self._scanning:
            return
        online = [m for m in self.module_manager.get_all_modules() if m.online]
        if online:
            # 逐台轮转对在线模块读状态，本身就是心跳
            addr = online[self._ka_index % len(online)].addr
            self._ka_index += 1
            self._send_read_command(addr, CMD_MODULE_STATUS)
        else:
            # 无在线模块时对组播地址发读，仍占用总线告知监控在线
            self._ka_index = 0
            self._send_read_command(0x01, CMD_MODULE_STATUS)

    def _check_offline_modules(self):
        """模块掉线检测：超时无应答 → 标记离线 + 日志提示 + 界面刷新。

        独立 timer 驱动，不依赖「自动轮询」开关——轮询关闭时由心跳
        逐台轮转探测兜底。超时随在线数量自适应：至少覆盖一轮探测
        周期，避免轮转结构下「还没轮到」被误判。扫描期间让位于扫描
        的探测/恢复路径。
        """
        if not self.can_client.is_connected() or self._scanning:
            return
        online = [m for m in self.module_manager.get_all_modules() if m.online]
        if not online:
            # 通讯状态：全部模块离线 = 通讯中断，右上角指示灯回灰
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)
            return
        probe_ms = (self.poll_interval if self.auto_poll and self.poll_timer.isActive()
                    else self._ka_interval)
        timeout = max(self._offline_timeout, probe_ms * (len(online) + 1) / 1000.0)
        now = time.time()
        changed = False
        for m in online:
            if m.online and (now - m.last_seen) > timeout:
                self.module_manager.set_offline(m.addr)
                changed = True
                self.signal_log.emit(
                    f"[系统] 模块 0x{m.addr:02X} 超时无响应, 标记离线")
        if changed:
            try:
                self.module_table.refresh_all()
            except Exception as e:
                self.signal_log.emit(f"[错误] 刷新表格失败: {e}")
            self._update_online_count()
        # 本轮掉线掉到全军覆没：同样视为通讯中断
        if not any(m.online for m in self.module_manager.get_all_modules()):
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)

    def _stop_polling(self):
        """停止轮询"""
        was = self.auto_poll or self.poll_timer.isActive()
        self.auto_poll = False
        self.poll_timer.stop()
        if was:
            self.signal_log.emit("[系统] 停止自动轮询")
    
    def _on_poll_timer(self):
        """轮询定时器 — 只读在线模块的状态，不对全地址空轮询"""
        if not self.can_client.is_connected():
            return

        online = [m for m in self.module_manager.get_all_modules() if m.online]
        if not online:
            return

        # 每次轮询一个在线模块的多个参数
        module = online[self.poll_index % len(online)]
        self.poll_index += 1

        # 发送读取状态命令
        self._send_read_command(module.addr, CMD_MODULE_STATUS)

        # 与 v2.5.14 同构：状态/电压/电流/告警，另加告警2与母线
        self._send_read_command(module.addr, CMD_VOUT)
        self._send_read_command(module.addr, CMD_IOUT)
        self._send_read_command(module.addr, CMD_ALARM1)
        self._send_read_command(module.addr, CMD_ALARM2)
        self._send_read_command(module.addr, CMD_VBAT)
    
    def _send_read_command(self, module_addr, cmd_type, group_addr=None):
        """发送读取命令（组地址默认用 self._group_addr，对照机先 0 后 1）"""
        if not self.can_client.is_connected():
            return
        g = self._group_addr if group_addr is None else group_addr
        frame = build_read_command(module_addr, cmd_type, group_addr=g)
        self.can_client.send_frame(frame)

        if self.show_tx:
            self._log_tx_frame(frame, module_addr, cmd_type)

    def _send_set_command(self, module_addr, cmd_type, data, group_addr=None, cmd_sup=None):
        """发送设置命令"""
        if not self.can_client.is_connected():
            return False
        g = self._group_addr if group_addr is None else group_addr
        frame = build_set_command(module_addr, cmd_type, data, group_addr=g, cmd_sup=cmd_sup)
        result = self.can_client.send_frame(frame)

        if self.show_tx:
            self._log_tx_frame(frame, module_addr, cmd_type, data)

        return result
    
    def _on_can_message(self, frame_info):
        """CAN消息接收回调（后台线程）"""
        self.signal_can_received.emit(frame_info)
    
    def _handle_can_message(self, frame_info):
        """处理CAN消息（UI线程）"""
        if not frame_info:
            return

        can_id = frame_info['can_id']
        data = frame_info['data']

        protocol, monitor_addr, module_addr, serial_low = parse_can_id(can_id)
        parsed = parse_data_frame(data)

        # 从应答里学组地址，后续命令沿用
        try:
            g = parsed.get('group_addr')
            if g is not None and g != self._group_addr:
                self._set_group(g, log=False)
        except Exception:
            pass

        if self.show_rx or self._scanning:
            self._log_rx_frame(frame_info, module_addr, parsed)

        # 根据消息类型处理
        msg_type = parsed['msg_type']
        cmd_type = parsed['cmd_type']
        cmd_data = parsed['cmd_data']

        # 任何有效应答都视为在线；地址落在可视区才进表
        m = self.module_manager.get_module(module_addr)
        if m is not None:
            was_offline = not m.online
            m.online = True
            m.last_seen = time.time()  # 刷新应答时间，供掉线检测判定
            if was_offline and not self._scanning:
                self.signal_log.emit(
                    f"[系统] 收到 0x{module_addr:02X} 应答（迟到），已标在线")
        else:
            self.signal_log.emit(
                f"[提示] 应答地址 0x{module_addr:02X} 不在 0x01~0x3F 可视区 "
                f"(CAN ID=0x{can_id:08X})，已忽略")

        try:
            if msg_type == MSG_READ_RESP:
                # 读应答
                self._handle_read_response(module_addr, cmd_type, cmd_data)
            elif msg_type == MSG_SET_RESP:
                # 设置应答
                self._handle_set_response(module_addr, cmd_type, cmd_data)
            elif msg_type == MSG_SN_RESP:
                # 序列号应答
                pass
        except Exception as e:
            self.signal_log.emit(f"[错误] 处理应答失败 0x{module_addr:02X}: {e}")

        # 刷新表格 + 在线数（UI 异常不得打断收包标在线）
        try:
            self.module_table.refresh_all()
        except Exception as e:
            self.signal_log.emit(f"[错误] 刷新表格失败: {e}")
        self._update_online_count()

    def _update_online_count(self):
        """刷新在线数（不再自动滚动定位，避免抢占用户手动滚动）"""
        try:
            online = self.module_manager.get_online_count()
        except Exception:
            online = 0
        if hasattr(self, "lbl_online"):
            self.lbl_online.setText(f"在线: {online}")
    
    def _handle_read_response(self, module_addr, cmd_type, cmd_data):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到读应答 = 通讯真正建立
        """处理读取应答"""
        # 任何有效应答都视为模块在线
        m = self.module_manager.get_module(module_addr)
        if m is not None:
            m.online = True
        if cmd_type == CMD_MODULE_STATUS:
            self.module_manager.update_module_status(module_addr, cmd_data & 0xFF)
        elif cmd_type == CMD_VOUT:
            self.module_manager.update_module_voltage(module_addr, cmd_data)
        elif cmd_type == CMD_IOUT:
            self.module_manager.update_module_current(module_addr, cmd_data)
        elif cmd_type == CMD_VOUT_SET:
            self.module_manager.update_module_set_voltage(module_addr, cmd_data)
        elif cmd_type == CMD_IOUT_LIMIT:
            self.module_manager.update_module_set_current(module_addr, cmd_data)
        elif cmd_type == CMD_OUTPUT_MODE:
            self.module_manager.update_module_mode(module_addr, cmd_data)
        elif cmd_type == CMD_ALARM1:
            self.module_manager.update_module_alarm(module_addr, alarm1=cmd_data)
            if cmd_data:
                self.signal_log.emit(
                    f"[告警] 0x{module_addr:02X} ALARM1=0x{cmd_data:08X}")
        elif cmd_type == CMD_ALARM2:
            self.module_manager.update_module_alarm(module_addr, alarm2=cmd_data)
            if cmd_data:
                self.signal_log.emit(
                    f"[告警] 0x{module_addr:02X} ALARM2=0x{cmd_data:08X}")
        elif cmd_type == CMD_VBAT:
            # 电池电压 Vbat（0x3D）；单位 mV，有符号，脏值在 model 层过滤
            raw = cmd_data & 0xFFFFFFFF
            self.module_manager.update_module_bus_voltage(module_addr, raw)
        elif cmd_type == CMD_P_ACTIVE:
            # 有符号32位
            if cmd_data & 0x80000000:
                cmd_data = cmd_data - 0x100000000
            self.module_manager.update_module_power(module_addr, active=cmd_data)

    def _handle_set_response(self, module_addr, cmd_type, cmd_data):
        """处理设置应答"""
        m = self.module_manager.get_module(module_addr)
        if m is not None:
            m.online = True
        # 设置成功，更新对应的数据
        if cmd_type == CMD_VOUT_SET:
            self.module_manager.update_module_set_voltage(module_addr, cmd_data)
        elif cmd_type == CMD_IOUT_LIMIT:
            self.module_manager.update_module_set_current(module_addr, cmd_data)
        elif cmd_type == CMD_OUTPUT_MODE:
            self.module_manager.update_module_mode(module_addr, cmd_data)
        elif cmd_type == CMD_POWER_CTRL:
            # 开关机应答后立刻回读状态+告警+电池电压，便于抓 E 类故障
            self._send_read_command(module_addr, CMD_MODULE_STATUS)
            self._send_read_command(module_addr, CMD_ALARM1)
            self._send_read_command(module_addr, CMD_ALARM2)
            self._send_read_command(module_addr, CMD_VBAT)
    
    # ==================== 日志相关 ====================
    
    def _log_tx_frame(self, frame, module_addr, cmd_type, data=None):
        """记录发送帧日志"""
        hex_str = frame.hex(' ').upper()
        addr_str = f"0x{module_addr:02X}" if module_addr != 0 else "广播"
        cmd_name = self._get_cmd_name(cmd_type)
        
        if data is not None:
            log = f"[TX] {addr_str} {cmd_name} 数据: {data} | {hex_str}"
        else:
            log = f"[TX] {addr_str} {cmd_name} | {hex_str}"
        
        self.signal_log.emit(log)
    
    def _log_rx_frame(self, frame_info, module_addr, parsed):
        """记录接收帧日志"""
        hex_str = frame_info['data'].hex(' ').upper() if frame_info['data'] else ""
        addr_str = f"0x{module_addr:02X}"
        cmd_name = self._get_cmd_name(parsed['cmd_type'])
        msg_type_name = self._get_msg_type_name(parsed['msg_type'])
        can_id = frame_info.get('can_id', 0)

        log = (f"[RX] id=0x{can_id:08X} {addr_str} {msg_type_name} {cmd_name} "
               f"数据: {parsed['cmd_data']} | {hex_str}")
        self.signal_log.emit(log)
    
    def _get_cmd_name(self, cmd_type):
        """获取命令名称"""
        cmd_names = {
            0x00: "输出电压",
            0x01: "输出电流",
            0x02: "电压设定",
            0x03: "电流设定",
            0x04: "开关机",
            0x05: "序列号",
            0x08: "模块状态",
            0x09: "AC电压设定",
            0x0A: "AC频率设定",
            0x0B: "有功功率设定",
            0x0C: "无功功率设定",
            0x0D: "有功功率",
            0x0E: "无功功率",
            0x0F: "视在功率",
            0x10: "AC频率",
            0x11: "告警1",
            0x12: "告警2",
            0x30: "进风口温度",
            0x3D: "电池电压",
            0x5F: "运行模式",
            0x59: "组地址",
        }
        return cmd_names.get(cmd_type, f"CMD_{cmd_type:02X}")
    
    def _get_msg_type_name(self, msg_type):
        """获取消息类型名称"""
        names = {
            0: "设置",
            1: "设置应答",
            2: "读取",
            3: "读取应答",
            4: "序列号应答",
        }
        return names.get(msg_type, f"MSG_{msg_type:X}")
    
    def _append_log(self, text):
        """追加日志"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # 根据类型设置颜色
        if "[TX]" in text:
            colored = f'<span style="color:#047857;">[{timestamp}]</span> {text}'
        elif "[RX]" in text:
            colored = f'<span style="color:#4F46E5;">[{timestamp}]</span> {text}'
        elif "[错误]" in text or "[ERROR]" in text:
            colored = f'<span style="color:#B01030;">[{timestamp}]</span> {text}'
        elif "[系统]" in text:
            colored = f'<span style="color:#F59E0B;">[{timestamp}]</span> {text}'
        else:
            colored = f'<span style="color:#6B7280;">[{timestamp}]</span> {text}'
        
        self.log_text.append(colored)
        
        if self.auto_scroll:
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )
    
    def _on_clear_log(self):
        """清空日志"""
        self.log_text.clear()
    
    # ==================== 批量操作 ====================
    
    def _confirm_power_on(self, addrs, title="确认开机"):
        """开机二次确认，弹窗列出目标模块"""
        if not addrs:
            QMessageBox.information(self, "提示", "请先选择模块")
            return False
        if len(addrs) > 30:
            addr_txt = ", ".join(f"0x{a:02X}" for a in addrs[:30]) + f" … 共 {len(addrs)} 台"
        else:
            addr_txt = ", ".join(f"0x{a:02X}" for a in addrs)
        return QMessageBox.question(
            self, title,
            f"将对以下模块执行开机：\n\n{addr_txt}\n\n确认继续?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def _on_all_power_on(self):
        """全部开机"""
        if not self._check_connected():
            return
        addrs = [m.addr for m in self.module_manager.get_all_modules() if m.online] or \
                [m.addr for m in self.module_manager.get_all_modules()]
        if not self._confirm_power_on(addrs, "确认全部开机"):
            return

        # 广播开机命令
        frame = build_power_command(0, power_on=True)
        self.can_client.send_frame(frame)

        if self.show_tx:
            hex_str = frame.hex(' ').upper()
            self.signal_log.emit(f"[TX] 广播 开机 | {hex_str}")
    
    def _on_all_power_off(self):
        """全部关机"""
        if not self._check_connected():
            return
        
        reply = QMessageBox.question(self, "确认", "确定要对所有模块执行关机操作吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        
        # 广播关机命令
        frame = build_power_command(0, power_on=False)
        self.can_client.send_frame(frame)
        
        if self.show_tx:
            hex_str = frame.hex(' ').upper()
            self.signal_log.emit(f"[TX] 广播 关机 | {hex_str}")
    
    def _on_batch_set_vi(self):
        """批量设置电压电流"""
        if not self._check_connected():
            return
        
        voltage = self.batch_voltage_spin.value()
        current = self.batch_current_spin.value()
        
        reply = QMessageBox.question(self, "确认", 
                                     f"确定要对所有模块设置电压 {voltage}V, 电流 {current}A 吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        
        # 广播设置电压
        v_frame = build_voltage_set_command(0, voltage * 1000)
        self.can_client.send_frame(v_frame)
        if self.show_tx:
            self.signal_log.emit(f"[TX] 广播 设置电压: {voltage}V | {v_frame.hex(' ').upper()}")
        
        # 广播设置电流
        i_frame = build_current_set_command(0, current * 1000)
        self.can_client.send_frame(i_frame)
        if self.show_tx:
            self.signal_log.emit(f"[TX] 广播 设置电流: {current}A | {i_frame.hex(' ').upper()}")
    
    def _on_one_key_init(self):
        """一键初始化"""
        if not self._check_connected():
            return
        
        reply = QMessageBox.question(self, "确认", 
                                     "确定要执行一键初始化吗？\n将设置模式、电压、电流并开机。",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        
        voltage = self.batch_voltage_spin.value()
        current = self.batch_current_spin.value()
        
        # 模式1：充电模式
        self._send_set_command(0, CMD_OUTPUT_MODE, 1)
        self._send_set_command(0, CMD_VOUT_SET, int(voltage * 1000))
        self._send_set_command(0, CMD_IOUT_LIMIT, int(current * 1000))
        self._send_set_command(0, CMD_POWER_CTRL, 0)  # 开机
        
        self.signal_log.emit("[系统] 一键初始化命令已发送")
    
    def _on_scan_modules(self):
        """发现在线模块；扫描中再点此按钮=中断扫描"""
        if not self._check_connected():
            return
        if self._scanning:
            self.signal_log.emit("[系统] 已中断扫描")
            self._cancel_scan()
            self._finish_scan()
            return

        self.module_manager.mark_all_offline()
        self.module_table.refresh_all()
        self._update_online_count()

        self._scanning = True
        self._scan_addrs = list(range(0x01, 0x40))
        self._scan_index = 0
        self._scan_phase = 0  # 0=listen, 1=read, 2=set, 3=final listen
        self._scan_pause_poll = self.poll_timer.isActive()
        self.poll_timer.stop()
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("停止扫描")

        self.signal_log.emit(
            "[系统] 开始发现模块：对照 UAB 上位机——先组地址 0，无应答再组地址 1，逐地址等待应答...")
        self._scan_settle_timer.start(5000)

    def _on_scan_tick(self):
        """逐地址发一帧，帧间隔 180ms，给模块留应答时间"""
        if not self._scanning or not self.can_client.is_connected():
            self._cancel_scan()
            return

        if self._scan_index >= len(self._scan_addrs):
            self._scan_timer.stop()
            self._scan_settle_timer.start(1500)  # 本阶段收尾
            return

        addr = self._scan_addrs[self._scan_index]
        self._scan_index += 1
        if self._scan_index % 8 == 0 or self._scan_index == 1:
            self.btn_scan.setText("停止扫描")

        if self._scan_phase == 1:
            self._send_read_command(addr, CMD_MODULE_STATUS, group_addr=0)
        elif self._scan_phase == 2:
            self._send_read_command(addr, CMD_MODULE_STATUS, group_addr=1)
        elif self._scan_phase == 3:
            self._send_set_command(addr, CMD_OUTPUT_MODE, 1, group_addr=0)
        elif self._scan_phase == 4:
            self._send_set_command(addr, CMD_OUTPUT_MODE, 1, group_addr=1)

    def _on_scan_settled(self):
        """阶段应答窗结束，决定下一步"""
        if not self._scanning:
            return
        online = [m.addr for m in self.module_manager.get_all_modules() if m.online]

        if self._scan_phase == 0:
            if online:
                self._finish_scan()
                return
            self._scan_phase = 1
            self._scan_index = 0
            self.btn_scan.setText("停止扫描")
            self.signal_log.emit(
                "[系统] 监听无周期帧，用组地址 0 逐地址读状态 (0x01~0x3F)...")
            self._scan_timer.start(180)
            return

        if self._scan_phase == 1:
            if online:
                self._set_group(0, log=False)
                self.signal_log.emit("[系统] 组地址 0 有效")
                self._finish_scan()
                return
            self._scan_phase = 2
            self._scan_index = 0
            self.signal_log.emit(
                "[系统] 组地址 0 全部无应答，改用组地址 1 再扫一遍...")
            self.btn_scan.setText("停止扫描")
            self._scan_timer.start(180)
            return

        if self._scan_phase == 2:
            if online:
                self._set_group(1, log=False)
                self.signal_log.emit("[系统] 组地址 1 有效")
                self._finish_scan()
                return
            self._scan_phase = 3
            self._scan_index = 0
            self.signal_log.emit("[系统] 读无应答，组地址 0 设置命令探测...")
            self.btn_scan.setText("停止扫描")
            self._scan_timer.start(180)
            return

        if self._scan_phase == 3:
            if online:
                self._set_group(0, log=False)
                self._finish_scan()
                return
            self._scan_phase = 4
            self._scan_index = 0
            self.signal_log.emit("[系统] 组地址 1 设置命令探测...")
            self.btn_scan.setText("停止扫描")
            self._scan_timer.start(180)
            return

        if self._scan_phase == 4:
            if online:
                self._set_group(1, log=False)
                self._finish_scan()
                return
            self._scan_phase = 5
            self.btn_scan.setText("停止扫描")
            self.signal_log.emit("[系统] 探测结束，再监听 3 秒收迟到帧...")
            self._scan_settle_timer.start(3000)
            return

        self._finish_scan()

    def _finish_scan(self):
        """汇总扫描结果"""
        self._scanning = False
        self._scan_timer.stop()
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("扫描在线模块")
        if getattr(self, "_scan_pause_poll", False) and self.chk_auto_poll.isChecked():
            self.poll_timer.start(self.poll_interval)

        raw = getattr(self.can_client, "rx_raw_log", []) or []
        rx_b = getattr(self.can_client, "rx_total_bytes", 0)
        rx_f = getattr(self.can_client, "rx_frame_count", 0)
        self.signal_log.emit(
            f"[诊断] 收包统计: TCP字节={rx_b}, 有效帧={rx_f}, 异常片段={len(raw)}")
        for seg in raw[:8]:
            self.signal_log.emit(f"[诊断] 异常原始: {seg}")

        online = [m.addr for m in self.module_manager.get_all_modules() if m.online]
        if online:
            addrs = ", ".join(f"0x{a:02X}" for a in online)
            self.signal_log.emit(f"[系统] 发现完成，在线 {len(online)} 台: {addrs}")
        else:
            self.signal_log.emit(
                "[系统] 发现完成，仍未找到在线模块。"
                "请发诊断行给开发：TCP字节=? 有无[RX]？"
                "并核对: ①模块上电/拨码 ②UT-6502 125k/扩展帧/固定格式 ③IP端口")
        try:
            self.module_table.refresh_all()
        except Exception:
            pass
        self._update_online_count()

    def _cancel_scan(self):
        """中断扫描（断开连接或出错时）"""
        self._scan_timer.stop()
        self._scan_settle_timer.stop()
        self._scanning = False
        if hasattr(self, "btn_scan"):
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText("扫描在线模块")
        if getattr(self, "_scan_pause_poll", False) and self.chk_auto_poll.isChecked():
            self.poll_timer.start(self.poll_interval)
    
    # ==================== 选中操作 ====================
    
    def _on_select_all(self):
        """全选"""
        self.module_manager.select_all()
        self.module_table.refresh_all()
        self._update_selected_count()
    
    def _on_clear_selection(self):
        """清空选择"""
        self.module_manager.clear_selection()
        self.module_table.refresh_all()
        self._update_selected_count()
    
    def _on_select_online_only(self):
        """仅选中在线"""
        self.module_manager.select_online_only()
        self.module_table.refresh_all()
        self._update_selected_count()
    
    def _update_selected_count(self):
        """更新选中数量显示"""
        count = self.module_manager.get_selected_count()
        self.lbl_selected.setText(f"已选: {count}")
    
    def _on_selected_power_on(self):
        """选中开机 — 模式→电压→电流→开机（避免 NameError 闪退）"""
        if not self._check_connected():
            return

        modules = self.module_manager.get_selected_modules()
        if not modules:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        if not self._confirm_power_on([m.addr for m in modules], "确认选中开机"):
            return

        try:
            voltage = float(self.batch_voltage_spin.value())
            current = float(self.batch_current_spin.value())
        except Exception:
            voltage, current = 0.0, 0.0

        for m in modules:
            try:
                self._send_set_command(m.addr, CMD_OUTPUT_MODE, 1)
                self._send_set_command(m.addr, CMD_VOUT_SET, int(voltage * 1000))
                self._send_set_command(m.addr, CMD_IOUT_LIMIT, int(current * 1000))
                self._send_set_command(m.addr, CMD_POWER_CTRL, 0)
                self._powered_addrs.add(m.addr)
            except Exception as e:
                self.signal_log.emit(f"[错误] 0x{m.addr:02X} 开机失败: {e}")

        self.signal_log.emit(
            f"[系统] 已向 {len(modules)} 个选中模块发送开机序列 V={voltage:.2f} I={current:.2f}")
        if self._powered_addrs:
            self._wd_timer.start(2000)

    def _on_selected_power_off(self):
        """选中关机"""
        if not self._check_connected():
            return

        modules = self.module_manager.get_selected_modules()
        if not modules:
            QMessageBox.information(self, "提示", "请先选择模块")
            return

        for m in modules:
            self._send_set_command(m.addr, CMD_POWER_CTRL, 1)
            self._powered_addrs.discard(m.addr)

        self.signal_log.emit(f"[系统] 已向 {len(modules)} 个选中模块发送关机命令")
    
    def _on_selected_set_vi(self):
        """选中设置V/I"""
        if not self._check_connected():
            return
        
        modules = self.module_manager.get_selected_modules()
        if not modules:
            QMessageBox.information(self, "提示", "请先选择模块")
            return
        
        voltage = self.batch_voltage_spin.value()
        current = self.batch_current_spin.value()
        
        for m in modules:
            self._send_set_command(m.addr, CMD_VOUT_SET, int(voltage * 1000))
            self._send_set_command(m.addr, CMD_IOUT_LIMIT, int(current * 1000))
        
        self.signal_log.emit(f"[系统] 已向 {len(modules)} 个选中模块发送V/I设置命令")
    
    # ==================== 单个模块操作 ====================
    
    def _on_module_power_on(self, addr):
        """单个模块开机 — 按协议附录顺序：模式→电压→电流→开机（喂狗）"""
        if not self._check_connected():
            return
        if not self._confirm_power_on([addr], "确认开机"):
            return
        try:
            m = self.module_manager.get_module(addr)
            # 优先用行内输入框的设定值
            v = None
            i = None
            sv = getattr(self.module_table, "_sv", {}).get(addr)
            si = getattr(self.module_table, "_si", {}).get(addr)
            if sv is not None:
                v = sv.value()
            if si is not None:
                i = si.value()
            if v is None and m is not None:
                v = m.set_voltage
            if i is None and m is not None:
                i = m.set_current
            v = float(v or 0.0)
            i = float(i or 0.0)

            self._send_set_command(addr, CMD_OUTPUT_MODE, 1)
            self._send_set_command(addr, CMD_VOUT_SET, int(v * 1000))
            self._send_set_command(addr, CMD_IOUT_LIMIT, int(i * 1000))
            self._send_set_command(addr, CMD_POWER_CTRL, 0)
            self.signal_log.emit(
                f"[下发] 0x{addr:02X} 开机序列 模式=1 V={v:.2f} I={i:.2f} POWER_CTRL=0")
            self._powered_addrs.add(addr)
            self._wd_timer.start(2000)
        except Exception as e:
            self.signal_log.emit(f"[错误] 0x{addr:02X} 开机异常: {e}")

    def _on_module_power_off(self, addr):
        """单个模块关机"""
        if not self._check_connected():
            return
        try:
            self._send_set_command(addr, CMD_POWER_CTRL, 1)
            self._powered_addrs.discard(addr)
            self.signal_log.emit(f"[下发] 0x{addr:02X} 关机 (POWER_CTRL=1)")
        except Exception as e:
            self.signal_log.emit(f"[错误] 0x{addr:02X} 关机异常: {e}")

    def _on_watchdog(self):
        """对已开机模块重发设定+开机，避免模块看门狗掉电 / 通信 E15"""
        try:
            if not self.can_client.is_connected() or self._scanning:
                return
            if not self._powered_addrs:
                self._wd_timer.stop()
                return
            for addr in list(self._powered_addrs):
                m = self.module_manager.get_module(addr)
                if m is None:
                    self._powered_addrs.discard(addr)
                    continue
                if not m.online:
                    # 模块已离线：停发喂狗帧，重新上线（应答刷新状态）后自动恢复
                    continue
                self._send_set_command(addr, CMD_VOUT_SET, int(float(m.set_voltage) * 1000))
                self._send_set_command(addr, CMD_IOUT_LIMIT, int(float(m.set_current) * 1000))
                self._send_set_command(addr, CMD_POWER_CTRL, 0)
            for m in self.module_manager.get_all_modules():
                if m.online:
                    self._send_read_command(m.addr, CMD_MODULE_STATUS)
                    self._send_read_command(m.addr, CMD_VOUT)
                    self._send_read_command(m.addr, CMD_IOUT)
                    break
        except Exception as e:
            self.signal_log.emit(f"[错误] 喂狗异常: {e}")
    
    def _on_module_set_vi(self, addr):
        """单个模块设置V/I（右侧公共输入框）"""
        if not self._check_connected():
            return

        voltage = self.set_voltage_spin.value()
        current = self.set_current_spin.value()

        self._send_set_command(addr, CMD_VOUT_SET, int(voltage * 1000))
        self._send_set_command(addr, CMD_IOUT_LIMIT, int(current * 1000))

    def _on_module_set_vi_values(self, addr, voltage, current):
        """单个模块设置V/I（表格行内输入框下发）"""
        if not self._check_connected():
            return
        v1 = int(voltage * 1000)
        i1 = int(current * 1000)
        self._send_set_command(addr, CMD_VOUT_SET, v1)
        self._send_set_command(addr, CMD_IOUT_LIMIT, i1)
        self.signal_log.emit(
            f"[下发] 0x{addr:02X} 设置 {voltage:.1f}V/{current:.1f}A (mV={v1} mA={i1})")
    
    def _on_table_selection_changed(self):
        """表格选中行改变：点任意列都更新「当前模块」，便于右侧面板操作对应模块"""
        items = self.module_table.selectedItems()
        if not items:
            return
        row = self.module_table.row(items[0])
        modules = self.module_manager.get_all_modules()
        if row < len(modules):
            self.current_module_addr = modules[row].addr
            self.lbl_current_module.setText(
                f"当前模块: 0x{self.current_module_addr:02X} ({self.current_module_addr}#)"
            )
    
    # ==================== 右侧面板操作 ====================
    
    def _on_set_mode(self):
        """设置运行模式"""
        if not self._check_connected():
            return
        
        mode = self.mode_combo.currentData()
        # 校验目标模块在线，避免设置发到离线/不存在的模块上「看似无反应」
        m = self.module_manager.get_module(self.current_module_addr)
        if m is None or not m.online:
            QMessageBox.warning(
                self, "提示",
                f"目标模块 0x{self.current_module_addr:02X} 当前离线。\n"
                "请先在左侧表格点选一台「在线」的模块，再设置运行模式。")
            return
        self._send_set_command(self.current_module_addr, CMD_OUTPUT_MODE, mode)
        self.signal_log.emit(
            f"[下发] 0x{self.current_module_addr:02X} 设置运行模式={mode} "
            f"({self.mode_combo.currentText()})")
    
    def _on_set_voltage_current(self):
        """设置电压电流"""
        if not self._check_connected():
            return
        
        voltage = self.set_voltage_spin.value()
        current = self.set_current_spin.value()
        
        self._send_set_command(self.current_module_addr, CMD_VOUT_SET, int(voltage * 1000))
        self._send_set_command(self.current_module_addr, CMD_IOUT_LIMIT, int(current * 1000))
    
    def _on_set_power(self):
        """设置功率"""
        if not self._check_connected():
            return
        
        active = self.set_power_spin.value()
        reactive = self.set_reactive_spin.value()
        
        self._send_set_command(self.current_module_addr, CMD_P_ACTIVE_SET, active)
        self._send_set_command(self.current_module_addr, CMD_P_REACTIVE_SET, reactive)
    
    def _on_read_status(self):
        """读取状态"""
        if not self._check_connected():
            return
        
        self._send_read_command(self.current_module_addr, CMD_MODULE_STATUS)
    
    def _on_read_voltage_current(self):
        """读取电压电流"""
        if not self._check_connected():
            return
        
        self._send_read_command(self.current_module_addr, CMD_VOUT)
        self._send_read_command(self.current_module_addr, CMD_IOUT)
        self._send_read_command(self.current_module_addr, CMD_VOUT_SET)
        self._send_read_command(self.current_module_addr, CMD_IOUT_LIMIT)
    
    def _on_read_alarm(self):
        """读取告警"""
        if not self._check_connected():
            return

        self._send_read_command(self.current_module_addr, CMD_ALARM1)
        self._send_read_command(self.current_module_addr, CMD_ALARM2)

    def _on_clear_fault(self):
        """清除故障：E15 通信超时靠恢复通信清除，其它可断电重启"""
        if not self._check_connected():
            return
        addr = self.current_module_addr
        self.signal_log.emit(
            f"[系统] 清除故障 0x{addr:02X}：恢复心跳/轮询并回读（E15=通信超时，恢复通信后应消除）")
        # 1) 确保心跳与轮询在跑
        if not self._ka_timer.isActive():
            self._ka_timer.start(self._ka_interval)
        if self.chk_auto_poll.isChecked() and not self.auto_poll:
            self._start_polling()
        # 2) 写长通信超时（120s），避免马上再超时
        self._send_set_command(addr, CMD_EXTENDED, 120, cmd_sup=EXT_COMM_TIMEOUT)
        self.signal_log.emit(f"[系统] 0x{addr:02X} 通信超时写入 120 秒（防再次 E15）")
        # 3) 回读状态/告警
        self._send_read_command(addr, CMD_MODULE_STATUS)
        self._send_read_command(addr, CMD_ALARM1)
        self._send_read_command(addr, CMD_ALARM2)
        # 4) 询问是否断电重启（硬故障才有效）
        reply = QMessageBox.question(
            self, "清除故障",
            f"已恢复通信并回读 0x{addr:02X}。\n\n"
            "E15 通信超时：一般恢复通信即可消除。\n"
            "若面板仍有其它 E 码（过压/过流等），需要断电重启。\n\n"
            "是否对该模块执行关机→开机？",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._send_set_command(addr, CMD_POWER_CTRL, 1)
            QTimer.singleShot(500, lambda: self._send_set_command(addr, CMD_POWER_CTRL, 0))
            self.signal_log.emit(f"[系统] 0x{addr:02X} 已下发关机→开机（500ms）")

    def _on_show_fault_codes(self):
        """显示 E02~E20 故障码表"""
        lines = ["UAB-1K030B-E 面板故障代码 E02~E20", ""]
        for code in range(2, 21):
            name, desc = FAULT_CODES.get(code, (f"E{code:02d}", ""))
            lines.append(f"{name}  {desc}")
        lines += [
            "",
            "说明：E 码为模块面板/手册代码，与 CAN「告警位」互为参考。",
            "E15 通信故障：超过通信超时未收到上位机报文；恢复通信后可清除。",
        ]
        QMessageBox.information(self, "故障码 E02~E20", "\n".join(lines))

    def _on_read_all(self):
        """读取全部信息"""
        if not self._check_connected():
            return

        cmds = [CMD_MODULE_STATUS, CMD_VOUT, CMD_IOUT, CMD_VOUT_SET, CMD_IOUT_LIMIT,
                CMD_OUTPUT_MODE, CMD_ALARM1, CMD_ALARM2, CMD_VBAT]
        for cmd in cmds:
            self._send_read_command(self.current_module_addr, cmd)
    
    def _on_read_module_id(self):
        """读取模块ID"""
        if not self._check_connected():
            return
        
        self._send_read_command(self.current_module_addr, 0x05)  # 读取序列号
        self.id_display.append(f"已向 0x{self.current_module_addr:02X} 发送ID读取命令")
    
    def _on_change_module_id(self):
        """修改模块ID（占位：真实命令待协议文档确认，暂不可用）"""
        # 模块 ID 修改命令尚未在协议文档中确认，禁止下发误导性命令
        QMessageBox.information(
            self, "修改模块ID",
            "模块 ID 修改命令尚未在协议文档中确认，暂不可用。\n"
            "请以厂家协议手册为准，确认后补充实现。")
        return
    
    # ==================== 工具方法 ====================

    def _check_connected(self):
        """检查是否已连接"""
        if not self.can_client.is_connected():
            QMessageBox.warning(self, "提示", "请先连接到UT-6502设备")
            return False
        return True

    def closeEvent(self, event):
        try:
            self.poll_timer.stop()
        except Exception:
            pass
        # 停止心跳/看门狗/扫描定时器，避免卸载后仍在后台跑
        for attr in ("_ka_timer", "_wd_timer", "_scan_timer"):
            t = getattr(self, attr, None)
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
        try:
            self.can_client.disconnect()
        except Exception:
            pass
        event.accept()


