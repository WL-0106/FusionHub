"""
后台CAN通讯工作线程
架构: UI线程只投递命令到队列, 所有socket收发和模块数据字典操作
     统一在本线程的run()循环内完成, 避免跨线程竞争
"""
import time
import queue
import struct
from PyQt5.QtCore import QThread, pyqtSignal

from .can_protocol import (
    ModuleCommand, parse_can_id, parse_data_frame, parse_status_flags,
    parse_status_indicators,
    MSG_TYPE_SET_RESP, MSG_TYPE_READ_RESP, MSG_TYPE_READ_SN_RESP,
    CMD_DC_VOLTAGE, CMD_CHARGE_CURRENT, CMD_SET_VOLTAGE, CMD_SET_CURRENT,
    CMD_POWER_ONOFF, CMD_STATUS, CMD_READ_SN, CMD_GROUP,
    CMD_HILO_MODE_READ, CMD_BATTERY_VOLTAGE, CMD_VOLTAGE_FAST, CMD_CURRENT_FAST,
    CMD_EXTENDED, EXT_READ_MODE,
)
from .ut6502_driver import UT6502Driver

MAX_SCAN_ADDR = 63

# 开机模块喂狗周期(秒): 模块通讯看门狗超时会自动停机, 必须周期性重发开机命令
HEARTBEAT_INTERVAL = 0.4

# 连续无响应次数上限: 达到即判定模块从总线掉线, 令其退出轮询/喂狗
OFFLINE_FAIL_LIMIT = 3

RESPONSE_TYPES = {MSG_TYPE_SET_RESP, MSG_TYPE_READ_RESP, MSG_TYPE_READ_SN_RESP}


class ModuleData:
    def __init__(self, addr):
        self.addr = addr
        self.online = False
        self.power_on = False
        self.voltage = None
        self.current = None
        self.bus_voltage = None
        self.set_voltage = None
        self.set_current = None
        self.mode = None
        self.faults = []
        self.indicators = []
        self.status_raw = 0
        self.serial_number = None
        self.last_seen = 0

    def to_dict(self):
        return {
            "addr": self.addr,
            "online": self.online,
            "power_on": self.power_on,
            "voltage": self.voltage,
            "current": self.current,
            "bus_voltage": self.bus_voltage,
            "set_voltage": self.set_voltage,
            "set_current": self.set_current,
            "mode": self.mode,
            "faults": self.faults,
            "indicators": self.indicators,
            "status_raw": self.status_raw,
            "serial_number": self.serial_number,
        }


class CANWorker(QThread):
    sig_log = pyqtSignal(str, str)
    sig_module_updated = pyqtSignal(int, dict)
    sig_connection = pyqtSignal(bool, str)
    sig_scan_progress = pyqtSignal(int, int)
    sig_scan_done = pyqtSignal(list)
    sig_scan_found = pyqtSignal(int)
    sig_cmd_done = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.driver = UT6502Driver()
        self._running = False
        self._auto_poll = False
        self._poll_interval = 1000
        self._modules = {}
        self._fail_counts = {}   # addr -> 连续无响应计数
        self._monitor_addr = 0x01
        self._group_addr = 0x01
        self._scanning = False
        self._cmd_queue = queue.Queue()

    @property
    def connected(self):
        return self.driver.connected

    def get_module(self, addr):
        if addr not in self._modules:
            self._modules[addr] = ModuleData(addr)
        return self._modules[addr]

    def get_online_addrs(self):
        return [a for a, m in self._modules.items() if m.online]

    def connect_device(self, ip, port):
        try:
            self.driver.connect(ip, port)
            self.sig_connection.emit(True, f"已连接 {ip}:{port}")
            return True
        except Exception as e:
            self.sig_connection.emit(False, f"连接失败: {e}")
            return False

    def disconnect_device(self):
        self.driver.disconnect()
        self._auto_poll = False
        self._scanning = False
        self._fail_counts.clear()
        with self._cmd_queue.mutex:
            self._cmd_queue.queue.clear()
        for mod in self._modules.values():
            mod.online = False
            mod.power_on = False
        self.sig_connection.emit(False, "已断开连接")

    def set_auto_poll(self, enabled, interval_ms=1000):
        self._auto_poll = enabled
        self._poll_interval = interval_ms

    def set_addr_config(self, monitor_addr, group_addr):
        self._monitor_addr = monitor_addr
        self._group_addr = group_addr

    # ---------- 主线程调用: 仅入队, 不做任何I/O ----------
    def power_on(self, addr):
        self._cmd_queue.put(("power_on", (addr,)))

    def power_off(self, addr):
        self._cmd_queue.put(("power_off", (addr,)))

    def set_voltage_current(self, addr, voltage_v, current_a):
        self._cmd_queue.put(("set_vi", (addr, voltage_v, current_a)))

    def read_serial_number(self, addr):
        self._cmd_queue.put(("read_sn", (addr,)))

    def set_group(self, addr, new_group):
        self._cmd_queue.put(("set_group", (addr, new_group)))

    def initialize_module(self, addr):
        self._cmd_queue.put(("init", (addr,)))

    def set_hilo_mode(self, addr, high):
        self._cmd_queue.put(("hilo", (addr, high)))

    def set_work_mode(self, addr, mode):
        self._cmd_queue.put(("work_mode", (addr, mode)))

    def start_scan(self):
        self._scanning = True

    def stop_scan(self):
        self._scanning = False

    # ---------- worker线程内部 ----------
    def _send_cmd(self, can_id, data):
        ok = self.driver.send_can(can_id, data)
        hex_id = f"0x{can_id:08X}"
        hex_data = " ".join(f"{b:02X}" for b in data)
        self.sig_log.emit("TX", f"ID:{hex_id} [{hex_data}]")
        return ok

    def _send_and_wait(self, cmd_tuple, timeout=0.15):
        can_id, data = cmd_tuple
        self._send_cmd(can_id, data)
        return self._recv_responses(timeout)

    def _recv_responses(self, timeout=0.3):
        responses = []
        frames = self.driver.recv_can(timeout=timeout)
        if frames:
            for f in frames:
                self._process_rx(f, responses)
        return responses

    def _process_rx(self, frame, responses):
        can_id = frame["can_id"]
        data = frame["data"]
        if len(data) < 8:
            data = data + b'\x00' * (8 - len(data))
        hex_id = f"0x{can_id:08X}"
        hex_data = " ".join(f"{b:02X}" for b in data)
        self.sig_log.emit("RX", f"ID:{hex_id} [{hex_data}]")

        parsed = parse_data_frame(data)
        if not parsed:
            return

        msg_type = parsed["msg_type"]

        # 回显过滤: 只处理响应帧
        if msg_type not in RESPONSE_TYPES:
            return

        id_info = parse_can_id(can_id)
        module_addr = id_info["module_addr"]
        if module_addr == 0:
            return

        mod = self.get_module(module_addr)
        mod.online = True
        mod.last_seen = time.time()

        cmd_type = parsed["cmd_type"]
        cmd_data = parsed["cmd_data"]
        cmd_sup = parsed["cmd_sup"]

        if msg_type == MSG_TYPE_SET_RESP:
            if cmd_type == CMD_POWER_ONOFF:
                mod.power_on = (cmd_data == 0)
        elif msg_type == MSG_TYPE_READ_RESP:
            if cmd_type == CMD_DC_VOLTAGE:
                if cmd_data:
                    mod.voltage = cmd_data / 1000.0
            elif cmd_type == CMD_CHARGE_CURRENT:
                mod.current = cmd_data / 1000.0
            elif cmd_type == CMD_VOLTAGE_FAST:
                mod.voltage = cmd_data / 1000.0
            elif cmd_type == CMD_CURRENT_FAST:
                mod.current = cmd_data / 1000.0
            elif cmd_type == CMD_STATUS:
                mod.status_raw = cmd_data
                mod.faults = parse_status_flags(cmd_data)
                mod.indicators = parse_status_indicators(cmd_data)
            elif cmd_type == CMD_EXTENDED and cmd_sup == EXT_READ_MODE:
                mod.mode = cmd_data
        elif msg_type == MSG_TYPE_READ_SN_RESP:
            sn_high = (data[2] << 8) | data[3]
            sn_low = struct.unpack(">I", data[4:8])[0]
            mod.serial_number = f"{sn_high:04X}{sn_low:08X}"

        parsed["module_addr"] = module_addr
        responses.append(parsed)
        self.sig_module_updated.emit(module_addr, mod.to_dict())

    def _exec_queue(self):
        while True:
            try:
                name, args = self._cmd_queue.get_nowait()
            except queue.Empty:
                return
            if not self._running or not self.driver.connected:
                return
            try:
                self._exec_one(name, args)
            except Exception as e:
                self.sig_cmd_done.emit(f"命令执行异常: {e}")

    def _exec_one(self, name, args):
        cmd = ModuleCommand(args[0], self._group_addr, self._monitor_addr)
        if name == "power_on":
            mod = self.get_module(args[0])
            # 开机前先下发缓存的设定值, 保证模块按用户设定输出
            if mod.set_voltage is not None:
                can_id, data = cmd.set_voltage(mod.set_voltage)
                self._send_cmd(can_id, data)
                time.sleep(0.01)
            if mod.set_current is not None:
                can_id, data = cmd.set_current(mod.set_current)
                self._send_cmd(can_id, data)
                time.sleep(0.01)
            responses = self._send_and_wait(cmd.power_on(), 0.15)
            acked = any(
                r.get("msg_type") == MSG_TYPE_SET_RESP and r.get("cmd_type") == CMD_POWER_ONOFF
                for r in responses
            )
            if acked:
                mod.power_on = True
                mod.online = True
                mod.last_seen = time.time()
                self._fail_counts[args[0]] = 0
                self.sig_module_updated.emit(args[0], mod.to_dict())
                self.sig_cmd_done.emit(f"模块 0x{args[0]:02X} 已确认开机")
            else:
                self.sig_module_updated.emit(args[0], mod.to_dict())
                self.sig_cmd_done.emit(f"模块 0x{args[0]:02X} 无响应, 未开机")
        elif name == "power_off":
            mod = self.get_module(args[0])
            responses = self._send_and_wait(cmd.power_off(), 0.15)
            acked = any(
                r.get("msg_type") == MSG_TYPE_SET_RESP and r.get("cmd_type") == CMD_POWER_ONOFF
                for r in responses
            )
            mod.power_on = False
            mod.voltage = 0.0
            mod.current = 0.0
            self.sig_module_updated.emit(args[0], mod.to_dict())
            self.sig_cmd_done.emit(
                f"模块 0x{args[0]:02X} 关机命令{'已确认' if acked else '已发送 (无响应)'}"
            )
        elif name == "set_vi":
            addr, v, i = args
            can_id, data = cmd.set_voltage(v)
            self._send_cmd(can_id, data)
            time.sleep(0.02)
            can_id, data = cmd.set_current(i)
            self._send_cmd(can_id, data)
            self._recv_responses(0.1)
            mod = self.get_module(addr)
            mod.set_voltage = float(v)
            mod.set_current = float(i)
            self.sig_module_updated.emit(addr, mod.to_dict())
            self.sig_cmd_done.emit(f"模块 0x{addr:02X} 已设置 {v}V / {i}A")
        elif name == "read_sn":
            self._send_and_wait(cmd.read_serial_number(), 0.2)
            self.sig_cmd_done.emit(f"模块 0x{args[0]:02X} 序列号读取完成")
        elif name == "set_group":
            addr, new_group = args
            can_id, data = cmd.set_group(new_group)
            self._send_cmd(can_id, data)
            self._recv_responses(0.2)
            self.sig_cmd_done.emit(f"模块 0x{addr:02X} 组号已修改为 {new_group}")
        elif name == "init":
            self._send_and_wait(cmd.set_charge_mode(), 0.15)
            self.sig_cmd_done.emit(f"模块 0x{args[0]:02X} 已初始化为充电模式")
        elif name == "hilo":
            addr, high = args
            if high:
                self._send_and_wait(cmd.set_high_voltage_mode(), 0.15)
                self.sig_cmd_done.emit(f"模块 0x{addr:02X} 已设置高压模式")
            else:
                self._send_and_wait(cmd.set_low_voltage_mode(), 0.15)
                self.sig_cmd_done.emit(f"模块 0x{addr:02X} 已设置低压模式")
        elif name == "work_mode":
            addr, mode = args
            if mode == 0:
                self._send_and_wait(cmd.set_charge_mode(), 0.15)
                self.sig_cmd_done.emit(f"模块 0x{addr:02X} 已设置充电模式")
            else:
                self._send_and_wait(cmd.set_discharge_mode(), 0.15)
                self.sig_cmd_done.emit(f"模块 0x{addr:02X} 已设置放电模式")

    def _do_scan_pass(self):
        online_addrs = []
        total = MAX_SCAN_ADDR
        for i, addr in enumerate(range(1, MAX_SCAN_ADDR + 1)):
            if not self._running or not self.driver.connected or not self._scanning:
                break
            self.sig_scan_progress.emit(i + 1, total)
            cmd = ModuleCommand(addr, self._group_addr, self._monitor_addr)
            can_id, data = cmd.read_status()
            self._send_cmd(can_id, data)
            time.sleep(0.01)
            frames = self.driver.recv_can(timeout=0.2)
            if frames:
                for f in frames:
                    fdata = f["data"] + b'\x00' * (8 - len(f["data"]))
                    parsed = parse_data_frame(fdata)
                    if parsed and parsed["msg_type"] == MSG_TYPE_READ_RESP:
                        id_info = parse_can_id(f["can_id"])
                        if id_info["module_addr"] == addr:
                            online_addrs.append(addr)
                            self._fail_counts[addr] = 0
                            self._process_rx(f, [])
                            self.sig_scan_found.emit(addr)
                            break
            time.sleep(0.005)
        for addr, mod in self._modules.items():
            if addr not in online_addrs:
                mod.online = False
                mod.power_on = False
                self.sig_module_updated.emit(addr, mod.to_dict())
        self._scanning = False
        self.sig_scan_done.emit(online_addrs)

    def _check_responding(self, addr, responses):
        """连续无响应计数: 达到上限判定模块从总线掉线, 令其退出轮询/喂狗"""
        mod = self.get_module(addr)
        if any(r.get("module_addr") == addr for r in (responses or [])):
            self._fail_counts[addr] = 0
            return
        self._fail_counts[addr] = self._fail_counts.get(addr, 0) + 1
        if self._fail_counts[addr] >= OFFLINE_FAIL_LIMIT and mod.online:
            mod.online = False
            mod.power_on = False
            self._fail_counts[addr] = 0
            self.sig_module_updated.emit(addr, mod.to_dict())
            self.sig_cmd_done.emit(
                f"模块 0x{addr:02X} 连续 {OFFLINE_FAIL_LIMIT} 次无响应, 标记离线")

    def _service_powered(self, addr):
        """已开机模块: 重发设定值+开机命令(喂狗), 并读取实时数据"""
        cmd = ModuleCommand(addr, self._group_addr, self._monitor_addr)
        mod = self.get_module(addr)

        # 顺序按协议: 先设电压/限流点, 最后发开机命令(保证喂狗帧最新)
        if mod.set_voltage is not None:
            can_id, data = cmd.set_voltage(mod.set_voltage)
            self._send_cmd(can_id, data)
            time.sleep(0.005)
        if mod.set_current is not None:
            can_id, data = cmd.set_current(mod.set_current)
            self._send_cmd(can_id, data)
            time.sleep(0.005)
        can_id, data = cmd.power_on()
        self._send_cmd(can_id, data)
        time.sleep(0.005)

        for can_id, data in (cmd.read_status(), cmd.read_voltage(), cmd.read_current()):
            if not self._running or not self.driver.connected:
                return
            self._send_cmd(can_id, data)
            time.sleep(0.008)
        responses = self._recv_responses(0.15)
        self._check_responding(addr, responses)

    def _poll_single(self, addr):
        """未开机模块: 只读取状态与实时数据"""
        cmd = ModuleCommand(addr, self._group_addr, self._monitor_addr)
        mod = self.get_module(addr)
        for can_id, data in (cmd.read_status(), cmd.read_voltage(), cmd.read_current()):
            if not self._running or not self.driver.connected:
                return
            self._send_cmd(can_id, data)
            time.sleep(0.008)
        responses = self._recv_responses(0.15)
        self._check_responding(addr, responses)

        if not mod.power_on:
            # 关机：电压电流强制归零, 设定值本地缓存保留不变
            changed = (mod.voltage != 0.0 or mod.current != 0.0)
            mod.voltage = 0.0
            mod.current = 0.0
            if changed:
                self.sig_module_updated.emit(addr, mod.to_dict())

    def run(self):
        self._running = True
        poll_index = 0
        last_heartbeat = 0.0
        while self._running:
            if not self.driver.connected:
                time.sleep(0.1)
                continue

            # 命令队列优先处理
            self._exec_queue()
            if not self._running or not self.driver.connected:
                continue

            if self._scanning:
                self._do_scan_pass()
                continue

            # 1) 开机模块心跳保活: 始终执行, 不受"自动轮询"开关影响
            powered = [a for a, m in self._modules.items() if m.online and m.power_on]
            if powered and (time.time() - last_heartbeat) >= HEARTBEAT_INTERVAL:
                for addr in powered:
                    if not self._running or not self.driver.connected:
                        break
                    self._service_powered(addr)
                last_heartbeat = time.time()
                continue

            # 2) 数据轮询
            if self._auto_poll:
                online_addrs = [a for a, m in self._modules.items() if m.online]
                if online_addrs:
                    addr = online_addrs[poll_index % len(online_addrs)]
                    poll_index += 1
                    if self.get_module(addr).power_on:
                        self._service_powered(addr)
                    else:
                        self._poll_single(addr)
                    time.sleep(max(0.05, self._poll_interval / 1000.0 / len(online_addrs)))
                else:
                    self._recv_responses(0.05)
                    time.sleep(0.05)
            else:
                self._recv_responses(0.02)
                time.sleep(0.02)

    def stop(self):
        self._running = False
        self.wait(3000)
