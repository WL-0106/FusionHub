# -*- coding: utf-8 -*-
"""继电器板卡(12CH) · 融合版界面（FusionHub 风格）。

Modbus 协议/传输/客户端复用原上位机 relay_hmi.py（CRC/Transport/RelayClient/Worker），
界面按整体 UI 风格重建：12 路独立控制（闭合二次确认）、全控、广播、开入/版本回读。
"""
import queue

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel,
                             QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog
from instrument_hub.widgets import Card

from . import relay_hmi as core

RELAY_COUNT = core.RELAY_COUNT      # 12 路
INPUT_COUNT = core.INPUT_COUNT      # 16 路开入


class RelayPage(QWidget):
    """继电器板卡控制：连接 → 单路/全控（闭合二次确认）→ 开入与版本实时回读。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client: core.RelayClient = None
        self.worker = core.Worker()
        self.worker.start()
        self._q = queue.Queue()
        self._relay_widgets = []      # [(指示灯, 切换按钮, 通道格)]
        self._relay_on = [False] * RELAY_COUNT   # 各路当前闭合状态（回读同步）
        self._input_labels = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_conn_card())

        # 主区左右分栏（分割条可拖，位置随平台记忆）：左=继电器控制，右=状态回读
        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_relay_card())
        mid.addWidget(self._build_status_card())
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 0)
        mid.setSizes([980, 460])
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(mid)
        split.addWidget(self._build_log_card())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([560, 190])
        root.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    # ------------------------------------------------------------ 连接
    def _build_conn_card(self) -> Card:
        card = Card("通讯连接", "RS485 串口或网络（RTU over TCP）；从站地址由板卡在测控机箱内的位置决定")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(QLabel("链路"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["RS485 串口", "网络 (RTU over TCP)"])
        self.cmb_link.setFixedWidth(150)
        h.addWidget(self.cmb_link)

        self.lbl_port = QLabel("端口")
        h.addWidget(self.lbl_port)
        self.ed_port = QComboBox()
        # 串口模式只允许从扫描列表选（不接受任意文字）；网络模式可手输 IP:端口
        self.ed_port.setEditable(False)
        ports = [name for name, _desc in core.list_serial_ports()]
        self.ed_port.addItems(ports or ["COM3"])
        self.ed_port.setCurrentText(ports[0] if ports else "COM3")
        # 容下 255.255.255.255:65535 不截断；用控件级 QSS 定宽——
        # 框架全局 QSS（min-width:90px）在之后应用会覆盖 setMinimumWidth
        self.ed_port.setStyleSheet("QComboBox{min-width:210px;}")
        self.ed_port.setMinimumWidth(210)
        h.addWidget(self.ed_port)

        self.lbl_baud = QLabel("波特率")
        h.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.cmb_baud.setFixedWidth(86)
        h.addWidget(self.cmb_baud)
        self.cmb_link.currentIndexChanged.connect(self._on_link_changed)

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
        self.lbl_ver = QLabel("未连接")
        self.lbl_ver.setObjectName("Muted")
        h.addWidget(self.lbl_ver)
        card.body_lay.addLayout(h)
        self._on_link_changed(0)   # 初始按串口模式归一显示
        return card

    def _on_link_changed(self, idx: int) -> None:
        """链路切换联动：串口→COM 列表+波特率；网络→IP:端口 候选、隐藏波特率。

        下拉候选按模式重建（不残留另一模式的选项）；
        各模式最近使用的地址互相记忆，切回时恢复而不是被默认值覆盖。
        """
        if not hasattr(self, "_addr_mem"):
            self._addr_mem = {"serial": "", "tcp": ""}
        serial_mode = idx == 0
        cur = self.ed_port.currentText().strip()
        prev_key = "tcp" if serial_mode else "serial"
        # 离开当前模式前记住用户输入（仅符合该模式形态时）
        if cur and ((prev_key == "serial") == (":" not in cur and cur.upper().startswith("COM"))):
            self._addr_mem[prev_key] = cur

        if serial_mode:
            self.lbl_port.setText("串口")
            self.ed_port.setEditable(False)   # 串口只从列表选，禁止手输
            self.lbl_baud.setVisible(True)
            self.cmb_baud.setVisible(True)
            ports = [name for name, _desc in core.list_serial_ports()] or ["COM3"]
            self.ed_port.clear()
            self.ed_port.addItems(ports)
            coms = [p for p in ports if p.upper().startswith("COM")]
            mem = self._addr_mem["serial"]
            if mem and mem.upper().startswith("COM"):
                self.ed_port.setCurrentText(mem)
            elif ":" not in cur and cur.upper().startswith("COM"):
                self.ed_port.setCurrentText(cur)
            else:
                self.ed_port.setCurrentText(coms[0] if coms else "COM3")
        else:
            self.lbl_port.setText("IP:端口")
            self.ed_port.setEditable(True)    # 网络模式可手输任意 IP:端口
            self.lbl_baud.setVisible(False)
            self.cmb_baud.setVisible(False)
            self.ed_port.clear()
            self.ed_port.addItems(["127.0.0.1:10502", "192.168.1.100:10502"])
            mem = self._addr_mem["tcp"]
            if mem and ":" in mem:
                self.ed_port.setCurrentText(mem)
            elif ":" in cur:
                self.ed_port.setCurrentText(cur)
            else:
                self.ed_port.setCurrentText("127.0.0.1:10502")

    # ------------------------------------------------------------ 继电器
    def _build_relay_card(self) -> Card:
        card = Card("继电器控制（12 路）",
                    "单击切换：闭合（绿色，须二次确认）↔ 断开（淡蓝，默认）；断开动作免确认")
        self._relay_card = card

        # 通道数/广播/全控行放右上角（用户要求）
        bar = QHBoxLayout()
        bar.setSpacing(8)
        from PyQt5.QtWidgets import QCheckBox, QComboBox
        bar.addStretch(1)
        bar.addWidget(QLabel("通道数"))
        self.cmb_channels = QComboBox()
        self.cmb_channels.addItems(["8 路", "12 路"])
        self.cmb_channels.setCurrentIndex(1)
        self.cmb_channels.setFixedWidth(90)
        self.cmb_channels.setToolTip("按板卡规格切换显示/控制路数（8 路板只用前 8 路）")
        self.cmb_channels.currentIndexChanged.connect(self._on_channels_changed)
        bar.addWidget(self.cmb_channels)
        self.chk_broadcast = QCheckBox("广播（总线上所有模块）")
        bar.addWidget(self.chk_broadcast)

        def _bulk_btn(text: str, bg: str, fg: str, bd: str, pressed: str) -> QPushButton:
            b = QPushButton(text)
            b.setProperty("selfStyled", True)   # 自绘配色，防框架统一上色覆刷
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{bg}; color:{fg}; border:2px solid {bd};"
                f"border-radius:10px; font-weight:700; padding:5px 14px;}}"
                f"QPushButton:pressed{{background:{pressed};}}")
            return b

        b_all_on = _bulk_btn("全部闭合", "#10B981", "#FFFFFF", "#047857", "#047857")
        b_all_on.clicked.connect(lambda: self.set_all(True))
        bar.addWidget(b_all_on)
        b_all_off = _bulk_btn("全部断开", "#DCE8FF", "#2855A6", "#A9C2F0", "#A9C2F0")
        b_all_off.clicked.connect(lambda: self.set_all(False))
        bar.addWidget(b_all_off)
        b_inv = _bulk_btn("全部取反", "#E8890C", "#FFFFFF", "#B36B09", "#B36B09")
        b_inv.clicked.connect(self.invert_all)
        bar.addWidget(b_inv)
        card.body_lay.addLayout(bar)

        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        for i in range(RELAY_COUNT):
            r, c = divmod(i, 4)
            box = QVBoxLayout()
            box.setSpacing(4)
            box.setAlignment(Qt.AlignHCenter)
            top = QHBoxLayout()
            top.setSpacing(6)
            lamp = QLabel("●")
            lamp.setStyleSheet("color:#D6D3EE; font-size:16px;")
            top.addWidget(lamp)
            lab = QLabel(f"{i + 1}#")
            lab.setStyleSheet("font-weight:700;")
            top.addWidget(lab)
            top.addStretch(1)
            box.addLayout(top)
            b = QPushButton("断开")
            b.setProperty("selfStyled", True)   # 自带两态配色，不参与框架统一上色
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(76, 76)              # 圆形按钮（正方形+半径=正圆）
            b.clicked.connect(lambda _=False, n=i: self.toggle_relay(n))
            self._style_relay_btn(b, False)
            box.addWidget(b, 0, Qt.AlignHCenter)
            cell = QWidget()
            cell.setLayout(box)
            g.addWidget(cell, r, c)
            self._relay_widgets.append((lamp, b, cell))
        card.body_lay.addLayout(g)
        return card

    # ------------------------------------------------------------ 回读
    def _build_status_card(self) -> Card:
        card = Card("状态回读", "输出状态 / 16 路开入 / 软硬件版本（每秒刷新）")
        h = QVBoxLayout()
        h.setSpacing(6)
        self.lbl_out = QLabel("输出：-")
        self.lbl_out.setObjectName("Muted")
        h.addWidget(self.lbl_out)
        self.lbl_hw = QLabel("硬件版本：-\n软件版本：-")
        self.lbl_hw.setObjectName("Muted")
        h.addWidget(self.lbl_hw)
        card.body_lay.addLayout(h)
        # 右侧窄栏：开入 4×4 排布（原 8×2 为通栏宽板）
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        for i in range(INPUT_COUNT):
            lab = QLabel(f"IN{i + 1} ●")
            lab.setStyleSheet("color:#C9C6E4; font-family:Consolas;")
            g.addWidget(lab, i // 4, i % 4)
            self._input_labels.append(lab)
        card.body_lay.addLayout(g)
        card.body_lay.addStretch(1)
        return card

    def _build_log_card(self) -> Card:
        card = Card("通讯日志", "TX/RX 帧记录，便于定位通讯问题")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(110)
        card.body_lay.addWidget(self.log)
        return card

    # ------------------------------------------------------------ 动作
    def toggle_conn(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
            self.btn_connect.setText("连接")
            self.btn_connect.setObjectName("btnConnect")
            self.lbl_ver.setText("未连接")
            self._append("已断开连接")
            return
        try:
            text = self.ed_port.currentText().strip()
            if self.cmb_link.currentIndex() == 0:
                tr = core.SerialTransport(text, baudrate=int(self.cmb_baud.currentText()))
            else:
                host, _, port = text.partition(":")
                tr = core.TcpTransport(host or "127.0.0.1", int(port or 10502))
            self.client = core.RelayClient(tr, slave_id=self.sp_slave.value(),
                                           trace=self._on_trace)
            self.client.connect()
            self.btn_connect.setText("已连接")
            self.btn_connect.setObjectName("btnConnected")
            self._append(f"连接成功：{text} @ 从站 {self.sp_slave.value()}")
            self.refresh_status()
        except Exception as e:
            self.client = None
            self._append(f"连接失败：{e}")

    @staticmethod
    def _style_relay_btn(btn: QPushButton, on: bool) -> None:
        """圆形单键两态：闭合=绿底白字，断开（默认）=淡蓝底。单击即换色换字。"""
        if on:
            btn.setText("闭合")
            btn.setStyleSheet(
                "QPushButton{background:#10B981; color:#FFFFFF; border:2px solid #047857;"
                "border-radius:38px; font-weight:700; font-size:12px;}"
                "QPushButton:pressed{background:#047857;}")
            btn.setToolTip("当前闭合 · 单击断开")
        else:
            btn.setText("断开")
            btn.setStyleSheet(
                "QPushButton{background:#DCE8FF; color:#2855A6; border:2px solid #A9C2F0;"
                "border-radius:38px; font-weight:700; font-size:12px;}"
                "QPushButton:pressed{background:#A9C2F0;}")
            btn.setToolTip("当前断开 · 单击闭合（须二次确认）")

    def _on_channels_changed(self, idx: int) -> None:
        """8 路 / 12 路切换：隐藏多出路格，标题同步；8 路板只显示/控制前 8 路。"""
        n = 8 if idx == 0 else 12
        for i, (_lamp, _btn, cell) in enumerate(self._relay_widgets):
            cell.setVisible(i < n)
        if self._relay_card.title_label is not None:
            self._relay_card.title_label.setText(f"继电器控制（{n} 路）")
        self._append(f"通道数切换为 {n} 路")

    def _active_count(self) -> int:
        return 8 if self.cmb_channels.currentIndex() == 0 else 12

    def toggle_relay(self, index: int) -> None:
        """单键切换：单击闭合（输出动作，须二次确认）；已闭合时单击断开（免确认）。"""
        if not self._ensure():
            return
        on = not self._relay_on[index]
        if on:
            dlg = ConfirmOutputDialog("继电器板卡(12CH)",
                                      f"闭合 {index + 1}# 继电器",
                                      "闭合将接通该路外部回路，确认接线与被测体状态无误后再闭合。",
                                      f"路号 {index + 1}#　从站 {self.sp_slave.value()}", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        self._submit(lambda: self.client.write_single_coil(index, on),
                     f"{index + 1}# {'闭合' if on else '断开'}")

    def set_all(self, on: bool) -> None:
        if not self._ensure():
            return
        n = self._active_count()
        if on:
            dlg = ConfirmOutputDialog("继电器板卡(12CH)", f"全部闭合（{n} 路）",
                                      "将接通全部继电器回路！确认接线与安全无误后再执行。",
                                      f"{n} 路全闭合", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        self._submit(lambda: self.client.write_coils(0, [on] * n),
                     f"全部{'闭合' if on else '断开'}")

    def invert_all(self) -> None:
        if not self._ensure():
            return
        n = self._active_count()
        dlg = ConfirmOutputDialog("继电器板卡(12CH)", "全部取反",
                                  "取反包含闭合动作，将翻转当前全部路状态，请确认安全。",
                                  f"{n} 路取反", self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return

        def _do():
            sr = self.client.read_status()
            cur = _to_flags(sr.outputs, RELAY_COUNT)[:n]
            self.client.write_coils(0, [not x for x in cur])
        self._submit(_do, "全部取反")

    def refresh_status(self) -> None:
        if self.client is None:
            return

        def _do():
            try:
                sr = self.client.read_status()
                self._q.put(("status", sr))
            except Exception as e:
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)   # 回读失败 = 通讯中断
                self._q.put(("err", f"回读失败：{e}"))
        self.worker.submit(_do)

    # ------------------------------------------------------------ 工具
    def _ensure(self) -> bool:
        if self.client is None:
            self._append("请先连接板卡")
            return False
        return True

    def _submit(self, fn, label: str) -> None:
        def _do():
            try:
                fn()
                self._q.put(("log", f"{label} ✓"))
                self._q.put(("refresh",))
            except Exception as e:
                self._q.put(("err", f"{label} 失败：{e}"))
        self.worker.submit(_do)

    def _on_trace(self, *args) -> None:
        self._q.put(("log", " ".join(str(a) for a in args if a)))

    def _append(self, text: str) -> None:
        self.log.appendPlainText(str(text))

    def _drain(self) -> None:
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "log":
                self._append(item[1])
            elif kind == "err":
                self._append(item[1])
            elif kind == "refresh":
                self.refresh_status()
            elif kind == "status":
                from instrument_hub.comm_state import mark_ok
                mark_ok(self)   # 状态回读成功 = 通讯真正建立
                sr = item[1]
                outs = _to_flags(sr.outputs, RELAY_COUNT)
                ins = _to_flags(sr.inputs, INPUT_COUNT)
                for i, (lamp, btn, _cell) in enumerate(self._relay_widgets):
                    on = i < len(outs) and outs[i]
                    self._relay_on[i] = on
                    lamp.setStyleSheet(
                        f"color:{'#10B981' if on else '#D6D3EE'}; font-size:16px;")
                    self._style_relay_btn(btn, on)
                self.lbl_out.setText("输出：" + "".join("1" if x else "0" for x in outs))
                self.lbl_hw.setText(f"硬件版本：{sr.hw_version}\n软件版本：{sr.sw_version}")
                for i, lab in enumerate(self._input_labels):
                    on = i < len(ins) and ins[i]
                    lab.setStyleSheet(
                        f"color:{'#4F46E5' if on else '#C9C6E4'}; font-family:Consolas;")
        if self.client is not None and self._q.empty():
            self.refresh_status()

    def shutdown(self) -> None:
        self._timer.stop()
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        self.worker.stop()


def _to_flags(value, count: int):
    """StatusResult 的 outputs/inputs 统一转 bool 列表（list[bool] 或位图整数）。"""
    if isinstance(value, int):
        return [bool(value >> i & 1) for i in range(count)]
    seq = [bool(x) for x in (value or [])]
    return (seq + [False] * count)[:count]
