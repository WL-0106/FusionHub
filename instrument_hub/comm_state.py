# -*- coding: utf-8 -*-
"""通讯状态指示（全模块统一）。

语义（用户硬约束）：
- 串口/TCP 链路打开 ≠ 连接成功——指示灯保持「未连接」；
- 只有模块与设备真正实现通讯（收到有效应答/数据更新）才显示「连接成功」；
- 通讯丢失/断开回「未连接」。

模块用法（在收到有效应答的回调里）：
    from instrument_hub.comm_state import mark_ok, mark_lost
    mark_ok(self)      # 有效应答到达，通讯真正建立
    mark_lost(self)    # 超时/掉线（可选，断开时框架也会自动复位）
"""
from typing import Dict, Optional

from PyQt5.QtCore import QCoreApplication, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget

# page（模块根 QWidget）→ CommIndicator；destroyed 时自动清理
_REGISTRY: Dict[int, QWidget] = {}


class CommIndicator(QWidget):
    """通讯状态指示灯：● 未连接（灰红）/ ● 连接成功（绿）。"""

    _sig = pyqtSignal(bool)   # 工作线程 → 主线程安全更新

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ok = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.dot = QLabel("●")
        self.text = QLabel("未连接")
        self.text.setStyleSheet("font-weight:700;")
        lay.addWidget(self.dot)
        lay.addWidget(self.text)
        self.setToolTip("通讯状态：仅串口/TCP 链路打开时显示「未连接」，"
                        "与设备真正建立通讯（收到有效应答）才显示「连接成功」")
        self._sig.connect(self._apply, Qt.QueuedConnection)
        self._apply(False)

    @property
    def is_ok(self) -> bool:
        return self._ok

    def set_ok(self, ok: bool) -> None:
        """线程安全：主线程同步生效（按键复位即时可见），工作线程排队到主线程。"""
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() is app.thread():
            self._apply(bool(ok))
        else:
            self._sig.emit(bool(ok))

    def _apply(self, ok: bool) -> None:
        self._ok = ok
        if ok:
            self.dot.setStyleSheet("color:#10B981; font-size:14pt;")
            self.text.setText("连接成功")
            self.text.setStyleSheet("font-weight:700; color:#047857;")
        else:
            self.dot.setStyleSheet("color:#9CA3AF; font-size:14pt;")
            self.text.setText("未连接")
            self.text.setStyleSheet("font-weight:700; color:#6B7280;")


def attach(page, indicator: CommIndicator) -> None:
    """框架把指示灯登记到页面（同页重复 attach 以最新为准）。"""
    key = id(page)
    old = _REGISTRY.get(key)
    if old is not None and old is not indicator:
        try:
            old.deleteLater()
        except Exception:  # noqa: BLE001
            pass

    def _cleanup(_=None, k=key):
        _REGISTRY.pop(k, None)

    try:
        page.destroyed.connect(_cleanup)
    except Exception:  # noqa: BLE001
        pass
    _REGISTRY[key] = indicator


def _get(page) -> Optional[CommIndicator]:
    ind = _REGISTRY.get(id(page))
    return ind if isinstance(ind, CommIndicator) else None


def get_indicator(page) -> Optional[CommIndicator]:
    """取页面登记的通讯指示灯（框架判定用；未挂载返回 None）。"""
    return _get(page)


def mark_ok(page) -> None:
    """收到设备有效应答，通讯真正建立（可从工作线程调用）。"""
    ind = _get(page)
    if ind is not None:
        ind.set_ok(True)


def mark_lost(page) -> None:
    """通讯中断/掉线，回「未连接」（可从工作线程调用）。"""
    ind = _get(page)
    if ind is not None:
        ind.set_ok(False)


def reset(page) -> None:
    """断开/退出时复位为「未连接」。"""
    mark_lost(page)
