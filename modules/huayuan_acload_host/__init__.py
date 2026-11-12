# -*- coding: utf-8 -*-
"""华源交流回馈式负载上位机 · 融合页（仪器仪表分组）。

接入契约（与 modules.msp_host 等一致）：
- create_page(parent) -> QWidget：构造可嵌入主窗口
- shutdown(page)：退出/卸载时停轮询、关输出、断开、回收工作线程

Modbus 协议栈 / 寄存器表 / 设备门面 / 模拟从站（core 包，复用原上位机逻辑层），
界面按整体 UI 风格重建：连接 → 运行控制/通道设置/设备信息/手动调试 + 实时监控 + 通讯日志。
"""
from PyQt5.QtWidgets import QSizePolicy

from .page import HuayuanLoadPage


def create_page(parent=None):
    """构造并返回可嵌入的交流回馈式负载控制页。"""
    page = HuayuanLoadPage()
    if parent is not None:
        page.setParent(parent)
    page.setMinimumSize(0, 0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return page


def shutdown(page):
    """退出/卸载页面时：停轮询、关输出、断链、回收线程（安全闭环）。"""
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
