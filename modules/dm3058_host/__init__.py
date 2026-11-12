# -*- coding: utf-8 -*-
"""RIGOL DM3058/DM3058E 万用表上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停止监控并断开

测量控制逻辑复用原上位机 dm3058 包，界面按 FusionHub 整体风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import Dm3058Page


def create_page(parent=None):
    """构造并返回可嵌入的 DM3058 控制页。"""
    page = Dm3058Page()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停止监控、断开连接、回收工作线程。"""
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
