# -*- coding: utf-8 -*-
"""弹窗：输出二次确认 / 版本记录。"""
from typing import List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .version import APP_NAME, APP_VERSION, VERSION_HISTORY
from .widgets import Chip


class ConfirmOutputDialog(QDialog):
    """输出开启二次确认弹窗 —— 所有涉及电源/拉载的输出按钮必须经过它。"""

    def __init__(self, instrument: str, output_label: str, risk: str,
                 param_summary: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认开启输出")
        self.setModal(True)
        self.setFixedSize(470, 360)
        self.setStyleSheet("QDialog { background: #FFFFFF; border-radius: 16px; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(12)

        head = QHBoxLayout()
        icon = QLabel("⚠")
        icon.setStyleSheet("background:#FFE4E6; color:#E11D48; border-radius:18px;"
                           "font-size:20px; padding:6px 12px;")
        head.addWidget(icon)
        title = QLabel("确认开启输出？")
        title.setObjectName("H1")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        info = QLabel(f"仪器：<b>{instrument}</b>　　输出：<b>{output_label}</b>")
        info.setWordWrap(True)
        lay.addWidget(info)

        risk_box = QFrame()
        risk_box.setStyleSheet("background:#FFF4F5; border:1px solid #FFD3D8; border-radius:10px;")
        rl = QVBoxLayout(risk_box)
        rl.setContentsMargins(12, 10, 12, 10)
        rt = QLabel("风险提示")
        rt.setStyleSheet("color:#B01030; font-weight:700;")
        rl.addWidget(rt)
        rv = QLabel(risk)
        rv.setWordWrap(True)
        rv.setStyleSheet("color:#B01030;")
        rl.addWidget(rv)
        lay.addWidget(risk_box)

        if param_summary:
            ps = QLabel("当前设定：" + param_summary)
            ps.setObjectName("Muted")
            ps.setWordWrap(True)
            lay.addWidget(ps)

        tip = QLabel("开启前请再次确认接线、量程与负载状态。关闭软件时会自动停止所有输出。")
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setFixedSize(110, 40)
        cancel.setDefault(True)          # 危险确认：回车默认取消，防止误开输出
        cancel.setAutoDefault(True)
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        ok = QPushButton("确认开启")
        ok.setFixedSize(140, 40)
        ok.setObjectName("Primary")
        ok.setStyleSheet("QPushButton#Primary{background:#E11D48; border:2px solid #A5082A;}"
                         "QPushButton#Primary:hover{background:#F43F5E;}"
                         "QPushButton#Primary:pressed{background:#A5082A;}")
        ok.setAutoDefault(False)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        lay.addLayout(btns)


class VersionDialog(QDialog):
    """版本记录：上位机版本 ↔ 各仪器协议/寄存器表版本对应关系 + 变更历史。"""

    def __init__(self, specs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("版本记录")
        self.setModal(True)
        self.resize(760, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)

        head = QHBoxLayout()
        t = QLabel(f"{APP_NAME}　v{APP_VERSION}")
        t.setObjectName("H1")
        head.addWidget(t)
        head.addWidget(Chip("版本单一事实源", "#4F46E5", "#EEF0FF"))
        head.addStretch(1)
        close = QPushButton("关闭")
        close.setFixedSize(90, 36)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        head.addWidget(close)
        lay.addLayout(head)

        sub = QLabel("规范：任何修改必须递增版本号并登记变更记录；现场问题按此表追溯。")
        sub.setObjectName("Muted")
        lay.addWidget(sub)

        # 版本对应关系
        t1 = QLabel("版本对应关系（上位机 ↔ 协议 ↔ 寄存器表）")
        t1.setObjectName("H2")
        lay.addWidget(t1)
        tbl = QTableWidget(len(specs) + 1, 6)
        tbl.setHorizontalHeaderLabels(["仪器", "型号", "上位机UI", "协议", "寄存器表", "备注"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setAlternatingRowColors(True)
        hdr = [("融合框架", "-", APP_VERSION, "-", "-", "本次交付基线")]
        rows = hdr + [
            (s.name, s.model,
             s.versions.get("上位机UI", "-"), s.versions.get("协议", "-"),
             s.versions.get("寄存器表", "-"), s.versions.get("备注", "-"))
            for s in specs
        ]
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                tbl.setItem(r, c, QTableWidgetItem(str(val)))
        tbl.setColumnWidth(0, 150)
        tbl.setColumnWidth(1, 120)
        tbl.setColumnWidth(2, 90)
        tbl.setColumnWidth(3, 110)
        tbl.setColumnWidth(4, 110)
        tbl.setFixedHeight(70 + 34 * len(rows))
        lay.addWidget(tbl)

        # 变更历史
        t2 = QLabel("变更历史")
        t2.setObjectName("H2")
        lay.addWidget(t2)
        hist = QTableWidget(len(VERSION_HISTORY), 3)
        hist.setHorizontalHeaderLabels(["版本", "日期", "变更说明"])
        hist.verticalHeader().setVisible(False)
        hist.setEditTriggers(QTableWidget.NoEditTriggers)
        hist.setAlternatingRowColors(True)
        for r, (v, d, note) in enumerate(VERSION_HISTORY):
            hist.setItem(r, 0, QTableWidgetItem(v))
            hist.setItem(r, 1, QTableWidgetItem(d))
            hist.setItem(r, 2, QTableWidgetItem(note))
        hist.setColumnWidth(0, 80)
        hist.setColumnWidth(1, 110)
        hist.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(hist, 1)


class FaultRecordDialog(QDialog):
    """记录调试过程中遇到的故障，用于「故障代码查询」页的调试故障记录。"""

    def __init__(self, instrument: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("记录调试故障")
        self.setModal(True)
        self.setFixedSize(470, 330)
        self.setStyleSheet("QDialog { background: #FFFFFF; border-radius: 16px; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(12)

        t = QLabel(f"记录调试故障 · {instrument}")
        t.setObjectName("H1")
        lay.addWidget(t)
        sub = QLabel("记录现象、关联操作与处理结论，随调试记录一并归档，可追溯、可查询。")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        lay.addWidget(QLabel("故障现象"))
        self.ed_scene = QLineEdit()
        self.ed_scene.setPlaceholderText("如：输出开启后电压跌落 2V")
        lay.addWidget(self.ed_scene)

        lay.addWidget(QLabel("关联操作"))
        self.ed_op = QLineEdit()
        self.ed_op.setPlaceholderText("如：下发设定 12V → 开启 OUT1")
        lay.addWidget(self.ed_op)

        lay.addWidget(QLabel("处理 / 结论"))
        self.ed_fix = QLineEdit()
        self.ed_fix.setPlaceholderText("如：更换 485 总线终端电阻后恢复（可后补）")
        lay.addWidget(self.ed_fix)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setFixedSize(100, 38)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton("保存记录")
        ok.setFixedSize(120, 38)
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)

    def values(self):
        return (self.ed_scene.text().strip() or "-",
                self.ed_op.text().strip() or "-",
                self.ed_fix.text().strip() or "待处理")
