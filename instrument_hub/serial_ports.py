# -*- coding: utf-8 -*-
"""串口枚举与串口下拉自动刷新（全模块统一）。

需求：所有串口连接的仪器，在上位机打开后自动刷新串口列表——
插上 USB 转串口即可见，无需手动点刷新；下拉候选始终反映系统实际端口。

用法：
    from instrument_hub.serial_ports import enumerate_ports, install_auto_refresh
    install_auto_refresh(page)   # 模块页加载后调用，纯串口型下拉自动接管
"""
import re
import sys

from PyQt5.QtCore import QEvent, QObject, QTimer

_COM_RE = re.compile(r"^(COM\d+|/dev/\S+)$", re.IGNORECASE)


def enumerate_ports():
    """枚举本机串口设备名列表（pyserial 优先，Windows 注册表兜底）。"""
    try:
        from serial.tools import list_ports
        return sorted((p.device for p in list_ports.comports()),
                      key=lambda s: (len(s), s))
    except Exception:  # noqa: BLE001
        pass
    if sys.platform.startswith("win"):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DEVICEMAP\SERIALCOMM")
            out = []
            i = 0
            while True:
                try:
                    _name, val, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                out.append(str(val))
                i += 1
            winreg.CloseKey(key)
            return sorted(set(out), key=lambda s: (len(s), s))
        except Exception:  # noqa: BLE001
            pass
    return []


def is_port_combo(combo) -> bool:
    """判断下拉是否含「纯串口名」候选（COMn / /dev/xxx）。

    只接管含纯串口名的下拉：带描述格式（COM4 - USB...）与纯 IP:端口下拉不接管，
    由模块自身维护。混合下拉（COM + TCP 候选）接管时只重建串口部分、保留其余候选。
    """
    items = [combo.itemText(i).strip() for i in range(combo.count())]
    items = [t for t in items if t]
    return any(_COM_RE.match(t) for t in items)


class PortComboRefresher(QObject):
    """串口下拉自动刷新：弹出前 / 周期检测端口集合，变化才重建候选。

    - 保留用户当前文本（手输未插的口不被打断）；
    - 枚举为空时保留原候选，不制造「COM1」假口。
    """

    def __init__(self, combo, parent=None):
        super().__init__(parent)
        self.combo = combo
        combo.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.combo and ev.type() == QEvent.Show:
            self.refresh()
        return False

    def refresh(self) -> None:
        combo = self.combo
        if combo is None:
            return
        try:
            if not is_port_combo(combo):
                return
            items = [combo.itemText(i).strip() for i in range(combo.count())]
            items = [t for t in items if t]
            ports = enumerate_ports()
            others = [t for t in items if not _COM_RE.match(t)]
            new_items = (ports or [t for t in items if _COM_RE.match(t)]) + others
            if new_items == items:
                return
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(new_items)
            if cur:
                combo.setCurrentText(cur)   # editable：保留用户选择/输入
            combo.blockSignals(False)
        except Exception:  # noqa: BLE001 —— 自动刷新永不打扰模块主流程
            pass


def install_auto_refresh(page):
    """给页面内所有纯串口型下拉装自动刷新（parent 挂 page，随页回收）。"""
    from PyQt5.QtWidgets import QComboBox
    out = []
    for combo in page.findChildren(QComboBox):
        if is_port_combo(combo):
            out.append(PortComboRefresher(combo, page))
    return out
