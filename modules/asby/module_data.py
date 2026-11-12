# -*- coding: utf-8 -*-
"""
模块数据模型
"""

from .can_protocol import STATUS_NAMES, MODE_NAMES


class ModuleData:
    """单个模块的数据模型"""
    
    def __init__(self, addr):
        self.addr = addr          # 模块地址 (0x01~0x7F)
        self.online = False       # 是否在线
        self.power_on = False     # 是否开机
        self.voltage = 0.0        # 输出电压 (V)
        self.current = 0.0        # 输出电流 (A)
        self.bus_voltage = 0.0    # 电池电压 Vbat (V)，协议命令0x3D
        self.set_voltage = 0.0    # 设置电压 (V)
        self.set_current = 0.0    # 设置电流 (A)
        self.mode = 1             # 运行模式
        self.status = 0           # 状态标志位
        self.alarm1 = 0           # 告警1
        self.alarm2 = 0           # 告警2
        self.active_power = 0.0   # 有功功率 (W)
        self.reactive_power = 0.0 # 无功功率 (Var)
        self.apparent_power = 0.0 # 视在功率 (VA)
        self.serial_number = ""   # 序列号
        self.last_update = 0      # 最后更新时间戳
        self.last_seen = 0.0      # 最后收到该模块应答的时间(time.time)，掉线检测用
        self.selected = False     # 是否被选中
    
    def get_status_text(self):
        """获取状态文本"""
        return STATUS_NAMES.get(self.status, f"未知({self.status})")
    
    def get_mode_text(self):
        """获取模式文本"""
        return MODE_NAMES.get(self.mode, f"未知({self.mode})")
    
    def has_alarm(self):
        """是否有告警"""
        return self.alarm1 != 0 or self.alarm2 != 0
    
    def get_alarm_count(self):
        """获取告警数量"""
        count = 0
        for i in range(32):
            if self.alarm1 & (1 << i):
                count += 1
            if self.alarm2 & (1 << i):
                count += 1
        return count


class ModuleManager:
    """模块管理器"""
    
    def __init__(self, min_addr=0x01, max_addr=0x3F):
        self.min_addr = min_addr
        self.max_addr = max_addr
        self.modules = {}
        self._init_modules()
    
    def _init_modules(self):
        """初始化所有模块"""
        for addr in range(self.min_addr, self.max_addr + 1):
            self.modules[addr] = ModuleData(addr)
    
    def get_module(self, addr):
        """获取指定地址的模块"""
        return self.modules.get(addr)
    
    def get_all_modules(self):
        """获取所有模块列表，按地址排序"""
        return [self.modules[addr] for addr in sorted(self.modules.keys())]
    
    def get_online_modules(self):
        """获取在线模块列表"""
        return [m for m in self.get_all_modules() if m.online]
    
    def get_selected_modules(self):
        """获取被选中的模块列表"""
        return [m for m in self.get_all_modules() if m.selected]
    
    def set_selected(self, addr, selected):
        """设置模块选中状态"""
        if addr in self.modules:
            self.modules[addr].selected = selected
    
    def select_all(self):
        """全选"""
        for m in self.modules.values():
            m.selected = True
    
    def clear_selection(self):
        """清空选择"""
        for m in self.modules.values():
            m.selected = False
    
    def select_online_only(self):
        """仅选中在线模块"""
        for m in self.modules.values():
            m.selected = m.online
    
    def get_selected_count(self):
        """获取选中数量"""
        return sum(1 for m in self.modules.values() if m.selected)
    
    def get_online_count(self):
        """获取在线数量"""
        return sum(1 for m in self.modules.values() if m.online)
    
    def update_module_status(self, addr, status):
        """更新模块状态"""
        if addr in self.modules:
            m = self.modules[addr]
            m.status = status
            m.online = True
            m.last_update = 0  # 这里可以用time.time()
            # 根据状态判断是否开机
            m.power_on = status in [3, 4, 5, 6, 7, 8]  # 运行中的状态
            return True
        return False
    
    def update_module_voltage(self, addr, voltage_mv):
        """更新模块电压 (mV)"""
        if addr in self.modules:
            self.modules[addr].voltage = voltage_mv / 1000.0
            self.modules[addr].online = True
            return True
        return False
    
    def update_module_current(self, addr, current_ma):
        """更新模块电流 (mA)"""
        if addr in self.modules:
            self.modules[addr].current = current_ma / 1000.0
            self.modules[addr].online = True
            return True
        return False
    
    def update_module_set_voltage(self, addr, voltage_mv):
        """更新设置电压 (mV)"""
        if addr in self.modules:
            self.modules[addr].set_voltage = voltage_mv / 1000.0
            self.modules[addr].online = True
            return True
        return False
    
    def update_module_set_current(self, addr, current_ma):
        """更新设置电流 (mA)"""
        if addr in self.modules:
            self.modules[addr].set_current = current_ma / 1000.0
            self.modules[addr].online = True
            return True
        return False
    
    def update_module_mode(self, addr, mode):
        """更新运行模式"""
        if addr in self.modules:
            self.modules[addr].mode = mode
            self.modules[addr].online = True
            return True
        return False
    
    def update_module_alarm(self, addr, alarm1=None, alarm2=None):
        """更新告警信息"""
        if addr in self.modules:
            if alarm1 is not None:
                self.modules[addr].alarm1 = alarm1
            if alarm2 is not None:
                self.modules[addr].alarm2 = alarm2
            self.modules[addr].online = True
            return True
        return False

    def update_module_bus_voltage(self, addr, voltage_mv):
        """更新电池电压 Vbat (mV→V)。有符号解析，脏值不显示。"""
        if addr not in self.modules:
            return False
        raw = int(voltage_mv) & 0xFFFFFFFF
        signed = raw - 0x100000000 if raw & 0x80000000 else raw
        volts = signed / 1000.0
        # 电池电压应在 0~2000V；-19 / 0xFFFFFFED 一类无效
        if 0.05 <= volts <= 2000.0:
            self.modules[addr].bus_voltage = volts
        else:
            self.modules[addr].bus_voltage = 0.0
        self.modules[addr].online = True
        return True

    def update_module_power(self, addr, active=None, reactive=None, apparent=None):
        """更新功率"""
        if addr in self.modules:
            if active is not None:
                self.modules[addr].active_power = active
            if reactive is not None:
                self.modules[addr].reactive_power = reactive
            if apparent is not None:
                self.modules[addr].apparent_power = apparent
            self.modules[addr].online = True
            return True
        return False
    
    def set_offline(self, addr):
        """设置模块离线"""
        if addr in self.modules:
            self.modules[addr].online = False
            return True
        return False
    
    def mark_all_offline(self):
        """标记所有模块为离线"""
        for m in self.modules.values():
            m.online = False
