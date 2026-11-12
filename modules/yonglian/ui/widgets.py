"""可复用控件：带全选框的表头、表格空态浮层、按钮工厂。"""

from PyQt5.QtCore import Qt, QRect, QEvent, pyqtSignal
from PyQt5.QtWidgets import (
    QHeaderView, QStyle, QStyleOptionButton, QPushButton, QWidget,
    QVBoxLayout, QLabel, QTableWidget,
)


class CheckableHeader(QHeaderView):
    """第 0 节绘制一个复选框，点击可全选/全不选。"""

    toggled = pyqtSignal(bool)

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._checked = False
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.sectionClicked.connect(self._on_clicked)

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.updateSection(0)

    def _on_clicked(self, index: int):
        if index == 0:
            self._checked = not self._checked
            self.updateSection(0)
            self.toggled.emit(self._checked)

    def paintSection(self, painter, rect, logical_index):
        super().paintSection(painter, rect, logical_index)
        if logical_index != 0:
            return
        painter.save()
        opt = QStyleOptionButton()
        size = 14
        opt.rect = QRect(rect.x() + (rect.width() - size) // 2,
                         rect.y() + (rect.height() - size) // 2, size, size)
        opt.state = QStyle.State_Enabled | QStyle.State_Active
        opt.state |= QStyle.State_On if self._checked else QStyle.State_Off
        self.style().drawPrimitive(QStyle.PE_IndicatorCheckBox, opt, painter, self)
        painter.restore()


class TableOverlay(QWidget):
    """覆盖在表格视口上的居中提示浮层（表格为空时显示）。"""

    def __init__(self, table: QTableWidget, title: str, lines=None):
        super().__init__(table.viewport())
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        self.box = QLabel()
        self.box.setObjectName("overlayBox")
        self.box.setAlignment(Qt.AlignCenter)
        self.box.setTextFormat(Qt.RichText)
        self.set_text(title, lines or [])
        lay.addWidget(self.box, 0, Qt.AlignCenter)
        table.viewport().installEventFilter(self)
        self.setGeometry(table.viewport().rect())

    def set_text(self, title: str, lines):
        html = f'<div style="font-size:11pt;color:#e6ecf2;">{title}</div>'
        for ln in lines:
            html += f'<div style="font-size:9pt;color:#aebbc8;margin-top:6px;">{ln}</div>'
        self.box.setText(html)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False


def make_button(text: str, kind: str = "", tooltip: str = "") -> QPushButton:
    """kind: primary/danger/success/warn/''(默认灰)。"""
    btn = QPushButton(text)
    if kind:
        btn.setObjectName({"primary": "btnPrimary", "danger": "btnDanger",
                           "success": "btnSuccess", "warn": "btnWarn"}.get(kind, ""))
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def hline():
    from PyQt5.QtWidgets import QFrame
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f