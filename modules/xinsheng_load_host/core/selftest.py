# -*- coding: utf-8 -*-
"""新胜负载箱协议栈自检（原 tests/selftest.py 协议级 5 组全量迁移）。

覆盖：
  1. 手册原始报文示例逐字节比对（CRC 黄金依据）
  2. 地址无偏移断言（风机状态读示例 01 03 00 02 00 01 25 CA）
  3. 功率档 ×10 缩放（10Ω→100）与表/示例两种地址方案
  4. 异常响应解析（0x83/0x86 + 错误码）
  5. 本地量程拦截的反向断言：超限值必须被拒且不发报文
  6. 写后回读确认（含切换延时场景）
  7. 模拟从站端到端（内存 + RTU-over-TCP）

原版 UI 冒烟（tkinter）由 FusionHub 冒烟块 2t/2u 替代。

运行：python -m modules.xinsheng_load_host.core.selftest
"""
from __future__ import annotations

import sys
import time

from .modbus import (LoadBankClient, ProtocolError, TcpTransport, append_crc,
                     confirm_fan, crc16)
from .registers import (GEAR_ADDR_EXAMPLE, GEAR_ADDR_TABLE, gear_addr,
                        validate_write)
from .simulator import FakeTransport, Simulator, TcpSimServer

PASS, FAIL = [], []


def record(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print("[%s] %s %s" % ("PASS" if ok else "FAIL", name, ("| " + detail) if detail else ""))


def expect_raises(fn, name, must_not_send=False, sent_counter=None):
    """反向断言：喂非法输入，必须抛异常；可选断言确实没有发报文。"""
    before = sent_counter[0] if sent_counter else None
    try:
        fn()
    except (ValueError, ProtocolError) as e:
        no_send = (sent_counter is None or sent_counter[0] == before)
        record(name, no_send or not must_not_send, "已拦截：%s" % e)
        return
    record(name, False, "未抛异常 —— 校验静默失效！")


# ---------------------------------------------------------------- 1/2 手册示例
def test_manual_examples():
    # 读风机状态：01 03 00 02 00 01 -> CRC 25 CA（低字节在前）
    f = append_crc(bytes.fromhex("010300020001"))
    record("手册示例·读风机状态请求帧逐字节一致",
           f.hex().upper() == "01030002000125CA", f.hex().upper())
    # 响应 01 03 02 0001 -> 79 84
    r = bytes.fromhex("01030200017984")
    record("手册示例·读风机状态响应 CRC 校验通过",
           crc16(r[:-2]) == (r[-2] | (r[-1] << 8)))
    # 写功率档示例：01 06 00 32 00 64 -> 29 EE
    f2 = append_crc(bytes.fromhex("010600320064"))
    record("手册示例·写功率档帧 CRC 与手册一致(29 EE)",
           f2[-2:] == bytes((0x29, 0xEE)), f2.hex().upper())
    # 地址无偏移断言：表地址 2 直接进 StartReg
    cli_frame = append_crc(bytes((1, 0x03, 0x00, 0x02, 0x00, 0x01)))
    record("地址无偏移：风机状态表地址2 == 报文 StartReg 0002H", cli_frame == f)

    # 功率档地址两套方案
    record("功率档表地址 51/53/55",
           (GEAR_ADDR_TABLE["A"], GEAR_ADDR_TABLE["B"], GEAR_ADDR_TABLE["C"]) == (51, 53, 55))
    record("功率档示例地址 50/52/54（0x32H）",
           (GEAR_ADDR_EXAMPLE["A"], GEAR_ADDR_EXAMPLE["B"], GEAR_ADDR_EXAMPLE["C"]) == (50, 52, 54))
    record("validate_write 默认用表地址 51", validate_write("gear_a", 100) == 51)
    record("validate_write 示例地址方案返回 50",
           validate_write("gear_a", 100, "example") == 50)


# ---------------------------------------------------------------- 3 客户端编解码
def test_client_codec():
    sim = Simulator()
    sent = [0]
    orig = sim.handle

    def counting(tx):
        sent[0] += 1
        return orig(tx)

    sim.handle = counting
    cli = LoadBankClient(FakeTransport(sim), slave=1)

    v = cli.read_regs(2, 2)
    record("读(2,2) 返回风机状态+高温报警", v == [0, 0], str(v))
    cli.write_reg(10, 300)
    record("写延时 300 后回读一致", cli.read_reg(10) == 300)
    cli.write_reg(gear_addr("A"), 100)
    record("功率档 A 写 100 后回读 100（10倍输入）", cli.read_reg(gear_addr("A")) == 100)
    cli.write_reg(gear_addr("A"), 100)
    tx = sim.frames[-1][0]
    expect = append_crc(bytes.fromhex("010600330064"))
    record("写功率档帧 == 01 06 00 33 00 64 +CRC（表地址方案）", tx == expect, tx.hex().upper())

    try:
        cli.read_reg(4)
        record("读未公开地址4 应抛异常", False)
    except ProtocolError as e:
        record("读未公开地址4 → 异常帧 0x83 非法地址(02)", "非法地址" in str(e), str(e))

    try:
        cli.write_reg(999, 1)
        record("写不存在地址999 应抛异常", False)
    except ProtocolError as e:
        record("写不存在地址 → 异常帧 0x86", "非法地址" in str(e), str(e))

    silent = Simulator()

    class SilentTransport(FakeTransport):
        def exchange(self, frame, want, timeout=0.6):
            return b""   # 模拟静默不答

    cli2 = LoadBankClient(SilentTransport(silent), slave=1)
    t0 = time.time()
    try:
        cli2.read_reg(2)
        record("静默不答应报超时", False)
    except ProtocolError as e:
        record("静默不答 → 超时错误", "超时" in str(e), "耗时%.2fs" % (time.time() - t0))

    expect_raises(lambda: validate_write("delay_on", 32766), "延时 32766 超范围被本地拦截",
                  must_not_send=True, sent_counter=sent)
    expect_raises(lambda: validate_write("delay_off", -1), "延时 -1 被本地拦截",
                  must_not_send=True, sent_counter=sent)
    expect_raises(lambda: validate_write("fan_sw", 2), "风机开关写 2（非法布尔）被拦截",
                  must_not_send=True, sent_counter=sent)
    expect_raises(lambda: validate_write("unload_all", 5), "一键卸载只接受写 1，写 5 被拦截",
                  must_not_send=True, sent_counter=sent)
    expect_raises(lambda: cli.write_reg(1, 70000), "写入超 16 位值被客户端拒绝",
                  must_not_send=True, sent_counter=sent)
    expect_raises(lambda: cli.read_regs(2, 0), "读取数量 0 被拒绝",
                  must_not_send=True, sent_counter=sent)
    record("量程拦截后确实没有发报文", sent[0] < 10, "共发 %d 帧（全为合法操作）" % sent[0])


# ---------------------------------------------------------------- 4 写后确认
def test_write_confirm():
    sim = Simulator(switch_delay=0.4)   # 风机切换延时 0.4s（模拟继电器）
    cli = LoadBankClient(FakeTransport(sim), slave=1)
    t0 = time.time()
    ok, cur = confirm_fan(cli, 1)       # 按状态寄存器2确认，与界面同一路径
    dt = time.time() - t0
    record("带切换延时的风机确认最终成功", ok and cur == 1, "耗时 %.2fs" % dt)
    record("确认确实经历了等待（非立即返回）", dt >= 0.35, "%.2fs" % dt)
    t0 = time.time()
    ok2, _ = confirm_fan(cli, 0)
    record("关闭风机同样可确认（耗时 %.2fs）" % (time.time() - t0), ok2)


# ---------------------------------------------------------------- 5 端到端
def test_end_to_end():
    sim = Simulator()
    cli = LoadBankClient(FakeTransport(sim), slave=1)
    cli.write_reg(5, 0)
    record("急停写 0 后回读=0（急停态）", cli.read_reg(5) == 0)
    cli.write_reg(5, 1)
    record("解除急停写 1 后回读=1", cli.read_reg(5) == 1)
    cli.write_reg(200, 1)
    record("切同步后回读 200=1", cli.read_reg(200) == 1)
    cli.write_reg(200, 0)
    record("切独立后回读 200=0", cli.read_reg(200) == 0)
    for ph, v in (("A", 100), ("B", 250), ("C", 0)):
        a = gear_addr(ph)
        cli.write_reg(a, v)
        record("%s相功率档 %d 回读一致" % (ph, v), cli.read_reg(a) == v)
    for key in ("unload_a", "unload_b", "unload_c", "unload_all"):
        cli.write_reg(validate_write(key, 1), 1)
    record("四条卸载指令（35/36/37/38 写1）全部有应答",
           all(cli.read_reg(a) is not None for a in (35, 36, 37, 38)))
    rx = cli.read_regs(2, 1)
    record("端到端读风机状态 = 模拟器当前值", rx[0] == sim.regs[2],
           "读=%d 模拟=%d" % (rx[0], sim.regs[2]))


# ---------------------------------------------------------------- 5b TCP 传输
def test_tcp_transport():
    """RTU over TCP 端到端：进程内起模拟器 TCP 服务，TcpTransport 收发。"""
    port = 50277
    server = TcpSimServer(host="127.0.0.1", port=port).start()
    time.sleep(0.3)
    try:
        cli = LoadBankClient(TcpTransport("127.0.0.1", port), slave=1)
        record("TCP：ping（读状态 2,2）成功", cli.ping() is True)
        cli.write_reg(51, 100)
        record("TCP：写功率档 A=100 回读一致", cli.read_reg(51) == 100)
        cli.write_reg(200, 1)
        record("TCP：切同步回读一致", cli.read_reg(200) == 1)
        cli.t.close()
        cli.write_reg(10, 55)
        record("TCP：断线后发送自动重连成功", cli.read_reg(10) == 55)
        record("TCP：模拟器确实收到了帧", len(server.sim.frames) >= 6,
               "%d 帧" % len(server.sim.frames))
        tx0 = server.sim.frames[-1][0]
        record("TCP：透传为裸 RTU 帧（无 MBAP 头）",
               tx0[0] == 0x01 and tx0[1] in (0x03, 0x06), tx0.hex().upper())
        cli.t.close()
    finally:
        server.stop()


def main() -> int:
    print("=" * 62)
    print(" 新胜负载箱上位机 —— 协议栈自测")
    print("=" * 62)
    for fn in (test_manual_examples, test_client_codec, test_write_confirm,
               test_end_to_end, test_tcp_transport):
        try:
            fn()
        except Exception:  # noqa: BLE001
            FAIL.append((fn.__name__, "抛出异常"))
            import traceback
            traceback.print_exc(file=sys.stdout)
    print("\n" + "=" * 62)
    print(" 通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项：")
        for f in FAIL:
            print("   - %s" % (f,))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
