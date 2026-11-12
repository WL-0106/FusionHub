"""MFG-2000 模拟从站：供无真机开发/回归，支持故障注入复现现场问题。

处理器由命令表(单一事实源)派生，覆盖正常帧 + 异常帧(错帧/超时/错误码)。
"""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, Optional, Tuple

from .command_table import CommandSpec, CommandTable, ParamError, load_table

SUFFIXES = {
    "HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9, "M HZ": 1e-3,
    "NS": 1e-9, "US": 1e-6, "MS": 1e-3, "S": 1.0,
    "V": 1.0, "MV": 1e-3, "VPP": 1.0, "VRMS": 1.0, "DBM": 1.0, "%": 1.0,
    "DEG": 1.0, "CYC": 1.0,
}


def _short_node(node: str) -> str:
    return "".join(c for c in node if c.isupper() or c.isdigit()).upper()


def _node_match(canon: str, incoming: str) -> bool:
    u = incoming.upper()
    return u == canon.upper() or u == _short_node(canon)


def _split_nodes(header: str) -> Tuple[str, ...]:
    return tuple(header.split(":"))


def _nr3(v: float) -> str:
    return f"{v:+.13E}"


class MfgSimulator:
    """进程内模拟从站。

    fault 注入：
      "timeout"      —— 持续不响应(模拟从站掉线)
      "timeout_once" —— 仅本次不响应，之后恢复
      "noise_once"   —— 先回一段无终结符脏字节，之后恢复(模拟错帧/失步)
      "error:<code> <msg>" —— 每条命令入队一条仪器错误(如 error:-222 Data out of range)
      其他/None      —— 正常
    """

    def __init__(self, table: Optional[CommandTable] = None):
        self.table = table or load_table()
        self.fault: Optional[str] = None
        self._rx = bytearray()
        self._errors: deque = deque()
        self._state: Dict[str, Any] = {}
        self._query_handlers: Dict[Tuple[str, ...], Tuple[str, Optional[int], CommandSpec]] = {}
        self._set_handlers: Dict[Tuple[str, ...], Tuple[str, Optional[int], CommandSpec]] = {}
        self._build_handlers()
        self.reset_state()

    # ---------- 构建 ----------
    def _build_handlers(self) -> None:
        for cmd_id, ch in self.table.instances():
            spec = self.table.get(cmd_id)
            if spec.scpi_query:
                header = spec.scpi_query.rstrip("?")
                nodes = _split_nodes(header.replace("{ch}", str(ch)))
                self._query_handlers[nodes] = (cmd_id, ch, spec)
            if spec.scpi_set:
                header = spec.scpi_set.split(" ")[0]
                nodes = _split_nodes(header.replace("{ch}", str(ch)))
                self._set_handlers[nodes] = (cmd_id, ch, spec)

    def reset_state(self) -> None:
        """恢复默认(等效 *RST 的参数部分)。"""
        self._state.clear()
        for cmd_id, ch in self.table.instances():
            spec = self.table.get(cmd_id)
            if spec.param is not None:
                self._state[self.table.state_key(cmd_id, ch)] = spec.param.get("default")
        self._state[self.table.state_key("counter_value")] = 1000.0

    # ---------- 字节流入口 ----------
    def handle(self, data: bytes) -> bytes:
        fault = self._fault_for_this_call()
        if fault == "timeout":
            return b""
        self._rx.extend(data)
        out = b""
        while b"\n" in self._rx:
            line, _, rest = self._rx.partition(b"\n")
            self._rx = bytearray(rest)
            resp = self._process_line(line.decode("ascii", errors="replace").strip("\r").strip())
            if resp is not None:
                out += (resp + "\n").encode("ascii")
        if fault == "noise_once":
            return b"\x1b[0m#GARBAGE"  # 无终结符脏字节：触发对端超时丢弃重同步
        return out

    def _fault_for_this_call(self) -> Optional[str]:
        f = self.fault
        if f in ("timeout_once", "noise_once"):
            self.fault = None
        return f

    # ---------- 单行处理 ----------
    def _process_line(self, line: str) -> Optional[str]:
        if not line:
            return None
        if self.fault and self.fault.startswith("error:"):
            _, _, payload = self.fault.partition("error:")
            self._errors.append(payload.strip())
        for part in line.split(";"):
            part = part.strip()
            if part:
                resp = self._process_cmd(part)
                if resp is not None:
                    return resp
        return None

    def _process_cmd(self, cmd: str) -> Optional[str]:
        is_query = "?" in cmd
        if is_query:
            header, _, arg = cmd.partition("?")
        else:
            header, _, arg = cmd.partition(" ")
        nodes = _split_nodes(header.strip())
        canon = self._match(self._query_handlers if is_query else self._set_handlers, nodes)
        if canon is None:
            self._errors.append("-113 Undefined header")
            return None
        cmd_id, ch, spec = canon
        if cmd_id == "rst":
            self.reset_state()
            return None
        if cmd_id == "cls":
            self._errors.clear()
            return None
        key = self.table.state_key(cmd_id, ch)

        if is_query:
            if arg:
                return self._query_bound(spec, arg)
            return self._format_return(spec, self._state.get(key))

        try:
            self._state[key] = self._parse_arg(spec, arg)
        except ParamError as e:
            self._errors.append(f"-222 Data out of range ({e})")
        return None

    @staticmethod
    def _match(handlers, nodes):
        for canon_nodes, payload in handlers.items():
            if len(canon_nodes) != len(nodes):
                continue
            if all(_node_match(c, n) for c, n in zip(canon_nodes, nodes)):
                return payload
        return None

    # ---------- 参数解析/校验(与上位机同表) ----------
    def _parse_arg(self, spec: CommandSpec, arg: str) -> Any:
        p = spec.param or {}
        ptype = p.get("type")
        s = arg.strip()
        u = s.upper()

        if u in ("MIN", "MINIMUM"):
            return p.get("min", p.get("default"))
        if u in ("MAX", "MAXIMUM"):
            return p.get("max", p.get("default"))
        if u in ("DEF", "DEFAULT"):
            return p.get("default")
        if u == "INF" and p.get("special"):
            return "INF"

        if ptype == "bool":
            if u in ("ON", "1", "TRUE"):
                return True
            if u in ("OFF", "0", "FALSE"):
                return False
            raise ParamError(f"布尔参数非法: {arg!r}")
        if ptype == "enum":
            if u not in p.get("choices", []):
                raise ParamError(f"枚举 {arg!r} 不在 {p.get('choices')}")
            return u
        if ptype in ("float", "int"):
            num, ok = self._parse_numeric(s)
            if not ok:
                raise ParamError(f"数值参数非法: {arg!r}")
            self.table.format_value(spec.id, num)  # 同表做范围/类型校验
            return int(round(num)) if ptype == "int" else num
        return s

    @staticmethod
    def _parse_numeric(s: str) -> Tuple[float, bool]:
        t = s.strip().upper().replace(" ", "")
        mult = 1.0
        for suf, m in sorted(SUFFIXES.items(), key=lambda kv: -len(kv[0])):
            if t.endswith(suf):
                t = t[: -len(suf)]
                mult = m
                break
        try:
            return float(t) * mult, True
        except ValueError:
            return 0.0, False

    def _query_bound(self, spec: CommandSpec, arg: str) -> str:
        p = spec.param or {}
        u = arg.strip().upper()
        if u in ("MIN", "MINIMUM"):
            v = p.get("min", p.get("default", 0.0))
        elif u in ("MAX", "MAXIMUM"):
            v = p.get("max", p.get("default", 0.0))
        else:
            self._errors.append("-103 Invalid separator")
            return "0"
        return self._format_return(spec, v)

    def _format_return(self, spec: CommandSpec, value: Any) -> str:
        r = spec.returns or {"type": "str"}
        rtype = r.get("type")
        if spec.id == "idn":
            return "GW INSTEK,MFG-2000,SN:SIM00001,V1.00"
        if spec.id == "sys_error":
            return self._errors.popleft() if self._errors else "0, No error"
        if spec.id == "sys_version":
            return "1994.0"
        if spec.id == "opc":
            return "1"
        if rtype == "bool":
            return "1" if value else "0"
        if rtype == "enum":
            return str(value)
        if rtype == "int_or_inf":
            return "INF" if value == "INF" else _nr3(float(value))
        if rtype == "float":
            return _nr3(float(value if value is not None else 0.0))
        return str(value)
