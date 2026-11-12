# -*- coding: utf-8 -*-
"""公共 UI 组件：圆角卡片、彩色标签、输出按钮、波形显示区。"""
from collections import deque
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from .theme import COLORS


# ---------------------------------------------------------------- 胶囊标签
class Chip(QLabel):
    """彩色圆角小标签。"""

    def __init__(self, text: str, fg: str, bg: str, border: str = "", parent=None):
        super().__init__(text, parent)
        border_css = f"1px solid {border};" if border else "none;"
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border:{border_css} border-radius:9px;"
            f"padding:2px 10px; font-size:11px; font-weight:700;"
        )
        self.setAlignment(Qt.AlignCenter)


def level_chip(level: str) -> Tuple[str, str, str]:
    """严重级别 -> (文字, 前景色, 背景色)"""
    return {
        "danger": ("危险", "#B01030", "#FFE4E6"),
        "warn": ("警告", "#B45309", "#FEF3C7"),
        "info": ("提示", "#1D4ED8", "#E0E7FF"),
    }.get(level, ("提示", "#1D4ED8", "#E0E7FF"))


def verified_chip(verified: bool) -> Chip:
    if verified:
        return Chip("已验证", "#047857", "#D1FAE5")
    return Chip("待真机确认", "#B45309", "#FEF3C7")


# ---------------------------------------------------------------- 卡片
class Card(QFrame):
    """白色圆角卡片，带标题行。"""

    def __init__(self, title: str = "", sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(10)
        self.title_label = None

        if title:
            head = QVBoxLayout()
            head.setSpacing(2)
            t = QLabel(title)
            t.setObjectName("CardTitle")
            self.title_label = t
            head.addWidget(t)
            if sub:
                s = QLabel(sub)
                s.setObjectName("CardSub")
                s.setWordWrap(True)
                head.addWidget(s)
            self._layout.addLayout(head)

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(8)
        self._layout.addWidget(self.body, 1)


# ---------------------------------------------------------------- 输出按钮
class OutputButton(QPushButton):
    """输出控制按钮：待机(粉)/开启(红)两态，按下有明显视觉变化；
    点击只发信号，是否执行由上层弹二次确认框后调用 set_on() 决定。"""

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.setMinimumWidth(150)
        self._on = False
        self._label = label
        self._apply()

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool) -> None:
        self._on = on
        self._apply()

    def _apply(self) -> None:
        self.setProperty("state", "on" if self._on else "idle")
        self.setText(f"关闭{self._label}" if self._on else f"开启{self._label}")
        self.style().unpolish(self)
        self.style().polish(self)


class ConnectButton(QPushButton):
    """连接/断开按钮：断开(绿描边)/已连接(绿底)两态。"""

    def __init__(self, parent=None):
        super().__init__("连接仪器", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self._on = False
        self._apply()

    def is_connected(self) -> bool:
        return self._on

    def set_connected(self, on: bool) -> None:
        self._on = on
        self._apply()

    def _apply(self) -> None:
        self.setProperty("state", "on_ok" if self._on else "off_ok")
        self.setText("断开连接" if self._on else "连接仪器")
        self.style().unpolish(self)
        self.style().polish(self)


# ---------------------------------------------------------------- 波形显示区
class WaveformWidget(QWidget):
    """示波屏风格波形预览：深色底 + 网格 + 亮色曲线。"""

    def __init__(self, ylim: Tuple[float, float] = (0.0, 1.0), parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._ylim = ylim
        self._series: Dict[str, deque] = {}
        self._colors: Dict[str, str] = {}
        self._labels: Dict[str, str] = {}
        self._units: Dict[str, str] = {}
        self._ranges: Dict[str, Tuple[float, float]] = {}
        self._max_points = 240

    def add_channel(self, key: str, label: str, unit: str, color: str,
                    vrange: Optional[Tuple[float, float]] = None) -> None:
        self._series[key] = deque(maxlen=self._max_points)
        self._colors[key] = color
        self._labels[key] = label
        self._units[key] = unit
        self._ranges[key] = vrange or self._ylim

    def _range_of(self, key: str) -> Tuple[float, float]:
        return self._ranges.get(key, self._ylim)

    def push(self, key: str, value: float) -> None:
        if key in self._series:
            self._series[key].append(value)
            self.update()

    def clear(self) -> None:
        for s in self._series.values():
            s.clear()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 底色（圆角）
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, w - 2, h - 2), 12, 12)
        p.fillPath(path, QColor(COLORS["wave_bg"]))

        # 网格
        grid_pen = QPen(QColor(COLORS["wave_grid"]), 1)
        p.setPen(grid_pen)
        for i in range(1, 10):
            x = w * i / 10.0
            p.drawLine(int(x), 10, int(x), h - 10)
        for i in range(1, 6):
            y = h * i / 6.0
            p.drawLine(10, int(y), w - 10, int(y))

        # 中线稍亮
        p.setPen(QPen(QColor("#343A63"), 1))
        p.drawLine(10, h // 2, w - 10, h // 2)

        def _y(v: float, _lo: float, _hi: float) -> float:
            sp = (_hi - _lo) or 1.0
            v = max(_lo, min(_hi, v))
            return h - 12 - (v - _lo) / sp * (h - 24)

        # 曲线（逐通道独立量程，避免小量程通道贴底）
        for key, series in self._series.items():
            if len(series) < 2:
                continue
            clo, chi = self._range_of(key)
            color = QColor(self._colors[key])
            pen = QPen(color, 2.4)
            p.setPen(pen)
            n = len(series)
            step = (w - 24) / float(self._max_points)
            pts_path = QPainterPath()
            for i, v in enumerate(series):
                x = 12 + (self._max_points - n + i) * step
                y = _y(v, clo, chi)
                if i == 0:
                    pts_path.moveTo(x, y)
                else:
                    pts_path.lineTo(x, y)
            p.drawPath(pts_path)

        # 图例 + 当前值
        x = 14
        for key, series in self._series.items():
            color = QColor(self._colors[key])
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, 10, 10, 10), 3, 3)
            cur = series[-1] if series else 0.0
            p.setPen(QPen(color, 1))
            p.setFont(QFont("Microsoft YaHei UI", 9))
            text = f"{self._labels[key]} {cur:.3f}{self._units[key]}"
            p.drawText(int(x + 16), 19, text)
            x += 16 + int(p.fontMetrics().horizontalAdvance(text)) + 22

        # 边框
        p.setPen(QPen(QColor("#2A2F52"), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 12, 12)
        p.end()
