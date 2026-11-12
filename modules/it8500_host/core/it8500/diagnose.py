"""真机通讯诊断: 波特率 × 地址扫描 + 原始字节采集。

用于排查"发了命令但设备毫无应答"的现场问题。

策略 (逐级深入):
  1. 快扫: 4 档波特率 × {地址0, 界面地址, FE} —— 覆盖绝大多数情况, 数秒内完成
  2. 矩阵: 未命中时 4 档波特率 × 地址 0~31 全扫 (最长约 30 秒)
  3. 复现确认: 首次命中再探测一次, 排除噪声偶发成帧; 6AH 应答若全零则视为
     发送回显 (RS232/RS485 环回), 不算命中
  4. 全程收集乱码字节 —— 区分"线上完全静默"与"有字节但格式不对"

传输工厂函数可注入, 便于单元测试 (无需真实串口)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from . import protocol as P
from .transport import Transport, TransportError

BAUDS = (9600, 4800, 19200, 38400)

TransportFactory = Callable[[str, int], Transport]
LogFn = Callable[[str], None]


@dataclass
class ScanResult:
    ok: bool
    baud: int | None = None
    addr: int | None = None
    frame: P.Frame | None = None
    junk: dict[tuple[int, int], bytes] = field(default_factory=dict)
    # junk: (baud, addr) -> 该次探测收到的未解析字节
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok and self.baud is not None and self.addr is not None:
            cmd = self.frame.cmd if self.frame else 0x6A
            return (f"找到设备 — 波特率 {self.baud}, 地址 {self.addr} "
                    f"(0x{self.addr:02X}), 应答命令字 0x{cmd:02X}")
        if self.junk:
            return ("未找到有效应答, 但线上检测到字节流入 (乱码) — "
                    "大概率线路/电平/回显问题, 见日志中的乱码十六进制")
        return ("所有波特率×地址组合均无任何字节回应 — "
                "检查端口选择、通讯模块 (IT-E121/122/123) 与接线 (TX/RX)")


def _dedupe(*addrs: int) -> list[int]:
    out: list[int] = []
    for a in addrs:
        if a not in out:
            out.append(a)
    return out


def _probe_at(make: TransportFactory, port: str, baud: int, addr: int,
              timeout: float, probe_cmd: int
              ) -> tuple[P.Frame | None, bytes, str | None, bool]:
    """单点探测。返回 (有效应答|None, 未解析字节, 端口级错误|None, 疑似回显)。"""
    junk = bytearray()
    tr = make(port, baud)
    try:
        tr.on_raw = junk.extend       # 传输层若支持原始字节回调则启用
    except Exception:  # noqa: BLE001
        pass
    try:
        tr.open()
    except TransportError as e:
        return None, bytes(junk), str(e), False
    try:
        tr.write_frame(P.build_frame(addr, probe_cmd))
        try:
            frame = tr.read_frame(timeout)
        except TransportError:
            return None, bytes(junk), None, False
        # 6AH 读身份: 全零数据 = 疑似本地回显 (环回/RS485 反射), 不算命中
        if probe_cmd == 0x6A and frame.data[:5] == b"\x00" * 5:
            return None, bytes(junk), None, True
        return frame, bytes(junk), None, False
    except TransportError as e:
        return None, bytes(junk), str(e), False
    finally:
        try:
            tr.close()
        except Exception:  # noqa: BLE001
            pass


def scan_device(make: TransportFactory, port: str, base_addr: int = 0,
                log: LogFn | None = None, probe_cmd: int = 0x6A) -> ScanResult:
    def emit(text: str) -> None:
        if log:
            log(text)

    res = ScanResult(ok=False)

    def run_pass(bauds, addrs, timeout: float, label: str):
        addrs = list(addrs)
        for baud in bauds:
            emit(f"[诊断] ── {label} · 波特率 {baud} ──")
            for addr in addrs:
                frame, junk, err, echoed = _probe_at(
                    make, port, baud, addr, timeout, probe_cmd)
                if err:
                    emit(f"[诊断]   端口错误, 中止扫描: {err}")
                    res.notes.append(err)
                    return None
                if junk:
                    res.junk[(baud, addr)] = junk
                    emit(f"[诊断]   地址 {addr:#04x}: 收到 {len(junk)} 字节"
                         f"但无法组帧: {P.hexdump(junk[:24])}"
                         f"{'…' if len(junk) > 24 else ''}")
                if frame is not None:
                    emit(f"[诊断]   地址 {addr:#04x}: ✔ 有效应答 "
                         f"cmd=0x{frame.cmd:02X} "
                         f"data={P.hexdump(frame.data[:8])}…")
                    return (baud, addr, frame)
                if echoed:
                    emit(f"[诊断]   地址 {addr:#04x}: 收到疑似发送回显 "
                         f"(环回/反射), 忽略")
                    res.notes.append(f"回显 @{baud}/{addr:#04x}")
                elif not junk:
                    emit(f"[诊断]   地址 {addr:#04x}: 无响应")
            time.sleep(0.05)
        return None

    spot = _dedupe(0, base_addr, 0xFE)
    emit(f"[诊断] 开始扫描 {port}: 波特率 {list(BAUDS)}, "
         f"快扫地址 {spot} → 未命中则全矩阵 0~31")

    hit = run_pass(BAUDS, spot, 0.3, "快扫")
    if hit is None:
        emit("[诊断] 快扫未命中, 执行全地址矩阵 "
             "(0~31 × 4 档波特率, 最长约 30 秒)…")
        hit = run_pass(BAUDS, range(32), 0.2, "矩阵")

    if hit is None:
        emit(f"[诊断] 结束: {res.summary()}")
        return res

    baud, addr, frame = hit

    # 复现确认: 排除噪声偶发成帧
    confirm, _, _, _ = _probe_at(make, port, baud, addr, 0.3, probe_cmd)
    if confirm is None:
        emit(f"[诊断] {baud}/地址{addr} 的命中不可复现 (疑噪声), 继续全矩阵…")
        hit = run_pass(BAUDS, range(32), 0.2, "矩阵")
        if hit is None:
            emit(f"[诊断] 结束: {res.summary()}")
            return res
        baud, addr, frame = hit
    else:
        emit(f"[诊断] 命中复现确认通过 ({baud} / 地址 {addr})")

    # 命中广播地址 FE 时, 精扫 0~31 找出设备真实地址
    if addr == 0xFE:
        emit("[诊断] 命中广播地址 FE, 精扫 0~31 确认真地址…")
        exact = run_pass((baud,), range(32), 0.2, "精扫")
        if exact is not None:
            addr, frame = exact[1], exact[2]
            emit(f"[诊断]   真实地址 = {addr}")

    res.ok = True
    res.baud = baud
    res.addr = addr
    res.frame = frame
    emit(f"[诊断] 完成: {res.summary()}")
    return res
