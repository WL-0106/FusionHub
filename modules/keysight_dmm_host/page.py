# -*- coding: utf-8 -*-
"""Keysight Truevolt 系列 DMM · 融合版界面（FusionHub 风格，功能对齐原 tkinter 上位机）。

core/（原 dmm 包）零改动复用：commands 命令表单一事实源 / protocol SCPI 协议栈
（半包粘包错帧重组、超时重发上限、命令队列化、异常码人话映射）/ semantic 语义化接口
（界面唯一入口，不接触帧字节）/ transport 串口+LAN+回环传输 / mock_slave 模拟从站。

界面重建要点：
- 12 种测量按钮、测量类型下拉、NPLC 范围、触发源枚举全部从 core.commands 派生，不硬编码；
- 连续采集 = QTimer 轮询 + 常驻工作线程 + queue.Queue（不每次新建线程），
  上一周期未完成跳过（_inflight），间隔下限 500ms（界面刷新不得快于串口吞吐）；
- TX/RX 日志经传输层代理（_LoggingTransport）打点，core 零改动；
- 掉线感知三坑：连续 3 次轮询失败 → mark_lost + 停采集；手动测量成功 → mark_ok + 提示恢复；
  断开全程 try/except，异常只记日志，按钮/状态/定时器复位必执行。
"""
import queue
import threading
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QScrollArea, QSplitter, QSpinBox, QVBoxLayout, QWidget)

from instrument_hub.comm_state import mark_lost, mark_ok
from instrument_hub.serial_ports import enumerate_ports
from instrument_hub.widgets import Card

from .core import SW_VERSION, PROTOCOL_VERSION, REG_TABLE_VERSION
from .core.commands import COMMANDS, get as get_cmd
from .core.mock_slave import MockDmmSlave
from .core.protocol import ProtocolError, ScpiClient, TimeoutError_
from .core.semantic import DmmService
from .core.transport import (LoopbackTransport, SerialTransport, TcpTransport,
                             TransportError)

# 采集间隔下限（毫秒）：界面刷新频率不得高于串口吞吐，防收发队列堆积假死
MIN_POLL_INTERVAL_MS = 500

# 连续轮询失败多少次判定仪器掉线（掉线感知三坑之一）
LOST_AFTER_FAILS = 3

# 单位显示映射（仅显示层美化，协议仍用命令表原文）
_UNIT_DISPLAY = {"Ohm": "Ω", "C": "℃"}

# 触发源下拉显示顺序（取值域仍以 core.commands 命令表 rng 为单一事实源）
_TRIG_ORDER = ("BUS", "IMMediate", "EXTernal", "INTernal")

# 日志条目前缀标记
_LOG_MARK = {"tx": "TX>", "rx": "RX<", "sys": "--", "err": "!!"}


def _explain_error(e: Exception) -> str:
    """异常 → 人话提示（坑位自查：错误必须翻译成现场能看懂的话）。"""
    if isinstance(e, TimeoutError_):
        return f"通信超时（已按上限重发并退出）: {e}"
    if isinstance(e, ProtocolError):
        return f"协议/参数错误: {e}"
    if isinstance(e, TransportError):
        return f"链路异常: {e}"
    if isinstance(e, ValueError):
        return f"参数无效: {e}"
    return f"操作失败: {e}"


class _LoggingTransport:
    """传输层代理：包装任意 Transport 记 TX/RX 日志（core 零改动，界面侧打点）。

    ScpiClient 只依赖 open/close/write/read/is_open（鸭子类型），包一层即可把
    真实链路字节（含重发帧）回传给页面日志：
    - TX：去掉换行尾巴记一行命令正文；
    - RX：按 LF 行重组记一行响应正文（半行残留缓冲到下一帧 TX 前冲日志）。
    """

    def __init__(self, inner, sink):
        self._inner = inner
        self._sink = sink            # callable(tag, text)，在工作线程内回调
        self._rx_acc = bytearray()   # 无换行尾巴的半行缓冲

    def open(self):
        return self._inner.open()

    def close(self):
        return self._inner.close()

    def write(self, data):
        if self._rx_acc:             # 上一条响应缺换行尾巴，先冲日志再发新帧
            self._flush_rx()
        self._sink("tx", bytes(data).decode("ascii", errors="replace").rstrip("\r\n"))
        return self._inner.write(data)

    def read(self, size=1, timeout_s=0.1):
        chunk = self._inner.read(size, timeout_s)
        if chunk:
            self._rx_acc.extend(chunk)
            while b"\n" in self._rx_acc:
                line, _, rest = self._rx_acc.partition(b"\n")
                self._sink("rx", bytes(line).decode("ascii", errors="replace").rstrip("\r"))
                self._rx_acc = bytearray(rest)
        return chunk

    def _flush_rx(self):
        if self._rx_acc:
            self._sink("rx", bytes(self._rx_acc).decode("ascii", errors="replace").rstrip("\r"))
            self._rx_acc = bytearray()

    @property
    def is_open(self):
        return self._inner.is_open


class KeysightDmmPage(QWidget):
    """Keysight Truevolt DMM 控制：连接 → 单次/连续测量 → 配置 → 通讯日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # ----- 协议侧状态 -----
        self._svc = None             # DmmService（工作线程内独占调用）
        self._mock = None            # 模拟从站引用（演示模式 / 测试切场景用）
        self.connected = False
        self._connecting = False
        self._acquiring = False
        self._inflight = False       # 上一轮询周期未完成标志（完成前跳过新周期）
        self._poll_fail = 0          # 连续轮询失败计数（满 3 次判掉线）
        self._lost = False           # 掉线标志（恢复时提示）

        # ----- 线程模型：常驻工作线程 + 双向队列（不每次操作新建线程） -----
        self._jobq = queue.Queue()   # 主线程 → 工作线程：任务
        self._uiq = queue.Queue()    # 工作线程 → 主线程：界面事件
        self._logq = queue.Queue()   # 任意线程 → 主线程：日志条目
        self._worker_stop = False
        self._worker = threading.Thread(target=self._worker_loop,
                                        name="keysight-dmm-worker", daemon=True)

        # ----- 界面 -----
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_conn_card())

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        # 左右分栏：左=测量值显示+触发+采集 | 右=测量功能按钮+仪器配置（配置在按钮下方）
        cols = QSplitter(Qt.Horizontal)
        cols.setChildrenCollapsible(False)
        cols.setHandleWidth(8)
        cols.addWidget(self._build_meas_card())
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        rl.addWidget(self._build_btn_card())
        rl.addWidget(self._build_config_card())
        rl.addStretch(1)
        cols.addWidget(right)
        cols.setStretchFactor(0, 1)
        cols.setStretchFactor(1, 0)
        cols.setSizes([760, 560])
        cl.addWidget(cols)
        scroll = QScrollArea()       # 小窗口时功能区滚动，日志区始终可见
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        scroll.setWidget(content)
        scroll.setMinimumHeight(280)
        split.addWidget(scroll)
        split.addWidget(self._build_log_card())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([640, 240])
        root.addWidget(split, 1)

        self._sync_conn_fields()

        # ----- 定时器：事件泵（常驻）+ 连续采集（按需） -----
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(100)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start()

        self._acq_timer = QTimer(self)
        self._acq_timer.timeout.connect(self._on_acq_tick)

        self._worker.start()

    # ------------------------------------------------------------ 连接卡
    def _build_conn_card(self) -> Card:
        card = Card("通讯连接", "模拟从站 / 串口 / LAN · Keysight Truevolt 34461A/34465A/34470A")

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("链路"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["模拟从站", "串口", "LAN"])
        self.cmb_link.setCurrentIndex(1)   # 默认串口（真机联调为主；模拟从站手动切换）
        self.cmb_link.setFixedWidth(100)
        self.cmb_link.currentIndexChanged.connect(self._sync_conn_fields)
        row1.addWidget(self.cmb_link)

        self.lbl_port = QLabel("端口")
        row1.addWidget(self.lbl_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setMinimumHeight(30)
        self.btn_refresh.clicked.connect(self._refresh_ports)
        row1.addWidget(self.btn_refresh)
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        ports = enumerate_ports()
        self.cmb_port.addItems(ports or ["COM3"])
        self.cmb_port.setCurrentText(ports[0] if ports else "COM3")
        self.cmb_port.setFixedWidth(130)
        row1.addWidget(self.cmb_port)

        self.lbl_baud = QLabel("波特率")
        row1.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "115200", "57600", "19200", "38400"])
        self.cmb_baud.setCurrentText("9600")
        self.cmb_baud.setFixedWidth(90)
        row1.addWidget(self.cmb_baud)

        self.lbl_ip = QLabel("IP 地址")
        row1.addWidget(self.lbl_ip)
        self.ed_ip = QLineEdit("192.168.1.100")
        self.ed_ip.setPlaceholderText("IP 或 IP:端口（默认 5025）")
        self.ed_ip.setFixedWidth(160)
        row1.addWidget(self.ed_ip)

        # 连接按钮并入参数行（波特率之后），不再单独占一行
        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("btnConnect")   # 框架契约：连接态改 btnConnected
        self.btn_connect.setMinimumHeight(32)
        self.btn_connect.clicked.connect(self._toggle_conn)
        row1.addWidget(self.btn_connect)
        row1.addStretch(1)
        card.body_lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.lbl_idn = QLabel("未连接")                # 连接成功后显示 *IDN? 身份串
        self.lbl_idn.setObjectName("Muted")
        self.lbl_idn.setWordWrap(True)
        row2.addWidget(self.lbl_idn, 1)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("Muted")
        row2.addWidget(self.lbl_status)
        card.body_lay.addLayout(row2)
        return card

    def _sync_conn_fields(self, *_args) -> None:
        """按链路类型显隐参数：串口=刷新+端口+波特率，LAN=IP，模拟从站无参数。"""
        mode = self.cmb_link.currentIndex()
        serial, lan = mode == 1, mode == 2
        for w in (self.lbl_port, self.btn_refresh, self.cmb_port,
                  self.lbl_baud, self.cmb_baud):
            w.setVisible(serial)
        self.lbl_ip.setVisible(lan)
        self.ed_ip.setVisible(lan)

    def _refresh_ports(self) -> None:
        """手动刷新串口下拉（框架另有 3s 自动刷新兜底）。"""
        ports = enumerate_ports()
        cur = self.cmb_port.currentText().strip()
        self.cmb_port.blockSignals(True)
        self.cmb_port.clear()
        self.cmb_port.addItems(ports or ([cur] if cur else ["COM3"]))
        if cur:
            self.cmb_port.setCurrentText(cur)
        self.cmb_port.blockSignals(False)
        self._log("sys", f"串口扫描完成，发现 {len(ports)} 个端口")

    def _make_transport_factory(self):
        """按链路类型生成传输工厂（在工作线程内调用，串口/TCP 打开不卡界面）。"""
        mode = self.cmb_link.currentIndex()
        if mode == 0:
            def factory():
                self._mock = MockDmmSlave(scenario="normal")
                return LoopbackTransport(self._mock.handle)
            return factory
        if mode == 1:
            port = self.cmb_port.currentText().strip() or "COM3"
            baud = int(self.cmb_baud.currentText())
            return lambda: SerialTransport(port, baudrate=baud)
        text = self.ed_ip.text().strip() or "192.168.1.100"
        host, _, port = text.partition(":")
        return lambda: TcpTransport(host, int(port) if port else 5025)

    def _toggle_conn(self) -> None:
        if self.connected:
            self._do_disconnect()
        else:
            self._do_connect()

    def _do_connect(self) -> None:
        if self.connected or self._connecting:
            return
        self._connecting = True
        factory = self._make_transport_factory()
        self.btn_connect.setEnabled(False)   # 连接期间防重复点击
        self.lbl_status.setText("正在连接…")
        self._log("sys", "正在连接仪器…")
        self._jobq.put(("connect", factory))

    def _do_disconnect(self) -> None:
        """断开：先停采集并复位按钮/状态/标志，再让工作线程收尾断链。

        全程 try/except 兜底——异常只记日志，状态复位必执行（掉线感知三坑之三）。
        """
        try:
            self._stop_acquisition()
        except Exception:
            pass
        self._connecting = False
        self.connected = False
        self._inflight = False
        self._poll_fail = 0
        self._lost = False
        try:
            self.btn_connect.setObjectName("btnConnect")
            self.btn_connect.setText("连接")
            self.btn_connect.setEnabled(True)
        except Exception:
            pass
        try:
            mark_lost(self)
        except Exception:
            pass
        self.lbl_idn.setText("未连接")
        self.lbl_status.setText("未连接")
        self._log("sys", "已断开连接")
        self._jobq.put(("disconnect",))

    # ------------------------------------------------------------ 测量卡
    def _build_meas_card(self) -> Card:
        """左栏：测量值显示区（大读数 + 触发读数 + 连续采集控制）。"""
        card = Card("测量显示", "大读数实时刷新 · 点右侧功能按钮单次测量或开始连续采集")

        top = QHBoxLayout()
        top.setSpacing(14)
        self.lbl_value = QLabel("--")
        self.lbl_value.setAlignment(Qt.AlignCenter)
        self.lbl_value.setStyleSheet(
            "font-size:32px; font-weight:800; color:#1D4ED8; font-family:Consolas;"
            "background:#FFFFFF; border:1px solid #CBD5E1; border-radius:6px; padding:8px 24px;")
        self.lbl_value.setMinimumHeight(58)
        top.addWidget(self.lbl_value)
        self.lbl_unit = QLabel("")
        self.lbl_unit.setAlignment(Qt.AlignCenter)
        self.lbl_unit.setStyleSheet(
            "font-size:16px; font-weight:700; color:#0F766E;"
            "background:#FFFFFF; border:1px solid #CBD5E1; border-radius:6px; padding:6px 14px;")
        self.lbl_unit.setMinimumHeight(40)
        top.addWidget(self.lbl_unit)
        top.addStretch(1)
        card.body_lay.addLayout(top)

        self.lbl_info = QLabel("点击右侧测量功能按钮单次测量，或开始连续采集")
        self.lbl_info.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_info)

        self._measure_defs = [c for c in COMMANDS if c.key.startswith("read_")]
        trig = next((c for c in self._measure_defs if c.key == "read_trigger"), None)
        if trig is not None:
            b_trig = QPushButton(trig.desc)
            b_trig.setProperty("selfStyled", True)   # 自绘琥珀态，框架不按文字刷色
            b_trig.setMinimumHeight(34)
            b_trig.setStyleSheet(
                "QPushButton{background:#FEF3C7; color:#B45309; border:2px solid #F59E0B;"
                " border-radius:10px; font-weight:700;}"
                "QPushButton:hover{background:#FDE68A;}"
                "QPushButton:pressed{background:#F59E0B;}")
            b_trig.setToolTip(f"{trig.scpi}　单位: {trig.unit or '—'}")
            b_trig.clicked.connect(lambda _=False, k=trig.key: self._on_measure_clicked(k))
            card.body_lay.addWidget(b_trig)

        acq = QHBoxLayout()
        acq.setSpacing(8)
        self.btn_acq_start = QPushButton("开始采集")
        self.btn_acq_start.setMinimumHeight(30)
        self.btn_acq_start.clicked.connect(self._on_acq_start)
        acq.addWidget(self.btn_acq_start)
        self.btn_acq_stop = QPushButton("停止采集")
        self.btn_acq_stop.setMinimumHeight(30)
        self.btn_acq_stop.setEnabled(False)   # 与开始按钮互斥使能
        self.btn_acq_stop.clicked.connect(self._on_acq_stop)
        acq.addWidget(self.btn_acq_stop)
        acq.addWidget(QLabel("采集间隔"))
        self.spn_interval = QSpinBox()
        self.spn_interval.setRange(MIN_POLL_INTERVAL_MS, 60000)
        self.spn_interval.setValue(1000)
        self.spn_interval.setSuffix(" ms")
        self.spn_interval.setFixedWidth(100)
        self.spn_interval.setToolTip(
            f"下限 {MIN_POLL_INTERVAL_MS}ms：界面刷新频率不得高于串口吞吐，防队列堆积假死")
        self.spn_interval.valueChanged.connect(self._on_interval_changed)
        acq.addWidget(self.spn_interval)
        acq.addWidget(QLabel("测量类型"))
        self.cmb_acq_type = QComboBox()
        for c in self._measure_defs:
            self.cmb_acq_type.addItem(f"{c.desc}（{c.unit}）" if c.unit else c.desc, c.key)
        self.cmb_acq_type.setFixedWidth(190)
        acq.addWidget(self.cmb_acq_type)
        acq.addStretch(1)
        card.body_lay.addLayout(acq)
        return card

    # 测量功能键分类着色（与统一上位机 UI 规范一致）
    _MEAS_COLORS = (
        ("volt", "#3b82f6"), ("curr", "#f97316"), ("res", "#10b981"),
        ("cap", "#ec4899"), ("freq", "#8b5cf6"), ("period", "#8b5cf6"),
        ("diode", "#14b8a6"), ("cont", "#14b8a6"), ("temp", "#0e7490"),
    )

    @classmethod
    def _meas_color(cls, key: str) -> str:
        for frag, color in cls._MEAS_COLORS:
            if frag in key:
                return color
        return "#4B4A73"

    def _build_btn_card(self) -> Card:
        """右栏上：12 种测量功能按钮（分类着色、紧凑比例，触发按钮独立在左栏）。"""
        card = Card("测量功能", "12 种测量功能由 core.commands 命令表派生（单一事实源），点击即单次测量")
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        funcs = [c for c in self._measure_defs if c.key != "read_trigger"]
        for i, c in enumerate(funcs):
            b = QPushButton(c.desc)
            b.setProperty("selfStyled", True)   # 自绘分类着色，框架不按文字刷色（未连接也保持彩框）
            b.setMinimumHeight(26)   # 右栏紧凑比例
            color = self._meas_color(c.key)
            b.setStyleSheet(
                f"QPushButton{{background:#FFFFFF; border:2px solid {color}; color:{color};"
                f" border-radius:8px; font-weight:700; font-size:12px; padding:3px 8px;}}"
                f"QPushButton:hover{{background:{color}22;}}"
                f"QPushButton:pressed{{background:{color}33;}}")
            b.setToolTip(f"{c.scpi}　单位: {c.unit or '—'}")
            b.clicked.connect(lambda _=False, k=c.key: self._on_measure_clicked(k))
            grid.addWidget(b, i // 2, i % 2)
        card.body_lay.addLayout(grid)
        return card

    def _build_config_card(self) -> Card:
        card = Card("仪器配置", "NPLC / 触发源 / 仪器显示文本 / 复位 / 错误队列（语义化接口写入）")

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(QLabel("积分 NPLC"))
        nplc_def = get_cmd("sense_nplc")
        lo, hi = nplc_def.rng          # 范围取自命令表单一事实源（0.02~100 PLC）
        self.spn_nplc = QDoubleSpinBox()
        self.spn_nplc.setRange(lo, hi)
        self.spn_nplc.setDecimals(2)
        self.spn_nplc.setSingleStep(0.1)
        self.spn_nplc.setValue(1.0)
        self.spn_nplc.setFixedWidth(90)
        self.spn_nplc.setToolTip(f"{lo}~{hi} PLC（34461A 上限 100；34465A/34470A 可到 200，写入前按型号确认）")
        r1.addWidget(self.spn_nplc)
        btn_nplc = QPushButton("写入")
        btn_nplc.setMinimumHeight(30)
        btn_nplc.clicked.connect(self._on_nplc)
        r1.addWidget(btn_nplc)
        r1.addSpacing(12)
        r1.addWidget(QLabel("触发源"))
        self.cmb_trig = QComboBox()
        trig_allowed = set(get_cmd("trig_source").rng)   # 取值域来自命令表
        for src in _TRIG_ORDER:
            if src in trig_allowed:
                self.cmb_trig.addItem(src)
        self.cmb_trig.setFixedWidth(110)
        r1.addWidget(self.cmb_trig)
        btn_trig = QPushButton("写入")
        btn_trig.setMinimumHeight(30)
        btn_trig.clicked.connect(self._on_trig)
        r1.addWidget(btn_trig)
        r1.addStretch(1)
        card.body_lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(QLabel("显示文本"))
        self.ed_text = QLineEdit("DMM-OK")
        self.ed_text.setMaxLength(32)
        self.ed_text.setFixedWidth(150)
        r2.addWidget(self.ed_text)
        btn_text = QPushButton("写入")
        btn_text.setMinimumHeight(30)
        btn_text.clicked.connect(self._on_text)
        r2.addWidget(btn_text)
        btn_clear = QPushButton("清除")
        btn_clear.setMinimumHeight(30)
        btn_clear.clicked.connect(self._on_clear_text)
        r2.addWidget(btn_clear)
        r2.addSpacing(12)
        btn_reset = QPushButton("复位 *RST")
        btn_reset.setMinimumHeight(30)
        btn_reset.clicked.connect(self._on_reset)
        r2.addWidget(btn_reset)
        btn_err = QPushButton("读错误队列")
        btn_err.setMinimumHeight(30)
        btn_err.clicked.connect(self._on_read_err)
        r2.addWidget(btn_err)
        r2.addStretch(1)
        card.body_lay.addLayout(r2)

        ver = QLabel(f"core v{SW_VERSION} · 协议 {PROTOCOL_VERSION} · 命令表 v{REG_TABLE_VERSION}")
        ver.setObjectName("Muted")
        card.body_lay.addWidget(ver)
        return card

    def _build_log_card(self) -> Card:
        card = Card("通讯日志", "TX/RX 带时间戳（传输层代理打点，core 零改动）")
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(4000)
        self.txt_log.setMinimumHeight(150)   # 小窗口下日志区仍可见
        self.txt_log.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,monospace; font-size:12px;"
            "background:#FFFFFF; border:1px solid #E5E7EB; border-radius:6px; padding:4px 8px;}")
        card.body_lay.addWidget(self.txt_log, 1)
        return card

    # ------------------------------------------------------------ 工作线程
    def _worker_loop(self) -> None:
        """常驻工作线程：串行消费任务队列，所有 SCPI 收发都在本线程完成。"""
        while True:
            try:
                job = self._jobq.get(timeout=0.2)
            except queue.Empty:
                if self._worker_stop:
                    break
                continue
            if job is None:
                break
            try:
                self._run_job(job)
            except Exception as e:   # 双保险：工作线程自身绝不带崩进程
                try:
                    self._uiq.put(("job_fail", "内部任务", _explain_error(e), None))
                except Exception:
                    pass

    @staticmethod
    def _job_label(job) -> str:
        if job[0] == "measure":
            try:
                return get_cmd(job[1]).desc
            except KeyError:
                return f"测量[{job[1]}]"
        names = {"nplc": "写入 NPLC", "trig": "写入触发源", "text": "写入显示文本",
                 "cleartext": "清除显示", "reset": "复位 *RST",
                 "readerr": "读错误队列", "disconnect": "断开连接"}
        return names.get(job[0], job[0])

    def _run_job(self, job) -> None:
        op = job[0]
        if op == "connect":
            _op, factory = job
            try:
                transport = _LoggingTransport(factory(), self._log)
                client = ScpiClient(transport, default_timeout_s=1.0,
                                    max_retries=2, queue_limit=32)
                svc = DmmService(client)
                idn = svc.connect()          # 打开链路 + *IDN? 身份识别
                self._svc = svc
                self._uiq.put(("connected", idn))
            except Exception as e:
                self._uiq.put(("conn_fail", _explain_error(e)))
            return
        if op == "disconnect":
            svc, self._svc = self._svc, None
            if svc is not None:
                try:
                    svc.disconnect()
                except Exception as e:
                    self._log("err", f"断开时链路异常（已忽略）: {_explain_error(e)}")
            return   # 界面状态在按钮按下时已复位，无需再发事件
        svc = self._svc
        if svc is None or not svc.connected:
            self._uiq.put(("job_fail", self._job_label(job),
                           "仪器未连接", job[2] if op == "measure" else None))
            return
        try:
            if op == "measure":
                _op, key, source = job
                info = svc.measure_with_unit(key)
                self._uiq.put(("reading", key, info["value"], info["unit"],
                               info["desc"], source))
            elif op == "nplc":
                svc.set_integration_nplc(job[1])
                self._uiq.put(("done", f"已写入积分 NPLC = {job[1]:g}"))
            elif op == "trig":
                svc.set_trigger_source(job[1])
                self._uiq.put(("done", f"已写入触发源 = {job[1]}"))
            elif op == "text":
                svc.set_display_text(job[1])
                self._uiq.put(("done", f"已写入仪器显示文本 = {job[1]}"))
            elif op == "cleartext":
                svc.clear_display()
                self._uiq.put(("done", "已清除仪器显示文本"))
            elif op == "reset":
                svc.reset()
                self._uiq.put(("done", "已下发仪器复位 *RST"))
            elif op == "readerr":
                self._uiq.put(("done", f"错误队列: {svc.last_error_text()}"))
        except Exception as e:
            self._uiq.put(("job_fail", self._job_label(job), _explain_error(e),
                           job[2] if op == "measure" else None))

    # ------------------------------------------------------------ 事件泵（主线程）
    def _drain(self) -> None:
        self._drain_logs()
        while True:
            try:
                ev = self._uiq.get_nowait()
            except queue.Empty:
                return
            self._dispatch(ev)

    def _dispatch(self, ev) -> None:
        kind = ev[0]
        if kind == "connected":
            self._connecting = False
            self.connected = True
            self._lost = False
            self._poll_fail = 0
            self._inflight = False
            self.btn_connect.setObjectName("btnConnected")
            self.btn_connect.setText("已连接")
            self.btn_connect.setEnabled(True)
            mark_ok(self)   # *IDN? 有效应答到达，通讯真正建立
            self.lbl_idn.setText(ev[1])
            self.lbl_status.setText("已连接")
            self._log("sys", f"连接成功: {ev[1]}")
        elif kind == "conn_fail":
            self._connecting = False
            self.btn_connect.setEnabled(True)
            mark_lost(self)   # 连接失败不置已连接
            self.lbl_status.setText(f"连接失败: {ev[1]}")
            self._log("err", f"连接失败: {ev[1]}")
        elif kind == "reading":
            self._on_reading(ev[1], ev[2], ev[3], ev[4], ev[5])
        elif kind == "job_fail":
            self._on_job_fail(ev[1], ev[2], ev[3])
        elif kind == "done":
            self.lbl_status.setText(ev[1])
            self._log("sys", ev[1])

    def _on_reading(self, key, value, unit, desc, source) -> None:
        if source == "poll":
            self._inflight = False
            if not self._acquiring:
                return   # 停止采集后迟到的读数，丢弃
        if not self.connected:
            return
        mark_ok(self)
        self._poll_fail = 0
        if self._lost:   # 掉线感知三坑之二：手动/轮询测量成功 → 恢复
            self._lost = False
            self._log("sys", "仪器已恢复响应")
            self.lbl_status.setText("仪器已恢复响应")
        self.lbl_value.setText(f"{value:.6g}")
        self.lbl_unit.setText(_UNIT_DISPLAY.get(unit, unit))
        self.lbl_info.setText(f"{desc}（{key}） · {time.strftime('%H:%M:%S')}")
        self._log("sys", f"[{key}] {value:.6g} {unit}")

    def _on_job_fail(self, label, text, source) -> None:
        self._log("err", f"{label}失败: {text}")
        self.lbl_status.setText(f"{label}失败: {text}")
        if source != "poll":
            return
        self._inflight = False
        if not self._acquiring or not self.connected:
            return
        self._poll_fail += 1
        if self._poll_fail >= LOST_AFTER_FAILS:
            # 掉线感知三坑之一：连续 3 次轮询失败 → 掉线提示 + 停采集
            self._lost = True
            try:
                mark_lost(self)
            except Exception:
                pass
            self._stop_acquisition()
            msg = f"仪器连续 {LOST_AFTER_FAILS} 次无响应，已停止采集（请检查链路后手动测量验证恢复）"
            self._log("err", msg)
            self.lbl_status.setText(msg)

    # ------------------------------------------------------------ 操作槽
    def _require_connected(self) -> bool:
        """操作前置检查：未连接只提示不弹窗（自动化友好，异常路径人话显示）。"""
        if self._connecting:
            self.lbl_status.setText("正在连接…")
            self._log("sys", "正在连接，请稍候")
            return False
        if not self.connected:
            self.lbl_status.setText("请先连接仪器")
            self._log("sys", "操作未执行：请先连接仪器")
            return False
        return True

    def _on_measure_clicked(self, key: str) -> None:
        if not self._require_connected():
            return
        self._jobq.put(("measure", key, "manual"))

    def _on_acq_start(self) -> None:
        if self._acquiring:
            return
        if not self._require_connected():
            return
        self._acquiring = True
        self._inflight = False
        self._poll_fail = 0
        self.btn_acq_start.setEnabled(False)
        self.btn_acq_stop.setEnabled(True)
        self._acq_timer.setInterval(self.spn_interval.value())
        self._acq_timer.start()
        self._log("sys", f"连续采集开始，间隔 {self.spn_interval.value()} ms"
                         f"（下限 {MIN_POLL_INTERVAL_MS} ms，防刷新快于串口吞吐）")

    def _on_acq_stop(self) -> None:
        self._stop_acquisition()
        self._log("sys", "连续采集已停止")

    def _stop_acquisition(self) -> None:
        """停止采集并复位互斥按钮（静默：日志由调用方按语境记录）。"""
        self._acquiring = False
        self._inflight = False
        if self._acq_timer is not None and self._acq_timer.isActive():
            self._acq_timer.stop()
        self.btn_acq_start.setEnabled(True)
        self.btn_acq_stop.setEnabled(False)

    def _on_acq_tick(self) -> None:
        if not self.connected or not self._acquiring:
            self._stop_acquisition()
            return
        if self._inflight:
            return   # 上一周期未完成，跳过本周期（防堆积）
        key = self.cmb_acq_type.currentData()
        if not key:
            return
        self._inflight = True
        self._jobq.put(("measure", key, "poll"))

    def _on_interval_changed(self, ms: int) -> None:
        if self._acq_timer.isActive():
            self._acq_timer.setInterval(max(MIN_POLL_INTERVAL_MS, int(ms)))

    def _on_nplc(self) -> None:
        if not self._require_connected():
            return
        self._jobq.put(("nplc", float(self.spn_nplc.value())))

    def _on_trig(self) -> None:
        if not self._require_connected():
            return
        self._jobq.put(("trig", self.cmb_trig.currentText()))

    def _on_text(self) -> None:
        if not self._require_connected():
            return
        self._jobq.put(("text", self.ed_text.text()))

    def _on_clear_text(self) -> None:
        if not self._require_connected():
            return
        self._jobq.put(("cleartext",))

    def _on_reset(self) -> None:
        if not self._require_connected():
            return
        self._jobq.put(("reset",))

    def _on_read_err(self) -> None:
        if not self._require_connected():
            return
        self._jobq.put(("readerr",))

    # ------------------------------------------------------------ 日志
    def _log(self, tag: str, text) -> None:
        """线程安全日志入口：任意线程调用，主线程定时统一显示。"""
        self._logq.put((time.time(), tag, str(text)))

    def _drain_logs(self) -> None:
        while True:
            try:
                ts, tag, text = self._logq.get_nowait()
            except queue.Empty:
                break
            stamp = time.strftime("%H:%M:%S", time.localtime(ts))
            self.txt_log.appendPlainText(f"[{stamp}] {_LOG_MARK.get(tag, '--')} {text}")
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------ 退出保护
    def shutdown(self) -> None:
        """退出/卸载：停全部定时器 → 停采集 → 停/join 工作线程 → 断开 → 状态复位。

        每步 try/except 兜底：异常只记日志，状态复位（按钮/标志/指示灯）必执行。
        """
        for t in (getattr(self, "_drain_timer", None), getattr(self, "_acq_timer", None)):
            if t is not None:
                try:
                    t.stop()
                except Exception:
                    pass
        try:
            self._stop_acquisition()
        except Exception:
            pass
        try:
            self._worker_stop = True
            self._jobq.put(None)
            if self._worker is not None:
                self._worker.join(timeout=5.0)
        except Exception:
            pass
        try:
            if self._svc is not None:
                self._svc.disconnect()
        except Exception as e:
            self._log("err", f"断开时异常（已忽略）: {_explain_error(e)}")
        self._svc = None
        self.connected = False
        self._connecting = False
        try:
            self.btn_connect.setObjectName("btnConnect")
            self.btn_connect.setText("连接")
            self.btn_connect.setEnabled(True)
        except Exception:
            pass
        try:
            mark_lost(self)
        except Exception:
            pass
        try:
            self._drain_logs()   # 定时器已停，剩余日志一次性落盘
        except Exception:
            pass
