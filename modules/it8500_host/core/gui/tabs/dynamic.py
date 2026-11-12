"""动态 (TRANSITION) 参数页: 四组模式 A/B 值与时间、动态波形模式。"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal as Signal
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ...it8500.protocol import DynamicParams

UNIT_OF = {"CC": "A", "CV": "V", "CW": "W", "CR": "Ω"}
RANGES = {"CC": (0.0, 600.0, 4), "CV": (0.0, 150.0, 3),
          "CW": (0.0, 60000.0, 3), "CR": (0.001, 100000.0, 3)}
DYN_MODES = [(0, "连续 CONTINUOUS"), (1, "脉冲 PULSE"), (2, "翻转 TOGGLED")]


class DynamicTab(QWidget):
    params_set = Signal(str, object)      # 模式, DynamicParams
    params_read = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        hint = QLabel("动态测试需将工作模式设为 TRANSITION (见「定值设置」页), 再使能输出。")
        hint.setProperty("role", "hint")
        root.addWidget(hint)

        top = QHBoxLayout()
        top.addWidget(QLabel("参数组:"))
        self.cmb_mode = QComboBox()
        for m in ("CC", "CV", "CW", "CR"):
            self.cmb_mode.addItem(f"{m} ({UNIT_OF[m]})", m)
        top.addWidget(self.cmb_mode)
        self.lbl_unit = QLabel("单位: A")
        self.lbl_unit.setProperty("role", "hint")
        top.addWidget(self.lbl_unit)
        top.addStretch(1)
        root.addLayout(top)

        grp = QGroupBox("动态参数")
        g = QGridLayout(grp)
        g.setHorizontalSpacing(10)

        self.spn_a = self._value_spin()
        self.spn_ta = self._time_spin()
        self.spn_b = self._value_spin()
        self.spn_tb = self._time_spin()
        self.cmb_dyn = QComboBox()
        for v, label in DYN_MODES:
            self.cmb_dyn.addItem(label, v)

        g.addWidget(QLabel("电平 A:"), 0, 0)
        g.addWidget(self.spn_a, 0, 1)
        g.addWidget(QLabel("持续 A:"), 0, 2)
        g.addWidget(self.spn_ta, 0, 3)
        g.addWidget(QLabel("ms"), 0, 4)
        g.addWidget(QLabel("电平 B:"), 1, 0)
        g.addWidget(self.spn_b, 1, 1)
        g.addWidget(QLabel("持续 B:"), 1, 2)
        g.addWidget(self.spn_tb, 1, 3)
        g.addWidget(QLabel("ms"), 1, 4)
        g.addWidget(QLabel("动态方式:"), 2, 0)
        g.addWidget(self.cmb_dyn, 2, 1, 1, 2)

        btns = QHBoxLayout()
        btn_set = QPushButton("设置动态参数")
        btn_set.setObjectName("ConnectBtn")
        btn_read = QPushButton("读取动态参数")
        btns.addWidget(btn_set)
        btns.addWidget(btn_read)
        btns.addStretch(1)
        g.addLayout(btns, 3, 0, 1, 5)
        root.addWidget(grp)

        self.lbl_state = QLabel("等待读取…")
        self.lbl_state.setProperty("role", "hint")
        root.addWidget(self.lbl_state)
        root.addStretch(1)

        btn_set.clicked.connect(self._on_set)
        btn_read.clicked.connect(
            lambda: self.params_read.emit(self.cmb_mode.currentData()))
        self.cmb_mode.currentIndexChanged.connect(self._on_group_changed)
        self._on_group_changed()

    # ----------------------------------------------------------
    @staticmethod
    def _value_spin() -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setDecimals(4)
        s.setRange(0.0, 60000.0)
        s.setKeyboardTracking(False)
        return s

    @staticmethod
    def _time_spin() -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setDecimals(1)
        s.setRange(0.1, 6553.5)
        s.setSuffix(" ms")
        s.setKeyboardTracking(False)
        return s

    def _on_group_changed(self, *_ ) -> None:
        m = self.cmb_mode.currentData()
        lo, hi, dec = RANGES[m]
        for spn in (self.spn_a, self.spn_b):
            spn.setRange(lo, hi)
            spn.setDecimals(dec)
        self.lbl_unit.setText(f"单位: {UNIT_OF[m]}")

    def _on_set(self) -> None:
        mode = self.cmb_mode.currentData()
        params = DynamicParams(value_a=self.spn_a.value(),
                               time_a_ms=self.spn_ta.value(),
                               value_b=self.spn_b.value(),
                               time_b_ms=self.spn_tb.value(),
                               dyn_mode=self.cmb_dyn.currentData())
        self.params_set.emit(mode, params)

    # ---------------------------------------------------------- 回填
    def show_params(self, mode: str, p: DynamicParams) -> None:
        if self.cmb_mode.currentData() != mode:
            self.cmb_mode.blockSignals(True)
            idx = self.cmb_mode.findData(mode)
            if idx >= 0:
                self.cmb_mode.setCurrentIndex(idx)
            self.cmb_mode.blockSignals(False)
            self._on_group_changed()
        self.spn_a.setValue(p.value_a)
        self.spn_ta.setValue(p.time_a_ms)
        self.spn_b.setValue(p.value_b)
        self.spn_tb.setValue(p.time_b_ms)
        idx = self.cmb_dyn.findData(p.dyn_mode)
        if idx >= 0:
            self.cmb_dyn.setCurrentIndex(idx)
        self.lbl_state.setText(
            f"回读 {mode}: A={p.value_a} / {p.time_a_ms} ms, "
            f"B={p.value_b} / {p.time_b_ms} ms, {DynamicParams.dyn_mode_name(p.dyn_mode)}")

    def set_connected(self, ok: bool) -> None:
        self.cmb_mode.setEnabled(ok)
