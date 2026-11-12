# -*- coding: utf-8 -*-
"""Keysight Truevolt 系列 DMM 上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.dm3058_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停止采集、断开连接、回收工作线程

core/（原 dmm 包：commands 命令表单一事实源 / protocol SCPI 协议栈 /
semantic 语义接口 / transport 串口+LAN+回环传输 / mock_slave 模拟从站）
零改动复用，界面按 FusionHub 整体风格用 PyQt5 重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import KeysightDmmPage


def create_page(parent=None):
    """构造并返回可嵌入的 Keysight DMM 控制页。"""
    page = KeysightDmmPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停全部定时器、停/join 工作线程、断开仪器连接。"""
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
