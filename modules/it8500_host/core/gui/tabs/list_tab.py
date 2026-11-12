"""LIST (列表) 编程页: 步进表格、循环/步数、文件存储区、触发型。"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal as Signal
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

MODE_UNITS = {"CC": "A", "CV": "V", "CW": "W", "CR": "Ω"}


class ListTab(QWidget):
    cfg_set = Signal(str, object)     # ("mode"|"loop"|"steps"|"file"|"part"|"area_save"|"area_recall", value)
    cfg_read = Signal(str)
    step_write = Signal(int, float, float)          # 步号, 值, 时间ms
    step_read = Signal(int)
    steps_write_all = Signal(list)                  # [(idx, value, time), ...]
    steps_read_all = Signal(int)
    trig_set = Signal(int)
    trig_read = Signal()
    trig_send = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---------- 顶部配置 ----------
        grp_cfg = QGroupBox("LIST 配置")
        g = QGridLayout(grp_cfg)
        g.setHorizontalSpacing(8)

        self.cmb_mode = QComboBox()
        for m in MODE_UNITS:
            self.cmb_mode.addItem(f"{m} ({MODE_UNITS[m]})", m)
        self.cmb_loop = QComboBox()
        self.cmb_loop.addItem("单次 ONCE", False)
        self.cmb_loop.addItem("循环 REPEAT", True)
        self.spn_steps = QSpinBox()
        self.spn_steps.setRange(1, 1024)
        self.spn_steps.setValue(4)
        self.edt_file = QLineEdit("LIST0001")
        self.edt_file.setMaxLength(10)
        self.cmb_part = QComboBox()
        for v in (1, 2, 4, 8):
            self.cmb_part.addItem(f"{v} 区划分", v)

        def add(r, c, w_label, w):
            g.addWidget(QLabel(w_label), r, c)
            g.addWidget(w, r, c + 1)

        add(0, 0, "操作模式:", self.cmb_mode)
        add(0, 2, "循环模式:", self.cmb_loop)
        add(0, 4, "步数:", self.spn_steps)
        add(1, 0, "文件名:", self.edt_file)
        g.addWidget(self.cmb_part, 1, 3, 1, 2)
        g.addWidget(QLabel("存储划分:"), 1, 2)

        btn_cfg_set = QPushButton("写入配置")
        btn_cfg_set.setObjectName("ConnectBtn")
        btn_cfg_get = QPushButton("读取配置")
        btn_cfg_set.clicked.connect(self._on_cfg_set)
        btn_cfg_get.clicked.connect(lambda: self.cfg_read.emit("all"))
        hint = QLabel("配置按模式/循环/步数/文件名/存储划分五项依次下发")
        hint.setProperty("role", "hint")
        g.addWidget(hint, 2, 0, 1, 3)
        g.addWidget(btn_cfg_set, 2, 3)
        g.addWidget(btn_cfg_get, 2, 4)
        root.addWidget(grp_cfg)

        # ---------- 步进表格 ----------
        grp_steps = QGroupBox("步进序列")
        vs = QVBoxLayout(grp_steps)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["步号", f"值", "时间 (ms)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 220)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        vs.addWidget(self.table)

        row = QHBoxLayout()
        btn_add = QPushButton("添加步")
        btn_del = QPushButton("删除所选")
        btn_one_w = QPushButton("写入所选步")
        btn_one_r = QPushButton("读取所选步")
        btn_all_w = QPushButton("全部下载 →")
        btn_all_w.setObjectName("ConnectBtn")
        btn_all_r = QPushButton("← 读取全部")
        for b in (btn_add, btn_del, btn_one_r, btn_one_w, btn_all_r, btn_all_w):
            row.addWidget(b)
        row.addStretch(1)
        vs.addLayout(row)
        root.addWidget(grp_steps, 1)

        # ---------- 存储区 ----------
        grp_file = QGroupBox("LIST 文件存储区")
        gf = QHBoxLayout(grp_file)
        self.spn_area = QSpinBox()
        self.spn_area.setRange(1, 8)
        btn_save = QPushButton("保存到区")
        btn_recall = QPushButton("从区取出")
        gf.addWidget(QLabel("区域:"))
        gf.addWidget(self.spn_area)
        gf.addWidget(btn_save)
        gf.addWidget(btn_recall)
        gf.addStretch(1)
        root.addWidget(grp_file)

        # ---------- 触发 ----------
        grp_trig = QGroupBox("触发")
        gt = QHBoxLayout(grp_trig)
        self.cmb_trig = QComboBox()
        self.cmb_trig.addItem("IMMediate 立即", 0)
        self.cmb_trig.addItem("EXTernal 外部", 1)
        self.cmb_trig.addItem("BUS 总线", 2)
        btn_trig_set = QPushButton("设置触发模式")
        btn_trig_get = QPushButton("读取")
        btn_trig_send = QPushButton("发送 BUS 触发")
        btn_trig_send.setObjectName("ConnectBtn")
        gt.addWidget(self.cmb_trig)
        gt.addWidget(btn_trig_set)
        gt.addWidget(btn_trig_get)
        gt.addWidget(btn_trig_send)
        gt.addStretch(1)
        root.addWidget(grp_trig)

        # ---------- 信号 ----------
        btn_add.clicked.connect(lambda: self._add_rows(1))
        btn_del.clicked.connect(self._del_rows)
        btn_one_w.clicked.connect(self._write_selected)
        btn_one_r.clicked.connect(self._read_selected)
        btn_all_w.clicked.connect(self._write_all)
        btn_all_r.clicked.connect(
            lambda: self.steps_read_all.emit(self.spn_steps.value()))
        btn_save.clicked.connect(
            lambda: self.cfg_set.emit("area_save", self.spn_area.value()))
        btn_recall.clicked.connect(
            lambda: self.cfg_set.emit("area_recall", self.spn_area.value()))
        btn_trig_set.clicked.connect(
            lambda: self.trig_set.emit(self.cmb_trig.currentData()))
        btn_trig_get.clicked.connect(self.trig_read.emit)
        btn_trig_send.clicked.connect(self.trig_send.emit)

        self._add_rows(4)

    # ---------------------------------------------------------- 表格操作
    def _selected_row(self) -> int:
        rows = {i.row() for i in self.table.selectedIndexes()}
        return sorted(rows)[0] if rows else -1

    def _add_rows(self, n: int = 1) -> None:
        for _ in range(n):
            r = self.table.rowCount()
            self.table.insertRow(r)
            idx = QTableWidgetItem(str(r))
            idx.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, idx)
            self.table.setItem(r, 1, QTableWidgetItem("1.000"))
            self.table.setItem(r, 2, QTableWidgetItem("100.0"))

    def _del_rows(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._renumber()

    def _renumber(self) -> None:
        for r in range(self.table.rowCount()):
            it = QTableWidgetItem(str(r))
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, it)

    def _row_values(self, r: int) -> tuple[float, float]:
        try:
            value = float(self.table.item(r, 1).text())
            t = float(self.table.item(r, 2).text())
        except (AttributeError, ValueError, TypeError):
            raise ValueError(f"第 {r} 步数值格式错误")
        return value, t

    def _write_selected(self) -> None:
        r = self._selected_row()
        if r < 0:
            return
        value, t = self._row_values(r)
        self.step_write.emit(r, value, t)

    def _read_selected(self) -> None:
        r = self._selected_row()
        if r >= 0:
            self.step_read.emit(r)

    def _write_all(self) -> None:
        out = []
        for r in range(self.table.rowCount()):
            value, t = self._row_values(r)
            out.append((r, value, t))
        self.steps_write_all.emit(out)

    # ---------------------------------------------------------- 配置
    def _on_cfg_set(self) -> None:
        self.cfg_set.emit("mode", self.cmb_mode.currentData())
        self.cfg_set.emit("loop", self.cmb_loop.currentData())
        self.cfg_set.emit("steps", self.spn_steps.value())
        self.cfg_set.emit("file", self.edt_file.text().strip())
        self.cfg_set.emit("part", self.cmb_part.currentData())

    # ---------------------------------------------------------- 回填
    def fill_steps(self, steps: list) -> None:
        self.table.setRowCount(0)
        for s in steps:
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(str(s.index))
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(f"{s.value:g}"))
            self.table.setItem(r, 2, QTableWidgetItem(f"{s.time_ms:g}"))

    def fill_step(self, step) -> None:
        r = step.index
        while self.table.rowCount() <= r:
            self._add_rows(1)
        self.table.item(r, 1).setText(f"{step.value:g}")
        self.table.item(r, 2).setText(f"{step.time_ms:g}")

    def fill_config(self, *, mode=None, loop=None, steps=None,
                    file=None, part=None) -> None:
        if mode is not None:
            i = self.cmb_mode.findData(mode)
            if i >= 0:
                self.cmb_mode.setCurrentIndex(i)
        if loop is not None:
            i = self.cmb_loop.findData(bool(loop))
            if i >= 0:
                self.cmb_loop.setCurrentIndex(i)
        if steps is not None:
            self.spn_steps.setValue(steps)
        if file is not None:
            self.edt_file.setText(file)
        if part is not None:
            i = self.cmb_part.findData(part)
            if i >= 0:
                self.cmb_part.setCurrentIndex(i)

    def fill_trigger(self, mode: int) -> None:
        i = self.cmb_trig.findData(mode)
        if i >= 0:
            self.cmb_trig.setCurrentIndex(i)

    def set_connected(self, ok: bool) -> None:
        for w in (self.cmb_mode, self.cmb_loop, self.spn_steps, self.edt_file,
                  self.cmb_part, self.spn_area, self.cmb_trig, self.table):
            w.setEnabled(ok)
