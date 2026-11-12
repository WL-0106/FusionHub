# -*- coding: utf-8 -*-
"""样式资源路径工具：运行时展开 %%ASSETS%%，兼容源码/冻结两种模式。"""
import os
import sys


def assets_dir() -> str:
    """arrow_*.png 等资源所在目录（正斜杠）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        base = os.path.dirname(here)  # 项目根
    return os.path.join(base, "assets").replace("\\", "/")


def expand_qss(qss: str) -> str:
    return qss.replace("%%ASSETS%%", assets_dir())
