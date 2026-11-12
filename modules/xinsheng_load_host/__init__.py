# -*- coding: utf-8 -*-
"""新胜负载箱上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.huayuan_acload_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、卸载（高危安全）、断开、回收工作线程

Modbus 栈 / 寄存器语义 / 模拟从站（core 包，复用原上位机协议层），
界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import XinshengLoadPage


def create_page(parent=None):
    """构造并返回可嵌入的新胜负载箱控制页。"""
    page = XinshengLoadPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停轮询、卸载负载、断链、回收线程（安全闭环）。"""
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
