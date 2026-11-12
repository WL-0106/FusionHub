# -*- coding: utf-8 -*-
"""汇川 EASY300/EASY500 PLC 上位机 · 融合版界面（FusionHub 风格）。

复用原上位机纯逻辑层（Modbus 协议栈/传输/地址映射/后台轮询/配置，零改动），
界面按整体 UI 风格重建：连接配置 → I/O 灯阵（Y/M 可强制）→ D 寄存器读写 → 通讯日志。
强制输出走二次确认弹窗（直接作用现场设备）。
"""
import queue
import time

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QScrollArea, QSpinBox, QSplitter, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog
from instrument_hub.widgets import Card

from .host.core.address_map import DeviceProfile
from .host.core.config import load_config, save_config
from .host.core.poller import Poller, Snapshot
from .host.protocol.client import ModbusClient
from .host.protocol.transport import (SerialTransport, TcpTransport,
                                      TransportError, list_serial_ports)


class Lamp(QWidget):
    """指示灯单元：圆灯 + 软元件名 + 强制角标；可选点击强制。"""

    clicked = pyqtSignal(object)

    def __init__(self, name: str, color: str, forceable: bool, parent=None):
        super().__init__(parent)
        self.color = color
        self.name = name
        self.forceable = forceable
        self._on = False
        v = QVBoxLayout(self)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(1)
        self.bulb = QLabel()
        self.bulb.setFixedSize(14, 14)
        self.bulb.setAlignment(Qt.AlignCenter)
        v.addWidget(self.bulb, 0, Qt.AlignHCenter)
        self.lbl = QLabel(name)
        self.lbl.setAlignment(Qt.AlignCenter)
        self.lbl.setStyleSheet("color:#6B7280; font-size:8pt;")
        v.addWidget(self.lbl)
        if forceable:
            badge = QLabel("强制")
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(f"color:{color}; font-size:7pt;")
            v.addWidget(badge)
        self.set_on(False)

    def set_on(self, on: bool):
        if self._on == on:
            return
        self._on = on
        bg = self.color if on else "#E5E7EB"
        border = self.color if on else "#D1D5DB"
        self.bulb.setStyleSheet(
            f"background:{bg}; border:1px solid {border}; border-radius:7px;")

    def mousePressEvent(self, ev):
        if self.forceable and ev.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(ev)


class Worker(QThread):
    """阻塞式 Modbus 操作的单线程执行器。"""

    sig_result = pyqtSignal(object, object, object)   # ctx, result, error

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = queue.Queue()
        self._running = False

    def submit(self, fn, ctx=None):
        self._q.put((fn, ctx))

    def run(self):
        self._running = True
        while self._running:
            try:
                fn, ctx = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if fn is None:
                break
            try:
                self.sig_result.emit(ctx, fn(), None)
            except Exception as e:  # noqa: BLE001
                self.sig_result.emit(ctx, None, e)

    def stop(self):
        self._running = False
        self._q.put((None, None))
        self.wait(3000)


class EasyPlcPage(QWidget):
    """汇川 EASY300/500 控制：连接 → I/O 监控/强制 → D 寄存器 → 通信诊断。"""

    snap_sig = pyqtSignal(object)      # Poller 线程 → UI 线程
    comm_sig = pyqtSignal(str, str)    # direction, hex-text
    plc_state_sig = pyqtSignal(bool)   # Poller 线程 → UI 线程（True=在线, False=离线）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = load_config()
        self.client: ModbusClient = None
        self.poller: Poller = None
        self._plc_run = None
        self._lamps = {"X": [], "Y": [], "M": []}
        self._lamp_cells = []

        self.worker = Worker(self)
        self.worker.sig_result.connect(self._on_result)
        self.worker.start()
        self.snap_sig.connect(self._apply_snapshot)
        self.comm_sig.connect(self._on_comm_log)
        self.plc_state_sig.connect(self._on_plc_state)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        tv.addWidget(self._build_conn_card())

        mid = QSplitter(Qt.Horizontal)
        mid.addWidget(self._build_io_card())
        mid.addWidget(self._build_d_card())
        mid.setStretchFactor(0, 3)
        mid.setStretchFactor(1, 2)
        mid.setCollapsible(0, False)
        mid.setCollapsible(1, False)
        tv.addWidget(mid, 1)

        split.addWidget(top)
        split.addWidget(self._build_log_group())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        root.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------------------------------------------------------- 连接卡
    def _build_conn_card(self) -> Card:
        card = Card("连接配置",
                    "汇川 EASY300/EASY500 小型 PLC · Modbus RTU(RS-485)/TCP(502) · "
                    "X/Y 八进制编号，M/D 十进制编号")
        g = QGridLayout()
        g.setSpacing(8)
        g.setVerticalSpacing(10)

        # 第一行：系列/模式/站号/轮询/运行状态（标签紧贴控件、富余空间推到行尾）
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("系列"))
        self.cmb_series = QComboBox()
        self.cmb_series.addItems(["EASY300", "EASY500"])
        self.cmb_series.setCurrentText(self.cfg.series)
        self.cmb_series.setFixedWidth(110)
        self.cmb_series.currentTextChanged.connect(self._on_series_change)
        top.addWidget(self.cmb_series)

        top.addWidget(QLabel("模式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["TCP", "RTU"])
        self.cmb_mode.setCurrentText(self.cfg.mode)
        self.cmb_mode.setFixedWidth(80)
        self.cmb_mode.currentTextChanged.connect(self._on_mode_change)
        top.addWidget(self.cmb_mode)

        top.addWidget(QLabel("站号"))
        self.sp_slave = QSpinBox()
        self.sp_slave.setRange(0, 247)
        self.sp_slave.setValue(self.cfg.slave)
        self.sp_slave.setFixedWidth(70)
        top.addWidget(self.sp_slave)

        top.addWidget(QLabel("轮询(s)"))
        self.ed_interval = QLineEdit(str(self.cfg.poll_interval))
        self.ed_interval.setFixedWidth(60)
        top.addWidget(self.ed_interval)

        self.lbl_run = QLabel("PLC —")
        self.lbl_run.setStyleSheet(
            "padding:3px 12px; border-radius:6px; background:#E5E7EB;"
            " color:#6B7280; font-weight:700;")
        top.addWidget(self.lbl_run)
        top.addStretch(1)
        g.addLayout(top, 0, 0)

        # 第二行：TCP / RTU 参数（互斥显示，HBox 下隐藏后自动前移）
        mid = QHBoxLayout()
        mid.setSpacing(6)
        self.w_tcp = QWidget()
        th = QHBoxLayout(self.w_tcp)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(6)
        th.addWidget(QLabel("IP"))
        self.ed_host = QLineEdit(self.cfg.host)
        self.ed_host.setFixedWidth(150)
        th.addWidget(self.ed_host)
        th.addWidget(QLabel("端口"))
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(self.cfg.port)
        self.sp_port.setFixedWidth(80)
        th.addWidget(self.sp_port)
        mid.addWidget(self.w_tcp)

        self.w_rtu = QWidget()
        rh = QHBoxLayout(self.w_rtu)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(6)
        rh.addWidget(QLabel("串口"))
        self.cmb_com = QComboBox()
        self.cmb_com.setEditable(False)
        self.cmb_com.setFixedWidth(150)
        rh.addWidget(self.cmb_com)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_com_ports)
        rh.addWidget(self.btn_refresh)
        rh.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["1200", "2400", "4800", "9600", "19200",
                                "38400", "57600", "115200"])
        self.cmb_baud.setCurrentText(str(self.cfg.baudrate))
        self.cmb_baud.setFixedWidth(90)
        rh.addWidget(self.cmb_baud)
        rh.addWidget(QLabel("校验"))
        self.cmb_parity = QComboBox()
        self.cmb_parity.addItems(["N", "E", "O"])
        self.cmb_parity.setCurrentText(self.cfg.parity)
        self.cmb_parity.setFixedWidth(60)
        rh.addWidget(self.cmb_parity)
        rh.addWidget(QLabel("停止位"))
        self.cmb_stop = QComboBox()
        self.cmb_stop.addItems(["1", "2"])
        self.cmb_stop.setCurrentText(str(int(self.cfg.stopbits)))
        self.cmb_stop.setFixedWidth(60)
        rh.addWidget(self.cmb_stop)
        mid.addWidget(self.w_rtu)
        mid.addStretch(1)
        g.addLayout(mid, 1, 0)

        # 第三行：按钮 + 状态
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.clicked.connect(self._on_connect)
        row.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("断开")
        self.btn_disc.clicked.connect(self._on_disconnect)
        self.btn_disc.setEnabled(False)
        row.addWidget(self.btn_disc)
        b_save = QPushButton("保存配置")
        b_save.clicked.connect(self._on_save_cfg)
        row.addWidget(b_save)
        self.chk_force = QCheckBox("允许强制输出（Y / M）")
        self.chk_force.setStyleSheet("color:#B45309; font-weight:700;")
        row.addWidget(self.chk_force)
        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("Muted")
        row.addWidget(self.lbl_hint)
        row.addStretch(1)
        self.lbl_stats = QLabel("TX 0   RX 0   ERR 0")
        self.lbl_stats.setObjectName("Muted")
        row.addWidget(self.lbl_stats)
        g.addLayout(row, 2, 0)
        card.body_lay.addLayout(g)

        self._refresh_com_ports()
        self._on_mode_change(self.cmb_mode.currentText())
        return card

    def _on_series_change(self, text):
        prof = DeviceProfile.of(text)
        self.cmb_baud.setCurrentText(str(prof.default_baud))
        if hasattr(self, "sp_x"):
            self.sp_x.setValue(prof.x_points)
            self.sp_y.setValue(prof.y_points)
            self.sp_m.setValue(min(prof.m_points, 64))
            self._rebuild_lamps()
        self._log(f"已切换系列 {text}（默认波特率 {prof.default_baud}）", "#A78BFA")

    def _on_mode_change(self, text):
        self.w_tcp.setVisible(text == "TCP")
        self.w_rtu.setVisible(text != "TCP")

    def _refresh_com_ports(self):
        cur = self.cmb_com.currentText()
        self.cmb_com.clear()
        try:
            ports = list_serial_ports()
        except Exception:
            ports = []
        for p in ports:
            self.cmb_com.addItem(p)
        if not ports:
            self.cmb_com.addItem("COM1")
        if cur in ports:
            self.cmb_com.setCurrentText(cur)
        elif self.cfg.com_port in ports:
            self.cmb_com.setCurrentText(self.cfg.com_port)
        elif ports:
            self.cmb_com.setCurrentText(ports[0])
        elif cur:
            self.cmb_com.setCurrentText(cur)

    def _on_save_cfg(self):
        cfg = self._collect_cfg()
        try:
            save_config(cfg)
            self._log("配置已保存", "#10B981")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def _collect_cfg(self):
        cfg = self.cfg
        cfg.mode = self.cmb_mode.currentText()
        cfg.series = self.cmb_series.currentText()
        cfg.host = self.ed_host.text().strip()
        cfg.port = self.sp_port.value()
        cfg.com_port = self.cmb_com.currentText().strip()
        cfg.baudrate = int(self.cmb_baud.currentText())
        cfg.parity = self.cmb_parity.currentText()
        cfg.stopbits = float(self.cmb_stop.currentText())
        cfg.slave = self.sp_slave.value()
        try:
            cfg.poll_interval = max(0.1, float(self.ed_interval.text()))
        except ValueError:
            pass
        if self.sp_x is not None:
            cfg.x_count = self.sp_x.value()
            cfg.y_count = self.sp_y.value()
            cfg.m_count = self.sp_m.value()
        cfg.d_count = self.sp_d_count.value()
        return cfg

    # ---------------------------------------------------------- I/O 灯阵
    def _build_io_card(self) -> Card:
        card = Card("I/O 实时状态",
                    "X 输入只读 · Y 输出 / M 辅助可强制（需勾选允许并二次确认）")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.sp_x = QSpinBox()
        self.sp_y = QSpinBox()
        self.sp_m = QSpinBox()
        self.sp_d_count = QSpinBox()
        for sp, label, val, hi in ((self.sp_x, "X 点数", self.cfg.x_count, 256),
                                   (self.sp_y, "Y 点数", self.cfg.y_count, 256),
                                   (self.sp_m, "M 点数", min(self.cfg.m_count, 64), 512)):
            row.addWidget(QLabel(label))
            sp.setRange(1, hi)
            sp.setValue(val)
            sp.setFixedWidth(64)
            row.addWidget(sp)
        b_apply = QPushButton("应用")
        b_apply.clicked.connect(self._apply_io_counts)
        row.addWidget(b_apply)
        row.addStretch(1)
        card.body_lay.addLayout(row)

        g = QGridLayout()
        g.setSpacing(8)
        self._io_body = {}
        for col, (key, title, sub, color) in enumerate((
                ("X", "X 输入", "只读 · 现场输入", "#0891B2"),
                ("Y", "Y 输出", "可强制 · 现场输出", "#D97706"),
                ("M", "M 辅助", "可强制 · 内部继电器", "#7C3AED"))):
            box = QGroupBox(f"{title}　{sub}")
            lay = QGridLayout(box)
            lay.setSpacing(2)
            self._io_body[key] = (box, lay)
            g.addWidget(box, 0, col)
        card.body_lay.addLayout(g, 1)
        self._rebuild_lamps(self.cfg.x_count, min(self.cfg.y_count, 64),
                            min(self.cfg.m_count, 64))
        return card

    def _rebuild_lamps(self, x_count=None, y_count=None, m_count=None):
        counts = {"X": x_count or self.sp_x.value(),
                  "Y": y_count or self.sp_y.value(),
                  "M": m_count or self.sp_m.value()}
        colors = {"X": "#0891B2", "Y": "#D97706", "M": "#7C3AED"}
        for key, (box, lay) in self._io_body.items():
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            self._lamps[key].clear()
            n = counts[key]
            for i in range(n):
                name = f"{key}{i:o}" if key in ("X", "Y") else f"{key}{i}"
                lamp = Lamp(name, colors[key], forceable=(key != "X"))
                if key != "X":
                    lamp.clicked.connect(self._on_lamp_click)
                lay.addWidget(lamp, i // 8, i % 8)
                self._lamps[key].append(lamp)

    def _apply_io_counts(self):
        self._rebuild_lamps()
        self._collect_cfg()
        if self.poller:
            self.poller.update_params(
                self.cfg.slave, self.cfg.x_count, self.cfg.y_count,
                self.cfg.m_count, self.cfg.d_count, self.cfg.poll_interval)
        self._log(f"IO 点数 X={self.sp_x.value()} Y={self.sp_y.value()} "
                  f"M={self.sp_m.value()}", "#A78BFA")

    def _on_lamp_click(self, lamp: Lamp):
        if self.client is None or not self.client.connected:
            QMessageBox.warning(self, "未连接", "请先连接 PLC")
            return
        if not self.chk_force.isChecked():
            QMessageBox.warning(self, "禁止强制", "请先勾选「允许强制输出」")
            return
        prefix = lamp.name[0]
        idx = int(lamp.name[1:], 8 if prefix in ("X", "Y") else 10)
        addr = 0xFC00 + idx if prefix == "Y" else idx
        new_state = not lamp._on
        dlg = ConfirmOutputDialog(
            "汇川 EASY300/500 PLC", f"强制 {lamp.name} → "
            f"{'ON' if new_state else 'OFF'}",
            "强制输出会直接作用于现场设备！操作前请确认工艺安全，"
            "并保持急停回路有效。",
            f"Modbus 线圈地址 {addr}（0x{addr:04X}）", self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return

        def job():
            self.client.write_coil(self.cfg.slave, addr, new_state)
            return True
        self.worker.submit(job, ("force", lamp, new_state, addr))

    # ---------------------------------------------------------- D 寄存器
    def _build_d_card(self) -> Card:
        card = Card("D 数据寄存器", "批量读取 · 单点写入 · DEC/HEX/有符号显示")
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("起始"))
        self.ed_d_start = QLineEdit("0")
        self.ed_d_start.setFixedWidth(64)
        row.addWidget(self.ed_d_start)
        row.addWidget(QLabel("数量"))
        self.sp_d_count = QSpinBox()
        self.sp_d_count.setRange(1, 125)
        self.sp_d_count.setValue(self.cfg.d_count)
        self.sp_d_count.setFixedWidth(64)
        row.addWidget(self.sp_d_count)
        b_rd = QPushButton("读取")
        b_rd.clicked.connect(self._on_read_d)
        row.addWidget(b_rd)
        row.addStretch(1)
        card.body_lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("写 D"))
        self.ed_w_addr = QLineEdit("0")
        self.ed_w_addr.setFixedWidth(64)
        row2.addWidget(self.ed_w_addr)
        row2.addWidget(QLabel("值"))
        self.ed_w_val = QLineEdit("0")
        self.ed_w_val.setFixedWidth(90)
        row2.addWidget(self.ed_w_val)
        b_wr = QPushButton("写入")
        b_wr.clicked.connect(self._on_write_d)
        row2.addWidget(b_wr)
        row2.addStretch(1)
        card.body_lay.addLayout(row2)

        self.tree_d = QTableWidget(0, 4)
        self.tree_d.setHorizontalHeaderLabels(["软元件", "DEC", "HEX", "有符号"])
        self.tree_d.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tree_d.setSelectionBehavior(QTableWidget.SelectRows)
        self.tree_d.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tree_d.cellDoubleClicked.connect(self._on_tree_pick)
        card.body_lay.addWidget(self.tree_d, 1)
        tip = QLabel("双击行可填入写入框")
        tip.setObjectName("Muted")
        card.body_lay.addWidget(tip)
        return card

    def _on_read_d(self):
        if self.client is None or not self.client.connected:
            QMessageBox.warning(self, "未连接", "请先连接 PLC")
            return
        start = _safe_int(self.ed_d_start.text(), 0)
        count = max(1, min(_safe_int(str(self.sp_d_count.value()), 64), 125))
        slave = self.sp_slave.value()

        def job():
            return self.client.read_registers(slave, start, count)
        self.worker.submit(job, ("read_d", start))

    def _fill_d_table(self, start: int, vals):
        self.tree_d.setRowCount(len(vals))
        for i, v in enumerate(vals):
            signed = v - 0x10000 if v >= 0x8000 else v
            for c, text in enumerate((f"D{start + i}", str(v),
                                      f"0x{v:04X}", str(signed))):
                self.tree_d.setItem(i, c, QTableWidgetItem(text))

    def _on_tree_pick(self, row, _col):
        dev = self.tree_d.item(row, 0).text()
        self.ed_w_addr.setText(dev[1:] if dev.startswith("D") else dev)
        self.ed_w_val.setText(self.tree_d.item(row, 1).text())
        self._log(f"已选中 {dev}={self.tree_d.item(row, 1).text()}", "#6B7280")

    def _on_write_d(self):
        if self.client is None or not self.client.connected:
            QMessageBox.warning(self, "未连接", "请先连接 PLC")
            return
        addr = _safe_int(self.ed_w_addr.text(), 0)
        raw = self.ed_w_val.text().strip()
        try:
            val = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 10)
        except ValueError:
            QMessageBox.critical(self, "数值无效", "数值无效")
            return
        val &= 0xFFFF
        slave = self.sp_slave.value()

        def job():
            self.client.write_register(slave, addr, val)
            return True
        self.worker.submit(job, ("write_d", addr, val))

    # ---------------------------------------------------------- 通讯日志
    def _build_log_group(self) -> QWidget:
        box = QGroupBox("通信日志（TX/RX 十六进制报文 + 统计）")
        v = QVBoxLayout(box)
        v.setSpacing(6)
        h = QHBoxLayout()
        self.chk_scroll = QCheckBox("自动滚动")
        self.chk_scroll.setChecked(True)
        h.addWidget(self.chk_scroll)
        h.addStretch(1)
        b_save = QPushButton("保存日志")
        b_save.clicked.connect(self._save_log)
        h.addWidget(b_save)
        b_clr = QPushButton("清空")
        b_clr.clicked.connect(lambda: self.txt_log.clear())
        h.addWidget(b_clr)
        v.addLayout(h)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("font-family:Consolas;")
        self.txt_log.setMinimumHeight(110)
        v.addWidget(self.txt_log)
        return box

    def _on_comm_log(self, direction, text):
        colors = {"TX": "#0F766E", "RX": "#1D4ED8", "ERR": "#D20A34"}
        self._log(f"{direction} {text}", colors.get(direction, "#6B7280"))

    def _log(self, msg, color="#111827"):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.appendHtml(
            f'<span style="color:#9CA3AF">[{ts}]</span> '
            f'<span style="color:{color}">{msg}</span>')
        if self.txt_log.blockCount() > 1500:
            doc = self.txt_log.document()
            doc.setPlainText(self.txt_log.toPlainText()[-20000:])
        if self.chk_scroll.isChecked():
            sb = self.txt_log.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _save_log(self):
        import datetime
        import os
        path = os.path.join(
            os.environ.get("TEMP", "."),
            f"easy_plc_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_log.toPlainText())
            self._log(f"日志已保存 → {path}", "#10B981")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ---------------------------------------------------------- 连接管理
    def _on_connect(self):
        if self.client is not None and self.client.connected:
            return
        cfg = self._collect_cfg()
        slave = cfg.slave
        page = self

        def do_connect():
            if cfg.mode == "TCP":
                transport = TcpTransport(cfg.host, cfg.port, unit_id=slave)
            else:
                transport = SerialTransport(
                    cfg.com_port, baudrate=cfg.baudrate,
                    bytesize=cfg.bytesize, parity=cfg.parity,
                    stopbits=cfg.stopbits, slave=slave)
            client = ModbusClient(transport, log=lambda d, t, r: page.comm_sig.emit(
                d, " ".join(f"{b:02X}" for b in r) if r else t))
            client.connect()
            ok = client.ping(slave)
            return (client, ok)

        self.btn_conn.setEnabled(False)
        self._log(f"正在连接 {cfg.mode} ...", "#B45309")
        self.worker.submit(do_connect, ("connect",))

    def _on_result(self, ctx, result, error):
        kind = ctx[0] if isinstance(ctx, tuple) else ctx
        if error is not None:
            if kind == "connect":
                self.btn_conn.setEnabled(True)
                QMessageBox.critical(self, "连接失败", str(error))
                self._log(f"连接失败: {error}", "#D20A34")
            else:
                QMessageBox.critical(self, "操作失败", str(error))
                self._log(f"失败: {error}", "#D20A34")
            return

        if kind == "connect":
            client, ok = result
            from instrument_hub.comm_state import mark_lost, mark_ok
            if ok:
                mark_ok(self)      # ping 应答成功 = 通讯真正建立
            else:
                mark_lost(self)    # 仅链路建立、无应答 = 未连接
            self.client = client
            self.btn_conn.setEnabled(False)
            self.btn_conn.setText("已连接")
            self.btn_conn.setObjectName("btnConnected")
            self.btn_disc.setEnabled(True)
            self.lbl_hint.setText(
                "通信测试：成功" if ok else "通信测试：无响应（仍可继续）")
            self._log(f"连接成功 {client.describe}  ping={'OK' if ok else 'FAIL'}",
                      "#10B981")
            if self.poller:
                self.poller.stop()
            cfg = self._collect_cfg()
            page = self
            self.poller = Poller(
                client=client, slave=cfg.slave,
                x_count=cfg.x_count, y_count=cfg.y_count,
                m_count=min(cfg.m_count, self.sp_m.value()),
                d_count=cfg.d_count, interval=cfg.poll_interval,
                on_snapshot=lambda s: page.snap_sig.emit(s),
                on_log=lambda m: page._log(f"轮询: {m}", "#B45309"),
                on_plc_state=lambda online: page.plc_state_sig.emit(online))
            self.poller.start()
        elif kind == "read_d":
            start = ctx[1]
            self._fill_d_table(start, result)
            self._log(f"D{start}..D{start + len(result) - 1} 读取完成", "#1D4ED8")
        elif kind == "write_d":
            addr, val = ctx[1], ctx[2]
            self._log(f"D{addr} = {val} (0x{val:04X})", "#0F766E")
            self._on_read_d()
        elif kind == "force":
            lamp, new_state, addr = ctx[1], ctx[2], ctx[3]
            lamp.set_on(new_state)
            self._log(f"强制 {lamp.name} → {int(new_state)}  (modbus={addr})",
                      "#B45309")

    def _on_disconnect(self):
        if self.poller:
            try:
                self.poller.stop()
            except Exception:
                pass
            self.poller = None
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 断开连接 = 通讯中断，状态灯回灰
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_disc.setEnabled(False)
        self.lbl_hint.setText("")
        self._set_plc_run(None)
        self._log("已断开连接", "#B45309")

    # ---------------------------------------------------------- 轮询刷新
    def _on_plc_state(self, online: bool):
        """PLC 在线/离线切换（由 Poller 连续失败计数触发）。"""
        from instrument_hub.comm_state import mark_lost, mark_ok
        if online:
            mark_ok(self)   # PLC 恢复响应，自动恢复在线
            self._log("PLC 已恢复响应", "#1D4ED8")
        else:
            mark_lost(self)   # PLC 无响应：状态灯回灰（链路可能仍连接）
            self._log("PLC 连续 5 轮无响应，已标记离线（链路仍连接）", "#D20A34")

    def _apply_snapshot(self, snap: Snapshot):
        if snap.error:
            self.lbl_hint.setText(f"轮询错误: {snap.error}")
            return   # 错误快照不点绿灯，离线由 _on_plc_state 处理
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 轮询数据到达 = 通讯真正建立
        for key, values in (("X", snap.x), ("Y", snap.y), ("M", snap.m)):
            lamps = self._lamps[key]
            if len(values) == len(lamps):
                for lamp, v in zip(lamps, values):
                    lamp.set_on(bool(v))
        if snap.plc_run is not None:
            self._set_plc_run(snap.plc_run)
        if snap.d and self.tree_d.rowCount() == 0:
            start = _safe_int(self.ed_d_start.text(), 0)
            self._fill_d_table(start, snap.d)

    def _set_plc_run(self, state):
        self._plc_run = state
        if state is None:
            self.lbl_run.setText("PLC —")
            self.lbl_run.setStyleSheet(
                "padding:3px 12px; border-radius:6px; background:#E5E7EB;"
                " color:#6B7280; font-weight:700;")
        elif state:
            self.lbl_run.setText("PLC  RUN")
            self.lbl_run.setStyleSheet(
                "padding:3px 12px; border-radius:6px; background:#10B981;"
                " color:#FFFFFF; font-weight:700;")
        else:
            self.lbl_run.setText("PLC  STOP")
            self.lbl_run.setStyleSheet(
                "padding:3px 12px; border-radius:6px; background:#EF4444;"
                " color:#FFFFFF; font-weight:700;")

    def _tick(self):
        if self.client is not None and self.client.connected:
            st = self.client.stats
            self.lbl_stats.setText(f"TX {st.tx}   RX {st.rx}   ERR {st.err}")

    # ---------------------------------------------------------- 清理
    def shutdown(self):
        """退出闭环：停轮询 → 断链 → 回收线程。"""
        try:
            self._timer.stop()
        except Exception:
            pass
        if self.poller:
            try:
                self.poller.stop()
            except Exception:
                pass
            self.poller = None
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        try:
            self.worker.stop()
        except Exception:
            pass


def _safe_int(text, default: int) -> int:
    try:
        return int(str(text).strip(), 0)
    except (ValueError, TypeError):
        return default
