# -*- coding: utf-8 -*-
"""RU 灵巧系列可编程直流电源 · 融合版界面（FusionHub 风格）。

Modbus-RTU 协议/寄存器/设备封装复用原上位机 ru 包（CRC16 低字节在前、
ModbusClient/RUDevice/registers），界面按整体 UI 风格重建：
设定电压/电流 → 开启输出（二次确认）→ 实时回读轮询。
"""
import queue

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog
from instrument_hub.widgets import Card

from .ru import ModbusClient, RUDevice, SerialTransport, TcpTransport


class RuPowerPage(QWidget):
    """RU 电源控制：连接 → 设定 V/I → 开输出（二次确认）→ 实时监控。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dev: RUDevice = None
        self.client: ModbusClient = None
        self._q = queue.Queue()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_conn_card())
        # 参数设定 | 实时监控 左右分布，分界线可拖拉
        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_param_card())
        mid.addWidget(self._build_status_card())
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 1)
        mid.setSizes([560, 560])
        root.addWidget(mid, 1)
        root.addWidget(self._build_log_card())

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------ 连接
    def _build_conn_card(self) -> Card:
        card = Card("通讯连接", "RS-232/485（8-N-1，默认 9600）或 RTU over TCP；Modbus-RTU，CRC16 低字节在前")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(QLabel("传输方式"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["串口", "RTU over TCP"])
        self.cmb_link.setFixedWidth(110)
        h.addWidget(self.cmb_link)

        h.addWidget(QLabel("端口/主机"))
        self.ed_port = QComboBox()
        self.ed_port.setEditable(False)
        # 串口候选自动枚举（打开即刷新），TCP 候选保留、默认 TCP
        from instrument_hub.serial_ports import enumerate_ports
        ports = enumerate_ports()
        self.ed_port.addItems((ports or ["COM3"]) + ["127.0.0.1:7502"])
        self.ed_port.setCurrentText("127.0.0.1:7502")
        self.ed_port.setFixedWidth(150)
        h.addWidget(self.ed_port)

        h.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.cmb_baud.setFixedWidth(86)
        h.addWidget(self.cmb_baud)

        h.addWidget(QLabel("从站地址"))
        self.sp_slave = QSpinBox()
        self.sp_slave.setRange(1, 247)
        self.sp_slave.setValue(1)
        self.sp_slave.setFixedWidth(70)
        h.addWidget(self.sp_slave)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.toggle_conn)
        h.addWidget(self.btn_connect)
        h.addStretch(1)
        self.lbl_info = QLabel("未连接")
        self.lbl_info.setObjectName("Muted")
        h.addWidget(self.lbl_info)
        card.body_lay.addLayout(h)
        card.body_lay.setAlignment(h, Qt.AlignTop)   # 内容顶对齐，卡内不留空旷
        return card

    # ------------------------------------------------------------ 参数
    def _build_param_card(self) -> Card:
        card = Card("参数设定", "按手册顺序：设定电压 → 设定电流 → 开启输出；「应用参数并输出」一键完成（二次确认）")
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)

        g.addWidget(QLabel("设定电压(V)"), 0, 0)
        self.sp_v = QDoubleSpinBox()
        self.sp_v.setRange(0, 600)
        self.sp_v.setDecimals(2)
        self.sp_v.setValue(12.00)
        self.sp_v.setFixedWidth(120)
        g.addWidget(self.sp_v, 0, 1)

        g.addWidget(QLabel("设定电流(A)"), 0, 2)
        self.sp_i = QDoubleSpinBox()
        self.sp_i.setRange(0, 100)
        self.sp_i.setDecimals(2)
        self.sp_i.setValue(3.00)
        self.sp_i.setFixedWidth(120)
        g.addWidget(self.sp_i, 0, 3)

        self.chk_ovp = QCheckBox("OVP 开启")
        g.addWidget(self.chk_ovp, 1, 0)
        self.sp_ovp = QDoubleSpinBox()
        self.sp_ovp.setRange(0, 600)
        self.sp_ovp.setDecimals(1)
        self.sp_ovp.setValue(30.0)
        self.sp_ovp.setFixedWidth(120)
        g.addWidget(self.sp_ovp, 1, 1)

        self.chk_ocp = QCheckBox("OCP 开启")
        g.addWidget(self.chk_ocp, 1, 2)
        self.sp_ocp = QDoubleSpinBox()
        self.sp_ocp.setRange(0, 100)
        self.sp_ocp.setDecimals(1)
        self.sp_ocp.setValue(5.0)
        self.sp_ocp.setFixedWidth(120)
        g.addWidget(self.sp_ocp, 1, 3)

        # 回读框 + 回读按钮（输出前安全闭环：设定值 vs 回读值比对）
        g.addWidget(QLabel("回读电压(V)"), 2, 0)
        self.ed_rb_v = QLineEdit("—")
        self.ed_rb_v.setReadOnly(True)
        self.ed_rb_v.setStyleSheet("font-family:Consolas;")
        g.addWidget(self.ed_rb_v, 2, 1)
        g.addWidget(QLabel("回读电流(A)"), 2, 2)
        self.ed_rb_i = QLineEdit("—")
        self.ed_rb_i.setReadOnly(True)
        self.ed_rb_i.setStyleSheet("font-family:Consolas;")
        g.addWidget(self.ed_rb_i, 2, 3)
        b_rb = QPushButton("回读设定值")
        b_rb.setToolTip("读回设定寄存器并显示（设定值下发后也会自动回读）")
        b_rb.clicked.connect(self.readback_setpoints)
        g.addWidget(b_rb, 2, 4)
        card.body_lay.addLayout(g)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        b_set = QPushButton("下发设定")
        b_set.clicked.connect(self.write_settings)
        bar.addWidget(b_set)
        b_prot = QPushButton("下发保护")
        b_prot.clicked.connect(self.write_protection)
        bar.addWidget(b_prot)
        self.btn_output = QPushButton("开启输出")
        self.btn_output.clicked.connect(lambda: self.set_output(True))
        bar.addWidget(self.btn_output)
        b_off = QPushButton("关闭输出")
        b_off.clicked.connect(lambda: self.set_output(False))
        bar.addWidget(b_off)
        b_apply = QPushButton("应用参数并输出")
        b_apply.setProperty("selfStyled", True)   # 自绘红色警示钮，框架不按文字刷色
        b_apply.setStyleSheet(
            "QPushButton{background:#B01030; color:#FFFFFF; border:2px solid #8A0C26;"
            " border-radius:10px; font-weight:700; padding:6px 16px;}")
        b_apply.clicked.connect(self.apply_all)
        bar.addWidget(b_apply)
        bar.addStretch(1)
        card.body_lay.addLayout(bar)
        # 设定参数栏放大：文字/输入框/按钮加大，填满卡片不留空旷
        for lb in card.findChildren(QLabel):
            lb.setStyleSheet("font-size:13px;")
        for sp in card.findChildren(QDoubleSpinBox):
            sp.setStyleSheet("QDoubleSpinBox{font-size:12px; min-height:30px;}")
            sp.setFixedWidth(150)
        for b in card.findChildren(QPushButton):
            b.setMinimumHeight(36)
        for chk in card.findChildren(QCheckBox):
            chk.setStyleSheet("font-size:12px;")
        return card

    # ------------------------------------------------------------ 状态
    def _build_status_card(self) -> Card:
        card = Card("实时监控", "电压/电流回读、输出状态与状态位（每秒刷新）")
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(8)
        self.lbl_v = QLabel("电压：-- V")
        self.lbl_v.setStyleSheet("font-size:20px; font-weight:800; color:#0E7490;")
        g.addWidget(self.lbl_v, 0, 0)
        self.lbl_i = QLabel("电流：-- A")
        self.lbl_i.setStyleSheet("font-size:20px; font-weight:800; color:#7C3AED;")
        g.addWidget(self.lbl_i, 0, 1)
        self.lbl_out = QLabel("输出：--")
        self.lbl_out.setStyleSheet("font-size:16px; font-weight:700;")
        g.addWidget(self.lbl_out, 0, 2)
        self.lbl_st = QLabel("状态：CC -　CV -　OVP -　OCP -　OTP -")
        self.lbl_st.setObjectName("Muted")
        g.addWidget(self.lbl_st, 0, 3)
        self.lbl_ver = QLabel("软件版本：-　额定：- V / - A")
        self.lbl_ver.setObjectName("Muted")
        g.addWidget(self.lbl_ver, 1, 0, 1, 4)
        card.body_lay.addLayout(g)
        return card

    def _build_log_card(self) -> Card:
        card = Card("通讯日志", "收发帧记录，便于定位通讯问题")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(110)
        card.body_lay.addWidget(self.log)
        return card

    # ------------------------------------------------------------ 动作
    def toggle_conn(self) -> None:
        if self.dev is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.dev = self.client = None
            self.btn_connect.setText("连接")
            self.btn_connect.setObjectName("btnConnect")
            self.lbl_info.setText("未连接")
            self._append("已断开连接")
            return
        try:
            text = self.ed_port.currentText().strip()
            if self.cmb_link.currentIndex() == 0:
                tr = SerialTransport(text, baudrate=int(self.cmb_baud.currentText()))
            else:
                host, _, port = text.partition(":")
                tr = TcpTransport(host or "127.0.0.1", int(port or 7502))
            tr.open()
            self.client = ModbusClient(tr, unit_id=self.sp_slave.value(),
                                       logger=self._modbus_log)
            self.dev = RUDevice(self.client)
            v_rated, i_rated = self.dev.read_rated()
            self.btn_connect.setText("已连接")
            self.btn_connect.setObjectName("btnConnected")
            self.lbl_info.setText(f"已连接　额定 {v_rated}V/{i_rated}A")
            self._append(f"连接成功：{text} @ 从站 {self.sp_slave.value()}")
            self._tick()
        except Exception as e:
            self.dev = self.client = None
            self._append(f"连接失败：{e}")

    def write_settings(self) -> None:
        if not self._ensure():
            return
        try:
            self.dev.set_voltage_current(self.sp_v.value(), self.sp_i.value())
            self._append(f"已设定 {self.sp_v.value()}V / {self.sp_i.value()}A")
        except Exception as e:
            self._append(f"设定失败：{e}")
            return
        self.readback_setpoints()   # 下发后自动回读一次

    def readback_setpoints(self):
        """回读电压/电流设定寄存器并刷新回读框；返回 (v_raw, i_raw) 或 None。"""
        if not self._ensure():
            return None
        try:
            v_raw = self.dev.read_holding("v_set")
            i_raw = self.dev.read_holding("i_set")
        except Exception as e:
            self._append(f"回读失败：{e}")
            return None
        v = self.dev.scale_in(v_raw, self.dev.v_dec)
        i = self.dev.scale_in(i_raw, self.dev.i_dec)
        self.ed_rb_v.setText(f"{v:.{self.dev.v_dec}f} (raw {v_raw})")   # 定显 + raw 对表
        self.ed_rb_i.setText(f"{i:.{self.dev.i_dec}f} (raw {i_raw})")
        self._append(f"回读设定：{v:g} V / {i:g} A（原始 {v_raw}/{i_raw}）")
        return v_raw, i_raw

    def _verify_setpoints(self) -> bool:
        """输出前安全闭环：设定值 vs 回读值比对，不一致弹窗并返回 False（禁止输出）。"""
        rb = self.readback_setpoints()
        if rb is None:
            return False
        v_raw, i_raw = rb
        try:
            exp_v = self.dev.scale_out(self.sp_v.value(), self.dev.v_dec)
            exp_i = self.dev.scale_out(self.sp_i.value(), self.dev.i_dec)
        except Exception as e:
            QMessageBox.warning(self, "设定值无效", f"设定值换算失败：{e}")
            return False
        bad = []
        if exp_v != v_raw:
            bad.append(f"电压：设定原始 {exp_v} ≠ 回读原始 {v_raw}")
        if exp_i != i_raw:
            bad.append(f"电流：设定原始 {exp_i} ≠ 回读原始 {i_raw}")
        if bad:
            QMessageBox.warning(
                self, "设定值与回读值不一致，已禁止开启输出",
                "设备里的设定值和上位机设定不一致，为安全起见不允许开启输出：\n\n"
                + "\n".join(bad)
                + "\n\n请重新「下发设定」并确认回读一致后再开启输出。")
            self._append("输出前校验不一致，已禁止开启输出：" + "；".join(bad))
            return False
        self._append("输出前校验通过：设定值与回读值一致")
        return True

    def write_protection(self) -> None:
        if not self._ensure():
            return
        try:
            self.dev.set_protection(ovp_en=self.chk_ovp.isChecked(),
                                    ovp_val=self.sp_ovp.value(),
                                    ocp_en=self.chk_ocp.isChecked(),
                                    ocp_val=self.sp_ocp.value())
            self._append(f"保护已下发：OVP {'开' if self.chk_ovp.isChecked() else '关'}"
                         f" {self.sp_ovp.value()}V　OCP {'开' if self.chk_ocp.isChecked() else '关'}"
                         f" {self.sp_ocp.value()}A")
        except Exception as e:
            self._append(f"保护下发失败：{e}")

    def set_output(self, on: bool) -> None:
        """输出开关：开启为电源输出动作，须回读校验 + 二次确认。"""
        if not self._ensure():
            return
        if on:
            if not self._verify_setpoints():
                return
            dlg = ConfirmOutputDialog("RU 灵巧系列电源", "开启输出",
                                      "输出端将带电！确认接线与量程无误、负载连接可靠后再开启。",
                                      f"设定 {self.sp_v.value()}V / {self.sp_i.value()}A", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        try:
            self.dev.set_output_confirmed(on)
            self._append(f"输出已{'开启' if on else '关闭'}")
            self._tick()
        except Exception as e:
            self._append(f"输出操作失败：{e}")

    def apply_all(self) -> None:
        """一键：设定电压/电流（单点写）→ 回读校验 → 开启输出（二次确认）。"""
        if not self._ensure():
            return
        try:
            self.dev.set_voltage(self.sp_v.value())
            self.dev.set_current(self.sp_i.value())
            self._append(f"已设定 {self.sp_v.value()}V / {self.sp_i.value()}A")
        except Exception as e:
            self._append(f"设定失败：{e}")
            return
        if not self._verify_setpoints():
            return
        dlg = ConfirmOutputDialog("RU 灵巧系列电源", "应用参数并开启输出",
                                  "将下发 V/I 设定并开启输出端带电！确认接线与安全无误。",
                                  f"设定 {self.sp_v.value()}V / {self.sp_i.value()}A", self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return
        try:
            self.dev.set_output_confirmed(True)
            self._append(f"已应用 {self.sp_v.value()}V/{self.sp_i.value()}A 并开启输出")
            self._tick()
        except Exception as e:
            self._append(f"应用失败：{e}")

    # ------------------------------------------------------------ 轮询
    def _tick(self) -> None:
        while not self._q.empty():
            self._append(self._q.get_nowait())
        if self.dev is None:
            return
        try:
            snap = self.dev.poll_snapshot()
            from instrument_hub.comm_state import mark_ok
            mark_ok(self)   # 轮询回读成功 = 通讯真正建立
            self.lbl_v.setText(f"电压：{snap.get('v_read', '--')} V")
            self.lbl_i.setText(f"电流：{snap.get('i_read', '--')} A")
            out = snap.get("output")
            self.lbl_out.setText("输出：" + ("开" if out else "关") if out is not None else "输出：--")
            self.lbl_out.setStyleSheet(
                "font-size:16px; font-weight:700; color:"
                + ("#B01030" if out else "#047857") if out is not None else "")
            self.lbl_st.setText("状态：CC {cc}　CV {cv}　OVP {ovp}　OCP {ocp}　OTP {otp}".format(
                cc=_onoff(snap.get("st_cc")), cv=_onoff(snap.get("st_cv")),
                ovp=_onoff(snap.get("st_ovp")), ocp=_onoff(snap.get("st_ocp")),
                otp=_onoff(snap.get("st_otp"))))
            self.lbl_ver.setText(
                f"软件版本：{snap.get('sw_ver', '-')}　"
                f"额定：{snap.get('v_rated', '-')} V / {snap.get('i_rated', '-')} A")
        except Exception as e:
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)   # 轮询失败 = 通讯中断
            self._append(f"轮询失败：{e}")

    # ------------------------------------------------------------ 工具
    def _ensure(self) -> bool:
        if self.dev is None:
            self._append("请先连接电源")
            return False
        return True

    def _modbus_log(self, *args) -> None:
        try:
            self._q.put(" ".join(str(a) for a in args if a))
        except Exception:
            pass

    def _append(self, text: str) -> None:
        self.log.appendPlainText(str(text))

    def shutdown(self) -> None:
        """退出保护：先关输出再断链（电源安全闭环）。"""
        self._timer.stop()
        if self.dev is not None:
            try:
                self.dev.set_output(False)
            except Exception:
                pass
            try:
                self.client.close()
            except Exception:
                pass
            self.dev = self.client = None


def _onoff(v):
    return "-" if v is None else ("ON" if v else "OFF")
