"""NXR 系列充电模块协议编解码（协议栈手写实现）。

覆盖两层：
1) NXR 应用层：29 位扩展帧 ID 组装/解析 + 数据域(功能码/寄存器/数据) 编解码。
2) UT-6502 链路层：13 字节固定格式封包/解包（帧信息1B + ID4B + 数据8B）。

参考：
- 《NXR系列充电模块通讯协议V1.48（客户版）》
- 《UT-6502 系列 TCP/IP 转 2 口 CANBUS 协议转换器使用说明书》
"""

import struct
from collections import namedtuple

# ============================================================ 常量
PROTNO_DEFAULT = 0x060        # 协议号，9bit
PTP_POINT = 1                 # 点对点
PTP_BROADCAST = 0             # 广播

ADDR_MODULE_MIN = 0x00
ADDR_MODULE_MAX = 0x3F        # 模块地址 0~63
ADDR_MONITOR = 0xF0           # 监控(上位机)地址
ADDR_BROADCAST = 0xFF         # 广播地址
ADDR_GROUP_BROADCAST = 0xFE   # 组内广播
ADDR_GROUP_EXT_BASE = 0xFD    # 扩展组广播：DSTADDR = 0xFD - group

FUNC_SET = 0x03               # 设置模块参数
FUNC_READ = 0x10              # 读取模块数据

RESP_FLOAT = 0x41             # 应答：浮点
RESP_INT = 0x42               # 应答：整型
ERR_OK = 0xF0                 # 应答：正常
ERR_FAIL = 0xF2               # 应答：设置失败

MAX_MODULES = 64
GROUP_MAX = 7
GROUP_EXT_MAX = 59            # 扩展组最多 60 组：组号 0~59 对应 DSTADDR 0xFD~0xC2

# ============================================================ 29 位 ID
# bit28-20 PROTNO(9) | bit19 PTP(1) | bit18-11 DSTADDR(8) | bit10-3 SRCADDR(8) | bit2-0 Group(3)
_ID_MASK = 0x1FFFFFFF

CanId = namedtuple("CanId", "protno ptp dst src group")


def make_id(ptp: int, dst: int, src: int = ADDR_MONITOR, group: int = 0,
            protno: int = PROTNO_DEFAULT) -> int:
    """组装 29 位扩展帧标识符。"""
    return (((protno & 0x1FF) << 20)
            | ((ptp & 0x01) << 19)
            | ((dst & 0xFF) << 11)
            | ((src & 0xFF) << 3)
            | (group & 0x07)) & _ID_MASK


def parse_id(can_id: int) -> CanId:
    """解析 29 位扩展帧标识符。"""
    can_id &= _ID_MASK
    return CanId(
        protno=(can_id >> 20) & 0x1FF,
        ptp=(can_id >> 19) & 0x01,
        dst=(can_id >> 11) & 0xFF,
        src=(can_id >> 3) & 0xFF,
        group=can_id & 0x07,
    )


def group_broadcast_addr(group: int) -> int:
    """组内广播(0~7组)地址 0xFE；扩展组(≥8)地址 0xFD-group。

    注意：0xFE 仅覆盖 0~7 组；组号 ≥8 时使用扩展广播地址（此时 Group 位填 0）。
    """
    if group <= GROUP_MAX:
        return ADDR_GROUP_BROADCAST
    return ADDR_GROUP_EXT_BASE - group


def make_group_broadcast_id(group: int, src: int = ADDR_MONITOR,
                            ptp: int = PTP_BROADCAST) -> int:
    """构造组播/扩展组播 ID。

    - 0~7 组：DSTADDR=0xFE，Group 位填组号；
    - ≥8 组：DSTADDR=0xFD-group，Group 位填 0（按手册）。
    """
    if group <= GROUP_MAX:
        return make_id(ptp, ADDR_GROUP_BROADCAST, src, group)
    return make_id(ptp, ADDR_GROUP_EXT_BASE - group, src, 0)


# ============================================================ 数据域编解码
def _u16(v: int) -> bytes:
    return bytes([(v >> 8) & 0xFF, v & 0xFF])


def build_read(reg: int, dst: int, src: int = ADDR_MONITOR, group: int = 0,
               ptp: int = PTP_POINT) -> (int, bytes):
    """构造读取帧：10 00 [寄存器] 00000000。"""
    data = bytes([FUNC_READ, 0x00]) + _u16(reg) + b"\x00\x00\x00\x00"
    return make_id(ptp, dst, src, group), data


def build_set_float(reg: int, value: float, dst: int, src: int = ADDR_MONITOR,
                    group: int = 0, ptp: int = PTP_POINT) -> (int, bytes):
    """构造浮点设置帧：03 00 [寄存器] IEEE754(value)。"""
    data = bytes([FUNC_SET, 0x00]) + _u16(reg) + struct.pack(">f", float(value))
    return make_id(ptp, dst, src, group), data


def build_set_int(reg: int, value: int, dst: int, src: int = ADDR_MONITOR,
                  group: int = 0, ptp: int = PTP_POINT) -> (int, bytes):
    """构造整型设置帧：03 00 [寄存器] 32bit(value，大端)。"""
    data = bytes([FUNC_SET, 0x00]) + _u16(reg) + struct.pack(">I", int(value) & 0xFFFFFFFF)
    return make_id(ptp, dst, src, group), data


# 语义化封装 ------------------------------------------------------------
def build_power(on: bool, dst: int, **kw) -> (int, bytes):
    from .registers import POWER_ON, POWER_OFF
    return build_set_int(0x0030, POWER_ON if on else POWER_OFF, dst, **kw)


def build_set_voltage(volts: float, dst: int, **kw) -> (int, bytes):
    return build_set_float(0x0021, volts, dst, **kw)


def build_set_current_ratio(ratio: float, dst: int, **kw) -> (int, bytes):
    """限流点按百分比下发：需求电流/额定电流。"""
    return build_set_float(0x0022, ratio, dst, **kw)


def build_set_current_int(amps: float, dst: int, **kw) -> (int, bytes):
    """整型电流下发：值 = 电流 × 1024。"""
    return build_set_int(0x001B, int(round(amps * 1024)), dst, **kw)


def build_set_output_power(ratio: float, dst: int, **kw) -> (int, bytes):
    """输出功率按额定比例下发（0.1~1，V1.48 新增 0x0020）。"""
    return build_set_float(0x0020, ratio, dst, **kw)


def build_set_ovp_point(volts: float, dst: int, **kw) -> (int, bytes):
    """输出过压点 0x0023（无特殊需求不设置）。"""
    return build_set_float(0x0023, volts, dst, **kw)


def build_set_ovp_related(allow: bool, dst: int, **kw) -> (int, bytes):
    """输出过压保护关联 0x003E：0x00000000 允许 / 0x00010000 禁止。"""
    from .registers import OVP_RELATED_ALLOW, OVP_RELATED_DENY
    return build_set_int(0x003E, OVP_RELATED_ALLOW if allow else OVP_RELATED_DENY, dst, **kw)


def build_set_group(group: int, dst: int, **kw) -> (int, bytes):
    """设置组号 0x001E：仅 byte7 低 3 位有效（0~7）。"""
    return build_set_int(0x001E, int(group) & 0x07, dst, **kw)


def build_set_addr_mode(dip: bool, dst: int, **kw) -> (int, bytes):
    """设置地址分配方式 0x001F：0x00010000 拨码 / 0x00000000 自动。"""
    from .registers import ADDR_MODE_DIP, ADDR_MODE_AUTO
    return build_set_int(0x001F, ADDR_MODE_DIP if dip else ADDR_MODE_AUTO, dst, **kw)


def build_set_input_mode(dc: bool, dst: int, **kw) -> (int, bytes):
    """设置输入模式 0x0046：0x01 交流 / 0x02 直流（需断电重启生效）。"""
    from .registers import INPUT_MODE_AC, INPUT_MODE_DC
    return build_set_int(0x0046, INPUT_MODE_DC if dc else INPUT_MODE_AC, dst, **kw)


def build_set_altitude(meters: int, dst: int, **kw) -> (int, bytes):
    """设置工作海拔 0x0017：1000~5000m。"""
    return build_set_int(0x0017, int(meters), dst, **kw)


def build_ovp_reset(dst: int, **kw) -> (int, bytes):
    """过压复位 0x0031：0x00010000 = 复位。"""
    from .registers import OVP_RESET_VALUE
    return build_set_int(0x0031, OVP_RESET_VALUE, dst, **kw)


def build_short_reset(dst: int, **kw) -> (int, bytes):
    """短路复位 0x0044：0x00010000 = 复位。"""
    from .registers import SHORT_RESET_VALUE
    return build_set_int(0x0044, SHORT_RESET_VALUE, dst, **kw)


Response = namedtuple("Response", "resp_type err reg value raw")


def parse_response(data: bytes):
    """解析应答帧数据域：类型 错误码 寄存器 数据。

    返回 Response；若帧长不足 8 字节返回 None。
    """
    if len(data) < 8:
        return None
    resp_type, err = data[0], data[1]
    reg = (data[2] << 8) | data[3]
    raw = bytes(data[4:8])
    if resp_type == RESP_FLOAT:
        value = struct.unpack(">f", raw)[0]
    elif resp_type == RESP_INT:
        value = struct.unpack(">I", raw)[0]
    else:
        value = None
    return Response(resp_type=resp_type, err=err, reg=reg, value=value, raw=raw)


def is_response_ok(resp: Response) -> bool:
    return resp is not None and resp.err == ERR_OK


def is_set_failed(resp: Response) -> bool:
    """设置帧被从站拒绝（回执 F2）。"""
    return resp is not None and resp.err == ERR_FAIL


# ============================================================ UT-6502 链路层
# 13 字节固定格式：帧信息(1) + ID(4, 大端) + 数据(8)
# 帧信息位: bit7 FF(1扩展/0标准) | bit6 RTR(1远程/0数据) | bit5-4 保留0 | bit3-0 DLC
UT6502_FRAME_LEN = 13

FI_EXTENDED = 0x80
FI_REMOTE = 0x40


def ut6502_encode(can_id: int, data: bytes, extended: bool = True,
                  remote: bool = False) -> bytes:
    """把 CAN 报文封成 UT-6502 13 字节固定格式。"""
    dlc = min(len(data), 8)
    info = (FI_EXTENDED if extended else 0x00) | (FI_REMOTE if remote else 0x00) | (dlc & 0x0F)
    body = bytes(data[:dlc]).ljust(8, b"\x00")
    return bytes([info]) + struct.pack(">I", can_id & _ID_MASK) + body


def ut6502_decode(buf: bytes):
    """解析单条 13 字节固定格式帧，返回 (can_id, data, info)；长度不足返回 None。"""
    if len(buf) < UT6502_FRAME_LEN:
        return None
    info = buf[0]
    can_id = struct.unpack(">I", buf[1:5])[0]
    dlc = info & 0x0F
    dlc = min(dlc, 8)
    return can_id, bytes(buf[5:5 + dlc]), info


class Ut6502StreamParser:
    """TCP 流式解析：按 13 字节对齐切分，丢弃无法对齐的残帧。"""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes):
        self._buf.extend(chunk)
        frames = []
        while len(self._buf) >= UT6502_FRAME_LEN:
            raw = bytes(self._buf[:UT6502_FRAME_LEN])
            del self._buf[:UT6502_FRAME_LEN]
            parsed = ut6502_decode(raw)
            if parsed:
                frames.append(parsed)
        return frames

    def reset(self):
        self._buf.clear()


# ============================================================ 便捷判断
def is_module_response(can_id: int) -> bool:
    """是否为模块发给监控(0xF0)的应答帧。"""
    cid = parse_id(can_id)
    return cid.src <= ADDR_MODULE_MAX and cid.dst == ADDR_MONITOR


def is_from_monitor(can_id: int) -> bool:
    return parse_id(can_id).src == ADDR_MONITOR


def fmt_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)