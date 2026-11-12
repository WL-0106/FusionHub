# -*- coding: utf-8 -*-
"""主窗口：左侧导航 + 中央工作区 + 右侧(连接/日志)。

布局（用户要求）：
- 通讯连接：右侧顶部，始终可见
- 通讯日志：右侧下方，始终可见
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal as Signal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..app.config import AppConfig, load_config, save_config
from ..app.devices import DataType, parse_device
from ..app.modbus import ModbusConfig, list_serial_ports
from ..app.plc import PlcClient
from ..app.polling import AlarmEvent, AlarmRule, MonitorTag, PollingEngine
from .styles import APP_STYLE
from .trend_widget import TrendWidget


# ---------------------------------------------------------------------------
# 后台轮询
# ---------------------------------------------------------------------------

class PollWorker(QObject):
    tags_updated = Signal()
    alarm_raised = Signal(object)
    error = Signal(str)
    plc_state = Signal(bool)

    def __init__(self, engine: PollingEngine):
        super().__init__()
        self.engine = engine
        self.engine.on_tags_updated = self.tags_updated.emit
        self.engine.on_alarm = self.alarm_raised.emit
        self.engine.on_error = self.error.emit
        self.engine.on_plc_state = self.plc_state.emit


# ---------------------------------------------------------------------------
# I/O 点按钮
# ---------------------------------------------------------------------------

class BitButton(QPushButton):
    toggle_requested = Signal(str, bool)

    def __init__(self, name: str, writable: bool = True):
        super().__init__(name)
        self.device_name = name
        self.writable = writable
        # 按名称长度自适应，避免 Y10000 / X11777 被截断
        w = max(52, 16 + 8 * len(name))
        self.setFixedSize(w, 34)
        self.setToolTip(name)
        self._on = False
        self._pending = False
        self._update_style()
        if writable:
            self.clicked.connect(self._on_click)
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setToolTip(f"{name}（只读）")

    def set_state(self, on: bool) -> None:
        self._on = on
        self._pending = False
        self._update_style()

    def set_pending(self) -> None:
        self._pending = True
        self._update_style()

    def _update_style(self) -> None:
        if self._pending:
            self.setStyleSheet(
                "QPushButton { background:#F59E0B; color:#fff; border:1px solid #D97706;"
                " border-radius:6px; font-weight:700; font-size:11px; }"
            )
        elif self._on:
            self.setStyleSheet(
                "QPushButton { background:#22C55E; color:#fff; border:1px solid #16A34A;"
                " border-radius:6px; font-weight:700; font-size:11px; }"
                "QPushButton:hover { background:#16A34A; }"
            )
        else:
            base = "#E8EDF4" if self.writable else "#F4F6F9"
            self.setStyleSheet(
                f"QPushButton {{ background:{base}; color:#5A677A; border:1px solid #D0D7E2;"
                " border-radius:6px; font-size:11px; }"
                "QPushButton:hover { background:#D7E1F0; }"
            )

    def _on_click(self) -> None:
        self.set_pending()
        self.toggle_requested.emit(self.device_name, not self._on)


# ---------------------------------------------------------------------------
# 连接面板（右侧顶部，紧凑版）
# ---------------------------------------------------------------------------

class ConnectionPanel(QFrame):
    connect_clicked = Signal()
    disconnect_clicked = Signal()
    settings_changed = Signal()
    diagnose_clicked = Signal()
    clear_force_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self._build()
        self.btn_diag.clicked.connect(self.diagnose_clicked.emit)
        self.btn_clear_force.clicked.connect(self.clear_force_clicked.emit)

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # 状态行
        top = QHBoxLayout()
        title = QLabel("通讯连接")
        title.setObjectName("CardHeading")
        top.addWidget(title)
        top.addStretch()
        self.lamp = QLabel()
        self.lamp.setFixedSize(12, 12)
        self.lamp.setObjectName("LampOff")
        top.addWidget(self.lamp)
        self.st_lab = QLabel("未连接")
        self.st_lab.setStyleSheet("color:#7A8699; font-weight:600; font-size:12px;")
        top.addWidget(self.st_lab)
        lay.addLayout(top)

        # 模式
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("方式"))
        self.mode = QComboBox()
        self.mode.addItems(["RTU 串口", "TCP 以太网"])
        self.mode.currentIndexChanged.connect(self._mode_changed)
        row1.addWidget(self.mode, 1)
        row1.addWidget(QLabel("系列"))
        self.series = QComboBox()
        self.series.addItems([
            "XD1", "XD2", "XD3", "XD3E", "XD5", "XDC", "XDM", "XD5E", "XDME", "XDH",
            "XL1", "XL3", "XL3E", "XL5", "XL5E", "XL5N", "XL5H", "XLME", "XLH",
        ])
        self.series.setCurrentText("XD3")
        row1.addWidget(self.series, 1)
        lay.addLayout(row1)

        # RTU 参数
        self.rtu_box = QGroupBox("串口")
        rg = QGridLayout(self.rtu_box)
        rg.setContentsMargins(8, 6, 8, 8)
        rg.setHorizontalSpacing(8)
        rg.setVerticalSpacing(6)

        self.port = QComboBox()
        self.port.setEditable(False)
        self._refresh_ports()
        rg.addWidget(QLabel("端口"), 0, 0)
        rg.addWidget(self.port, 0, 1)

        self.baud = QComboBox()
        self.baud.addItems([
            "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200",
        ])
        self.baud.setCurrentText("9600")
        rg.addWidget(QLabel("波特率"), 0, 2)
        rg.addWidget(self.baud, 0, 3)

        self.parity = QComboBox()
        self.parity.addItems(["无 N", "偶 E", "奇 O"])
        rg.addWidget(QLabel("校验"), 1, 0)
        rg.addWidget(self.parity, 1, 1)

        self.stopbits = QComboBox()
        self.stopbits.addItems(["1", "2"])
        rg.addWidget(QLabel("停止"), 1, 2)
        rg.addWidget(self.stopbits, 1, 3)

        self.slave = QSpinBox()
        self.slave.setRange(1, 254)
        self.slave.setValue(1)
        rg.addWidget(QLabel("站号"), 2, 0)
        rg.addWidget(self.slave, 2, 1)

        btn_ref = QPushButton("刷新口")
        btn_ref.clicked.connect(self._refresh_ports)
        rg.addWidget(btn_ref, 2, 2, 1, 2)

        lay.addWidget(self.rtu_box)

        # TCP
        self.tcp_box = QGroupBox("以太网")
        tg = QGridLayout(self.tcp_box)
        tg.setContentsMargins(8, 6, 8, 8)
        tg.setHorizontalSpacing(8)
        self.host = QLineEdit("192.168.1.10")
        tg.addWidget(QLabel("IP"), 0, 0)
        tg.addWidget(self.host, 0, 1)
        self.tcp_port = QSpinBox()
        self.tcp_port.setRange(1, 65535)
        self.tcp_port.setValue(502)
        tg.addWidget(QLabel("端口"), 0, 2)
        tg.addWidget(self.tcp_port, 0, 3)
        self.tcp_slave = QSpinBox()
        self.tcp_slave.setRange(1, 254)
        self.tcp_slave.setValue(1)
        tg.addWidget(QLabel("站号"), 1, 0)
        tg.addWidget(self.tcp_slave, 1, 1)
        lay.addWidget(self.tcp_box)
        self.tcp_box.hide()

        # 超时 / 轮询
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("超时"))
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(0.1, 5.0)
        self.timeout.setSingleStep(0.1)
        self.timeout.setValue(0.5)
        self.timeout.setSuffix(" s")
        row2.addWidget(self.timeout)
        row2.addWidget(QLabel("轮询"))
        self.poll_interval = QDoubleSpinBox()
        self.poll_interval.setRange(0.05, 5.0)
        self.poll_interval.setSingleStep(0.05)
        self.poll_interval.setValue(0.2)
        self.poll_interval.setSuffix(" s")
        row2.addWidget(self.poll_interval)
        lay.addLayout(row2)

        # 按钮
        btn_row = QHBoxLayout()
        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("Primary")
        self.btn_connect.setMinimumHeight(36)
        self.btn_connect.clicked.connect(self.connect_clicked.emit)
        self.btn_disconnect = QPushButton("断开")
        self.btn_disconnect.setObjectName("Danger")
        self.btn_disconnect.setMinimumHeight(36)
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_clicked.emit)
        self.btn_diag = QPushButton("通讯诊断")
        self.btn_diag.setMinimumHeight(36)
        self.btn_diag.setToolTip("探测 M/X/Y/D 等区的 01/02/03/04 功能码，结果写入日志")
        btn_row.addWidget(self.btn_connect, 2)
        btn_row.addWidget(self.btn_disconnect, 1)
        btn_row.addWidget(self.btn_diag, 1)
        lay.addLayout(btn_row)

        # 持续强制
        force_row = QHBoxLayout()
        self.chk_force = QCheckBox("持续强制已置位的 Y/M")
        self.chk_force.setToolTip(
            "开启后每隔约100ms重写强制点，对抗PLC程序扫描覆盖。"
            "输出会以本机强制为准。"
        )
        force_row.addWidget(self.chk_force)
        self.btn_clear_force = QPushButton("清除强制")
        force_row.addWidget(self.btn_clear_force)
        force_row.addStretch()
        lay.addLayout(force_row)

        # 实时状态简报
        self.stats_lab = QLabel("TX 0   RX 0   ERR 0")
        self.stats_lab.setStyleSheet("color:#7A8699; font-size:11px;")
        lay.addWidget(self.stats_lab)

        # PLC RUN/STOP 状态
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("PLC 状态"))
        self.run_lamp = QLabel()
        self.run_lamp.setFixedSize(12, 12)
        self.run_lamp.setObjectName("LampOff")
        run_row.addWidget(self.run_lamp)
        self.run_lab = QLabel("未知")
        self.run_lab.setStyleSheet("color:#7A8699; font-weight:600; font-size:12px;")
        run_row.addWidget(self.run_lab)
        run_row.addStretch()
        btn_run_help = QPushButton("RUN/STOP?")
        btn_run_help.setToolTip(
            "标准 Modbus 无远程 RUN/STOP 命令。\n"
            "请用编程软件：PLC 操作 → 运行/停止；\n"
            "或拨 PLC 面板上的 RUN/STOP 开关。\n"
            "本界面通过 SM0（运行常ON）监视状态。"
        )
        btn_run_help.clicked.connect(self._show_run_help)
        run_row.addWidget(btn_run_help)
        lay.addLayout(run_row)

    def _mode_changed(self, idx: int) -> None:
        is_tcp = idx == 1
        self.tcp_box.setVisible(is_tcp)
        self.rtu_box.setVisible(not is_tcp)
        self.settings_changed.emit()

    def _refresh_ports(self) -> None:
        cur = self.port.currentText()
        self.port.clear()
        ports = list_serial_ports()
        self.port.addItems(ports or ["COM1"])
        if cur in ports:
            self.port.setCurrentText(cur)
        elif ports:
            self.port.setCurrentText(ports[0])
        elif cur:
            self.port.setCurrentText(cur)

    def apply_config(self, cfg: AppConfig) -> None:
        self.mode.setCurrentIndex(1 if cfg.mode == "tcp" else 0)
        self.series.setCurrentText(cfg.series)
        self.port.setCurrentText(cfg.port)
        self.baud.setCurrentText(str(cfg.baudrate))
        self.parity.setCurrentIndex({"N": 0, "E": 1, "O": 2}.get(cfg.parity.upper(), 0))
        self.stopbits.setCurrentText(str(int(cfg.stopbits)))
        self.slave.setValue(cfg.slave_id)
        self.host.setText(cfg.host)
        self.tcp_port.setValue(cfg.tcp_port)
        self.tcp_slave.setValue(cfg.slave_id)
        self.timeout.setValue(cfg.timeout)
        self.poll_interval.setValue(cfg.poll_interval)

    def to_config(self) -> AppConfig:
        mode = "tcp" if self.mode.currentIndex() == 1 else "rtu"
        parity = ["N", "E", "O"][self.parity.currentIndex()]
        return AppConfig(
            series=self.series.currentText(),
            mode=mode,
            port=self.port.currentText(),
            baudrate=int(self.baud.currentText()),
            parity=parity,
            stopbits=float(self.stopbits.currentText()),
            host=self.host.text().strip(),
            tcp_port=self.tcp_port.value(),
            slave_id=self.slave.value() if mode == "rtu" else self.tcp_slave.value(),
            timeout=self.timeout.value(),
            poll_interval=self.poll_interval.value(),
        )

    def to_modbus_config(self) -> ModbusConfig:
        return self.to_config().to_modbus_config()

    def set_connected(self, on: bool) -> None:
        self.btn_connect.setEnabled(not on)
        self.btn_disconnect.setEnabled(on)
        self.mode.setEnabled(not on)
        self.series.setEnabled(not on)
        self.rtu_box.setEnabled(not on)
        self.tcp_box.setEnabled(not on)
        if on:
            self.lamp.setObjectName("LampOn")
            self.st_lab.setText("已连接")
            self.st_lab.setStyleSheet(
                "color:#1F9D63; font-weight:600; font-size:12px;"
            )
        else:
            self.lamp.setObjectName("LampOff")
            self.st_lab.setText("未连接")
            self.st_lab.setStyleSheet(
                "color:#7A8699; font-weight:600; font-size:12px;"
            )
        self.lamp.style().unpolish(self.lamp)
        self.lamp.style().polish(self.lamp)

    def set_error(self, msg: str) -> None:
        self.lamp.setObjectName("LampErr")
        self.lamp.style().unpolish(self.lamp)
        self.lamp.style().polish(self.lamp)
        self.st_lab.setText(msg[:28])
        self.st_lab.setStyleSheet(
            "color:#E24B4B; font-weight:600; font-size:12px;"
        )

    def update_stats(self, tx: int, rx: int, err: int, extra: str = "") -> None:
        self.stats_lab.setText(f"TX {tx}   RX {rx}   ERR {err}  {extra}")

    def set_run_state(self, running: Optional[bool]) -> None:
        if running is True:
            self.run_lamp.setObjectName("LampOn")
            self.run_lab.setText("RUN")
            self.run_lab.setStyleSheet("color:#1F9D63; font-weight:600; font-size:12px;")
        elif running is False:
            self.run_lamp.setObjectName("LampOff")
            self.run_lab.setText("STOP")
            self.run_lab.setStyleSheet("color:#E24B4B; font-weight:600; font-size:12px;")
        else:
            self.run_lamp.setObjectName("LampWarn")
            self.run_lab.setText("未知")
            self.run_lab.setStyleSheet("color:#7A8699; font-weight:600; font-size:12px;")
        self.run_lamp.style().unpolish(self.run_lamp)
        self.run_lamp.style().polish(self.run_lamp)

    def _show_run_help(self) -> None:
        QMessageBox.information(
            self, "RUN / STOP 说明",
            "标准 Modbus 协议没有「强制 RUN/STOP」命令。\n\n"
            "信捷 XD/XL 切换运行方式：\n"
            "1. 编程软件：PLC 操作 → 运行 / 停止\n"
            "2. PLC 面板 RUN/STOP 开关\n"
            "3. USB 下载线连上后用「上电停止 PLC」\n\n"
            "本软件通过 SM0（运行常 ON）监视状态：\n"
            "  SM0=ON  → RUN\n  SM0=OFF → STOP\n\n"
            "若要远程切 STOP 方便强制 Y，请先用编程软件停止程序。",
        )


# ---------------------------------------------------------------------------
# I/O 面板
# ---------------------------------------------------------------------------

class IOGroup(QFrame):
    """一组点位监视/强制（双栏中的左栏或右栏）。"""
    write_bit = Signal(str, bool)

    def __init__(self, title: str, default_kind: int = 1):
        super().__init__()
        self.setObjectName("Card")
        self.buttons: dict[str, BitButton] = {}
        self._title = title
        self._default_kind = default_kind
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        head_row = QHBoxLayout()
        head = QLabel(self._title)
        head.setObjectName("CardHeading")
        head_row.addWidget(head)
        head_row.addStretch()
        head_row.addWidget(QLabel("类型"))
        self.kind = QComboBox()
        self.kind.addItems(["输入 X", "输出 Y", "辅助 M"])
        self.kind.setCurrentIndex(self._default_kind)
        self.kind.currentIndexChanged.connect(self._on_kind_changed)
        head_row.addWidget(self.kind)

        # 区域：本体 / 扩展模块 / BD / ED（X/Y 有效）
        self.zone = QComboBox()
        self.zone.addItem("本体", (0, 0))
        for m in range(16):
            self.zone.addItem(f"模块 #{m+1}", (1, m))
        for m in range(2):
            self.zone.addItem(f"BD #{m+1}", (2, m))
        self.zone.addItem("ED #1", (3, 0))
        self.zone.currentIndexChanged.connect(self._rebuild)
        head_row.addWidget(QLabel("区域"))
        head_row.addWidget(self.zone)

        self.count = QSpinBox()
        self.count.setRange(8, 128)
        self.count.setValue(32)
        self.count.setSingleStep(8)
        head_row.addWidget(QLabel("点数"))
        head_row.addWidget(self.count)
        self.count.valueChanged.connect(self._rebuild)
        lay.addLayout(head_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(5)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.grid_host)
        lay.addWidget(self.scroll, 1)
        self._rebuild()

    def _on_kind_changed(self) -> None:
        # M 没有扩展模块区域
        is_xy = self.kind.currentIndex() in (0, 1)
        self.zone.setEnabled(is_xy)
        self._rebuild()

    def _rebuild(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.buttons.clear()

        prefix = ["X", "Y", "M"][self.kind.currentIndex()]
        writable = prefix in ("Y", "M")
        n = self.count.value()

        from ..app.devices import io_module_names
        if prefix in ("X", "Y"):
            station, module = self.zone.currentData() or (0, 0)
            names = io_module_names(prefix, station, module, n)
        else:
            names = [f"{prefix}{i}" for i in range(n)]

        cols = 4
        for idx, name in enumerate(names):
            btn = BitButton(name, writable=writable)
            if writable:
                btn.toggle_requested.connect(self._on_toggle)
            self.buttons[name] = btn
            self.grid.addWidget(btn, idx // cols, idx % cols)
        for c in range(cols):
            self.grid.setColumnStretch(c, 0)
        self.grid.setColumnStretch(cols, 1)

    def _on_toggle(self, name: str, new_state: bool) -> None:
        self.write_bit.emit(name, new_state)

    def update_bits(self, values: dict[str, bool]) -> None:
        for name, on in values.items():
            btn = self.buttons.get(name)
            if btn:
                btn.set_state(on)

    def force_state(self, name: str, on: bool) -> None:
        btn = self.buttons.get(name)
        if btn:
            btn.set_state(on)

    def set_pending(self, name: str) -> None:
        btn = self.buttons.get(name)
        if btn:
            btn.set_pending()

    def current_names(self) -> list[str]:
        return list(self.buttons.keys())


class IOPanel(QFrame):
    """双栏 I/O：左右两组同时监视/强制。"""
    write_bit = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        head_row = QHBoxLayout()
        head = QLabel("I/O 监视与强制（双栏）")
        head.setObjectName("CardHeading")
        head_row.addWidget(head)
        head_row.addStretch()
        self.btn_refresh = QPushButton("立即刷新")
        head_row.addWidget(self.btn_refresh)
        lay.addLayout(head_row)

        self.hint = QLabel(
            "左右两组可分别选 X/Y/M，方便对照监控。"
            "绿=ON  灰=OFF  橙=写入中。点击 Y/M 强制；X/Y 八进制编号。"
        )
        self.hint.setObjectName("CardSub")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        split = QHBoxLayout()
        split.setSpacing(10)
        self.group_a = IOGroup("组 A", default_kind=0)  # 默认 X
        self.group_b = IOGroup("组 B", default_kind=1)  # 默认 Y
        self.group_a.write_bit.connect(self.write_bit.emit)
        self.group_b.write_bit.connect(self.write_bit.emit)
        split.addWidget(self.group_a, 1)
        split.addWidget(self.group_b, 1)
        lay.addLayout(split, 1)

    def update_bits(self, values: dict[str, bool]) -> None:
        self.group_a.update_bits(values)
        self.group_b.update_bits(values)

    def force_state(self, name: str, on: bool) -> None:
        self.group_a.force_state(name, on)
        self.group_b.force_state(name, on)

    def set_pending(self, name: str) -> None:
        self.group_a.set_pending(name)
        self.group_b.set_pending(name)

    def all_names(self) -> list[str]:
        return self.group_a.current_names() + self.group_b.current_names()

    def all_groups(self) -> list[IOGroup]:
        return [self.group_a, self.group_b]


# ---------------------------------------------------------------------------
# 寄存器面板
# ---------------------------------------------------------------------------

class RegisterPanel(QFrame):
    write_word = Signal(str, int)
    write_bit = Signal(str, bool)
    add_trend = Signal(str)
    tag_added = Signal(str, str)
    tag_removed = Signal(str)

    COLS = ["设备", "地址", "类型", "数值", "HEX", "状态"]

    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        head = QLabel("软元件监视表")
        head.setObjectName("CardHeading")
        lay.addWidget(head)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("软元件"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("例如 D100 / M10 / HD20 / Y5")
        self.ed_name.returnPressed.connect(self._add_row)
        add_row.addWidget(self.ed_name, 2)

        add_row.addWidget(QLabel("类型"))
        self.ed_kind = QComboBox()
        self.ed_kind.addItems(["word", "bit", "dword", "float"])
        add_row.addWidget(self.ed_kind)

        add_row.addWidget(QLabel("注释"))
        self.ed_label = QLineEdit()
        add_row.addWidget(self.ed_label, 1)

        btn_add = QPushButton("添加")
        btn_add.setObjectName("Primary")
        btn_add.clicked.connect(self._add_row)
        add_row.addWidget(btn_add)

        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._del_selected)
        add_row.addWidget(btn_del)

        btn_trend = QPushButton("曲线")
        btn_trend.clicked.connect(self._emit_trend)
        add_row.addWidget(btn_trend)
        lay.addLayout(add_row)

        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("批量"))
        self.batch_prefix = QComboBox()
        self.batch_prefix.addItems(["D", "M", "HD", "X", "Y", "SD", "TD", "CD"])
        batch_row.addWidget(self.batch_prefix)
        self.batch_start = QSpinBox()
        self.batch_start.setRange(0, 65535)
        batch_row.addWidget(QLabel("起始"))
        batch_row.addWidget(self.batch_start)
        self.batch_count = QSpinBox()
        self.batch_count.setRange(1, 128)
        self.batch_count.setValue(10)
        batch_row.addWidget(QLabel("数量"))
        batch_row.addWidget(self.batch_count)
        btn_batch = QPushButton("批量添加")
        btn_batch.clicked.connect(self._batch_add)
        batch_row.addWidget(btn_batch)
        batch_row.addStretch()
        btn_write = QPushButton("写入选中")
        btn_write.setObjectName("Success")
        btn_write.clicked.connect(self._write_selected)
        batch_row.addWidget(btn_write)
        lay.addLayout(batch_row)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(self._edit_value)
        lay.addWidget(self.table, 1)

        self.hint = QLabel("双击「数值」可写入；位元件输入 0/1 或 ON/OFF。")
        self.hint.setObjectName("CardSub")
        lay.addWidget(self.hint)

    def _add_row(self, name: Optional[str] = None, kind: Optional[str] = None) -> None:
        name = (name or self.ed_name.text()).strip().upper()
        kind = kind or self.ed_kind.currentText()
        label = self.ed_label.text().strip()
        if not name:
            return
        try:
            d = parse_device(name, "XD3")
        except Exception as e:
            QMessageBox.warning(self, "无效设备", str(e))
            return

        if d.kind in (DataType.COIL, DataType.DISCRETE_INPUT):
            kind = "bit"
        elif kind == "bit":
            kind = "word"

        for r in range(self.table.rowCount()):
            if self.table.item(r, 0) and self.table.item(r, 0).text() == name:
                return

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(
            f"{d.modbus_addr} (H{d.modbus_addr:04X})"
        ))
        self.table.setItem(row, 2, QTableWidgetItem(kind))
        self.table.setItem(row, 3, QTableWidgetItem("--"))
        self.table.setItem(row, 4, QTableWidgetItem("--"))
        st = QTableWidgetItem("等待")
        st.setForeground(QColor("#7A8699"))
        self.table.setItem(row, 5, st)
        if label:
            self.table.item(row, 0).setToolTip(label)

        self.tag_added.emit(name, kind)
        self.ed_name.clear()
        self.ed_label.clear()

    def _batch_add(self) -> None:
        prefix = self.batch_prefix.currentText()
        start = self.batch_start.value()
        count = self.batch_count.value()
        if prefix in ("X", "Y"):
            names = [f"{prefix}{oct(start + k)[2:].upper()}" for k in range(count)]
        else:
            names = [f"{prefix}{start + k}" for k in range(count)]
        for n in names:
            self._add_row(n)

    def _del_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            item = self.table.item(r, 0)
            name = item.text() if item else ""
            self.table.removeRow(r)
            if name:
                self.tag_removed.emit(name)

    def _emit_trend(self) -> None:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.isSelected():
                self.add_trend.emit(item.text())

    def _write_selected(self) -> None:
        for r in {i.row() for i in self.table.selectedIndexes()}:
            self._write_row(r)

    def _edit_value(self, item: QTableWidgetItem) -> None:
        if item.column() == 3:
            self._write_row(item.row())

    def _write_row(self, row: int) -> None:
        name_item = self.table.item(row, 0)
        if not name_item:
            return
        name = name_item.text()
        kind = self.table.item(row, 2).text() if self.table.item(row, 2) else "word"
        cur = self.table.item(row, 3).text() if self.table.item(row, 3) else ""

        if kind == "bit":
            text, ok = QInputDialog.getText(
                self, "写入位", f"写入 {name}（ON/OFF 或 1/0）：", text=cur
            )
            if not ok:
                return
            val = text.strip().upper()
            bit = val in ("1", "ON", "TRUE", "Y", "是")
            self.write_bit.emit(name, bit)
        else:
            text, ok = QInputDialog.getText(
                self, "写入数值", f"写入 {name}：", text=cur
            )
            if not ok:
                return
            try:
                s = text.strip()
                v = int(s, 16) if s.upper().startswith("0X") else int(s, 0)
                self.write_word.emit(name, v)
            except Exception:
                QMessageBox.warning(self, "错误", f"无效数值: {text}")

    def update_values(self, tags) -> None:
        by_name = {t.name: t for t in tags}
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if not item:
                continue
            t = by_name.get(item.text())
            if not t:
                continue

            # 数值列：bit 用颜色区分 ON/OFF
            val_item = QTableWidgetItem(t.display)
            if t.kind == "bit" and t.value is not None:
                if t.value:
                    val_item.setForeground(QColor("#16A34A"))
                    val_item.setBackground(QColor("#DCFCE7"))
                    val_item.setTextAlignment(Qt.AlignCenter)
                    f = val_item.font()
                    f.setBold(True)
                    val_item.setFont(f)
                else:
                    val_item.setForeground(QColor("#64748B"))
                    val_item.setBackground(QColor("#F1F5F9"))
                    val_item.setTextAlignment(Qt.AlignCenter)
            elif t.kind in ("word", "dword", "float") and t.value is not None:
                val_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 3, val_item)

            self.table.setItem(r, 4, QTableWidgetItem(f"0x{t.raw & 0xFFFFFFFF:04X}"))
            st = self.table.item(r, 5)
            if st is None:
                st = QTableWidgetItem()
                self.table.setItem(r, 5, st)
            if t.ok:
                st.setText("OK")
                st.setForeground(QColor("#1F9D63"))
            else:
                st.setText("ERR")
                st.setForeground(QColor("#E24B4B"))
                st.setToolTip(t.error)


# ---------------------------------------------------------------------------
# 报警面板
# ---------------------------------------------------------------------------

class AlarmPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Card")
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        head = QLabel("报警与事件")
        head.setObjectName("CardHeading")
        lay.addWidget(head)

        rule_row = QHBoxLayout()
        rule_row.addWidget(QLabel("设备"))
        self.rule_tag = QLineEdit()
        self.rule_tag.setPlaceholderText("D100")
        rule_row.addWidget(self.rule_tag)
        rule_row.addWidget(QLabel("规则"))
        self.rule_type = QComboBox()
        self.rule_type.addItems([
            "hi 高于", "lo 低于", "hihi 高高报", "lolo 低低报", "ne 不等于",
        ])
        rule_row.addWidget(self.rule_type)
        rule_row.addWidget(QLabel("限值"))
        self.rule_limit = QDoubleSpinBox()
        self.rule_limit.setRange(-1e9, 1e9)
        rule_row.addWidget(self.rule_limit)
        rule_row.addWidget(QLabel("2nd"))
        self.rule_limit2 = QDoubleSpinBox()
        self.rule_limit2.setRange(-1e9, 1e9)
        rule_row.addWidget(self.rule_limit2)
        self.rule_msg = QLineEdit()
        self.rule_msg.setPlaceholderText("描述")
        rule_row.addWidget(self.rule_msg, 1)
        btn_add = QPushButton("添加规则")
        btn_add.clicked.connect(self._add_rule_clicked)
        rule_row.addWidget(btn_add)
        lay.addLayout(rule_row)

        self.rule_table = QTableWidget(0, 5)
        self.rule_table.setHorizontalHeaderLabels(
            ["设备", "规则", "限值", "描述", "状态"]
        )
        self.rule_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rule_table.setMaximumHeight(130)
        lay.addWidget(self.rule_table)

        self.ev_table = QTableWidget(0, 6)
        self.ev_table.setHorizontalHeaderLabels(
            ["时间", "设备", "规则", "限值", "当前值", "状态"]
        )
        self.ev_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ev_table.setAlternatingRowColors(True)
        lay.addWidget(self.ev_table, 1)

        btn_clear = QPushButton("清空事件")
        btn_clear.clicked.connect(lambda: self.ev_table.setRowCount(0))
        lay.addWidget(btn_clear, 0, Qt.AlignRight)

        self._add_rule_handler = None

    def _add_rule_clicked(self) -> None:
        if self._add_rule_handler:
            self._add_rule_handler()

    def set_add_rule_handler(self, fn) -> None:
        self._add_rule_handler = fn

    def rule_inputs(self) -> dict:
        rt = self.rule_type.currentText().split()[0]
        return {
            "tag_name": self.rule_tag.text().strip().upper(),
            "rule_type": rt,
            "limit": self.rule_limit.value(),
            "limit2": self.rule_limit2.value(),
            "message": self.rule_msg.text().strip(),
        }

    def add_rule(self, rule: AlarmRule) -> None:
        r = self.rule_table.rowCount()
        self.rule_table.insertRow(r)
        self.rule_table.setItem(r, 0, QTableWidgetItem(rule.tag_name))
        self.rule_table.setItem(r, 1, QTableWidgetItem(rule.rule_type))
        self.rule_table.setItem(r, 2, QTableWidgetItem(str(rule.limit)))
        self.rule_table.setItem(r, 3, QTableWidgetItem(rule.message))
        self.rule_table.setItem(r, 4, QTableWidgetItem("监控中"))

    def append_event(self, ev: AlarmEvent) -> None:
        r = self.ev_table.rowCount()
        self.ev_table.insertRow(r)
        ts = time.strftime("%H:%M:%S", time.localtime(ev.ts))
        self.ev_table.setItem(r, 0, QTableWidgetItem(ts))
        self.ev_table.setItem(r, 1, QTableWidgetItem(ev.tag_name))
        self.ev_table.setItem(r, 2, QTableWidgetItem(ev.rule_type))
        self.ev_table.setItem(r, 3, QTableWidgetItem(str(ev.limit)))
        self.ev_table.setItem(r, 4, QTableWidgetItem(f"{ev.value:.3f}"))
        st = QTableWidgetItem(ev.state)
        st.setForeground(QColor("#E24B4B" if ev.state == "ON" else "#1F9D63"))
        self.ev_table.setItem(r, 5, st)
        self.ev_table.scrollToBottom()

    def update_rule_states(self, rules) -> None:
        for i, rule in enumerate(rules):
            if i < self.rule_table.rowCount():
                item = self.rule_table.item(i, 4)
                if item:
                    item.setText("报警中" if rule.active else "监控中")
                    item.setForeground(
                        QColor("#E24B4B" if rule.active else "#1F9D63")
                    )


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    # 跨线程日志：任何线程 emit，主线程 append
    _log_sig = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("信捷 XD/XL 系列上位机控制软件  ·  Xinje Host Studio")
        self.resize(1480, 900)
        self.setMinimumSize(1180, 720)

        self.cfg = load_config()
        self.plc = PlcClient(self.cfg.series)
        self.engine = PollingEngine(self.plc, interval=self.cfg.poll_interval)
        self._worker = PollWorker(self.engine)
        # 持续强制表：name -> value
        self._force_table: dict[str, bool] = {}

        self._build_ui()
        # 日志必须主线程写入，否则轮询线程碰 UI 会闪退
        self._log_sig.connect(self._append_log, Qt.QueuedConnection)
        self._bind()
        self.conn.apply_config(self.cfg)
        self._load_cfg_tags()

        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._refresh_status)
        self._ui_timer.start(400)

    # -- UI ---------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== 左侧导航 =====
        side = QFrame()
        side.setObjectName("SideBar")
        side.setFixedWidth(200)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 18, 16, 18)
        sl.setSpacing(6)

        title = QLabel("Xinje Host")
        title.setObjectName("AppTitle")
        sl.addWidget(title)
        sub = QLabel("XD / XL 系列上位机")
        sub.setObjectName("AppSub")
        sl.addWidget(sub)
        sl.addSpacing(16)

        self.nav_buttons: list[QPushButton] = []
        for text, icon in [
            ("I/O 监视", "⚡"),
            ("寄存器监视", "📋"),
            ("实时曲线", "📈"),
            ("报警事件", "🔔"),
        ]:
            btn = QPushButton(f"  {icon}  {text}")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            sl.addWidget(btn)
            self.nav_buttons.append(btn)

        sl.addStretch()
        ver = QLabel("v1.1  ·  Modbus RTU/TCP")
        ver.setObjectName("AppSub")
        sl.addWidget(ver)
        root.addWidget(side)

        # ===== 中央工作区 =====
        center_host = QWidget()
        cl = QVBoxLayout(center_host)
        cl.setContentsMargins(14, 12, 8, 12)
        cl.setSpacing(10)

        self.stack = QTabWidget()
        self.stack.setDocumentMode(True)

        self.io_panel = IOPanel()
        self.reg_panel = RegisterPanel()
        self.trend = TrendWidget()
        self.alarm_panel = AlarmPanel()

        # 趋势控制条
        trend_page = QWidget()
        tl = QVBoxLayout(trend_page)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tctrl = QHBoxLayout()
        tctrl.addWidget(QLabel("时间窗"))
        self.trend_window = QComboBox()
        self.trend_window.addItems(["30 秒", "60 秒", "2 分钟", "5 分钟", "10 分钟"])
        self.trend_window.setCurrentIndex(1)
        self.trend_window.currentIndexChanged.connect(self._trend_window_changed)
        tctrl.addWidget(self.trend_window)
        btn_auto = QPushButton("自动量程")
        btn_auto.clicked.connect(self.trend.set_auto_y)
        tctrl.addWidget(btn_auto)
        btn_clear_t = QPushButton("清空曲线")
        btn_clear_t.clicked.connect(self.trend.clear)
        tctrl.addWidget(btn_clear_t)
        btn_exp = QPushButton("导出 CSV")
        btn_exp.clicked.connect(self._export_history)
        tctrl.addWidget(btn_exp)
        tctrl.addStretch()
        tctrl.addWidget(QLabel("序列"))
        self.trend_list = QComboBox()
        self.trend_list.setMinimumWidth(140)
        tctrl.addWidget(self.trend_list)
        tl.addLayout(tctrl)
        tl.addWidget(self.trend, 1)

        self.stack.addTab(self.io_panel, "I/O 监视")
        self.stack.addTab(self.reg_panel, "寄存器监视")
        self.stack.addTab(trend_page, "实时曲线")
        self.stack.addTab(self.alarm_panel, "报警事件")
        cl.addWidget(self.stack)

        from PyQt5.QtWidgets import QScrollArea, QSplitter, QSizePolicy

        def _flat_scroll(w):
            """包滚动区：解除控件 minimumSizeHint 顶死分割条（框架规范）。"""
            s = QScrollArea()
            s.setWidgetResizable(True)
            s.setFrameShape(QFrame.NoFrame)
            s.setStyleSheet("QScrollArea{background:transparent; border:none;}")
            s.setWidget(w)
            return s

        # ===== 右侧：连接面板（宽度可拖动缩放，不写死固定宽度） =====
        right = QFrame()
        right.setMinimumWidth(220)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 12, 12, 12)
        right_lay.setSpacing(10)

        self.conn = ConnectionPanel()
        self.conn.setMinimumHeight(240)
        right_lay.addWidget(self.conn, 1)

        # ===== 日志：归属操作区下方，与内容区用可拖动分割条缩放 =====
        log_card = QFrame()
        log_card.setObjectName("Card")
        log_lay = QVBoxLayout(log_card)
        log_lay.setContentsMargins(14, 10, 14, 12)
        log_lay.setSpacing(8)
        log_head = QHBoxLayout()
        log_title = QLabel("通讯日志")
        log_title.setObjectName("CardHeading")
        log_head.addWidget(log_title)
        log_head.addStretch()
        btn_clear_log = QPushButton("清空")
        btn_clear_log.setFixedWidth(64)
        btn_clear_log.clicked.connect(lambda: self.log_view.clear())
        log_head.addWidget(btn_clear_log)
        log_lay.addLayout(log_head)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("连接、读写、报警日志…")
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMinimumHeight(110)
        log_lay.addWidget(self.log_view, 1)

        # 上：导航 + 工作区 + 连接（水平可拖）；下：日志（垂直可拖）
        # 各栏包滚动区：下拉框行的 minimumSizeHint 不再顶死分割条/挤出可视区
        h_split = QSplitter(Qt.Horizontal)
        h_split.setChildrenCollapsible(False)
        h_split.addWidget(_flat_scroll(side))
        h_split.addWidget(_flat_scroll(center_host))
        h_split.addWidget(_flat_scroll(right))
        h_split.setStretchFactor(0, 0)
        h_split.setStretchFactor(1, 1)
        h_split.setStretchFactor(2, 0)
        h_split.setCollapsible(1, False)

        # 内容区（各栏已包滚动区）：日志放大时功能区上下滚动，控件保持原形态
        main_split = QSplitter(Qt.Vertical)
        main_split.setHandleWidth(14)
        main_split.setChildrenCollapsible(False)
        main_split.addWidget(h_split)
        main_split.addWidget(log_card)
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 0)
        main_split.setSizes([520, 190])
        h_split.setMinimumHeight(120)
        root.addWidget(main_split)

        # ===== 状态栏 =====
        self.statusBar().setSizeGripEnabled(True)
        self.st_conn = QLabel("○ 未连接")
        self.st_poll = QLabel("轮询: --")
        self.st_stats = QLabel("TX 0  RX 0  ERR 0")
        self.st_tag = QLabel("标签: 0")
        self.statusBar().addWidget(self.st_conn)
        self.statusBar().addPermanentWidget(self.st_tag)
        self.statusBar().addPermanentWidget(self.st_poll)
        self.statusBar().addPermanentWidget(self.st_stats)

        for i, btn in enumerate(self.nav_buttons):
            btn.clicked.connect(lambda _, idx=i: self._nav(idx))
        if self.nav_buttons:
            self.nav_buttons[0].setChecked(True)
        # 顶部页签变化时，同步左侧导航
        self.stack.currentChanged.connect(self._sync_nav)

    def _nav(self, idx: int) -> None:
        self.stack.blockSignals(True)
        self.stack.setCurrentIndex(idx)
        self.stack.blockSignals(False)
        self._sync_nav(idx)

    def _sync_nav(self, idx: int) -> None:
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == idx)

    def _bind(self) -> None:
        self.conn.connect_clicked.connect(self._do_connect)
        self.conn.disconnect_clicked.connect(self._do_disconnect)
        self.conn.diagnose_clicked.connect(self._run_diagnose)
        self.conn.clear_force_clicked.connect(self._clear_force)
        self.io_panel.write_bit.connect(self._on_write_bit)
        self.io_panel.btn_refresh.clicked.connect(self._refresh_io)
        self.reg_panel.write_word.connect(self._on_write_word)
        self.reg_panel.write_bit.connect(self._on_write_bit)
        self.reg_panel.add_trend.connect(self._add_trend_tag)
        self.reg_panel.tag_added.connect(self._on_tag_added)
        self.reg_panel.tag_removed.connect(self._on_tag_removed)

        self._worker.tags_updated.connect(self._on_tags_updated, Qt.QueuedConnection)
        self._worker.alarm_raised.connect(self._on_alarm, Qt.QueuedConnection)
        self._worker.error.connect(self._on_poll_error, Qt.QueuedConnection)
        self._worker.plc_state.connect(self._on_plc_state, Qt.QueuedConnection)

        self.alarm_panel.set_add_rule_handler(self._add_alarm_rule)

    # -- 连接 -------------------------------------------------------------
    def _do_connect(self) -> None:
        try:
            cfg = self.conn.to_config()
            mcfg = cfg.to_modbus_config()
            self.plc.series = cfg.series
            self.plc.clear_cache()
            self.plc.connect(mcfg, cfg.series)
            self.engine.interval = cfg.poll_interval
            self.cfg = cfg
            save_config(cfg)

            self.conn.set_connected(True)
            # 帧日志 → 右侧通讯日志
            self.plc.modbus.on_frame = self._on_frame
            desc = (
                f"TCP {mcfg.host}:{mcfg.tcp_port}"
                if mcfg.mode == "tcp"
                else f"{mcfg.port} {mcfg.baudrate},{mcfg.bytesize},{mcfg.parity},{int(mcfg.stopbits)}"
            )
            self._log(f"已连接  {desc}  站号={mcfg.slave_id}  系列={cfg.series}")
            self.engine.start()
            self._log(f"轮询启动，周期 {self.engine.interval:.2f}s")

        except Exception as e:
            self.conn.set_error(str(e))
            self._log(f"连接失败: {e}")
            QMessageBox.critical(self, "连接失败", str(e))

    def _do_disconnect(self) -> None:
        try:
            self.engine.stop()
        except Exception as e:
            self._log(f"轮询停止异常: {e}")
        try:
            self.plc.disconnect()
        except Exception as e:
            self._log(f"断开连接异常: {e}")
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 断开连接 = 通讯中断，状态灯回灰
        self.conn.set_connected(False)
        self._log("已断开连接")

    # -- 位/字写入（带回读） ---------------------------------------------
    def _on_write_bit(self, name: str, value: bool) -> None:
        if not self.plc.connected:
            self.io_panel.force_state(name, not value)  # 恢复按钮
            QMessageBox.warning(self, "未连接", "请先在右侧连接 PLC")
            return
        # 强制输出直接作用于现场设备，必须二次确认（安全硬约束）
        if value:
            try:
                from instrument_hub.dialogs import ConfirmOutputDialog
                dlg = ConfirmOutputDialog(
                    "信捷 XD/XL 系列 PLC", f"强制 {name} → ON",
                    "强制输出会直接改变 PLC 输出点，直接作用于现场设备！"
                    "操作前请确认工艺安全，并保持急停回路有效。",
                    f"软元件 {name}（写 Y/M 点）", self)
                if dlg.exec_() != ConfirmOutputDialog.Accepted:
                    self.io_panel.force_state(name, not value)
                    return
            except ImportError:
                if not QMessageBox.question(
                        self, "确认强制",
                        f"确定强制 {name} → ON ？\n"
                        "（该操作会直接作用于现场设备）") == QMessageBox.Yes:
                    self.io_panel.force_state(name, not value)
                    return
        self.io_panel.set_pending(name)
        try:
            ok, detail = self.plc.force_bit(name, value)
            self._log(detail)
            if ok:
                self.io_panel.force_state(name, value)
                self._force_table[name] = value
                if self.conn.chk_force.isChecked():
                    self._log(f"持续强制已登记: {name}={'ON' if value else 'OFF'}")
            else:
                try:
                    actual = self.plc.read_bit(name)
                    self.io_panel.force_state(name, actual)
                except Exception:
                    self.io_panel.force_state(name, not value)
                # 仍登记，配合持续强制
                self._force_table[name] = value
                self.conn.chk_force.setChecked(True)
                QMessageBox.warning(
                    self, "强制结果",
                    f"{name} 写入后读回不一致。\n{detail}\n\n"
                    "已自动开启「持续强制」：系统会循环重写该点。\n"
                    "若仍无效，请：\n"
                    "1. 点「通讯诊断」把日志发我\n"
                    "2. 将 PLC 置为 STOP 后再强制\n"
                    "3. 确认程序没有 OUT 该 Y 点",
                )
        except Exception as e:
            self.io_panel.force_state(name, not value)
            self._log(f"写位失败 {name}: {e}")
            QMessageBox.warning(self, "写入失败", str(e))

    def _clear_force(self) -> None:
        self._force_table.clear()
        self.conn.chk_force.setChecked(False)
        self._log("已清除持续强制表")

    def _run_diagnose(self) -> None:
        if not self.plc.connected:
            QMessageBox.warning(self, "未连接", "请先连接 PLC")
            return
        self._log("开始通讯诊断…")
        try:
            report = self.plc.diagnose()
        except Exception as e:
            report = f"诊断异常: {e}"
        for line in report.splitlines():
            self._log(line)
        QMessageBox.information(self, "通讯诊断", report)

    def _on_write_word(self, name: str, value: int) -> None:
        if not self.plc.connected:
            QMessageBox.warning(self, "未连接", "请先在右侧连接 PLC")
            return
        try:
            ok, detail = self.plc.force_word(name, value)
            self._log(detail)
            if not ok:
                QMessageBox.warning(self, "写入结果", detail)
        except Exception as e:
            self._log(f"写字失败 {name}: {e}")
            QMessageBox.warning(self, "写入失败", str(e))

    def _add_trend_tag(self, name: str) -> None:
        self.trend.add_series(name)
        self.trend_list.clear()
        self.trend_list.addItems(list(self.trend.series.keys()))
        self._log(f"已加入曲线: {name}")

    def _on_tag_added(self, name: str, kind: str) -> None:
        self.engine.add_tag(MonitorTag(name=name, kind=kind))
        self._log(f"监视标签 + {name} ({kind})")

    def _on_tag_removed(self, name: str) -> None:
        self.engine.remove_tag(name)
        self.trend.remove_series(name)
        self._log(f"监视标签 - {name}")

    def _add_alarm_rule(self) -> None:
        data = self.alarm_panel.rule_inputs()
        if not data["tag_name"]:
            QMessageBox.warning(self, "提示", "请填写设备名")
            return
        rule = AlarmRule(**data)
        self.engine.add_alarm(rule)
        self.alarm_panel.add_rule(rule)
        self._log(f"报警规则 + {rule.tag_name} {rule.rule_type} {rule.limit}")

    # -- I/O 刷新 --------------------------------------------------------
    def _refresh_io(self) -> None:
        if not self.plc.connected:
            return
        for grp in self.io_panel.all_groups():
            names = grp.current_names()
            if not names:
                continue
            try:
                bits = self.plc.read_range_bits(names[0], len(names))
                grp.update_bits({n: bits[i] for i, n in enumerate(names)})
            except Exception as e:
                self._log(f"I/O 刷新失败({names[0]}): {e}")

    # -- 轮询回调 ---------------------------------------------------------
    def _on_plc_state(self, online: bool) -> None:
        """PLC 在线/离线切换（由轮询引擎连续失败计数触发）。"""
        if online:
            from instrument_hub.comm_state import mark_ok
            mark_ok(self)   # PLC 恢复响应，自动恢复在线
            self._log("PLC 已恢复响应")
        else:
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)   # PLC 无响应：状态灯回灰（链路仍可能连接）
            self._log("PLC 连续 5 轮无响应，已标记离线（链路仍连接）")

    def _on_tags_updated(self) -> None:
        tags = self.engine.get_tags()
        if any(t.ok for t in tags):
            from instrument_hub.comm_state import mark_ok
            mark_ok(self)   # 有标签读取成功 = 通讯真正建立；全失败不点绿灯
        self.reg_panel.update_values(tags)
        now = time.time()
        for t in tags:
            if t.name in self.trend.series and t.value is not None:
                try:
                    self.trend.append(t.name, now, float(t.value))
                except Exception:
                    pass
        # I/O 同步（双栏）
        name_set = set(self.io_panel.all_names())
        bits = {
            t.name: bool(t.value)
            for t in tags
            if t.kind == "bit" and t.name in name_set
        }
        if bits:
            self.io_panel.update_bits(bits)

    def _on_alarm(self, ev: AlarmEvent) -> None:
        self.alarm_panel.append_event(ev)
        self.alarm_panel.update_rule_states(self.engine.alarms)
        self._log(f"报警[{ev.state}] {ev.tag_name} {ev.rule_type} {ev.limit} → {ev.value}")

    def _on_poll_error(self, msg: str) -> None:
        self._log(f"轮询错误: {msg}")

    def _refresh_status(self) -> None:
        st = self.plc.status()
        if st.connected:
            self.st_conn.setText(f"● 已连接 · {st.series}")
            self.st_conn.setStyleSheet("color:#22C55E;")
        else:
            self.st_conn.setText("○ 未连接")
            self.st_conn.setStyleSheet("color:#F59E0B;")
        self.st_poll.setText(
            f"轮询: {self.engine.cycle_count}  {self.engine.last_cycle_ms:.0f}ms"
        )
        self.st_stats.setText(f"TX {st.tx}  RX {st.rx}  ERR {st.err}")
        self.st_tag.setText(f"标签: {len(self.engine.tags)}")
        self.conn.update_stats(st.tx, st.rx, st.err)

        # SM0：运行常 ON → 判断 RUN/STOP
        if st.connected:
            try:
                run = self.plc.read_bit("SM0")
                self.conn.set_run_state(run)
            except Exception:
                self.conn.set_run_state(None)
        else:
            self.conn.set_run_state(None)

        # 持续强制：对抗 PLC 程序扫描覆盖
        if st.connected and self.conn.chk_force.isChecked() and self._force_table:
            for n, v in list(self._force_table.items()):
                try:
                    self.plc.write_bit(n, v)
                except Exception as e:
                    self._log(f"持续强制失败 {n}: {e}")
                    break

        # 连接时常刷 I/O（仅 I/O 页，减轻负载）
        if st.connected and self.stack.currentIndex() == 0:
            self._refresh_io()

    def _trend_window_changed(self, idx: int) -> None:
        self.trend.set_window([30, 60, 120, 300, 600][idx])

    def _log(self, msg: str) -> None:
        """线程安全：轮询线程 / 主线程均可调用。"""
        self._log_sig.emit(msg)

    def _append_log(self, msg: str) -> None:
        """仅主线程调用，真正写日志控件。"""
        ts = time.strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {msg}")

    def _on_frame(self, direction: str, data: bytes) -> None:
        """Modbus 帧日志（可能来自轮询线程）。"""
        if not data:
            self._log(f"{direction}  (无数据/超时)")
            return
        hexpart = " ".join(f"{b:02X}" for b in data)
        if len(hexpart) > 72:
            hexpart = hexpart[:72] + "…"
        self._log(f"{direction}  {hexpart}")

    def _export_history(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出历史数据", "xinje_history.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            n = self.engine.export_history_csv(path)
            self._log(f"已导出 {n} 条历史 → {path}")
            QMessageBox.information(self, "导出成功", f"已导出 {n} 条记录")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _load_cfg_tags(self) -> None:
        for t in self.cfg.tags:
            name = t.get("name")
            if name:
                self.reg_panel._add_row(name, t.get("kind"))

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.engine.stop()
            # 安全闭环：退出前清除持续强制（防输出保持 ON 离开现场）
            if self._force_table and self.plc.connected:
                self.conn.chk_force.setChecked(False)
                for _name in list(self._force_table.keys()):
                    try:
                        self.plc.force_bit(_name, False)
                    except Exception:
                        pass
                self._force_table.clear()
            self.plc.disconnect()
        except Exception:
            pass
        self.cfg.tags = []
        for r in range(self.reg_panel.table.rowCount()):
            name_item = self.reg_panel.table.item(r, 0)
            kind_item = self.reg_panel.table.item(r, 2)
            if name_item:
                self.cfg.tags.append({
                    "name": name_item.text(),
                    "kind": kind_item.text() if kind_item else "word",
                })
        try:
            save_config(self.cfg)
        except Exception:
            pass
        super().closeEvent(event)


def run() -> int:
    import sys
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(run())
