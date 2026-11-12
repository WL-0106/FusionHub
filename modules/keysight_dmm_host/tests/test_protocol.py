# -*- coding: utf-8 -*-
"""
自动化验证（一键回归）
====================
运行方式（无需 pytest，纯标准库 unittest）：
    python -m unittest discover -s tests -v

覆盖（七步流程第6步：全命令读写比对 + 边界/异常路径，协议栈改动必须重跑）：
    正常路径：全查询命令读数比对、全设置命令下发、可读可写回读、语义接口单位/类型
    异常路径：错帧重同步、超时重发上限退出、从站断开不卡死、
              SCPI 错误码人话映射、命令队列上限拒绝、参数越界拒绝
    半包/粘包：分片响应重组、多命令粘连写入
"""
from __future__ import annotations

import threading
import time
import unittest

from core.commands import COMMANDS
from core.mock_slave import MockDmmSlave, _NORMAL_RESPONSES
from core.protocol import (ScpiClient, TimeoutError_, ProtocolError,
                           parse_error_response, explain_error, parse_float)
from core.semantic import DmmService
from core.transport import LoopbackTransport


def make_client(scenario="normal", queue_limit=32, **slave_kw):
    slave = MockDmmSlave(scenario=scenario, **slave_kw)
    transport = LoopbackTransport(slave.handle)
    client = ScpiClient(transport, default_timeout_s=0.3,
                        max_retries=2, queue_limit=queue_limit,
                        retry_backoff_s=0.001)
    client.connect()
    return client, slave


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------
class TestNormalFrames(unittest.TestCase):
    def test_idn(self):
        client, _ = make_client()
        svc = DmmService(client)
        idn = svc.identify()
        self.assertIn("KEYSIGHT", idn)
        self.assertIn("34465A", idn)

    def test_all_queries_readback(self):
        """全查询命令读数比对（步骤6：全寄存器读写比对）。"""
        client, _ = make_client()
        for cmd in COMMANDS:
            if not cmd.is_query:
                continue
            with self.subTest(key=cmd.key):
                raw = client.query(cmd.key)
                self.assertTrue(raw, f"{cmd.key} 无响应")
                self.assertEqual(raw, _NORMAL_RESPONSES[cmd.key],
                                 f"{cmd.key} 读数与模拟从站不符")

    def test_measure_semantic(self):
        client, _ = make_client()
        svc = DmmService(client)
        v = svc.measure_dc_voltage()
        self.assertIsInstance(v, float)
        self.assertAlmostEqual(v, 1.23456789, places=5)
        info = svc.measure_with_unit("read_temp")
        self.assertEqual(info["unit"], "C")
        self.assertEqual(info["key"], "read_temp")

    def test_all_sets_accept(self):
        """全设置命令下发（写侧不报错）。"""
        client, slave = make_client()
        sent = 0
        for cmd in COMMANDS:
            if not cmd.is_set:
                continue
            with self.subTest(key=cmd.key):
                if "{v}" in cmd.scpi:
                    val = "ON" if isinstance(cmd.rng, frozenset) else "1"
                    if cmd.key == "disp_text":
                        val = "hello"
                    elif cmd.key == "cal_secure_code":
                        val = "1234"
                    client.set(cmd.key, val)
                else:
                    client.set(cmd.key)
                sent += 1
        self.assertGreater(sent, 0)
        self.assertEqual(slave.commands_received, sent)

    def test_set_query_readback(self):
        """可读可写命令：写后可回读（读写比对）。"""
        client, _ = make_client()
        client.set("sense_nplc", "5.0")
        self.assertEqual(client.query("sense_nplc"), _NORMAL_RESPONSES["sense_nplc"])
        client.set("trig_source", "EXTernal")
        self.assertEqual(client.query("trig_source"), _NORMAL_RESPONSES["trig_source"])

    def test_set_rejects_on_pure_query(self):
        client, _ = make_client()
        with self.assertRaises(ProtocolError):
            client.set("read_dc_volt", "1")
        with self.assertRaises(ProtocolError):
            client.query("reset")


# ---------------------------------------------------------------------------
# 异常路径
# ---------------------------------------------------------------------------
class TestBadFrames(unittest.TestCase):
    def test_bad_frame_recovers(self):
        """错帧：上位机不应崩溃，能继续收后续正常帧（重同步）。"""
        client, _ = make_client(scenario="bad_frame")
        for _ in range(5):
            try:
                client.query("read_dc_volt")
            except (ProtocolError, TimeoutError_):
                pass  # 错帧被拒，允许失败，但不得抛未预期异常/卡死

    def test_mixed_bad_then_good(self):
        """错帧后恢复：模拟从站先错帧后正常，上位机能重同步取到正确值。"""
        client, slave = make_client(scenario="intermittent", error_rate=0.5, seed=3)
        got = None
        for _ in range(20):
            try:
                got = client.query("read_dc_volt")
                break
            except (ProtocolError, TimeoutError_):
                continue
        self.assertEqual(got, _NORMAL_RESPONSES["read_dc_volt"])

    def test_timeout_resend_limit(self):
        """超时：重发有上限，超限退出——不许无限重发（坑位自查）。"""
        client, slave = make_client(scenario="timeout")
        t0 = time.monotonic()
        with self.assertRaises(TimeoutError_) as cm:
            client.query("read_dc_volt")
        elapsed = time.monotonic() - t0
        self.assertIn("重发", str(cm.exception))
        # 1 次 + 2 次重发后必须退出：3 次尝试 × 每帧 2s 超时 = 上限约 6s
        self.assertEqual(slave.commands_received, 3)
        self.assertLess(elapsed, 10.0, "超时退出太慢，可能陷入死循环")

    def test_slave_disconnect_no_hang(self):
        """从站断开：链路异常必须抛出并退出，不得卡死。"""
        client, _ = make_client(scenario="disconnect")
        t0 = time.monotonic()
        with self.assertRaises(TimeoutError_):
            client.query("read_dc_volt")
        self.assertLess(time.monotonic() - t0, 5.0)

    def test_scpi_error_mapping(self):
        """SCPI 错误码 -> 人话提示。"""
        client, _ = make_client(scenario="scpi_error")
        raw = client.query("error_query")
        err = parse_error_response(raw)
        self.assertEqual(err.code, -105)
        text = explain_error(err.code, err.message)
        self.assertIn("参数越界", text)
        self.assertIn("仪器", text)

    def test_queue_limit_rejects(self):
        """命令队列上限：并发超限必须被拒绝，不许无限堆积（坑位自查）。"""
        client, _ = make_client(scenario="timeout", queue_limit=2)
        errs = []
        def hammer():
            try:
                client.query("read_dc_volt")
            except Exception as e:
                errs.append(e)
        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertTrue(
            any(isinstance(e, ProtocolError) and "队列已满" in str(e) for e in errs),
            "队列超限未被拒绝")
        self.assertTrue(any(isinstance(e, TimeoutError_) for e in errs))

    def test_parse_float_rejects_garbage(self):
        with self.assertRaises(ProtocolError):
            parse_float("NOT_A_NUMBER")

    def test_intermittent_stress(self):
        """混合异常压力回归：不得死锁/崩溃，失败都受控。"""
        client, _ = make_client(scenario="intermittent", error_rate=0.4, seed=7)
        ok = fail = 0
        for _ in range(30):
            try:
                client.query("read_dc_volt")
                ok += 1
            except (TimeoutError_, ProtocolError):
                fail += 1
        self.assertEqual(ok + fail, 30)


# ---------------------------------------------------------------------------
# 半包 / 粘包
# ---------------------------------------------------------------------------
class TestStreamBoundaries(unittest.TestCase):
    def _client(self):
        slave = MockDmmSlave()
        t = LoopbackTransport(slave.handle)
        client = ScpiClient(t, default_timeout_s=0.5, max_retries=1,
                            retry_backoff_s=0.001)
        client.connect()
        return client, slave

    def test_chunked_response(self):
        """半包：响应分片到达也能重组。"""
        client, _ = self._client()
        for c in (b"1.", b"23", b"45\n"):
            client._rxbuf.extend(c)
        line = client._read_line(time.monotonic() + 1.0)
        self.assertEqual(line, "1.2345")

    def test_pasted_commands(self):
        """粘包：一次写入两条命令，两条响应都能正确取回。"""
        client, _ = self._client()
        client._t.write(b"*IDN?\nMEASure:VOLTage:DC?\n")
        l1 = client._read_line(time.monotonic() + 1.0)
        l2 = client._read_line(time.monotonic() + 1.0)
        self.assertIn("KEYSIGHT", l1)
        self.assertIn("E+", l2)

    def test_garbage_cleaned(self):
        """错帧杂散控制字符被剔除。"""
        client, _ = self._client()
        client._rxbuf.extend(b"\x00\x014.2\n")
        line = client._read_line(time.monotonic() + 1.0)
        self.assertEqual(line, "4.2")


# ---------------------------------------------------------------------------
# 命令表自身一致性（单一事实源自检）
# ---------------------------------------------------------------------------
class TestCommandTable(unittest.TestCase):
    def test_keys_unique(self):
        keys = [c.key for c in COMMANDS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_query_has_mock_response(self):
        """保证模拟从站覆盖所有查询命令（回归完整性）。"""
        for cmd in COMMANDS:
            if cmd.is_query:
                self.assertIn(cmd.key, _NORMAL_RESPONSES,
                              f"模拟从站缺少 {cmd.key} 的正常响应")
                self.assertIn(cmd.query_form,
                              MockDmmSlave._prefix_keys(),
                              f"模拟从站无法解析 {cmd.key} 的查询帧 {cmd.query_form}")

    def test_verify_items_listed(self):
        """待澄清项必须显式标注（禁止猜测，抽表质量卡点）。"""
        from core.commands import need_verify
        items = need_verify()
        self.assertGreater(len(items), 0)
        for c in items:
            self.assertTrue(c.verify.strip())

    def test_get_raises_on_unknown(self):
        from core.commands import get
        with self.assertRaises(KeyError):
            get("no_such_key")

    def test_version_triple_present(self):
        from core import SW_VERSION, PROTOCOL_VERSION, REG_TABLE_VERSION
        self.assertTrue(SW_VERSION and PROTOCOL_VERSION and REG_TABLE_VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
