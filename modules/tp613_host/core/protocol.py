# -*- coding: utf-8 -*-
"""TP613 三相智能电量仪 · Modbus-RTU 协议层（语义等价重建，依据原上位机字节码）。

物理层：RS485 串口 / TCP 网口透传
应用层：Modbus-RTU，FC03 读保持寄存器 / FC06 写单寄存器 / FC10 写多寄存器
CRC：标准 Modbus CRC-16（多项式 0xA001，初值 0xFFFF），低字节在前
数据：电量参数为 IEEE754 FLOAT（ABCD 大端，占 2 寄存器）
"""
from __future__ import annotations

import struct

# --------------------------------------------------------------------------- #
# 寄存器表（单一事实源，与原上位机逐地址一致）
# --------------------------------------------------------------------------- #
REG_UAB = 100        # 0x0064 线电压 Uab
REG_UBC = 102
REG_UCA = 104
REG_ULLAVG = 106     # 线电压平均
REG_UAN = 108        # 相电压 Uan
REG_UBN = 110
REG_UCN = 112
REG_ULNAVG = 114     # 相电压平均
REG_IA = 116         # 0x0074 电流 Ia
REG_IB = 118
REG_IC = 120
REG_IAVG = 122
REG_IN = 124         # 零序电流
REG_FREQ = 126       # 频率
REG_PF = 128         # 功率因数
REG_P = 130          # 有功功率
REG_Q = 132          # 无功功率
REG_S = 134          # 视在功率
REG_PFA = 136
REG_PFB = 138
REG_PFC = 140
REG_PA = 142
REG_PB = 144
REG_PC = 146
REG_QA = 148
REG_QB = 150
REG_QC = 152
REG_SA = 154
REG_SB = 156
REG_SC = 158
REG_EP = 160         # 0x00A0 有功电能
REG_EQ = 162         # 无功电能
REG_EPA = 164
REG_EPB = 166
REG_EPC = 168
REG_EQA = 170
REG_EQB = 172
REG_EQC = 174
REG_EP_FWD = 176     # 正向有功
REG_EP_REV = 178     # 反向有功
REG_EQ_FWD = 180
REG_EQ_REV = 182

REG_CLR_DEMAND = 60000   # 0xEA60 清空月最大需量（写 1）
REG_CLR_ENERGY = 60002   # 0xEA62 清空累积电能（写 1）
REG_4_20MA = 59998       # 0xEA5E 4-20mA 输出（FLOAT）

# 实时采集显示表：(键, 名称, 单位, 格式, 地址)
BASIC_PARAMS = [
    ('Uab', '线电压Uab', 'V', '.1f', 100), ('Ubc', '线电压Ubc', 'V', '.1f', 102),
    ('Uca', '线电压Uca', 'V', '.1f', 104), ('ULLAvg', '线电压平均', 'V', '.1f', 106),
    ('Uan', '相电压Uan', 'V', '.1f', 108), ('Ubn', '相电压Ubn', 'V', '.1f', 110),
    ('Ucn', '相电压Ucn', 'V', '.1f', 112), ('ULNAvg', '相电压平均', 'V', '.1f', 114),
    ('Ia', '电流Ia', 'A', '.3f', 116), ('Ib', '电流Ib', 'A', '.3f', 118),
    ('Ic', '电流Ic', 'A', '.3f', 120), ('In', '零序电流In', 'A', '.3f', 124),
    ('F', '频率', 'Hz', '.2f', 126), ('PF', '功率因数PF', '', '.3f', 128),
    ('P', '有功功率P', 'kW', '.3f', 130), ('Q', '无功功率Q', 'kvar', '.3f', 132),
    ('S', '视在功率S', 'kVA', '.3f', 134),
]
ENERGY_PARAMS = [
    ('Ep', '有功电能', 'kWh', '.2f', 160), ('Eq', '无功电能', 'kvarh', '.2f', 162),
    ('Ep_forward', '正向有功', 'kWh', '.2f', 176), ('Ep_reverse', '反向有功', 'kWh', '.2f', 178),
]

# 轮询块：一次读 60 寄存器（0x0064 起 30 个 FLOAT）+ 一次读 24 寄存器（0x00A0 起 12 个 FLOAT）
POLL_BLOCK_BASIC = (100, 60)
POLL_BLOCK_ENERGY = (160, 24)

# 波特率寄存器索引映射（设备存 0~5，界面上显示实际波特率）
BAUD_RATE_MAP = {0: 2400, 1: 4800, 2: 9600, 3: 19200, 4: 38400, 5: 115200}
BAUD_RATE_REVERSE = {v: k for k, v in BAUD_RATE_MAP.items()}

EXCEPTION_TEXT = {1: '非法功能码', 2: '非法数据地址', 3: '非法数据值', 4: '从机故障'}

# 参数设置表：(键, 名称, 默认地址, 类型)  —— 地址默认 0x0000(无效)，按设备手册修改
PARAM_DEFS = [
    ('device_addr', '设备地址', 0, 'uint'),
    ('baud_rate', '波特率', 0, 'combo'),
    ('net_mode', '接线方式', 0, 'combo'),
    ('pt_primary', 'PT一次侧', 0, 'uint'),
    ('pt_secondary', 'PT二次侧', 0, 'uint'),
    ('ct_primary', 'CT一次侧', 0, 'uint'),
    ('ct_secondary', 'CT二次侧', 0, 'uint'),
]

PARAM_NOTE = ('重要: 根据TP613文档, 设备地址/波特率/PT变比/CT变比/接线方式等系统参数\n'
              '      只能通过仪表面板菜单或TP助手软件设置, Modbus不提供读写接口。\n'
              '      下方寄存器地址默认为0x0000(无效), 请根据实际设备手册修改后使用。\n'
              '      以下Modbus可操作寄存器: 0xEA5E(4-20mA输出,FLOAT) '
              '0xEA60(清空需量) 0xEA62(清空电能)')


# --------------------------------------------------------------------------- #
# CRC-16 / Modbus
# --------------------------------------------------------------------------- #
def crc16_modbus(data: bytes) -> int:
    """标准 Modbus CRC-16（多项式 0xA001，初值 0xFFFF），返回 16 位整数（低字节先发）。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def frame_text(data: bytes) -> str:
    return ' '.join(f'{b:02X}' for b in data)


# --------------------------------------------------------------------------- #
# Modbus-RTU 报文构造 / 解析
# --------------------------------------------------------------------------- #
class ModbusRTU:
    """纯静态报文工具（与原上位机接口一致）。"""

    @staticmethod
    def build_read(slave_addr: int, start_addr: int, reg_count: int) -> bytes:
        pdu = struct.pack('>BBHH', slave_addr & 0xFF, 3,
                          start_addr & 0xFFFF, reg_count & 0xFFFF)
        return pdu + struct.pack('<H', crc16_modbus(pdu))

    @staticmethod
    def build_write_single(slave_addr: int, reg_addr: int, value: int) -> bytes:
        pdu = struct.pack('>BBHH', slave_addr & 0xFF, 6,
                          reg_addr & 0xFFFF, value & 0xFFFF)
        return pdu + struct.pack('<H', crc16_modbus(pdu))

    @staticmethod
    def build_write_multi(slave_addr: int, start_addr: int, values) -> bytes:
        values = [int(v) & 0xFFFF for v in values]
        pdu = struct.pack('>BBHHB', slave_addr & 0xFF, 16,
                          start_addr & 0xFFFF, len(values), len(values) * 2)
        for v in values:
            pdu += struct.pack('>H', v)
        return pdu + struct.pack('<H', crc16_modbus(pdu))

    @staticmethod
    def parse_read_response(response: bytes):
        """校验并解析 FC03 响应，返回寄存器值列表。失败抛 ValueError。"""
        if len(response) < 5:
            raise ValueError(f'响应帧过短({len(response)}字节)')
        if response[1] & 0x80:
            code = response[2] if len(response) > 2 else 0
            raise ValueError(f'异常响应: 错误码0x{code:02X}'
                             f'({EXCEPTION_TEXT.get(code, "未知")})')
        recv_crc = struct.unpack('<H', response[-2:])[0]
        calc_crc = crc16_modbus(response[:-2])
        if recv_crc != calc_crc:
            raise ValueError(f'CRC校验失败: 收到=0x{recv_crc:04X} 计算=0x{calc_crc:04X}')
        count = response[2]
        if len(response) != 3 + count + 2:
            raise ValueError(f'响应帧长度异常({len(response)}字节)')
        return list(struct.unpack('>' + 'H' * (count // 2), response[3:3 + count]))

    @staticmethod
    def regs_to_float(regs) -> float:
        """2 寄存器（ABCD 大端）→ IEEE754 float。"""
        raw = struct.pack('>HH', regs[0] & 0xFFFF, regs[1] & 0xFFFF)
        return struct.unpack('>f', raw)[0]

    @staticmethod
    def float_to_regs(val: float):
        """IEEE754 float → 2 寄存器（ABCD 大端）。"""
        raw = struct.pack('>f', float(val))
        return struct.unpack('>HH', raw)

    @staticmethod
    def parse_write_response(response: bytes):
        """校验 FC06/FC10 写响应。返回 (ok, 错误码)。"""
        if len(response) < 8:
            return False, 0
        if response[1] & 0x80:
            return False, (response[2] if len(response) > 2 else 0)
        recv_crc = struct.unpack('<H', response[-2:])[0]
        if recv_crc != crc16_modbus(response[:-2]):
            return False, 0
        return True, 0
