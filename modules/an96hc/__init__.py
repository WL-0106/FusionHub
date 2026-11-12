# -*- coding: utf-8 -*-
"""AN9637HC 安规综合分析仪 · 融合页（仪器仪表分组）。

接入契约（与 modules.hbtw 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停止测试并断开（高压安全）

协议/传输/设备逻辑复用原上位机（protocol / transport / device / dialects / probe），
界面按 FusionHub 整体风格重建。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import An96hcPage


def create_page(parent=None):
    """构造并返回可嵌入的安规综合分析仪页。"""
    page = An96hcPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停止测试（高压）并断开连接。"""
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
