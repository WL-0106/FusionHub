# -*- coding: utf-8 -*-
"""AN9637HC 模拟器（假仪器）——没有真机也能把上位机跑通。

用法：
    python simulator.py                 # 监听 TCP 127.0.0.1:5020
    python simulator.py --port 5020
    python simulator.py --serial COM9   # 作为真实串口设备（需另一端口或回环线接电脑）

实现的是 SE 协议子集：档案管理 / 追加四种测试步 / 设置与查询参数 / 启动停止 / 查结果。
说明：本模拟器的 TD? / RD? 返回格式是「模拟器专用」，仅用于演示上位机如何展示结果；
真机的 TD? 原始格式以手册为准，上位机对真机一律原样展示 + 尽力解析。
"""

import sys
import socket
import threading
import time
import random

from . import protocol as P

# 系统参数按 set_cmd 索引（get_cmd = set_cmd + "?"）
_SYS_PARAMS = {p.set_cmd: p for p in P.SYSTEM_PARAMS}


class FakeAN96HC:
    def __init__(self):
        self.files = {}          # num(str) -> {"name":..., "steps":[...]}
        self.work_file = "01"
        self.files["01"] = {"name": "DEFAULT", "steps": []}
        self.cur_step = -1       # 当前步索引（最近追加的）
        self.sys_params = {}     # 系统参数（与测试步无关）
        self.testing = False
        self.lock = threading.Lock()

    # ---- 内部 ----
    def _mode_of_cur(self):
        if 0 <= self.cur_step < len(self.files[self.work_file]["steps"]):
            return self.files[self.work_file]["steps"][self.cur_step]["mode"]
        return None

    def _find_param(self, mode, cmd):
        for p in P.MODES[mode]["params"]:
            if p.set_cmd == cmd:
                return p
        return None

    def _fmt_stored(self, param: P.Param, val):
        if param.kind == "scanner":
            return val
        if param.kind == "enum":
            return str(int(val))
        if param.kind == "int":
            return str(int(val))
        return P._fmt_num(float(val))

    # ---- 命令处理：返回 (kind, payload) ----
    #   kind: 'ACK' / 'NAK' / 'DATA'
    def handle(self, line: str):
        line = line.strip()
        if not line:
            return ("ACK", "")
        # 容忍可选的地址前缀（1~3 位数字），SE 协议本身不带
        head = line
        while head and head[0].isdigit() and len(head) > 1:
            # 仅当整段像 "01EV 2500" 这类才剥离；稳妥起见只在首个字母前剥离数字
            idx = 0
            while idx < len(head) and head[idx].isdigit():
                idx += 1
            # 若数字后紧跟字母命令，则视为地址前缀
            if idx > 0 and idx < len(head) and head[idx].isalpha():
                head = head[idx:]
            break
        up = head.upper()
        if up.startswith("*IDN?"):
            # 忠实真机：SE 协议仪器对 *IDN? 回 NAK（或不响应）——
            # 真机日志实证 b'\x15\n'；上位机靠查询命令兜底判活、探测步类型补上下文。
            return ("NAK", "")
        if up == "TEST":
            with self.lock:
                self.testing = True
                self._gen_results()
            return ("ACK", "")
        if up == "RESET":
            with self.lock:
                self.testing = False
            return ("ACK", "")
        if up == "SAO":
            return ("ACK", "")
        if up == "LF?":
            with self.lock:
                f = self.files[self.work_file]
                return ("DATA", "%s,%s" % (self.work_file, f["name"]))
        if up == "ST?":
            with self.lock:
                return ("DATA", str(len(self.files[self.work_file]["steps"])))
        if up == "TD?":
            with self.lock:
                return ("DATA", self._td())
        if up == "FS":
            return ("ACK", "")
        if up == "FD":
            with self.lock:
                self.files.pop(self.work_file, None)
                self.work_file = "01"
                self.files.setdefault("01", {"name": "DEFAULT", "steps": []})
                self.cur_step = -1
            return ("ACK", "")
        if up.startswith("FN "):
            parts = head[3:].split(",", 1)
            num = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else "FILE%s" % num
            with self.lock:
                self.files[num] = {"name": name, "steps": []}
                self.work_file = num
                self.cur_step = -1
            return ("ACK", "")
        if up.startswith("FL "):
            num = head[3:].strip()
            with self.lock:
                self.files.setdefault(num, {"name": "FILE%s" % num, "steps": []})
                self.work_file = num
                self.cur_step = -1
            return ("ACK", "")
        if up.startswith("FSA "):
            parts = head[4:].split(",", 1)
            num = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else "FILE%s" % num
            with self.lock:
                self.files[num] = {"name": name,
                                   "steps": list(self.files[self.work_file]["steps"])}
            return ("ACK", "")
        if up.startswith("SD "):
            num = head[3:].strip()
            with self.lock:
                try:
                    self.files[self.work_file]["steps"].pop(int(num) - 1)
                    self.cur_step = len(self.files[self.work_file]["steps"]) - 1
                except Exception:
                    return ("NAK", "")
            return ("ACK", "")
        if up in ("SAA", "SAD", "SAI", "SAG"):
            mode = {"SAA": "ACW", "SAD": "DCW", "SAI": "IR", "SAG": "GND"}[up]
            with self.lock:
                # 真机实证（2.43.2 现场）：追加命令只把空步加到档案末尾，
                # 仪器屏幕不会自动切到新步——参数命令仍写「屏幕当前编辑步」。
                # 因此这里刻意不更新 cur_step（cur_step 模拟的就是屏幕焦点）。
                self.files[self.work_file]["steps"].append(
                    {"mode": mode, "params": {}, "result": None})
            return ("ACK", "")
        if up.startswith("RD "):
            num = head[3:].strip().rstrip("?").strip()
            with self.lock:
                steps = self.files[self.work_file]["steps"]
                if num.isdigit() and 0 < int(num) <= len(steps):
                    return ("DATA", self._step_result(int(num) - 1))
            return ("NAK", "")
        # 参数 setter / getter
        if " " in head:
            cmd, arg = head.split(" ", 1)
        else:
            cmd, arg = head, ""
        cmd = cmd.upper()
        # 系统参数（SBR/SLA/SCT/SAL/SF/SPR）：与测试步无关，独立存储——
        # 不能落入下面的「按当前步类型解释」分支（真机系统参数与步解耦）
        if cmd.endswith("?"):
            sp = _SYS_PARAMS.get(cmd[:-1])
            if sp is not None:
                with self.lock:
                    stored = self.sys_params.get(sp.set_cmd)
                    return ("DATA", self._fmt_stored(
                        sp, stored if stored is not None else sp.default))
        else:
            sp = _SYS_PARAMS.get(cmd)
            if sp is not None:
                try:
                    norm = P.validate(sp, arg)
                except P.ProtocolError:
                    return ("NAK", "")
                with self.lock:
                    self.sys_params[cmd] = norm
                return ("ACK", "")
        if cmd.endswith("?"):
            # getter
            base = cmd[:-1]
            with self.lock:
                mode = self._mode_of_cur()
                if mode is None:
                    return ("NAK", "")
                p = self._find_param(mode, base)
                if p is None:
                    return ("NAK", "")
                stored = self.files[self.work_file]["steps"][self.cur_step]["params"].get(base)
                if stored is None:
                    return ("DATA", self._fmt_stored(p, p.default))
                return ("DATA", self._fmt_stored(p, stored))
        else:
            # setter
            with self.lock:
                mode = self._mode_of_cur()
                if mode is None:
                    return ("NAK", "")
                p = self._find_param(mode, cmd)
                if p is None:
                    return ("NAK", "")
                try:
                    norm = P.validate(p, arg)
                except P.ProtocolError:
                    return ("NAK", "")
                self.files[self.work_file]["steps"][self.cur_step]["params"][cmd] = norm
            return ("ACK", "")
        return ("NAK", "")

    # ---- 结果生成（模拟器专用） ----
    def _gen_results(self):
        for st in self.files[self.work_file]["steps"]:
            mode = st["mode"]
            pr = st["params"]
            if mode == "GND":
                cur = pr.get("EC", 25.0)
                hi = pr.get("EH", 100.0)
                meas = round(hi * 0.48, 1)        # 远低于上限 -> PASS
                st["result"] = ("PASS", "%sA %smΩ" % (P._fmt_num(cur), P._fmt_num(meas)))
            elif mode == "IR":
                hi = pr.get("EH", 2000.0)
                meas = round(hi * 1.5, 1)
                st["result"] = ("PASS", "%sMΩ" % P._fmt_num(meas))
            else:  # ACW / DCW
                hi = pr.get("EHT", pr.get("EH", 25.0))
                meas = round(hi * 0.09, 3)
                unit = "mA" if mode == "ACW" else "uA"
                st["result"] = ("PASS", "%s%s" % (P._fmt_num(meas), unit))

    def _step_result(self, idx):
        st = self.files[self.work_file]["steps"][idx]
        r = st.get("result") or ("-", "")
        return "STEP %02d %s %s %s" % (idx + 1, st["mode"], r[1], r[0])

    def _td(self):
        lines = []
        for i, st in enumerate(self.files[self.work_file]["steps"]):
            r = st.get("result") or ("-", "")
            lines.append("STEP %02d %s %s %s" % (i + 1, st["mode"], r[1], r[0]))
        return "\n".join(lines) if lines else "(无测试步)"


def _conn_loop(conn, eng: FakeAN96HC):
    conn.settimeout(0.2)
    buf = b""
    try:
        while True:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.rstrip(b"\r")
                try:
                    resp = eng.handle(line.decode("ascii", "replace"))
                except Exception as ex:
                    print("[simulator] 处理指令异常 %r: %s" % (line, ex))
                    resp = ("NAK", "")
                if resp[0] == "ACK":
                    conn.sendall(b"\x06\x0a")
                elif resp[0] == "NAK":
                    conn.sendall(b"\x15\x0a")
                else:
                    conn.sendall((resp[1] + "\n").encode("utf-8"))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve_tcp(host="127.0.0.1", port=5020):
    eng = FakeAN96HC()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Windows 的 SO_REUSEADDR 语义与 Linux 不同：它允许「抢占」已被占用的端口，
    # 于是两个进程会同时 listen 同一端口——后启动的以为绑成功了，实际新连接
    # 被前一个（可能已卡死的）进程接走，现象是「能连上，但每条指令都返回 0 字节」，
    # 极难排查。Windows 下必须用 SO_EXCLUSIVEADDRUSE 独占端口，被占用就直接报错。
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((host, port))
    except OSError as e:
        print("[simulator] 端口 %d 已被占用（%s）。换个端口：python simulator.py --port <端口>"
              % (port, e))
        raise
    srv.listen(5)
    print("[simulator] SE 协议模拟器已启动 TCP %s:%d，等待连接… (Ctrl+C 退出)"
          % (host, port))
    try:
        while True:
            conn, addr = srv.accept()
            print("[simulator] 客户端接入:", addr)
            threading.Thread(target=_conn_loop, args=(conn, eng), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[simulator] 已退出")


def main():
    port = 5020
    host = "127.0.0.1"
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    if "--host" in sys.argv:
        host = sys.argv[sys.argv.index("--host") + 1]
    serve_tcp(host, port)


if __name__ == "__main__":
    main()
