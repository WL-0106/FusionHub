"""自绘实时曲线：电压/电流/功率，多通道叠加，QPainter 无第三方依赖。"""
from __future__ import annotations

import math
from collections import deque
from typing import Iterable, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

from ..models import ChannelSpec, MeasSample

_SERIES_META = {"v": ("电压", "V"), "i": ("电流", "A"), "p": ("功率", "W")}
_BG = "#FFFFFF"
_GRID = "#E5E7EB"
_AXIS = "#9CA3AF"
_TEXT = "#6B7280"


class RealtimeChart(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self._span = 60.0
        self._series = "v"
        self._paused = False
        self._specs: dict[int, ChannelSpec] = {}
        self._visible: set[int] = set()
        # 每通道: {"t","v","i","p"} -> deque
        self._buf: dict[int, dict[str, deque]] = {}
        self._maxlen = 16000
        self._font = QFont("Microsoft YaHei UI", 9)
        self._font_num = QFont("Consolas", 9)

    # ---------------- 配置 ----------------
    def set_specs(self, specs: Iterable[ChannelSpec]) -> None:
        self._specs = {s.index: s for s in specs}
        self._visible = set(self._specs)
        self.clear()

    def set_visible(self, channels: set[int]) -> None:
        self._visible = {c for c in channels if c in self._specs}
        self.update()

    def set_series(self, series: str) -> None:
        if series in _SERIES_META:
            self._series = series
            self.update()

    def set_span(self, seconds: float) -> None:
        self._span = max(5.0, float(seconds))
        self.update()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    @property
    def paused(self) -> bool:
        return self._paused

    def clear(self) -> None:
        self._buf = {n: {"t": deque(maxlen=self._maxlen),
                         "v": deque(maxlen=self._maxlen),
                         "i": deque(maxlen=self._maxlen),
                         "p": deque(maxlen=self._maxlen)}
                     for n in self._specs}
        self.update()

    # ---------------- 数据 ----------------
    def append_samples(self, samples: Iterable[MeasSample]) -> None:
        if self._paused:
            return
        for s in samples:
            if s.channel not in self._buf:
                continue
            b = self._buf[s.channel]
            b["t"].append(s.t)
            b["v"].append(s.v)
            b["i"].append(s.i)
            b["p"].append(s.p)
        self._trim()
        self.update()

    def _trim(self) -> None:
        if not self._buf:
            return
        all_t = [b["t"][-1] for b in self._buf.values() if b["t"]]
        if not all_t:
            return
        newest = max(all_t)
        cutoff = newest - (self._span + 30.0)
        for b in self._buf.values():
            t = b["t"]
            while t and t[0] < cutoff:
                for key in ("t", "v", "i", "p"):
                    b[key].popleft()

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(_BG))

        margin_l, margin_r, margin_t, margin_b = 62, 14, 26, 26
        plot = QRectF(margin_l, margin_t, w - margin_l - margin_r, h - margin_t - margin_b)
        if plot.width() < 40 or plot.height() < 40:
            return

        # 数据窗口
        key = self._series
        newest = None
        for n in self._visible:
            b = self._buf.get(n)
            if b and b["t"]:
                newest = max(newest or b["t"][-1], b["t"][-1])
        if newest is None:
            p.setFont(self._font)
            p.setPen(QColor(_TEXT))
            p.drawText(plot, Qt.AlignCenter, "等待测量数据…\n连接设备后曲线将自动刷新")
            return
        t1 = newest
        t0 = t1 - self._span

        # Y 范围
        vals: list[float] = []
        for n in self._visible:
            b = self._buf.get(n)
            if not b:
                continue
            for t, v in zip(b["t"], b[key]):
                if t0 <= t <= t1:
                    vals.append(v)
        if vals:
            lo, hi = min(vals), max(vals)
        else:
            lo, hi = 0.0, 1.0
        lo, hi = self._nice_range(lo, hi)

        # 网格与刻度
        p.setFont(self._font_num)
        p.setPen(QPen(QColor(_GRID), 1))
        steps = 5
        for k in range(steps + 1):
            y = plot.bottom() - plot.height() * k / steps
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            val = lo + (hi - lo) * k / steps
            p.setPen(QColor(_TEXT))
            p.drawText(QRectF(0, y - 9, margin_l - 8, 18),
                       Qt.AlignRight | Qt.AlignVCenter, f"{val:g}")
            p.setPen(QPen(QColor(_GRID), 1))
        x_steps = 6
        for k in range(x_steps + 1):
            x = plot.left() + plot.width() * k / x_steps
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            tsec = t0 + (t1 - t0) * k / x_steps
            p.setPen(QColor(_TEXT))
            p.drawText(QRectF(x - 40, plot.bottom() + 3, 80, 18),
                       Qt.AlignHCenter | Qt.AlignTop, f"{tsec - t1:+.0f}s")
            p.setPen(QPen(QColor(_GRID), 1))

        # 坐标轴
        p.setPen(QPen(QColor(_AXIS), 1))
        p.drawRect(plot)

        # 曲线
        span_px = plot.width()
        for n in sorted(self._visible):
            b = self._buf.get(n)
            spec = self._specs.get(n)
            if not b or not spec or not b["t"]:
                continue
            ts, vs = b["t"], b[key]
            count = len(ts)
            stride = max(1, count // int(max(span_px * 2, 100)))
            pts: list[QPointF] = []
            for idx in range(0, count, stride):
                t = ts[idx]
                if t < t0:
                    continue
                x = plot.left() + (t - t0) / (t1 - t0) * span_px
                yfrac = (vs[idx] - lo) / (hi - lo) if hi > lo else 0.5
                y = plot.bottom() - yfrac * plot.height()
                pts.append(QPointF(x, y))
            # 补最后一个点
            if ts[-1] >= t0:
                x = plot.left() + (ts[-1] - t0) / (t1 - t0) * span_px
                yfrac = (vs[-1] - lo) / (hi - lo) if hi > lo else 0.5
                pts.append(QPointF(x, plot.bottom() - yfrac * plot.height()))
            if len(pts) >= 2:
                p.setPen(QPen(QColor(spec.color), 1.8))
                p.setBrush(Qt.NoBrush)
                path = QPainterPath(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                p.drawPath(path)

        # 图例(右上)
        legend_x = plot.right() - 128
        legend_y = plot.top() + 8
        p.setFont(self._font)
        for n in sorted(self._visible):
            spec = self._specs.get(n)
            b = self._buf.get(n)
            if not spec:
                continue
            latest = f"{b[key][-1]:.5g}" if b and b[key] else "—"
            p.setPen(QColor(_BG))
            p.setBrush(QColor(spec.color))
            p.drawRoundedRect(QRectF(legend_x, legend_y + 3, 10, 10), 2, 2)
            p.setPen(QColor("#374151"))
            p.drawText(QRectF(legend_x + 16, legend_y - 2, 110, 18),
                       Qt.AlignLeft | Qt.AlignVCenter, f"{spec.label} {latest}")
            legend_y += 18

        unit = _SERIES_META[self._series][1]
        p.setPen(QColor(_TEXT))
        p.setFont(self._font)
        p.drawText(QRectF(margin_l, 2, 200, 18),
                   Qt.AlignLeft | Qt.AlignVCenter, f"测量{_SERIES_META[self._series][0]} ({unit})")
        if self._paused:
            p.setPen(QColor("#B45309"))
            p.drawText(QRectF(w - 70, 2, 66, 18),
                       Qt.AlignRight | Qt.AlignVCenter, "已暂停")

    @staticmethod
    def _nice_range(lo: float, hi: float) -> tuple[float, float]:
        if not math.isfinite(lo) or not math.isfinite(hi):
            return 0.0, 1.0
        if hi - lo < 1e-12:
            hi = lo + 1.0 if lo == 0 else abs(lo) * 0.1 + lo
            if hi <= lo:
                hi = lo + 1.0
        raw = (hi - lo) / 5.0
        mag = 10.0 ** math.floor(math.log10(raw))
        step = mag
        for m in (1, 2, 5, 10):
            if mag * m >= raw - 1e-15:
                step = mag * m
                break
        return math.floor(lo / step) * step, math.ceil(hi / step) * step
