# -*- coding: utf-8 -*-
"""电阻变送器上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.tp613_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、断链、回收线程

Modbus-RTU 协议栈 / 寄存器定义复用 core.protocol（手写帧编解码 + 说明书寄存器表），
界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import ResTxPage


def create_page(parent=None):
    """构造并返回可嵌入的电阻变送器控制页。"""
    page = ResTxPage()
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
