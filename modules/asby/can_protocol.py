# -*- coding: utf-8 -*-
"""
安世博源 UAB-1K030B-E CAN通信协议封装
版本 S5
"""

# 命令类型定义
CMD_VOUT = 0x00          # 模块输出电压 (R)
CMD_IOUT = 0x01          # 模块输出电流 (R)
CMD_VOUT_SET = 0x02      # 模块输出电压设定值 (R/W)
CMD_IOUT_LIMIT = 0x03    # 模块输出限流点设定值 (R/W)
CMD_POWER_CTRL = 0x04    # 模块开关机 (W) 0:开机 1:关机
CMD_SERIAL_NUMBER = 0x05 # 读取模块序列号 (R)
CMD_MODULE_STATUS = 0x08 # 模块状态标志位 (R)
CMD_VAC_SET = 0x09       # 模块AC电压设定值 模式2 (R/W)
CMD_FREQ_SET = 0x0A      # 模块AC频率设定值 模式2 (R/W)
CMD_P_ACTIVE_SET = 0x0B  # 模块有功功率设定值 模式3,4 (R/W)
CMD_P_REACTIVE_SET = 0x0C # 模块无功功率设定值 模式3 (R/W)
CMD_P_ACTIVE = 0x0D      # 模块有功功率 (R)
CMD_P_REACTIVE = 0x0E    # 模块无功功率 (R)
CMD_P_APPARENT = 0x0F    # 模块视在功率 (R)
CMD_AC_FREQ = 0x10       # AC频率 (R)
CMD_ALARM1 = 0x11        # 告警信息1 (R)
CMD_ALARM2 = 0x12        # 告警信息2 (R)
CMD_VAB = 0x14           # 线电压AB (R)
CMD_VBC = 0x15           # 线电压BC (R)
CMD_VCA = 0x16           # 线电压CA (R)
CMD_IA = 0x17            # A相电流 (R)
CMD_IB = 0x18            # B相电流 (R)
CMD_IC = 0x19            # C相电流 (R)
CMD_TIN = 0x1E           # 进风口温度 (R)
CMD_TPFC = 0x1F          # PFC温度 (R)
CMD_TDCDC1 = 0x20        # DCDC1温度 (R)
CMD_TDCDC2 = 0x21        # DCDC2温度 (R)
CMD_VA = 0x32            # 相电压AN (R)
CMD_VB = 0x33            # 相电压BN (R)
CMD_VC = 0x34            # 相电压CN (R)
CMD_VBAT = 0x3D          # 电池电压 (R)
CMD_GROUP_ADDR = 0x59    # 组地址 (R/W)
CMD_OUTPUT_MODE = 0x5F   # 模块运行模式 (R/W)
CMD_DCDC_SW_VER = 0x63   # DCDC软件版本 (R)
CMD_PFC_SW_VER = 0x64    # PFC软件版本 (R)
CMD_CURR_PWR_CAP = 0x68  # 读取模块输出电流和功率能力 (R)
CMD_FAN_SPEED1 = 0x78    # 风扇1转速 (R)
CMD_FAN_SPEED2 = 0x79    # 风扇2转速 (R)
CMD_FAN_SPEED3 = 0x7A    # 风扇3转速 (R)
CMD_TEMP_MARGIN = 0x7B   # 温度裕量 (R)
CMD_HW_VERSION = 0x7D    # 硬件版本号 (R)
CMD_FAN_RPM_PCT = 0x7E   # 最大风扇转速百分比 (R)
CMD_EXTENDED = 0x7F      # 拓展类型命令 (R/W)
# CMD_EXTENDED 子命令（Byte2-3）；通信超时超时会报面板 E15
EXT_SLEEP_TIME = 0
EXT_WORK_TIME = 1
EXT_COMM_TIMEOUT = 2     # 通信超时(秒)，0~120；默认约 10s

# 消息类型
MSG_SET = 0x00           # 设置模块参数
MSG_SET_RESP = 0x01      # 模块设置应答
MSG_READ = 0x02          # 读模块信息
MSG_READ_RESP = 0x03     # 模块读信息应答
MSG_SN_RESP = 0x04       # 模块读序列号应答

# 模块状态
STATUS_INIT = 0          # 初始化
STATUS_STANDBY = 1       # 待机
STATUS_READY = 2         # 准备完毕
STATUS_CHARGE_SOFT = 3   # 充电软启动
STATUS_CHARGE_NORMAL = 4 # 充电正常
STATUS_DISCHARGE_SOFT = 5 # 放电软启动
STATUS_DISCHARGE_NORMAL = 6 # 放电正常
STATUS_GRID_SOFT = 7     # 并网软启动
STATUS_GRID_NORMAL = 8   # 并网正常
STATUS_FAULT = 9         # 故障
STATUS_UPDATE = 10       # 更新
STATUS_TEST = 11         # 测试

STATUS_NAMES = {
    0: "初始化",
    1: "待机",
    2: "准备完毕",
    3: "充电软启动",
    4: "充电正常",
    5: "放电软启动",
    6: "放电正常",
    7: "并网软启动",
    8: "并网正常",
    9: "故障",
    10: "更新",
    11: "测试",
}

# 面板/手册故障代码 E02~E20（设备自身判定，与告警位互为参考）
# 依据对照上位机《UAB-1K030B-E》E 码表
FAULT_CODES = {
    2: ("E02", "环温过/欠温，内部器件过欠温"),
    3: ("E03", "AC 过/欠压"),
    4: ("E04", "AC 功率不平衡"),
    5: ("E05", "AC 电压不平衡"),
    6: ("E06", "DC 过压"),
    7: ("E07", "地址冲突"),
    8: ("E08", "风扇故障"),
    9: ("E09", "DC 不均流"),
    10: ("E10", "AC 过/欠频"),
    11: ("E11", "BUS 过/欠压"),
    12: ("E12", "保留"),
    13: ("E13", "DC 过流"),
    14: ("E14", "AC 过流"),
    15: ("E15", "通信故障（超时未收到上位机报文）"),
    16: ("E16", "PFC 启动失败"),
    17: ("E17", "DCDC 启动失败"),
    18: ("E18", "ADC 采样偏置校准失败"),
    19: ("E19", "保留"),
    20: ("E20", "放电电路故障"),
}

# 运行模式
MODE_CHARGE = 1          # 充电模式
MODE_OFF_GRID = 2        # 离网放电模式
MODE_GRID_TIE = 3        # 并网模式
MODE_CONST_VIP = 4       # 恒压恒流恒功率模式

MODE_NAMES = {
    1: "充电模式",
    2: "离网放电",
    3: "并网模式",
    4: "恒压恒流恒功率",
}

# 告警1定义
ALARM1_BITS = [
    (0, "GridOverVolt", "电网过压"),
    (1, "GridUnderVolt", "电网欠压"),
    (2, "SyncLost", "从机同步失败"),
    (3, "GridOverFreq", "电网过频"),
    (4, "GridUnderFreq", "电网欠频"),
    (5, "InvOverVolt", "AC过压"),
    (6, "InvUnderVolt", "AC欠压"),
    (7, "AcOverLoad", "AC过功率"),
    (8, "GridImbalance", "电网电压不平衡"),
    (11, "BusOverVolt", "PFC母线过压"),
    (12, "BusUnderVolt", "PFC母线欠压"),
    (13, "InrushOverCurr", "浪涌过流"),
    (14, "PowerImbalance", "三相功率不平衡"),
    (15, "TraOTP", "变压器过温"),
    (16, "DcBus1OverVolt", "直流母线1过压"),
    (17, "DcBus1UnderVolt", "直流母线1欠压"),
    (18, "DcBus2OverVolt", "直流母线2过压"),
    (19, "DcBus2UnderVolt", "直流母线2欠压"),
    (20, "VoutOverVolt", "直流输出过压"),
    (21, "VoutUnderVolt", "直流输出欠压"),
    (22, "BatOverVolt", "电池过压"),
    (23, "BatUnderVolt", "电池欠压"),
    (24, "DcChargeOverCurr", "直流输出过流"),
    (25, "DcDischargeOverCurr", "直流输入过流"),
    (26, "AcOverCurr", "交流侧过流"),
    (27, "Critical1OTP", "关键器件1温度过高"),
    (28, "Critical2OTP", "关键器件2温度过高"),
    (29, "Critical3OTP", "关键器件3温度过高"),
    (30, "AmbOTP", "环境温度过高"),
    (31, "AmbUTP", "环境温度过低"),
]

# 告警2定义
ALARM2_BITS = [
    (1, "ParallelComLoss", "并联通信丢失"),
    (2, "InternalComErr", "内部通信错误"),
    (3, "ExternalComLoss", "外部通信丢失"),
    (5, "HwDcdcOCP", "硬件DC过流"),
    (6, "HwPfcBusOVP", "硬件PFC母线过压"),
    (7, "HwDcdcBusOVP", "硬件DCDC母线过压"),
    (8, "HwDcOVP", "硬件输出过压"),
    (9, "HwPfcOCP", "硬件PFC过流"),
    (13, "PhyAddrConflict", "地址重复"),
    (14, "D2aBlackstartFail", "PFC模式2启动失败"),
    (15, "DcBusImbalance", "D2D母线不平衡"),
    (16, "AdcOffsetCaliFail", "DSP ADC偏移校准失败"),
    (17, "DischargeCircuitFail", "内部输出放电电路故障"),
    (18, "PfcPreloadFail", "PFC母线电压预充电失败"),
    (19, "PfcSoftstartFail", "PFC母线电压软启动失败"),
    (20, "DcdcPreloadFail", "DCDC母线电压预充电失败"),
    (21, "DcdcSoftstartFail", "输出电压软启动失败"),
    (24, "OringDiodeFail", "防反灌二极管故障"),
    (25, "ILCurrImbalance", "DCDC电感电流不平衡"),
    (29, "Fan1Fail", "风扇1故障"),
    (30, "Fan2Fail", "风扇2故障"),
    (31, "Fan3Fail", "风扇3故障"),
]


def build_can_id(protocol=1, monitor_addr=1, module_addr=0, serial_low=0):
    """
    构建29位扩展帧ID
    Protocol(4bit) + MonitorAddress(4bit) + ModuleAddress(7bit) + Reserved(5bit) + SerialNumberLowPart(9bit)
    """
    can_id = ((protocol & 0x0F) << 25) | \
             ((monitor_addr & 0x0F) << 21) | \
             ((module_addr & 0x7F) << 14) | \
             (serial_low & 0x1FF)
    return can_id


def parse_can_id(can_id):
    """解析29位扩展帧ID"""
    protocol = (can_id >> 25) & 0x0F
    monitor_addr = (can_id >> 21) & 0x0F
    module_addr = (can_id >> 14) & 0x7F
    serial_low = can_id & 0x1FF
    return protocol, monitor_addr, module_addr, serial_low


def build_data_frame(group_addr=1, msg_type=MSG_SET, cmd_type=0, data=0, cmd_sup=None):
    """
    构建8字节数据帧
    Byte0: GroupAddress(4bit) + MessageType(4bit)
    Byte1: CommandType
    Byte2-3: Reserved / CommandSup (for cmd_type=0x7F)
    Byte4-7: CommandData (32位整数，大端)
    """
    byte0 = ((group_addr & 0x0F) << 4) | (msg_type & 0x0F)
    byte1 = cmd_type & 0xFF
    
    if cmd_sup is not None and cmd_type == 0x7F:
        byte2 = (cmd_sup >> 8) & 0xFF
        byte3 = cmd_sup & 0xFF
    else:
        byte2 = 0
        byte3 = 0
    
    byte4 = (data >> 24) & 0xFF
    byte5 = (data >> 16) & 0xFF
    byte6 = (data >> 8) & 0xFF
    byte7 = data & 0xFF
    
    return bytes([byte0, byte1, byte2, byte3, byte4, byte5, byte6, byte7])


def parse_data_frame(data_bytes):
    """解析8字节数据帧"""
    if len(data_bytes) < 8:
        data_bytes = data_bytes + b'\x00' * (8 - len(data_bytes))
    
    byte0 = data_bytes[0]
    group_addr = (byte0 >> 4) & 0x0F
    msg_type = byte0 & 0x0F
    cmd_type = data_bytes[1]
    byte2 = data_bytes[2]
    byte3 = data_bytes[3]
    cmd_sup = (byte2 << 8) | byte3
    cmd_data = (data_bytes[4] << 24) | (data_bytes[5] << 16) | (data_bytes[6] << 8) | data_bytes[7]
    
    return {
        'group_addr': group_addr,
        'msg_type': msg_type,
        'cmd_type': cmd_type,
        'cmd_sup': cmd_sup,
        'cmd_data': cmd_data,
    }


def build_ut6502_frame(can_id, data_bytes, extended=True):
    """
    构建UT-6502固定格式帧 (13字节)
    Byte0: 帧信息 - 高4位帧类型(8=扩展,0=标准), 低4位数据长度
    Byte1-4: 帧ID (大端)
    Byte5-12: 数据 (8字节)
    """
    data_len = len(data_bytes)
    if data_len > 8:
        data_len = 8
        data_bytes = data_bytes[:8]
    elif data_len < 8:
        data_bytes = data_bytes + b'\x00' * (8 - data_len)
    
    frame_info = (0x80 if extended else 0x00) | (data_len & 0x0F)
    id_bytes = bytes([
        (can_id >> 24) & 0xFF,
        (can_id >> 16) & 0xFF,
        (can_id >> 8) & 0xFF,
        can_id & 0xFF,
    ])
    
    return bytes([frame_info]) + id_bytes + data_bytes


def parse_ut6502_frame(frame_bytes):
    """解析UT-6502固定格式帧"""
    if len(frame_bytes) < 13:
        return None
    
    frame_info = frame_bytes[0]
    extended = bool(frame_info & 0x80)
    data_len = frame_info & 0x0F
    
    can_id = (frame_bytes[1] << 24) | (frame_bytes[2] << 16) | (frame_bytes[3] << 8) | frame_bytes[4]
    data_bytes = frame_bytes[5:5+data_len]
    
    return {
        'extended': extended,
        'data_len': data_len,
        'can_id': can_id,
        'data': data_bytes,
    }


# 便捷函数：构建设置命令
def build_set_command(module_addr, cmd_type, data, group_addr=1, monitor_addr=1, cmd_sup=None):
    """构建设置命令帧（0x7F 可带子命令）"""
    can_id = build_can_id(protocol=1, monitor_addr=monitor_addr, module_addr=module_addr)
    data_frame = build_data_frame(group_addr=group_addr, msg_type=MSG_SET, cmd_type=cmd_type,
                                  data=data, cmd_sup=cmd_sup)
    return build_ut6502_frame(can_id, data_frame, extended=True)


# 便捷函数：构建读取命令
def build_read_command(module_addr, cmd_type, group_addr=1, monitor_addr=1):
    """构建读取命令帧"""
    can_id = build_can_id(protocol=1, monitor_addr=monitor_addr, module_addr=module_addr)
    data_frame = build_data_frame(group_addr=group_addr, msg_type=MSG_READ, cmd_type=cmd_type)
    return build_ut6502_frame(can_id, data_frame, extended=True)


# 便捷函数：开关机
def build_power_command(module_addr, power_on=True, group_addr=1, monitor_addr=1):
    """构建开关机命令 0=开机 1=关机"""
    data = 0 if power_on else 1
    return build_set_command(module_addr, CMD_POWER_CTRL, data, group_addr, monitor_addr)


# 便捷函数：设置电压
def build_voltage_set_command(module_addr, voltage_mv, group_addr=1, monitor_addr=1):
    """设置输出电压 (单位: mV)"""
    return build_set_command(module_addr, CMD_VOUT_SET, int(voltage_mv), group_addr, monitor_addr)


# 便捷函数：设置电流
def build_current_set_command(module_addr, current_ma, group_addr=1, monitor_addr=1):
    """设置输出限流 (单位: mA)"""
    return build_set_command(module_addr, CMD_IOUT_LIMIT, int(current_ma), group_addr, monitor_addr)


# 便捷函数：设置运行模式
def build_mode_set_command(module_addr, mode, group_addr=1, monitor_addr=1):
    """设置运行模式"""
    return build_set_command(module_addr, CMD_OUTPUT_MODE, int(mode), group_addr, monitor_addr)


# 便捷函数：设置有功功率
def build_power_set_command(module_addr, power_w, group_addr=1, monitor_addr=1):
    """设置有功功率 (单位: W)"""
    return build_set_command(module_addr, CMD_P_ACTIVE_SET, int(power_w), group_addr, monitor_addr)


def get_alarm_descriptions(alarm1_val, alarm2_val):
    """获取告警描述列表"""
    alarms = []
    for bit, name, desc in ALARM1_BITS:
        if alarm1_val & (1 << bit):
            alarms.append(desc)
    for bit, name, desc in ALARM2_BITS:
        if alarm2_val & (1 << bit):
            alarms.append(desc)
    return alarms


def fault_code_text(code):
    """E 码 → 文本，如 E15 通信故障"""
    info = FAULT_CODES.get(code)
    if not info:
        return f"E{code:02d}" if 1 <= code <= 99 else ""
    return f"{info[0]} {info[1]}"


def guess_fault_codes(alarm1, alarm2, status):
    """从告警位/状态推测可能的 E 码（面板码不在 CAN 告警位时给提示）"""
    hints = []
    mapping = [
        (1, 30, 2), (1, 31, 2),   # 环温
        (1, 0, 3), (1, 1, 3),     # AC 过/欠压
        (1, 14, 4),               # AC 功率不平衡
        (1, 8, 5),                # AC 电压不平衡
        (1, 20, 6),               # DC 过压
        (2, 13, 7),               # 地址冲突
        (2, 29, 8), (2, 30, 8), (2, 31, 8),  # 风扇
        (2, 15, 9), (2, 25, 9),   # 不均流
        (1, 3, 10), (1, 4, 10),   # AC 频
        (1, 11, 11), (1, 12, 11), # BUS
        (1, 24, 13),              # DC 过流
        (1, 26, 14),              # AC 过流
        (2, 19, 16), (2, 18, 16), # PFC 启动
        (2, 21, 17), (2, 20, 17), # DCDC 启动
        (2, 16, 18),              # ADC
        (2, 17, 20),              # 放电电路
    ]
    seen = set()
    for src, bit, code in mapping:
        val = alarm1 if src == 1 else alarm2
        if val & (1 << bit) and code not in seen:
            seen.add(code)
            hints.append(code)
    # 状态故障但告警位为 0：多半是面板 E 码（如 E15 通信超时）
    if status == 9 and not hints:
        hints.append(15)
    return hints
