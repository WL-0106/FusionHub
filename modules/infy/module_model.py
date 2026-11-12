"""
充电模块数据模型
"""
from dataclasses import dataclass, field
from typing import List, Optional
from .protocol import InfyCANProtocol


@dataclass
class ChargingModule:
    """充电模块数据模型"""
    addr: int = 0  # 模块地址 0x00-0x3B

    # 在线状态
    online: bool = False
    last_update_time: float = 0.0
    resp_count: int = 0  # 连续有效回复计数(>=2才判定在线, 过滤噪声假在线)

    # 电源状态
    power_on: bool = False  # True=开机, False=关机

    # 电压电流 (定点格式 mV/mA)
    voltage: int = 0        # mV
    current: int = 0        # mA

    # 母线电压 (输入电压)
    bus_voltage_vab: float = 0.0
    bus_voltage_vbc: float = 0.0
    bus_voltage_vca: float = 0.0

    # 设置值
    set_voltage: int = 0    # mV
    set_current: int = 0    # mA

    # 状态
    group: int = 0
    temperature: int = 0    # ℃
    status0: int = 0
    status1: int = 0
    status2: int = 0
    status3: int = 0

    # 模块信息
    v_max: int = 0          # V
    v_min: int = 0          # V
    i_max: float = 0.0      # A
    p_rate: int = 0         # W

    # 外部电压/允许电流
    ext_voltage: float = 0.0
    allow_current: float = 0.0

    # 条码
    barcode: str = ""

    # 故障信息
    faults: List[str] = field(default_factory=list)
    states: List[str] = field(default_factory=list)  # 运行/配置状态(非告警)

    @property
    def voltage_v(self) -> float:
        return self.voltage / 1000.0

    @property
    def current_a(self) -> float:
        return self.current / 1000.0

    @property
    def set_voltage_v(self) -> float:
        return self.set_voltage / 1000.0

    @property
    def set_current_a(self) -> float:
        return self.set_current / 1000.0

    @property
    def power_w(self) -> float:
        return self.voltage_v * self.current_a

    @property
    def status_text(self) -> str:
        """状态文本"""
        if not self.online:
            return "离线"
        if self.faults:
            return "故障"
        if self.power_on:
            return "运行"
        return "待机"

    @property
    def fault_text(self) -> str:
        """故障文本"""
        if not self.faults:
            return "正常"
        return ", ".join(self.faults[:3])  # 最多显示3个故障

    @property
    def power_text(self) -> str:
        """电源状态: 开机/待机/关机
        判据(协议0x04状态表): 离线或DC侧关机(状态表1 bit0)=1 -> 关机;
        输出电压达到10V以上(模块DC侧真正输出, 排除待机微小电压) -> 开机;
        其余(上电但未输出) -> 待机
        """
        if not self.online:
            return "关机"
        if self.status1 & 0x01:          # DC侧处于关机状态(状态表1 bit0)
            return "关机"
        if self.voltage > 10000:         # 输出电压>10V, 模块DC侧真正工作
            return "开机"
        return "待机"

    def update_status(self, status_data: dict):
        """更新状态数据"""
        self.group = status_data.get('group', self.group)
        self.status3 = status_data.get('status3', self.status3)
        self.temperature = status_data.get('temperature', self.temperature)
        self.status2 = status_data.get('status2', self.status2)
        self.status1 = status_data.get('status1', self.status1)
        self.status0 = status_data.get('status0', self.status0)

        # 解析告警/状态(位定义见 InfyCANProtocol.decode_status_bits 注释)
        self.faults = InfyCANProtocol.decode_status_bits(
            self.status0, self.status1, self.status2, self.status3
        )
        self.states = InfyCANProtocol.decode_status_states(
            self.status0, self.status1, self.status2, self.status3
        )

        # 判断开关机状态: 状态表1 bit0=模块DC侧处于关机状态(1=关机)
        self.power_on = not bool(self.status1 & 0x01)

    def update_voltage_current(self, voltage_mv: int, current_ma: int):
        """更新电压电流"""
        self.voltage = voltage_mv
        self.current = current_ma

    def update_input_voltage(self, vab: float, vbc: float, vca: float):
        """更新输入电压"""
        self.bus_voltage_vab = vab
        self.bus_voltage_vbc = vbc
        self.bus_voltage_vca = vca

    def update_module_info(self, info: dict):
        """更新模块信息"""
        self.v_max = info.get('v_max', self.v_max)
        self.v_min = info.get('v_min', self.v_min)
        self.i_max = info.get('i_max', self.i_max)
        self.p_rate = info.get('p_rate', self.p_rate)

    def update_external(self, voltage: float, current: float):
        """更新外部电压和允许电流"""
        self.ext_voltage = voltage
        self.allow_current = current

    def to_dict(self) -> dict:
        """转换为字典显示"""
        return {
            'addr': f"0x{self.addr:02X}",
            'online': "在线" if self.online else "离线",
            'power': self.power_text,
            'voltage': f"{self.voltage_v:.2f}" if self.voltage > 0 else "---",
            'current': f"{self.current_a:.2f}" if self.current > 0 else "---",
            'bus_voltage': f"{self.bus_voltage_vab:.1f}" if self.bus_voltage_vab > 0 else "---",
            'set_voltage': f"{self.set_voltage_v:.2f}" if self.set_voltage > 0 else "---",
            'set_current': f"{self.set_current_a:.2f}" if self.set_current > 0 else "---",
            'mode': f"组{self.group}",
            'fault': self.fault_text,
            'temperature': f"{self.temperature}℃" if self.online else "---",
        }


class ModuleManager:
    """模块管理器"""

    def __init__(self, max_modules: int = 60):
        self.modules: List[ChargingModule] = []
        self.max_modules = max_modules
        self._init_modules()

    def _init_modules(self):
        """初始化模块列表"""
        for i in range(self.max_modules):
            self.modules.append(ChargingModule(addr=i))

    def get_module(self, addr: int) -> Optional[ChargingModule]:
        """获取模块"""
        if 0 <= addr < len(self.modules):
            return self.modules[addr]
        return None

    def update_online_status(self, addr: int, online: bool):
        """更新在线状态"""
        module = self.get_module(addr)
        if module:
            module.online = online
            if online:
                import time as _t
                module.last_update_time = _t.time()

    def get_online_modules(self) -> List[ChargingModule]:
        """获取在线模块列表"""
        return [m for m in self.modules if m.online]

    def get_selected_modules(self, selected_addrs: List[int]) -> List[ChargingModule]:
        """获取选中模块"""
        return [self.modules[i] for i in selected_addrs if 0 <= i < len(self.modules)]

    def check_offline(self, timeout_sec: float = 5.0) -> List[int]:
        """检查超时离线的模块，返回变更为离线的地址列表"""
        import time as _t
        now = _t.time()
        changed = []
        for m in self.modules:
            if m.online and m.last_update_time > 0:
                if now - m.last_update_time > timeout_sec:
                    m.online = False
                    m.power_on = False
                    m.faults = []
                    m.states = []
                    changed.append(m.addr)
        return changed

    def reset_all(self):
        """重置所有模块数据"""
        for m in self.modules:
            m.online = False
            m.power_on = False
            m.voltage = 0
            m.current = 0
            m.bus_voltage_vab = 0.0
            m.bus_voltage_vbc = 0.0
            m.bus_voltage_vca = 0.0
            m.faults = []
            m.states = []
            m.resp_count = 0
            m.status0 = 0
            m.status1 = 0
            m.status2 = 0
            m.status3 = 0
            m.last_update_time = 0.0
