"""定值设置页: 工作模式 + 负载模式 (CC/CV/CW/CR) + 定值设定/回读。"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal as Signal
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QRadioButton, QButtonGroup, QVBoxLayout,
                               QWidget)

MODE_RANGES = {   # 模式: (min, max, decimals)
    "CC": (0.0, 600.0, 4),
    "CV": (0.0, 150.0, 3),
    "CW": (0.0, 60000.0, 3),
    "CR": (0.001, 100000.0, 3),
}
MODE_UNITS = {"CC": "A", "CV": "V", "CW": "W", "CR": "Ω"}
WORK_MODES_ZH = [("FIXED", "固定 FIXED"), ("SHORT", "短路 SHORT"),
                 ("TRANSITION", "过渡(动态) TRANSITION"),
                 ("LIST", "列表 LIST"), ("BATTERY", "电池 BATTERY")]


class FixedTab(QWidget):
    mode_selected = Signal(str)            # 请求切负载模式
    value_set = Signal(str, float)         # 设置定值
    value_read = Signal(str)               # 回读定值
    mode_read = Signal()                   # 回读负载模式
    work_mode_set = Signal(str)            # 设置工作模式
    work_mode_read = Signal()              # 回读工作模式

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fill_on_read = False   # 切换模式触发的自动回读：结果填进设定值框
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ------- 工作模式 -------
        grp_work = QGroupBox("工作模式")
        h = QHBoxLayout(grp_work)
        self.cmb_work = QComboBox()
        for zh, label in WORK_MODES_ZH:
            self.cmb_work.addItem(label, zh)
        btn_work_set = QPushButton("设置工作模式")
        btn_work_get = QPushButton("读取")
        self.lbl_work = QLabel("—")
        self.lbl_work.setProperty("role", "value")
        h.addWidget(QLabel("模式:"))
        h.addWidget(self.cmb_work, 1)
        h.addWidget(btn_work_set)
        h.addWidget(btn_work_get)
        h.addWidget(QLabel("当前:"))
        h.addWidget(self.lbl_work)
        btn_work_set.clicked.connect(
            lambda: self.work_mode_set.emit(self.cmb_work.currentData()))
        btn_work_get.clicked.connect(self.work_mode_read.emit)
        root.addWidget(grp_work)

        # ------- 负载模式 + 定值 -------
        grp = QGroupBox("定值 (FIXED 模式下生效)")
        g = QGridLayout(grp)
        g.setHorizontalSpacing(12)

        self._mode_buttons: dict[str, QRadioButton] = {}
        self._mode_group = QButtonGroup(self)
        row = QHBoxLayout()
        for i, m in enumerate(("CC", "CV", "CW", "CR")):
            rb = QRadioButton(f"{m}  {MODE_UNITS[m]}")
            rb.toggled.connect(self._on_mode_toggled)
            row.addWidget(rb)
            self._mode_buttons[m] = rb
            self._mode_group.addButton(rb, i)
        row.addStretch(1)
        g.addLayout(row, 0, 0, 1, 4)

        self.spn_value = QDoubleSpinBox()
        self.spn_value.setDecimals(4)
        self.spn_value.setRange(*MODE_RANGES["CC"][:2])
        self.spn_value.setKeyboardTracking(False)
        self.lbl_unit = QLabel("A")
        btn_set = QPushButton("设置定值")
        btn_read = QPushButton("读取定值")
        btn_mode_read = QPushButton("回读模式")
        btn_set.setObjectName("ConnectBtn")
        self.lbl_readback = QLabel("等待读取…")
        self.lbl_readback.setProperty("role", "hint")

        g.addWidget(QLabel("设定值:"), 1, 0)
        g.addWidget(self.spn_value, 1, 1)
        g.addWidget(self.lbl_unit, 1, 2)
        g.addWidget(btn_set, 1, 3)
        g.addWidget(btn_read, 2, 3)
        g.addWidget(btn_mode_read, 3, 3)
        g.addWidget(self.lbl_readback, 2, 0, 1, 3)
        g.setColumnStretch(1, 1)
        root.addWidget(grp)

        # ------- 各模式定值一览 -------
        grp_all = QGroupBox("设备内已存定值 (读取后刷新)")
        ga = QGridLayout(grp_all)
        self._lbl_stored: dict[str, QLabel] = {}
        for i, m in enumerate(("CC", "CV", "CW", "CR")):
            ga.addWidget(QLabel(f"{m}:"), 0, i * 2)
            lb = QLabel("—")
            lb.setProperty("role", "value")
            ga.addWidget(lb, 0, i * 2 + 1)
            ga.setColumnStretch(i * 2 + 1, 1)
            self._lbl_stored[m] = lb
        root.addWidget(grp_all)
        root.addStretch(1)

        btn_set.clicked.connect(self._on_set)
        btn_read.clicked.connect(
            lambda: self.value_read.emit(self.current_mode()))
        btn_mode_read.clicked.connect(self.mode_read.emit)

        # 控件全部就绪后再触发默认模式 (toggled 回调依赖 spn_value)
        self._mode_buttons["CC"].setChecked(True)
        self._fill_on_read = False   # 构建期默认选中不触发自动回读

    # ---------------------------------------------------------- 交互
    def current_mode(self) -> str:
        for m, rb in self._mode_buttons.items():
            if rb.isChecked():
                return m
        return "CC"

    def _on_mode_toggled(self, checked: bool) -> None:
        if not checked:
            return
        m = self.current_mode()
        lo, hi, dec = MODE_RANGES[m]
        self.spn_value.setDecimals(dec)
        self.spn_value.setRange(lo, hi)
        self.lbl_unit.setText(MODE_UNITS[m])
        self.mode_selected.emit(m)
        # 切换模式自动回读一次该模式当前值，结果填进设定值输入框
        self._fill_on_read = True
        self.value_read.emit(m)

    def _on_set(self) -> None:
        self.value_set.emit(self.current_mode(), self.spn_value.value())

    # ---------------------------------------------------------- 回填
    def show_mode(self, mode: str) -> None:
        rb = self._mode_buttons.get(mode)
        if rb and not rb.isChecked():
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)
            lo, hi, dec = MODE_RANGES[mode]
            self.spn_value.setDecimals(dec)
            self.spn_value.setRange(lo, hi)
            self.lbl_unit.setText(MODE_UNITS[mode])

    def show_value(self, mode: str, value: float) -> None:
        unit = MODE_UNITS[mode]
        self.lbl_readback.setText(f"回读 {mode} = {value} {unit}")
        if mode in self._lbl_stored:
            self._lbl_stored[mode].setText(f"{value} {unit}")
        # 模式切换触发的自动回读：把当前值写进设定值框（仅当模式仍为当前选中，
        # 且只认切换触发这一次——避免「设备内已存定值」批量刷新覆写正在输入的值）
        if self._fill_on_read and mode == self.current_mode():
            self._fill_on_read = False
            self.spn_value.setValue(value)

    def show_work_mode(self, name: str) -> None:
        self.lbl_work.setText(name)

    def set_connected(self, ok: bool) -> None:
        for w in (self.cmb_work, self.spn_value):
            w.setEnabled(ok)
