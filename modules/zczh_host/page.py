# -*- coding: utf-8 -*-
"""中创智合采集卡 · 融合版界面（FusionHub 风格）。

温度 / 电压 / 电流 / 混合 四大系列共用一套 Modbus 协议栈，
切换「系列」下拉即切换寄存器映射表，协议层与界面框架不变。

界面结构：
- 连接配置（真实串口 / 网口 TCP / 模拟从站）+ 系列选择 + 量程值
- 左侧：通道实时读数卡片（Canvas 滚动）
- 右侧：通讯协议切换 / 关键寄存器参考（可搜索）/ 直接发报文
- 底部：通讯日志

协议栈 / 寄存器映射 / 换算 / 模拟从站 零改动复用 core 包，
界面只消费 core.modbus.Device 语义接口与 core.series 映射表。
"""
import socket
import threading

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                             QSplitter, QVBoxLayout, QWidget)

from instrument_hub.widgets import Card

from .core import series as S
from .core import simulator
from .core.modbus import (Device, ModbusError, ProtocolError, SerialTransport,
                          TcpTransport, crc16_bytes)


def _hexs(data):
    """bytes -> '01 03 00 00 00 04' 大写空格分隔。"""
    return data.hex(" ").upper() if data else ""


class _SimServer:
    """内嵌模拟从站：本地 TCP 服务器，复用 simulator.SimSlave 逻辑。"""

    def __init__(self, series_key, slave):
        self.slave = simulator.SimSlave(series_key, slave)
        self._stop = threading.Event()
        self._srv = None
        self.port = self._bind()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _bind(self):
        for port in range(5061, 5078):
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                try:
                    srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                except OSError:
                    pass
            try:
                srv.bind(("127.0.0.1", port))
                srv.listen(8)
            except OSError:
                srv.close()
                continue
            self._srv = srv
            return port
        raise ProtocolError("无法启动模拟从站：端口 5061~5077 均被占用")

    def _run(self):
        srv = self._srv
        srv.settimeout(0.4)
        try:
            while not self._stop.is_set():
                try:
                    conn, _addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        finally:
            try:
                srv.close()
            except OSError:
                pass

    def _handle(self, conn):
        try:
            conn.settimeout(10)
            buf = bytearray()
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(512)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                # 用 RTU 处理（CRC 校验），简单可靠
                frame, rest = simulator.try_unpack(bytes(buf), "rtu")
                if frame is None:
                    continue
                buf = bytearray(rest)
                resp = self.slave.handle_rtu(frame)
                if resp:
                    conn.sendall(resp)
        except Exception:
            pass
        finally:
            conn.close()

    def close(self):
        self._stop.set()
        try:
            if self._srv is not None:
                self._srv.close()
        except OSError:
            pass


class ZczhPage(QWidget):
    """中创智合采集卡：连接 → 系列选择 → 实时采集 → 协议切换 / 寄存器 / 报文调试。"""

    # 采集启停按钮两态配色（与 pk9018b 等采集卡一致）
    _COLLECT_ON_QSS = ("QPushButton{background:#10B981; color:#FFFFFF; border:2px solid #047857; "
                       "border-radius:10px; font-weight:700; font-size:12px; padding:3px 12px;}"
                       "QPushButton:pressed{background:#047857;}")
    _COLLECT_OFF_QSS = ("QPushButton{background:#FFFFFF; color:#4B4A73; border:2px solid #D6D3EE; "
                        "border-radius:10px; font-weight:700; font-size:12px; padding:3px 12px;}"
                        "QPushButton:pressed{background:#D6D3EE;}")

    sig_log = pyqtSignal(str, str)
    sig_meas = pyqtSignal(object)
    sig_conn_ok = pyqtSignal(object)
    sig_conn_fail = pyqtSignal(str)
    sig_raw_resp = pyqtSignal(str, str, str)  # (resp_text, ok_flag, err_text)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        self._sim = None
        self._collecting = False
        self._inflight = False
        self._trace_on = False
        self._ok = 0
        self._fail = 0
        self._series_key = "temperature"
        self._series = S.SERIES[self._series_key]
        self._range_value = 1.0

        self.sig_log.connect(self._append_log)
        self.sig_meas.connect(self._show_measurement)
        self.sig_conn_ok.connect(self._on_conn_ok)
        self.sig_conn_fail.connect(self._on_conn_fail)
        self.sig_raw_resp.connect(self._on_raw_resp)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        bv.addWidget(self._build_conn_card())

        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_measure_card())
        mid.addWidget(self._build_side())
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 0)
        mid.setSizes([720, 400])
        bv.addWidget(mid, 1)

        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QScrollArea.NoFrame)
        content_scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        content_scroll.setWidget(body)
        content_scroll.setMinimumHeight(200)
        split.addWidget(content_scroll)
        split.addWidget(self._build_log_group())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([470, 190])
        root.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.setInterval(1000)

        self._refresh_ports()
        self._apply_series()

    # ---------------------------------------------------------- 连接配置
    def _build_conn_card(self) -> Card:
        card = Card("连接配置",
                    "中创智合采集卡：温度 / 电压 / 电流 / 混合四大系列共用 Modbus-RTU/TCP；"
                    "电压电流系列量程见铭牌，填入下方「量程值」否则读数错 10 倍")
        g = QVBoxLayout()
        g.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("系列"))
        self.cmb_series = QComboBox()
        for k in S.SERIES:
            self.cmb_series.addItem(S.SERIES[k].name)
        self.cmb_series.currentIndexChanged.connect(self._on_series_changed)
        top.addWidget(self.cmb_series)

        top.addWidget(QLabel("链路"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["真实串口", "网口 TCP", "模拟从站"])
        self.cmb_link.currentIndexChanged.connect(self._on_link_changed)
        top.addWidget(self.cmb_link)

        self.lbl_port = QLabel("串口")
        top.addWidget(self.lbl_port)
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setStyleSheet("QComboBox{min-width:120px;}")
        top.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setMinimumHeight(30)
        self.btn_refresh.setFixedWidth(56)
        self.btn_refresh.clicked.connect(self._refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_baud = QLabel("波特率")
        top.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        for b in ("4800", "9600", "19200", "38400", "57600", "115200"):
            self.cmb_baud.addItem(b)
        self.cmb_baud.setCurrentText("9600")
        top.addWidget(self.cmb_baud)

        # TCP 参数
        self.lbl_ip = QLabel("IP")
        top.addWidget(self.lbl_ip)
        self.e_ip = QLineEdit("192.168.2.7")
        self.e_ip.setFixedWidth(110)
        top.addWidget(self.e_ip)
        self.lbl_port2 = QLabel("端口")
        top.addWidget(self.lbl_port2)
        self.e_tcp_port = QLineEdit("20108")
        self.e_tcp_port.setFixedWidth(64)
        top.addWidget(self.e_tcp_port)

        top.addWidget(QLabel("从站"))
        self.sp_slave = QSpinBox()
        self.sp_slave.setRange(1, 247)
        self.sp_slave.setValue(1)
        self.sp_slave.setFixedWidth(64)
        top.addWidget(self.sp_slave)

        top.addSpacing(6)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.setMinimumHeight(30)
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.clicked.connect(self._on_connect)
        top.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("断开")
        self.btn_disc.setMinimumHeight(30)
        self.btn_disc.clicked.connect(self._on_disconnect)
        self.btn_disc.setEnabled(False)
        top.addWidget(self.btn_disc)
        top.addStretch(1)
        g.addLayout(top)

        low = QHBoxLayout()
        low.setSpacing(8)
        low.addWidget(QLabel("量程值"))
        self.e_range = QLineEdit("1")
        self.e_range.setFixedWidth(80)
        low.addWidget(self.e_range)
        self.lbl_range_hint = QLabel("")
        self.lbl_range_hint.setObjectName("Muted")
        low.addWidget(self.lbl_range_hint)
        low.addWidget(QLabel("采集间隔(ms)"))
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(100, 10000)
        self.sp_interval.setValue(1000)
        self.sp_interval.setFixedWidth(88)
        low.addWidget(self.sp_interval)
        self.chk_trace = QCheckBox("显示通讯报文")
        self.chk_trace.toggled.connect(self._on_trace_toggled)
        low.addWidget(self.chk_trace)
        self.lbl_state = QLabel("未连接")
        self.lbl_state.setObjectName("Muted")
        low.addWidget(self.lbl_state)
        low.addStretch(1)
        self.lbl_stat = QLabel("成功: 0   失败: 0")
        self.lbl_stat.setObjectName("Muted")
        low.addWidget(self.lbl_stat)
        self.btn_clear_stat = QPushButton("清除")
        self.btn_clear_stat.setMinimumHeight(30)
        self.btn_clear_stat.setFixedWidth(52)
        self.btn_clear_stat.clicked.connect(self._on_clear_stat)
        low.addWidget(self.btn_clear_stat)
        g.addLayout(low)

        card.body_lay.addLayout(g)
        return card

    def _refresh_ports(self):
        from instrument_hub.serial_ports import enumerate_ports
        try:
            names = enumerate_ports()
        except Exception:
            names = []
        cur = self.cmb_port.currentText().strip()
        self.cmb_port.blockSignals(True)
        self.cmb_port.clear()
        self.cmb_port.addItems(names or ["COM3", "COM4", "COM5"])
        if cur in names:
            self.cmb_port.setCurrentText(cur)
        self.cmb_port.blockSignals(False)

    def _on_link_changed(self):
        link = self.cmb_link.currentText()
        is_tcp = link == "网口 TCP"
        is_sim = link == "模拟从站"
        # 串口参数：仅真实串口显示
        for w in (self.lbl_port, self.cmb_port, self.btn_refresh,
                  self.lbl_baud, self.cmb_baud):
            w.setVisible(not is_tcp and not is_sim)
        # TCP 参数：仅网口 TCP 显示
        for w in (self.lbl_ip, self.e_ip, self.lbl_port2, self.e_tcp_port):
            w.setVisible(is_tcp)

    def _on_series_changed(self):
        keys = list(S.SERIES.keys())
        idx = self.cmb_series.currentIndex()
        if 0 <= idx < len(keys):
            self._series_key = keys[idx]
            self._series = S.SERIES[keys[idx]]
            self._apply_series()
            self._log("INFO", "切换系列：%s（%d 通道）" % (
                self._series.name, self._series.channel_count))

    def _on_trace_toggled(self, checked):
        self._trace_on = bool(checked)

    # ---------------------------------------------------------- 采集区
    def _build_measure_card(self) -> Card:
        card = Card("通道实时读数", "切换系列自动重建通道；温度 ÷10，电压/电流 ×量程÷10000")
        top = QHBoxLayout()
        top.setSpacing(8)
        self.btn_start_collect = QPushButton("开始采集")
        self.btn_start_collect.setMinimumHeight(30)
        self.btn_start_collect.setEnabled(False)
        self.btn_start_collect.setProperty("selfStyled", True)
        self.btn_start_collect.setStyleSheet(self._COLLECT_OFF_QSS)
        self.btn_start_collect.clicked.connect(lambda: self._set_collecting(True))
        top.addWidget(self.btn_start_collect)
        self.btn_stop_collect = QPushButton("停止采集")
        self.btn_stop_collect.setMinimumHeight(30)
        self.btn_stop_collect.setEnabled(False)
        self.btn_stop_collect.clicked.connect(lambda: self._set_collecting(False))
        top.addWidget(self.btn_stop_collect)
        top.addStretch(1)
        card.body_lay.addLayout(top)

        # 通道卡片滚动区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(8)
        self.scroll.setWidget(self._grid_host)
        card.body_lay.addWidget(self.scroll, 1)

        self._card_widgets = []
        self._channel_vals = {}
        self._rebuild_channels()
        return card

    def _rebuild_channels(self):
        for w in self._card_widgets:
            w.setParent(None)
            w.deleteLater()
        self._card_widgets = []
        self._channel_vals = {}
        # 清空 grid
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        s = self._series
        cols = 4
        for i in range(s.channel_count):
            card = QWidget()
            card.setStyleSheet(
                "QWidget{background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px;}")
            v = QVBoxLayout(card)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(2)
            cap = QLabel("CH%d" % (i + 1))
            cap.setObjectName("Muted")
            v.addWidget(cap)
            val = QLabel("----")
            val.setStyleSheet("font-size:20px; font-weight:800; color:#B45309;"
                              "background:#FFFFFF; border:none;")
            val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            v.addWidget(val)
            unit = QLabel(s.unit)
            unit.setObjectName("Muted")
            v.addWidget(unit)
            self._grid.addWidget(card, i // cols, i % cols)
            self._card_widgets.append(card)
            self._channel_vals[i] = val
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    def _apply_series(self):
        s = self._series
        self.lbl_range_hint.setText(s.range_hint)
        # 量程值仅 voltage/current/mixed 需要
        need_range = s.scale_mode in ("range10000", "range100000")
        self.e_range.setEnabled(need_range)
        self._rebuild_channels()
        self._refresh_side_panel()

    # ---------------------------------------------------------- 右侧面板
    def _build_side(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._build_proto_card())
        v.addWidget(self._build_reg_card())
        v.addWidget(self._build_raw_card())
        v.addStretch(1)
        return w

    def _build_proto_card(self) -> Card:
        card = Card("通讯协议切换", "写入协议寄存器（06 功能码），系列切换自动选对应寄存器")
        self.lbl_proto_reg = QLabel("")
        self.lbl_proto_reg.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_proto_reg)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("目标协议"))
        self.cmb_proto = QComboBox()
        self.cmb_proto.currentIndexChanged.connect(self._on_proto_sel)
        row.addWidget(self.cmb_proto)
        card.body_lay.addLayout(row)

        self.lbl_proto_hint = QLabel("")
        self.lbl_proto_hint.setObjectName("Muted")
        self.lbl_proto_hint.setWordWrap(True)
        card.body_lay.addWidget(self.lbl_proto_hint)

        self.btn_proto = QPushButton("写入协议")
        self.btn_proto.setMinimumHeight(30)
        self.btn_proto.clicked.connect(self._on_switch_proto)
        card.body_lay.addWidget(self.btn_proto)
        return card

    def _build_reg_card(self) -> Card:
        card = Card("关键寄存器", "按当前系列的配置寄存器参考（地址 / 名称 / 说明）")
        self.e_search = QLineEdit()
        self.e_search.setPlaceholderText("搜索寄存器…")
        self.e_search.textChanged.connect(self._filter_regs)
        card.body_lay.addWidget(self.e_search)

        self.reg_tree = QPlainTextEdit()
        self.reg_tree.setReadOnly(True)
        self.reg_tree.setMaximumBlockCount(500)
        self.reg_tree.setStyleSheet("QPlainTextEdit{font-family:Consolas; font-size:12px;}")
        card.body_lay.addWidget(self.reg_tree)
        return card

    def _build_raw_card(self) -> Card:
        card = Card("直接发报文", "16 进制 RTU 帧（可留空 CRC 自动补），显示原始响应")
        self.txt_raw = QPlainTextEdit()
        self.txt_raw.setPlaceholderText("如：01 03 00 00 00 04")
        self.txt_raw.setStyleSheet("QPlainTextEdit{font-family:Consolas; font-size:12px;}")
        self.txt_raw.setFixedHeight(48)
        card.body_lay.addWidget(self.txt_raw)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_send = QPushButton("发送")
        self.btn_send.setMinimumHeight(30)
        self.btn_send.clicked.connect(self._on_send_raw)
        row.addWidget(self.btn_send)
        self.btn_crc = QPushButton("补CRC")
        self.btn_crc.setMinimumHeight(30)
        self.btn_crc.clicked.connect(self._on_auto_crc)
        row.addWidget(self.btn_crc)
        card.body_lay.addLayout(row)

        self.lbl_raw_resp = QLabel("响应：—")
        self.lbl_raw_resp.setObjectName("Muted")
        self.lbl_raw_resp.setWordWrap(True)
        self.lbl_raw_resp.setStyleSheet("font-family:Consolas; font-size:12px;")
        card.body_lay.addWidget(self.lbl_raw_resp)
        return card

    def _refresh_side_panel(self):
        s = self._series
        self.lbl_proto_reg.setText("寄存器 0x%04X（写 06 功能码）" % s.proto_reg)
        labels = [o[0] for o in s.proto_options]
        self.cmb_proto.blockSignals(True)
        self.cmb_proto.clear()
        self.cmb_proto.addItems(labels)
        self.cmb_proto.blockSignals(False)
        self._on_proto_sel()
        self._fill_regs(s.regs)

    def _on_proto_sel(self):
        s = self._series
        idx = self.cmb_proto.currentIndex()
        if 0 <= idx < len(s.proto_options):
            _label, val, hint = s.proto_options[idx]
            self.lbl_proto_hint.setText("写值 0x%04X —— %s" % (val, hint))

    def _fill_regs(self, regs):
        self._all_regs = regs
        self._render_regs(regs)

    def _render_regs(self, regs):
        lines = []
        for addr, name, desc in regs:
            lines.append("0x%04X  %-10s  %s" % (addr, name, desc))
        self.reg_tree.setPlainText("\n".join(lines) if lines else "（无）")

    def _filter_regs(self):
        kw = self.e_search.text().strip().lower()
        regs = getattr(self, "_all_regs", [])
        if not kw:
            self._render_regs(regs)
            return
        self._render_regs([
            (a, n, d) for a, n, d in regs
            if kw in ("0x%04X %s %s" % (a, n, d)).lower()])

    # ---------------------------------------------------------- 通讯日志
    def _build_log_group(self) -> QGroupBox:
        grp = QGroupBox("通讯日志")
        grp.setMinimumHeight(150)
        v = QVBoxLayout(grp)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(3000)
        v.addWidget(self.txt_log)
        return grp

    # ---------------------------------------------------------- 连接
    def _trace_cb(self):
        def cb(sent, got):
            if self._trace_on:
                self.sig_log.emit("TX", ">> " + _hexs(sent))
                if got:
                    self.sig_log.emit("RX", "<< " + _hexs(got))
        return cb

    def _on_connect(self):
        if self._dev is not None:
            return
        link = self.cmb_link.currentText()
        slave = self.sp_slave.value()
        series_key = self._series_key
        self.btn_conn.setEnabled(False)
        self.btn_conn.setText("连接中…")
        self.lbl_state.setText("连接中…")

        def work():
            dev = None
            try:
                if link == "模拟从站":
                    self._close_sim()
                    self._sim = _SimServer(series_key, slave)
                    tr = TcpTransport("127.0.0.1", self._sim.port, 1.0, mode="rtu")
                elif link == "网口 TCP":
                    host = self.e_ip.text().strip()
                    port = int(self.e_tcp_port.text() or "20108")
                    tr = TcpTransport(host, port, 1.5, mode="tcp")
                else:
                    port_name = self.cmb_port.currentText().strip()
                    baud = int(self.cmb_baud.currentText())
                    tr = SerialTransport(port_name, baud, "N", 1, 8, 1.0)
                dev = Device(tr, mode=("tcp" if link == "网口 TCP" else "rtu"),
                             slave=slave)
                # 读一次验证通讯
                dev.read_registers(self._series.data_start,
                                   min(self._series.channel_count, 4), fc=0x03)
                self.sig_conn_ok.emit(dev)
            except Exception as e:
                if dev is not None:
                    try:
                        dev.close()
                    except Exception:
                        pass
                self.sig_conn_fail.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_conn_ok(self, dev):
        self._dev = dev
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("已连接")
        self.btn_conn.setObjectName("btnConnected")
        self.btn_disc.setEnabled(True)
        self.lbl_state.setText("已连接")
        self._set_collecting(True)
        self._log("INFO", "已连接：%s · 从站 %d · %s（%d 通道）" % (
            self.cmb_link.currentText(), self.sp_slave.value(),
            self._series.name, self._series.channel_count))

    def _on_conn_fail(self, msg):
        self._close_sim()
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_disc.setEnabled(False)
        self.lbl_state.setText("未连接")
        self._log("ERR", "连接失败：%s" % msg)
        QMessageBox.critical(self, "连接失败", msg)

    def _on_disconnect(self):
        self._set_collecting(False)
        dev, self._dev = self._dev, None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
        self._close_sim()
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_disc.setEnabled(False)
        self.lbl_state.setText("未连接")
        self._clear_readings()
        self._log("INFO", "已断开连接")

    def _close_sim(self):
        if self._sim is not None:
            try:
                self._sim.close()
            except Exception:
                pass
            self._sim = None

    # ---------------------------------------------------------- 采集启停
    def _set_collecting(self, on):
        on = bool(on) and self._dev is not None
        self._collecting = on
        self.btn_start_collect.setEnabled(not on)
        self.btn_stop_collect.setEnabled(on)
        self.btn_start_collect.setStyleSheet(self._COLLECT_ON_QSS if on else self._COLLECT_OFF_QSS)
        if on:
            self._timer.setInterval(self.sp_interval.value())
            self._timer.start()
            self.lbl_state.setText("采集中")
        else:
            self._timer.stop()
            self.lbl_state.setText("已连接" if self._dev is not None else "未连接")

    # ---------------------------------------------------------- 轮询
    def _on_tick(self):
        if not (self._collecting and self._dev is not None):
            return
        if self._inflight:
            return
        self._timer.setInterval(self.sp_interval.value())
        self._inflight = True
        dev = self._dev
        s = self._series
        rv = self._range_value

        def work():
            try:
                words = dev.read_registers(s.data_start, s.channel_count, fc=0x03)
                vals = {}
                for i in range(s.channel_count):
                    raw = S.words_to_int([words[i]], s.dtype)
                    v = S.decode_value(raw, s, rv)
                    if s.scale_mode == "div10" and words[i] in (0x7FFF, 0x8000):
                        v = None
                    vals[i] = v
                self.sig_meas.emit(vals)
            except Exception:
                self.sig_meas.emit(None)
            finally:
                self._inflight = False

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- 协议切换
    def _on_switch_proto(self):
        dev = self._require_dev()
        if dev is None:
            return
        s = self._series
        idx = self.cmb_proto.currentIndex()
        if not (0 <= idx < len(s.proto_options)):
            self._log("WARN", "请选择目标协议。")
            return
        label, val, hint = s.proto_options[idx]
        proto_reg = s.proto_reg

        def work():
            try:
                dev.write_single(proto_reg, val)
                self.sig_log.emit("INFO", "协议切换成功：0x%04X ← 0x%04X（%s）" % (
                    proto_reg, val, label))
            except Exception as e:
                self.sig_log.emit("ERR", "协议切换失败：%s" % e)

        self._log("INFO", "正在写入协议寄存器 0x%04X = 0x%04X（%s）…" % (proto_reg, val, label))
        self._run_worker(work)

    # ---------------------------------------------------------- 直接发报文
    def _on_auto_crc(self):
        raw = self.txt_raw.toPlainText().strip()
        try:
            body = self._parse_hex(raw)
        except ValueError as e:
            self._log("ERR", "报文解析失败：%s" % e)
            return
        if len(body) < 2:
            self._log("WARN", "报文过短。")
            return
        full = body + crc16_bytes(body)
        self.txt_raw.setPlainText(full.hex(" ").upper())
        self._log("INFO", "已补 CRC：%s" % full.hex(" ").upper())

    def _on_send_raw(self):
        dev = self._require_dev()
        if dev is None:
            return
        raw = self.txt_raw.toPlainText().strip()
        try:
            data = self._parse_hex(raw)
        except ValueError as e:
            self._log("ERR", "报文解析失败：%s" % e)
            return
        if len(data) < 2:
            self._log("WARN", "报文过短。")
            return
        body = data
        if len(data) >= 2 and crc16_bytes(data[:-2]) == data[-2:]:
            body = data[:-2]
        full = body + crc16_bytes(body)
        is_tcp = dev.mode == "tcp"

        def work():
            try:
                if is_tcp:
                    pdu = full[1:-2]
                    resp = dev._exchange_raw_mbap(full[0], pdu)
                else:
                    resp = dev._exchange_raw_rtu(full)
                self.sig_raw_resp.emit(_hexs(resp) if resp else "(无)", "ok", "")
            except Exception as e:
                self.sig_raw_resp.emit("", "err", str(e))

        self._log("INFO", "[发送] %s" % full.hex(" ").upper())
        self._run_worker(work)

    def _on_raw_resp(self, resp_text, ok_flag, err_text):
        if ok_flag == "err":
            self.lbl_raw_resp.setText("响应：出错（%s）" % err_text)
            self._log("ERR", "发送失败：%s" % err_text)
        else:
            self.lbl_raw_resp.setText("响应：%s" % resp_text)
            self._log("INFO", "[响应] %s" % resp_text)

    @staticmethod
    def _parse_hex(raw):
        s = raw.replace(" ", "").replace("\n", "").replace("\r", "")
        s = s.replace(",", "").replace("0x", "").replace("0X", "")
        if not s:
            return b""
        if len(s) % 2 != 0:
            raise ValueError("十六进制字符数应为偶数")
        try:
            return bytes.fromhex(s)
        except ValueError:
            raise ValueError("含非十六进制字符")

    # ---------------------------------------------------------- 显示 / 日志
    def _show_measurement(self, vals):
        from instrument_hub.comm_state import mark_ok, mark_lost
        if vals is None:
            mark_lost(self)
            self._fail += 1
            self._update_stat_label()
            return
        mark_ok(self)
        self._ok += 1
        self._update_stat_label()
        s = self._series
        for i in range(s.channel_count):
            v = vals.get(i)
            lbl = self._channel_vals.get(i)
            if lbl is None:
                continue
            if v is None:
                lbl.setText("--")
                lbl.setStyleSheet("font-size:20px; font-weight:800; color:#9CA3AF;"
                                  "background:#FFFFFF; border:none;")
            elif s.scale_mode == "div10":
                lbl.setText("%.1f" % v)
                lbl.setStyleSheet("font-size:20px; font-weight:800; color:#B45309;"
                                  "background:#FFFFFF; border:none;")
            else:
                lbl.setText(("%.4f" % v).rstrip("0").rstrip("."))
                lbl.setStyleSheet("font-size:20px; font-weight:800; color:#B45309;"
                                  "background:#FFFFFF; border:none;")

    def _clear_readings(self):
        for i, lbl in self._channel_vals.items():
            lbl.setText("----")
            lbl.setStyleSheet("font-size:20px; font-weight:800; color:#B45309;"
                              "background:#FFFFFF; border:none;")

    def _update_stat_label(self):
        self.lbl_stat.setText("成功: %d   失败: %d" % (self._ok, self._fail))

    def _on_clear_stat(self):
        self._ok = self._fail = 0
        self._update_stat_label()

    def _append_log(self, direction, text):
        colors = {"TX": "#4F46E5", "RX": "#059669", "WARN": "#B45309",
                  "ERR": "#DC2626", "INFO": "#6B7280"}
        color = colors.get(direction, "#6B7280")
        self.txt_log.appendHtml(
            '<span style="color:%s">[%s] %s</span>' % (color, direction, text))
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _log(self, direction, text):
        self.sig_log.emit(direction, text)

    def _require_dev(self):
        if self._dev is None:
            QMessageBox.warning(self, "提示", "请先连接设备")
            return None
        return self._dev

    def _run_worker(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    # ---------------------------------------------------------- 退出闭环
    def shutdown(self):
        self._set_collecting(False)
        dev, self._dev = self._dev, None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
        self._close_sim()
