# -*- mode: python ; coding: utf-8 -*-
"""FusionHub 融合上位机打包配置（PyInstaller）。

设计目标（源码与构建彻底分离）：
- 本 spec 只描述「如何打包」，不碰任何源码；
- 源码目录永远是唯一事实源，改代码只在这里改；
- 打包产物（EXE + build 中间文件）输出到源码外的独立目录，可整体删除重建；
- 之后改完源码，重跑 build_release.bat 即出新的 EXE，无需复制代码、无需拆码。

新增资源（CAN 驱动 / 命令表 / 图标 / 字体等）时：
在下方 _datas 追加一行 (源相对项目根, 目标相对 _MEIPASS) 即可，其余不要动。
"""
import os

from PyInstaller.utils.hooks import collect_submodules

# 项目根 = 本 spec 所在目录（源码唯一事实源）
try:
    PROJ = SPECPATH  # PyInstaller 提供的全局变量
except NameError:
    PROJ = os.path.dirname(os.path.abspath(__file__))

# 产物输出：源码同级独立目录（源码外，零污染）
_PROJ_ROOT = os.path.dirname(PROJ)
DISTPATH = os.path.join(_PROJ_ROOT, "FusionHub_release")
WORKPATH = os.path.join(DISTPATH, "build")

# ---- 需要打进 EXE 的资源（源相对项目根 → 目标相对 _MEIPASS）----
_datas = [
    # CAN 驱动（en/youyou/asby/yonglian 等 UT-6502 / ZLG 模块）
    ("assets/ControlCAN.dll", "assets"),
    ("assets/zlgcan.dll", "assets"),
    ("assets/kerneldlls", "assets/kerneldlls"),          # ZLG 依赖 DLL + devices_property XML
    # 图标与图片
    ("assets/app.ico", "assets"),
    ("assets/app_icon.png", "assets"),
    ("assets/robot.png", "assets"),
    # 下拉箭头：全局主题（instrument_hub/theme.py）用 arrow_down；theme_util 用 up/drop
    ("instrument_hub/assets/arrow_down.png", "assets"),
    ("assets/arrow_up.png", "assets"),
    ("assets/arrow_drop.png", "assets"),
    # SCPI 命令表（MFG2000 单一事实源）
    ("modules/mfg2000_host/core/registers", "registers"),
]
datas = [(os.path.join(PROJ, src), tgt) for src, tgt in _datas]

# 动态 import 的模块包：module_page 用 importlib 按 CHARGE_MODULES 的 pkg 字段加载，
# 静态分析发现不了，必须显式收集为 hiddenimports。
hiddenimports = (
    collect_submodules("instrument_hub")
    + collect_submodules("instruments")
    + collect_submodules("modules")
)

a = Analysis(
    [os.path.join(PROJ, "main.py")],
    pathex=[PROJ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FusionHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # 不用 UPX，避免杀软误报
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJ, "assets", "app.ico"),
)
