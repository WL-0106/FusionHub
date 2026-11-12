# -*- coding: utf-8 -*-
"""二合一调试助手（串口调试 / MODBUS RTU）· 融合页（调试助手分组）。

接入契约（与 modules.msp_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停定时器、关串口/网络、关落盘文件、回收线程

收发与协议逻辑零改动复用原上位机 serial_assistant.py（core 包：SerialCore /
NetCore / Modbus CRC16 / HEX 解析 / 串口参数识别与降级），界面按整体 UI 风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import SerialDebugPage


def create_page(parent=None):
    """构造并返回可嵌入的二合一调试助手控制页。"""
    page = SerialDebugPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停定时器、关串口与网络、关落盘文件、回收线程（安全闭环）。"""
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
