"""
联明标准ModBus通信协议 V02 - Modbus RTU 协议实现

物理接口: RS485, 9600bps, 8N1
地址范围: 0x01~0xF7, 0x00为广播地址
功能码: 0x03(读), 0x05(写线圈), 0x06(写寄存器)
"""


def _build_crc_table():
    """生成标准Modbus CRC16查找表 (多项式0xA001, 初始值0xFFFF)"""
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        table.append(crc)
    return table

_CRC16_TABLE = _build_crc_table()


def crc16(data: bytes) -> int:
    """计算CRC16校验值 (标准Modbus RTU, 返回16位整数)"""
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC16_TABLE[(crc ^ byte) & 0xFF]
    return crc

# 寄存器地址定义
REG_STATUS = 0x0001       # 读取电源状态
REG_VOLTAGE = 0x0002      # 读取输出电压
REG_CURRENT = 0x0003       # 读取输出电流
REG_TEMPERATURE = 0x0004   # 读取温度
REG_POWER_SWITCH = 0x0005  # 电源开关机
REG_SET_VOLTAGE = 0x0006   # 设定输出电压
REG_MODULE_ADDR = 0x0007   # 读/写模块地址
REG_DEFAULT_VOLTAGE = 0x0010  # 设定默认输出电压

# 功能码
FC_READ_HOLDING = 0x03     # 读数据寄存器
FC_WRITE_COIL = 0x05       # 写单个线圈寄存器
FC_WRITE_REG = 0x06        # 写单个数据寄存器

# 广播地址
BROADCAST_ADDR = 0x00

# 电源状态位定义
STATUS_BITS = {
    0:  ("电源开关机状态", "1=开机 0=关机"),
    1:  ("输出正常", "1=正常 0=异常"),
    2:  ("输入正常", "1=正常 0=异常"),
    3:  ("风扇1异常", "1=异常 0=正常"),
    4:  ("风扇2异常", "1=异常 0=正常"),
    5:  ("输出过流", "1=异常 0=正常"),
    6:  ("输出过压", "1=异常 0=正常"),
    7:  ("前级故障", "1=异常 0=正常"),
    8:  ("EEP故障", "1=异常 0=正常"),
    9:  ("过温故障", "1=异常 0=正常"),
    10: ("硬件开关机标志", "1=开机 0=关机"),
    11: ("通信使能开关机标志", "1=开机 0=关机"),
}


def _add_crc(frame: bytes) -> bytes:
    """在帧末尾添加CRC (低字节在前, 高字节在后)"""
    crc = crc16(frame)
    return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def build_read_registers(addr: int, reg: int, qty: int = 1) -> bytes:
    """构建读保持寄存器请求 (功能码0x03)
    帧: [addr][0x03][reg_hi][reg_lo][qty_hi][qty_lo][CRC_Lo][CRC_Hi]
    """
    frame = bytes([addr, FC_READ_HOLDING,
                   (reg >> 8) & 0xFF, reg & 0xFF,
                   (qty >> 8) & 0xFF, qty & 0xFF])
    return _add_crc(frame)


def build_write_single_coil(addr: int, reg: int, on: bool) -> bytes:
    """构建写单个线圈请求 (功能码0x05)
    帧: [addr][0x05][reg_hi][reg_lo][data_hi][data_lo][CRC_Lo][CRC_Hi]
    data: 0xFF00=ON, 0x0000=OFF
    """
    data = 0xFF00 if on else 0x0000
    frame = bytes([addr, FC_WRITE_COIL,
                   (reg >> 8) & 0xFF, reg & 0xFF,
                   (data >> 8) & 0xFF, data & 0xFF])
    return _add_crc(frame)


def build_write_single_reg(addr: int, reg: int, value: int, little_endian: bool = False) -> bytes:
    """构建写单个寄存器请求 (功能码0x06)
    帧: [addr][0x06][reg_hi][reg_lo][data_hi][data_lo][CRC_Lo][CRC_Hi]
    little_endian: True时数据字节低字节在前
    """
    if little_endian:
        data_bytes = [value & 0xFF, (value >> 8) & 0xFF]
    else:
        data_bytes = [(value >> 8) & 0xFF, value & 0xFF]
    frame = bytes([addr, FC_WRITE_REG,
                   (reg >> 8) & 0xFF, reg & 0xFF] + data_bytes)
    return _add_crc(frame)


def build_read_status(addr: int) -> bytes:
    """读取电源状态 (寄存器0x0001)"""
    return build_read_registers(addr, REG_STATUS, 1)


def build_read_all(addr: int) -> bytes:
    """批量读取状态+电压+电流+温度 (寄存器0x0001~0x0004, 一次读4个)"""
    return build_read_registers(addr, REG_STATUS, 4)


def build_read_voltage(addr: int) -> bytes:
    """读取输出电压 (寄存器0x0002)"""
    return build_read_registers(addr, REG_VOLTAGE, 1)


def build_read_current(addr: int) -> bytes:
    """读取输出电流 (寄存器0x0003)"""
    return build_read_registers(addr, REG_CURRENT, 1)


def build_read_temperature(addr: int) -> bytes:
    """读取温度 (寄存器0x0004)"""
    return build_read_registers(addr, REG_TEMPERATURE, 1)


def build_power_on(addr: int) -> bytes:
    """开机 (线圈0x0005, 值0xFF00)"""
    return build_write_single_coil(addr, REG_POWER_SWITCH, True)


def build_power_off(addr: int) -> bytes:
    """关机 (线圈0x0005, 值0x0000)"""
    return build_write_single_coil(addr, REG_POWER_SWITCH, False)


def build_set_voltage(addr: int, voltage: float, little_endian: bool = False) -> bytes:
    """设定输出电压 (寄存器0x0006, 实际值*100)"""
    value = int(voltage * 100)
    return build_write_single_reg(addr, REG_SET_VOLTAGE, value, little_endian)


def build_set_default_voltage(addr: int, voltage: float, little_endian: bool = False) -> bytes:
    """设定默认输出电压 (寄存器0x0010, 单位0.01V)"""
    value = int(voltage * 100)
    return build_write_single_reg(addr, REG_DEFAULT_VOLTAGE, value, little_endian)


def build_read_module_addr(addr: int) -> bytes:
    """读取模块地址 (寄存器0x0007)"""
    return build_read_registers(addr, REG_MODULE_ADDR, 1)


def build_write_module_addr(addr: int, new_addr: int, little_endian: bool = False) -> bytes:
    """更改模块地址 (寄存器0x0007, 功能码0x06)"""
    return build_write_single_reg(addr, REG_MODULE_ADDR, new_addr, little_endian)


def verify_crc(data: bytes) -> bool:
    """验证数据的CRC是否正确"""
    if len(data) < 3:
        return False
    payload = data[:-2]
    crc_lo = data[-2]
    crc_hi = data[-1]
    expected = crc16(payload)
    return (expected & 0xFF) == crc_lo and ((expected >> 8) & 0xFF) == crc_hi


def parse_read_response(data: bytes, little_endian: bool = False):
    """解析读寄存器响应
    返回: (成功?, 地址, 功能码, [数据值列表]) 或 (False, 地址, 功能码, 错误信息)
    little_endian: True=低字节在前(非标准), False=高字节在前(标准Modbus)
    """
    if len(data) < 5:
        return (False, 0, 0, None)
    addr = data[0]
    fc = data[1]

    # 异常响应
    if fc & 0x80:
        exception_code = data[2] if len(data) >= 3 else 0
        return (False, addr, fc, exception_code)

    # 正常响应: [addr][0x03][byte_count][data_hi][data_lo]...[CRC_Lo][CRC_Hi]
    if not verify_crc(data):
        return (False, addr, fc, "CRC_ERROR")

    byte_count = data[2]
    values = []
    for i in range(0, byte_count, 2):
        if 3 + i + 1 <= len(data) - 3:
            hi_byte = data[3 + i]
            lo_byte = data[3 + i + 1]
            if little_endian:
                val = (lo_byte << 8) | hi_byte
            else:
                val = (hi_byte << 8) | lo_byte
            values.append(val)
    return (True, addr, fc, values)


def parse_write_response(data: bytes, little_endian: bool = False):
    """解析写寄存器/线圈响应
    返回: (成功?, 地址, 功能码, 寄存器地址, 数据值) 或 (False, ...)
    little_endian: True=低字节在前(非标准), False=高字节在前(标准Modbus)
    """
    if len(data) < 8:
        return (False, 0, 0, 0, 0)
    addr = data[0]
    fc = data[1]

    if fc & 0x80:
        return (False, addr, fc & 0x7F, data[2] if len(data) > 2 else 0, 0)

    if not verify_crc(data):
        return (False, addr, fc, 0, "CRC_ERROR")

    reg = (data[2] << 8) | data[3]
    if little_endian:
        value = (data[5] << 8) | data[4]
    else:
        value = (data[4] << 8) | data[5]
    return (True, addr, fc, reg, value)


def parse_status(status_val: int) -> dict:
    """解析电源状态字为各状态位"""
    result = {}
    for bit, (name, desc) in STATUS_BITS.items():
        result[bit] = {
            "name": name,
            "desc": desc,
            "value": (status_val >> bit) & 1,
        }
    return result


def get_fault_summary(status_val: int) -> str:
    """从状态字提取故障摘要"""
    faults = []
    if not ((status_val >> 1) & 1):
        faults.append("输出异常")
    if not ((status_val >> 2) & 1):
        faults.append("输入异常")
    if (status_val >> 3) & 1:
        faults.append("风扇1故障")
    if (status_val >> 4) & 1:
        faults.append("风扇2故障")
    if (status_val >> 5) & 1:
        faults.append("输出过流")
    if (status_val >> 6) & 1:
        faults.append("输出过压")
    if (status_val >> 7) & 1:
        faults.append("前级故障")
    if (status_val >> 8) & 1:
        faults.append("EEP故障")
    if (status_val >> 9) & 1:
        faults.append("过温故障")
    return "  ".join(faults) if faults else "无"


def format_bytes(data: bytes) -> str:
    """格式化字节为十六进制字符串用于日志显示"""
    return " ".join(f"{b:02X}" for b in data)
