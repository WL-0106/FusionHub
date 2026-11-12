# -*- coding: utf-8 -*-
"""RU 灵巧系列可编程直流电源 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时关闭输出并断开（电源安全闭环）

Modbus-RTU 协议/寄存器/设备封装复用原上位机 ru 包，界面按 FusionHub 整体风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import RuPowerPage


def create_page(parent=None):
    """构造并返回可嵌入的 RU 电源控制页。"""
    page = RuPowerPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：关闭输出、断开链路。"""
    if page is None:
        return
    try:
        page.shutdown()
    except Exception:
        pass
    try:
        page.close()
    except Exception:
        pass
