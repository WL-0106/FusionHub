# -*- coding: utf-8 -*-
"""
禾享源 HBTW 模块监控上位机
通过 UT-6502 以太网(光纤)-CAN 转换器控制 HBTW60160/80100/12075/20070 模块
- 开机: 恒压限流指令 (0xD8 模式01, 发送电压/电流设定值)
- 关机: 单机停机 (0xD8 模式00) / 并机停机广播 (0x0E)
- 设备 ID 读取(生命帧回读) 与 修改 (0xD9)
"""

import json
import os
import sys
import time
from datetime import datetime

from modules.theme_util import expand_qss
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGroupBox, QHBoxLayout, QVBoxLayout,
    QGridLayout, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QPlainTextEdit, QSplitter, QComboBox,
    QListWidget, QMessageBox, QFileDialog, QFrame, QScrollArea,
)

from . import hbtw_protocol as hp
from .ut6502_client import Ut6502Client

if getattr(sys, "frozen", False):
    # PyInstaller 打包后: 配置文件放在 EXE 旁, 而非临时解压目录
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "settings_hbtw.json")

# 配色 (与参考界面一致)
C_TEXT = "#2A3340"
C_TEXT2 = "#6B7280"
C_GREEN = "#047857"
C_BLUE = "#0E7490"
C_RED = "#B01030"

QSS = """
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

COL_SEL, COL_ADDR, COL_ONLINE, COL_POWER, COL_V, COL_I, COL_BUS, \
    COL_SV, COL_SI, COL_MODE, COL_FAULT, COL_ON, COL_OFF, COL_SETVI = range(14)
TABLE_HEADERS = ["", "地址", "在线", "电源", "电压(V)", "电流(A)", "母线电压(V)",
                 "设置电压(V)", "设置电流(A)", "单/并机", "故障", "开机", "关机", "设置V/I"]


def green_btn(text, tip=""):
    return _btn(text, "green", tip)


def pink_btn(text, tip=""):
    return _btn(text, "pink", tip)


def blue_btn(text, tip=""):
    return _btn(text, "blue", tip)


def cream_btn(text, tip=""):
    return _btn(text, "cream", tip)


def _btn(text, cls, tip):
    b = QPushButton(text)
    b.setProperty("cls", cls)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


RUN_ON_A = 1.0    # 进入"运行"的电流门限(A): 需连续 RUN_ON_CNT 帧达标, 随机噪声无法连续触发
RUN_ON_CNT = 3     # 进入"运行"所需连续电流帧数
RUN_OFF_A = 0.5    # 退出"运行"的电流门限(A): 必须高于实测零点噪声幅度(约±0.4A), 否则被噪声卡住退不出
RUN_V_ON = 10.0    # 进入"运行"的电压门限(V)
RUN_V_OFF = 5.0    # 退出"运行"的电压门限(V)


class ModuleState:
    __slots__ = ("online", "last_seen", "v_dc", "v_bus", "i_dc",
                 "parallel", "faults", "power", "set_v", "set_i", "running",
                 "run_cnt")

    def __init__(self):
        self.online = False
        self.last_seen = 0.0
        self.v_dc = None
        self.v_bus = None
        self.i_dc = None
        self.parallel = None
        self.faults = []
        self.power = False
        self.set_v = None
        self.set_i = None
        self.running = False
        self.run_cnt = 0

    def reset(self):
        self.online = False
        self.v_dc = self.v_bus = self.i_dc = None
        self.parallel = None
        self.faults = []
        self.power = False
        self.running = False
        self.run_cnt = 0

    def clear_running(self):
        """关机/停机指令后立即清除运行状态(电压不泄放时靠电流退出不可靠)"""
        self.running = False
        self.run_cnt = 0

    def is_running(self):
        """带滞回+连续帧确认的运行判定:
        进入: V>=RUN_V_ON 且 |I|>=RUN_ON_A 连续 RUN_ON_CNT 次
        退出: V<RUN_V_OFF 或 |I|<RUN_OFF_A (RUN_OFF_A 高于零点噪声, 噪声不会卡住退出)"""
        if self.i_dc is None or self.v_dc is None:
            self.running = False
            self.run_cnt = 0
        elif self.running:
            if abs(self.i_dc) < RUN_OFF_A or self.v_dc < RUN_V_OFF:
                self.running = False
                self.run_cnt = 0
        elif abs(self.i_dc) >= RUN_ON_A and self.v_dc >= RUN_V_ON:
            self.run_cnt += 1
            if self.run_cnt >= RUN_ON_CNT:
                self.running = True
        else:
            self.run_cnt = 0
        return self.running


def fmt(v, nd=1):
    return "---" if v is None else ("%." + str(nd) + "f") % v


class HexSpin(QSpinBox):
    """以 0xNN 两位十六进制显示的 ID 选择框"""

    def textFromValue(self, v):
        return "0x%02X" % v


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("禾享源 HBTW 模块监控上位机 v1.0  (UT-6502 以太网-CAN)")
        self.resize(1420, 900)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(expand_qss(QSS))

        self.cfg = self._load_config()
        self.states = {i: ModuleState() for i in range(hp.MIN_ID, hp.MAX_ID + 1)}
        self.current_module = 1
        self.life_seq = 0
        self.scan_deadline = 0.0
        self.scan_seen = set()
        self._scan_busy = False
        self._scan_cancelled = False
        self.chk_by_addr = {}
        self.row_vi = {}   # addr -> (电压输入框, 电流输入框) 表格行内设置V/I

        self.client = Ut6502Client(self)
        self.client.connected.connect(self._on_connected)
        self.client.disconnected.connect(self._on_disconnected)
        self.client.error_occurred.connect(self._on_sock_error)
        self.client.frame_received.connect(self._on_frame)
        self.client.stats_changed.connect(self._on_stats)

        self.life_timer = QTimer(self)                     # 自动轮询: 发送生命帧
        self.life_timer.timeout.connect(self._send_life)
        self.offline_timer = QTimer(self)                  # 在线超时检测
        self.offline_timer.timeout.connect(self._check_offline)
        self.offline_timer.start(1000)

        self._build_ui()
        self._apply_config()
        self._log_sys("软件就绪. 请先在 UT-6502 Web 页面确认: TCP Server / 端口 %d / "
                      "CAN 波特率 1Mbps / 固定格式传输 / 扩展帧" % self.spn_port.value())

    # ================= 配置 =================
    def _load_config(self):
        default = {"ip": "192.168.1.125", "port": 5001, "poll": True, "poll_ms": 1000,
                   "batch_v": 50.0, "batch_i": 50.0, "ctrl_v": 50.0, "ctrl_i": 50.0,
                   "v_scale": 100, "show_tx": True, "show_rx": True, "autoscroll": True}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                default.update(json.load(f))
        except Exception:
            pass
        return default

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _apply_config(self):
        self.edt_ip.setText(str(self.cfg.get("ip", "192.168.1.125")))
        self.spn_port.setValue(int(self.cfg.get("port", 5001)))
        self.chk_poll.setChecked(bool(self.cfg.get("poll", True)))
        self.spn_poll.setValue(int(self.cfg.get("poll_ms", 1000)))
        self.spn_batch_v.setValue(float(self.cfg.get("batch_v", 50.0)))
        self.spn_batch_i.setValue(float(self.cfg.get("batch_i", 50.0)))
        self.spn_ctrl_v.setValue(float(self.cfg.get("ctrl_v", 50.0)))
        self.spn_ctrl_i.setValue(float(self.cfg.get("ctrl_i", 50.0)))
        self.cmb_vscale.setCurrentIndex(0 if int(self.cfg.get("v_scale", 100)) == 100 else 1)
        self.chk_show_tx.setChecked(bool(self.cfg.get("show_tx", True)))
        self.chk_show_rx.setChecked(bool(self.cfg.get("show_rx", True)))
        self.chk_autoscroll.setChecked(bool(self.cfg.get("autoscroll", True)))

    def _gather_config(self):
        self.cfg.update({
            "ip": self.edt_ip.text().strip(), "port": self.spn_port.value(),
            "poll": self.chk_poll.isChecked(), "poll_ms": self.spn_poll.value(),
            "batch_v": self.spn_batch_v.value(), "batch_i": self.spn_batch_i.value(),
            "ctrl_v": self.spn_ctrl_v.value(), "ctrl_i": self.spn_ctrl_i.value(),
            "v_scale": self._v_scale(), "show_tx": self.chk_show_tx.isChecked(),
            "show_rx": self.chk_show_rx.isChecked(), "autoscroll": self.chk_autoscroll.isChecked(),
        })

    def _v_scale(self):
        return 100 if self.cmb_vscale.currentIndex() == 0 else 10

    # ================= UI 构建 =================
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_conn_group())
        root.addWidget(self._build_batch_group())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_table_group())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([980, 440])
        root.addWidget(splitter, 1)

        root.addWidget(self._build_log_group(), 0)

        sb = self.statusBar()
        self.lbl_online = QLabel("在线: 0/63")
        self.lbl_tx = QLabel("TX: 0")
        self.lbl_rx = QLabel("RX: 0")
        self.lbl_net = QLabel("未连接")
        sb.addPermanentWidget(self.lbl_net)
        sb.addPermanentWidget(self.lbl_tx)
        sb.addPermanentWidget(self.lbl_rx)
        sb.addPermanentWidget(self.lbl_online)

    def _build_conn_group(self):
        g = QGroupBox("连接配置")
        h = QHBoxLayout(g)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(8)
        h.addWidget(QLabel("UT-6502 IP:"))
        self.edt_ip = QLineEdit("192.168.1.125")
        self.edt_ip.setFixedWidth(120)
        h.addWidget(self.edt_ip)
        h.addWidget(QLabel("端口:"))
        self.spn_port = QSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(5001)
        h.addWidget(self.spn_port)
        self.btn_connect = green_btn("连接", "连接 UT-6502 (TCP)")
        self.btn_connect.clicked.connect(self._do_connect)
        h.addWidget(self.btn_connect)
        self.btn_disconnect = pink_btn("断开", "断开 TCP 连接")
        self.btn_disconnect.clicked.connect(self._do_disconnect)
        self.btn_disconnect.setEnabled(False)
        h.addWidget(self.btn_disconnect)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#E4E9EF;")
        h.addWidget(sep)
        self.chk_poll = QCheckBox("自动轮询在线模块")
        self.chk_poll.setChecked(True)
        h.addWidget(self.chk_poll)
        h.addWidget(QLabel("间隔(ms):"))
        self.spn_poll = QSpinBox()
        self.spn_poll.setRange(200, 60000)
        self.spn_poll.setValue(1000)
        self.spn_poll.setToolTip("协议要求生命帧间隔 1000ms")
        self.spn_poll.valueChanged.connect(self._poll_changed)
        h.addWidget(self.spn_poll)
        h.addStretch(1)
        self.lbl_status = QLabel("● 未连接")
        self.lbl_status.setStyleSheet("color:#B01030; font-weight:bold;")
        h.addWidget(self.lbl_status)
        return g

    def _build_batch_group(self):
        g = QGroupBox("批量操作")
        h = QHBoxLayout(g)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(8)
        self.btn_all_on = green_btn("全部开机",
                                    "广播恒压限流指令(0x08E07F11 D8 00 01), 使用下方批量电压/电流")
        self.btn_all_on.clicked.connect(lambda: self._power_on(None, True))
        h.addWidget(self.btn_all_on)
        self.btn_all_off = pink_btn("并机关机(全部)",
                                    "并机停机广播 0x08E07F11 0E 00 01——总线上所有模块一起停")
        self.btn_all_off.clicked.connect(self._stop_broadcast)
        h.addWidget(self.btn_all_off)
        self.btn_bcast_clear = blue_btn("广播故障清除",
                                        "关机后源红灯/故障锁存时用：0x08E07F11 0F 00 01")
        self.btn_bcast_clear.clicked.connect(lambda: self._clear_fault(True))
        h.addWidget(self.btn_bcast_clear)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#E4E9EF;")
        h.addWidget(sep)
        h.addWidget(QLabel("批量电压(V):"))
        self.spn_batch_v = QDoubleSpinBox()
        self.spn_batch_v.setRange(0.0, 6553.5)
        self.spn_batch_v.setDecimals(1)
        self.spn_batch_v.setSingleStep(0.5)
        self.spn_batch_v.setValue(50.0)
        h.addWidget(self.spn_batch_v)
        h.addWidget(QLabel("批量电流(A):"))
        self.spn_batch_i = QDoubleSpinBox()
        self.spn_batch_i.setRange(0.0, 6553.5)
        self.spn_batch_i.setDecimals(1)
        self.spn_batch_i.setSingleStep(0.5)
        self.spn_batch_i.setValue(50.0)
        h.addWidget(self.spn_batch_i)
        self.btn_batch_vi = blue_btn("批量设置电压电流",
                                     "向所有勾选模块发送恒压限流指令(该指令同时为开机指令)")
        self.btn_batch_vi.clicked.connect(self._batch_set_vi)
        h.addWidget(self.btn_batch_vi)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color:#E4E9EF;")
        h.addWidget(sep2)
        self.btn_init = cream_btn("一键初始化", "广播故障清除 + 广播并机停机")
        self.btn_init.clicked.connect(self._init_all)
        h.addWidget(self.btn_init)
        self.btn_scan = blue_btn("扫描在线模块", "发送生命帧并收集 3 秒内的模块应答")
        self.btn_scan.clicked.connect(self.start_scan)
        h.addWidget(self.btn_scan)
        self.btn_fault_codes = blue_btn("故障代码查询", "查看 HBTW 故障位定义")
        self.btn_fault_codes.clicked.connect(self._on_show_fault_codes)
        h.addWidget(self.btn_fault_codes)
        h.addStretch(1)
        return g

    def _build_table_group(self):
        g = QGroupBox("模块实时监控")
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 6)
        v.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(10)
        lbl1 = QLabel("地址 0x01~0x3F")
        lbl1.setProperty("role", "h")
        top.addWidget(lbl1)
        self.lbl_cur = QLabel("当前模块: 0x01 (1#)")
        self.lbl_cur.setStyleSheet("color:#0E7490;")
        top.addWidget(self.lbl_cur)
        self.lbl_sel = QLabel("已选: 0")
        self.lbl_sel.setProperty("role", "h")
        top.addWidget(self.lbl_sel)
        top.addStretch(1)
        b_sel_all = blue_btn("全选", "勾选全部模块")
        b_sel_all.clicked.connect(lambda: self._set_all_checked(True))
        top.addWidget(b_sel_all)
        b_sel_none = blue_btn("清空", "取消全部勾选")
        b_sel_none.clicked.connect(lambda: self._set_all_checked(False))
        top.addWidget(b_sel_none)
        b_sel_online = blue_btn("仅在线", "只勾选在线模块")
        b_sel_online.clicked.connect(self._select_online)
        top.addWidget(b_sel_online)
        b_chk_on = green_btn("选中开机", "对勾选模块发送恒压限流(开机)指令")
        b_chk_on.clicked.connect(self._checked_power_on)
        top.addWidget(b_chk_on)
        b_chk_off = pink_btn("选中单机关机", "对勾选模块逐台发送单机停机(不会广播)")
        b_chk_off.clicked.connect(self._checked_stop)
        top.addWidget(b_chk_off)
        b_chk_vi = blue_btn("选中设置V/I", "对勾选模块发送批量电压/电流")
        b_chk_vi.clicked.connect(self._batch_set_vi)
        top.addWidget(b_chk_vi)
        v.addLayout(top)

        self.table = QTableWidget(hp.MAX_ID, len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setDefaultSectionSize(27)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        widths = [36, 52, 52, 56, 68, 68, 88, 90, 90, 56, 170, 46, 46, 58]
        for col, w in enumerate(widths):
            self.table.setColumnWidth(col, w)
        header.setSectionResizeMode(COL_FAULT, QHeaderView.Stretch)
        # 窄屏幕下允许表格水平滚动, 避免右侧面板被挤出窗口
        self.table.setMinimumWidth(420)

        for addr in range(hp.MIN_ID, hp.MAX_ID + 1):
            row = addr - 1
            # 勾选框
            cw = QWidget()
            cl = QHBoxLayout(cw)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            cl.setAlignment(Qt.AlignCenter)
            chk = QCheckBox()
            chk.toggled.connect(self._update_sel_count)
            cl.addWidget(chk)
            self.chk_by_addr[addr] = chk
            self.table.setCellWidget(row, COL_SEL, cw)
            # 文本单元格
            texts = {COL_ADDR: "0x%02X" % addr, COL_ONLINE: "○ 离线", COL_POWER: "○ 关机",
                     COL_V: "---", COL_I: "---", COL_BUS: "---",
                     COL_MODE: "---", COL_FAULT: "---"}
            for col, text in texts.items():
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, it)
            # 设置电压/电流: 行内可输入数值框, 行内按钮按此值发送
            spn_v = QDoubleSpinBox()
            spn_v.setRange(0.0, 6553.5)
            spn_v.setDecimals(1)
            spn_v.setSingleStep(0.5)
            spn_v.setValue(50.0)
            spn_v.setToolTip("该模块的设置电压, 点\"开/设置\"按此值发送恒压限流指令")
            self.table.setCellWidget(row, COL_SV, spn_v)
            spn_i = QDoubleSpinBox()
            spn_i.setRange(0.0, 6553.5)
            spn_i.setDecimals(1)
            spn_i.setSingleStep(0.5)
            spn_i.setValue(50.0)
            spn_i.setToolTip("该模块的设置电流(限流值), 点\"开/设置\"按此值发送恒压限流指令")
            self.table.setCellWidget(row, COL_SI, spn_i)
            self.row_vi[addr] = (spn_v, spn_i)
            # 行内按钮
            b_on = green_btn("开", "按本行设置电压/电流发送恒压限流指令(开机)")
            b_on.setFixedHeight(22)
            b_on.clicked.connect(lambda _, a=addr: self._power_on(a, False, self.row_vi[a]))
            self.table.setCellWidget(row, COL_ON, b_on)
            b_off = pink_btn("单关", "只关这一台（单机停机 D8 00 00），不影响其它模块")
            b_off.setFixedHeight(22)
            b_off.clicked.connect(lambda _, a=addr: self._stop_single(a))
            self.table.setCellWidget(row, COL_OFF, b_off)
            b_vi = blue_btn("设置", "按本行设置电压/电流设置该模块(恒压限流)")
            b_vi.setFixedHeight(22)
            b_vi.clicked.connect(lambda _, a=addr: self._power_on(a, False, self.row_vi[a]))
            self.table.setCellWidget(row, COL_SETVI, b_vi)

        self.table.cellClicked.connect(self._table_clicked)
        self.table.selectRow(0)
        v.addWidget(self.table)
        return g

    def _build_right_panel(self):
        self.tabs = QTabWidget()

        def add_tab(builder, title):
            # 页签内容放入滚动区: 小屏幕上右面板被压缩时可滚动, 不被裁切
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            w = builder()
            w.setObjectName("tabPage")
            area.setWidget(w)
            self.tabs.addTab(area, title)

        add_tab(self._build_ctrl_tab, "模块控制")
        add_tab(self._build_id_tab, "ID 管理")
        add_tab(self._build_init_tab, "初始化配置")
        add_tab(self._build_info_tab, "模块信息")
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tabs)
        panel.setMinimumWidth(380)
        panel.setMaximumWidth(520)
        return panel

    # ---- Tab1 模块控制 ----
    def _build_ctrl_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        gb1 = QGroupBox("输出电压电流设定 (恒压限流 = 开机)")
        gb1.setToolTip("恒压限流指令: 0xD8 / 模式01, 发送至 0x08E0C(ID)11")
        g1 = QGridLayout(gb1)
        g1.setContentsMargins(8, 4, 8, 6)
        g1.setVerticalSpacing(6)
        g1.addWidget(QLabel("目标模块:"), 0, 0)
        self.cmb_module = QComboBox()
        for i in range(hp.MIN_ID, hp.MAX_ID + 1):
            self.cmb_module.addItem("0x%02X (%d#)" % (i, i))
        self.cmb_module.currentIndexChanged.connect(self._module_changed)
        g1.addWidget(self.cmb_module, 0, 1)
        g1.addWidget(QLabel("电压(V):"), 1, 0)
        self.spn_ctrl_v = QDoubleSpinBox()
        self.spn_ctrl_v.setRange(0.0, 6553.5)
        self.spn_ctrl_v.setDecimals(1)
        self.spn_ctrl_v.setSingleStep(0.5)
        self.spn_ctrl_v.setValue(50.0)
        g1.addWidget(self.spn_ctrl_v, 1, 1)
        g1.addWidget(QLabel("电流(A):"), 1, 2)
        self.spn_ctrl_i = QDoubleSpinBox()
        self.spn_ctrl_i.setRange(0.0, 6553.5)
        self.spn_ctrl_i.setDecimals(1)
        self.spn_ctrl_i.setSingleStep(0.5)
        self.spn_ctrl_i.setValue(50.0)
        g1.addWidget(self.spn_ctrl_i, 1, 3)
        self.btn_ctrl_on = green_btn("设置电压电流并开机",
                                     "向目标模块发送恒压限流指令(开机即由此实现)")
        self.btn_ctrl_on.clicked.connect(lambda: self._power_on(None, False))
        g1.addWidget(self.btn_ctrl_on, 2, 0, 1, 4)
        self.btn_ctrl_bcast = blue_btn("此值应用到全部模块(广播)",
                                       "以广播帧 0x08E07F11 发送恒压限流指令")
        self.btn_ctrl_bcast.clicked.connect(lambda: self._power_on(None, True))
        g1.addWidget(self.btn_ctrl_bcast, 3, 0, 1, 4)
        v.addWidget(gb1)

        gbcc = QGroupBox("恒流充放电设定 (电流符号定方向)")
        gbcc.setToolTip("恒流模式: 0xD8 / 模式02, 充电=正电流, 放电=负电流(补码)")
        gcc = QGridLayout(gbcc)
        gcc.setContentsMargins(8, 4, 8, 6)
        gcc.setVerticalSpacing(6)
        gcc.addWidget(QLabel("方向:"), 0, 0)
        self.cmb_dir = QComboBox()
        self.cmb_dir.addItem("充电 (+)")
        self.cmb_dir.addItem("放电 (-)")
        self.cmb_dir.setToolTip("充电=正电流; 放电=负电流(补码, 如放电50A=0xFE0C)")
        gcc.addWidget(self.cmb_dir, 0, 1)
        gcc.addWidget(QLabel("电流(A):"), 0, 2)
        self.spn_cc_i = QDoubleSpinBox()
        self.spn_cc_i.setRange(0.0, 6553.5)
        self.spn_cc_i.setDecimals(1)
        self.spn_cc_i.setSingleStep(0.5)
        self.spn_cc_i.setValue(50.0)
        self.spn_cc_i.setToolTip("电流绝对值, 方向由左侧选择")
        gcc.addWidget(self.spn_cc_i, 0, 3)
        self.btn_cc_on = green_btn("发送恒流指令",
                                   "目标模块: D8 00 02 00 <电流LE16>, 充电为正/放电为负(补码); 恒流指令同时为开机")
        self.btn_cc_on.clicked.connect(lambda: self._send_cc(False))
        gcc.addWidget(self.btn_cc_on, 1, 0, 1, 2)
        self.btn_cc_bcast = blue_btn("广播到全部",
                                     "以广播帧 0x08E07F11 发送恒流充放电指令")
        self.btn_cc_bcast.clicked.connect(lambda: self._send_cc(True))
        gcc.addWidget(self.btn_cc_bcast, 1, 2, 1, 2)
        cc_note = QLabel("模块为双向(±160A/±110A/±75A/±70A): 充电与放电由电流正负号切换;"
                         "恒流指令即开机, 关机请用\"关机\"按钮。")
        cc_note.setProperty("role", "h")
        cc_note.setWordWrap(True)
        gcc.addWidget(cc_note, 2, 0, 1, 4)
        v.addWidget(gbcc)

        gb2 = QGroupBox("开关机控制")
        g2 = QGridLayout(gb2)
        g2.setContentsMargins(8, 4, 8, 6)
        g2.setVerticalSpacing(6)
        b1 = green_btn("开机", "目标模块: 恒压限流指令开机")
        b1.clicked.connect(lambda: self._power_on(None, False))
        g2.addWidget(b1, 0, 0)
        b2 = pink_btn("单机关机", "D8 00 00 00 00 00 00 00 -> 0x08E0C(目标)11")
        b2.clicked.connect(lambda: self._stop_single(None))
        g2.addWidget(b2, 0, 1)
        b3 = pink_btn("并机关机", "并机停机命令(广播) 0E 00 01")
        b3.clicked.connect(self._stop_broadcast)
        g2.addWidget(b3, 0, 2)
        b4 = green_btn("全部开机", "广播恒压限流指令")
        b4.clicked.connect(lambda: self._power_on(None, True))
        g2.addWidget(b4, 1, 0)
        b5 = pink_btn("并机关机(全部)", "并机停机广播，总线上所有模块一起停")
        b5.clicked.connect(self._stop_broadcast)
        g2.addWidget(b5, 1, 1)
        b6 = blue_btn("故障清除", "目标模块: e0 00 01")
        b6.clicked.connect(lambda: self._clear_fault(None))
        g2.addWidget(b6, 1, 2)
        b7 = blue_btn("故障清除(广播)", "并机故障清除 0F 00 01")
        b7.clicked.connect(lambda: self._clear_fault(True))
        g2.addWidget(b7, 2, 0, 1, 3)
        v.addWidget(gb2)

        gb3 = QGroupBox("选中模块实时数据")
        g3 = QGridLayout(gb3)
        g3.setContentsMargins(8, 4, 8, 6)
        g3.setVerticalSpacing(4)
        self.lbl_rt = {}
        rows = [("电压:", "v", " V"), ("电流:", "i", " A"),
                ("母线电压:", "bus", " V"), ("单/并机:", "mode", ""),
                ("电源状态:", "power", ""), ("故障:", "fault", "")]
        for r, (name, key, unit) in enumerate(rows):
            lab = QLabel(name)
            lab.setProperty("role", "h")
            g3.addWidget(lab, r, 0)
            val = QLabel("---")
            val.setStyleSheet("font-weight:bold;")
            val.setMinimumHeight(18)
            self.lbl_rt[key] = (val, unit)
            g3.addWidget(val, r, 1)
        v.addWidget(gb3)
        v.addStretch(1)
        return page

    # ---- Tab2 ID 管理 ----
    def _build_id_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        tip = QLabel("模块 ID 通过生命帧触发回读: 模块状态帧 ID 末字节即为 ID 号"
                     "(如 0x18C1FFC1 表示 1 号 ID)。修改 ID 使用 0xD9 命令发送至模块当前 ID。")
        tip.setProperty("role", "h")
        tip.setWordWrap(True)
        v.addWidget(tip)

        self.btn_id_read = blue_btn("读取模块 ID (生命帧回读)", "发送生命帧, 收集 3 秒内的模块应答")
        self.btn_id_read.clicked.connect(self.start_scan)
        v.addWidget(self.btn_id_read)

        self.lst_ids = QListWidget()
        v.addWidget(self.lst_ids, 1)

        gb = QGroupBox("修改模块 ID (0xD9)")
        g = QGridLayout(gb)
        g.setContentsMargins(8, 4, 8, 6)
        g.setVerticalSpacing(6)
        g.addWidget(QLabel("当前模块 ID:"), 0, 0)
        self.spn_cur_id = HexSpin()
        self.spn_cur_id.setRange(hp.MIN_ID, hp.MAX_ID)
        self.spn_cur_id.setValue(1)
        g.addWidget(self.spn_cur_id, 0, 1)
        g.addWidget(QLabel("新模块 ID:"), 1, 0)
        self.spn_new_id = HexSpin()
        self.spn_new_id.setRange(hp.MIN_ID, hp.MAX_ID)
        self.spn_new_id.setValue(2)
        g.addWidget(self.spn_new_id, 1, 1)
        self.btn_id_write = cream_btn("修改 ID",
                                      "发送 D9 00 <新ID> 至模块当前 ID, 修改后自动重新扫描验证")
        self.btn_id_write.clicked.connect(self._write_id)
        g.addWidget(self.btn_id_write, 2, 0, 1, 2)
        warn = QLabel("注意: 修改后模块将以新 ID 应答; 新 ID 不能与在线模块冲突; "
                      "一次只修改一台模块(请断开其他模块或逐台操作)。")
        warn.setProperty("role", "warn")
        warn.setWordWrap(True)
        g.addWidget(warn, 3, 0, 1, 2)
        v.addWidget(gb)
        return page

    # ---- Tab3 初始化配置 ----
    def _build_init_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        gb0 = QGroupBox("电压指令系数")
        g0 = QGridLayout(gb0)
        g0.setContentsMargins(8, 4, 8, 6)
        g0.addWidget(QLabel("恒压限流电压系数:"), 0, 0)
        self.cmb_vscale = QComboBox()
        self.cmb_vscale.addItem("x100 (协议文档: 50V=5000=0x1388)")
        self.cmb_vscale.addItem("x10  (若模块按显示帧同系数)")
        self.cmb_vscale.currentIndexChanged.connect(
            lambda _: self.statusBar().showMessage(
                "电压指令系数已切换为 x%d" % self._v_scale(), 3000))
        g0.addWidget(self.cmb_vscale, 0, 1)
        note = QLabel("协议文档设定示例 50V=5000(即 x100), 而回读电压为 x10 系数。"
                      "若现场发现设定电压与实际输出差 10 倍, 请切换此系数。")
        note.setProperty("role", "h")
        note.setWordWrap(True)
        g0.addWidget(note, 1, 0, 1, 2)
        v.addWidget(gb0)

        gb1 = QGroupBox("故障与停机")
        g1 = QHBoxLayout(gb1)
        g1.setContentsMargins(8, 4, 8, 6)
        b = blue_btn("广播故障清除", "0x08E07F11 0F 00 01 00 00 00 00 00")
        b.clicked.connect(lambda: self._clear_fault(True))
        g1.addWidget(b)
        b2 = pink_btn("广播并机停机", "0x08E07F11 0E 00 01 00 00 00 00 00")
        b2.clicked.connect(self._stop_broadcast)
        g1.addWidget(b2)
        v.addWidget(gb1)

        gb2 = QGroupBox("限功率设定 (仅 HBTW80100 支持)")
        g2 = QHBoxLayout(gb2)
        g2.setContentsMargins(8, 4, 8, 6)
        g2.addWidget(QLabel("功率(W):"))
        self.spn_power = QSpinBox()
        self.spn_power.setRange(0, 65535)
        self.spn_power.setSingleStep(100)
        self.spn_power.setValue(2500)
        g2.addWidget(self.spn_power)
        b3 = blue_btn("设置限功率", "DD 00 <功率LE16> 00... -> 目标模块")
        b3.clicked.connect(self._set_power_limit)
        g2.addWidget(b3)
        v.addWidget(gb2)

        gb3 = QGroupBox("校准设置 (标幺值 4096)")
        g3 = QGridLayout(gb3)
        g3.setContentsMargins(8, 4, 8, 6)
        g3.setVerticalSpacing(6)
        cal_defs = [("直流电压校准:", hp.CMD_CAL_DC_V, "D4"),
                    ("直流电流校准:", hp.CMD_CAL_DC_I, "D5"),
                    ("母线电压校准:", hp.CMD_CAL_BUS_V, "D3")]
        self.spn_cals = {}
        for r, (name, cmd, code) in enumerate(cal_defs):
            g3.addWidget(QLabel(name), r, 0)
            spn = QSpinBox()
            spn.setRange(3000, 5000)
            spn.setValue(4096)
            self.spn_cals[cmd] = spn
            g3.addWidget(spn, r, 1)
            btn = blue_btn("写入", "命令 0x%s, 发送至目标模块" % code)
            btn.clicked.connect(lambda _, c=cmd: self._write_cal(c))
            g3.addWidget(btn, r, 2)
        v.addWidget(gb3)
        v.addStretch(1)
        return page

    # ---- Tab4 模块信息 ----
    def _build_info_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        b = blue_btn("刷新信息")
        b.clicked.connect(self._refresh_info)
        v.addWidget(b)
        self.txt_info = QPlainTextEdit()
        self.txt_info.setReadOnly(True)
        v.addWidget(self.txt_info, 1)
        return page

    def _build_log_group(self):
        g = QGroupBox("CAN 报文日志")
        v = QVBoxLayout(g)
        v.setContentsMargins(8, 4, 8, 6)
        v.setSpacing(5)
        h = QHBoxLayout()
        h.setSpacing(12)
        self.chk_show_tx = QCheckBox("显示发送")
        self.chk_show_tx.setChecked(True)
        h.addWidget(self.chk_show_tx)
        self.chk_show_rx = QCheckBox("显示接收")
        self.chk_show_rx.setChecked(True)
        h.addWidget(self.chk_show_rx)
        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        h.addWidget(self.chk_autoscroll)
        h.addStretch(1)
        b_clear = blue_btn("清空")
        b_clear.clicked.connect(lambda: self.txt_log.clear())
        h.addWidget(b_clear)
        b_save = blue_btn("保存")
        b_save.clicked.connect(self._save_log)
        h.addWidget(b_save)
        v.addLayout(h)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(5000)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        self.txt_log.setFont(f)
        self.txt_log.setMinimumHeight(120)
        v.addWidget(self.txt_log)
        return g

    # ================= 连接管理 =================
    def _do_connect(self):
        self._gather_config()
        self._save_config()
        self._log_sys("正在连接 %s:%d ..." % (self.cfg["ip"], self.cfg["port"]))
        self.client.connect_to(self.cfg["ip"], self.cfg["port"])

    def _do_disconnect(self):
        self.client.disconnect()

    def _on_connected(self):
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("已连接")
        self.btn_connect.setObjectName("btnConnected")
        self.btn_disconnect.setEnabled(True)
        self.edt_ip.setEnabled(False)
        self.spn_port.setEnabled(False)
        self.lbl_status.setText("● 已连接")
        self.lbl_status.setStyleSheet("color:#047857; font-weight:bold;")
        self.lbl_net.setText("%s:%d 已连接" % (self.cfg["ip"], self.cfg["port"]))
        self._log_sys("已连接 UT-6502 %s:%d" % (self.cfg["ip"], self.cfg["port"]))
        self._poll_changed()
        self._send_life()

    def _on_disconnected(self):
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("连接")
        self.btn_connect.setObjectName("btnConnect")
        self.btn_disconnect.setEnabled(False)
        self.edt_ip.setEnabled(True)
        self.spn_port.setEnabled(True)
        self.life_timer.stop()
        self._scan_cancelled = True
        self.btn_scan.setText("扫描在线模块")
        self.btn_scan.setEnabled(True)
        self.lbl_status.setText("● 未连接")
        self.lbl_status.setStyleSheet("color:#B01030; font-weight:bold;")
        self.lbl_net.setText("未连接")
        self._log_sys("连接已断开")
        for addr, st in self.states.items():
            if st.online:
                st.reset()
                self._update_row(addr)
        self._update_online_count()

    def _on_sock_error(self, msg):
        self._log_sys("[错误] %s" % msg)
        self.statusBar().showMessage("连接错误: %s" % msg, 5000)

    def _poll_changed(self):
        ms = self.spn_poll.value()
        self.life_timer.setInterval(ms)
        if self.client.is_connected and self.chk_poll.isChecked():
            self.life_timer.start()
        else:
            self.life_timer.stop()

    def _send_life(self):
        self.life_seq = (self.life_seq % 255) + 1
        cid, data = hp.build_life_frame(self.life_seq)
        self._send(cid, data, "生命帧 seq=%d" % self.life_seq)

    # ================= 收发与解析 =================
    def _send(self, can_id, data, note=""):
        ok = self.client.send_can(can_id, data)
        if ok and self.chk_show_tx.isChecked():
            self._log_can("TX", can_id, data, note, "#0E7490")
        elif not ok:
            self.statusBar().showMessage("发送失败: 未连接", 3000)
        return ok

    def _on_frame(self, can_id, data):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到设备 CAN 帧 = 通讯真正建立
        parsed = hp.parse_status(can_id, data)
        if parsed is None:
            if self.chk_show_rx.isChecked():
                self._log_can("RX", can_id, data, "", "#4B5563")
            return
        module, kind, info = parsed
        st = self.states[module]
        st.online = True
        st.last_seen = time.time()
        if kind == "voltage":
            st.v_dc, st.v_bus = info["v_dc"], info["v_bus"]
            note = "%d# 直流电压 %.1fV 母线电压 %.1fV" % (module, st.v_dc, st.v_bus)
        elif kind == "current":
            st.i_dc = info["i_dc"]
            note = "%d# 直流电流 %.1fA" % (module, st.i_dc)
        elif kind == "mode":
            st.parallel = info["parallel"]
            note = "%d# %s" % (module, "并机模式" if st.parallel else "单机模式")
        else:
            st.faults = info["faults"]
            note = "%d# 故障: %s" % (module, "、".join(st.faults) if st.faults else "已清除")
            if st.faults and not st.power:
                self._log_sys("[提示] %d# 关机后仍有故障(%s)——源红灯属锁存，请点「广播故障清除」"
                              % (module, "、".join(st.faults)))
        if self.scan_deadline > time.time():
            self.scan_seen.add(module)
        st.is_running()   # 仅在收到状态帧时评估运行判定(计连续帧)
        if self.chk_show_rx.isChecked():
            self._log_can("RX", can_id, data, note, "#047857")
        self._update_row(module)
        self._update_online_count()
        if module == self.current_module:
            self._refresh_current_panel()

    def _on_stats(self, tx, rx):
        self.lbl_tx.setText("TX: %d" % tx)
        self.lbl_rx.setText("RX: %d" % rx)

    def _check_offline(self):
        if not self.client.is_connected:
            return
        timeout = max(5000, self.spn_poll.value() * 3)
        now = time.time()
        changed = False
        for addr, st in self.states.items():
            if st.online and now - st.last_seen > timeout:
                st.online = False
                self._update_row(addr)
                changed = True
        if changed:
            self._update_online_count()
            if self.current_module:
                self._refresh_current_panel()
        # 通讯状态：全部模块离线 = 通讯中断，右上角指示灯回灰
        if not any(st.online for st in self.states.values()):
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)

    # ================= 命令操作 =================
    def _confirm_power_on(self, addrs, broadcast=False, title="确认开机"):
        """开机二次确认，弹窗列出目标模块"""
        if broadcast:
            addr_txt = "全部模块(广播)"
        elif not addrs:
            QMessageBox.information(self, "提示", "请先选择模块")
            return False
        elif len(addrs) > 30:
            addr_txt = ", ".join("0x%02X" % a for a in addrs[:30]) + " … 共 %d 台" % len(addrs)
        else:
            addr_txt = ", ".join("0x%02X" % a for a in addrs)
        return QMessageBox.question(
            self, title,
            "将对以下模块执行开机：\n\n%s\n\n确认继续?" % addr_txt,
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def _on_show_fault_codes(self):
        """显示 HBTW 故障位定义"""
        lines = ["HBTW 模块故障位定义 (故障帧 SID 0x10B0FF00)", ""]
        for idx, bits in sorted(hp.FAULT_BITS.items()):
            for bit, name in bits:
                lines.append("  第%d字节 bit%d: %s" % (idx, bit, name))
        lines += [
            "",
            "说明：故障帧 b0/b1/b2 位定义如上；置 1 表示对应故障。",
            "故障清除：单机 0xE0 / 广播 0x0F。",
        ]
        QMessageBox.information(self, "故障代码查询", "\n".join(lines))

    def _power_on(self, module=None, broadcast=False, vi=None):
        """恒压限流指令 = 设置电压电流 = 开机; vi=(电压输入框,电流输入框) 时按行内值发送"""
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        if module is None:
            module = self.cmb_module.currentIndex() + 1
        if broadcast:
            if not self._confirm_power_on(None, True, "确认全部开机"):
                return
        else:
            if not self._confirm_power_on([module], False, "确认开机"):
                return
        if broadcast:
            v, i = self.spn_batch_v.value(), self.spn_batch_i.value()
        elif vi is not None:
            v, i = vi[0].value(), vi[1].value()
        else:
            v, i = self.spn_ctrl_v.value(), self.spn_ctrl_i.value()
        try:
            _, data = hp.build_cv_cl(v, i, self._v_scale())
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return
        if broadcast:
            can_id = hp.BROADCAST_CMD_ID
            note = "广播 恒压限流 %.1fV / %.1fA (开机)" % (v, i)
            targets = [a for a, st in self.states.items() if st.online] or list(self.states)
        else:
            can_id = hp.cmd_id(module)
            note = "%d# 恒压限流 %.1fV / %.1fA (开机)" % (module, v, i)
            targets = [module]
        if self._send(can_id, data, note):
            for a in targets:
                st = self.states[a]
                st.power = True
                st.set_v, st.set_i = v, i
                self._update_row(a)

    def _send_cc(self, broadcast=False):
        """恒流充放电指令: 电流符号决定方向 (正=充电, 负=放电/补码); 恒流指令同时为开机"""
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        module = self.cmb_module.currentIndex() + 1
        if broadcast:
            if not self._confirm_power_on(None, True, "确认全部开机"):
                return
        else:
            if not self._confirm_power_on([module], False, "确认开机"):
                return
        sign = 1 if self.cmb_dir.currentIndex() == 0 else -1
        i_abs = self.spn_cc_i.value()
        if i_abs <= 0:
            QMessageBox.warning(self, "参数错误", "恒流电流必须大于 0。")
            return
        _, data = hp.build_cc(sign * i_abs)
        direction = "充电" if sign > 0 else "放电"
        if broadcast:
            cid = hp.BROADCAST_CMD_ID
            note = "广播 恒流%s %.1fA" % (direction, i_abs)
            targets = [a for a, st in self.states.items() if st.online] or list(self.states)
        else:
            cid = hp.cmd_id(module)
            note = "%d# 恒流%s %.1fA" % (module, direction, i_abs)
            targets = [module]
        if self._send(cid, data, note):
            for a in targets:
                st = self.states[a]
                st.power = True
                st.set_i = sign * i_abs
                self._update_row(a)
            self._refresh_current_panel()

    def _stop_single(self, module=None):
        """单机停机；数秒后再清故障（协议要求停机与清故障不能同拍）"""
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        if module is None:
            module = self.cmb_module.currentIndex() + 1
        _, data = hp.build_stop()
        if self._send(hp.cmd_id(module), data, "%d# 单机停机" % module):
            st = self.states[module]
            st.power = False
            st.clear_running()
            self._update_row(module)
            if module == self.current_module:
                self._refresh_current_panel()
            self._schedule_fault_clear(lambda: self._clear_fault_for(module))

    def _stop_broadcast(self):
        """广播停机；数秒后再广播清故障（不能同拍发送）"""
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        can_id, data = hp.build_broadcast_stop()
        if self._send(can_id, data, "并机停机命令(广播)"):
            for a, st in self.states.items():
                st.power = False
                st.clear_running()
                self._update_row(a)
            self._refresh_current_panel()
            self._log_sys("[提示] 已广播停机。约 2.5 秒后自动清故障，再 2.5 秒补清一次…")
            self._schedule_fault_clear(self._clear_fault_broadcast_quiet)

    def _schedule_fault_clear(self, fn):
        """停机与清故障必须间隔数秒：2.5s 清一次，5s 再补一次（等价按两次）"""
        QTimer.singleShot(2500, fn)
        QTimer.singleShot(5000, fn)

    def _clear_fault(self, broadcast=False):
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        if broadcast is True:
            self._clear_fault_broadcast_quiet()
        else:
            module = self.cmb_module.currentIndex() + 1
            self._clear_fault_for(module)
        self._refresh_current_panel()
        self._log_sys("已发送故障清除。")

    def _clear_fault_broadcast_quiet(self):
        """广播清故障并刷新本地状态（供关机自动调用，不重复弹提示）"""
        if not self.client.is_connected:
            return
        can_id, data = hp.build_broadcast_clear_fault()
        self._send(can_id, data, "并机故障清除(广播)")
        for a, st in self.states.items():
            if st.faults:
                st.faults = []
                self._update_row(a)
        self._refresh_current_panel()

    def _clear_fault_for(self, module):
        """单机清故障并刷新本地状态"""
        if not self.client.is_connected:
            return
        _, data = hp.build_clear_fault()
        self._send(hp.cmd_id(module), data, "%d# 故障清除" % module)
        st = self.states.get(module)
        if st is not None:
            st.faults = []
            self._update_row(module)
        self._refresh_current_panel()

    def _init_all(self):
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        if QMessageBox.question(
                self, "一键初始化",
                "将执行: 广播并机停机，约 2.5 秒后自动清故障（再补清一次）。\n确定继续?") != QMessageBox.Yes:
            return
        self._stop_broadcast()

    def _batch_set_vi(self):
        """对勾选模块发送批量电压/电流(恒压限流指令, 同时为开机指令)"""
        checked = [a for a in range(hp.MIN_ID, hp.MAX_ID + 1) if self.chk_by_addr[a].isChecked()]
        if not checked:
            QMessageBox.information(self, "提示",
                                    "请先在表格中勾选目标模块。\n(如需作用于全部模块, 请使用"
                                    "\"此值应用到全部模块(广播)\")")
            return
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        if not self._confirm_power_on(checked, False, "确认选中开机"):
            return
        v, i = self.spn_batch_v.value(), self.spn_batch_i.value()
        try:
            _, data = hp.build_cv_cl(v, i, self._v_scale())
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return
        for a in checked:
            cid = hp.cmd_id(a)
            self._send(cid, data, "%d# 恒压限流 %.1fV / %.1fA" % (a, v, i))
            st = self.states[a]
            st.power = True
            st.set_v, st.set_i = v, i
            self._update_row(a)

    def _checked_power_on(self):
        self._batch_set_vi()

    def _checked_stop(self):
        checked = [a for a in range(hp.MIN_ID, hp.MAX_ID + 1) if self.chk_by_addr[a].isChecked()]
        if not checked:
            QMessageBox.information(self, "提示", "请先在表格中勾选目标模块。")
            return
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        _, data = hp.build_stop()
        for a in checked:
            self._send(hp.cmd_id(a), data, "%d# 单机停机" % a)
            self.states[a].power = False
            self.states[a].clear_running()
            self._update_row(a)
        self._log_sys("[提示] 已选中单机关机。约 2.5 秒后自动清故障，再 2.5 秒补清一次…")
        addrs = list(checked)
        self._schedule_fault_clear(lambda: [self._clear_fault_for(x) for x in addrs])

    def _set_power_limit(self):
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        module = self.cmb_module.currentIndex() + 1
        try:
            _, data = hp.build_power_limit(self.spn_power.value())
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return
        self._send(hp.cmd_id(module), data, "%d# 限功率 %dW" % (module, self.spn_power.value()))

    def _write_cal(self, cmd):
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        module = self.cmb_module.currentIndex() + 1
        try:
            _, data = hp.build_calibration(cmd, self.spn_cals[cmd].value())
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return
        self._send(hp.cmd_id(module), data, "%d# 校准写入 cmd=0x%02X val=%d"
                   % (module, cmd, self.spn_cals[cmd].value()))

    # ================= ID 管理 =================
    def start_scan(self):
        # 扫描中再点此按钮 = 中断扫描
        if getattr(self, "_scan_busy", False):
            self._scan_cancelled = True
            self._finish_scan()
            self._log_sys("已中断扫描")
            return
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        self.scan_seen = set()
        self.scan_deadline = time.time() + 3.0
        self._scan_busy = True
        self._scan_cancelled = False
        self.btn_scan.setText("停止扫描")
        self.btn_scan.setEnabled(True)
        self.btn_id_read.setEnabled(False)
        self.statusBar().showMessage("正在扫描在线模块(3 秒)...", 3000)
        self._send_life()
        QTimer.singleShot(3000, self._finish_scan)

    def _finish_scan(self):
        self._scan_busy = False
        self.btn_scan.setText("扫描在线模块")
        self.btn_scan.setEnabled(True)
        self.btn_id_read.setEnabled(True)
        self.scan_deadline = 0.0
        for addr, st in self.states.items():
            if addr not in self.scan_seen and st.online:
                st.reset()
                self._update_row(addr)
        self._update_online_count()
        self._refresh_current_panel()
        online = sorted(a for a, st in self.states.items() if st.online)
        self.lst_ids.clear()
        for a in online:
            st = self.states[a]
            fault = "、".join(st.faults) if st.faults else "无故障"
            mode = "并机" if st.parallel else "单机" if st.parallel is not None else "---"
            self.lst_ids.addItem("0x%02X (%d#)   电压 %sV   电流 %sA   %s   %s"
                                 % (a, a, fmt(st.v_dc), fmt(st.i_dc), mode, fault))
        self._refresh_info()
        self.statusBar().showMessage("扫描完成: 在线 %d 台" % len(online), 5000)
        self._log_sys("扫描完成, 在线模块: %s" % (
            ", ".join("0x%02X(%d#)" % (a, a) for a in online) if online else "无"))

    def _write_id(self):
        if not self.client.is_connected:
            self._warn_not_connected()
            return
        cur = self.spn_cur_id.value()
        new = self.spn_new_id.value()
        if cur == new:
            QMessageBox.information(self, "提示", "新 ID 与当前 ID 相同, 无需修改。")
            return
        if self.states[new].online:
            QMessageBox.warning(self, "ID 冲突",
                                "新 ID 0x%02X 已有模块在线, 请先扫描确认或更换 ID。" % new)
            return
        if not self.states[cur].online:
            ret = QMessageBox.question(
                self, "确认",
                "模块 0x%02X 当前不在线, 仍要发送修改命令吗?" % cur)
            if ret != QMessageBox.Yes:
                return
        ret = QMessageBox.question(
            self, "修改模块 ID",
            "即将把模块 0x%02X (%d#) 的 ID 修改为 0x%02X (%d#)。\n"
            "命令: 0x%08X -> D9 00 %02X 00 00 00 00 00\n"
            "修改后模块将以新 ID 应答, 稍后将自动重新扫描验证。\n确定修改?"
            % (cur, cur, new, new, hp.cmd_id(cur), new),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        try:
            _, data = hp.build_set_id(new)
        except ValueError as e:
            QMessageBox.warning(self, "参数错误", str(e))
            return
        if self._send(hp.cmd_id(cur), data, "%d# 修改ID -> %d#" % (cur, new)):
            st = self.states[cur]
            st.reset()
            self._update_row(cur)
            self._log_sys("已发送修改 ID 命令(0x%02X -> 0x%02X), 2.5 秒后自动重新扫描验证" % (cur, new))
            QTimer.singleShot(2500, lambda: self._verify_id_change(cur, new))

    def _verify_id_change(self, old, new):
        if not self.client.is_connected:
            return
        self._log_sys("正在重新扫描验证 ID 修改(0x%02X -> 0x%02X)..." % (old, new))
        self.start_scan()
        QTimer.singleShot(3200, lambda: self._report_id_change(old, new))

    def _report_id_change(self, old, new):
        if self.states[new].online:
            QMessageBox.information(self, "修改成功",
                                    "模块已使用新 ID 0x%02X (%d#) 在线应答。" % (new, new))
        else:
            QMessageBox.warning(
                self, "待确认",
                "未在 3 秒内收到新 ID 0x%02X 的应答。\n"
                "可能原因: 模块需要重新上电生效 / 修改命令未送达。\n请手动点击\"读取模块 ID\"再次确认。" % new)

    # ================= 表格与面板刷新 =================
    def _table_clicked(self, row, col):
        # 模块地址选中固定在勾选列（选择区域），其余列点击不可选中（规范）
        if col != COL_SEL:
            return
        addr = row + 1
        self.cmb_module.setCurrentIndex(row)
        self.current_module = addr
        self._refresh_current_panel()

    def _module_changed(self, idx):
        self.current_module = idx + 1
        self.lbl_cur.setText("当前模块: 0x%02X (%d#)" % (self.current_module, self.current_module))
        self.table.selectRow(idx)
        self._refresh_current_panel()
        self._refresh_info()

    def _update_sel_count(self):
        n = sum(1 for c in self.chk_by_addr.values() if c.isChecked())
        self.lbl_sel.setText("已选: %d" % n)

    def _set_all_checked(self, on):
        for c in self.chk_by_addr.values():
            c.setChecked(on)

    def _select_online(self):
        for addr, c in self.chk_by_addr.items():
            c.setChecked(self.states[addr].online)

    def _update_row(self, addr):
        row = addr - 1
        st = self.states[addr]
        t = self.table

        def set_txt(col, text, color=None, big=False):
            it = t.item(row, col)
            it.setText(text)
            it.setTextAlignment(Qt.AlignCenter)
            it.setForeground(QColor(color or C_TEXT))
            if big:
                it.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))

        if st.online:
            set_txt(COL_ONLINE, "● 在线", C_GREEN, big=True)
        else:
            set_txt(COL_ONLINE, "○ 离线", C_TEXT2, big=True)
        running = st.running
        if running:
            set_txt(COL_POWER, "● 运行", C_GREEN)
        elif st.power:
            set_txt(COL_POWER, "● 开机", C_BLUE)
        else:
            set_txt(COL_POWER, "○ 关机", C_TEXT2)
        set_txt(COL_V, fmt(st.v_dc), C_TEXT if st.v_dc is not None else C_TEXT2)
        set_txt(COL_I, fmt(st.i_dc), C_TEXT if st.i_dc is not None else C_TEXT2)
        set_txt(COL_BUS, fmt(st.v_bus), C_TEXT2 if st.v_bus is None else C_TEXT)
        # COL_SV/COL_SI 为行内输入框, 不在此更新
        if st.parallel is None:
            set_txt(COL_MODE, "---", C_TEXT2)
        else:
            set_txt(COL_MODE, "并机" if st.parallel else "单机",
                    C_BLUE if st.parallel else C_TEXT)
        if st.faults:
            # 关机后也可能锁存故障（源红灯），离线同样显示
            set_txt(COL_FAULT, "、".join(st.faults), C_RED)
        elif st.online:
            set_txt(COL_FAULT, "无", C_GREEN)
        else:
            set_txt(COL_FAULT, "---", C_TEXT2)

    def _refresh_current_panel(self):
        st = self.states[self.current_module]
        self.lbl_rt["v"][0].setText("%s V" % fmt(st.v_dc))
        self.lbl_rt["i"][0].setText("%s A" % fmt(st.i_dc))
        self.lbl_rt["bus"][0].setText("%s V" % fmt(st.v_bus))
        mode = "---" if st.parallel is None else ("并机" if st.parallel else "单机")
        self.lbl_rt["mode"][0].setText(mode)
        running = st.running
        if running:
            self.lbl_rt["power"][0].setText("● 运行")
            self.lbl_rt["power"][0].setStyleSheet("font-weight:bold; color:#047857;")
        elif st.power:
            self.lbl_rt["power"][0].setText("● 开机")
            self.lbl_rt["power"][0].setStyleSheet("font-weight:bold; color:#0E7490;")
        else:
            self.lbl_rt["power"][0].setText("○ 关机")
            self.lbl_rt["power"][0].setStyleSheet("font-weight:bold; color:#6B7280;")
        if st.faults:
            self.lbl_rt["fault"][0].setText("、".join(st.faults))
            self.lbl_rt["fault"][0].setStyleSheet("font-weight:bold; color:#B01030;")
        elif st.online:
            self.lbl_rt["fault"][0].setText("无")
            self.lbl_rt["fault"][0].setStyleSheet("font-weight:bold; color:#047857;")
        else:
            self.lbl_rt["fault"][0].setText("--- (离线)")
            self.lbl_rt["fault"][0].setStyleSheet("font-weight:bold; color:#6B7280;")

    def _update_online_count(self):
        n = sum(1 for st in self.states.values() if st.online)
        self.lbl_online.setText("在线: %d/63" % n)

    def _refresh_info(self):
        lines = ["=== 在线模块概览 ==="]
        online = [(a, st) for a, st in sorted(self.states.items()) if st.online]
        if not online:
            lines.append("(暂无在线模块, 请连接后点击\"扫描在线模块\")")
        for a, st in online:
            mode = "---" if st.parallel is None else ("并机" if st.parallel else "单机")
            lines.append("0x%02X (%2d#):  直流 %s V / %s A    母线 %s V    %s    %s"
                         % (a, a, fmt(st.v_dc), fmt(st.i_dc), fmt(st.v_bus),
                            mode, "、".join(st.faults) if st.faults else "无故障"))
        st = self.states[self.current_module]
        lines.append("")
        lines.append("=== 当前模块 0x%02X (%d#) ===" % (self.current_module, self.current_module))
        lines.append("在线状态 : %s" % ("在线" if st.online else "离线"))
        lines.append("直流电压 : %s V" % fmt(st.v_dc))
        lines.append("直流电流 : %s A  (放电为负值)" % fmt(st.i_dc))
        lines.append("母线电压 : %s V" % fmt(st.v_bus))
        lines.append("工作模式 : %s" % ("---" if st.parallel is None
                                       else ("并机(默认1#为主机)" if st.parallel else "单机")))
        lines.append("本机指令 : 设定 %s V / %s A, 电源 %s"
                     % (fmt(st.set_v), fmt(st.set_i), "开机" if st.power else "关机"))
        lines.append("故障     : %s" % ("、".join(st.faults) if st.faults else "无"))
        self.txt_info.setPlainText("\n".join(lines))

    # ================= 日志 =================
    def _log_can(self, direction, can_id, data, note, color):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        hexstr = " ".join("%02X" % b for b in data)
        line = '<span style="color:%s">%s %s %08X  %s  %s</span>' % (
            color, ts, direction, can_id, hexstr, note)
        self.txt_log.appendHtml(line)
        if self.chk_autoscroll.isChecked():
            sb = self.txt_log.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _log_sys(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.appendHtml('<span style="color:#6B7280">[%s] [系统] %s</span>' % (ts, msg))
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", os.path.join(APP_DIR, "can_log_%s.txt"
                                           % datetime.now().strftime("%Y%m%d_%H%M%S")),
            "文本文件 (*.txt);;所有文件 (*.*)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.txt_log.toPlainText())
                self._log_sys("日志已保存: %s" % path)
            except Exception as e:
                QMessageBox.warning(self, "保存失败", str(e))

    def _warn_not_connected(self):
        QMessageBox.warning(self, "未连接", "请先连接 UT-6502 再执行该操作。")

    # ================= 关闭 =================
    def closeEvent(self, event):
        try:
            self._gather_config()
            self._save_config()
            self.life_timer.stop()
            self.offline_timer.stop()
            try:
                self.client.disconnect()
            except Exception:
                pass
            super().closeEvent(event)
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass


