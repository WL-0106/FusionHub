# -*- coding: utf-8 -*-
"""调试记录页：调试过程留痕（连接信息/设定值/输出值/IO/采集值），可勾选仪器、可导出表格。

- 所有记录始终保留（可追溯），勾选只决定"表格展示与导出"包含哪些仪器；
- 手动快照 + 自动记录（每 5 秒）两种留痕方式；
- 导出 Excel(.xlsx)/CSV(.csv)，随问题单/交付包归档。
"""
from typing import Callable, Dict, List

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QKeySequence
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout,
                             QLabel, QMessageBox, QPushButton, QScrollArea, QShortcut,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import registry
from .recorder import DebugRecorder
from .sim import LOG_SYS
from .spec import InstrumentSpec
from .widgets import Card


class InstrumentListDialog(QDialog):
    """已测试仪器清单：每台仪器一行（型号 / IP / 串口 / 端口 + 调试时间），可单独预览与导出。"""

    WIDTHS = [132, 110, 92, 92, 150, 196, 110, 82, 158, 82, 150, 150]

    def __init__(self, recorder: DebugRecorder, spec_ids: List[str],
                 log: Callable[[str, str, str], None], parent=None):
        super().__init__(parent)
        self.recorder = recorder
        self.spec_ids = spec_ids
        self.log = log
        self.setWindowTitle("已测试仪器清单")
        self.setModal(True)
        self.resize(1180, 500)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        rows = recorder.tested_summary(spec_ids)
        t = QLabel(f"已测试仪器清单 · 共 {len(rows)} 台")
        t.setObjectName("H1")
        lay.addWidget(t)
        sub = QLabel("调试完成后的独立汇总表：每台仪器一行，含型号、IP 地址、串口/COM口、波特率、"
                     "端口号与调试起止时间，可单独导出归档。")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.table = QTableWidget(0, len(DebugRecorder.SUMMARY_HEADERS))
        self.table.setHorizontalHeaderLabels(DebugRecorder.SUMMARY_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        for i, w in enumerate(self.WIDTHS):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        for s in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            for c, v in enumerate(s.cells()):
                it = QTableWidgetItem(str(v))
                if c == 5 and s.ip != "-":
                    it.setForeground(QColor("#0E7490"))
                elif c == 6 and s.com != "-":
                    it.setForeground(QColor("#4F46E5"))
                self.table.setItem(i, c, it)
        lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        self.count_label = QLabel(f"{len(rows)} 台 · 共 {sum(s.count for s in rows)} 条调试记录")
        self.count_label.setObjectName("Muted")
        bar.addWidget(self.count_label)
        bar.addStretch(1)
        btn_export = QPushButton("导出表格")
        btn_export.setObjectName("Primary")
        btn_export.clicked.connect(self._export)
        bar.addWidget(btn_export)
        btn_close = QPushButton("关闭")
        btn_close.setFixedSize(100, 38)
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        bar.addWidget(btn_close)
        lay.addLayout(bar)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出已测试仪器清单", "FusionHub_仪器清单.xlsx",
            "Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv)")
        if not path:
            return
        real = self.recorder.export_summary(path, self.spec_ids)
        n = len(self.recorder.tested_summary(self.spec_ids))
        if self.log:
            self.log(LOG_SYS, "", f"[调试记录] 已导出仪器清单 {n} 台 -> {real}")
        QMessageBox.information(self, "导出完成", f"已生成仪器清单（{n} 台）：\n{real}")


class RecordPage(QWidget):
    COLS = ["时间", "仪器", "型号", "接口", "IP/COM口", "波特率", "端口号",
            "项目", "类型", "数值", "单位", "说明"]

    def __init__(self, recorder: DebugRecorder,
                 get_sessions: Callable[[], List[tuple]],
                 log: Callable[[str, str, str], None] = None,
                 parent=None):
        super().__init__(parent)
        self.recorder = recorder
        self.get_sessions = get_sessions
        self.log = log
        self.checks: Dict[str, QCheckBox] = {}
        self._auto = False

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._auto_snapshot)

        self._build_ui()
        QShortcut(QKeySequence.Copy, self, self._copy_selection)
        QShortcut(QKeySequence("Ctrl+E"), self, self._export)
        self.refresh()

    # ================================================================ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ------- 工具条卡片 -------
        head = Card("调试记录",
                    "调试过程中使用过的仪器与数据全部留痕 · 勾选仪器决定表格/导出内容 · 原始记录始终保留可追溯")
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_snapshot = QPushButton("手动记录快照")
        self.btn_snapshot.setObjectName("Primary")
        self.btn_snapshot.setToolTip("立即记录当前所有仪器状态")
        self.btn_snapshot.clicked.connect(self._manual_snapshot)
        bar.addWidget(self.btn_snapshot)

        self.btn_auto = QPushButton("开始自动记录（每 5s）")
        self.btn_auto.setToolTip("开启后每 5 秒自动快照一次")
        self.btn_auto.clicked.connect(self._toggle_auto)
        bar.addWidget(self.btn_auto)

        self.btn_clear = QPushButton("清空记录")
        self.btn_clear.setObjectName("Danger")
        self.btn_clear.setToolTip("清空后不可恢复，导出前请确认")
        self.btn_clear.clicked.connect(self._clear)
        bar.addWidget(self.btn_clear)
        bar.addStretch(1)

        self.count_label = QLabel("0 条记录")
        self.count_label.setObjectName("Muted")
        bar.addWidget(self.count_label)

        self.btn_list = QPushButton("生成仪器清单")
        self.btn_list.setToolTip("按仪器汇总型号/IP/端口/调试时间，可单独导出")
        self.btn_list.clicked.connect(self._show_list)
        bar.addWidget(self.btn_list)

        self.btn_export = QPushButton("导出表格")
        self.btn_export.setObjectName("Primary")
        self.btn_export.setToolTip("导出 Excel/CSV（Ctrl+E）")
        self.btn_export.clicked.connect(self._export)
        bar.addWidget(self.btn_export)
        head.body_lay.addLayout(bar)
        root.addWidget(head)

        # ------- 勾选 + 表格 -------
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)

        sel_card = Card("选择生成表格的仪器", "取消勾选仅隐藏显示，不影响已记录数据")
        sel_card.setFixedWidth(288)
        sel_bar = QHBoxLayout()
        all_btn = QPushButton("全选")
        all_btn.clicked.connect(lambda: self._set_all(True))
        sel_bar.addWidget(all_btn)
        none_btn = QPushButton("清空选择")
        none_btn.clicked.connect(lambda: self._set_all(False))
        sel_bar.addWidget(none_btn)
        sel_card.body_lay.addLayout(sel_bar)

        sel_host = QWidget()
        self.sel_lay = QVBoxLayout(sel_host)
        self.sel_lay.setContentsMargins(0, 0, 0, 0)
        self.sel_lay.setSpacing(6)
        self._build_checks()
        self.sel_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        scroll.setWidget(sel_host)
        sel_card.body_lay.addWidget(scroll, 1)
        bl.addWidget(sel_card)

        tbl_card = Card("记录明细", "类型：设定值 / 输出值 / 反馈值 / 采集值 / 连接")
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 152)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 92)
        self.table.setColumnWidth(3, 84)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 76)
        self.table.setColumnWidth(6, 120)
        self.table.setColumnWidth(7, 132)
        self.table.setColumnWidth(8, 78)
        self.table.setColumnWidth(9, 96)
        self.table.setColumnWidth(10, 60)
        self.table.horizontalHeader().setStretchLastSection(True)
        tbl_card.body_lay.addWidget(self.table, 1)
        bl.addWidget(tbl_card, 1)
        root.addWidget(body, 1)

    def _build_checks(self) -> None:
        for spec in self.get_specs():
            cb = QCheckBox(f"{spec.name}（{spec.model}）")
            cb.setChecked(True)
            cb.setToolTip(f"{spec.group} · {spec.iface}")
            cb.stateChanged.connect(self.refresh)
            self.checks[spec.id] = cb
            self.sel_lay.addWidget(cb)

    def get_specs(self) -> List[InstrumentSpec]:
        """勾选列表包含全部已注册仪器 + 融合的模块上位机：用过的都可追溯。"""
        from . import module_page
        mods = [module_page.recorder_spec(m) for m in module_page.all_modules()]
        return registry.all_specs() + mods

    # ================================================================ 行为
    def _selected_ids(self) -> List[str]:
        return [sid for sid, cb in self.checks.items() if cb.isChecked()]

    def _set_all(self, checked: bool) -> None:
        for cb in self.checks.values():
            cb.setChecked(checked)

    def _manual_snapshot(self) -> None:
        n = 0
        for spec, session in self.get_sessions():
            n += self.recorder.record_snapshot(spec, session)
        self.refresh()
        if self.log:
            self.log(LOG_SYS, "", f"[调试记录] 手动快照 {n} 条")

    def _toggle_auto(self) -> None:
        self._auto = not self._auto
        if self._auto:
            self._timer.start()
            self.btn_auto.setText("停止自动记录")
            self.btn_auto.setObjectName("Primary")
            if self.log:
                self.log(LOG_SYS, "", "[调试记录] 自动记录已开启（每 5s）")
        else:
            self._timer.stop()
            self.btn_auto.setText("开始自动记录（每 5s）")
            self.btn_auto.setObjectName("")
            if self.log:
                self.log(LOG_SYS, "", "[调试记录] 自动记录已停止")
        self.btn_auto.style().unpolish(self.btn_auto)
        self.btn_auto.style().polish(self.btn_auto)

    def _auto_snapshot(self) -> None:
        for spec, session in self.get_sessions():
            self.recorder.record_snapshot(spec, session)
        self.refresh()

    def _clear(self) -> None:
        n = len(self.recorder.rows)
        if n == 0:
            return
        # 破坏性操作：二次确认，回车默认不删
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("确认清空记录")
        box.setText(f"将清空全部 {n} 条调试记录，且不可恢复。")
        box.setInformativeText("建议先导出备份。确定继续？")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("确认清空")
        box.button(QMessageBox.Cancel).setText("取消")
        if box.exec_() != QMessageBox.Yes:
            return
        self.recorder.clear()
        self.refresh()
        if self.log:
            self.log(LOG_SYS, "", f"[调试记录] 已清空 {n} 条记录")

    def _copy_selection(self) -> None:
        """Ctrl+C：复制表格选中行（TSV，可直接贴进 Excel）。"""
        items = self.table.selectedItems()
        if not items:
            return
        rows: Dict[int, Dict[int, str]] = {}
        for it in items:
            rows.setdefault(it.row(), {})[it.column()] = it.text()
        lines = []
        for r in sorted(rows):
            cols = rows[r]
            lines.append("\t".join(cols.get(c, "") for c in sorted(cols)))
        QApplication.clipboard().setText("\n".join(lines))
        if self.log:
            self.log(LOG_SYS, "", f"[调试记录] 已复制 {len(rows)} 行")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出调试记录表格", "FusionHub_调试记录.xlsx",
            "Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv)")
        if not path:
            return
        real = self.recorder.export(path, self._selected_ids())
        n = len(self.recorder.rows_for(self._selected_ids()))
        if self.log:
            self.log(LOG_SYS, "", f"[调试记录] 已导出 {n} 条 -> {real}")
        QMessageBox.information(self, "导出完成", f"已导出调试记录 {n} 条：\n{real}")

    def _show_list(self) -> None:
        """生成"已测试仪器清单"独立表：每台一行（型号/IP/串口/端口），可预览、可单独导出。"""
        ids = self._selected_ids()
        if not self.recorder.tested_summary(ids):
            QMessageBox.information(
                self, "仪器清单",
                "所选仪器暂无调试记录。\n先连接仪器并记录（手动快照或自动记录）后再生成。")
            return
        dlg = InstrumentListDialog(self.recorder, ids, self.log, self)
        dlg.exec_()

    # ================================================================ 表格
    def refresh(self) -> None:
        rows = self.recorder.rows_for(self._selected_ids())
        self.count_label.setText(f"{len(rows)} 条（全部 {len(self.recorder.rows)} 条）")
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            vals = [r.ts, r.name, r.model, r.iface, r.addr, r.baud, r.port_no,
                    r.item, r.kind, r.value, r.unit, r.note]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if r.kind == "输出值":
                    it.setForeground(QColor("#B01030" if v == "开" else "#047857") if c == 9 else QColor("#23263A"))
                elif r.kind == "设定值" and c == 9:
                    it.setForeground(QColor("#4F46E5"))
                elif r.kind == "采集值" and c == 9:
                    it.setForeground(QColor("#0E7490"))
                self.table.setItem(i, c, it)
        self.table.scrollToBottom()
