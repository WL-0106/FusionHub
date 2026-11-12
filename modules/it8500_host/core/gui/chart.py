"""实时趋势图: 三泳道 (U/I/P) 自绘曲线, 无第三方依赖。"""
from __future__ import annotations

import time
from collections import deque

from PyQt5.QtCore import Qt, QRectF, QLineF
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget

LANES = (
    ("U", "电压 U", "#0d9b6c", "V"),
    ("I", "电流 I", "#1f7ae0", "A"),
    ("P", "功率 P", "#c98a00", "W"),
)


class TrendChart(QWidget):
    """滚动窗口三泳道曲线。X 轴为相对秒。"""

    def __init__(self, parent=None, window: int = 900):
        super().__init__(parent)
        self._t: deque[float] = deque(maxlen=window)
        self._v: dict[str, deque[float]] = {k: deque(maxlen=window) for k, _, _, _ in LANES}
        self.setMinimumHeight(70)     # 保底极小: 优先保证底部日志可见
        self._font = QFont("Microsoft YaHei UI", 8)
        self._mono = QFont("Consolas", 9)

    # ---------------------------------------------------------- 数据
    def append_sample(self, t: float, u: float, i: float, p: float) -> None:
        self._t.append(t)
        self._v["U"].append(u)
        self._v["I"].append(i)
        self._v["P"].append(p)
        self.update()

    def clear(self) -> None:
        self._t.clear()
        for d in self._v.values():
            d.clear()
        self.update()

    # ---------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#f7f9fc"))

        lane_h = h / len(LANES)
        pad_l, pad_r, pad_t, pad_b = 54, 12, 6, 14

        for li, (key, label, color, unit) in enumerate(LANES):
            top = li * lane_h + pad_t
            bottom = (li + 1) * lane_h - pad_b
            rect = QRectF(pad_l, top, max(10, w - pad_l - pad_r), max(10, bottom - top))
            self._draw_lane(painter, rect, key, label, color, unit)

        # X 轴时间标注 (最底泳道下沿)
        if len(self._t) >= 2:
            t0, t1 = self._t[0], self._t[-1]
            painter.setFont(self._font)
            painter.setPen(QPen(QColor("#7a8699")))
            painter.drawText(QRectF(pad_l, h - pad_b + 1, w - pad_l - pad_r, pad_b - 1),
                             Qt.AlignLeft | Qt.AlignVCenter, f"{t0:.0f} s")
            painter.drawText(QRectF(pad_l, h - pad_b + 1, w - pad_l - pad_r, pad_b - 1),
                             Qt.AlignRight | Qt.AlignVCenter, f"{t1:.0f} s")

    def _draw_lane(self, painter: QPainter, rect: QRectF,
                   key: str, label: str, color: str, unit: str) -> None:
        vals = self._v[key]
        # 背景网格
        painter.setPen(QPen(QColor("#e3e8f0"), 1))
        for f in (0.0, 0.5, 1.0):
            y = rect.bottom() - rect.height() * f
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))

        vmin = min(vals) if vals else 0.0
        vmax = max(vals) if vals else 0.0
        if vmax - vmin < 1e-9:
            vmax = vmin + (abs(vmin) * 0.05 + 1.0)
        span = vmax - vmin
        vmin -= span * 0.08
        vmax += span * 0.08
        span = vmax - vmin

        # 曲线
        if len(self._t) >= 2 and len(vals) >= 2:
            t0, t1 = self._t[0], self._t[-1]
            tspan = (t1 - t0) or 1.0
            pen = QPen(QColor(color), 1.6)
            painter.setPen(pen)
            pts = []
            for t, v in zip(self._t, vals):
                x = rect.left() + (t - t0) / tspan * rect.width()
                y = rect.bottom() - (v - vmin) / span * rect.height()
                pts.append((x, y))
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                painter.drawLine(QLineF(x1, y1, x2, y2))

        # 标注
        painter.setFont(self._font)
        painter.setPen(QPen(QColor("#5c6b80")))
        painter.drawText(QRectF(4, rect.top() - 2, 46, 14), Qt.AlignLeft, label)
        painter.setPen(QPen(QColor(color)))
        painter.setFont(self._mono)
        cur = vals[-1] if vals else 0.0
        painter.drawText(QRectF(4, rect.top() + 12, 46, 14), Qt.AlignLeft,
                         f"{cur:.3f}")
        painter.drawText(QRectF(4, rect.top() + 26, 46, 12), Qt.AlignLeft, unit)
        # 最大/最小
        painter.setPen(QPen(QColor("#9aa4b5")))
        painter.setFont(self._font)
        if vals:
            painter.drawText(QRectF(rect.left() + 2, rect.top(), rect.width(), 13),
                             Qt.AlignRight, f"max {max(vals):.3f}")
            painter.drawText(QRectF(rect.left() + 2, rect.bottom() - 13,
                                    rect.width(), 13),
                             Qt.AlignRight, f"min {min(vals):.3f}")


def now() -> float:
    return time.monotonic()
