"""主窗口: 连接栏 + 六个功能页 + 设备工作线程接线。"""
from __future__ import annotations

import os
import sys
import time

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ..it8500 import protocol as P
from ..it8500.transport import (SerialTransport, SimTransport, SimulatedLoad,
                                enumerate_ports)
from ..it8500.worker import DeviceWorker, fmt_log

from .style import apply_theme
from .tabs.dynamic import DynamicTab
from .tabs.fixed import FixedTab
from .tabs.list_tab import ListTab
from .tabs.log_tab import LogTab
from .tabs.realtime import RealtimeTab
from .tabs.system_tab import SystemTab

PROT_SETTERS = {
    "ovp": "set_ovp", "ocp": "set_ocp", "opp": "set_opp",
    "pullon": "set_pullon", "release": "set_release", "bat_min": "set_bat_min",
}


class MainWindow(QMainWindow):
    def __init__(self, sim_default: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IT8500 上位机 — 艾德克斯直流可编程电子负载")
        self.resize(1180, 800)

        self._connected = False
        self._pending: dict[int, tuple] = {}
        self._sim_load: SimulatedLoad | None = None
        self._csv = None
        self._csv_path = ""
        self._csv_rows = 0
        self._sim_default = sim_default

        self.worker = DeviceWorker()
        self.worker.result.connect(self._on_result)
        self.worker.measured.connect(self._on_measured)
        self.worker.raw_log.connect(self._on_raw_log)
        self.worker.conn_state.connect(self._on_conn_state)

        self._build_ui()
        self._wire_tabs()
        self.refresh_ports()
        if sim_default:
            self.chk_sim.setChecked(True)
        self.worker.start()
        self._set_connected_ui(False)
        self._splitter_patched = False
        self._fit_to_screen()

    def _fit_to_screen(self) -> None:
        """窗口自适应屏幕: 小屏工控机上打开也保证底部日志可见。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        w = max(980, min(1180, geo.width() - 60))
        h = max(600, min(880, geo.height() - 60))
        self.resize(w, h)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._splitter_patched:
            self._splitter_patched = True
            total = self.splitter.height()
            if total > 100:
                bottom = max(250, int(total * 0.32))   # 日志至少 ~1/3
                self.splitter.setSizes([max(200, total - bottom), bottom])

    # ================================================================ UI
    def _build_ui(self) -> None:
        central = QWidget()
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._build_connect_bar())

        self.tabs = QTabWidget()
        self.tab_realtime = RealtimeTab()
        self.tab_fixed = FixedTab()
        self.tab_dynamic = DynamicTab()
        self.tab_list = ListTab()
        self.tab_system = SystemTab()
        self.tab_log = LogTab()
        # 页签内容套滚动区: 小屏 (600~768 高) 也能完整放下, 不把日志挤出屏
        self._tab_wrappers: dict[int, QScrollArea] = {}

        def _wrap(widget):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(widget)
            self._tab_wrappers[id(widget)] = scroll
            return scroll

        # 主页同屏：左=实时测量，右=定值设置（用户要求同屏显示，免切页）
        home = QSplitter(Qt.Horizontal)
        home.setChildrenCollapsible(False)
        home.addWidget(_wrap(self.tab_realtime))
        home.addWidget(_wrap(self.tab_fixed))
        home.setStretchFactor(0, 1)
        home.setStretchFactor(1, 1)
        self.tabs.addTab(home, "实时测量 / 定值设置")
        for widget, title in (
                (self.tab_dynamic, "动态测试"),
                (self.tab_list, "LIST 列表"),
                (self.tab_system, "系统与保护")):
            self.tabs.addTab(_wrap(widget), title)

        # 上: 功能页签 / 下: 常驻信息与日志 (分割条可调高度, 但日志永不折叠)
        log_box = QGroupBox("信息与日志 (常驻底部, 便于随时查看)")
        log_lay = QVBoxLayout(log_box)
        log_lay.setContentsMargins(6, 10, 6, 6)
        log_lay.addWidget(self.tab_log)
        log_box.setMinimumHeight(240)          # 标题+两行控制条+多行日志
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(log_box)
        self.splitter.setStretchFactor(0, 2)   # 拉伸时日志多分一些
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, False)  # 日志区禁止拖没
        self.splitter.setSizes([480, 280])
        vbox.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        self.statusBar().showMessage("就绪 — 选择串口或勾选模拟设备后点击连接")
        self.lbl_csv = QLabel("")
        self.statusBar().addPermanentWidget(self.lbl_csv)

    def select_tab(self, widget: QWidget) -> None:
        """按内部页签 widget 切换 (页签被滚动区包装后仍可用原对象)。"""
        scroll = self._tab_wrappers.get(id(widget))
        if scroll is not None:
            self.tabs.setCurrentWidget(scroll)

    def _build_connect_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("ConnectBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(8)

        h.addWidget(QLabel("串口:"))
        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(150)
        h.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        h.addWidget(self.btn_refresh)

        h.addWidget(QLabel("波特率:"))
        self.cmb_baud = QComboBox()
        for b in ("4800", "9600", "19200", "38400"):
            self.cmb_baud.addItem(b)
        self.cmb_baud.setCurrentText("9600")
        h.addWidget(self.cmb_baud)

        h.addWidget(QLabel("地址:"))
        self.spn_addr = QSpinBox()
        self.spn_addr.setRange(0, 31)
        self.spn_addr.setValue(1)   # 默认地址 1（与现场一致；改动需与面板地址一致）
        self.spn_addr.setToolTip("本机地址 0~31，须与仪器面板设置一致（本软件默认 1）")
        h.addWidget(self.spn_addr)

        self.chk_sim = QCheckBox("模拟设备")
        self.chk_sim.setToolTip("无硬件联调: 用内置模拟负载")
        h.addWidget(self.chk_sim)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.setObjectName("ConnectBtn")
        self.btn_connect.setFixedWidth(96)
        self.btn_connect.clicked.connect(self.toggle_connect)
        h.addWidget(self.btn_connect)

        h.addStretch(1)

        # ---- 右上角连接说明 (短文案, 详见弹窗) ----
        self.lbl_warn = QLabel("须帧格式(FRAME)协议 · SCPI 不可用")
        self.lbl_warn.setProperty("role", "warn")
        self.lbl_warn.setToolTip(
            "连接须知: 设备必须工作在帧格式 FRAME 协议下, "
            "SCPI 模式无法使用本上位机 (点击「连接说明」查看完整注意事项)")
        h.addWidget(self.lbl_warn)
        self.btn_help = QPushButton("连接说明")
        self.btn_help.setToolTip("点击查看接线 / 协议 / 波特率等完整注意事项")
        self.btn_help.clicked.connect(self._show_connect_help)
        h.addWidget(self.btn_help)

        self.lbl_dot = QLabel("● 未连接")
        self.lbl_dot.setObjectName("StatusDot")
        self.lbl_dot.setProperty("on", False)
        h.addWidget(self.lbl_dot)
        self.lbl_ident = QLabel("")
        self.lbl_ident.setProperty("role", "hint")
        self.lbl_ident.setMaximumWidth(240)
        h.addWidget(self.lbl_ident)

        self.chk_sim.toggled.connect(self._on_sim_toggled)
        return bar

    def _show_connect_help(self) -> None:
        QMessageBox.information(self, "连接说明 — IT8500 上位机", (
            "连接前请逐项确认:\n\n"
            "1. 协议模式 (最重要)\n"
            "   设备必须工作在「帧格式 FRAME」协议下, 本软件只实现帧格式。\n"
            "   若设备被设为 SCPI 模式, 本上位机将完全无法通讯\n"
            "   (表现为持续「接收超时」)。请在设备面板菜单中将\n"
            "   通讯协议切回帧格式后再连接。\n\n"
            "2. 串口参数\n"
            "   波特率 4800 / 9600 / 19200 / 38400 与面板一致 (出厂 9600),\n"
            "   数据位 8、停止位 1、无校验; 本机地址 0~31 与面板一致 (出厂 0)。\n\n"
            "3. 硬件接线\n"
            "   后面板 DB9 为 TTL 电平, 必须使用 IT-E121 (RS232) /\n"
            "   IT-E122 (USB) / IT-E123 (RS485) 通讯模块, 不可直连 RS232 线。\n\n"
            "4. 连接后行为\n"
            "   软件自动下发 20H 进入远程模式, 并开始约 0.35s 周期的测量轮询。\n\n"
            "5. 排查工具\n"
            "   连不上时: 先断开, 在「信息与日志」页点击「通讯诊断」\n"
            "   自动扫描波特率与地址; 日志页可查看原始帧 (TX/RX/RAW)。\n"
        ))

    def _wire_tabs(self) -> None:
        rt = self.tab_realtime
        rt.output_clicked.connect(self._set_output)
        rt.remote_clicked.connect(self._set_remote)
        rt.record_clicked.connect(self._toggle_record)

        fx = self.tab_fixed
        fx.mode_selected.connect(self._set_load_mode)
        fx.mode_read.connect(lambda: self.op(
            "读取负载模式", lambda: self.dev().get_load_mode(),
            ok=fx.show_mode))
        fx.value_set.connect(self._set_value)
        fx.value_read.connect(self._read_value)
        fx.work_mode_set.connect(self._set_work_mode)
        fx.work_mode_read.connect(lambda: self.op(
            "读取工作模式", lambda: self.dev().get_work_mode(),
            ok=fx.show_work_mode))

        dy = self.tab_dynamic
        dy.params_set.connect(self._set_dynamic)
        dy.params_read.connect(lambda m: self.op(
            f"读取动态 {m}", lambda m=m: self.dev().set_dynamic(m),
            ok=lambda p, m=m: dy.show_params(m, p)))

        lt = self.tab_list
        lt.cfg_set.connect(self._list_cfg_set)
        lt.cfg_read.connect(self._list_cfg_read)
        lt.step_write.connect(self._list_step_write)
        lt.step_read.connect(self._list_step_read)
        lt.steps_write_all.connect(self._list_steps_write_all)
        lt.steps_read_all.connect(self._list_steps_read_all)
        lt.trig_set.connect(lambda m: self.op(
            "设置触发模式", lambda m=m: self.dev().set_trigger_mode(m)))
        lt.trig_read.connect(lambda: self.op(
            "读取触发模式", lambda: self.dev().get_trigger_mode(),
            ok=lt.fill_trigger))
        lt.trig_send.connect(lambda: self.op(
            "发送 BUS 触发", lambda: self.dev().trigger_bus()))

        st = self.tab_system
        st.prot_set.connect(self._prot_set)
        st.prot_read.connect(self._prot_read)
        st.prot_reset.connect(self._prot_reset)
        st.timer_set.connect(lambda s: self.op(
            f"设置定时器 {s}s", lambda s=s: self.dev().set_timer(s),
            ok=st.show_timer))
        st.timer_read.connect(lambda: self.op(
            "读取定时器", lambda: self.dev().set_timer(),
            ok=st.show_timer))
        st.timer_en_set.connect(lambda b: self.op(
            "设置定时器状态", lambda b=b: self.dev().set_timer_enabled(b)))
        st.timer_en_read.connect(lambda: self.op(
            "读取定时器状态", lambda: self.dev().get_timer_enabled(),
            ok=st.show_timer_en))
        st.sense_set.connect(lambda b: self.op(
            "设置远程测量", lambda b=b: self.dev().set_sense(b)))
        st.sense_read.connect(lambda: self.op(
            "读取远程测量", lambda: self.dev().get_sense(),
            ok=st.show_sense))
        st.local_set.connect(lambda b: self.op(
            "设置 LOCAL 键", lambda b=b: self.dev().set_local_key(b)))
        st.addr_apply.connect(self._apply_address)
        st.setup_save.connect(lambda a: self.op(
            f"保存设置到区 {a}", lambda a=a: self.dev().save_setup(a)))
        st.setup_recall.connect(lambda a: self.op(
            f"取出设置区 {a}", lambda a=a: self.dev().recall_setup(a)))

        lg = self.tab_log
        lg.read_identity.connect(lambda: self.op(
            "读取设备信息", lambda: self.dev().read_identity(),
            ok=lg.show_identity))
        lg.read_barcode.connect(lambda: self.op(
            "读取条形码", lambda: self.dev().read_barcode(),
            ok=lg.show_barcode))
        lg.diagnose.connect(self._run_diagnosis)

    # ============================================================ 连接
    def refresh_ports(self) -> None:
        current = self.cmb_port.currentData()
        self.cmb_port.clear()
        ports = enumerate_ports()
        for dev, label in ports:
            self.cmb_port.addItem(label, dev)
        if not ports:
            self.cmb_port.addItem("无可用串口", None)
        if current:
            i = self.cmb_port.findData(current)
            if i >= 0:
                self.cmb_port.setCurrentIndex(i)

    def _on_sim_toggled(self, checked: bool) -> None:
        self.cmb_port.setEnabled(not checked)
        self.cmb_baud.setEnabled(not checked)
        self.btn_refresh.setEnabled(not checked)
        if checked and self._connected:
            self.toggle_connect()

    def toggle_connect(self) -> None:
        if self._connected:
            self.op("disconnect", lambda: self.worker.do_disconnect())
            return
        addr = self.spn_addr.value()
        if self.chk_sim.isChecked():
            if self._sim_load is None:
                self._sim_load = SimulatedLoad()
            tr = SimTransport(self._sim_load)
        else:
            port = self.cmb_port.currentData()
            if not port:
                self._err("未选择串口 (或刷新后重试)")
                return
            tr = SerialTransport(port, int(self.cmb_baud.currentText()),
                                 on_raw=self._log_raw)
        self.btn_connect.setEnabled(False)
        self.op("connect", lambda: self.worker.do_connect(
            tr, addr, self._log_tx, self._log_rx),
            err=lambda e: (self.btn_connect.setEnabled(True),
                           self._err(f"连接失败: {e}")))

    def dev(self):
        return self.worker.device_or_raise()

    def _set_connected_ui(self, ok: bool) -> None:
        self._connected = ok
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("已连接" if ok else "连接")
        self.btn_connect.setObjectName("btnConnected" if ok else "btnConnect")
        self.btn_connect.setProperty("connected", ok)
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)
        self.lbl_dot.setProperty("on", ok)
        self.lbl_dot.setText("● 已连接" if ok else "● 未连接")
        self.lbl_dot.style().unpolish(self.lbl_dot)
        self.lbl_dot.style().polish(self.lbl_dot)
        # 连接期间锁定地址; 串口参数在模拟模式下本就禁用
        sim = self.chk_sim.isChecked()
        self.cmb_port.setEnabled(not ok and not sim)
        self.cmb_baud.setEnabled(not ok and not sim)
        self.btn_refresh.setEnabled(not ok and not sim)
        self.spn_addr.setEnabled(not ok)
        for tab in (self.tab_realtime, self.tab_fixed, self.tab_dynamic,
                    self.tab_list, self.tab_system, self.tab_log):
            tab.set_connected(ok)
        if not ok:
            self.lbl_ident.setText("")
            self.tab_log.set_connected(False)
            if self._csv:
                self._toggle_record(False)

    def _on_conn_state(self, ok: bool, msg: str) -> None:
        self._set_connected_ui(ok)
        self.statusBar().showMessage(msg, 8000)
        if not ok:
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)   # 链路断开 = 通讯中断，右上角指示灯回灰
        if ok:
            # 手册要求: PC 控制前必须先由 20H 进入远程模式 (真机面板模式下
            # 所有写命令都会回 B0H), 连接成功后自动下发
            self.op("进入远程模式",
                    lambda: self.dev().set_remote(True),
                    ok=lambda _: self.tab_realtime.set_remote_state(True),
                    err=lambda e: self._err(f"进入远程模式失败: {e}"))
            self.op("读取设备信息", lambda: self.dev().read_identity(),
                    ok=self._on_identity)
            self.op("读取工作模式", lambda: self.dev().get_work_mode(),
                    ok=self.tab_fixed.show_work_mode)

    def _on_identity(self, ident) -> None:
        self.tab_log.show_identity(ident)
        self.lbl_ident.setText(
            f"IT{ident.model}  SN {ident.serial}  {ident.version}"
            if ident.model else "")
        self.statusBar().showMessage(
            f"设备信息: IT{ident.model} SN {ident.serial} {ident.version}", 8000)

    # ============================================================ 任务调度
    def op(self, name: str, fn, ok=None, err=None) -> int:
        seq = self.worker.submit(name, fn)
        self._pending[seq] = (name, ok, err)
        return seq

    def _on_result(self, seq: int, name: str, success: bool, payload) -> None:
        if name == "poll":
            if not success:
                from instrument_hub.comm_state import mark_lost
                mark_lost(self)   # 轮询失败 = 通讯中断（成功则由 measured 点绿）
            return
        entry = self._pending.pop(seq, None)
        if entry is None:
            return
        _, ok_cb, err_cb = entry
        if success:
            if ok_cb is not None:
                try:
                    ok_cb(payload)
                except Exception as e:  # noqa: BLE001
                    self._err(f"界面刷新失败: {e}")
            else:
                self.statusBar().showMessage(f"{name}: 完成", 4000)
        else:
            if err_cb is not None:
                err_cb(payload)
            else:
                self._err(f"{name}: {payload}")

    def _err(self, text: str) -> None:
        self.statusBar().showMessage(f"✗ {text}", 10000)
        self.tab_log.append_log(f"[错误] {text}")

    # ============================================================ 帧日志
    def _log_tx(self, data: bytes) -> None:
        self.worker.raw_log.emit("TX", fmt_log("TX", data))

    def _log_rx(self, data: bytes) -> None:
        self.worker.raw_log.emit("RX", fmt_log("RX", data))

    def _log_raw(self, data: bytes) -> None:
        """未解析/被丢弃的原始字节 (波特率错、线路干扰时的关键线索)。"""
        self.worker.raw_log.emit("RAW", fmt_log("RAW", data))

    def _on_raw_log(self, direction: str, text: str) -> None:
        if direction == "ERR":
            text = f"[错误] {text}"
        elif direction == "DIAG":
            pass        # 诊断行已是完整文本
        self.tab_log.append_log(text)

    # ============================================================ 通讯诊断
    def _run_diagnosis(self) -> None:
        if self._connected:
            self._err("请先断开连接, 再执行通讯诊断")
            return
        port = self.cmb_port.currentData()
        if not port:
            self._err("未选择串口, 无法诊断")
            return
        base_addr = self.spn_addr.value()
        self.tab_log.set_diag_running(True)
        self.statusBar().showMessage(
            "通讯诊断进行中: 扫描 4 档波特率 × 抽查地址, 约 10~40 秒…")

        def diag():
            from ..it8500.diagnose import scan_device
            log_line = lambda t: self.worker.raw_log.emit("DIAG", t)  # noqa: E731
            return scan_device(lambda p, b: SerialTransport(p, b),
                               port, base_addr, log=log_line)

        self.op("通讯诊断", diag,
                ok=self._diag_done,
                err=lambda e: self._diag_failed(e))

    def _diag_done(self, res) -> None:
        self.tab_log.set_diag_running(False)
        if res.ok and res.baud is not None:
            i = self.cmb_baud.findText(str(res.baud))
            if i >= 0:
                self.cmb_baud.setCurrentIndex(i)
            if res.addr is not None and res.addr <= 31:
                self.spn_addr.setValue(res.addr)
        self.statusBar().showMessage(f"诊断完成: {res.summary()}", 20000)

    def _diag_failed(self, err) -> None:
        self.tab_log.set_diag_running(False)
        self._err(f"通讯诊断失败: {err}")

    # ============================================================ 测量/CSV
    def _on_measured(self, m: P.Measurement) -> None:
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 收到测量回读 = 通讯真正建立
        t = time.monotonic()
        self.tab_realtime.apply_measurement(m, t)
        if self._csv:
            flags = "/".join(sorted(m.op_flags | m.query_flags))
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            self._csv.write(f"{ts},{t:.3f},{m.voltage:.4f},{m.current:.4f},"
                            f"{m.power:.4f},{flags}\n")
            self._csv_rows += 1
            if self._csv_rows % 10 == 0:
                self._csv.flush()

    def _toggle_record(self, on: bool) -> None:
        if on and not self._csv:
            # 打包成 EXE 后快捷方式的 cwd 不确定, 记录固定放在 EXE 旁
            base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                    else os.getcwd())
            rec_dir = os.path.join(base, "记录")
            os.makedirs(rec_dir, exist_ok=True)
            path = os.path.join(rec_dir, time.strftime("IT8500_%Y%m%d_%H%M%S.csv"))
            try:
                self._csv = open(path, "w", encoding="utf-8-sig", newline="")
            except OSError as e:
                self._err(f"无法创建记录文件: {e}")
                self.tab_realtime.set_recording(False)
                return
            self._csv.write("时间,monotonic,电压V,电流A,功率W,状态\n")
            self._csv_path = path
            self._csv_rows = 0
            self.lbl_csv.setText(f"● 记录中 {path}")
            self.statusBar().showMessage(f"开始记录: {path}")
        elif not on and self._csv:
            try:
                self._csv.flush()
                self._csv.close()
            finally:
                self._csv = None
                self.lbl_csv.setText(f"已保存 {self._csv_rows} 行 → {self._csv_path}")
                self.statusBar().showMessage(
                    f"记录已保存: {self._csv_path} ({self._csv_rows} 行)", 8000)
        if self.tab_realtime.btn_record.isChecked() != on:
            self.tab_realtime.set_recording(on)

    # ============================================================ 实时控制
    def _set_output(self, on: bool) -> None:
        if on:
            # 电子负载拉载属高危动作，须二次确认（对齐框架安全规范）
            from instrument_hub.dialogs import ConfirmOutputDialog
            dlg = ConfirmOutputDialog(
                "IT8500 电子负载", "开启拉载（输入 ON）",
                "负载将开始拉载，被拉载的电源/电池会持续放电！"
                "确认被测对象、接线与拉载量程无误后再开启。",
                "", self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        self.op("输出 " + ("ON" if on else "OFF"),
                lambda: self.dev().set_input(on),
                ok=lambda _: self.tab_realtime.set_output_state(on),
                err=lambda e: self._err(f"输出控制失败: {e}"))

    def _set_remote(self, remote: bool) -> None:
        self.op("遥控" if remote else "面板",
                lambda: self.dev().set_remote(remote),
                ok=lambda _: self.tab_realtime.set_remote_state(remote))

    # ============================================================ 定值页
    def _set_load_mode(self, mode: str) -> None:
        if not self._connected:
            return
        self.op(f"设置负载模式 {mode}",
                lambda: self.dev().set_load_mode(mode),
                ok=lambda _: self.tab_fixed.show_mode(mode))

    def _set_value(self, mode: str, value: float) -> None:
        setter = {"CC": "set_cc", "CV": "set_cv",
                  "CW": "set_cw", "CR": "set_cr"}[mode]
        self.op(f"设置 {mode} = {value}",
                lambda: getattr(self.dev(), setter)(value),
                ok=lambda back, m=mode: self.tab_fixed.show_value(m, back))

    def _read_value(self, mode: str) -> None:
        setter = {"CC": "set_cc", "CV": "set_cv",
                  "CW": "set_cw", "CR": "set_cr"}[mode]
        self.op(f"读取 {mode}",
                lambda: getattr(self.dev(), setter)(),
                ok=lambda back, m=mode: self.tab_fixed.show_value(m, back))

    def _set_work_mode(self, mode: str) -> None:
        def set_then_read():
            d = self.dev()
            d.set_work_mode(mode)
            return d.get_work_mode()
        self.op(f"设置工作模式 {mode}", set_then_read,
                ok=self.tab_fixed.show_work_mode)

    # ============================================================ 动态页
    def _set_dynamic(self, mode: str, params) -> None:
        self.op(f"设置动态 {mode}",
                lambda: self.dev().set_dynamic(mode, params),
                ok=lambda p, m=mode: self.tab_dynamic.show_params(m, p))

    # ============================================================ LIST 页
    def _list_mode(self) -> str:
        return self.tab_list.cmb_mode.currentData()

    def _list_cfg_set(self, kind: str, value) -> None:
        actions = {
            "mode": lambda: self.dev().set_list_mode(value),
            "loop": lambda: self.dev().set_list_loop(bool(value)),
            "steps": lambda: self.dev().set_list_steps(int(value)),
            "file": lambda: self.dev().set_list_filename(str(value)),
            "part": lambda: self.dev().set_list_partition(int(value)),
            "area_save": lambda: self.dev().save_list_file(int(value)),
            "area_recall": lambda: self.dev().recall_list_file(int(value)),
        }
        self.op(f"LIST {kind} = {value}", actions[kind])

    def _list_cfg_read(self, _kind: str) -> None:
        def read_all():
            d = self.dev()
            return dict(mode=d.get_list_mode(), loop=d.get_list_loop(),
                        steps=d.get_list_steps(),
                        file=d.get_list_filename(),
                        part=d.get_list_partition())
        self.op("读取 LIST 配置", read_all,
                ok=lambda cfg: self.tab_list.fill_config(**cfg))

    def _list_step_write(self, index: int, value: float, t_ms: float) -> None:
        mode = self._list_mode()
        self.op(f"写入 LIST 第 {index} 步",
                lambda: self.dev().set_list_step(
                    mode, P.ListStep(index, value, t_ms)))

    def _list_step_read(self, index: int) -> None:
        mode = self._list_mode()
        self.op(f"读取 LIST 第 {index} 步",
                lambda: self.dev().get_list_step(mode, index),
                ok=self.tab_list.fill_step)

    def _list_steps_write_all(self, rows: list) -> None:
        mode = self._list_mode()

        def write_all():
            d = self.dev()
            for idx, value, t_ms in rows:
                d.set_list_step(mode, P.ListStep(idx, value, t_ms))
            return len(rows)

        self.op(f"下载 {len(rows)} 步到设备",
                write_all,
                ok=lambda n: self.statusBar().showMessage(
                    f"已下载 {n} 步 ({mode})", 6000))

    def _list_steps_read_all(self, count: int) -> None:
        mode = self._list_mode()

        def read_all():
            d = self.dev()
            return [d.get_list_step(mode, i) for i in range(count)]

        self.op(f"读取 LIST 前 {count} 步", read_all,
                ok=self.tab_list.fill_steps)

    # ============================================================ 系统页
    def _prot_set(self, key: str, value: float) -> None:
        self.op(f"设置 {key.upper()} = {value}",
                lambda: getattr(self.dev(), PROT_SETTERS[key])(value),
                ok=lambda v, k=key: self.tab_system.show_prot(k, v))

    def _prot_read(self, key: str) -> None:
        self.op(f"读取 {key.upper()}",
                lambda: getattr(self.dev(), PROT_SETTERS[key])(),
                ok=lambda v, k=key: self.tab_system.show_prot(k, v))

    def _prot_reset(self) -> None:
        """保护复位：输出 OFF→ON 清除保护锁存（帧协议无清故障命令，按手册输入开关复位）。"""
        from instrument_hub.dialogs import ConfirmOutputDialog
        dlg = ConfirmOutputDialog(
            "IT8500 电子负载", "保护复位（输出 OFF→ON）",
            "将关闭输入并立即重新开启，以清除锁存的保护状态"
            "（RV 反接 / OV 过压 / OC 过流 / OP 过功率 / OH 过温）。\n"
            "复位完成后输入处于开启状态，请确认负载接线与量程安全。",
            "保护复位", self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return
        def cycle():
            self.dev().set_input(False)
            self.dev().set_input(True)
        self.op("保护复位（输出 OFF→ON）", cycle)

    def _apply_address(self, new_addr: int) -> None:
        self.op(f"修改地址为 {new_addr}",
                lambda: self.dev().set_address(new_addr),
                ok=lambda _: self.statusBar().showMessage(
                    f"通讯地址已改为 {new_addr}, 后续命令将使用新地址", 8000))

    # ============================================================ 关闭
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._csv:
                try:
                    self._csv.close()
                except Exception:  # noqa: BLE001
                    pass
            self.worker.stop(2000)
            super().closeEvent(event)
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass
