# -*- coding: utf-8 -*-
"""GW Instek GDM-9060/9061 数字万用表 · 融合版界面（FusionHub 风格）。

测量逻辑零改动复用原上位机 gdm906x 包（core/：scpi 指令构建与读数解析、
transport 串口/TCP/模拟从站三通道、Meter 高层 API + Poller 后台轮询），
界面按整体 UI 风格重建：连接配置 → （测量显示 | 测量设置）→ 设备控制 → 通讯日志。
"""
import queue
import threading
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                             QSpinBox, QSplitter, QVBoxLayout, QWidget)

from instrument_hub.serial_ports import enumerate_ports
from instrument_hub.widgets import Card

from .core import scpi
from .core.meter import Meter, NoDataError, Poller

LINKS = ("串口 / USB-CDC", "网络 TCP", "模拟从站")
BAUDS = ("115200", "57600", "38400", "19200", "9600")   # 手册 RS232 可选档，默认 115200
INTERVALS = ("200 ms", "500 ms", "1 s", "2 s", "5 s")


class TrendChart(QWidget):
    """最近 600 个采样点的实时曲线（自绘，无第三方依赖）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pts = []
        self.setMinimumHeight(130)
        self.setMaximumHeight(190)

    def push(self, value: float) -> None:
        self._pts.append(float(value))
        if len(self._pts) > 600:
            del self._pts[:-600]
        self.update()

    def clear(self) -> None:
        self._pts.clear()
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor("#F8FAFC"))
        p.setPen(QPen(QColor("#E2E8F0"), 1))
        p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 8, 8)
        plot = r.adjusted(56, 10, -12, -22)
        if len(self._pts) < 2:
            p.setPen(QColor("#94A3B8"))
            p.drawText(r, Qt.AlignCenter, "暂无数据（开始测量后绘制趋势）")
            return
        vmin, vmax = min(self._pts), max(self._pts)
        if vmax - vmin < 1e-12:
            vmin, vmax = vmin - 0.5, vmax + 0.5
        pad = (vmax - vmin) * 0.08
        vmin, vmax = vmin - pad, vmax + pad

        p.setPen(QPen(QColor("#E2E8F0"), 1, Qt.DashLine))
        fnt = QFont(p.font())
        fnt.setPointSize(8)
        p.setFont(fnt)
        for frac in (0.0, 0.5, 1.0):
            y = plot.bottom() - frac * plot.height()
            p.drawLine(plot.left(), int(y), plot.right(), int(y))
            val = vmin + frac * (vmax - vmin)
            p.setPen(QColor("#64748B"))
            p.drawText(4, int(y) - 8, 50, 16, Qt.AlignRight | Qt.AlignVCenter,
                       scpi.format_si(val, "", sig=4))
            p.setPen(QPen(QColor("#E2E8F0"), 1, Qt.DashLine))

        pen = QPen(QColor("#0E7490"), 2)
        p.setPen(pen)
        n = len(self._pts)
        step = max(1, (n - 1) // 599)
        pts = self._pts[::step]
        m = len(pts)
        for i in range(1, m):
            x0 = plot.left() + (i - 1) / (m - 1) * plot.width()
            x1 = plot.left() + i / (m - 1) * plot.width()
            y0 = plot.bottom() - (pts[i - 1] - vmin) / (vmax - vmin) * plot.height()
            y1 = plot.bottom() - (pts[i] - vmin) / (vmax - vmin) * plot.height()
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
        p.setPen(QColor("#64748B"))
        p.drawText(plot.left(), r.bottom() - 18, 200, 14, Qt.AlignLeft,
                   f"最近 {n} 点")
        p.drawText(plot.right() - 220, r.bottom() - 18, 220, 14, Qt.AlignRight,
                   f"最小 {scpi.format_si(min(self._pts), '', 4)}　"
                   f"最大 {scpi.format_si(max(self._pts), '', 4)}")


class Gdm906xPage(QWidget):
    """GDM-9060/9061 控制：连接 → 测量设置 → 单次/连续测量 → 设备控制 → 通讯日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.meter = Meter()
        self.poller = None
        self._events = queue.Queue()
        # 常驻工作线程：串行执行后台 I/O 任务，替代原先「每次操作新建短命线程」，
        # 避免线程 churn，且天然串行化、无需担心多线程并发争抢 Meter。
        self._jobs = queue.Queue()
        self._worker_stop = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop,
                                        name="gdm-job", daemon=True)
        self._worker.start()
        self._func_key = "DCV"
        self._local_mode = False      # 「返回本地」后不再自动下发任何指令
        self._second_busy = False
        self._connecting = False
        self._records = []            # CSV 记录行 [(时间, 功能, 数值, 单位)]
        self._recording = False
        self._stat = dict(n=0, vmin=None, vmax=None, total=0.0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_conn_card())
        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        lv.addWidget(self._build_setup_card())
        lv.addWidget(self._build_dev_card())
        lv.addStretch(1)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)
        rv.addWidget(self._build_disp_card())
        rv.addStretch(1)
        mid.addWidget(left)
        mid.addWidget(right)
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 1)
        mid.setSizes([640, 640])
        root.addWidget(mid, 1)
        root.addWidget(self._build_log_card())   # 末项：框架自动改造成可拖分割条

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._pump)
        self._timer.start()
        self._second_timer = QTimer(self)        # 副显示低频查询（DATA2:LAST?）
        self._second_timer.setInterval(1500)
        self._second_timer.timeout.connect(self._poll_second)
        self._second_timer.start()

        self._refresh_ports()
        self._on_link_changed()

    # ---------------------------------------------------------- 连接配置
    def _build_conn_card(self) -> Card:
        card = Card("通讯连接",
                    "串口 RS232/USB-CDC 默认 115200-8-N-1（CR+LF）；LAN SCPI 走 TCP 3001（LF）；"
                    "模拟从站无真机也能开发/演示")
        g = QGridLayout()
        g.setSpacing(8)
        g.setVerticalSpacing(10)

        # 单行工具栏式：标签紧贴控件、单元间统一间距、富余空间推到行尾。
        # 模式切换（_on_link_changed）用 setVisible 控制列显隐，HBox 下隐藏后控件自动前移、不残留空洞。
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("接口类型"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(list(LINKS))
        self.cmb_link.setFixedWidth(140)
        self.cmb_link.currentIndexChanged.connect(self._on_link_changed)
        top.addWidget(self.cmb_link)

        self.lbl_addr = QLabel("端口")
        top.addWidget(self.lbl_addr)
        self.cmb_addr = QComboBox()
        self.cmb_addr.setEditable(True)
        self.cmb_addr.setFixedWidth(150)
        top.addWidget(self.cmb_addr)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_baud = QLabel("波特率")
        top.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(list(BAUDS))
        top.addWidget(self.cmb_baud)

        self.lbl_tcp = QLabel("TCP端口")
        top.addWidget(self.lbl_tcp)
        self.sp_tcp = QSpinBox()
        self.sp_tcp.setRange(1, 65535)
        self.sp_tcp.setValue(3001)          # 手册：SCPI 默认 TCP 3001
        self.sp_tcp.setFixedWidth(90)
        top.addWidget(self.sp_tcp)

        top.addSpacing(8)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.clicked.connect(self._on_connect)
        top.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("断开")
        self.btn_disc.clicked.connect(self._on_disconnect)
        self.btn_disc.setEnabled(False)
        top.addWidget(self.btn_disc)
        top.addStretch(1)
        g.addLayout(top, 0, 0)

        self.lbl_idn = QLabel("未连接")
        self.lbl_idn.setObjectName("Muted")
        g.addWidget(self.lbl_idn, 1, 0)
        card.body_lay.addLayout(g)
        return card

    def _on_link_changed(self) -> None:
        idx = self.cmb_link.currentIndex()
        serial_mode = idx == 0
        tcp_mode = idx == 1
        self.lbl_addr.setVisible(idx != 2)
        self.cmb_addr.setVisible(idx != 2)
        self.btn_refresh.setVisible(serial_mode)
        self.lbl_baud.setVisible(serial_mode)
        self.cmb_baud.setVisible(serial_mode)
        self.lbl_addr.setText("端口" if serial_mode else "IP 地址")
        self.lbl_tcp.setVisible(tcp_mode)
        self.sp_tcp.setVisible(tcp_mode)
        if serial_mode:
            self._refresh_ports()
        elif tcp_mode:
            text = self.cmb_addr.currentText().strip()
            if not text or text.upper().startswith("COM") or text.startswith("/dev/"):
                self.cmb_addr.setCurrentText("192.168.1.100")

    def _refresh_ports(self) -> None:
        if self.cmb_link.currentIndex() != 0:
            return
        ports = enumerate_ports()
        cur = self.cmb_addr.currentText().strip()
        self.cmb_addr.blockSignals(True)
        self.cmb_addr.clear()
        self.cmb_addr.addItems(ports or ["COM3"])
        self.cmb_addr.setCurrentText(cur if cur in ports else (ports[0] if ports else cur or "COM3"))
        self.cmb_addr.blockSignals(False)

    # ---------------------------------------------------------- 测量显示
    def _build_disp_card(self) -> Card:
        card = Card("测量显示",
                    "大读数自动换算 SI 词头；+9.9E37 = 超量程/开路/测量未完成（显示 ----，非通信故障）")
        h = QHBoxLayout()
        h.setSpacing(14)
        self.lbl_value = QLabel("----")
        self.lbl_value.setStyleSheet("font-size:36px; font-weight:800; color:#0E7490;")
        h.addWidget(self.lbl_value)
        self.lbl_unit = QLabel("")
        self.lbl_unit.setStyleSheet("font-size:18px; font-weight:700; color:#7C3AED;")
        h.addWidget(self.lbl_unit)
        h.addStretch(1)
        self.lbl_time = QLabel("")
        self.lbl_time.setObjectName("Muted")
        h.addWidget(self.lbl_time)
        card.body_lay.addLayout(h)

        h2 = QHBoxLayout()
        h2.setSpacing(14)
        self.lbl_second = QLabel("副显示：----")
        self.lbl_second.setObjectName("Muted")
        h2.addWidget(self.lbl_second)
        self.lbl_raw = QLabel("原始返回：")
        self.lbl_raw.setObjectName("Muted")
        self.lbl_raw.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h2.addWidget(self.lbl_raw)
        h2.addStretch(1)
        card.body_lay.addLayout(h2)

        self.lbl_stats = QLabel("样本 0")
        self.lbl_stats.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_stats)

        self.chart = TrendChart()
        card.body_lay.addWidget(self.chart)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_single = QPushButton("单次读取")
        self.btn_single.clicked.connect(self.single_read)
        row.addWidget(self.btn_single)
        self.btn_run = QPushButton("连续测量")
        self.btn_run.clicked.connect(self.start_measure)
        row.addWidget(self.btn_run)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self.stop_measure)
        row.addWidget(self.btn_stop)
        row.addWidget(QLabel("间隔"))
        self.cmb_interval = QComboBox()
        self.cmb_interval.addItems(list(INTERVALS))
        self.cmb_interval.setCurrentText("500 ms")
        self.cmb_interval.setFixedWidth(90)
        row.addWidget(self.cmb_interval)
        self.btn_rec = QPushButton("开始记录")
        self.btn_rec.clicked.connect(self.toggle_record)
        row.addWidget(self.btn_rec)
        self.btn_export = QPushButton("导出CSV")
        self.btn_export.clicked.connect(self.export_csv)
        row.addWidget(self.btn_export)
        row.addStretch(1)
        self.btn_chart_clr = QPushButton("清曲线")
        self.btn_chart_clr.clicked.connect(self.chart.clear)
        row.addWidget(self.btn_chart_clr)
        card.body_lay.addLayout(row)
        return card

    # ---------------------------------------------------------- 测量设置
    def _build_setup_card(self) -> Card:
        card = Card("测量设置",
                    "12 种测量功能（第一显示）；量程/速率/副显示/相对值按手册指令集下发")
        g = QGridLayout()
        g.setSpacing(8)
        self._func_btns = {}
        for i, key in enumerate(scpi.FUNC_ORDER):
            spec = scpi.FUNCS[key]
            b = QPushButton(spec.label)
            b.setToolTip(f"CONF:{spec.conf}　单位 {spec.unit}")
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, k=key: self.select_func(k))
            self._func_btns[key] = b
            g.addWidget(b, i // 6, i % 6)
        for c in range(6):
            g.setColumnStretch(c, 1)   # 功能按钮列均分拉伸，填满卡宽不留空旷
        card.body_lay.addLayout(g)

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(QLabel("量程"))
        self.cmb_range = QComboBox()
        self.cmb_range.setMinimumWidth(130)
        r1.addWidget(self.cmb_range)
        r1.addWidget(QLabel("速率"))
        self.cmb_nplc = QComboBox()
        for val, desc in scpi.NPLC_CHOICES:
            self.cmb_nplc.addItem(desc, val)
        self.cmb_nplc.setCurrentIndex(2)   # 默认 1 PLC（手册默认档）
        self.cmb_nplc.setMinimumWidth(210)
        r1.addWidget(self.cmb_nplc)
        r1.addStretch(1)
        self.lbl_func = QLabel("当前功能：直流电压")
        self.lbl_func.setObjectName("Muted")
        r1.addWidget(self.lbl_func)
        card.body_lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        self.lbl_ttype = QLabel("热电偶")
        r2.addWidget(self.lbl_ttype)
        self.cmb_ttype = QComboBox()
        self.cmb_ttype.addItems(list(scpi.TEMP_TYPES))
        self.cmb_ttype.setFixedWidth(70)
        r2.addWidget(self.cmb_ttype)
        self.lbl_tunit = QLabel("温度单位")
        r2.addWidget(self.lbl_tunit)
        self.cmb_tunit = QComboBox()
        for code, name in scpi.TEMP_UNITS:
            self.cmb_tunit.addItem(name, code)
        self.cmb_tunit.setFixedWidth(80)
        r2.addWidget(self.cmb_tunit)
        r2.addWidget(QLabel("副显示"))
        self.cmb_second = QComboBox()
        for cmd, name in scpi.SECOND_FUNCS:
            self.cmb_second.addItem(name, cmd)
        r2.addWidget(self.cmb_second)
        r2.addStretch(1)
        card.body_lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(8)
        self.btn_apply = QPushButton("应用测量设置")
        self.btn_apply.clicked.connect(lambda: self.apply_settings(False))
        r3.addWidget(self.btn_apply)
        self.btn_rel_on = QPushButton("相对值清零")
        self.btn_rel_on.clicked.connect(self.zero_relative)
        r3.addWidget(self.btn_rel_on)
        self.btn_rel_off = QPushButton("关闭相对值")
        self.btn_rel_off.clicked.connect(self.clear_relative)
        r3.addWidget(self.btn_rel_off)
        self.btn_autozero = QPushButton("自动调零")
        self.btn_autozero.clicked.connect(self.autozero)
        r3.addWidget(self.btn_autozero)
        r3.addStretch(1)
        card.body_lay.addLayout(r3)

        self._fill_ranges()
        return card

    def _fill_ranges(self) -> None:
        spec = scpi.FUNCS[self._func_key]
        self.cmb_range.clear()
        if spec.has_range:
            self.cmb_range.addItem("自动量程", None)
            for v in spec.ranges:
                self.cmb_range.addItem(scpi.range_label(v), v)
            self.cmb_range.setEnabled(True)
        else:
            self.cmb_range.addItem("（该功能无量程设置）", None)
            self.cmb_range.setEnabled(False)
        self.cmb_nplc.setEnabled(spec.has_nplc)
        is_temp = self._func_key == "TEMP"
        self.lbl_ttype.setVisible(is_temp)
        self.cmb_ttype.setVisible(is_temp)
        self.lbl_tunit.setVisible(is_temp)
        self.cmb_tunit.setVisible(is_temp)

    # ---------------------------------------------------------- 设备控制
    def _build_dev_card(self) -> Card:
        card = Card("设备控制",
                    "设备指令在通讯日志留痕；蜂鸣/显示文字/远程锁定执行后自动补 SYST:ERR? 自检")
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        b = QPushButton("蜂鸣一声")
        b.clicked.connect(self.do_beep)
        r1.addWidget(b)
        self.ed_disp_text = QLineEdit()
        self.ed_disp_text.setPlaceholderText("仪器屏幕显示文字（≤40 字符）")
        r1.addWidget(self.ed_disp_text, 1)
        b = QPushButton("显示文字")
        b.clicked.connect(self.do_display_text)
        r1.addWidget(b)
        b = QPushButton("清除文字")
        b.clicked.connect(self.do_display_clear)
        r1.addWidget(b)
        card.body_lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        b = QPushButton("远程锁定")
        b.clicked.connect(self.do_remote)
        r2.addWidget(b)
        b = QPushButton("返回本地")
        b.clicked.connect(self.do_local)
        r2.addWidget(b)
        b = QPushButton("屏幕截图")
        b.clicked.connect(self.do_screenshot)
        r2.addWidget(b)
        b = QPushButton("复位")
        b.clicked.connect(self.do_reset)
        r2.addWidget(b)
        b = QPushButton("故障查询")     # 框架「故障代码查询」自动点它
        b.clicked.connect(self.do_check_error)
        r2.addWidget(b)
        r2.addStretch(1)
        self.lbl_dev = QLabel("")
        self.lbl_dev.setObjectName("Muted")
        r2.addWidget(self.lbl_dev)
        card.body_lay.addLayout(r2)
        return card

    # ---------------------------------------------------------- 通讯日志
    def _build_log_card(self) -> Card:
        card = Card("通讯日志",
                    "TX/RX 报文与语义事件；SCPI 透传以 ? 结尾自动读响应")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.ed_cmd = QLineEdit()
        self.ed_cmd.setPlaceholderText("SCPI 透传，如 *IDN? 或 CONF:VOLT:DC")
        self.ed_cmd.returnPressed.connect(self.send_console)
        row.addWidget(self.ed_cmd, 1)
        b = QPushButton("发送")
        b.clicked.connect(self.send_console)
        row.addWidget(b)
        row.addStretch(1)
        b = QPushButton("保存日志")
        b.clicked.connect(self.save_log)
        row.addWidget(b)
        b = QPushButton("清空")
        b.clicked.connect(lambda: self.txt_log.clear())
        row.addWidget(b)
        card.body_lay.addLayout(row)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("font-family:Consolas;")
        self.txt_log.setMinimumHeight(110)
        self.txt_log.setMaximumBlockCount(3000)   # 防日志无限增长
        card.body_lay.addWidget(self.txt_log)
        return card

    # ---------------------------------------------------------- 工具
    def _log(self, tag: str, text: str) -> None:
        self.txt_log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {tag} {text}")

    def _in_thread(self, fn) -> None:
        """投递后台任务到常驻工作线程（串行执行，替代短命线程）。"""
        self._jobs.put(fn)

    def _worker_loop(self) -> None:
        """常驻工作线程：串行消费任务队列，直到 shutdown。"""
        while not self._worker_stop.is_set():
            try:
                fn = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                fn()
            except Exception:  # noqa: BLE001
                # 任务内部已各自 try/except，这里兜底防止异常杀死工作线程
                pass
            finally:
                self._jobs.task_done()

    def _takeover(self) -> None:
        """任何主动下发都会让仪器回到远程态，同步清掉「已交还本地」标志。"""
        self._local_mode = False

    def _require_conn(self) -> bool:
        if not self.meter.connected:
            QMessageBox.warning(self, "提示", "请先连接设备")
            return False
        return True

    def _write(self, cmd: str) -> None:
        self.meter.write(cmd)
        self._events.put(("log", ">>", cmd))

    def _query(self, cmd: str, timeout: float = 2.0) -> str:
        self._events.put(("log", ">>", cmd))
        resp = self.meter.query(cmd, timeout)
        self._events.put(("log", "<<", resp))
        return resp

    # ---------------------------------------------------------- 连接
    def _on_connect(self) -> None:
        if self.meter.connected or self._connecting:
            return
        idx = self.cmb_link.currentIndex()
        addr = self.cmb_addr.currentText().strip()
        if idx == 0:
            kind, kw = "serial", dict(port=addr, baud=int(self.cmb_baud.currentText()))
        elif idx == 1:
            host = addr.split(":")[0].strip() or "192.168.1.100"
            kind, kw = "tcp", dict(host=host, port=self.sp_tcp.value())
        else:
            kind, kw = "sim", dict(model="GDM9061")
        self._connecting = True
        self.btn_conn.setEnabled(False)
        self.lbl_idn.setText("正在连接…")

        def job():
            try:
                info = self.meter.open(kind, **kw)
                self._events.put(("connected", info))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("connect_failed", str(exc)))

        self._log("INFO", f"正在连接：{LINKS[idx]}{'' if idx == 2 else ' · ' + addr}")
        self._in_thread(job)

    def _on_disconnect(self) -> None:
        self._stop_measure()
        try:
            self.meter.close()
        except Exception:  # noqa: BLE001
            pass
        self._local_mode = False
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_disc.setEnabled(False)
        self.lbl_idn.setText("未连接")
        self.lbl_dev.setText("")
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)   # 链路断开 = 通讯中断
        self._log("INFO", "已断开连接")

    def _on_connected(self, info: dict) -> None:
        self._connecting = False
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("已连接")
        self.btn_conn.setObjectName("btnConnected")
        self.btn_disc.setEnabled(True)
        self.lbl_idn.setText(
            f"{info.get('vendor', '')} {info.get('model', '')}　"
            f"SN {info.get('serial', '')}　FW {info.get('firmware', '')}　"
            f"通道 {info.get('channel', '')}")
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # *IDN? 应答到达 = 与设备真正建立通讯
        self._log("INFO", f"已连接 {info.get('raw', '')}")
        self.apply_settings(True)

    # ---------------------------------------------------------- 测量设置下发
    def select_func(self, key: str) -> None:
        self._func_key = key
        self._fill_ranges()
        self.lbl_func.setText(f"当前功能：{scpi.FUNCS[key].label}")
        self._stat = dict(n=0, vmin=None, vmax=None, total=0.0)
        self._update_stats()
        self.chart.clear()
        if self.meter.connected:
            self._log("INFO", f"切换功能 → {scpi.FUNCS[key].label}")
            self.apply_settings(True)

    def apply_settings(self, auto: bool = False) -> None:
        if not self.meter.connected:
            if not auto:
                QMessageBox.warning(self, "提示", "请先连接设备")
            return
        self._takeover()
        key = self._func_key
        spec = scpi.FUNCS[key]
        range_value = self.cmb_range.currentData() if spec.has_range else None
        nplc = self.cmb_nplc.currentData() if spec.has_nplc else None
        temp_type = self.cmb_ttype.currentText()
        temp_unit = self.cmb_tunit.currentData()
        second = self.cmb_second.currentData()
        range_text = self.cmb_range.currentText()   # 工作线程里不再读控件
        nplc_text = self.cmb_nplc.currentText()
        restart = self.poller is not None and self.poller.running

        def job():
            try:
                cmds = scpi.cmd_configure(key, range_value, nplc, temp_type, temp_unit)
                cmds += scpi.cmd_second_display(second)
                for c in cmds:
                    self._write(c)
                self._events.put(("note", f"测量设置已下发：{spec.label} / "
                                          f"{range_text} / {nplc_text}"))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"设置下发失败：{exc}"))
                return
            if restart:
                self._events.put(("restart_poll", None))

        self._in_thread(job)

    # ---------------------------------------------------------- 读数
    def single_read(self) -> None:
        if not self._require_conn():
            return
        self._takeover()
        self._log("INFO", f"单次读取（{scpi.FUNCS[self._func_key].label}）")

        def job():
            try:
                r = self.meter.read_value(self._func_key)
                self._events.put(("reading", r))
            except NoDataError as exc:
                self._events.put(("no_data", str(exc)))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"读取失败：{exc}"))

        self._in_thread(job)

    def start_measure(self) -> None:
        if not self._require_conn():
            return
        if self.poller is not None and self.poller.running:
            return
        self._takeover()
        self._stat = dict(n=0, vmin=None, vmax=None, total=0.0)
        self._update_stats()
        self.chart.clear()
        self._start_poller()
        self.btn_run.setText("测量中")
        self._log("INFO", f"连续测量中 · 间隔 {self.cmb_interval.currentText()}")

    def _start_poller(self) -> None:
        text = self.cmb_interval.currentText()
        num = float(text.split()[0])
        ms = num * (1000.0 if text.endswith("s") and not text.endswith("ms") else 1.0)
        interval = max(0.05, ms / 1000.0)
        self.poller = Poller(self.meter, interval, self._func_key,
                             on_sample=lambda r: self._events.put(("reading", r)),
                             on_error=self._on_poll_error)
        self.poller.start()

    def stop_measure(self) -> None:
        self._stop_measure()
        self._log("INFO", "已停止连续测量")

    def _stop_measure(self) -> None:
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
        self.btn_run.setText("连续测量")

    def _on_poll_error(self, exc) -> None:
        """轮询线程回调（非主线程，只能往队列里塞事件）。"""
        if isinstance(exc, NoDataError):
            self._events.put(("no_data", str(exc)))
        else:
            self._events.put(("poll_error", str(exc)))

    def _poll_second(self) -> None:
        """副显示低频查询 DATA2:LAST?（仅连接且启用副显示时；本地模式不自动下发）。"""
        if (self._second_busy or self._local_mode
                or not self.meter.connected
                or self.cmb_second.currentData() == "NON"):
            return
        self._second_busy = True

        def job():
            try:
                v = self.meter.read_second()
                self._events.put(("second", v))
            except Exception:  # noqa: BLE001
                self._events.put(("second", None))
            finally:
                self._second_busy = False

        self._in_thread(job)

    # ---------------------------------------------------------- 相对值
    def zero_relative(self) -> None:
        if not self._require_conn():
            return
        key = self._func_key
        if not scpi.FUNCS[key].has_nplc:
            QMessageBox.information(self, "提示",
                                    f"{scpi.FUNCS[key].label} 不支持相对值（手册未提供 NULL 指令）")
            return
        self._takeover()

        def job():
            try:
                r = self.meter.read_value(key)
                self.meter.relative_on(key, r.value)
                self._events.put(("note", f"已把 {scpi.format_si(r.value, r.unit)} 设为相对零点"))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"设置相对值失败：{exc}"))

        self._in_thread(job)

    def clear_relative(self) -> None:
        if not self._require_conn():
            return
        self._takeover()
        key = self._func_key

        def job():
            try:
                self.meter.relative_off(key)
                self._events.put(("note", "已关闭相对值"))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"关闭相对值失败：{exc}"))

        self._in_thread(job)

    def autozero(self) -> None:
        if not self._require_conn():
            return
        self._takeover()
        key = self._func_key

        def job():
            try:
                self.meter.autozero_once(key)
                self._events.put(("note", "已执行一次自动调零（ZERO:AUTO ONCE）"))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"调零失败：{exc}"))

        self._in_thread(job)

    # ---------------------------------------------------------- 设备控制
    def _dev_action(self, fn, echo: str, check_error: bool = False) -> None:
        """后台执行一条设备命令，结果写入通讯日志；可选执行后补 SYST:ERR? 自检。"""
        if not self._require_conn():
            return
        self._takeover()

        def job():
            self._events.put(("log", ">>", echo))
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"操作失败：{exc}"))
                return
            if check_error:
                try:
                    raw = self.meter.check_error()
                except Exception as exc:  # noqa: BLE001
                    self._events.put(("note", f"SYST:ERR? 自检失败：{exc}"))
                    return
                self._events.put(("log", "<<", raw or '+0,"No error"'))
                if raw:
                    self._events.put(("dev_err", raw))
                else:
                    self._events.put(("note", "操作完成，设备无报错"))
            else:
                self._events.put(("note", "操作完成"))

        self._in_thread(job)

    def do_beep(self) -> None:
        self._dev_action(self.meter.beep, "SYST:BEEP:IMM", check_error=True)

    def do_display_text(self) -> None:
        text = self.ed_disp_text.text().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入要显示的文字")
            return
        safe = text.replace('"', "'")[:40]
        self._dev_action(lambda: self.meter.display_text(text),
                         f'DISP:TEXT:DATA "{safe}"', check_error=True)

    def do_display_clear(self) -> None:
        self._dev_action(self.meter.display_text_clear, "DISP:TEXT:CLE", check_error=True)

    def do_remote(self) -> None:
        self._dev_action(self.meter.remote, "SYST:REM")
        self.lbl_dev.setText("状态：<远程锁定中>")

    def do_local(self) -> None:
        """返回本地：先停连续测量再发 SYST:LOC，之后不再自动下发任何指令。

        SCPI 规定收到任何指令都会重新进入远程态——若轮询还在每 200ms 发 READ?，
        SYST:LOC 会被立刻顶回远程，面板看着像「没反应」。
        """
        if not self._require_conn():
            return
        self._stop_measure()
        self._log("INFO", "返回本地：已停连续测量，随后不再自动下发指令")
        self._dev_action(self.meter.local, "SYST:LOC")
        # 注意在 _dev_action 之后置位：_dev_action 内部的 _takeover() 会清该标志
        self._local_mode = True
        self.lbl_dev.setText("状态：<本地面板>（重新点单次/连续测量或应用设置即重新接管）")

    def do_reset(self) -> None:
        if QMessageBox.question(self, "复位确认",
                                "将下发 *RST + *CLS，仪器设置恢复默认。\n确定复位？") != QMessageBox.Yes:
            return

        def fn():
            self.meter.reset()
        self._dev_action(fn, "*RST / *CLS")

    def do_check_error(self) -> None:
        if not self._require_conn():
            return
        self._takeover()

        def job():
            try:
                raw = self.meter.check_error()
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"故障查询失败：{exc}"))
                return
            self._events.put(("log", "<<", raw or '+0,"No error"'))
            self._events.put(("dev_err" if raw else "note",
                              raw if raw else "SYST:ERR? → 无错误"))

        self._in_thread(job)

    def do_screenshot(self) -> None:
        if not self._require_conn():
            return
        path, ok = QFileDialog.getSaveFileName(self, "保存仪器屏幕截图",
                                               f"gdm906x_screen_{time.strftime('%H%M%S')}.bmp",
                                               "BMP 图像 (*.bmp)")
        if not ok or not path:
            return
        self._takeover()

        def job():
            self._events.put(("log", ">>", "HCOP:SDUM:DATA?"))
            try:
                self.meter.screenshot(path)
                self._events.put(("note", f"屏幕截图已保存：{path}"))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"截图失败：{exc}"))

        self._in_thread(job)

    # ---------------------------------------------------------- SCPI 透传
    def send_console(self) -> None:
        cmd = self.ed_cmd.text().strip()
        if not cmd:
            return
        if not self._require_conn():
            return
        self._takeover()

        def job():
            try:
                if cmd.endswith("?"):
                    self._query(cmd, timeout=5.0)
                    self._events.put(("mark_ok", None))
                else:
                    self._write(cmd)
            except Exception as exc:  # noqa: BLE001
                self._events.put(("note", f"指令执行失败：{exc}"))

        self._in_thread(job)

    # ---------------------------------------------------------- 记录导出
    def toggle_record(self) -> None:
        self._recording = not self._recording
        self.btn_rec.setText("停止记录" if self._recording else "开始记录")
        self._log("INFO", "开始记录数据" if self._recording else
                  f"停止记录，共 {len(self._records)} 条")

    def export_csv(self) -> None:
        if not self._records:
            QMessageBox.information(self, "提示", "暂无记录数据（先「开始记录」再测量）")
            return
        path, ok = QFileDialog.getSaveFileName(self, "导出记录 CSV",
                                               f"gdm906x_record_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                               "CSV 文件 (*.csv)")
        if not ok or not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write("时间,功能,数值,单位\r\n")
                for row in self._records:
                    fh.write(",".join(str(x) for x in row) + "\r\n")
            self._log("INFO", f"记录已导出：{path}（{len(self._records)} 条）")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))

    def save_log(self) -> None:
        path, ok = QFileDialog.getSaveFileName(self, "保存通讯日志",
                                               f"gdm906x_log_{time.strftime('%Y%m%d_%H%M%S')}.txt",
                                               "文本文件 (*.txt)")
        if not ok or not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.txt_log.toPlainText())
            self._log("INFO", f"日志已保存：{path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(exc))

    # ---------------------------------------------------------- 事件泵
    def _pump(self) -> None:
        while True:
            try:
                ev = self._events.get_nowait()
            except queue.Empty:
                return
            kind = ev[0]
            if kind == "connected":
                self._on_connected(ev[1])
            elif kind == "connect_failed":
                self._connecting = False
                self.btn_conn.setEnabled(True)
                self.lbl_idn.setText("未连接")
                self._log("[错误]", f"连接失败：{ev[1]}")
            elif kind == "reading":
                self._show_reading(ev[1])
            elif kind == "second":
                self.lbl_second.setText(
                    "副显示：" + (scpi.format_si(ev[1], "") if ev[1] is not None else "----"))
            elif kind == "no_data":
                self._show_no_data(ev[1])
            elif kind == "poll_error":
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)   # 轮询失败 = 通讯中断
                self._log("[错误]", f"轮询异常：{ev[1]}")
            elif kind == "log":
                self._log(ev[1], ev[2])
            elif kind == "note":
                self._log("INFO", ev[1])
            elif kind == "dev_err":
                self._log("!!", f"设备报错 {ev[1]}")
                QMessageBox.warning(self, "设备报错", f"设备返回错误：\n{ev[1]}")
            elif kind == "restart_poll":
                if self.poller is not None and self.poller.running:
                    self.poller.stop()
                    self._start_poller()
            elif kind == "mark_ok":
                from instrument_hub.comm_state import mark_ok
                mark_ok(self)   # 查询应答到达 = 真实通讯

    def _show_reading(self, r) -> None:
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 有效读数到达 = 通讯真正建立
        text = scpi.format_si(r.value, r.unit)
        num, _, unit = text.rpartition(" ")
        self.lbl_value.setText(num or text)
        self.lbl_unit.setText(unit)
        self.lbl_time.setText(time.strftime("%H:%M:%S"))
        self.lbl_raw.setText(f"原始返回：{(r.raw or '')[:60]}")
        self.chart.push(r.value)
        st = self._stat
        st["n"] += 1
        st["total"] += r.value
        st["vmin"] = r.value if st["vmin"] is None else min(st["vmin"], r.value)
        st["vmax"] = r.value if st["vmax"] is None else max(st["vmax"], r.value)
        self._update_stats()
        if self._recording:
            self._records.append((time.strftime("%H:%M:%S"), scpi.FUNCS[r.func].label
                                  if r.func in scpi.FUNCS else r.func,
                                  f"{r.value:.8g}", r.unit))

    def _update_stats(self) -> None:
        st = self._stat
        if not st["n"]:
            self.lbl_stats.setText("样本 0")
            return
        self.lbl_stats.setText(
            f"样本 {st['n']}　最大 {scpi.format_si(st['vmax'], '', 5)}　"
            f"最小 {scpi.format_si(st['vmin'], '', 5)}　"
            f"平均 {scpi.format_si(st['total'] / st['n'], '', 5)}　"
            f"峰峰值 {scpi.format_si(st['vmax'] - st['vmin'], '', 5)}")

    def _show_no_data(self, reason: str) -> None:
        """超量程 / 开路不是通信故障：大屏显示 ----，橙色提示，不污染通讯状态。"""
        self.lbl_value.setText("----")
        self.lbl_unit.setText("")
        self.lbl_raw.setText("原始返回：+9.9E37")
        self._log("WARN", f"无读数：{reason}（仪器返回 +9.9E37）")

    # ---------------------------------------------------------- 退出清理
    def shutdown(self) -> None:
        """退出/卸载：停轮询、停定时器、断开连接、回收线程（安全闭环）。"""
        self._timer.stop()
        self._second_timer.stop()
        self._stop_measure()
        try:
            self.meter.close()
        except Exception:  # noqa: BLE001
            pass
        # 停常驻工作线程（daemon 线程，正常路径显式回收更稳妥）
        self._worker_stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=1.0)
        from instrument_hub.comm_state import mark_lost
        mark_lost(self)
