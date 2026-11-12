"""命令表加载与值编解码。

命令表(registers/scpi_commands.json)是全流程"单一事实源"：
协议栈、模拟从站、界面、自动化验证均由本模块派生。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _table_path() -> Path:
    """命令表路径：兼容 PyInstaller 打包(sys._MEIPASS)与源码运行。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "registers" / "scpi_commands.json"


TABLE_PATH = _table_path()

_SPECIAL_TOKENS = {"MIN", "MAX", "DEF", "INF", "MINIMUM", "MAXIMUM", "DEFAULT", "INFINITY"}


class TableError(Exception):
    """命令表结构错误。"""


class ParamError(ValueError):
    """参数本地校验失败(未发往仪器)。"""


@dataclass
class CommandSpec:
    id: str
    group: str
    name_cn: str
    template: bool
    access: str  # "R" / "W" / "RW"
    scpi_set: Optional[str] = None
    scpi_query: Optional[str] = None
    param: Optional[Dict[str, Any]] = None
    returns: Optional[Dict[str, Any]] = None
    ui: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    @property
    def writable(self) -> bool:
        return "W" in self.access

    @property
    def readable(self) -> bool:
        return "R" in self.access


class CommandTable:
    def __init__(self, meta: Dict[str, Any], commands: List[CommandSpec], channels: List[int]):
        self.meta = meta
        self.commands = commands
        self.channels = channels
        self._by_id = {c.id: c for c in commands}
        if len(self._by_id) != len(commands):
            raise TableError("命令表存在重复 id")

    # ---------- 查询 ----------
    def get(self, cmd_id: str) -> CommandSpec:
        try:
            return self._by_id[cmd_id]
        except KeyError:
            raise TableError(f"命令表中不存在 id={cmd_id!r}")

    def apply_series(self, key: str) -> str:
        """按系列覆盖参数范围（单一事实源：scpi_commands.json meta.series）。

        AFG-2000 系列实际规格（AFG-2225：25MHz/1mVpp~10Vpp/脉宽 20ns 起）
        严于 MFG-2000 系列命令表默认上限，切换系列即收紧校验。
        """
        s = (self.meta.get("series") or {}).get(key)
        if not s:
            raise TableError(f"未知系列 {key!r}")
        self.series = key
        for c in self.commands:
            p = c.param
            if not p:
                continue
            if c.id == "freq" and "freq_max" in s:
                p["max"] = s["freq_max"]
            elif c.id == "ampl":
                p["min"] = s.get("ampl_min", p.get("min", 0))
                p["max"] = s.get("ampl_max", p.get("max", 10))
            elif c.id == "dcoffset":
                a = abs(s.get("offset_abs", 5.0))
                p["min"], p["max"] = -a, a
            elif c.id == "pulse_width" and "pw_min" in s:
                p["min"] = s["pw_min"]
        return s.get("label", key)

    def instances(self, access: Optional[str] = None) -> List[Tuple[str, Optional[int]]]:
        """展开所有 (命令id, 通道) 实例；access 过滤 R/W/RW。"""
        out: List[Tuple[str, Optional[int]]] = []
        for c in self.commands:
            if access and c.access != access:
                continue
            if c.template:
                for ch in self.channels:
                    out.append((c.id, ch))
            else:
                out.append((c.id, None))
        return out

    # ---------- SCPI 生成 ----------
    def build_set(self, cmd_id: str, value: Any, ch: Optional[int] = None) -> str:
        spec = self.get(cmd_id)
        if not spec.writable:
            raise ParamError(f"{spec.name_cn}({cmd_id}) 为只读命令，不可写入")
        if spec.scpi_set is None:
            raise TableError(f"{cmd_id} 缺少 scpi_set 模板")
        if spec.param is None:
            return self._fill(spec.scpi_set, ch)  # 无参 set 命令(如 *RST)
        payload = self.format_value(cmd_id, value)
        return self._fill(spec.scpi_set, ch).format(value=payload)

    def build_query(self, cmd_id: str, ch: Optional[int] = None) -> str:
        spec = self.get(cmd_id)
        if not spec.readable:
            raise ParamError(f"{spec.name_cn}({cmd_id}) 为只写命令，不可查询")
        if spec.scpi_query is None:
            raise TableError(f"{cmd_id} 缺少 scpi_query 模板")
        return self._fill(spec.scpi_query, ch)

    def _fill(self, template: str, ch: Optional[int]) -> str:
        if "{ch}" in template:
            if ch is None:
                raise ParamError(f"该命令为通道命令，必须指定通道(可选 {self.channels})")
            if ch not in self.channels:
                raise ParamError(f"通道 {ch} 非法，可选 {self.channels}")
            return template.replace("{ch}", str(ch))
        return template

    def state_key(self, cmd_id: str, ch: Optional[int] = None) -> str:
        """模拟从站/回读比对使用的规范化键：命令头大写(兼容只写命令)。"""
        spec = self.get(cmd_id)
        tmpl = spec.scpi_query or spec.scpi_set
        if tmpl is None:
            raise TableError(f"{cmd_id} 既无 scpi_query 也无 scpi_set")
        header = tmpl.split(" ")[0].rstrip("?")
        return self._fill(header, ch).upper()

    # ---------- 参数校验与编码 ----------
    def format_value(self, cmd_id: str, value: Any) -> str:
        spec = self.get(cmd_id)
        p = spec.param
        if p is None:
            raise ParamError(f"{cmd_id} 不接受参数")
        ptype = p.get("type")

        if isinstance(value, str) and value.strip().upper() in _SPECIAL_TOKENS:
            return value.strip().upper()

        if ptype == "bool":
            if isinstance(value, str):
                v = value.strip().upper()
                if v in ("1", "ON", "TRUE"):
                    return "ON"
                if v in ("0", "OFF", "FALSE"):
                    return "OFF"
                raise ParamError(f"{spec.name_cn}: 布尔参数仅接受 ON/OFF/1/0，收到 {value!r}")
            return "ON" if bool(value) else "OFF"

        if ptype == "enum":
            choices = p.get("choices", [])
            v = str(value).strip().upper()
            if v not in choices:
                raise ParamError(f"{spec.name_cn}: 取值 {value!r} 非法，可选 {choices}")
            return v

        if ptype in ("float", "int"):
            try:
                num = float(value)
            except (TypeError, ValueError):
                raise ParamError(f"{spec.name_cn}: 需要数值参数，收到 {value!r}")
            if ptype == "int":
                if abs(num - round(num)) > 1e-9:
                    raise ParamError(f"{spec.name_cn}: 需要整数参数，收到 {value!r}")
                num = float(round(num))
            specials = p.get("special") or []
            if specials and str(value).strip().upper() in {s.upper() for s in specials}:
                return str(value).strip().upper()
            self._check_range(spec, num)
            return f"{num:.12g}"

        if ptype in ("str", "int_or_inf"):
            return str(value)

        raise TableError(f"{cmd_id} 参数类型 {ptype!r} 未定义")

    def _check_range(self, spec: CommandSpec, num: float) -> None:
        p = spec.param or {}
        if p.get("range_tbd"):
            return  # 手册未写明上下限(澄清项Q3)：仅做类型校验
        choices_num = p.get("choices_num")
        if choices_num is not None:
            if not any(abs(num - float(c)) < 1e-12 for c in choices_num):
                raise ParamError(f"{spec.name_cn}: 取值 {num} 非法，可选 {choices_num}")
            return
        lo, hi = p.get("min"), p.get("max")
        if lo is not None and num < float(lo) - 1e-12:
            raise ParamError(f"{spec.name_cn}: {num} 低于下限 {lo}")
        if hi is not None and num > float(hi) + 1e-12:
            raise ParamError(f"{spec.name_cn}: {num} 超出上限 {hi}")

    # ---------- 回读解析 ----------
    def parse_return(self, cmd_id: str, text: str) -> Any:
        spec = self.get(cmd_id)
        r = spec.returns or {"type": "str"}
        rtype = r.get("type")
        s = text.strip()

        if rtype == "str":
            return s
        if rtype == "bool":
            if s in ("1", "ON"):
                return True
            if s in ("0", "OFF"):
                return False
            raise ParamError(f"{spec.name_cn}: 回读 {s!r} 不是合法布尔值")
        if rtype == "enum":
            v = s.upper()
            choices = r.get("choices", [])
            if v not in choices:
                raise ParamError(f"{spec.name_cn}: 回读 {s!r} 不在 {choices} 中")
            return v
        if rtype == "int_or_inf":
            if s.upper() == "INF":
                return "INF"
            return int(round(float(s)))
        if rtype == "float":
            return parse_nr3(s)
        raise TableError(f"{cmd_id} 返回类型 {rtype!r} 未定义")


def parse_nr3(text: str) -> float:
    """解析仪器 NR3 回读(如 +1.0000000000000E+03)，兼容普通浮点。"""
    s = text.strip()
    try:
        return float(s)
    except ValueError:
        raise ParamError(f"无法解析数值回读 {text!r}")


def load_table(path: Path = TABLE_PATH) -> CommandTable:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    channels = list(meta.get("channels", [1]))
    commands = []
    for raw in data.get("commands", []):
        for key in ("id", "group", "name_cn", "access"):
            if key not in raw:
                raise TableError(f"命令 {raw.get('id', '<无id>')} 缺少字段 {key}")
        spec = CommandSpec(
            id=raw["id"],
            group=raw["group"],
            name_cn=raw["name_cn"],
            template=bool(raw.get("template", False)),
            access=raw["access"],
            scpi_set=raw.get("scpi_set"),
            scpi_query=raw.get("scpi_query"),
            param=raw.get("param"),
            returns=raw.get("returns"),
            ui=raw.get("ui", {}),
            notes=raw.get("notes", ""),
        )
        if "W" in spec.access and not spec.scpi_set:
            raise TableError(f"{spec.id} 可写但缺少 scpi_set")
        if "R" in spec.access and not spec.scpi_query:
            raise TableError(f"{spec.id} 可读但缺少 scpi_query")
        commands.append(spec)
    return CommandTable(meta, commands, channels)
