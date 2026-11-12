# -*- coding: utf-8 -*-
"""RU 灵巧系列电源 —— 寄存器映射表。

来源：《RU 灵巧系列电源串口通讯操作流程》
地址定义为「报文实际地址」，无偏移（已用手册原始报文样例反推确认：
  `01 04 00 64 00 01 70 15` 读取电压回读值，地址 0x0064 = 100，与文档一致）。

注意：不同功能码各自独立的地址空间，同一个十进制地址在不同空间含义不同
（例如 144 = 0x0090 既是「输入寄存器·软件版本号」，也是「线圈·开关量功能开关」）。
"""

from dataclasses import dataclass, field

# ---------------- 地址空间 ----------------
SPACE_INPUT = "input"        # 功能码 04 读
SPACE_DISCRETE = "discrete"  # 功能码 02 读
SPACE_COIL = "coil"          # 功能码 01 读 / 05 写单个 / 0F 写多个
SPACE_HOLDING = "holding"    # 功能码 03 读 / 06 写单个 / 10 写多个


@dataclass
class Register:
    key: str
    name: str
    addr: int
    space: str
    access: str = "R"          # R / W / RW
    unit: str = ""
    rng: tuple = None          # (min, max) 原始整型范围
    default: int = None
    enum: dict = field(default_factory=dict)
    desc: str = ""

    @property
    def hex_addr(self) -> str:
        return "0x%04X" % self.addr


# ---------------- 输入寄存器（只读，FC04） ----------------
INPUT_REGISTERS = [
    Register("v_read", "电压输出（回读值）", 100, SPACE_INPUT, "R",
             unit="×10^-n V", desc="需除以 10 的「电压小数点」次幂"),
    Register("i_read", "电流输出（回读值）", 101, SPACE_INPUT, "R",
             unit="×10^-n A", desc="需除以 10 的「电流小数点」次幂"),
    Register("v_rated", "额定电压", 103, SPACE_INPUT, "R", unit="×10^-n V"),
    Register("i_rated", "额定电流", 104, SPACE_INPUT, "R", unit="×10^-n A"),
    Register("v_dec", "电压小数点", 106, SPACE_INPUT, "R", unit="位",
             rng=(0, 4), default=1),
    Register("i_dec", "电流小数点", 107, SPACE_INPUT, "R", unit="位",
             rng=(0, 4), default=2),
    Register("sw_ver", "软件版本号", 144, SPACE_INPUT, "R"),
]

# ---------------- 离散输入（只读，FC02） ----------------
DISCRETE_INPUTS = [
    Register("cc", "稳流状态 (CC)", 116, SPACE_DISCRETE, "R"),
    Register("cv", "稳压状态 (CV)", 117, SPACE_DISCRETE, "R"),
    Register("ovp_flag", "输出过压保护 (OVP)", 120, SPACE_DISCRETE, "R"),
    Register("ocp_flag", "输出过流保护 (OCP)", 121, SPACE_DISCRETE, "R"),
    Register("otp_flag", "过温保护 (OTP)", 122, SPACE_DISCRETE, "R"),
]

# ---------------- 线圈（读写，FC01/05/0F） ----------------
COILS = [
    Register("output", "输出开关", 133, SPACE_COIL, "RW", enum={0: "关", 1: "开"}),
    Register("lock", "锁定操作", 134, SPACE_COIL, "RW", enum={0: "未锁", 1: "锁定"}),
    Register("ovp_en", "输出过压保护允许", 136, SPACE_COIL, "RW", enum={0: "禁止", 1: "允许"}),
    Register("ocp_en", "输出过流保护允许", 137, SPACE_COIL, "RW", enum={0: "禁止", 1: "允许"}),
    Register("comm_save", "通讯存储允许", 141, SPACE_COIL, "RW", enum={0: "禁止", 1: "允许"}),
    Register("boot_output", "开机输出", 142, SPACE_COIL, "RW", enum={0: "关", 1: "开"}),
    Register("dio_func", "开关量功能开关", 144, SPACE_COIL, "RW"),
    Register("dio_en", "开关量状态使能", 145, SPACE_COIL, "RW"),
    Register("dio_out", "开关量输出内容", 146, SPACE_COIL, "RW"),
    Register("dio_in", "开关量输入电平", 147, SPACE_COIL, "RW"),
]

# ---------------- 保持寄存器（读写，FC03/06/10） ----------------
HOLDING_REGISTERS = [
    Register("addr_id", "ID（设备地址）", 148, SPACE_HOLDING, "RW", rng=(1, 255), default=1),
    Register("v_set", "电压设置值", 149, SPACE_HOLDING, "RW", unit="×10^-n V"),
    Register("i_set", "电流设置值", 150, SPACE_HOLDING, "RW", unit="×10^-n A",
             desc="负数 = 定制换相功能输出负相（取补码低 2 字节）"),
    Register("baud", "通讯波特率", 156, SPACE_HOLDING, "RW"),
    Register("ovp_val", "输出过压保护值", 157, SPACE_HOLDING, "RW"),
    Register("ocp_val", "输出过流保护值", 158, SPACE_HOLDING, "RW"),
    Register("can_baud", "CAN 波特率", 186, SPACE_HOLDING, "RW"),
]

ALL_REGISTERS = INPUT_REGISTERS + DISCRETE_INPUTS + COILS + HOLDING_REGISTERS

BY_KEY = {r.key: r for r in ALL_REGISTERS}

# ---------------- 波特率代码表（面板 BAUD 可设，仅作对照提示） ----------------
BAUD_RATES = [1200, 2400, 4800, 9600, 14400, 19200, 38400, 43000, 57600, 115200]
DEFAULT_BAUD = 9600

# 广播地址：所有设备都会响应，写操作可用于群发
BROADCAST_ADDR = 0

# 电压/电流小数点缺省值（读取失败时的兜底）
DEFAULT_V_DECIMALS = 1
DEFAULT_I_DECIMALS = 2
