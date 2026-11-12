# -*- coding: utf-8 -*-
"""TP613 三相智能电量仪配置软件 · 融合版界面（FusionHub 风格）。

Modbus-RTU 协议层 / 串口/TCP/模拟从站传输 / 通讯线程复用重建的 core 包
（语义与原上位机逐寄存器一致），界面按整体 UI 风格重建：
端口配置 → 数据采集 → 参数设置 → 自定义报文 → 通讯状态 + 底部通讯日志。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox,
                             QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from instrument_hub.widgets import Card

from .core.comm import CommThread
from .core.protocol import (BAUD_RATE_MAP, BAUD_RATE_REVERSE, BASIC_PARAMS,
                            ENERGY_PARAMS, PARAM_DEFS, PARAM_NOTE,
                            REG_4_20MA, REG_CLR_DEMAND, REG_CLR_ENERGY,
                            frame_text)
from .core.transport import (SIM_PORT_NAME, SerialConnection, SimConnection,
                             TcpConnection, available_ports)

CUSTOM_TEMPLATES = [
    ('-- 选择模板 --', ''),
    ('读UA(0x006C)', '01 03 00 6C 00 02'),
    ('读全部电压(0x0064)', '01 03 00 64 00 08'),
    ('读电流(0x0074)', '01 03 00 74 00 06'),
    ('读功率(0x0080)', '01 03 00 80 00 08'),
    ('读电能(0x00A0)', '01 03 00 A0 00 04'),
    ('读设备地址(0xEA00)', '01 03 EA 00 00 01'),
]


class Tp613Page(QWidget):
    """TP613 配置：连接 → 采集轮询 / 参数读写 / 自定义报文。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.conn = None
        self.worker = CommThread(self)
        self.worker.sig_tx.connect(lambda m: self._log(m, "#4FC3F7"))
        self.worker.sig_rx.connect(lambda m: self._log(m, "#81C784"))
        self.worker.sig_info.connect(lambda m: self._log(m, "#FFD54F"))
        self.worker.sig_error.connect(lambda m: self._log(m, "#EF5350"))
        self.worker.sig_data.connect(self._on_data)
        self.worker.sig_comm_ok.connect(self._on_comm_ok)
        self.worker.sig_comm_fail.connect(self._on_comm_fail)
        self.worker.sig_custom_resp.connect(self._on_custom_resp)
        self.worker.sig_param_result.connect(self._on_param_result)
        self._ok_cnt = 0
        self._fail_cnt = 0
        self._cells = {}
        self._param_widgets = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        tv.addWidget(self._build_conn_card())
        # 数据采集 | 参数设置/自定义报文（按钮切换）左右并排，主界面免下拉直看通讯日志
        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_collect_card())
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(6)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_tab_param = QPushButton("参数设置")
        self.btn_tab_custom = QPushButton("自定义报文")
        for b in (self.btn_tab_param, self.btn_tab_custom):
            b.setCheckable(True)
            b.setFixedWidth(110)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        sv.addLayout(btn_row)
        self.side_stack = QStackedWidget()
        self.side_stack.addWidget(self._build_param_card())
        self.side_stack.addWidget(self._build_custom_card())
        sv.addWidget(self.side_stack, 1)
        self.btn_tab_param.setChecked(True)
        self.btn_tab_param.clicked.connect(lambda: self._switch_side(0))
        self.btn_tab_custom.clicked.connect(lambda: self._switch_side(1))
        mid.addWidget(side)
        mid.setStretchFactor(0, 3)
        mid.setStretchFactor(1, 2)
        mid.setSizes([520, 430])
        tv.addWidget(mid)
        split.addWidget(top)
        split.addWidget(self._build_log_group())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        root.addWidget(split, 1)

        self.worker.start()
        self._refresh_ports()

    # ---------------------------------------------------------- 端口配置
    def _build_conn_card(self) -> Card:
        card = Card("端口配置",
                    "通讯方式: TCP / 串口(RS485) · 协议: Modbus RTU · "
                    "FC03 读 / FC06 写单 / FC10 写多 · CRC16 低字节在前")
        g = QGridLayout()
        g.setSpacing(8)
        g.setVerticalSpacing(10)

        # 第一行：通讯链路（通讯方式 + 串口号/刷新 + IP/端口 + 连接/断开）
        # 用单行 QHBoxLayout 让「标签紧贴控件、单元间统一间距、富余空间推到行尾」，
        # 避免多行 QGridLayout 列宽互相牵连导致固定宽失效、行尾大片空白。
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("通讯方式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["串口 RS485", "TCP 网口"])
        self.cmb_mode.setFixedWidth(120)
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        top.addWidget(self.cmb_mode)

        self.lbl_port = QLabel("串口号")
        top.addWidget(self.lbl_port)
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setFixedWidth(170)
        top.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_ip = QLabel("IP地址")
        top.addWidget(self.lbl_ip)
        self.ed_ip = QLineEdit("192.168.1.100")
        self.ed_ip.setFixedWidth(130)
        top.addWidget(self.ed_ip)
        self.lbl_tcpport = QLabel("端口")
        top.addWidget(self.lbl_tcpport)
        self.sp_tcpport = QSpinBox()
        self.sp_tcpport.setRange(1, 65535)
        self.sp_tcpport.setValue(502)
        self.sp_tcpport.setFixedWidth(80)
        top.addWidget(self.sp_tcpport)

        top.addSpacing(8)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.setFixedWidth(80)
        self.btn_conn.clicked.connect(self._on_connect)
        top.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("断开")
        self.btn_disc.setFixedWidth(80)
        self.btn_disc.clicked.connect(self._on_disconnect)
        self.btn_disc.setEnabled(False)
        top.addWidget(self.btn_disc)
        top.addStretch(1)
        g.addLayout(top, 0, 0)

        # 第二行：协议参数（波特率/数据位/停止位/校验位/设备地址）
        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["1200", "2400", "4800", "9600", "19200",
                                "38400", "57600", "115200"])
        self.cmb_baud.setCurrentText("9600")
        self.cmb_baud.setFixedWidth(100)
        mid.addWidget(self.cmb_baud)

        mid.addWidget(QLabel("数据位"))
        self.cmb_bits = QComboBox()
        self.cmb_bits.addItems(["8", "7"])
        self.cmb_bits.setFixedWidth(64)
        mid.addWidget(self.cmb_bits)

        mid.addWidget(QLabel("停止位"))
        self.cmb_stop = QComboBox()
        self.cmb_stop.addItems(["1", "2"])
        self.cmb_stop.setFixedWidth(64)
        mid.addWidget(self.cmb_stop)

        mid.addWidget(QLabel("校验位"))
        self.cmb_parity = QComboBox()
        self.cmb_parity.addItems(["无(None)", "偶(Even)", "奇(Odd)"])
        self.cmb_parity.setFixedWidth(100)
        mid.addWidget(self.cmb_parity)

        mid.addWidget(QLabel("设备地址"))
        self.sp_slave = QSpinBox()
        self.sp_slave.setRange(0, 247)
        self.sp_slave.setValue(1)
        self.sp_slave.setFixedWidth(80)
        self.sp_slave.valueChanged.connect(self._on_slave_changed)
        mid.addWidget(self.sp_slave)
        mid.addStretch(1)
        g.addLayout(mid, 1, 0)

        card.body_lay.addLayout(g)
        return card

    # ---------------------------------------------------------- 数据采集
    def _build_collect_card(self) -> Card:
        card = Card("数据采集 — TP613",
                    "FLOAT(ABCD, 2寄存器) · 轮询块 0x0064 起 60 寄存器 + 0x00A0 起 24 寄存器")
        h = QHBoxLayout()
        h.setSpacing(8)
        self.btn_poll = QPushButton("开始采集")
        self.btn_poll.clicked.connect(self._on_start_poll)
        h.addWidget(self.btn_poll)
        self.btn_poll_stop = QPushButton("停止采集")
        self.btn_poll_stop.clicked.connect(self._on_stop_poll)
        self.btn_poll_stop.setEnabled(False)
        h.addWidget(self.btn_poll_stop)
        h.addWidget(QLabel("采集间隔(ms)"))
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(200, 60000)
        self.sp_interval.setValue(1000)
        self.sp_interval.setFixedWidth(90)
        h.addWidget(self.sp_interval)
        h.addStretch(1)
        card.body_lay.addLayout(h)

        g = QGridLayout()
        g.setSpacing(6)
        for idx, (key, name, unit, fmt, _addr) in enumerate(
                BASIC_PARAMS + ENERGY_PARAMS):
            cell = QLabel("--")
            cell.setStyleSheet(
                "border:1px solid #C0C0C0; border-radius:4px; background:#FFF;"
                "padding:4px 6px; color:#1565C0; font-weight:700;"
                "font-family:Consolas;")
            cell.setMinimumWidth(104)
            cell.setAlignment(Qt.AlignCenter)
            cell.setToolTip(f"{name}（寄存器 0x{_addr:04X}，{unit or '—'}）")
            wrap = QVBoxLayout()
            wrap.setSpacing(2)
            cap = QLabel(f"{name}{'（' + unit + '）' if unit else ''}")
            cap.setStyleSheet("color:#666; font-size:8pt;")
            cap.setAlignment(Qt.AlignCenter)
            wrap.addWidget(cap)
            wrap.addWidget(cell)
            col, row = idx // 8, idx % 8
            g.addLayout(wrap, row, col)
            self._cells[key] = (cell, fmt)
        card.body_lay.addLayout(g)
        return card

    # ---------------------------------------------------------- 参数设置
    def _build_param_card(self) -> Card:
        card = Card("参数设置 — TP613（寄存器地址可修改，支持功能码06/10）")
        note = QLabel(PARAM_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet("color:#FF6600; font-size:8pt;")
        card.body_lay.addWidget(note)

        g = QGridLayout()
        g.setSpacing(6)
        heads = ["参数", "地址", "设定值", "FC10", "FLOAT", "", "当前值"]
        for c, t in enumerate(heads):
            lb = QLabel(t)
            lb.setObjectName("Muted")
            g.addWidget(lb, 0, c)
        for r, (key, name, addr0, ptype) in enumerate(PARAM_DEFS, start=1):
            g.addWidget(QLabel(name), r, 0)
            ed_addr = QLineEdit(f"0x{addr0:04X}")
            ed_addr.setFixedWidth(86)
            g.addWidget(ed_addr, r, 1)
            if key == "baud_rate":
                w = QComboBox()
                w.addItems([str(BAUD_RATE_MAP[i]) for i in sorted(BAUD_RATE_MAP)])
                w.setFixedWidth(96)
            elif key == "net_mode":
                w = QComboBox()
                w.addItems(["三相三线", "三相四线"])
                w.setFixedWidth(96)
            else:
                w = QLineEdit("0")
                w.setFixedWidth(96)
            g.addWidget(w, r, 2)
            chk10 = QCheckBox()
            chk10.setToolTip("使用功能码0x10(写多寄存器)代替0x06")
            g.addWidget(chk10, r, 3)
            chkf = QCheckBox()
            chkf.setToolTip("以FLOAT(ABCD, 2寄存器)格式读写")
            g.addWidget(chkf, r, 4)
            bw = QWidget()
            bh = QHBoxLayout(bw)
            bh.setContentsMargins(0, 0, 0, 0)
            bh.setSpacing(4)
            b_rd = QPushButton("读取")
            b_rd.clicked.connect(lambda _c, k=key: self._read_param(k))
            bh.addWidget(b_rd)
            b_wr = QPushButton("写入")
            b_wr.clicked.connect(lambda _c, k=key: self._write_param(k))
            bh.addWidget(b_wr)
            g.addWidget(bw, r, 5)
            cur = QLabel("--")
            cur.setStyleSheet("font-family:Consolas; color:#1f7ae0; font-weight:700;")
            g.addWidget(cur, r, 6)
            self._param_widgets[key] = (ed_addr, w, chk10, chkf, cur)
        card.body_lay.addLayout(g)

        h = QHBoxLayout()
        h.setSpacing(8)
        b_all = QPushButton("读取全部参数")
        b_all.clicked.connect(self._read_all_params)
        h.addWidget(b_all)
        b_ce = QPushButton("清空电能")
        b_ce.clicked.connect(self._clear_energy)
        h.addWidget(b_ce)
        b_cd = QPushButton("清空需量")
        b_cd.clicked.connect(self._clear_demand)
        h.addWidget(b_cd)
        h.addStretch(1)
        card.body_lay.addLayout(h)
        return card

    # ---------------------------------------------------------- 自定义报文
    def _build_custom_card(self) -> Card:
        card = Card("自定义报文", "Hex 空格分隔 · 可选附加 CRC16 · 快捷模板一键取用")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(QLabel("快捷模板"))
        self.cmb_tpl = QComboBox()
        for name, _hex in CUSTOM_TEMPLATES:
            self.cmb_tpl.addItem(name)
        self.cmb_tpl.currentIndexChanged.connect(self._on_template_changed)
        self.cmb_tpl.setFixedWidth(190)
        h.addWidget(self.cmb_tpl)
        h.addStretch(1)
        card.body_lay.addLayout(h)

        h2 = QHBoxLayout()
        h2.setSpacing(8)
        h2.addWidget(QLabel("报文(Hex)"))
        self.ed_hex = QLineEdit()
        self.ed_hex.setPlaceholderText("例: 01 03 00 6C 00 02")
        self.ed_hex.setStyleSheet("font-family:Consolas;")
        h2.addWidget(self.ed_hex, 1)
        self.chk_crc = QCheckBox("附加CRC16校验码")
        h2.addWidget(self.chk_crc)
        b_send = QPushButton("发送报文")
        b_send.clicked.connect(self._send_custom)
        h2.addWidget(b_send)
        card.body_lay.addLayout(h2)

        self.lbl_resp = QLabel("响应数据: 等待响应...")
        self.lbl_resp.setObjectName("Muted")
        self.lbl_resp.setStyleSheet("font-family:Consolas;")
        self.lbl_resp.setWordWrap(True)
        card.body_lay.addWidget(self.lbl_resp)
        return card

    # ---------------------------------------------------------- 日志
    def _build_log_group(self) -> QWidget:
        box = QGroupBox("通讯日志")
        v = QVBoxLayout(box)
        v.setSpacing(6)
        h = QHBoxLayout()
        h.addWidget(QLabel("通讯状态"))
        self.lbl_dot = QLabel("●")
        self.lbl_dot.setStyleSheet("color:#F44336; font-size:18pt;")
        h.addWidget(self.lbl_dot)
        self.lbl_state = QLabel("未连接")
        self.lbl_state.setStyleSheet("font-weight:700;")
        h.addWidget(self.lbl_state)
        h.addSpacing(16)
        h.addWidget(QLabel("通讯成功:"))
        self.lbl_ok = QLabel("0")
        self.lbl_ok.setStyleSheet("color:#4CAF50; font-weight:700;")
        h.addWidget(self.lbl_ok)
        h.addWidget(QLabel("通讯失败:"))
        self.lbl_fail = QLabel("0")
        self.lbl_fail.setStyleSheet("color:#F44336; font-weight:700;")
        h.addWidget(self.lbl_fail)
        b_clr_cnt = QPushButton("清除计数")
        b_clr_cnt.clicked.connect(self._clear_counters)
        h.addWidget(b_clr_cnt)
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

    # ---------------------------------------------------------- 连接
    def _refresh_ports(self):
        cur = self.cmb_port.currentText()
        self.cmb_port.clear()
        for name, desc in available_ports():
            self.cmb_port.addItem(f"{name} - {desc}", name)
        if cur:
            self.cmb_port.setCurrentText(cur)
        elif self.cmb_port.currentData() == SIM_PORT_NAME:
            # 默认选真实串口（模拟从站排列表首位但不默认），模拟口保留供手动选择
            for i in range(self.cmb_port.count()):
                if self.cmb_port.itemData(i) != SIM_PORT_NAME:
                    self.cmb_port.setCurrentIndex(i)
                    break

    def _switch_side(self, idx):
        self.side_stack.setCurrentIndex(idx)
        self.btn_tab_param.setChecked(idx == 0)
        self.btn_tab_custom.setChecked(idx == 1)

    def _on_mode_changed(self, idx):
        serial_mode = idx == 0
        for w in (self.lbl_port, self.cmb_port, self.btn_refresh,
                  self.lbl_ip, self.ed_ip, self.lbl_tcpport, self.sp_tcpport):
            w.setVisible(True)
        self.lbl_port.setVisible(serial_mode)
        self.cmb_port.setVisible(serial_mode)
        self.btn_refresh.setVisible(serial_mode)
        self.lbl_ip.setVisible(not serial_mode)
        self.ed_ip.setVisible(not serial_mode)
        self.lbl_tcpport.setVisible(not serial_mode)
        self.sp_tcpport.setVisible(not serial_mode)

    def _on_slave_changed(self, val):
        self.worker.set_slave_addr(val)

    def _on_connect(self):
        try:
            if self.cmb_mode.currentIndex() == 0:
                port = self.cmb_port.currentData() or \
                    self.cmb_port.currentText().split(" - ")[0]
                if port == SIM_PORT_NAME:
                    conn = SimConnection(self.sp_slave.value())
                else:
                    if not port:
                        QMessageBox.warning(self, "警告", "请选择有效的串口")
                        return
                    pmap = {"无(None)": "N", "偶(Even)": "E", "奇(Odd)": "O"}
                    conn = SerialConnection(
                        port, int(self.cmb_baud.currentText()),
                        int(self.cmb_bits.currentText()),
                        int(self.cmb_stop.currentText()),
                        pmap[self.cmb_parity.currentText()])
            else:
                conn = TcpConnection(self.ed_ip.text().strip(),
                                     self.sp_tcpport.value())
            conn.connect()
        except Exception as e:
            QMessageBox.critical(self, "连接失败", str(e))
            self._log(f"[{_now()}] 连接失败: {e}", "#EF5350")
            return
        self.conn = conn
        self.worker.set_connection(conn)
        self.worker.set_slave_addr(self.sp_slave.value())
        self.lbl_dot.setStyleSheet("color:#4CAF50; font-size:18pt;")
        self.lbl_state.setText("已连接")
        self.btn_conn.setText("已连接")
        self.btn_conn.setObjectName("btnConnected")
        self.btn_conn.setEnabled(False)
        self.btn_disc.setEnabled(True)
        self._log(f"[{_now()}] 连接成功", "#81C784")

    def _on_disconnect(self):
        self.worker.stop_polling()
        self.btn_poll.setEnabled(True)
        self.btn_poll_stop.setEnabled(False)
        if self.conn is not None:
            try:
                self.conn.disconnect()
            except Exception:
                pass
            self.conn = None
        self.worker.set_connection(None)
        self.lbl_dot.setStyleSheet("color:#F44336; font-size:18pt;")
        self.lbl_state.setText("未连接")
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.setEnabled(True)
        self.btn_disc.setEnabled(False)
        self._log(f"[{_now()}] 已断开连接", "#EF5350")

    # ---------------------------------------------------------- 采集
    def _on_start_poll(self):
        if self.conn is None:
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        self.worker.set_poll_interval(self.sp_interval.value() / 1000.0)
        self.worker.start_polling()
        self.btn_poll.setEnabled(False)
        self.btn_poll_stop.setEnabled(True)
        self._log(f"[{_now()}] 开始数据采集, 间隔="
                  f"{self.sp_interval.value() / 1000.0:.1f}s", "#FFD54F")

    def _on_stop_poll(self):
        self.worker.stop_polling()
        self.btn_poll.setEnabled(True)
        self.btn_poll_stop.setEnabled(False)
        self._log(f"[{_now()}] 停止数据采集", "#FFD54F")

    def _on_data(self, data: dict):
        for key, (cell, fmt) in self._cells.items():
            if key in data:
                cell.setText(format(data[key], fmt))

    def _on_comm_ok(self):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到有效应答 = 通讯真正建立
        self._ok_cnt += 1
        self.lbl_ok.setText(str(self._ok_cnt))

    def _on_comm_fail(self, msg):
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 通讯超时/失败 = 通讯中断
        self._fail_cnt += 1
        self.lbl_fail.setText(str(self._fail_cnt))
        self._log(f"[{_now()}] 通讯异常: {msg}", "#EF5350")

    # ---------------------------------------------------------- 参数读写
    def _parse_addr(self, key):
        ed_addr = self._param_widgets[key][0]
        try:
            return int(ed_addr.text().strip(), 0)
        except ValueError:
            QMessageBox.warning(self, "地址格式",
                                "地址用 0x 十六进制或十进制，如 0x0000")
            return None

    def _read_param(self, key):
        if self.conn is None:
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        addr = self._parse_addr(key)
        if addr is None:
            return
        _a, _w, _c10, chkf, _cur = self._param_widgets[key]
        self.worker.queue_read_param(key, addr, 2 if chkf.isChecked() else 1)

    def _write_param(self, key):
        if self.conn is None:
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        addr = self._parse_addr(key)
        if addr is None:
            return
        _a, w, chk10, chkf, _cur = self._param_widgets[key]
        name = dict((k, n) for k, n, _x, _t in PARAM_DEFS)[key]
        if key == "baud_rate":
            value = BAUD_RATE_REVERSE.get(int(w.currentText()), 0)
            shown = f"{w.currentText()}(寄存器值 {value})"
        elif key == "net_mode":
            value = w.currentIndex()
            shown = f"{w.currentText()}(寄存器值 {value})"
        else:
            try:
                value = float(w.text()) if chkf.isChecked() \
                    else int(w.text(), 0)
            except ValueError:
                QMessageBox.warning(self, "数值格式", "请输入数值")
                return
            shown = str(value)
        ret = QMessageBox.question(
            self, "确认写入",
            f"确认写入参数?\n\n参数: {name}\n寄存器: 0x{addr:04X}\n值: {shown}\n"
            f"功能码: {'0x10(多寄存器)' if chk10.isChecked() else '0x06(单寄存器)'}\n"
            f"数据类型: {'FLOAT(2寄存器)' if chkf.isChecked() else 'UINT16(1寄存器)'}")
        if ret != QMessageBox.Yes:
            return
        self.worker.queue_write_param(key, addr, value,
                                      chk10.isChecked(), chkf.isChecked())

    def _read_all_params(self):
        if self.conn is None:
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        for key in self._param_widgets:
            self._read_param(key)

    def _on_param_result(self, name, value, ok):
        if not ok:
            self._log(f"[{_now()}] 参数 {name} 读取/写入失败", "#EF5350")
            return
        if name in self._param_widgets:
            _a, w, _c10, _chkf, cur = self._param_widgets[name]
            if name == "baud_rate":
                text = str(BAUD_RATE_MAP.get(int(value), value))
                idx = w.findText(text)
                if idx >= 0:
                    w.setCurrentIndex(idx)
            elif name == "net_mode":
                idx = w.findText("三相三线" if int(value) == 0 else "三相四线")
                if idx >= 0:
                    w.setCurrentIndex(idx)
            else:
                text = (f"{value:.2f}" if isinstance(value, float)
                        else str(value))
            cur.setText(text)
        self._log(f"[{_now()}] {name} = {value}", "#81C784")

    # ---------------------------------------------------------- 清零
    def _clear_energy(self):
        if self.conn is None:
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        if QMessageBox.question(self, "确认", "确认清空累积电能？") != QMessageBox.Yes:
            return
        self.worker.queue_write_param("clear_energy", REG_CLR_ENERGY, 1,
                                      False, False)

    def _clear_demand(self):
        if self.conn is None:
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        if QMessageBox.question(self, "确认", "确认清空月最大需量？") != QMessageBox.Yes:
            return
        self.worker.queue_write_param("clear_demand", REG_CLR_DEMAND, 1,
                                      False, False)

    # ---------------------------------------------------------- 自定义报文
    def _on_template_changed(self, idx):
        if idx > 0:
            self.ed_hex.setText(CUSTOM_TEMPLATES[idx][1])

    def _send_custom(self):
        if self.conn is None:
            QMessageBox.warning(self, "警告", "请先建立连接")
            return
        text = self.ed_hex.text().replace(",", " ").replace("\n", " ")
        if not text.strip():
            QMessageBox.warning(self, "警告", "请输入报文内容")
            return
        try:
            data = bytes.fromhex(text.replace(" ", ""))
        except ValueError:
            QMessageBox.critical(self, "错误", "Hex格式错误，请检查输入")
            return
        self.worker.queue_custom(data, self.chk_crc.isChecked())

    def _on_custom_resp(self, resp: bytes):
        if not resp:
            self.lbl_resp.setText("响应数据: (无响应或超时)")
            return
        text = frame_text(resp)
        try:
            from .core.protocol import ModbusRTU
            regs = ModbusRTU.parse_read_response(resp)
            text += f"   解析: 寄存器值 = {regs}"
        except Exception as e:
            text += f"   (非标准读响应或解析失败: {e})"
        self.lbl_resp.setText("响应数据: " + text)

    # ---------------------------------------------------------- 日志/清理
    def _log(self, msg, color="#D4D4D4"):
        self.txt_log.appendHtml(
            f'<span style="color:{color}">{msg}</span>')
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_counters(self):
        self._ok_cnt = self._fail_cnt = 0
        self.lbl_ok.setText("0")
        self.lbl_fail.setText("0")

    def _save_log(self):
        import datetime
        import os
        path = os.path.join(
            os.environ.get("TEMP", "."),
            f"tp613_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_log.toPlainText())
            self._log(f"日志已保存 → {path}", "#FFD54F")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def shutdown(self):
        """退出闭环：停采集 → 断链 → 停线程。"""
        try:
            self.worker.stop_polling()
            if self.conn is not None:
                self.conn.disconnect()
                self.conn = None
            self.worker.set_connection(None)
            self.worker.stop()
        except Exception:
            pass


def _now() -> str:
    import datetime
    n = datetime.datetime.now()
    return f"{n:%H:%M:%S}.{n.microsecond // 1000:03d}"
