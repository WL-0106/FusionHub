# -*- coding: utf-8 -*-
"""单台仪器面板：操作面板（连接/设定/输出/读数/波形） + 协议速查（粗细结合 + 搜索）。

界面只消费 SimSession 的语义化接口（connect/set_param/toggle_output/read_value），
不直接接触帧字节 —— 界面与协议解耦，后续换真实协议栈不影响界面。
"""
import datetime
from typing import Dict, List

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (QAction, QApplication, QComboBox, QDoubleSpinBox, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                             QShortcut, QSplitter, QStackedWidget, QTabWidget, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from .dialogs import ConfirmOutputDialog, FaultRecordDialog
from .log_panel import CommLogPanel
from .sim import LOG_SYS, SimSession
from .spec import Caution, InstrumentSpec
from .theme import COLORS
from .widgets import (Card, Chip, ConnectButton, OutputButton, WaveformWidget,
                      level_chip)


class InstrumentPanel(QWidget):
    def __init__(self, spec: InstrumentSpec, log_panel=None, recorder=None, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.log_panel = log_panel or CommLogPanel()   # 每台仪器一份通讯日志（在本界面下方）
        self.recorder = recorder          # 调试记录器（可选）：设定/输出/连接事件留痕
        self.session = SimSession(spec, self._log)

        self._readout_labels: Dict[str, QLabel] = {}
        self._param_spins: Dict[str, QDoubleSpinBox] = {}
        self._output_btns: Dict[str, OutputButton] = {}
        self._card_buttons: List[QPushButton] = []
        self._tables: List[QTableWidget] = []
        self._fault_log: List[List[str]] = []   # 调试故障记录：[时间, 现象, 关联操作, 处理]

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        # 页内常用快捷键：Ctrl+1/2 切选项卡，Ctrl+C 复制表格选中
        for key, slot in (("Ctrl+1", lambda: self.tabs.setCurrentIndex(0)),
                          ("Ctrl+2", lambda: self.tabs.setCurrentIndex(1)),
                          (QKeySequence.Copy, self._copy_table_selection)):
            s = QShortcut(QKeySequence(key) if not isinstance(key, QKeySequence) else key, self)
            s.setContext(Qt.WidgetWithChildrenShortcut)
            s.activated.connect(slot)

    # ================================================================ 日志
    def _log(self, direction: str, content: str, note: str = "") -> None:
        prefix = f"[{self.spec.model}]"
        self.log_panel.append(direction, content, f"{prefix} {note}".strip())

    # ================================================================ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ---------------- 头部信息条 ----------------
        head = Card()
        h = QHBoxLayout()
        h.setSpacing(10)
        head.body_lay.addLayout(h)
        title = QLabel(self.spec.name)
        title.setObjectName("H1")
        h.addWidget(title)
        h.addWidget(Chip(self.spec.model, "#4F46E5", "#EEF0FF"))
        h.addWidget(Chip(self.spec.category, "#7C3AED", "#F3E8FF"))
        for k, v in self.spec.versions.items():
            if k in ("协议", "寄存器表"):
                h.addWidget(Chip(f"{k} {v}", "#0E7490", "#CFFAFE"))
        summary = QLabel(self.spec.summary)
        summary.setObjectName("Muted")
        summary.setWordWrap(True)
        h.addWidget(summary, 1)

        port = QComboBox()
        port.addItems(["COM3", "COM4", "COM5", "COM6", "USB-TMC"])
        port.setFixedWidth(104)
        baud = QComboBox()
        baud.addItems(["9600", "19200", "115200"])
        baud.setFixedWidth(90)
        self._port, self._baud = port, baud
        h.addWidget(QLabel("端口"))
        h.addWidget(port)
        h.addWidget(QLabel("波特率"))
        h.addWidget(baud)

        self.connect_btn = ConnectButton()
        self.connect_btn.clicked.connect(self._on_connect)
        h.addWidget(self.connect_btn)
        root.addWidget(head)

        # ---------------- 主体：选项卡 | 通讯日志 ----------------
        # 通讯日志在本仪器界面下方（每台仪器独立一份），中间手柄可拖动随时缩放
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_control_page(), "  操作面板  ")
        self.tabs.addTab(self._build_protocol_page(), "  协议速查  ")
        self.tabs.addTab(self._build_help_page(), "  帮助  ")
        self.tabs.addTab(self._build_fault_page(), "  故障代码查询  ")
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setHandleWidth(14)
        self.splitter.setChildrenCollapsible(False)
        # 上方内容包滚动区：日志放大时内容区上下滚动，不再压扁控件/文字（保留原形态）
        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QScrollArea.NoFrame)
        content_scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        content_scroll.setWidget(self.tabs)
        content_scroll.setMinimumHeight(120)   # 只约束滚动区：手柄始终拖得动，内容不足时内部滚动
        self.splitter.addWidget(content_scroll)
        self.splitter.addWidget(self.log_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([560, 210])
        self.log_panel.setMinimumHeight(110)
        root.addWidget(self.splitter, 1)
        # 分割条拖动记忆（内容|日志 与 协议速查 导航|详情 两条，关平台重开恢复）
        from .layout_mem import bind_splitters
        bind_splitters(self, "panel:" + str(getattr(self.spec, "model", "generic")))

    # ---------------- 帮助页：通讯协议 + 基础参数，快速了解模块和上位机 ----------------
    def _build_help_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        lay.addWidget(self._kv_card("模块基础参数", "量程 / 精度 / 供电等，接线与选型前先看这里",
                                    self.spec.basics))
        lay.addWidget(self._kv_card("通信接口要点", "接口、波特率、超时；命令明细见「协议速查」",
                                    self.spec.comm_info))
        lay.addWidget(self._kv_card("帧结构与时序要点", "帧格式、校验与响应时序约束",
                                    self.spec.frame_info))
        lay.addWidget(self._kv_card("版本对应关系", "现场问题追溯（上位机 ↔ 协议 ↔ 寄存器表）",
                                    list(self.spec.versions.items())))

        quick = Card("快速上手", "本上位机的标准操作路径")
        tip = QLabel(
            "① 头部选择端口/波特率 → 连接仪器；"
            "② 「操作面板」下发设定值；"
            "③ 开启输出需二次确认，关闭上位机自动停止全部输出；"
            "④ 通讯日志在本页下方，拖动中间分割条可随时缩放；"
            "⑤ 遇到异常切到「故障代码查询」：可查故障码，并把调试中遇到的故障记录下来。")
        tip.setWordWrap(True)
        quick.body_lay.addWidget(tip)
        lay.addWidget(quick)

        dangers = [c for c in self.spec.cautions if c.level == "danger"]
        if dangers:
            warn = QLabel("⚠ " + "　".join(c.text for c in dangers[:2]))
            warn.setObjectName("Banner")
            warn.setWordWrap(True)
            lay.addWidget(warn)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        return page

    def _kv_card(self, title: str, sub: str, rows) -> Card:
        card = Card(title, sub)
        tbl = QTableWidget(0, 2)
        tbl.setHorizontalHeaderLabels(["项目", "内容"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        tbl.setAlternatingRowColors(True)
        for k, v in (rows or []):
            i = tbl.rowCount()
            tbl.insertRow(i)
            tbl.setItem(i, 0, QTableWidgetItem(str(k)))
            tbl.setItem(i, 1, QTableWidgetItem(str(v)))
        tbl.setColumnWidth(0, 180)
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.setFixedHeight(min(64 + 34 * max(1, tbl.rowCount()), 300))
        card.body_lay.addWidget(tbl)
        self._tables.append(tbl)
        return card

    # ---------------- 故障代码查询：故障码表 + 调试故障记录 ----------------
    def _build_fault_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.fault_search = QLineEdit()
        self.fault_search.setPlaceholderText("搜索故障码 / 含义 / 处理建议 / 调试记录…")
        self.fault_search.setClearButtonEnabled(True)
        self.fault_search.textChanged.connect(self._filter_faults)
        bar.addWidget(self.fault_search, 1)
        btn_add = QPushButton("记录调试故障")
        btn_add.setObjectName("Primary")
        btn_add.setToolTip("把调试过程中遇到的故障记入下方记录表（随调试记录归档）")
        btn_add.clicked.connect(self._add_fault_record)
        bar.addWidget(btn_add)
        lay.addLayout(bar)

        card1 = Card("故障代码表",
                     f"共 {len(self.spec.error_codes)} 条 · 来源：厂家故障代码 / 协议异常码，与手册逐条比对")
        self.fault_table = QTableWidget(0, 3)
        self.fault_table.setHorizontalHeaderLabels(["故障码", "含义", "建议处理"])
        self.fault_table.verticalHeader().setVisible(False)
        self.fault_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fault_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.fault_table.setAlternatingRowColors(True)
        for row in self.spec.error_codes:
            i = self.fault_table.rowCount()
            self.fault_table.insertRow(i)
            for c, val in enumerate(row[:3]):
                self.fault_table.setItem(i, c, QTableWidgetItem(str(val)))
        self.fault_table.setColumnWidth(0, 120)
        self.fault_table.setColumnWidth(1, 190)
        self.fault_table.horizontalHeader().setStretchLastSection(True)
        self.fault_table.setFixedHeight(min(64 + 34 * max(1, self.fault_table.rowCount()), 300))
        card1.body_lay.addWidget(self.fault_table)
        self._tables.append(self.fault_table)
        lay.addWidget(card1)

        card2 = Card("调试故障记录", "调试过程中遇到的现象与处理结论，可搜索、随调试记录归档")
        self.fault_log_table = QTableWidget(0, 4)
        self.fault_log_table.setHorizontalHeaderLabels(["时间", "故障现象", "关联操作", "处理 / 结论"])
        self.fault_log_table.verticalHeader().setVisible(False)
        self.fault_log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.fault_log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.fault_log_table.setAlternatingRowColors(True)
        self.fault_log_table.setColumnWidth(0, 152)
        self.fault_log_table.setColumnWidth(1, 220)
        self.fault_log_table.setColumnWidth(2, 220)
        self.fault_log_table.horizontalHeader().setStretchLastSection(True)
        card2.body_lay.addWidget(self.fault_log_table)
        self._tables.append(self.fault_log_table)
        lay.addWidget(card2, 1)
        self._refresh_fault_log()
        return page

    def _filter_faults(self, text: str) -> None:
        key = text.strip().lower()
        for tbl in (self.fault_table, self.fault_log_table):
            for r in range(tbl.rowCount()):
                hay = " ".join(tbl.item(r, c).text() for c in range(tbl.columnCount())
                               if tbl.item(r, c)).lower()
                tbl.setRowHidden(r, bool(key) and key not in hay)

    def _add_fault_record(self) -> None:
        dlg = FaultRecordDialog(f"{self.spec.name}（{self.spec.model}）", self)
        if dlg.exec_() != FaultRecordDialog.Accepted:
            return
        scene, op, fix = dlg.values()
        self._log_fault(scene, op, fix)

    def _log_fault(self, scene: str, op: str, fix: str) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._fault_log.append([ts, scene, op, fix])
        self._refresh_fault_log()
        self._record("调试故障", "故障", scene, "-", f"{op} → {fix}")
        self._log(LOG_SYS, "", f"[故障记录] {scene}")

    def _refresh_fault_log(self) -> None:
        if not hasattr(self, "fault_log_table"):
            return
        self.fault_log_table.setRowCount(0)
        for row in self._fault_log:
            i = self.fault_log_table.rowCount()
            self.fault_log_table.insertRow(i)
            for c, val in enumerate(row):
                self.fault_log_table.setItem(i, c, QTableWidgetItem(str(val)))

    # ---------------- 操作面板页 ----------------
    def _build_control_page(self) -> QWidget:
        page = QWidget()
        lay = QGridLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)
        lay.setColumnStretch(0, 3)
        lay.setColumnStretch(1, 4)

        # 左列：参数设定 + 输出控制
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)

        pcard = Card("参数设定", "设定值通过语义化接口下发，帧封装在协议层完成")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        for i, p in enumerate(self.spec.params):
            grid.addWidget(self._param_label(p.label, p.unit), i, 0)
            spin = QDoubleSpinBox()
            spin.setRange(p.min, p.max)
            spin.setSingleStep(p.step)
            spin.setDecimals(p.decimals)
            spin.setValue(p.value)
            spin.setSuffix(" " + p.unit)
            self._param_spins[p.key] = spin
            grid.addWidget(spin, i, 1)
        if not self.spec.params:
            grid.addWidget(QLabel("该仪器无设定参数", ), 0, 0)
        pcard.body_lay.addLayout(grid)
        apply_btn = QPushButton("下发设定")
        apply_btn.setObjectName("Primary")
        apply_btn.clicked.connect(self._on_apply_params)
        pcard.body_lay.addWidget(apply_btn, 0, Qt.AlignRight)
        ll.addWidget(pcard)

        ocard = Card("输出控制", "所有输出开启均需二次确认弹窗；退出软件时自动停止全部输出")
        for o in self.spec.outputs:
            row = QHBoxLayout()
            btn = OutputButton(o.label)
            btn.clicked.connect(lambda _=False, k=o.key: self._on_output_clicked(k))
            self._output_btns[o.key] = btn
            row.addWidget(btn)
            risk = QLabel("⚠ " + o.risk)
            risk.setWordWrap(True)
            risk.setStyleSheet("color:#B01030; font-size:11px;")
            row.addWidget(risk, 1)
            ocard.body_lay.addLayout(row)
        if not self.spec.outputs:
            note = QLabel("该仪器无输出控制项（测量类设备）")
            note.setObjectName("Muted")
            ocard.body_lay.addWidget(note)
        stop_all = QPushButton("一键关闭全部输出")
        stop_all.setObjectName("Danger")
        stop_all.setToolTip("立即停止本机全部输出，无需二次确认（安全动作）")
        stop_all.clicked.connect(lambda: self.stop_all_outputs(from_button=True))
        ocard.body_lay.addWidget(stop_all, 0, Qt.AlignRight)
        ll.addWidget(ocard)
        ll.addStretch(1)
        lay.addWidget(left, 0, 0)

        # 右列：读数 + 波形
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)

        rcard = Card("实时读数", "模拟从站数据源 · 10 Hz 刷新（低于串口吞吐，防止队列堆积）")
        rgrid = QGridLayout()
        rgrid.setSpacing(10)
        for i, r in enumerate(self.spec.readouts):
            box = QWidget()
            box.setStyleSheet(f"background:#FBFBFE; border:1px solid {COLORS['card_border']};"
                              "border-radius:12px;")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(14, 10, 14, 10)
            lb = QLabel(r.label)
            lb.setStyleSheet(f"color:{COLORS['text_sub']}; font-size:12px;")
            bl.addWidget(lb)
            val = QLabel("--")
            val.setObjectName("BigValue")
            val.setStyleSheet(f"color:{r.color};")
            bl.addWidget(val)
            unit = QLabel(r.unit)
            unit.setObjectName("Muted")
            bl.addWidget(unit)
            self._readout_labels[r.key] = val
            rgrid.addWidget(box, i // 3, i % 3)
        rcard.body_lay.addLayout(rgrid)
        rl.addWidget(rcard)

        wcard = Card("波形预览", "示波屏风格 · 按当前设定实时绘制")
        self.wave = WaveformWidget(self.spec.wave_ylim)
        for key in self.spec.wave_channels:
            r = next((x for x in self.spec.readouts if x.key == key), None)
            if r:
                # 电压通道按整机量程，其余通道按自身基准放大，避免曲线贴底
                vrange = self.spec.wave_ylim if r.unit == "V" else (0.0, max(1.0, r.base * 2.2))
                self.wave.add_channel(r.key, r.label, r.unit, r.color, vrange)
        wcard.body_lay.addWidget(self.wave)
        rl.addWidget(wcard, 1)
        lay.addWidget(right, 0, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(page)
        scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        return scroll

    @staticmethod
    def _param_label(text: str, unit: str) -> QLabel:
        lb = QLabel(f"{text}（{unit}）")
        lb.setStyleSheet("font-weight:600;")
        return lb

    # ---------------- 协议速查页（粗细结合） ----------------
    def _build_protocol_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        # 版本 + 搜索条
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(Chip(f"上位机UI {self.spec.versions.get('上位机UI', '-')}", "#4F46E5", "#EEF0FF"))
        bar.addWidget(Chip(f"协议 {self.spec.versions.get('协议', '-')}", "#0E7490", "#CFFAFE"))
        bar.addWidget(Chip(f"寄存器表 {self.spec.versions.get('寄存器表', '-')}", "#7C3AED", "#F3E8FF"))
        bar.addStretch(1)
        self.proto_search = QLineEdit()
        self.proto_search.setPlaceholderText("搜索命令 / 寄存器 / 异常码 / 注意事项…（Esc 清空）")
        self.proto_search.setFixedWidth(300)
        self.proto_search.setObjectName("SearchBox")
        self.proto_search.setClearButtonEnabled(True)
        self.proto_search.textChanged.connect(self._on_proto_search)
        self.proto_search.returnPressed.connect(self._goto_first_proto_hit)
        bar.addWidget(self.proto_search)
        lay.addLayout(bar)

        # 重点提醒（粗）
        dangers = [c for c in self.spec.cautions if c.level == "danger"]
        if dangers:
            banner = QLabel("重点提醒（危险级）：" + "　◆　".join(c.text for c in dangers[:2])
                            + (f"　…共 {len(dangers)} 条危险项" if len(dangers) > 2 else ""))
            banner.setObjectName("Banner")
            banner.setWordWrap(True)
            lay.addWidget(banner)

        # 粗：卡片导航 | 细：详情
        split = QSplitter(Qt.Horizontal)
        nav_card = Card("速查目录（粗览）", "点选右侧展开明细")
        nav_lay = QVBoxLayout()
        nav_lay.setSpacing(6)
        cards = [
            ("comm", "通信接口", self._brief(self.spec.comm_info)),
            ("frame", "帧结构与时序", self._brief(self.spec.frame_info)),
            ("commands", "命令集", f"{len(self.spec.commands)} 条核心命令 · "
                                  f"已验证 {sum(1 for c in self.spec.commands if c.verified)} 条"),
            ("registers", "寄存器 / 量程", f"{len(self.spec.registers)} 个寄存器 · "
                                          f"读写属性与量程见明细"),
            ("errors", "异常码", f"{len(self.spec.error_codes)} 条异常响应及处理建议"),
            ("cautions", "调试注意（坑位）", f"{len(self.spec.cautions)} 条 · "
                                            f"危险 {sum(1 for c in self.spec.cautions if c.level == 'danger')} 条"),
        ]
        self._card_meta = cards
        for key, title, brief in cards:
            btn = QPushButton(f"{title}\n{brief}")
            btn.setCheckable(True)
            btn.setMinimumHeight(64)
            btn.setStyleSheet(
                "QPushButton{text-align:left; padding:10px 12px; border-radius:12px;"
                "border:2px solid #E4E2F3; background:#FBFBFE; color:#23263A; font-weight:600;}"
                "QPushButton:hover{background:#EEF0FF; border-color:#4F46E5;}"
                "QPushButton:checked{background:#4F46E5; border-color:#3B34C4; color:#FFFFFF;}"
                "QPushButton:checked:pressed{background:#2A249E;}")
            btn.clicked.connect(lambda _=False, k=key: self._show_proto(k))
            self._card_buttons.append(btn)
            nav_lay.addWidget(btn)
        nav_lay.addStretch(1)
        nav_list = QWidget()
        nav_list.setLayout(nav_lay)
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QScrollArea.NoFrame)
        nav_scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        nav_scroll.setWidget(nav_list)
        nav_card.body_lay.addWidget(nav_scroll)
        split.addWidget(nav_card)

        self.detail_stack = QStackedWidget()
        self.detail_pages: Dict[str, QWidget] = {
            "comm": self._table_page("通信接口明细", ["项目", "内容"], self.spec.comm_info),
            "frame": self._table_page("帧结构与时序明细", ["项目", "内容"], self.spec.frame_info),
            "commands": self._table_page("命令表（单一事实源派生）",
                                         ["命令", "功能", "参数", "返回", "验证状态"],
                                         [(c.cmd, c.desc, c.params, c.resp,
                                           "已验证" if c.verified else "待真机确认") for c in self.spec.commands]),
            "registers": self._table_page("寄存器表（抽表产物）",
                                          ["地址", "名称", "类型", "单位", "量程", "读写", "验证状态"],
                                          [(r.addr, r.name, r.dtype, r.unit, r.span, r.rw,
                                            "已验证" if r.verified else "待真机确认") for r in self.spec.registers],
                                          warn="未标注\"已验证\"的地址/量程为占位内容，须以厂家手册与真机核对后再使用，禁止按猜测值下发。"),
            "errors": self._table_page("异常码 / 错误响应", ["代码", "含义", "建议处理"],
                                       [tuple(e) for e in self.spec.error_codes]),
            "cautions": self._caution_page(),
        }
        for key in ("comm", "frame", "commands", "registers", "errors", "cautions"):
            self.detail_stack.addWidget(self.detail_pages[key])
        split.addWidget(self.detail_stack)
        split.setSizes([300, 760])
        lay.addWidget(split, 1)

        self._show_proto("comm")
        return page

    def _brief(self, kv) -> str:
        return " · ".join(f"{k} {v}" for k, v in kv[:2]) if kv else "-"

    def _table_page(self, title: str, headers: List[str], rows, warn: str = "") -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("H2")
        lay.addWidget(t)
        if warn:
            banner = QLabel("⚠ " + warn)
            banner.setObjectName("Banner")
            banner.setWordWrap(True)
            lay.addWidget(banner)
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setFont(QFont("Microsoft YaHei UI", 10))
        self._tables.append(table)
        table._src_rows = [tuple(r) for r in rows]   # 供搜索过滤
        self._fill_table(table, "")
        lay.addWidget(table, 1)
        return w

    @staticmethod
    def _fill_table(table: QTableWidget, key: str) -> None:
        rows = getattr(table, "_src_rows", [])
        key = key.strip().lower()
        shown = [r for r in rows if not key or key in " ".join(str(x) for x in r).lower()]
        table.setRowCount(0)
        for r in rows:
            if r not in shown:
                continue
            i = table.rowCount()
            table.insertRow(i)
            for c, val in enumerate(r):
                it = QTableWidgetItem(str(val))
                if str(val) == "待真机确认":
                    it.setForeground(QColor("#B45309"))
                elif str(val) == "已验证":
                    it.setForeground(QColor("#047857"))
                table.setItem(i, c, it)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    def _caution_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        t = QLabel("调试注意 / 坑位清单（逐条自查）")
        t.setObjectName("H2")
        lay.addWidget(t)
        self._caution_box = QWidget()
        self._caution_lay = QVBoxLayout(self._caution_box)
        self._caution_lay.setContentsMargins(0, 0, 0, 0)
        self._caution_lay.setSpacing(8)
        self._caution_items: List[tuple] = []
        for c in self.spec.cautions:
            self._caution_items.append(self._make_caution_row(c))
            self._caution_lay.addWidget(self._caution_items[-1][0])
        self._caution_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        scroll.setWidget(self._caution_box)
        lay.addWidget(scroll, 1)
        return w

    def _make_caution_row(self, c: Caution):
        text, fg, bg = level_chip(c.level)
        row = QWidget()
        row.setStyleSheet(f"background:{bg}; border-radius:10px;")
        hl = QHBoxLayout(row)
        hl.setContentsMargins(12, 8, 12, 8)
        hl.setSpacing(10)
        chip = QLabel(text)
        chip.setStyleSheet(f"color:{fg}; font-weight:800; font-size:11px;")
        chip.setFixedWidth(40)
        chip.setAlignment(Qt.AlignCenter)
        hl.addWidget(chip)
        lab = QLabel(c.text)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{fg};")
        hl.addWidget(lab, 1)
        return row, lab

    # ================================================================ 交互
    def _show_proto(self, key: str) -> None:
        for b, (k, _t, _b) in zip(self._card_buttons, self._card_meta):
            b.setChecked(k == key)
        self.detail_stack.setCurrentWidget(self.detail_pages[key])
        self._on_proto_search(self.proto_search.text())

    def _goto_first_proto_hit(self) -> None:
        """搜索回车：跳到第一个仍可见的速查目录卡片。"""
        for btn in self._card_buttons:
            if btn.isVisible():
                btn.click()
                return

    def _copy_table_selection(self) -> None:
        """Ctrl+C：复制当前表格选中单元格（TSV，可直接贴进 Excel）。"""
        table = self.focusWidget()
        if not isinstance(table, QTableWidget):
            for t in self._tables:
                if t.hasFocus() or t.selectionModel().hasSelection():
                    table = t
                    break
        if not isinstance(table, QTableWidget):
            return
        items = table.selectedItems()
        if not items:
            return
        rows: Dict[int, Dict[int, str]] = {}
        for it in items:
            rows.setdefault(it.row(), {})[it.column()] = it.text()
        lines = []
        for r in sorted(rows):
            cols = rows[r]
            lines.append("\t".join(cols.get(c, "") for c in sorted(cols)))
        QApplication.clipboard().setText("\n".join(lines))

    def _on_proto_search(self, text: str) -> None:
        """搜索：过滤当前明细表行 + 隐藏无匹配的速查目录卡片。"""
        for table in self._tables:
            self._fill_table(table, text)
        key = text.strip().lower()
        for btn, (k, title, brief) in zip(self._card_buttons, self._card_meta):
            page = self.detail_pages[k]
            has = True
            if key:
                rows_text = " ".join(" ".join(map(str, r)) for r in getattr(
                    page.findChild(QTableWidget), "_src_rows", [])) if page.findChild(QTableWidget) else ""
                if k == "cautions":
                    rows_text = " ".join(c.text for c in self.spec.cautions)
                has = key in (title + brief + rows_text).lower()
            btn.setVisible(has)

    def _on_connect(self) -> None:
        if self.session.connected:
            self.session.disconnect()
            self.connect_btn.set_connected(False)
            self._record("通讯连接", "连接", "断开")
        else:
            try:
                self.session.connect(self._port.currentText(), int(self._baud.currentText()))
            except Exception as e:      # 连接异常自动入调试故障记录，便于事后查询定位
                self._log_fault(f"连接失败：{e}", f"{self._port.currentText()} @ {self._baud.currentText()}",
                                "待处理")
                return
            self.connect_btn.set_connected(True)
            self._record("通讯连接", "连接", f"{self._port.currentText()} @ {self._baud.currentText()}")

    def _record(self, item: str, kind: str, value, unit: str = "", note: str = "") -> None:
        if self.recorder is not None:
            self.recorder.record_event(self.spec, self.session, item, kind, value, unit, note)

    def _on_apply_params(self) -> None:
        for key, spin in self._param_spins.items():
            self.session.set_param(key, spin.value())
            p = next(p for p in self.spec.params if p.key == key)
            self._record(p.label, "设定值", f"{spin.value():.{p.decimals}f}", p.unit, "下发设定")
        self._log(LOG_SYS, "", "参数设定已下发")

    def _on_output_clicked(self, key: str) -> None:
        btn = self._output_btns[key]
        out = next(o for o in self.spec.outputs if o.key == key)
        if btn.is_on():
            self.session.toggle_output(key, False)
            btn.set_on(False)
            self._record(out.label, "输出值", "关", "-", "手动关闭")
            self._log(LOG_SYS, "", f"{out.label} 已关闭")
            return
        # 开启输出：必须二次确认
        summary = "　".join(f"{p.label} {self._param_spins[p.key].value():.{p.decimals}f}{p.unit}"
                            for p in self.spec.params if p.key in self._param_spins)
        dlg = ConfirmOutputDialog(f"{self.spec.name}（{self.spec.model}）",
                                  out.label, out.risk, summary, self)
        if dlg.exec_() == ConfirmOutputDialog.Accepted:
            self.session.toggle_output(key, True)
            btn.set_on(True)
            self._record(out.label, "输出值", "开", "-", f"二次确认开启 · {summary}")
            self._log(LOG_SYS, "", f"{out.label} 已开启（用户二次确认）")

    def stop_all_outputs(self, from_button: bool = False) -> None:
        stopped = [k for k, b in self._output_btns.items() if b.is_on()]
        for k in stopped:
            self.session.toggle_output(k, False)
            self._output_btns[k].set_on(False)
        if stopped:
            self._log(LOG_SYS, "", f"已关闭全部输出：{len(stopped)} 路"
                      + ("（一键关闭）" if from_button else "（退出保护）"))

    # ================================================================ 安全关闭
    def is_connected(self) -> bool:
        """当前仪器是否已连接（供目录指示灯/切换弹窗判定）。"""
        return bool(getattr(self.session, "connected", False))

    def safe_shutdown(self) -> None:
        """关闭上位机前调用：停止所有输出 + 断开连接。"""
        self.stop_all_outputs()
        self.session.disconnect()

    # ================================================================ 刷新
    def _on_tick(self) -> None:
        self.session.tick(0.2)
        connected = self.session.connected
        for r in self.spec.readouts:
            v = self.session.read_value(r.key)
            if r.key in self._readout_labels:
                self._readout_labels[r.key].setText(
                    f"{v:.{r.decimals}f}" if connected else "--")
            self.wave.push(r.key, v if connected else 0.0)
