# -*- coding: utf-8 -*-
"""中创智合采集卡系列寄存器表配置。

全系列共用同一套 Modbus 协议（见 modbus.py），差异仅在「寄存器映射」。
本模块把每个系列/型号抽象成一份配置，新增型号 = 加一条配置，协议栈和界面都不用动。

已收录（依据官网公开说明书）：
  - temperature（温度系列）：ZH-T16PT（热电阻）/ ZH-T16TC（热电偶）/ ZH-T08NTC
      数据寄存器 0000~000F（16路），有符号16位，实际值 = 原始值 ÷ 10（单位 0.1℃）
      配置寄存器：0050H地址 / 0051H波特率 / 0052H校验 / 0081H采样速率 / 01FAH协议切换
  - voltage / current（电压电流系列）：ZH-4404#D / ZH-4424# 等
      数据寄存器 0000 起（多路），无符号16位，实际值 = 原始值 × 量程 ÷ 10000
      高精度型还有 32 位（÷100000）与浮点寄存器
      配置寄存器：0050H地址 / 0051H波特率 / 0052H校验 / 0060H协议切换 / 0053H量程系数
"""


class Series:
    """一个系列的配置描述。"""

    def __init__(self, key, name, channel_count, dtype, scale_mode,
                 data_start=0, unit="", range_hint="",
                 addr_reg=None, baud_reg=None, parity_reg=None,
                 proto_reg=None, proto_kind="t16pt",
                 proto_options=None, regs=None,
                 desc=""):
        self.key = key
        self.name = name
        self.channel_count = channel_count      # 通道数
        self.dtype = dtype                      # 'i16' / 'u16' / 'u32' / 'f32'
        self.scale_mode = scale_mode            # 'div10' / 'range10000' / 'range100000'
        self.data_start = data_start            # 数据起始寄存器地址
        self.unit = unit                        # 单位显示（℃/V/A）
        self.range_hint = range_hint            # 量程提示（用于 UI）
        self.addr_reg = addr_reg
        self.baud_reg = baud_reg
        self.parity_reg = parity_reg
        self.proto_reg = proto_reg
        self.proto_kind = proto_kind
        # 协议切换寄存器取值表 [(label, 寄存器值, 说明)]
        self.proto_options = proto_options or []
        # 系列特有寄存器（不含 base 四项），后面 _patch_regs 会合并成完整 regs
        self._extra_regs = regs or []
        # 关键寄存器清单 [(地址, 名称, 取值/说明)]，用于界面参考面板
        self.regs = []
        self.desc = desc


# 波特率代码（各系列通用，0051H/005AH 寄存器值 → bps）
BAUD_CODES = {
    0x00: 115200, 0x01: 9600, 0x02: 19200, 0x03: 38400,
    0x04: 2400, 0x05: 4800, 0x06: 9600, 0x07: 19200,
    0x08: 38400, 0x09: 57600, 0x0A: 115200,
}
BAUD_TO_CODE = {v: k for k, v in sorted(BAUD_CODES.items())}

# 校验代码（0052H 寄存器值 → (parity, stopbits)）
PARITY_CODES = {
    0: ("N", 1), 1: ("O", 1), 2: ("E", 1),
    3: ("N", 2), 4: ("O", 2), 5: ("E", 2),
}
PARITY_TO_CODE = {v: k for k, v in PARITY_CODES.items()}


def _base_regs(series, proto_name):
    """构造一个系列共用的关键寄存器参考清单（不含数据区）。"""
    regs = []
    if series.addr_reg is not None:
        regs.append((series.addr_reg, "从站地址", "本机 Modbus 地址，1~247"))
    if series.baud_reg is not None:
        regs.append((series.baud_reg, "波特率",
                     "00=115200 01=9600 02=19200 03=38400 04=2400 "
                     "05=4800 09=57600 0A=115200"))
    if series.parity_reg is not None:
        regs.append((series.parity_reg, "校验/停止位",
                     "0=N,1 1=O,1 2=E,1 3=N,2 4=O,2 5=E,2"))
    if series.proto_reg is not None:
        regs.append((series.proto_reg, proto_name, "见协议切换面板"))
    return regs


SERIES = {
    # ---- 温度系列 ----
    "temperature": Series(
        key="temperature",
        name="温度系列（热电偶/热电阻/NTC）",
        channel_count=16,
        dtype="i16",
        scale_mode="div10",
        data_start=0,
        unit="℃",
        range_hint="分辨率 0.1℃，原始值 ÷ 10",
        addr_reg=0x0050, baud_reg=0x0051, parity_reg=0x0052,
        proto_reg=0x01FA, proto_kind="t16pt",
        proto_options=[
            ("RTU（RS485 口）", 0x0, "RS485 口 = Modbus-RTU"),
            ("TCP（RS485 口）", 0x1, "RS485 口 = Modbus-TCP"),
            ("RTU（以太网口）", 0x0, "以太网口 = Modbus-RTU"),
            ("TCP（以太网口）", 0x1, "以太网口 = Modbus-TCP"),
        ],
        regs=[
            (0x0081, "采样速率", "数据刷新速率设置"),
            (0x0200, "传感器型号", "热电阻/热电偶类型设置（0200H 起）"),
            (0x02C0, "温度补偿", "温度补偿值（02C0H 起，0.1℃）"),
            (0x8000, "写保护", "写保护锁，非 0 锁定配置"),
        ],
        desc="ZH-T16PT / ZH-T16TC / ZH-T08NTC；0x7FFF=断线/过温，0x8000=短路/超低温",
    ),
    # ---- 电压系列（直流） ----
    "voltage": Series(
        key="voltage",
        name="电压系列（直流/交流）",
        channel_count=4,
        dtype="u16",
        scale_mode="range10000",
        data_start=0,
        unit="V",
        range_hint="额定输入输出 10000，实际值 = 原始值 × 量程 ÷ 10000",
        addr_reg=0x0050, baud_reg=0x0051, parity_reg=0x0052,
        proto_reg=0x0060, proto_kind="t4404",
        proto_options=[
            ("RTU 与 TCP 兼容（默认）", 0x00, "Modbus-RTU 与 TCP 兼容"),
            ("指定 Modbus-TCP", 0x01, "仅 Modbus-TCP 协议"),
        ],
        regs=[
            (0x0053, "量程系数", "量程换算系数（见铭牌量程）"),
            (0x005D, "软件滤波", "1 开启滤波（数据更新慢 10 倍），0 关闭"),
        ],
        desc="ZH-44041D / ZH-44241；量程见铭牌（75mV~1000V）",
    ),
    # ---- 电流系列（直流） ----
    "current": Series(
        key="current",
        name="电流系列（直流/交流）",
        channel_count=4,
        dtype="u16",
        scale_mode="range10000",
        data_start=0,
        unit="A",
        range_hint="额定输入输出 10000，实际值 = 原始值 × 量程 ÷ 10000",
        addr_reg=0x0050, baud_reg=0x0051, parity_reg=0x0052,
        proto_reg=0x0060, proto_kind="t4404",
        proto_options=[
            ("RTU 与 TCP 兼容（默认）", 0x00, "Modbus-RTU 与 TCP 兼容"),
            ("指定 Modbus-TCP", 0x01, "仅 Modbus-TCP 协议"),
        ],
        regs=[
            (0x0053, "量程系数", "量程换算系数（见铭牌量程）"),
            (0x005D, "软件滤波", "1 开启滤波（数据更新慢 10 倍），0 关闭"),
        ],
        desc="ZH-44042D / ZH-44242；量程见铭牌（5mA~10A）",
    ),
    # ---- 电压电流组合（多路，可扩展） ----
    "mixed": Series(
        key="mixed",
        name="电压电流组合（多路采集）",
        channel_count=24,
        dtype="u16",
        scale_mode="range10000",
        data_start=0,
        unit="",
        range_hint="24 路真有效值，实际值 = 原始值 × 量程 ÷ 10000",
        addr_reg=0x0050, baud_reg=0x0051, parity_reg=0x0052,
        proto_reg=0x0060, proto_kind="t4404",
        proto_options=[
            ("RTU 与 TCP 兼容（默认）", 0x00, "Modbus-RTU 与 TCP 兼容"),
            ("指定 Modbus-TCP", 0x01, "仅 Modbus-TCP 协议"),
        ],
        regs=[
            (0x0053, "量程系数", "量程换算系数（见铭牌量程）"),
            (0x005D, "软件滤波", "1 开启滤波（数据更新慢 10 倍），0 关闭"),
        ],
        desc="ZH-4124# 24 路全隔离交直流采集",
    ),
}


def _patch_regs():
    """回填各系列完整关键寄存器（base 四项 + 系列特有项）。"""
    for key, s in SERIES.items():
        proto_name = "通讯协议" if s.proto_kind == "t16pt" else "协议转换"
        s.regs = _base_regs(s, proto_name) + s._extra_regs


_patch_regs()


def decode_value(raw, series, range_value=1.0):
    """把寄存器原始值换算成实际物理值。

    raw: 已合并成整数的原始值（i16 已做符号扩展，u32/f32 已拼好）
    range_value: 量程值（range10000 / range100000 模式需要）
    """
    m = series.scale_mode
    if m == "div10":
        # 有符号 16 位 ÷ 10；0x7FFF / 0x8000 特殊
        return raw / 10.0
    if m == "range10000":
        return raw * range_value / 10000.0
    if m == "range100000":
        return raw * range_value / 100000.0
    return float(raw)


def words_to_int(words, dtype):
    """把 16 位字列表合并成整数（按 dtype 处理符号/字节序，大端）。"""
    if dtype == "i16":
        v = words[0]
        if v & 0x8000:
            v -= 0x10000
        return v
    if dtype == "u16":
        return words[0]
    if dtype == "u32":
        return (words[0] << 16) | words[1]
    raise ValueError("不支持 dtype: %s" % dtype)
