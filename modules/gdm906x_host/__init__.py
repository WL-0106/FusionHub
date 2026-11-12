# -*- coding: utf-8 -*-
"""GW Instek GDM-9060/9061 数字万用表上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.msp_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、断开、回收线程

SCPI 指令构建与读数解析 / 串口·TCP·模拟从站三通道 / 高层 API 与后台轮询
（core 包，零改动复用原上位机 gdm906x 逻辑层），界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import Gdm906xPage


def create_page(parent=None):
    """构造并返回可嵌入的 GDM-906X 万用表控制页。"""
    page = Gdm906xPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停轮询、停定时器、断链、回收线程（安全闭环）。"""
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
