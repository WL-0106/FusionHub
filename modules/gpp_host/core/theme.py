"""全局面板主题：按钮配色 + 明显按下反馈 + 现代化输入控件。

统一通过 QApplication.setStyleSheet 应用；按钮用 role / kind 动态属性选色，
避免各处零散 setStyleSheet 覆盖。下拉箭头为 assets/ 下 PNG，
开发态从项目目录读取，打包态从 PyInstaller 临时目录(_MEIPASS)读取。
"""
from __future__ import annotations

import os
import sys


def _asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name).replace("\\", "/")


APP_QSS = """
/* ---------- 基础按钮：白底描边 + 按下下压 ---------- */
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 7px;
    padding: 6px 14px;
    color: #374151;
    font-weight: 600;
}
QPushButton:hover { background: #F3F4F6; border-color: #9CA3AF; }
QPushButton:pressed {
    background: #E5E7EB;
    border-color: #6B7280;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton:disabled {
    background: #F9FAFB;
    color: #9CA3AF;
    border-color: #E5E7EB;
}
QPushButton:focus { outline: none; }

/* ---------- 蓝色主按钮：连接 / 描边小按钮 ---------- */
QPushButton[role="accent"] {
    background: #3B82F6;
    color: #FFFFFF;
    border: none;
    font-weight: 700;
}
QPushButton[role="accent"]:hover { background: #2563EB; }
QPushButton[role="accent"]:pressed {
    background: #1D4ED8;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[role="accent"]:disabled {
    background: #A5C8FF;
    color: #EFF6FF;
}

QPushButton[role="outline"] {
    background: #EFF6FF;
    border: 1px solid #93C5FD;
    color: #2563EB;
}
QPushButton[role="outline"]:hover {
    background: #DBEAFE;
    border-color: #60A5FA;
}
QPushButton[role="outline"]:pressed {
    background: #BFDBFE;
    border-color: #3B82F6;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[role="outline"]:disabled {
    background: #F8FAFC;
    color: #93C5FD;
    border-color: #E2E8F0;
}

/* ---------- 绿色：全部开启 ---------- */
QPushButton[role="ok"] {
    background: #22C55E;
    color: #FFFFFF;
    border: none;
    font-weight: 700;
}
QPushButton[role="ok"]:hover { background: #16A34A; }
QPushButton[role="ok"]:pressed {
    background: #15803D;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[role="ok"]:disabled {
    background: #BBF7D0;
    color: #F0FDF4;
}

/* ---------- 红色：全部关闭 ---------- */
QPushButton[role="danger"] {
    background: #EF4444;
    color: #FFFFFF;
    border: none;
    font-weight: 700;
}
QPushButton[role="danger"]:hover { background: #DC2626; }
QPushButton[role="danger"]:pressed {
    background: #B91C1C;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[role="danger"]:disabled {
    background: #FECACA;
    color: #FEF2F2;
}

/* ---------- 记录：绿=开始，红=停止 ---------- */
QPushButton[role="record"] {
    background: #22C55E;
    color: #FFFFFF;
    border: none;
    font-weight: 700;
}
QPushButton[role="record"]:hover { background: #16A34A; }
QPushButton[role="record"]:pressed {
    background: #15803D;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[role="record"]:checked { background: #EF4444; }
QPushButton[role="record"]:checked:hover { background: #DC2626; }
QPushButton[role="record"]:checked:pressed {
    background: #B91C1C;
    padding-top: 8px;
    padding-bottom: 4px;
}

/* ---------- 通道输出开关：灰=关，绿=开 ---------- */
QPushButton[role="output"] {
    background: #F3F4F6;
    color: #6B7280;
    border: 1px solid #D1D5DB;
    border-radius: 7px;
    padding: 5px 14px;
    font-weight: 700;
}
QPushButton[role="output"]:hover {
    background: #E5E7EB;
    border-color: #9CA3AF;
}
QPushButton[role="output"]:pressed {
    background: #D1D5DB;
    padding-top: 7px;
    padding-bottom: 3px;
}
QPushButton[role="output"]:checked {
    background: #22C55E;
    color: #FFFFFF;
    border: 1px solid #16A34A;
}
QPushButton[role="output"]:checked:hover {
    background: #16A34A;
    border-color: #15803D;
}
QPushButton[role="output"]:checked:pressed {
    background: #15803D;
    padding-top: 7px;
    padding-bottom: 3px;
}
QPushButton[role="output"]:disabled {
    background: #F9FAFB;
    color: #9CA3AF;
    border: 1px solid #E5E7EB;
}
QPushButton[role="output"]:disabled:checked {
    background: #D1FAE5;
    color: #6EE7B7;
    border: 1px solid #A7F3D0;
}

/* ---------- 暂停曲线：勾选后变琥珀色 ---------- */
QPushButton[role="hold"]:checked {
    background: #F59E0B;
    color: #FFFFFF;
    border: none;
}
QPushButton[role="hold"]:checked:hover { background: #D97706; }
QPushButton[role="hold"]:checked:pressed {
    background: #B45309;
    padding-top: 8px;
    padding-bottom: 4px;
}

/* ---------- 曲线系列按钮：电压琥珀 / 电流蓝 / 功率紫 ---------- */
QPushButton[kind="v"] {
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    color: #B45309;
    border-radius: 7px;
}
QPushButton[kind="v"]:hover { background: #FEF3C7; border-color: #FCD34D; }
QPushButton[kind="v"]:pressed {
    background: #FDE68A;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[kind="v"]:checked {
    background: #F59E0B;
    border: 1px solid #D97706;
    color: #FFFFFF;
}

QPushButton[kind="i"] {
    background: #EFF6FF;
    border: 1px solid #BFDBFE;
    color: #1D4ED8;
    border-radius: 7px;
}
QPushButton[kind="i"]:hover { background: #DBEAFE; border-color: #93C5FD; }
QPushButton[kind="i"]:pressed {
    background: #BFDBFE;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[kind="i"]:checked {
    background: #3B82F6;
    border: 1px solid #2563EB;
    color: #FFFFFF;
}

QPushButton[kind="p"] {
    background: #F5F3FF;
    border: 1px solid #DDD6FE;
    color: #6D28D9;
    border-radius: 7px;
}
QPushButton[kind="p"]:hover { background: #EDE9FE; border-color: #C4B5FD; }
QPushButton[kind="p"]:pressed {
    background: #DDD6FE;
    padding-top: 8px;
    padding-bottom: 4px;
}
QPushButton[kind="p"]:checked {
    background: #8B5CF6;
    border: 1px solid #7C3AED;
    color: #FFFFFF;
}

/* ---------- 输入控件 ---------- */
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 6px;
    padding: 3px 4px;
    color: #1F2937;
}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover, QLineEdit:hover {
    border-color: #60A5FA;
}
QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {
    border-color: #3B82F6;
}
QComboBox:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled, QLineEdit:disabled {
    background: #F9FAFB;
    color: #9CA3AF;
    border-color: #E5E7EB;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
    subcontrol-origin: padding;
    subcontrol-position: right center;
}
/* 下拉箭头：PNG 资源随包分发。
   注意(踩坑记录): 只保留这一条 ::down-arrow 规则——
   若再加 :hover/:disabled 伪状态的 down-arrow 变体, Qt 会在框体中心
   额外画出一支“幽灵箭头”(双重绘制), 实测已复现, 切勿添加。 */
QComboBox::down-arrow {
    image: url("@ARROW@");
    width: 14px;
    height: 9px;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    selection-background-color: #DBEAFE;
    selection-color: #111827;
    border-radius: 6px;
}

/* ---------- 复选框：圆角彩色指示块 ---------- */
QCheckBox { spacing: 6px; color: #374151; }
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1.5px solid #94A3B8;
    background: #FFFFFF;
}
QCheckBox::indicator:hover {
    border-color: #60A5FA;
    background: #EFF6FF;
}
QCheckBox::indicator:checked {
    background: #3B82F6;
    border: 1.5px solid #2563EB;
}
QCheckBox::indicator:checked:hover {
    background: #2563EB;
}
QCheckBox::indicator:disabled {
    background: #F3F4F6;
    border-color: #E5E7EB;
}
QCheckBox:disabled { color: #9CA3AF; }

/* ---------- 分组框(SCPI 日志等；通道卡片自带内联样式不受影响) ---------- */
QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: #374151;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}

/* ---------- 滚动条：细圆角 ---------- */
QScrollBar:vertical {
    background: #F3F4F6;
    width: 11px;
    border-radius: 5px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #CBD5E1;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar:horizontal {
    background: #F3F4F6;
    height: 11px;
    border-radius: 5px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #CBD5E1;
    border-radius: 5px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background: #94A3B8; }
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
"""

# 占位符替换成真实箭头路径（开发态与 onefile 打包态均可解析）
APP_QSS = (
    APP_QSS
    .replace("@ARROW@", _asset("arrow_down.png"))
    .replace("@ARROW_HOVER@", _asset("arrow_hover.png"))
    .replace("@ARROW_DISABLED@", _asset("arrow_disabled.png"))
)


def set_role(widget, role: str) -> None:
    """切换按钮 role 并强制刷新样式（如 连接↔断开 配色变化）。"""
    widget.setProperty("role", role)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
