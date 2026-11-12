# -*- coding: utf-8 -*-
"""中创智合采集卡 全系列上位机 · 融合页（采集卡分组）。

接入契约（与 modules.pk9018b_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、断链、关闭内嵌模拟从站、回收线程

温度 / 电压 / 电流 / 混合四大系列共用一套 Modbus 协议栈（core/modbus.py），
差异抽象成寄存器映射表（core/series.py），新增型号 = 加一条配置。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import ZczhPage


def create_page(parent=None):
    """构造并返回可嵌入的中创智合采集卡控制页。"""
    page = ZczhPage()
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
