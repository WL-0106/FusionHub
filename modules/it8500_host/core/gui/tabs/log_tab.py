"""底部常驻「信息与日志」面板: 设备信息条 + 通讯日志区。

被主窗口放在分割条下半区, 任意页签下均可查看收发日志。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal as Signal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ...it8500.protocol import Identity


class LogTab(QWidget):
    read_identity = Signal()
    read_barcode = Signal()
    diagnose = Signal()                 # 请求通讯诊断 (波特率/地址扫描)

    MAX_LINES = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 2, 8, 2)
        root.setSpacing(4)

        # ---- 第 1 行: 设备信息 ----
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        def kv(label: str) -> QLabel:
            lb = QLabel(label)
            lb.setProperty("role", "value")
            row1.addWidget(lb)
            return lb

        def tag(text: str) -> None:
            lb = QLabel(text)
            lb.setProperty("role", "hint")
            row1.addWidget(lb)

        tag("型号:")
        self.lbl_model = kv("—")
        tag("序列号:")
        self.lbl_serial = kv("—")
        tag("软件版本:")
        self.lbl_version = kv("—")
        tag("条形码:")
        self.lbl_barcode = kv("—")
        row1.addStretch(1)

        self.btn_id = QPushButton("读取设备信息 (6AH)")
        self.btn_id.setObjectName("ConnectBtn")
        self.btn_bc = QPushButton("读取条形码 (6BH)")
        self.btn_id.clicked.connect(self.read_identity.emit)
        self.btn_bc.clicked.connect(self.read_barcode.emit)
        row1.addWidget(self.btn_id)
        row1.addWidget(self.btn_bc)
        root.addLayout(row1)

        # ---- 第 2 行: 日志控制 ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.btn_diag = QPushButton("通讯诊断 (扫描波特率/地址)")
        self.btn_diag.setObjectName("ConnectBtn")
        self.btn_diag.setToolTip(
            "断开连接后使用: 依次尝试 4 档波特率 × 地址扫描, "
            "找到设备后回填界面; 即使失败也会列出线上收到的乱码字节")
        self.btn_diag.clicked.connect(self.diagnose.emit)
        self.chk_auto = QCheckBox("自动滚动")
        self.chk_auto.setChecked(True)
        self.lbl_count = QLabel("0 行")
        self.lbl_count.setProperty("role", "hint")
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.clear)
        row2.addWidget(self.btn_diag)
        row2.addWidget(self.chk_auto)
        row2.addStretch(1)
        row2.addWidget(self.lbl_count)
        row2.addWidget(btn_clear)
        root.addLayout(row2)

        # ---- 日志文本 (保底高度: 保证窗口再小也能看到多行日志) ----
        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setMaximumBlockCount(self.MAX_LINES)
        self.txt.setFont(QFont("Consolas", 9))
        self.txt.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.txt.setMinimumHeight(150)      # ≈7~8 行, 不允许被压没
        self.txt.setPlaceholderText(
            "通讯日志 (TX 发送 / RX 接收 / RAW 原始字节)…")
        root.addWidget(self.txt, 1)

        # 面板整体保底高度 (含两行控制条 + 日志)
        self.setMinimumHeight(230)

    # ----------------------------------------------------------
    def append_log(self, text: str) -> None:
        self.txt.appendPlainText(text)
        if self.chk_auto.isChecked():
            sb = self.txt.verticalScrollBar()
            sb.setValue(sb.maximum())
        self.lbl_count.setText(f"{self.txt.document().blockCount()} 行")

    def clear(self) -> None:
        self.txt.clear()
        self.lbl_count.setText("0 行")

    def set_diag_running(self, running: bool) -> None:
        self.btn_diag.setEnabled(not running)
        self.btn_diag.setText("诊断中… 请稍候" if running
                              else "通讯诊断 (扫描波特率/地址)")

    def show_identity(self, ident: Identity) -> None:
        self.lbl_model.setText(ident.model or "—")
        self.lbl_serial.setText(ident.serial or "—")
        self.lbl_version.setText(ident.version or "—")

    def show_barcode(self, code: str) -> None:
        self.lbl_barcode.setText(code or "—")

    def set_connected(self, ok: bool) -> None:
        self.btn_id.setEnabled(ok)
        self.btn_bc.setEnabled(ok)
        self.btn_diag.setEnabled(not ok)      # 诊断仅在断开时可用
        if not ok:
            for lb in (self.lbl_model, self.lbl_serial, self.lbl_version,
                       self.lbl_barcode):
                lb.setText("—")
