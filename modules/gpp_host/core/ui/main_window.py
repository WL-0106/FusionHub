"""GPP 上位机主窗口：连接管理、通道控制、实时曲线、数据记录、指令日志。"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)
from PyQt5.QtSerialPort import QSerialPortInfo

from .. import scpi
from ..driver import ConnectParams, GppDriver
from ..models import LinkType, MODEL_ORDER, generic_specs, specs_for
from ..recorder import CsvRecorder
from ..theme import set_role
from .channel_card import ChannelCard
from .chart_widget import RealtimeChart

_MONO = QFont("Consolas", 9)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPP 系列可编程直流电源 · 上位机")
        self.resize(1240, 820)

        self.driver = GppDriver(self)
        self.recorder = CsvRecorder()
        self.cards: dict[int, ChannelCard] = {}
        self._connected = False
        self._model = "GPP-4323"

        self._build_ui()
        self._wire_driver()
        self._rebuild_cards()
        self.driver.start()

    # ---------------- UI 构建 ----------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        root.addWidget(self._build_connect_bar())
        root.addWidget(self._build_global_bar())

        split = QSplitter(Qt.Vertical)
        mid = QSplitter(Qt.Horizontal)
        # 曲线显示在左、CH1-4 设置区在右（用户要求左右对调）
        mid.addWidget(self._build_chart_panel())
        mid.addWidget(self._build_cards_area())
        mid.setStretchFactor(0, 6)
        mid.setStretchFactor(1, 5)
        mid.setSizes([640, 560])
        split.addWidget(mid)
        split.addWidget(self._build_log_panel())
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([640, 170])
        root.addWidget(split, 1)

        self.status = self.statusBar()
        self.status_led = QLabel("● 未连接")
        self.status_led.setStyleSheet("color:#9CA3AF; font-weight:700;")
        self.status.addWidget(self.status_led)
        self.status_rec = QLabel("")
        self.status_rec.setStyleSheet("color:#6B7280;")
        self.status.addPermanentWidget(self.status_rec)

    def _build_connect_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet("QFrame{background:#F9FAFB; border:1px solid #E5E7EB;"
                          "border-radius:8px;}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        lay.addWidget(QLabel("接口"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItem("RS-232 串口", "rs232")
        self.cmb_link.addItem("USB 虚拟串口", "usb")
        self.cmb_link.addItem("LAN 网口", "lan")
        self.cmb_link.addItem("模拟设备", "sim")
        self.cmb_link.setFixedWidth(124)
        lay.addWidget(self.cmb_link)

        self.stack = QStackedWidget()
        # 串口页
        sp = QWidget()
        spl = QHBoxLayout(sp)
        spl.setContentsMargins(0, 0, 0, 0)
        spl.setSpacing(6)
        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(150)
        self.cmb_port.setEditable(False)
        spl.addWidget(self.cmb_port)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setFixedWidth(52)
        btn_refresh.setProperty("role", "outline")
        btn_refresh.clicked.connect(self._refresh_ports)
        spl.addWidget(btn_refresh)
        spl.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        for b in (9600, 19200, 38400, 57600, 115200):
            self.cmb_baud.addItem(str(b), b)
        self.cmb_baud.setCurrentIndex(4)     # 默认 115200
        self.cmb_baud.setFixedWidth(88)
        spl.addWidget(self.cmb_baud)
        self.stack.addWidget(sp)
        # LAN 页
        lp = QWidget()
        lpl = QHBoxLayout(lp)
        lpl.setContentsMargins(0, 0, 0, 0)
        lpl.setSpacing(6)
        lpl.addWidget(QLabel("IP"))
        self.ed_ip = QLineEdit("169.254.129.17")
        self.ed_ip.setFixedWidth(140)
        lpl.addWidget(self.ed_ip)
        lpl.addWidget(QLabel("端口"))
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(1026)
        self.sp_port.setFixedWidth(80)
        lpl.addWidget(self.sp_port)
        self.stack.addWidget(lp)
        # 模拟页
        sim = QWidget()
        siml = QHBoxLayout(sim)
        siml.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("无硬件试用：使用内置模拟器，指令与真实设备一致")
        lbl.setStyleSheet("color:#6B7280;")
        siml.addWidget(lbl)
        self.stack.addWidget(sim)

        lay.addWidget(self.stack)
        lay.addSpacing(6)
        lay.addWidget(QLabel("机型"))
        self.cmb_model = QComboBox()
        self.cmb_model.addItems(MODEL_ORDER)
        self.cmb_model.setEditable(True)
        self.cmb_model.setCurrentText(self._model)
        self.cmb_model.setFixedWidth(110)
        lay.addWidget(self.cmb_model)
        lay.addStretch(1)

        self.btn_conn = QPushButton("连接")
        self.btn_conn.setFixedWidth(96)
        self.btn_conn.setProperty("role", "accent")
        self.btn_conn.clicked.connect(self._toggle_connect)
        lay.addWidget(self.btn_conn)

        self.lbl_idn = QLabel("未连接")
        self.lbl_idn.setStyleSheet("color:#6B7280;")
        self.lbl_idn.setMinimumWidth(340)
        lay.addWidget(self.lbl_idn)

        self.cmb_link.currentIndexChanged.connect(self._link_changed)
        self._link_changed()
        self._refresh_ports()
        return bar

    def _build_global_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet("QFrame{background:#F9FAFB; border:1px solid #E5E7EB;"
                          "border-radius:8px;}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        self.btn_all_on = QPushButton("全部开启")
        self.btn_all_off = QPushButton("全部关闭")
        self.btn_all_on.setProperty("role", "ok")
        self.btn_all_off.setProperty("role", "danger")
        for b in (self.btn_all_on, self.btn_all_off):
            b.setEnabled(False)
            b.setFixedWidth(84)
        self.btn_all_on.clicked.connect(lambda: self._all_output(True))
        self.btn_all_off.clicked.connect(lambda: self._all_output(False))
        lay.addWidget(self.btn_all_on)
        lay.addWidget(self.btn_all_off)

        lay.addWidget(QLabel("跟踪"))
        self.cmb_track = QComboBox()
        self.cmb_track.addItem("独立", "independent")
        self.cmb_track.addItem("串联", "series")
        self.cmb_track.addItem("并联", "parallel")
        self.cmb_track.setFixedWidth(84)
        self.cmb_track.setEnabled(False)
        self.cmb_track.currentIndexChanged.connect(self._tracking_changed)
        lay.addWidget(self.cmb_track)

        lay.addSpacing(10)
        lay.addWidget(QLabel("采样"))
        self.cmb_interval = QComboBox()
        for txt, sec in (("0.2 s", 0.2), ("0.5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0)):
            self.cmb_interval.addItem(txt, sec)
        self.cmb_interval.setCurrentIndex(1)
        self.cmb_interval.setFixedWidth(76)
        self.cmb_interval.currentIndexChanged.connect(
            lambda: self.driver.set_poll_interval(self.cmb_interval.currentData()))
        lay.addWidget(self.cmb_interval)
        self.chk_pause = QCheckBox("暂停采集")
        self.chk_pause.toggled.connect(
            lambda on: self.driver.set_polling(not on))
        lay.addWidget(self.chk_pause)

        lay.addStretch(1)

        self.btn_rec = QPushButton("开始记录")
        self.btn_rec.setFixedWidth(88)
        self.btn_rec.setCheckable(True)
        self.btn_rec.setProperty("role", "record")
        self.btn_rec.toggled.connect(self._toggle_record)
        lay.addWidget(self.btn_rec)
        self.ed_recpath = QLineEdit()
        self.ed_recpath.setPlaceholderText("记录路径留空则自动 data/gpp_时间戳.csv")
        self.ed_recpath.setReadOnly(True)
        lay.addWidget(self.ed_recpath, 1)
        self.btn_browse = QPushButton("选择…")
        self.btn_browse.setFixedWidth(64)
        self.btn_browse.setProperty("role", "outline")
        self.btn_browse.clicked.connect(self._browse_record)
        lay.addWidget(self.btn_browse)
        return bar

    def _build_cards_area(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        self.cards_layout = QGridLayout(container)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(8)
        scroll.setWidget(container)
        scroll.setMinimumWidth(330)
        return scroll

    def _build_chart_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.series_group: dict[str, QPushButton] = {}
        for key, name in (("v", "电压"), ("i", "电流"), ("p", "功率")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setFixedWidth(64)
            b.setProperty("kind", key)
            b.clicked.connect(lambda _, k=key: self._select_series(k))
            self.series_group[key] = b
            top.addWidget(b)
        self.series_group["v"].setChecked(True)
        top.addSpacing(8)
        top.addWidget(QLabel("时窗"))
        self.cmb_span = QComboBox()
        for txt, sec in (("30 秒", 30), ("1 分钟", 60), ("2 分钟", 120),
                         ("5 分钟", 300), ("10 分钟", 600)):
            self.cmb_span.addItem(txt, sec)
        self.cmb_span.setCurrentIndex(1)
        self.cmb_span.setFixedWidth(88)
        self.cmb_span.currentIndexChanged.connect(
            lambda: self.chart.set_span(self.cmb_span.currentData()))
        top.addWidget(self.cmb_span)
        self.btn_chart_pause = QPushButton("暂停曲线")
        self.btn_chart_pause.setCheckable(True)
        self.btn_chart_pause.setFixedWidth(84)
        self.btn_chart_pause.setProperty("role", "hold")
        self.btn_chart_pause.toggled.connect(self._toggle_chart_pause)
        top.addWidget(self.btn_chart_pause)
        btn_clear = QPushButton("清空")
        btn_clear.setFixedWidth(60)
        btn_clear.clicked.connect(lambda: self.chart.clear())
        top.addWidget(btn_clear)
        top.addStretch(1)
        lay.addLayout(top)

        vis_row = QHBoxLayout()
        vis_row.setSpacing(10)
        vis_row.addWidget(QLabel("显示"))
        self.chk_vis: dict[int, QCheckBox] = {}
        vis_row.addStretch(1)
        lay.addLayout(vis_row)

        self.chart = RealtimeChart()
        lay.addWidget(self.chart, 1)
        return panel

    def _build_log_panel(self) -> QGroupBox:
        grp = QGroupBox("SCPI 指令日志")
        grp.setCheckable(True)
        grp.setChecked(True)
        lay = QVBoxLayout(grp)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(_MONO)
        self.log.setMaximumBlockCount(2000)
        self.log.setMinimumHeight(90)
        lay.addWidget(self.log)
        return grp

    # ---------------- 通道卡片 ----------------
    def _rebuild_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cards.clear()
        specs = specs_for(self._model) if self._model in MODEL_ORDER else generic_specs(4)
        for i, spec in enumerate(specs):
            card = ChannelCard(spec)
            card.command.connect(self.driver.set)
            card.set_changed.connect(self._on_set_changed)
            card.output_toggled.connect(self._on_output_toggled)
            card.set_connected(self._connected)
            self.cards_layout.addWidget(card, i // 2, i % 2)
            self.cards[spec.index] = card
        # 曲线可见通道勾选
        for idx in list(self.chk_vis):
            self.chk_vis[idx].deleteLater()
            del self.chk_vis[idx]
        lay = self.chart.parentWidget().layout()
        # 追加到“显示”行
        vis_row = lay.itemAt(1).layout()
        while vis_row.count() > 2:      # 保留 label 与 stretch
            it = vis_row.takeAt(1)
            if it.widget():
                it.widget().deleteLater()
        for spec in specs:
            chk = QCheckBox(spec.label)
            chk.setStyleSheet(f"color:{spec.color}; font-weight:600;")
            chk.setChecked(True)
            chk.toggled.connect(self._visibility_changed)
            self.chk_vis[spec.index] = chk
            vis_row.insertWidget(vis_row.count() - 1, chk)
        self.chart.set_specs(specs)
        self._visibility_changed()

    def _visibility_changed(self) -> None:
        vis = {i for i, c in self.chk_vis.items() if c.isChecked()}
        self.chart.set_visible(vis)

    # ---------------- 驱动接线 ----------------
    def _wire_driver(self) -> None:
        d = self.driver
        d.state_changed.connect(self._on_state)
        d.snapshot.connect(self._on_snapshot)
        d.samples.connect(self._on_samples)
        d.notice.connect(self._on_notice)
        d.fatal.connect(self._on_fatal)
        d.log_tx.connect(lambda s: self._log_line("→", s))
        d.log_rx.connect(lambda s: self._log_line("←", s))

    def _log_line(self, direction: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log.appendPlainText(f"{stamp} {direction} {text}")

    # ---------------- 连接流程 ----------------
    def _link_changed(self) -> None:
        key = self.cmb_link.currentData()
        self.stack.setCurrentIndex({"rs232": 0, "usb": 0, "lan": 1, "sim": 2}[key])

    def _refresh_ports(self) -> None:
        current = self.cmb_port.currentText()
        self.cmb_port.clear()
        for info in QSerialPortInfo.availablePorts():
            desc = info.description()
            label = f"{info.portName()} — {desc}" if desc else info.portName()
            self.cmb_port.addItem(label, info.portName())
        self.cmb_port.setCurrentIndex(0)
        if current:
            for i in range(self.cmb_port.count()):
                if self.cmb_port.itemData(i) == current or current.startswith(str(self.cmb_port.itemData(i))):
                    self.cmb_port.setCurrentIndex(i)
                    break

    def _build_params(self) -> Optional[ConnectParams]:
        key = self.cmb_link.currentData()
        if key == "sim":
            return ConnectParams(simulate=True, sim_model=self.cmb_model.currentText().strip())
        if key == "lan":
            host = self.ed_ip.text().strip()
            if not host:
                QMessageBox.warning(self, "连接", "请填写仪器 IP 地址。")
                return None
            return ConnectParams(link=LinkType.LAN, host=host,
                                 tcp_port=self.sp_port.value())
        port = self.cmb_port.currentData() or self.cmb_port.currentText().split(" ")[0].strip()
        if not port:
            QMessageBox.warning(self, "连接", "未选择串口，请先刷新并选择端口。")
            return None
        return ConnectParams(link=LinkType.SERIAL, port=str(port),
                             baud=int(self.cmb_baud.currentData()))

    def _toggle_connect(self) -> None:
        if self._connected:
            self.btn_conn.setEnabled(False)
            self.driver.disconnect(send_local=True)
            QTimer.singleShot(600, lambda: self.btn_conn.setEnabled(True))
            return
        params = self._build_params()
        if params is None:
            return
        self._model = self.cmb_model.currentText().strip()
        self.btn_conn.setEnabled(False)
        self.btn_conn.setText("连接中…")
        self.driver.connect(params)

    def _on_state(self, st) -> None:
        self._connected = st.connected
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("已连接" if st.connected else "连接")
        self.btn_conn.setObjectName("btnConnected" if st.connected else "btnConnect")
        if not st.connected:
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)   # 链路断开 = 通讯中断，右上角指示灯回灰
        # 连接=蓝色，断开=红色，切换时强制刷新样式
        set_role(self.btn_conn, "danger" if st.connected else "accent")
        if st.connected:
            self.status_led.setText(f"● 已连接 · {st.detail}")
            self.status_led.setStyleSheet("color:#16A34A; font-weight:700;")
            self.lbl_idn.setText(st.idn)
            if st.model in MODEL_ORDER:
                self._model = st.model
                self.cmb_model.blockSignals(True)
                self.cmb_model.setCurrentText(st.model)
                self.cmb_model.blockSignals(False)
        else:
            self.status_led.setText(
                "● 未连接" if st.detail in ("", "已断开") else f"● {st.detail}")
            self.status_led.setStyleSheet("color:#9CA3AF; font-weight:700;")
            self.lbl_idn.setText(st.detail or "未连接")
        self._rebuild_cards()
        for card in self.cards.values():
            card.set_connected(st.connected)
        self.btn_all_on.setEnabled(st.connected)
        self.btn_all_off.setEnabled(st.connected)
        self.cmb_track.setEnabled(
            st.connected and self._model != "GPP-1326" and len(self.cards) >= 2)

    def _on_snapshot(self, snap: dict) -> None:
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到通道回读快照 = 通讯真正建立
        for n, card in self.cards.items():
            cs = snap.get("channels", {}).get(n)
            if cs:
                card.apply_snapshot(cs)
                card.set_connected(True)

    def _on_samples(self, samples: list) -> None:
        for s in samples:
            card = self.cards.get(s.channel)
            if card:
                card.apply_sample(s)
        self.chart.append_samples(samples)
        if self.recorder.active:
            self.recorder.record(samples)
            self.status_rec.setText(f"记录中 {self.recorder.rows} 行")

    def _on_notice(self, msg: str) -> None:
        self.status.showMessage(msg, 8000)
        self._log_line("!!", msg)

    def _on_fatal(self, msg: str) -> None:
        self._log_line("!!", msg)
        self.status.showMessage(msg, 10000)
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 致命通讯错误 = 通讯中断

    # ---------------- 控制动作 ----------------
    def _on_set_changed(self, ch: int, kind: str, value: float) -> None:
        if not self._connected:
            return
        if kind == "v":
            self.driver.set_local_value(ch, "v", value)
            self.driver.set(scpi.source_volt_set(ch, value))
        elif kind == "i":
            self.driver.set_local_value(ch, "i", value)
            self.driver.set(scpi.source_curr_set(ch, value))
        elif kind == "ovp":
            self.driver.set(scpi.ovp_set(ch, value))
        elif kind == "ocp":
            self.driver.set(scpi.ocp_set(ch, value))
        elif kind == "res":
            self.driver.set(scpi.load_res_set(ch, value))

    def _on_output_toggled(self, ch: int, on: bool) -> None:
        if not self._connected:
            return
        if on:
            # 电源开启输出：输出端带电，须二次确认（对齐框架安全规范）
            from instrument_hub.dialogs import ConfirmOutputDialog
            card = self.cards.get(ch)
            label = card.spec.label if card else f"CH{ch}"
            summary = "　".join(
                f"{self.cards[ch].v_spin.value()}V / {self.cards[ch].i_spin.value()}A")
            dlg = ConfirmOutputDialog(
                "GPP 系列电源", f"开启 {label} 输出",
                "输出端将带电！确认接线与量程无误、负载连接可靠后再开启。",
                f"设定 {summary}", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                # 取消：回滚开关勾选态，不改变输出状态
                if card is not None:
                    card.out_btn.blockSignals(True)
                    card.out_btn.setChecked(False)
                    card.out_btn.blockSignals(False)
                return
        self.driver.set_local_value(ch, "out", on)
        self.driver.set(scpi.output_set(ch, on))

    def _all_output(self, on: bool) -> None:
        if not self._connected:
            return
        if on:
            # 一键全开输出：带高压/带载风险，须二次确认
            from instrument_hub.dialogs import ConfirmOutputDialog
            dlg = ConfirmOutputDialog(
                "GPP 系列电源", "全部通道开启输出",
                "所有通道输出端将同时带电！确认各通道接线、量程与负载无误后再开启。",
                "", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                # 取消：回滚各通道开关勾选态
                for card in self.cards.values():
                    card.out_btn.blockSignals(True)
                    card.out_btn.setChecked(False)
                    card.out_btn.blockSignals(False)
                return
        for n in self.cards:
            self.driver.set_local_value(n, "out", on)
        self.driver.set(scpi.ALLOUTON if on else scpi.ALLOUTOFF)

    def _tracking_changed(self) -> None:
        if not self._connected:
            return
        self.driver.set(scpi.tracking_set(self.cmb_track.currentData()))

    # ---------------- 图表控制 ----------------
    def _select_series(self, key: str) -> None:
        for k, b in self.series_group.items():
            b.setChecked(k == key)
        self.chart.set_series(key)

    def _toggle_chart_pause(self, paused: bool) -> None:
        self.chart.set_paused(paused)
        self.btn_chart_pause.setText("继续曲线" if paused else "暂停曲线")

    # ---------------- 数据记录 ----------------
    def _browse_record(self) -> None:
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "选择记录文件", os.path.join(os.getcwd(), f"gpp_{datetime.now():%Y%m%d_%H%M%S}.csv"),
            "CSV 文件 (*.csv)")
        if path:
            self.ed_recpath.setText(path)

    def _toggle_record(self, on: bool) -> None:
        if on:
            path = self.ed_recpath.text().strip()
            if not path:
                path = os.path.join(
                    os.getcwd(), "data",
                    f"gpp_{datetime.now():%Y%m%d_%H%M%S}.csv")
                self.ed_recpath.setText(path)
            try:
                self.recorder.start(path)
            except OSError as e:
                self.btn_rec.setChecked(False)
                QMessageBox.warning(self, "记录", f"无法创建文件:\n{e}")
                return
            self.btn_rec.setText("停止记录")
            self.btn_browse.setEnabled(False)
            self.status_rec.setText(f"记录中 {path}")
        else:
            rows = self.recorder.rows
            self.recorder.stop()
            self.btn_rec.setText("开始记录")
            self.btn_browse.setEnabled(True)
            self.status_rec.setText(f"已停止，共 {rows} 行")

    # ---------------- 退出 ----------------
    def closeEvent(self, event) -> None:
        try:
            if self.driver.is_connected():
                box = QMessageBox(self)
                box.setWindowTitle("退出")
                box.setText("设备仍处于连接状态，退出前是否先关闭所有输出？")
                btn_off = box.addButton("关闭输出并退出", QMessageBox.AcceptRole)
                btn_plain = box.addButton("直接退出", QMessageBox.DestructiveRole)
                box.addButton(QMessageBox.Cancel)
                box.exec_()
                clicked = box.clickedButton()
                if clicked is btn_off:
                    self.driver.shutdown(outputs_off=True)
                elif clicked is btn_plain:
                    self.driver.shutdown(outputs_off=False)
                else:
                    event.ignore()
                    return
            else:
                self.driver.shutdown(outputs_off=False)
            if self.recorder.active:
                self.recorder.stop()
            event.accept()
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass
