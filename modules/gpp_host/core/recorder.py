"""CSV 数据记录：长表格式，每个通道每个采样一行。"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime
from typing import Iterable, Optional

from .models import MeasSample

HEADER = [
    "iso_time", "unix_time", "elapsed_s", "channel",
    "v_set", "i_set", "v_meas", "i_meas", "p_meas",
    "output_on", "cc",
]


class CsvRecorder:
    def __init__(self, flush_every: int = 10):
        self._file = None
        self._writer = None
        self._path: Optional[str] = None
        self._t0 = 0.0
        self._pending = 0
        self._flush_every = flush_every
        self._rows = 0

    @property
    def active(self) -> bool:
        return self._file is not None

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def rows(self) -> int:
        return self._rows

    def start(self, path: str) -> None:
        self.stop()
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        exists = os.path.exists(path) and os.path.getsize(path) > 0
        self._file = open(path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._file)
        if not exists:
            self._writer.writerow(HEADER)
        self._path = path
        self._t0 = time.monotonic()
        self._pending = 0
        self._rows = 0

    def record(self, samples: Iterable[MeasSample]) -> None:
        if not self._writer:
            return
        now = time.monotonic()
        wall = datetime.now()
        iso = wall.strftime("%Y-%m-%d %H:%M:%S.") + f"{wall.microsecond // 1000:03d}"
        unix = time.time()
        for s in samples:
            self._writer.writerow([
                iso, f"{unix:.3f}", f"{now - self._t0:.3f}", s.channel,
                f"{s.v_set:.4f}", f"{s.i_set:.4f}",
                f"{s.v:.5f}", f"{s.i:.6f}", f"{s.p:.4f}",
                int(s.output_on), int(s.cc),
            ])
            self._rows += 1
        self._pending += 1
        if self._pending >= self._flush_every:
            self._file.flush()
            self._pending = 0

    def stop(self) -> None:
        if self._file:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._writer = None
        self._path = None
