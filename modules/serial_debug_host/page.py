# -*- coding: utf-8 -*-
"""二合一调试助手（串口调试 / MODBUS RTU）· 融合版界面（FusionHub 风格）。

收发与协议逻辑零改动复用原上位机 serial_assistant.py（core/：SerialCore / NetCore /
Modbus CRC16 / HEX 解析 / 串口参数识别与降级），界面按整体 UI 风格重建，
功能键切换两页：
- 「串口调试」串口 + TCP/UDP 双接口（SSCOM 风格 HEX/编码/定时/快捷指令/数据落盘、
  串口↔TCP 双向转发、二选一自动切换）；
- 「MODBUS RTU」01H~10H 指令面板 + 任意指令（可带 CRC）、响应解析/异常码/超时提示。
两页各自持有独立串口，可同时连接不同端口（打开前预检端口占用）。
"""
import datetime
import html
import os
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                             QStackedWidget, QVBoxLayout, QWidget)

from instrument_hub.serial_ports import enumerate_ports
from instrument_hub.widgets import Card

from .core.serial_assistant import (NetCore, SerialCore, downshift_params, hex_str,
                                    intval, local_ips, mb_append_crc, mb_crc_ok,
                                    parse_hex, port_param_error, port_param_hint)

BAUDS = ("1200", "2400", "4800", "9600", "19200", "38400",
         "57600", "115200", "230400", "460800", "921600")
DATAS = ("5", "6", "7", "8")
STOPS = ("1", "1.5", "2")
PARITIES = (("无 None", "N"), ("奇 Odd", "O"), ("偶 Even", "E"),
            ("标记 Mark", "M"), ("空格 Space", "S"))
FLOWS = (("无", "none"), ("RTS/CTS", "rtscts"), ("XON/XOFF", "xonxoff"))
ENCS = ("GBK", "UTF-8", "ASCII", "GB18030")
NET_MODES = ("TCP Client", "TCP Server", "UDP")

# 接收区着色（沿用原上位机语义色）
C_RX = "#101010"     # 串口收
C_TX = "#0A6C2F"     # 串口发
C_SYS = "#1A4FA0"    # 系统提示
C_NET = "#8A3FB0"    # TCP 收
C_NETTX = "#B0603A"  # TCP 发
C_ERR = "#B00020"    # 错误
C_OK = "#0A6C2F"     # 校验通过


class SerialDebugPage(QWidget):
    """二合一调试助手：串口调试（含 TCP/UDP） + MODBUS RTU。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.s_core = SerialCore()     # 串口调试页（独立串口）
        self.net = NetCore()           # 串口调试页 TCP/UDP
        self.m_core = SerialCore()     # MODBUS 页（独立串口）
        self._s_tx_bytes = 0
        self._s_rx_bytes = 0
        self._net_rx_bytes = 0
        self._net_tx_bytes = 0
        self._m_tx_bytes = 0
        self._m_rx_bytes = 0
        self._mb_reads = {}            # func -> (地址/个数/结果) 输入框
        self._mb_writes = {}           # func -> (地址/值) 输入框
        self._raw_fp = None            # 保存数据（原始字节）
        self._txt_fp = None            # 接收数据到文件（显示文本）
        self._m_buf = b""
        self._m_pending = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        page_lay = QVBoxLayout()   # 嵌套布局：框架日志分割条跳过本页（自管分割条）
        page_lay.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_page_serial = QPushButton("串口调试")
        self.btn_page_modbus = QPushButton("MODBUS RTU")
        for b in (self.btn_page_serial, self.btn_page_modbus):
            b.setCheckable(True)
            b.setFixedWidth(130)
            bar.addWidget(b)
        bar.addStretch(1)
        self.lbl_hint = QLabel("两页各自独立串口，可同时连接不同端口")
        self.lbl_hint.setObjectName("Muted")
        bar.addWidget(self.lbl_hint)
        page_lay.addLayout(bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_serial_page())
        self.stack.addWidget(self._build_modbus_page())
        page_lay.addWidget(self.stack, 1)
        root.addLayout(page_lay)
        self.btn_page_serial.setChecked(True)
        self.btn_page_serial.clicked.connect(lambda: self._switch_page(0))
        self.btn_page_modbus.clicked.connect(lambda: self._switch_page(1))

        self._refresh_ports()
        self._sync_net_mode()

        self._timer = QTimer(self)            # 主泵：串口/网络收数据 → 界面
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._pump)
        self._timer.start()
        self._timed_timer = QTimer(self)      # 定时发送
        self._timed_timer.timeout.connect(self._tick_timed)
        self._mb_timer = QTimer(self)         # MODBUS 响应超时（900ms）
        self._mb_timer.setSingleShot(True)
        self._mb_timer.timeout.connect(self._mb_on_timeout)

    def _switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        self.btn_page_serial.setChecked(idx == 0)
        self.btn_page_modbus.setChecked(idx == 1)

    # ================================================================ 串口调试页
    def _build_serial_page(self) -> QWidget:
        w = QWidget()
        tv = QVBoxLayout(w)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(8)
        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        bv.addWidget(self._build_link_card())
        bv.addWidget(self._build_send_card())
        bv.addStretch(1)
        split.addWidget(body)
        split.addWidget(self._build_rx_card())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)   # 多余高度给接收区（原版 SSCOM 布局习惯）
        split.setSizes([430, 220])
        tv.addWidget(split, 1)
        return w

    def _build_link_card(self) -> Card:
        card = Card("通讯连接",
                    "串口 与 TCP/UDP 二选一自动切换（勾「双向转发」可并存）；"
                    "串口默认 115200-8-N-1，端口下拉自动刷新")

        # 行0 串口参数（QBox 行：框架通讯状态指示灯固定挂「连接」按钮所在行行尾）
        r0 = QHBoxLayout()
        r0.setSpacing(8)
        r0.addWidget(QLabel("端口"))
        self.cmb_s_port = QComboBox()
        self.cmb_s_port.setEditable(False)
        self.cmb_s_port.setMinimumWidth(150)
        r0.addWidget(self.cmb_s_port)
        b = QPushButton("刷新")
        b.clicked.connect(self._refresh_ports)
        r0.addWidget(b)
        self.btn_s_conn = QPushButton("连接")
        self.btn_s_conn.setProperty("portOpenOnly", True)   # 透传工具：已连接=端口打开
        self.btn_s_conn.clicked.connect(self._toggle_serial)
        r0.addWidget(self.btn_s_conn)
        self.btn_s_disc = QPushButton("断开")
        self.btn_s_disc.clicked.connect(self._close_serial)
        self.btn_s_disc.setEnabled(False)
        r0.addWidget(self.btn_s_disc)
        r0.addWidget(QLabel("波特率"))
        self.cmb_s_baud = QComboBox()
        self.cmb_s_baud.setEditable(True)
        self.cmb_s_baud.addItems(list(BAUDS))
        self.cmb_s_baud.setCurrentText("115200")
        self.cmb_s_baud.setFixedWidth(88)
        r0.addWidget(self.cmb_s_baud)
        r0.addWidget(QLabel("数据位"))
        self.cmb_s_data = QComboBox()
        self.cmb_s_data.addItems(list(DATAS))
        self.cmb_s_data.setCurrentText("8")
        self.cmb_s_data.setFixedWidth(56)
        r0.addWidget(self.cmb_s_data)
        r0.addWidget(QLabel("停止位"))
        self.cmb_s_stop = QComboBox()
        self.cmb_s_stop.addItems(list(STOPS))
        self.cmb_s_stop.setFixedWidth(56)
        r0.addWidget(self.cmb_s_stop)
        r0.addWidget(QLabel("校验位"))
        self.cmb_s_parity = QComboBox()
        for name, _c in PARITIES:
            self.cmb_s_parity.addItem(name)
        self.cmb_s_parity.setFixedWidth(92)
        r0.addWidget(self.cmb_s_parity)
        r0.addWidget(QLabel("流控"))
        self.cmb_s_flow = QComboBox()
        for name, _c in FLOWS:
            self.cmb_s_flow.addItem(name)
        self.cmb_s_flow.setFixedWidth(88)
        r0.addWidget(self.cmb_s_flow)
        card.body_lay.addLayout(r0)

        # 行1 TCP/UDP 接口
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        tcp_lbl = QLabel("TCP接口")
        tcp_lbl.setStyleSheet("font-weight:700; color:#8A3FB0;")
        r1.addWidget(tcp_lbl)
        self.cmb_net_mode = QComboBox()
        self.cmb_net_mode.addItems(list(NET_MODES))
        self.cmb_net_mode.setFixedWidth(110)
        self.cmb_net_mode.currentIndexChanged.connect(self._sync_net_mode)
        r1.addWidget(self.cmb_net_mode)
        self.lbl_net_ip = QLabel("远程IP")
        r1.addWidget(self.lbl_net_ip)
        self.cmb_net_ip = QComboBox()
        self.cmb_net_ip.setEditable(True)
        self.cmb_net_ip.addItems(local_ips())
        self.cmb_net_ip.setCurrentText("192.168.1.77")
        self.cmb_net_ip.setMinimumWidth(130)
        r1.addWidget(self.cmb_net_ip)
        self.lbl_net_port = QLabel("远程端口")
        r1.addWidget(self.lbl_net_port)
        self.sp_net_port = QSpinBox()
        self.sp_net_port.setRange(1, 65535)
        self.sp_net_port.setValue(5020)
        self.sp_net_port.setFixedWidth(80)
        r1.addWidget(self.sp_net_port)
        self.btn_net_conn = QPushButton("开启TCP")
        self.btn_net_conn.setProperty("portOpenOnly", True)   # 透传工具：已连接=端口打开
        self.btn_net_conn.clicked.connect(self._toggle_net)
        r1.addWidget(self.btn_net_conn)
        self.btn_net_disc = QPushButton("关闭TCP")
        self.btn_net_disc.clicked.connect(self._close_net)
        self.btn_net_disc.setEnabled(False)
        r1.addWidget(self.btn_net_disc)
        self.lbl_net_state = QLabel("未连接")
        self.lbl_net_state.setObjectName("Muted")
        r1.addWidget(self.lbl_net_state)
        self.chk_bridge = QCheckBox("串口 ↔ TCP 双向转发")
        self.chk_bridge.setToolTip("勾选后串口与 TCP 允许并存：一路收到的数据自动转发到另一路")
        r1.addWidget(self.chk_bridge)
        r1.addStretch(1)
        card.body_lay.addLayout(r1)

        # 行2 收发选项
        opts = QHBoxLayout()
        opts.setSpacing(10)
        self.chk_hex_show = QCheckBox("HEX显示")
        opts.addWidget(self.chk_hex_show)
        self.chk_hex_send = QCheckBox("HEX发送")
        opts.addWidget(self.chk_hex_send)
        self.chk_crlf = QCheckBox("加回车换行")
        self.chk_crlf.setChecked(True)
        opts.addWidget(self.chk_crlf)
        self.chk_ts = QCheckBox("加时间戳和分包显示")
        opts.addWidget(self.chk_ts)
        self.chk_timed = QCheckBox("定时发送")
        self.chk_timed.toggled.connect(self._apply_timed)
        opts.addWidget(self.chk_timed)
        self.ed_interval = QLineEdit("1000")
        self.ed_interval.setFixedWidth(56)
        self.ed_interval.setAlignment(Qt.AlignCenter)
        opts.addWidget(self.ed_interval)
        opts.addWidget(QLabel("ms/次"))
        b = QPushButton("停止")
        b.clicked.connect(self._stop_timed)
        opts.addWidget(b)
        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        opts.addWidget(self.chk_autoscroll)
        opts.addWidget(QLabel("编码"))
        self.cmb_enc = QComboBox()
        self.cmb_enc.addItems(list(ENCS))
        self.cmb_enc.setFixedWidth(88)
        opts.addWidget(self.cmb_enc)
        opts.addStretch(1)
        card.body_lay.addLayout(opts)

        # 行3 数据落盘
        opts2 = QHBoxLayout()
        opts2.setSpacing(10)
        self.chk_save_data = QCheckBox("保存数据(原始)")
        self.chk_save_data.toggled.connect(self._toggle_save_data)
        opts2.addWidget(self.chk_save_data)
        self.chk_rx_file = QCheckBox("接收数据到文件")
        self.chk_rx_file.toggled.connect(self._toggle_rx_file)
        opts2.addWidget(self.chk_rx_file)
        b = QPushButton("发送文件")
        b.clicked.connect(self._send_file)
        opts2.addWidget(b)
        opts2.addWidget(QLabel("超时时间"))
        self.ed_timeout = QLineEdit("20")
        self.ed_timeout.setFixedWidth(44)
        self.ed_timeout.setAlignment(Qt.AlignCenter)
        opts2.addWidget(self.ed_timeout)
        opts2.addWidget(QLabel("ms"))
        opts2.addStretch(1)
        card.body_lay.addLayout(opts2)
        return card

    def _build_send_card(self) -> Card:
        card = Card("发送区", "HEX发送按十六进制解析（空格/逗号均可分隔）；勾「加回车换行」自动补 CRLF")
        h = QHBoxLayout()
        h.setSpacing(8)

        col = QVBoxLayout()
        col.setSpacing(4)
        self.btn_send = QPushButton("发 送")
        self.btn_send.setMinimumHeight(48)
        self.btn_send.setStyleSheet("font-size:15px; font-weight:800;")
        self.btn_send.clicked.connect(self._send_current)
        col.addWidget(self.btn_send)
        tgt = QHBoxLayout()
        tgt.setSpacing(6)
        self.chk_send_serial = QCheckBox("串口")
        self.chk_send_serial.setChecked(True)
        tgt.addWidget(self.chk_send_serial)
        self.chk_send_net = QCheckBox("TCP")
        tgt.addWidget(self.chk_send_net)
        col.addLayout(tgt)
        h.addLayout(col)

        self.txt_tx = QPlainTextEdit()
        self.txt_tx.setPlaceholderText("要发送的内容（HEX发送时填 01 03 00 00 之类）")
        self.txt_tx.setStyleSheet("font-family:Consolas;")
        self.txt_tx.setFixedHeight(110)
        h.addWidget(self.txt_tx, 1)

        quick = QVBoxLayout()
        quick.setSpacing(4)
        b = QPushButton("*IDN?  发送")
        b.setToolTip("一键读取设备标识（自动加 CRLF）")
        b.clicked.connect(lambda: self._send_quick("*IDN?"))
        quick.addWidget(b)
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (txt, cmd) in enumerate((("*RST", "*RST"), ("AT", "AT"),
                                        ("ATI", "ATI"), ("清空", None))):
            bb = QPushButton(txt)
            if cmd is None:
                bb.clicked.connect(self.txt_tx.clear)
            else:
                bb.clicked.connect(lambda _=False, v=cmd: self._send_quick(v))
            grid.addWidget(bb, i // 2, i % 2)
        quick.addLayout(grid)
        h.addLayout(quick)
        card.body_lay.addLayout(h)
        return card

    def _build_rx_card(self) -> Card:
        card = Card("通讯日志（接收区）",
                    "黑=串口收　绿=串口发　紫=TCP收　棕=TCP发　蓝=系统提示；接收区即通讯日志")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_count = QLabel("S:0  R:0   TCP发:0  收:0")
        self.lbl_count.setObjectName("Muted")
        row.addWidget(self.lbl_count)
        row.addStretch(1)
        b = QPushButton("清除窗口")
        b.clicked.connect(lambda: self.txt_rx.clear())
        row.addWidget(b)
        b = QPushButton("保存窗口")
        b.clicked.connect(self._save_rx_view)
        row.addWidget(b)
        card.body_lay.addLayout(row)
        self.txt_rx = QPlainTextEdit()
        self.txt_rx.setReadOnly(True)
        self.txt_rx.setStyleSheet("font-family:Consolas;")
        self.txt_rx.setMinimumHeight(110)
        self.txt_rx.setMaximumBlockCount(5000)   # 防日志无限增长
        card.body_lay.addWidget(self.txt_rx)
        return card

    # ---------------------------------------------------------- 串口连接
    def _refresh_ports(self):
        ports = enumerate_ports()
        for combo in (self.cmb_s_port, self.cmb_m_port):
            cur = combo.currentText().strip()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(ports or ["COM3"])
            combo.setCurrentText(cur if cur in ports else (ports[0] if ports else cur or "COM3"))
            combo.blockSignals(False)

    @staticmethod
    def _parity_code(text):
        for name, code in PARITIES:
            if name == text:
                return code
        return "N"

    @staticmethod
    def _flow_code(text):
        for name, code in FLOWS:
            if name == text:
                return code
        return "none"

    def _sync_net_mode(self):
        """TCP Client 连远端；Server/UDP 绑定本地地址，标签随模式变化。"""
        mode = self.cmb_net_mode.currentText()
        if mode == "TCP Client":
            self.lbl_net_ip.setText("远程IP")
            self.lbl_net_port.setText("远程端口")
        else:
            self.lbl_net_ip.setText("本地IP")
            self.lbl_net_port.setText("本地端口")

    def _toggle_serial(self):
        if self.s_core.is_open:
            self._close_serial()
        else:
            self._open_serial()

    def _port_owner(self, port):
        """端口占用预检：同页/另一页面已占用同一 COM 口时提示。"""
        if self.m_core.is_open and self.m_core.port.upper() == port.upper():
            return "MODBUS RTU 页"
        return ""

    def _open_serial(self):
        port = self.cmb_s_port.currentText().strip()
        if not port:
            QMessageBox.warning(self, "提示", "没有可用串口，请插入设备后重试。")
            return
        owner = self._port_owner(port)
        if owner:
            QMessageBox.warning(self, "端口被占用",
                                f"端口 {port} 正被本程序「{owner}」占用。\n"
                                "两个分页各自使用独立串口，请在那一页先关闭，或换一个端口。")
            return
        c = dict(baud=self.cmb_s_baud.currentText().strip(),
                 bytesize=self.cmb_s_data.currentText(),
                 stopbits=self.cmb_s_stop.currentText(),
                 parity=self._parity_code(self.cmb_s_parity.currentText()),
                 flow=self._flow_code(self.cmb_s_flow.currentText()),
                 auto_answer="", rx_buf=8192, tx_buf=8192)
        ok, err = self._try_open(port, c)
        if not ok and port_param_error(err):
            # 驱动不接受 5/6 位数据位或 1.5 位停止位：自动退到 8 数据位 / 1 停止位
            bs, sb = downshift_params(c["bytesize"], c["stopbits"])
            if (bs, sb) != (str(c["bytesize"]), str(c["stopbits"])):
                ok2, err2 = self._try_open(port, dict(c, bytesize=bs, stopbits=sb))
                if ok2:
                    self.cmb_s_data.setCurrentText(bs)
                    self.cmb_s_stop.setCurrentText(sb)
                    self._rx_sys("该串口驱动不支持 %s 位数据位 / %s 位停止位，"
                                 "已自动改用 %s 数据位、%s 停止位"
                                 % (c["bytesize"], c["stopbits"], bs, sb))
                    ok, err = True, ""
                else:
                    err = err2 or err
        if not ok:
            QMessageBox.warning(self, "打开失败", port_param_hint(err))
            return
        self.btn_s_conn.setText("已连接")
        self.btn_s_conn.setObjectName("btnConnected")
        self.btn_s_disc.setEnabled(True)
        self._rx_sys("已打开 %s  %s" % (port, self._param_text()))
        self._auto_off_net()

    def _try_open(self, port, c):
        return self.s_core.open(port, c["baud"], c["bytesize"], c["parity"],
                                c["stopbits"], flow=c["flow"],
                                auto_answer=c["auto_answer"],
                                rx_buf=c["rx_buf"], tx_buf=c["tx_buf"])

    def _param_text(self):
        txt = "%s  %s %s-%s-%s" % (self.s_core.port or "-",
                                   self.cmb_s_baud.currentText().strip(),
                                   self.cmb_s_data.currentText(),
                                   self.cmb_s_parity.currentText()[0],
                                   self.cmb_s_stop.currentText())
        flow = self._flow_code(self.cmb_s_flow.currentText())
        if flow != "none":
            txt += "  " + ("RTS/CTS" if flow == "rtscts" else "XON/XOFF")
        return txt

    def _close_serial(self):
        was = self.s_core.is_open
        self.s_core.close()
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 链路关闭 = 通讯中断（下次真实数据到达自动复绿）
        self.btn_s_conn.setText("连接")
        self.btn_s_conn.setObjectName("btnConnect")
        self.btn_s_disc.setEnabled(False)
        if was:
            self._rx_sys("串口已关闭")
            self._stop_timed()
            if self.net.is_open:      # 另一路仍在线：发送目标切到 TCP
                self.chk_send_serial.setChecked(False)
                self.chk_send_net.setChecked(True)

    # ---------------------------------------------------------- TCP/UDP
    def _toggle_net(self):
        if self.net.is_open:
            self._close_net()
        else:
            self._open_net()

    def _open_net(self):
        mode = self.cmb_net_mode.currentText()
        ip = self.cmb_net_ip.currentText().strip() or "0.0.0.0"
        port = self.sp_net_port.value()
        if mode == "TCP Client":
            ok, err = self.net.open(mode, "", 0, ip, port)
        else:
            ok, err = self.net.open(mode, ip, port)
        if not ok:
            QMessageBox.warning(self, "TCP 打开失败", str(err))
            return
        self.btn_net_conn.setEnabled(True)
        self.btn_net_conn.setText("已连接")
        self.btn_net_conn.setObjectName("btnConnected")
        self.btn_net_disc.setEnabled(True)
        self.lbl_net_state.setText(self.net.info)
        self._rx_sys("TCP 已打开：%s  %s" % (mode, self.net.info), net=True)
        self._auto_off_serial()

    def _close_net(self):
        was = self.net.is_open
        self.net.close()
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 链路关闭 = 通讯中断
        self.btn_net_conn.setText("开启TCP")
        self.btn_net_conn.setObjectName("btnConnect")
        self.btn_net_disc.setEnabled(False)
        self.lbl_net_state.setText("未连接")
        if was:
            self._rx_sys("TCP 已关闭", net=True)
            self.chk_send_net.setChecked(False)
            if self.s_core.is_open:
                self.chk_send_serial.setChecked(True)

    def _auto_off_net(self):
        """串口打开成功 → 未勾双向转发时自动断开 TCP（二选一）。"""
        if not self.chk_bridge.isChecked() and self.net.is_open:
            self._close_net()
            self._rx_sys("[自动切换] 已断开 TCP，发送目标 → 串口", net=True)

    def _auto_off_serial(self):
        """TCP 打开成功 → 未勾双向转发时自动关闭串口（二选一）。"""
        if not self.chk_bridge.isChecked() and self.s_core.is_open:
            self._close_serial()
            self._rx_sys("[自动切换] 已关闭串口，发送目标 → TCP", net=True)
            self.chk_send_serial.setChecked(False)
            self.chk_send_net.setChecked(True)

    # ---------------------------------------------------------- 发送
    def _send_targets(self):
        out = []
        if self.chk_send_serial.isChecked():
            out.append("serial")
        if self.chk_send_net.isChecked():
            out.append("net")
        return out

    def _send_current(self):
        text = self.txt_tx.toPlainText()
        if not text.strip():
            return
        self.send_text(text, self.chk_crlf.isChecked())

    def _send_quick(self, s):
        self.send_text(s, True, force_ascii=True)

    def send_text(self, text, crlf, force_ascii=False):
        targets = self._send_targets()
        if not targets:
            QMessageBox.warning(self, "提示", "请先勾选发送目标：「串口」或「TCP」。")
            return False
        if "serial" in targets and not self.s_core.is_open:
            QMessageBox.warning(self, "提示", "串口未打开，请先选择端口并点「连接」。")
            return False
        if "net" in targets and not self.net.is_open:
            QMessageBox.warning(self, "提示", "TCP 未连接，请先点「开启TCP」，或取消勾选 TCP。")
            return False
        try:
            if self.chk_hex_send.isChecked() and not force_ascii:
                data = parse_hex(text)
            else:
                data = text.encode(self.cmb_enc.currentText(), errors="replace")
            if crlf:
                data += b"\r\n"
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "格式错误", f"发送内容解析失败：\n{e}")
            return False
        if not data:
            return False

        as_hex = self.chk_hex_send.isChecked() and not force_ascii
        body = hex_str(data) if as_hex else data.decode(
            self.cmb_enc.currentText(), errors="replace").rstrip("\r\n")
        failed = []
        if "serial" in targets:
            ok, err = self.s_core.write(data)
            if ok:
                self._s_tx_bytes += len(data)
                self._rx_append(C_TX, "-> %s" % body)
            else:
                failed.append("串口：%s" % err)
        if "net" in targets:
            ok, err = self.net.write(data)
            if ok:
                self._net_tx_bytes += len(data)
                self._rx_append(C_NETTX, "TCP-> %s" % body)
            else:
                failed.append("TCP：%s" % err)
        self._update_count()
        if failed:
            QMessageBox.warning(self, "发送失败", "\n".join(failed))
            return False
        return True

    def _send_file(self):
        path, ok = QFileDialog.getOpenFileName(self, "选择要发送的文件")
        if not ok or not path:
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "读取失败", str(e))
            return
        ok, err = self.s_core.write(data)
        if not ok:
            QMessageBox.warning(self, "发送失败", err)
            return
        self._update_count()
        self._rx_sys("已发送文件 %s（%d 字节）" % (os.path.basename(path), len(data)))

    # ---------------------------------------------------------- 定时
    def _apply_timed(self, on):
        self._timed_timer.stop()
        if on:
            self._tick_timed()

    def _tick_timed(self):
        if not self.chk_timed.isChecked():
            return
        self._send_current()
        try:
            ms = max(20, int(self.ed_interval.text()))
        except Exception:  # noqa: BLE001
            ms = 1000
        self._timed_timer.start(ms)

    def _stop_timed(self):
        self._timed_timer.stop()
        self.chk_timed.setChecked(False)

    # ---------------------------------------------------------- 数据落盘
    def _toggle_save_data(self, on):
        if on:
            path, ok = QFileDialog.getSaveFileName(
                self, "保存接收数据（原始字节，追加写入）",
                "rx_%s.bin" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
                "二进制文件 (*.bin)")
            if not ok or not path:
                self.chk_save_data.setChecked(False)
                return
            try:
                self._raw_fp = open(path, "ab")
                self._rx_sys("开始保存原始数据到 %s" % path)
            except Exception as e:  # noqa: BLE001
                self.chk_save_data.setChecked(False)
                QMessageBox.warning(self, "无法写入", str(e))
        elif self._raw_fp:
            try:
                self._raw_fp.close()
            except Exception:  # noqa: BLE001
                pass
            self._raw_fp = None
            self._rx_sys("已停止保存原始数据")

    def _toggle_rx_file(self, on):
        if on:
            path, ok = QFileDialog.getSaveFileName(
                self, "接收数据到文件（按显示文本写入）",
                "rx_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
                "文本文件 (*.txt)")
            if not ok or not path:
                self.chk_rx_file.setChecked(False)
                return
            try:
                self._txt_fp = open(path, "a", encoding="utf-8", errors="replace")
                self._rx_sys("开始写入文本日志 %s" % path)
            except Exception as e:  # noqa: BLE001
                self.chk_rx_file.setChecked(False)
                QMessageBox.warning(self, "无法写入", str(e))
        elif self._txt_fp:
            try:
                self._txt_fp.close()
            except Exception:  # noqa: BLE001
                pass
            self._txt_fp = None

    def _save_rx_view(self):
        path, ok = QFileDialog.getSaveFileName(self, "保存接收窗口内容",
                                               "rx_view.txt", "文本文件 (*.txt)")
        if not ok or not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.txt_rx.toPlainText())
            self._rx_sys("接收窗口内容已保存到 %s" % path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(e))

    # ---------------------------------------------------------- 接收显示
    def _rx_append(self, color, text):
        self.txt_rx.appendHtml(
            '<span style="color:%s">%s</span>' % (color, html.escape(text)))
        if self.chk_autoscroll.isChecked():
            sb = self.txt_rx.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _rx_sys(self, text, net=False):
        self._rx_append(C_NET if net else C_SYS,
                        "[%s] %s" % (time.strftime("%H:%M:%S"), text))

    def _update_count(self):
        self.lbl_count.setText(
            "S:%d  R:%d   TCP发:%d  收:%d" % (
                self._s_tx_bytes, self._s_rx_bytes,
                self._net_tx_bytes, self._net_rx_bytes))

    def _on_serial_rx(self, data):
        if not data:
            return
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 设备真实数据到达 = 通讯真正建立
        self._s_rx_bytes += len(data)
        if self._raw_fp:
            try:
                self._raw_fp.write(data)
                self._raw_fp.flush()
            except Exception:  # noqa: BLE001
                pass
        if self.chk_hex_show.isChecked():
            body = hex_str(data)
        else:
            try:
                body = data.decode(self.cmb_enc.currentText(), errors="replace")
            except Exception:  # noqa: BLE001
                body = repr(data)
        if self.chk_ts.isChecked():
            body = datetime.datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] " + body
        self._rx_append(C_RX, body)
        if self._txt_fp:
            try:
                self._txt_fp.write(body)
                self._txt_fp.flush()
            except Exception:  # noqa: BLE001
                pass
        self._update_count()
        if self.chk_bridge.isChecked() and self.net.is_open:
            self.net.write(data)

    def _on_net_rx(self, data):
        if not data:
            return
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 对端真实数据到达 = 通讯真正建立
        self._net_rx_bytes += len(data)
        if self.chk_hex_show.isChecked():
            body = hex_str(data)
        else:
            try:
                body = data.decode(self.cmb_enc.currentText(), errors="replace")
            except Exception:  # noqa: BLE001
                body = repr(data)
        if self.chk_ts.isChecked():
            body = datetime.datetime.now().strftime("[%H:%M:%S.%f")[:-3] + "] " + body
        self._rx_append(C_NET, body)
        if self._txt_fp:
            try:
                self._txt_fp.write(body)
                self._txt_fp.flush()
            except Exception:  # noqa: BLE001
                pass
        self._update_count()
        if self.chk_bridge.isChecked() and self.s_core.is_open:
            self.s_core.write(data)

    def _pump(self):
        packs, err = self.s_core.drain()
        for d in packs:
            self._on_serial_rx(d)
        if err is not None:
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)   # 串口读异常 = 通讯中断
            self._rx_sys("串口读取异常：%s" % err)
            self._close_serial()
        packs, logs = self.net.drain()
        for msg in logs:
            self._rx_sys(msg, net=True)
        for d in packs:
            self._on_net_rx(d)

        packs, err = self.m_core.drain()
        for d in packs:
            self._mb_on_rx(d)
        if err is not None:
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)
            self._mb_log(self.txt_m_rx, "✗ 串口读取异常：%s" % err, C_ERR)
            self._mb_close_serial()

    # ================================================================ MODBUS RTU 页
    def _build_modbus_page(self) -> QWidget:
        w = QWidget()
        tv = QVBoxLayout(w)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(8)
        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        bv.addWidget(self._build_mb_conn_card())
        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(self._mb_read_group("01H指令 （读线圈寄存器）", 1))
        lv.addWidget(self._mb_read_group("02H指令 （读离散输入寄存器）", 2))
        lv.addWidget(self._mb_read_group("03H指令 （读保持寄存器）", 3))
        lv.addWidget(self._mb_read_group("04H指令 （读输入寄存器）", 4))
        lv.addStretch(1)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        rv.addWidget(self._mb_write_group("05H指令 （写单个线圈寄存器）", 5, single=True))
        rv.addWidget(self._mb_write_group("06H指令 （写单个保持寄存器）", 6, single=True))
        rv.addWidget(self._mb_write_group("10H指令 （写多个保持寄存器）", 16, single=False))
        rv.addWidget(self._build_mb_any_group())
        rv.addStretch(1)
        mid.addWidget(left)
        mid.addWidget(right)
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 1)
        mid.setSizes([560, 560])
        bv.addWidget(mid, 1)
        split.addWidget(body)
        split.addWidget(self._build_mb_buffers())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)   # 多余高度给收发缓冲区
        split.setSizes([480, 210])
        tv.addWidget(split, 1)
        return w

    def _build_mb_conn_card(self) -> Card:
        card = Card("MODBUS RTU 串口",
                    "本页独立串口（与串口调试页互不占用）；FC01~FC06/FC10 自动组帧 + CRC16，"
                    "响应 900ms 超时")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(QLabel("端口"))
        self.cmb_m_port = QComboBox()
        self.cmb_m_port.setEditable(False)
        self.cmb_m_port.setMinimumWidth(150)
        h.addWidget(self.cmb_m_port)
        b = QPushButton("刷新")
        b.clicked.connect(self._refresh_ports)
        h.addWidget(b)
        self.btn_m_conn = QPushButton("打开串口")   # 沿用原版命名：不与「连接」状态机识别冲突
        self.btn_m_conn.clicked.connect(self._mb_toggle_serial)
        h.addWidget(self.btn_m_conn)
        self.btn_m_disc = QPushButton("关闭串口")
        self.btn_m_disc.clicked.connect(self._mb_close_serial)
        self.btn_m_disc.setEnabled(False)
        h.addWidget(self.btn_m_disc)
        h.addWidget(QLabel("波特率"))
        self.cmb_m_baud = QComboBox()
        self.cmb_m_baud.setEditable(True)
        self.cmb_m_baud.addItems(list(BAUDS))
        self.cmb_m_baud.setCurrentText("9600")   # Modbus 默认 9600
        self.cmb_m_baud.setFixedWidth(88)
        h.addWidget(self.cmb_m_baud)
        h.addWidget(QLabel("数据位"))
        self.cmb_m_data = QComboBox()
        self.cmb_m_data.addItems(list(DATAS))
        self.cmb_m_data.setCurrentText("8")
        self.cmb_m_data.setFixedWidth(56)
        h.addWidget(self.cmb_m_data)
        h.addWidget(QLabel("停止位"))
        self.cmb_m_stop = QComboBox()
        self.cmb_m_stop.addItems(list(STOPS))
        self.cmb_m_stop.setFixedWidth(56)
        h.addWidget(self.cmb_m_stop)
        h.addWidget(QLabel("校验位"))
        self.cmb_m_parity = QComboBox()
        for name, _c in PARITIES:
            self.cmb_m_parity.addItem(name)
        self.cmb_m_parity.setFixedWidth(92)
        h.addWidget(self.cmb_m_parity)
        h.addWidget(QLabel("流控"))
        self.cmb_m_flow = QComboBox()
        for name, _c in FLOWS:
            self.cmb_m_flow.addItem(name)
        self.cmb_m_flow.setFixedWidth(88)
        h.addWidget(self.cmb_m_flow)
        h.addStretch(1)
        self.lbl_m_state = QLabel("当前串口: 未连接")
        self.lbl_m_state.setObjectName("Muted")
        h.addWidget(self.lbl_m_state)
        card.body_lay.addLayout(h)
        return card

    def _mb_read_group(self, title, func) -> QGroupBox:
        box = QGroupBox(title)
        g = QGridLayout(box)
        g.setSpacing(6)
        g.addWidget(QLabel("485地址"), 0, 0)
        ed_slave = QLineEdit("1")
        ed_slave.setFixedWidth(70)
        g.addWidget(ed_slave, 0, 1)
        g.addWidget(QLabel("寄存器地址"), 0, 2)
        ed_addr = QLineEdit("0")
        ed_addr.setFixedWidth(90)
        g.addWidget(ed_addr, 0, 3)
        g.addWidget(QLabel("寄存器个数"), 0, 4)
        ed_qty = QLineEdit("1")
        ed_qty.setFixedWidth(70)
        g.addWidget(ed_qty, 0, 5)
        b = QPushButton("读取")
        g.addWidget(b, 0, 6)
        g.addWidget(QLabel("寄存器值"), 1, 0)
        ed_out = QLineEdit()
        ed_out.setReadOnly(True)
        ed_out.setStyleSheet("font-family:Consolas;")
        g.addWidget(ed_out, 1, 1, 1, 7)
        # 富余宽度给末尾空列(7)，让「寄存器值」输入框填满，「读取」按钮保持自然宽度不被拉变形
        g.setColumnStretch(7, 1)
        self._mb_reads[func] = (ed_slave, ed_addr, ed_qty, ed_out)
        b.clicked.connect(lambda _=False, f=func: self._mb_do_read(f))
        return box

    def _mb_write_group(self, title, func, single) -> QGroupBox:
        box = QGroupBox(title)
        g = QGridLayout(box)
        g.setSpacing(6)
        g.addWidget(QLabel("485地址"), 0, 0)
        ed_slave = QLineEdit("1")
        ed_slave.setFixedWidth(70)
        g.addWidget(ed_slave, 0, 1)
        g.addWidget(QLabel("寄存器地址"), 0, 2)
        ed_addr = QLineEdit("0")
        ed_addr.setFixedWidth(90)
        g.addWidget(ed_addr, 0, 3)
        g.addWidget(QLabel("寄存器值"), 0, 4)
        ed_val = QLineEdit("0")
        if not single:
            ed_val.setPlaceholderText("多个值用空格/逗号分隔")
        g.addWidget(ed_val, 0, 5)
        b = QPushButton("发送")
        g.addWidget(b, 0, 6)
        g.setColumnStretch(5, 1)
        self._mb_writes[func] = (ed_slave, ed_addr, ed_val, single)
        b.clicked.connect(lambda _=False, f=func: self._mb_do_write(f))
        return box

    def _build_mb_any_group(self) -> QGroupBox:
        box = QGroupBox("任意指令")
        h = QHBoxLayout(box)
        h.setSpacing(6)
        self.ed_mb_any = QLineEdit()
        self.ed_mb_any.setPlaceholderText("十六进制，例如 01 03 00 00 00 01")
        self.ed_mb_any.setStyleSheet("font-family:Consolas;")
        self.ed_mb_any.returnPressed.connect(lambda: self._mb_send_any(False))
        h.addWidget(self.ed_mb_any, 1)
        b = QPushButton("发送")
        b.clicked.connect(lambda: self._mb_send_any(False))
        h.addWidget(b)
        b = QPushButton("带CRC发送")
        b.clicked.connect(lambda: self._mb_send_any(True))
        h.addWidget(b)
        return box

    def _build_mb_buffers(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for title, attr in (("发送缓冲区", "txt_m_tx"), ("接收缓冲区", "txt_m_rx")):
            box = QGroupBox(title)
            v = QVBoxLayout(box)
            row = QHBoxLayout()
            row.addStretch(1)
            b = QPushButton("清空数据")
            b.clicked.connect(lambda _=False, a=attr: getattr(self, a).clear())
            row.addWidget(b)
            v.addLayout(row)
            txt = QPlainTextEdit()
            txt.setReadOnly(True)
            txt.setStyleSheet("font-family:Consolas;")
            txt.setMinimumHeight(110)
            txt.setMaximumBlockCount(3000)
            v.addWidget(txt)
            setattr(self, attr, txt)
            h.addWidget(box, 1)
        return w

    # ---------------------------------------------------------- MODBUS 串口
    def _mb_toggle_serial(self):
        if self.m_core.is_open:
            self._mb_close_serial()
        else:
            self._mb_open_serial()

    def _mb_open_serial(self):
        port = self.cmb_m_port.currentText().strip()
        if not port:
            QMessageBox.warning(self, "提示", "没有可用串口，请插入设备后重试。")
            return
        if self.s_core.is_open and self.s_core.port.upper() == port.upper():
            QMessageBox.warning(self, "端口被占用",
                                f"端口 {port} 正被本程序「串口调试」页占用。\n"
                                "两个分页各自使用独立串口，请在那一页先关闭，或换一个端口。")
            return
        c = dict(baud=self.cmb_m_baud.currentText().strip(),
                 bytesize=self.cmb_m_data.currentText(),
                 stopbits=self.cmb_m_stop.currentText(),
                 parity=self._parity_code(self.cmb_m_parity.currentText()),
                 flow=self._flow_code(self.cmb_m_flow.currentText()),
                 auto_answer="", rx_buf=8192, tx_buf=8192)
        ok, err = self.m_core.open(port, c["baud"], c["bytesize"], c["parity"],
                                   c["stopbits"], flow=c["flow"],
                                   auto_answer=c["auto_answer"],
                                   rx_buf=c["rx_buf"], tx_buf=c["tx_buf"])
        fixed = ""
        if not ok and port_param_error(err):
            bs, sb = downshift_params(c["bytesize"], c["stopbits"])
            if (bs, sb) != (str(c["bytesize"]), str(c["stopbits"])):
                ok2, err2 = self.m_core.open(port, c["baud"], bs, c["parity"], sb,
                                             flow=c["flow"],
                                             auto_answer=c["auto_answer"],
                                             rx_buf=c["rx_buf"], tx_buf=c["tx_buf"])
                if ok2:
                    fixed = ("驱动不支持 %s 位数据位 / %s 位停止位，"
                             "已自动改用 %s-%s" % (c["bytesize"], c["stopbits"], bs, sb))
                    self.cmb_m_data.setCurrentText(bs)
                    self.cmb_m_stop.setCurrentText(sb)
                    ok = True
                else:
                    err = err2 or err
        if not ok:
            QMessageBox.warning(self, "打开失败", port_param_hint(err))
            return
        if fixed:
            self._mb_log(self.txt_m_rx, fixed, C_ERR)
        self.btn_m_conn.setEnabled(False)
        self.btn_m_disc.setEnabled(True)
        self.lbl_m_state.setText("当前串口:%s 波特率: %s" % (port, c["baud"]))
        self._mb_log(self.txt_m_rx, "串口已打开 %s  %s %s-%s-%s" % (
            port, c["baud"], c["bytesize"], c["parity"], c["stopbits"]), C_SYS)

    def _mb_close_serial(self):
        was = self.m_core.is_open
        self.m_core.close()
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 链路关闭 = 通讯中断
        self.btn_m_conn.setEnabled(True)
        self.btn_m_disc.setEnabled(False)
        self.lbl_m_state.setText("当前串口: 未连接")
        if was:
            self._mb_log(self.txt_m_rx, "串口已关闭", C_SYS)

    # ---------------------------------------------------------- MODBUS 收发
    @staticmethod
    def _mb_log(widget, text, color=None):
        if color:
            widget.appendHtml('<span style="color:%s">%s</span>'
                              % (color, html.escape(text)))
        else:
            widget.appendPlainText(text)
        sb = widget.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _mb_send(self, frame, desc):
        if not self.m_core.is_open:
            QMessageBox.warning(self, "提示", "串口未打开，请先点「连接」。")
            return False
        ok, err = self.m_core.write(frame)
        if not ok:
            QMessageBox.warning(self, "发送失败", err)
            return False
        self._m_tx_bytes += len(frame)
        self._mb_log(self.txt_m_tx, "%s %s" % (time.strftime("%H:%M:%S"), hex_str(frame)),
                     C_TX)
        self._mb_log(self.txt_m_rx, "→ %s  [%s]" % (hex_str(frame), desc), C_TX)
        return True

    def _mb_do_read(self, func):
        ed_slave, ed_addr, ed_qty, ed_out = self._mb_reads[func]
        try:
            slave = intval(ed_slave.text(), 1)
            addr = intval(ed_addr.text(), 0)
            qty = intval(ed_qty.text(), 1)
            if not 0 <= slave <= 247:
                raise ValueError("485地址应在 0~247")
            if not 1 <= qty <= 125:
                raise ValueError("寄存器个数应在 1~125")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "参数错误", str(e))
            return
        body = bytes((slave, func, (addr >> 8) & 0xFF, addr & 0xFF,
                      (qty >> 8) & 0xFF, qty & 0xFF))
        frame = mb_append_crc(body)
        if not self._mb_send(frame, "%02XH 读 %d 个 @%d" % (func, qty, addr)):
            return
        self._m_pending = dict(func=func, slave=slave, qty=qty, out=ed_out,
                               title="%02XH" % func)
        self._m_buf = b""
        self._mb_timer.start(900)

    def _mb_do_write(self, func):
        ed_slave, ed_addr, ed_val, single = self._mb_writes[func]
        try:
            slave = intval(ed_slave.text(), 1)
            addr = intval(ed_addr.text(), 0)
            val = intval(ed_val.text(), 0) if single else None
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "参数错误", str(e))
            return

        if func == 5:
            body = bytes((slave, 5, (addr >> 8) & 0xFF, addr & 0xFF)) + \
                   (b"\xFF\x00" if val else b"\x00\x00")
        elif func == 6:
            body = bytes((slave, 6, (addr >> 8) & 0xFF, addr & 0xFF,
                          (val >> 8) & 0xFF, val & 0xFF))
        else:
            try:
                text = ed_val.text().replace(",", " ").replace("，", " ").split()
                regs = [intval(t, 0) for t in text]
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "参数错误",
                                    "寄存器值应填多个数值，用空格或逗号分隔：\n%s" % e)
                return
            if not 1 <= len(regs) <= 123:
                QMessageBox.warning(self, "参数错误", "寄存器个数应为 1~123 个")
                return
            body = bytes((slave, 16, (addr >> 8) & 0xFF, addr & 0xFF,
                          (len(regs) >> 8) & 0xFF, len(regs) & 0xFF, len(regs) * 2))
            for rg in regs:
                body += bytes(((rg >> 8) & 0xFF, rg & 0xFF))

        frame = mb_append_crc(body)
        if not self._mb_send(frame, "%02XH 写 @%d" % (func, addr)):
            return
        self._m_pending = dict(func=func, slave=slave, qty=0, out=None,
                               title="%02XH" % func)
        self._m_buf = b""
        self._mb_timer.start(900)

    def _mb_send_any(self, with_crc):
        text = self.ed_mb_any.text().strip()
        if not text:
            return
        try:
            body = parse_hex(text)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "格式错误",
                                "请按十六进制输入，例如 01 03 00 00 00 01：\n%s" % e)
            return
        if not body:
            return
        frame = mb_append_crc(body) if with_crc else body
        if self._mb_send(frame, "任意指令%s" % ("+CRC" if with_crc else "")):
            self._m_pending = dict(func=frame[1] if len(frame) > 1 else 0,
                                   slave=frame[0], qty=0, out=None, title="任意")
            self._m_buf = b""
            self._mb_timer.start(900)

    def _mb_on_timeout(self):
        p = self._m_pending
        self._m_pending = None
        if p:
            self._mb_log(self.txt_m_rx, "✗ %s 响应超时（900ms）" % p.get("title", ""), C_ERR)
            if p.get("out") is not None:
                p["out"].setText("超时")

    def _mb_on_rx(self, data):
        if not data:
            return
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 从站真实响应到达 = 通讯真正建立
        self._m_rx_bytes += len(data)
        self._m_buf += data
        self._mb_log(self.txt_m_rx, "← %s" % hex_str(data), C_RX)
        self._mb_parse()

    def _mb_parse(self):
        while len(self._m_buf) >= 5:
            func = self._m_buf[1]
            if func & 0x80:
                total = 5
            elif func in (1, 2, 3, 4):
                total = 3 + self._m_buf[2] + 2
            else:
                total = 8
            if len(self._m_buf) < total:
                break
            frame = self._m_buf[:total]
            self._m_buf = self._m_buf[total:]
            self._mb_handle(frame)

    def _mb_handle(self, frame):
        self._mb_timer.stop()
        p = self._m_pending
        self._m_pending = None

        if not mb_crc_ok(frame):
            self._mb_log(self.txt_m_rx, "✗ CRC 校验错误：%s" % hex_str(frame), C_ERR)
            if p and p.get("out") is not None:
                p["out"].setText("CRC错误")
            return

        func = frame[1]
        slave = frame[0]
        if func & 0x80:
            code = frame[2]
            names = {1: "非法功能码", 2: "非法数据地址", 3: "非法数据值",
                     4: "从站设备故障", 5: "确认", 6: "从站设备忙"}
            self._mb_log(self.txt_m_rx, "✗ 从站 %d 异常响应 %02XH：%s" % (
                slave, code, names.get(code, "未知")), C_ERR)
            if p and p.get("out") is not None:
                p["out"].setText("异常 %02XH" % code)
            return

        if func in (1, 2):
            n = frame[2]
            bits = []
            for i in range(n):
                b_ = frame[3 + i]
                for k in range(8):
                    bits.append((b_ >> k) & 1)
            qty = (p or {}).get("qty") or len(bits)
            vals = bits[:qty]
            disp = " ".join(str(v) for v in vals)
            if p and p.get("out") is not None:
                p["out"].setText(disp)
            self._mb_log(self.txt_m_rx, "✓ %02XH 从站%d 读回 %d 位：%s" % (
                func, slave, len(vals), disp), C_OK)
        elif func in (3, 4):
            n = frame[2] // 2
            regs = [(frame[3 + i * 2] << 8) | frame[4 + i * 2] for i in range(n)]
            disp = " ".join("0x%04X" % rg for rg in regs)
            if p and p.get("out") is not None:
                p["out"].setText(disp)
            self._mb_log(self.txt_m_rx, "✓ %02XH 从站%d 读回 %d 个寄存器：%s" % (
                func, slave, n, disp), C_OK)
            self._mb_log(self.txt_m_rx, "   十进制：%s" % ", ".join(str(rg) for rg in regs))
        else:
            self._mb_log(self.txt_m_rx, "✓ %02XH 从站%d 写入成功（回显一致）" % (func, slave),
                         C_OK)

    # ================================================================ 退出清理
    def shutdown(self):
        """退出/卸载：停定时器、关串口与网络、关落盘文件、回收线程（安全闭环）。"""
        self._timer.stop()
        self._stop_timed()
        self._mb_timer.stop()
        for core in (self.s_core, self.m_core):
            try:
                core.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.net.close()
        except Exception:  # noqa: BLE001
            pass
        for fp in (self._raw_fp, self._txt_fp):
            if fp:
                try:
                    fp.close()
                except Exception:  # noqa: BLE001
                    pass
        self._raw_fp = None
        self._txt_fp = None
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)
