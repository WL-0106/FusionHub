# -*- coding: utf-8 -*-
"""
禾享源 HBTW 模块 CAN 通信协议封装
适用模块: HBTW60160 / HBTW80100 / HBTW12075 / HBTW20070
协议版本: 模块通信协议 V1.2-20250607

通信物理层: CAN 2.0B 标准扩展帧, 波特率 1 Mbps
字节序    : 多字节数据一律小端 (低字节在前)
数值系数  : 电压/电流显示 x10; 设定电压按文档示例 x100 (50V=5000), 可切换 x10; 设定电流 x10
"""

MIN_ID = 1
MAX_ID = 63              # 模块地址范围 0x01 ~ 0x3F
BROADCAST_ID = 0x7F

# ---------------- 帧 ID 定义 ----------------
# 模块号在帧 ID 中表示为 0xC0|ID: C1=1号, C2=2号, ..., FF=0x3F号
LIFE_FRAME_ID = 0x0850FF11          # 生命帧(广播), 数据首字节递增, 间隔1000ms
BROADCAST_CMD_ID = 0x08E07F11       # 广播命令帧 ID (0x7F 为广播地址)


def cmd_id(module_id):
    """单模块命令帧 ID: 1# -> 0x08E0C111, 0x10# -> 0x08E0D011, 0x3F# -> 0x08E0FF11"""
    return 0x08E00011 | ((0xC0 | (module_id & 0x3F)) << 8)


def is_cmd_id(can_id):
    return (can_id & 0xFF00FFFF) == 0x08E00011


def cmd_module(can_id):
    return (can_id >> 8) & 0x3F


# 模块上传状态帧高 24 位(低 8 位为 0xC0|模块ID)
SID_VOLTAGE = 0x18C1FF00   # 数据帧: b4:b5=直流电压x10, b6:b7=母线电压x10
SID_CURRENT = 0x18C2FF00   # 数据帧: b0:b1=直流电流x10, 有符号(放电为负)
SID_MODE = 0x18C4FF00      # 数据帧: b0:b1, 0x0001=并机模式, 0x0000=单机模式
SID_FAULT = 0x10B0FF00     # 故障帧: b0/b1/b2 位定义见 FAULT_BITS

# 命令首字节
CMD_OUTPUT = 0xD8          # 输出控制: b2=模式 01恒压限流 02恒流 00停机
CMD_SET_ID = 0xD9          # 更改 ID 号: b2=新 ID
CMD_POWER_LIMIT = 0xDD     # 限功率设定(仅 80100 支持): b2:b3=功率值
CMD_CLEAR_FAULT = 0xE0     # 故障清除(单机): b2=01
CMD_CAL_DC_V = 0xD4        # 直流电压校准, 标幺值 4096
CMD_CAL_DC_I = 0xD5        # 直流电流校准, 标幺值 4096
CMD_CAL_BUS_V = 0xD3       # 母线电压校准, 标幺值 4096
BCAST_STOP = 0x0E          # 并机停机命令(广播): b2=01
BCAST_CLEAR = 0x0F         # 并机故障清除(广播): b2=01

MODE_CV_CL = 0x01          # 恒压限流
MODE_CC = 0x02             # 恒流
MODE_STOP = 0x00           # 停机

# 故障位映射: {字节下标: [(bit, 名称), ...]}
# 依据协议 V1.2 故障举例逐条验证: biteN 对应数据第 N 字节(0起)
FAULT_BITS = {
    0: [(5, "母线过压故障"), (6, "直流输出过压快检")],
    1: [(3, "母线过压快检"), (4, "母线欠压快检"), (5, "过温故障")],
    2: [(2, "直流输出电压异常"), (4, "过流故障"), (6, "母线欠压")],
}


def le16(data, off):
    return data[off] | (data[off + 1] << 8)


def sle16(data, off):
    v = le16(data, off)
    return v - 0x10000 if v >= 0x8000 else v


def decode_faults(data):
    """解析故障帧数据 -> 故障名列表"""
    faults = []
    for idx, bits in FAULT_BITS.items():
        if idx < len(data):
            for bit, name in bits:
                if data[idx] & (1 << bit):
                    faults.append(name)
    return faults


# ---------------- 发送帧构造 (返回 can_id, 8字节数据) ----------------

def build_life_frame(seq):
    """生命帧: 广播, 首字节递增, 用于触发模块回读状态(含模块ID)"""
    return LIFE_FRAME_ID, bytes([seq & 0xFF]) + b"\x00" * 7


def build_cv_cl(volt, curr, v_scale=100):
    """恒压限流设定 = 开机指令. volt:V curr:A; v_scale=100(文档:50V=5000)或10"""
    v = int(round(volt * v_scale))
    i = int(round(curr * 10))
    if not 0 <= v <= 0xFFFF:
        raise ValueError("电压值 %gV 超出系数 x%d 下 16 位范围(最大 %gV)" % (volt, v_scale, 0xFFFF / v_scale))
    if not 0 <= i <= 0xFFFF:
        raise ValueError("电流值 %gA 超出范围(最大 6553.5A)" % curr)
    data = bytes([CMD_OUTPUT, 0x00, MODE_CV_CL, 0x00,
                  v & 0xFF, v >> 8, i & 0xFF, i >> 8])
    return BROADCAST_CMD_ID, data  # 调用方按目标模块替换 can_id


def build_cc(curr):
    """恒流模式设定, curr<0 为放电(补码)"""
    i = int(round(curr * 10)) & 0xFFFF
    return BROADCAST_CMD_ID, bytes([CMD_OUTPUT, 0x00, MODE_CC, 0x00,
                                    i & 0xFF, i >> 8, 0x00, 0x00])


def build_stop():
    """单机停机命令: D8 00 00 00 00 00 00 00"""
    return BROADCAST_CMD_ID, bytes([CMD_OUTPUT, 0x00, MODE_STOP]) + b"\x00" * 5


def build_broadcast_stop():
    """并机停机命令(广播): 0E 00 01 00 00 00 00 00 -> 0x08E07F11"""
    return BROADCAST_CMD_ID, bytes([BCAST_STOP, 0x00, 0x01]) + b"\x00" * 5


def build_clear_fault():
    """单机故障清除: e0 00 01 00 00 00 00 00"""
    return BROADCAST_CMD_ID, bytes([CMD_CLEAR_FAULT, 0x00, 0x01]) + b"\x00" * 5


def build_broadcast_clear_fault():
    """并机故障清除(广播): 0F 00 01 00 00 00 00 00 -> 0x08E07F11"""
    return BROADCAST_CMD_ID, bytes([BCAST_CLEAR, 0x00, 0x01]) + b"\x00" * 5


def build_set_id(new_id):
    """更改 ID 号: D9 00 <新ID> 00 00 00 00 00 (发送至模块当前 ID)"""
    if not MIN_ID <= new_id <= MAX_ID:
        raise ValueError("新 ID 必须在 0x01~0x3F 范围内")
    return BROADCAST_CMD_ID, bytes([CMD_SET_ID, 0x00, new_id]) + b"\x00" * 5


def build_power_limit(watt):
    """限功率设定(仅 HBTW80100 支持): DD 00 <P LE16> 00..."""
    w = int(round(watt))
    if not 0 <= w <= 0xFFFF:
        raise ValueError("功率值超出 16 位范围")
    return BROADCAST_CMD_ID, bytes([CMD_POWER_LIMIT, 0x00,
                                    w & 0xFF, w >> 8]) + b"\x00" * 4


def build_calibration(cmd, value):
    """校准命令(标幺值 4096): D3母线电压 / D4直流电压 / D5直流电流"""
    v = int(round(value))
    if not 0 <= v <= 0xFFFF:
        raise ValueError("校准值超出 16 位范围")
    return BROADCAST_CMD_ID, bytes([cmd, 0x00, v & 0xFF, v >> 8]) + b"\x00" * 4


# ---------------- 接收帧解析 ----------------

def parse_status(can_id, data):
    """
    解析模块上传帧.
    返回 (module_id, kind, info_dict) 或 None(非状态帧)
      kind: 'voltage' / 'current' / 'mode' / 'fault'
    """
    if len(data) < 8:
        return None
    raw = can_id & 0xFF
    if not 0xC1 <= raw <= 0xFF:            # 低字节须为 0xC0|ID
        return None
    module_id = raw & 0x3F
    if not MIN_ID <= module_id <= MAX_ID:
        return None
    base = can_id & 0xFFFFFF00
    if base == SID_VOLTAGE:
        return module_id, "voltage", {
            "v_dc": le16(data, 4) / 10.0,     # 直流输出电压 V
            "v_bus": le16(data, 6) / 10.0,    # 母线电压 V
        }
    if base == SID_CURRENT:
        return module_id, "current", {
            "i_dc": sle16(data, 0) / 10.0,    # 直流电流 A, 放电为负
        }
    if base == SID_MODE:
        return module_id, "mode", {
            "parallel": le16(data, 0) == 0x0001,   # True=并机 False=单机
        }
    if base == SID_FAULT:
        return module_id, "fault", {
            "faults": decode_faults(data),
            "raw": data[:3].hex(" ").upper(),
        }
    return None
