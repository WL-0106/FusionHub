# -*- coding: utf-8 -*-
"""
模拟从站（自测/回放工具）
========================
无真机也能开发回归。覆盖：
    正常帧：各语义命令的正确响应（*IDN?、测量类、配置类…）
    异常帧：
      - 错帧      乱字符/半截响应（考验上位机行重组与错帧自净）
      - 超时      命令不回（考验上位机重发上限与退出）
      - 从站断开  拔线/掉电（考验上位机断链处理，不卡死）
      - SCPI错误  返回 -105 等错误码（考验异常码人话映射）

用法：
    slave = MockDmmSlave(scenario="normal")
    transport = LoopbackTransport(slave.handle)
    client = ScpiClient(transport); ...
"""
from __future__ import annotations

import random
from typing import Dict

# 与命令表 key 对应的固定响应（正常帧）
_NORMAL_RESPONSES: Dict[str, str] = {
    "idn_query": "KEYSIGHT TECHNOLOGIES,34465A,MY12345678,1.2.3-1.0.3",
    "error_query": '0,"No error"',
    "self_test": "0",
    "opc_query": "1",
    "cal_query": "12",
    # 测量类：返回带物理量纲的合理数值
    "read_dc_volt": "1.23456789E+00",
    "read_ac_volt": "1.234567E-01",
    "read_dc_curr": "2.500000E-03",
    "read_ac_curr": "1.000000E-04",
    "read_res": "1.000000E+03",
    "read_fres": "9.999990E+02",
    "read_cap": "1.000000E-06",
    "read_freq": "5.000000E+01",
    "read_period": "2.000000E-02",
    "read_temp": "2.500000E+01",
    "read_cont": "1.000000E+00",
    "read_diode": "6.500000E-01",
    "read_trigger": "1.000000E+00",
    "fetch": "1.000000E+00",
    "stat_oper": "0",
    "stat_ques": "0",
    "sense_range_volt": "10",
    "sense_nplc": "1",
    "sense_zero_auto": "ON",
    "trig_source": "BUS",
    "trig_delay": "0",
    "trig_count": "1",
    "sample_count": "1",
    "init_cont": "OFF",
    "disp_state": "ON",
    "fmt_data": "ASCii",
    "route_scan": "OFF",
}

# 命令前缀 -> 语义键（解析上位机帧用）
_PREFIX_TO_KEY = {
    "*IDN?": "idn_query",
    "*TST?": "self_test",
    "*OPC?": "opc_query",
    "SYSTem:ERRor?": "error_query",
    "CALibration:COUNt?": "cal_query",
    "MEASure:VOLTage:DC?": "read_dc_volt",
    "MEASure:VOLTage:AC?": "read_ac_volt",
    "MEASure:CURRent:DC?": "read_dc_curr",
    "MEASure:CURRent:AC?": "read_ac_curr",
    "MEASure:RESistance?": "read_res",
    "MEASure:FRESistance?": "read_fres",
    "MEASure:CAPacitance?": "read_cap",
    "MEASure:FREQuency?": "read_freq",
    "MEASure:PERiod?": "read_period",
    "MEASure:TEMPerature?": "read_temp",
    "MEASure:CONTinuity?": "read_cont",
    "MEASure:DIODe?": "read_diode",
    "READ?": "read_trigger",
    "FETCh?": "fetch",
    "STATus:OPERation?": "stat_oper",
    "STATus:QUEStionable?": "stat_ques",
    "SENSe:VOLTage:DC:RANGe?": "sense_range_volt",
    "SENSe:VOLTage:DC:NPLCycles?": "sense_nplc",
    "SENSe:VOLTage:DC:ZERO:AUTO?": "sense_zero_auto",
    "TRIGger:SOURce?": "trig_source",
    "TRIGger:DELay?": "trig_delay",
    "TRIGger:COUNt?": "trig_count",
    "SAMPle:COUNt?": "sample_count",
    "INITiate:CONTinuous?": "init_cont",
    "DISPlay:STATe?": "disp_state",
    "FORMat:DATA?": "fmt_data",
    "ROUTe:SCAN:FUNC?": "route_scan",
}


class MockDmmSlave:
    """
    SCPI 模拟从站。

    scenario:
        normal      正常响应（默认）
        bad_frame   返回错帧/乱字符/半截响应
        timeout     不响应（触发上位机超时重发→退出）
        disconnect  抛链路断开异常（模拟拔线）
        scpi_error  返回 -105 参数越界错误码
        intermittent按概率混入超时/错帧（回归混合压力）
    """

    def __init__(self, scenario: str = "normal", error_rate: float = 0.3, seed: int = 42):
        self.scenario = scenario
        self.error_rate = error_rate
        self._rng = random.Random(seed)
        self.commands_received = 0
        self.responses_sent = 0
        self.log = []

    @staticmethod
    def _prefix_keys():
        """返回模拟从站可解析的查询帧集合（供回归完整性自检）。"""
        return set(_PREFIX_TO_KEY.keys())

    def handle(self, cmd: str) -> str:
        self.commands_received += 1
        self.log.append(cmd)
        sc = self.scenario

        if sc == "disconnect":
            from .transport import TransportError
            raise TransportError("模拟从站掉线")

        if sc == "timeout":
            return ""            # 不回：上位机超时重发

        if sc == "bad_frame":
            return self._bad_response(cmd)

        if sc == "scpi_error":
            self.responses_sent += 1
            return '-105,"Parameter out of range"\n'

        if sc == "intermittent" and self._rng.random() < self.error_rate:
            return self._rng.choice(["", self._bad_response(cmd)])

        return self._normal_response(cmd)

    def _normal_response(self, cmd: str) -> str:
        # 命令可能带参数（如 CONFigure / 设置类），去掉参数再匹配查询键
        head = cmd.split(" ", 1)[0] if not cmd.endswith("?") else cmd
        key = _PREFIX_TO_KEY.get(cmd) or _PREFIX_TO_KEY.get(head)
        # 设置类命令（无 ?）不产生响应正文，仅确认
        if not cmd.endswith("?"):
            self.responses_sent += 0
            return ""
        resp = _NORMAL_RESPONSES.get(key, "0")
        self.responses_sent += 1
        return resp + "\n"

    def _bad_response(self, cmd: str) -> str:
        """造错帧：乱字符 / 半截响应 / 缺终止符的垃圾数据。"""
        kind = self._rng.randint(0, 2)
        if kind == 0:
            return "\x00\x01GARBAGE!!\n"          # 乱字符+终止符
        if kind == 1:
            return "1.234"                          # 半截（无终止符，考验半包）
        return "\n\n###bad###\n"                    # 空行+垃圾
