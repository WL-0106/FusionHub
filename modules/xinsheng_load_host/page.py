# -*- coding: utf-8 -*-
"""新胜负载箱上位机 · 融合版界面（FusionHub 风格）。

原上位机（tkinter 单文件）功能全量移植：
连接（串口 RTU / 网络 RTU(TCP) / 模拟从站）→ 风机控制 / 急停 / 加载控制（功率档）/
高级设置 + 右侧实时监控 + 底部通讯日志。

线程模型沿用原版：常驻单工作线程 + 任务队列（代际号作废过期任务），结果经事件队列
回主线程；界面只消费 registers/modbus 语义层，不触碰帧字节。
"""
import os
import queue
import threading
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QRadioButton, QScrollArea, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog

from .core import modbus as mb
from .core.registers import REG_BY_KEY, gear_addr, validate_write
from .core.simulator import TcpSimServer

APP_TITLE = "新胜负载箱上位机"

LOG_MAX_LINES = 3000

MODE_LABELS = {0: "独立", 1: "同步"}


class Led(QWidget):
    """圆形指示灯。"""

    def __init__(self, parent=None, color="#9AA2AA", diameter=12):
        super().__init__(parent)
        self._color = color
        self._d = diameter
        self.setFixedSize(diameter, diameter)

    def set_on(self, on: bool, on_color="#1F9D55", off_color="#9AA2AA"):
        self._color = on_color if on else off_color
        self.update()

    def paintEvent(self, ev):  # noqa: N802
        from PyQt5.QtGui import QColor, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(self._color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, self._d, self._d)


class XinshengLoadPage(QWidget):
    """新胜负载箱控制：连接 → 风机/急停/加载控制 + 实时监控 + 通讯日志。"""

    sig = pyqtSignal(str, object)   # (kind, payload) 工作线程 → 主线程

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected = False
        self.transport = None
        self.client = None
        self._conn_tcp = False
        self._sim: TcpSimServer | None = None
        self._gen = 0
        self.busy = 0
        self.poll_inflight = False
        self._poll_fails = 0
        self._next_poll_t = 0.0
        self._unsupported = set()
        self._closing = False

        self.jobs: "queue.Queue" = queue.Queue()
        self.events: "queue.Queue" = queue.Queue()
        self._worker = threading.Thread(target=self._worker_main, daemon=True,
                                        name="xinsheng-load-worker")
        self._worker.start()

        self.sig.connect(self._handle_event)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        page_lay = QVBoxLayout()   # 嵌套布局：框架日志分割条跳过本页（自管分割条）
        page_lay.setSpacing(8)

        page_lay.addWidget(self._build_conn_card())

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_controls())
        mid.addWidget(self._build_monitor())
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 0)
        mid.setSizes([760, 300])
        bv.addWidget(mid, 1)
        split.addWidget(body)
        split.addWidget(self._build_log_group())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([520, 160])
        page_lay.addWidget(split, 1)
        root.addLayout(page_lay)

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(60)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start()

        self._set_controls_enabled(False)
        self.log("上位机已就绪。协议：新胜负载箱 MODBUS RTU（FC03/FC06，9600 8N1）")
        self.log("提示：没有真机时可选「模拟从站」链路，或另起 "
                 "python -m modules.xinsheng_load_host.core.simulator")

    # ---------------------------------------------------------- 线程模型
    def _worker_main(self):
        while True:
            try:
                job = self.jobs.get(timeout=0.2)
            except queue.Empty:
                if self._closing:
                    return
                continue
            gen, tag, fn, on_ok, on_err, is_poll = job
            if gen != self._gen:
                continue                       # 过期任务作废
            try:
                res = fn()
                self.sig.emit("done", (gen, tag, res, on_ok, on_err, None, is_poll))
            except Exception as e:  # noqa: BLE001
                self.sig.emit("done", (gen, tag, None, on_ok, on_err, "%s" % e, is_poll))

    def _submit(self, tag, fn, on_ok=None, on_err=None, force=False):
        """主线程调用。force=True 用于「连接」本身（此时还没建立连接，必须放行）。"""
        if not self.connected and not force:
            return
        self.busy += 1
        self._show_busy()
        self.jobs.put((self._gen, tag, fn, on_ok, on_err, False))

    def _submit_poll(self):
        if self.poll_inflight:
            return
        self.poll_inflight = True
        gear_mode = self.gear_mode()           # 主线程先取值再带进闭包
        cli = self.client

        def work():
            st = {}
            st["fan_status"], st["overtemp"] = cli.read_regs(2, 2)
            items = [("fan_sw", 1), ("estop", 5), ("sync_mode", 200),
                     ("delay_on", 10), ("delay_off", 20),
                     ("gear_a", gear_addr("A", gear_mode)),
                     ("gear_b", gear_addr("B", gear_mode)),
                     ("gear_c", gear_addr("C", gear_mode))]
            for key, addr in items:
                if key in self._unsupported:
                    continue
                try:
                    st[key] = cli.read_reg(addr)
                except Exception as e:  # noqa: BLE001
                    self._unsupported.add(key)
                    self.sig.emit("log", ("[提示] 轮询项 %s(地址%s) 无响应，之后自动跳过：%s"
                                          % (key, addr, e), True))
            return st

        self.jobs.put((self._gen, "poll", work, None, None, True))

    def _drain(self):
        if self._closing:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self.sig.emit(kind, payload)
        except queue.Empty:
            pass
        # 轮询调度：不占 busy 标志，busy==0 且无在飞轮询时才发
        if (self.connected and not self.poll_inflight and self.busy == 0
                and self.chk_poll.isChecked()):
            period = self._poll_period()
            if time.time() >= self._next_poll_t:
                self._next_poll_t = time.time() + period
                self._submit_poll()

    def _poll_period(self):
        try:
            return max(0.5, float(self.spn_poll.value()))
        except (ValueError, TypeError):
            return 1.5

    def gear_mode(self) -> str:
        return "example" if self.rdo_gear_example.isChecked() else "table"

    # ---------------------------------------------------------- 连接区
    def _build_conn_card(self) -> QWidget:
        box = QGroupBox("连接配置")
        g = QGridLayout(box)
        g.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("模式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["串口 RTU", "网络 RTU (TCP)", "模拟从站"])
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_change)
        top.addWidget(self.cmb_mode)

        self.lbl_port = QLabel("端口")
        top.addWidget(self.lbl_port)
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setStyleSheet("QComboBox{min-width:110px;}")
        top.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_baud = QLabel("波特率")
        top.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        top.addWidget(self.cmb_baud)
        self.lbl_fmt = QLabel("格式")
        top.addWidget(self.lbl_fmt)
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.setEditable(True)
        self.cmb_fmt.addItems(["8N1", "8E1", "8O1", "8N2"])
        self.cmb_fmt.setFixedWidth(78)
        top.addWidget(self.cmb_fmt)

        self.lbl_host = QLabel("主机")
        top.addWidget(self.lbl_host)
        self.ed_host = QLineEdit("127.0.0.1")
        self.ed_host.setFixedWidth(130)
        top.addWidget(self.ed_host)
        self.lbl_tcp_port = QLabel("端口")
        top.addWidget(self.lbl_tcp_port)
        self.spn_tcp_port = QSpinBox()
        self.spn_tcp_port.setRange(1, 65535)
        self.spn_tcp_port.setValue(5026)
        self.spn_tcp_port.setFixedWidth(80)
        top.addWidget(self.spn_tcp_port)

        top.addWidget(QLabel("从站地址"))
        self.spn_slave = QSpinBox()
        self.spn_slave.setRange(1, 247)
        self.spn_slave.setFixedWidth(72)
        top.addWidget(self.spn_slave)
        top.addSpacing(8)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.clicked.connect(self._connect)
        top.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("断开")
        self.btn_disc.setEnabled(False)
        self.btn_disc.clicked.connect(self._disconnect)
        top.addWidget(self.btn_disc)
        self.lbl_lamp = QLabel("○ 未连接")
        self.lbl_lamp.setStyleSheet("color:#6B7280;")
        top.addWidget(self.lbl_lamp)
        self.lbl_busy = QLabel("")
        self.lbl_busy.setStyleSheet("color:#D97706;")
        top.addWidget(self.lbl_busy)
        top.addStretch(1)
        g.addLayout(top, 0, 0)
        self._refresh_ports()
        self._on_mode_change()
        return box

    def _on_mode_change(self):
        mode = self.cmb_mode.currentText()
        serial = mode.startswith("串口")
        tcp = mode.startswith("网络")
        sim = mode == "模拟从站"
        self.lbl_port.setVisible(serial)
        self.cmb_port.setVisible(serial)
        self.btn_refresh.setVisible(serial)
        self.lbl_baud.setVisible(serial)
        self.cmb_baud.setVisible(serial)
        self.lbl_fmt.setVisible(serial)
        self.lbl_host.setVisible(tcp)
        self.ed_host.setVisible(tcp)
        self.lbl_tcp_port.setVisible(tcp or sim)
        self.spn_tcp_port.setVisible(tcp or sim)
        if self.connected:
            self.log("[提示] 通讯模式变更需先断开再连接。")

    def _refresh_ports(self):
        try:
            ports = mb.SerialTransport.list_ports()
        except Exception:  # noqa: BLE001
            ports = []
        cur = self.cmb_port.currentText()
        self.cmb_port.clear()
        self.cmb_port.addItems(ports)
        if ports and not cur:
            self.cmb_port.setCurrentText(ports[0])
        elif cur:
            self.cmb_port.setCurrentText(cur)

    def _conn_desc(self) -> str:
        if self.cmb_mode.currentText().startswith("网络"):
            return "TCP %s:%d" % (self.ed_host.text().strip(), self.spn_tcp_port.value())
        if self.cmb_mode.currentText() == "模拟从站":
            return "模拟从站 127.0.0.1:%d" % self.spn_tcp_port.value()
        return self.cmb_port.currentText()

    # ---------------------------------------------------------- 控制区
    def _build_controls(self) -> QWidget:
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        grid.addWidget(self._card_fan(), 0, 0)
        grid.addWidget(self._card_unload_ctrl(), 0, 1)
        grid.addWidget(self._card_estop(), 1, 0)
        grid.addWidget(self._card_advanced(), 1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return wrap

    def _card_fan(self) -> QGroupBox:
        c = QGroupBox("风机控制")
        v = QVBoxLayout(c)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_fan_on = QPushButton("打开风机")
        self.btn_fan_on.setStyleSheet(
            "QPushButton{background:#1F9D55;color:#FFFFFF;min-width:96px;}"
            "QPushButton:disabled{background:#C8CFD9;color:#FFFFFF;}")
        self.btn_fan_on.clicked.connect(lambda: self._cmd_fan(True))
        row.addWidget(self.btn_fan_on)
        self.btn_fan_off = QPushButton("关闭风机")
        self.btn_fan_off.setStyleSheet(
            "QPushButton{background:#FFFFFF;color:#1F2933;border:1px solid #C8CFD9;"
            "min-width:96px;}QPushButton:disabled{background:#C8CFD9;color:#FFFFFF;}")
        self.btn_fan_off.clicked.connect(lambda: self._cmd_fan(False))
        row.addWidget(self.btn_fan_off)
        row.addStretch(1)
        v.addLayout(row)

        for label, key in (("延时开启(s)", "delay_on"), ("延时关闭(s)", "delay_off")):
            r = QHBoxLayout()
            r.setSpacing(8)
            r.addWidget(QLabel(label))
            sp = QSpinBox()
            sp.setRange(0, 32765)
            sp.setFixedWidth(110)
            setattr(self, "sp_" + key, sp)
            r.addWidget(sp)
            btn = QPushButton("写入")
            btn.setFixedWidth(72)
            btn.clicked.connect(lambda _=False, k=key: self._cmd_delay(k))
            r.addWidget(btn)
            r.addStretch(1)
            v.addLayout(r)
        return c

    def _card_estop(self) -> QGroupBox:
        c = QGroupBox("急停")
        v = QVBoxLayout(c)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_stop = QPushButton("急停（写0）")
        self.btn_stop.setStyleSheet(
            "QPushButton{background:#D64545;color:#FFFFFF;min-width:110px;}"
            "QPushButton:disabled{background:#C8CFD9;color:#FFFFFF;}")
        self.btn_stop.clicked.connect(lambda: self._cmd_estop(0))
        row.addWidget(self.btn_stop)
        self.btn_reset = QPushButton("解除急停（写1）")
        self.btn_reset.setStyleSheet(
            "QPushButton{background:#1F9D55;color:#FFFFFF;min-width:120px;}"
            "QPushButton:disabled{background:#C8CFD9;color:#FFFFFF;}")
        self.btn_reset.clicked.connect(lambda: self._cmd_estop(1))
        row.addWidget(self.btn_reset)
        row.addStretch(1)
        v.addLayout(row)
        hint = QLabel("急停寄存器（地址5）：1=正常，0=急停")
        hint.setStyleSheet("color:#6B7280;")
        v.addWidget(hint)
        return c

    def _card_unload_ctrl(self) -> QGroupBox:
        c = QGroupBox("加载控制（功率档）")
        v = QVBoxLayout(c)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("模式"))
        self.rdo_mode_ind = QRadioButton("独立")
        self.rdo_mode_ind.setChecked(True)
        self.rdo_mode_sync = QRadioButton("同步")
        self.rdo_mode_ind.toggled.connect(self._cmd_mode_toggle)
        self.rdo_mode_sync.toggled.connect(self._cmd_mode_toggle)
        row.addWidget(self.rdo_mode_ind)
        row.addWidget(self.rdo_mode_sync)
        row.addSpacing(12)
        self.btn_unload_all = QPushButton("一键卸载/复位")
        self.btn_unload_all.setStyleSheet(
            "QPushButton{background:#E8890C;color:#FFFFFF;min-width:110px;}"
            "QPushButton:disabled{background:#C8CFD9;color:#FFFFFF;}")
        self.btn_unload_all.clicked.connect(lambda: self._cmd_unload("all"))
        row.addWidget(self.btn_unload_all)
        row.addStretch(1)
        v.addLayout(row)

        grid = QHBoxLayout()
        grid.setSpacing(8)
        self.gear_entries = {}
        for ph in ("A", "B", "C"):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            lab = QLabel(ph + " 相")
            lab.setAlignment(Qt.AlignCenter)
            f = lab.font()
            f.setBold(True)
            lab.setFont(f)
            cell.addWidget(lab)
            sp = QSpinBox()
            sp.setRange(0, 65535)
            sp.setAlignment(Qt.AlignCenter)
            sp.setFixedWidth(110)
            self.gear_entries[ph] = sp
            cell.addWidget(sp, 0, Qt.AlignCenter)
            btn_load = QPushButton("加载写入")
            btn_load.setStyleSheet(
                "QPushButton{background:#1F6FEB;color:#FFFFFF;min-width:100px;}"
                "QPushButton:disabled{background:#C8CFD9;color:#FFFFFF;}")
            btn_load.clicked.connect(lambda _=False, p=ph: self._cmd_gear(p))
            cell.addWidget(btn_load)
            btn_un = QPushButton(ph + "相卸载")
            btn_un.setStyleSheet(
                "QPushButton{background:#FFFFFF;color:#1F2933;border:1px solid #C8CFD9;"
                "min-width:100px;}QPushButton:disabled{background:#C8CFD9;color:#FFFFFF;}")
            btn_un.clicked.connect(lambda _=False, p=ph: self._cmd_unload(p.lower()))
            cell.addWidget(btn_un)
            grid.addLayout(cell, 1)
        v.addLayout(grid)
        hint = QLabel("功率档为 10 倍输入：加载 10Ω 时输入 100（输入框填协议输入值）。"
                      "同步模式下 A 相即三相。")
        hint.setStyleSheet("color:#6B7280;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        return c

    def _card_advanced(self) -> QGroupBox:
        c = QGroupBox("高级设置")
        v = QVBoxLayout(c)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("功率档地址"))
        self.rdo_gear_table = QRadioButton("寄存器表 51/53/55")
        self.rdo_gear_table.setChecked(True)
        self.rdo_gear_example = QRadioButton("手册示例 50/52/54")
        row.addWidget(self.rdo_gear_table)
        row.addWidget(self.rdo_gear_example)
        row.addStretch(1)
        v.addLayout(row)
        hint = QLabel("手册示例帧写 0x32H(=50) 与寄存器表 51 不一致。"
                      "现场「加载写入」无响应或无效时，切换此项再试。")
        hint.setStyleSheet("color:#6B7280;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("轮询周期"))
        self.spn_poll = QDoubleSpinBox()
        self.spn_poll.setRange(0.5, 10.0)
        self.spn_poll.setSingleStep(0.5)
        self.spn_poll.setValue(1.5)
        self.spn_poll.setFixedWidth(90)
        row2.addWidget(self.spn_poll)
        self.chk_poll = QCheckBox("自动轮询")
        self.chk_poll.setChecked(True)
        row2.addWidget(self.chk_poll)
        row2.addStretch(1)
        v.addLayout(row2)
        return c

    # ---------------------------------------------------------- 右侧监控
    def _build_monitor(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(280)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        title = QLabel("实时监控")
        f = title.font()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
        v.addWidget(title)

        self.mon = {}

        def mrow(name, title_text):
            r = QHBoxLayout()
            led = Led()
            r.addWidget(led)
            lab = QLabel(title_text)
            r.addWidget(lab)
            r.addStretch(1)
            val = QLabel("—")
            f2 = val.font()
            f2.setBold(True)
            val.setFont(f2)
            r.addWidget(val)
            v.addLayout(r)
            self.mon[name] = (led, val)

        mrow("fan", "风机状态")
        mrow("temp", "高温报警")
        mrow("estop", "急停（1=正常）")
        mrow("mode", "同步/独立")
        mrow("gear_a", "A相档位回读")
        mrow("gear_b", "B相档位回读")
        mrow("gear_c", "C相档位回读")
        mrow("delay_on", "延时开启(s)")
        mrow("delay_off", "延时关闭(s)")
        v.addSpacing(8)
        self.lbl_poll = QLabel("轮询：未连接")
        self.lbl_poll.setStyleSheet("color:#6B7280;")
        v.addWidget(self.lbl_poll)
        v.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    # ---------------------------------------------------------- 日志
    def _build_log_group(self) -> QGroupBox:
        box = QGroupBox("运行日志")
        lay = QVBoxLayout(box)
        lay.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.chk_hex = QCheckBox("显示通讯报文")
        bar.addWidget(self.chk_hex)
        btn_clr = QPushButton("清空日志")
        btn_clr.setFixedWidth(96)
        btn_clr.clicked.connect(lambda: self.txt_log.clear())
        bar.addWidget(btn_clr)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(LOG_MAX_LINES)
        self.txt_log.setFont(QFont("Consolas", 9))
        lay.addWidget(self.txt_log, 1)
        return box

    def log(self, msg: str, err: bool = False):
        stamp = time.strftime("%H:%M:%S")
        color = "#DC2626" if err else "#6B7280"
        self.txt_log.appendHtml(
            '<span style="color:%s">[%s] %s</span>' % (color, stamp, msg))
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------------------------------------------------------- 连接管理
    def _parse_fmt(self, text):
        t = [c for c in (text or "8N1").strip().upper() if c in "NEOSM"]
        parity = t[0] if t else "N"
        data = int(text[0]) if text and text[0].isdigit() else 8
        stop = int(text[-1]) if text and text[-1] in "12" else 1
        return data, parity, stop

    def _connect(self):
        if self.connected:
            return
        mode = self.cmb_mode.currentText()
        use_tcp = mode.startswith("网络")
        use_sim = mode == "模拟从站"
        if use_tcp or use_sim:
            host = "127.0.0.1" if use_sim else self.ed_host.text().strip()
            tcpport = int(self.spn_tcp_port.value())
            if not host:
                QMessageBox.warning(self, APP_TITLE, "请填写主机地址")
                return
            desc = ("模拟从站 %s:%d" if use_sim else "TCP %s:%d") % (host, tcpport)
        else:
            host, tcpport = None, None
            port = self.cmb_port.currentText().strip()
            if not port:
                QMessageBox.warning(self, APP_TITLE, "请先选择串口")
                return
            desc = str(port)
        slave = int(self.spn_slave.value())
        baud = int(self.cmb_baud.currentText() or 9600)
        dbs, parity, sbit = self._parse_fmt(self.cmb_fmt.currentText())
        hex_on = bool(self.chk_hex.isChecked())
        if not use_tcp and not use_sim:
            self.log("连接 %s @%d %d%s%d，从站地址 %d …" % (port, baud, dbs, parity, sbit, slave))
        else:
            self.log("连接 %s（RTU over TCP），从站地址 %d …" % (desc, slave))

        def work():
            if use_sim:
                if self._sim is None:
                    self._sim = TcpSimServer(host="127.0.0.1", port=tcpport).start()
                tr = mb.TcpTransport(host, tcpport, timeout=0.6)
            elif use_tcp:
                tr = mb.TcpTransport(host, tcpport, timeout=0.6)
            else:
                tr = mb.SerialTransport(port, baud=baud, bytesize=dbs, parity=parity,
                                        stopbits=sbit, timeout=0.6)
            cli = mb.LoadBankClient(tr, slave=slave,
                                    trace=lambda tx, rx, note="":
                                        self._trace(tx, rx, hex_on))
            ok = cli.ping()
            return tr, cli, ok

        def on_ok(res):
            tr, cli, ok = res
            self.transport, self.client = tr, cli
            self.connected = True
            self._conn_tcp = use_tcp or use_sim
            self._unsupported.clear()
            self._poll_fails = 0
            self._next_poll_t = 0.0
            self.btn_conn.setEnabled(False)
            self.btn_conn.setObjectName("btnConnected")
            self.btn_conn.setText("已连接")
            self.btn_conn.style().unpolish(self.btn_conn)
            self.btn_conn.style().polish(self.btn_conn)
            self.btn_disc.setEnabled(True)
            self.lbl_lamp.setText("● 已连接 %s" % self._conn_desc())
            self.lbl_lamp.setStyleSheet("color:#047857;")
            self._set_controls_enabled(True)
            self.log("已连接（%s）。" % ("RTU over TCP" if self._conn_tcp else "串口 RTU"))
            if not ok:
                self.log("[提示] 链路已建立但未收到设备应答，请核对接线/透传映射与从站地址。",
                         err=True)

        def on_err(e):
            self.log("[失败] 连接：%s" % e, err=True)
            QMessageBox.critical(self, APP_TITLE, "连接失败：\n%s" % e)

        self._submit("connect", work, on_ok, on_err, force=True)

    def _disconnect(self):
        """断开是逃生通道：不检查忙标志，直接复位状态 + 关链路，过期任务作废。"""
        if not self.connected and self.transport is None:
            return
        self._gen += 1
        self._drain_jobs()
        try:
            if self.transport:
                self.transport.close()
        except Exception:  # noqa: BLE001
            pass
        self.transport = None
        self.client = None
        self.connected = False
        self.busy = 0
        self.poll_inflight = False
        self._poll_fails = 0
        self.btn_conn.setEnabled(True)
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.setText("连接")
        self.btn_conn.style().unpolish(self.btn_conn)
        self.btn_conn.style().polish(self.btn_conn)
        self.btn_disc.setEnabled(False)
        self.lbl_lamp.setText("○ 未连接")
        self.lbl_lamp.setStyleSheet("color:#6B7280;")
        self._show_busy()
        self._set_controls_enabled(False)
        self._reset_monitor()
        self.lbl_poll.setText("轮询：未连接")
        self.log("已断开。")
        if self._sim is not None:
            try:
                self._sim.stop()
            except Exception:  # noqa: BLE001
                pass
            self._sim = None

    def _drain_jobs(self):
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                return

    def _show_busy(self):
        self.lbl_busy.setText("执行中…" if self.busy else "")
        self._set_controls_enabled(self.busy == 0 and self.connected)

    # ---------------------------------------------------------- 事件处理
    def _handle_event(self, kind, payload):
        # 槽内异常会触发 Qt abort（0xC0000409），这里兜底：出错只记日志不崩进程
        try:
            self._handle_event_inner(kind, payload)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.log("[内部错误] 事件处理异常：%s" % e, err=True)

    def _handle_event_inner(self, kind, payload):
        if kind == "done":
            gen, tag, res, on_ok, on_err, err, is_poll = payload
            if is_poll:
                self.poll_inflight = False
                if err is not None:
                    self._poll_fails += 1
                    if self._poll_fails >= 3:
                        self.log("[轮询] 连续失败 %d 次，最近错误：%s" % (self._poll_fails, err),
                                 err=True)
                else:
                    self._poll_fails = 0
                    self._apply_status(res)
            else:
                self.busy = max(0, self.busy - 1)
                self._show_busy()
                if err is not None:
                    self.log("[失败] %s：%s" % (tag, err), err=True)
                    if on_err is not None:
                        on_err(err)
                elif on_ok is not None:
                    on_ok(res)
            self.lbl_poll.setText(
                "轮询：未连接" if not self.connected else
                ("轮询：正常（每 %ss）" % ("%g" % self._poll_period())
                 if self._poll_fails < 3 else "轮询：连续失败"))
        elif kind == "log":
            line, err = payload
            self.log(line, err=err)

    def _apply_status(self, st):
        if not st:
            return
        led, val = self.mon["fan"]
        led.set_on(bool(st.get("fan_status")))
        val.setText("打开" if st.get("fan_status") else "关闭")
        led, val = self.mon["temp"]
        ot = bool(st.get("overtemp"))
        led.set_on(ot, on_color="#D64545")
        val.setText("报警！" if ot else "正常")
        val.setStyleSheet("color:#D64545;" if ot else "")
        est = st.get("estop")
        if est is not None:
            led, val = self.mon["estop"]
            led.set_on(est == 0, on_color="#D64545")
            val.setText("急停" if est == 0 else "正常")
            val.setStyleSheet("color:#D64545;" if est == 0 else "")
        mode = st.get("sync_mode")
        if mode is not None:
            led, val = self.mon["mode"]
            led.set_on(mode == 1, on_color="#1F6FEB")
            val.setText("同步" if mode == 1 else "独立")
        for k in ("gear_a", "gear_b", "gear_c"):
            v = st.get(k)
            self.mon[k][1].setText("—" if v is None else "%d (≈%.1f 档)" % (v, v / 10.0))
        for k in ("delay_on", "delay_off"):
            v = st.get(k)
            self.mon[k][1].setText("—" if v is None else str(v))

    def _reset_monitor(self):
        for led, val in self.mon.values():
            led.set_on(False)
            val.setText("—")
            val.setStyleSheet("")

    def _trace(self, tx, rx, hex_on):
        if hex_on:
            line = "&gt;&gt; " + mb.hexs(tx)
            if rx:
                line += "&nbsp;&nbsp;&nbsp;&nbsp;&lt;&lt; " + mb.hexs(rx)
            self.sig.emit("log", (line, False))

    # ---------------------------------------------------------- 指令
    def _cmd_fan(self, on: bool):
        cli = self.client
        if cli is None:
            return
        label = "打开风机" if on else "关闭风机"

        def work():
            return mb.confirm_fan(cli, on)

        def on_ok(res):
            ok, cur = res
            if ok:
                self.log("%s：已确认（风机状态寄存器2=%d）。" % (label, cur))
            else:
                self.log("%s：指令已下发，状态回读暂未确认（当前 %s），轮询会继续刷新。"
                         % (label, cur))

        self._submit(label, work, on_ok)

    def _cmd_estop(self, on: int):
        cli = self.client
        if cli is None:
            return
        label = "解除急停（写1）" if on else "急停（写0）"
        if on:
            # 解除急停 = 释放安全互锁（保护复位类），须二次确认
            dlg = ConfirmOutputDialog(
                "新胜负载箱", "解除急停（写1）",
                "急停寄存器语义为 1=正常 / 0=急停。解除后输出回路恢复可操作状态，"
                "确认现场安全条件已具备、人员已知晓。",
                "寄存器 5 ← 1", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return

        def work():
            return mb.write_and_confirm(cli, 5, on)

        def on_ok(res):
            ok, cur = res
            if ok:
                self.log("%s：已确认（寄存器5=%d）。" % (label, on))
            else:
                self.log("%s：指令已下发，回读暂未确认（当前回读 %s）。" % (label, cur))

        self._submit(label, work, on_ok)

    def _cmd_mode_toggle(self, _checked=False):
        if not self.rdo_mode_sync.isChecked() and not self.rdo_mode_ind.isChecked():
            return
        cli = self.client
        if cli is None:
            return
        mode = 1 if self.rdo_mode_sync.isChecked() else 0
        label = "切换为同步（写1）" if mode else "切换为独立（写0）"

        def work():
            return mb.write_and_confirm(cli, 200, mode)

        def on_ok(res):
            ok, cur = res
            if ok:
                self.log("%s：已确认（寄存器200=%d）。" % (label, mode))
            else:
                self.log("%s：指令已下发，回读暂未确认（当前回读 %s）。" % (label, cur))

        self._submit(label, work, on_ok)

    def _cmd_delay(self, key: str):
        cli = self.client
        if cli is None:
            return
        sp = getattr(self, "sp_" + key)
        raw = int(sp.value())
        r = REG_BY_KEY[key]
        try:
            addr = validate_write(key, raw)
        except ValueError as e:
            QMessageBox.warning(self, APP_TITLE, str(e))
            return

        def work():
            cli.write_reg(addr, raw)
            cur = cli.read_reg(addr)
            return raw, cur

        def on_ok(res):
            raw, cur = res
            if cur == raw:
                self.log("%s：已写入 %d，回读一致。" % (r.name, raw))
            else:
                self.log("%s：已写入 %d，但回读为 %s。" % (r.name, raw, cur), err=True)

        self._submit(r.name, work, on_ok)

    def _cmd_gear(self, phase: str):
        cli = self.client
        if cli is None:
            return
        key = "gear_" + phase.lower()
        raw = int(self.gear_entries[phase].value())
        gear_mode = self.gear_mode()           # 主线程取值
        try:
            addr = validate_write(key, raw, gear_mode)
        except ValueError as ex:
            QMessageBox.warning(self, APP_TITLE, str(ex))
            return
        dlg = ConfirmOutputDialog(
            "新胜负载箱", "%s相功率档加载写入" % phase,
            "加载写入即拉载：功率档为 10 倍输入，当前输入 %d（≈%.1f 档）。"
            "确认散热、接线与现场负载条件允许。" % (raw, raw / 10.0),
            "寄存器 %d ← %d（%s）" % (addr, raw, gear_mode), self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return

        def work():
            cli.write_reg(addr, raw)
            cur = None
            for i in range(3):
                try:
                    cur = cli.read_reg(addr)
                    if cur == raw:
                        break
                    time.sleep(0.15)
                except Exception:  # noqa: BLE001
                    time.sleep(0.15)
            return raw, cur, addr

        def on_ok(res):
            raw, cur, a = res
            if cur == raw:
                self.log("%s相功率档：地址 %s 已写入 %d，回读一致（≈%.1f 档）。"
                         % (phase, a, raw, raw / 10.0))
            else:
                self.log("%s相功率档：地址 %s 已写入 %d，回读未确认（当前 %s）。"
                         "若设备无反应，请在「高级设置」切换功率档地址方案。"
                         % (phase, a, raw, cur), err=True)

        self._submit("%s相功率档" % phase, work, on_ok)

    def _cmd_unload(self, which: str):
        cli = self.client
        if cli is None:
            return
        key = "unload_" + which
        r = REG_BY_KEY[key]
        try:
            addr = validate_write(key, 1)
        except ValueError as e:
            self.log("[拦截] %s" % e, err=True)
            return

        def work():
            cli.write_reg(addr, 1)

        def on_ok(_=None):
            self.log("%s：上升沿指令已下发（地址 %d 写 1，此类触发量不做回读）。"
                     % (r.name, addr))

        self._submit(r.name, work, on_ok)

    # ---------------------------------------------------------- 控件使能
    def _set_controls_enabled(self, enabled: bool):
        for b in (self.btn_fan_on, self.btn_fan_off, self.btn_stop, self.btn_reset,
                  self.btn_unload_all):
            b.setEnabled(enabled)
        for key in ("delay_on", "delay_off"):
            getattr(self, "sp_" + key).setEnabled(enabled)
        for e in self.gear_entries.values():
            e.setEnabled(enabled)

    # ---------------------------------------------------------- 退出清理
    def shutdown(self):
        """停轮询 → 一键卸载（高危安全）→ 断链 → 回收工作线程。"""
        self._closing = True
        self._drain_timer.stop()
        if self.connected and self.client is not None:
            # 高危输出安全关闭：负载箱退出前先卸载全部相（上升沿写 38=1），再断链。
            # 同步直发（短超时）：经任务队列会被代际号竞态作废，不可靠。
            try:
                self.client.write_reg(38, 1)
                self.log("退出：已下发一键卸载（38←1）。")
            except Exception as e:  # noqa: BLE001
                self.log("退出卸载未确认：%s" % e, err=True)
        self._gen += 1
        self._drain_jobs()
        try:
            if self.transport:
                self.transport.close()
        except Exception:  # noqa: BLE001
            pass
        self.transport = None
        self.client = None
        self.connected = False
        if self._sim is not None:
            try:
                self._sim.stop()
            except Exception:  # noqa: BLE001
                pass
            self._sim = None
        try:
            self._worker.join(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        # 同步复位连接按钮
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.setText("连接")
        self.btn_conn.setEnabled(True)
