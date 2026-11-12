"""
EN+ 充电模块 CAN 通信协议 V2.7.1
深圳驿普乐氏科技有限公司

CAN2.0B 扩展帧, 29位ID, 波特率 125kbps

ID 结构 (29 bit):
  Bit 28:      通讯错误标志 (1 bit)
  Bit 27-22:   设备号 (6 bit)  - 0x0A: 监控单元->模块, 0x0B: 监控单元->组
  Bit 21-16:   命令号 (6 bit)
  Bit 15-8:    目的地址 (8 bit) - 模块: 0x01~0x3F(0x3F=广播), 监控单元: 0xF0~0xF8
  Bit 7-0:     源地址 (8 bit)   - 监控单元默认 0xF0

CAN_ID = (error << 28) | (device << 22) | (cmd << 16) | (dest << 8) | src
"""

import struct

# ============================================================
# 常量定义
# ============================================================

# 设备号
DEV_MODULE_TO_MODULE = 0x01  # 模块间通讯
DEV_MONITOR_TO_MODULE = 0x0A  # 监控单元 -> 某个模块
DEV_MONITOR_TO_GROUP = 0x0B  # 监控单元 -> 某组模块

# 地址
ADDR_BROADCAST = 0x3F  # 广播地址(所有模块)
ADDR_MONITOR = 0xF0  # 监控单元地址(默认)

# 通讯错误码
ERROR_CODES = {
    0x00: "无错误",
    0x01: "地址无效",
    0x02: "命令号异常",
    0x03: "数据信息异常",
    0x04: "EEPROM芯片忙,无法写入数据",
    0x05: "地址分配过程结束",
    0x06: "模块尚未完成初始化",
    0x07: "启动过程中",
}

# 命令号
CMD_MODULE_SN = 0x00       # 模块广播序列号(上位机不可用)
CMD_READ_SYS_VI = 0x01     # 读取: 输出电压, 总电流 (IEEE754浮点)
CMD_READ_MODULE_NUM = 0x02  # 读取: 模块数量, 组号
CMD_READ_VI = 0x03          # 读取: 输出电压电流实际值 (IEEE754浮点)
CMD_READ_FAN_TEMP_ERR = 0x04  # 读取: 风扇转速, 温度, 错误码
CMD_READ_TEMP_SERIES = 0x05  # 读取: 温度(系列)
CMD_READ_INPUT_VI = 0x06    # 读取: 输入电压, 模块状态
CMD_PARALLEL_BROADCAST = 0x07  # 并机广播报文(上位机不可用)
CMD_READ_RUNTIME = 0x08     # 读取: 运行时间
CMD_READ_LLC_PFC = 0x09     # 读取: LLC和PFC数据
CMD_SET_WALKIN = 0x13       # 设置: walkin功能使能/禁止
CMD_CTRL_LED = 0x14         # 控制: 绿色LED灯闪烁
CMD_SET_GROUP = 0x16        # 设置: 模块分组
CMD_CTRL_SLEEP = 0x19       # 控制: 进入/退出休眠
CMD_CTRL_POWER = 0x1A       # 控制: 开机/关机
CMD_SET_VI = 0x1C           # 设置: 输出电压和电流
CMD_SET_ADDR_MODE = 0x1F    # 设置: 模块地址模式
CMD_REASSIGN_ADDR = 0x20    # 总线所有模块重新分配地址
CMD_SET_PARALLEL_MODE = 0x21  # 设置: 智能并机模式
CMD_SET_CAN_BROADCAST = 0x22  # CAN广播报文使能/禁止
CMD_SET_VOLTAGE_MODE = 0x23  # 设置: 高低压模式
CMD_SET_MPPT = 0x24          # 设置: MPPT曲线
CMD_SET_CURRENT_SHARE = 0x25  # 设置: 并联均流功能
CMD_SET_VOLTAGE_SHARE = 0x26  # 设置: 串联均压功能
CMD_SET_AUTO_SWITCH = 0x27   # 设置: 高低档自动切换
CMD_SET_VOLTAGE_RATE = 0x28  # 设置: 电压变化率
CMD_SET_CURRENT_RATE = 0x29  # 设置: 电流变化率
CMD_SET_AGING_MODE = 0x2A   # 设置: 老化模式
CMD_READ_INFO_1 = 0x30      # 读取: 模块固有信息1
CMD_READ_INFO_2 = 0x31      # 读取: 模块固有信息2
CMD_READ_INFO_3 = 0x32      # 读取: 模块固有信息3 (序列号高)
CMD_READ_INFO_4 = 0x33      # 读取: 模块固有信息4 (序列号低)
CMD_READ_INFO_5 = 0x34      # 读取: 模块固有信息5 (ModelName高)
CMD_READ_INFO_6 = 0x35      # 读取: 模块固有信息6 (ModelName低)
CMD_READ_INFO_7 = 0x36      # 读取: 模块固有信息7 (制造商ID高)
CMD_READ_INFO_8 = 0x37      # 读取: 模块固有信息8 (制造商ID低)
CMD_READ_INFO_9 = 0x38      # 读取: 模块固有信息9 (软件版本号高)
CMD_READ_INFO_A = 0x39      # 读取: 模块固有信息A (软件版本号低)

# 模块状态 (State1)
MODULE_STATES = {
    0: "等待开机 (WaitState)",
    1: "自检中 (CheckState)",
    2: "软启动 (SoftStartState)",
    3: "正常输出 (NormalState)",
    4: "故障状态 (FaultState)",
}

# 机型定义
MODEL_TYPES = {
    0: "DCM50050",
    1: "DCM75034",
    2: "DCM50043",
    3: "DCM100025",
    4: "HDCM50034",
    10: "DCM1000100",
    11: "DCM100084",
    12: "DCM1000100E",
    13: "DCM150038",
}

# 故障码定义 (64位, Bit0~Bit63)
FAULT_CODES = {
    0:  "PFC控制板温度过高错误",
    1:  "PFC散热器温度过高错误",
    2:  "bus硬件过压错误",
    3:  "bus软件过压错误",
    4:  "bus硬件连续过压故障",
    5:  "bus软件连续过压故障",
    6:  "Iac硬件连续过流故障",
    7:  "Iac软件连续过流故障",
    8:  "市电过欠频错误",
    9:  "市电过欠压错误",
    10: "保留",
    11: "Iac软件过流错误",
    12: "Iac硬件过流错误",
    13: "保留",
    14: "保留",
    15: "保留",
    16: "风扇错误",
    17: "地址异常错误",
    18: "CAN通讯中断错误",
    19: "软硬件版本不匹配故障",
    20: "LLC eeprom读写错误",
    21: "LLC变压器温度过高错误",
    22: "LLC进风口温度过高错误",
    23: "LLC散热器温度过高错误",
    24: "保留",
    25: "输出电流Idc硬件连续过流故障",
    26: "输出电流Idc软件连续过流故障",
    27: "输出电压Udc硬件连续过压故障",
    28: "输出电压Udc软件连续过压故障",
    29: "谐振槽电流硬件连续过流故障",
    30: "谐振槽电流软件连续过流故障",
    31: "输出短路或输出低压错误",
    32: "谐振槽电流软件过流错误",
    33: "谐振槽电流硬件过流错误",
    34: "输出电压Udc软件过压错误",
    35: "输出电压Udc硬件过压错误",
    36: "输出电流Idc软件过流错误",
    37: "输出电流Idc硬件过流错误",
    38: "内部串口通讯中断错误",
    39: "保留",
    40: "LLC变压器过温降载告警",
    41: "LLC进风口过温降载告警",
    42: "LLC散热器过温降载告警",
    43: "PFC控制板过温降载告警",
    44: "PFC散热器过温降载告警",
    45: "CAN通讯时间间隔太大告警",
    46: "放电失败告警",
    47: "保留",
}


# ============================================================
# CAN ID 编解码
# ============================================================

def build_can_id(cmd, dest, src=ADDR_MONITOR, device=DEV_MONITOR_TO_MODULE, error=0):
    """
    构建 29 位 CAN ID
    :param cmd: 命令号 (6 bit)
    :param dest: 目的地址 (8 bit)
    :param src: 源地址 (8 bit), 默认 0xF0 (监控单元)
    :param device: 设备号 (6 bit), 默认 0x0A
    :param error: 错误标志 (1 bit), 默认 0
    :return: 29位 CAN ID 整数
    """
    can_id = ((error & 0x01) << 28) | \
             ((device & 0x3F) << 22) | \
             ((cmd & 0x3F) << 16) | \
             ((dest & 0xFF) << 8) | \
             (src & 0xFF)
    return can_id


def parse_can_id(can_id):
    """
    解析 29 位 CAN ID
    :param can_id: 29位 CAN ID 整数
    :return: dict {error, device, cmd, dest, src}
    """
    return {
        'error': (can_id >> 28) & 0x01,
        'device': (can_id >> 22) & 0x3F,
        'cmd': (can_id >> 16) & 0x3F,
        'dest': (can_id >> 8) & 0xFF,
        'src': can_id & 0xFF,
    }


# ============================================================
# 命令构造函数 — 返回 (can_id, data[8])
# ============================================================

def cmd_read_sys_vi(dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x01 读取系统输出电压和总电流 (IEEE754浮点)"""
    can_id = build_can_id(CMD_READ_SYS_VI, dest, src)
    return can_id, bytes(8)


def cmd_read_module_num(dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x02 读取模块数量"""
    can_id = build_can_id(CMD_READ_MODULE_NUM, dest, src)
    return can_id, bytes(8)


def cmd_read_vi(dest, src=ADDR_MONITOR):
    """0x03 读取单个模块输出电压电流实际值 (IEEE754浮点)"""
    can_id = build_can_id(CMD_READ_VI, dest, src)
    return can_id, bytes(8)


def cmd_read_fan_temp_err(dest, src=ADDR_MONITOR):
    """0x04 读取风扇转速, 温度, 错误码"""
    can_id = build_can_id(CMD_READ_FAN_TEMP_ERR, dest, src)
    return can_id, bytes(8)


def cmd_read_temp_series(dest, src=ADDR_MONITOR):
    """0x05 读取温度系列"""
    can_id = build_can_id(CMD_READ_TEMP_SERIES, dest, src)
    return can_id, bytes(8)


def cmd_read_input_vi(dest, src=ADDR_MONITOR):
    """0x06 读取输入电压和模块状态"""
    can_id = build_can_id(CMD_READ_INPUT_VI, dest, src)
    return can_id, bytes(8)


def cmd_read_runtime(dest, src=ADDR_MONITOR):
    """0x08 读取运行时间"""
    can_id = build_can_id(CMD_READ_RUNTIME, dest, src)
    return can_id, bytes(8)


def cmd_read_llc_pfc(dest, src=ADDR_MONITOR):
    """0x09 读取LLC和PFC数据"""
    can_id = build_can_id(CMD_READ_LLC_PFC, dest, src)
    return can_id, bytes(8)


def cmd_set_walkin(enable, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x13 设置walkin功能使能/禁止 (单位s)"""
    can_id = build_can_id(CMD_SET_WALKIN, dest, src)
    data = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    return can_id, data


def cmd_ctrl_led(dest, flash_time_s, src=ADDR_MONITOR):
    """0x14 控制绿色LED灯闪烁 (flash_time_s: 闪烁时间秒, 32位无符号)"""
    can_id = build_can_id(CMD_CTRL_LED, dest, src)
    data = struct.pack('>I', flash_time_s) + bytes(4)
    return can_id, data


def cmd_set_group(dest, group_num, src=ADDR_MONITOR):
    """0x16 设置模块分组 (group_num: 0x00~0xFF)"""
    can_id = build_can_id(CMD_SET_GROUP, dest, src, DEV_MONITOR_TO_MODULE)
    data = bytes([group_num & 0xFF, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_ctrl_sleep(sleep, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x19 控制进入/退出休眠 (sleep: 1=休眠, 0=不休眠)"""
    can_id = build_can_id(CMD_CTRL_SLEEP, dest, src)
    data = bytes([0x01 if sleep else 0x00, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_ctrl_power(power_on, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x1A 控制开机/关机 (power_on: True=开机(0x00), False=关机(0x01))"""
    can_id = build_can_id(CMD_CTRL_POWER, dest, src)
    data = bytes([0x00 if power_on else 0x01, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_set_vi(voltage_mv, current_ma, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """
    0x1C 设置输出电压和电流 (32位整型, 单位1mV, 1mA)
    :param voltage_mv: 电压值, 单位mV (如 500000 = 500.000V)
    :param current_ma: 电流值, 单位mA (如 50000 = 50.000A)
    """
    can_id = build_can_id(CMD_SET_VI, dest, src)
    data = struct.pack('>II', voltage_mv & 0xFFFFFFFF, current_ma & 0xFFFFFFFF)
    return can_id, data


def cmd_set_addr_mode(dial_switch, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """
    0x1F 设置模块地址模式
    :param dial_switch: True=拨码设定, False=自动分配
    """
    can_id = build_can_id(CMD_SET_ADDR_MODE, dest, src)
    data = bytes([0x01 if dial_switch else 0x00, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_reassign_addr(src=ADDR_MONITOR):
    """0x20 总线所有模块重新分配地址 (必须广播, 设备号0x0A)"""
    can_id = build_can_id(CMD_REASSIGN_ADDR, ADDR_BROADCAST, src)
    return can_id, bytes(8)


def cmd_set_parallel_mode(smart_parallel, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """
    0x21 设置智能并机模式
    :param smart_parallel: True=智能并机, False=正常并机
    """
    can_id = build_can_id(CMD_SET_PARALLEL_MODE, dest, src)
    data = bytes([0x01 if smart_parallel else 0x00, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_set_can_broadcast(enable, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x22 CAN广播报文使能/禁止 (enable: True=使能, False=禁止)"""
    can_id = build_can_id(CMD_SET_CAN_BROADCAST, dest, src)
    data = bytes([0x01 if enable else 0x00, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_set_voltage_mode(mode, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """
    0x23 设置模块高低压模式
    :param mode: 1=低压模式, 2=高压模式
    """
    can_id = build_can_id(CMD_SET_VOLTAGE_MODE, dest, src)
    data = bytes([mode & 0xFF, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_set_mppt(upv_open, upv_mpp, ipv_mpp, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """
    0x24 设置MPPT曲线 (电压:0.1V, 电流:0.01A)
    :param upv_open: 开路电压, 单位0.1V (如 6000 = 600.0V)
    :param upv_mpp: 最大功率点电压, 单位0.1V (如 5000 = 500.0V)
    :param ipv_mpp: 最大功率点电流, 单位0.01A (如 2000 = 20.00A)
    两个电压相同即为恒压模式, 电流即为限流值
    """
    can_id = build_can_id(CMD_SET_MPPT, dest, src)
    data = bytes([0x00, 0x00]) + \
           struct.pack('>HH', upv_open & 0xFFFF, upv_mpp & 0xFFFF) + \
           struct.pack('>H', ipv_mpp & 0xFFFF) + \
           bytes(2)
    return can_id, data


def cmd_set_current_share(mode, coeff=0, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """
    0x25 设置模块间并联均流功能
    :param mode: 0=关闭, 1=被动均流, 2=主动均流
    :param coeff: 均流系数 (mV/A)
    """
    can_id = build_can_id(CMD_SET_CURRENT_SHARE, dest, src)
    data = bytes([mode & 0xFF, 0x00]) + struct.pack('>H', coeff & 0xFFFF) + bytes(4)
    return can_id, data


def cmd_set_voltage_share(mode, coeff=0, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x26 设置模块间串联均压功能"""
    can_id = build_can_id(CMD_SET_VOLTAGE_SHARE, dest, src)
    data = bytes([mode & 0xFF, 0x00]) + struct.pack('>H', coeff & 0xFFFF) + bytes(4)
    return can_id, data


def cmd_set_auto_switch(enable, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x27 设置高低档自动切换功能 (enable: True=打开(默认), False=关闭)"""
    can_id = build_can_id(CMD_SET_AUTO_SWITCH, dest, src)
    data = bytes([0x01 if enable else 0x00, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_set_voltage_rate(rate, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x28 设置电压变化率 (1~1000: 每秒上升电压值V)"""
    can_id = build_can_id(CMD_SET_VOLTAGE_RATE, dest, src)
    data = struct.pack('>H', rate & 0xFFFF) + bytes(6)
    return can_id, data


def cmd_set_current_rate(rate, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x29 设置电流变化率 (1~100: 每秒上升电流值A)"""
    can_id = build_can_id(CMD_SET_CURRENT_RATE, dest, src)
    data = struct.pack('>H', rate & 0xFFFF) + bytes(6)
    return can_id, data


def cmd_set_aging_mode(enable, dest=ADDR_BROADCAST, src=ADDR_MONITOR):
    """0x2A 设置老化模式 (enable: True=老化模式(上电输出))"""
    can_id = build_can_id(CMD_SET_AGING_MODE, dest, src)
    data = bytes([0x01 if enable else 0x00, 0, 0, 0, 0, 0, 0, 0])
    return can_id, data


def cmd_read_info(info_cmd, dest, src=ADDR_MONITOR):
    """0x30~0x39 读取模块固有信息"""
    can_id = build_can_id(info_cmd, dest, src)
    return can_id, bytes(8)


# ============================================================
# 响应数据解析函数
# ============================================================

def parse_vi_response(data):
    """
    解析 0x01/0x03 电压电流响应 (IEEE754浮点)
    :return: (voltage_V, current_A)
    """
    if len(data) < 8:
        return 0.0, 0.0
    voltage = struct.unpack('>f', data[0:4])[0]
    current = struct.unpack('>f', data[4:8])[0]
    return voltage, current


def parse_module_num_response(data):
    """
    解析 0x02 模块数量响应
    :return: module_count
    """
    if len(data) < 8:
        return 0
    return data[2]


def parse_fan_temp_err_response(data):
    """
    解析 0x04 风扇转速, 温度, 错误码响应
    Byte0: FanSpeed (0%~100%)
    Byte1: 温度 (有符号, 单位℃)
    Byte2-7: 错误码 (6字节, Byte2最高字节, 拼成64位)
    :return: (fan_speed_pct, temperature_c, fault_code)
    """
    if len(data) < 8:
        return 0, 0, 0
    fan_speed = data[0]
    temperature = struct.unpack('>b', bytes([data[1]]))[0]
    fault_bytes = data[2:8]
    fault_code = int.from_bytes(fault_bytes, byteorder='big', signed=False)
    return fan_speed, temperature, fault_code


def parse_input_vi_response(data):
    """
    解析 0x06 输入电压和模块状态
    Byte0-1: Uab (单位0.1V)
    Byte2-3: Ubc (单位0.1V)
    Byte4-5: Uca (单位0.1V)
    Byte6: State1 (模块状态)
    Byte7: State2 (智能并机模式)
    :return: (uab, ubc, uca, state1, state2)
    """
    if len(data) < 8:
        return 0, 0, 0, 0, 0
    uab = struct.unpack('>H', data[0:2])[0] / 10.0
    ubc = struct.unpack('>H', data[2:4])[0] / 10.0
    uca = struct.unpack('>H', data[4:6])[0] / 10.0
    state1 = data[6]
    state2 = data[7]
    return uab, ubc, uca, state1, state2


def parse_runtime_response(data):
    """
    解析 0x08 运行时间
    Byte0-3: 总运行时间 (32位无符号, 0.1h)
    Byte4-7: 本次开机运行时间 (32位无符号, s)
    :return: (total_hours, boot_seconds)
    """
    if len(data) < 8:
        return 0, 0
    total_time = struct.unpack('>I', data[0:4])[0] / 10.0
    boot_time = struct.unpack('>I', data[4:8])[0]
    return total_time, boot_time


def parse_llc_pfc_response(data):
    """
    解析 0x09 LLC和PFC数据
    Byte0-1: Fq (kHz, 16位带符号)
    Byte2-3: Iq2 (0.1A, 16位带符号)
    Byte4-5: Fac (0.01Hz, 16位带符号)
    Byte6-7: Ubus (0.1V, 16位带符号)
    """
    if len(data) < 8:
        return 0, 0, 0, 0
    fq = struct.unpack('>h', data[0:2])[0]
    iq2 = struct.unpack('>h', data[2:4])[0] / 10.0
    fac = struct.unpack('>h', data[4:6])[0] / 100.0
    ubus = struct.unpack('>h', data[6:8])[0] / 10.0
    return fq, iq2, fac, ubus


def parse_set_vi_response(data):
    """
    解析 0x1C 设置电压电流响应
    Byte0-3: 设定电压 (32位无符号, 单位mV)
    Byte4-7: 设定电流 (32位无符号, 单位mA)
    :return: (set_voltage_V, set_current_A)
    """
    if len(data) < 8:
        return 0.0, 0.0
    voltage_mv = struct.unpack('>I', data[0:4])[0]
    current_ma = struct.unpack('>I', data[4:8])[0]
    return voltage_mv / 1000.0, current_ma / 1000.0


def parse_power_response(data):
    """
    解析 0x1A 开关机响应中的 State3
    State3 位定义:
      Bit 0: 地址模式 (0=已初始化, 1=未初始化)
      Bit 1: 智能并机模式 (0=已初始化, 1=未初始化)
      Bit 2: 高低压模式 (0=已初始化, 1=未初始化)
    """
    if len(data) < 8:
        return {}
    state3 = data[7]
    return {
        'addr_mode_init': not (state3 & 0x01),
        'parallel_mode_init': not (state3 & 0x02),
        'voltage_mode_init': not (state3 & 0x04),
        'state3_raw': state3,
    }


def parse_info1_response(data):
    """
    解析 0x30 模块固有信息1
    Byte0-3: 软件物料号码 (32位整型, 如 0x01010501 -> A32010105-01)
    Byte4-5: MatchCode (16位, 2个ASCII字符)
    Byte6-7: ModelType (16位)
    """
    if len(data) < 8:
        return "", "", ""
    sw_part = struct.unpack('>I', data[0:4])[0]
    sw_str = f"A32{sw_part:08X}-01"
    match_code = struct.unpack('>H', data[4:6])[0]
    match_str = chr(match_code >> 8) + chr(match_code & 0xFF)
    model_type = struct.unpack('>H', data[6:8])[0]
    model_name = MODEL_TYPES.get(model_type, f"未知({model_type})")
    return sw_str, match_str, model_name


def parse_sn_response(data):
    """解析 0x32~0x33 序列号 (每个字节是一个ASCII字符)"""
    return ''.join(chr(b) if 32 <= b < 127 else '' for b in data[:8])


def parse_sn_decimal(data):
    """
    解析 0x32~0x33 序列号, 返回十进制字符串
    每个字节按BCD方式转换为2位十进制数, 拼接为完整序列号
    非BCD字节(>0x99)按原始十进制值3位显示
    """
    result = ""
    for b in data[:8]:
        hi = (b >> 4) & 0x0F
        lo = b & 0x0F
        if hi <= 9 and lo <= 9:
            result += f"{hi}{lo}"
        else:
            result += f"{b:03d}"
    return result


def parse_info2_response(data):
    """
    解析 0x31 模块特征字 (32位)
    Bit 31-30: 供电方式 (00=单供电, 01=双供电, 11=支持交流/直流/太阳能)
    Bit 29-28: 交流相数 (00=单相, 01=三相)
    Bit 27-26: 输入电压 (00=220VAC, 01=110VAC)
    Bit 25-16: 额定输出电流 (0x01=0.1A, 0x64=10A, 以此类推)
    Bit 15-13: 输出电压类型 (000=500V, 001=750V, 002=1000V)
    Bit 12-9: 效率类型
    """
    if len(data) < 4:
        return {}
    feature = struct.unpack('>I', data[0:4])[0]
    power_supply = (feature >> 30) & 0x03
    ac_phase = (feature >> 28) & 0x03
    input_voltage = (feature >> 26) & 0x03
    rated_current = (feature >> 16) & 0x3FF
    output_voltage_type = (feature >> 13) & 0x07
    efficiency_type = (feature >> 9) & 0x0F

    power_map = {0: "单供电", 1: "双供电", 3: "支持交流/直流/太阳能输入"}
    phase_map = {0: "单相", 1: "三相"}
    vin_map = {0: "220VAC", 1: "110VAC"}
    vout_map = {0: "500V", 1: "750V", 2: "1000V"}
    eff_map = {i: f"{90+i}~{90+i+1}%" for i in range(11)}
    eff_map[0] = "<90%"
    eff_map[10] = ">99%"

    return {
        'power_supply': power_map.get(power_supply, f"未知({power_supply})"),
        'ac_phase': phase_map.get(ac_phase, f"未知({ac_phase})"),
        'input_voltage': vin_map.get(input_voltage, f"未知({input_voltage})"),
        'rated_current': f"{rated_current * 0.1:.1f}A",
        'output_voltage_type': vout_map.get(output_voltage_type, f"未知({output_voltage_type})"),
        'efficiency': eff_map.get(efficiency_type, f"未知({efficiency_type})"),
        'raw': f"0x{feature:08X}",
    }


def decode_fault_code(fault_code):
    """
    解码64位故障码, 返回故障描述列表
    :param fault_code: 64位整数
    :return: list of fault strings
    """
    faults = []
    for bit in range(48):
        if fault_code & (1 << bit):
            fault_str = FAULT_CODES.get(bit, f"未知故障(Bit {bit})")
            faults.append(f"[Bit {bit}] {fault_str}")
    return faults


def format_can_id(can_id):
    """格式化 CAN ID 为十六进制字符串"""
    return f"0x{can_id:08X}"


def format_data(data):
    """格式化数据为十六进制字符串"""
    return ' '.join(f'{b:02X}' for b in data)


def format_can_message(can_id, data, direction="TX"):
    """格式化CAN消息为可读字符串"""
    info = parse_can_id(can_id)
    err_str = ERROR_CODES.get(info['error'], f"未知({info['error']})")
    return (f"[{direction}] ID={format_can_id(can_id)} "
            f"Err={err_str} Dev=0x{info['device']:02X} "
            f"Cmd=0x{info['cmd']:02X} "
            f"Dst=0x{info['dest']:02X} Src=0x{info['src']:02X} "
            f"Data=[{format_data(data)}]")
