# -*- coding: utf-8 -*-
"""调试记录器：调试过程中使用过的仪器、设定值、输出值、IO/采集值全部落表，可追溯、可导出。

记录原则：
- 所有产生过的记录行都保留（可追溯）；
- 勾选/取消仪器只影响"表格展示与导出"，不删除原始记录；
- 行内包含连接信息（接口 / IP 或 COM 口 / 波特率 / 端口号），方便现场复现问题。
"""
import csv
import datetime
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .spec import InstrumentSpec

_EMPTY = ("", "-", "—")   # spec/记录里的空值占位（两种破折号写法都算空）


def _filled(v: str) -> bool:
    return bool(v) and v.strip() not in _EMPTY


@dataclass
class RecordRow:
    ts: str          # 时间
    name: str        # 仪器名
    model: str       # 型号
    iface: str       # 接口
    addr: str        # IP / COM 口
    baud: str        # 波特率
    port_no: str     # 端口号
    item: str        # 项目（电压设定 / 输出 OUT1 / 输出电压 / 温度…）
    kind: str        # 类型：设定值 / 输出值 / 反馈值 / 采集值 / 连接
    value: str       # 数值
    unit: str        # 单位
    note: str        # 说明
    spec_id: str = ""


@dataclass
class SummaryRow:
    """已测试仪器清单行：一台仪器一行（调试完成后单独成表）。"""
    name: str        # 仪器名
    model: str       # 型号
    vendor: str      # 厂商
    group: str       # 类别（AC/DC源 / 仪器仪表 / 采集卡…）
    iface: str       # 接口类型
    ip: str          # IP 地址（串口设备为 -）
    com: str         # 串口 / COM 口（网口设备为 -）
    baud: str        # 波特率
    port_no: str     # 端口号（TCP 端口 / 从机地址）
    count: int       # 调试记录条数
    first_ts: str    # 首次记录时间
    last_ts: str     # 最后记录时间

    def cells(self) -> List[str]:
        return [self.name, self.model, self.vendor, self.group, self.iface, self.ip,
                self.com, self.baud, self.port_no, str(self.count),
                self.first_ts, self.last_ts]


class DebugRecorder:
    def __init__(self) -> None:
        self.rows: List[RecordRow] = []
        self._specs: Dict[str, InstrumentSpec] = {}   # 记录过的仪器元信息（厂商/IP/类别）

    # ------------------------------------------------------------------
    def _conn_fields(self, spec: InstrumentSpec, session) -> tuple:
        if session is not None and getattr(session, "connected", False):
            addr = f"{session.port}"
            baud = f"{session.baud}"
        else:
            addr = spec.ip if _filled(spec.ip) else "-"
            baud = "-"
        return spec.iface, addr, baud, spec.port_no

    def _add(self, spec: InstrumentSpec, session, item: str, kind: str,
             value: str, unit: str = "", note: str = "") -> None:
        iface, addr, baud, port_no = self._conn_fields(spec, session)
        self._specs[spec.id] = spec
        self.rows.append(RecordRow(
            ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name=spec.name, model=spec.model, iface=iface, addr=addr,
            baud=baud, port_no=port_no, item=item, kind=kind,
            value=str(value), unit=unit, note=note, spec_id=spec.id))

    # ------------------------------------------------------------------
    def record_event(self, spec: InstrumentSpec, session,
                     item: str, kind: str, value, unit: str = "", note: str = "") -> None:
        """记录一次人工操作/事件（下发设定、开关输出、连接断开）。"""
        self._add(spec, session, item, kind, value, unit, note)

    def record_snapshot(self, spec: InstrumentSpec, session) -> int:
        """快照当前仪器状态：设定值 + 输出值 + 实测/采集值。返回新增行数。"""
        n0 = len(self.rows)
        if session is None:
            return 0
        for p in spec.params:
            v = session.params.get(p.key, p.value)
            self._add(spec, session, p.label, "设定值", f"{v:.{p.decimals}f}", p.unit, "快照")
        for o in spec.outputs:
            on = session.outputs.get(o.key, False)
            self._add(spec, session, o.label, "输出值", "开" if on else "关", "-", "快照")
        kind = "采集值" if spec.group == "采集卡" else "反馈值"
        for r in spec.readouts:
            v = session.values.get(r.key, 0.0)
            self._add(spec, session, r.label, kind, f"{v:.{r.decimals}f}", r.unit,
                      "快照" if session.connected else "未连接")
        return len(self.rows) - n0

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self.rows.clear()
        self._specs.clear()

    def rows_for(self, spec_ids: Optional[Sequence[str]]) -> List[RecordRow]:
        if not spec_ids:
            return list(self.rows)
        ids = set(spec_ids)
        return [r for r in self.rows if r.spec_id in ids]

    # ------------------------------------------------------------------
    HEADERS = ["时间", "仪器", "型号", "接口", "IP/COM口", "波特率", "端口号",
               "项目", "类型", "数值", "单位", "说明"]

    # 已测试仪器清单：一台一行，型号/IP/串口/端口 + 调试时间，单独成表
    SUMMARY_HEADERS = ["仪器名称", "型号", "厂商", "类别", "接口类型", "IP 地址",
                       "串口/COM口", "波特率", "端口号", "记录条数", "首次记录", "最后记录"]

    _IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}")

    def tested_summary(self, spec_ids: Optional[Sequence[str]] = None) -> List[SummaryRow]:
        """汇总已测试（产生过记录）的仪器：每台一行，含连接信息与调试起止时间。"""
        grouped: Dict[str, List[RecordRow]] = {}
        for r in self.rows_for(spec_ids):
            grouped.setdefault(r.spec_id, []).append(r)
        out: List[SummaryRow] = []
        for sid, rs in grouped.items():
            spec = self._specs.get(sid)
            ips, coms, bauds, ports = [], [], [], []
            for r in rs:
                a = (r.addr or "").strip()
                if _filled(a):
                    (ips if self._IP_RE.match(a) else coms).append(a)
                if _filled(r.baud):
                    bauds.append(r.baud)
                if _filled(r.port_no):
                    ports.append(r.port_no)
            ip = " / ".join(dict.fromkeys(ips))
            if not ip and spec is not None and _filled(spec.ip):
                ip = spec.ip
            out.append(SummaryRow(
                name=rs[0].name, model=rs[0].model,
                vendor=spec.vendor if spec else "-",
                group=spec.group if spec else "-",
                iface=rs[0].iface,
                ip=ip or "-",
                com=" / ".join(dict.fromkeys(coms)) or "-",
                baud=" / ".join(dict.fromkeys(bauds)) or "-",
                port_no=" / ".join(dict.fromkeys(ports)) or "-",
                count=len(rs), first_ts=rs[0].ts, last_ts=rs[-1].ts))
        return out

    def export(self, path: str, spec_ids: Optional[Sequence[str]] = None) -> str:
        """导出选中仪器的记录；优先 xlsx（openpyxl），否则回退 csv。返回实际文件路径。"""
        rows = self.rows_for(spec_ids)
        data = [[r.ts, r.name, r.model, r.iface, r.addr, r.baud, r.port_no,
                 r.item, r.kind, r.value, r.unit, r.note] for r in rows]
        return self._write_table(path, "调试记录", self.HEADERS, data,
                                 [19, 14, 12, 10, 16, 9, 16, 14, 9, 12, 8, 24])

    def export_summary(self, path: str, spec_ids: Optional[Sequence[str]] = None) -> str:
        """导出"已测试仪器清单"（每台一行）；优先 xlsx，否则回退 csv。返回实际文件路径。"""
        data = [s.cells() for s in self.tested_summary(spec_ids)]
        return self._write_table(path, "仪器清单", self.SUMMARY_HEADERS, data,
                                 [14, 12, 10, 10, 18, 24, 12, 10, 18, 10, 19, 19])

    # ------------------------------------------------------------------
    @staticmethod
    def _write_table(path: str, sheet: str, headers: List[str],
                     data: List[List[str]], widths: List[int]) -> str:
        if path.lower().endswith(".xlsx"):
            try:
                from openpyxl import Workbook   # 有则导 xlsx，无则回退 csv
                wb = Workbook()
                ws = wb.active
                ws.title = sheet
                ws.append(headers)
                for row in data:
                    ws.append(row)
                for i, w in enumerate(widths, 1):
                    ws.column_dimensions[chr(64 + i) if i <= 26 else "A"].width = w
                wb.save(path)
                return path
            except ImportError:
                path = path[:-5] + ".csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data)
        return path
