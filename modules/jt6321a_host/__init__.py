# -*- coding: utf-8 -*-
"""JT6321A 电子负载上位机（Jartul JT632xA）· 融合入口。

原工程 tkinter，按 playbook 走路线 1：逻辑层（protocol/transport/device/simulator）
零改动复用（本目录 jt6321a/ 为原样拷贝），界面按 FusionHub 风格用 PyQt5 重建。
"""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget

from .page import JT6321APage


def create_page(parent=None) -> QWidget:
    page = JT6321APage(parent)
    page.setMinimumSize(0, 0)
    return page


def shutdown(page) -> None:
    if page is not None:
        page.shutdown()
