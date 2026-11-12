# -*- coding: utf-8 -*-
"""全局视觉规范（单一事实源）：浅灰紫底 + 白色圆角卡片 + 靛蓝主色，禁止默认灰系统主题。"""
import os
import sys

# 下拉箭头 PNG 资源路径解析：开发态从项目目录读取，打包态从 PyInstaller 临时目录(_MEIPASS)读取。
def _asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets", name).replace("\\", "/")

COLORS = {
    "bg": "#F3F2FA",          # 浅灰紫底
    "card": "#FFFFFF",
    "card_border": "#E9E7F5",
    "primary": "#4F46E5",     # 靛蓝主色
    "primary_hover": "#635BEF",
    "primary_press": "#3B34C4",
    "primary_soft": "#EEF0FF",
    "text": "#23263A",
    "text_sub": "#7A7B93",
    "green": "#10B981",
    "red": "#E11D48",
    "amber": "#F59E0B",
    "cyan": "#22D3EE",
    "violet": "#A78BFA",
    "wave_bg": "#12142A",     # 示波屏深色底
    "wave_grid": "#262B45",
}

QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; color: %(text)s; }
QMainWindow, QWidget#RootBg { background: %(bg)s; }

/* ---------- 卡片 ---------- */
QFrame#Card, QWidget#Card {
    background: %(card)s; border: 1px solid %(card_border)s; border-radius: 14px;
}
QLabel#CardTitle { font-size: 15px; font-weight: 700; color: #2A2550; background: transparent; border: none; }
QLabel#CardSub { font-size: 11px; color: %(text_sub)s; background: transparent; border: none; }
QLabel#H1 { font-size: 20px; font-weight: 800; color: #2A2550; }
QLabel#H2 { font-size: 15px; font-weight: 700; color: #2A2550; }
QLabel#BigValue { font-size: 26px; font-weight: 800; }
QLabel#Muted { color: %(text_sub)s; }
QLabel#Banner { background: #FFF4F5; border: 1px solid #FFD3D8; border-radius: 10px;
                padding: 8px 12px; color: #B01030; }

/* ---------- 侧边目录 ---------- */
QFrame#Sidebar { background: %(card)s; border: 1px solid %(card_border)s; border-radius: 14px; }
QTreeWidget#NavTree {
    background: transparent; border: none; outline: none;
    font-size: 13px;
}
QTreeWidget#NavTree::item { height: 34px; border-radius: 9px; padding-left: 4px; margin: 2px 6px; }
QTreeWidget#NavTree::item:hover { background: %(primary_soft)s; }
QTreeWidget#NavTree::item:selected { background: %(primary)s; color: #FFFFFF; }
QLineEdit#SearchBox {
    background: #F7F7FC; border: 2px solid #E4E2F3; border-radius: 10px;
    padding: 7px 12px 7px 32px; selection-background-color: %(primary)s;
}
QLineEdit#SearchBox:focus { border-color: %(primary)s; background: #FFFFFF; }
QLineEdit {
    background: #FFFFFF; border: 2px solid #E4E2F3; border-radius: 9px;
    padding: 5px 10px; selection-background-color: %(primary)s;
}
QLineEdit:focus { border-color: %(primary)s; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border-color: %(primary)s;
}

/* ---------- 按钮（按下态必须有明显变化） ---------- */
QPushButton {
    background: #FFFFFF; border: 2px solid #DAD7F0; border-radius: 10px;
    padding: 7px 16px; font-weight: 600; color: %(primary)s;
}
QPushButton:hover { background: %(primary_soft)s; border-color: %(primary)s; }
QPushButton:pressed { background: #D9DCFF; border-color: %(primary_press)s; color: #2A249E; padding-top: 9px; padding-bottom: 5px; }
QPushButton:disabled { background: #F2F2F7; border-color: #E2E2EE; color: #B3B3C3; }
QPushButton#Primary { background: %(primary)s; border: 2px solid %(primary)s; color: #FFFFFF; }
QPushButton#Primary:hover { background: %(primary_hover)s; border-color: %(primary_hover)s; }
QPushButton#Primary:pressed { background: %(primary_press)s; border-color: #2A249E; padding-top: 9px; padding-bottom: 5px; }
QPushButton#Ghost { background: transparent; border: 2px solid transparent; color: %(text_sub)s; }
QPushButton#Ghost:hover { background: %(primary_soft)s; color: %(primary)s; }
QPushButton#Ghost:pressed { background: #D9DCFF; color: #2A249E; }
QPushButton#Danger {
    background: #FFF1F2; border: 2px solid #FDA4AF; color: #D20A34; font-weight: 700;
}
QPushButton#Danger:hover { background: #FFE4E6; border-color: #E11D48; }
QPushButton#Danger:pressed { background: #FFD3D8; border-color: #A5082A; padding-top: 9px; padding-bottom: 5px; }

/* 输出按钮：待机/开启两态 + 按下态 */
QPushButton[state="idle"] {
    background: #FFF1F2; border: 2px solid #FDA4AF; color: #D20A34; font-weight: 700;
}
QPushButton[state="idle"]:hover { background: #FFE4E6; border-color: #E11D48; }
QPushButton[state="idle"]:pressed { background: #FFD3D8; border-color: #A5082A; padding-top: 9px; padding-bottom: 5px; }
QPushButton[state="on"] {
    background: #E11D48; border: 2px solid #A5082A; color: #FFFFFF; font-weight: 700;
}
QPushButton[state="on"]:hover { background: #F43F5E; }
QPushButton[state="on"]:pressed { background: #A5082A; border-color: #7A0520; padding-top: 9px; padding-bottom: 5px; }

QPushButton[state="off_ok"] { background: #ECFDF5; border: 2px solid #A7F3D0; color: #047857; font-weight: 700; }
QPushButton[state="off_ok"]:pressed { background: #C9F2E0; border-color: #047857; padding-top: 9px; padding-bottom: 5px; }
QPushButton[state="on_ok"] { background: #10B981; border: 2px solid #047857; color: #FFFFFF; font-weight: 700; }
QPushButton[state="on_ok"]:pressed { background: #047857; border-color: #034F35; padding-top: 9px; padding-bottom: 5px; }

/* ---------- 标签页 ---------- */
QTabWidget::pane { border: 1px solid %(card_border)s; border-radius: 12px; background: %(card)s; top: -1px; }
QTabBar::tab {
    background: transparent; border: none; padding: 10px 22px; margin-right: 6px;
    font-size: 14px; font-weight: 700; color: %(text_sub)s; border-radius: 10px 10px 0 0;
}
QTabBar::tab:hover { color: %(primary)s; background: %(primary_soft)s; }
QTabBar::tab:selected { color: #FFFFFF; background: %(primary)s; }

/* ---------- 表格 ---------- */
QTableWidget, QTableView {
    background: #FFFFFF; border: 1px solid %(card_border)s;
    gridline-color: #F0EFF8; alternate-background-color: #FAFAFE;
}
QHeaderView::section {
    background: #F5F4FC; border: none;
    border-bottom: 2px solid #E4E2F3; border-right: 1px solid #E4E2F3;
    padding: 8px 10px; font-weight: 700; color: #4B4A73;
}
QHeaderView::section:hover { background: #EDEBFA; }
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background: %(primary_soft)s; color: %(text)s; }

/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #D6D3EE; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(primary)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #D6D3EE; border-radius: 5px; min-width: 30px; }

/* ---------- 顶部/杂项 ---------- */
QFrame#Header { background: %(card)s; border: 1px solid %(card_border)s; border-radius: 14px; }
QComboBox {
    background: #FFFFFF; border: 2px solid #E4E2F3; border-radius: 9px;
    padding: 5px 10px; min-width: 90px;
}
QComboBox:hover { border-color: %(primary)s; }
QComboBox::drop-down {
    border: none; width: 22px;
    subcontrol-origin: padding;
    subcontrol-position: right center;
}
/* 下拉箭头：PNG 资源（assets/arrow_down.png，靛蓝主色适配主题）。
   注意(踩坑记录): 只保留这一条 ::down-arrow 规则——若再加 :hover/:disabled 等
   伪状态变体, Qt 会在框体中心额外画出“幽灵箭头”(双重绘制), 切勿添加。 */
QComboBox::down-arrow {
    image: url("@ARROW@");
    width: 14px;
    height: 14px;
}
QComboBox QAbstractItemView {
    background: #FFFFFF; border: 1px solid %(card_border)s; border-radius: 8px;
    selection-background-color: %(primary_soft)s; selection-color: %(text)s;
}
QDoubleSpinBox, QSpinBox {
    background: #FFFFFF; border: 2px solid #E4E2F3; border-radius: 9px; padding: 5px 8px;
}
QDoubleSpinBox:focus, QSpinBox:focus { border-color: %(primary)s; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 5px; border: 2px solid #C9C6E4; background: #FFFFFF; }
QCheckBox::indicator:checked { background: %(primary)s; border-color: %(primary)s; }
QSplitter::handle { background: transparent; width: 10px; }
QSplitter::handle:vertical {
    height: 14px;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 %(bg)s, stop:0.45 #D9D6EE, stop:0.55 #D9D6EE, stop:1 %(bg)s);
}
QSplitter::handle:vertical:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 %(bg)s, stop:0.45 %(primary)s, stop:0.55 %(primary)s, stop:1 %(bg)s);
}
QSplitter::handle:horizontal {
    width: 14px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 %(bg)s, stop:0.45 #D9D6EE, stop:0.55 #D9D6EE, stop:1 %(bg)s);
}
QSplitter::handle:horizontal:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 %(bg)s, stop:0.45 %(primary)s, stop:0.55 %(primary)s, stop:1 %(bg)s);
}
QPushButton#SideToggle {
    background: %(primary)s; color: #FFFFFF; border: none; border-radius: 10px;
    font-size: 17px; font-weight: 800; padding: 0;
}
QPushButton#SideToggle:hover { background: #6366F1; }
QPushButton#SideToggle:pressed { background: #4338CA; }
QStatusBar {
    background: %(card)s; border-top: 1px solid %(card_border)s;
    color: %(text_sub)s; font-size: 12px;
}
QStatusBar::item { border: none; }
QToolTip {
    background: #2A2550; color: #FFFFFF; border: none; padding: 6px 10px; border-radius: 8px;
}

/* ---------- 通用控件（嵌入的模块上位机页也统一吃这套风格） ---------- */
QGroupBox {
    background: %(card)s; border: 1px solid %(card_border)s; border-radius: 12px;
    margin-top: 14px; padding: 10px 12px 12px 12px; font-weight: 700; color: #2A2550;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: %(primary)s; }
QTextEdit, QPlainTextEdit {
    background: #FFFFFF; border: 1px solid %(card_border)s; border-radius: 10px;
    padding: 6px 8px; selection-background-color: %(primary_soft)s;
}
QListWidget, QTreeWidget {
    background: #FFFFFF; border: 1px solid %(card_border)s; border-radius: 10px; outline: none;
}
QListWidget::item, QTreeWidget::item { padding: 4px 6px; border-radius: 6px; }
QListWidget::item:selected, QTreeWidget::item:selected { background: %(primary_soft)s; color: %(text)s; }
QRadioButton { spacing: 8px; }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 2px solid #C9C6E4; background: #FFFFFF; }
QRadioButton::indicator:checked { border: 5px solid %(primary)s; background: #FFFFFF; }
QProgressBar {
    background: #ECEBF7; border: none; border-radius: 8px; height: 14px;
    text-align: center; color: #FFFFFF; font-size: 11px;
}
QProgressBar::chunk { background: %(primary)s; border-radius: 8px; }
QToolBar { background: transparent; border: none; spacing: 6px; }
QMenuBar { background: transparent; }
QMenuBar::item:selected { background: %(primary_soft)s; border-radius: 8px; }
QMenu { background: %(card)s; border: 1px solid %(card_border)s; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 6px 22px 6px 14px; border-radius: 6px; }
QMenu::item:selected { background: %(primary_soft)s; }
QSlider::groove:horizontal { height: 6px; background: #ECEBF7; border-radius: 3px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: %(primary)s; }
QLabel#ModulePage { background: transparent; }
""" % COLORS
# 注入下拉箭头 PNG 的绝对路径（开发态/打包态均可正确解析）
QSS = QSS.replace("@ARROW@", _asset("arrow_down.png"))


def apply_theme(app) -> None:
    app.setStyleSheet(QSS)


# 嵌入页紧凑变体：融合的模块上位机控件密集且多为固定小尺寸，
# 统一用小内边距/细边框，防止按钮、电压电流输入框被撑大裁切而“缩小看不见”。
QSS_EMBED = QSS + """
QPushButton { padding: 2px 10px; border-width: 1px; border-radius: 8px; }
QPushButton#Primary, QPushButton#Danger { padding: 2px 10px; border-width: 1px; }
QTableWidget QPushButton, QTableView QPushButton { padding: 1px 6px; font-size: 11px; border-radius: 6px; }
QSpinBox, QDoubleSpinBox, QComboBox { padding: 1px 4px; border-width: 1px; border-radius: 7px; }
QLineEdit { padding: 2px 6px; border-width: 1px; border-radius: 7px; }
QCheckBox::indicator { width: 14px; height: 14px; }
QRadioButton::indicator { width: 13px; height: 13px; }
QTabBar::tab { padding: 5px 14px; margin-right: 2px; font-size: 13px; }
QGroupBox { padding: 6px 8px 8px 8px; margin-top: 12px; }
QTableWidget, QTableView { font-size: 12px; }
"""
