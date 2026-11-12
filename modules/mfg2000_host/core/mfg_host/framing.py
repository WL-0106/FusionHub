"""SCPI 报文分帧：半包/粘包/错帧处理。

SCPI 为 ASCII 文本协议，以 LF(可含 CR) 作为消息终结符：
- 半包：数据未含终结符时缓存，等待后续到达；
- 粘包：一次读出多条消息时按终结符切分，逐条返回；
- 错帧：流中出现超长无终结符内容视为失步，抛 FrameError，由协议栈清缓存重同步。
"""
from __future__ import annotations

from typing import List

TERMINATOR = b"\n"
MAX_FRAME = 4096  # 手册未规定最大帧长，按 SCPI 常规取 4KB，超长按失步处理


class FrameError(Exception):
    """错帧/失步。"""


class FrameDecoder:
    """增量分帧器，feed() 返回本批解析出的完整消息(已去 CR/LF)。"""

    def __init__(self, max_frame: int = MAX_FRAME):
        self._buf = bytearray()
        self._max_frame = max_frame

    @property
    def pending(self) -> int:
        return len(self._buf)

    def feed(self, data: bytes) -> List[str]:
        frames: List[str] = []
        self._buf.extend(data)
        while True:
            # 兼容 CR / LF / CR+LF 三种终结符（部分仪器 RS232 响应以 CR 结尾，
            # 仅认 LF 会导致永远等不到终结符而超时、残片污染后续帧）
            idx = -1
            for i, b in enumerate(self._buf):
                if b in (0x0A, 0x0D):
                    idx = i
                    break
            if idx < 0:
                break
            raw = bytes(self._buf[:idx])
            del self._buf[: idx + 1]
            while self._buf and self._buf[0] in (0x0A, 0x0D):
                del self._buf[0]          # 吞掉 CRLF/LFCR 的另一半
            if not raw:
                continue                   # 连续换行产生的空帧跳过
            frames.append(raw.decode("ascii", errors="replace"))
        if len(self._buf) > self._max_frame:
            self.flush()
            raise FrameError(f"接收缓冲超长({self._max_frame}B)无终结符，判定失步，已丢弃缓存重同步")
        return frames

    def flush(self) -> None:
        """丢弃未完成的半包(超时/失步后重同步)。"""
        self._buf.clear()
