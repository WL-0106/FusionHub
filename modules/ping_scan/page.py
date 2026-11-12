# -*- coding: utf-8 -*-
"""网段Ping扫描助手 · 融合版界面（FusionHub 风格）。

扫描核心逻辑复用原上位机 ping_net_assistant.py（ICMP 探活 / ARP 表 / 目标解析 /
手写 xlsx 导出），界面按整体 UI 风格重建，嵌入「调试助手」分组。
"""
import queue
import socket
import threading

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QApplication, QCheckBox, QFileDialog, QGridLayout,
                             QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                             QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from instrument_hub.widgets import Card

from . import ping_net_assistant as core


class PingScanPage(QWidget):
    """网段 Ping 扫描：目标混写输入 → 并发探活 → 结果明细/在线统计/导出。"""

    COLS = ["IP地址", "状态", "延迟(ms)", "TTL", "主机名", "MAC地址"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = queue.Queue()          # 工作线程 → 界面
        self._stop = threading.Event()
        self._workers = []
        self._done = 0
        self._total = 0
        self._online = 0
        self._rows = {}                  # ip -> (alive, ms, ttl, hostname)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_target_card())
        root.addWidget(self._build_option_card())
        root.addWidget(self._build_result_card(), 1)

        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._drain)

    # ------------------------------------------------------------ 扫描目标
    def _build_target_card(self) -> Card:
        card = Card("扫描目标", "支持混写：单个 IP / 起止范围 / 网段(CIDR 或 x.x.x.*)，用空格、逗号或换行分开")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.target_edit = QPlainTextEdit()
        self.target_edit.setPlaceholderText(
            "例如：192.168.1.100　192.168.1.10-50　192.168.1.0/24　192.168.1.*　（一行一个网段也可）")
        self.target_edit.setFixedHeight(64)
        row.addWidget(self.target_edit, 1)
        col = QVBoxLayout()
        col.setSpacing(8)
        b_fill = QPushButton("填入本机网段")
        b_fill.setToolTip("把本机所有网段填入目标框")
        b_fill.clicked.connect(self._fill_local)
        col.addWidget(b_fill)
        b_clear = QPushButton("清空")
        b_clear.clicked.connect(self.target_edit.clear)
        col.addWidget(b_clear)
        row.addLayout(col)
        card.body_lay.addLayout(row)
        return card

    # ------------------------------------------------------------ 高级选项
    def _build_option_card(self) -> Card:
        card = Card("高级选项", "并发数与超时决定扫描速度；解析主机名较慢，默认关闭")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)

        g.addWidget(QLabel("并发数"), 0, 0)
        self.sp_conc = QSpinBox()
        self.sp_conc.setRange(1, 256)
        self.sp_conc.setValue(32)
        g.addWidget(self.sp_conc, 0, 1)

        g.addWidget(QLabel("超时(ms)"), 0, 2)
        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(100, 10000)
        self.sp_timeout.setValue(800)
        g.addWidget(self.sp_timeout, 0, 3)

        g.addWidget(QLabel("重试次数"), 0, 4)
        self.sp_retry = QSpinBox()
        self.sp_retry.setRange(0, 5)
        self.sp_retry.setValue(1)
        g.addWidget(self.sp_retry, 0, 5)

        self.chk_skip_self = QCheckBox("跳过本机")
        self.chk_skip_self.setChecked(True)
        g.addWidget(self.chk_skip_self, 0, 6)
        self.chk_mac = QCheckBox("读取 MAC")
        self.chk_mac.setChecked(True)
        g.addWidget(self.chk_mac, 0, 7)
        self.chk_host = QCheckBox("解析主机名(慢)")
        g.addWidget(self.chk_host, 0, 8)
        self.chk_only_online = QCheckBox("只显示在线")
        g.addWidget(self.chk_only_online, 0, 9)
        card.body_lay.addLayout(g)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_start = QPushButton("开始扫描")
        self.btn_start.setObjectName("Primary")
        self.btn_start.clicked.connect(self.start_scan)
        bar.addWidget(self.btn_start)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_scan)
        bar.addWidget(self.btn_stop)
        self.btn_clear = QPushButton("清空结果")
        self.btn_clear.clicked.connect(self.clear_results)
        bar.addWidget(self.btn_clear)
        self.btn_export = QPushButton("导出详细表")
        self.btn_export.clicked.connect(self.export_table)
        bar.addWidget(self.btn_export)
        self.btn_copy = QPushButton("复制在线 IP")
        self.btn_copy.clicked.connect(self.copy_online)
        bar.addWidget(self.btn_copy)
        self.btn_help = QPushButton("格式说明")
        self.btn_help.clicked.connect(self.show_help)
        bar.addWidget(self.btn_help)
        bar.addStretch(1)
        self.stat_label = QLabel("就绪")
        self.stat_label.setObjectName("Muted")
        bar.addWidget(self.stat_label)
        card.body_lay.addLayout(bar)
        return card

    # ------------------------------------------------------------ 结果明细
    def _build_result_card(self) -> Card:
        card = Card("结果明细", "在线绿色 / 离线灰色 · 双击行可复制 IP")
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(4, 240)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self._copy_row_ip)
        card.body_lay.addWidget(self.table, 1)
        return card

    # ------------------------------------------------------------ 扫描控制
    def start_scan(self) -> None:
        text = self.target_edit.toPlainText()
        targets, err = core.parse_targets(text)
        if err:
            QMessageBox.warning(self, "目标解析失败", str(err))
            return
        if not targets:
            QMessageBox.information(self, "提示", "请先输入扫描目标（IP / 范围 / 网段）")
            return
        if self.chk_skip_self.isChecked():
            me = {ip for _, ip in core.local_networks()}
            targets = [t for t in targets if t not in me]
        self.clear_results(quiet=True)
        self._stop.clear()
        self._total = len(targets)
        self.table.setRowCount(self._total)
        for i, ip in enumerate(targets):
            self.table.setItem(i, 0, QTableWidgetItem(ip))
            st = QTableWidgetItem("扫描中")
            st.setForeground(QColor("#7A7B93"))
            self.table.setItem(i, 1, st)
            self._rows[ip] = (None, None, None, "")

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._timer.start()
        self.stat_label.setText(f"扫描中… 0/{self._total}")

        conc = self.sp_conc.value()
        timeout = self.sp_timeout.value()
        retry = self.sp_retry.value()
        want_host = self.chk_host.isChecked()
        chunks = [targets[i::conc] for i in range(conc)]
        for part in chunks:
            if not part:
                continue
            t = threading.Thread(
                target=self._worker, args=(part, timeout, retry, want_host), daemon=True)
            t.start()
            self._workers.append(t)

    def _worker(self, ips, timeout, retry, want_host) -> None:
        for ip in ips:
            if self._stop.is_set():
                break
            alive, ms, ttl = False, None, None
            for _ in range(retry + 1):
                alive, ms, ttl = core.ping_once(ip, timeout)
                if alive:
                    break
            host = ""
            if alive and want_host:
                try:
                    host = socket.gethostbyaddr(ip)[0]
                except Exception:
                    host = ""
            self._q.put((ip, alive, ms, ttl, host))
        self._q.put(("__worker_done__",))

    def stop_scan(self) -> None:
        self._stop.set()
        self.stat_label.setText("已停止扫描")

    def clear_results(self, quiet: bool = False) -> None:
        self.table.setRowCount(0)
        self._rows.clear()
        self._done = self._online = self._total = 0
        self._workers.clear()
        if not quiet:
            self.stat_label.setText("已清空")

    # ------------------------------------------------------------ 结果更新
    def _drain(self) -> None:
        finished = False
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item[0] == "__worker_done__":
                finished = True
                continue
            ip, alive, ms, ttl, host = item
            self._done += 1
            if alive:
                self._online += 1
            self._rows[ip] = (alive, ms, ttl, host)
            self._update_row(ip, alive, ms, ttl, host)
        self.stat_label.setText(
            f"扫描中… {self._done}/{self._total}　在线 {self._online}"
            if not finished else
            f"完成：{self._total} 个目标，在线 {self._online} 个")
        if finished and self._done >= self._total:
            self._timer.stop()
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            if self.chk_mac.isChecked():
                self.read_mac()

    def _update_row(self, ip, alive, ms, ttl, host) -> None:
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0) and self.table.item(i, 0).text() == ip:
                st = QTableWidgetItem("在线" if alive else "离线")
                st.setForeground(QColor("#047857" if alive else "#9CA3AF"))
                self.table.setItem(i, 1, st)
                self.table.setItem(i, 2, QTableWidgetItem(
                    "-" if ms is None else f"{ms:.0f}" if float(ms).is_integer() else f"{ms:.1f}"))
                self.table.setItem(i, 3, QTableWidgetItem("-" if ttl is None else str(ttl)))
                self.table.setItem(i, 4, QTableWidgetItem(host or "-"))
                if not alive or self.chk_only_online.isChecked():
                    self.table.setRowHidden(i, not alive)
                return

    def read_mac(self) -> None:
        table = core.read_arp_table()
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it is not None:
                self.table.setItem(i, 5, QTableWidgetItem(table.get(it.text(), "-")))
        self.stat_label.setText(self.stat_label.text() + "　MAC 已回填")

    # ------------------------------------------------------------ 工具
    def _fill_local(self) -> None:
        nets = core.local_networks()
        if not nets:
            QMessageBox.information(self, "提示", "未识别到本机网段")
            return
        self.target_edit.setPlainText(" ".join(n for n, _ in nets))

    def export_table(self) -> None:
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "提示", "暂无结果可导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出详细表", "网段Ping扫描结果.xlsx", "Excel 工作簿 (*.xlsx);;CSV 文件 (*.csv)")
        if not path:
            return
        rows = []
        for i in range(self.table.rowCount()):
            rows.append([self.table.item(i, c).text() if self.table.item(i, c) else ""
                         for c in range(len(self.COLS))])
        if path.lower().endswith(".xlsx"):
            core.write_xlsx(path, self.COLS, rows, "扫描结果", [16, 8, 10, 8, 28, 20])
        else:
            import csv as _csv
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = _csv.writer(f)
                w.writerow(self.COLS)
                w.writerows(rows)
        QMessageBox.information(self, "导出完成", f"已导出 {len(rows)} 条结果：\n{path}")

    def copy_online(self) -> None:
        ips = [self.table.item(i, 0).text() for i in range(self.table.rowCount())
               if self.table.item(i, 1) and self.table.item(i, 1).text() == "在线"
               and self.table.item(i, 0)]
        if not ips:
            QMessageBox.information(self, "提示", "暂无在线 IP")
            return
        QApplication.clipboard().setText("\n".join(ips))
        self.stat_label.setText(f"已复制 {len(ips)} 个在线 IP")

    def _copy_row_ip(self, row: int, _col: int) -> None:
        it = self.table.item(row, 0)
        if it is not None:
            QApplication.clipboard().setText(it.text())
            self.stat_label.setText(f"已复制 {it.text()}")

    def show_help(self) -> None:
        QMessageBox.information(
            self, "格式说明 · 网段Ping扫描助手",
            "目标写法（可混写，用空格 / 逗号 / 换行分开）：\n"
            "① 单个 IP：192.168.1.100\n"
            "② 起止范围：192.168.1.10-50 或 192.168.1.10-192.168.1.254\n"
            "③ 整个网段：192.168.1.0/24（或 192.168.1.*）\n"
            "④ 多段批量：一行写一个网段\n\n"
            "排查指引（扫不到设备时）：\n"
            "1) 确认本机与目标同网段或有路由；2) 关闭防火墙 ICMP 限制；\n"
            "3) 超时调大重试；4) 用「填入本机网段」先扫本段验证。\n\n"
            "扫描核心复用原上位机逻辑（ICMP 探活/ARP/导出），行为一致。")

    def shutdown(self) -> None:
        self.stop_scan()
        self._timer.stop()
