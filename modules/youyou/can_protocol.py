"""
优优绿能双向模块 CAN 通讯协议层
CAN 2.0B 扩展帧, 29-bit ID, 125kbps
所有电压单位 mV, 所有电流单位 mA
"""
import struct

PROTOCOL_ID = 0x01
CAN_BAUDRATE = 125000

MSG_TYPE_SET = 0x00
MSG_TYPE_SET_RESP = 0x01
MSG_TYPE_READ = 0x02
MSG_TYPE_READ_RESP = 0x03
MSG_TYPE_READ_SN_RESP = 0x04

CMD_DC_VOLTAGE = 0x00
CMD_CHARGE_CURRENT = 0x01
CMD_SET_VOLTAGE = 0x02
CMD_SET_CURRENT = 0x03
CMD_POWER_ONOFF = 0x04
CMD_READ_SN = 0x05
CMD_STATUS = 0x08
CMD_LINE_VOLT_AB = 20
CMD_LINE_VOLT_BC = 21
CMD_LINE_VOLT_CA = 22
CMD_TEMP_INTAKE = 30
CMD_TEMP_PFC = 31
CMD_TEMP_DCDC = 34
CMD_CURRENT_FASTEST = 47
CMD_CURRENT_FAST = 48
CMD_BATTERY_VOLTAGE = 61
CMD_POWER_FACTOR = 88
CMD_GROUP = 89
CMD_HILO_MODE_SET = 95
CMD_HILO_MODE_READ = 96
CMD_VOLTAGE_FAST = 98
CMD_DC_SW_VERSION = 99
CMD_PFC_SW_VERSION = 100
CMD_HILO_ACTUAL = 101
CMD_EXTENDED = 0x7F

EXT_SET_MODE = 51
EXT_READ_MODE = 52
EXT_DISCHARGE_CURRENT_SET = 66
EXT_DISCHARGE_CURRENT = 67
EXT_DISCHARGE_CURRENT_FAST = 68
EXT_OFFGRID_ENABLE = 73

MODE_CHARGE = 0
MODE_DISCHARGE = 1
MODE_OFFGRID_DISCHARGE = 3

HI_VOLTAGE = 1
LO_VOLTAGE = 2

STATUS_BITS = {
    0: "交流过压",
    1: "交流欠压",
    2: "交流过压保护",
    3: "PFC母线过压",
    4: "PFC母线欠压",
    5: "PFC母线不平衡",
    6: "直流输出过压",
    7: "直流过压保护",
    8: "直流输出欠压",
    9: "风扇故障",
    11: "风扇驱动损坏",
    12: "过温保护",
    13: "环境温度过低",
    14: "PFC过温",
    15: "输出继电器故障",
    16: "DC过温",
    18: "PFC-DCDC通信故障",
    20: "PFC故障",
    21: "DCDC故障",
    22: "输入电压降额",
    23: "温度降额",
    29: "序列号重复",
    31: "泄放电路异常",
}

STATUS_INDICATOR_BITS = {
    25: "DCDC关机",
    27: "模块待机",
}


def build_can_id(module_addr, monitor_addr=0x01, production_day=0, serial_low=0):
    return ((PROTOCOL_ID & 0xF) << 25) | \
           ((monitor_addr & 0xF) << 21) | \
           ((module_addr & 0x7F) << 14) | \
           ((production_day & 0x1F) << 9) | \
           (serial_low & 0x1FF)


def parse_can_id(can_id):
    protocol = (can_id >> 25) & 0xF
    monitor = (can_id >> 21) & 0xF
    module = (can_id >> 14) & 0x7F
    prod_day = (can_id >> 9) & 0x1F
    serial_low = can_id & 0x1FF
    return {
        "protocol": protocol,
        "monitor_addr": monitor,
        "module_addr": module,
        "production_day": prod_day,
        "serial_low": serial_low,
    }


def build_data_frame(group_addr, msg_type, cmd_type, cmd_sup=0, cmd_data=0, extended=False):
    byte0 = ((group_addr & 0xF) << 4) | (msg_type & 0xF)
    byte1 = cmd_type & 0xFF
    if extended:
        byte2 = (cmd_sup >> 8) & 0xFF
        byte3 = cmd_sup & 0xFF
        byte4 = (cmd_data >> 24) & 0xFF
        byte5 = (cmd_data >> 16) & 0xFF
        byte6 = (cmd_data >> 8) & 0xFF
        byte7 = cmd_data & 0xFF
    else:
        byte2 = 0x00
        byte3 = 0x00
        byte4 = (cmd_data >> 24) & 0xFF
        byte5 = (cmd_data >> 16) & 0xFF
        byte6 = (cmd_data >> 8) & 0xFF
        byte7 = cmd_data & 0xFF
    return bytes([byte0, byte1, byte2, byte3, byte4, byte5, byte6, byte7])


def parse_data_frame(data):
    if len(data) < 8:
        return None
    byte0 = data[0]
    group_addr = (byte0 >> 4) & 0xF
    msg_type = byte0 & 0xF
    cmd_type = data[1]
    cmd_sup = (data[2] << 8) | data[3]
    cmd_data = struct.unpack(">I", bytes(data[4:8]))[0]
    return {
        "group_addr": group_addr,
        "msg_type": msg_type,
        "cmd_type": cmd_type,
        "cmd_sup": cmd_sup,
        "cmd_data": cmd_data,
        "raw": list(data[:8]),
    }


class ModuleCommand:
    def __init__(self, module_addr, group_addr=0x01, monitor_addr=0x01):
        self.module_addr = module_addr
        self.group_addr = group_addr
        self.monitor_addr = monitor_addr

    def can_id(self):
        return build_can_id(self.module_addr, self.monitor_addr)

    def power_on(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_POWER_ONOFF, cmd_data=0)
        return self.can_id(), data

    def power_off(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_POWER_ONOFF, cmd_data=1)
        return self.can_id(), data

    def set_voltage(self, voltage_v):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_SET_VOLTAGE, cmd_data=int(voltage_v * 1000))
        return self.can_id(), data

    def set_current(self, current_a):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_SET_CURRENT, cmd_data=int(current_a * 1000))
        return self.can_id(), data

    def set_charge_mode(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_EXTENDED, cmd_sup=EXT_SET_MODE, cmd_data=MODE_CHARGE, extended=True)
        return self.can_id(), data

    def set_discharge_mode(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_EXTENDED, cmd_sup=EXT_SET_MODE, cmd_data=MODE_DISCHARGE, extended=True)
        return self.can_id(), data

    def set_discharge_current(self, current_a):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_EXTENDED, cmd_sup=EXT_DISCHARGE_CURRENT_SET, cmd_data=int(current_a * 1000), extended=True)
        return self.can_id(), data

    def set_high_voltage_mode(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_HILO_MODE_SET, cmd_data=HI_VOLTAGE)
        return self.can_id(), data

    def set_low_voltage_mode(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_SET, CMD_HILO_MODE_SET, cmd_data=LO_VOLTAGE)
        return self.can_id(), data

    def set_group(self, new_group):
        data = build_data_frame(new_group, MSG_TYPE_SET, CMD_GROUP, cmd_data=new_group)
        return self.can_id(), data

    def read_voltage(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_DC_VOLTAGE)
        return self.can_id(), data

    def read_voltage_fast(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_VOLTAGE_FAST)
        return self.can_id(), data

    def read_current(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_CHARGE_CURRENT)
        return self.can_id(), data

    def read_current_fast(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_CURRENT_FAST)
        return self.can_id(), data

    def read_set_voltage(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_SET_VOLTAGE)
        return self.can_id(), data

    def read_set_current(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_SET_CURRENT)
        return self.can_id(), data

    def read_status(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_STATUS)
        return self.can_id(), data

    def read_serial_number(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_READ_SN)
        return self.can_id(), data

    def read_work_mode(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_EXTENDED, cmd_sup=EXT_READ_MODE, extended=True)
        return self.can_id(), data

    def read_hilo_mode(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_HILO_MODE_READ)
        return self.can_id(), data

    def read_battery_voltage(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_BATTERY_VOLTAGE)
        return self.can_id(), data

    def read_group(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_GROUP)
        return self.can_id(), data

    def read_bus_voltage(self):
        data = build_data_frame(self.group_addr, MSG_TYPE_READ, CMD_LINE_VOLT_AB)
        return self.can_id(), data


def parse_status_flags(status_data):
    faults = []
    for bit, name in STATUS_BITS.items():
        if status_data & (1 << bit):
            faults.append(name)
    return faults


def parse_status_indicators(status_data):
    indicators = []
    for bit, name in STATUS_INDICATOR_BITS.items():
        if status_data & (1 << bit):
            indicators.append(name)
    return indicators


def mode_to_str(mode):
    return {0: "充电", 1: "恒流放电", 3: "离网放电"}.get(mode, "未知")


def hilo_to_str(mode):
    return {1: "高压(1000V)", 2: "低压(500V)"}.get(mode, "未知")
