# -*- coding: utf-8 -*-
"""美恩斯 MSP65/MSP62 直流电源上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.hspy_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、关输出、断开、回收协议栈线程

Modbus-RTU 协议栈 / 帧层 / 传输 / 模拟从站 / 寄存器表 / 设备语义层
（core 包，零改动复用原上位机逻辑层），界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import MspPage


def create_page(parent=None):
    """构造并返回可嵌入的美恩斯直流电源控制页。"""
    page = MspPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停轮询、关输出、断链、回收线程（安全闭环）。"""
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
