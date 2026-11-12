"""语义化仪器接口：界面只消费本层(如 set_frequency/read_amplitude)，不接触帧字节。

所有收发经命令表派生：参数校验、SCPI 生成、回读解析均来自单一事实源。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .command_table import CommandTable, ParamError, load_table
from .errors import DeviceError, DeviceErrorList, ProtocolError, parse_error_string
from .stack import ScpiStack


class Instrument:
    def __init__(self, stack: ScpiStack, table: Optional[CommandTable] = None):
        self._stack = stack
        self.table = table or load_table()

    # ---------- 连接生命周期 ----------
    def start(self) -> None:
        self._stack.start()

    def stop(self) -> None:
        self._stack.stop()

    # ---------- 通用读写(命令表驱动) ----------
    def set(self, cmd_id: str, value: Any, ch: Optional[int] = None) -> None:
        """写参数：本地按命令表校验 -> 生成 SCPI -> 入队发送。"""
        scpi = self.table.build_set(cmd_id, value, ch)  # 校验失败在此抛 ParamError
        self._stack.write(scpi)

    def get(self, cmd_id: str, ch: Optional[int] = None) -> Any:
        """读参数：查询并按命令表解析回读。"""
        scpi = self.table.build_query(cmd_id, ch)
        raw = self._stack.request(scpi)
        return self.table.parse_return(cmd_id, raw)

    def read_raw(self, scpi: str) -> str:
        """逃生舱：发送任意 SCPI 查询(供调试)，界面常规功能禁止使用。"""
        return self._stack.request(scpi)

    def write_raw(self, scpi: str) -> None:
        self._stack.write(scpi)

    # ---------- 系统语义接口 ----------
    def idn(self) -> str:
        return self.get("idn")

    def reset(self) -> None:
        self.set("rst", None)

    def clear_status(self) -> None:
        self.set("cls", None)

    def local(self) -> None:
        self.set("sys_local", None)

    def remote(self) -> None:
        self.set("sys_remote", None)

    def read_errors(self) -> List[DeviceError]:
        """弹出错误队列直至为空。"""
        errs: List[DeviceError] = []
        for _ in range(32):  # 上限保护，防止模拟器/仪器异常时死循环
            raw = self._stack.request(self.table.build_query("sys_error"))
            err = parse_error_string(raw)
            if err is None:
                break
            errs.append(err)
            if err.code == -1:
                break   # 无法识别的响应（错位残片/回显）：不再当错误刷屏
        return errs

    def check_errors(self) -> None:
        """读错误队列，非空则抛 DeviceErrorList(人话提示)。"""
        errs = self.read_errors()
        if errs:
            raise DeviceErrorList(errs)

    # ---------- 高层语义封装(界面/脚本常用) ----------
    def apply_waveform(self, ch: int, wave: str, freq: Optional[float] = None,
                       ampl: Optional[float] = None, offset: Optional[float] = None) -> None:
        """一键设置波形+频率+幅值+偏移(等效手册 APPLy 快捷语义)。"""
        self.set("func", wave, ch)
        if freq is not None:
            self.set("freq", freq, ch)
        if ampl is not None:
            self.set("ampl", ampl, ch)
        if offset is not None:
            self.set("dcoffset", offset, ch)

    def set_output(self, ch: int, on: bool) -> None:
        self.set("output", on, ch)

    def read_channel_state(self, ch: int) -> Dict[str, Any]:
        """读取通道常用参数快照(界面刷新用，频率受串口吞吐约束)。"""
        keys = ["func", "freq", "ampl", "dcoffset", "output"]
        return {k: self.get(k, ch) for k in keys}

    def verify_command(self, cmd_id: str, ch: Optional[int], value: Any) -> Tuple[bool, str]:
        """自动化验证用：写入-回读比对，返回 (是否一致, 描述)。"""
        self.set(cmd_id, value, ch)
        readback = self.get(cmd_id, ch)
        expected = value
        if isinstance(readback, float) and isinstance(value, (int, float)):
            ok = abs(readback - float(value)) <= max(1e-9, abs(float(value)) * 1e-6)
        else:
            ok = str(readback).upper() == str(expected).upper()
        return ok, f"{cmd_id}[ch={ch}] set={value!r} readback={readback!r}"
