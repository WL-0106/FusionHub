# -*- coding: utf-8 -*-
"""youyou 模块包 — 单体统一上位机内嵌页。"""
from .main_window import MainWindow


def create_page(parent=None):
    """构造并返回可嵌入的主窗口（QMainWindow 即 QWidget）。"""
    win = MainWindow()
    if parent is not None:
        win.setParent(parent)
    # 嵌入模式：放开最小尺寸限制，让页面跟随壳布局伸缩
    win.setMinimumSize(0, 0)
    from PyQt5.QtWidgets import QSizePolicy
    win.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return win


def shutdown(page):
    """退出/卸载页面时触发原工程 closeEvent 清理逻辑。"""
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