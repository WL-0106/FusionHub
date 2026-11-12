"""单通道控制卡片：设定 V/I、实测显示、输出开关、OVP/OCP、负载模式。"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal as Signal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import scpi
from ..models import ChannelSpec, MeasSample

_MONO = QFont("Consolas")
_MONO.setPointSize(10)


class ChannelCard(QGroupBox):
    """所有用户操作都通过信号上抛，由主窗口转发给驱动。"""

    command = Signal(str)                     # 直接下发的 SCPI
    set_changed = Signal(int, str, float)     # (channel, 'v'|'i'|'ovp'|'ocp'|'res', value)
    output_toggled = Signal(int, bool)

    def __init__(self, spec: ChannelSpec, parent: Optional[QWidget] = None):
        super().__init__(spec.label, parent)
        self.spec = spec
        self._updating = False
        self._connected = False
        self._nominal: dict[QWidget, bool] = {}
        self.setStyleSheet(f"""
            QGroupBox {{
                font-weight: 600; border: 1px solid #D1D5DB;
                border-radius: 8px; margin-top: 10px; padding-top: 6px;
                background: #FFFFFF;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 4px;
                color: {spec.color};
            }}
        """)
        self.setMinimumWidth(288)
        self._build()

    # ---------------- UI 构建 ----------------
    def _build(self) -> None:
        spec = self.spec
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 4, 10, 8)
        root.setSpacing(6)

        # 输出开关（两态配色：OFF 浅红描边红字 / ON 实心绿白字；
        # selfStyled 防止融合框架按文字统一刷白）
        head = QHBoxLayout()
        self.out_btn = QPushButton("输出 OFF")
        self.out_btn.setCheckable(True)
        self.out_btn.setFixedHeight(30)
        self.out_btn.setProperty("role", "output")
        self.out_btn.setProperty("selfStyled", True)
        self.out_btn.toggled.connect(self._on_out_toggled)
        head.addStretch(1)
        head.addWidget(self.out_btn)
        root.addLayout(head)
        self._paint_out(False)

        # 设定行
        grid = QGridLayout()
        grid.setVerticalSpacing(5)
        self.v_spin = self._make_spin(0.0, spec.v_max, 3, "V")
        self.i_spin = self._make_spin(0.0, spec.i_max, 4, "A")
        if spec.v_choices:
            self.v_spin.setEnabled(False)
        if not spec.i_settable:
            self.i_spin.setEnabled(False)
            self.i_spin.setSpecialValueText("固定 5.000 A")

        grid.addWidget(QLabel("电压设定"), 0, 0)
        grid.addWidget(self.v_spin, 0, 1)
        if spec.v_choices:
            self.v_combo = QComboBox()
            for v in spec.v_choices:
                self.v_combo.addItem(f"{v:.1f} V", v)
            self.v_combo.currentIndexChanged.connect(self._v_combo_changed)
            grid.addWidget(self.v_combo, 0, 2)
        grid.addWidget(QLabel("电流设定"), 1, 0)
        grid.addWidget(self.i_spin, 1, 1)

        self.v_spin.valueChanged.connect(lambda val: self._emit_set("v", val))
        self.i_spin.valueChanged.connect(lambda val: self._emit_set("i", val))
        root.addLayout(grid)

        # 实测
        meas_row = QHBoxLayout()
        self.v_meas = self._meas_label("--.-----", spec.color)
        self.i_meas = self._meas_label("--.-----", spec.color)
        self.p_meas = self._meas_label("--.----", spec.color)
        for lab, unit in ((self.v_meas, "V"), (self.i_meas, "A"), (self.p_meas, "W")):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(lab)
            u = QLabel(unit)
            u.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            u.setStyleSheet("color:#9CA3AF; font-size:10px;")
            box.addWidget(u)
            w = QWidget()
            w.setLayout(box)
            meas_row.addWidget(w, 1)
        root.addLayout(meas_row)

        # 状态与负载模式
        mode_row = QHBoxLayout()
        self.state_badge = QLabel("—")
        self.state_badge.setAlignment(Qt.AlignCenter)
        self.state_badge.setStyleSheet(
            "background:#F3F4F6; color:#6B7280; border-radius:4px; padding:2px 8px; font-size:11px;")
        mode_row.addWidget(self.state_badge)
        mode_row.addStretch(1)
        self.load_combo = QComboBox()
        self.load_combo.addItem("电源", "source")
        if spec.load_capable:
            self.load_combo.addItem("负载 CV", "cv")
            self.load_combo.addItem("负载 CC", "cc")
            self.load_combo.addItem("负载 CR", "cr")
        else:
            # 硬件能力边界（GPP-x323 负载模式仅 CH1/CH2 双象限通道）：
            # 保持下拉可点开但只列唯一模式 + tooltip 说明，避免“灰按钮点不开”被当成故障
            self.load_combo.setToolTip(
                "该通道仅支持「电源」模式\n"
                "GPP 系列负载模式（CV/CC/CR）仅 CH1/CH2 支持（双象限通道）")
        self.load_combo.setFixedWidth(92)
        self.load_combo.currentIndexChanged.connect(self._load_changed)
        mode_row.addWidget(self.load_combo)

        self.res_spin = QDoubleSpinBox()
        self.res_spin.setRange(1.0, 1000.0)
        self.res_spin.setDecimals(1)
        self.res_spin.setSuffix(" Ω")
        self.res_spin.setEnabled(False)
        self.res_spin.valueChanged.connect(lambda val: self._emit_set("res", val))
        mode_row.addWidget(self.res_spin)
        root.addLayout(mode_row)

        # 保护
        prot = QHBoxLayout()
        self.ovp_en = QCheckBox("OVP")
        self.ovp_val = self._make_spin(0.0, max(spec.v_max * 1.1, 5.5), 2, "V")
        self.ocp_en = QCheckBox("OCP")
        self.ocp_val = self._make_spin(0.0, spec.i_max * 1.1, 3, "A")
        if not spec.ovp_settable:
            self.ovp_en.setEnabled(False)
            self.ovp_val.setEnabled(False)
            self.ovp_val.setSpecialValueText("固定 5.5 V")
        if not spec.ocp_settable:
            self.ocp_en.setEnabled(False)
            self.ocp_val.setEnabled(False)
        self.ovp_en.toggled.connect(
            lambda on: self.command.emit(scpi.ovp_state_set(self.spec.index, on)))
        self.ocp_en.toggled.connect(
            lambda on: self.command.emit(scpi.ocp_state_set(self.spec.index, on)))
        self.ovp_val.valueChanged.connect(lambda val: self._emit_set("ovp", val))
        self.ocp_val.valueChanged.connect(lambda val: self._emit_set("ocp", val))
        for w in (self.ovp_en, self.ovp_val, self.ocp_en, self.ocp_val):
            prot.addWidget(w)
        prot.addStretch(1)
        root.addLayout(prot)

        if spec.note:
            note = QLabel(f"注: {spec.note}")
            note.setStyleSheet("color:#9CA3AF; font-size:10px;")
            root.addWidget(note)

        if spec.v_choices:
            self.v_combo.setCurrentIndex(
                max(0, spec.v_choices.index(5.0) if 5.0 in spec.v_choices else 0))

        # 记录名义可用性(固定电压/固定电流等字段本来就要禁用)
        for w in (self.out_btn, self.v_spin, self.i_spin, self.ovp_en, self.ovp_val,
                  self.ocp_en, self.ocp_val, self.load_combo, self.res_spin):
            self._nominal[w] = w.isEnabled()
        if hasattr(self, "v_combo"):
            self._nominal[self.v_combo] = True
        self.set_connected(False)

    @staticmethod
    def _make_spin(lo: float, hi: float, decimals: int, suffix: str) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(decimals)
        sp.setSingleStep(10 ** (-decimals))
        sp.setSuffix(" " + suffix)
        sp.setKeyboardTracking(False)
        sp.setAlignment(Qt.AlignRight)
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return sp

    @staticmethod
    def _meas_label(text: str, color: str) -> QLabel:
        lab = QLabel(text)
        lab.setFont(_MONO)
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lab.setStyleSheet(f"color:{color}; font-weight:600;")
        lab.setMinimumWidth(76)
        return lab

    # ---------------- 事件 ----------------
    def _on_out_toggled(self, checked: bool) -> None:
        if self._updating:
            return
        self._paint_out(checked)   # 立即两态着色（平台输出按钮规范）
        self.output_toggled.emit(self.spec.index, checked)

    _OUT_STYLES = {
        False: ("#FFF1F2", "#D20A34", "#FDA4AF"),   # OFF：浅红描边红字（待机）
        True: ("#10B981", "#FFFFFF", "#047857"),    # ON：实心绿白字
    }

    def _paint_out(self, out: bool) -> None:
        """输出按钮两态：OFF 浅红描边红字 → ON 实心绿白字。"""
        state = "on" if out else "idle"
        text = "输出 ON" if out else "输出 OFF"
        if self.out_btn.property("state") == state and self.out_btn.text() == text:
            return
        self.out_btn.setProperty("state", state)
        self.out_btn.setText(text)
        bg, fg, bd = self._OUT_STYLES[bool(out)]
        self.out_btn.setStyleSheet(
            f"QPushButton{{background:{bg}; color:{fg}; border:2px solid {bd};"
            f" border-radius:8px; font-weight:700;}}"
            f"QPushButton:pressed{{background:{bd};}}")

    def _emit_set(self, kind: str, value: float) -> None:
        if self._updating:
            return
        self.set_changed.emit(self.spec.index, kind, float(value))

    def _v_combo_changed(self, idx: int) -> None:
        if self._updating:
            return
        val = self.v_combo.currentData()
        if val is not None:
            self._updating = True
            self.v_spin.setValue(float(val))
            self._updating = False
            self._emit_set("v", float(val))

    def _load_changed(self, idx: int) -> None:
        if self._updating:
            return
        kind = self.load_combo.currentData()
        self.res_spin.setEnabled(kind == "cr")
        self.command.emit(scpi.load_mode_set(self.spec.index, kind))

    # ---------------- 状态回填 ----------------
    def apply_snapshot(self, snap: dict) -> None:
        self._updating = True
        try:
            if self.spec.v_choices:
                v = snap.get("v_set", 0.0)
                idx = 0
                for i, c in enumerate(self.spec.v_choices):
                    if abs(c - v) < 1e-6:
                        idx = i
                        break
                self.v_combo.setCurrentIndex(idx)
                self.v_spin.setValue(float(self.spec.v_choices[idx]))
            else:
                self.v_spin.setValue(round(snap.get("v_set", 0.0), 4))
            if self.spec.i_settable:
                self.i_spin.setValue(round(snap.get("i_set", 0.0), 4))
            if self.spec.ovp_settable:
                self.ovp_val.setValue(round(snap.get("ovp", 0.0), 2))
                self.ovp_en.setChecked(bool(snap.get("ovp_en")))
            if self.spec.ocp_settable:
                self.ocp_val.setValue(round(snap.get("ocp", 0.0), 3))
                self.ocp_en.setChecked(bool(snap.get("ocp_en")))
            out = bool(snap.get("output"))
            self.out_btn.setChecked(out)
            self._paint_out(out)

            mode = str(snap.get("mode", "Independent"))
            if mode in ("CV Load", "CC Load", "CR Load"):
                kind = mode.split()[0].lower()
            else:
                kind = "source"
            idx = self.load_combo.findData(kind)
            if idx >= 0:
                self.load_combo.setCurrentIndex(idx)
            self.res_spin.setEnabled(kind == "cr")
        finally:
            self._updating = False
        out = bool(snap.get("output"))
        self.state_badge.setText("输出中" if out else "已关闭")
        self._paint_badge(out)

    def apply_sample(self, s: MeasSample) -> None:
        self.v_meas.setText(f"{s.v:.5f}")
        self.i_meas.setText(f"{s.i:.5f}")
        self.p_meas.setText(f"{s.p:.4f}")
        out = s.output_on
        self.out_btn.blockSignals(True)
        if self.out_btn.isChecked() != out:
            self.out_btn.setChecked(out)
        self.out_btn.blockSignals(False)
        self._paint_out(out)
        if out:
            badge = "CC 限流" if s.cc else "CV 输出"
        else:
            badge = "已关闭"
        self.state_badge.setText(badge)
        self._paint_badge(out, s.cc)

    def _paint_badge(self, out: bool, cc: bool = False) -> None:
        if not out:
            style = "background:#F3F4F6; color:#6B7280;"
        elif cc:
            style = "background:#FEF3C7; color:#B45309;"
        else:
            style = "background:#DCFCE7; color:#15803D;"
        self.state_badge.setStyleSheet(
            f"{style} border-radius:4px; padding:2px 8px; font-size:11px;")

    def set_connected(self, on: bool) -> None:
        """连接/断开时统一启停交互(保留固定字段的禁用状态)。"""
        self._connected = on
        for w, nominal in self._nominal.items():
            w.setEnabled(on and nominal)
