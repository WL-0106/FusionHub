"""
英飞源REG系列充电模块CAN通讯协议 V1.09
底层协议: CAN2.0B, 125Kbps, 29位扩展标识符
"""
import struct
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional, Tuple


class DeviceType(IntEnum):
    SINGLE_MODULE = 0x0A  # 监控与单个整流模块之间协议
    GROUP_MODULE = 0x0B   # 监控与整组整流模块之间协议


class CommandCode(IntEnum):
    READ_SYSTEM_VOLTAGE_CURRENT = 0x01  # 读取系统电压电流(浮点)
    READ_MODULE_COUNT = 0x02            # 读取模块数
    READ_MODULE_VOLTAGE_CURRENT = 0x03  # 读取模块N电压电流(浮点)
    READ_MODULE_STATUS = 0x04           # 读取模块N状态
    READ_MODULE_INPUT_VOLTAGE = 0x06    # 读取模块N输入电压
    READ_SYSTEM_VOLTAGE_CURRENT_FIXED = 0x08  # 读取系统电压电流(定点)
    READ_MODULE_VOLTAGE_CURRENT_FIXED = 0x09  # 读取模块N电压电流(定点)
    READ_MODULE_INFO = 0x0A             # 读取模块N信息(最大电压/电流/功率)
    READ_MODULE_BARCODE = 0x0B          # 读取模块条码
    READ_EXTERNAL_VOLTAGE_CURRENT = 0x0C # 读取外部电压/允许电流
    SET_COMPREHENSIVE = 0x0F            # 设置综合命令
    SET_WALKIN = 0x13                   # 设置Walkin使能
    SET_GREEN_LED = 0x14                # 设置绿灯闪烁
    SET_GROUP_ID = 0x16                 # 设置模块组号
    SET_SLEEP = 0x19                    # 设置休眠
    SET_ONOFF = 0x1A                    # 开关机控制
    SET_VOLTAGE_TOTAL_CURRENT = 0x1B    # 设置输出电压和总电流
    SET_VOLTAGE_CURRENT = 0x1C          # 设置输出电压和电流
    SET_ADDRESS_MODE = 0x1F             # 设置地址分配方式


@dataclass
class CANFrame:
    """CAN帧数据类"""
    arbitration_id: int  # 29位标识符
    data: bytes          # 数据域 (0-8字节)
    is_extended_id: bool = True
    timestamp: float = 0.0  # 接收时间戳

    @property
    def error_code(self) -> int:
        return (self.arbitration_id >> 26) & 0x07

    @property
    def device_type(self) -> int:
        return (self.arbitration_id >> 22) & 0x0F

    @property
    def command(self) -> int:
        return (self.arbitration_id >> 16) & 0x3F

    @property
    def dest_addr(self) -> int:
        return (self.arbitration_id >> 8) & 0xFF

    @property
    def src_addr(self) -> int:
        return self.arbitration_id & 0xFF

    def __str__(self):
        data_hex = self.data.hex(' ').upper() if self.data else ''
        return f"ID=0x{self.arbitration_id:08X} [{data_hex}]"


class InfyCANProtocol:
    """英飞源CAN协议封装"""

    # 地址常量
    BROADCAST_ADDR = 0x3F
    MONITOR_ADDR = 0xF0
    MAX_MODULE_ADDR = 0x3B  # 实际有效模块地址 0x00~0x3B

    # 数据合理性范围(定点格式)
    VOLTAGE_MIN_MV = 0
    VOLTAGE_MAX_MV = 800000      # 800V
    CURRENT_MIN_MA = 0
    CURRENT_MAX_MA = 200000      # 200A

    @staticmethod
    def build_frame_id(error_code: int, device_type: int, command: int,
                       dest_addr: int, src_addr: int) -> int:
        """构建29位CAN帧标识符"""
        frame_id = 0
        frame_id |= (error_code & 0x07) << 26
        frame_id |= (device_type & 0x0F) << 22
        frame_id |= (command & 0x3F) << 16
        frame_id |= (dest_addr & 0xFF) << 8
        frame_id |= (src_addr & 0xFF)
        return frame_id

    @classmethod
    def parse_frame_id(cls, frame_id: int) -> dict:
        """解析29位CAN帧标识符"""
        return {
            'error_code': (frame_id >> 26) & 0x07,
            'device_type': (frame_id >> 22) & 0x0F,
            'command': (frame_id >> 16) & 0x3F,
            'dest_addr': (frame_id >> 8) & 0xFF,
            'src_addr': frame_id & 0xFF,
        }

    # ==================== 读取命令 ====================

    @classmethod
    def read_system_voltage_current(cls, group: int = 0) -> CANFrame:
        """读取系统电压电流 (0x01)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = cls.BROADCAST_ADDR
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_SYSTEM_VOLTAGE_CURRENT,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_module_count(cls, group: int = 0) -> CANFrame:
        """读取模块数 (0x02)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = cls.BROADCAST_ADDR
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_MODULE_COUNT,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_module_voltage_current(cls, addr: int, group: int = 0) -> CANFrame:
        """读取模块N电压电流定点 (0x09)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_MODULE_VOLTAGE_CURRENT_FIXED,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_module_voltage_current_float(cls, addr: int, group: int = 0) -> CANFrame:
        """读取模块N电压电流浮点 (0x03) - 部分固件仅支持此格式"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_MODULE_VOLTAGE_CURRENT,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_module_status(cls, addr: int, group: int = 0) -> CANFrame:
        """读取模块N状态 (0x04)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_MODULE_STATUS,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_module_input_voltage(cls, addr: int, group: int = 0) -> CANFrame:
        """读取模块N输入电压 (0x06)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_MODULE_INPUT_VOLTAGE,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_module_info(cls, addr: int, group: int = 0) -> CANFrame:
        """读取模块N信息 (0x0A)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_MODULE_INFO,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_module_barcode(cls, addr: int, group: int = 0) -> CANFrame:
        """读取模块条码 (0x0B)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_MODULE_BARCODE,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    @classmethod
    def read_external_voltage_current(cls, addr: int, group: int = 0) -> CANFrame:
        """读取外部电压/允许电流 (0x0C)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        frame_id = cls.build_frame_id(0, dev, CommandCode.READ_EXTERNAL_VOLTAGE_CURRENT,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, bytes(8))

    # ==================== 设置命令 ====================

    @classmethod
    def set_onoff(cls, on: bool, addr: int = BROADCAST_ADDR, group: int = 0) -> CANFrame:
        """开关机控制 (0x1A), on=True开机, on=False关机"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        # 协议: 0x1A 命令, data[0]=01关机, 00开机
        data = bytes([0x00 if on else 0x01] + [0] * 7)
        frame_id = cls.build_frame_id(0, dev, CommandCode.SET_ONOFF,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, data)

    @classmethod
    def set_voltage_total_current(cls, voltage_mv: int, current_ma: int,
                                   addr: int = BROADCAST_ADDR, group: int = 0) -> CANFrame:
        """设置输出电压和总电流 (0x1B) - 大端"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        v_bytes = struct.pack('>I', voltage_mv & 0xFFFFFFFF)
        i_bytes = struct.pack('>I', current_ma & 0xFFFFFFFF)
        data = v_bytes + i_bytes
        frame_id = cls.build_frame_id(0, dev, CommandCode.SET_VOLTAGE_TOTAL_CURRENT,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, data)

    @classmethod
    def set_voltage_current(cls, voltage_mv: int, current_ma: int,
                             addr: int = BROADCAST_ADDR, group: int = 0) -> CANFrame:
        """设置输出电压和电流 (0x1C) - 大端"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        v_bytes = struct.pack('>I', voltage_mv & 0xFFFFFFFF)
        i_bytes = struct.pack('>I', current_ma & 0xFFFFFFFF)
        data = v_bytes + i_bytes
        frame_id = cls.build_frame_id(0, dev, CommandCode.SET_VOLTAGE_CURRENT,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, data)

    @classmethod
    def set_group_id(cls, group: int, addr: int) -> CANFrame:
        """设置模块组号 (0x16)"""
        data = bytes([group & 0xFF] + [0] * 7)
        frame_id = cls.build_frame_id(0, DeviceType.SINGLE_MODULE, CommandCode.SET_GROUP_ID,
                                      addr, cls.MONITOR_ADDR)
        return CANFrame(frame_id, data)

    @classmethod
    def set_sleep(cls, sleep: bool, addr: int = BROADCAST_ADDR, group: int = 0) -> CANFrame:
        """设置休眠 (0x19)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        data = bytes([0x01 if sleep else 0x00] + [0] * 7)
        frame_id = cls.build_frame_id(0, dev, CommandCode.SET_SLEEP,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, data)

    @classmethod
    def set_walkin(cls, enable: bool, addr: int = BROADCAST_ADDR, group: int = 0) -> CANFrame:
        """设置Walkin使能 (0x13)"""
        if group > 0:
            dev = DeviceType.GROUP_MODULE
            dest = group
        else:
            dev = DeviceType.SINGLE_MODULE
            dest = addr
        data = bytes([0x01 if enable else 0x00] + [0] * 7)
        frame_id = cls.build_frame_id(0, dev, CommandCode.SET_WALKIN,
                                      dest, cls.MONITOR_ADDR)
        return CANFrame(frame_id, data)

    @classmethod
    def set_address_mode(cls, dial_mode: bool) -> CANFrame:
        """设置地址分配方式 (0x1F), True=拨码方式, False=自动分配"""
        data = bytes([0x01 if dial_mode else 0x00] + [0] * 7)
        frame_id = cls.build_frame_id(0, DeviceType.SINGLE_MODULE, CommandCode.SET_ADDRESS_MODE,
                                      cls.BROADCAST_ADDR, cls.MONITOR_ADDR)
        return CANFrame(frame_id, data)

    # ==================== 数据解析 ====================

    @staticmethod
    def parse_float_voltage_current(data: bytes) -> Tuple[float, float]:
        """解析浮点格式的电压电流
        单模块精简单帧可能只用DLC=4只带电压4字节(电流缺失);
        完整8字节为 电压4字节(V,大端) + 电流4字节(A,大端)
        """
        voltage = 0.0
        current = 0.0
        if len(data) >= 4:
            voltage = struct.unpack('>f', data[0:4])[0]
        if len(data) >= 8:
            current = struct.unpack('>f', data[4:8])[0]
        return voltage, current

    @staticmethod
    def parse_fixed_voltage_current(data: bytes) -> Tuple[int, int]:
        """解析定点格式的电压电流 (mV, mA) - 大端
        协议规定: data[0..3]=电压(mV,大端), data[4..7]=电流(mA,大端)
        """
        if len(data) < 8:
            return 0, 0

        # 数据有效性检查: 全部0xFF视为无效(未初始化)
        if data[:8] == b'\xff' * 8 or data[:8] == b'\x00' * 8:
            return 0, 0

        voltage = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
        current = (data[4] << 24) | (data[5] << 16) | (data[6] << 8) | data[7]

        # 处理有符号32位整数
        if voltage & 0x80000000:
            voltage -= 0x100000000
        if current & 0x80000000:
            current -= 0x100000000

        # 合理性校验: 超出物理范围则视为无效
        if not (InfyCANProtocol.VOLTAGE_MIN_MV <= voltage <= InfyCANProtocol.VOLTAGE_MAX_MV):
            voltage = 0
        if not (InfyCANProtocol.CURRENT_MIN_MA <= current <= InfyCANProtocol.CURRENT_MAX_MA):
            current = 0

        return voltage, current

    @staticmethod
    def parse_module_status(data: bytes) -> dict:
        """解析模块状态 (0x04回复)
        协议: Byte2=组号, Byte3=状态表3, Byte4=温度, Byte5=状态表2,
              Byte6=状态表1, Byte7=状态表0
        注: 实例 "00 00 02 00 1B 00 40 00" = 组2, 27℃, 状态表1=0x40(walkin)
        """
        if len(data) < 8:
            return {}
        temp = data[4]
        return {
            'group': data[2],
            'status3': data[3],
            'temperature': temp if temp < 128 else temp - 256,
            'status2': data[5],
            'status1': data[6],
            'status0': data[7],
        }

    @staticmethod
    def parse_input_voltage(data: bytes) -> dict:
        """解析输入电压 (0x06回复)。单模块精简单帧可能只有4字节(AB/BC, 无CA)"""
        res = {'Vab': 0.0, 'Vbc': 0.0, 'Vca': 0.0}
        if len(data) >= 2:
            res['Vab'] = ((data[0] << 8) | data[1]) * 0.1
        if len(data) >= 4:
            res['Vbc'] = ((data[2] << 8) | data[3]) * 0.1
        if len(data) >= 6:
            res['Vca'] = ((data[4] << 8) | data[5]) * 0.1
        return res

    @staticmethod
    def parse_module_info(data: bytes) -> dict:
        """解析模块信息 (0x0A回复)"""
        if len(data) < 8:
            return {}
        vmax = (data[0] << 8) | data[1]
        vmin = (data[2] << 8) | data[3]
        imax = (data[4] << 8) | data[5]
        prate = (data[6] << 8) | data[7]
        return {
            'v_max': vmax,
            'v_min': vmin,
            'i_max': imax * 0.1,
            'p_rate': prate * 10,
        }

    @staticmethod
    def parse_external_voltage_current(data: bytes) -> Tuple[float, float]:
        """解析外部电压和允许电流 (0x0C回复)"""
        if len(data) < 4:
            return 0.0, 0.0
        voltage = ((data[0] << 8) | data[1]) * 0.1
        current = ((data[2] << 8) | data[3]) * 0.1
        return voltage, current

    @staticmethod
    def parse_barcode(data: bytes) -> str:
        """解析条码 (0x0B回复)"""
        if len(data) < 8:
            return ""
        try:
            return data.decode('ascii')
        except:
            return data.hex().upper()

    @staticmethod
    def parse_module_count(data: bytes) -> int:
        """解析模块数量 (0x02回复)"""
        if len(data) < 2:
            return 0
        return (data[0] << 8) | data[1]

    @staticmethod
    def decode_status_bits(status0: int, status1: int, status2: int, status3: int) -> list:
        """解析状态位为告警列表(不含运行/配置状态位, 详见 decode_status_states)。
        位定义以协议 V1.09 0x04 状态表原文为准(状态表0/1 的 bit0 不可互换,
        状态表2 告警位从 bit2 起, bit1 保留):
          状态表0(Byte7): 0=输出短路 1=模块故障 2=内部通信故障 3=输入/母线异常
                          5=放电异常 6=风道不畅 7=通信中断(bit4 休眠为状态位)
          状态表1(Byte6): 1=ID重复 2=保护告警 3=风扇故障 4=过温 5=输出过压
                          (bit0 DC侧关机、bit6 WALK-IN使能为状态位)
          状态表2(Byte5): 2=严重不均流 3=三相缺相 4=三相不平衡 5=输入欠压 6=输入过压
                          (bit0 限功率、bit7 PFC侧关机为状态位)
        """
        faults = []
        # 状态表0
        if status0 & 0x01:
            faults.append("输出短路")
        if status0 & 0x02:
            faults.append("模块故障")
        if status0 & 0x04:
            faults.append("内部通信故障")
        if status0 & 0x08:
            faults.append("输入/母线异常")
        if status0 & 0x20:
            faults.append("放电异常")
        if status0 & 0x40:
            faults.append("风道不畅")
        if status0 & 0x80:
            faults.append("通信中断")

        # 状态表1
        if status1 & 0x02:
            faults.append("ID重复")
        if status1 & 0x04:
            faults.append("保护告警")
        if status1 & 0x08:
            faults.append("风扇故障")
        if status1 & 0x10:
            faults.append("过温告警")
        if status1 & 0x20:
            faults.append("输出过压")

        # 状态表2
        if status2 & 0x04:
            faults.append("严重不均流")
        if status2 & 0x08:
            faults.append("三相缺相")
        if status2 & 0x10:
            faults.append("三相不平衡")
        if status2 & 0x20:
            faults.append("输入欠压")
        if status2 & 0x40:
            faults.append("输入过压")

        return faults

    @staticmethod
    def decode_status_states(status0: int, status1: int, status2: int, status3: int) -> list:
        """解析状态位中的运行/配置状态(非告警, 不进故障列)"""
        states = []
        if status1 & 0x01:
            states.append("DC侧关机")
        if status1 & 0x40:
            states.append("Walkin使能")
        if status2 & 0x80:
            states.append("PFC侧关机")
        if status0 & 0x10:
            states.append("模块休眠")
        if status2 & 0x01:
            states.append("限功率")
        hv_mode = (status3 >> 1) & 0x03
        if hv_mode == 1:
            states.append("高低压自动")
        elif hv_mode == 2:
            states.append("低压模式")
        elif hv_mode == 3:
            states.append("高压模式")
        return states