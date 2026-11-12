# -*- coding: utf-8 -*-
"""FLUKE 8808A 上位机程序入口：启动 QApplication + 主窗口。"""
import sys

from PyQt5.QtWidgets import QApplication

from .ui_main import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FLUKE 8808A 上位机")
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
