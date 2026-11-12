# -*- coding: utf-8 -*-
"""
HSPY 电源通讯驱动
==================
把「传输层」（真实串口 / 内置模拟器）与「协议层」拼装成一个易用的设备对象。

    dev = HspyDevice.open_serial('COM3', slave=1)      # 真实电源
    dev = HspyDevice.open_simulator(slave=1)           # 无硬件，内置仿真

    print(dev.read_all())
    dev.set_voltage(12.5)
    dev.set_current(2.0)
    dev.output(True)
    dev.close()

现场调试要点（2026 版）
----------------------
针对真实电源实测中暴露的三个问题，这里做了针对性加固：

1. **读取不再是「全有或全无」**
   不同批次 HSPY 固件对以下三点表现不一致，本驱动全部做了自适应：
     · 单次读取寄存器数量上限（有的是 8、有的是 16、有的是 125）
     · 只写寄存器（如 SET_OUT 0x1017）读回来是异常码 0x02/ 0x03 还是 0
     · 地址块空洞（0x100F~0x1013 未定义）
   `read_registers_safe()` 会自动二分降级：整块读-> 半块 -> 单个寄存器，
   读不到的就跳过并记录原因，绝不因为一个寄存器失败而让整次读取失败。

2. **写入后一定读回校验**
   `write_key()` 成功后立刻回读该寄存器并比对，UI 上会明确显示
   「已写入 / 写入被设备拒绝 / 写入成功但回读不一致」三种不同结果。

3. **严格遵守 Modbus RTU 帧间隔**
   协议要求帧间静默 >= 3.5 个字符时间，且 RS485 收发器需要换向时间。
   发送前插入静默间隔，发送后插入换向延时，避免连发时设备漏帧。
"""

from __future__ import annotations

import re
import threading
import time

try:
    import serial  # pyserial
    from serial.tools import list_ports
except ImportError:                       # 允许在没装 pyserial 时使用仿真模式
    serial = None
    list_ports = None

from .HspyProtocol import (
    ADDR_BASE,
    POLL_COUNT,
    POLL_START,
    REGISTERS,
    FC_READ_HOLDING,
    FC_WRITE_MULTI,
    FC_WRITE_SINGLE,
    HspyProtocolError,
    build_read,
    build_write_multi,
    build_write_single,
    format_frame,
    parse_response,
    reg,
)
from .HspySim import HspySimulator

SIM_PORT_NAME = '『仿真设备』(无需硬件)'

# 读取时单块最多尝试多少个寄存器；失败会自动二分降级
DEFAULT_MAX_CHUNK = 8


class HspyError(Exception):
    """通讯失败"""


# --------------------------------------------------------------------------- #
# 传输层
# --------------------------------------------------------------------------- #
class SerialTransport:
    """真实串口（pyserial）。"""

    def __init__(self, port, baudrate=9600, bytesize=8, parity='N',
                 stopbits=2, timeout=0.3):
        if serial is None:
            raise HspyError('未安装 pyserial，无法使用真实串口（可先使用仿真模式）')
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=timeout,
            write_timeout=1.0,
        )
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.description = f'{port} {baudrate},{bytesize},{parity},{stopbits}'

    # ---- 时序参数 ---- #
    @property
    def char_bits(self) -> int:
        """一个字符占多少位：1 起始 +数据位 + 校验位 + 停止位。"""
        parity_bits = 0 if self.parity in ('N', None) else 1
        return 1 + self.bytesize + parity_bits + int(self.stopbits)

    @property
    def char_time(self) -> float:
        return self.char_bits / float(self.baudrate)

    def write(self, data: bytes) -> int:
        return self.ser.write(data)

    def read(self, size: int) -> bytes:
        return self.ser.read(size)

    @property
    def in_waiting(self) -> int:
        return self.ser.in_waiting

    def reset_input_buffer(self) -> None:
        self.ser.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        self.ser.reset_output_buffer()

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass


class SimulatedTransport:
    """内置电源模拟器。"""

    def __init__(self, slave: int = 1, noise: bool = True, rated=None):
        self.sim = HspySimulator(slave, noise=noise)
        self.description = f'仿真设备（{self.sim.slave} 号机）'
        self.baudrate = 9600
        self.bytesize = 8
        self.parity = 'N'
        self.stopbits = 2
        if rated:
            self.sim.set_rating(*rated)

    def set_rating(self, rated_voltage=None, rated_current=None,
                   rated_power=None):
        """切换仿真机型额定值（仅仿真传输层有）。"""
        self.sim.set_rating(rated_voltage, rated_current, rated_power)

    @property
    def char_time(self) -> float:
        return 11 / 9600.0

    def write(self, data: bytes) -> int:
        return self.sim.write(data)

    def read(self, size: int) -> bytes:
        data = self.sim.read(size)
        if not data:
            time.sleep(0.002)             # 模拟串口等待
        return data

    @property
    def in_waiting(self) -> int:
        return self.sim.in_waiting

    def reset_input_buffer(self) -> None:
        self.sim.reset_input_buffer()

    def reset_output_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.sim.close()


# --------------------------------------------------------------------------- #
# 串口枚举
# --------------------------------------------------------------------------- #
def _natural_key(name: str):
    """自然排序键：COM2 排在 COM10 前面。"""
    m = re.match(r'^([A-Za-z]*)(\d+)$', name or '')
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return ((name or '').upper(), 0)


def registry_com_ports():
    """读注册表 HARDWARE\\DEVICEMAP\\SERIALCOMM，返回系统登记的 COM 口名。

    com0com / VSPD 等虚拟串口软件创建的端口有时不会出现在标准枚举里，
    但一定会登记在这张表里，所以这里再兜一层。
    """
    names = []
    try:
        import winreg
    except ImportError:
        return names
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r'HARDWARE\DEVICEMAP\SERIALCOMM')
    except OSError:
        return names
    try:
        i = 0
        while True:
            try:
                _dev, val, _t = winreg.EnumValue(key, i)
                i += 1
                if isinstance(val, str) and val.strip():
                    names.append(val.strip())
            except OSError:
                break
    finally:
        key.Close()
    return names


def _short(text: str, limit: int = 20) -> str:
    """把描述截短，保证端口下拉列表里能看全（设备名总在最前面）。"""
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def available_ports(candidates: int = 16):
    """返回 [(设备名, 描述, 类型), ...]，类型为 'sim' / 'detected' / 'candidate'。

    * 'sim'       —— 内置仿真设备，永远排第一
    * 'detected'  —— 系统里真实存在的串口（含虚拟串口软件创建的口）
    * 'candidate' —— COM1..COMn 候选，系统当前没有也允许选择：
                     既能配合虚拟串口软件使用，也能先选好再插线
    """
    ports = [(SIM_PORT_NAME, '', 'sim')]
    detected = []

    if list_ports is not None:
        try:
            found = list(list_ports.comports())
        except Exception:
            found = []
        for p in sorted(found, key=lambda x: _natural_key(x.device)):
            desc = (p.description or '').strip()
            if not desc or desc.lower() == 'n/a':
                desc = '串口设备（无描述）'
            extra = []
            if p.vid is not None and p.pid is not None:
                extra.append('%04X:%04X' % (p.vid, p.pid))
            if extra:
                desc = f'{desc} [{" ".join(extra)}]'
            detected.append(p.device)
            ports.append((p.device, _short(desc), 'detected'))

    # 注册表兜底（虚拟串口软件创建的端口）
    for name in registry_com_ports():
        if name not in detected:
            detected.append(name)
            ports.append((name, '系统已登记（虚拟串口）', 'detected'))

    # 候选 COM 口：保证下拉框里一定能选到 COM 号
    for i in range(1, candidates + 1):
        name = f'COM{i}'
        if name not in detected:
            ports.append((name, '未检测到（可选）', 'candidate'))
    return ports


def probe_com_ports(max_index: int = 64, timeout: float = 0.05):
    """逐个尝试打开 COM1..COMn，返回「能打开但枚举不到」的串口名。

    用于系统串口列表为空时做深度扫描：某些虚拟串口或驱动信息缺失的 USB 转串口线
    不会出现在标准枚举里，但实际可以打开。只在常规枚举一无所获时调用。
    """
    if serial is None:
        return []
    names = []
    for i in range(1, max_index + 1):
        name = f'COM{i}'
        try:
            s = serial.Serial(port=name, timeout=timeout)
            s.close()
            names.append(name)
        except Exception:
            continue
    return names


# --------------------------------------------------------------------------- #
# 设备驱动
# --------------------------------------------------------------------------- #
class HspyDevice:
    """HSPY 电源设备对象（线程安全）。"""

    def __init__(self, transport, slave: int = 1, addr_base: int = ADDR_BASE,
                 timeout: float = 0.6, retries: int = 2,
                 max_chunk: int = DEFAULT_MAX_CHUNK,
                 logger=None):
        self.t = transport
        self.slave = slave
        self.dead_regs: set = set()   # 本会话已确认无应答的地址（跳过，不再耗超时×重试）
        self.addr_base = addr_base
        self.timeout = timeout
        self.retries = retries
        self.max_chunk = max_chunk
        self.run_stop_inverted = False   # Run-Stop 极性，默认 0=停止 1=输出
        # ---- 通信时序（可现场调整） ---- #
        self.frame_gap_ms = 4.0          # 每帧前静默，Modbus 要求 >= 3.5 字符时间
        self.write_quiet_ms = 25.0       # 写入前额外静默，防与轮询撞车
        self.settle_ms = 200.0           # 一次命令后暂停轮询的时长
        self.poll_chunk = 8              # 轮询单次读取的寄存器个数
        self.logger = logger
        self._lock = threading.RLock()
        self.stats = {'tx': 0, 'rx': 0, 'err': 0}
        self.last_read_errors = []      # 最近一次安全读取失败的 {地址: 原因}

    # ---------------- 构造 ---------------- #
    @classmethod
    def open_serial(cls, port, slave=1, baudrate=9600, bytesize=8,
                    parity='N', stopbits=2, timeout=0.6, logger=None,
                    max_chunk=DEFAULT_MAX_CHUNK):
        tr = SerialTransport(port, baudrate, bytesize, parity, stopbits, timeout)
        return cls(tr, slave=slave, timeout=timeout, logger=logger,
                   max_chunk=max_chunk)

    @classmethod
    def open_simulator(cls, slave=1, noise=True, logger=None, rated=None):
        return cls(SimulatedTransport(slave, noise, rated), slave=slave,
                   logger=logger)

    # ---------------- 地址换算 ---------------- #
    def _addr(self, key_or_reg) -> int:
        """把协议里的绝对地址换算成本机实际使用的地址（支持 0x1000 / 0x0000 两种基址）。"""
        r = reg(key_or_reg) if isinstance(key_or_reg, str) else key_or_reg
        return self.addr_base + (r.addr - ADDR_BASE)

    def _abs_addr(self, addr: int) -> int:
        """把寄存器表里的绝对地址（0x1000 基址）换算成本机正在使用的地址。"""
        return self.addr_base + (int(addr) - ADDR_BASE)

    # ---------------- 原始寄存器直读直写（调试用） ---------------- #
    def read_raw(self, addr: int) -> int:
        """按寄存器表地址直接读一个寄存器（不查键名，界面「原始寄存器读写」用）。"""
        return self.read_registers(self._abs_addr(addr), 1)[0]

    def write_raw(self, addr: int, value: int):
        """按寄存器表地址直接写一个寄存器；FC06 失败自动回退 FC10。

        返回 (实际生效的功能码, 响应)。
        """
        a = self._abs_addr(addr)
        v = int(value) & 0xFFFF
        try:
            return 'FC06', self.write_register(a, v)
        except Exception:
            return 'FC10', self.write_registers(a, [v])

    def set_sim_rating(self, rated_voltage=None, rated_current=None,
                       rated_power=None) -> bool:
        """仅当连接的是内置仿真设备时生效：切换仿真机型的额定值。"""
        fn = getattr(self.t, 'set_rating', None)
        if callable(fn):
            fn(rated_voltage, rated_current, rated_power)
            return True
        return False

    # ---------------- 其它 ---------------- #
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def _log(self, direction, frame, note=''):
        if self.logger:
            try:
                self.logger(direction, frame, note)
            except Exception:
                pass

    def close(self):
        with self._lock:
            if self.t:
                self.t.close()

    @property
    def is_open(self) -> bool:
        return self.t is not None

    # ---------------- 时序 ---------------- #
    @property
    def char_time(self) -> float:
        try:
            return float(self.t.char_time)
        except Exception:
            return 11 / 9600.0

    @property
    def frame_gap(self) -> float:
        """帧间静默：取「配置值」与「3.5 个字符时间」的较大者。"""
        return max(self.frame_gap_ms / 1000.0, self.char_time * 3.5)

    @property
    def turnaround(self) -> float:
        """RS485 收发器换向延时（发完等一下再收）。"""
        return max(0.002, self.char_time)

    def set_timing(self, frame_gap_ms=None, write_quiet_ms=None,
                   settle_ms=None, poll_chunk=None):
        """调整通信时序（现场遇到丢帧时可加大）。

        frame_gap_ms   —— 每帧前的静默时间，Modbus RTU 要求 ≥3.5 字符时间
        write_quiet_ms —— **写入命令前的额外静默**。半双工总线上如果轮询很密，
                         写入帧容易和前一次响应的尾巴撞车，设备就把整帧丢掉，
                         于是表现为「点了没反应」。给它一段安静时间即可解决。
        settle_ms      —— 一次命令完成后，暂停轮询多久再继续
        poll_chunk     —— 轮询一次读多少个寄存器（设备有上限时改小）
        """
        if frame_gap_ms is not None:
            self.frame_gap_ms = float(frame_gap_ms)
        if write_quiet_ms is not None:
            self.write_quiet_ms = float(write_quiet_ms)
        if settle_ms is not None:
            self.settle_ms = float(settle_ms)
        if poll_chunk is not None:
            self.poll_chunk = max(1, int(poll_chunk))

    def _wait_idle(self, extra: float = 0.0) -> None:
        """等总线彻底安静后再发帧。

        半双工 RS485（尤其 MOXA 之类的转换器）在设备还在回送上一帧时，
        主机若抢先发送，两边的驱动会撞在总线上，结果是主机这一帧被设备
        当成噪声丢掉 —— 现象就是「命令发出去了但设备毫无反应」。
        这里先等输入缓冲排空，再补上一段静默时间。
        """
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                if self.t.in_waiting == 0:
                    break
            except Exception:
                break
            time.sleep(0.002)
        try:
            self.t.reset_input_buffer()
        except Exception:
            pass
        time.sleep(self.frame_gap + max(0.0, extra))

    # ---------------- 基本收发 ---------------- #
    def _fill(self, buf: bytearray, n: int, deadline: float) -> None:
        """尽量读满 n 字节或直到超时。"""
        while len(buf) < n:
            try:
                chunk = self.t.read(max(1, n - len(buf)))
            except Exception:
                break
            if chunk:
                buf.extend(chunk)
                continue
            if time.time() >= deadline:
                break
            time.sleep(0.002)

    def _send_and_recv(self, frame: bytes, expect_func: int, expect_len: int = 0,
                       is_write: bool = False) -> bytes:
        """发送请求并收取响应帧。

        读取响应（功能码 03）的长度由从机返回的第 3 字节（字节计数）决定，
        不用调用方猜测。

        is_write=True 时，发送前额外插入 write_quiet_ms 的静默，
        避免与轮询流量撞车导致这一帧被设备丢弃。
        """
        with self._lock:
            self._wait_idle(self.write_quiet_ms / 1000.0 if is_write else 0.0)
            self._log('tx', frame)
            self.stats['tx'] += 1
            try:
                self.t.write(frame)
            except Exception as e:
                self.stats['err'] += 1
                raise HspyError(f'串口写入失败：{e}') from e

            time.sleep(self.turnaround)         # 等待收发器换向

            buf = bytearray()
            deadline = time.time() + self.timeout

            if expect_func == FC_READ_HOLDING:
                # 先取 3 字节头，拿到字节计数后再决定还差多少
                self._fill(buf, 3, deadline)
                if len(buf) >= 3 and (buf[1] & 0x80):
                    self._fill(buf, 5, deadline)          # 异常响应固定 5 字节
                elif len(buf) >= 3:
                    need = 3 + buf[2] + 2
                    if need > 255 + 5:
                        need = 5
                    self._fill(buf, need, deadline)
            else:
                self._fill(buf, expect_len or 8, deadline)

            # 响应收完后若还有残留字节，说明总线没干净，排掉免得影响下一帧
            try:
                if self.t.in_waiting:
                    time.sleep(self.turnaround)
                    self.t.reset_input_buffer()
            except Exception:
                pass

            rx = bytes(buf)
            if rx:
                self._log('rx', rx)
                self.stats['rx'] += 1
            if not rx:
                self.stats['err'] += 1
                raise HspyError('超时：未收到电源响应（请检查串口号 / 波特率 / 停止位 / '
                                '从机地址 / A-B 接线 / 设备供电）')
            try:
                return parse_response(rx, self.slave, expect_func)
            except HspyProtocolError as e:
                self.stats['err'] += 1
                raise HspyError(str(e)) from e

    def _transact(self, frame: bytes, func: int, expect_len: int = 0,
                  is_write: bool = False):
        last = None
        for attempt in range(self.retries + 1):
            try:
                return self._send_and_recv(frame, func, expect_len, is_write)
            except HspyError as e:
                last = e
                if attempt < self.retries:
                    time.sleep(0.12)
        raise last

    # ---------------- 寄存器级 API ---------------- #
    def read_registers(self, start: int, count: int):
        """功能码 03：读保持寄存器（严格模式，失败即抛异常）。"""
        frame = build_read(self.slave, start, count)
        return self._transact(frame, FC_READ_HOLDING)

    def write_register(self, addr: int, value: int):
        """功能码 06：写单个寄存器。"""
        frame = build_write_single(self.slave, addr, value)
        return self._transact(frame, FC_WRITE_SINGLE, 8, is_write=True)

    def write_registers(self, start: int, values):
        """功能码 10：写多个寄存器。"""
        frame = build_write_multi(self.slave, start, values)
        return self._transact(frame, FC_WRITE_MULTI, 8, is_write=True)

    # ---------------- 自适应安全读取 ---------------- #
    def _read_chunk(self, start: int, count: int, out: dict, fail: dict) -> None:
        """读 start..start+count-1；失败或返回不全时自动二分降级到单寄存器。"""
        if count <= 0:
            return
        # 死寄存器缓存：同会话已确认无应答的地址直接跳过——
        # 否则个别固件缺失的寄存器（如 0x1014~0x1017）每次 read_all 都耗超时×重试泥潭
        if all((start + i) in self.dead_regs for i in range(count)):
            for i in range(count):
                fail[start + i] = '此前无应答（本会话已跳过）'
            return
        try:
            vals = self.read_registers(start, count)
        except Exception as e:
            if count == 1:
                fail[start] = str(e)
                self.dead_regs.add(start)
            else:
                half = count // 2
                self._read_chunk(start, half, out, fail)
                self._read_chunk(start + half, count - half, out, fail)
            return

        got = min(len(vals), count)
        for i in range(got):
            out[start + i] = vals[i]

        if got >= count:
            return

        # 设备只回了一部分（固件常对单次读取数量设上限）。
        # 关键：不能把没读到的寄存器当 0 —— 那会让显示悄悄变成假数据。
        # 这里把缺的部分再按小块重读。
        rest = count - got
        fail[start + got] = f'设备仅返回 {got}/{count} 个寄存器'
        half = max(1, rest // 2)
        self._read_chunk(start + got, half, out, fail)
        if rest - half > 0:
            self._read_chunk(start + got + half, rest - half, out, fail)

    def read_registers_safe(self, start: int, count: int,
                            max_chunk: int = None):
        """容错读取：返回 (值字典, 失败字典)，单个寄存器失败不影响其它。

        先按 max_chunk 分块读；某块失败或返回不全时自动二分降级，
        直到单寄存器；仍拿不到则记录原因并跳过。
        """
        max_chunk = max_chunk or self.max_chunk
        out, fail = {}, {}
        offset = 0
        while offset < count:
            n = min(max_chunk, count - offset)
            self._read_chunk(start + offset, n, out, fail)
            offset += n
        return out, fail

    # ---------------- 语义级 API ---------------- #
    def read_key(self, key: str) -> int:
        """读取某寄存器（返回原始值，严格模式）。"""
        return self.read_registers(self._addr(key), 1)[0]

    def read_key_float(self, key: str) -> float:
        """读取某寄存器并按小数点位数换算为物理量。"""
        r = reg(key)
        return r.to_physical(self.read_key(key))

    def write_key(self, key: str, value: float, *, physical: bool = True,
                  use_multi: bool = False, verify: bool = True,
                  fallback: bool = True):
        """写入某寄存器并读回校验。

        physical=True 时 value 为物理量（如 12.5V），自动按小数位换算成原始值；
        physical=False 时 value 直接作为原始值写入。

        部分固件只接受功能码 10（写多寄存器），另一些只接受 06；
        还有的固件会「应答但不执行」。因此 fallback=True 时，只要回读值与设定
        不一致，就会自动换另一种功能码继续尝试，全部无效才判定为写入失败。

        返回信息字典（供 UI 展示）：
            {ok, key, name, raw, readback, readback_text, method, note, verified}
            ok=False 且 verified=True  —— 设备应答了但没接受（回读不符）
            ok=False 且 verified=False —— 写入请求本身没发出去
        """
        r = reg(key)
        if r.readonly:
            raise HspyError(f'寄存器「{r.name}」为只读，不可写入')
        addr = self._addr(key)
        raw = r.to_raw(value) if physical else int(value) & 0xFFFF

        methods = [('FC10', True), ('FC06', False)] if use_multi else \
                  [('FC06', False), ('FC10', True)]
        if not fallback:
            methods = methods[:1]

        errors = []
        best = None          # 「已发出且被应答，但回读与设定不符」的最佳记录
        acked = False        # 是否至少有一种功能码被设备应答过

        for name, multi in methods:
            try:
                if multi:
                    self.write_registers(addr, [raw])
                else:
                    self.write_register(addr, raw)
            except Exception as e:
                errors.append(f'{name} 失败：{e}')
                continue

            acked = True

            if not verify:
                return {
                    'ok': True, 'key': key, 'name': r.name, 'unit': r.unit,
                    'decimals': r.d, 'addr': addr, 'raw': raw,
                    'value': r.to_physical(raw), 'readback': None,
                    'readback_text': '', 'method': name, 'note': '',
                    'errors': errors, 'verified': False,
                }

            # 写成功 —— 读回校验；不一致时继续尝试另一种功能码
            time.sleep(0.05)
            try:
                readback = self.read_registers(addr, 1)[0]
            except Exception as e:
                errors.append(f'{name} 已发出但回读校验失败：{e}')
                if best is None:
                    best = {'method': name, 'readback': None,
                            'note': f'已发送 {name} 写入请求，但回读校验失败：{e}'}
                continue

            if readback == raw:
                return {
                    'ok': True, 'key': key, 'name': r.name, 'unit': r.unit,
                    'decimals': r.d, 'addr': addr, 'raw': raw,
                    'value': r.to_physical(raw), 'readback': readback,
                    'readback_text': r.format(readback), 'method': name,
                    'note': '', 'errors': errors, 'verified': True,
                }

            # 设备应答了但没接受 —— 换另一种功能码再试，很多固件只认其中一种
            note = (f'已发送 {name} 写入请求，但设备回读值 {r.format(readback)} '
                    f'与设定 {r.format(raw)} 不一致')
            errors.append(note)
            if best is None or best.get('readback') is None:
                best = {'method': name, 'readback': readback, 'note': note}

        if acked and best is not None:
            # 写入被应答但没生效：返回结果让界面明确提示，而不是假装成功
            return {
                'ok': False, 'key': key, 'name': r.name, 'unit': r.unit,
                'decimals': r.d, 'addr': addr, 'raw': raw,
                'value': r.to_physical(raw), 'readback': best.get('readback'),
                'readback_text': (r.format(best['readback'])
                                  if best.get('readback') is not None else ''),
                'method': best.get('method', ''), 'note': best.get('note', ''),
                'errors': errors, 'verified': True,
            }

        raise HspyError('；'.join(errors) or '写入失败')

    # ---- 常用快捷方法 ---- #
    def set_voltage(self, volts: float, **kw):
        return self.write_key('set_u', volts, **kw)

    def set_current(self, amps: float, **kw):
        return self.write_key('set_i', amps, **kw)

    def set_power(self, watts: float, **kw):
        return self.write_key('set_p', watts, **kw)

    def set_ovp(self, volts: float, **kw):
        return self.write_key('ovp', volts, **kw)

    def set_ocp(self, amps: float, **kw):
        return self.write_key('ocp', amps, **kw)

    def output(self, on: bool, **kw):
        """输出开/关（Run-Stop 寄存器）。

        协议文档：0=停止，1=输出。但个别兼容机型极性相反，
        可通过 set_run_polarity(inverted=True) 切换。
        """
        val = (0 if on else 1) if self.run_stop_inverted else (1 if on else 0)
        return self.write_key('run_stop', val, physical=False, **kw)

    def set_run_polarity(self, inverted: bool) -> None:
        """设置 Run-Stop 寄存器极性。inverted=True 表示 0=输出、1=停止。"""
        self.run_stop_inverted = bool(inverted)

    # ---------------- 批量读取 ---------------- #
    def read_all(self):
        """一键读取全部可读寄存器。

        返回 (values, failures)：
            values   = {key: (原始值, 物理量, 显示文本)}
            failures = [(key, 名称, 地址, 原因), ...]  —— 只写/不支持的寄存器会在这里

        只写寄存器（如 SET_OUT）会被跳过并在 failures 中说明，
        因此本函数几乎不会整体失败。
        """
        readable = [r for r in REGISTERS if not r.writeonly]
        values, failures = {}, []

        # 按地址连续性分块，减少往返次数
        blocks = []
        for r in sorted(readable, key=lambda x: x.addr):
            if blocks and r.addr == blocks[-1][1] + blocks[-1][2]:
                s, _e, n = blocks[-1]
                blocks[-1] = (s, r.addr, n + 1)
            else:
                blocks.append((r.addr, r.addr, 1))

        raw_map, fail_map = {}, {}
        for start, _end, n in blocks:
            got, bad = self.read_registers_safe(start, n)
            raw_map.update(got)
            fail_map.update(bad)

        for r in REGISTERS:
            if r.writeonly:
                failures.append((r.key, r.name, r.addr, '只写寄存器，无法读取'))
                continue
            raw = raw_map.get(r.addr)
            if raw is None:
                failures.append((r.key, r.name, r.addr,
                                 fail_map.get(r.addr, '设备无响应')))
                continue
            values[r.key] = (raw, r.to_physical(raw), r.format(raw))

        self.last_read_errors = [{'key': k, 'name': n, 'addr': a, 'reason': why}
                                 for k, n, a, why in failures]
        return values, failures

    def read_poll_block(self):
        """读取监测块（0x1000 起共 15 个），返回长度为 POLL_COUNT 的列表。

        单个寄存器读不到时用 0 占位，保证界面不会崩；
        失败详情记录在 self.last_read_errors。
        """
        start = self.addr_base + (POLL_START - ADDR_BASE)
        got, bad = self.read_registers_safe(start, POLL_COUNT,
                                            max_chunk=self.poll_chunk)
        self.last_read_errors = [{'key': f'0x{a:04X}', 'name': '轮询块',
                                  'addr': a, 'reason': why} for a, why in bad.items()]
        return [got.get(start + i, 0) for i in range(POLL_COUNT)]

    def ping(self) -> bool:
        """探测设备是否在线。"""
        for base in (self.addr_base, 0x0000 if self.addr_base != 0 else 0x1000):
            try:
                self.read_registers(self.addr_base + 0, 1)
                if base != self.addr_base:
                    self.addr_base = base
                return True
            except Exception:
                continue
        return False

    def scan_slaves(self, first=1, last=15, progress=None):
        """扫描从机地址（文档：单机地址范围 1~15）。返回在线地址列表。"""
        found = []
        old = self.slave
        try:
            for addr in range(first, last + 1):
                self.slave = addr
                try:
                    self.read_registers(self.addr_base, 1)
                    found.append(addr)
                except Exception:
                    pass
                if progress:
                    progress(addr, last)
        finally:
            self.slave = old
        return found

    # ---------------- 报文（供日志/调试） ---------------- #
    @staticmethod
    def frame_text(frame: bytes) -> str:
        return format_frame(frame)