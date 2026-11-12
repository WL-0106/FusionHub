# -*- coding: utf-8 -*-
"""IT8500 系列电子负载上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停工作线程、关闭拉载

原上位机为 PySide6 工程，已迁移到 PyQt5 与本 UI 同栈；驱动/协议/传输/
诊断/图表功能零改动，界面统一换肤适配整体 UI。
"""
from PyQt5.QtWidgets import QSizePolicy

from .core.gui.main_window import MainWindow
from .core.gui.style import APP_QSS  # 原主题（含布局尺寸定义）
from instrument_hub.theme import QSS_EMBED


def create_page(parent=None):
    """构造并返回可嵌入的 IT8500 主窗口（QMainWindow 即 QWidget）。"""
    win = MainWindow(sim_default=False)
    # 风格适配：原主题打底（保留布局尺寸），整体 UI 主题在后覆盖颜色
    win.setStyleSheet(APP_QSS + QSS_EMBED)
    if parent is not None:
        win.setParent(parent)
    win.setMinimumSize(0, 0)
    win.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return win


def shutdown(page):
    """退出/卸载页面时：停工作线程并关闭拉载（电子负载安全闭环）。"""
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
