"""实时测量页: 大字读数 + 状态字 + 趋势曲线 + 输出控制。"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal as Signal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ...it8500.protocol import (Measurement, OP_STATUS_BITS, QUERY_STATUS_BITS)
from ..chart import TrendChart


def _card(title: str, cls: str, unit: str) -> tuple[QFrame, QLabel]:
    card = QFrame()
    card.setObjectName("ReadCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(2)
    top = QHBoxLayout()
    lab = QLabel(title)
    lab.setObjectName("ReadLabel")
    top.addWidget(lab)
    top.addStretch(1)
    u = QLabel(unit)
    u.setObjectName("ReadUnit")
    top.addWidget(u)
    lay.addLayout(top)
    val = QLabel("--.----")
    val.setObjectName("ReadValue")
    val.setProperty("cls", cls)
    lay.addWidget(val)
    # 用样式表动态着色 (objectName 相同, 靠属性区分)
    return card, val


class RealtimeTab(QWidget):
    output_clicked = Signal(bool)      # 用户请求输出开/关
    remote_clicked = Signal(bool)      # 用户请求遥控/面板
    record_clicked = Signal(bool)      # 开始/停止 CSV 记录
    clear_clicked = Signal()           # 清空曲线

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t0: float | None = None
        self._build_ui()
        self.set_connected(False)

    # ---------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(10)

        # ---- 读数卡 ----
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._cards: dict[str, QLabel] = {}
        colors = {"U": "#0d9b6c", "I": "#1f7ae0", "P": "#c98a00"}
        for key, title, unit in (("U", "输入电压", "V"),
                                 ("I", "输入电流", "A"),
                                 ("P", "输入功率", "W")):
            card, val = _card(title, key, unit)
            val.setStyleSheet(f"color: {colors[key]};")
            val.setMinimumWidth(150)
            val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._cards[key] = val
            cards.addWidget(card, 1)
        left.addLayout(cards)

        # ---- 状态字 ----
        flag_box = QFrame()
        flag_box.setObjectName("ReadCard")
        fbox = QVBoxLayout(flag_box)
        fbox.setContentsMargins(12, 8, 12, 8)
        fbox.setSpacing(4)
        r1 = QLabel("操作状态")
        r1.setObjectName("ReadLabel")
        fbox.addWidget(r1)
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        self._op_chips: dict[str, QLabel] = {}
        for bit, name in sorted(OP_STATUS_BITS.items()):
            chip = QLabel(name)
            chip.setObjectName("FlagChip")
            chip.setProperty("on", False)
            row1.addWidget(chip)
            self._op_chips[name] = chip
        row1.addStretch(1)
        fbox.addLayout(row1)
        r2 = QLabel("查询状态 (保护 / 稳压稳流)")
        r2.setObjectName("ReadLabel")
        fbox.addWidget(r2)
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        self._q_chips: dict[str, QLabel] = {}
        fault = {"RV", "OV", "OC", "OP", "OH"}
        for bit, name in sorted(QUERY_STATUS_BITS.items()):
            chip = QLabel(name)
            chip.setObjectName("FlagChip")
            chip.setProperty("on", False)
            chip.setProperty("fault", name in fault)
            tip = {"RV": "输入极性反接", "OV": "过电压", "OC": "过电流",
                   "OP": "过功率", "OH": "过温度", "SV": "远程测量端子未接",
                   "CC": "定电流", "CV": "定电压", "CP": "定功率",
                   "CR": "定电阻"}[name]
            chip.setToolTip(f"{name} — {tip}")
            row2.addWidget(chip)
            self._q_chips[name] = chip
        row2.addStretch(1)
        fbox.addLayout(row2)
        left.addWidget(flag_box)

        # ---- 操作按钮 ----
        ops = QHBoxLayout()
        ops.setSpacing(8)
        self.btn_output = QPushButton("输出 OFF")
        self.btn_output.setObjectName("OutputBtn")
        self.btn_output.setProperty("state", "off")
        self.btn_output.clicked.connect(self._on_output)
        self.btn_remote = QPushButton("遥控")
        self.btn_remote.setObjectName("RemoteBtn")
        self.btn_remote.setProperty("remote", True)
        self.btn_remote.clicked.connect(self._on_remote)
        self.btn_record = QPushButton("记录 CSV")
        self.btn_record.setCheckable(True)
        self.btn_record.toggled.connect(self.record_clicked.emit)
        self.btn_clear = QPushButton("清空曲线")
        self.btn_clear.clicked.connect(self._on_clear)
        for b in (self.btn_output, self.btn_remote, self.btn_record, self.btn_clear):
            ops.addWidget(b)
        ops.addStretch(1)
        left.addLayout(ops)

        # ---- 曲线 ----
        self.chart = TrendChart()
        left.addWidget(self.chart, 1)

        root.addLayout(left, 1)

    # ---------------------------------------------------------- 交互
    def _on_output(self) -> None:
        turning_on = self.btn_output.property("state") == "off"
        self.output_clicked.emit(turning_on)

    def _on_remote(self) -> None:
        now_remote = self.btn_remote.property("remote")
        self.remote_clicked.emit(not now_remote)

    def _on_clear(self) -> None:
        self.chart.clear()
        self._t0 = None
        self.clear_clicked.emit()

    # ---------------------------------------------------------- 状态刷新
    def set_connected(self, ok: bool) -> None:
        for b in (self.btn_output, self.btn_remote, self.btn_record,
                  self.btn_clear):
            b.setEnabled(ok)
        if not ok:
            for key in self._cards:
                self._cards[key].setText("--.----")
            self.set_output_state(False, False)
            self.btn_remote.setProperty("remote", True)
            self._polish(self.btn_remote)
            for chip in self._op_chips.values():
                self._set_chip(chip, False)
            for chip in self._q_chips.values():
                self._set_chip(chip, False)
            self.chart.clear()
            self._t0 = None

    def set_output_state(self, on: bool, local: bool = False) -> None:
        self.btn_output.setProperty("state", "on" if on else "off")
        self.btn_output.setText("输出 ON" if on else "输出 OFF")
        self.btn_output.setEnabled(not local)
        self._polish(self.btn_output)

    def set_remote_state(self, remote: bool) -> None:
        self.btn_remote.setProperty("remote", remote)
        self.btn_remote.setText("遥控" if remote else "面板")
        self._polish(self.btn_remote)

    def set_recording(self, recording: bool) -> None:
        if self.btn_record.isChecked() != recording:
            self.btn_record.blockSignals(True)
            self.btn_record.setChecked(recording)
            self.btn_record.blockSignals(False)
        self.btn_record.setText("停止记录" if recording else "记录 CSV")

    def apply_measurement(self, m: Measurement, t: float) -> None:
        if self._t0 is None:
            self._t0 = t
        self._cards["U"].setText(f"{m.voltage:.4f}")
        self._cards["I"].setText(f"{m.current:.4f}")
        self._cards["P"].setText(f"{m.power:.3f}")
        self.chart.append_sample(t - self._t0, m.voltage, m.current, m.power)

        for name, chip in self._op_chips.items():
            self._set_chip(chip, name in m.op_flags)
        for name, chip in self._q_chips.items():
            self._set_chip(chip, name in m.query_flags)

        self.set_output_state(m.is_output_on)
        self.set_remote_state(m.is_remote)

    # ---------------------------------------------------------- 工具
    @staticmethod
    def _set_chip(chip: QLabel, on: bool) -> None:
        if chip.property("on") != on:
            chip.setProperty("on", on)
            chip.style().unpolish(chip)
            chip.style().polish(chip)

    @staticmethod
    def _polish(w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)
