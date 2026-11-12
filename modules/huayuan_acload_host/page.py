# -*- coding: utf-8 -*-
"""华源交流回馈式负载上位机 · 融合版界面（FusionHub 风格）。

原上位机（tkinter）功能全量移植：
连接（串口 / 网口 TCP / UDP / 模拟从站）→ 运行控制 / 通道设置 / 设备信息 / 手动调试
+ 右侧实时监控 + 底部通讯日志 + 高级设置（地址偏移/字序/轮询/本地量程）。

线程模型沿用原版：常驻单工作线程串行执行 Modbus 操作，结果经队列回主线程；
界面只消费 device.ACFeedbackLoad / Snapshot 语义层，不触碰帧字节。
"""
import json
import os
import queue
import threading
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                             QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                             QRadioButton, QScrollArea, QSpinBox, QSplitter,
                             QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog
from instrument_hub.widgets import Card

from .core import modbus_rtu as mb
from .core import registers as rg
from .core.device import ACFeedbackLoad, ChannelMeasure, RangeError
from .core.simulator import SlaveSimulator

APP_TITLE = "交流回馈式负载上位机 · 华源 MODBUS V1.4"

MODE_LABELS = {0: "三相统调", 1: "三相独立", 2: "单相并联"}
CTRL_LABELS = {0: "功率模式", 1: "电流模式"}

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".huayuan_acload.json")

DEFAULT_CFG = {
    "conn_mode": "serial",
    "serial_port": "",
    "baud": 9600,
    "parity": "N",
    "stopbits": "1",
    "host": "127.0.0.1",
    "tcp_port": 7000,
    "mbap": False,
    "unit": 1,
    "offset": 0,
    "word_swap": False,
    "align_even": False,
    "timeout": 0.8,
    "inter_frame": 0.02,
    "poll_period": 1.2,
    "with_channels": True,
    "limit_power": 0.0,
    "limit_current": 0.0,
    "limit_voltage": 0.0,
    "show_wire": False,
}

BTN_CSS = "QPushButton{min-width:76px;}"


def load_cfg() -> dict:
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except Exception:  # noqa: BLE001
        pass
    return cfg


def save_cfg(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def _hint(msg: str) -> str:
    m = msg.lower()
    if "超时" in msg or "timeout" in m:
        return ("排查建议：\n"
                "· 确认串口端口 / IP 端口正确，设备已上电\n"
                "· 确认从站地址与设备一致\n"
                "· 网口若为裸 RTU 透传，不要勾选 MBAP\n"
                "· 确认波特率（默认 9600）、8 位数据、无校验、1 位停止")
    if "crc" in m:
        return "排查建议：线路干扰或波特率不符，可试试增大「帧间隔」到 0.05 秒。"
    if "异常码 0x02" in msg:
        return "排查建议：地址不对。检查高级设置里的「寄存器地址偏移」。"
    if "异常码 0x03" in msg:
        return ("排查建议：值超出设备允许范围。\n"
                "重点核对单位：功率是 0.1W、电流电压是 0.001。\n"
                "也可在高级设置里填「功率/电流上限」，让软件本地拦截。")
    return ""


# ==========================================================================
# 工作线程：所有 Modbus 操作串行执行（常驻单线程 + 任务队列）
# ==========================================================================

class Worker(threading.Thread):
    def __init__(self, cmd_q: "queue.Queue", res_q: "queue.Queue"):
        super().__init__(daemon=True, name="huayuan-load-worker")
        self.cmd_q = cmd_q
        self.res_q = res_q
        self.client = None
        self.load: ACFeedbackLoad | None = None
        self._stop = False

        self.poll_period = 1.2
        self.poll_enabled = True
        self.with_channels = True
        self.log_wire = False
        self._next_poll = 0.0
        self._fail = 0
        self._sim: SlaveSimulator | None = None

    def run(self) -> None:
        while not self._stop:
            task = None
            try:
                task = self.cmd_q.get(timeout=0.05)
            except queue.Empty:
                if (self.client is not None and self.poll_enabled
                        and time.monotonic() >= self._next_poll):
                    task = ("poll", None)
            if task is None:
                continue
            self._dispatch(task)

    def _dispatch(self, task) -> None:
        kind, payload = task
        try:
            if kind == "connect":
                self._do_connect(payload)
            elif kind == "disconnect":
                self._do_disconnect()
            elif kind == "poll":
                self._do_poll()
            elif kind == "ops":
                self._do_ops(payload)
            elif kind == "read":
                self._do_read(payload)
            elif kind == "stop":
                self._stop = True
        except Exception as exc:  # noqa: BLE001
            self.res_q.put(("error", (kind, str(exc), type(exc).__name__)))
            if kind == "poll":
                self._poll_failed(str(exc))

    def _do_connect(self, cfg: dict) -> None:
        self._do_disconnect()
        mode = cfg["conn_mode"]
        if mode == "sim":
            # 模拟从站：进程内起假从站，走 TCP 真链路回环（无真机可跑通全流程）
            if self._sim is None:
                self._sim = SlaveSimulator(unit=int(cfg["unit"]), mbap=bool(cfg["mbap"]),
                                           host="127.0.0.1", port=int(cfg["tcp_port"]))
                self._sim.start()
            cfg = dict(cfg)
            cfg["conn_mode"] = "tcp"
            cfg["host"] = "127.0.0.1"
            mode = "tcp"
        if mode == "serial":
            tp = mb.SerialTransport(cfg["serial_port"], int(cfg["baud"]), 8,
                                    cfg["parity"], float(cfg["stopbits"]))
        elif mode == "tcp":
            tp = mb.TcpTransport(cfg["host"], int(cfg["tcp_port"]))
            tp.mbap = bool(cfg["mbap"])
        else:
            tp = mb.UdpTransport(cfg["host"], int(cfg["tcp_port"]))
            tp.mbap = bool(cfg["mbap"])

        def on_tx(b):
            if self.log_wire:
                self.res_q.put(("wire", ("TX", b)))

        def on_rx(b):
            if self.log_wire:
                self.res_q.put(("wire", ("RX", b)))

        client = mb.ModbusClient(tp, unit=int(cfg["unit"]), offset=int(cfg["offset"]),
                                 word_swap=bool(cfg["word_swap"]),
                                 align_even=bool(cfg["align_even"]),
                                 timeout=float(cfg["timeout"]),
                                 inter_frame_delay=float(cfg["inter_frame"]),
                                 on_tx=on_tx, on_rx=on_rx)
        load = ACFeedbackLoad(client, limits={"power": cfg["limit_power"],
                                              "current": cfg["limit_current"],
                                              "voltage": cfg["limit_voltage"]})
        ver = client.read_registers(rg.ADDR_VERSION, 1)[0]   # 连通性探测
        serial = None
        try:
            serial = load.read_serial()
        except Exception:  # noqa: BLE001
            pass
        self.client, self.load = client, load
        self.poll_period = float(cfg["poll_period"])
        self.with_channels = bool(cfg["with_channels"])
        self.poll_enabled = True
        self._fail = 0
        self._next_poll = 0.0
        self.res_q.put(("connected", (tp.describe, ver, serial)))

    def _do_disconnect(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
            self.load = None
            self.res_q.put(("disconnected", None))
        if self._sim is not None:
            try:
                self._sim.stop()
            except Exception:  # noqa: BLE001
                pass
            self._sim = None

    def _do_poll(self) -> None:
        if self.client is None:
            return
        try:
            snap = self.load.read_status_block()["snapshot"]
            chans = self.load.read_channels_block() if self.with_channels else None
            self._fail = 0
            self.res_q.put(("poll", (snap, chans)))
        except Exception as exc:  # noqa: BLE001
            self._fail += 1
            self._poll_failed(str(exc))
        finally:
            self._next_poll = time.monotonic() + self.poll_period

    def _poll_failed(self, msg: str) -> None:
        if self._fail >= 3:
            self.poll_enabled = False
            self.res_q.put(("poll_stopped", msg))
        else:
            self.res_q.put(("poll_error", msg))

    def _do_ops(self, payload) -> None:
        ops, label = payload
        if self.load is None:
            raise mb.ModbusError("尚未连接设备，无法下发")
        self.load.run_ops(ops)
        self._next_poll = 0.0
        self.res_q.put(("ops_done", label))

    def _do_read(self, payload) -> None:
        start, count = payload
        if self.client is None:
            raise mb.ModbusError("尚未连接设备，无法读取")
        vals = self.client.read_registers(start, count)
        self.res_q.put(("read_result", (start, vals)))


# ==========================================================================
# 界面
# ==========================================================================

class HuayuanLoadPage(QWidget):
    """交流回馈式负载控制：连接 → 运行控制/通道设置/设备信息/手动调试 + 监控 + 日志。"""

    sig = pyqtSignal(str, object)   # (kind, payload) 工作线程 → 主线程

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = load_cfg()
        self.connected = False
        self.connecting = False
        # 无连接的门面实例：仅用于组包 + 本地量程校验（原版 self.builder）
        self.builder = ACFeedbackLoad(None, limits={"power": self.cfg["limit_power"],
                                                    "current": self.cfg["limit_current"],
                                                    "voltage": self.cfg["limit_voltage"]})
        self.set_power = {ch: 0.0 for ch in range(1, rg.CHANNEL_COUNT + 1)}
        self.set_current = {ch: 0.0 for ch in rg.PHASE_CHANNELS}
        self._serial = 0

        self.cmd_q: "queue.Queue" = queue.Queue()
        self.res_q: "queue.Queue" = queue.Queue()
        self.worker = Worker(self.cmd_q, self.res_q)
        self.worker.poll_period = float(self.cfg["poll_period"])
        self.worker.with_channels = bool(self.cfg["with_channels"])
        self.worker.log_wire = bool(self.cfg["show_wire"])
        self.worker.start()

        self.sig.connect(self._handle)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        page_lay = QVBoxLayout()   # 嵌套布局：框架日志分割条跳过本页（自管分割条）
        page_lay.setSpacing(8)

        page_lay.addWidget(self._build_conn_card())

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(12)
        split.setChildrenCollapsible(False)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)

        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        # 监控栏在左、控制页签在右（用户要求对调）
        mid.addWidget(self._build_monitor())
        mid.addWidget(self._build_tabs())
        mid.setStretchFactor(0, 0)
        mid.setStretchFactor(1, 1)
        mid.setSizes([560, 820])
        bv.addWidget(mid, 1)
        split.addWidget(body)
        split.addWidget(self._build_log_group())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        # 日志区默认可见（用户要求）：给足初始高度并设下限，拖动仍可调
        self._log_group.setMinimumHeight(120)
        split.setSizes([430, 170])
        page_lay.addWidget(split, 1)
        root.addLayout(page_lay)

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(40)
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start()

        self._log("上位机已就绪。协议：华源交流回馈式负载 MODBUS RTU V1.4")
        self._log("提示：没有真机时可选「模拟从站」链路，或另起 python -m modules.huayuan_acload_host.core.simulator")

    # ---------------------------------------------------------- 连接区
    def _build_conn_card(self) -> Card:
        card = Card("连接配置",
                    "华源交流回馈式负载 · MODBUS RTU V1.4 · 8 数据位无校验 1 停止位；"
                    "功率单位 0.1W、电流/电压 0.001（写错单位设备回异常码 03）")
        g = QGridLayout()
        g.setSpacing(6)
        g.setVerticalSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("通讯方式"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["串口", "网口(TCP)", "网口(UDP)", "模拟从站"])
        self.cmb_mode.currentIndexChanged.connect(self._rebuild_params)
        top.addWidget(self.cmb_mode)

        self.lbl_port = QLabel("端口")
        top.addWidget(self.lbl_port)
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setStyleSheet("QComboBox{min-width:120px;}")
        top.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_ports)
        top.addWidget(self.btn_refresh)

        self.lbl_baud = QLabel("波特率")
        top.addWidget(self.lbl_baud)
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        top.addWidget(self.cmb_baud)
        self.lbl_fmt = QLabel("8/N/1")
        top.addWidget(self.lbl_fmt)

        self.lbl_host = QLabel("地址")
        top.addWidget(self.lbl_host)
        self.ed_host = QLineEdit()
        self.ed_host.setFixedWidth(130)
        top.addWidget(self.ed_host)

        self.lbl_tcp_port = QLabel("端口")
        top.addWidget(self.lbl_tcp_port)
        self.spn_tcp_port = QSpinBox()
        self.spn_tcp_port.setRange(1, 65535)
        self.spn_tcp_port.setFixedWidth(80)
        top.addWidget(self.spn_tcp_port)

        self.chk_mbap = QCheckBox("MBAP(标准 Modbus TCP)")
        top.addWidget(self.chk_mbap)
        self.lbl_mbap_hint = QLabel("不勾选=裸 RTU 帧透传")
        top.addWidget(self.lbl_mbap_hint)

        # 从站地址与操作按钮紧随波特率之后（单行排布，用户要求）
        top.addSpacing(12)
        top.addWidget(QLabel("从站地址"))
        self.spn_unit = QSpinBox()
        self.spn_unit.setRange(0, 254)
        self.spn_unit.setFixedWidth(80)
        top.addWidget(self.spn_unit)
        top.addWidget(QLabel("(0=广播)"))
        top.addSpacing(12)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.setStyleSheet(BTN_CSS)
        self.btn_conn.clicked.connect(self._toggle_conn)
        top.addWidget(self.btn_conn)
        self.btn_adv = QPushButton("高级…")
        self.btn_adv.clicked.connect(self._open_advanced)
        top.addWidget(self.btn_adv)
        self.lbl_lamp = QLabel("○ 未连接")
        self.lbl_lamp.setStyleSheet("color:#6B7280;")
        top.addWidget(self.lbl_lamp)
        top.addStretch(1)
        g.addLayout(top, 0, 0)

        card.body_lay.addLayout(g)
        self._load_conn_ui()
        self._rebuild_params()
        return card

    def _load_conn_ui(self):
        c = self.cfg
        self.cmb_mode.setCurrentText({"serial": "串口", "tcp": "网口(TCP)",
                                      "udp": "网口(UDP)"}.get(c.get("conn_mode"), "串口"))
        self.cmb_port.setCurrentText(str(c.get("serial_port", "")))
        self.cmb_baud.setCurrentText(str(int(c.get("baud", 9600))))
        self.ed_host.setText(str(c.get("host", "127.0.0.1")))
        self.spn_tcp_port.setValue(int(c.get("tcp_port", 7000)))
        self.chk_mbap.setChecked(bool(c.get("mbap", False)))
        self.spn_unit.setValue(int(c.get("unit", 1)))

    def _rebuild_params(self):
        serial = self.cmb_mode.currentText() == "串口"
        net = self.cmb_mode.currentText().startswith("网口")
        sim = self.cmb_mode.currentText() == "模拟从站"
        self.lbl_port.setVisible(serial)
        self.cmb_port.setVisible(serial)
        self.btn_refresh.setVisible(serial)
        self.lbl_baud.setVisible(serial)
        self.cmb_baud.setVisible(serial)
        self.lbl_fmt.setVisible(serial)
        self.lbl_host.setVisible(net)
        self.ed_host.setVisible(net)
        self.lbl_tcp_port.setVisible(net or sim)
        self.spn_tcp_port.setVisible(net or sim)
        self.chk_mbap.setVisible(net or sim)
        self.lbl_mbap_hint.setVisible(net or sim)

    def _refresh_ports(self):
        ports = []
        try:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        except Exception:  # noqa: BLE001
            ports = []
        cur = self.cmb_port.currentText()
        self.cmb_port.clear()
        self.cmb_port.addItems(ports)
        if ports and not cur:
            self.cmb_port.setCurrentText(ports[0])
        elif cur:
            self.cmb_port.setCurrentText(cur)

    def _set_lamp(self, color: str, text: str):
        self.lbl_lamp.setText(("● " if self.connected or self.connecting else "○ ") + text)
        self.lbl_lamp.setStyleSheet(f"color:{color};")

    # ---------------------------------------------------------- 页签
    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_tab_run(), "运行控制")
        tabs.addTab(self._build_tab_ch(), "通道设置")
        tabs.addTab(self._build_tab_info(), "设备信息")
        tabs.addTab(self._build_tab_dbg(), "手动调试")
        return tabs

    # ---------------- 页签 1：运行控制
    def _build_tab_run(self) -> QWidget:
        w = QWidget()
        # 2×2 并排：左列 输出控制/模式设置，右列 总设定/一键下发（用户要求图二放图三右侧）
        grid = QGridLayout(w)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(10)

        out = QGroupBox("输出控制")
        ol = QHBoxLayout(out)
        ol.setSpacing(12)
        self.lbl_big = QLabel("已停止")
        self.lbl_big.setAlignment(Qt.AlignCenter)
        self.lbl_big.setFixedHeight(64)
        self.lbl_big.setStyleSheet(
            "background:#9AA1AC;color:#FFFFFF;font-size:22px;font-weight:bold;"
            "border-radius:6px;min-width:220px;")
        ol.addWidget(self.lbl_big)
        bs = QVBoxLayout()
        bs.setSpacing(4)
        self.btn_on = QPushButton("开启输出")
        self.btn_on.setStyleSheet(BTN_CSS)
        self.btn_on.clicked.connect(lambda: self._on_output(True))
        bs.addWidget(self.btn_on)
        self.btn_off = QPushButton("关闭输出")
        self.btn_off.setStyleSheet(BTN_CSS)
        self.btn_off.clicked.connect(lambda: self._on_output(False))
        bs.addWidget(self.btn_off)
        btn_clr = QPushButton("清除故障")
        btn_clr.setStyleSheet(BTN_CSS)
        btn_clr.clicked.connect(self._clear_fault)
        bs.addWidget(btn_clr)
        ol.addLayout(bs)
        self.lbl_fault_brief = QLabel("无故障")
        self.lbl_fault_brief.setStyleSheet("color:#6B7280;")
        ol.addWidget(self.lbl_fault_brief)
        ol.addStretch(1)
        grid.addWidget(out, 0, 0)

        mode = QGroupBox("模式设置")
        ml = QGridLayout(mode)
        ml.setSpacing(8)
        ml.addWidget(QLabel("操作模式"), 0, 0)
        self.rdo_mode_op = []
        hb = QHBoxLayout()
        hb.setSpacing(8)
        for val, text in MODE_LABELS.items():
            r = QRadioButton(text)
            r.setChecked(val == 0)
            self.rdo_mode_op.append(r)
            hb.addWidget(r)
        hb.addSpacing(8)
        btn_op = QPushButton("下发")
        btn_op.setStyleSheet(BTN_CSS)
        btn_op.clicked.connect(self._send_mode_op)
        hb.addWidget(btn_op)
        hb.addStretch(1)
        ml.addLayout(hb, 0, 1)
        ml.addWidget(QLabel("控制模式"), 1, 0)
        self.rdo_mode_ctrl = []
        hb2 = QHBoxLayout()
        hb2.setSpacing(8)
        for val, text in CTRL_LABELS.items():
            r = QRadioButton(text)
            r.setChecked(val == 0)
            self.rdo_mode_ctrl.append(r)
            hb2.addWidget(r)
        hb2.addSpacing(8)
        btn_ctrl = QPushButton("下发")
        btn_ctrl.setStyleSheet(BTN_CSS)
        btn_ctrl.clicked.connect(self._send_mode_ctrl)
        hb2.addWidget(btn_ctrl)
        hb2.addStretch(1)
        ml.addLayout(hb2, 1, 1)
        ml.setColumnStretch(1, 1)
        grid.addWidget(mode, 1, 0)

        tot = QGroupBox("单相 / 三相统调 总设定")
        tl = QGridLayout(tot)
        tl.setSpacing(8)
        tl.addWidget(QLabel("总功率"), 0, 0)
        self.spn_total_p = QDoubleSpinBox()
        self.spn_total_p.setRange(0, 10_000_000)
        self.spn_total_p.setDecimals(1)
        self.spn_total_p.setFixedWidth(140)
        tl.addWidget(self.spn_total_p, 0, 1)
        tl.addWidget(QLabel("W"), 0, 2)
        btn_p = QPushButton("下发")
        btn_p.setStyleSheet(BTN_CSS)
        btn_p.clicked.connect(self._send_total_power)
        tl.addWidget(btn_p, 0, 3)
        tl.addWidget(QLabel("（寄存器 0x38，单位 0.1W）"), 0, 4)
        tl.addWidget(QLabel("总电流"), 1, 0)
        self.spn_total_i = QDoubleSpinBox()
        self.spn_total_i.setRange(0, 10_000_000)
        self.spn_total_i.setDecimals(3)
        self.spn_total_i.setFixedWidth(140)
        tl.addWidget(self.spn_total_i, 1, 1)
        tl.addWidget(QLabel("A"), 1, 2)
        btn_i = QPushButton("下发")
        btn_i.setStyleSheet(BTN_CSS)
        btn_i.clicked.connect(self._send_total_current)
        tl.addWidget(btn_i, 1, 3)
        tl.addWidget(QLabel("（寄存器 0x3E，单位 0.001A）"), 1, 4)
        tl.setColumnStretch(5, 1)
        grid.addWidget(tot, 0, 1)

        one = QGroupBox("一键下发（推荐）")
        ol2 = QVBoxLayout(one)
        ol2.setSpacing(8)
        hint = QLabel("按手册要求的顺序执行：\n"
                      "    关闭输出 → 写入操作模式 → 写入控制模式 → 写入总功率/总电流 "
                      "→ 写入各通道设定 → 开启输出")
        hint.setStyleSheet("color:#6B7280;")
        hint.setWordWrap(True)
        ol2.addWidget(hint)
        hb3 = QHBoxLayout()
        btn_all = QPushButton("一键下发全部参数")
        btn_all.setStyleSheet(BTN_CSS)
        btn_all.clicked.connect(self._apply_all)
        hb3.addWidget(btn_all)
        hb3.addStretch(1)
        ol2.addLayout(hb3)
        grid.addWidget(one, 1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return w

    # ---------------- 页签 2：通道设置
    def _build_tab_ch(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("全体通道功率"))
        self.spn_bulk_p = QDoubleSpinBox()
        self.spn_bulk_p.setRange(0, 10_000_000)
        self.spn_bulk_p.setDecimals(1)
        self.spn_bulk_p.setFixedWidth(120)
        top.addWidget(self.spn_bulk_p)
        top.addWidget(QLabel("W"))
        btn_fill = QPushButton("填入下表全部通道")
        btn_fill.setStyleSheet(BTN_CSS)
        btn_fill.clicked.connect(self._bulk_fill)
        top.addWidget(btn_fill)
        top.addSpacing(14)
        btn_sel = QPushButton("下发选中通道")
        btn_sel.setStyleSheet(BTN_CSS)
        btn_sel.clicked.connect(self._send_selected)
        top.addWidget(btn_sel)
        btn_all = QPushButton("下发全部通道")
        btn_all.setStyleSheet(BTN_CSS)
        btn_all.clicked.connect(self._send_all_channels)
        top.addWidget(btn_all)
        top.addStretch(1)
        v.addLayout(top)

        hint = QLabel("双击「设定功率」或「设定电流」单元格即可编辑。"
                      "电流设定仅对通道 1~3（A/B/C 相）有效，与手册 0xE0~0xE5 对应。")
        hint.setStyleSheet("color:#6B7280;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.tree_ch = QTableWidget(rg.CHANNEL_COUNT, 7)
        self.tree_ch.setHorizontalHeaderLabels(
            ["通道", "相别", "设定功率(W)", "设定电流(A)", "实测电压(V)", "实测电流(A)", "实测功率(W)"])
        self.tree_ch.verticalHeader().setVisible(False)
        self.tree_ch.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.tree_ch.setSelectionBehavior(QTableWidget.SelectRows)
        self.tree_ch.setAlternatingRowColors(True)
        hh = self.tree_ch.horizontalHeader()
        hh.setStretchLastSection(True)
        from PyQt5.QtWidgets import QHeaderView
        for i, wdt in enumerate((60, 60, 110, 110, 110, 110, 110)):
            self.tree_ch.setColumnWidth(i, wdt)
        self.tree_ch.itemChanged.connect(self._on_ch_item_changed)
        self._fill_channel_rows()
        v.addWidget(self.tree_ch, 1)
        return w

    def _fill_channel_rows(self):
        for ch in range(1, rg.CHANNEL_COUNT + 1):
            r = ch - 1
            phase = rg.PHASE_NAMES.get(ch, "—")
            items = [QTableWidgetItem(str(ch)), QTableWidgetItem(phase),
                     QTableWidgetItem("%.1f" % self.set_power[ch]),
                     QTableWidgetItem("%.3f" % self.set_current[ch] if ch in rg.PHASE_CHANNELS else "—"),
                     QTableWidgetItem("0.000"), QTableWidgetItem("0.000"), QTableWidgetItem("0.0")]
            for c, it in enumerate(items):
                it.setTextAlignment(Qt.AlignCenter)
                if c >= 4 or (c == 3 and ch not in rg.PHASE_CHANNELS):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 0:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.tree_ch.setItem(r, c, it)

    def _on_ch_item_changed(self, item: QTableWidgetItem):
        col, row = item.column(), item.row()
        ch = row + 1
        if col not in (2, 3):
            return
        if col == 3 and ch not in rg.PHASE_CHANNELS:
            return
        try:
            val = float(item.text())
        except ValueError:
            val = -1.0
        if val < 0:
            QMessageBox.information(self, "输入有误", "请输入非负数字。")
            cur = self.set_power[ch] if col == 2 else self.set_current[ch]
            item.setText("%.1f" % cur if col == 2 else "%.3f" % cur)
            return
        if col == 2:
            self.set_power[ch] = val
            item.setText("%.1f" % val)
        else:
            self.set_current[ch] = val
            item.setText("%.3f" % val)

    def _bulk_fill(self):
        v = self.spn_bulk_p.value()
        for ch in range(1, rg.CHANNEL_COUNT + 1):
            self.set_power[ch] = v
            self.tree_ch.item(ch - 1, 2).setText("%.1f" % v)

    # ---------------- 页签 3：设备信息
    def _build_tab_info(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        box = QGroupBox("基本信息")
        bl = QGridLayout(box)
        bl.setSpacing(6)
        self.info_vars = {}
        rows = [("version", "版本号"), ("serial", "序列号"), ("run", "运行状态"),
                ("mode_op", "操作模式"), ("mode_ctrl", "控制模式"), ("status", "输出状态原始值")]
        for i, (key, label) in enumerate(rows):
            bl.addWidget(QLabel(label + "："), i, 0, Qt.AlignRight)
            lab = QLabel("—")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info_vars[key] = lab
            bl.addWidget(lab, i, 1, Qt.AlignLeft)
        bl.setColumnStretch(1, 1)
        v.addWidget(box)

        fl = QGroupBox("故障代码（手册第七节）")
        ll = QVBoxLayout(fl)
        self.tree_fault = QTableWidget(len(rg.FAULT_BITS), 3)
        self.tree_fault.setHorizontalHeaderLabels(["BIT 位", "故障含义", "状态"])
        self.tree_fault.verticalHeader().setVisible(False)
        self.tree_fault.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tree_fault.setAlternatingRowColors(True)
        from PyQt5.QtWidgets import QHeaderView
        self.tree_fault.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for r, (bit, name) in enumerate(sorted(rg.FAULT_BITS.items())):
            for c, text in enumerate(("bit%d" % bit, name, "正常")):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter if c != 1 else Qt.AlignLeft)
                self.tree_fault.setItem(r, c, it)
        self.tree_fault.resizeColumnToContents(0)
        self.tree_fault.resizeColumnToContents(2)
        ll.addWidget(self.tree_fault)
        v.addWidget(fl, 1)

        note = QLabel("故障寄存器：0x7E(bit47~32) / 0x7F(bit31~16) / 0x80(bit15~0)，"
                      "当前手册仅定义了 bit0~bit7，其余位预留。")
        note.setStyleSheet("color:#6B7280;")
        note.setWordWrap(True)
        v.addWidget(note)
        return w

    # ---------------- 页签 4：手动调试
    def _build_tab_dbg(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        rd = QGroupBox("读寄存器（0x03）")
        rl = QVBoxLayout(rd)
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(QLabel("起始地址(hex)"))
        self.ed_rd_addr = QLineEdit("0x60")
        self.ed_rd_addr.setFixedWidth(90)
        r1.addWidget(self.ed_rd_addr)
        r1.addWidget(QLabel("数量"))
        self.spn_rd_n = QSpinBox()
        self.spn_rd_n.setRange(1, 125)
        self.spn_rd_n.setValue(33)
        self.spn_rd_n.setFixedWidth(80)
        r1.addWidget(self.spn_rd_n)
        btn_rd = QPushButton("读取")
        btn_rd.setStyleSheet(BTN_CSS)
        btn_rd.clicked.connect(self._do_read)
        r1.addWidget(btn_rd)
        r1.addStretch(1)
        rl.addLayout(r1)

        self.tree_dbg = QTableWidget(0, 4)
        self.tree_dbg.setHorizontalHeaderLabels(["地址", "HEX", "DEC", "说明"])
        self.tree_dbg.verticalHeader().setVisible(False)
        self.tree_dbg.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tree_dbg.setAlternatingRowColors(True)
        from PyQt5.QtWidgets import QHeaderView
        self.tree_dbg.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        rl.addWidget(self.tree_dbg, 1)
        v.addWidget(rd, 1)

        wr = QGroupBox("写寄存器")
        wl = QGridLayout(wr)
        wl.setSpacing(8)
        wl.addWidget(QLabel("地址(hex)"), 0, 0)
        self.ed_wr_addr = QLineEdit()
        self.ed_wr_addr.setFixedWidth(110)
        wl.addWidget(self.ed_wr_addr, 0, 1)
        wl.addWidget(QLabel("值(十进制)"), 0, 2)
        self.ed_wr_val = QLineEdit()
        self.ed_wr_val.setFixedWidth(110)
        wl.addWidget(self.ed_wr_val, 0, 3)
        btn_w1 = QPushButton("写单个 (0x06)")
        btn_w1.setStyleSheet(BTN_CSS)
        btn_w1.clicked.connect(self._do_write_single)
        wl.addWidget(btn_w1, 0, 4)
        wl.addWidget(QLabel("多个值用逗号分隔（最多 123 个）"), 1, 0, 1, 5)
        self.ed_wr_multi = QLineEdit()
        wl.addWidget(self.ed_wr_multi, 2, 0, 1, 4)
        btn_w2 = QPushButton("写多个 (0x10)")
        btn_w2.setStyleSheet(BTN_CSS)
        btn_w2.clicked.connect(self._do_write_multi)
        wl.addWidget(btn_w2, 2, 4)
        wl.setColumnStretch(1, 1)
        wl.setColumnStretch(3, 1)
        v.addWidget(wr)

        note = QLabel("注意：这里填的地址是「协议表地址」，软件会自动叠加高级设置里的地址偏移。"
                      "手动写入不做量程保护，请谨慎操作。")
        note.setStyleSheet("color:#6B7280;")
        note.setWordWrap(True)
        v.addWidget(note)
        return w

    # ---------------------------------------------------------- 左侧实时监控
    def _build_monitor(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(420)
        inner = QWidget()
        # 2×3 并排（用户要求）：上排 输出状态/总输出/设备，下排 A/B/C 三相对照
        grid = QGridLayout(inner)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(8)
        self.mon = {}

        def section(title, r, c):
            box = QGroupBox(title)
            vl = QVBoxLayout(box)
            vl.setSpacing(2)
            grid.addWidget(box, r, c)
            return vl

        def row(parent, label, big=False):
            hb = QHBoxLayout()
            lab = QLabel(label)
            lab.setStyleSheet("color:#6B7280;")
            lab.setFixedWidth(56)
            hb.addWidget(lab)
            val = QLabel("—")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            f = val.font()
            f.setPointSize(12 if big else 10)
            f.setBold(big)
            val.setFont(f)
            hb.addWidget(val)
            parent.addLayout(hb)
            return val

        st = section("输出状态", 0, 0)
        self.lbl_mon_run = QLabel("○ 已停止")
        f = self.lbl_mon_run.font()
        f.setPointSize(12)
        f.setBold(True)
        self.lbl_mon_run.setFont(f)
        self.lbl_mon_run.setStyleSheet("color:#6B7280;")
        st.addWidget(self.lbl_mon_run)
        self.mon["mode"] = row(st, "运行模式")
        self.mon["ctrl"] = row(st, "控制模式")
        self.mon["fault"] = row(st, "故障")

        tp = section("总输出", 0, 1)
        self.mon["ptotal"] = row(tp, "总功率", big=True)

        info = section("设备", 0, 2)
        self.mon["ver"] = row(info, "版本号")
        self.mon["sn"] = row(info, "序列号")

        for idx, name in enumerate(("A 相", "B 相", "C 相")):
            box = section(name, 1, idx)
            self.mon["v%d" % idx] = row(box, "电压")
            self.mon["i%d" % idx] = row(box, "电流")
            self.mon["p%d" % idx] = row(box, "功率")

        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        scroll.setWidget(inner)
        return scroll

    # ---------------------------------------------------------- 底部日志
    def _build_log_group(self) -> QGroupBox:
        box = QGroupBox("运行日志")
        self._log_group = box   # 供外层设最小高度（打开即可见日志区）
        lay = QVBoxLayout(box)
        lay.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.chk_wire = QCheckBox("显示通讯报文")
        self.chk_wire.setChecked(bool(self.cfg["show_wire"]))
        self.chk_wire.toggled.connect(self._on_wire_toggle)
        bar.addWidget(self.chk_wire)
        btn_clr = QPushButton("清空日志")
        btn_clr.setStyleSheet(BTN_CSS)
        btn_clr.clicked.connect(self._clear_log)
        bar.addWidget(btn_clr)
        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        bar.addWidget(self.chk_autoscroll)
        self.lbl_poll = QLabel("")
        self.lbl_poll.setStyleSheet("color:#6B7280;")
        bar.addWidget(self.lbl_poll)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setMaximumBlockCount(3000)   # 行数上限，长跑不吃内存
        f = QFont("Consolas", 9)
        self.txt.setFont(f)
        lay.addWidget(self.txt, 1)
        return box

    def _on_wire_toggle(self, on: bool):
        self.worker.log_wire = bool(on)
        self.cfg["show_wire"] = bool(on)

    def _clear_log(self):
        self.txt.clear()

    def _log(self, msg: str, kind: str = "sys"):
        color = {"tx": "#1668DC", "rx": "#16A34A", "err": "#DC2626"}.get(kind, "#6B7280")
        self.txt.appendHtml(
            f'<span style="color:{color}">[{time.strftime("%H:%M:%S")}] {msg}</span>')
        if self.chk_autoscroll.isChecked():
            sb = self.txt.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ---------------------------------------------------------- 命令提交
    def _guard(self) -> bool:
        if not self.connected:
            QMessageBox.warning(self, "未连接", "请先连接设备。")
            return False
        return True

    def _submit_ops(self, ops, label: str):
        if not self._guard():
            return
        self._log("下发：%s" % label)
        self.cmd_q.put(("ops", (ops, label)))

    def _send_mode_op(self):
        val = next(i for i, r in enumerate(self.rdo_mode_op) if r.isChecked())
        self._submit_ops([("w16", rg.ADDR_MODE_OP, val)],
                         "下发操作模式 %s" % MODE_LABELS[val])

    def _send_mode_ctrl(self):
        val = next(i for i, r in enumerate(self.rdo_mode_ctrl) if r.isChecked())
        self._submit_ops([("w16", rg.ADDR_MODE_CTRL, val)],
                         "下发控制模式 %s" % CTRL_LABELS[val])

    def _send_total_power(self):
        v = self.spn_total_p.value()
        try:
            ops = self.builder.build_apply_ops(total_power=v, output_on=False,
                                               power_off_first=False)
        except RangeError as e:
            QMessageBox.information(self, "超出限值", str(e))
            return
        self._submit_ops(ops, "下发总功率 %.1f W" % v)

    def _send_total_current(self):
        v = self.spn_total_i.value()
        try:
            ops = self.builder.build_apply_ops(total_current=v, output_on=False,
                                               power_off_first=False)
        except RangeError as e:
            QMessageBox.information(self, "超出限值", str(e))
            return
        self._submit_ops(ops, "下发总电流 %.3f A" % v)

    def _send_channels(self, chans):
        try:
            ops = self.builder.build_apply_ops(
                channel_power={ch: self.set_power[ch] for ch in chans},
                channel_current={ch: self.set_current[ch] for ch in chans
                                 if ch in rg.PHASE_CHANNELS},
                output_on=False, power_off_first=False)
        except RangeError as e:
            QMessageBox.information(self, "超出限值", str(e))
            return
        self._submit_ops(ops, "下发通道参数（%d 个通道）" % len(chans))

    def _send_selected(self):
        rows = sorted({i.row() + 1 for i in self.tree_ch.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "提示", "请先在表格里选中要下发的通道。")
            return
        self._send_channels(rows)

    def _send_all_channels(self):
        self._send_channels(list(range(1, rg.CHANNEL_COUNT + 1)))

    def _on_output(self, on: bool):
        if not self._guard():
            return
        if on:
            dlg = ConfirmOutputDialog(
                "华源交流回馈式负载", "开启输出",
                "负载将按当前设定开始拉载，回馈电网。开启前确认接线牢固、散热与电网"
                "回馈条件允许，现场人员已知晓。",
                "总功率 %.1f W / 总电流 %.3f A" % (self.spn_total_p.value(),
                                                   self.spn_total_i.value()), self)
            if dlg.exec_() != ConfirmOutputDialog.Accepted:
                return
        self._submit_ops([("w16", rg.ADDR_OUTPUT_CTRL, 1 if on else 0)],
                         "开启输出" if on else "关闭输出")

    def _apply_all(self):
        if not self._guard():
            return
        tp = self.spn_total_p.value()
        ti = self.spn_total_i.value()
        try:
            ops = self.builder.build_apply_ops(
                mode_op=next(i for i, r in enumerate(self.rdo_mode_op) if r.isChecked()),
                mode_ctrl=next(i for i, r in enumerate(self.rdo_mode_ctrl) if r.isChecked()),
                total_power=tp, total_current=ti,
                channel_power=dict(self.set_power),
                channel_current=dict(self.set_current),
                output_on=True)
        except RangeError as e:
            QMessageBox.information(self, "超出限值", str(e))
            return
        dlg = ConfirmOutputDialog(
            "华源交流回馈式负载", "一键下发全部参数（含开启输出）",
            "将按手册顺序下发操作模式/控制模式/总设定/各通道设定并开启输出，"
            "负载立即开始拉载。确认接线、量程与现场安全条件已具备。",
            "总功率 %.1f W / 总电流 %.3f A / %d 通道" % (tp, ti, rg.CHANNEL_COUNT), self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return
        self._submit_ops(ops, "一键下发全部参数")

    def _clear_fault(self):
        if not self._guard():
            return
        ret = QMessageBox.question(self, "确认", "确定向设备发送「清除故障」指令？",
                                   QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self._submit_ops([("w16", rg.ADDR_CLEAR_FAULT, 1)], "清除故障")

    def _do_read(self):
        if not self._guard():
            return
        try:
            addr = int(self.ed_rd_addr.text().strip(), 16)
        except ValueError:
            QMessageBox.information(self, "输入有误",
                                    "地址请填十六进制（如 0x60），数量填十进制整数。")
            return
        n = self.spn_rd_n.value()
        self.cmd_q.put(("read", (addr, n)))

    def _parse_hex_addr(self):
        try:
            return int(self.ed_wr_addr.text().strip(), 16)
        except ValueError:
            QMessageBox.information(self, "输入有误", "地址请填十六进制，如 0x38。")
            return None

    def _do_write_single(self):
        if not self._guard():
            return
        addr = self._parse_hex_addr()
        if addr is None:
            return
        try:
            val = int(self.ed_wr_val.text().strip(), 0)
        except ValueError:
            QMessageBox.information(self, "输入有误", "值请填十进制整数（0~65535）。")
            return
        if not 0 <= val <= 0xFFFF:
            QMessageBox.information(self, "输入有误", "值需在 0~65535 之间。")
            return
        self._submit_ops([("w16", addr, val)], "手动写单个 0x%02X ← %d" % (addr, val))

    def _do_write_multi(self):
        if not self._guard():
            return
        addr = self._parse_hex_addr()
        if addr is None:
            return
        try:
            vals = [int(x.strip(), 0) for x in self.ed_wr_multi.text().split(",") if x.strip()]
        except ValueError:
            QMessageBox.information(self, "输入有误", "多个值请用英文逗号分隔的十进制整数。")
            return
        if not vals:
            QMessageBox.information(self, "输入有误", "请填写至少一个值。")
            return
        if len(vals) > 123:
            QMessageBox.information(self, "输入有误", "一次最多写 123 个值。")
            return
        ops = [("w16", addr + i, v) for i, v in enumerate(vals)]
        self._submit_ops(ops, "手动写多个 0x%02X 起 %d 个" % (addr, len(vals)))

    # ---------------------------------------------------------- 连接管理
    def _toggle_conn(self):
        if self.connected or self.connecting:
            self.cmd_q.put(("disconnect", None))
            return
        cfg = dict(self.cfg)
        label = self.cmb_mode.currentText()
        cfg["conn_mode"] = {"串口": "serial", "网口(TCP)": "tcp", "网口(UDP)": "udp",
                            "模拟从站": "sim"}[label]
        if cfg["conn_mode"] == "serial":
            port = self.cmb_port.currentText().strip()
            if not port:
                QMessageBox.information(self, "缺少参数", "请选择串口端口。")
                return
            cfg["serial_port"] = port
            cfg["baud"] = int(self.cmb_baud.currentText())
        elif cfg["conn_mode"] == "sim":
            cfg["tcp_port"] = int(self.spn_tcp_port.value())
            cfg["mbap"] = bool(self.chk_mbap.isChecked())
        else:
            cfg["host"] = self.ed_host.text().strip()
            cfg["tcp_port"] = int(self.spn_tcp_port.value())
            cfg["mbap"] = bool(self.chk_mbap.isChecked())
        cfg["unit"] = int(self.spn_unit.value())
        self.cfg.update(cfg)
        self.connecting = True
        self.btn_conn.setEnabled(False)
        self._set_lamp("#D97706", "正在连接…")
        self._log("正在连接：%s" % label)
        self.cmd_q.put(("connect", cfg))

    def _on_connected(self, payload):
        desc, ver, serial = payload
        self.connected = True
        self.connecting = False
        self.btn_conn.setEnabled(True)
        self.btn_conn.setObjectName("btnConnected")
        self.btn_conn.setText("断开")
        self.btn_conn.style().unpolish(self.btn_conn)
        self.btn_conn.style().polish(self.btn_conn)
        self._set_lamp("#047857", "已连接 · %s" % desc)
        self._log("连接成功：%s，设备版本号 %d（%s）" % (desc, ver, rg.decode_version(ver)))
        self._serial = serial or 0
        sn = str(serial) if serial else "读取失败（可忽略）"
        self.info_vars["serial"].setText(sn)
        self.mon["sn"].setText(sn)

    def _on_disconnected(self):
        self.connected = False
        self.connecting = False
        self.btn_conn.setEnabled(True)
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.setText("连接")
        self.btn_conn.style().unpolish(self.btn_conn)
        self.btn_conn.style().polish(self.btn_conn)
        self._set_lamp("#6B7280", "未连接")
        self._log("已断开连接")
        self.lbl_poll.setText("")
        self._reset_readings()

    # ---------------------------------------------------------- 结果处理
    def _drain(self):
        try:
            while True:
                kind, payload = self.res_q.get_nowait()
                self.sig.emit(kind, payload)
        except queue.Empty:
            pass

    def _handle(self, kind: str, payload):
        if kind == "poll":
            snap, chans = payload
            self._apply_snapshot(snap, chans)
        elif kind == "poll_error":
            self.lbl_poll.setText("读取异常：%s" % payload)
            self.lbl_poll.setStyleSheet("color:#D97706;")
        elif kind == "poll_stopped":
            self._set_lamp("#DC2626", "通讯中断")
            self.lbl_poll.setText("已停止自动轮询")
            self.lbl_poll.setStyleSheet("color:#DC2626;")
            self._log("连续 3 次轮询失败，已停止自动轮询：%s" % payload, "err")
            QMessageBox.warning(self, "通讯中断",
                                "连续 3 次读取失败，已停止自动轮询。\n\n最后一次错误：%s" % payload)
        elif kind == "connected":
            self._on_connected(payload)
        elif kind == "disconnected":
            self._on_disconnected()
        elif kind == "ops_done":
            self._log("下发完成：%s" % payload)
        elif kind == "read_result":
            self._show_read_result(*payload)
        elif kind == "wire":
            direction, data = payload
            self._log("%s  %s" % (direction, mb.hexs(data)),
                      "tx" if direction == "TX" else "rx")
        elif kind == "error":
            op, msg, exc = payload
            if op == "connect":
                self.connecting = False
                self.connected = False
                self.btn_conn.setEnabled(True)
                self.btn_conn.setObjectName("btnConnect")
                self.btn_conn.setText("连接")
                self.btn_conn.style().unpolish(self.btn_conn)
                self.btn_conn.style().polish(self.btn_conn)
                self._set_lamp("#6B7280", "未连接")
                self._log("连接失败：%s" % msg, "err")
                QMessageBox.critical(self, "连接失败", "%s\n\n%s" % (msg, _hint(msg)))
            elif op == "poll":
                pass
            else:
                self._log("操作失败（%s）：%s" % (op, msg), "err")
                QMessageBox.critical(self, "操作失败", "%s\n\n%s" % (msg, _hint(msg)))

    def _merge_measure(self, snap, chans) -> dict:
        """合并两路数据源：A/B/C 相电压电流在状态块、功率在通道块，统一成每通道 (v,i,p)。"""
        out = dict(chans or {})
        for i, ch in enumerate(rg.PHASE_CHANNELS):
            m = out.get(ch)
            if m is None:
                m = ChannelMeasure(ch)
                out[ch] = m
            m.voltage = snap.voltage[i]
            m.current = snap.current[i]
        return out

    def _apply_snapshot(self, snap, chans):
        meas = self._merge_measure(snap, chans)

        if snap.has_fault:
            self.lbl_big.setText("故障")
            self.lbl_big.setStyleSheet(
                "background:#DC2626;color:#FFFFFF;font-size:22px;font-weight:bold;"
                "border-radius:6px;min-width:220px;")
            self.lbl_mon_run.setText("● 故障")
            self.lbl_mon_run.setStyleSheet("color:#DC2626;")
            self.lbl_fault_brief.setText(
                "故障：" + ("、".join(snap.active_faults()) or "有故障"))
            self.lbl_fault_brief.setStyleSheet("color:#DC2626;")
        elif snap.running:
            self.lbl_big.setText("运行中")
            self.lbl_big.setStyleSheet(
                "background:#16A34A;color:#FFFFFF;font-size:22px;font-weight:bold;"
                "border-radius:6px;min-width:220px;")
            self.lbl_mon_run.setText("● 运行中")
            self.lbl_mon_run.setStyleSheet("color:#16A34A;")
            self.lbl_fault_brief.setText("无故障")
            self.lbl_fault_brief.setStyleSheet("color:#16A34A;")
        else:
            self.lbl_big.setText("已停止")
            self.lbl_big.setStyleSheet(
                "background:#9AA1AC;color:#FFFFFF;font-size:22px;font-weight:bold;"
                "border-radius:6px;min-width:220px;")
            self.lbl_mon_run.setText("○ 已停止")
            self.lbl_mon_run.setStyleSheet("color:#6B7280;")
            self.lbl_fault_brief.setText("无故障")
            self.lbl_fault_brief.setStyleSheet("color:#6B7280;")

        self.mon["mode"].setText(snap.mode_op_name)
        self.mon["ctrl"].setText(snap.mode_ctrl_name)
        self.mon["fault"].setText("有" if snap.has_fault else "无")
        self.mon["ptotal"].setText("%.1f W" % snap.power_total)
        for i in range(3):
            self.mon["v%d" % i].setText("%.2f V" % snap.voltage[i])
            self.mon["i%d" % i].setText("%.3f A" % snap.current[i])
            m = meas.get(i + 1)
            self.mon["p%d" % i].setText("%.1f W" % (m.power if m else 0.0))
        self.mon["ver"].setText(snap.version_name)

        for i, rdo in enumerate(self.rdo_mode_op):
            rdo.blockSignals(True)
            rdo.setChecked(i == snap.mode_op)
            rdo.blockSignals(False)
        for i, rdo in enumerate(self.rdo_mode_ctrl):
            rdo.blockSignals(True)
            rdo.setChecked(i == snap.mode_ctrl)
            rdo.blockSignals(False)

        self.info_vars["version"].setText("%d（%s）" % (snap.version_raw, snap.version_name))
        self.info_vars["run"].setText("运行中" if snap.running else "已停止")
        self.info_vars["mode_op"].setText(snap.mode_op_name)
        self.info_vars["mode_ctrl"].setText(snap.mode_ctrl_name)
        self.info_vars["status"].setText("0x%08X  (低字 0x%04X / 高字 0x%04X)"
                                         % (snap.status_raw, snap.status_raw & 0xFFFF,
                                            (snap.status_raw >> 16) & 0xFFFF))
        for bit in rg.FAULT_BITS:
            on = bool(snap.fault_bits & (1 << bit))
            item = self.tree_fault.item(bit, 2)
            item.setText("★ 触发" if on else "正常")
            color = QColor("#DC2626") if on else QColor("#047857")
            for c in range(3):
                self.tree_fault.item(bit, c).setForeground(color)

        if chans:
            for ch in range(1, rg.CHANNEL_COUNT + 1):
                m = meas.get(ch)
                if m is None:
                    continue
                for col, text in ((4, "%.3f" % m.voltage), (5, "%.3f" % m.current),
                                  (6, "%.1f" % m.power)):
                    it = self.tree_ch.item(ch - 1, col)
                    it.setText(text)
        self.lbl_poll.setText("最后刷新 %s" % time.strftime("%H:%M:%S"))
        self.lbl_poll.setStyleSheet("color:#6B7280;")

    def _reset_readings(self):
        self.lbl_big.setText("已停止")
        self.lbl_big.setStyleSheet(
            "background:#9AA1AC;color:#FFFFFF;font-size:22px;font-weight:bold;"
            "border-radius:6px;min-width:220px;")
        self.lbl_mon_run.setText("○ 已停止")
        self.lbl_mon_run.setStyleSheet("color:#6B7280;")
        self.mon["ptotal"].setText("—")
        for k in ("mode", "ctrl", "fault", "ver", "sn"):
            self.mon[k].setText("—")
        for i in range(3):
            for pfx in ("v", "i", "p"):
                self.mon["%s%d" % (pfx, i)].setText("—")
        for key, lab in self.info_vars.items():
            lab.setText("—" if key != "serial" else lab.text())

    def _show_read_result(self, start: int, vals):
        self.tree_dbg.setRowCount(len(vals))
        for i, v in enumerate(vals):
            addr = start + i
            for c, text in enumerate(("0x%02X" % addr, "0x%04X" % v, str(v),
                                      rg.describe_addr(addr))):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter if c < 3 else Qt.AlignLeft)
                self.tree_dbg.setItem(i, c, it)
        self._log("读取 0x%02X 起 %d 个寄存器：%s" % (start, len(vals),
                                                   " ".join("%04X" % v for v in vals)))

    # ---------------------------------------------------------- 高级设置
    def _open_advanced(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("高级设置")
        dlg.setMinimumWidth(460)
        v = QVBoxLayout(dlg)
        v.setSpacing(10)

        g = QGroupBox("通讯")
        gl = QGridLayout(g)
        gl.setSpacing(6)
        fields = {}
        rows = [
            ("offset", "寄存器地址偏移", int,
             "默认 0。华源手册中的地址即为报文 StartReg。若现场遇到「读写地址差 1」的机型，可填 -1。"),
            ("timeout", "响应超时(秒)", float, "等待设备回帧的最长时间。"),
            ("inter_frame", "帧间隔(秒)", float, "两次请求之间的静默时间，RS485 建议 0.02~0.05。"),
            ("poll_period", "轮询周期(秒)", float, "后台自动刷新监控数据的间隔。"),
        ]
        for i, (key, label, kind, tip) in enumerate(rows):
            gl.addWidget(QLabel(label), i, 0, Qt.AlignRight)
            if kind is int:
                sp = QSpinBox()
                sp.setRange(-16, 16)
                sp.setValue(int(self.cfg[key]))
            else:
                sp = QDoubleSpinBox()
                sp.setDecimals(3)
                sp.setRange(0, 3600)
                sp.setValue(float(self.cfg[key]))
            sp.setFixedWidth(140)
            fields[key] = (sp, kind)
            gl.addWidget(sp, i, 1)
            tl = QLabel(tip)
            tl.setStyleSheet("color:#6B7280;")
            tl.setWordWrap(True)
            gl.addWidget(tl, i, 2)
            gl.setColumnStretch(2, 1)
        chk_swap = QCheckBox("32 位值低位字在前（字序交换）")
        chk_swap.setChecked(bool(self.cfg["word_swap"]))
        gl.addWidget(chk_swap, len(rows), 0, 1, 3)
        t1 = QLabel("默认高位字在前。若读写 32 位数值明显异常，可尝试勾选。")
        t1.setStyleSheet("color:#6B7280;")
        gl.addWidget(t1, len(rows) + 1, 0, 1, 3)
        chk_align = QCheckBox("起始地址与数量对齐到偶数")
        chk_align.setChecked(bool(self.cfg["align_even"]))
        gl.addWidget(chk_align, len(rows) + 2, 0, 1, 3)
        t2 = QLabel("部分国产仪器有此硬性要求，默认关闭。")
        t2.setStyleSheet("color:#6B7280;")
        gl.addWidget(t2, len(rows) + 3, 0, 1, 3)
        chk_ch = QCheckBox("轮询时读取通道 4~15 明细")
        chk_ch.setChecked(bool(self.cfg["with_channels"]))
        gl.addWidget(chk_ch, len(rows) + 4, 0, 1, 3)
        t3 = QLabel("关掉可显著提速（只读 0x60~0x80 核心参数）。")
        t3.setStyleSheet("color:#6B7280;")
        gl.addWidget(t3, len(rows) + 5, 0, 1, 3)
        v.addWidget(g)

        g2 = QGroupBox("本地量程保护（0 = 不校验）")
        g2l = QGridLayout(g2)
        g2l.setSpacing(6)
        lim_fields = {}
        for i, (key, label) in enumerate((("limit_power", "功率上限 (W)"),
                                          ("limit_current", "电流上限 (A)"),
                                          ("limit_voltage", "电压上限 (V)"))):
            g2l.addWidget(QLabel(label), i, 0, Qt.AlignRight)
            sp = QDoubleSpinBox()
            sp.setDecimals(3)
            sp.setRange(0, 10_000_000)
            sp.setValue(float(self.cfg[key]))
            sp.setFixedWidth(140)
            lim_fields[key] = sp
            g2l.addWidget(sp, i, 1)
        t4 = QLabel("超出上限的设定值会在本地被拦截，不会发给设备，\n"
                    "从而避免设备返回异常码 03（ILLEGAL DATA VALUE）。")
        t4.setStyleSheet("color:#6B7280;")
        g2l.addWidget(t4, len(lim_fields), 0, 1, 2)
        v.addWidget(g2)

        def save():
            try:
                for key, (sp, kind) in fields.items():
                    self.cfg[key] = int(sp.value()) if kind is int else float(sp.value())
                for key, sp in lim_fields.items():
                    self.cfg[key] = float(sp.value() or 0)
            except ValueError:
                QMessageBox.information(dlg, "输入有误", "请检查数值格式。")
                return
            self.cfg["word_swap"] = bool(chk_swap.isChecked())
            self.cfg["align_even"] = bool(chk_align.isChecked())
            self.cfg["with_channels"] = bool(chk_ch.isChecked())
            self.worker.poll_period = float(self.cfg["poll_period"])
            self.worker.with_channels = bool(self.cfg["with_channels"])
            if self.worker.load is not None:
                self.worker.load.set_limits(self.cfg["limit_power"], self.cfg["limit_current"],
                                            self.cfg["limit_voltage"])
            self.builder.set_limits(self.cfg["limit_power"], self.cfg["limit_current"],
                                    self.cfg["limit_voltage"])
            save_cfg(self.cfg)
            self._log("高级设置已保存（地址偏移 %d，字序 %s，轮询 %.1fs）"
                      % (self.cfg["offset"],
                         "低位在前" if self.cfg["word_swap"] else "高位在前",
                         self.cfg["poll_period"]))
            dlg.accept()

        bb = QHBoxLayout()
        bb.addStretch(1)
        btn_save = QPushButton("保存")
        btn_save.setStyleSheet(BTN_CSS)
        btn_save.clicked.connect(save)
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet(BTN_CSS)
        btn_cancel.clicked.connect(dlg.reject)
        bb.addWidget(btn_save)
        bb.addWidget(btn_cancel)
        v.addLayout(bb)

        dlg.exec_()

    # ---------------------------------------------------------- 退出清理
    def shutdown(self):
        """停轮询 → 关输出（高危安全）→ 断链 → 回收工作线程。"""
        self._drain_timer.stop()
        try:
            self.cfg["unit"] = int(self.spn_unit.value())
            self.cfg["show_wire"] = bool(self.chk_wire.isChecked())
            save_cfg(self.cfg)
        except Exception:  # noqa: BLE001
            pass
        if self.connected:
            # 高危输出先安全关闭再断链（负载箱规则：退出必须先停拉载）
            try:
                self.cmd_q.put(("ops", ([("w16", rg.ADDR_OUTPUT_CTRL, 0)], "退出自动关闭输出")))
            except Exception:  # noqa: BLE001
                pass
        self.cmd_q.put(("disconnect", None))
        self.cmd_q.put(("stop", None))
        try:
            self.worker.join(timeout=3.0)
        except Exception:  # noqa: BLE001
            pass
        self.connected = False
        # 同步复位连接按钮（worker 的 disconnected 信号可能赶不上页面销毁）
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.setText("连接")
        self.btn_conn.setEnabled(True)
