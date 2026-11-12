"""界面主题：还原截图配色（浅色工具栏/右侧面板 + 深色监控区与日志区）。"""

# 调色板
BG = "#f0f0f0"
PANEL = "#ececec"
BORDER = "#c9c9c9"
TEXT = "#202020"
SUBTEXT = "#5a6672"

DARK = "#3d4b5a"          # 监控区背景
DARK_BAR = "#46566a"      # 监控区标题条
DARK_ROW = "#33414f"      # 表格行
DARK_ROW_ALT = "#2d3a47"
DARK_LOG = "#2b3846"      # 日志区
HEADER_BG = "#b9b9b9"
HEADER_TEXT = "#000000"

BLUE = "#2f80ed"
BLUE_H = "#3d8bf7"
BLUE_P = "#2568c4"
RED = "#e2574c"
RED_H = "#ec6a60"
GREEN = "#43b04a"
GREEN_H = "#4fc257"
ORANGE = "#f0a020"
ORANGE_H = "#f5b03a"

APP_QSS = """
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