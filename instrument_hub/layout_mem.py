# -*- coding: utf-8 -*-
"""分割条位置记忆：拖动即写 QSettings，建页即恢复 —— 关平台重开布局不丢。

用法：模块页/面板构建完成后调 bind_splitters(root, scope)，一处接入全树生效。
键位 layout/{scope}/{序号}-{h|v}，序号取 QSplitter 创建序（findChildren 顺序），
同版本页面内稳定；拖动 splitterMoved 即存，恢复只在建页时做一次。
"""
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QSplitter


def _store() -> QSettings:
    # 显式作用域：与 main.py 的 setOrganizationName/ApplicationName("FusionHub") 同仓，
    # 裸 QApplication（冒烟/脚本）下也有效
    return QSettings("FusionHub", "FusionHub")


def bind_splitters(root, scope: str) -> int:
    """把 root 含子级的所有 QSplitter 尺寸按 scope 持久化并恢复上次值。

    返回绑定数量。已存尺寸非法时忽略并保留代码默认值。
    """
    settings = _store()
    n = 0
    for sp in root.findChildren(QSplitter):
        key = "layout/%s/%d-%s" % (scope, n, "h" if sp.orientation() == Qt.Horizontal else "v")
        n += 1
        saved = settings.value(key)
        if saved:
            try:
                sp.setSizes([int(x) for x in saved])
            except (TypeError, ValueError):
                pass

        def _save(_pos=None, _idx=None, _sp=sp, _k=key):
            _store().setValue(_k, _sp.sizes())

        sp.splitterMoved.connect(_save)
    return n
