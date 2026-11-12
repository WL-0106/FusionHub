# -*- coding: utf-8 -*-
"""TP613 三相智能电量仪配置软件 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停采集、断链、回收通讯线程

原上位机为 PySide6/PyQt5 双兼容单文件工程，此处按字节码语义等价重建
（Modbus-RTU 协议/寄存器表/采集块逐地址一致），界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import Tp613Page


def create_page(parent=None):
    """构造并返回可嵌入的 TP613 配置页。"""
    page = Tp613Page()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停采集、断开链路、回收线程（安全闭环）。"""
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
