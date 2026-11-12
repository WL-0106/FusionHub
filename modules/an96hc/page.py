# -*- coding: utf-8 -*-
"""AN9637HC 安规综合分析仪 · 融合版界面（FusionHub 风格）。

协议/传输/设备逻辑复用原上位机（protocol / transport / device / dialects / probe），
界面按整体 UI 风格重建：四测试模式参数编辑、启动/停止（高压二次确认）、结果查询。
"""
from typing import Dict

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from instrument_hub.dialogs import ConfirmOutputDialog
from instrument_hub.widgets import Card, Chip

from . import dialects as D
from . import protocol as P
from .device import AN96HC
from .transport import SerialTransport, TcpTransport


class An96hcPage(QWidget):
    """安规综合分析仪：连接 → 参数编辑/下发 → 启动测试（二次确认）→ 结果查询。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dev: AN96HC = None
        self._editors: Dict[str, Dict[str, QWidget]] = {}   # mode -> {key: 控件}
        # SE 步上下文跟踪：仪器「当前测试步」的模式（最后追加的步）。
        # SE 参数命令作用于当前步且按该步类型解释（ACW 步上限是 EHT、DCW/IR/GND 是 EH），
        # 上下文与页签不一致时专有命令被仪器静默拒收 → 后续每条等满超时（表象：下发卡死）。
        self._cur_step_mode = None   # None = 未知（刚连接）

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_conn_card())
        root.addWidget(self._build_param_card(), 1)
        root.addWidget(self._build_ctrl_card())
        self._update_capability()   # 按初始方言落定按钮可用性/步号显隐

    # ------------------------------------------------------------ 连接
    def _build_conn_card(self) -> Card:
        card = Card("通讯连接",
                    "协议/波特率必须与仪器面板设置一致（SE / Ainuo ASCII / SCPI），"
                    "否则命令发出不生效；接线用 RS232 交叉线（2-3 交叉、5 共地），"
                    "接电脑 COM 口")
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(QLabel("连接方式"))
        self.cmb_link = QComboBox()
        self.cmb_link.addItems(["串口 RS232/485", "TCP（模拟器）"])
        self.cmb_link.setFixedWidth(130)
        h.addWidget(self.cmb_link)

        h.addWidget(QLabel("端口"))
        self.ed_port = QComboBox()
        self.ed_port.setEditable(False)
        # 串口候选自动枚举（打开即刷新，插拔后手动刷新仍可用），TCP 候选保留
        from instrument_hub.serial_ports import enumerate_ports
        self._serial_ports = enumerate_ports()
        self.ed_port.addItems((self._serial_ports or ["COM3"]) + ["127.0.0.1:5020"])
        self.ed_port.setCurrentText(self._serial_ports[0] if self._serial_ports else "COM3")
        self.ed_port.setFixedWidth(140)
        h.addWidget(self.ed_port)

        h.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        self.cmb_baud.addItems(["9600", "19200", "38400", "57600"])
        self.cmb_baud.setFixedWidth(86)
        h.addWidget(self.cmb_baud)

        h.addWidget(QLabel("协议"))
        self.cmb_dialect = QComboBox()
        for d in D.DIALECTS:
            self.cmb_dialect.addItem(d.label)
        self.cmb_dialect.setFixedWidth(120)
        self.cmb_dialect.setToolTip("必须与仪器面板通讯协议设置一致（SE / Ainuo ASCII / SCPI）")
        self.cmb_dialect.currentIndexChanged.connect(lambda _i: self._update_capability())
        h.addWidget(self.cmb_dialect)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.toggle_conn)
        h.addWidget(self.btn_connect)
        self.btn_diag = QPushButton("仪器诊断")
        self.btn_diag.setToolTip("只读探测仪器当前协议，排查协议不匹配")
        self.btn_diag.clicked.connect(self.diagnose)
        h.addWidget(self.btn_diag)
        h.addStretch(1)
        self.lbl_info = QLabel("未连接")
        self.lbl_info.setObjectName("Muted")
        h.addWidget(self.lbl_info)
        card.body_lay.addLayout(h)
        return card

    # ------------------------------------------------------------ 参数
    def _build_param_card(self) -> Card:
        card = Card("测试参数", "参数表由协议（单一事实源）生成；下发设定写入仪器当前步/系统")
        self.tabs = QTabWidget()
        for mode, spec in P.MODES.items():
            self.tabs.addTab(self._mode_tab(mode, spec), f"  {spec['name']}（{mode}）  ")
        self.tabs.addTab(self._mode_tab("SYS", {"params": P.SYSTEM_PARAMS}), "  系统参数  ")
        self.tabs.currentChanged.connect(lambda _i: self._update_capability())
        card.body_lay.addWidget(self.tabs, 1)
        return card

    def _mode_tab(self, mode: str, spec: dict) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(16, 16, 16, 16)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(14)
        editors = {}
        for i, p in enumerate(spec["params"]):
            # 每行 2 组参数，7 列结构：
            #   [左弹性 | 标签 | 输入框 | 固定分隔 | 标签 | 输入框 | 右弹性]
            # 左右弹性列各 stretch 1 → 整组参数居中；标签紧贴各自输入框；
            # 两组之间用固定间距(列3)分隔，彻底消除「标签贴最左、控件悬中、大片空白」。
            col = 1 if i % 2 == 0 else 4
            lab = QLabel(p.label + (p.unit and f"（{p.unit}）" or ""))
            g.addWidget(lab, i // 2, col)
            ed = self._make_editor(p)
            ed.setToolTip(p.note or p.set_cmd)
            g.addWidget(ed, i // 2, col + 1)
            editors[p.key] = ed
        self._editors[mode] = editors
        # 左右弹性列承接富余宽度（居中），标签/输入框列与中间分隔列保持紧凑
        g.setColumnStretch(0, 1)
        g.setColumnStretch(6, 1)
        g.setColumnMinimumWidth(3, 32)   # 两组之间的固定间距
        g.setRowStretch(len(spec["params"]) // 2 + 1, 1)
        return w

    @staticmethod
    def _make_editor(p: P.Param):
        if p.kind == "enum" and p.enum:
            w = QComboBox()
            for k, v in p.enum.items():
                w.addItem(str(v), k)
            keys = list(p.enum.keys())
            if p.default in keys:
                w.setCurrentIndex(keys.index(p.default))
            w.setFixedWidth(170)
            return w
        if p.kind == "scanner":
            w = QLineEdit(str(p.default))
            w.setFixedWidth(170)
            return w
        w = QDoubleSpinBox()
        lo, hi = p.rng or (0.0, 99999.0)
        w.setRange(float(lo), float(hi))
        w.setDecimals(3 if p.kind == "float" else 0)
        try:
            w.setValue(float(p.default))
        except (TypeError, ValueError):
            pass
        w.setFixedWidth(170)
        return w

    # ------------------------------------------------------------ 控制
    def _build_ctrl_card(self) -> Card:
        card = Card("测试控制", "启动测试输出高压，必须二次确认；退出上位机自动停止测试")
        h = QHBoxLayout()
        h.setSpacing(8)
        self.lbl_step = QLabel("目标步号")
        h.addWidget(self.lbl_step)
        self.sp_step = QSpinBox()
        self.sp_step.setRange(1, 99)
        self.sp_step.setValue(1)
        self.sp_step.setFixedWidth(64)
        self.sp_step.setToolTip("SCPI 协议参数按步号寻址（SAFE:STEP n:...），"
                                "下发/回读均作用于这里指定的步；SE/Ainuo 作用于当前步，无需填写")
        h.addWidget(self.sp_step)
        self.btn_apply = QPushButton("下发设定")
        self.btn_apply.setToolTip("把当前参数表写入仪器（SCPI 按目标步号寻址；"
                                  "Ainuo 为「追加步并带参数」语义，自动按当前参数追加一步）")
        self.btn_apply.clicked.connect(self.apply_params)
        h.addWidget(self.btn_apply)
        self.btn_add_step = QPushButton("添加测试步")
        self.btn_add_step.setToolTip("按当前模式追加测试步并携带当前参数表"
                                     "（SE: SAA/SAD/SAI/SAG 后写参数；Ainuo: SET-XXX 一条带全参）")
        self.btn_add_step.clicked.connect(self.add_step)
        h.addWidget(self.btn_add_step)
        self.btn_read = QPushButton("读取仪器")
        self.btn_read.setToolTip("回读仪器参数到当前参数表（SCPI 按目标步号寻址）")
        self.btn_read.clicked.connect(self.read_params)
        h.addWidget(self.btn_read)
        self.btn_start = QPushButton("启动测试")
        self.btn_start.setProperty("selfStyled", True)   # 自绘红色警示钮，框架不按文字刷色
        self.btn_start.setStyleSheet(
            "QPushButton{background:#B01030; color:#FFFFFF; border:2px solid #8A0C26;"
            " border-radius:10px; font-weight:700; padding:6px 16px;}")
        self.btn_start.clicked.connect(self.start_test)
        h.addWidget(self.btn_start)
        self.btn_stop = QPushButton("停止测试")
        self.btn_stop.clicked.connect(self.stop_test)
        h.addWidget(self.btn_stop)
        self.btn_result = QPushButton("查询结果")
        self.btn_result.clicked.connect(self.query_result)
        h.addWidget(self.btn_result)
        h.addStretch(1)
        self.lbl_stat = QLabel("就绪")
        self.lbl_stat.setObjectName("Muted")
        h.addWidget(self.lbl_stat)
        card.body_lay.addLayout(h)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("通讯应答 / 测试结果 / 诊断信息显示在这里…")
        self.log.setFixedHeight(150)
        card.body_lay.addWidget(self.log)
        return card

    # ------------------------------------------------------------ 动作
    def toggle_conn(self) -> None:
        if self.dev is not None:
            try:
                self.dev.transport.close()
            except Exception:
                pass
            self.dev = None
            from instrument_hub.comm_state import mark_lost
            mark_lost(self)   # 断开 = 通讯中断
            self.btn_connect.setText("连接")
            self.btn_connect.setObjectName("btnConnect")
            self.lbl_info.setText("未连接")
            self._log("已断开连接")
            return
        try:
            if self.cmb_link.currentIndex() == 0:
                tr = SerialTransport(self.ed_port.currentText().strip(),
                                     baud=int(self.cmb_baud.currentText()))
            else:
                host, _, port = self.ed_port.currentText().strip().partition(":")
                tr = TcpTransport(host or "127.0.0.1", int(port or 5020))
            tr.open()      # 传输层需显式打开
            self.dev = AN96HC(tr, b"\r\n", D.get(self.cmb_dialect.currentText()))
            self.dev.set_logger(self._log)
            # 打开串口 ≠ 连接成功：探测到有效应答才置已连接（波特率/协议不对时仪器静默）
            alive, info = self.dev.probe()
            if not alive:
                raise P.ProtocolError(
                    "仪器无应答（打开串口成功但通讯未建立）。"
                    "请核对波特率 %s 与仪器面板是否一致，并确认协议选择「%s」正确"
                    % (self.cmb_baud.currentText(), self.cmb_dialect.currentText()))
            from instrument_hub.comm_state import mark_ok
            mark_ok(self)   # probe() 读到应答 = 通讯真正建立
            self.btn_connect.setText("已连接")
            self.btn_connect.setObjectName("btnConnected")
            self._cur_step_mode = None   # 重连后仪器当前步类型待探测
            if self.dev.d.needs_step_context:
                # SE：*IDN? 无应答/NAK 属协议特性——用专有命令试探当前步类型，
                # 连接即建立步上下文（否则参数页读写全被「上下文未知」拦住）
                m = self.dev.detect_step_mode()
                self._cur_step_mode = m
                if m:
                    info = info or "已连接（SE·当前步 %s）" % m
                    self._log(f"已探测仪器当前测试步类型：{m}"
                              f"（SE 参数读写作用于仪器屏幕当前编辑的该步）")
                else:
                    info = info or "已连接（SE·当前档案无测试步）"
                    self._log("仪器当前档案无测试步，请先在模式页签点「添加测试步」"
                              "建立测试步后再下发参数")
            self.lbl_info.setText(str(info)[:60] or "已连接（未识别到型号）")
            self._log(f"连接成功：{info or '（仪器应答正常，未识别到型号）'}")
            # 连上即自动回读仪器真实参数设置（含系统参数），免手动逐页点「读取仪器」
            self._auto_read()
        except Exception as e:
            # 失败必须关传输——否则串口被占着，下次连接必失败
            if self.dev is not None:
                try:
                    self.dev.transport.close()
                except Exception:
                    pass
            self.dev = None
            self.btn_connect.setText("连接")
            self.btn_connect.setObjectName("btnConnect")
            self.lbl_info.setText("未连接")
            self._log(f"连接失败：{e}")

    def add_step(self) -> None:
        """追加测试步（SE 仅追加空步——真机屏幕不会切到新步，无法立即写参；
        Ainuo 一条 SET-XXX 全参追加）。"""
        if not self._ensure():
            return
        mode = self._current_mode()
        if mode == "SYS":
            self._log("系统参数页不涉及测试步")
            return
        d = self.dev.d
        values = self._collect_values(mode)
        try:
            if d.needs_step_context:
                # SE：SAD 只把空步追加到档案末尾，仪器屏幕不会自动打开它——
                # 立即写参会写进「屏幕当前编辑步」（写错步），所以只追加并引导。
                self.dev.add_step(mode)
                self._log(f"已在仪器档案末尾追加 {mode} 空测试步。"
                          f"请在仪器面板上打开该步后，回上位机 {mode} 页签下发参数")
            elif d.add_step_takes_values:
                self.dev.add_step(mode, values)
                self._log(f"已追加测试步：{mode}（含当前参数）")
            else:   # 兜底（SCPI 无新增步命令，按钮已禁用）
                self.dev.add_step(mode)
                self._log(f"已追加测试步：{mode}")
        except Exception as e:
            self._log(f"追加测试步失败：{e}")

    def _verify_readback(self, mode: str, editors) -> None:
        """SE 专用：下发后读回首个参数验证写入。

        真机两个特性决定 ACK 不可信、必须读回：① 仪器屏幕编辑页不实时刷新，
        看屏幕确认不了；② 对与步类型不符的专有命令也可能回 ACK（收到即 ACK）。
        读回是唯一可靠的写入确认。"""
        params = P.MODES[mode]["params"]
        if not params:
            return
        p0 = params[0]
        try:
            sent = float(self._value(editors[p0.key], p0))
        except (TypeError, ValueError):
            return
        try:
            back_v = float(self.dev.get_param(mode, p0, None))
        except Exception as e:
            self._log(f"读回验证失败（{p0.label}）：{e}")
            return
        if abs(back_v - sent) < 1e-6:
            self._log(f"读回验证通过：{p0.label} 已写入仪器（{p0.set_cmd}={back_v:g}）。"
                      f"注：仪器屏幕编辑页可能不实时刷新，以读回值为准")
        else:
            self._log(f"读回验证不符：{p0.label} 下发 {sent:g}、仪器读回 {back_v:g}"
                      f"——参数可能未写入目标步，请在仪器上核对")

    def _collect_values(self, mode: str) -> dict:
        """当前参数表 → {参数键: 界面值}（线程外/同步收集，供带参追加步用）。"""
        editors = self._editors[mode]
        return {p.key: self._value(editors[p.key], p)
                for p in P.MODES[mode]["params"]}

    def apply_params(self) -> None:
        if not self._ensure():
            return
        mode = self._current_mode()
        editors = self._editors[mode]
        d = self.dev.d
        step = self.sp_step.value() if d.needs_step_no else None
        try:
            if mode == "SYS":
                for p in P.SYSTEM_PARAMS:
                    self.dev.set_system(p, self._value(editors[p.key], p))
                self._log("系统参数已下发。注意：波特率/远程控制写入后仪器侧立即生效，"
                          "若通讯中断请按新参数重新连接")
            elif not d.can_set_existing_step and d.add_step_takes_values:
                # Ainuo：SET-XXX 是「追加一步并带全部参数」，无改写命令——
                # 「下发设定」自动转为带当前参数追加一步，避免必现报错两头堵
                self.dev.add_step(mode, self._collect_values(mode))
                self._log(f"{mode} 参数已下发（{d.label} 按「追加步并带参数」语义，"
                          f"本次已在末尾追加一步）")
            else:
                if d.needs_step_context and self._cur_step_mode != mode:
                    # 真机实证（2.43.2 现场）：SE 参数命令写入「仪器屏幕当前编辑的
                    # 测试步」，SAD 追加新步不会让屏幕切过去——失配时下发会把参数
                    # 写进屏幕上别的模式的步（现场：DCW 参数写进了 ACW 步，且真机
                    # 对 DCW 专有命令也回 ACK 不报错）。上位机无法远程切换屏幕步，
                    # 只能阻止下发并引导用户在仪器面板上切换。
                    self._log(
                        "已阻止下发：SE 参数将写入「仪器屏幕当前编辑的测试步」（当前为 %s），"
                        "与 %s 页签不一致。请先在仪器面板上切到 %s 模式的测试步"
                        "（或新建并打开），再回上位机下发"
                        % (self._cur_step_mode or "未知", mode, mode))
                    return
                skipped = [p.label for p in P.MODES[mode]["params"]
                           if not d.has_param(mode, p)]
                for p in P.MODES[mode]["params"]:
                    if not d.has_param(mode, p):
                        continue      # 手册无此命令的参数跳过，不中断整组下发
                    self.dev.set_param(mode, p, self._value(editors[p.key], p), step)
                note = (f"（目标步号 {step}）" if step else "") + \
                       (f"；{d.label} 无命令的参数已跳过：{'、'.join(skipped)}" if skipped else "")
                self._log(f"{mode} 参数已下发{note}")
                if d.needs_step_context:
                    self._verify_readback(mode, editors)
        except Exception as e:
            self._log(f"下发失败：{e}")

    def read_params(self) -> None:
        if not self._ensure():
            return
        self._read_mode_into(self._current_mode())

    def _read_mode_into(self, mode: str) -> None:
        """把仪器参数回读到指定页编辑器（不切页签，供手动回读/连接自动回读共用）。"""
        d = self.dev.d
        if mode != "SYS" and d.needs_step_context and self._cur_step_mode != mode:
            # SE 读参数同样作用于「仪器屏幕当前编辑的测试步」：上下文不一致/未知时，
            # 读回的是屏幕上别的模式的步（张冠李戴），还可能把界面值覆盖成错值——
            # 明确跳过并引导用户在仪器面板上切换。
            self._log(
                "回读已跳过：SE 参数按「仪器屏幕当前编辑的测试步」读写（当前为 %s），"
                "与 %s 页签不一致。请先在仪器面板上切到 %s 模式的测试步，再读取/下发"
                % (self._cur_step_mode or "未知", mode, mode))
            return
        editors = self._editors[mode]
        step = self.sp_step.value() if d.needs_step_no else None
        try:
            params = P.SYSTEM_PARAMS if mode == "SYS" else P.MODES[mode]["params"]
            skipped = []
            for p in params:
                if mode != "SYS" and not self.dev.d.has_param(mode, p):
                    skipped.append(p.label)
                    continue
                v = (self.dev.get_system(p) if mode == "SYS"
                     else self.dev.get_param(mode, p, step))
                if v is not None:
                    self._set_value(editors[p.key], p, v)
            note = (f"（目标步号 {step}）" if step else "") + \
                   (f"；无命令的参数已跳过：{'、'.join(skipped)}" if skipped else "")
            self._log(f"{mode} 参数已回读{note}")
        except Exception as e:
            self._log(f"回读失败：{e}")

    def _auto_read(self) -> None:
        """连接成功后自动回读仪器参数设置：系统参数（方言支持时）+ 当前页签。

        让用户连上即看到仪器上的真实参数，而不是界面默认值。
        回读能力按方言：Ainuo 无「回读单步参数」命令则跳过并提示。"""
        if self.dev is None:
            return
        d = self.dev.d
        targets = []
        if d.supports_system_params():
            targets.append("SYS")
        cur = self._current_mode()
        cur_ok = (cur != "SYS" and d.can_set_existing_step
                  and (not d.needs_step_context or self._cur_step_mode == cur))
        if cur_ok:
            targets.append(cur)   # get_param 与改参能力同源（Ainuo 无回读命令）
        if not targets:
            self._log(f"{d.label} 无参数回读命令，已跳过自动回读（可点「查询结果」查数据）")
            return
        self._log(f"连接成功，自动回读仪器参数设置（{'、'.join(targets)}）…")
        for mode in targets:
            self._read_mode_into(mode)
        if cur != "SYS" and not cur_ok and d.needs_step_context:
            self._log(f"{d.label} 参数按「仪器屏幕当前编辑的测试步」读写（当前步为 "
                      f"{self._cur_step_mode or '未知'}），已跳过 {cur} 页自动回读；"
                      f"请在仪器面板切换到对应模式的测试步后再读写")

    def start_test(self) -> None:
        if not self._ensure():
            return
        mode = self._current_mode()
        summary = "　".join(f"{p.label} {self._value(self._editors[mode][p.key], p)}"
                            for p in (P.MODES[mode]["params"] if mode in P.MODES else [])[:4])
        dlg = ConfirmOutputDialog("AN9637HC 安规综合分析仪",
                                  f"启动 {mode} 测试（输出高压）",
                                  "测试将输出高压！确认接线（H.V.1/SENSE）与量程无误、"
                                  "被测体固定到位、人员离开后再启动。", summary, self)
        if dlg.exec_() != ConfirmOutputDialog.Accepted:
            return
        try:
            self.dev.start_test()
            self._log(f"{mode} 测试已启动（用户二次确认）")
        except Exception as e:
            self._log(f"启动失败：{e}")

    def stop_test(self) -> None:
        if not self._ensure():
            return
        try:
            self.dev.stop_test()
            self._log("测试已停止")
        except Exception as e:
            self._log(f"停止失败：{e}")

    def query_result(self) -> None:
        if not self._ensure():
            return
        try:
            text = self.dev.query_test_data()
            self._log(f"测试数据：{text}")
            try:
                rows = self.dev.parse_results(text)
                if rows:
                    self._log(f"解析结果：{rows}")
            except Exception:
                pass
        except Exception as e:
            self._log(f"查询失败：{e}")

    def diagnose(self) -> None:
        """仪器诊断：只读探测当前协议，排查协议不匹配。"""
        if self.dev is None:
            self.toggle_conn()
            if self.dev is None:
                return
        try:
            self._log(f"诊断：identify = {self.dev.identify()}")
        except Exception as e:
            self._log(f"诊断失败：{e}")

    # ------------------------------------------------------------ 工具
    def _update_capability(self) -> None:
        """按协议方言能力位联动控件：步号仅 SCPI 可见；SCPI 无新增步命令；
        Ainuo 无「回读/改写单步参数」命令；系统参数仅 SE 支持。"""
        d = D.get(self.cmb_dialect.currentText())
        is_sys = self._current_mode() == "SYS"
        self.lbl_step.setVisible(d.needs_step_no)
        self.sp_step.setVisible(d.needs_step_no)
        if is_sys:
            ok = d.supports_system_params()
            self.btn_apply.setEnabled(ok)
            self.btn_read.setEnabled(ok)
            self.btn_add_step.setEnabled(False)
            if not ok:
                tip = f"{d.label} 不支持系统参数读写（请切到 SE 协议，或在仪器面板设置）"
                self.btn_apply.setToolTip(tip)
                self.btn_read.setToolTip(tip)
        else:
            self.btn_apply.setEnabled(True)
            self.btn_read.setEnabled(d.can_set_existing_step)
            self.btn_add_step.setEnabled(d.can_add_step)
            if not d.can_set_existing_step:
                self.btn_read.setToolTip(f"{d.label} 没有「回读单步参数」命令，请用查询结果查数据")
            if not d.can_add_step:
                self.btn_add_step.setToolTip(
                    f"{d.label} 没有「新增测试步」命令，请在仪器面板建步后按步号改参数")

    def _ensure(self) -> bool:
        if self.dev is None:
            self._log("请先连接仪器")
            return False
        return True

    def _current_mode(self) -> str:
        text = self.tabs.tabText(self.tabs.currentIndex())
        for mode in list(P.MODES) + ["SYS"]:
            if f"（{mode}）" in text or (mode == "SYS" and "系统参数" in text):
                return mode
        return "ACW"

    @staticmethod
    def _value(ed: QWidget, p: P.Param):
        if isinstance(ed, QComboBox):
            return ed.currentData()
        if isinstance(ed, QLineEdit):
            return ed.text().strip()
        return ed.value()

    @staticmethod
    def _set_value(ed: QWidget, p: P.Param, v) -> None:
        try:
            if isinstance(ed, QComboBox):
                idx = list(p.enum.keys()).index(int(v))
                ed.setCurrentIndex(idx)
            elif isinstance(ed, QLineEdit):
                ed.setText(str(v))
            else:
                ed.setValue(float(v))
        except Exception:
            pass

    def _log(self, text: str) -> None:
        self.log.appendPlainText(str(text))

    def shutdown(self) -> None:
        if self.dev is not None:
            try:
                self.dev.stop_test()
            except Exception:
                pass
            try:
                self.dev.transport.close()
            except Exception:
                pass
            self.dev = None
