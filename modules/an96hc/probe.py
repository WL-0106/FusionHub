# -*- coding: utf-8 -*-
"""仪器通讯诊断：探出仪器此刻说的是哪种协议 / 是否处于回显状态。

设计约束（现场安全）：
- **只发查询类指令**（`*IDN?` / `ST?` / `LF?` / `SAFE:SNUM?`），绝不发设置、
  启动、复位类指令，避免干扰正在跑的耐压测试。
- 两个结束符（CRLF / LF）都试，因为 SE 手册要求 LF、附录 C 又写 CRLF，
  现场对不上时表现为「完全无响应」，很容易被误判成接线问题。
- 判定逻辑是纯函数 `decide()`，可以离线单测。

背景（2026-09-24 现场）：
真机在 **SCPI 模式**下 `*IDN?` 正常回 `Ainuo,AN9637HC,...`，但 SE 的 `SAA`
被静默忽略（0 字节）。而 SCPI 没有任何「新建/改类型测试步」的命令，上位机在
SCPI 下无法建档 → 必须把仪器切到 SE。本模块就是为了让用户一眼看出该切什么。
"""

from . import protocol as P

# 探测序列：(期望协议, 命令, 用途)。全部为只读查询。
PROBES = [
    ("SE", "ST?", "查当前档案测试步数"),
    ("SE", "LF?", "查当前工作档案"),
    ("SCPI", "*IDN?", "读仪器识别信息"),
    ("SCPI", "SAFE:SNUM?", "查测试步数"),
]

VERDICT_SE = "SE"
VERDICT_SCPI = "SCPI"
VERDICT_ECHO = "ECHO"
VERDICT_NONE = "NONE"


def decide(rows):
    """由探测结果行推断结论。

    rows: list of dict(proto, cmd, term, status, payload, echo)
    status: 'ACK' | 'NAK' | 'DATA' | 'EMPTY' | 'ERR'
    返回 (verdict, term)
    """
    se_term = None
    scpi_answered = False
    echo_seen = False
    for r in rows:
        if r.get("echo"):
            echo_seen = True
        st = r.get("status")
        if r["proto"] == "SE" and st in ("ACK", "NAK", "DATA") and not r.get("echo"):
            se_term = r["term"]
        if r["proto"] == "SCPI" and st == "DATA" and (r.get("payload") or "").strip():
            scpi_answered = True
    if se_term is not None:
        return VERDICT_SE, se_term
    if scpi_answered:
        return VERDICT_SCPI, None
    if echo_seen:
        return VERDICT_ECHO, None
    return VERDICT_NONE, None


def advise(verdict, term=None):
    """把结论翻译成「下一步做什么」。"""
    if verdict == VERDICT_SE:
        t = {b"\r\n": "CRLF", b"\n": "LF"}.get(term, str(term))
        return ("仪器按 SE 协议应答（结束符 %s），软件可直接用。"
                "若结束符不是当前选择，已自动切好。" % t)
    if verdict == VERDICT_SCPI:
        return ("仪器当前是 SCPI 协议。SCPI 没有「新建测试步/改步类型」命令，"
                "上位机在 SCPI 下无法建档案 → 请在仪器上改："
                "系统设置 → 通信设置 → 协议选「SE」，然后重新连接。"
                "（仪器识别信息已读到，说明接线、波特率都是对的，只是协议选错。）")
    if verdict == VERDICT_ECHO:
        return ("收到的都是命令回显、没有仪器应答。检查："
                "① 是否走 RS485（半双工回显属正常，软件会自动跳过）；"
                "② 是否插在主通讯口而非 CTRL-COM 条码口；"
                "③ 波特率是否与仪器一致。")
    return ("仪器完全没有应答。检查：① 通讯口选择是否正确（设备管理器看端口号）；"
            "② 波特率/数据位/校验位是否与仪器「通信设置」一致；"
            "③ 线缆是否为交叉/直连对应（RS232 需交叉）；④ 仪器是否上电、通讯功能是否开启。")


def run_probe(transport, term_pref=b"\r\n", per_timeout=1.2):
    """实际探测。transport 需实现 exchange(text, term=..., timeout=...)。

    返回 dict(verdict, term, rows, advice)
    """
    terms = [term_pref] + [t for t in (b"\r\n", b"\n") if t != term_pref]
    rows = []
    for proto, cmd, note in PROBES:
        for term in terms:
            row = {"proto": proto, "cmd": cmd, "note": note, "term": term,
                   "status": "ERR", "payload": "", "echo": False}
            try:
                raw = transport.exchange(cmd, term=term, timeout=per_timeout)
            except Exception as e:
                row["payload"] = str(e)
                rows.append(row)
                continue
            rest = P.strip_echo(raw, cmd)
            if rest is not None:
                row["echo"] = True
                raw = rest
            if not raw:
                row["status"] = "EMPTY"          # 只收到回显，没别的
                rows.append(row)
                continue
            status, payload = P.parse_response(raw)
            row["status"], row["payload"] = status, payload
            rows.append(row)
            if proto == "SE" and status in ("ACK", "NAK", "DATA"):
                break                            # 该协议已确认，换下一条
            if proto == "SCPI" and status == "DATA" and payload.strip():
                break
    verdict, term = decide(rows)
    return {"verdict": verdict, "term": term, "rows": rows,
            "advice": advise(verdict, term)}
