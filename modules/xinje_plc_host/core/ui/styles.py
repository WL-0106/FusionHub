# -*- coding: utf-8 -*-
"""工业风界面样式。"""

APP_STYLE = """
/* ===== 全局 ===== */
* {
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
}
QWidget {
    background: #F4F6F9;
    color: #1C2333;
}
QMainWindow, QDialog {
    background: #EEF1F6;
}

/* ===== 标题栏/侧边 ===== */
#SideBar {
    background: #1B2434;
    color: #D7DEE9;
}
#SideBar QLabel {
    color: #D7DEE9;
    background: transparent;
}
#SideBar QPushButton {
    background: transparent;
    color: #C5CFDE;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
}
#SideBar QPushButton:hover {
    background: #2A3649;
    color: #FFFFFF;
}
#SideBar QPushButton:checked {
    background: #2F6FED;
    color: #FFFFFF;
    border: 1px solid #2F6FED;
}
#AppTitle {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 600;
    background: transparent;
}
#AppSub {
    color: #8B98AC;
    font-size: 11px;
    background: transparent;
}

/* ===== 卡片 ===== */
QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #E2E7EF;
    border-radius: 10px;
}
QFrame#CardTitle {
    background: transparent;
    border: none;
}
QLabel#CardHeading {
    font-size: 14px;
    font-weight: 600;
    color: #1C2333;
    background: transparent;
}
QLabel#CardSub {
    font-size: 11px;
    color: #7A8699;
    background: transparent;
}

/* ===== 按钮 ===== */
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D0D7E2;
    border-radius: 6px;
    padding: 7px 14px;
    color: #1C2333;
}
QPushButton:hover {
    background: #F0F4FA;
    border-color: #B7C2D3;
}
QPushButton:pressed {
    background: #E4EAF3;
}
QPushButton:disabled {
    color: #A0AAB8;
    background: #F5F7FA;
    border-color: #E2E7EF;
}
QPushButton#Primary {
    background: #2F6FED;
    border: 1px solid #2F6FED;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#Primary:hover {
    background: #2558C4;
}
QPushButton#Primary:pressed {
    background: #1E4AA8;
}
QPushButton#Primary:disabled {
    background: #9BB6F0;
    border-color: #9BB6F0;
    color: #EEF3FF;
}
QPushButton#Danger {
    background: #E24B4B;
    border: 1px solid #E24B4B;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#Danger:hover {
    background: #C93A3A;
}
QPushButton#Success {
    background: #1F9D63;
    border: 1px solid #1F9D63;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#Success:hover {
    background: #188A55;
}

/* ===== 输入 ===== */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    background: #FFFFFF;
    border: 1px solid #D0D7E2;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #2F6FED;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2F6FED;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #6B778A;
    margin-right: 8px;
}

/* ===== 表格 ===== */
QTableWidget, QTableView {
    background: #FFFFFF;
    border: 1px solid #E2E7EF;
    border-radius: 8px;
    gridline-color: #EEF1F6;
    selection-background-color: #E8F0FE;
    selection-color: #1C2333;
}
QHeaderView::section {
    background: #F7F9FC;
    color: #5A677A;
    border: none;
    border-bottom: 1px solid #E2E7EF;
    border-right: 1px solid #EEF1F6;
    padding: 8px 10px;
    font-weight: 600;
    font-size: 12px;
}
QTableWidget::item {
    padding: 4px 8px;
    border-bottom: 1px solid #F2F5F9;
}
QTableWidget::item:selected {
    background: #E8F0FE;
}

/* ===== Tab ===== */
QTabWidget::pane {
    border: 1px solid #E2E7EF;
    border-radius: 8px;
    background: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background: #E9EEF5;
    color: #5A677A;
    padding: 8px 18px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border: 1px solid #E2E7EF;
    border-bottom: none;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #1C2333;
    font-weight: 600;
    border: 1px solid #E2E7EF;
    border-bottom: 1px solid #FFFFFF;
}
QTabBar::tab:hover:!selected {
    background: #F2F6FC;
}

/* ===== 状态栏 ===== */
QStatusBar {
    background: #1B2434;
    color: #AAB6C7;
    font-size: 12px;
}
QStatusBar QLabel {
    color: #AAB6C7;
    background: transparent;
    padding: 0 8px;
}

/* ===== 分组 ===== */
QGroupBox {
    border: 1px solid #E2E7EF;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    background: #FFFFFF;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #2F6FED;
}

/* ===== 滚动条 ===== */
QScrollBar:vertical {
    width: 10px;
    background: #F0F3F8;
}
QScrollBar::handle:vertical {
    background: #C5CFDD;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #A8B4C6;
}
QScrollBar:horizontal {
    height: 10px;
    background: #F0F3F8;
}
QScrollBar::handle:horizontal {
    background: #C5CFDD;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
}

/* ===== 指示灯 ===== */
#LampOn {
    background: #22C55E;
    border-radius: 8px;
}
#LampOff {
    background: #CBD5E1;
    border-radius: 8px;
}
#LampWarn {
    background: #F59E0B;
    border-radius: 8px;
}
#LampErr {
    background: #EF4444;
    border-radius: 8px;
}

/* ===== 提示 ===== */
QToolTip {
    background: #1B2434;
    color: #FFFFFF;
    border: none;
    padding: 6px 10px;
    border-radius: 4px;
}
"""
