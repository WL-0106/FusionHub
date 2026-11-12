"""通信控制器：把协议栈 + 传输层编排成面向界面的服务。

职责：
- 连接/断开
- 扫描在线模块（逐地址点对点探测 0~63）
- 周期轮询在线模块（电压/电流/输入电压/限流点/温度/状态/输入功率）
- 下发设置（电压/电流/开关机/组号/输入模式/海拔/功率等），支持广播
- 汇聚模块状态并发出信号；同时产生可读报文日志
"""

import time
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from . import protocol as P
from .registers import (
    is_power_on, fault_list, decode_status, reg_name,
    INPUT_WORK_MODES, ADDR_MODE_DIP, EXT_TELEMETRY_REGS,
)
from .transport import create_transport, SimTransport

# 轮询寄存器集合（读）
POLL_REGS = [0x0001, 0x0002, 0x0005, 0x0003, 0x0004, 0x0040, 0x0048]
# 模块首次上线时补读的静态参数
ONLINE_EXTRA_REGS = [0x0012, 0x0011, 0x004B, 0x0043, 0x0056, 0x0057, 0x004A]

SCAN_INTERVAL_MS = 25
DEFAULT_POLL_MS = 500
OFFLINE_GRACE_MS = 3000


class ModuleState:
    """单个模块的实时状态快照。"""

    def __init__(self, addr: int):
        self.addr = addr
        self.online = False
        self.last_seen = 0.0
        self.group = 0
        self.voltage = None
        self.current = None
        self.input_v = None
        self.ratio = None            # 限流点 0~1
        self.temp = None
        self.input_power = None
        self.status = 0
        self.rated_current = None
        self.rated_power = None
        self.work_mode = None
        self.dip_addr = None
        self.dcdc_ver = None
        self.pfc_ver = None
        self.altitude = None
        # 扩展遥测
        self.pfc_temp = None         # 0x0010
        self.panel_temp = None       # 0x000B
        self.bus_pos = None          # 0x0008 正半母线
        self.bus_neg = None          # 0x000A 负半母线
        self.ac_a = None             # 0x000C
        self.ac_b = None             # 0x000D
        self.ac_c = None             # 0x000E

    @property
    def power_on(self) -> bool:
        return is_power_on(self.status)

    @property
    def allowed_current(self):
        if self.ratio is None:
            return None
        if self.rated_current:
            return self.ratio * self.rated_current
        return self.ratio

    @property
    def faults(self):
        return fault_list(self.status)

    @property
    def status_text(self) -> str:
        return decode_status(self.status)


class CommController(QObject):
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(int, int)          # 已扫描, 总数
    scan_finished = pyqtSignal(int)               # 在线模块数

    module_seen = pyqtSignal(int)                 # 新上线模块地址
    module_updated = pyqtSignal(int, object)      # 地址, ModuleState
    module_offline = pyqtSignal(int)
    set_failed = pyqtSignal(int, int, str)        # 地址, 寄存器, 说明（F2 回执）

    log_line = pyqtSignal(str, str)               # 文本, 类别(tx/rx/info/err)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.transport = None
        self.mode = "tcp"
        self.modules = {}                         # addr -> ModuleState
        self.polling_enabled = True
        self.poll_interval = DEFAULT_POLL_MS
        self.selected_addr = None                 # 选中模块（补读扩展遥测）

        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(SCAN_INTERVAL_MS)
        self._scan_timer.timeout.connect(self._scan_step)
        self._scan_addr = 0
        self._scanning = False

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.poll_interval)
        self._poll_timer.timeout.connect(self._poll_tick)

        # 掉线检测：独立常驻 timer（连接成功启动、断开停止），
        # 不依赖「自动轮询」开关——轮询关闭时由本 timer 兜底探测
        self._offline_timer = QTimer(self)
        self._offline_timer.setInterval(1000)
        self._offline_timer.timeout.connect(self._check_offline_modules)
        self._probe_index = 0  # 兜底探测逐台轮转索引

    # ------------------------------------------------------------ 连接
    def open(self, mode: str, ip: str = "", port: int = 0):
        self.close()
        self.mode = mode
        self.transport = create_transport(mode, parent=self)
        self.transport.connected.connect(self._on_connected)
        self.transport.disconnected.connect(self._on_disconnected)
        self.transport.error.connect(self.error)
        self.transport.frame_rx.connect(self._on_frame_rx)
        self.transport.frame_tx.connect(self._on_frame_tx)
        if mode == "tcp":
            self.log_line.emit(f"正在连接 UT-6502 {ip}:{port} …", "info")
            self.transport.open_host(ip, port)
        else:
            self.log_line.emit("已启用内置模拟从站（离线模式）", "info")
            self.transport.open()

    def close(self):
        self._scan_timer.stop()
        self._poll_timer.stop()
        self._offline_timer.stop()
        self._scanning = False
        if self.transport:
            try:
                self.transport.close()
            except Exception:
                pass
            finally:
                # 无论断开是否抛异常，transport 引用必须复位，保证状态必复位
                self.transport.deleteLater()
                self.transport = None

    def is_open(self) -> bool:
        return self.transport is not None and self.transport.is_open()

    def _on_connected(self):
        self.log_line.emit("连接成功", "info")
        self._probe_index = 0
        self._offline_timer.start()   # 掉线检测常驻，断开时停止
        self.connected.emit()

    def _on_disconnected(self):
        self._poll_timer.stop()
        self._scan_timer.stop()
        self._offline_timer.stop()
        self.log_line.emit("连接已断开", "info")
        self.disconnected.emit()

    # ------------------------------------------------------------ 扫描
    def start_scan(self):
        if not self.is_open():
            self.error.emit("尚未连接，无法扫描")
            return
        self._scanning = True
        self._scan_addr = P.ADDR_MODULE_MIN
        self.scan_started.emit()
        self.log_line.emit("开始扫描在线模块（地址 0~63）…", "info")
        self._scan_timer.start()

    def stop_scan(self):
        """中断扫描"""
        self._scan_timer.stop()
        self._scanning = False
        online = sum(1 for m in self.modules.values() if m.online)
        self.scan_finished.emit(online)
        if self.polling_enabled:
            self._poll_timer.start()

    def _scan_step(self):
        if self._scan_addr > P.ADDR_MODULE_MAX:
            self._scan_timer.stop()
            self._scanning = False
            online = sum(1 for m in self.modules.values() if m.online)
            self.log_line.emit(f"扫描完成，在线模块 {online} 个", "info")
            self.scan_finished.emit(online)
            if self.polling_enabled:
                self._poll_timer.start()
            return
        self.scan_progress.emit(self._scan_addr, P.ADDR_MODULE_MAX + 1)
        can_id, data = P.build_read(0x0040, self._scan_addr)
        self.transport.send(can_id, data)
        self._scan_addr += 1

    # ------------------------------------------------------------ 轮询
    def set_polling(self, enabled: bool, interval_ms: int = None):
        self.polling_enabled = enabled
        if interval_ms:
            self.poll_interval = int(interval_ms)
        self._poll_timer.setInterval(self.poll_interval)
        if enabled and self.is_open() and not self._scanning:
            self._poll_timer.start()
        else:
            self._poll_timer.stop()

    def _poll_tick(self):
        if not self.is_open():
            return
        for addr, st in list(self.modules.items()):
            if not st.online:
                continue
            for reg in POLL_REGS:
                can_id, data = P.build_read(reg, addr)
                self.transport.send(can_id, data)
            # 选中模块补读扩展遥测（温度/母线/交流相电压）
            if addr == self.selected_addr:
                for reg in EXT_TELEMETRY_REGS:
                    self.transport.send(*P.build_read(reg, addr))

    def _check_offline_modules(self):
        """模块掉线检测：常驻 timer 驱动，不依赖「自动轮询」开关。

        判定复用 last_seen 超时（原轮询 tick 内的逻辑移此）；自动轮询
        关闭时由本 timer 逐台轮转发一条状态读兜底探测，保证 last_seen
        有机会刷新、掉线仍可感知。阈值至少覆盖一轮兜底探测周期，
        避免「还没轮到」被误判。
        """
        if not self.is_open():
            return
        online = [st for st in self.modules.values() if st.online]
        if not online:
            return
        now = time.time()
        if self._poll_timer.isActive():
            grace_ms = max(OFFLINE_GRACE_MS, self.poll_interval * 4)
        else:
            grace_ms = max(OFFLINE_GRACE_MS,
                           self._offline_timer.interval() * (len(online) + 1))
        for st in online:
            if now - st.last_seen > grace_ms / 1000.0:
                st.online = False
                self.module_offline.emit(st.addr)
                self.module_updated.emit(st.addr, st)
                self.log_line.emit(f"模块 {st.addr} 超时无响应, 标记离线", "err")
        # 自动轮询关闭时兜底探测：逐台轮转发状态读，刷新在线模块 last_seen
        if not self._poll_timer.isActive() and not self._scanning:
            online_now = [st for st in self.modules.values() if st.online]
            if online_now:
                st = online_now[self._probe_index % len(online_now)]
                self._probe_index += 1
                self.transport.send(*P.build_read(0x0040, st.addr))

    def set_selected(self, addr):
        """设置当前选中模块，用于补读扩展遥测。"""
        self.selected_addr = addr

    # ------------------------------------------------------------ 设置
    def _send(self, can_id, data):
        if self.is_open():
            self.transport.send(can_id, data)
        else:
            self.error.emit("尚未连接，无法下发")

    def set_voltage(self, addr: int, volts: float):
        self._send(*P.build_set_voltage(volts, addr))

    def set_current(self, addr: int, amps: float):
        """按限流点(需求电流/额定电流)下发；额定电流未知时退化为整型电流下发。"""
        st = self.modules.get(addr)
        if st and st.rated_current:
            ratio = max(0.0, min(1.0, amps / st.rated_current))
            self._send(*P.build_set_current_ratio(ratio, addr))
        else:
            self._send(*P.build_set_current_int(amps, addr))

    def set_voltage_current(self, addr: int, volts: float, amps: float):
        self.set_voltage(addr, volts)
        self.set_current(addr, amps)

    def set_power(self, addr: int, on: bool):
        self._send(*P.build_power(on, addr))

    def set_group(self, addr: int, group: int):
        self._send(*P.build_set_group(group, addr))

    def set_addr_mode(self, addr: int, dip: bool):
        self._send(*P.build_set_addr_mode(dip, addr))

    def set_input_mode(self, addr: int, dc: bool):
        self._send(*P.build_set_input_mode(dc, addr))

    def set_altitude(self, addr: int, meters: int):
        self._send(*P.build_set_altitude(int(meters), addr))

    def set_output_power(self, addr: int, ratio: float):
        self._send(*P.build_set_output_power(ratio, addr))

    def set_ovp_point(self, addr: int, volts: float):
        self._send(*P.build_set_ovp_point(volts, addr))

    def set_ovp_related(self, addr: int, allow: bool):
        self._send(*P.build_set_ovp_related(allow, addr))

    def ovp_reset(self, addr: int):
        self._send(*P.build_ovp_reset(addr))

    def short_reset(self, addr: int):
        self._send(*P.build_short_reset(addr))

    # --- 广播（dst=0xFF, PTP=0）---
    def broadcast_power(self, on: bool):
        self._send(*P.build_power(on, P.ADDR_BROADCAST, ptp=P.PTP_BROADCAST))

    def broadcast_voltage_current(self, volts: float, amps: float, rated_current=None):
        self._send(*P.build_set_voltage(volts, P.ADDR_BROADCAST, ptp=P.PTP_BROADCAST))
        if rated_current:
            ratio = max(0.0, min(1.0, amps / rated_current))
            self._send(*P.build_set_current_ratio(ratio, P.ADDR_BROADCAST, ptp=P.PTP_BROADCAST))
        else:
            self._send(*P.build_set_current_int(amps, P.ADDR_BROADCAST, ptp=P.PTP_BROADCAST))

    def broadcast_set_int(self, reg: int, value: int):
        self._send(*P.build_set_int(reg, value, P.ADDR_BROADCAST, ptp=P.PTP_BROADCAST))

    def broadcast_set_float(self, reg: int, value: float):
        self._send(*P.build_set_float(reg, value, P.ADDR_BROADCAST, ptp=P.PTP_BROADCAST))

    # --- 组播（0~7 组用 0xFE+组号位；≥8 组用扩展地址 0xFD-group）---
    def _send_group(self, group: int, data: bytes):
        self._send(P.make_group_broadcast_id(group), data)

    def broadcast_group_power(self, group: int, on: bool):
        _cid, data = P.build_power(on, P.ADDR_GROUP_BROADCAST)
        self._send_group(group, data)

    def broadcast_group_voltage_current(self, group: int, volts: float, amps: float,
                                       rated_current=None):
        _cid, d1 = P.build_set_voltage(volts, P.ADDR_GROUP_BROADCAST)
        self._send_group(group, d1)
        if rated_current:
            ratio = max(0.0, min(1.0, amps / rated_current))
            _cid, d2 = P.build_set_current_ratio(ratio, P.ADDR_GROUP_BROADCAST)
        else:
            _cid, d2 = P.build_set_current_int(amps, P.ADDR_GROUP_BROADCAST)
        self._send_group(group, d2)

    def broadcast_group_set_int(self, group: int, reg: int, value: int):
        _cid, data = P.build_set_int(reg, value, P.ADDR_GROUP_BROADCAST)
        self._send_group(group, data)

    def broadcast_group_set_float(self, group: int, reg: int, value: float):
        _cid, data = P.build_set_float(reg, value, P.ADDR_GROUP_BROADCAST)
        self._send_group(group, data)

    def read_register(self, addr: int, reg: int):
        self._send(*P.build_read(reg, addr))

    # ------------------------------------------------------------ 收帧
    def _on_frame_rx(self, can_id: int, data: bytes):
        cid = P.parse_id(can_id)
        self.log_line.emit(self._fmt_rx(can_id, data), "rx")
        if cid.src > P.ADDR_MODULE_MAX or cid.dst != P.ADDR_MONITOR:
            return
        resp = P.parse_response(data)
        if resp is None:
            return
        if P.is_set_failed(resp):
            reason = self._fail_reason(resp.reg)
            self.set_failed.emit(cid.src, resp.reg, reason)
            self.log_line.emit(
                f"[设置失败] 模块 {cid.src} 拒绝 {reg_name(resp.reg)}"
                f"(0x{resp.reg:04X})：{reason}", "err")
            return
        if not P.is_response_ok(resp):
            return
        addr = cid.src
        st = self.modules.get(addr)
        is_new = st is None
        if is_new:
            st = ModuleState(addr)
            self.modules[addr] = st
        st.group = cid.group
        st.last_seen = time.time()
        self._apply(st, resp)
        if not st.online:
            st.online = True
            self.module_seen.emit(addr)
            self.log_line.emit(f"发现模块 地址={addr}", "info")
            if self.is_open():
                for reg in ONLINE_EXTRA_REGS:
                    self.transport.send(*P.build_read(reg, addr))
        self.module_updated.emit(addr, st)

    def _apply(self, st: ModuleState, resp: P.Response):
        reg, val = resp.reg, resp.value
        if reg == 0x0001:
            st.voltage = val
        elif reg == 0x0002:
            st.current = val
        elif reg == 0x0005:
            st.input_v = val
        elif reg == 0x0003:
            st.ratio = val
        elif reg == 0x0004:
            st.temp = val
        elif reg == 0x0040:
            st.status = int(val)
        elif reg == 0x0048:
            st.input_power = int(val)
        elif reg == 0x0012:
            st.rated_current = val
        elif reg == 0x0011:
            st.rated_power = val
        elif reg == 0x004B:
            st.work_mode = int(val)
        elif reg == 0x0043:
            st.dip_addr = int(val)
        elif reg == 0x0056:
            st.dcdc_ver = int(val) & 0xFFFF
        elif reg == 0x0057:
            st.pfc_ver = int(val) & 0xFFFF
        elif reg == 0x004A:
            st.altitude = int(val)
        elif reg == 0x0010:
            st.pfc_temp = val
        elif reg == 0x000B:
            st.panel_temp = val
        elif reg == 0x0008:
            st.bus_pos = val
        elif reg == 0x000A:
            st.bus_neg = val
        elif reg == 0x000C:
            st.ac_a = val
        elif reg == 0x000D:
            st.ac_b = val
        elif reg == 0x000E:
            st.ac_c = val

    @staticmethod
    def _fail_reason(reg: int) -> str:
        return {
            0x001E: "地址分配方式为「自动分配」时，通信设置组号无效",
            0x001F: "地址分配方式取值非法（仅支持 0x00000000 自动 / 0x00010000 拨码）",
            0x0046: "输入模式取值非法（仅支持 0x01 交流 / 0x02 直流）",
            0x0017: "海拔超出范围（1000~5000m）",
            0x0030: "当前状态不允许开机（输入模式不匹配或存在保护）",
        }.get(reg, "模块拒绝该设置")

    def _on_frame_tx(self, can_id: int, data: bytes):
        self.log_line.emit(self._fmt_tx(can_id, data), "tx")

    # ------------------------------------------------------------ 日志格式
    @staticmethod
    def _fmt_tx(can_id: int, data: bytes) -> str:
        cid = P.parse_id(can_id)
        ts = time.strftime("%H:%M:%S")
        head = f"[{ts}] TX  ID=0x{can_id:08X}  {P.fmt_hex(data)}"
        if len(data) >= 4:
            func = data[0]
            reg = (data[2] << 8) | data[3]
            if func == P.FUNC_READ:
                head += f"   读 {reg_name(reg)}(0x{reg:04X}) @{cid.dst}"
            elif func == P.FUNC_SET:
                head += f"   写 {reg_name(reg)}(0x{reg:04X}) @{cid.dst}"
        return head

    @staticmethod
    def _fmt_rx(can_id: int, data: bytes) -> str:
        cid = P.parse_id(can_id)
        ts = time.strftime("%H:%M:%S")
        head = f"[{ts}] RX  ID=0x{can_id:08X}  {P.fmt_hex(data)}"
        resp = P.parse_response(data)
        if resp and resp.value is not None:
            if resp.resp_type == P.RESP_FLOAT:
                head += f"   {reg_name(resp.reg)}= {resp.value:.2f}"
            else:
                head += f"   {reg_name(resp.reg)}= {resp.value} (0x{resp.value:08X})"
            head += f" @{cid.src}"
        return head