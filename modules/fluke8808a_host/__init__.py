# -*- coding: utf-8 -*-
"""FLUKE 8808A 上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时清理（断开连接、回收协议栈线程）

原上位机为 PyQt5 工程（协议栈/寄存器表/传输/模拟器分层），原样嵌入并统一换肤，
风格适配整体 UI；功能（测量/量程/速率/触发/趋势图/自动测试）零改动。
"""
from PyQt5.QtWidgets import QSizePolicy

from .core.ui_main import MainWindow
from instrument_hub.theme import QSS_EMBED


def create_page(parent=None):
    """构造并返回可嵌入的 FLUKE 8808A 主窗口（QMainWindow 即 QWidget）。"""
    win = MainWindow()
    win.setStyleSheet(QSS_EMBED)      # 风格适配：替换原工程主题，统一为整体 UI 风格
    if parent is not None:
        win.setParent(parent)
    win.setMinimumSize(0, 0)
    win.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return win


def shutdown(page):
    """退出/卸载页面时触发原工程 closeEvent 清理（断开连接、回收线程）。"""
    if page is None:
        return
    try:
        from PyQt5.QtGui import QCloseEvent
        page.closeEvent(QCloseEvent())
    except Exception:
        pass
    try:
        page.close()
    except Exception:
        pass
