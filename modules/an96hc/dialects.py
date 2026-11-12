# -*- coding: utf-8 -*-
"""协议方言层：同一套上位机流程，按「仪器当前用的是哪种协议」翻译成不同命令。

为什么需要它（2026-09-24 现场教训）
------------------------------------
仪器面板里可选的协议有三种（手册 4.9「通信协议：内置 Ainuo 公司 ASCII 协议、
SCPI 协议、SE 协议」），**SE 的系统参数指令集里没有「切换协议」命令**，只能在
仪器上手动改。所以上位机必须自己适配当前协议，否则就会出现「仪器回话了但指令
不生效」——现场表现为：SCPI 模式下 `*IDN?` 正常回 `Ainuo,AN9637HC,...`，
而 SE 的 `SAA` 被静默忽略（0 字节）。

三种协议的能力差异（这决定了界面上哪些按钮可用）
--------------------------------------------------
| 能力            | SE              | Ainuo ASCII        | SCPI                     |
|-----------------|-----------------|--------------------|--------------------------|
| 新建档案        | `FN nn,name`    | `ENTER-SET`+`FNN`  | `:MEM:STAT:DEF name,n`   |
| 追加测试步      | `SAA/SAD/SAI/SAG` | `SET-ACW/DCW/IR/GB`（**追加且带参**） | **无命令** |
| 改已有步参数    | 作用于最后追加的步 | 不能改（只能 DELI-LAST 重加） | 按步号 `SAFE:STEP n:AC ...` |
| 保存            | `FS`            | `FS`               | `:MEM:SAVE`              |
| 启动/停止       | `TEST`/`RESET`  | `TEST`/`RESET`     | `SAFE:STAR`/`SAFE:STOP`  |
| 查结果          | `TD?`/`RD nn?`  | `TD?`/`RD nn?`（格式手册已定义，可解析） | `SAFE:RES:ALL?` |
| 设置命令应答    | `ACK`/`NAK`     | **回显命令字符串** | **无应答**               |
| 错误报送        | `NAK(0x15)`     | 文本 `UnkownCmd` 等 | 无（需读回校验）         |

注意 Ainuo 的「设置类回传命令字符串」——这正是 9-24 现场看到的"回显"。
在 Ainuo 协议下那是**正常应答**，不是故障。
"""

from . import protocol as P
from .protocol import MODES, ProtocolError


# --------------------------------------------------------------------------- #
# 回读值归一化（2026-09-24 用户现场提问引出）
# --------------------------------------------------------------------------- #
# 用户输入「1111」，输入框却显示 `+1.111000E+03`——看着像值被改了，其实是
# SCPI 仪器把数值按科学计数法回读（1.111×10³ = 1111，值没错），而上位机把这段
# 原文直接塞回了输入框；再加上输入框只有 12 字符宽，末尾的 `3` 被裁掉，
# 显示成 `+1.111000E+0`，更让人怀疑"数被吃了"。
#
# 处置原则：**仪器单位 ≠ 界面单位**，且回读文本要经「反换算 + 人类可读格式化」
# 才能写回输入框。写入时是 `value * scale`（界面单位 → 仪器单位），
# 读回时就必须 `raw / scale`（仪器单位 → 界面单位），否则 2.5 mA 会显示成 0.0025。
def num_to_text(v):
    """数值 → 不带科学计数法、不留多余尾零的字符串。"""
    f = float(v)
    if f != 0 and abs(f) < 1e15 and f == int(f):
        return str(int(f))
    if f == 0:
        return "0"
    s = ("%.10f" % f).rstrip("0").rstrip(".")
    if s in ("", "-", "+"):          # 太小，10 位小数截没了，回退到原始表示
        s = repr(f)
    return s


def fmt_readback(text):
    """把仪器回读文本变回人看的样子：`+1.111000E+03` → `1111`。

    非纯数值文本（如 `OK`、`UnkownCmd`）原样返回，不猜测。
    """
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""
    try:
        return num_to_text(float(s))
    except (ValueError, TypeError):
        return s


# --------------------------------------------------------------------------- #
# 基类
# --------------------------------------------------------------------------- #
class Dialect:
    name = "?"
    label = "?"
    # 能力位（界面据此启用/禁用按钮）
    can_add_step = True        # 能否新增测试步
    add_step_takes_values = False   # 新增步时是否要带参数（Ainuo 是）
    can_set_existing_step = True    # 能否改写「已有」步的参数
    needs_step_no = False      # 参数读写是否必须指定步号（SCPI 是）
    needs_step_context = False # 参数写入作用于「当前测试步」（SE）：步类型须与页签一致
    # 应答语义
    set_needs_reply = True     # 设置命令是否一定有应答

    # ---- 应答分类：三种协议的差异集中在这里 ----
    def classify(self, raw: bytes, sent: str):
        """把原始应答翻译成 (status, payload)。

        status: 'ACK' | 'NAK' | 'DATA' | 'ERROR' | 'EMPTY'
        """
        raise NotImplementedError

    def file_new(self, num, name):
        raise NotImplementedError("该协议不支持此操作: 新建档案")

    def file_save(self):
        return ["FS"]

    def file_load(self, num):
        raise NotImplementedError("该协议不支持此操作: 读取档案")

    def file_delete(self, num=None):
        raise NotImplementedError("该协议不支持此操作: 删除档案")

    def add_step(self, mode, values=None):
        raise NotImplementedError("该协议不支持此操作: 新增测试步")

    def set_param(self, mode, param, value, step=None):
        raise NotImplementedError

    def get_param(self, mode, param, step=None):
        raise NotImplementedError

    def parse_readback(self, mode, param, text):
        """把「仪器回读原文」转成该协议下界面应显示的值。

        基类只做格式化（去科学计数法、去尾零）；有单位换算的协议自己覆盖。
        """
        return fmt_readback(text)

    def has_param(self, mode, param) -> bool:
        """该方言是否有此参数的命令（无则界面跳过该项，不中断整组下发）。"""
        return True

    def delete_last_step(self):
        raise NotImplementedError("该协议不支持此操作: 删除最后一步")

    def start(self):
        return ["TEST"]

    def stop(self):
        return ["RESET"]

    def query_all(self):
        return "TD?"

    def query_step(self, num):
        return "RD %s?" % num

    def parse_results(self, text):
        """把结果文本尽力解析成 [(项目, 值..., 结论)]；解析不了返回 None。"""
        return None

    # 查询类（不支持时给 None，由设备层决定报错还是跳过）
    step_count_cmd = "ST?"
    file_current_cmd = "LF?"

    def supports_system_params(self):
        return True


# --------------------------------------------------------------------------- #
# SE 协议（现有实现，命令最完整）
# --------------------------------------------------------------------------- #
class SEDialect(Dialect):
    name = "SE"
    label = "SE 协议"
    can_add_step = True
    add_step_takes_values = False
    can_set_existing_step = True
    needs_step_no = False
    needs_step_context = True
    set_needs_reply = True

    def classify(self, raw, sent):
        if not raw:
            # SE 的每条命令都应有应答，空应答即异常（由设备层报出友好提示）
            return "EMPTY", ""
        return P.parse_response(raw)

    def file_new(self, num, name):
        return [P.build_file_new(num, name)]

    def file_load(self, num):
        return [P.build_file_load(num)]

    def file_save(self):
        return [P.build_file_save()]

    def file_saveas(self, num, name):
        return [P.build_file_saveas(num, name)]

    def file_delete(self, num=None):
        return [P.build_file_delete(num or "")]

    def add_step(self, mode, values=None):
        return [P.build_add_step(mode)]

    def set_param(self, mode, param, value, step=None):
        return [P.build_set(param, value)]

    def get_param(self, mode, param, step=None):
        return [P.build_get(param)]


# --------------------------------------------------------------------------- #
# Ainuo ASCII 协议（建档最方便：一条 SET-XXX 就是「追加一步并配好参数」）
# --------------------------------------------------------------------------- #
# 每种模式的参数顺序（严格按手册 3.2.5 的表格）。
#   ("参数键", None) 表示取界面当前值；  (None, "缺省值") 表示该位置手册有、
#   但界面没暴露的参数，按手册缺省值填，保证位次不错。
AINUO_SPEC = {
    "ACW": [("voltage", None), ("hi_limit", None), ("lo_limit", None), ("dwell", None),
            (None, "0"),            # 5 三通道扫描选项，缺省 0
            ("ramp_up", None), ("ramp_down", None), ("arc", None),
            (None, "0"),            # 9 补偿开关，缺省 0
            ("freq", None)],
    "DCW": [("voltage", None), ("hi_limit", None), ("lo_limit", None), ("dwell", None),
            (None, "0"),            # 5 三通道扫描选项
            ("ramp_up", None), ("ramp_down", None), ("arc", None),
            ("charge_lo", None), ("offset", None),
            (None, "0")],           # 11 补偿开关
    "IR":  [("voltage", None), ("hi_limit", None), ("lo_limit", None), ("dwell", None),
            (None, "0"),            # 5 三通道扫描选项
            ("ramp_up", None), ("ramp_down", None), ("charge_lo", None),
            (None, "50000")],       # 9 补偿值(MΩ)，手册缺省 50000
    "GND": [("current", None), ("hi_limit", None), ("lo_limit", None), ("dwell", None),
            ("voltage", None), ("offset", None),
            (None, "0"),            # 7 补偿开关
            ("freq", None)],
}

AINUO_SET_CMD = {"ACW": "SET-ACW", "DCW": "SET-DCW", "IR": "SET-IR", "GND": "SET-GB"}

AINUO_ERRORS = ("UnkownCmd", "CanntExecute", "ExceedPara")


class AinuoDialect(Dialect):
    name = "AINUO"
    label = "Ainuo ASCII"
    can_add_step = True
    add_step_takes_values = True      # 追加步时必须把参数一起发
    can_set_existing_step = False     # SET-XXX 只会「追加」，改不了已有步
    needs_step_no = False
    set_needs_reply = True            # 会回显命令字符串，等于收到应答

    def classify(self, raw, sent):
        if not raw:
            return "EMPTY", ""
        text = raw.rstrip(b"\r\n").decode("utf-8", "replace").strip()
        if not text:
            return "EMPTY", ""
        # 兼容混入的 SE 应答，便于串协议时快速看出问题
        if text == "\x06":
            return "ACK", ""
        if text == "\x15":
            return "NAK", ""
        for e in AINUO_ERRORS:
            if text.startswith(e):
                return "ERROR", text
        if text.upper() == sent.strip().upper():
            return "ACK", ""              # 设置类：回显命令字符串 = 执行成功
        head = sent.split()[0].upper() if sent.split() else ""
        if head and text.upper().startswith(head):
            return "DATA", text[len(head):].strip()
        return "DATA", text

    def file_new(self, num, name):
        # Ainuo 必须在设置页面下操作；FNN 的 index 是 0~99，与界面 01~100 对应
        try:
            idx = int(num) - 1
        except Exception:
            idx = 0
        if not (0 <= idx <= 99):
            raise ProtocolError("Ainuo 协议档案号须为 01~100（对应索引 0~99）")
        return ["ENTER-SET", "FNN %d,%s" % (idx, name)]

    def file_save(self):
        return ["FS"]

    def delete_last_step(self):
        return ["DELI-LAST"]

    def delete_all_steps(self):
        return ["DELI-ALL"]

    def add_step(self, mode, values=None):
        """按手册参数位次拼一条 SET-XXX（含参数）= 追加一步并配好参数。"""
        if mode not in AINUO_SPEC:
            raise ProtocolError("Ainuo 协议不支持 %s" % mode)
        values = values or {}
        out = []
        for key, dflt in AINUO_SPEC[mode]:
            if key is None:
                out.append(dflt)
                continue
            param = _param(mode, key)
            if param is None:
                out.append("0")
                continue
            v = values.get(key, param.default)
            out.append(_fmt(_norm(param, v)))
        return ["%s %s," % (AINUO_SET_CMD[mode], ",".join(out))]

    def set_param(self, mode, param, value, step=None):
        raise ProtocolError(
            "Ainuo 协议里 SET-XXX 是「在最后添加一个步骤」，无法改写已有步的参数。\n"
            "请把参数填好后点「下发设定」或「添加测试步」——会自动按当前参数追加一步；"
            "已有步的参数只能 DELI-LAST 删除后重建。")

    def get_param(self, mode, param, step=None):
        raise ProtocolError("Ainuo 协议没有「回读单步参数」命令，请用 TD?/RD? 查测试数据")

    def start(self):
        return ["ENTER-TEST", "TEST"]

    def stop(self):
        return ["RESET"]

    def query_step(self, num):
        # Ainuo 的 RD 是 0 基（0~7 表示第 1~8 步，-1=当前步）
        try:
            return "RD %d?" % (int(num) - 1)
        except Exception:
            return "RD -1?"

    # Ainuo 没有「查步数 / 查当前档案」命令
    step_count_cmd = None
    file_current_cmd = None

    def supports_system_params(self):
        return False

    def parse_results(self, text):
        """解析 TD? / RD? 回传。

        TD? 例：`GB,25.0A,3.3mΩ,OK,;ACW,0.20kV,2.638mA,OK,;...;OK;`
        RD? 例：`DCW,1.50kV,0.0uA,OK,;`
        """
        if not text:
            return None
        rows = []
        for item in text.split(";"):
            item = item.strip()
            if not item:
                continue
            fields = [f.strip() for f in item.split(",") if f.strip() != ""]
            if not fields:
                continue
            if len(fields) == 1:
                rows.append(("综合结论", fields[0], ""))
            else:
                rows.append((fields[0], ", ".join(fields[1:-1]), fields[-1]))
        return rows or None


def _param(mode, key):
    for p in MODES[mode]["params"]:
        if p.key == key:
            return p
    return None


def _norm(param, value):
    """复用 protocol 的取值归一化（含范围校验）。"""
    return P.validate(param, value)


def _fmt(v):
    if isinstance(v, str):
        return v
    if float(v) == int(float(v)):
        return str(int(float(v)))
    return ("%.6f" % float(v)).rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- #
# SCPI 协议（能改参/启停/读结果，但**没有**新增测试步的命令）
# --------------------------------------------------------------------------- #
# (模式, 参数键) -> (步号占位命令, 查询命令, 单位换算系数)
SCPI_MAP = {
    ("ACW", "voltage"):   ("AC", "AC?", 1.0),
    ("ACW", "hi_limit"):  ("AC:LIM", "AC:LIM?", 0.001),      # mA -> A
    ("ACW", "lo_limit"):  ("AC:LIM:LOW", "AC:LIM:LOW?", 0.001),
    ("ACW", "ramp_up"):   ("AC:TIME:RAMP", "AC:TIME:RAMP?", 1.0),
    ("ACW", "ramp_down"): ("AC:TIME:FALL", "AC:TIME:FALL?", 1.0),
    ("ACW", "dwell"):     ("AC:TIME", "AC:TIME?", 1.0),
    ("ACW", "arc"):       ("AC:LIM:ARC", "AC:LIM:ARC?", 1.0),
    ("ACW", "freq"):      ("AC:FREQ", "AC:FREQ?", 1.0),

    ("DCW", "voltage"):   ("DC", "DC?", 1.0),
    ("DCW", "hi_limit"):  ("DC:LIM", "DC:LIM?", 1e-6),       # uA -> A
    ("DCW", "lo_limit"):  ("DC:LIM:LOW", "DC:LIM:LOW?", 1e-6),
    ("DCW", "ramp_up"):   ("DC:TIME:RAMP", "DC:TIME:RAMP?", 1.0),
    ("DCW", "ramp_down"): ("DC:TIME:FALL", "DC:TIME:FALL?", 1.0),
    ("DCW", "dwell"):     ("DC:TIME", "DC:TIME?", 1.0),

    ("IR", "voltage"):    ("IR", "IR?", 1.0),
    ("IR", "hi_limit"):   ("IR:LIM", "IR:LIM?", 1e6),        # MΩ -> Ω
    ("IR", "ramp_up"):    ("IR:TIME:RAMP", "IR:TIME:RAMP?", 1.0),
    ("IR", "ramp_down"):  ("IR:TIME:FALL", "IR:TIME:FALL?", 1.0),
    ("IR", "dwell"):      ("IR:TIME", "IR:TIME?", 1.0),

    ("GND", "current"):   ("GB", "GB?", 1.0),
    ("GND", "hi_limit"):  ("GB:LIM", "GB:LIM?", 0.001),      # mΩ -> Ω
    ("GND", "lo_limit"):  ("GB:LIM:LOW", "GB:LIM:LOW?", 0.001),
    ("GND", "dwell"):     ("GB:TIME", "GB:TIME?", 1.0),
    ("GND", "voltage"):   ("GB:VOLT", "GB:VOLT?", 1.0),
    ("GND", "freq"):      ("GB:FREQ", "GB:FREQ?", 1.0),
}


class SCPIDialect(Dialect):
    name = "SCPI"
    label = "SCPI 协议"
    can_add_step = False             # 手册无新增步命令
    add_step_takes_values = False
    can_set_existing_step = True     # 但必须按步号寻址
    needs_step_no = True
    set_needs_reply = False          # SCPI 设置命令不回任何东西

    def classify(self, raw, sent):
        if raw:
            t = raw.rstrip(b"\r\n")
            if t == b"\x06":
                return "ACK", ""
            if t == b"\x15":
                return "NAK", ""
            text = t.decode("utf-8", "replace").strip()
            if text:
                if text.upper() in ("ERROR",) or text.startswith("UnkownCmd"):
                    return "ERROR", text
                return "DATA", text
        # 空应答：SCPI 的设置命令本来就不回；查询命令空则是异常
        if sent.strip().endswith("?"):
            return "EMPTY", ""
        return "ACK", ""

    def file_new(self, num, name):
        try:
            n = int(num)
        except Exception:
            raise ProtocolError("SCPI 档案号须为整数（1~100）")
        if not (1 <= n <= 100):
            raise ProtocolError("SCPI 档案号须为 1~100")
        return [":MEM:STAT:DEF %s,%d" % (name, n), ":MEM:SAVE"]

    def file_save(self):
        return [":MEM:SAVE"]

    def file_delete(self, num=None):
        if num is None:
            raise ProtocolError("SCPI 删除档案须指定号码")
        return [":MEM:DEL:LOCA %d" % int(num)]

    def add_step(self, mode, values=None):
        raise ProtocolError(
            "SCPI 协议**没有**「新增测试步 / 改步类型」命令（手册只有 :STEP<n>:DELete 和 "
            ":MODE? 查询）。\n请在仪器面板上先建好测试步，再用本软件按步号改参数、启停、读结果。\n"
            "若要用上位机建档，请把仪器协议切到 SE 或 Ainuo ASCII。")

    def set_param(self, mode, param, value, step=None):
        if step is None:
            raise ProtocolError("SCPI 协议必须指定步号（参数按 `SAFE:STEP n:...` 寻址）")
        key = (mode, param.key)
        if key not in SCPI_MAP:
            raise ProtocolError("SCPI 未定义 %s.%s 的命令（手册无此参数）"
                                % (mode, param.key))
        cmd, _, scale = SCPI_MAP[key]
        norm = _norm(param, value)
        return ["SAFE:STEP %d:%s %s" % (int(step), cmd, _fmt(float(norm) * scale))]

    def get_param(self, mode, param, step=None):
        if step is None:
            raise ProtocolError("SCPI 协议必须指定步号")
        key = (mode, param.key)
        if key not in SCPI_MAP:
            raise ProtocolError("SCPI 未定义 %s.%s 的查询命令" % (mode, param.key))
        _, q, scale = SCPI_MAP[key]
        return ["SAFE:STEP %d:%s" % (int(step), q)]

    def parse_readback(self, mode, param, text):
        """SCPI 回读多为科学计数法（`+1.111000E+03`），且单位是仪器单位。

        写入时 `value * scale`，所以这里要 `raw / scale` 换回界面单位，
        再格式化成普通十进制，用户输入多少就看到多少。
        """
        key = (mode, getattr(param, "key", None))
        if key not in SCPI_MAP:
            return fmt_readback(text)
        _, _, scale = SCPI_MAP[key]
        try:
            raw = float(str(text).strip())
        except (ValueError, TypeError):
            return fmt_readback(text)
        if scale in (0, None):
            return num_to_text(raw)
        return num_to_text(raw / scale)

    def has_param(self, mode, param) -> bool:
        return (mode, getattr(param, "key", None)) in SCPI_MAP

    def start(self):
        return ["SAFE:STAR"]

    def stop(self):
        return ["SAFE:STOP"]

    def query_all(self):
        return "SAFE:RES:ALL?"

    def query_step(self, num):
        return "SAFE:RES:LAST?"

    step_count_cmd = "SAFE:SNUM?"
    file_current_cmd = None

    def supports_system_params(self):
        return False


# --------------------------------------------------------------------------- #
DIALECTS = [SEDialect(), AinuoDialect(), SCPIDialect()]
BY_LABEL = {d.label: d for d in DIALECTS}
BY_NAME = {d.name: d for d in DIALECTS}


def get(label_or_name):
    d = BY_LABEL.get(label_or_name) or BY_NAME.get(label_or_name)
    if d is None:
        raise ProtocolError("未知协议: %r" % label_or_name)
    return d
