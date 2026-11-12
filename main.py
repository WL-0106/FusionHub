# -*- coding: utf-8 -*-
"""FusionHub 融合上位机 入口。

运行：python main.py
打包：PyInstaller onefile 单文件（EXE(..., a.binaries, a.datas, ...)），upx=False，console=False；
     交付前须只拷单 EXE 到空目录试装验证。
"""
import os
import sys
import traceback

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

CRASH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log")


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """槽函数未捕获异常只记录不终止：PyQt5 默认会 qFatal 直接崩掉整个上位机。

    除控制台外追加写 crash.log —— 窗口模式看不到 stderr，落盘才能事后查因。
    """
    traceback.print_exception(exc_type, exc_value, exc_tb)
    try:
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] 未捕获异常\n" % __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
            f.write("\n")
    except Exception:  # noqa: BLE001
        pass


sys.excepthook = _excepthook


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setOrganizationName("FusionHub")
    app.setApplicationName("FusionHub")
    app.setFont(QFont("Microsoft YaHei UI", 10))

    from instrument_hub.theme import apply_theme
    apply_theme(app)

    import instruments  # noqa: F401  注册内置仪器（新增仪器在此包内自动接入）
    from instrument_hub.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
