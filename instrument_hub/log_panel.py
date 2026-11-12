# -*- coding: utf-8 -*-
"""通讯日志面板：所有仪器共用，固定在主界面下方，方便测试快速定位问题。"""
import datetime
from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPushButton, QShortcut,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .sim import LOG_ERR, LOG_RX, LOG_SYS, LOG_TX
from .theme import COLORS
from .widgets import Card

_DIR_STYLE = {
    LOG_TX: ("#FFFFFF", "#4F46E5"),
    LOG_RX: ("#FFFFFF", "#0891B2"),
    LOG_ERR: ("#FFFFFF", "#E11D48"),
    LOG_SYS: ("#FFFFFF", "#6B7280"),
}

_MAX_ROWS = 2000   # 日志上限，防止长跑内存/卡顿


class CommLogPanel(QWidget):
    """底部通讯日志：时间 | 方向 | 帧内容(Hex/ASCII) | 说明，支持过滤/自动滚动/清空/导出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = Card("通讯日志", "TX/RX 帧记录 · 点击行可查看完整内容 · 导出后可随问题单归档")
        root.addWidget(card)

        # ---- 工具条 ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.filter_dir = QComboBox()
        self.filter_dir.addItems(["全部方向", LOG_TX, LOG_RX, LOG_ERR, LOG_SYS])
        self.filter_dir.setFixedWidth(110)
        bar.addWidget(self.filter_dir)

        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("按关键字过滤（命令 / 说明 / 仪器名）…（Esc 清空）")
        self.filter_text.setFixedWidth(260)
        self.filter_text.setClearButtonEnabled(True)
        bar.addWidget(self.filter_text)

        self.auto_scroll = QCheckBox("自动滚动")
        self.auto_scroll.setChecked(True)
        bar.addWidget(self.auto_scroll)
        bar.addStretch(1)

        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("Muted")
        bar.addWidget(self.count_label)

        btn_clear = QPushButton("清空")
        btn_clear.setObjectName("Danger")
        btn_clear.setFixedWidth(76)
        btn_clear.clicked.connect(self.clear)
        bar.addWidget(btn_clear)

        btn_export = QPushButton("导出日志")
        btn_export.setFixedWidth(92)
        btn_export.setObjectName("Primary")
        btn_export.clicked.connect(self.export)
        bar.addWidget(btn_export)
        card.body_lay.addLayout(bar)

        # ---- 表格 ----
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "方向", "帧内容 (Hex / ASCII)", "说明"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 620)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont("Consolas", 10))
        self.table.setWordWrap(False)
        card.body_lay.addWidget(self.table, 1)

        self.filter_dir.currentIndexChanged.connect(self._apply_filter)
        self.filter_text.textChanged.connect(self._apply_filter)
        self.table.itemDoubleClicked.connect(self._show_full_content)
        QShortcut(QKeySequence.Copy, self, self._copy_selection)

        self._rows: List[tuple] = []   # (time, dir, content, note)

    # ------------------------------------------------------------------
    def append(self, direction: str, content: str, note: str = "") -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._rows.append((ts, direction, content, note))
        if len(self._rows) > _MAX_ROWS:
            self._rows = self._rows[-_MAX_ROWS:]
        self.count_label.setText(f"{len(self._rows)} 条")
        self._apply_filter(append_last=True)

    def clear(self) -> None:
        if not self._rows:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("确认清空日志")
        box.setText(f"将清空通讯日志（{len(self._rows)} 条），且不可恢复。")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("确认清空")
        box.button(QMessageBox.Cancel).setText("取消")
        if box.exec_() != QMessageBox.Yes:
            return
        self._rows.clear()
        self.table.setRowCount(0)
        self.count_label.setText("0 条")

    def _copy_selection(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        rows = {}
        for it in items:
            rows.setdefault(it.row(), {})[it.column()] = it.text()
        lines = []
        for r in sorted(rows):
            cols = rows[r]
            lines.append("\t".join(cols.get(c, "") for c in sorted(cols)))
        QApplication.clipboard().setText("\n".join(lines))

    def _show_full_content(self, item) -> None:
        """双击行：弹窗查看完整帧内容（表格里常被截断）。"""
        row = item.row()
        ts = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
        d = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        content = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
        note = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(f"日志详情 · {ts} · {d}")
        box.setText(content or "（空）")
        box.setInformativeText(note)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec_()

    def export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出通讯日志", "comm_log.log", "日志文件 (*.log *.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("# FusionHub 通讯日志  导出时间 "
                    + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
            for ts, d, c, n in self._rows:
                f.write(f"[{ts}] [{d:^3}] {c}    {n}\n")
        self.append(LOG_SYS, f"日志已导出 -> {path}", "导出")

    # ------------------------------------------------------------------
    def _apply_filter(self, *_args, append_last: bool = False) -> None:
        dir_sel = self.filter_dir.currentText()
        key = self.filter_text.text().strip().lower()

        if append_last and dir_sel == "全部方向" and not key:
            self._append_row(*self._rows[-1])
            self._scroll_to_end()
            return

        self.table.setRowCount(0)
        for row in self._rows:
            ts, d, c, n = row
            if dir_sel != "全部方向" and d != dir_sel:
                continue
            if key and key not in (c + n + ts).lower():
                continue
            self._append_row(*row)
        self._scroll_to_end()

    def _append_row(self, ts: str, d: str, c: str, n: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        items = [QTableWidgetItem(ts), QTableWidgetItem(d),
                 QTableWidgetItem(c.replace("\n", "\\n")), QTableWidgetItem(n)]
        fg, bg = _DIR_STYLE.get(d, ("#FFFFFF", "#6B7280"))
        items[1].setBackground(QColor(bg))
        items[1].setForeground(QColor(fg))
        items[1].setTextAlignment(Qt.AlignCenter)
        items[2].setForeground(QColor("#1F2333" if d != LOG_ERR else "#B01030"))
        items[3].setForeground(QColor(COLORS["text_sub"]))
        for col, it in enumerate(items):
            self.table.setItem(r, col, it)

    def _scroll_to_end(self) -> None:
        if self.auto_scroll.isChecked() and self.table.rowCount():
            self.table.scrollToBottom()
