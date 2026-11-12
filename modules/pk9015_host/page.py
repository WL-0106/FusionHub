# -*- coding: utf-8 -*-
"""PK9015 12 路电流采集模块上位机 · 融合版界面（FusionHub 风格）。

Modbus RTU 协议栈 / 寄存器表 / 换算 / 模拟从站 零改动复用 core 包，
界面按整体 UI 风格重建：
连接配置（真实串口 / 模拟从站）→ 12 路电流实时采集 →
量程设置 / 模块搜索 / 地址修改 → 底部通讯日志。

界面只消费 protocol.PK9015 语义接口，不接触帧字节；
寄存器地址与换算一律来自 registers.py 单一事实源；轮询上一周期未完成自动跳过，
不堆积命令；工作线程不读控件（参数一律主线程先取好再传入）。
"""
import socket
import threading

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                             QPushButton, QScrollArea, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)

from instrument_hub.widgets import Card

from .core import registers as R
from .core import simulator
from .core.protocol import (BAUD_CODES, PK9015, ProtocolError, SerialTransport,
                            TcpTransport, hexs)

# PK9015 手册：地址/波特率只写寄存器 0x0000 支持 1200~19200（码 03~07）
BAUDS = sorted(BAUD_CODES)


class _SimServer:
    """内嵌模拟从站：本地 TCP 串口服务器，复用 simulator.build_slaves / make_handler。"""

    def __init__(self, addr, range_code):
        self.slaves = simulator.build_slaves((addr,), 9600, range_code)
        self._stop = threading.Event()
        self._srv = None
        self.port = self._bind()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _bind(self):
        for port in range(5023, 5040):
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
        raise ProtocolError("无法启动模拟从站：端口 5023~5039 均被占用")

    def _run(self):
        handler = simulator.make_handler(self.slaves, verbose=False)
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
                threading.Thread(target=handler, args=(conn, _addr), daemon=True).start()
        finally:
            try:
                srv.close()
            except OSError:
                pass

    def close(self):
        self._stop.set()
        try:
            if self._srv is not None:
                self._srv.close()
        except OSError:
            pass


class Pk9015Page(QWidget):
    """PK9015 12 路电流采集模块：连接 → 采集 → 量程/搜索/地址。"""

    # 采集启停按钮两态配色：采集中「开始采集」变绿色实心，停止恢复白底
    _COLLECT_ON_QSS = ("QPushButton{background:#10B981; color:#FFFFFF; border:2px solid #047857; "
                       "border-radius:10px; font-weight:700; font-size:12px; padding:3px 12px;}"
                       "QPushButton:pressed{background:#047857;}")
    _COLLECT_OFF_QSS = ("QPushButton{background:#FFFFFF; color:#4B4A73; border:2px solid #D6D3EE; "
                        "border-radius:10px; font-weight:700; font-size:12px; padding:3px 12px;}"
                        "QPushButton:pressed{background:#D6D3EE;}")

    sig_log = pyqtSignal(str, str)             # (方向, 文本) 工作线程 → 主线程
    sig_meas = pyqtSignal(object)              # 12 个原始寄存器（None 表示失败）
    sig_conn_ok = pyqtSignal(object, object)   # (dev, cfg)
    sig_conn_fail = pyqtSignal(str)
    sig_scan = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dev = None
        self._sim = None
        self._collecting = False   # 采集启停（开始/停止采集按钮 与「自动采集」勾选双向同步）
        self._inflight = False
        self._trace_on = False
        self._ok = 0
        self._fail = 0
        self._stop_search = False
        self._searching = False
        self._range_code = R.RANGE_0_20MA

        self.sig_log.connect(self._append_log)
        self.sig_meas.connect(self._show_measurement)
        self.sig_conn_ok.connect(self._on_conn_ok)
        self.sig_conn_fail.connect(self._on_conn_fail)
        self.sig_scan.connect(self._on_scan_done)

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
        mid.setSizes([720, 360])
        bv.addWidget(mid, 1)

        # 上方内容包滚动区：窗口不够高时采集区/右侧功能区内部下拉滚动，
        # 通讯日志保持可见底线——打开页面即可看到日志，无需手动拉伸
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
        self._timer.setInterval(500)
        self._refresh_ports()

    # ---------------------------------------------------------- 连接配置
    def _build_conn_card(self) -> Card:
        card = Card("连接配置",
                    "Modbus-RTU · RS-485 · 8-N-1 · 波特率 1200~19200；"
                    "12 路电流 I0~I11，量程 0-20mA / 4-20mA 可切换")
        g = QVBoxLayout()
        g.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("链路"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["真实串口", "模拟从站"])
        self.cmb_link.currentIndexChanged.connect(self._on_link_changed)
        top.addWidget(self.cmb_link)

        self.lbl_port = QLabel("串口")
        top.addWidget(self.lbl_port)
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setStyleSheet("QComboBox{min-width:130px;}")
        top.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setFixedWidth(56)
        self.btn_refresh.setMinimumHeight(30)
        self.btn_refresh.clicked.connect(self._refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_baud = QLabel("波特率")
        top.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        for b in BAUDS:
            self.cmb_baud.addItem(str(b))
        self.cmb_baud.setCurrentText("9600")
        top.addWidget(self.cmb_baud)

        top.addWidget(QLabel("设备地址"))
        self.sp_addr = QSpinBox()
        self.sp_addr.setRange(1, 247)
        self.sp_addr.setValue(1)
        self.sp_addr.setFixedWidth(72)
        top.addWidget(self.sp_addr)

        top.addSpacing(10)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.setMinimumHeight(30)
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
        low.addWidget(QLabel("采集间隔(ms)"))
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(50, 10000)
        self.sp_interval.setValue(500)
        self.sp_interval.setFixedWidth(88)
        low.addWidget(self.sp_interval)
        self.chk_auto = QCheckBox("自动采集")
        self.chk_auto.setChecked(True)
        self.chk_auto.toggled.connect(self._on_auto_toggled)
        low.addWidget(self.chk_auto)
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
        self.btn_clear_stat.setFixedWidth(52)
        self.btn_clear_stat.setMinimumHeight(30)
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
        is_sim = self.cmb_link.currentText() == "模拟从站"
        self.lbl_port.setText("端口" if is_sim else "串口")
        self.btn_refresh.setEnabled(not is_sim)
        self.lbl_baud.setEnabled(not is_sim)
        self.cmb_baud.setEnabled(not is_sim)

    def _on_trace_toggled(self, checked):
        self._trace_on = bool(checked)

    # ---------------------------------------------------------- 数据采集
    def _build_measure_card(self) -> Card:
        card = Card("12 路电流采集（I0~I11）",
                    "每路 16 位无符号原始值，按量程换算显示；量程切换即时生效")
        # 手动采集启停（原上位机同款按钮；与「自动采集」勾选双向同步）
        top = QHBoxLayout()
        top.setSpacing(8)
        self.btn_start_collect = QPushButton("开始采集")
        self.btn_start_collect.setMinimumHeight(30)
        self.btn_start_collect.setEnabled(False)
        self.btn_start_collect.setProperty("selfStyled", True)  # 采集中手动切色，框架不覆盖
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

        self._lbl_currents = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setVerticalSpacing(4)
        # 3 列 × 4 行排布 12 路（I0~I11）
        for ch in range(R.CHANNEL_COUNT):
            row, col = ch // 3, ch % 3
            # 单行紧凑排布：标题 | 值方框 | 单位（不再三行堆叠）
            cell = QHBoxLayout()
            cell.setSpacing(6)
            cap = QLabel("I%d" % ch)
            cap.setObjectName("Muted")
            cell.addWidget(cap)
            val = QLabel("----")
            val.setStyleSheet("font-size:20px; font-weight:800; color:#0E7490;"
                              "background:#FFFFFF; border:1px solid #CBD5E1;"
                              "border-radius:6px; padding:4px 10px;")
            val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            val.setMinimumWidth(110)   # 方框统一宽度，数值纵向对齐
            cell.addWidget(val, 1)
            unit = QLabel("mA")
            unit.setObjectName("Muted")
            cell.addWidget(unit)
            grid.addLayout(cell, row, col)
            self._lbl_currents[ch] = val
        for c in range(3):
            grid.setColumnStretch(c, 1)  # 三列均匀分布
        # 量程提示
        self.lbl_range_hint = QLabel("当前量程：0-20mA")
        self.lbl_range_hint.setObjectName("Muted")
        grid.addWidget(self.lbl_range_hint, 4, 0, 1, 3)
        card.body_lay.addLayout(grid)
        card.body_lay.addStretch(1)
        return card

    # ---------------------------------------------------------- 右侧栏
    def _build_side(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._build_range_card())
        v.addWidget(self._build_scan_card())
        v.addWidget(self._build_addr_card())
        v.addStretch(1)
        return w

    def _build_range_card(self) -> Card:
        card = Card("量程设置", "寄存器 0x02BE：0=0-20mA、1=4-20mA、2=0-10V")
        g = QGridLayout()
        g.setSpacing(6)
        g.addWidget(QLabel("量程"), 0, 0)
        self.cmb_range = QComboBox()
        self.cmb_range.addItem("0-20mA", R.RANGE_0_20MA)
        self.cmb_range.addItem("4-20mA", R.RANGE_4_20MA)
        self.cmb_range.addItem("0-10V", R.RANGE_0_10V)
        self.cmb_range.currentIndexChanged.connect(self._on_range_selected)
        g.addWidget(self.cmb_range, 0, 1)
        self.btn_set_range = QPushButton("写入量程")
        self.btn_set_range.setMinimumHeight(30)
        self.btn_set_range.clicked.connect(self._on_set_range)
        g.addWidget(self.btn_set_range, 1, 0, 1, 2)
        self.lbl_range_state = QLabel("—")
        self.lbl_range_state.setObjectName("Muted")
        self.lbl_range_state.setWordWrap(True)
        g.addWidget(self.lbl_range_state, 2, 0, 1, 2)
        card.body_lay.addLayout(g)
        return card

    def _build_scan_card(self) -> Card:
        card = Card("模块搜索", "按地址区间扫描在线模块（复用当前串口/链路）")
        g = QGridLayout()
        g.setSpacing(6)
        g.addWidget(QLabel("起始"), 0, 0)
        self.sp_scan_from = QSpinBox()
        self.sp_scan_from.setRange(1, 247)
        self.sp_scan_from.setValue(1)
        g.addWidget(self.sp_scan_from, 0, 1)
        g.addWidget(QLabel("结束"), 0, 2)
        self.sp_scan_to = QSpinBox()
        self.sp_scan_to.setRange(1, 247)
        self.sp_scan_to.setValue(247)
        g.addWidget(self.sp_scan_to, 0, 3)
        row = QHBoxLayout()
        self.btn_scan = QPushButton("开始搜索")
        self.btn_scan.setMinimumHeight(30)
        self.btn_scan.clicked.connect(self._on_scan)
        row.addWidget(self.btn_scan)
        self.btn_scan_stop = QPushButton("停止")
        self.btn_scan_stop.setMinimumHeight(30)
        self.btn_scan_stop.clicked.connect(self._on_scan_stop)
        self.btn_scan_stop.setEnabled(False)
        row.addWidget(self.btn_scan_stop)
        g.addLayout(row, 1, 0, 1, 4)
        self.lbl_scan_result = QLabel("未搜索")
        self.lbl_scan_result.setObjectName("Muted")
        self.lbl_scan_result.setWordWrap(True)
        g.addWidget(self.lbl_scan_result, 2, 0, 1, 4)
        card.body_lay.addLayout(g)
        return card

    def _build_addr_card(self) -> Card:
        card = Card("地址修改（写 0x0000）",
                    "寄存器 0x0000 高字节=地址(01~F7H)、低字节=波特率码(03~07H)；"
                    "只写寄存器，改后模块立即切换，需按新参数重新连接")
        g = QGridLayout()
        g.setSpacing(6)
        g.addWidget(QLabel("新地址"), 0, 0)
        self.sp_new_addr = QSpinBox()
        self.sp_new_addr.setRange(1, 247)
        self.sp_new_addr.setValue(1)
        g.addWidget(self.sp_new_addr, 0, 1)
        g.addWidget(QLabel("新波特率"), 1, 0)
        self.cmb_new_baud = QComboBox()
        for b in BAUDS:
            self.cmb_new_baud.addItem(str(b))
        self.cmb_new_baud.setCurrentText("9600")
        g.addWidget(self.cmb_new_baud, 1, 1)
        self.btn_set_addr = QPushButton("修改地址与波特率")
        self.btn_set_addr.setMinimumHeight(30)
        self.btn_set_addr.clicked.connect(self._on_set_addr)
        g.addWidget(self.btn_set_addr, 2, 0, 1, 2)
        card.body_lay.addLayout(g)
        return card

    # ---------------------------------------------------------- 通讯日志
    def _build_log_group(self) -> QGroupBox:
        grp = QGroupBox("通讯日志")
        grp.setMinimumHeight(150)   # 日志区可见底线：内容再多也不把日志挤出屏幕
        v = QVBoxLayout(grp)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(3000)
        v.addWidget(self.txt_log)
        return grp

    # ---------------------------------------------------------- 连接
    def _on_connect(self):
        if self._dev is not None:
            return
        # 主线程先取好参数，工作线程不读控件
        link = self.cmb_link.currentText()
        addr = self.sp_addr.value()
        baud = int(self.cmb_baud.currentText())
        port = self.cmb_port.currentText().strip()
        range_code = self.cmb_range.currentData()
        self.btn_conn.setEnabled(False)
        self.btn_conn.setText("连接中…")
        self.lbl_state.setText("连接中…")

        def work():
            dev = None
            try:
                if link == "模拟从站":
                    self._close_sim()
                    self._sim = _SimServer(addr, range_code)
                    tr = TcpTransport("127.0.0.1", self._sim.port, 0.6)
                else:
                    tr = SerialTransport(port, baud, 8, "N", 1, 0.6)
                dev = PK9015(tr, addr, trace=self._trace_cb())
                cfg = dev.read_config(timeout=1.0)   # 读地址/波特率/量程 = 连通判定
                self.sig_conn_ok.emit(dev, cfg)
            except Exception as e:  # noqa: BLE001
                if dev is not None:
                    try:
                        dev.close()
                    except Exception:  # noqa: BLE001
                        pass
                self.sig_conn_fail.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    def _trace_cb(self):
        def cb(sent, got):
            if self._trace_on:
                self.sig_log.emit("TX", ">> " + hexs(sent))
                if got:
                    self.sig_log.emit("RX", "<< " + hexs(got))
        return cb

    def _on_conn_ok(self, dev, cfg):
        self._dev = dev
        # 用设备读到的量程回填
        rc = cfg.get("range_code", R.RANGE_0_20MA)
        self._range_code = rc
        idx = self.cmb_range.findData(rc)
        if idx >= 0:
            self.cmb_range.blockSignals(True)
            self.cmb_range.setCurrentIndex(idx)
            self.cmb_range.blockSignals(False)
        self._update_range_hint()
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("已连接")
        self.btn_conn.setObjectName("btnConnected")
        self.btn_disc.setEnabled(True)
        self.lbl_state.setText("已连接")
        self._set_collecting(True)   # 连接成功默认开始采集
        self._log("INFO", "已连接：%s（地址 %d，8-N-1，%s）量程 %s"
                  % (self.cmb_link.currentText(), self.sp_addr.value(),
                     "模拟从站" if self.cmb_link.currentText() == "模拟从站"
                     else self.cmb_baud.currentText(),
                     R.RANGE_LABELS.get(rc, "未知")))

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
            except Exception:  # noqa: BLE001
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
            except Exception:  # noqa: BLE001
                pass
            self._sim = None

    # ---------------------------------------------------------- 采集启停
    def _set_collecting(self, on):
        """开始/停止采集（与「自动采集」勾选双向同步；未连接时一律停）。"""
        on = bool(on) and self._dev is not None
        self._collecting = on
        self.chk_auto.blockSignals(True)
        self.chk_auto.setChecked(on)
        self.chk_auto.blockSignals(False)
        self.btn_start_collect.setEnabled(not on)
        self.btn_stop_collect.setEnabled(on)
        # 采集中「开始采集」绿色实心，停止恢复白底
        self.btn_start_collect.setStyleSheet(self._COLLECT_ON_QSS if on else self._COLLECT_OFF_QSS)
        if on:
            self._timer.setInterval(self.sp_interval.value())
            self._timer.start()
            self.lbl_state.setText("采集中")
        else:
            self._timer.stop()
            self.lbl_state.setText("已连接" if self._dev is not None else "未连接")

    def _on_auto_toggled(self, checked):
        # 「自动采集」勾选 ↔ 开始/停止采集按钮 双向同步
        if self._dev is not None:
            self._set_collecting(checked)

    # ---------------------------------------------------------- 轮询
    def _on_tick(self):
        if not (self._collecting and self._dev is not None):
            return
        if self._inflight:
            return                       # 上一周期未完成，跳过不堆积
        self._timer.setInterval(self.sp_interval.value())
        self._inflight = True
        dev = self._dev

        def work():
            try:
                m = dev.read_currents(timeout=0.8)
                self.sig_meas.emit(m)
            except Exception:  # noqa: BLE001
                self.sig_meas.emit(None)
            finally:
                self._inflight = False

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- 语义操作
    def _require_dev(self):
        if self._dev is None:
            QMessageBox.warning(self, "提示", "请先连接设备")
            return None
        return self._dev

    def _run_worker(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _on_range_selected(self):
        self._range_code = self.cmb_range.currentData()
        self._update_range_hint()

    def _update_range_hint(self):
        self.lbl_range_hint.setText("当前量程：%s" % R.RANGE_LABELS.get(self._range_code, "未知"))

    def _on_set_range(self):
        dev = self._require_dev()
        if dev is None:
            return
        rc = self.cmb_range.currentData()

        def work():
            try:
                dev.save_range(rc)
                self.sig_log.emit("INFO", "量程已写入：%s" % R.RANGE_LABELS.get(rc, "未知"))
            except Exception as e:  # noqa: BLE001
                self.sig_log.emit("ERR", "写入量程失败：%s" % e)
        self._run_worker(work)

    def _on_set_addr(self):
        dev = self._require_dev()
        if dev is None:
            return
        cur = self.sp_addr.value()
        addr = self.sp_new_addr.value()
        baud = int(self.cmb_new_baud.currentText())
        if addr == cur:
            QMessageBox.warning(self, "提示", "新地址与当前地址相同。")
            return
        if QMessageBox.question(
                self, "确认修改",
                "将模块地址由 %d 改为 %d，新波特率 %d bps？\n\n"
                "写入后模块立即切换新参数，务必把新参数填回上方连接配置重新连接。"
                % (cur, addr, baud)) != QMessageBox.Yes:
            return

        def work():
            try:
                dev.save_address_baud(addr, baud)
                self.sig_log.emit("INFO", "地址已写入 %d，波特率 %d bps。请用新参数重新连接。"
                                  % (addr, baud))
            except Exception as e:  # noqa: BLE001
                self.sig_log.emit("ERR", "修改地址失败：%s" % e)
        self._run_worker(work)

    def _on_scan(self):
        dev = self._require_dev()
        if dev is None:
            return
        lo = min(self.sp_scan_from.value(), self.sp_scan_to.value())
        hi = max(self.sp_scan_from.value(), self.sp_scan_to.value())
        restore = self.sp_addr.value()
        self._stop_search = False
        self._searching = True
        self.btn_scan.setEnabled(False)
        self.btn_scan_stop.setEnabled(True)
        self.lbl_scan_result.setText("正在扫描 %d ~ %d ……" % (lo, hi))

        def work():
            found, tested = [], 0
            try:
                for s in range(lo, hi + 1):
                    if self._stop_search:
                        break
                    tested += 1
                    dev.set_slave(s)
                    try:
                        if dev.ping(timeout=0.30):
                            found.append(s)
                            self.sig_log.emit("INFO", "发现模块：地址 %d" % s)
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                dev.set_slave(restore)
            self.sig_scan.emit("已完成｜扫过 %d 个，发现 %d 个%s"
                               % (tested, len(found),
                                  "（已停止）" if self._stop_search else "") +
                               ("；地址：%s" % "、".join(str(x) for x in found) if found else ""))
        self._run_worker(work)

    def _on_scan_stop(self):
        self._stop_search = True

    def _on_scan_done(self, text):
        self._searching = False
        self.btn_scan.setEnabled(True)
        self.btn_scan_stop.setEnabled(False)
        self.lbl_scan_result.setText(text)

    def _on_clear_stat(self):
        self._ok = self._fail = 0
        self._update_stat_label()

    def _update_stat_label(self):
        self.lbl_stat.setText("成功: %d   失败: %d" % (self._ok, self._fail))

    # ---------------------------------------------------------- 显示 / 日志
    def _show_measurement(self, m):
        from instrument_hub.comm_state import mark_ok, mark_lost
        if m is None:
            mark_lost(self)
            self._fail += 1
            self._update_stat_label()
            self.sig_log.emit("ERR", "轮询失败")
            return
        mark_ok(self)   # 收到有效测量值 = 通讯真正建立
        self._ok += 1
        self._update_stat_label()
        rc = self._range_code
        for ch in range(R.CHANNEL_COUNT):
            if ch < len(m):
                ma = R.raw_to_current_ma(m[ch], rc)
                self._lbl_currents[ch].setText("%.2f" % ma)

    def _clear_readings(self):
        for ch in range(R.CHANNEL_COUNT):
            self._lbl_currents[ch].setText("----")

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

    # ---------------------------------------------------------- 退出闭环
    def shutdown(self):
        """退出保护：停轮询 → 断链 → 关闭内嵌模拟从站（安全闭环）。"""
        self._set_collecting(False)
        self._stop_search = True
        dev, self._dev = self._dev, None
        if dev is not None:
            try:
                dev.close()
            except Exception:  # noqa: BLE001
                pass
        self._close_sim()
