# -*- coding: utf-8 -*-
"""模拟从站 / 会话层。

界面只调用语义化接口（connect / set_param / toggle_output / read_value），
帧字节在本层封装并通过 log 回调写入通讯日志 —— 界面与协议解耦。
后续接真机时，只需把 SimSession 换成真实协议栈会话类（同名语义接口）。
"""
import math
import struct
import time
from typing import Callable, Dict, Optional

from .spec import InstrumentSpec

LOG_TX = "TX"
LOG_RX = "RX"
LOG_SYS = "SYS"
LOG_ERR = "ERR"


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


class SimSession:
    """单台仪器的模拟会话（同时也是真机协议栈的对接契约）。"""

    def __init__(self, spec: InstrumentSpec,
                 log: Callable[[str, str, str], None]):
        self.spec = spec
        self.log = log
        self.connected = False
        self.port = "-"
        self.baud = 9600
        self.params: Dict[str, float] = {p.key: p.value for p in spec.params}
        self.outputs: Dict[str, bool] = {o.key: False for o in spec.outputs}
        self.values: Dict[str, float] = {r.key: 0.0 for r in spec.readouts}
        self._t = 0.0
        self._last_poll = 0.0

    # ---------------- 语义化接口（界面只用这些） ----------------
    def connect(self, port: str, baud: int) -> None:
        self.port, self.baud = port, baud
        self.connected = True
        self.log(LOG_SYS, f"[{self.spec.model}] 已连接 {port} @ {baud}", "连接建立")

    def disconnect(self) -> None:
        if not self.connected:
            return
        self.connected = False
        self.log(LOG_SYS, f"[{self.spec.model}] 已断开 {self.port}", "连接关闭")

    def set_param(self, key: str, value: float) -> None:
        self.params[key] = value
        label = next((p.label for p in self.spec.params if p.key == key), key)
        if self.spec.comm_type == "modbus":
            addr = {"v_set": 0x0000, "i_set": 0x0001}.get(key, 0x0003)
            val = int(round(value * 100))
            req = bytes([0x01, 0x06, (addr >> 8) & 0xFF, addr & 0xFF,
                         (val >> 8) & 0xFF, val & 0xFF])
            req += struct.pack("<H", crc16_modbus(req))
            self.log(LOG_TX, to_hex(req), f"写设定：{label} = {value:.2f}")
            self.log(LOG_RX, to_hex(req), "模拟从站写回显（0x06 正常应答）")
        else:
            self.log(LOG_TX, f"SOUR:{key.upper()} {value:.3f}\n".replace("V_SET", "VOLT").replace("I_SET", "CURR"),
                     f"写设定：{label} = {value:.2f}")
            self.log(LOG_RX, "", "无数据响应（SCPI 写命令）")

    def toggle_output(self, key: str, on: bool) -> None:
        self.outputs[key] = on
        label = next((o.label for o in self.spec.outputs if o.key == key), key)
        if self.spec.comm_type == "modbus":
            val = 1 if on else 0
            req = bytes([0x01, 0x06, 0x00, 0x02, 0x00, val])
            req += struct.pack("<H", crc16_modbus(req))
            self.log(LOG_TX, to_hex(req), f"{'开启' if on else '关闭'} {label}")
            self.log(LOG_RX, to_hex(req), "模拟从站写回显（0x06 正常应答）")
        else:
            cmd = "OUTP ON" if self.spec.category != "电子负载" else ("INP ON" if on else "INP OFF")
            if self.spec.category != "电子负载":
                cmd = f"OUTP {'ON' if on else 'OFF'}"
            self.log(LOG_TX, cmd + "\n", f"{'开启' if on else '关闭'} {label}")
            self.log(LOG_RX, "", "无数据响应（SCPI 写命令）")

    def read_value(self, key: str) -> float:
        return self.values.get(key, 0.0)

    def any_output_on(self) -> bool:
        return any(self.outputs.values())

    # ---------------- 周期刷新（模拟从站数据 + 轮询帧） ----------------
    def tick(self, dt: float, now: Optional[float] = None) -> None:
        self._t += dt
        if not self.connected:
            return
        for r in self.spec.readouts:
            v = self._wave_value(r.key)
            self.values[r.key] = v

        now = time.monotonic() if now is None else now
        if now - self._last_poll >= 1.2:
            self._last_poll = now
            self._emit_poll()

    def _wave_value(self, key: str) -> float:
        r = next((x for x in self.spec.readouts if x.key == key), None)
        if r is None:
            return 0.0
        # 无输出控制项的仪器（万用表等）视为始终"在测"；有输出项的按输出状态归零
        out_on = self.any_output_on() or not self.spec.outputs
        # 输出关闭时：电压/电流类读数归零，其余保持基准
        if not out_on and (r.unit in ("V", "A", "W")):
            return abs(math.sin(self._t)) * r.amp
        base = r.base
        if r.unit == "V":
            base = self.params.get("v_set", self.params.get("ch1_v", r.base)) if self.params else r.base
        elif r.unit == "A":
            base = self.params.get("i_set", self.params.get("ch1_i", r.base)) if self.params else r.base
        wave = math.sin(self._t * 1.7 + hash(key) % 7) * r.amp + math.sin(self._t * 0.6) * r.amp * 0.5
        return max(0.0, base + wave)

    def _emit_poll(self) -> None:
        spec = self.spec
        if spec.comm_type == "modbus":
            req = bytes([0x01, 0x03, 0x00, 0x10, 0x00, 0x03])
            req += struct.pack("<H", crc16_modbus(req))
            vals = []
            for r in spec.readouts[:2]:
                vals.append(int(round(self.values.get(r.key, 0.0) * 100)) & 0xFFFF)
            vals.append(0x0001 if self.any_output_on() else 0x0000)
            data = b"".join(struct.pack(">H", v) for v in vals)
            resp = bytes([0x01, 0x03, len(data)]) + data
            resp += struct.pack("<H", crc16_modbus(resp))
            self.log(LOG_TX, to_hex(req), "轮询：读实际值寄存器 0x0010 起 3 个")
            self.log(LOG_RX, to_hex(resp), "模拟从站数据应答")
        else:
            cmd = spec.poll_cmd or (spec.readouts[0].label if spec.readouts else "MEAS?")
            self.log(LOG_TX, cmd.strip() + "\n", "轮询查询")
            first = spec.readouts[0] if spec.readouts else None
            if first:
                resp = f"{self.values.get(first.key, 0.0):.4f}\n"
                self.log(LOG_RX, resp, "模拟从站数据应答")
