# -*- coding: utf-8 -*-
"""MFG-2000 信号发生器上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、断链、回收工作线程

原上位机为 tkinter 工程，命令表/分帧/协议栈/传输/模拟从站/语义接口
（mfg_host 包）零改动复用，界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import Mfg2000Page


def create_page(parent=None):
    """构造并返回可嵌入的 MFG-2000 控制页。"""
    page = Mfg2000Page()
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
