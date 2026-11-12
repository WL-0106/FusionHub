# -*- coding: utf-8 -*-
"""FLUKE 8808A 模拟从站 —— 自测/回归用（性价比最高的投资）。

覆盖：正常帧 + 异常帧（错帧、超时无响应、从站断开、半包/粘包、提示符错误、参数越界）。
命令解析与响应格式严格按手册第4章实现，作为协议栈的"可执行规格"。
"""
import math
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .commands import (
    DBREF_TABLE, RANGE_TABLE, RATE_TABLE, TRIGGER_TYPES,
    PROMPT_CMD_ERR, PROMPT_EXE_ERR, PROMPT_OK, OVERLOAD_VALUE,
)
from .transport import LoopbackTransport


def _parse_num(arg: str) -> Optional[float]:
    """解析手册数值格式：带符号整数/实数/指数实数（可带单位字符）。"""
    try:
        return float(re.sub(r"[^0-9eE+\-.]", "", arg))
    except ValueError:
        return None


class Fault:
    """故障注入模式（自动化异常用例用）。"""
    NONE = "none"
    NO_RESPONSE = "no_response"       # 超时：不回任何字节
    WRONG_PROMPT = "wrong_prompt"     # 回 !>/?>（执行/命令错误）
    GARBAGE = "garbage"               # 错帧：提示符前掺乱码
    DISCONNECT = "disconnect"         # 从站断开：直接关链路
    SPLIT = "split"                   # 半包：响应分片投递
    EXTRA_PREFIX = "extra_prefix"     # 粘包干扰：响应前多一段噪声
    SLOW = "slow"                     # 慢响应（压测超时边界）


@dataclass
class SimulatorConfig:
    fault: str = Fault.NONE
    fault_count: int = 1          # 注入次数后自动恢复正常
    split_chunk: int = 3          # 半包分片大小
    split_delay: float = 0.02
    slow_delay: float = 0.3
    noise: str = "@@GARBAGE@@"


class Sim8808A:
    """8808A 模拟从站内部状态机（忠实于手册命令语义）。"""

    def __init__(self, transport: LoopbackTransport, config: Optional[SimulatorConfig] = None):
        self._t = transport
        self._cfg = config or SimulatorConfig()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._inbuf = bytearray()
        self._fault_budget = 0
        self.command_log: list = []      # (时间, 命令, 响应)

        # ---- 仪表状态（默认上电状态）----
        self.func1 = "VDC"
        self.func2: Optional[str] = None
        self.auto_range = True
        self.range_n = 3
        self.rate = "M"
        self.trigger_type = 1
        self.format = 1
        self.echo = False
        self.remote_mode = "LOCS"
        self.dbref_index = 19            # 1000 Ω
        self.db_enabled = False
        self.rel_enabled = False
        self.rel_base = 0.0
        self.minmax_mode: Optional[str] = None   # "MIN"/"MAX"/"BOTH"
        self.min_val: Optional[float] = None
        self.max_val: Optional[float] = None
        self.hold = False
        self.hold_thresh = 2
        self.comp_enabled = False
        self.comp_hi = 1.0
        self.comp_lo = 0.0
        self.wire4 = False
        self.saved: dict = {}
        self.serial_no = "8808A01"
        self.firmware = "1.0D1.0"
        self.esr = 0
        self._measure_seed = 0.0

        self._injector: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="fluke8808a-sim", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def set_fault(self, fault: str, count: int = 1) -> None:
        with self._lock:
            self._cfg.fault = fault
            self._fault_budget = count

    # ------------------------------------------------------------ 字节流处理（半包/粘包）
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._t.read(256, 0.05)
            except Exception:
                break
            if not chunk:
                continue
            self._inbuf.extend(chunk)
            self._drain_input()

    def _drain_input(self) -> None:
        # 手册：CR / LF / CRLF 为输入结束符；50 字节输入缓冲，超限=设备错误并丢弃
        while True:
            buf = self._inbuf
            if not buf:
                return
            # ^C（0x03）清除设备状态
            if 0x03 in buf:
                i = buf.index(0x03)
                del buf[:i + 1]
                self._respond_prompt(PROMPT_OK)
                continue
            m = re.search(rb"\r\n|\r|\n", bytes(buf))
            if not m:
                if len(buf) > 50:                    # 输入缓冲溢出 -> 设备相关错误
                    buf.clear()
                    self.esr |= 1 << 3               # DDE
                    self._respond_prompt(PROMPT_EXE_ERR)
                return
            line = bytes(buf[:m.start()]).decode("ascii", errors="replace")
            del buf[:m.end()]
            if self.echo:
                # 回显开启：回显字符 + 命令结果 + 提示符（模拟逐字符回显简化为整行）
                self._send_raw(line + "\r\n")
            self._handle(line.strip())

    # ------------------------------------------------------------ 命令执行
    def _handle(self, line: str) -> None:
        with self._lock:
            if not line:
                self._respond_prompt(PROMPT_OK)
                return
            fault = self._take_fault()
            if fault == Fault.NO_RESPONSE:
                self.command_log.append((time.time(), line, "<无响应>"))
                return
            if fault == Fault.DISCONNECT:
                self.command_log.append((time.time(), line, "<断开>"))
                self._t.close()
                return

            # 一行可含多条命令（手册规则3：按顺序完整执行），以分号/逗号外分隔——
            # 手册未明确分隔符，此处按"空格间助记符+参数"的整行单命令处理，
            # 若首个 token 不可解析 -> ?>（整行命令错误，符合"不能解析则整行忽略+错误"）
            resp_body, prompt = self._execute(line)
            self.command_log.append((time.time(), line, prompt + resp_body))

            if fault == Fault.GARBAGE:
                prompt, resp_body = PROMPT_EXE_ERR, self._cfg.noise
            elif fault == Fault.WRONG_PROMPT:
                prompt = PROMPT_EXE_ERR
            elif fault == Fault.SLOW:
                time.sleep(self._cfg.slow_delay)

            frame = self._compose_frame(resp_body, prompt)
            if fault == Fault.SPLIT:
                self._t.push_chunked(frame, self._cfg.split_chunk, self._cfg.split_delay)
            elif fault == Fault.EXTRA_PREFIX:
                self._send_raw(self._cfg.noise + "\r\n")   # 噪声段独立成行（帧前掺噪声）
                self._send_raw(frame)
            else:
                self._send_raw(frame)

    def _compose_frame(self, body: str, prompt: str) -> bytes:
        # 响应格式：[数据<CR><LF>]<提示符>（回显关闭时不带回显行）
        if body:
            return (body + "\r\n" + prompt).encode("ascii")
        return prompt.encode("ascii")

    def _take_fault(self) -> str:
        if self._cfg.fault == Fault.NONE or self._fault_budget <= 0:
            return Fault.NONE
        self._fault_budget -= 1
        if self._fault_budget <= 0:
            f = self._cfg.fault
            self._cfg.fault = Fault.NONE
            return f
        return self._cfg.fault

    def _execute(self, line: str) -> tuple:
        """返回 (响应体, 提示符)。解析失败 -> (?, ?>)；参数/功能错误 -> (?, !>)。"""
        tokens = line.split()
        if not tokens:
            return "", PROMPT_OK
        head = tokens[0]
        args = tokens[1:]

        def exe_err():
            self.esr |= 1 << 4
            return "", PROMPT_EXE_ERR

        def cmd_err():
            self.esr |= 1 << 5
            return "", PROMPT_CMD_ERR

        num = _parse_num

        key = head.upper()

        # ---- 通用命令 ----
        if key.startswith("*"):
            return self._exec_star(key, args, exe_err, cmd_err)

        # ---- 查询（先查带 ? 的）----
        if key.endswith("?"):
            return self._exec_query(key[:-1], exe_err, cmd_err)

        # ---- 设置类命令 ----
        if key in ("VDC", "VAC", "VACDC", "ADC", "AAC", "AACDC", "OHMS", "FREQ", "CONT", "DIODE"):
            self.func1 = key
            self._reset_modifiers_for_function(key)
            return "", PROMPT_OK
        if key in ("VDC2", "VAC2", "ADC2", "AAC2", "OHMS2", "FREQ2"):
            if self.func1 in ("VACDC", "AACDC"):
                return exe_err()      # 副屏不可用
            self.func2 = key[:-1]
            return "", PROMPT_OK
        if key == "CLR2":
            self.func2 = None
            return "", PROMPT_OK
        if key == "WIRE2":
            if self.func1 != "OHMS":
                return exe_err()
            self.wire4 = False
            return "", PROMPT_OK
        if key == "WIRE4":
            if self.func1 != "OHMS":
                return exe_err()
            self.wire4 = True
            return "", PROMPT_OK

        if key == "AUTO":
            if self.rel_enabled or self.minmax_mode or self.func1 in ("DIODE", "CONT"):
                return exe_err()
            self.auto_range = True
            return "", PROMPT_OK
        if key == "FIXED":
            self.auto_range = False
            return "", PROMPT_OK
        if key == "RANGE":
            n = num(args[0]) if args else None
            if n is None or int(n) not in RANGE_TABLE:
                return exe_err()
            n = int(n)
            if not self._range_valid_for(self.func1, n):
                return exe_err()
            self.auto_range, self.range_n = False, n
            return "", PROMPT_OK
        if key == "RATE":
            if not args or args[0].upper() not in RATE_TABLE:
                return exe_err()
            self.rate = args[0].upper()
            return "", PROMPT_OK

        if key == "TRIGGER":
            t = num(args[0]) if args else None
            if t is None or int(t) not in TRIGGER_TYPES:
                return exe_err()
            self.trigger_type = int(t)
            return "", PROMPT_OK

        if key == "FORMAT":
            f = num(args[0]) if args else None
            if f is None or int(f) not in (1, 2):
                return exe_err()
            self.format = int(f)
            return "", PROMPT_OK
        if key == "PRINT":
            return "", PROMPT_OK

        # ---- 调节器 ----
        if key == "DB":
            if self.func1 not in ("VDC", "VAC", "VACDC"):
                return exe_err()
            self.db_enabled = True
            return "", PROMPT_OK
        if key == "DBCLR":
            self.db_enabled = False
            self.rel_enabled = False
            self.minmax_mode = None
            return "", PROMPT_OK
        if key == "DBPOWER":
            if DBREF_TABLE.get(self.dbref_index) not in (2, 4, 8, 16) or \
                    self.func1 not in ("VDC", "VAC", "VACDC"):
                return exe_err()
            self.db_enabled = True
            return "", PROMPT_OK
        if key == "DBREF":
            v = num(args[0]) if args else None
            if v is None or int(v) not in DBREF_TABLE:
                return exe_err()
            self.dbref_index = int(v)
            return "", PROMPT_OK
        if key == "HOLD":
            self.hold = True
            return "", PROMPT_OK
        if key == "HOLDCLR":
            self.hold = False
            return "", PROMPT_OK
        if key == "HOLDTHRESH":
            v = num(args[0]) if args else None
            if v is None or int(v) not in (1, 2, 3, 4):
                return exe_err()
            self.hold_thresh = int(v)
            return "", PROMPT_OK
        if key in ("MAX", "MIN", "MNMX"):
            val = self._measure_value()
            if key == "MAX":
                self.minmax_mode, self.max_val = "MAX", val
            elif key == "MIN":
                self.minmax_mode, self.min_val = "MIN", val
            else:
                self.minmax_mode, self.min_val, self.max_val = "BOTH", val, val
            self.auto_range = False
            return "", PROMPT_OK
        if key in ("MAXSET", "MINSET", "MNMXSET"):
            vals = [num(a) for a in args]
            if not vals or any(v is None for v in vals):
                return exe_err()
            if key == "MAXSET":
                self.minmax_mode, self.max_val = "MAX", vals[0]
            elif key == "MINSET":
                self.minmax_mode, self.min_val = "MIN", vals[0]
            else:
                if len(vals) < 2:
                    return cmd_err()
                self.minmax_mode, self.min_val, self.max_val = "BOTH", vals[0], vals[1]
            self.auto_range = False
            return "", PROMPT_OK
        if key == "MMCLR":
            self.minmax_mode, self.min_val, self.max_val = None, None, None
            return "", PROMPT_OK
        if key == "REL":
            self.rel_enabled, self.rel_base = True, self._measure_value()
            self.auto_range = False
            return "", PROMPT_OK
        if key == "RELCLR":
            self.rel_enabled = False
            return "", PROMPT_OK
        if key == "RELSET":
            v = num(args[0]) if args else None
            if v is None:
                return exe_err()
            self.rel_enabled, self.rel_base = True, v
            self.auto_range = False
            return "", PROMPT_OK

        if key == "COMP":
            self.comp_enabled, self.hold = True, True
            return "", PROMPT_OK
        if key == "COMPCLR":
            self.comp_enabled = False
            return "", PROMPT_OK
        if key == "COMPHI":
            v = num(args[0]) if args else None
            if v is None:
                return exe_err()
            self.comp_hi = v
            return "", PROMPT_OK
        if key == "COMPLO":
            v = num(args[0]) if args else None
            if v is None:
                return exe_err()
            self.comp_lo = v
            return "", PROMPT_OK

        if key in ("REMS", "RWLS", "LOCS", "LWLS"):
            self.remote_mode = key
            return "", PROMPT_OK
        if key == "SAVE":
            v = num(args[0]) if args else None
            if v is None or not 1 <= int(v) <= 6:
                return exe_err()
            self.saved[int(v)] = self._snapshot()
            return "", PROMPT_OK
        if key == "CALL":
            v = num(args[0]) if args else None
            if v is None or int(v) not in self.saved:
                return exe_err()
            self._restore(self.saved[int(v)])
            return "", PROMPT_OK

        return cmd_err()   # 未知命令 -> ?>（命令错误）

    # ------------------------------------------------------------ 查询分支
    def _exec_query(self, key, exe_err, cmd_err):
        if key == "IDN":
            return f"FLUKE, 8808A, {self.serial_no}, {self.firmware}", PROMPT_OK
        if key == "SERIAL":
            return self.serial_no, PROMPT_OK
        if key == "TST":
            return "0", PROMPT_OK
        if key == "FUNC1":
            return self.func1, PROMPT_OK
        if key == "FUNC2":
            if self.func2 is None:
                return exe_err()
            return self.func2, PROMPT_OK
        if key == "AUTO":
            return ("1" if self.auto_range else "0"), PROMPT_OK
        if key == "RANGE1":
            return str(self.range_n), PROMPT_OK
        if key == "RANGE2":
            if self.func2 is None:
                return exe_err()
            return str(self.range_n), PROMPT_OK
        if key == "RATE":
            return self.rate, PROMPT_OK
        if key == "TRIGGER":
            return str(self.trigger_type), PROMPT_OK
        if key == "FORMAT":
            return str(self.format), PROMPT_OK
        if key == "DBREF":
            return str(self.dbref_index), PROMPT_OK
        if key == "HOLDTHRESH":
            return str(self.hold_thresh), PROMPT_OK
        if key == "MOD":
            m = 0
            m |= 1 if self.minmax_mode == "MIN" else 0
            m |= 2 if self.minmax_mode == "MAX" else 0
            m |= 1 | 2 if self.minmax_mode == "BOTH" else 0
            m |= 4 if self.hold else 0
            m |= 8 if self.db_enabled else 0
            m |= 32 if self.rel_enabled else 0
            m |= 64 if self.comp_enabled else 0
            return str(m), PROMPT_OK
        if key == "RELSET":
            if not self.rel_enabled:
                return exe_err()
            return self._fmt_num(self.rel_base), PROMPT_OK
        if key == "MEAS1":
            return self._fmt_num(self._measure_value()), PROMPT_OK
        if key == "MEAS2":
            if self.func2 is None:
                return exe_err()
            return self._fmt_num(self._measure_value() * 0.5), PROMPT_OK
        if key == "MEAS":
            if self.func2 is None:
                return self._fmt_num(self._measure_value()), PROMPT_OK
            v1, v2 = self._measure_value(), self._measure_value() * 0.5
            return self._fmt_dual(v1, v2), PROMPT_OK
        if key == "VAL1":
            return self._fmt_num(self._measure_value()), PROMPT_OK
        if key == "VAL2":
            if self.func2 is None:
                return exe_err()
            return self._fmt_num(self._measure_value() * 0.5), PROMPT_OK
        if key == "VAL":
            if self.func2 is None:
                return self._fmt_num(self._measure_value()), PROMPT_OK
            return self._fmt_dual(self._measure_value(), self._measure_value() * 0.5), PROMPT_OK
        if key == "COMP":
            if not self.comp_enabled:
                return exe_err()
            v = self._measure_value()
            if v > self.comp_hi:
                return "HI", PROMPT_OK
            if v < self.comp_lo:
                return "LO", PROMPT_OK
            return "PASS", PROMPT_OK
        return cmd_err()

    # ------------------------------------------------------------ 星号命令
    def _exec_star(self, key, args, exe_err, cmd_err):
        num = _parse_num
        if key == "*IDN?":
            return f"FLUKE, 8808A, {self.serial_no}, {self.firmware}", PROMPT_OK
        if key == "*TST?":
            return "0", PROMPT_OK
        if key == "*OPC?":
            return "1", PROMPT_OK
        if key == "*STB?":
            return "0", PROMPT_OK
        if key == "*ESR?":
            v, self.esr = self.esr, 0
            return str(v), PROMPT_OK
        if key == "*CLS":
            self.esr = 0
            return "", PROMPT_OK
        if key == "*RST":
            self.__init__(self._t, self._cfg)  # 上电复位
            return "", PROMPT_OK
        if key == "*TRG":
            return "", PROMPT_OK
        if key in ("*OPC", "*WAI", "*TST"):
            return "", PROMPT_OK
        if key in ("*ESE?", "*SRE?"):
            return "0", PROMPT_OK
        if key in ("*ESE", "*SRE"):
            v = num(args[0]) if args else None
            if v is None or not 0 <= int(v) <= 255:
                return exe_err()
            return "", PROMPT_OK
        return cmd_err()

    # ------------------------------------------------------------ 测量模拟
    def _measure_value(self) -> float:
        """按功能与量程产生确定性伪读数（回归可比对）。"""
        self._measure_seed += 0.001
        base = {
            "VDC": 1.2345, "VAC": 0.9876, "VACDC": 1.1000,
            "ADC": 0.0123, "AAC": 0.0111, "AACDC": 0.0120,
            "OHMS": 123.45, "FREQ": 50.00, "CONT": 0.0, "DIODE": 0.65,
        }.get(self.func1, 0.0)
        scale = {1: 0.01, 2: 0.1, 3: 1.0, 4: 10.0, 5: 100.0, 6: 1000.0, 7: 10000.0}.get(self.range_n, 1.0)
        scalable = self.func1 in ("VDC", "VAC", "ADC", "AAC", "OHMS")
        v = base * (scale if scalable else 1.0)
        v += math.sin(self._measure_seed * 10) * abs(v) * 0.002
        if self.rel_enabled:
            v -= self.rel_base
        return v

    def _fmt_num(self, v: float) -> str:
        # 手册输出示例：+1.2345E+0；过载 = +/- 1.0E+9
        if abs(v) >= OVERLOAD_VALUE:
            return "+1.0E+9"
        s = f"{v:+.4E}"
        return s

    def _fmt_dual(self, v1: float, v2: float) -> str:
        units = {"VDC": "VDC", "VAC": "VAC", "VACDC": "VAC", "ADC": "ADC",
                 "AAC": "AAC", "AACDC": "AAC", "OHMS": "OHMS", "FREQ": "HZ",
                 "DIODE": "VDC", "CONT": "OHMS"}
        u1 = units.get(self.func1, "")
        u2 = units.get(self.func2 or "", "")
        if self.format == 2:
            return f"{self._fmt_num(v1)} {u1}, {self._fmt_num(v2)} {u2}"
        return f"{self._fmt_num(v1)},{self._fmt_num(v2)}"

    def _range_valid_for(self, func: str, n: int) -> bool:
        cols = {"VDC": 0, "VAC": 0, "VACDC": 0, "ADC": 4, "AAC": 2,
                "AACDC": 2, "OHMS": 1, "FREQ": 3}
        col = cols.get(func)
        if col is None:
            return False
        return RANGE_TABLE[n][col] is not None

    def _reset_modifiers_for_function(self, func: str) -> None:
        if func not in ("VDC", "VAC", "VACDC"):
            self.db_enabled = False
        if func in ("DIODE", "CONT"):
            self.auto_range = False

    def _snapshot(self) -> dict:
        return {"func1": self.func1, "func2": self.func2, "range_n": self.range_n,
                "rate": self.rate, "auto_range": self.auto_range,
                "trigger_type": self.trigger_type, "format": self.format}

    def _restore(self, snap: dict) -> None:
        for k, v in snap.items():
            setattr(self, k, v)

    # ------------------------------------------------------------ 输出
    def _respond_prompt(self, prompt: str) -> None:
        self._send_raw(prompt)

    def _send_raw(self, text) -> None:
        try:
            # 帧（_compose_frame）为 bytes，文本为 str，统一成 bytes 发出
            self._t.write(text if isinstance(text, bytes) else text.encode("ascii"))
        except Exception:
            pass


def build_sim_pair(config: Optional[SimulatorConfig] = None):
    """构建 (上位机端传输, 模拟从站)。协议栈接第一个返回值。"""
    host_end, sim_end = LoopbackTransport.pair()
    sim = Sim8808A(sim_end, config)
    return host_end, sim
