"""High-level Modbus master client (RTU / TCP)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from . import modbus as mb
from .crc16 import verify_crc
from .transport import SerialTransport, TcpTransport, Transport, TransportError

LogFn = Callable[[str, str, bytes], None]  # direction, text, raw


@dataclass
class CommStats:
    tx: int = 0
    rx: int = 0
    err: int = 0
    last_ok: Optional[float] = None


class ModbusClient:
    def __init__(self, transport: Transport, log: Optional[LogFn] = None):
        self.transport = transport
        self.log = log
        self.stats = CommStats()
        self._lock_depth = 0

    # -- lifecycle --------------------------------------------------------
    def connect(self) -> None:
        self.transport.open()
        self.stats.last_ok = time.time()

    def disconnect(self) -> None:
        self.transport.close()

    @property
    def connected(self) -> bool:
        return self.transport.is_open

    @property
    def describe(self) -> str:
        return self.transport.describe

    # -- raw exchange -----------------------------------------------------
    def _exchange(self, request: bytes, timeout: float = 1.0) -> bytes:
        self.stats.tx += 1
        if self.log:
            self.log("TX", f"{self.transport.describe}", request)
        try:
            resp = self.transport.exchange(request, timeout=timeout)
        except TransportError:
            self.stats.err += 1
            if self.log:
                self.log("ERR", "通信失败", request)
            raise
        self.stats.rx += 1
        self.stats.last_ok = time.time()
        if self.log:
            self.log("RX", "", resp)
        return resp

    def _response_pdu(self, request: bytes, resp: bytes) -> bytes:
        """Strip framing; return PDU starting at function code."""
        if isinstance(self.transport, TcpTransport):
            # MBAP(7) + PDU
            if len(resp) < 8:
                raise TransportError("TCP 响应过短")
            pdu = resp[7:]
            return pdu
        # RTU: slave + PDU + CRC
        if len(resp) < 4:
            raise TransportError("RTU 响应过短")
        if not verify_crc(resp):
            raise TransportError("RTU 响应 CRC 校验失败")
        if resp[0] != request[0]:
            raise TransportError(f"站号不匹配: 请求 {request[0]}, 响应 {resp[0]}")
        return resp[1:-2]

    # -- public ops -------------------------------------------------------
    def read_bits(self, slave: int, address: int, count: int, discrete: bool = False) -> List[bool]:
        fc = mb.FC_READ_DISCRETE_INPUTS if discrete else mb.FC_READ_COILS
        req = mb.build_read_bits(slave, fc, address, count)
        resp = self._exchange(req)
        pdu = self._response_pdu(req, resp)
        raw = mb.parse_response(fc, pdu)
        assert isinstance(raw, list)
        return mb.unpack_bits(raw, count)

    def read_coils(self, slave: int, address: int, count: int) -> List[bool]:
        return self.read_bits(slave, address, count, discrete=False)

    def read_discrete(self, slave: int, address: int, count: int) -> List[bool]:
        return self.read_bits(slave, address, count, discrete=True)

    def read_registers(self, slave: int, address: int, count: int) -> List[int]:
        req = mb.build_read_registers(slave, address, count)
        resp = self._exchange(req)
        pdu = self._response_pdu(req, resp)
        raw = mb.parse_response(mb.FC_READ_HOLDING, pdu)
        assert isinstance(raw, list)
        return raw

    def write_coil(self, slave: int, address: int, on: bool) -> None:
        req = mb.build_write_single_coil(slave, address, on)
        resp = self._exchange(req)
        pdu = self._response_pdu(req, resp)
        mb.parse_response(mb.FC_WRITE_SINGLE_COIL, pdu)

    def write_register(self, slave: int, address: int, value: int) -> None:
        req = mb.build_write_single_reg(slave, address, value)
        resp = self._exchange(req)
        pdu = self._response_pdu(req, resp)
        mb.parse_response(mb.FC_WRITE_SINGLE_REG, pdu)

    def write_coils(self, slave: int, address: int, bits: Sequence[bool]) -> None:
        req = mb.build_write_multi_coils(slave, address, bits)
        resp = self._exchange(req)
        pdu = self._response_pdu(req, resp)
        mb.parse_response(mb.FC_WRITE_MULTI_COILS, pdu)

    def write_registers(self, slave: int, address: int, values: Sequence[int]) -> None:
        req = mb.build_write_multi_regs(slave, address, values)
        resp = self._exchange(req)
        pdu = self._response_pdu(req, resp)
        mb.parse_response(mb.FC_WRITE_MULTI_REGS, pdu)

    def ping(self, slave: int) -> bool:
        """Read 1 holding register at 0 to test connectivity (fast timeout)."""
        try:
            self.read_registers(slave, 0, 1)
            return True
        except Exception:
            return False
