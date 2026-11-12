# -*- coding: utf-8 -*-
"""MFG-2000 信号发生器上位机 · 融合版界面（FusionHub 风格）。

复用原上位机纯逻辑层（命令表/分帧/协议栈/传输/模拟从站/语义接口，零改动），
界面按整体 UI 风格重建：
- 控件由命令表（单一事实源）绑定生成，界面只消费 Instrument 语义化接口；
- 每通道波形预览（示波屏风格，按当前参数实时绘制）；
- 刷新走工作线程 + Qt 信号，轮询下限 0.5s，防收发队列堆积假死。
"""
import queue

from PyQt5.QtCore import QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QScrollArea,
                             QSpinBox, QSplitter, QTabWidget, QVBoxLayout,
                             QWidget)

from instrument_hub.widgets import Card

from .core.mfg_host.command_table import ParamError, load_table
from .core.mfg_host.errors import ProtocolError
from .core.mfg_host.instrument import Instrument
from .core.mfg_host.simulator import MfgSimulator
from .core.mfg_host.stack import ScpiStack
from .core.mfg_host.transport import (LoopbackTransport, SerialTransport,
                                      TcpTransport, TransportError)

POLL_MIN_INTERVAL = 0.5   # 界面刷新下限(s)：不得高于串口吞吐

WAVE_ZH = {
    "SIN": "正弦", "SQU": "方波", "TRI": "三角波", "RAMP": "斜波",
    "UPRAMP": "上斜波", "DNRAMP": "下斜波", "PULS": "脉冲",
    "NOIS": "噪声", "USER": "任意波",
}
ZH_WAVE = {v: k for k, v in WAVE_ZH.items()}

CH_COLORS = ("#22D3EE", "#A78BFA", "#F472B6")


def _fmt_num(v) -> str:
    """纯十进制显示，禁止科学计数法(5e-05 -> 0.00005)；波形枚举显示中文。"""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        s = f"{v:.12f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-") else "0"
    if isinstance(v, str) and v in WAVE_ZH:
        return WAVE_ZH[v]
    return str(v)


class WavePreview(QWidget):
    """波形预览：示波屏风格，按当前参数实时绘制（功能与原上位机一致）。"""

    def __init__(self, ch: int, parent=None):
        super().__init__(parent)
        self.ch = ch
        self.color = CH_COLORS[(ch - 1) % len(CH_COLORS)]
        self.setMinimumHeight(170)
        self._p = {"func": "SIN", "freq": 1000.0, "ampl": 0.1, "offset": 0.0,
                   "duty": 50.0, "symm": 50.0, "pw": 5e-5}

    def set_params(self, **kw):
        self._p.update(kw)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#0B1220"))

        grid = QPen(QColor("#1E293B"), 1)
        p.setPen(grid)
        for i in range(1, 10):
            x = w * i / 10.0
            p.drawLine(int(x), 0, int(x), h)
        for i in range(1, 4):
            y = h * i / 4.0
            p.drawLine(0, int(y), w, int(y))
        p.setPen(QPen(QColor("#334155"), 1, Qt.DashLine))
        p.drawLine(0, h // 2, w, h // 2)

        func = str(self._p.get("func", "SIN")).upper()
        freq = float(self._p.get("freq", 1000.0) or 1000.0)
        ampl = float(self._p.get("ampl", 0.1) or 0.1)
        offset = float(self._p.get("offset", 0.0) or 0.0)
        duty = float(self._p.get("duty", 50.0) or 50.0) / 100.0
        symm = float(self._p.get("symm", 50.0) or 50.0) / 100.0
        pw = float(self._p.get("pw", 5e-5) or 5e-5)
        period = 1.0 / freq if freq > 0 else 1.0
        pw_frac = min(max(pw / period, 0.02), 0.98)
        symm_c = max(0.02, min(0.98, symm))

        def shape(t: float) -> float:
            q = (t * 2.0) % 1.0
            if func == "SQU":
                return 1.0 if q < duty else -1.0
            if func in ("RAMP", "TRI", "UPRAMP", "DNRAMP"):
                return ((q / symm_c) if q < symm_c
                        else 1.0 - (q - symm_c) / (1.0 - symm_c))
            if func == "PULS":
                return 1.0 if q < pw_frac else -1.0
            if func == "NOIS":
                import random
                return random.uniform(-1.0, 1.0)
            import math
            return math.sin(2.0 * 3.141592653589793 * q)

        span = max(abs(offset + ampl / 2.0), abs(offset - ampl / 2.0), 1e-9) * 1.25
        poly = QPolygonF()
        n = max(2, w)
        for i in range(n + 1):
            t = i / n
            v = offset + (ampl / 2.0) * shape(t)
            poly.append(QPointF(t * w, h / 2.0 - (v / span) * (h / 2.0 - 8)))
        p.setPen(QPen(QColor(self.color), 2))
        p.drawPolyline(poly)

        p.setPen(QColor(self.color))
        p.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        p.drawText(10, 18, WAVE_ZH.get(func, func))
        p.end()


class Worker(QThread):
    """阻塞式仪器操作的单线程执行器：UI 入队，结果经信号回 UI 线程。"""

    sig_result = pyqtSignal(object, object, object)   # ctx, result, error

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = queue.Queue()
        self._running = False
        self._busy = False

    def submit(self, fn, ctx=None):
        self._q.put((fn, ctx))

    def clear(self):
        """丢弃未执行的 job（断开/重连时防旧命令堆积拖慢与迟到报错）。"""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def run(self):
        self._running = True
        while self._running:
            try:
                fn, ctx = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            if fn is None:
                break
            self._busy = True
            try:
                self.sig_result.emit(ctx, fn(), None)
            except Exception as e:  # noqa: BLE001
                self.sig_result.emit(ctx, None, e)
            finally:
                self._busy = False

    def stop(self):
        self._running = False
        self._q.put((None, None))
        self.wait(3000)

    def idle(self) -> bool:
        return self._q.empty() and not self._busy   # 执行中也算忙：防轮询 job 堆积


class Mfg2000Page(QWidget):
    """MFG-2000 控制：连接 → 通道输出/调制/扫描/脉冲串/计频/系统 + 收发日志。"""

    sig_traffic = pyqtSignal(str, str)   # TX/RX 帧日志（协议栈线程→UI，QueuedConnection）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = load_table()
        self.instrument: Instrument = None
        self._sim = None
        self.worker = Worker(self)
        self.worker.sig_result.connect(self._on_result)
        self.sig_traffic.connect(self._on_traffic_ui)   # 帧日志：工作线程 emit → UI 槽
        self.worker.start()
        self._poll_fail = 0

        self._cells = {}       # key -> (widget, kind, spec, ch)
        self._waves = {}       # ch -> WavePreview
        self._wave_info = {}   # ch -> QLabel

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        tv.addWidget(self._build_conn_card())
        tv.addWidget(self._build_tabs())
        split.addWidget(top)
        split.addWidget(self._build_log_group())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        split.setSizes([520, 150])   # 一屏内可见：连接+主体+日志免滚动
        root.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll_tick)
        self._timer.start()
        self._on_kind_changed(0)   # 按默认串口落定预填（自动填检测到的真实口）
        self.table.apply_series("MFG")   # 系列默认 MFG-2000（与下拉一致）

    # ---------------------------------------------------------- 连接栏
    def _build_conn_card(self) -> Card:
        card = Card("连接",
                    "GW INSTEK MFG-2000 系列 · SCPI 1994 / IEEE 488.2 · "
                    "命令表驱动（单一事实源）· 下发后自动回读校验")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(QLabel("连接方式"))
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItems(["串口", "TCP", "模拟从站"])   # 默认串口，模拟从站保留可选
        self.cmb_kind.setFixedWidth(104)
        self.cmb_kind.currentIndexChanged.connect(self._on_kind_changed)
        h.addWidget(self.cmb_kind)

        h.addWidget(QLabel("系列"))
        self.cmb_series = QComboBox()
        self.cmb_series.addItems(["MFG-2000 系列", "AFG-2000 系列"])
        self.cmb_series.setFixedWidth(130)
        self.cmb_series.setToolTip("AFG-2000 系列（AFG-2225）按手册收紧参数范围：25MHz / 1mVpp~10Vpp / 脉宽 20ns 起")
        self.cmb_series.currentIndexChanged.connect(self._on_series_changed)
        h.addWidget(self.cmb_series)

        self.lbl_target = QLabel("地址")
        h.addWidget(self.lbl_target)
        self.ed_target = QLineEdit("-")
        self.ed_target.setFixedWidth(140)
        h.addWidget(self.ed_target)

        self.lbl_param = QLabel("端口")
        h.addWidget(self.lbl_param)
        self.ed_param = QLineEdit("-")
        self.ed_param.setFixedWidth(96)
        h.addWidget(self.ed_param)

        self.btn_conn = QPushButton("连接")
        self.btn_conn.clicked.connect(self.toggle_connection)
        h.addWidget(self.btn_conn)

        self.lbl_dot = QLabel("●")
        self.lbl_dot.setStyleSheet("color:#9CA3AF; font-size:16pt;")
        h.addWidget(self.lbl_dot)
        self.lbl_idn = QLabel("未连接")
        self.lbl_idn.setObjectName("Muted")
        h.addWidget(self.lbl_idn)
        h.addStretch(1)

        self.chk_poll = QCheckBox("定时刷新(≥0.5s)")
        self.chk_poll.setChecked(True)
        h.addWidget(self.chk_poll)
        card.body_lay.addLayout(h)
        return card

    _CONN_PRESETS = {
        "模拟从站": (("地址", "-"), ("端口", "-")),
        "串口": (("串口", "COM3"), ("波特率", "115200")),
        "TCP": (("IP 地址", "192.168.1.100"), ("端口", "5025")),
    }

    def _on_kind_changed(self, _idx):
        preset = self._CONN_PRESETS[self.cmb_kind.currentText()]
        (t_lbl, t_def), (p_lbl, p_def) = preset
        known = {d for pair in self._CONN_PRESETS.values() for _, d in pair}
        if self.ed_target.text() in known | {"", "-"}:
            self.ed_target.setText(t_def)
        if self.ed_param.text() in known | {"", "-"}:
            self.ed_param.setText(p_def)
        self.lbl_target.setText(t_lbl)
        self.lbl_param.setText(p_lbl)
        if self.cmb_kind.currentText() == "串口":
            # 串口模式自动填检测到的真实端口（打开/切换即刷新，不靠手输占位）
            from instrument_hub.serial_ports import enumerate_ports
            ports = enumerate_ports()
            cur = self.ed_target.text().strip()
            if ports and cur not in ports and cur.upper().startswith("COM"):
                self.ed_target.setText(ports[0])

    def _on_series_changed(self):
        """系列切换：按单一事实源收紧/放宽参数范围，输入框范围即时同步。"""
        key = "AFG" if "AFG" in self.cmb_series.currentText() else "MFG"
        try:
            label = self.table.apply_series(key)
        except Exception as e:  # noqa: BLE001
            self._log(f"系列切换失败: {e}", "#EF4444")
            return
        for _key, (w, _k, spec, _ch, _g) in self._cells.items():
            p = spec.param or {}
            if hasattr(w, "setRange") and ("min" in p or "max" in p):
                try:
                    w.setRange(p.get("min", w.minimum()), p.get("max", w.maximum()))
                except Exception:  # noqa: BLE001
                    pass
        s = (self.table.meta.get("series") or {}).get(key, {})
        self._log(f"已切换系列：{label}（{s.get('note', '')}）", "#A78BFA")

    # ---------------------------------------------------------- 页签
    def _build_tabs(self) -> QWidget:
        # 左：通道 1/2/3 波形显示；右：参数页签——左右一分为二，免下拉看全部参数
        panel = QSplitter(Qt.Horizontal)
        panel.setChildrenCollapsible(False)
        panel.addWidget(self._build_wave_panel())
        panel.addWidget(self._build_param_tabs())
        panel.setStretchFactor(0, 1)
        panel.setStretchFactor(1, 1)
        panel.setSizes([500, 500])
        return panel

    def _build_wave_panel(self) -> QWidget:
        w = QWidget()
        v = QHBoxLayout(w)   # 三通道横排：整页紧凑，通讯日志免滚动直视
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)
        for ch in self.table.channels:
            box = QGroupBox(f"通道 {ch} 波形")
            bv = QVBoxLayout(box)
            wave = WavePreview(ch)
            self._waves[ch] = wave
            info = QLabel("")
            info.setObjectName("Muted")
            self._wave_info[ch] = info
            bv.addWidget(wave, 1)
            bv.addWidget(info)
            v.addWidget(box, 1)
        return w

    def _build_param_tabs(self) -> QTabWidget:
        self.tabs = QTabWidget()
        groups = {}
        for spec in self.table.commands:
            groups.setdefault(spec.group, []).append(spec)

        self.tabs.addTab(self._build_channel_tab(), "基础输出")
        for group, specs in groups.items():
            if group in ("基础输出", "系统"):
                continue
            self.tabs.addTab(self._build_group_tab(specs), group)

        sys_tab = QWidget()
        sv = QVBoxLayout(sys_tab)
        sv.setContentsMargins(0, 6, 0, 0)
        sv.setSpacing(8)
        body = QWidget()
        gl = QGridLayout(body)
        gl.setSpacing(6)
        self._fill_group(gl, [s for s in self.table.commands
                              if s.group == "系统"], None)
        sv.addWidget(body)
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, fn in (("读错误队列", self._on_read_errors),
                         ("清状态(*CLS)", self._on_clear_status),
                         ("复位(*RST)", self._on_reset),
                         ("返回本地", self._on_local)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        sv.addLayout(row)
        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#EF4444;")
        self.lbl_err.setWordWrap(True)
        sv.addWidget(self.lbl_err)
        sv.addStretch(1)
        self.tabs.addTab(sys_tab, "系统")
        return self.tabs

    def _build_channel_tab(self) -> QWidget:
        sub = QTabWidget()
        base = [s for s in self.table.commands if s.group == "基础输出"]
        for ch in self.table.channels:
            body = QWidget()
            gl = QGridLayout(body)
            gl.setSpacing(6)
            self._fill_group(gl, base, ch)
            sub.addTab(body, f"源 {ch}")
        return sub

    def _build_group_tab(self, specs) -> QWidget:
        """调制/扫描/脉冲串等模板命令组：通道选择 + 参数行。"""
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(8)
        if any(s.template for s in specs):
            row = QHBoxLayout()
            row.addWidget(QLabel("通道"))
            cmb = QComboBox()
            for ch in self.table.channels:
                cmb.addItem(str(ch))
            cmb.setFixedWidth(80)
            row.addWidget(cmb)
            row.addStretch(1)
            v.addLayout(row)
            self._group_ch = getattr(self, "_group_ch", {})
            self._group_ch[id(wrap)] = cmb
            ch_getter = lambda: int(cmb.currentText())  # noqa: E731
        else:
            ch_getter = lambda: None  # noqa: E731

        body = QWidget()
        gl = QGridLayout(body)
        gl.setSpacing(6)
        self._fill_group(gl, specs, None, ch_getter)
        v.addWidget(body)

        btns = QHBoxLayout()
        b_all = QPushButton("本页全部读回")
        b_all.clicked.connect(lambda: self._on_read_group(specs, ch_getter))
        btns.addWidget(b_all)
        btns.addStretch(1)
        v.addLayout(btns)
        v.addStretch(1)
        return wrap

    # ---------------------------------------------------------- 参数行
    def _fill_group(self, gl: QGridLayout, specs, ch, ch_getter=None):
        heads = ("参数", "值", "范围/单位", "", "", "备注")
        for c, t in enumerate(heads):
            lb = QLabel(t)
            lb.setObjectName("Muted")
            lb.setMaximumHeight(24)   # 限高防表头行吸收多余空间（行高膨胀挤出空白）
            gl.addWidget(lb, 0, c)
        gl.setColumnStretch(5, 1)   # 备注列吃富余宽度，按钮列不被拉变形
        for r, spec in enumerate(specs, start=1):
            key = f"{spec.id}:{ch if ch is not None else 'grp'}"
            gl.addWidget(QLabel(spec.name_cn + (f" (CH{ch})" if ch else "")),
                         r, 0)
            p = spec.param or {}
            widget = (spec.ui or {}).get("widget", "spinbox")
            if widget == "combo" or p.get("choices") or p.get("choices_num"):
                values = p.get("choices") or p.get("choices_num") or []
                w = QComboBox()
                w.addItems([_fmt_num(v) for v in values])
                w.setFixedWidth(120)
                kind = "combo"
            elif widget == "switch":
                w = QCheckBox()
                w.setChecked(bool(p.get("default", False)))
                kind = "switch"
            elif widget == "readonly":
                w = QLabel("--")
                w.setStyleSheet("font-family:Consolas; color:#1f7ae0;"
                                " font-weight:700;")
                w.setFixedWidth(150)
                kind = "readonly"
            else:
                w = QLineEdit(_fmt_num(p.get("default", "")))
                w.setFixedWidth(150)
                kind = "entry"
            gl.addWidget(w, r, 1)
            self._cells[key] = (w, kind, spec, ch, ch_getter)

            hint = self._param_hint(spec)
            lb = QLabel(hint)
            lb.setObjectName("Muted")
            gl.addWidget(lb, r, 2)

            if spec.writable:
                b_wr = QPushButton("下发")
                b_wr.setFixedWidth(72)   # 定宽防列拉伸把按钮撑变形
                b_wr.clicked.connect(
                    lambda _c, k=key: self._on_write(k))
                gl.addWidget(b_wr, r, 3)
            if spec.readable:
                b_rd = QPushButton("读回")
                b_rd.setFixedWidth(72)
                b_rd.clicked.connect(
                    lambda _c, k=key: self._on_read(k))
                gl.addWidget(b_rd, r, 4)
            note = QLabel((spec.notes or "")[:40])
            note.setObjectName("Muted")
            gl.addWidget(note, r, 5)

            if ch is not None:
                w.valueChanged.connect(  # noqa: attr-defined
                    lambda _v, c=ch: self._refresh_wave(c)) \
                    if hasattr(w, "valueChanged") else None
                if isinstance(w, QComboBox):
                    w.currentIndexChanged.connect(
                        lambda _i, c=ch: self._refresh_wave(c))
                elif isinstance(w, QLineEdit):
                    w.textChanged.connect(
                        lambda _t, c=ch: self._refresh_wave(c))

    @staticmethod
    def _param_hint(spec) -> str:
        p = spec.param or spec.returns or {}
        parts = []
        unit = p.get("unit")
        if unit:
            parts.append(f"[{unit}]")
        lo, hi = p.get("min"), p.get("max")
        if lo is not None or hi is not None:
            if p.get("range_tbd"):
                parts.append("范围待定")
            else:
                lo_s = "" if lo is None else _fmt_num(lo)
                hi_s = "" if hi is None else _fmt_num(hi)
                parts.append(f"{lo_s}~{hi_s}")
        if p.get("special"):
            parts.append("或 " + "/".join(str(s) for s in p["special"]))
        return "  ".join(parts)

    # ---------------------------------------------------------- 值编解码
    def _get_value(self, key):
        w, kind, spec, _ch, _g = self._cells[key]
        if kind == "combo":
            return ZH_WAVE.get(w.currentText(), w.currentText())
        if kind == "switch":
            return w.isChecked()
        return w.text()

    def _set_value(self, key, value):
        w, kind, _spec, _ch, _g = self._cells[key]
        if kind == "combo":
            text = _fmt_num(value)
            idx = w.findText(text)
            if idx >= 0:
                w.setCurrentIndex(idx)
        elif kind == "switch":
            w.setChecked(bool(value))
        elif kind == "readonly":
            w.setText(_fmt_num(value))
        else:
            w.setText(_fmt_num(value))

    def _ch_of(self, key):
        _w, _k, _s, ch, getter = self._cells[key]
        return ch if ch is not None else (getter() if getter else None)

    # ---------------------------------------------------------- 操作
    def _require(self):
        if self.instrument is None:
            QMessageBox.warning(self, "未连接", "请先建立连接")
            return None
        return self.instrument

    def _on_write(self, key):
        ins = self._require()
        if ins is None:
            return
        _w, _k, spec, _ch, _g = self._cells[key]
        ch = self._ch_of(key)
        value = self._get_value(key)

        def job():
            ins.set(spec.id, value, ch)
            if spec.readable:
                return ins.get(spec.id, ch)   # 下发后自动回读校验
            return None

        self.worker.submit(job, ("write", key, spec.name_cn))

    def _on_read(self, key):
        ins = self._require()
        if ins is None:
            return
        _w, _k, spec, _ch, _g = self._cells[key]
        ch = self._ch_of(key)
        self.worker.submit(lambda: ins.get(spec.id, ch),
                           ("read", key, spec.name_cn))

    def _on_read_group(self, specs, ch_getter):
        ins = self._require()
        if ins is None:
            return
        ch = ch_getter()
        keys = []
        for spec in specs:
            if spec.readable:
                key = f"{spec.id}:{ch if ch is not None else 'grp'}"
                if key in self._cells:
                    keys.append((key, spec.id, ch))
        self.worker.submit(
            lambda: [(k, ins.get(sid, c)) for k, sid, c in keys],
            ("read_group",))

    def _on_read_errors(self):
        ins = self._require()
        if ins is None:
            return
        self.worker.submit(ins.read_errors, ("errors",))

    def _on_clear_status(self):
        ins = self._require()
        if ins is None:
            return
        self.worker.submit(ins.clear_status, ("info", "已清状态(*CLS)"))

    def _on_reset(self):
        if QMessageBox.question(self, "确认", "确认复位仪器到出厂默认？") \
                != QMessageBox.Yes:
            return
        ins = self._require()
        if ins is None:
            return
        self.worker.submit(ins.reset, ("info", "已复位"))

    def _on_local(self):
        ins = self._require()
        if ins is None:
            return
        self.worker.submit(ins.local, ("info", "已返回本地模式"))

    def _diag_syserr(self):
        """通信失败后自动读仪器错误队列（SYSTem:ERRor?）：

        若仪器回出错误码（如 -113 命令头未定义）说明命令被仪器拒绝；
        若也超时无响应则说明链路/仪器状态问题。诊断结果只进日志，不弹窗。
        """
        ins = self.instrument
        if ins is None:
            return

        def job():
            try:
                return ins.read_errors()
            except Exception as e:   # noqa: BLE001
                return e             # 诊断自身失败不走 error 通道，防止递归诊断

        self.worker.submit(job, ("diag",))

    def _check_model(self, idn: str):
        """按 IDN 校验型号/通道语义（MFG-2000 手册：函数通道仅 SOURce1/2）。

        - AFG-2125(1通道) / AFG-2225、MFG-2125/2225(2通道)：函数波形通道 SOURce1/2；
        - MFG-2000 系列的「脉冲通道」「RF 通道(SOURce3RF)」「功率放大器」是独立子系统，
          不是 SOURce3:FUNCtion 波形通道——上位机按 2 个函数通道建模。
        """
        model = idn.split(",")[1].strip().upper() if "," in idn else idn.upper()
        if "2125" in model:
            self._log(f"型号 {model}：1 通道机型，仅 SOURce1 波形通道有效", "#F59E0B")
        elif "2225" in model or "MFG-2" in model:
            self._log(f"型号 {model}：函数波形通道 SOURce1/2"
                      "（脉冲/RF/功放为独立子系统，非波形通道）", "#A78BFA")
        else:
            self._log(f"型号 {model}：未知型号，按 2 个函数波形通道处理", "#F59E0B")
        # 系列联动：IDN 与所选系列不匹配时提示切换（AFG-2225 按 AFG 系列规格校验）
        series = getattr(self.table, "series", "MFG")
        if "AFG" in model and series != "AFG":
            self._log("提示：检测到 AFG 系列机型，请把「系列」切换为 AFG-2000 系列"
                      "（25MHz/10VPP 规格校验）", "#F59E0B")
        elif "MFG" in model and series == "AFG":
            self._log("提示：检测到 MFG 系列机型，建议把「系列」切换为 MFG-2000 系列", "#F59E0B")

    # ---------------------------------------------------------- 结果处理
    def _on_result(self, ctx, result, error):
        from instrument_hub.comm_state import mark_lost, mark_ok
        if error is None:
            mark_ok(self)      # 回读成功 = 通讯真正建立
        else:
            mark_lost(self)    # 回读失败 = 通讯中断
        if error is not None:
            if self.instrument is None:
                return   # 断开后的迟到失败：静默丢弃，不再报错打扰
            if isinstance(error, ParamError):
                QMessageBox.warning(self, "参数错误", str(error))
            elif isinstance(error, (ProtocolError, TransportError)):
                # 通信错误不弹模态框打断操作：详情进日志 + 自动诊断仪器错误队列
                self._log(f"通信错误：{error}", "#EF4444")
                self._diag_syserr()
                return
            else:
                QMessageBox.critical(self, "错误", str(error))
            self._log(f"错误: {error}", "#EF4444")
            return
        kind = ctx[0] if isinstance(ctx, tuple) else ctx
        if kind == "diag":
            if isinstance(result, list):
                text = "；".join(e.human() for e in result) if result \
                    else "错误队列为空（仪器未记录错误，命令头可能未被识别或响应未回传）"
                self._log(f"通信诊断 SYSTem:ERRor? → {text}", "#F59E0B")
            else:
                self._log(f"通信诊断 SYSTem:ERRor? 也超时/失败：{result}", "#EF4444")
        elif kind == "idn":
            self.lbl_idn.setText(str(result))
            self.lbl_dot.setStyleSheet("color:#10B981; font-size:16pt;")
            self.btn_conn.setText("已连接")
            self.btn_conn.setObjectName("btnConnected")
            self._log(f"已连接: {result}", "#10B981")
            self._check_model(str(result))
        elif kind == "stop_done":
            self.lbl_idn.setText("未连接")
            self.lbl_dot.setStyleSheet("color:#9CA3AF; font-size:16pt;")
            self.btn_conn.setText("连接")
            self.btn_conn.setObjectName("btnConnect")
            self._log("已断开", "#F59E0B")
        elif kind == "write":
            _k, key, name = ctx
            if result is not None:
                self._set_value(key, result)
            self._log(f"已下发并回读 {name} = "
                      f"{_fmt_num(result) if result is not None else '—'}",
                      "#22D3EE")
            self._refresh_wave_of(key)
        elif kind == "read":
            _k, key, name = ctx
            self._set_value(key, result)
            self._log(f"已读回 {name} = {_fmt_num(result)}", "#22D3EE")
            self._refresh_wave_of(key)
        elif kind == "read_group":
            for key, value in result:
                self._set_value(key, value)
                self._refresh_wave_of(key)
            self._log("本页读回完成", "#22D3EE")
        elif kind == "errors":
            text = "；".join(e.human() for e in result) if result \
                else "错误队列为空"
            self.lbl_err.setText(text)
            self._log(f"错误队列: {text}", "#F59E0B" if result else "#22D3EE")
        elif kind == "poll":
            out, err = result if isinstance(result, tuple) else (result, None)
            for key, value in out:
                self._set_value(key, value)
                self._refresh_wave_of(key)
            if err is not None:
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)   # 轮询无应答 = 通讯中断
                self._poll_fail += 1
                self._log(f"定时刷新失败({self._poll_fail} 次): {err}", "#EF4444")
                if self._poll_fail >= 3:
                    self.chk_poll.setChecked(False)
                    self._log("定时刷新连续失败，已自动停止（检查接线/仪器后重新勾选）",
                              "#F59E0B")
            else:
                from instrument_hub.comm_state import mark_ok
                mark_ok(self)   # 轮询有应答 = 通讯真正建立
                self._poll_fail = 0
        elif kind == "info":
            name = ctx[1] if len(ctx) > 1 else ""
            self._log(name, "#A78BFA")

    # ---------------------------------------------------------- 连接管理
    def toggle_connection(self):
        if self.instrument is not None:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        kind = self.cmb_kind.currentText()
        try:
            if kind == "模拟从站":
                self._sim = MfgSimulator(self.table)
                transport = LoopbackTransport(self._sim)
            elif kind == "串口":
                baud = int(self.ed_param.text() or 115200)
                transport = SerialTransport(self.ed_target.text(),
                                            baudrate=baud)
            else:
                port = int(self.ed_param.text() or 5025)
                transport = TcpTransport(self.ed_target.text(), port=port)
            # 手册未规定响应超时(澄清项Q1)：真机切换波形/参数后短暂忙，1.0s 偏紧易误报超时
            stack = ScpiStack(transport, timeout=2.0, on_traffic=self._on_traffic)
            ins = Instrument(stack, self.table)
            ins.start()
            self.instrument = ins
        except (TransportError, ProtocolError, ValueError) as e:
            QMessageBox.critical(self, "连接失败", str(e))
            self.disconnect()
            return
        self.worker.clear()   # 清掉断开/上一会话残留 job，连接快速响应
        self.worker.submit(self.instrument.idn, ("idn",))

    def disconnect(self):
        ins, self.instrument = self.instrument, None
        self._sim = None
        self.worker.clear()   # 丢弃排队中的轮询/操作 job，断开立即响应
        # 立即更新 UI（不等后台回收），避免"断开要等好长时间"
        self.lbl_idn.setText("未连接")
        self.lbl_dot.setStyleSheet("color:#9CA3AF; font-size:16pt;")
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self._log("已断开", "#F59E0B")

        def job():
            if ins is not None:
                try:
                    ins.stop()
                except Exception:
                    pass
        self.worker.submit(job, ("stop_done",))

    # ---------------------------------------------------------- 轮询/日志
    def _poll_tick(self):
        if self.instrument is None or not self.chk_poll.isChecked():
            return
        if not self.worker.idle():
            return   # 有命令在途：跳过本轮，防队列堆积
        ins = self.instrument
        chs = list(self.table.channels)
        keys = [(f"func:{ch}", "func", ch) for ch in chs] + \
               [(f"output:{ch}", "output", ch) for ch in chs]

        def job():
            out, err = [], None
            for key, sid, ch in keys:
                try:
                    out.append((key, ins.get(sid, ch)))
                except Exception as e:   # noqa: BLE001
                    err = e   # 一次失败即停本轮，不阻塞后续命令
                    break
            return out, err
        self.worker.submit(job, ("poll",))

    def _on_traffic(self, direction, text):
        # 协议栈线程回调：QTimer.singleShot 在无事件循环线程不触发（帧日志曾整体丢失），
        # 改走 Qt 信号跨线程排队到 UI
        self.sig_traffic.emit(direction, text)

    def _on_traffic_ui(self, direction, text):
        self._log(f"{direction}> {text}",
                  "#22D3EE" if direction == "TX" else "#81C784")

    def _log(self, msg, color="#D4D4D4"):
        self.txt_log.appendHtml(
            f'<span style="color:{color}">{msg}</span>')
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _build_log_group(self) -> QWidget:
        box = QGroupBox("通讯日志（TX/RX SCPI 报文）")
        v = QVBoxLayout(box)
        v.setSpacing(6)
        h = QHBoxLayout()
        h.addWidget(QLabel("状态"))
        self.lbl_state = QLabel("就绪")
        self.lbl_state.setObjectName("Muted")
        h.addWidget(self.lbl_state)
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

    def _save_log(self):
        import datetime
        import os
        path = os.path.join(
            os.environ.get("TEMP", "."),
            f"mfg2000_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_log.toPlainText())
            self._log(f"日志已保存 → {path}", "#F59E0B")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ---------------------------------------------------------- 波形刷新
    def _refresh_wave_of(self, key):
        _w, _k, _s, ch, _g = self._cells[key]
        if ch is not None:
            self._refresh_wave(ch)

    def _refresh_wave(self, ch):
        wave = self._waves.get(ch)
        if wave is None:
            return
        def val(cmd, dflt):
            key = f"{cmd}:{ch}"
            if key not in self._cells:
                return dflt
            w, kind, _s, _c, _g = self._cells[key]
            text = w.currentText() if kind == "combo" else (
                "1" if (kind == "switch" and w.isChecked()) else
                ("0" if kind == "switch" else w.text()))
            try:
                return float(text)
            except (TypeError, ValueError):
                return dflt

        func_key = f"func:{ch}"
        func = "SIN"
        if func_key in self._cells:
            w, kind, _s, _c, _g = self._cells[func_key]
            if kind == "combo":
                func = ZH_WAVE.get(w.currentText(), w.currentText()).upper()
        params = {
            "func": func,
            "freq": val("freq", 1000.0),
            "ampl": val("ampl", 0.1),
            "offset": val("dcoffset", 0.0),
            "duty": val("duty", 50.0),
            "symm": val("symmetry", 50.0),
            "pw": val("pulse_width", 5e-5),
        }
        wave.set_params(**params)
        info = self._wave_info.get(ch)
        if info is not None:
            freq = params["freq"] or 1000.0
            period = 1.0 / freq if freq > 0 else 1.0
            info.setText(
                f"{WAVE_ZH.get(func, func)} | 频率 {freq:g} Hz | "
                f"幅值 {params['ampl']:g} Vpp | 偏移 {params['offset']:g} V | "
                f"周期 {period * 1e6:.3f} µs")

    # ---------------------------------------------------------- 清理
    def shutdown(self):
        """退出闭环：停轮询 → 停线程 → 断链回收。"""
        try:
            self._timer.stop()
        except Exception:
            pass
        ins, self.instrument = self.instrument, None
        if ins is not None:
            try:
                ins.stop()
            except Exception:
                pass
        self._sim = None
        try:
            self.worker.stop()
        except Exception:
            pass
