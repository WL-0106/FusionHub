# -*- coding: utf-8 -*-
"""信捷 XD/XL 系列 PLC 上位机 · 融合页（PLC 分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、断链、保存监视配置

原上位机为 PySide6 工程，已迁移到 PyQt5 与本 UI 同栈；信捷软元件地址映射/
Modbus RTU/TCP 客户端/高层读写/轮询报警引擎/趋势曲线功能零改动，统一换肤。
"""
from PyQt5.QtWidgets import QSizePolicy

from .core.ui.main_window import MainWindow
from .core.ui.styles import APP_STYLE  # 原主题（工业风布局定义）
from instrument_hub.theme import QSS_EMBED


def create_page(parent=None):
    """构造并返回可嵌入的信捷 PLC 主窗口（QMainWindow 即 QWidget）。"""
    win = MainWindow()
    # 风格适配：原主题打底（保留布局尺寸），整体 UI 主题在后覆盖颜色
    win.setStyleSheet(APP_STYLE + QSS_EMBED)
    if parent is not None:
        win.setParent(parent)
    win.setMinimumSize(0, 0)
    win.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return win


def shutdown(page):
    """退出/卸载页面时：停轮询、断链、回收资源（安全闭环）。"""
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
