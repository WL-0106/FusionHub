"""
联明电源数字电源模块 CAN通讯协议 V1.0
CAN 2.0B, 29bit扩展帧, 波特率125kbps

UT-6502 固定格式传输: 每帧13字节
  Byte0: 帧信息 (Bit7=FF扩展/标准, Bit6=RTR远程/数据, Bit3-0=DLC数据长度)
  Byte1-4: CAN ID (大端, 高字节在前)
  Byte5-12: 数据 (8字节, 不足补0)
"""

MAX_MODULE_ADDR = 60
CAN_BAUDRATE = 125000

ADDR_MASK = 0x7F

SEND_BASE_SET_OUTPUT   = 0x1907C080
SEND_BASE_SET_POWER    = 0x1907C080
SEND_BASE_READ_STATUS  = 0x1907C080
SEND_BASE_READ_SET_V   = 0x19010080
SEND_BASE_READ_SET_I   = 0x19010880
SEND_BASE_READ_INPUT_V = 0x1907A080
SEND_BASE_READ_TEMP    = 0x19008080
SEND_BASE_CURRENT_SHARE = 0x19C21880
SEND_BASE_FIND_MODULE  = 0x19C22880

RECV_BASE_STATUS     = 0x1807C080
RECV_BASE_SET_V      = 0x18010080
RECV_BASE_SET_I      = 0x18010880
RECV_BASE_INPUT_V    = 0x1807A080
RECV_BASE_TEMP       = 0x18008080
RECV_BASE_CURRENT_SHARE = 0x18078080

RECV_BASE_MAP = {
    RECV_BASE_STATUS: "status",
    RECV_BASE_SET_V: "set_voltage",
    RECV_BASE_SET_I: "set_current",
    RECV_BASE_INPUT_V: "input_voltage",
    RECV_BASE_TEMP: "temperature",
    RECV_BASE_CURRENT_SHARE: "current_share",
}

CMD_SET_OUTPUT = 0
CMD_READ_STATUS = 1
CMD_SET_POWER = 2

POWER_ON = 0x55
POWER_OFF = 0xAA


def make_can_id(base, addr):
    return (base & 0xFFFFFF80) | (addr & ADDR_MASK)


def extract_addr(can_id):
    return can_id & ADDR_MASK


def extract_base(can_id):
    return can_id & 0xFFFFFF80


def build_ut6502_frame(can_id, data, extended=True, remote=False):
    dlc = len(data)
    frame_info = 0
    if extended:
        frame_info |= 0x80
    if remote:
        frame_info |= 0x40
    frame_info |= (dlc & 0x0F)
    id_bytes = can_id.to_bytes(4, 'big')
    data_bytes = bytes(data)
    if len(data_bytes) < 8:
        data_bytes = data_bytes + b'\x00' * (8 - len(data_bytes))
    frame = bytes([frame_info]) + id_bytes + data_bytes
    return frame


def parse_ut6502_frame(frame_bytes):
    if len(frame_bytes) < 13:
        return None
    frame_info = frame_bytes[0]
    extended = bool(frame_info & 0x80)
    remote = bool(frame_info & 0x40)
    dlc = frame_info & 0x0F
    can_id = int.from_bytes(frame_bytes[1:5], 'big')
    data = list(frame_bytes[5:5 + max(dlc, 8)])
    return {
        'extended': extended,
        'remote': remote,
        'dlc': dlc,
        'id': can_id,
        'data': data,
    }


def build_set_output(addr, voltage_v, current_a):
    can_id = make_can_id(SEND_BASE_SET_OUTPUT, addr)
    current_ma = int(round(current_a * 1000))
    voltage_mv = int(round(voltage_v * 1000))
    cur_bytes = current_ma.to_bytes(3, 'big')
    vol_bytes = voltage_mv.to_bytes(4, 'big')
    data = bytes([CMD_SET_OUTPUT]) + cur_bytes + vol_bytes
    return can_id, list(data)


def build_read_status(addr):
    can_id = make_can_id(SEND_BASE_READ_STATUS, addr)
    data = [CMD_READ_STATUS, 0, 0, 0, 0, 0, 0, 0]
    return can_id, data


def build_set_power(addr, power_on):
    can_id = make_can_id(SEND_BASE_SET_POWER, addr)
    data = [CMD_SET_POWER, 0, 0, 0, 0, 0, 0, POWER_ON if power_on else POWER_OFF]
    return can_id, data


def build_read_set_voltage(addr):
    can_id = make_can_id(SEND_BASE_READ_SET_V, addr)
    return can_id, []


def build_read_set_current(addr):
    can_id = make_can_id(SEND_BASE_READ_SET_I, addr)
    return can_id, []


def build_read_input_voltage(addr):
    can_id = make_can_id(SEND_BASE_READ_INPUT_V, addr)
    data = [0x31, 0, 0, 0, 0, 0, 0, 0]
    return can_id, data


def build_read_temperature(addr):
    can_id = make_can_id(SEND_BASE_READ_TEMP, addr)
    return can_id, []


def build_current_sharing(enable):
    can_id = SEND_BASE_CURRENT_SHARE
    data = [0, 0, 0, 0xAA if enable else 0x55, 0, 0]
    return can_id, data


def build_find_module(addr):
    can_id = make_can_id(SEND_BASE_FIND_MODULE, addr)
    data = [0, 0, 0, 0x55, 0, 0, 0, 0]
    return can_id, data


def parse_status_response(data):
    if len(data) < 8:
        return None
    current_raw = (data[2] << 8) | data[3]
    voltage_raw = (data[4] << 8) | data[5]
    status_hi = data[6]
    status_lo = data[7]
    output_current = current_raw / 10.0
    output_voltage = voltage_raw / 10.0
    info = parse_status_bytes(status_hi, status_lo)
    return {
        'output_voltage': output_voltage,
        'output_current': output_current,
        'status_hi': status_hi,
        'status_lo': status_lo,
        **info,
    }


def parse_status_bytes(status_hi, status_lo):
    faults = []
    mode = "恒压"
    power_on = True

    if status_lo & 0x01:
        power_on = False
    if status_lo & 0x02:
        faults.append("模块故障")
    if status_lo & 0x04:
        mode = "恒流"
    if status_lo & 0x08:
        faults.append("风扇故障")
    if status_lo & 0x10:
        faults.append("输入过压")
    if status_lo & 0x20:
        faults.append("输入欠压")
    if status_lo & 0x40:
        faults.append("输出过压")
    if status_lo & 0x80:
        faults.append("输出欠压")

    if status_hi & 0x01:
        faults.append("过流保护")
    if status_hi & 0x02:
        faults.append("过温保护")
    if status_hi & 0x04:
        power_on = False

    return {
        'mode': mode,
        'power_on': power_on,
        'fault': "；".join(faults) if faults else "正常",
        'has_fault': len(faults) > 0,
    }


def parse_set_voltage_response(data):
    if len(data) < 8:
        return None
    raw = (data[6] << 8) | data[7]
    return raw / 10.0


def parse_set_current_response(data):
    if len(data) < 2:
        return None
    raw = (data[0] << 8) | data[1]
    return raw / 10.0


def parse_input_voltage_response(data):
    if len(data) < 8:
        return None
    vab = ((data[2] << 8) | data[3]) / 32.0
    vbc = ((data[4] << 8) | data[5]) / 32.0
    vca = ((data[6] << 8) | data[7]) / 32.0
    non_zero = [v for v in (vab, vbc, vca) if v > 0]
    if non_zero:
        avg = sum(non_zero) / len(non_zero)
    else:
        avg = 0.0
    return {'vab': vab, 'vbc': vbc, 'vca': vca, 'avg': avg}


def parse_temperature_response(data):
    if len(data) < 6:
        return None
    raw = (data[4] << 8) | data[5]
    return raw / 10.0


def get_response_type(can_id):
    base = extract_base(can_id)
    return RECV_BASE_MAP.get(base)


def format_can_id(can_id):
    return f"0x{can_id:08X}"


def format_data_hex(data):
    return " ".join(f"{b:02X}" for b in data)
