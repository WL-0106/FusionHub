# -*- coding: utf-8 -*-
"""继电器板卡(12CH) · 融合页（PLC 分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时断开链路、回收工作线程

Modbus 协议/传输/客户端复用原上位机 relay_hmi.py，界面按 FusionHub 整体风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import RelayPage


def create_page(parent=None):
    """构造并返回可嵌入的继电器板卡控制页。"""
    page = RelayPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：断开链路、停止轮询与工作线程。"""
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
