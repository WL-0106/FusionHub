# -*- coding: utf-8 -*-
"""GPP 系列可编程直流电源上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时关闭输出并停驱动线程

原上位机为 PySide6 工程，已迁移到 PyQt5（Signal/exec 兼容替换）与本 UI 同栈；
驱动/SCPI/传输/记录/图表功能零改动，界面统一换肤适配整体 UI。
"""
from PyQt5.QtWidgets import QSizePolicy

from .core.ui.main_window import MainWindow
from .core.theme import APP_QSS
from instrument_hub.theme import QSS_EMBED


def create_page(parent=None):
    """构造并返回可嵌入的 GPP 电源主窗口（QMainWindow 即 QWidget）。"""
    win = MainWindow()
    # 风格适配：原主题打底（保留布局尺寸定义），整体 UI 主题在后覆盖颜色
    win.setStyleSheet(APP_QSS + QSS_EMBED)
    if parent is not None:
        win.setParent(parent)
    win.setMinimumSize(0, 0)
    win.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return win


def shutdown(page):
    """退出/卸载页面时：关闭输出、停驱动线程（电源安全闭环）。"""
    if page is None:
        return
    try:
        page.driver.shutdown(outputs_off=True)
    except Exception:
        pass
    try:
        from PyQt5.QtGui import QCloseEvent
        page.closeEvent(QCloseEvent())
    except Exception:
        pass
    try:
        page.close()
    except Exception:
        pass
