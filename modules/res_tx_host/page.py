# -*- coding: utf-8 -*-
"""电阻变送器上位机 · 融合版界面（FusionHub 风格）。

Modbus-RTU 协议栈 / 寄存器定义复用 core.protocol（零逻辑改动），
界面按整体 UI 风格重建：
串口配置 → 实时读值（整数 + 浮点两路电阻值）→ RS485 参数读写 →
手动发帧（自动补 CRC）→ 通讯日志。

通信参数修改协议约束：写 7167/7168/7169 前必须先写 7166=0xCCAA 打开许可。
"""
import threading
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
                             QWidget)

from instrument_hub.widgets import Card

from .core.protocol import (ALLOW_VALUE, BAUD_MAP, BAUD_TO_CODE, FMT_MAP,
                            REG_ADDR, REG_ALLOW, REG_BAUD, REG_FMT,
                            REG_RES_FLOAT, REG_RES_INT, build_frame, check_frame,
                            f32_abcd, parse_exception, read_regs, u16,
                            write_single_reg)


def _hexs(data: bytes) -> str:
    return " ".join("%02X" % b for b in data)


class ResTxPage(QWidget):
    """电阻变送器：连接 → 电阻值轮询 / RS485 参数读写 / 手动发帧。"""

    # 采集启停按钮两态配色（与采集卡模块一致）
    _POLL_ON_QSS = ("QPushButton{background:#10B981; color:#FFFFFF; border:2px solid #047857; "
                    "border-radius:10px; font-weight:700; font-size:12px; padding:3px 12px;}"
                    "QPushButton:pressed{background:#047857;}")
    _POLL_OFF_QSS = ("QPushButton{background:#FFFFFF; color:#4B4A73; border:2px solid #D6D3EE; "
                     "border-radius:10px; font-weight:700; font-size:12px; padding:3px 12px;}"
                     "QPushButton:pressed{background:#D6D3EE;}")

    sig_log = pyqtSignal(str, str)
    sig_res = pyqtSignal(object)         # (int_val, float_val) 或 None
    sig_param = pyqtSignal(str)          # 参数读取结果文本
    sig_write = pyqtSignal(str)          # 写操作结果文本

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ser = None
        self._polling = False
        self._inflight = False
        self._ok = 0
        self._fail = 0
        self._addr = 1
        self._trace_on = False
        self._tx_lock = threading.Lock()

        self.sig_log.connect(self._append_log)
        self.sig_res.connect(self._on_res)
        self.sig_param.connect(self._on_param)
        self.sig_write.connect(self._on_write)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(self._build_conn_card())

        mid = QHBoxLayout()
        mid.setSpacing(8)
        mid.addWidget(self._build_read_card(), 1)
        mid.addWidget(self._build_param_card(), 0)
        root.addLayout(mid, 1)

        root.addWidget(self._build_raw_card())
        root.addWidget(self._build_log_group())

        self._refresh_ports()

    # ---------------------------------------------------------- 串口配置
    def _build_conn_card(self) -> Card:
        card = Card("串口配置",
                    "Modbus-RTU · RS-485 · 8 数据位 · 出厂 9600 8N1 · 从站地址 1~247")
        g = QHBoxLayout()
        g.setSpacing(8)

        g.addWidget(QLabel("串口"))
        self.cmb_port = QComboBox()
        self.cmb_port.setEditable(False)
        self.cmb_port.setStyleSheet("QComboBox{min-width:110px;}")
        g.addWidget(self.cmb_port)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setMinimumHeight(30)
        self.btn_refresh.setFixedWidth(56)
        self.btn_refresh.clicked.connect(self._refresh_ports)
        g.addWidget(self.btn_refresh)

        g.addWidget(QLabel("波特率"))
        self.cmb_baud = QComboBox()
        for b in BAUD_MAP.values():
            self.cmb_baud.addItem(str(b))
        self.cmb_baud.setCurrentText("9600")
        g.addWidget(self.cmb_baud)

        g.addWidget(QLabel("校验"))
        self.cmb_parity = QComboBox()
        self.cmb_parity.addItems(["N", "E", "O"])
        g.addWidget(self.cmb_parity)

        g.addWidget(QLabel("从站地址"))
        self.sp_addr = QSpinBox()
        self.sp_addr.setRange(1, 247)
        self.sp_addr.setValue(1)
        self.sp_addr.setFixedWidth(64)
        g.addWidget(self.sp_addr)

        g.addSpacing(6)
        self.btn_conn = QPushButton("连接")
        self.btn_conn.setMinimumHeight(30)
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.clicked.connect(self._on_connect)
        g.addWidget(self.btn_conn)
        self.btn_disc = QPushButton("断开")
        self.btn_disc.setMinimumHeight(30)
        self.btn_disc.clicked.connect(self._on_disconnect)
        self.btn_disc.setEnabled(False)
        g.addWidget(self.btn_disc)

        self.chk_trace = QCheckBox("显示报文")
        self.chk_trace.toggled.connect(self._on_trace_toggled)
        g.addWidget(self.chk_trace)

        self.lbl_state = QLabel("未连接")
        self.lbl_state.setObjectName("Muted")
        g.addWidget(self.lbl_state)
        g.addStretch(1)
        self.lbl_stat = QLabel("成功: 0   失败: 0")
        self.lbl_stat.setObjectName("Muted")
        g.addWidget(self.lbl_stat)
        card.body_lay.addLayout(g)
        return card

    def _refresh_ports(self):
        from instrument_hub.serial_ports import enumerate_ports
        try:
            names = enumerate_ports()
        except Exception:
            names = []
        cur = self.cmb_port.currentText().strip()
        self.cmb_port.blockSignals(True)
        self.cmb_port.clear()
        self.cmb_port.addItems(names or ["COM3", "COM4", "COM5"])
        if cur in names:
            self.cmb_port.setCurrentText(cur)
        self.cmb_port.blockSignals(False)

    def _on_trace_toggled(self, checked):
        self._trace_on = bool(checked)

    # ---------------------------------------------------------- 实时读值
    def _build_read_card(self) -> Card:
        card = Card("实时读值", "电阻值：整数寄存器 0（UShort）+ 浮点寄存器 2048~2049（IEEE754）")
        grid = QGridLayout()
        grid.setSpacing(8)

        cap1 = QLabel("电阻值（整数 · 寄存器 0）")
        cap1.setObjectName("Muted")
        grid.addWidget(cap1, 0, 0)
        self.lbl_res_int = QLabel("--")
        self.lbl_res_int.setStyleSheet("font-size:32px; font-weight:800; color:#2563EB;")
        grid.addWidget(self.lbl_res_int, 0, 1)
        grid.addWidget(QLabel("Ω"), 0, 2)

        cap2 = QLabel("电阻值（Float · 寄存器 2048）")
        cap2.setObjectName("Muted")
        grid.addWidget(cap2, 1, 0)
        self.lbl_res_float = QLabel("--")
        self.lbl_res_float.setStyleSheet("font-size:32px; font-weight:800; color:#2563EB;")
        grid.addWidget(self.lbl_res_float, 1, 1)
        grid.addWidget(QLabel("Ω"), 1, 2)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_poll = QPushButton("开始轮询")
        self.btn_poll.setMinimumHeight(30)
        self.btn_poll.setProperty("selfStyled", True)
        self.btn_poll.setStyleSheet(self._POLL_OFF_QSS)
        self.btn_poll.clicked.connect(self._toggle_poll)
        row.addWidget(self.btn_poll)
        self.lbl_interval = QLabel("间隔(ms)")
        self.lbl_interval.setObjectName("Muted")
        row.addWidget(self.lbl_interval)
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(100, 10000)
        self.sp_interval.setValue(500)
        self.sp_interval.setFixedWidth(80)
        row.addWidget(self.sp_interval)
        row.addStretch(1)
        grid.addLayout(row, 2, 0, 1, 3)

        card.body_lay.addLayout(grid)
        card.body_lay.addStretch(1)
        return card

    # ---------------------------------------------------------- 参数读写
    def _build_param_card(self) -> Card:
        card = Card("RS485 参数读写", "修改参数前自动先写寄存器 7166=0xCCAA 打开许可")
        card.body_lay.setSpacing(8)

        self.lbl_addr_now = QLabel("地址：--")
        self.lbl_addr_now.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_addr_now)
        self.lbl_baud_now = QLabel("波特率：--")
        self.lbl_baud_now.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_baud_now)
        self.lbl_fmt_now = QLabel("数据格式：--")
        self.lbl_fmt_now.setObjectName("Muted")
        card.body_lay.addWidget(self.lbl_fmt_now)

        self.btn_read_param = QPushButton("读取当前参数")
        self.btn_read_param.setMinimumHeight(30)
        self.btn_read_param.clicked.connect(self._read_params)
        card.body_lay.addWidget(self.btn_read_param)

        # 分隔
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#E5E7EB;")
        card.body_lay.addWidget(line)

        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel("新地址"), 0, 0)
        self.e_new_addr = QLineEdit()
        self.e_new_addr.setPlaceholderText("1~247")
        self.e_new_addr.setFixedWidth(80)
        grid.addWidget(self.e_new_addr, 0, 1)
        self.btn_set_addr = QPushButton("写入")
        self.btn_set_addr.setMinimumHeight(30)
        self.btn_set_addr.clicked.connect(self._set_addr)
        grid.addWidget(self.btn_set_addr, 0, 2)

        grid.addWidget(QLabel("新波特率"), 1, 0)
        self.cmb_new_baud = QComboBox()
        for b in BAUD_MAP.values():
            self.cmb_new_baud.addItem(str(b))
        self.cmb_new_baud.setCurrentText("9600")
        grid.addWidget(self.cmb_new_baud, 1, 1)
        self.btn_set_baud = QPushButton("写入")
        self.btn_set_baud.setMinimumHeight(30)
        self.btn_set_baud.clicked.connect(self._set_baud)
        grid.addWidget(self.btn_set_baud, 1, 2)

        grid.addWidget(QLabel("数据格式"), 2, 0)
        self.cmb_new_fmt = QComboBox()
        for i, name in FMT_MAP.items():
            self.cmb_new_fmt.addItem(name, i)
        grid.addWidget(self.cmb_new_fmt, 2, 1, 1, 2)
        self.btn_set_fmt = QPushButton("写入数据格式")
        self.btn_set_fmt.setMinimumHeight(30)
        self.btn_set_fmt.clicked.connect(self._set_fmt)
        grid.addWidget(self.btn_set_fmt, 3, 0, 1, 3)

        card.body_lay.addLayout(grid)

        self.lbl_rw = QLabel("")
        self.lbl_rw.setObjectName("Muted")
        self.lbl_rw.setWordWrap(True)
        card.body_lay.addWidget(self.lbl_rw)
        return card

    # ---------------------------------------------------------- 手动发帧
    def _build_raw_card(self) -> Card:
        card = Card("手动发帧", "十六进制，空格分隔，自动补 CRC（如 01 03 00 00 00 01）")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.e_raw = QLineEdit()
        self.e_raw.setPlaceholderText("01 03 00 00 00 01")
        self.e_raw.setStyleSheet("QLineEdit{font-family:Consolas; font-size:12px;}")
        row.addWidget(self.e_raw, 1)
        self.btn_send = QPushButton("发送")
        self.btn_send.setMinimumHeight(30)
        self.btn_send.clicked.connect(self._send_raw)
        row.addWidget(self.btn_send)
        self.btn_clear = QPushButton("清空日志")
        self.btn_clear.setMinimumHeight(30)
        self.btn_clear.clicked.connect(self._clear_log)
        row.addWidget(self.btn_clear)
        card.body_lay.addLayout(row)
        return card

    # ---------------------------------------------------------- 通讯日志
    def _build_log_group(self) -> QGroupBox:
        grp = QGroupBox("报文日志（TX 发送 / RX 接收）")
        grp.setMinimumHeight(150)
        v = QVBoxLayout(grp)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(3000)
        self.txt_log.setStyleSheet("QPlainTextEdit{font-family:Consolas; font-size:11px;"
                                   "background:#0F172A; color:#A5B4FC;}")
        v.addWidget(self.txt_log)
        return grp

    # ---------------------------------------------------------- 连接
    def _on_connect(self):
        if self._ser is not None:
            return
        port = self.cmb_port.currentText().strip()
        if not port:
            QMessageBox.warning(self, "提示", "未选择串口")
            return
        try:
            import serial
            baud = int(self.cmb_baud.currentText())
            parity = self.cmb_parity.currentText()
            self._ser = serial.Serial(port=port, baudrate=baud, parity=parity,
                                      bytesize=8, stopbits=1, timeout=0.2)
        except Exception as e:
            QMessageBox.critical(self, "连接失败", str(e))
            return
        self._addr = self.sp_addr.value()
        self.btn_conn.setEnabled(False)
        self.btn_conn.setText("已连接")
        self.btn_conn.setObjectName("btnConnected")
        self.btn_disc.setEnabled(True)
        self.lbl_state.setText("已连接")
        self._log("INFO", "串口已打开：%s %d %s 8 1" % (port, int(self.cmb_baud.currentText()),
                                                        self.cmb_parity.currentText()))

    def _on_disconnect(self):
        self._set_polling(False)
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("连接")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_disc.setEnabled(False)
        self.lbl_state.setText("未连接")
        self._log("INFO", "串口已关闭")

    # ---------------------------------------------------------- 轮询
    def _toggle_poll(self):
        if self._polling:
            self._set_polling(False)
            return
        if self._ser is None:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        self._addr = self.sp_addr.value()
        self._set_polling(True)

    def _set_polling(self, on):
        on = bool(on) and self._ser is not None
        self._polling = on
        self.btn_poll.setStyleSheet(self._POLL_ON_QSS if on else self._POLL_OFF_QSS)
        self.btn_poll.setText("停止轮询" if on else "开始轮询")
        if on:
            self._poll_once()

    def _poll_once(self):
        if not (self._polling and self._ser is not None):
            return
        if self._inflight:
            QTimer.singleShot(50, self._poll_once)
            return
        self._inflight = True
        ser = self._ser
        addr = self._addr

        def work():
            try:
                iv = self._transact(ser, addr, read_regs(addr, REG_RES_INT, 1, 0x03))
                time.sleep(0.02)
                fv = self._transact(ser, addr, read_regs(addr, REG_RES_FLOAT, 2, 0x03))
                int_val = None
                float_val = None
                if iv and check_frame(iv) and not parse_exception(iv) and len(iv) >= 5:
                    int_val = u16(iv, 3)
                if fv and check_frame(fv) and not parse_exception(fv) and len(fv) >= 7:
                    float_val = f32_abcd(fv, 3)
                self.sig_res.emit((int_val, float_val))
            except Exception:
                self.sig_res.emit(None)
            finally:
                self._inflight = False
                if self._polling:
                    QTimer.singleShot(self.sp_interval.value(), self._poll_once)

        threading.Thread(target=work, daemon=True).start()

    def _transact(self, ser, addr, frame):
        """串口收一帧。带锁避免并发写。"""
        with self._tx_lock:
            ser.reset_input_buffer()
            ser.write(frame)
        if self._trace_on:
            self.sig_log.emit("TX", ">> " + _hexs(frame))
        resp = self._read_frame(ser)
        if resp and self._trace_on:
            self.sig_log.emit("RX", "<< " + _hexs(resp))
        return resp

    @staticmethod
    def _read_frame(ser, timeout=0.3):
        deadline = time.time() + timeout
        buf = bytearray()
        while time.time() < deadline:
            c = ser.read(1)
            if not c:
                if buf:
                    break
                continue
            buf += c
            if len(buf) >= 2:
                func = buf[1]
                if func & 0x80:
                    need = 5
                elif func in (0x01, 0x02, 0x03, 0x04):
                    if len(buf) < 3:
                        continue
                    need = 5 + buf[2]
                elif func in (0x05, 0x06, 0x0F, 0x10):
                    need = 8
                else:
                    need = 5
                if len(buf) >= need:
                    return bytes(buf[:need])
        return bytes(buf) if buf else None

    # ---------------------------------------------------------- 参数读写
    def _on_res(self, payload):
        from instrument_hub.comm_state import mark_ok, mark_lost
        if payload is None:
            mark_lost(self)
            self._fail += 1
            self._update_stat()
            return
        mark_ok(self)
        self._ok += 1
        self._update_stat()
        int_val, float_val = payload
        self.lbl_res_int.setText(str(int_val) if int_val is not None else "--")
        self.lbl_res_float.setText("%.2f" % float_val if float_val is not None else "--")

    def _update_stat(self):
        self.lbl_stat.setText("成功: %d   失败: %d" % (self._ok, self._fail))

    def _require_ser(self):
        if self._ser is None:
            QMessageBox.warning(self, "提示", "请先连接")
            return False
        return True

    def _run_tx(self, frame, on_done):
        """后台发一帧，回调 on_done(resp_or_None, err)。"""
        if not self._require_ser():
            return
        ser = self._ser
        addr = self.sp_addr.value()

        def work():
            try:
                resp = self._transact(ser, addr, frame)
                on_done(resp, None)
            except Exception as e:
                on_done(None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _read_params(self):
        if not self._require_ser():
            return
        addr = self.sp_addr.value()
        frame = read_regs(addr, REG_ADDR, 3, 0x03)

        def done(resp, err):
            if err:
                self.sig_param.emit("读取参数失败：%s" % err)
            elif resp is None:
                self.sig_param.emit("读取参数无响应")
            else:
                exc = parse_exception(resp)
                if exc:
                    self.sig_param.emit("异常：%s" % exc)
                elif len(resp) < 9:
                    self.sig_param.emit("参数响应长度异常")
                else:
                    a = u16(resp, 3)
                    b = u16(resp, 5)
                    f = u16(resp, 7)
                    self.sig_param.emit("OK|%d|%d|%d" % (a, b, f))
        self._run_tx(frame, done)

    def _on_param(self, text):
        if text.startswith("OK|"):
            _, a, b, f = text.split("|")
            a, b, f = int(a), int(b), int(f)
            self.lbl_addr_now.setText("地址：%d" % a)
            self.lbl_baud_now.setText("波特率：%s (代码%d)" % (BAUD_MAP.get(b, "未知"), b))
            self.lbl_fmt_now.setText("数据格式：%s (代码%d)" % (FMT_MAP.get(f, "未知"), f))
            self.lbl_rw.setText("参数读取成功")
        else:
            self.lbl_rw.setText(text)

    def _write_param(self, reg, value, label):
        if not self._require_ser():
            return
        addr = self.sp_addr.value()
        # 先写许可（7166=0xCCAA），再写参数，串成一次后台事务
        f_allow = write_single_reg(addr, REG_ALLOW, ALLOW_VALUE)
        f_param = write_single_reg(addr, reg, value)

        def work():
            try:
                ser = self._ser
                r1 = self._transact(ser, addr, f_allow)
                time.sleep(0.05)
                r2 = self._transact(ser, addr, f_param)
                self.sig_write.emit("OK|%s" % label)
            except Exception as e:
                self.sig_write.emit("ERR|%s" % e)

        self.lbl_rw.setText("正在写入 %s …" % label)
        threading.Thread(target=work, daemon=True).start()

    def _on_write(self, text):
        if text.startswith("OK|"):
            self.lbl_rw.setText("%s 写入成功，请重新读取参数确认" % text[3:])
            self._log("INFO", "%s 写入成功" % text[3:])
        else:
            self.lbl_rw.setText("写入失败：%s" % text[4:])
            self._log("ERR", "写入失败：%s" % text[4:])

    def _set_addr(self):
        try:
            v = int(self.e_new_addr.text())
            if not 1 <= v <= 247:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "提示", "地址应为 1~247")
            return
        if QMessageBox.question(self, "确认", "将地址改为 %d？改后需按新地址重连" % v) != QMessageBox.Yes:
            return
        self._write_param(REG_ADDR, v, "地址=%d" % v)

    def _set_baud(self):
        v = int(self.cmb_new_baud.currentText())
        code = BAUD_TO_CODE[v]
        if QMessageBox.question(self, "确认", "将波特率改为 %d？改后需按新波特率重连" % v) != QMessageBox.Yes:
            return
        self._write_param(REG_BAUD, code, "波特率=%d" % v)

    def _set_fmt(self):
        code = self.cmb_new_fmt.currentData()
        name = FMT_MAP.get(code, "未知")
        if QMessageBox.question(self, "确认", "将数据格式改为 %s？" % name) != QMessageBox.Yes:
            return
        self._write_param(REG_FMT, code, "数据格式=%s" % name)

    # ---------------------------------------------------------- 手动发帧
    def _send_raw(self):
        if not self._require_ser():
            return
        s = self.e_raw.text().strip()
        try:
            data = bytes(int(x, 16) for x in s.split())
        except ValueError:
            QMessageBox.warning(self, "提示", "格式错误：应填十六进制，空格分隔，如 01 03 00 00 00 01")
            return
        if len(data) < 2:
            QMessageBox.warning(self, "提示", "至少需要地址+功能码两个字节")
            return
        frame = build_frame(data[0], data[1], data[2:])

        def done(resp, err):
            if err:
                self.lbl_rw.setText("发送失败：%s" % err)
            elif resp is None:
                self.lbl_rw.setText("无响应")
            else:
                exc = parse_exception(resp)
                self.lbl_rw.setText("异常：%s" % exc if exc else "操作成功，响应：%s" % _hexs(resp))
        self._run_tx(frame, done)

    # ---------------------------------------------------------- 日志
    def _append_log(self, direction, text):
        colors = {"TX": "#4FC3F7", "RX": "#81C784", "WARN": "#FFD54F",
                  "ERR": "#EF5350", "INFO": "#A5B4FC"}
        color = colors.get(direction, "#A5B4FC")
        self.txt_log.appendHtml(
            '<span style="color:%s">[%s] %s</span>' % (color, direction, text))
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _log(self, direction, text):
        self.sig_log.emit(direction, text)

    def _clear_log(self):
        self.txt_log.clear()

    # ---------------------------------------------------------- 退出闭环
    def shutdown(self):
        self._set_polling(False)
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
