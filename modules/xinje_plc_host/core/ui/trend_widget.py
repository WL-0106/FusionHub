# -*- coding: utf-8 -*-
"""实时趋势曲线控件（QPainter 自绘，零第三方依赖）。"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PyQt5.QtWidgets import QWidget


@dataclass
class TrendSeries:
    name: str
    color: str = "#2F80ED"
    visible: bool = True
    points: deque = field(default_factory=lambda: deque(maxlen=3000))

    def add(self, ts: float, value: float) -> None:
        self.points.append((ts, value))


class TrendWidget(QWidget):
    """多序列实时曲线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: dict[str, TrendSeries] = {}
        self.window_seconds: float = 60.0
        self.auto_y = True
        self.y_min = 0.0
        self.y_max = 100.0
        self.show_grid = True
        self.show_legend = True
        self._bg = QColor("#FFFFFF")
        self.setMinimumHeight(260)

        self._palette = [
            "#2F6FED", "#E24B4B", "#1F9D63", "#F59E0B",
            "#8B5CF6", "#06B6D4", "#EC4899", "#84CC16",
        ]

    # -- API -------------------------------------------------------------
    def add_series(self, name: str, color: Optional[str] = None) -> TrendSeries:
        if name not in self.series:
            color = color or self._palette[len(self.series) % len(self._palette)]
            self.series[name] = TrendSeries(name=name, color=color)
        return self.series[name]

    def remove_series(self, name: str) -> None:
        self.series.pop(name, None)

    def clear(self) -> None:
        for s in self.series.values():
            s.points.clear()

    def clear_all(self) -> None:
        self.series.clear()

    def append(self, name: str, ts: float, value: float,
               color: Optional[str] = None) -> None:
        if name not in self.series:
            self.add_series(name, color)
        if self.series[name].visible:
            self.series[name].add(ts, value)
        self.update()

    def set_window(self, seconds: float) -> None:
        self.window_seconds = max(5.0, min(seconds, 3600.0))
        self.update()

    def set_y_range(self, lo: float, hi: float) -> None:
        self.auto_y = False
        self.y_min, self.y_max = lo, hi
        self.update()

    def set_auto_y(self, on: bool = True) -> None:
        self.auto_y = on
        self.update()

    # -- 绘制 ------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        p.fillRect(rect, self._bg)

        margin_l, margin_r, margin_t, margin_b = 56, 16, 28, 32
        plot = QRectF(
            rect.left() + margin_l,
            rect.top() + margin_t,
            max(10, rect.width() - margin_l - margin_r),
            max(10, rect.height() - margin_t - margin_b),
        )

        # 时间窗
        now = time.time()
        t1 = now
        t0 = now - self.window_seconds

        # Y 轴范围
        y0, y1 = self._calc_y_range(t0, t1)

        # 网格
        if self.show_grid:
            self._draw_grid(p, plot, t0, t1, y0, y1)

        # 边框
        p.setPen(QPen(QColor("#E2E7EF"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(plot, 4, 4)

        # 裁剪曲线区
        p.save()
        p.setClipRect(plot.adjusted(1, 1, -1, -1))

        for s in self.series.values():
            if not s.visible or len(s.points) < 1:
                continue
            self._draw_series(p, plot, s, t0, t1, y0, y1)

        p.restore()

        # 图例
        if self.show_legend:
            self._draw_legend(p, rect)

        # 标题
        p.setPen(QColor("#1C2333"))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        p.setFont(font)
        p.drawText(
            QRectF(rect.left() + 12, rect.top() + 6, rect.width() - 24, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            "实时趋势",
        )

    def _calc_y_range(self, t0: float, t1: float) -> tuple[float, float]:
        if not self.auto_y:
            return self.y_min, self.y_max
        vmin: Optional[float] = None
        vmax: Optional[float] = None
        for s in self.series.values():
            if not s.visible:
                continue
            for ts, v in s.points:
                if t0 <= ts <= t1:
                    if vmin is None or v < vmin:
                        vmin = v
                    if vmax is None or v > vmax:
                        vmax = v
        if vmin is None or vmax is None:
            return 0.0, 100.0
        if abs(vmax - vmin) < 1e-9:
            pad = max(1.0, abs(vmax) * 0.1)
            return vmin - pad, vmax + pad
        pad = (vmax - vmin) * 0.12
        return vmin - pad, vmax + pad

    def _x_to_px(self, t: float, plot: QRectF, t0: float, t1: float) -> float:
        if t1 <= t0:
            return plot.left()
        return plot.left() + (t - t0) / (t1 - t0) * plot.width()

    def _y_to_px(self, v: float, plot: QRectF, y0: float, y1: float) -> float:
        if y1 <= y0:
            return plot.center().y()
        return plot.bottom() - (v - y0) / (y1 - y0) * plot.height()

    def _draw_grid(self, p: QPainter, plot: QRectF,
                   t0: float, t1: float, y0: float, y1: float) -> None:
        pen = QPen(QColor("#F0F3F8"), 1)
        p.setPen(pen)
        # 水平
        steps = 5
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        for i in range(steps + 1):
            y = plot.top() + plot.height() * i / steps
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            val = y1 - (y1 - y0) * i / steps
            p.setPen(QColor("#8B98AC"))
            p.drawText(
                QRectF(0, y - 8, plot.left() - 6, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                self._fmt_num(val),
            )
            p.setPen(pen)

        # 垂直（时间）
        vsteps = 6
        for i in range(vsteps + 1):
            x = plot.left() + plot.width() * i / vsteps
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            t = t0 + (t1 - t0) * i / vsteps
            p.setPen(QColor("#8B98AC"))
            label = time.strftime("%H:%M:%S", time.localtime(t))
            p.drawText(
                QRectF(x - 40, plot.bottom() + 4, 80, 16),
                Qt.AlignCenter,
                label,
            )
            p.setPen(pen)

    def _draw_series(self, p: QPainter, plot: QRectF, s: TrendSeries,
                     t0: float, t1: float, y0: float, y1: float) -> None:
        pts = [(ts, v) for ts, v in s.points if t0 - 1 <= ts <= t1 + 1]
        if not pts:
            return
        color = QColor(s.color)

        if len(pts) == 1:
            x = self._x_to_px(pts[0][0], plot, t0, t1)
            y = self._y_to_px(pts[0][1], plot, y0, y1)
            p.setPen(QPen(color, 3))
            p.setBrush(color)
            p.drawEllipse(QPointF(x, y), 3.5, 3.5)
            return

        path = QPainterPath()
        first = True
        for ts, v in pts:
            x = self._x_to_px(ts, plot, t0, t1)
            y = self._y_to_px(v, plot, y0, y1)
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)

        # 渐变填充
        grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
        c1 = QColor(color)
        c1.setAlpha(70)
        c2 = QColor(color)
        c2.setAlpha(0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)

        fill = QPainterPath(path)
        last_ts, last_v = pts[-1]
        first_ts = pts[0][0]
        fill.lineTo(self._x_to_px(last_ts, plot, t0, t1), plot.bottom())
        fill.lineTo(self._x_to_px(first_ts, plot, t0, t1), plot.bottom())
        fill.closeSubpath()
        p.fillPath(fill, grad)

        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # 最新点
        lx = self._x_to_px(last_ts, plot, t0, t1)
        ly = self._y_to_px(last_v, plot, y0, y1)
        p.setPen(QPen(QColor("#FFFFFF"), 1.5))
        p.setBrush(color)
        p.drawEllipse(QPointF(lx, ly), 4, 4)

    def _draw_legend(self, p: QPainter, rect) -> None:
        visible = [s for s in self.series.values() if s.visible]
        if not visible:
            return
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        x = rect.right() - 12
        y = rect.top() + 10
        metrics = p.fontMetrics()

        items = []
        for s in visible:
            label = f"{s.name} {self._fmt_num(s.points[-1][1]) if s.points else '--'}"
            w = metrics.horizontalAdvance(label) + 28
            items.append((s, label, w))

        total_w = sum(w for _, _, w in items) + 8 * (len(items) - 1)
        x = rect.right() - 12 - total_w

        for s, label, w in items:
            p.setPen(QPen(QColor(s.color), 3))
            p.drawLine(QPointF(x + 2, y + 7), QPointF(x + 14, y + 7))
            p.setPen(QColor("#5A677A"))
            p.drawText(QPointF(x + 18, y + 11), label)
            x += w + 8

    @staticmethod
    def _fmt_num(v: float) -> str:
        if abs(v) >= 10000:
            return f"{v:.0f}"
        if abs(v) >= 100:
            return f"{v:.1f}"
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return f"{v:.2f}"
