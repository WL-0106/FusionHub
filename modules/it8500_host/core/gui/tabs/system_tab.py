"""系统与保护页: OVP/OCP/OPP、拉载/卸载电压、定时器、SENSE、地址与设置存储。"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal as Signal
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)


class SystemTab(QWidget):
    prot_set = Signal(str, float)     # id, 数值
    prot_read = Signal(str)
    prot_reset = Signal()             # 保护复位：输出 OFF→ON 清除保护锁存
    timer_set = Signal(int)
    timer_read = Signal()
    timer_en_set = Signal(bool)
    timer_en_read = Signal()
    sense_set = Signal(bool)
    sense_read = Signal()
    local_set = Signal(bool)
    addr_apply = Signal(int)
    setup_save = Signal(int)
    setup_recall = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- 保护限值 ----
        grp_prot = QGroupBox("输入保护限值 (超限自动报警/保护)")
        g = QGridLayout(grp_prot)
        self._spn: dict[str, QDoubleSpinBox] = {}
        self._lbl: dict[str, QLabel] = {}
        specs = [("ovp", "过压 OVP", "V", 0.0, 150.0, 3),
                 ("ocp", "过流 OCP", "A", 0.0, 600.0, 4),
                 ("opp", "过功率 OPP", "W", 0.0, 60000.0, 3)]
        for row, (key, label, unit, lo, hi, dec) in enumerate(specs):
            spn = QDoubleSpinBox()
            spn.setRange(lo, hi)
            spn.setDecimals(dec)
            spn.setKeyboardTracking(False)
            rb = QPushButton("读取")
            sb = QPushButton("设置")
            sb.setObjectName("ConnectBtn")
            rb.clicked.connect(lambda _=False, k=key: self.prot_read.emit(k))
            sb.clicked.connect(lambda _=False, k=key, s=spn:
                               self.prot_set.emit(k, s.value()))
            g.addWidget(QLabel(label + ":"), row, 0)
            g.addWidget(spn, row, 1)
            g.addWidget(QLabel(unit), row, 2)
            g.addWidget(sb, row, 3)
            g.addWidget(rb, row, 4)
            cur = QLabel("—")
            cur.setProperty("role", "value")
            g.addWidget(QLabel("设备值:"), row, 5)
            g.addWidget(cur, row, 6)
            self._spn[key] = spn
            self._lbl[key] = cur
        # 保护复位：协议无清故障命令，按手册以输出 OFF→ON 复位保护锁存（RV/OV/OC/OP/OH）
        btn_reset = QPushButton("保护复位（输出 OFF→ON 清除保护锁存）")
        btn_reset.setObjectName("ConnectBtn")
        btn_reset.setToolTip(
            "保护触发后锁存（面板 ERROR 灯类）：帧协议无清故障命令，"
            "按手册以输入开关 OFF→ON 复位。复位后输入处于开启状态，请确认接线与量程安全。")
        btn_reset.clicked.connect(self.prot_reset.emit)
        g.addWidget(btn_reset, len(specs), 0, 1, 7)
        root.addWidget(grp_prot)

        # ---- 拉载/卸载/电池 ----
        grp_v = QGroupBox("带载相关电压")
        gv = QGridLayout(grp_v)
        self._vspn: dict[str, QDoubleSpinBox] = {}
        self._vlbl: dict[str, QLabel] = {}
        vspecs = [("pullon", "拉载电压 (0x10)", "V"),
                  ("release", "卸载电压 (0x12)", "V"),
                  ("bat_min", "电池测试最小电压", "V")]
        for row, (key, label, unit) in enumerate(vspecs):
            spn = QDoubleSpinBox()
            spn.setRange(0.0, 150.0)
            spn.setDecimals(3)
            spn.setKeyboardTracking(False)
            rb = QPushButton("读取")
            sb = QPushButton("设置")
            sb.setObjectName("ConnectBtn")
            rb.clicked.connect(lambda _=False, k=key: self.prot_read.emit(k))
            sb.clicked.connect(lambda _=False, k=key, s=spn:
                               self.prot_set.emit(k, s.value()))
            gv.addWidget(QLabel(label + ":"), row, 0)
            gv.addWidget(spn, row, 1)
            gv.addWidget(QLabel(unit), row, 2)
            gv.addWidget(sb, row, 3)
            gv.addWidget(rb, row, 4)
            cur = QLabel("—")
            cur.setProperty("role", "value")
            gv.addWidget(QLabel("设备值:"), row, 5)
            gv.addWidget(cur, row, 6)
            self._vspn[key] = spn
            self._vlbl[key] = cur
        root.addWidget(grp_v)

        # ---- 定时器 ----
        grp_t = QGroupBox("FOR LOAD ON 定时器")
        gt = QHBoxLayout(grp_t)
        self.spn_timer = QSpinBox()
        self.spn_timer.setRange(0, 65535)
        self.spn_timer.setSuffix(" s")
        btn_tset = QPushButton("设置时间")
        btn_tset.setObjectName("ConnectBtn")
        btn_tget = QPushButton("读取时间")
        self.cmb_timer_en = QComboBox()
        self.cmb_timer_en.addItem("关闭", False)
        self.cmb_timer_en.addItem("打开", True)
        btn_eset = QPushButton("设置状态")
        btn_eget = QPushButton("读取状态")
        self.lbl_timer = QLabel("—")
        self.lbl_timer.setProperty("role", "value")
        gt.addWidget(QLabel("时间:"))
        gt.addWidget(self.spn_timer)
        gt.addWidget(btn_tset)
        gt.addWidget(btn_tget)
        gt.addWidget(QLabel("状态:"))
        gt.addWidget(self.cmb_timer_en)
        gt.addWidget(btn_eset)
        gt.addWidget(btn_eget)
        gt.addWidget(QLabel("设备:"))
        gt.addWidget(self.lbl_timer)
        gt.addStretch(1)
        root.addWidget(grp_t)

        # ---- 远程测量 / LOCAL / 地址 / 设置存储 ----
        grp_sys = QGroupBox("系统")
        gs = QGridLayout(grp_sys)

        self.cmb_sense = QComboBox()
        self.cmb_sense.addItem("关闭", False)
        self.cmb_sense.addItem("打开 (远程测量)", True)
        btn_sset = QPushButton("设置")
        btn_sget = QPushButton("读取")
        gs.addWidget(QLabel("远程测量 SENSE:"), 0, 0)
        gs.addWidget(self.cmb_sense, 0, 1)
        gs.addWidget(btn_sset, 0, 2)
        gs.addWidget(btn_sget, 0, 3)

        self.cmb_local = QComboBox()
        self.cmb_local.addItem("禁止 LOCAL 键", False)
        self.cmb_local.addItem("允许 LOCAL 键", True)
        btn_lset = QPushButton("设置")
        gs.addWidget(QLabel("面板 LOCAL 键:"), 1, 0)
        gs.addWidget(self.cmb_local, 1, 1)
        gs.addWidget(btn_lset, 1, 2)

        self.spn_addr = QSpinBox()
        self.spn_addr.setRange(0, 31)
        btn_addr = QPushButton("修改通讯地址")
        btn_addr.setObjectName("DangerBtn")
        btn_addr.setToolTip("下发后设备立即切换到新地址 (0x54)")
        gs.addWidget(QLabel("新地址 (0~31):"), 2, 0)
        gs.addWidget(self.spn_addr, 2, 1)
        gs.addWidget(btn_addr, 2, 2)

        self.spn_setup = QSpinBox()
        self.spn_setup.setRange(1, 8)
        btn_ss = QPushButton("保存设置到区")
        btn_sr = QPushButton("从区取出设置")
        gs.addWidget(QLabel("设置存储区:"), 3, 0)
        gs.addWidget(self.spn_setup, 3, 1)
        gs.addWidget(btn_ss, 3, 2)
        gs.addWidget(btn_sr, 3, 3)
        root.addWidget(grp_sys)
        root.addStretch(1)

        # ---- 信号 ----
        btn_tset.clicked.connect(lambda: self.timer_set.emit(self.spn_timer.value()))
        btn_tget.clicked.connect(self.timer_read.emit)
        btn_eset.clicked.connect(
            lambda: self.timer_en_set.emit(self.cmb_timer_en.currentData()))
        btn_eget.clicked.connect(self.timer_en_read.emit)
        btn_sset.clicked.connect(
            lambda: self.sense_set.emit(self.cmb_sense.currentData()))
        btn_sget.clicked.connect(self.sense_read.emit)
        btn_lset.clicked.connect(
            lambda: self.local_set.emit(self.cmb_local.currentData()))
        btn_addr.clicked.connect(lambda: self.addr_apply.emit(self.spn_addr.value()))
        btn_ss.clicked.connect(lambda: self.setup_save.emit(self.spn_setup.value()))
        btn_sr.clicked.connect(lambda: self.setup_recall.emit(self.spn_setup.value()))

    # ---------------------------------------------------------- 回填
    def show_prot(self, key: str, value: float) -> None:
        unit = {"ovp": "V", "ocp": "A", "opp": "W",
                "pullon": "V", "release": "V", "bat_min": "V"}[key]
        if key in self._lbl:
            self._lbl[key].setText(f"{value} {unit}")
        if key in self._vlbl:
            self._vlbl[key].setText(f"{value} {unit}")
        spn = self._spn.get(key) or self._vspn.get(key)
        if spn and not spn.hasFocus():
            spn.setValue(value)

    def show_timer(self, seconds: int) -> None:
        self.lbl_timer.setText(f"{seconds} s")
        if not self.spn_timer.hasFocus():
            self.spn_timer.setValue(seconds)

    def show_timer_en(self, enabled: bool) -> None:
        i = self.cmb_timer_en.findData(bool(enabled))
        if i >= 0:
            self.cmb_timer_en.setCurrentIndex(i)

    def show_sense(self, enabled: bool) -> None:
        i = self.cmb_sense.findData(bool(enabled))
        if i >= 0:
            self.cmb_sense.setCurrentIndex(i)

    def set_connected(self, ok: bool) -> None:
        for w in (*self._spn.values(), *self._vspn.values(),
                  self.spn_timer, self.cmb_timer_en, self.cmb_sense,
                  self.cmb_local, self.spn_addr, self.spn_setup):
            w.setEnabled(ok)
