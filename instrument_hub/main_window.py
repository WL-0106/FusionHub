# -*- coding: utf-8 -*-
"""主窗口：左侧目录（两级 + 可搜索） + 工作区（首页/仪器面板/调试记录/帮助） + 可拖动通讯日志 + 退出安全保护。"""
from typing import Dict, Optional

from PyQt5.QtCore import QSettings, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PyQt5.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QMessageBox, QPushButton, QScrollArea, QShortcut, QSplitter,
                             QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

from . import module_page, registry
from .dialogs import VersionDialog
from .help_page import build_help_page
from .panel import InstrumentPanel
from .record_page import RecordPage
from .recorder import DebugRecorder
from .version import APP_NAME, APP_VERSION
from .widgets import Card, Chip


class ExitConfirmDialog(QDialog):
    """退出确认：明确告知将停止所有输出。"""

    def __init__(self, active_outputs: int, connected_modules: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("退出融合上位机")
        self.setModal(True)
        self.setFixedWidth(460)   # 高度随提示条数量自适应（输出/连接两种警告可同时出现）
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(12)
        t = QLabel("确认退出上位机？")
        t.setObjectName("H1")
        lay.addWidget(t)
        msg = QLabel("退出前将自动停止所有仪器输出并断开连接，确保现场设备安全。")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        if active_outputs:
            warn = QLabel(f"⚠ 当前仍有 {active_outputs} 路输出处于开启状态，将被强制关闭。")
            warn.setObjectName("Banner")
            warn.setWordWrap(True)
            lay.addWidget(warn)
        if connected_modules:
            warn = QLabel(f"⚠ 当前仍有 {connected_modules} 台模块上位机处于连接状态，退出时将自动停机并断开。")
            warn.setObjectName("Banner")
            warn.setWordWrap(True)
            lay.addWidget(warn)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setFixedSize(100, 38)
        cancel.setDefault(True)          # 危险确认：回车默认不退出
        cancel.setAutoDefault(True)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton("确认退出")
        ok.setFixedSize(120, 38)
        ok.setObjectName("Primary")
        ok.setAutoDefault(False)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1500, 950)
        self.setMinimumSize(1180, 760)
        self.skip_exit_confirm = False   # 自动化测试时置 True
        self._side_collapsed = False     # 左侧目录是否收起（贴最左侧窄条）
        self._settings = QSettings()     # 记住窗口尺寸/目录宽度/收起状态
        self._nav_nodes: Dict[str, QTreeWidgetItem] = {}

        self.recorder = DebugRecorder()
        self._pages: Dict[str, InstrumentPanel] = {}
        self._mod_pages: Dict[str, "module_page.ModuleHostPage"] = {}   # 融合的模块上位机页
        self._help_pages: Dict[str, QWidget] = {}

        root = QWidget()
        root.setObjectName("RootBg")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(12)
        outer.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_home())

        # 左右分割条：目录 | 工作区，手柄可自由拖动调宽；目录可收起贴到最左侧窄条
        self.side_split = QSplitter(Qt.Horizontal)
        self.side_split.setHandleWidth(14)
        self.side_split.setChildrenCollapsible(False)
        self.sidebar = self._build_sidebar()
        self.side_split.addWidget(self.sidebar)
        self.side_split.addWidget(self.stack)
        self.side_split.setStretchFactor(0, 0)
        self.side_split.setStretchFactor(1, 1)
        self.side_split.setSizes([292, 1150])

        # 通讯日志在每个电源/仪器仪表面板自己的下方（不在总界面），工作区占满剩余空间
        outer.addWidget(self.side_split, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("就绪 · 选择左侧仪器开始调试")

        self.record_page = RecordPage(self.recorder, self._all_sessions, self._log_to_status)
        self.stack.addWidget(self.record_page)
        self._build_nav_tree()
        self._bind_shortcuts()
        self._restore_state()

        # 目录绿色指示灯：周期扫描已连接设备并点亮对应目录项
        self._conn_dot = self._make_conn_dot()
        self._nav_timer = QTimer(self)
        self._nav_timer.setInterval(1000)
        self._nav_timer.timeout.connect(self._refresh_conn_dots)
        self._nav_timer.start()

    def _log_to_status(self, direction: str, content: str, note: str = "") -> None:
        """RecordPage 日志钩子：把动作摘要打到状态栏。"""
        self._status(note or content or direction)

    # ================================================================ 快捷键
    def _bind_shortcuts(self) -> None:
        """桌面软件常用快捷键：Ctrl+F 搜索、Esc 清空/回首页、Ctrl+R 记录、F5 刷新、Ctrl+Q 退出。

        统一 WindowShortcut：模态弹窗打开时不抢 Esc/回车，避免误关对话框。
        """
        def _sc(key, slot):
            s = QShortcut(QKeySequence(key) if not isinstance(key, QKeySequence) else key, self)
            s.setContext(Qt.WindowShortcut)
            s.activated.connect(slot)
            return s

        _sc(QKeySequence.Find, self._focus_search)
        _sc(Qt.Key_Escape, self._on_escape)
        _sc("Ctrl+R", self.show_record_page)
        _sc(Qt.Key_F5, self._refresh_current)
        _sc(QKeySequence.Quit, self.close)
        _sc("Ctrl+H", self.show_home)
        _sc("Ctrl+,", self._show_versions)
        _sc("Ctrl+E", self._export_records)

    def _export_records(self) -> None:
        """导出调试记录（Ctrl+E / 头部「导出记录」按钮）。"""
        self.show_record_page()
        self.record_page._export()

    def _focus_search(self) -> None:
        if self._side_collapsed:
            self._toggle_sidebar()
        self.nav_search.setFocus()
        self.nav_search.selectAll()

    def _on_escape(self) -> None:
        """Esc：优先清空有内容的搜索框（无需聚焦），否则回到首页。"""
        if self.nav_search.text():
            self.nav_search.clear()
            return
        focus = self.focusWidget()
        if isinstance(focus, QLineEdit) and focus is not self.nav_search and focus.text():
            focus.clear()
            return
        if self.stack.currentIndex() != 0:
            self.show_home()

    def _refresh_current(self) -> None:
        if self.stack.currentWidget() is self.record_page:
            self.record_page.refresh()
            self._status("调试记录已刷新")
        elif self.stack.currentIndex() == 0:
            self._status("首页已是最新")

    def _status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 5000)

    # ================================================================ 状态记忆
    def _restore_state(self) -> None:
        geo = self._settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        widths = self._settings.value("window/splitter")
        if widths is not None:
            self.side_split.setSizes([int(w) for w in widths])
        collapsed = self._settings.value("window/sideCollapsed", False, type=bool)
        if collapsed and not self._side_collapsed:
            self._toggle_sidebar()

    def _save_state(self) -> None:
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/splitter", self.side_split.sizes())
        self._settings.setValue("window/sideCollapsed", self._side_collapsed)

    # ================================================================ 顶部
    def _build_header(self) -> QFrame:
        head = QFrame()
        head.setObjectName("Header")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(12)

        logo = QPushButton("FH")
        logo.setObjectName("LogoBtn")
        logo.setFixedSize(46, 46)
        logo.setCursor(Qt.PointingHandCursor)
        logo.setToolTip("回到首页（Ctrl+H）")
        logo.setStyleSheet(
            "QPushButton{background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #6366F1, stop:1 #8B5CF6);"
            "color:white; border-radius:13px; font-size:18px; font-weight:900; border:none;}"
            "QPushButton:hover{background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #5558E8, stop:1 #7C4FE0);}"
            "QPushButton:pressed{background:#4338CA;}")
        logo.clicked.connect(self.show_home)
        lay.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("H1")
        title_box.addWidget(title)
        sub = QLabel("多仪器融合测试工作台 · 协议速查 / 调试联调 / 自动化验证")
        sub.setObjectName("Muted")
        title_box.addWidget(sub)
        lay.addLayout(title_box)

        lay.addWidget(Chip(f"v{APP_VERSION}", "#4F46E5", "#EEF0FF"))
        lay.addWidget(Chip("退出自动停输出 ✓", "#047857", "#D1FAE5"))

        # 常用快捷键工具按钮（紧跟退出自动停输出之后，点击等效对应快捷键）
        for text, slot, tip in (
                ("搜索", self._focus_search, "搜索仪器（Ctrl+F）"),
                ("首页", self.show_home, "回到首页（Ctrl+H）"),
                ("调试记录", self.show_record_page, "打开调试记录（Ctrl+R）"),
                ("刷新", self._refresh_current, "刷新当前记录/首页（F5）"),
                ("导出记录", self._export_records, "导出调试记录（Ctrl+E）"),
                ("版本记录", self._show_versions, "查看版本对应关系与变更历史（Ctrl+,）"),
                ("退出", self.close, "退出并自动停止全部输出（Ctrl+Q）")):
            b = QPushButton(text)
            b.setObjectName("Ghost")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            lay.addWidget(b)

        lay.addStretch(1)

        self.current_label = QLabel("当前：首页概览")
        self.current_label.setObjectName("H2")
        lay.addWidget(self.current_label)
        return head

    # ================================================================ 左侧目录
    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setMinimumWidth(200)
        self.side_lay = QVBoxLayout(side)
        self.side_lay.setContentsMargins(14, 14, 14, 14)
        self.side_lay.setSpacing(10)

        head_w = QWidget()
        head_w.setFixedHeight(32)   # 定高：收起时标题行不会吸收整列高度把按钮顶到中部
        head = QHBoxLayout(head_w)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self.side_title = QLabel("仪器目录")
        self.side_title.setObjectName("CardTitle")
        head.addWidget(self.side_title)
        head.addStretch(1)
        self.btn_side_toggle = QPushButton("«")
        self.btn_side_toggle.setObjectName("SideToggle")
        self.btn_side_toggle.setFixedSize(40, 32)
        self.btn_side_toggle.setToolTip("收起目录到最左侧（拖动右侧手柄可自由调宽）")
        self.btn_side_toggle.clicked.connect(self._toggle_sidebar)
        head.addWidget(self.btn_side_toggle)
        self.side_lay.addWidget(head_w, 0, Qt.AlignTop)   # AlignTop：收起时钉在窄条顶部

        self.nav_search = QLineEdit()
        self.nav_search.setObjectName("SearchBox")
        self.nav_search.setPlaceholderText("搜索仪器 / 型号 / 协议关键词…（Ctrl+F）")
        self.nav_search.setClearButtonEnabled(True)
        self.nav_search.textChanged.connect(self._filter_nav)
        self.nav_search.returnPressed.connect(self._open_first_search_hit)
        self.side_lay.addWidget(self.nav_search)

        self.tree = QTreeWidget()
        self.tree.setObjectName("NavTree")
        self.tree.setHeaderHidden(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemActivated.connect(self._on_nav_clicked)   # 双击 / 回车 才切换面板
        self.side_lay.addWidget(self.tree, 1)

        self.side_tip = QLabel("提示：双击或回车打开面板；已连接设备前亮绿灯 · Ctrl+F 搜索 · Esc 清空 · F5 刷新")
        self.side_tip.setObjectName("Muted")
        self.side_tip.setWordWrap(True)
        self.side_lay.addWidget(self.side_tip)
        return side

    def _toggle_sidebar(self) -> None:
        """目录收起/展开：收起后贴在最左侧只留展开按钮，展开恢复可拖动宽度。"""
        self._side_collapsed = not self._side_collapsed
        collapsed = self._side_collapsed
        for w in (self.side_title, self.nav_search, self.tree, self.side_tip):
            w.setVisible(not collapsed)
        if collapsed:
            self.side_lay.setContentsMargins(10, 14, 10, 14)
            self.sidebar.setFixedWidth(54)
            self.side_split.setSizes([54, max(self.side_split.width() - 68, 600)])   # 右侧立即自适应
            self.btn_side_toggle.setText("»")
            self.btn_side_toggle.setToolTip("展开仪器目录")
        else:
            self.side_lay.setContentsMargins(14, 14, 14, 14)
            self.sidebar.setMinimumWidth(200)
            self.sidebar.setMaximumWidth(16777215)
            self.side_split.setSizes([292, max(self.side_split.width() - 306, 600)])  # 右侧立即自适应
            self.btn_side_toggle.setText("«")
            self.btn_side_toggle.setToolTip("收起目录到最左侧（拖动右侧手柄可自由调宽）")

    def _build_nav_tree(self) -> None:
        self.tree.clear()
        self._nav_nodes.clear()
        # 一级：上位机 → 二级：五类设备 → 三级：仪器
        root_dev = self._add_node(None, "上位机", None)
        for group in registry.NAV_GROUPS:
            specs = registry.by_group().get(group, [])
            mods = [m for m in module_page.all_modules()
                    if m.get("group", module_page.GROUP) == group]   # 融合的模块/工具页
            gnode = self._add_node(root_dev, f"{group}　·　{len(specs) + len(mods)} 台", None)
            for spec in specs:
                leaf = self._add_node(gnode, f"{spec.name}（{spec.model}）", ("inst", spec.id))
                leaf.setToolTip(0, f"{spec.vendor} · {spec.summary}")
                self._nav_nodes[spec.id] = leaf
            for m in mods:
                leaf = self._add_node(gnode, f"{m['name']}（{m['vendor']}）", ("mod", m["id"]))
                leaf.setToolTip(0, f"{m['vendor']} · {m['proto']} · {m['summary']}")
                self._nav_nodes[f"mod:{m['id']}"] = leaf
            if not specs and not mods:
                ph = self._add_node(gnode, "（暂无设备，待接入）", None)
                ph.setForeground(0, QColor("#B3B3C3"))
            gnode.setExpanded(True)
        root_dev.setExpanded(True)

        # 一级：帮助手册协议 → 二级：文档
        root_help = self._add_node(None, "帮助手册协议", None)
        self._add_node(root_help, "使用说明", ("help", "guide"))
        self._add_node(root_help, "协议与调试规范", ("help", "pitfalls"))
        self._add_node(root_help, "版本记录", ("help", "version"))
        root_help.setExpanded(True)

    def _add_node(self, parent, text: str, role) -> QTreeWidgetItem:
        node = QTreeWidgetItem([text])
        node.setData(0, Qt.UserRole, role)
        f = node.font(0)
        f.setBold(True)
        node.setFont(0, f)
        if parent is None:
            self.tree.addTopLevelItem(node)
        else:
            parent.addChild(node)
        return node

    def _open_first_search_hit(self) -> None:
        """搜索框回车：打开第一个命中的仪器。"""
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            for j in range(root.childCount()):
                group = root.child(j)
                for k in range(group.childCount()):
                    leaf = group.child(k)
                    if not leaf.isHidden() and leaf.data(0, Qt.UserRole):
                        self._on_nav_clicked(leaf, 0)
                        return

    def _filter_nav(self, text: str) -> None:
        key = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            root_visible = False
            for j in range(root.childCount()):
                group = root.child(j)
                visible_children = 0
                has_leaf = group.childCount() > 0
                for k in range(group.childCount()):
                    leaf = group.child(k)
                    role = leaf.data(0, Qt.UserRole)
                    if role and role[0] == "inst":
                        spec = registry.get_spec(role[1])
                        hay = " ".join([
                            spec.name, spec.model, spec.vendor, spec.category,
                            spec.group, spec.summary,
                            *[c.cmd + c.desc for c in spec.commands],
                            *[r.addr + r.name for r in spec.registers],
                            *[c.text for c in spec.cautions],
                        ]).lower()
                    elif role and role[0] == "mod":
                        m = module_page.get_module(role[1])
                        hay = " ".join([m["name"], m["vendor"], m["proto"], m["summary"]]).lower()
                    else:
                        hay = leaf.text(0).lower()
                    ok = (not key) or (key in hay)
                    leaf.setHidden(not ok)
                    visible_children += 1 if ok else 0
                group.setHidden(bool(key) and visible_children == 0)
                if visible_children or (not key and has_leaf):
                    group.setExpanded(True)
                root_visible = root_visible or (not group.isHidden())
            root.setHidden(bool(key) and not root_visible)
            root.setExpanded(True)

    def _on_nav_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        role = item.data(0, Qt.UserRole)
        if not role:
            return
        kind, key = role
        if kind == "inst":
            self.open_instrument(key)
        elif kind == "mod":
            self.open_module_page(key)
        elif kind == "help":
            if key == "version":
                self._show_versions()
            else:
                self.show_help(key)

    def _select_nav(self, spec_id: Optional[str] = None, help_key: Optional[str] = None) -> None:
        """打开页面时同步高亮左侧对应节点，方便用户知道自己在哪。"""
        target = self._nav_nodes.get(spec_id) if spec_id else None
        if target is None and help_key:
            for i in range(self.tree.topLevelItemCount()):
                root = self.tree.topLevelItem(i)
                for j in range(root.childCount()):
                    leaf = root.child(j)
                    role = leaf.data(0, Qt.UserRole)
                    if role and role == ("help", help_key):
                        target = leaf
                        break
        if target is not None:
            self.tree.setCurrentItem(target)

    # ================================================================ 首页
    def _build_home(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(12)

        banner = Card("欢迎使用 FusionHub 融合上位机",
                      "所有仪器统一协议速查 / 操作面板 / 通讯日志三件套，风格一致、可扩展、可迭代")
        mods = module_page.all_modules()
        group_counts = {}
        for m in mods:
            g = m.get("group", module_page.GROUP)
            group_counts[g] = group_counts.get(g, 0) + 1
        group_stat = " · ".join(f"{g} {n}" for g, n in group_counts.items() if n)
        info = QLabel(
            f"· 已集成仪器（协议速查型）：{len(registry.all_specs())} 台　|　"
            f"已融合模块上位机：{len(mods)} 个（{group_stat}）　|　"
            f"融合框架版本：v{APP_VERSION}（每次修改必须递增版本号并登记变更记录）\n"
            "· 新增仪器：协议速查型在 instruments/ 新建 xxx.py 并 register(spec)；"
            "整机上位机在 modules/ 新建包并登记到 module_page.CHARGE_MODULES，均自动接入，框架零改动\n"
            "· 安全规范：所有输出开启均需二次确认；关闭上位机自动停止全部输出；异常路径必测")
        info.setWordWrap(True)
        info.setStyleSheet("line-height:180%;")
        banner.body_lay.addWidget(info)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        b_rec = QPushButton("打开调试记录")
        b_rec.setObjectName("Primary")
        b_rec.clicked.connect(self.show_record_page)
        btns.addWidget(b_rec)
        b_help = QPushButton("使用说明")
        b_help.clicked.connect(lambda: self.show_help("guide"))
        btns.addWidget(b_help)
        b_rule = QPushButton("协议与调试规范")
        b_rule.clicked.connect(lambda: self.show_help("pitfalls"))
        btns.addWidget(b_rule)
        btns.addStretch(1)
        banner.body_lay.addLayout(btns)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        for idx, spec in enumerate(registry.all_specs()):
            grid.addWidget(self._home_card(spec), idx // 3, idx % 3)
        base = len(registry.all_specs())
        for j, m in enumerate(mods):
            grid.addWidget(self._home_mod_card(m), (base + j) // 3, (base + j) % 3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(12)
        wl.addWidget(banner)
        wl.addWidget(grid_host, 1)
        scroll.setWidget(wrap)
        lay.addWidget(scroll, 1)
        return page

    def _home_card(self, spec) -> Card:
        card = Card()
        lay = card.body_lay
        top = QHBoxLayout()
        name = QLabel(spec.name)
        name.setObjectName("H2")
        top.addWidget(name)
        top.addWidget(Chip(spec.category, "#7C3AED", "#F3E8FF"))
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(self._chip(spec.model))
        summary = QLabel(spec.summary)
        summary.setWordWrap(True)
        summary.setObjectName("Muted")
        lay.addWidget(summary)

        kv = QLabel(f"协议 {spec.versions.get('协议', '-')}　·　"
                    f"寄存器表 {spec.versions.get('寄存器表', '-')}　·　"
                    f"命令 {len(spec.commands)} 条　·　注意事项 {len(spec.cautions)} 条")
        kv.setObjectName("Muted")
        kv.setWordWrap(True)
        lay.addWidget(kv)
        lay.addStretch(1)

        row = QHBoxLayout()
        b1 = QPushButton("操作面板")
        b1.setObjectName("Primary")
        b1.clicked.connect(lambda: self.open_instrument(spec.id, tab=0))
        row.addWidget(b1)
        b2 = QPushButton("协议速查")
        b2.clicked.connect(lambda: self.open_instrument(spec.id, tab=1))
        row.addWidget(b2)
        lay.addLayout(row)
        return card

    def _home_mod_card(self, mod: dict) -> Card:
        """首页模块卡片：与仪器卡片同栅格，点击直接打开融合模块页。"""
        card = Card()
        lay = card.body_lay
        top = QHBoxLayout()
        name = QLabel(mod["name"])
        name.setObjectName("H2")
        top.addWidget(name)
        top.addWidget(Chip(mod.get("group", module_page.GROUP), "#7C3AED", "#F3E8FF"))
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(self._chip(mod["vendor"]))
        proto = QLabel(mod["proto"])
        proto.setObjectName("Muted")
        lay.addWidget(proto)
        summary = QLabel(mod["summary"])
        summary.setWordWrap(True)
        summary.setObjectName("Muted")
        lay.addWidget(summary)
        lay.addStretch(1)

        row = QHBoxLayout()
        b1 = QPushButton("打开模块")
        b1.setObjectName("Primary")
        b1.clicked.connect(lambda _=False, mid=mod["id"]: self.open_module_page(mid))
        row.addWidget(b1)
        lay.addLayout(row)
        return card

    @staticmethod
    def _chip(text: str) -> Chip:
        return Chip(text, "#4F46E5", "#EEF0FF")

    # ================================================================ 工作区
    def _make_conn_dot(self) -> QIcon:
        """绿色指示灯图标（目录项开头显示，表示该设备已连接）。"""
        pm = QPixmap(14, 14)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#22C55E"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, 10, 10)
        p.end()
        return QIcon(pm)

    def _refresh_conn_dots(self) -> None:
        """周期扫描已连接设备，点亮/熄灭目录项开头的绿色指示灯。"""
        for key, node in self._nav_nodes.items():
            if key.startswith("mod:"):
                page = self._mod_pages.get(key[4:])
                connected = bool(page is not None and page.is_connected())
            else:
                panel = self._pages.get(key)
                connected = bool(panel is not None and panel.is_connected())
            if connected != getattr(node, "_conn_lit", False):
                node._conn_lit = connected
                node.setIcon(0, self._conn_dot if connected else QIcon())

    def _connected_names(self, exclude_key: Optional[str] = None) -> list:
        """当前已连接（未断开）的仪器/模块名称列表，exclude_key 为切换目标（不算在内）。"""
        names = []
        for sid, panel in self._pages.items():
            if sid != exclude_key and panel.is_connected():
                spec = registry.get_spec(sid)
                names.append(f"{spec.name}（{spec.model}）")
        for mid, page in self._mod_pages.items():
            if mid != exclude_key and page.is_connected():
                names.append(module_page.get_module(mid)["name"])
        return names

    def _guard_switch(self, exclude_key: Optional[str] = None) -> bool:
        """切换上位机前安全确认：存在未断开连接时弹窗提示，防测试中误切。"""
        names = self._connected_names(exclude_key)
        if not names:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("测试安全确认")
        box.setText("仍有设备处于已连接状态，切换上位机不会自动断开该连接。")
        box.setInformativeText("已连接：" + "、".join(names)
                               + "\n\n请确认当前测试允许离开后再切换，保证测试安全。")
        ok = box.addButton("继续切换", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec_()
        return box.clickedButton() is ok

    def open_instrument(self, spec_id: str, tab: int = 0) -> None:
        if self.stack.currentWidget() is not self._pages.get(spec_id):
            if not self._guard_switch(exclude_key=spec_id):
                self._status("已取消切换（有设备仍处于连接状态）")
                return
        if spec_id not in self._pages:
            panel = InstrumentPanel(registry.get_spec(spec_id), recorder=self.recorder)
            self._pages[spec_id] = panel
            self.stack.addWidget(panel)
        panel = self._pages[spec_id]
        panel.tabs.setCurrentIndex(tab)
        self.stack.setCurrentWidget(panel)
        spec = registry.get_spec(spec_id)
        self.current_label.setText(f"当前：{spec.name}（{spec.model}）")
        self._select_nav(spec_id=spec_id)
        self._status(f"已打开 {spec.name}（{spec.model}）")

    def open_module_page(self, mid: str) -> None:
        """打开融合进来的模块上位机页（懒加载并缓存，退出时统一 shutdown）。"""
        if self.stack.currentWidget() is not self._mod_pages.get(mid):
            if not self._guard_switch(exclude_key=mid):
                self._status("已取消切换（有设备仍处于连接状态）")
                return
        if mid not in self._mod_pages:
            page = module_page.ModuleHostPage(module_page.get_module(mid),
                                                recorder=self.recorder)
            self._mod_pages[mid] = page
            self.stack.addWidget(page)
        page = self._mod_pages[mid]
        self.stack.setCurrentWidget(page)
        mod = module_page.get_module(mid)
        self.current_label.setText(f"当前：{mod['name']}（{mod['vendor']}）")
        self._select_nav(spec_id=f"mod:{mid}")
        self._status(f"已打开 {mod['name']}")

    def show_record_page(self) -> None:
        self.record_page.refresh()
        self.stack.setCurrentWidget(self.record_page)
        self.current_label.setText("当前：调试记录")
        self.tree.clearSelection()
        self._status("调试记录")

    def show_help(self, key: str) -> None:
        if key not in self._help_pages:
            page = build_help_page(key)
            self._help_pages[key] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self._help_pages[key])
        self.current_label.setText("当前：使用说明" if key == "guide" else "当前：协议与调试规范")
        self._select_nav(help_key=key)
        self._status("帮助手册")

    def show_home(self) -> None:
        self.stack.setCurrentIndex(0)
        self.current_label.setText("当前：首页概览")
        self.tree.clearSelection()
        self._status("首页概览")

    def _all_sessions(self):
        """调试记录数据源：所有已打开仪器面板的 (spec, session)。"""
        return [(p.spec, p.session) for p in self._pages.values()]

    def _show_versions(self) -> None:
        VersionDialog(registry.all_specs(), self).exec_()

    # ================================================================ 退出安全
    def active_output_count(self) -> int:
        n = 0
        for panel in self._pages.values():
            n += sum(1 for b in panel._output_btns.values() if b.is_on())
        return n

    def connected_module_count(self) -> int:
        """处于连接状态的融合模块上位机数量（退出弹窗提示用，退出时统一停机断开）。"""
        return sum(1 for page in self._mod_pages.values() if page.is_connected())

    def closeEvent(self, event) -> None:
        self._save_state()
        if not self.skip_exit_confirm:
            dlg = ExitConfirmDialog(self.active_output_count(),
                                    self.connected_module_count(), self)
            if dlg.exec_() != QDialog.Accepted:
                event.ignore()
                return
        for panel in self._pages.values():
            panel.safe_shutdown()
        for mpage in self._mod_pages.values():
            mpage.shutdown()          # 融合的模块上位机：停机、断开、回收线程
        event.accept()
