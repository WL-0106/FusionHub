# -*- coding: utf-8 -*-
"""实时趋势曲线（纯 tkinter Canvas，无第三方依赖）"""

import time
from collections import deque
from tkinter import Canvas


class TrendChart(Canvas):
    BG = "#ffffff"
    GRID = "#e8edf3"
    LINE = "#3b82f6"
    TEXT = "#6b7280"
    ACCENT = "#f59e0b"

    def __init__(self, master, max_points: int = 300, **kw):
        super().__init__(master, bg=self.BG, highlightthickness=1,
                         highlightbackground="#dfe4ea", **kw)
        self._points = deque(maxlen=max_points)
        self._unit = ""
        self._max_points = max_points
        self.bind("<Configure>", lambda e: self.redraw())

    def set_max_points(self, n: int) -> None:
        n = max(20, int(n))
        self._max_points = n
        old = list(self._points)
        self._points = deque(old[-n:], maxlen=n)

    def set_unit(self, unit: str) -> None:
        self._unit = unit

    def clear(self) -> None:
        self._points.clear()
        self.redraw()

    def add(self, value: float, ts: float | None = None) -> None:
        self._points.append((ts if ts is not None else time.time(), float(value)))
        self.redraw()

    def redraw(self) -> None:
        w = self.winfo_width()
        h = self.winfo_height()
        self.delete("all")
        if w < 50 or h < 40:
            return
        pad_l, pad_r, pad_t, pad_b = 64, 12, 10, 22
        x0, y0 = pad_l, pad_t
        x1, y1 = w - pad_r, h - pad_b
        # 背景网格
        for i in range(5):
            y = y0 + (y1 - y0) * i / 4
            self.create_line(x0, y, x1, y, fill=self.GRID, dash=(2, 3))
        for i in range(6):
            x = x0 + (x1 - x0) * i / 5
            self.create_line(x, y0, x, y1, fill=self.GRID, dash=(2, 3))

        if len(self._points) < 2:
            self.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                             text="等待测量数据…", fill=self.TEXT,
                             font=("Microsoft YaHei UI", 11))
            return

        ys = [p[1] for p in self._points]
        vmin, vmax = min(ys), max(ys)
        if vmax - vmin < 1e-30:
            vmin -= 1.0
            vmax += 1.0
        span = vmax - vmin
        vmin -= span * 0.08
        vmax += span * 0.08

        n = len(self._points)
        coords = []
        for i, (_, v) in enumerate(self._points):
            x = x0 + (x1 - x0) * i / (n - 1)
            y = y1 - (y1 - y0) * (v - vmin) / (vmax - vmin)
            coords.extend((x, y))
        self.create_line(*coords, fill=self.LINE, width=2, smooth=False)

        # 最新点高亮
        self.create_oval(coords[-4] - 3, coords[-3] - 3, coords[-4] + 3, coords[-3] + 3,
                         fill=self.ACCENT, outline="")
        # 刻度文字
        self.create_text(pad_l - 6, y0, text=self._fmt(vmax), anchor="ne",
                         fill=self.TEXT, font=("Consolas", 9))
        self.create_text(pad_l - 6, y1, text=self._fmt(vmin), anchor="se",
                         fill=self.TEXT, font=("Consolas", 9))
        self.create_text(pad_l - 6, (y0 + y1) / 2, text=self._unit, anchor="e",
                         fill=self.TEXT, font=("Microsoft YaHei UI", 9))
        latest = self._points[-1][1]
        self.create_text(x1, y1 + 12, text=f"最新 {self._fmt(latest)}  点数 {n}",
                         anchor="se", fill=self.TEXT, font=("Microsoft YaHei UI", 9))

    @staticmethod
    def _fmt(v: float) -> str:
        a = abs(v)
        if a == 0:
            return "0"
        if a >= 1e6 or a < 1e-3:
            return f"{v:.3e}"
        return f"{v:.4f}"
