# -*- coding: utf-8 -*-
"""PK9015-32 32 通道模拟量输入模块上位机 · 融合页（采集卡分组）。

接入契约（与 modules.pk6011r_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、断链、关闭内嵌模拟从站、回收线程

Modbus-RTU 协议栈 / 寄存器表 / 换算 / 模拟从站（core 包），界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import Pk9015_32Page


def create_page(parent=None):
    """构造并返回可嵌入的 PK9015-32 32 通道模拟量输入模块控制页。"""
    page = Pk9015_32Page()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停轮询、断链、关闭模拟从站、回收线程（安全闭环）。"""
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
