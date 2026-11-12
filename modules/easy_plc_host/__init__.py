# -*- coding: utf-8 -*-
"""汇川 EASY300/EASY500 PLC 上位机 · 融合页（PLC 分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、断链、回收线程

原上位机为 tkinter 工程，Modbus 协议栈/传输（TCP/RTU）/地址映射/后台轮询/
配置持久化零改动复用，界面按整体 UI 风格重建；强制输出二次确认。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import EasyPlcPage


def create_page(parent=None):
    """构造并返回可嵌入的汇川 PLC 控制页。"""
    page = EasyPlcPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停轮询、断链、回收线程（安全闭环）。"""
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
