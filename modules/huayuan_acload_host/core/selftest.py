# -*- coding: utf-8 -*-
"""
协议栈自测 —— 不连真机也能验证实现是否正确。

运行：  python selftest.py
"""

from __future__ import annotations

import random
import sys
import traceback

from . import modbus_rtu as mb
from . import registers as rg
from .device import ACFeedbackLoad, RangeError

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s%s" % ("OK" if cond else "!!", name, ("  -> " + detail) if detail and not cond else ""))


# --------------------------------------------------------------------------

def t_crc() -> None:
    print("\n[1] CRC16/Modbus")
    check("查表法与逐位法结果一致",
          all(mb.crc16(bytes([i]) * (i % 37 + 1)) == mb.crc16_bitwise(bytes([i]) * (i % 37 + 1))
              for i in range(256)))
    rnd = [bytes(random.randrange(256) for _ in range(random.randrange(4, 40))) for _ in range(400)]
    check("随机数据两法一致",
          all(mb.crc16(d) == mb.crc16_bitwise(d) for d in rnd))
    # 黄金向量：来自标准 Modbus 报文示例，CRC 低字节在前
    vec = bytes.fromhex("0110000400020400000000")
    check("黄金向量 01 10 00 04 00 02 04 00 00 00 00 -> CRC F2 5C",
          mb.hexs(mb.append_crc(vec)).endswith("F2 5C"),
          "实际 %s" % mb.hexs(mb.append_crc(vec)))
    check("check_crc 能识破篡改",
          not mb.check_crc(mb.append_crc(vec)[:-1] + bytes([mb.append_crc(vec)[-1] ^ 0xFF])))


def t_frames() -> None:
    print("\n[2] 帧构造与长度推算")
    f = mb.build_read_registers(1, 0x60, 0x21)
    check("FC03 帧头正确", mb.hexs(f[:6]) == "01 03 00 60 00 21", mb.hexs(f))
    check("FC03 帧 8 字节且 CRC 自洽", len(f) == 8 and mb.check_crc(f))
    f2 = mb.build_write_single(3, 0x20, 1)
    check("FC06 帧正确", mb.hexs(f2[:6]) == "03 06 00 20 00 01" and mb.check_crc(f2), mb.hexs(f2))
    f3 = mb.build_write_multiple(1, 0x38, [0x0000, 0x2710])
    check("FC10 帧正确", mb.hexs(f3[:11]) == "01 10 00 38 00 02 04 00 00 27 10", mb.hexs(f3))
    check("读 33 个寄存器响应长 71 字节", mb.read_response_len(33) == 71)
    check("写响应长 8 字节", mb.write_response_len() == 8)
    check("异常响应长 5 字节", mb.exception_response_len() == 5)
    check("MBAP 响应长度（无 CRC，地址在头里）",
          mb.read_response_len(33, True) == 75 and mb.write_response_len(True) == 12
          and mb.exception_response_len(True) == 9 and mb.fc_index(True) == 7)
    # 本地拦截
    for bad in (lambda: mb.build_write_single(1, 0x20, 70000),
                lambda: mb.build_read_registers(1, 0x60, 0),
                lambda: mb.build_read_registers(1, 0x60, 200)):
        try:
            bad()
            check("非法参数应被本地拦截", False)
            break
        except ValueError:
            pass
    else:
        check("非法参数均被本地拦截（不发给设备）", True)


def t_u32() -> None:
    print("\n[3] 32 位编解码")
    for v in (0, 1, 0xFFFF, 0x10000, 0x02710000, 0xFFFFFFFF, 199999):
        hi, lo = mb.u32_to_words(v)
        check("往返 0x%08X" % v, mb.words_to_u32(hi, lo) == v)
    check("默认高字在前", mb.u32_to_words(0x11223344) == [0x1122, 0x3344])
    check("字序可翻转", mb.u32_to_words(0x11223344, True) == [0x3344, 0x1122])


def t_units() -> None:
    print("\n[4] 单位换算（最易踩的坑）")
    check("功率 1000W -> raw 10000 (0.1W)", rg.p2raw(1000.0) == 10000)
    check("功率不是 0.0001kW 口径", rg.p2raw(1000.0) != 10000000)
    check("电流 5A -> raw 5000 (0.001A)", rg.a2raw(5.0) == 5000)
    check("电压 220V -> raw 220000 (0.001V)", rg.v2raw(220.0) == 220000)
    check("版本号 104 -> V1.4", rg.decode_version(104) == "V1.4")
    check("通道 n 功率地址 = 0x40+2(n-1)",
          rg.ch_power_addr(1) == 0x40 and rg.ch_power_addr(15) == 0x5C and rg.ch_power_addr(4) == 0x46)
    check("A/B/C 电流设定地址", [rg.phase_i_set_addr(c) for c in (1, 2, 3)] == [0xE0, 0xE2, 0xE4])


def _make_client(port, mbap=False, unit=1):
    tp = mb.TcpTransport("127.0.0.1", port)
    tp.mbap = mbap
    return mb.ModbusClient(tp, unit=unit, timeout=0.8, inter_frame_delay=0.0)


def t_end_to_end() -> None:
    print("\n[5] 端到端（真客户端 <-> 模拟从站）")
    from .simulator import SlaveSimulator

    for mbap in (False, True):
        tag = "MBAP" if mbap else "RTU-over-TCP"
        port = random.randint(21000, 26000)
        sim = SlaveSimulator(unit=1, mbap=mbap, port=port).start()
        try:
            c = _make_client(port, mbap)
            d = ACFeedbackLoad(c, limits={"power": 50000.0, "current": 100.0, "voltage": 300.0})

            check("[%s] 读版本号 = 104 (V1.4)" % tag, c.read_registers(0x61, 1)[0] == 104)
            check("[%s] 读序列号 = 20241030" % tag, d.read_serial() == 20241030)

            s0 = d.read_status_block()["snapshot"]
            check("[%s] 初始未运行" % tag, not s0.running and s0.power_total == 0.0)
            check("[%s] 版本名解析" % tag, s0.version_name == "V1.4")

            d.set_mode_op(1)          # 三相独立
            d.set_mode_ctrl(0)        # 功率模式
            d.set_channel_power(1, 1000.0)     # A 相 1000W
            d.set_channel_power(2, 2000.0)     # B 相 2000W
            d.set_output(True)

            s1 = d.read_status_block()["snapshot"]
            check("[%s] 状态：运行中" % tag, s1.running)
            check("[%s] 操作模式回读 = 三相独立" % tag, s1.mode_op == 1 and s1.mode_op_name == "三相独立")
            check("[%s] 控制模式回读 = 功率模式" % tag, s1.mode_ctrl == 0)
            check("[%s] A 相电压约 220V" % tag, abs(s1.voltage[0] - 220.0) < 0.5,
                  "实际 %.3f" % s1.voltage[0])
            check("[%s] A 相功率约 1000W" % tag, abs(s1.power_total - 3000.0) < 20.0,
                  "实际总功率 %.3f" % s1.power_total)

            ch = d.read_channels_block()
            check("[%s] 通道 1 功率约 1000W" % tag, abs(ch[1].power - 1000.0) < 10.0,
                  "实际 %.3f" % ch[1].power)
            check("[%s] 通道 2 功率约 2000W" % tag, abs(ch[2].power - 2000.0) < 20.0,
                  "实际 %.3f" % ch[2].power)
            check("[%s] 通道 4 无输出" % tag, ch[4].power == 0.0)
            check("[%s] 通道 15 明细可读" % tag, 15 in ch)

            # 电流模式
            d.set_mode_ctrl(1)
            d.set_mode_op(1)
            d.set_channel_current(2, 4.0)
            s2 = d.read_status_block()["snapshot"]
            check("[%s] 控制模式回读 = 电流模式" % tag, s2.mode_ctrl == 1)
            check("[%s] A 相电流约 0A / B 相约 4A" % tag,
                  s2.current[0] < 0.01 and abs(s2.current[1] - 4.0) < 0.05,
                  "收到 %s" % (s2.current,))

            # 故障
            sim.fault_bits = (1 << 0) | (1 << 6)
            s3 = d.read_status_block()["snapshot"]
            check("[%s] 故障标志置位" % tag, s3.has_fault)
            check("[%s] 故障位解析 = 电流过流 + 过温保护" % tag,
                  s3.active_faults() == ["电流过流", "过温保护"], str(s3.active_faults()))
            d.clear_fault()
            s4 = d.read_status_block()["snapshot"]
            check("[%s] 清除故障后故障消失" % tag, not s4.has_fault and s4.fault_bits == 0)

            # 下发异常
            d.set_output(False)
            s5 = d.read_status_block()["snapshot"]
            check("[%s] 关输出后运行位清零" % tag, not s5.running)

            # 本地量程拦截
            try:
                d.set_channel_power(1, 99999.0)
                check("[%s] 超限值应被本地拦截" % tag, False)
            except RangeError:
                check("[%s] 超限值被本地拦截（不发报文）" % tag, True)
            c.close()
        finally:
            sim.stop()

    # 异常响应解析（假从站回非法功能码）
    print("\n[6] 异常响应解析")
    port = random.randint(26001, 29000)
    sim = SlaveSimulator(unit=1, port=port).start()
    try:
        c = _make_client(port)
        raw_resp = bytes((1, 0x83, 0x02)) + bytes((mb.crc16(bytes((1, 0x83, 0x02))) & 0xFF,
                                                   (mb.crc16(bytes((1, 0x83, 0x02))) >> 8) & 0xFF))
        try:
            c._check_exception(raw_resp)
            check("异常响应应抛 ModbusExceptionResponse", False)
        except mb.ModbusExceptionResponse as e:
            check("异常响应解析出异常码 0x02", e.code == 0x02 and "非法数据地址" in str(e))
        c.close()
    finally:
        sim.stop()

    # 地址偏移
    print("\n[7] 地址偏移开关")
    port = random.randint(29001, 32000)
    sim = SlaveSimulator(unit=1, port=port).start()
    try:
        c = _make_client(port)
        c.offset = -1
        check("offset=-1 时读到的是 0x62 的原始值（0x61 落到 0x60）",
              c.read_registers(0x62, 1)[0] == 104)
        c.offset = 0
        check("offset=0 时 0x61 = 104", c.read_registers(0x61, 1)[0] == 104)
        c.close()
    finally:
        sim.stop()


def main() -> int:
    print("=" * 62)
    print(" 交流回馈式负载上位机 —— 协议栈自测")
    print("=" * 62)
    for fn in (t_crc, t_frames, t_u32, t_units, t_end_to_end):
        try:
            fn()
        except Exception:
            FAIL.append(fn.__name__)
            print("  [!!] %s 抛出异常：" % fn.__name__)
            traceback.print_exc(file=sys.stdout)
    print("\n" + "=" * 62)
    print(" 通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项：")
        for f in FAIL:
            print("   - %s" % f)
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
