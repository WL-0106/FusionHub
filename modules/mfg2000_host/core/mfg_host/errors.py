"""异常码映射：仪器错误码 → 人话提示。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# 手册"错误信息"章节(P355~P367)典型错误码
ERROR_HINTS = {
    -101: "命令串中出现非法字符(如 #、$、%)，检查上位机是否拼接了异常参数",
    -102: "命令语法错误(如出现意外空格)，检查命令帧格式",
    -103: "分隔符使用错误(空格/逗号/冒号位置不对)，检查命令头与参数间仅一个空格",
    -108: "参数多余：命令收到了多于预期的参数",
    -109: "参数缺失：命令收到了少于预期的参数",
    -112: "命令助记符过长：短形式/长形式拼写不完整",
    -138: "不允许的后缀：参数带了单位后缀但该命令不接受",
}


@dataclass
class DeviceError:
    code: int
    message: str
    raw: str

    @property
    def hint(self) -> str:
        return ERROR_HINTS.get(self.code, "未知错误码，请对照手册错误信息章节")

    def human(self) -> str:
        return f"[{self.code}] {self.message} —— {self.hint}"


_ERR_RE = re.compile(r"^\s*([+-]?\d+)(?:[, ]\s*(.*))?$")


def parse_error_string(text: str) -> Optional[DeviceError]:
    """解析 SYSTem:ERRor? 返回，如 '-138 Suffix not allowed' 或 '0, No error'。

    空队列格式手册未明确(澄清项Q4)，'0'/'0, No error' 视为无错误。
    """
    s = text.strip()
    if not s:
        return None
    if "no error" in s.lower():
        return None   # 空队列语义（0,"No error" / "." 等变体），停止弹队列
    m = _ERR_RE.match(s)
    if m:
        code = int(m.group(1))
        msg = (m.group(2) or "").strip()
        if code == 0:
            return None
        return DeviceError(code=code, message=msg or "无描述", raw=s)
    return DeviceError(code=-1, message=s, raw=s)


class ProtocolError(Exception):
    """协议栈基础异常。"""


class CommTimeoutError(ProtocolError):
    """超时无响应(重试已用尽)。"""


class FrameError(ProtocolError):
    """错帧(非法字节流/超长帧)，已触发重同步。"""


class DeviceErrorList(ProtocolError):
    """读回的仪器错误队列非空。"""

    def __init__(self, errors: List[DeviceError]):
        self.errors = errors
        super().__init__("；".join(e.human() for e in errors))
