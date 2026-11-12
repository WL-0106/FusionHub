"""主窗口：按截图还原的永联充电模块上位机界面。"""

from ...theme_util import expand_qss
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QTabWidget, QFrame, QPlainTextEdit, QMenu, QMessageBox, QFileDialog,
    QSizePolicy, QApplication, QScrollArea, QSplitter,
)

from ..core.controller import CommController
from ..core.registers import (
    INPUT_WORK_MODES, ADDR_MODE_DIP, ADDR_MODE_AUTO,
    OVP_RELATED_ALLOW, OVP_RELATED_DENY, OVP_RESET_VALUE, SHORT_RESET_VALUE,
)

from .theme import APP_QSS
from .widgets import CheckableHeader, TableOverlay, make_button

COLUMNS = ["", "地址", "在线", "电源", "电压(V)", "电流(A)",
           "输入BC(V)", "允许电流(A)", "温度(°C)", "故障",
           "设置电压(V)", "设置电流(A)", "操作"]
COL_ADDR, COL_ONLINE, COL_POWER = 1, 2, 3
COL_V, COL_A, COL_VIN, COL_ALLOW, COL_TEMP, COL_FAULT = 4, 5, 6, 7, 8, 9
COL_SV, COL_SI, COL_BTN = 10, 11, 12

DASH = "–"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("永联 UXR100040 充电模块上位机 v1.0")
        self.resize(1040, 720)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(expand_qss(APP_QSS))

        self.controller = CommController(self)
        self._row_of = {}          # addr -> row
        self._addr_of = {}         # row -> addr
        self._sv_spins = {}        # addr -> 设置电压输入框
        self._si_spins = {}        # addr -> 设置电流输入框
        self._current_addr = None
        self._updating = False
        self._log_lines = []

        self._build_ui()
        self._connect_controller()
        self._update_conn_state(False)
        self._update_selection_stats()
        self._show_detail(None)

    # ============================================================ 构建 UI
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        root.addWidget(self._build_connection_row())
        root.addWidget(self._build_batch_row())

        # 中部：监控表 | 右侧功能区，分割条可拖动缩放（与其他模块一致）
        mid = QSplitter(Qt.Horizontal)
        mid.setHandleWidth(10)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_monitor())
        mid.addWidget(self._build_right_panel())
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 0)
        mid.setSizes([760, 320])
        root.addWidget(mid, 1)

        root.addWidget(self._build_log_panel())

        self.status = self.statusBar()
        self.status.showMessage("就绪")

    # ------------------------------------------------------------ 行1 连接
    def _build_connection_row(self):
        box = QGroupBox("连接配置")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        lay.addWidget(QLabel("UT-6502 IP"))
        self.ip_edit = QLineEdit("192.168.1.125")
        self.ip_edit.setFixedWidth(120)
        lay.addWidget(self.ip_edit)

        lay.addWidget(QLabel("端口"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5000)
        self.port_spin.setFixedWidth(70)
        lay.addWidget(self.port_spin)

        self.btn_connect = make_button("连接", "primary")
        self.btn_disconnect = make_button("断开", "danger")
        self.btn_disconnect.setEnabled(False)
        lay.addWidget(self.btn_connect)
        lay.addWidget(self.btn_disconnect)

        lay.addSpacing(8)
        self.chk_poll = QCheckBox("自动轮询在线模块")
        self.chk_poll.setChecked(True)
        lay.addWidget(self.chk_poll)

        lay.addWidget(QLabel("间隔(ms)"))
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(100, 10000)
        self.poll_spin.setSingleStep(100)
        self.poll_spin.setValue(500)
        self.poll_spin.setFixedWidth(72)
        lay.addWidget(self.poll_spin)

        self.conn_dot = QLabel("●")
        self.conn_dot.setObjectName("connDot")
        self.conn_text = QLabel("未连接")
        lay.addWidget(self.conn_dot)
        lay.addWidget(self.conn_text)

        lay.addStretch(1)
        self.chk_sim = QCheckBox("模拟从站")
        self.chk_sim.setToolTip("勾选后使用内置模拟模块，无需真实硬件即可演示与自测")
        lay.addWidget(self.chk_sim)
        return box

    # ------------------------------------------------------------ 行2 批量
    def _build_batch_row(self):
        box = QGroupBox("批量操作")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        self.btn_all_on = make_button("全部开机", "success")
        self.btn_all_off = make_button("全部关机", "danger")
        lay.addWidget(self.btn_all_on)
        lay.addWidget(self.btn_all_off)

        lay.addSpacing(10)
        lay.addWidget(QLabel("批量电压(V):"))
        self.batch_v = QSpinBox()
        self.batch_v.setRange(0, 1000)
        self.batch_v.setValue(500)
        self.batch_v.setFixedWidth(80)
        lay.addWidget(self.batch_v)

        lay.addWidget(QLabel("批量电流(A):"))
        self.batch_a = QSpinBox()
        self.batch_a.setRange(0, 1000)
        self.batch_a.setValue(50)
        self.batch_a.setFixedWidth(80)
        lay.addWidget(self.batch_a)

        self.btn_batch_set = make_button("批量设电压电流", "primary")
        lay.addWidget(self.btn_batch_set)

        lay.addStretch(1)
        self.btn_one_key = make_button("一键初始化", "warn")
        self.btn_scan = make_button("开始扫描", "primary")
        self.btn_fault_codes = make_button("故障代码查询", "primary")
        lay.addWidget(self.btn_one_key)
        lay.addWidget(self.btn_scan)
        lay.addWidget(self.btn_fault_codes)
        return box

    # ------------------------------------------------------------ 监控区
    def _build_monitor(self):
        frame = QFrame()
        frame.setObjectName("monitor")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("monitorBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(6, 5, 6, 5)
        bl.setSpacing(6)

        title = QLabel("模块实时监控")
        title.setObjectName("monitorTitle")
        bl.addWidget(title)
        bl.addSpacing(12)

        self.lbl_stats = QLabel("模块:0 在线:0 已选:0")
        self.lbl_stats.setObjectName("monitorStat")
        bl.addWidget(self.lbl_stats)
        bl.addStretch(1)

        self.btn_select_all = make_button("全选")
        self.btn_clear_sel = make_button("清空")
        self.btn_online_only = make_button("仅在线")
        bl.addWidget(self.btn_select_all)
        bl.addWidget(self.btn_clear_sel)
        bl.addWidget(self.btn_online_only)

        bl.addSpacing(10)
        self.btn_sel_on = make_button("选中开机", "success")
        self.btn_sel_off = make_button("选中关机", "danger")
        bl.addWidget(self.btn_sel_on)
        bl.addWidget(self.btn_sel_off)

        self.btn_adv = make_button("进阶")
        self.btn_adv.setToolTip("进阶操作：过压复位 / 短路复位 / 读取拨码地址等")
        self._build_adv_menu()
        bl.addWidget(self.btn_adv)
        lay.addWidget(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("monitorTable")
        self.table.setHorizontalHeader(CheckableHeader(Qt.Horizontal))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)

        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(True)
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(COL_ADDR, 56)
        self.table.setColumnWidth(COL_ONLINE, 48)
        self.table.setColumnWidth(COL_POWER, 52)
        self.table.setColumnWidth(COL_V, 74)
        self.table.setColumnWidth(COL_A, 74)
        self.table.setColumnWidth(COL_VIN, 90)
        self.table.setColumnWidth(COL_ALLOW, 96)
        self.table.setColumnWidth(COL_TEMP, 72)
        self.table.verticalHeader().setDefaultSectionSize(24)
        lay.addWidget(self.table, 1)

        self.overlay = TableOverlay(
            self.table, "尚未扫描到模块",
            ["请先点右上角「开始扫描」", "(模块上电约 10 秒后才分配地址)"])
        # 预置空表行（0x00~0x3F），未扫描时也可见完整列表
        self._updating = True
        for a in range(0x00, 0x40):
            self._create_row(a, online=False)
        self._updating = False
        self.overlay.hide()

        self.table.horizontalHeader().toggled.connect(self._on_header_toggle)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemClicked.connect(self._on_item_clicked)
        return frame

    def _build_adv_menu(self):
        menu = QMenu(self)
        menu.addAction("过压复位 (0x31)", lambda: self._adv_send("ovp"))
        menu.addAction("短路复位 (0x44)", lambda: self._adv_send("short"))
        menu.addAction("读取拨码地址 (0x43)", lambda: self._adv_send("dip"))
        menu.addAction("读取 DCDC/PFC 版本", lambda: self._adv_send("ver"))
        self.btn_adv.setMenu(menu)

    # ------------------------------------------------------------ 右侧面板
    def _build_right_panel(self):
        self.tabs = QTabWidget()
        # 不写死宽度：由中部分割条拖动缩放（与其他模块一致）
        self.tabs.setMinimumWidth(240)
        self.tabs.addTab(self._scrollable(self._build_tab_control()), "模块控制")
        self.tabs.addTab(self._scrollable(self._build_tab_init()), "初始化配置")
        self.tabs.addTab(self._scrollable(self._build_tab_info()), "模块信息")
        return self.tabs

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(page)
        sa.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        return sa

    def _build_tab_control(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(6)

        # --- 输出电压电流设置 ---
        g1 = QGroupBox("输出电压电流设置 (0x1C)")
        g1.setObjectName("panelGroup")
        f = QFormLayout(g1)
        f.setContentsMargins(6, 6, 6, 6)
        f.setSpacing(6)
        self.ctrl_v = QSpinBox()
        self.ctrl_v.setRange(0, 1000)
        self.ctrl_v.setValue(500)
        self.ctrl_v.setMinimumWidth(56)
        self.ctrl_a = QSpinBox()
        self.ctrl_a.setRange(0, 1000)
        self.ctrl_a.setValue(50)
        self.ctrl_a.setMinimumWidth(56)
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        row1.addWidget(QLabel("电压(V):"))
        row1.addWidget(self.ctrl_v, 1)
        row1.addSpacing(4)
        row1.addWidget(QLabel("电流(A):"))
        row1.addWidget(self.ctrl_a, 1)
        f.addRow(row1)
        self.btn_set_va = make_button("设置电压电流", "primary")
        self.btn_set_va.setMinimumHeight(30)
        f.addRow(self.btn_set_va)
        self.chk_broadcast_va = QCheckBox("此值应用到全部模块（广播）")
        f.addRow(self.chk_broadcast_va)
        lay.addWidget(g1)

        # --- 开关机控制 ---
        g2 = QGroupBox("开关机控制 (0x1A)")
        g2.setObjectName("panelGroup")
        h = QHBoxLayout(g2)
        h.setContentsMargins(8, 8, 8, 8)
        h.setSpacing(6)
        self.btn_on = make_button("开机", "success")
        self.btn_off = make_button("关机", "danger")
        self.btn_on_all = make_button("全部", "success")
        self.btn_on_all.setToolTip("对全部模块下发开机（广播）")
        for b in (self.btn_on, self.btn_off, self.btn_on_all):
            h.addWidget(b, 1)
        lay.addWidget(g2)

        # --- 选中模块实时数据 ---
        g3 = QGroupBox("选中模块实时数据")
        g3.setObjectName("panelGroup")
        v = QVBoxLayout(g3)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
        self.detail_title = QLabel("未选中模块")
        self.detail_title.setObjectName("detailTitle")
        v.addWidget(self.detail_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        self.detail_fields = {}
        for i, (key, label) in enumerate([("voltage", "电压"), ("current", "电流"),
                                          ("temp", "温度"), ("status", "状态")]):
            k = QLabel(label)
            k.setObjectName("detailKey")
            val = QLabel(DASH)
            val.setObjectName("detailVal")
            grid.addWidget(k, i // 2, (i % 2) * 2)
            grid.addWidget(val, i // 2, (i % 2) * 2 + 1)
            self.detail_fields[key] = val
        v.addLayout(grid)

        self.detail_note = QLabel("选中模块后可在此查看限值、故障位、输入电压等详细数据。")
        self.detail_note.setObjectName("detailNote")
        self.detail_note.setWordWrap(True)
        v.addWidget(self.detail_note)
        lay.addWidget(g3)
        lay.addStretch(1)
        return page

    def _build_tab_init(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(8)

        self.chk_broadcast_init = QCheckBox("应用到全部模块（广播）")
        lay.addWidget(self.chk_broadcast_init)
        self.chk_group_cast = QCheckBox("组播（按下方组号下发）")
        self.chk_group_cast.setToolTip("仅对指定组内的模块下发；组号 ≥8 时自动使用扩展组播地址")
        lay.addWidget(self.chk_group_cast)

        g1 = QGroupBox("组号设置 (0x1E)")
        g1.setObjectName("panelGroup")
        h1 = QHBoxLayout(g1)
        h1.setContentsMargins(8, 8, 8, 8)
        self.spin_group = QSpinBox()
        self.spin_group.setRange(0, 59)
        self.spin_group.setMinimumWidth(56)
        self.spin_group.setToolTip("0~7 组写入 0x1E 仅取低 3 位；组播时 ≥8 组使用扩展组播地址")
        self.btn_set_group = make_button("设置")
        h1.addWidget(QLabel("组号:"))
        h1.addWidget(self.spin_group, 1)
        h1.addWidget(self.btn_set_group)
        lay.addWidget(g1)

        g2 = QGroupBox("地址分配方式 (0x1F)")
        g2.setObjectName("panelGroup")
        h2 = QHBoxLayout(g2)
        h2.setContentsMargins(8, 8, 8, 8)
        self.combo_addr_mode = QComboBox()
        self.combo_addr_mode.addItems(["拨码设置(默认)", "自动分配"])
        self.btn_set_addr_mode = make_button("设置")
        h2.addWidget(self.combo_addr_mode, 1)
        h2.addWidget(self.btn_set_addr_mode)
        lay.addWidget(g2)

        g3 = QGroupBox("输入模式 (0x46)")
        g3.setObjectName("panelGroup")
        h3 = QHBoxLayout(g3)
        h3.setContentsMargins(8, 8, 8, 8)
        self.combo_input_mode = QComboBox()
        self.combo_input_mode.addItems(["交流模式(默认)", "直流模式"])
        self.btn_set_input_mode = make_button("设置")
        h3.addWidget(self.combo_input_mode, 1)
        h3.addWidget(self.btn_set_input_mode)
        lay.addWidget(g3)
        note = QLabel("注：设置输入模式后需模块断电重启方可生效。")
        note.setObjectName("detailNote")
        note.setWordWrap(True)
        lay.addWidget(note)

        g4 = QGroupBox("工作海拔 (0x17)")
        g4.setObjectName("panelGroup")
        h4 = QHBoxLayout(g4)
        h4.setContentsMargins(8, 8, 8, 8)
        self.spin_altitude = QSpinBox()
        self.spin_altitude.setRange(1000, 5000)
        self.spin_altitude.setSingleStep(100)
        self.spin_altitude.setValue(1000)
        self.spin_altitude.setMinimumWidth(72)
        self.btn_set_altitude = make_button("设置")
        h4.addWidget(QLabel("海拔(m):"))
        h4.addWidget(self.spin_altitude, 1)
        h4.addWidget(self.btn_set_altitude)
        lay.addWidget(g4)

        g5 = QGroupBox("输出功率 (0x20)")
        g5.setObjectName("panelGroup")
        h5 = QHBoxLayout(g5)
        h5.setContentsMargins(8, 8, 8, 8)
        self.spin_power = QDoubleSpinBox()
        self.spin_power.setRange(0.1, 1.0)
        self.spin_power.setSingleStep(0.1)
        self.spin_power.setValue(1.0)
        self.spin_power.setMinimumWidth(72)
        self.btn_set_power = make_button("设置")
        h5.addWidget(QLabel("比例:"))
        h5.addWidget(self.spin_power, 1)
        h5.addWidget(self.btn_set_power)
        lay.addWidget(g5)

        g5b = QGroupBox("过压点与保护关联 (0x23/0x3E)")
        g5b.setObjectName("panelGroup")
        v5b = QVBoxLayout(g5b)
        v5b.setContentsMargins(8, 8, 8, 8)
        v5b.setSpacing(6)
        r5b1 = QHBoxLayout()
        self.spin_ovp_point = QDoubleSpinBox()
        self.spin_ovp_point.setRange(0.0, 1000.0)
        self.spin_ovp_point.setSingleStep(5.0)
        self.spin_ovp_point.setValue(0.0)
        self.spin_ovp_point.setMinimumWidth(64)
        self.spin_ovp_point.setToolTip("0 表示不设置；无特殊需求请保持 0")
        self.btn_set_ovp_point = make_button("设置")
        r5b1.addWidget(QLabel("过压点(V):"))
        r5b1.addWidget(self.spin_ovp_point, 1)
        r5b1.addWidget(self.btn_set_ovp_point)
        v5b.addLayout(r5b1)
        r5b2 = QHBoxLayout()
        self.combo_ovp_related = QComboBox()
        self.combo_ovp_related.addItems(["允许关联", "禁止关联"])
        self.btn_set_ovp_related = make_button("设置")
        r5b2.addWidget(self.combo_ovp_related, 1)
        r5b2.addWidget(self.btn_set_ovp_related)
        v5b.addLayout(r5b2)
        lay.addWidget(g5b)

        g6 = QGroupBox("复位操作")
        g6.setObjectName("panelGroup")
        h6 = QHBoxLayout(g6)
        h6.setContentsMargins(8, 8, 8, 8)
        self.btn_ovp = make_button("过压复位", tooltip="0x31 过压复位")
        self.btn_short = make_button("短路复位", tooltip="0x44 短路复位")
        h6.addWidget(self.btn_ovp, 1)
        h6.addWidget(self.btn_short, 1)
        lay.addWidget(g6)
        lay.addStretch(1)
        return page

    def _build_tab_info(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 8, 6, 6)
        lay.setSpacing(8)

        self.btn_read_info = make_button("读取选中模块信息", "primary")
        self.btn_read_info.setMinimumHeight(28)
        lay.addWidget(self.btn_read_info)

        g = QGroupBox("模块信息")
        g.setObjectName("panelGroup")
        form = QFormLayout(g)
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(6)
        self.info_fields = {}
        items = [("rated_power", "额定功率(W)"), ("rated_current", "额定电流(A)"),
                 ("work_mode", "输入工作模式"), ("dip_addr", "拨码地址"),
                 ("altitude", "当前海拔(m)"), ("dcdc_ver", "DCDC版本号"),
                 ("pfc_ver", "PFC版本号")]
        for key, label in items:
            val = QLabel(DASH)
            val.setObjectName("detailVal")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(QLabel(label), val)
            self.info_fields[key] = val
        lay.addWidget(g)

        g2 = QGroupBox("扩展遥测")
        g2.setObjectName("panelGroup")
        form2 = QFormLayout(g2)
        form2.setContentsMargins(8, 8, 8, 8)
        form2.setSpacing(6)
        self.ext_fields = {}
        ext_items = [("pfc_temp", "PFC板温度(°C)"), ("panel_temp", "面板温度(°C)"),
                     ("bus_pos", "正半母线(V)"), ("bus_neg", "负半母线(V)"),
                     ("ac_a", "A相电压(V)"), ("ac_b", "B相电压(V)"),
                     ("ac_c", "C相电压(V)")]
        for key, label in ext_items:
            val = QLabel(DASH)
            val.setObjectName("detailVal")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form2.addRow(QLabel(label), val)
            self.ext_fields[key] = val
        lay.addWidget(g2)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------ 日志区
    def _build_log_panel(self):
        frame = QFrame()
        frame.setObjectName("logPanel")
        frame.setFixedHeight(170)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("logBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(6, 4, 6, 4)
        bl.setSpacing(8)
        t = QLabel("CAN 报文日志")
        t.setObjectName("logTitle")
        bl.addWidget(t)
        bl.addSpacing(10)

        self.chk_show_frames = QCheckBox("显示报文")
        self.chk_show_frames.setChecked(True)
        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        bl.addWidget(self.chk_show_frames)
        bl.addWidget(self.chk_autoscroll)

        bl.addWidget(QLabel("导出:"))
        self.btn_log_clear = make_button("清空")
        self.btn_log_clear.setObjectName("logBtn")
        self.btn_log_save = make_button("保存")
        self.btn_log_save.setObjectName("logBtn")
        bl.addWidget(self.btn_log_clear)
        bl.addWidget(self.btn_log_save)
        bl.addStretch(1)

        self.lbl_log_count = QLabel("0 条")
        self.lbl_log_count.setObjectName("logCount")
        bl.addWidget(self.lbl_log_count)
        lay.addWidget(bar)

        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("logText")
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(5000)
        lay.addWidget(self.log_text, 1)
        return frame

    # ============================================================ 信号连接
    def _connect_controller(self):
        c = self.controller
        c.connected.connect(lambda: self._update_conn_state(True))
        c.disconnected.connect(lambda: self._update_conn_state(False))
        c.error.connect(self._on_error)
        c.module_seen.connect(self._on_module_seen)
        c.module_updated.connect(self._on_module_updated)
        c.module_offline.connect(self._on_module_offline)
        c.scan_finished.connect(self._on_scan_finished)
        c.set_failed.connect(self._on_set_failed)
        c.log_line.connect(self._append_log)

        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        self.chk_poll.toggled.connect(
            lambda v: self.controller.set_polling(v, self.poll_spin.value()))
        self.poll_spin.valueChanged.connect(
            lambda v: self.controller.set_polling(self.chk_poll.isChecked(), v))
        self.btn_scan.clicked.connect(self._on_scan)
        self.btn_fault_codes.clicked.connect(self._on_show_fault_codes)

        self.btn_all_on.clicked.connect(lambda: self._broadcast_power(True))
        self.btn_all_off.clicked.connect(lambda: self._broadcast_power(False))
        self.btn_batch_set.clicked.connect(self._on_batch_set)
        self.btn_one_key.clicked.connect(self._on_one_key_init)

        self.btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_clear_sel.clicked.connect(lambda: self._set_all_checked(False))
        self.btn_online_only.clicked.connect(self._select_online_only)
        self.btn_sel_on.clicked.connect(lambda: self._selected_power(True))
        self.btn_sel_off.clicked.connect(lambda: self._selected_power(False))

        self.btn_set_va.clicked.connect(self._on_set_voltage_current)
        self.btn_on.clicked.connect(lambda: self._selected_power(True))
        self.btn_off.clicked.connect(lambda: self._selected_power(False))
        self.btn_on_all.clicked.connect(lambda: self._broadcast_power(True))

        self.btn_set_group.clicked.connect(lambda: self._init_send("group"))
        self.btn_set_addr_mode.clicked.connect(lambda: self._init_send("addr_mode"))
        self.btn_set_input_mode.clicked.connect(lambda: self._init_send("input_mode"))
        self.btn_set_altitude.clicked.connect(lambda: self._init_send("altitude"))
        self.btn_set_power.clicked.connect(lambda: self._init_send("power"))
        self.btn_set_ovp_point.clicked.connect(lambda: self._init_send("ovp_point"))
        self.btn_set_ovp_related.clicked.connect(lambda: self._init_send("ovp_related"))
        self.btn_ovp.clicked.connect(lambda: self._init_send("ovp"))
        self.btn_short.clicked.connect(lambda: self._init_send("short"))

        self.btn_read_info.clicked.connect(self._on_read_info)

        self.btn_log_clear.clicked.connect(self._on_log_clear)
        self.btn_log_save.clicked.connect(self._on_log_save)

    # ============================================================ 连接
    def _on_connect(self):
        mode = "sim" if self.chk_sim.isChecked() else "tcp"
        self._clear_table()
        self.controller.open(mode, self.ip_edit.text().strip(), self.port_spin.value())
        self.controller.set_polling(self.chk_poll.isChecked(), self.poll_spin.value())

    def _on_disconnect(self):
        try:
            self.controller.close()
        except Exception as e:
            self._append_log(f"[错误] 断开连接异常: {e}", "err")
            # 异常路径也要保证界面状态复位
            self._update_conn_state(False)

    def _update_conn_state(self, on: bool):
        self.conn_dot.setProperty("state", "on" if on else "off")
        self.conn_dot.style().unpolish(self.conn_dot)
        self.conn_dot.style().polish(self.conn_dot)
        self.conn_text.setText("已连接" if on else "未连接")
        self.btn_connect.setEnabled(not on)
        self.btn_connect.setText("已连接" if on else "连接")
        self.btn_disconnect.setEnabled(on)
        self.ip_edit.setEnabled(not on)
        self.port_spin.setEnabled(not on)
        self.chk_sim.setEnabled(not on)
        self.status.showMessage("已连接" if on else "未连接")

    def _on_error(self, msg: str):
        self.status.showMessage(msg, 5000)
        self._append_log(f"[错误] {msg}", "err")

    def _on_set_failed(self, addr: int, reg: int, reason: str):
        self.status.showMessage(f"模块 {addr} 设置失败：{reason}", 6000)

    # ============================================================ 扫描 / 模块
    def _on_scan(self):
        if not self.controller.is_open():
            QMessageBox.information(self, "提示", "请先点击「连接」。")
            return
        # 扫描中再点此按钮=中断扫描
        if getattr(self.controller, "_scanning", False):
            self.controller.stop_scan()
            self.btn_scan.setText("开始扫描")
            self._append_log("已中断扫描", "info")
            return
        self._clear_table()
        self.btn_scan.setText("停止扫描")
        self.controller.start_scan()

    def _on_scan_finished(self, found: int):
        self.btn_scan.setText("开始扫描")
        self.overlay.hide()  # 空表预置行已可见，无需占位遮罩
        self._update_selection_stats()

    def _on_module_seen(self, addr: int):
        if addr in self._row_of:
            # 已预置行：标记在线并隐藏遮罩
            row = self._row_of[addr]
            self._updating = True
            self._set_cell(row, COL_ONLINE, "在线", center=True, color="#5ad07a")
            self._updating = False
            self.overlay.hide()
            self._update_selection_stats()
            return
        self._create_row(addr, online=True)

    def _create_row(self, addr: int, online: bool):
        """创建/填充一行（空表预置 或 扫描发现时调用）"""
        if addr in self._row_of:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._row_of[addr] = row
        self._addr_of[row] = addr

        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        chk.setCheckState(Qt.Unchecked)
        chk.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, chk)

        self._set_cell(row, COL_ADDR, f"0x{addr:02X}", center=True)
        if online:
            self._set_cell(row, COL_ONLINE, "● 在线", center=True, color="#047857", big=True)
        else:
            self._set_cell(row, COL_ONLINE, "○ 离线", center=True, color="#9AA2AA", big=True)
        for col in range(COL_POWER, len(COLUMNS)):
            self._set_cell(row, col, DASH, center=(col != COL_FAULT))

        # 设置电压/电流：行内可编辑输入框
        sv = QDoubleSpinBox()
        sv.setRange(0, 1200)
        sv.setDecimals(1)
        sv.setSingleStep(0.5)
        sv.setMinimumWidth(80)
        sv.valueChanged.connect(lambda _v, w=sv: setattr(w, "_user_edited", True))
        self.table.setCellWidget(row, COL_SV, sv)
        self._sv_spins[addr] = sv

        si = QDoubleSpinBox()
        si.setRange(0, 300)
        si.setDecimals(1)
        si.setSingleStep(0.5)
        si.setMinimumWidth(80)
        si.valueChanged.connect(lambda _v, w=si: setattr(w, "_user_edited", True))
        self.table.setCellWidget(row, COL_SI, si)
        self._si_spins[addr] = si

        # 行内设置按钮
        btn = QPushButton("设置")
        btn.setMinimumWidth(52)
        btn.clicked.connect(lambda _=False, a=addr: self._row_set_vi(a))
        self.table.setCellWidget(row, COL_BTN, btn)

        self.overlay.hide()
        self._update_selection_stats()

    def _row_set_vi(self, addr: int):
        """表格行内 设置 按钮：下发该行输入的电压电流"""
        if not self.controller.is_open():
            QMessageBox.information(self, "提示", "请先点击「连接」。")
            return
        sv = self._sv_spins.get(addr)
        si = self._si_spins.get(addr)
        v = sv.value() if sv is not None else 0.0
        i = si.value() if si is not None else 0.0
        self.controller.set_voltage_current(addr, v, i)
        self.status.showMessage(f"已下发模块 {addr} 设置 {v:.1f}V / {i:.1f}A", 5000)
        self._append_log(f"[下发] 模块{addr} 设定 {v:.1f}V / {i:.1f}A", "tx")

    def _on_module_updated(self, addr: int, st):
        from instrument_hub.comm_state import mark_ok
        mark_ok(self)   # 模块实时数据更新 = 通讯真正建立
        row = self._row_of.get(addr)
        if row is None:
            return
        self._updating = True
        try:
            self._set_cell(row, COL_ONLINE, "在线" if st.online else "离线",
                           center=True, color="#5ad07a" if st.online else "#e2574c")
            self._set_cell(row, COL_POWER, "开机" if st.power_on else "关机",
                           center=True, color="#5ad07a" if st.power_on else "#c8c8c8")
            self._set_cell(row, COL_V, self._f(st.voltage, 1), center=True)
            self._set_cell(row, COL_A, self._f(st.current, 1), center=True)
            self._set_cell(row, COL_VIN, self._f(st.input_v, 0), center=True)
            self._set_cell(row, COL_ALLOW, self._f(st.allowed_current, 1), center=True)
            self._set_cell(row, COL_TEMP, self._f(st.temp, 1), center=True)
            faults = st.faults
            self._set_cell(row, COL_FAULT, "；".join(faults) if faults else "正常",
                           center=False, color="#ff8a80" if faults else "#9fe6a8")
        finally:
            self._updating = False
        if self._current_addr == addr:
            self._show_detail(addr)
        self._update_selection_stats()

    def _on_module_offline(self, addr: int):
        row = self._row_of.get(addr)
        if row is not None:
            self._updating = True
            self._set_cell(row, COL_ONLINE, "离线", center=True, color="#e2574c")
            self._updating = False
        # 通讯状态：全部模块离线 = 通讯中断，右上角指示灯回灰
        if all(not m.online for m in self.controller.modules.values()):
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)

    def _set_cell(self, row, col, text, center=False, color=None, big=False):
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, col, item)
        item.setText(text)
        if center:
            item.setTextAlignment(Qt.AlignCenter)
        if color:
            item.setForeground(QColor(color))
        if big:
            item.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))

    @staticmethod
    def _f(v, nd):
        if v is None:
            return DASH
        try:
            return f"{float(v):.{nd}f}"
        except (TypeError, ValueError):
            return DASH

    # ============================================================ 表格交互
    def _row_addr(self, row: int):
        return self._addr_of.get(row)

    def _checked_addrs(self):
        out = []
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 0)
            if it and it.checkState() == Qt.Checked:
                a = self._row_addr(row)
                if a is not None:
                    out.append(a)
        return out

    def _selected_or_current(self):
        sel = self._checked_addrs()
        if sel:
            return sel
        return [self._current_addr] if self._current_addr is not None else []

    def _on_header_toggle(self, checked: bool):
        self._set_all_checked(checked)

    def _set_all_checked(self, checked: bool):
        self._updating = True
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 0)
            if it:
                it.setCheckState(state)
        self._updating = False
        self.table.horizontalHeader().set_checked(checked)
        self._update_selection_stats()

    def _select_online_only(self):
        self._updating = True
        for row in range(self.table.rowCount()):
            addr = self._row_addr(row)
            st = self.controller.modules.get(addr)
            it = self.table.item(row, 0)
            if it and st:
                it.setCheckState(Qt.Checked if st.online else Qt.Unchecked)
        self._updating = False
        self._update_selection_stats()

    def _on_item_changed(self, item):
        if self._updating:
            return
        if item.column() == 0:
            self._update_selection_stats()

    def _on_item_clicked(self, item):
        # 模块地址选中固定在勾选列（选择区域），其余列点击不可选中（规范）
        if item.column() != 0:
            return
        row = item.row()
        addr = self._row_addr(row)
        self._current_addr = addr
        self.controller.set_selected(addr)
        self._update_selection_stats()
        self._show_detail(addr)

    def _update_selection_stats(self):
        total = self.table.rowCount()
        online = sum(1 for a, st in self.controller.modules.items() if st.online)
        selected = len(self._checked_addrs())
        self.lbl_stats.setText(f"模块:{total} 在线:{online} 已选:{selected}")

    def _clear_table(self):
        self._updating = True
        self.table.setRowCount(0)
        self._row_of.clear()
        self._addr_of.clear()
        self._current_addr = None
        self.controller.set_selected(None)
        self._updating = False
        self.table.horizontalHeader().set_checked(False)
        self.overlay.show()
        self._show_detail(None)
        self._update_selection_stats()

    # ============================================================ 详情面板
    def _show_detail(self, addr):
        if addr is None:
            self.detail_title.setText("未选中模块")
            for v in self.detail_fields.values():
                v.setText(DASH)
            self.detail_note.setText("选中模块后可在此查看限值、故障位、输入电压等详细数据。")
            self._clear_info()
            return
        st = self.controller.modules.get(addr)
        if st is None:
            return
        self.detail_title.setText(f"模块 地址 {addr}")
        self.detail_fields["voltage"].setText(self._f(st.voltage, 1) + " V")
        self.detail_fields["current"].setText(self._f(st.current, 1) + " A")
        self.detail_fields["temp"].setText(self._f(st.temp, 1) + " °C")
        self.detail_fields["status"].setText("开机" if st.power_on else "关机")
        parts = []
        if st.rated_current is not None:
            parts.append(f"额定电流 {st.rated_current:.0f} A")
        if st.rated_power is not None:
            parts.append(f"额定功率 {st.rated_power:.0f} W")
        if st.input_v is not None:
            parts.append(f"输入电压 {st.input_v:.0f} V")
        if st.input_power is not None:
            parts.append(f"输入功率 {st.input_power} W")
        if st.work_mode is not None:
            parts.append("输入模式 " + INPUT_WORK_MODES.get(st.work_mode, str(st.work_mode)))
        self.detail_note.setText("；".join(parts) if parts else "暂无详细数据。")
        self._update_info(st)

    def _clear_info(self):
        for v in self.info_fields.values():
            v.setText(DASH)
        for v in self.ext_fields.values():
            v.setText(DASH)

    def _update_info(self, st):
        self.info_fields["rated_power"].setText(self._f(st.rated_power, 0))
        self.info_fields["rated_current"].setText(self._f(st.rated_current, 0))
        self.info_fields["work_mode"].setText(
            INPUT_WORK_MODES.get(st.work_mode, DASH) if st.work_mode is not None else DASH)
        self.info_fields["dip_addr"].setText(DASH if st.dip_addr is None else str(st.dip_addr))
        self.info_fields["altitude"].setText(DASH if st.altitude is None else str(st.altitude))
        self.info_fields["dcdc_ver"].setText(DASH if st.dcdc_ver is None else str(st.dcdc_ver))
        self.info_fields["pfc_ver"].setText(DASH if st.pfc_ver is None else str(st.pfc_ver))
        self.ext_fields["pfc_temp"].setText(self._f(st.pfc_temp, 1))
        self.ext_fields["panel_temp"].setText(self._f(st.panel_temp, 1))
        self.ext_fields["bus_pos"].setText(self._f(st.bus_pos, 1))
        self.ext_fields["bus_neg"].setText(self._f(st.bus_neg, 1))
        self.ext_fields["ac_a"].setText(self._f(st.ac_a, 0))
        self.ext_fields["ac_b"].setText(self._f(st.ac_b, 0))
        self.ext_fields["ac_c"].setText(self._f(st.ac_c, 0))

    # ============================================================ 批量/控制
    def _confirm_power_on(self, addrs, broadcast=False, title="确认开机"):
        """开机二次确认, 弹窗列出目标模块"""
        if broadcast:
            addr_txt = "全部模块(广播)"
        elif not addrs:
            QMessageBox.information(self, "提示", "请先选择模块")
            return False
        elif len(addrs) > 30:
            addr_txt = ", ".join(f"0x{a:02X}" for a in addrs[:30]) + f" … 共 {len(addrs)} 台"
        else:
            addr_txt = ", ".join(f"0x{a:02X}" for a in addrs)
        return QMessageBox.question(
            self, title,
            f"将对以下模块执行开机：\n\n{addr_txt}\n\n确认继续?",
            QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def _on_show_fault_codes(self):
        """显示永联模块状态字/故障位定义"""
        from ..core.registers import STATUS_BITS   # core 在上级包：ui.main_window 里必须用 ..core
        lines = ["永联 NXR 模块状态字故障位定义 (寄存器 0x0040)", ""]
        for bit in sorted(STATUS_BITS.keys()):
            name, is_fault = STATUS_BITS[bit]
            tag = "故障" if is_fault else "状态"
            lines.append(f"  bit{bit:02d} [{tag}]: {name}")
        lines += ["", "说明：bit22 为开关机状态(0=开机/1=关机)，其余故障位置 1 表示对应故障。"]
        QMessageBox.information(self, "故障代码查询", "\n".join(lines))

    def _broadcast_power(self, on: bool):
        if not self.controller.is_open():
            QMessageBox.information(self, "提示", "请先点击「连接」。")
            return
        if on and not self._confirm_power_on(None, True, "确认全部开机"):
            return
        self.controller.broadcast_power(on)

    def _on_batch_set(self):
        if not self.controller.is_open():
            QMessageBox.information(self, "提示", "请先点击「连接」。")
            return
        v = self.batch_v.value()
        a = self.batch_a.value()
        self.controller.broadcast_voltage_current(v, a)
        self.status.showMessage(f"已广播下发 电压 {v}V / 电流 {a}A", 4000)

    def _on_one_key_init(self):
        if not self.controller.is_open():
            QMessageBox.information(self, "提示", "请先点击「连接」。")
            return
        if QMessageBox.question(
                self, "一键初始化",
                "将对全部模块广播下发：\n"
                f"  · 输出电压 {self.batch_v.value()} V\n"
                f"  · 输出电流 {self.batch_a.value()} A\n"
                "  · 地址分配方式 = 拨码设置(默认)\n"
                "  · 组号 = 0\n\n是否继续？") != QMessageBox.Yes:
            return
        self.controller.broadcast_voltage_current(self.batch_v.value(), self.batch_a.value())
        self.controller.broadcast_set_int(0x001F, ADDR_MODE_DIP)
        self.controller.broadcast_set_int(0x001E, 0)
        self.status.showMessage("一键初始化已下发", 4000)

    def _selected_power(self, on: bool):
        addrs = self._selected_or_current()
        if not addrs:
            QMessageBox.information(self, "提示", "请先勾选或点选一个模块。")
            return
        if on and not self._confirm_power_on(addrs, False, "确认选中开机"):
            return
        for a in addrs:
            self.controller.set_power(a, on)

    def _on_set_voltage_current(self):
        v = self.ctrl_v.value()
        a = self.ctrl_a.value()
        if self.chk_broadcast_va.isChecked():
            self.controller.broadcast_voltage_current(v, a)
            self.status.showMessage(f"已广播下发 电压 {v}V / 电流 {a}A", 4000)
            return
        addrs = self._selected_or_current()
        if not addrs:
            QMessageBox.information(self, "提示", "请先勾选或点选一个模块。")
            return
        for addr in addrs:
            self.controller.set_voltage_current(addr, v, a)

    def _init_send(self, what: str):
        if self.chk_group_cast.isChecked():
            mode = "group"
        elif self.chk_broadcast_init.isChecked():
            mode = "all"
        else:
            mode = "sel"

        addrs = []
        if mode == "sel":
            addrs = self._selected_or_current()
            if not addrs:
                QMessageBox.information(self, "提示", "请先勾选或点选一个模块。")
                return
        grp = self.spin_group.value()

        def dispatch(set_one, set_all, set_group):
            if mode == "sel":
                for a in addrs:
                    set_one(a)
            elif mode == "all":
                set_all()
            else:
                set_group(grp)

        if what == "group":
            dispatch(lambda a: self.controller.set_group(a, grp),
                     lambda: self.controller.broadcast_set_int(0x001E, grp),
                     lambda g: self.controller.broadcast_group_set_int(g, 0x001E, grp))
        elif what == "addr_mode":
            dip = (self.combo_addr_mode.currentIndex() == 0)
            val = ADDR_MODE_DIP if dip else ADDR_MODE_AUTO
            dispatch(lambda a: self.controller.set_addr_mode(a, dip),
                     lambda: self.controller.broadcast_set_int(0x001F, val),
                     lambda g: self.controller.broadcast_group_set_int(g, 0x001F, val))
        elif what == "input_mode":
            dc = (self.combo_input_mode.currentIndex() == 1)
            val = 0x00000002 if dc else 0x00000001
            dispatch(lambda a: self.controller.set_input_mode(a, dc),
                     lambda: self.controller.broadcast_set_int(0x0046, val),
                     lambda g: self.controller.broadcast_group_set_int(g, 0x0046, val))
        elif what == "altitude":
            v = self.spin_altitude.value()
            dispatch(lambda a: self.controller.set_altitude(a, v),
                     lambda: self.controller.broadcast_set_int(0x0017, v),
                     lambda g: self.controller.broadcast_group_set_int(g, 0x0017, v))
        elif what == "power":
            v = self.spin_power.value()
            dispatch(lambda a: self.controller.set_output_power(a, v),
                     lambda: self.controller.broadcast_set_float(0x0020, v),
                     lambda g: self.controller.broadcast_group_set_float(g, 0x0020, v))
        elif what == "ovp_point":
            v = self.spin_ovp_point.value()
            dispatch(lambda a: self.controller.set_ovp_point(a, v),
                     lambda: self.controller.broadcast_set_float(0x0023, v),
                     lambda g: self.controller.broadcast_group_set_float(g, 0x0023, v))
        elif what == "ovp_related":
            allow = (self.combo_ovp_related.currentIndex() == 0)
            val = OVP_RELATED_ALLOW if allow else OVP_RELATED_DENY
            dispatch(lambda a: self.controller.set_ovp_related(a, allow),
                     lambda: self.controller.broadcast_set_int(0x003E, val),
                     lambda g: self.controller.broadcast_group_set_int(g, 0x003E, val))
        elif what == "ovp":
            dispatch(lambda a: self.controller.ovp_reset(a),
                     lambda: self.controller.broadcast_set_int(0x0031, OVP_RESET_VALUE),
                     lambda g: self.controller.broadcast_group_set_int(g, 0x0031, OVP_RESET_VALUE))
        elif what == "short":
            dispatch(lambda a: self.controller.short_reset(a),
                     lambda: self.controller.broadcast_set_int(0x0044, SHORT_RESET_VALUE),
                     lambda g: self.controller.broadcast_group_set_int(g, 0x0044, SHORT_RESET_VALUE))

    def _on_read_info(self):
        addrs = self._selected_or_current()
        if not addrs:
            QMessageBox.information(self, "提示", "请先勾选或点选一个模块。")
            return
        addr = addrs[0]
        self._current_addr = addr
        self.controller.set_selected(addr)
        for reg in (0x0011, 0x0012, 0x004B, 0x0043, 0x004A, 0x0056, 0x0057):
            self.controller.read_register(addr, reg)

    def _adv_send(self, kind: str):
        addrs = self._selected_or_current()
        if not addrs:
            QMessageBox.information(self, "提示", "请先勾选或点选一个模块。")
            return
        for addr in addrs:
            if kind == "ovp":
                self.controller.ovp_reset(addr)
            elif kind == "short":
                self.controller.short_reset(addr)
            elif kind == "dip":
                self.controller.read_register(addr, 0x0043)
            elif kind == "ver":
                self.controller.read_register(addr, 0x0056)
                self.controller.read_register(addr, 0x0057)

    # ============================================================ 日志
    def _append_log(self, text: str, kind: str = "info"):
        self._log_lines.append((text, kind))
        if kind in ("tx", "rx") and not self.chk_show_frames.isChecked():
            self.lbl_log_count.setText(f"{len(self._log_lines)} 条")
            return
        self.log_text.appendPlainText(text)
        if self.chk_autoscroll.isChecked():
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum())
        self.lbl_log_count.setText(f"{len(self._log_lines)} 条")

    def _on_log_clear(self):
        self._log_lines.clear()
        self.log_text.clear()
        self.lbl_log_count.setText("0 条")

    def _on_log_save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存报文日志", "can_log.txt", "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for text, _kind in self._log_lines:
                    f.write(text + "\n")
            self.status.showMessage(f"日志已保存：{path}", 5000)
        except OSError as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def closeEvent(self, event):
        try:
            self.controller.close()
            super().closeEvent(event)
        except Exception:  # noqa: BLE001  closeEvent 槽内异常不得 abort 整机
            pass
