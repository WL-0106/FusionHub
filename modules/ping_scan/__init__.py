# -*- coding: utf-8 -*-
"""网段Ping扫描助手 · 融合页（调试助手分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停止扫描线程

扫描核心逻辑来自原上位机 ping_net_assistant.py（ICMP 探活 / ARP / 目标解析 /
手写 xlsx 导出），界面按 FusionHub 整体风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import PingScanPage


def create_page(parent=None):
    """构造并返回可嵌入的网段 Ping 扫描页。"""
    page = PingScanPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时停止扫描线程与刷新定时器。"""
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
