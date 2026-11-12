# -*- coding: utf-8 -*-
"""RU 灵巧系列电源 —— 面向业务的高层设备接口。

数值换算规则（手册「注意事项 8」）：
  通讯收发的都是整型数，实际值 = 整型数 ÷ 10^n，n = 对应的小数点位数。
  电压分母取输入寄存器 106，电流分母取 107。
"""

from . import registers as R
from .modbus import ModbusClient, ModbusError

import time

__all__ = ["RUDevice", "ModbusError", "bits_to_int", "int_to_bits"]


def bits_to_int(bits):
    val = 0
    for i, b in enumerate(bits):
        if b:
            val |= 1 << i
    return val


def int_to_bits(value, count):
    return [bool(value & (1 << i)) for i in range(count)]


class RUDevice:
    def __init__(self, client: ModbusClient):
        self.c = client
        self.v_dec = R.DEFAULT_V_DECIMALS
        self.i_dec = R.DEFAULT_I_DECIMALS
        self.unit_id = client.unit_id
        self.status_supported = None   # None=未探测 True=可用 False=机型不支持 FC02

    # ---------------- 数值换算 ----------------
    def scale_in(self, raw, dec):
        return raw / (10.0 ** dec)

    def scale_out(self, value, dec):
        return int(round(float(value) * (10 ** dec)))

    def to_signed16(self, value):
        value &= 0xFFFF
        return value - 0x10000 if value >= 0x8000 else value

    # ---------------- 读：模拟量 ----------------
    def read_decimals(self):
        """读取电压/电流小数点位数（106、107 连续，一帧搞定）。"""
        regs = self.c.read_input_registers(R.BY_KEY["v_dec"].addr, 2)
        self.v_dec = regs[0] if 0 <= regs[0] <= 4 else R.DEFAULT_V_DECIMALS
        self.i_dec = regs[1] if 0 <= regs[1] <= 4 else R.DEFAULT_I_DECIMALS
        return self.v_dec, self.i_dec

    def read_live(self):
        """读取电压/电流回读值（100、101 连续，一帧搞定 —— 手册示例 4）。"""
        regs = self.c.read_input_registers(R.BY_KEY["v_read"].addr, 2)
        return self.scale_in(regs[0], self.v_dec), self.scale_in(regs[1], self.i_dec)

    def read_voltage(self):
        regs = self.c.read_input_registers(R.BY_KEY["v_read"].addr, 1)
        return self.scale_in(regs[0], self.v_dec)

    def read_current(self):
        regs = self.c.read_input_registers(R.BY_KEY["i_read"].addr, 1)
        return self.scale_in(regs[0], self.i_dec)

    def read_rated(self):
        """额定电压 / 额定电流（103、104 连续）。"""
        regs = self.c.read_input_registers(R.BY_KEY["v_rated"].addr, 2)
        return self.scale_in(regs[0], self.v_dec), self.scale_in(regs[1], self.i_dec)

    def read_software_version(self):
        return self.c.read_input_registers(R.BY_KEY["sw_ver"].addr, 1)[0]

    def read_status(self):
        """读离散输入状态：CC / CV / OVP / OCP / OTP。

        手册只公开了 116、117、120、121、122 五个地址，118/119 未列出。
        手册「注意事项 2」明确要求不要访问列表外地址，因此按两段连续区间
        （116~117、120~122）分别读取，不做 116~122 整段读取。
        """
        a = self.c.read_discrete_inputs(R.BY_KEY["cc"].addr, 2)        # 116, 117
        b = self.c.read_discrete_inputs(R.BY_KEY["ovp_flag"].addr, 3)  # 120 ~ 122
        return {
            "cc": a[0],
            "cv": a[1],
            "ovp": b[0],
            "ocp": b[1],
            "otp": b[2],
        }

    # ---------------- 读：开关量 ----------------
    def read_output_state(self):
        """读输出开关状态 —— 手册示例 2（FC01 @0x0085 x1）。"""
        return self.c.read_coils(R.BY_KEY["output"].addr, 1)[0]

    # 线圈读取方式：实机固件对 FC01 多位读取（count>1）不响应也不回异常帧
    # （与 FC02/FC10 同样的静默行为），手册示例也只有单点读 —— 因此逐个读。
    def read_coils_map(self):
        """逐个读回全部公开线圈。返回 (out, failed_keys)：
        out = {key: bool}，failed_keys = 读取失败的 key 列表（不影响其它）。"""
        out = {}
        failed = []
        for r in R.COILS:
            try:
                out[r.key] = self.c.read_coils(r.addr, 1)[0]
            except ModbusError:
                failed.append(r.key)
        return out, failed

    # ---------------- 读：保持寄存器 ----------------
    def read_settings(self):
        """ID / 电压设定 / 电流设定（148~150 连续）。"""
        regs = self.c.read_holding_registers(R.BY_KEY["addr_id"].addr, 3)
        return {
            "addr_id": regs[0],
            "v_set": self.scale_in(regs[1], self.v_dec),
            "i_set": self.to_signed16(regs[2]) / (10.0 ** self.i_dec),
        }

    def read_holding(self, key):
        r = R.BY_KEY[key]
        return self.c.read_holding_registers(r.addr, 1)[0]

    def write_holding(self, key, value):
        r = R.BY_KEY[key]
        return self.c.write_single_register(r.addr, int(value))

    def read_coil(self, key):
        r = R.BY_KEY[key]
        return self.c.read_coils(r.addr, 1)[0]

    def write_coil(self, key, on):
        r = R.BY_KEY[key]
        return self.c.write_single_coil(r.addr, bool(on))

    # ---------------- 写：核心控制 ----------------
    def set_output(self, on: bool):
        """输出开关（线圈 133）—— 手册示例 1：01 05 00 85 FF00/0000。"""
        return self.write_coil("output", on)

    def set_output_confirmed(self, on: bool, attempts=6, gap=0.2):
        """下发输出开关并等待设备状态真正切换。

        实机在 FC05 应答后继电器/输出回路还要几十~几百毫秒才切到位，
        立即回读会拿到旧值（表现为「开/关日志相反」）。这里重试回读，
        最多约 attempts×gap 秒；超时仍未一致返回 False（命令本身已成功）。
        """
        self.set_output(on)
        for _ in range(attempts):
            time.sleep(gap)
            try:
                if self.read_output_state() == on:
                    return True
            except ModbusError:
                pass
        return False

    # ---------------- 波特率（寄存器 156） ----------------
    # 手册备注1 脚注缺失，实机验证：9600bps 的机器寄存器读回 960，
    # 即原始值 = 波特率 ÷ 10。写入同理 ÷10 后下发。
    BAUD_LIST = [1200, 2400, 4800, 9600, 14400, 19200, 38400, 43000,
                 57600, 115200]

    def read_baud(self):
        """返回 (bps, raw)。bps 无法识别（raw×10 不在支持列表）时为 None。"""
        raw = self.read_holding("baud")
        bps = raw * 10
        return (bps if bps in self.BAUD_LIST else None), raw

    def write_baud(self, bps: int):
        if bps not in self.BAUD_LIST:
            raise ModbusError(
                "不支持的波特率 %d。可选值：%s"
                % (bps, "、".join(str(b) for b in self.BAUD_LIST)))
        self.write_holding("baud", bps // 10)
        return bps // 10

    def set_voltage(self, volts: float):
        """电压设置值（保持寄存器 149）—— 手册示例 6。"""
        raw = self.scale_out(volts, self.v_dec)
        if not 0 <= raw <= 0xFFFF:
            raise ModbusError("电压原始值越界：%d，请检查小数点位数设定" % raw)
        self.write_holding("v_set", raw)
        return raw

    def set_current(self, amps: float):
        """电流设置值（保持寄存器 150）。

        支持定制换相功能：负值 → 输出负相。按手册要求把负数转换成
        16 位补码后取低 2 字节（即标准 int16 表示）。
        """
        raw = self.scale_out(amps, self.i_dec)
        if not -0x8000 <= raw <= 0x7FFF:
            raise ModbusError("电流原始值越界：%d，请检查小数点位数设定" % raw)
        self.write_holding("i_set", raw & 0xFFFF)
        return raw & 0xFFFF

    def set_voltage_current(self, volts: float, amps: float):
        """149、150 连续，用一条 FC10 同时下发，减少报文数。"""
        v_raw = self.scale_out(volts, self.v_dec)
        i_raw = self.scale_out(amps, self.i_dec)
        if not 0 <= v_raw <= 0xFFFF:
            raise ModbusError("电压原始值越界：%d" % v_raw)
        if not -0x8000 <= i_raw <= 0x7FFF:
            raise ModbusError("电流原始值越界：%d" % i_raw)
        self.c.write_multiple_registers(R.BY_KEY["v_set"].addr,
                                        [v_raw, i_raw & 0xFFFF])
        return v_raw, i_raw & 0xFFFF

    def apply(self, volts: float, amps: float, enable_output=True):
        """按手册推荐的执行顺序：设定电压 → 设定电流 → 开启输出。

        三步都用手册示例对应的单点写（FC06 写寄存器 / FC05 写线圈）。
        不用 FC10：手册示例未出现 FC10，部分固件对它不响应也不回异常帧，
        表现为「下发没反应」。
        手册「注意事项 6」：指令中应包含开启指令、设置电压、设置电流三个基本操作。
        """
        v_raw = self.set_voltage(volts)
        i_raw = self.set_current(amps)
        if enable_output:
            self.set_output(True)
        return v_raw, i_raw

    def set_protection(self, ovp_en=None, ovp_val=None, ocp_en=None, ocp_val=None):
        """过压/过流保护。值为 None 的项不动。返回本次操作的说明列表。"""
        acts = []
        if ovp_en is not None:
            self.write_coil("ovp_en", ovp_en)
            acts.append("OVP 允许 = %s" % ("开" if ovp_en else "关"))
        if ocp_en is not None:
            self.write_coil("ocp_en", ocp_en)
            acts.append("OCP 允许 = %s" % ("开" if ocp_en else "关"))
        if ovp_val is not None:
            raw = self.scale_out(ovp_val, self.v_dec)
            self.write_holding("ovp_val", raw)
            acts.append("OVP 值 = %sV (raw %d)" % (ovp_val, raw))
        if ocp_val is not None:
            raw = self.scale_out(ocp_val, self.i_dec)
            self.write_holding("ocp_val", raw)
            acts.append("OCP 值 = %sA (raw %d)" % (ocp_val, raw))
        return acts

    def set_device_id(self, new_id: int):
        """修改设备地址（保持寄存器 148）。改动立即生效，需按新地址重新连接。"""
        if not 1 <= int(new_id) <= 255:
            raise ModbusError("设备地址应在 1~255（0 为广播地址，不可作为设备地址）")
        self.write_holding("addr_id", int(new_id))
        return int(new_id)

    # ---------------- 组合：一次 READ 全量快照 ----------------
    def poll_snapshot(self):
        """读取监控页所需的全部数据。相邻寄存器已尽量合并成少量报文。"""
        snap = {}
        regs = self.c.read_input_registers(R.BY_KEY["v_read"].addr, 2)   # 100,101
        v_dec, i_dec = self.v_dec, self.i_dec
        snap["v_read"] = self.scale_in(regs[0], v_dec)
        snap["i_read"] = self.scale_in(regs[1], i_dec)

        rated = self.c.read_input_registers(R.BY_KEY["v_rated"].addr, 2)  # 103,104
        snap["v_rated"] = self.scale_in(rated[0], v_dec)
        snap["i_rated"] = self.scale_in(rated[1], i_dec)

        dec = self.c.read_input_registers(R.BY_KEY["v_dec"].addr, 2)      # 106,107
        snap["v_dec"], snap["i_dec"] = dec[0], dec[1]

        try:
            snap["sw_ver"] = self.read_software_version()
        except ModbusError:
            snap["sw_ver"] = None

        # 状态位（FC02 读离散输入）。部分机型不响应 FC02（读寄存器正常），
        # 失败一次就记下来不再重试，避免每轮轮询都超时刷屏。
        if self.status_supported is not False:
            try:
                st = self.read_status()
                self.status_supported = True
                snap.update({("st_" + k): v for k, v in st.items()})
            except ModbusError:
                if self.status_supported is None:
                    self.status_supported = False
                    snap["st_unsupported"] = True

        try:
            snap["output"] = self.read_output_state()
        except ModbusError:
            snap["output"] = None

        return snap
