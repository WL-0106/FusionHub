# -*- coding: utf-8 -*-
"""HSPY 可编程直流电源上位机（多机型融合版）· 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停记录、关输出、断开、回收工作线程

Modbus-RTU 协议栈 / 串口驱动 / 内置仿真 / 机型预设（HspyProtocol/HspyDevice/
HspySim/HspyModels）复用原上位机 core 包，界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import HspyPage


def create_page(parent=None):
    """构造并返回可嵌入的 HSPY 电源控制页。"""
    page = HspyPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停记录、关输出、断开链路、回收线程（安全闭环）。"""
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
