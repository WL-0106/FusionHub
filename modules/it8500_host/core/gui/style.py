"""界面主题: 亮色仪器风格 QSS。

方向: 参考现代测量仪器上位机 (Keysight/NI 亮色风) ——
冷灰画布 + 白色卡片 + 细描边, 橙色强调 (连接/主操作),
读数用高对比绿/蓝/琥珀, 摒弃初版的暗黑风。
"""
import os
import sys


def _asset(name: str) -> str:
    """资源路径解析：开发态从模块目录读取，打包态从 PyInstaller 临时目录(_MEIPASS)读取。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", name).replace("\\", "/")


APP_QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 9pt; }
QMainWindow, QDialog { background: #eef1f7; }
QWidget { color: #222b3a; }

/* ---------- 顶部连接栏 ---------- */
#ConnectBar { background: #ffffff; border-bottom: 1px solid #d5dbe6; }
#ConnectBar QLabel { color: #5c6b80; background: transparent; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #ffffff; border: 1px solid #c4cddb; border-radius: 4px;
    padding: 3px 6px; color: #222b3a; min-height: 20px;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover { border-color: #8fa1ba; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus { border-color: #e8721f; }
QComboBox::drop-down { border: none; width: 18px; subcontrol-origin: padding; subcontrol-position: right center; }
/* 下拉箭头：PNG 资源（橙色适配主题）。只保留单条规则，勿加伪状态变体防幽灵箭头。 */
QComboBox::down-arrow {
    image: url("@ARROW@");
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background: #ffffff; border: 1px solid #c4cddb; selection-background-color: #fde9d7;
    color: #222b3a;
}
QToolButton, QPushButton {
    background: #ffffff; border: 1px solid #c4cddb; border-radius: 4px;
    padding: 4px 14px; color: #222b3a;
}
QToolButton:hover, QPushButton:hover { background: #f3f6fb; border-color: #8fa1ba; }
QToolButton:pressed, QPushButton:pressed { background: #e6ebf3; }
QPushButton:disabled, QToolButton:disabled { color: #9aa4b5; background: #f0f2f6; }

QPushButton#ConnectBtn { background: #e8721f; border: 1px solid #d06010; color: #ffffff; font-weight: 600; }
QPushButton#ConnectBtn:hover { background: #f07d2a; }
QPushButton#ConnectBtn[connected="true"] { background: #ffffff; border-color: #e8721f; color: #c85f12; }

QPushButton#OutputBtn { font-size: 11pt; font-weight: 700; padding: 8px 18px; }
QPushButton#OutputBtn[state="off"] { background: #ffffff; border: 1px solid #c4cddb; color: #5c6b80; }
QPushButton#OutputBtn[state="on"] { background: #d64545; border: 1px solid #c0392b; color: #ffffff; }

QPushButton#RemoteBtn[remote="true"] { background: #dff3e8; border: 1px solid #4cab80; color: #0f7a50; }
QPushButton#RemoteBtn[remote="false"] { background: #ffffff; border: 1px solid #c4cddb; color: #5c6b80; }

QPushButton#DangerBtn { background: #fdecec; border: 1px solid #e08b8b; color: #c0392b; }
QPushButton#DangerBtn:hover { background: #fadcdc; }

/* ---------- 选项卡 ---------- */
QTabWidget::pane { border: 1px solid #d5dbe6; background: #ffffff; border-radius: 6px; top: -1px; }
QTabBar::tab {
    background: #e4e9f1; border: 1px solid #d5dbe6; border-bottom: none;
    padding: 7px 18px; margin-right: 2px; color: #5c6b80;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #ffffff; color: #c85f12; font-weight: 600; }
QTabBar::tab:hover:!selected { color: #222b3a; }

/* ---------- 分组卡片 ---------- */
QGroupBox {
    background: #ffffff; border: 1px solid #d5dbe6; border-radius: 6px;
    margin-top: 12px; padding: 14px 10px 10px 10px; font-weight: 600; color: #3a4557;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; top: 2px; padding: 0 6px; color: #c85f12; }

/* ---------- 大字读数卡 ---------- */
#ReadCard {
    background: #ffffff; border: 1px solid #d5dbe6; border-radius: 8px;
}
#ReadValue { font-family: "Consolas", monospace; font-size: 34px; font-weight: 700;
             background: transparent; border: none; }
#ReadValueU { color: #0d9b6c; }
#ReadValueI { color: #1f7ae0; }
#ReadValueP { color: #c98a00; }
#ReadLabel { color: #5c6b80; font-size: 10pt; background: transparent; border: none; }
#ReadUnit  { color: #5c6b80; font-size: 12pt; background: transparent; border: none; }

/* ---------- 状态指示灯 ---------- */
#StatusDot { font-size: 10pt; }
#StatusDot[on="true"] { color: #0d9b6c; }
#StatusDot[on="false"] { color: #9aa4b5; }

/* ---------- 状态字芯片 ---------- */
QLabel#FlagChip {
    background: #f0f3f8; border: 1px solid #c9d2e0; border-radius: 9px;
    padding: 2px 9px; color: #7a8699; font-family: "Consolas", monospace;
    font-size: 8.5pt; margin: 2px;
}
QLabel#FlagChip[on="true"] { background: #d8f0e4; border-color: #4cab80; color: #0f7a50; }
QLabel#FlagChip[fault="true"] { background: #fdecec; border-color: #e08b8b; color: #c0392b; font-weight: 700; }
QLabel#FlagChip[fault="true"][on="true"] { background: #f9c9c9; border-color: #d64545; color: #a3211c; }

/* ---------- 表格 ---------- */
QTableWidget, QListWidget, QPlainTextEdit {
    background: #ffffff; border: 1px solid #d5dbe6; border-radius: 4px;
    gridline-color: #e3e8f0; color: #222b3a; selection-background-color: #fde9d7;
}
QHeaderView::section {
    background: #eef1f7; color: #5c6b80; border: none;
    border-bottom: 1px solid #d5dbe6; padding: 5px 8px; font-weight: 600;
}
QTableWidget::item { padding: 2px; }

/* ---------- 滚动条 / 其它 ---------- */
QScrollBar:vertical { background: #eef1f7; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #c4cddb; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal { background: #eef1f7; height: 10px; }
QScrollBar::handle:horizontal { background: #c4cddb; border-radius: 4px; min-width: 24px; }

QStatusBar { background: #ffffff; color: #5c6b80; border-top: 1px solid #d5dbe6; }
QCheckBox { color: #222b3a; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #c4cddb; border-radius: 3px; background: #ffffff; }
QCheckBox::indicator:checked { background: #e8721f; border-color: #e8721f; }
QLabel[role="hint"] { color: #7a8699; }
QLabel[role="warn"] { color: #c85f12; font-size: 8.5pt; }
QLabel[role="value"] { font-family: "Consolas", monospace; color: #222b3a; }
"""


def apply_theme(app) -> None:
    app.setStyleSheet(APP_QSS.replace("@ARROW@", _asset("arrow_down.png")))
