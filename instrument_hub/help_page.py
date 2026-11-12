# -*- coding: utf-8 -*-
"""帮助手册协议页：使用说明 / 协议与调试规范（内容与开发规范保持一致）。"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
                             QLineEdit, QTreeWidget, QTreeWidgetItem, QTableWidget,
                             QTableWidgetItem, QSplitter, QStackedWidget, QPushButton,
                             QHeaderView, QAbstractItemView, QFrame, QDialog)

from . import module_page, registry
from .version import APP_VERSION
from .widgets import Card, Chip
from .protocol_detail import get_detail, build_table_row


def _bullets(items) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    for level, text in items:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        if level:
            colors = {"danger": ("危险", "#B01030", "#FFE4E6"),
                      "warn": ("注意", "#B45309", "#FEF3C7"),
                      "info": ("提示", "#1D4ED8", "#E0E7FF")}[level]
            chip = Chip(colors[0], colors[1], colors[2])
            chip.setFixedWidth(44)
            hl.addWidget(chip)
        lab = QLabel(text)
        lab.setWordWrap(True)
        hl.addWidget(lab, 1)
        lay.addWidget(row)
    return w


# ============================================================================
# 协议与调试规范页（左右分栏重设计）
# ============================================================================

_TBL_HEADERS = ["模块名称", "通信口", "通信协议", "默认波特率", "默认IP / 端口"]


def _wrap_scroll(page: QWidget, content: QWidget) -> QWidget:
    """把 content 包进免边框滚动区，整体作为页面返回。"""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
    scroll.setWidget(content)
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(scroll)
    return page


def _section_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("H2")
    lab.setStyleSheet("margin-top:4px;")
    return lab


def _kv_row(key: str, value: str) -> QWidget:
    """通信参数键值行：左侧灰标签 + 右侧取值。"""
    row = QWidget()
    hl = QHBoxLayout(row)
    hl.setContentsMargins(0, 1, 0, 1)
    hl.setSpacing(10)
    k = QLabel(key)
    k.setObjectName("Muted")
    k.setFixedWidth(90)
    k.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    hl.addWidget(k)
    v = QLabel(value)
    v.setWordWrap(True)
    v.setTextInteractionFlags(Qt.TextSelectableByMouse)
    hl.addWidget(v, 1)
    return row


def _make_table(headers, rows, stretch_cols=(), widths=None) -> QTableWidget:
    """构造只读表格：可拖拉列宽、行高自适应（内容不截断）、列间有分界线。

    stretch_cols：给定列走 Stretch（填满剩余宽，该列不可拖）；其余列 Interactive 可拖。
    widths：各列初始宽（Interactive 列生效），不给则按默认值。
    """
    tbl = QTableWidget(len(rows), len(headers))
    tbl.setHorizontalHeaderLabels(headers)
    tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
    tbl.setSelectionMode(QAbstractItemView.SingleSelection)
    tbl.setAlternatingRowColors(True)
    tbl.verticalHeader().setVisible(False)
    tbl.setShowGrid(True)            # 列间分界线（无分界=列糊成一片、拖不把手不可见）
    tbl.setWordWrap(True)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem(str(val))
            it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            it.setToolTip(str(val))   # 全文提示：窄列也能看全
            tbl.setItem(r, c, it)
    hdr = tbl.horizontalHeader()
    hdr.setTextElideMode(Qt.ElideNone)
    hdr.setMinimumSectionSize(64)
    hdr.setSectionResizeMode(QHeaderView.Interactive)
    hdr.setStretchLastSection(False)
    for c in stretch_cols:
        hdr.setSectionResizeMode(c, QHeaderView.Stretch)
    if widths:
        for c, w in enumerate(widths):
            if c < len(headers) and c not in stretch_cols:
                tbl.setColumnWidth(c, w)
    tbl.resizeRowsToContents()       # 行高自适应换行内容，杜绝省略号截断
    tbl.setMinimumHeight(min(220, 42 + 34 * len(rows)))
    return tbl


def _mono(text: str) -> QLabel:
    """等宽字体报文标签（HEX 举例）。"""
    lab = QLabel(text)
    lab.setStyleSheet("font-family:Consolas,'Courier New',monospace; font-size:12px; "
                      "color:#1E3A8A; background:#F5F7FF; border:1px solid #E0E7FF; "
                      "border-radius:6px; padding:4px 8px;")
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lab.setWordWrap(True)
    return lab


# ---------------------------------------------------------------------------
# 面板参数弹窗（模块面板按键/指示灯/数码管/故障码速查）
# ---------------------------------------------------------------------------

_PANEL_PARAMS: dict = {
    # 英飞源 REG1K070 面板按键操作指导（国网协议 / 旧网协议）
    "infy": {
        "title": "REG1K070 面板按键操作指导",
        "sub": "3 位显示数码管 + 两个方向按键（取消拨码开关）· 三色 LED 运行指示",
        "led": [
            ("运行指示灯", "绿色", [
                ("常灭", "无输入电源"),
                ("常亮", "有交流输入，正常状态"),
            ]),
            ("报警指示灯", "黄色", [
                ("常灭", "正常状态，无电压失压/缺相告警"),
                ("常亮", "输入过压、欠压、缺相、环境过温、地址重叠"),
                ("闪烁", "模块与上位机通讯中断"),
            ]),
            ("故障指示灯", "红色", [
                ("常灭", "正常状态，无电压损坏故障"),
                ("常亮", "输出过压、输出短路、风扇故障、温度故障、模块内部过温、模块内部原边电流中断、不良供电或无输出电流"),
            ]),
        ],
        "display_items": [
            ("输出电压", "默认显示项；关机显示 0FF，开机显示实际电压，精度 1V（100V 以下 0XX，100V 以上 XXX）"),
            ("输出电流", "实际输出电流，精度 1 位小数，无电流显示 00.0"),
            ("模块地址", "显示为 xxH，字母 H 固定；后两位十六进制为地址值（范围 0x20~0x9E），出厂默认 80H（0x80）"),
            ("模块组号", "显示为 Gxx，字母 G 固定；组号范围 0x00~0xFF，出厂默认固定分组 G01"),
            ("硬件版本", "模块整机版本号，如 A00、A01、B00 等"),
            ("软件版本", "软件版本号，如 b36、c01、d28 等"),
            ("故障代码", "显示为 Ex，字母 E 固定；后两位十六进制为当前故障信息（见故障代码表）"),
        ],
        "switch_order": (
            "上方向键（循环）：输出电压 → 输出电流 → 模块地址 → 模块组号 → 硬件版本 → 软件版本 → 故障代码",
            "下方向键（循环）：输出电压 → 故障代码 → 软件版本 → 硬件版本 → 模块组号 → 模块地址 → 输出电流",
            "显示故障状态且未下达「显示地址」命令时，切到其他显示项后 10s 无按键操作自动切回输出电压；"
            "若下达「显示地址」命令，数码管持续显示地址，直到取消命令后切回输出电压。",
        ),
        "errors": [
            ("E01", "交流输入掉线"),
            ("E02", "直流输出过压"),
            ("E03", "输出缺相/不均流"),
            ("E04", "过温"),
            ("E05", "直流输出短路故障"),
            ("E06", "风扇故障"),
            ("E07", "温度过高"),
            ("E08", "环境温度过低保护"),
            ("E09", "模块内部 Allan 故障/中断"),
            ("E10", "均充地址重复"),
            ("E11", "共享告警"),
            ("E12", "预留"),
        ],
        "address_setting": [
            "可设参数仅「模块地址」，范围 0x20~0x9F，设置值下电自动保存，下次开机默认为上一次设置值。",
            "地址设置方法：在显示页切换到「地址显示」，长按（约 3s）上或下方向键进入地址设置页（显示 xxH，当前可改位闪烁）。",
            "按上/下方向键在 0~F 之间循环设置当前位；短按下方按键切换可设置位（切换后该位闪烁）。",
            "设置值超出范围时自动跳回允许的最小值；设置完成后长按上或下方向键保存并退出。",
        ],
    },
    # 优优绿能 UBR100030 双向 ACDC 模块（面板按键 / 指示灯 / 数码管 / 故障码）
    "youyou": {
        "title": "UBR100030 面板按键操作指导",
        "sub": "双向 ACDC 模块 · 上键 ▲ / 下键 ▼ 两个按键 + 数码管显示 · 三色运行指示灯",
        "led": [
            ("电源指示灯", "绿色", [
                ("亮", "模块正常工作"),
                ("闪烁", "与监控或后台通信；监控或后台下发 DCDC 关机命令"),
            ]),
            ("保护指示灯", "黄色", [
                ("亮", "输入交流电压缺相导致功率降额；温度导致功率降额"),
                ("灭", "运行在自动模式正常工作"),
                ("闪烁", "运行在手动模式正常工作"),
            ]),
            ("故障指示灯", "红色", [
                ("闪烁", "风扇转动不正常"),
                ("亮", "EEPROM 故障；风扇驱动故障；交流输入过压/欠压；内部过温；"
                       "原边副边通信不正常；输出过压/欠压；交流过压脱离；序列号重复"),
            ]),
        ],
        "display_items": [
            ("输出电压", "显示实际输出电压，如 220（表示 220V）"),
            ("输出电流", "显示实际输出电流，如 05.0（表示 5A）"),
            ("模块地址", "显示为 Axx，地址范围 A01~A60（每组最大并机 60 个）"),
            ("模块分组号", "显示为 Gxx，分组号范围 G01~G15，仅同组内均流"),
            ("运行模式", "A-H 自动高压 / A-L 自动低压 / C-H 手动高压 / C-L 手动低压（A-U / C-U 为保留暂无含义）"),
            ("故障代码", "显示为 Exx，如 E00 无故障，见故障代码表"),
        ],
        "switch_order": (
            "上键 ▲ / 下键 ▼ 循环切换显示：输出电压 → 输出电流 → 模块地址 → 模块分组号 → 运行模式 → 故障代码（双向循环）。",
            "自动模式下按 ▲ 或 ▼ 仅用于查看模块信息，无法干预输出电压/限流点/开关机（这些由监控单元控制）。",
        ),
        "errors": [
            ("E00", "无故障"),
            ("E01", "输出欠压"),
            ("E02", "模块环境和内部温度过欠温"),
            ("E03", "交流输入过欠压、缺相"),
            ("E06", "输出过压"),
            ("E07", "序列号重复"),
            ("E08", "风扇停转"),
            ("E10", "输入电压类型为直流正向（DC+）输入状态（非故障代码）"),
            ("E11", "输入电压类型为单相输入状态（非故障代码）"),
            ("E12", "输入电压类型为直流反向（DC-）输入状态（非故障代码）"),
            ("E13", "输入电压类型不确定"),
            ("E14", "泄放故障"),
            ("E15", "母线不均压"),
            ("E16", "输出继电器故障"),
            ("E17", "收到监控器下发的紧急故障信号"),
            ("E18", "输出故障"),
        ],
        "address_setting": [
            "自动模式 → 手动模式转换：按 ▲ 或 ▼ 直到出现 A-H 或 A-L 界面 → 按 ▼ 约 2.5s 释放（显示 E00）→ "
            "再按 ▼ 约 2.5s 释放（显示 E99 并闪烁）→ 再按 ▼ 约 2.5s 释放（显示 E00）→ 按 ▲ 或 ▼ 回到 A-H / A-L → "
            "按 ▼ 约 2.5s 释放（A-H / A-L 闪烁）→ 再按 ▼ 出现 C-H / C-L → 按 ▼ 约 2.5s 保存，即进入手动模式。",
            "手动模式设置参数：① 按 ▲ 或 ▼ 切换到要更改的信息界面；② 按 ▲ 或 ▼ 约 2.5s 释放，显示开始闪烁；"
            "③ 按 ▲ 或 ▼ 更改设置值；④ 按 ▼ 约 2.5s 释放保存数据；若放弃更改，按 ▲ 约 2.5s 释放即回到原设置值。",
            "CAN 通讯地址范围 A01~A60（每组最大并机 60 个）；分组号范围 G01~G15，仅同组号模块间均流，组间不均流；"
            "不同组 CAN 总线可接同一主监控 CAN 口，同一电源系统内「分组号 + 模块地址」不能相同。",
            "模块序列号出厂已设置；模块 CAN 通讯用于均流及与监控通讯，需均流的模块接上 CAN 总线即可均流。",
        ],
    },
    # 禾享源 HBTW 充放电模块（新款面板 / 旧款拨码尾板两套接口与拨码定义）
    "hbtw": {
        "title": "禾享源模块面板 / 拨码尾板参数",
        "sub": "充放电模块 · 分「新款」（SW1 两位 + SW2 三位拨码）与「旧款」（拨码尾板，仅 SW1 两位拨码）两套接口布局",
        "led": [
            ("LED 指示灯", "黄色/绿色", [
                ("黄色亮", "上电后进入充放电待机状态"),
                ("绿色常亮", "收到充电指令或放电指令，进入正常工作状态"),
            ]),
        ],
        "errors": [
            ("电网过压", "电网电压高于上限值，告警并停止输出；故障恢复后进入待机状态"),
            ("电网欠压", "电网电压低于下限值，告警并停止输出；故障恢复后进入待机状态"),
            ("电池过压", "电池电压高于上限值，告警并停止输出；故障恢复后进入待机状态"),
            ("电池欠压", "电池电压低于下限值，告警并停止输出；故障恢复后进入待机状态"),
            ("电池过流", "电池电流超过电流设定值，告警并停止输出；故障恢复后进入待机状态"),
            ("风扇故障", "有风扇不能正常工作，告警并停止输出"),
            ("过温", "发热器件工作温度异常，告警并停止输出"),
            ("母线过压", "母线电压超过规定值，告警并停止输出"),
            ("母线欠压", "母线电压低于规定值，告警并停止输出"),
        ],
        "dip": [
            {
                "group": "新款 · SW1（2 位拨码开关，工作模式）",
                "headers": ["ID", "1#", "2#", "定义说明"],
                "rows": [
                    ["1", "ON", "ON", "单机工作模式，开机待机"],
                    ["2", "OFF", "ON", "并机模式，并机主机"],
                    ["3", "ON", "OFF", "并机模式，并机从机"],
                    ["4", "OFF", "OFF", "单机工作模式，开机输出电压"],
                ],
            },
            {
                "group": "新款 · SW2（3 位拨码开关，模块 ID 地址）",
                "headers": ["说明", "含义"],
                "rows": [
                    ["二进制拨码", "3 位二进制拨码开关，均为 OFF 时为 1# ID，依次递增"],
                ],
                "note": "SW2 用于设定模块 ID 地址，二进制编码，全 OFF 对应 1#，逐位递增。",
            },
            {
                "group": "旧款（拨码尾板）· SW1（2 位拨码开关）",
                "headers": ["ID", "1#", "2#", "定义说明"],
                "rows": [
                    ["1", "ON", "ON", "单机工作模式"],
                    ["2", "OFF", "ON", "并机主机"],
                    ["3", "ON", "OFF", "并机从机"],
                    ["4", "OFF", "OFF", "开机输出电压"],
                ],
                "note": "旧款拨码均为 ON 时开机进入工作状态，正常工作。",
            },
        ],
        "ports": [
            {
                "group": "新款 · 输入输出面板接口（共 10 个）",
                "items": [
                    ("1 三相交流电源接口", "⏚ 保护接地，A/B/C 为三相 L 相线（火线）；单根导线截面积 ≥6mm²(M4)"),
                    ("2 COM1、3 COM2", "内部调试使用，未对外开放"),
                    ("4 SW2 三位拨码开关", "二进制拨码，均为 OFF 时为 1# ID，依次递增"),
                    ("5 SW1 两位拨码开关", "工作模式选择（单机/并机主机/并机从机/开机输出），见拨码定义表"),
                    ("6 CR CAN 匹配电阻接口", "通过短路帽设定是否接入 120Ω 电阻；CAN 总线建议匹配电阻值 60Ω"),
                    ("7 CAN 通讯接口", "通过此接口操作上位机可控制 DC 电源开关机及读取电源工作状态"),
                    ("8 VS 外接远端电压采集", "需定制开放"),
                    ("9 直流电压输出负极", "单根导线截面积 ≥16mm²(M5)"),
                    ("10 直流电压输出正极", "单根导线截面积 ≥16mm²(M5)"),
                ],
            },
            {
                "group": "旧款 · 输入输出面板接口（共 12 个）",
                "items": [
                    ("① 三相交流输入端子", "⏚ 保护接地，A/B/C 为三相 L 相线（火线）；单根导线截面积 ≥6mm²(M4)"),
                    ("② COM 口", "内部调试使用，未对外开放"),
                    ("③ S2 CAN 匹配电阻接口", "短路帽设定是否接入 120Ω 电阻；CAN 总线建议匹配电阻值 60Ω"),
                    ("④ CAN2 通讯接口", "通过此接口操作上位机可控制 DC 电源开关机及读取电源工作状态"),
                    ("⑤ S1 CAN 匹配电阻接口", "短路帽设定是否接入 120Ω 电阻；CAN 总线建议匹配电阻值 60Ω"),
                    ("⑥ CAN1 通讯接口", "通过此接口实现并机"),
                    ("⑦ Is2 外端电流采样", "通过外接霍尔采集远端电流"),
                    ("⑧ Is1 远端电压采样", "通过外接实现远端电压采集或补偿"),
                    ("⑨ SW1 两位拨码开关", "拨码均为 ON 开机进入工作状态，正常工作；定义见拨码定义表"),
                    ("⑩ 直流输出负极", "单根导线截面积 ≥16mm²(M6)"),
                    ("⑪ 直流输出正极", "单根导线截面积 ≥16mm²(M6)"),
                ],
            },
        ],
        "address_setting": [
            "接线顺序：确认电压/交流输入范围匹配 → 直流正负极（极性勿接反，空开断开）→ 交流 L/PE 线（空开断开）→ 外接 CAN 通讯线缆，"
            "确认无误后先闭合交流空开、再合直流侧空开。",
            "上电后 LED 黄色亮=充放电待机；收到充/放电指令后 LED 绿灯常亮=正常工作；告警时参考故障信息表排查。",
            "CAN 匹配电阻：通过短路帽决定是否接入 120Ω，整条 CAN 总线建议匹配电阻值 60Ω（首末端各一个 120Ω 并联）。",
            "新款 SW2 三位二进制拨码设定模块 ID 地址（全 OFF=1#，依次递增）；SW1 两位拨码设定工作模式（单机/并机主机/并机从机）。",
        ],
    },
    # 安世博 UAB-1K030B-E 双向逆变充电器（面板按键 / 指示灯 / 数码管 / 故障码）
    "asby": {
        "title": "UAB-1K030B-E 面板按键操作指导",
        "sub": "双向逆变充电器 · 上键 ▲ / 下键 ▼ 两个按键 + 数码管显示 · 三色运行指示灯",
        "led": [
            ("电源指示灯", "绿色", [
                ("亮", "运行正常"),
                ("闪烁", "监控/后台通信；监控/后台下发 DCDC 关机命令"),
            ]),
            ("保护指示灯", "黄色", [
                ("亮", "交流电压或直流电压和温度导致功率降额；地址冲突"),
                ("灭", "运行正常"),
            ]),
            ("故障指示灯", "红色", [
                ("亮", "AC 过压/欠压/过频/欠频/不平衡；过温；原副边通信异常；DC 过欠压；"
                       "BUS 过/欠压；AC/DC 过流；启动失败；放电电路故障；ADC 采样偏置校准失败"),
                ("闪烁", "风扇故障"),
                ("灭", "无故障"),
            ]),
        ],
        "display_items": [
            ("DC 电压", "显示直流电压，如 750（750V）；AC 电压与 DC 电压通过个位后小数点区分（AC 如 400.）"),
            ("DC 电流", "显示直流电流，如 05.0（5A）"),
            ("模块地址", "显示为 Axx，地址范围 A01~A60（每组最大并机 60 个），默认 A01"),
            ("AC 电压", "显示交流电压，如 400.（400V）"),
            ("分组号", "显示为 Gxx，分组号范围 G01~G15"),
            ("故障代码", "显示为 Exx，如 E00 无故障，见故障代码表"),
            ("运行模式", "显示为 A-x，如 A-1 表示运行在模式 1"),
            ("协议", "显示为 b-x，如 b-1 / b-2 / b-3，对应不同 CAN 波特率"),
        ],
        "switch_order": (
            "上键 ▲ / 下键 ▼ 循环切换显示：DC 电压 → DC 电流 → 模块地址 → AC 电压 → 分组号 → 故障代码 → 运行模式 → 协议（双向循环）。",
            "AC 电压与 DC 电压通过「个位后小数点」加以区别：AC 电压带小数点（400.），DC 电压不带（750）。",
        ),
        "errors": [
            ("E00", "无故障"),
            ("E01", "DC 欠压"),
            ("E02", "环境过高温、内部器件过/高温"),
            ("E03", "AC 过/欠压"),
            ("E04", "AC 功率不平衡"),
            ("E05", "AC 电压不平衡"),
            ("E06", "DC 过压"),
            ("E07", "地址冲突（接地冲突）"),
            ("E08", "风扇故障"),
            ("E09", "DC 不均流"),
            ("E10", "AC 过/欠频"),
            ("E11", "BUS 过/欠压"),
            ("E12", "保留"),
            ("E13", "DC 过流"),
            ("E14", "AC 过流"),
            ("E15", "通信故障"),
            ("E16", "PFC 启动失败"),
            ("E17", "DCDC 启动失败"),
            ("E18", "ADC 采样偏置校准失败"),
            ("E19", "保留"),
            ("E20", "放电电路故障"),
        ],
        "address_setting": [
            "默认地址 A01。地址设置（待机状态下）：① 按 ▲ 或 ▼ 切换到地址信息界面；② 按 ▲ 或 ▼ 约 2.5s 释放，显示开始闪烁；"
            "③ 按 ▲ 或 ▼ 更改设置值；④ 按 ▼ 约 2.5s 释放保存数据；若放弃更改，按 ▲ 约 2.5s 释放即恢复到以前设置值。",
            "协议 b-1 / b-2 / b-3 下，模块 CAN 通信地址范围 A01~A60（每组最大并机 60 个）；分组号范围 G01~G15。",
            "同一电源系统中模块地址不能相同，否则模块黄灯闪烁并拒绝充电。",
            "协议号与模块地址支持待机模式下修改，运行时不可修改；组号待机和运行时都可修改。",
        ],
        "protocols": [
            ("b-1", "默认协议（波特率 125kbps）"),
            ("b-2", "默认协议（波特率 250kbps）"),
            ("b-3", "默认协议（波特率 500kbps）"),
        ],
        "ports": [
            {
                "group": "模块后端接口定义",
                "items": [
                    ("交流输入端子", "R、S、T、N、PE 五个端子"),
                    ("直流输出端子", "DC-、DC+"),
                    ("信号接口", "信号接口（通讯/监控）"),
                ],
            },
        ],
    },
    # TP613 多功能电量表（4 按键 + LCD 多级菜单 · Modbus RTU 三相电量仪）
    "tp613_host": {
        "title": "TP613 面板及操作说明",
        "sub": "多功能电量表 · 4 按键（确认 SET / 减少 / 增加 / 返回）+ LCD 大屏显示（默认白光）· 多级菜单",
        "keys": [
            ("① 确认键 SET", "长按 3 秒进入菜单；对修改的菜单值进行确认"),
            ("② 减少键", "菜单操作中进入数据修改/菜单切换；数值减少 / 菜单向左切换"),
            ("③ 增加键", "菜单操作中进入数据修改/菜单切换；数值增加 / 菜单向右切换"),
            ("④ 返回键", "菜单操作中返回上一层"),
        ],
        "display_items": [
            ("三相电压 / 线电压", "三相相电压或三相线电压显示"),
            ("零序电流", "漏电电流（剩余电流）测量显示"),
            ("三相电流", "A/B/C 三相电流显示"),
            ("三相有功功率", "三相总有功功率显示"),
            ("三相无功功率", "三相总无功功率显示"),
            ("三相视在功率", "三相总视在功率显示"),
            ("系统频率", "频率 40~65Hz 显示"),
            ("三相功率因数", "功率因数显示"),
            ("最大需量 / 当前需量", "按键可查看当前需量、最大需量"),
            ("电流/电压总谐波", "谐波分析功能（含总谐波）"),
            ("电压/电流不平衡度", "三相不平衡度显示"),
        ],
        "switch_order": (
            "测量状态下按键进行三相有功功率、三相无功功率、总功率、频率等画面循环切换显示。",
            "工作状态指示：DO1、DO2 在报警模式下作报警输出状态指示，在开关量「遥控」模式下作开关量输出状态指示；"
            "S1~S4 为开关量「遥控」输入状态指示；COM 闪动时表示正在通信。",
            "对显示页面选择 / 有功电度 / 无功电度有掉电保护功能。",
        ),
        "errors": [
            ("报警输出", "DO1/DO2 报警模式下作报警输出状态指示，报警方式 0-54 可选（值为 DO 时对应遥控模式）"),
            ("遥信输入", "S1~S4 四路开关量（无源）输入，用于「遥信」电气开关状态"),
            ("遥控输出", "DO1/DO2 两路继电器输出（250VAC/3A 或 30VDC/5A），控制量经 RS485 写入"),
            ("COM 通信", "COM 字符闪动表示当前正在通信"),
        ],
        "address_setting": [
            "长按 SET 键 >3 秒进入用户菜单（出厂默认密码 0001）；若已设密码，先输入正确密码。",
            "菜单操作：第 1 级长按 SET 进入下级；第 2/3 级点动返回键退回上一级；第 3 级长按减少/增加键改变数字闪动位、"
            "点动移位调整数值，按 SET 保存，按返回键不保存并退回第 2 级；修改完毕按 SET 确认。",
            "菜单结构（第 1 级）：系统设置（清除电能/用户密码/背光时间/翻页时间/软件版本）、信号输入（输入网络/电压变比/电流变比）、"
            "通信参数（仪表地址 1~9999/波特率 4800·9600·115200）、开关量设置（报警方式/报警动作值/回差/继电器选择/动作延时/结束时间）、"
            "模拟输出（变送模式/变送上下限）、时间设置、复费率设置（时段 1~8 费率，尖峰平谷 4 种）。",
            "清除电能：输入 1111 清除电能；输入 2222 清除最大需量；输入 1234 恢复出厂设置。",
            "背光时间单位为秒，数值 0 时不熄屏；翻页时间单位秒，数值 0 时不自动翻页。",
        ],
        "ports": [
            {
                "group": "基础版接线接口",
                "items": [
                    ("A1/B1", "RS485-1 北向（Modbus RTU 通信）"),
                    ("A2/B2", "RS485-2 南向（可支持定制）"),
                    ("V+/V-", "DC24V 接口输出"),
                    ("L/N", "交流 220V 电源接口"),
                    ("IA+/IA-、IB+/IB-、IC+/IC-", "A/B/C 三相电流输入/输出"),
                    ("IR+/IR-", "剩余电流互感器（漏电电流）"),
                    ("UA/UB/UC", "A/B/C 三相电压输入"),
                    ("AP/RP/SP", "有功/无功/视在电能脉冲输出（集电极开路光耦，3200imp/kWh）"),
                    ("PG", "AP/RP/SP 公共地（电能接地）"),
                ],
            },
        ],
    },
    # 福禄克 8808A 数字万用表（双显 + 键盘 + 前面板/后面板 · SCPI/RS-232）
    "fluke8808a_host": {
        "title": "FLUKE 8808A 前面板操作说明",
        "sub": "5-1/2 位真空荧光双显屏（主屏 + 副屏）· 键盘 + 输入端子 · SCPI/RS-232 程控",
        "keys": [
            ("INPUT VΩHI/LO", "电压、2 线/4 线电阻及频率测量输入端子；LO 为公共输入，隔离可安全隔离高于地 500V 峰；HI-LO 最大额定 1000V DC"),
            ("SENSE 4WΩ HI/LO", "4 线电阻测量端子"),
            ("C（COMP）", "比对功能，判断读数是否在规定限值范围内"),
            ("a~f（S1~S6）", "保存/调用最多 6 组测试配置"),
            ("CAL（内陷式按钮）", "校准万用表"),
            ("P", "激活/解除待机模式（省电）"),
            ("Q（SHIFT）", "激活功能按钮的第二功能；远程模式下锁定前面板"),
            ("K", "第一功能：选择打印模式；第二功能：设置 RS-232 通信参数（波特率/奇偶校验/回显）"),
            ("J", "第一功能：设置测量速度（慢/中/快）；第二功能：选择触发测量源"),
            ("I（HOLD）", "第一功能：接触保持（Touch Hold）；第二功能：设置最小响应电平"),
            ("T（REL）", "第一功能：相对读数；第二功能：设置相对基值"),
            ("W（dB）", "第一功能：dB 测量；第二功能：设置 dB 参考阻抗"),
            ("N（MIN MAX）", "保存最小和最大测量值"),
            ("功能键组", "选择测量功能：频率/直流电压/交流电压/直流电流/交流电流/电阻/通断性·二极管测试"),
            ("R", "手动/自动量程切换"),
            ("U/V", "手动量程模式下增大/减小量程"),
            ("10 A", "10 A 交流和直流电流输入端子"),
            ("200 mA", "200 mA 交流和直流电流输入端子"),
        ],
        "display_items": [
            ("r", "万用表处于远程模式（远程控制）"),
            ("L", "前面板被锁定"),
            ("Ext Trig", "处于外部触发模式"),
            ("S", "Q 键被按下，第二功能被选中"),
            ("RELΔ", "相对读数功能调节器被选中"),
            ("H", "接触保持（Touch Hold）功能被选中"),
            ("M", "最小/最大值功能调节器被选中"),
            ("MAX/MIN", "读数为最大或最小值"),
            ("2x4 Wire", "所选电阻测量方法（2 线或 4 线）"),
            ("R/G", "通断性测试或二极管测试功能被选中"),
            ("Slow/Medium/Fast", "所选测量速度（慢/中/快）"),
            ("Setup 8", "当前所选配置"),
            ("Auto/Manual Range", "自动/手动量程模式"),
            ("CAL Error", "校准失败"),
            ("Y", "检测到高压（电压 >30V 直流或交流有效值时显示）"),
            ("OL", "输入超过所选量程满刻度值，表示过载"),
        ],
        "switch_order": (
            "量程选择：按 R 在自动/手动量程间切换；自动量程下读数大于满刻度自动升档、小于 95% 满刻度自动降档；"
            "手动模式下按 U 升档、按 V 降档；手动量程仅适用于主屏读数。",
            "测量速度三档（慢/中/快），按 J 设置；频率测量固定 4 次/秒，二极管/导通测试恒为高速。",
            "选择测量功能：按对应功能键；选（ac+dc）总有效值读数需同时按下 A 和 D（或 B 和 E）保持 2 秒以上。",
            "功能调节器（REL/HOLD/MIN MAX/dB/COMP）可组合使用；调节器选中后按任意功能键即关闭所有调节器并返回主屏原始读数。",
            "接触保持（HOLD）：读数稳定后主屏显示并蜂鸣；最小响应电平可选 5%/7%/8% 量程。",
            "比对功能（COMP）：副屏显示 PASS（范围内）/ HI / LO（超限）；设上下限可长按 S+U（上限）或 S+V（下限）2 秒。",
        ),
        "errors": [
            ("OL", "输入超过所选量程满刻度值（过载），主/副屏显示 OL"),
            ("CAL Error", "校准失败"),
            ("Y", "检测到高压（电压 >30V 直流或交流有效值）"),
        ],
        "protocols": [
            ("RS-232 波特率", "300、600、1200、2400、4800、9600、19200（默认 9600）"),
            ("数据位/停止位", "8 位（或 7 位）数据、1 或 2 位停止位"),
            ("奇偶校验", "偶校验（Even）/奇校验（Odd）/无校验（No）"),
            ("回显模式", "开启/关闭"),
            ("打印模式速率", "0、1、2、5、10、20、50、100、200、500、1000、2000、5000、10000、20000、50000 读数"),
        ],
        "address_setting": [
            "第二功能（SHIFT）：按 Q 键后，随后按下的按钮执行其红色印刷的第二功能，仪器显示 S。",
            "第二功能速查：Q→A/D/B/E/F/O 在副屏显示交流/直流电压、交流/直流电流、频率、电阻读数；"
            "Q→I 设 HOLD 灵敏度门限；Q→T 编辑相对基值；Q→K 设 RS-232 通信参数；Q→J 设触发模式；"
            "Q→Q 关副屏；Q→U/V 编辑比对上下限；Q→J 显示软件版本号。",
            "列表编辑器（Q 放弃编辑）：按 U/V 滚动选项、按 R 选中，用于 HOLD 电平/打印速率/波特率/数据位/奇偶/停止位/回显/触发模式。",
            "数字编辑器（Q 中断）：编辑相对基值、比对上下限；U/V 调位、S1~S6 选位（S1 最左/S6 最右）、C 切正负号、R 长按 2 秒保存。",
            "功能键 S1~S6 保存/调用最多 6 组设置（Q+功能键保存；按功能键调用，蜂鸣 + Setup 8 指示最新配置）。",
            "出厂上电配置：直流电压、自动量程、慢速（2.5 读数/秒）、HOLD 灵敏度 1（5% 读数）；RS-232 波特率/奇偶/回显断电保持不变。",
        ],
        "ports": [
            {
                "group": "前面板输入端子",
                "items": [
                    ("INPUT VΩ HI/LO", "电压、2 线/4 线电阻、频率测量输入"),
                    ("SENSE 4WΩ HI/LO", "4 线电阻测量端子"),
                    ("10 A", "10 A 交流/直流电流输入"),
                    ("200 mA", "200 mA 交流/直流电流输入"),
                ],
            },
            {
                "group": "后面板特性",
                "items": [
                    ("电源线连接端子", "通过电源线连接电源（47~440Hz，12VA MAX）"),
                    ("电源开关", "接通/关断万用表电源"),
                    ("保险丝支架/电压选择器", "保险丝 1/8A 慢熔 100/120VAC、1/16A 慢熔 220/240VAC；可选 100/120/220/240 Vac"),
                    ("RS-232 连接器", "RS-232 与外部触发输入；连接主机、串行打印机或终端"),
                    ("接地端子", "提供接地连接"),
                ],
            },
        ],
    },
}


def _build_panel_param_dialog(module: dict, parent: QWidget) -> QDialog:
    """「面板参数」弹窗：模块面板按键/指示灯/数码管/故障码速查。"""
    data = _PANEL_PARAMS.get(module["id"])
    if not data:
        return None

    dlg = QDialog(parent)
    dlg.setWindowTitle(f"{module.get('name', module['id'])} · 面板参数")
    dlg.setModal(True)
    dlg.resize(680, 620)
    dlg.setStyleSheet("QDialog{background:#FFFFFF;}")

    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(22, 20, 22, 20)
    outer.setSpacing(12)

    # 标题
    t = QLabel(data["title"])
    t.setObjectName("H1")
    outer.addWidget(t)
    if data.get("sub"):
        s = QLabel(data["sub"])
        s.setObjectName("Muted")
        s.setWordWrap(True)
        outer.addWidget(s)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
    body = QWidget()
    blay = QVBoxLayout(body)
    blay.setContentsMargins(2, 2, 2, 2)
    blay.setSpacing(12)

    # 按键功能说明（可选项，如确认/减少/增加/返回四键）
    if data.get("keys"):
        blay.addWidget(_section_title("按键功能说明"))
        rows = [[k, v] for k, v in data["keys"]]
        blay.addWidget(_make_table(["按键", "功能"], rows, stretch_cols=(1,)))

    # 三色 LED 状态指示
    if data.get("led"):
        blay.addWidget(_section_title("三色 LED 状态指示"))
        c = Card("", "")
        for name, color, states in data["led"]:
            head = QLabel(f"<b>{name}</b>（{color}）")
            head.setTextFormat(Qt.RichText)
            c.body_lay.addWidget(head)
            rows = [[st, meaning] for st, meaning in states]
            tbl = _make_table(["状态", "异常原因"], rows, stretch_cols=(1,))
            tbl.setMinimumHeight(42 + 34 * len(rows))
            c.body_lay.addWidget(tbl)
        blay.addWidget(c)

    # 数码管显示项
    if data.get("display_items"):
        blay.addWidget(_section_title("数码管显示项"))
        rows = [[k, v] for k, v in data["display_items"]]
        blay.addWidget(_make_table(["显示项", "说明"], rows, stretch_cols=(1,)))

    # 按键切换循环顺序
    if data.get("switch_order"):
        blay.addWidget(_section_title("按键切换循环顺序"))
        blay.addWidget(_bullets([(None, x) for x in data["switch_order"]]))

    # 故障代码表
    if data.get("errors"):
        blay.addWidget(_section_title("故障代码表"))
        rows = [[c, m] for c, m in data["errors"]]
        blay.addWidget(_make_table(["代码", "含义"], rows, stretch_cols=(1,)))

    # 拨码开关定义（可多组，每组含 group 标题 + headers + rows）
    if data.get("dip"):
        blay.addWidget(_section_title("拨码开关定义"))
        for dip in data["dip"]:
            if dip.get("group"):
                g = QLabel(dip["group"])
                g.setObjectName("CardHeading")
                blay.addWidget(g)
            headers = dip.get("headers", ["位", "定义"])
            rows = dip.get("rows", [])
            blay.addWidget(_make_table(headers, rows, stretch_cols=(len(headers) - 1,)))
            if dip.get("note"):
                n = QLabel(dip["note"])
                n.setObjectName("Muted")
                n.setWordWrap(True)
                blay.addWidget(n)

    # 接口 / 端口介绍（可多组，每组含 group 标题 + items 列表）
    if data.get("ports"):
        blay.addWidget(_section_title("接口 / 端口介绍"))
        for port in data["ports"]:
            if port.get("group"):
                g = QLabel(port["group"])
                g.setObjectName("CardHeading")
                blay.addWidget(g)
            rows = port.get("items", [])
            blay.addWidget(_make_table(["接口", "说明"], rows, stretch_cols=(1,)))

    # 通信协议选项（可选项，如 b-1/b-2/b-3 对应不同波特率）
    if data.get("protocols"):
        blay.addWidget(_section_title("通信协议"))
        rows = [[k, v] for k, v in data["protocols"]]
        blay.addWidget(_make_table(["协议", "说明"], rows, stretch_cols=(1,)))

    # 地址设置
    if data.get("address_setting"):
        blay.addWidget(_section_title("模块地址设置"))
        blay.addWidget(_bullets([(None, x) for x in data["address_setting"]]))

    blay.addStretch(1)
    scroll.setWidget(body)
    outer.addWidget(scroll, 1)

    # 关闭按钮
    btn_close = QPushButton("关闭")
    btn_close.setCursor(Qt.PointingHandCursor)
    btn_close.setFixedHeight(34)
    btn_close.setStyleSheet("QPushButton{background:#4F46E5; color:#FFFFFF; "
                            "border:none; border-radius:8px; font-weight:700; padding:2px 28px;}"
                            "QPushButton:hover{background:#4338CA;}")
    btn_close.clicked.connect(dlg.accept)
    hb = QHBoxLayout()
    hb.addStretch(1)
    hb.addWidget(btn_close)
    outer.addLayout(hb)

    return dlg


def _build_detail_panel(module: dict, parent_page: QWidget, on_back) -> QWidget:
    """某模块的协议详情面板（内嵌于右侧 stack）。"""
    detail = get_detail(module["id"])
    name = module.get("name", module["id"])
    vendor = module.get("vendor", "-")
    proto = module.get("proto", "-")

    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(6, 6, 6, 6)
    lay.setSpacing(10)

    # 顶部：返回按钮 + 标题
    head = QHBoxLayout()
    head.setSpacing(10)
    btn_back = QPushButton("← 返回总览")
    btn_back.setCursor(Qt.PointingHandCursor)
    btn_back.setFixedHeight(30)
    btn_back.setStyleSheet("QPushButton{background:#EEF0FF; color:#4F46E5; "
                           "border:1px solid #C7C3F0; border-radius:8px; font-weight:700; padding:2px 12px;}"
                           "QPushButton:hover{background:#E0E7FF;}")
    btn_back.clicked.connect(on_back)
    head.addWidget(btn_back)
    t = QLabel(f"{name}（{vendor}）")
    t.setObjectName("H2")
    head.addWidget(t)
    head.addStretch(1)
    # 面板参数按钮（该模块登记了面板按键/指示灯/数码管速查时显示）
    if module["id"] in _PANEL_PARAMS:
        btn_panel = QPushButton("面板参数")
        btn_panel.setCursor(Qt.PointingHandCursor)
        btn_panel.setFixedHeight(30)
        btn_panel.setStyleSheet("QPushButton{background:#FFF7ED; color:#B45309; "
                                "border:1px solid #F3D8B0; border-radius:8px; font-weight:700; padding:2px 14px;}"
                                "QPushButton:hover{background:#FFEDD5;}")
        btn_panel.clicked.connect(
            lambda: (_build_panel_param_dialog(module, parent_page) or QDialog(parent_page)).show())
        head.addWidget(btn_panel)
    head.addWidget(Chip(proto, "#4F46E5", "#EEF0FF"))
    lay.addLayout(head)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
    body = QWidget()
    blay = QVBoxLayout(body)
    blay.setContentsMargins(2, 2, 2, 2)
    blay.setSpacing(12)

    # 通信参数卡
    if detail:
        c_comm = Card("通信参数", "")
        for cp in detail.comm:
            c_comm.body_lay.addWidget(_kv_row(cp.key, cp.value))
        blay.addWidget(c_comm)

        # 功能码
        if detail.func_codes:
            blay.addWidget(_section_title("主要功能码 / 命令"))
            rows = [[f.code, f.name, f.desc] for f in detail.func_codes]
            blay.addWidget(_make_table(["功能码", "名称", "说明"], rows, stretch_cols=(2,)))

        # 寄存器表
        if detail.registers:
            blay.addWidget(_section_title("相关寄存器"))
            rows = [[r.addr, r.name, r.rw, r.note] for r in detail.registers]
            blay.addWidget(_make_table(["地址", "名称", "读写", "说明"], rows, stretch_cols=(3,)))

        # 报文举例（请求 + 返回）
        if detail.frames:
            blay.addWidget(_section_title("报文举例（请求 / 返回）"))
            c_frm = Card("", "")
            for f in detail.frames:
                ft = QLabel(f"<b>{f.title}</b>")
                ft.setTextFormat(Qt.RichText)
                c_frm.body_lay.addWidget(ft)
                r1 = QWidget()
                h1 = QHBoxLayout(r1)
                h1.setContentsMargins(0, 0, 0, 0)
                h1.setSpacing(8)
                l1 = QLabel("请求")
                l1.setObjectName("Muted")
                l1.setFixedWidth(40)
                h1.addWidget(l1)
                h1.addWidget(_mono(f.req), 1)
                c_frm.body_lay.addWidget(r1)
                r2 = QWidget()
                h2 = QHBoxLayout(r2)
                h2.setContentsMargins(0, 0, 0, 0)
                h2.setSpacing(8)
                l2 = QLabel("返回")
                l2.setObjectName("Muted")
                l2.setFixedWidth(40)
                h2.addWidget(l2)
                h2.addWidget(_mono(f.resp), 1)
                c_frm.body_lay.addWidget(r2)
            blay.addWidget(c_frm)

        # 故障信息表
        if detail.errors:
            blay.addWidget(_section_title("故障信息表"))
            rows = [[e.code, e.name, e.fix] for e in detail.errors]
            blay.addWidget(_make_table(["代码", "含义", "建议处理"], rows, stretch_cols=(2,)))

        # 补充说明
        if detail.notes:
            blay.addWidget(_section_title("补充说明"))
            blay.addWidget(_bullets([("info", n) for n in detail.notes]))
    else:
        # 未登记结构化详情：回退到 proto_note 纯文本
        note = module.get("proto_note", "") or module.get("summary", "")
        c = Card("协议说明", "该模块尚未录入结构化协议详情，以下为注册表协议要点")
        lab = QLabel(note)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        c.body_lay.addWidget(lab)
        blay.addWidget(c)

    blay.addStretch(1)
    scroll.setWidget(body)
    lay.addWidget(scroll, 1)
    return panel


def _build_protocol_page(content: QWidget) -> None:
    """协议与调试规范页：左目录+搜索，右表格/协议详情内嵌切换。"""
    lay = content.layout()

    title = QLabel("协议与调试规范")
    title.setObjectName("H1")
    lay.addWidget(title)
    sub = QLabel("各仪器 / 模块通讯协议总览 + 结构化协议详情（功能码 / 寄存器 / 报文 / 故障码）· 左侧目录可搜索")
    sub.setObjectName("Muted")
    lay.addWidget(sub)

    # 模块分组
    groups: dict = {}
    for m in module_page.all_modules():
        groups.setdefault(m.get("group", module_page.GROUP), []).append(m)

    # ---- 左侧：搜索 + 目录树 ----
    left = QWidget()
    left.setFixedWidth(280)
    ll = QVBoxLayout(left)
    ll.setContentsMargins(0, 0, 0, 0)
    ll.setSpacing(8)

    search = QLineEdit()
    search.setObjectName("SearchBox")
    search.setPlaceholderText("搜索模块 / 协议 / 关键词…")
    ll.addWidget(search)

    tree = QTreeWidget()
    tree.setObjectName("NavTree")
    tree.setHeaderHidden(True)
    tree.setIndentation(16)
    tree.setAnimated(True)
    tree.setRootIsDecorated(True)
    ll.addWidget(tree, 1)

    # 填目录树：分组 → 模块；item 存 module id（UserRole）
    for grp in registry.NAV_GROUPS:
        mods = groups.get(grp) or []
        if not mods:
            continue
        gitem = QTreeWidgetItem([f"{grp}（{len(mods)}）"])
        gitem.setFlags(gitem.flags() & ~Qt.ItemIsSelectable)
        gitem.setData(0, Qt.UserRole, f"__grp__{grp}")
        f = gitem.font(0)
        f.setBold(True)
        gitem.setFont(0, f)
        for m in mods:
            mitem = QTreeWidgetItem([m["name"]])
            mitem.setData(0, Qt.UserRole, m["id"])
            gitem.addChild(mitem)
        tree.addTopLevelItem(gitem)
    tree.expandAll()

    # ---- 右侧：stack（总览表格 / 详情面板） ----
    stack = QStackedWidget()

    # Page 0：协议总览表格
    overview = QWidget()
    ol = QVBoxLayout(overview)
    ol.setContentsMargins(0, 0, 0, 0)
    ol.setSpacing(8)
    oh = QLabel("协议总览（点击左侧模块查看结构化协议详情）")
    oh.setObjectName("CardHeading")
    ol.addWidget(oh)
    rows = []
    for m in module_page.all_modules():
        r = build_table_row(m)
        rows.append([r["name"], r["iface"], r["proto"], r["baud"], r["ip_port"]])
    # 五列全部 Interactive 可拖拉（不设 Stretch 列），初始宽按内容配比
    tbl = _make_table(_TBL_HEADERS, rows, stretch_cols=(),
                      widths=[180, 170, 230, 130, 190])
    tbl.setMinimumHeight(300)
    ol.addWidget(tbl, 1)
    stack.addWidget(overview)

    # Page 1：协议详情（占位，点目录项时动态填充）
    detail_host = QWidget()
    dhl = QVBoxLayout(detail_host)
    dhl.setContentsMargins(0, 0, 0, 0)
    stack.addWidget(detail_host)

    # 右侧容器（表格 + 详情切换）
    right = QWidget()
    rl = QVBoxLayout(right)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.addWidget(stack, 1)

    # ---- 左右分栏 ----
    split = QSplitter(Qt.Horizontal)
    split.addWidget(left)
    split.addWidget(right)
    split.setStretchFactor(0, 0)
    split.setStretchFactor(1, 1)
    split.setCollapsible(0, False)
    split.setCollapsible(1, False)
    lay.addWidget(split, 1)

    # ---- 交互：搜索过滤 + 点目录项切详情 ----
    def _rebuild_tree(keyword: str):
        kw = keyword.strip().lower()
        tree.clear()
        for grp in registry.NAV_GROUPS:
            mods = groups.get(grp) or []
            matched = [m for m in mods if not kw or
                       kw in m["name"].lower() or kw in m.get("proto", "").lower() or
                       kw in (m.get("proto_note", "") or "").lower() or
                       kw in m.get("vendor", "").lower()]
            if not matched:
                continue
            gitem = QTreeWidgetItem([f"{grp}（{len(matched)}）"])
            gitem.setFlags(gitem.flags() & ~Qt.ItemIsSelectable)
            gitem.setData(0, Qt.UserRole, f"__grp__{grp}")
            f = gitem.font(0)
            f.setBold(True)
            gitem.setFont(0, f)
            for m in matched:
                mitem = QTreeWidgetItem([m["name"]])
                mitem.setData(0, Qt.UserRole, m["id"])
                gitem.addChild(mitem)
            tree.addTopLevelItem(gitem)
        tree.expandAll()

    search.textChanged.connect(_rebuild_tree)

    def _on_item_clicked(item, _col):
        mid = item.data(0, Qt.UserRole)
        if not mid or str(mid).startswith("__grp__"):
            return
        m = None
        for mod in module_page.all_modules():
            if mod["id"] == mid:
                m = mod
                break
        if m is None:
            return
        # 动态重建详情面板
        while stack.count() > 2:
            stack.removeWidget(stack.widget(2))
        panel = _build_detail_panel(m, content, lambda: stack.setCurrentIndex(0))
        stack.addWidget(panel)
        stack.setCurrentWidget(panel)

    tree.itemClicked.connect(_on_item_clicked)





def build_help_page(key: str) -> QWidget:
    page = QWidget()
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.setSpacing(12)

    if key == "guide":
        title = QLabel("使用说明")
        title.setObjectName("H1")
        lay.addWidget(title)
        sub = QLabel(f"FusionHub 融合上位机快速上手 · 当前版本 v{APP_VERSION}")
        sub.setObjectName("Muted")
        lay.addWidget(sub)

        c1 = Card("三步上手", "仪器面板结构一致、融合模块页保留各自布局，整体风格与操作习惯统一")
        c1.body_lay.addWidget(_bullets([
            (None, "① 左侧目录选择仪器/模块（可搜索型号/命令/注意事项；目录可拖动调宽，也可收起贴到最左侧）→ 打开面板；首页卡片也可直达"),
            (None, "② 连接设备（IP/端口或串口参数）→ 下发设定 → 开启输出/拉载（涉及输出、高压、拉载的操作均有二次确认弹窗）；通讯日志在每台设备界面下方，与上方界面之间可拖动缩放"),
            (None, "③ 需要查协议细节时：仪器面板切到“协议速查”页签（粗览卡片 + 明细表格 + 页内搜索）；融合模块页的协议要点见「协议与调试规范」与各模块自带说明"),
        ]))
        lay.addWidget(c1)

        c_kbd = Card("常用快捷键", "桌面软件通用习惯，按需取用")
        c_kbd.body_lay.addWidget(_bullets([
            (None, "Ctrl+F 搜索仪器　·　Esc 清空搜索 / 回首页　·　Ctrl+H 首页　·　Ctrl+R 调试记录"),
            (None, "F5 刷新记录　·　仪器面板内 Ctrl+1 / Ctrl+2 切换操作面板与协议速查　·　Ctrl+C 复制表格选中行"),
            (None, "Ctrl+E 导出记录　·　Ctrl+, 版本记录　·　Ctrl+Q 退出　·　回车打开搜索结果 / 确认弹窗默认安全项"),
            (None, "日志表格双击某行可查看完整帧内容"),
        ]))
        lay.addWidget(c_kbd)

        c2 = Card("安全规范（必读）", "涉及电源/拉载的操作一律有二次保护")
        c2.body_lay.addWidget(_bullets([
            ("danger", "所有输出开启按钮均弹二次确认框，确认接线/量程/负载后再开启"),
            ("danger", "关闭上位机自动停止全部输出并断开连接；退出弹窗会提示当前开启的输出路数"),
            ("warn", "界面刷新频率不高于串口吞吐，防止收发队列堆积、界面假死"),
        ]))
        lay.addWidget(c2)

        c3 = Card("调试记录", "调试过程自动留痕，表格可导出交付")
        c3.body_lay.addWidget(_bullets([
            (None, "顶部“调试记录”按钮打开记录页：连接信息（IP/COM口、波特率、端口号）、设定值、输出值、IO/采集值"),
            (None, "支持手动快照 + 每 5 秒自动记录；勾选仪器决定表格/导出包含哪些仪器（原始记录始终保留，可追溯）"),
            (None, "导出表格支持 Excel(.xlsx)/CSV(.csv)，随问题单/交付包归档"),
            (None, "调试完成后点“生成仪器清单”：已测试仪器每台一行（型号、IP、串口/COM口、波特率、端口号、调试起止时间），可单独预览与导出"),
        ]))
        lay.addWidget(c3)

        c4 = Card("新增仪器（可扩展）", "框架零改动，插件式接入")
        mods = module_page.all_modules()
        mod_groups: dict = {}
        for m in mods:
            g = m.get("group", module_page.GROUP)
            mod_groups[g] = mod_groups.get(g, 0) + 1
        mod_stat = "、".join(f"{g} {n} 个" for g, n in mod_groups.items() if n) or "暂无"
        c4.body_lay.addWidget(_bullets([
            (None, "协议速查型仪器：在 instruments/ 新建 xxx.py，构造 InstrumentSpec 并 register(spec) 即自动出现在目录/首页/记录表"),
            (None, "协议、寄存器表、注意事项全部写在 spec 中，作为单一事实源，界面自动派生"),
            (None, "接真机时替换 SimSession 为真实协议栈（保持语义化接口），界面不改"),
            (None, f"整机上位机模块：在 modules/ 新建包（create_page/shutdown 契约）并登记到 module_page.CHARGE_MODULES，"
                   f"已融合 {len(mods)} 个（{mod_stat}），风格适配整体界面；退出上位机统一停机断开"),
            (None, "每台仪器/模块上位机标配「帮助」与「故障代码查询」入口（基础参数+协议要点、故障码表+调试故障记录，可搜索可记录）"),
        ]))
        lay.addWidget(c4)
    else:
        # ============ 协议与调试规范（左右分栏重设计） ============
        _build_protocol_page(content)
        return _wrap_scroll(page, content)

    lay.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
    scroll.setWidget(content)
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(scroll)
    return page
