# -*- coding: utf-8 -*-
"""设备高层封装：把「协议方言 + 传输层」组合成业务操作。

三种协议（SE / Ainuo ASCII / SCPI）的命令差异、应答语义差异全部收敛在
dialects.py，本模块只负责：发命令、按方言判定应答、把失败转成异常。
所有方法都是同步的，必须在工作线程里调用（不要碰 tkinter）。
"""

from . import protocol as P
from . import dialects as D


class AN96HC:
    def __init__(self, transport, term: bytes = b"\r\n", dialect=None):
        self.t = transport
        self.term = term
        self.d = dialect if dialect is not None else D.get("SE")
        self.logger = None      # 可选：由 UI 注入，收到每条收发报文时回调（线程安全由注入方保证）

    def set_dialect(self, dialect):
        self.d = dialect

    def set_logger(self, fn):
        self.logger = fn

    @property
    def protocol_name(self):
        return self.d.label

    # ---- 底层 ----
    def _exchange(self, text: str):
        """发一条命令并解析应答，返回 (status, payload)。不抛异常（除 IO 失败）。"""
        # SCPI 的设置命令仪器不应答（set_needs_reply=False，查询以 ? 结尾除外）：
        # 若按默认超时干等，每条命令都会卡满 2s——一排参数下发十几秒假死。
        # 无应答命令用短应答窗口快速返回（窗口内收到的错误帧/回显照常解析）；
        # SE/Ainuo 设置命令有 ACK/回显，仍走完整等待，不受影响。
        no_reply = (not self.d.set_needs_reply) and not text.strip().endswith("?")
        raw = self.t.exchange(text, term=self.term,
                              timeout=0.25 if no_reply else None)
        status, payload = self.d.classify(raw, text)
        # 回显兜底：SE/SCPI 下若只收到与命令完全相同的文本，说明仪器在回显
        # （RS485 半双工等），真实应答可能还在后面 —— 再读一次。
        # 注意 Ainuo 协议里「回显」本身就是设置成功的语义，classify 已处理成 ACK。
        if status == "DATA" and payload.strip().upper() == text.strip().upper():
            try:
                raw2 = self.t.read_reply(0.25 if no_reply else 1.5)
            except Exception:
                raw2 = b""
            if raw2:
                raw = raw2
                status, payload = self.d.classify(raw, text)
        if self.logger:
            try:
                self.logger({"cmd": text, "raw": raw,
                             "status": status, "payload": payload})
            except Exception:
                pass
        return status, payload

    def _cmd(self, text: str):
        status, payload = self._exchange(text)
        if status == "NAK":
            raise P.ProtocolError("设备返回 NAK（指令被拒）: %r" % text)
        if status == "ERROR":
            raise P.ProtocolError("设备报错: %s  （指令 %r）" % (payload, text))
        if status == "EMPTY":
            raise P.ProtocolError(
                "无有效响应（收到 0 字节）。当前选择的协议是「%s」，"
                "请确认仪器上的协议设置与之一致（点「仪器诊断」可自动判断）。" % self.d.label)
        if status == "ACK":
            return None
        return payload          # DATA

    def _seq(self, cmds):
        """按顺序发一组命令（如 ENTER-SET + FNN；ENTER-TEST + TEST）。"""
        res = None
        for c in cmds:
            res = self._cmd(c)
        return res

    def _need(self, cmd, what):
        if cmd is None:
            raise P.ProtocolError("当前协议（%s）不支持：%s" % (self.d.label, what))
        return cmd

    # ---- 档案管理 ----
    def file_new(self, num, name):
        self._seq(self.d.file_new(num, name))

    def file_load(self, num):
        self._seq(self.d.file_load(num))

    def file_save(self):
        self._seq(self.d.file_save())

    def file_saveas(self, num, name):
        fn = getattr(self.d, "file_saveas", None)
        if fn is None:
            raise P.ProtocolError("当前协议（%s）不支持另存为" % self.d.label)
        self._seq(fn(num, name))

    def file_delete(self, num=None):
        self._seq(self.d.file_delete(num))

    def file_current(self):
        return self._cmd(self._need(self.d.file_current_cmd, "查询当前档案")) or ""

    def step_count(self):
        return self._cmd(self._need(self.d.step_count_cmd, "查询测试步数")) or "0"

    def step_delete(self, num):
        self._cmd("SD %s" % num)

    # ---- 测试步 ----
    def add_step(self, mode, values=None):
        """新增测试步。Ainuo 下 values 为该步的全部参数（SET-XXX 需带参）。"""
        self._seq(self.d.add_step(mode, values))

    def delete_last_step(self):
        self._seq(self.d.delete_last_step())

    # ---- 参数 ----
    def set_param(self, mode, param: P.Param, value, step=None):
        self._seq(self.d.set_param(mode, param, value, step))

    def get_param(self, mode, param: P.Param, step=None):
        # 注意：不能写成 _cmd(_seq(...))——_seq 返回的是上一命令的应答文本，
        # 再套一层 _cmd 会把它当成新命令又发一遍（曾导致 SCPI 读回恒为空串）。
        raw = self._seq(self.d.get_param(mode, param, step)) or ""
        # 仪器回读要经方言层翻译（SCPI 是科学计数法 + 仪器单位），
        # 否则输入 1111 会显示成 +1.111000E+03。
        try:
            return self.d.parse_readback(mode, param, raw)
        except Exception:
            return raw

    # ---- 系统参数（仅 SE 有） ----
    def set_system(self, param: P.Param, value):
        if not self.d.supports_system_params():
            raise P.ProtocolError("当前协议（%s）不支持系统参数读写" % self.d.label)
        self._cmd(P.build_set(param, value))

    def get_system(self, param: P.Param):
        if not self.d.supports_system_params():
            raise P.ProtocolError("当前协议（%s）不支持系统参数读写" % self.d.label)
        return self._cmd(P.build_get(param)) or ""

    # ---- 自动归零（ACW/DCW/GND 的 Offset） ----
    def auto_zero(self):
        self._cmd("SAO")

    # ---- 测试控制 ----
    def start_test(self):
        self._seq(self.d.start())

    def stop_test(self):
        self._seq(self.d.stop())

    # ---- 结果 ----
    def query_test_data(self):
        """整组结果（SE/Ainuo: TD?；SCPI: SAFE:RES:ALL?）。"""
        return self._cmd(self.d.query_all()) or ""

    def query_step_result(self, num):
        return self._cmd(self.d.query_step(num)) or ""

    def parse_results(self, text):
        return self.d.parse_results(text)

    # ---- 识别（IEEE488.2；SE 协议下可能无响应） ----
    def identify(self):
        try:
            return self._cmd("*IDN?") or ""
        except Exception:
            return ""

    def probe(self, timeout: float = 1.0):
        """连接探测，返回 (alive, info)。

        *IDN? 优先；部分协议（SE）不支持 *IDN? 时用方言只读查询兜底
        （步数/当前档案/测试数据），任一收到应答即认为链路通。
        任何应答（含 NAK/ERROR）都算仪器在线——只有全部 0 字节才判未连接。
        这是「打开串口 ≠ 连接成功、收到应答才亮绿灯」的判定依据。
        """
        pings = ["*IDN?"]
        for c in (self.d.step_count_cmd, self.d.file_current_cmd,
                  self.d.query_all()):
            if c and c not in pings:
                pings.append(c)
        for cmd in pings:
            try:
                raw = self.t.exchange(cmd, term=self.term, timeout=timeout)
                status, payload = self.d.classify(raw, cmd)
            except Exception:
                continue
            if status != "EMPTY":
                return True, (payload if cmd == "*IDN?" else "")
        return False, ""

    def detect_step_mode(self, timeout: float = 0.4):
        """SE 专用：探测仪器「当前测试步」的类型。

        手册没有「查询当前步类型」命令，只能用各模式专有命令试探
        （真机对无效命令可能回 NAK 也可能静默，均按「无此命令」处理）：
          EHT? 仅 ACW 有（DCW/IR/GND 上限是 EH）
          EO?  仅 DCW/GND 有（IR 无归零设置）
          ERU? GND 无缓升时间（DCW 有；ACW 已被 EHT? 排除）
        每条试探用短超时（0.4s），静默拒收也绝不按默认超时干等。
        返回 'ACW'/'DCW'/'IR'/'GND'，无当前步/探测失败返回 None。
        """
        def _ask(cmd):
            full = "%s?" % cmd
            try:
                raw = self.t.exchange(full, term=self.term, timeout=timeout)
                status, payload = self.d.classify(raw, full)
            except Exception:
                return None
            if self.logger:
                try:
                    self.logger({"cmd": full, "raw": raw,
                                 "status": status, "payload": payload})
                except Exception:
                    pass
            return payload if status == "DATA" else None

        if _ask("EHT") is not None:
            return "ACW"
        if _ask("EO") is not None:
            return "DCW" if _ask("ERU") is not None else "GND"
        if _ask("ERU") is not None:   # EHT?/EO? 均无 → 排除 ACW/DCW/GND
            return "IR"
        return None
