# -*- coding: utf-8 -*-
"""
网段 Ping 扫描助手 (Ping Net Assistant)  v2.2
================================================
一个用来快速搜索网段内在线 IP 的小工具。

支持的目标写法（输入框里可以混着写，用空格/逗号/分号/换行分隔）：
    192.168.1.100                       单个 IP
    192.168.1.1-192.168.1.254           起止范围
    192.168.1.10-50                     同网段简写范围
    192.168.1.0/24                      整个网段（CIDR，自动排除网络号/广播地址）
    192.168.1.*    或  192.168.1.       整个 C 段（.1 ~ .254）
    10.0.0.1-10.0.0.5, 172.16.0.0/28    多网段批量

功能：
    - 多线程并发 ping，扫描速度快（254 个地址通常 2~4 秒）
    - 开启 DPI 感知，系统缩放 125% / 150% 下界面依然清晰不发虚；
      窗口初始大小按屏幕工作区自适应，保证底部图例和统计不会被任务栏挡住
    - 地址显示区：按 C 段把 0~255 的尾码画成格子图，用颜色直观表示每个地址的
      在线 / 离线 / 待扫描状态，鼠标移上去看详细结果（延迟、TTL、主机名、MAC）
    - 结果明细表（表头可点排序）默认收起，点「显示明细表」展开
    - 目标框下面**常驻「写法总览」**：6 类写法各给例子和展开数量；
      点「格式说明」还有一张详表（每种写法 + 例子 + 展开多少个地址
      + 掩码位数对照 + 注意事项），数据源就是文件开头的 INPUT_FORMATS
    - 按钮按操作分组上了不同颜色（开始=蓝 / 停止=红 / 导出=绿·青 / 复制=紫 …），
      一目了然好找
    - 「本机 IP」直接读电脑自己的地址列出来，可单选 / 多选（Ctrl、Shift），
      双击某一行直接把该网段填进目标框（多选则全部填入）
    - 「仅显示在线 IP」按钮：主区切成在线设备列表，只列在线的，
      设备名称按常用设备表自动填，双击可手写、随导出一起走，IP 按数值大小排序；
      双击「设备名称」那一格可以手写名字，回车保存，导出设备表时跟着一起走
    - 支持随时停止
    - 「导出设备表」：只导在线设备，三列（设备名称 / IP地址/串口 / 备注），
      直接生成 .xlsx（手写 Office 包，不依赖第三方库），也可存成 CSV
    - 「出口网卡」一列：写清每个地址**实际**是从哪块网卡出去的（有线 · 以太网 /
      WiFi · WLAN），用来区分「网线 ping 到的」和「WiFi ping 到的」。
      判定直接问系统（GetBestInterface + GetIfEntry），**不是**自己算路由表最长前缀 ——
      本机实测两者结论会不一致：192.168.6.0/24 明明有条指向有线网卡的直连路由，
      Windows 真正发包时却走无线网卡，结果就是「关掉 WiFi 这些设备全没了」。
      不是直连、绕网关出去的会标「（经默认网关）」，一眼能看出不在本机网线上
    - 「只看网线直连」：勾上后结果明细 / 在线列表 / **地址图** / 导出都只保留真在网线上的
      地址，经无线网卡（默认网关）绕进来的直接隐藏（地址图里这种格子画成「已隐藏」灰，
      不再亮成在线绿）；状态栏永远会告诉你隐藏了几个。
      **v2.1 起默认就是勾上的**（老配置会自动迁移一次），因为「经 WiFi 绕进来的设备
      关掉 WiFi 就搜不到」容易让人误以为是自己网线上的设备。要重新看见它们，
      把这个勾去掉即可，取消状态会记进配置。
      （v2.2 修正：此前地址图没有吃这个过滤，导致明细表已隐藏、顶部地址图里仍亮绿点）
    - 「导出详细结果」：全部地址的完整字段 CSV
    - 「复制在线 IP」：一行一个，方便贴到别处
    - 自动记忆上次的配置（含手写的设备名称）

运行环境：Windows + Python 3.8+（自带 tkinter）
启动方式：双击同目录 start_ping_assistant.bat，或命令行 python ping_net_assistant.py
打包成独立 exe（目标机器无需装 Python）：
    pyinstaller --noconfirm --clean --onefile --windowed --name PingNetAssistant ping_net_assistant.py
打包后配置会写在 exe 旁边（整个文件夹拷走即可带着走）；exe 旁边不可写时自动退到
%APPDATA%\\PingNetAssistant\\。
"""

from __future__ import annotations

import csv
import ctypes
import ipaddress
import json
import locale
import os
import platform
import queue
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "网段 Ping 扫描助手  v2.2"
IS_WIN = platform.system().lower().startswith("win")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


def _enable_dpi_awareness():
    """开启 DPI 感知。

    不开的话，Windows 会把整个窗口当位图整体放大（系统缩放 125% 就拉伸 1.25 倍），
    界面上的字和线条全部发虚。开启后 Tk 直接按物理像素绘制，界面是清晰的。
    """
    if not IS_WIN:
        return False
    try:                                    # Win8.1+：按主显示器 DPI
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return True
    except Exception:
        pass
    try:                                    # 老系统的退路
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


# 必须在创建 Tk 窗口之前调用
DPI_AWARE = _enable_dpi_awareness()

# 一次最多展开多少个目标，防止手滑输入 0.0.0.0/0 把程序跑死
MAX_TARGETS = 65536

IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_TIME_RE = re.compile(r"(?:time|时间)\s*([=<])\s*(\d+(?:\.\d+)?)\s*ms", re.I)
_TTL_RE = re.compile(r"ttl\s*=\s*(\d+)", re.I)
# ping 的回显应答和出错提示是同一种句式：「来自 <地址> 的回复」「Reply from <地址>」，
# 所以判定在线时还要看这一行有没有 TTL=，以及这个地址是不是目标自己
_REPLY_FROM_RE = re.compile(r"(?:来自|from)\s*(\d{1,3}(?:\.\d{1,3}){3})", re.I)
_MAC_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-f]{2}(?:[-:][0-9a-f]{2}){5})", re.I)

def _base_dir():
    """程序所在目录。

    打包成 exe 后 `__file__` 指向 PyInstaller 的临时解包目录（每次启动都变），
    所以要改用 `sys.executable`（就是 exe 自己）；源码运行时用脚本所在目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _config_path():
    """配置文件位置。

    优先放程序旁边（便携：整个文件夹拷到别的机器，配置、设备名跟着走）；
    旁边不可写（例如放进 Program Files）时退回 %APPDATA%\\PingNetAssistant\\。
    """
    d = _base_dir()
    try:
        probe = os.path.join(d, ".pa_write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
        return os.path.join(d, ".ping_assistant.json")
    except Exception:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        dd = os.path.join(base, "PingNetAssistant")
        try:
            os.makedirs(dd, exist_ok=True)
        except Exception:
            pass
        return os.path.join(dd, ".ping_assistant.json")


CONFIG_PATH = _config_path()

# 配置文件结构版本。老配置（没有这个键）里 wired_only=False 是「旧默认值」，
# 不是用户主动取消 —— 升到 v2.1 后「只看网线直连」默认勾上，老配置要按新默认重设一次。
CFG_VERSION = 2


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def _decode(raw: bytes) -> str:
    """Windows 命令行输出在中文系统上是 GBK，这里做一次兼容解码。"""
    if raw is None:
        return ""
    for enc in ("gbk", "utf-8", "cp936", locale.getpreferredencoding(False) or "utf-8"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def run_cmd(args, timeout: float = 6.0):
    """执行外部命令，返回 (returncode, 输出文本)，不弹黑框。"""
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    if IS_WIN:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        p = subprocess.run(args, timeout=timeout, **kwargs)
        return p.returncode, _decode(p.stdout)
    except subprocess.TimeoutExpired as e:
        return 124, _decode(getattr(e, "stdout", b""))
    except Exception as e:  # 命令不存在等
        return -1, str(e)


# --------------------------------------------------------------------------
# 目标解析
# --------------------------------------------------------------------------
def expand_spec(spec: str):
    """把单条规则展开成 IP 字符串列表。"""
    spec = spec.strip().strip(",")
    if not spec:
        return []

    # 1) CIDR：192.168.1.0/24
    if "/" in spec:
        net = ipaddress.ip_network(spec, strict=False)
        if net.num_addresses > MAX_TARGETS:
            raise ValueError(
                "网段 %s 包含 %d 个地址，超过单次上限 %d。请拆分后再扫。"
                % (spec, net.num_addresses, MAX_TARGETS)
            )
        hosts = list(net.hosts())
        if not hosts:  # /31、/32 的兜底
            hosts = [net.network_address]
        return [str(h) for h in hosts]

    # 2) 完整起止范围：192.168.1.1-192.168.1.254
    m = re.match(r"^(\d{1,3}(?:\.\d{1,3}){3})\s*-\s*(\d{1,3}(?:\.\d{1,3}){3})$", spec)
    if m:
        start = int(ipaddress.IPv4Address(m.group(1)))
        end = int(ipaddress.IPv4Address(m.group(2)))
        if end < start:
            start, end = end, start
        if end - start + 1 > MAX_TARGETS:
            raise ValueError("范围 %s 地址数超过 %d，请拆分后再扫。" % (spec, MAX_TARGETS))
        return [str(ipaddress.IPv4Address(i)) for i in range(start, end + 1)]

    # 3) 同网段简写范围：192.168.1.10-50
    m = re.match(r"^(\d{1,3}(?:\.\d{1,3}){2})\.(\d{1,3})\s*-\s*(\d{1,3})$", spec)
    if m:
        base, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        if b < a:
            a, b = b, a
        return ["%s.%d" % (base, i) for i in range(a, b + 1)]

    # 4) 通配符：192.168.1.*  /  192.168.1.
    if spec.endswith("*") or spec.endswith("."):
        prefix = spec.rstrip("*.")
        parts = prefix.split(".")
        if len(parts) == 3:
            return ["%s.%d" % (prefix, i) for i in range(1, 255)]
        if len(parts) == 2:
            out = []
            for i in range(256):
                for j in range(1, 255):
                    out.append("%s.%d.%d" % (prefix, i, j))
            return out
        if len(parts) == 1:
            raise ValueError("请写清网段，例如 192.168.1.0/24 或 192.168.1.*")

    # 5) 单个 IP
    return [spec]


def parse_targets(text: str):
    """解析整段输入，返回 (ip 列表, 错误信息)。"""
    tokens = [t for t in re.split(r"[\s,;、]+", (text or "").strip()) if t]
    if not tokens:
        return [], "请先填写要扫描的 IP 或网段。"

    ips, seen, errors = [], set(), []
    for t in tokens:
        try:
            for ip in expand_spec(t):
                if not IP_RE.match(ip):
                    errors.append("%s 不是合法的 IPv4 地址" % ip)
                    continue
                ipaddress.IPv4Address(ip)  # 值域校验（>255 会抛异常）
                if ip not in seen:
                    seen.add(ip)
                    ips.append(ip)
        except ValueError as e:
            msg = str(e)
            errors.append("%s → %s" % (t, msg if "上限" in msg else "格式无法识别"))
        except Exception:
            errors.append("%s → 格式无法识别" % t)

    if not ips and errors:
        return [], "\n".join(errors[:6])
    if len(ips) > MAX_TARGETS:
        return [], "共展开 %d 个目标，超过单次上限 %d，请拆分后再扫。" % (len(ips), MAX_TARGETS)
    return ips, ("\n".join(errors[:6]) if errors else None)


# --------------------------------------------------------------------------
# 探活
#
# 优先走 Windows 原生 ICMP API（iphlpapi!IcmpSendEcho）：不起子进程、不需要管理员
# 权限，几百并发也不会漏报。实测用 ping.exe 子进程时并发越高漏报越狠
# （8 并发扫出 99 台在线，100 并发只剩 5 台）。
# 非 Windows 或 API 不可用时自动回退到 ping 命令行。
# --------------------------------------------------------------------------
if IS_WIN:
    class _IP_OPTION_INFORMATION(ctypes.Structure):
        _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte),
                    ("Flags", ctypes.c_ubyte), ("OptionsSize", ctypes.c_ubyte),
                    ("OptionsData", ctypes.c_void_p)]

    class _ICMP_ECHO_REPLY(ctypes.Structure):
        _fields_ = [("Address", wintypes.ULONG), ("Status", wintypes.ULONG),
                    ("RoundTripTime", wintypes.ULONG), ("DataSize", wintypes.USHORT),
                    ("Reserved", wintypes.USHORT), ("Data", ctypes.c_void_p),
                    ("Options", _IP_OPTION_INFORMATION)]

    try:
        _iphlp = ctypes.WinDLL("iphlpapi.dll")
        _IcmpCreateFile = _iphlp.IcmpCreateFile
        _IcmpCreateFile.restype = wintypes.HANDLE
        _IcmpSendEcho = _iphlp.IcmpSendEcho
        _IcmpSendEcho.restype = wintypes.DWORD
        _IcmpSendEcho.argtypes = [
            wintypes.HANDLE, wintypes.ULONG, ctypes.c_char_p, wintypes.USHORT,
            ctypes.POINTER(_IP_OPTION_INFORMATION), ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD,
        ]
        _IcmpCloseHandle = _iphlp.IcmpCloseHandle
        _IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        _ICMP_API_OK = True
    except Exception:
        _ICMP_API_OK = False
else:
    _ICMP_API_OK = False

_ICMP_PAYLOAD = b"ping-net-assistant-payload-32b"


def _to_ipaddr(ip: str):
    """把点分地址转成 IcmpSendEcho 要的地址整数（网络字节序）。

    这里踩过大坑：IcmpSendEcho 的 DestinationAddress 要的是**网络字节序**的 ULONG，
    也就是 inet_aton 出来的 4 个字节按小端读回来的整数，而**不是** int(IPv4Address)。
    传错时系统会把地址的字节整个反过来用，程序实际打的是别人：

        192.168.1.100  -> 真的在打 100.1.168.192（公网地址）
        192.168.1.127  -> 真的在打 127.1.168.192（回环地址，本机自己应答）

    后者最坑：所有网段里以 .127 结尾的地址都会显示「在线」，而且 TTL=128、0ms。
    """
    return struct.unpack("<I", socket.inet_aton(ip))[0]


def _from_ipaddr(value: int):
    """IcmpSendEcho 返回结构体里的地址字段也是网络字节序，同样要换回来。"""
    return socket.inet_ntoa(struct.pack("<I", value & 0xFFFFFFFF))


def _icmp_ping(ip: str, timeout_ms: int):
    """用 ICMP API 探活，返回 (alive, ms, ttl)；API 不可用时返回 None 走回退。"""
    if not _ICMP_API_OK:
        return None
    handle = _IcmpCreateFile()
    if not handle or handle == 0 or handle > 2 ** 63:
        return None
    try:
        dst = _to_ipaddr(ip)
        size = ctypes.sizeof(_ICMP_ECHO_REPLY) + len(_ICMP_PAYLOAD) + 16
        buf = ctypes.create_string_buffer(size)
        opt = _IP_OPTION_INFORMATION()
        opt.Ttl = 128
        count = _IcmpSendEcho(handle, dst, _ICMP_PAYLOAD, len(_ICMP_PAYLOAD),
                              ctypes.byref(opt), buf, size, int(timeout_ms))
        if count == 0:
            return False, None, None
        rep = ctypes.cast(buf, ctypes.POINTER(_ICMP_ECHO_REPLY)).contents
        if rep.Status != 0:
            return False, None, None
        # 应答必须真的来自目标地址本身，被系统改写地址或本机回环应答的都不认
        if _from_ipaddr(rep.Address) != ip:
            return False, None, None
        return True, float(rep.RoundTripTime), int(rep.Options.Ttl)
    except Exception:
        return None
    finally:
        try:
            _IcmpCloseHandle(handle)
        except Exception:
            pass


def _ping_cli(ip: str, timeout_ms: int):
    """回退方案：调用系统 ping 命令。

    判定要苛刻：目标主机不可达时 ping 会打印
    「来自 192.168.1.102 的回复: 无法访问目标主机。」——**这也带「回复」二字，
    而且退出码还是 0**，只看退出码或只看有没有「回复」都会把不可达当在线。
    真正的回显应答一定满足两条：来源地址 == 目标地址，且这一行带 TTL=。
    """
    if IS_WIN:
        args = ["ping", "-n", "1", "-w", str(int(timeout_ms)), ip]
    else:
        args = ["ping", "-c", "1", "-W", str(max(1, int(timeout_ms / 1000))), ip]

    rc, out = run_cmd(args, timeout=timeout_ms / 1000.0 + 3.0)
    for line in out.splitlines():
        m = _REPLY_FROM_RE.search(line)
        if not m or m.group(1) != ip:
            continue
        m2 = _TTL_RE.search(line)
        if not m2:
            continue                      # 没有 TTL= 就不是回显应答（超时/不可达提示）
        ms = None
        m3 = _TIME_RE.search(line)
        if m3:
            ms = 0.4 if m3.group(1) == "<" else float(m3.group(2))
        return True, ms, int(m2.group(1))
    return False, None, None


def ping_once(ip: str, timeout_ms: int = 800):
    """探活一次，返回 (是否在线, 延迟毫秒或 None, TTL 或 None)。"""
    r = _icmp_ping(ip, timeout_ms)
    if r is not None:
        return r
    return _ping_cli(ip, timeout_ms)


def read_arp_table():
    """从系统 ARP 缓存里读 IP -> MAC（只对同一广播域内的地址有效）。"""
    table = {}
    if IS_WIN:
        rc, out = run_cmd(["arp", "-a"], 8.0)
    else:
        try:
            with open("/proc/net/arp", "r", encoding="utf-8", errors="ignore") as f:
                out = f.read()
        except Exception:
            return table
    for line in out.splitlines():
        m = _MAC_RE.match(line.strip())
        if m:
            table[m.group(1)] = m.group(2).replace("-", ":").upper()
    return table


# --------------------------------------------------------------------------
# 导出表格
#
# 为了不在程序里引入第三方依赖，这里手写一个最小的 .xlsx
# （本质就是一个 zip，里面几个固定 XML）。文本单元格用 inlineStr，
# 省掉共享字符串表，写出来 Excel / WPS 都能直接打开。
# --------------------------------------------------------------------------
def _xml_esc(v):
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def _col_letter(idx):
    """0 -> A, 25 -> Z, 26 -> AA"""
    s, idx = "", idx + 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_xlsx(path, headers, rows, sheet_name="Sheet1", widths=None):
    """写一个只有一张表、带加粗表头的 .xlsx。"""
    import zipfile

    widths = widths or [22] * len(headers)

    def cell(ref, text, style=0):
        if text is None or text == "":
            return '<c r="%s" s="%d"/>' % (ref, style)
        return ('<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                % (ref, style, _xml_esc(text)))

    body = ['<row r="1">%s</row>' % "".join(
        cell("%s1" % _col_letter(i), h, 1) for i, h in enumerate(headers))]
    for r, row in enumerate(rows, start=2):
        body.append('<row r="%d">%s</row>' % (r, "".join(
            cell("%s%d" % (_col_letter(i), r), v) for i, v in enumerate(row))))

    cols = "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>'
                   % (i + 1, i + 1, w) for i, w in enumerate(widths))
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="%s"><sheetViews><sheetView workbookViewId="0">'
             '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
             '</sheetView></sheetViews><cols>%s</cols><sheetData>%s</sheetData></worksheet>'
             % (ns, cols, "".join(body)))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>'
                   % (ns, _xml_esc(sheet_name[:31])))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="%s">'
                   '<fonts count="2">'
                   '<font><sz val="11"/><name val="微软雅黑"/></font>'
                   '<font><b/><sz val="11"/><color rgb="FF1F2328"/><name val="微软雅黑"/></font>'
                   '</fonts>'
                   '<fills count="3"><fill><patternFill patternType="none"/></fill>'
                   '<fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFEEF1F4"/>'
                   '<bgColor indexed="64"/></patternFill></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   '</styleSheet>' % ns)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def local_networks():
    """识别本机所有 IPv4 网段，返回 [(网段/掩码, 本机IP), ...]。

    一块网卡可以同时绑多个 IPv4（IP 别名，做多网段调试时很常见），此时
    ipconfig 会在同一个适配器块里列出多组「IPv4 地址 / 子网掩码」。
    只取每组的第一条会漏掉同一块网卡上其余的网段，所以要按出现顺序全部配对取出来。

    返回顺序：带默认网关的那块网卡排最前（通常就是当前真正在用的网络），其余按出现顺序。
    """
    pairs = []            # (ip, mask, 该网卡是否有默认网关)
    if IS_WIN:
        # 必须用 /all：不带 /all 时 Windows 不列出带冲突标记（复制）的地址，
        # 本机就有一条 192.168.1.101(复制)，只有 /all 才会输出。
        rc, out = run_cmd(["ipconfig", "/all"], 12.0)
        blocks = re.split(r"\r?\n(?=\S)", out)
        item_re = re.compile(
            r"(?:IPv4 地址|IPv4 Address|IP Address)[^:：]*[:：]\s*(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
            r"|(?:子网掩码|Subnet Mask)[^:：]*[:：]\s*(?P<mask>\d{1,3}(?:\.\d{1,3}){3})")
        gw_re = re.compile(r"(?:默认网关|Default Gateway)[^:：]*[:：]\s*\d{1,3}(?:\.\d{1,3}){3}")
        for blk in blocks:
            if not item_re.search(blk):
                continue
            has_gw = bool(gw_re.search(blk))
            pending = None
            for m in item_re.finditer(blk):
                if m.group("ip"):
                    pending = m.group("ip")
                elif pending:
                    pairs.append((pending, m.group("mask"), has_gw))
                    pending = None
    else:
        rc, out = run_cmd(["ip", "-4", "-o", "addr"], 8.0)
        for line in out.splitlines():
            m = re.search(r"inet\s+([0-9.]+)/(\d+)", line)
            if m:
                pairs.append((m.group(1), m.group(2), False))

    seen, primary, extra = set(), [], []
    for ip, mask, has_gw in pairs:
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue          # 回环地址 / APIPA 自动私有地址，都不是能扫的网段
        try:
            net = ipaddress.IPv4Network("%s/%s" % (ip, mask), strict=False)
        except Exception:
            continue
        if net.num_addresses <= 2 or net.prefixlen > 30:
            continue
        key = "%s/%d" % (net.network_address, net.prefixlen)
        if key in seen:
            continue
        seen.add(key)
        (primary if has_gw else extra).append((key, ip))
    return primary + extra


def local_adapters():
    """本机每个 IPv4 地址属于哪块网卡，返回 {ip: (网卡名, "有线"/"WiFi")}。

    光有路由表只能知道「从哪个接口出去」，接口是个 IP；要显示成「以太网 / WLAN」
    这种人话，还得把它们对上 ipconfig 里的适配器标题。
    标题含无线相关关键字的算 WiFi，其余（以太网、隧道、虚拟网卡…）都算有线。
    """
    out = {}
    if not IS_WIN:
        return out
    _rc, text = run_cmd(["ipconfig", "/all"], 12.0)
    ip_re = re.compile(
        r"(?:IPv4 地址|IPv4 Address|IP Address)[^:：]*[:：]\s*(\d{1,3}(?:\.\d{1,3}){3})")
    for blk in re.split(r"\r?\n(?=\S)", text):
        lines = blk.strip().splitlines()
        if not lines:
            continue
        m0 = re.match(r"^(.+?):\s*$", lines[0])
        if not m0:
            continue
        title = m0.group(1).strip()
        ips = ip_re.findall(blk)
        if not ips:
            continue
        # Windows 中文 / 英文界面的适配器前缀都剥掉，只留卡名本身
        name = re.sub(r"^(以太网适配器|无线局域网适配器|Ethernet adapter|Wireless LAN adapter)\s*",
                      "", title, flags=re.I).strip() or title
        kind = "WiFi" if re.search(r"无线|Wireless|Wi-?Fi|WLAN|802\.11", title, re.I) else "有线"
        for ip in ips:
            out[ip] = (name, kind)
    return out


def ipv4_routes():
    """读系统 IPv4 路由表，返回 [(掩码位数, 网络号整数, 出口接口IP, 网关), ...]。

    已按掩码位数从大到小排好，做最长前缀匹配时第一条命中的就是最优路由，
    和 Windows 选路的真实行为一致。
    """
    rows = []
    if IS_WIN:
        _rc, text = run_cmd(["route", "print", "-4"], 15.0)
        # 表格形如： 网络目标  网络掩码  网关  接口  跃点数 ；网关可能是「在链路上 / On-link」
        row_re = re.compile(
            r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+(\d{1,3}(?:\.\d{1,3}){3})\s+"
            r"(在链路上|On-link|[\d.]+)\s+(\d{1,3}(?:\.\d{1,3}){3})\s+\d+\s*$", re.I)
        in_tbl = False
        for line in text.splitlines():
            # 只有「永久路由」这一段才要停；表头和表体之间的 ===== 分隔线不能停，
            # 否则第一条路由都读不到。
            if re.search(r"(永久路由|Persistent Routes)", line):
                in_tbl = False
                continue
            if re.search(r"(IPv4 路由表|IPv4 Route Table)", line):
                in_tbl = True
                continue
            if not in_tbl:
                continue
            m = row_re.match(line)
            if not m:
                continue
            dest, mask, gw, iface = m.group(1), m.group(2), m.group(3), m.group(4)
            if dest.startswith(("127.", "224.")) or dest == "255.255.255.255":
                continue        # 回环 / 组播 / 广播，不是给普通目标用的路由
            try:
                net = ipaddress.IPv4Network("%s/%s" % (dest, mask), strict=False)
            except Exception:
                continue
            rows.append((net.prefixlen, int(net.network_address), iface, gw))
    else:
        _rc, text = run_cmd(["ip", "-4", "route"], 10.0)
        for line in text.splitlines():
            m = re.match(
                r"(?:default|(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d+))?)\s.*?(?:dev\s+(\S+))?", line)
            if not m or not m.group(3):
                continue
            dest, plen, dev = m.group(1), m.group(2), m.group(3)
            gw = "0.0.0.0"
            mg = re.search(r"via\s+([\d.]+)", line)
            if mg:
                gw = mg.group(1)
            if dest is None:                     # default 路由 → 0.0.0.0/0
                rows.append((0, 0, dev, gw))
                continue
            try:
                net = ipaddress.IPv4Network("%s/%s" % (dest, plen or 32), strict=False)
            except Exception:
                continue
            rows.append((net.prefixlen, int(net.network_address), dev, gw))
    rows.sort(key=lambda r: -r[0])
    return rows


# --------------------------------------------------------------------------
# 「这个目标会从哪块网卡出去」—— 必须问系统本人
#
# 踩过的大坑：原来是自己解析 route print 做最长前缀匹配，结论是
# 「192.168.6.x 全走有线网卡」。可用户把 WiFi 一关，这些在线设备全没了 ——
# 说明它们其实一直是经无线网卡（默认网关）绕进来的，那列标签在骗人。
# 指定源地址发包复核也证实：同一个目标，从有线卡发不通、换无线卡立刻通。
#
# 唯一可信的答案只能问 iphlpapi：
#     GetBestInterface(目标)  → 系统自己会用的那块网卡（ifIndex）
#     GetIfEntry(ifIndex)     → 网卡描述 + 类型（71 = 无线 802.11）
#     GetIpAddrTable()        → 每块卡上绑了哪些 (地址, 掩码)，用来分直连 / 经网关
# 全都是查表，一个包不发，扫描速度不受影响。
# --------------------------------------------------------------------------
_IF_TYPE_IEEE80211 = 71         # 无线网卡（IF_TYPE_IEEE80211）
_IF_TYPE_LOOPBACK = 24          # 回环，不参与显示
_IPHLP_READY = False


class _MIB_IFROW(ctypes.Structure):
    """GetIfEntry 返回的网卡信息（这边只用到 dwIndex / dwType / dwDescrLen / bDescr）。"""
    _fields_ = [
        ("wszName", ctypes.c_wchar * 256), ("dwIndex", wintypes.DWORD),
        ("dwType", wintypes.DWORD), ("dwMtu", wintypes.DWORD),
        ("dwSpeed", wintypes.DWORD), ("dwPhysAddrLen", wintypes.DWORD),
        ("bPhysAddr", ctypes.c_byte * 8), ("dwAdminStatus", wintypes.DWORD),
        ("dwOperStatus", wintypes.DWORD), ("dwLastChange", wintypes.DWORD),
        ("dwInOctets", wintypes.DWORD), ("dwInUcastPkts", wintypes.DWORD),
        ("dwInNUcastPkts", wintypes.DWORD), ("dwInDiscards", wintypes.DWORD),
        ("dwInErrors", wintypes.DWORD), ("dwInUnknownProtos", wintypes.DWORD),
        ("dwOutOctets", wintypes.DWORD), ("dwOutUcastPkts", wintypes.DWORD),
        ("dwOutNUcastPkts", wintypes.DWORD), ("dwOutDiscards", wintypes.DWORD),
        ("dwOutErrors", wintypes.DWORD), ("dwOutQLen", wintypes.DWORD),
        ("dwDescrLen", wintypes.DWORD), ("bDescr", ctypes.c_byte * 256),
    ]


class _MIB_IPADDRROW(ctypes.Structure):
    """GetIpAddrTable 的一行：本机一个 IPv4 地址 + 掩码 + 属于哪块卡（地址是网络字节序）。"""
    _fields_ = [("dwAddr", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                ("dwMask", wintypes.DWORD), ("dwBCastAddr", wintypes.DWORD),
                ("dwReasmSize", wintypes.DWORD), ("unused1", ctypes.c_ushort),
                ("wType", ctypes.c_ushort)]


def _iphlp_api():
    """配好要用的 iphlpapi 函数签名（只配一次）。配不上返回 None，调用方走文本兜底。"""
    global _IPHLP_READY
    lib = globals().get("_iphlp")
    if not IS_WIN or lib is None:
        return None
    if _IPHLP_READY:
        return lib
    try:
        for name, argtypes, restype in (
            ("GetBestInterface", [wintypes.ULONG, ctypes.POINTER(wintypes.DWORD)],
             wintypes.DWORD),
            ("GetIfEntry", [ctypes.c_void_p], wintypes.DWORD),
            ("GetNumberOfInterfaces", [ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            ("GetIpAddrTable", [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                wintypes.BOOL], wintypes.DWORD),
        ):
            fn = getattr(lib, name)
            fn.argtypes = argtypes
            fn.restype = restype
        _IPHLP_READY = True
        return lib
    except Exception:
        return None


def best_if_index(ip):
    """问系统：发往这个地址时会用哪块网卡，返回 ifIndex；问不到返回 None。

    GetBestInterface 只查路由表 / 路径表，不发任何包，所以只用来打标签不会拖慢扫描。
    地址必须是网络字节序（和 IcmpSendEcho 一个规矩）。
    """
    lib = _iphlp_api()
    if lib is None:
        return None
    try:
        idx = wintypes.DWORD(0)
        if lib.GetBestInterface(wintypes.ULONG(_to_ipaddr(ip)), ctypes.byref(idx)) != 0:
            return None
        return int(idx.value)
    except Exception:
        return None


def _ip_addr_rows():
    """GetIpAddrTable → [(ifIndex, 地址整数, 掩码整数), ...]（已换成本机字节序）。"""
    lib = _iphlp_api()
    if lib is None:
        return []
    size = wintypes.DWORD(0)
    try:
        # 第一次调用只为了问需要多大缓冲，它会返回 ERROR_INSUFFICIENT_BUFFER(122)，
        # 这不是错误；真正的判据是 size 有没有填上，别拿返回值当失败。
        lib.GetIpAddrTable(None, ctypes.byref(size), False)
        if not size.value:
            return []
        buf = ctypes.create_string_buffer(size.value)
        if lib.GetIpAddrTable(buf, ctypes.byref(size), False) != 0:
            return []
        n = wintypes.DWORD.from_buffer(buf).value
        rows = ctypes.cast(ctypes.byref(buf, 4),
                           ctypes.POINTER(_MIB_IPADDRROW * n)).contents
        return [(int(r.dwIndex), socket.ntohl(r.dwAddr), socket.ntohl(r.dwMask))
                for r in rows]
    except Exception:
        return []


def _if_entry(idx):
    """GetIfEntry → (网卡描述, 类型)；失败返回 (None, 0)。"""
    lib = _iphlp_api()
    if lib is None:
        return None, 0
    try:
        row = _MIB_IFROW()
        row.dwIndex = int(idx)
        if lib.GetIfEntry(ctypes.byref(row)) != 0:
            return None, 0
        # dwDescrLen 把结尾的 \0 也算进去了，先切掉再解码
        raw = bytes(bytearray(row.bDescr[:row.dwDescrLen]))
        descr = raw.split(b"\x00", 1)[0].decode("gbk", "ignore").strip()
        return (descr or None), int(row.dwType)
    except Exception:
        return None, 0


def nic_index_map():
    """{ifIndex: (网卡名, "有线"/"WiFi")} —— 类型直接问系统，不靠 ipconfig 的标题猜。"""
    lib = _iphlp_api()
    out = {}
    if lib is None:
        return out
    try:
        n = wintypes.DWORD(0)
        if lib.GetNumberOfInterfaces(ctypes.byref(n)) != 0:
            return out
        for idx in range(1, int(n.value) + 1):
            descr, iftype = _if_entry(idx)
            if not descr or iftype == _IF_TYPE_LOOPBACK:
                continue            # 没有第 idx 块卡 / 回环，跳过
            if "Filter" in descr or "Packet Scheduler" in descr:
                continue            # 挂在真网卡上的协议过滤子接口，不是独立网卡
            out[idx] = (descr, "WiFi" if iftype == _IF_TYPE_IEEE80211 else "有线")
    except Exception:
        return out
    return out


def nic_display_names():
    """{ifIndex: (显示名, "有线"/"WiFi")}。

    显示名优先用 ipconfig 里的适配器名（「以太网」/「WLAN」这种短名，界面上好看），
    拿不到就退到系统给的驱动描述（Realtek PCIe GbE Family Controller 之类）。
    类型一律以系统报告的类型为准，不认识的名字不影响 WiFi 判定。
    """
    named = nic_index_map()
    if not named:
        return {}
    short = {}
    try:
        adapters = local_adapters()              # {本机IP: (短名, 类型)}
        for idx, addr, _mask in _ip_addr_rows():
            ip = str(ipaddress.IPv4Address(addr))    # 表里的地址已换成本机字节序
            got = adapters.get(ip)
            if got and got[0]:
                short.setdefault(idx, got[0])
    except Exception:
        short = {}
    return {idx: (short.get(idx) or descr, kind) for idx, (descr, kind) in named.items()}


def build_nic_map(ips):
    """算出每个目标 IP 会从哪块网卡发出去，返回 {ip: (显示文本, 传输方式)}。

    显示文本形如「有线 · 以太网」/「WiFi · WLAN（经默认网关）」。
    这就是结果表里「出口网卡」那一列的内容 —— 靠系统自己的选路得出，
    **不能再自己 tail 路由表做最长前缀匹配**，那套算出来的结论和真实行为不一致
    （详见本节开头的说明）。查表不发包，扫描速度不受影响。

    带「（经默认网关）」= 目标不在这块卡的网段里，是绕网关出去的：
    实测把无线网卡一关，这类地址就全都搜不到了。
    """
    ips = list(ips)
    names = nic_display_names()
    if not names:
        return _build_nic_map_route(ips)         # 非 Windows / API 拿不到 → 文本兜底
    addrs = {}
    for idx, addr, mask in _ip_addr_rows():      # ifIndex -> 这块卡上的网段
        addrs.setdefault(idx, []).append((addr, mask))
    out = {}
    for ip in ips:
        try:
            v = int(ipaddress.IPv4Address(ip))
        except Exception:
            continue
        idx = best_if_index(ip)
        if idx is None:
            return _build_nic_map_route(ips)
        name, kind = names.get(idx, ("", ""))
        direct = any((v & m) == (a & m) for a, m in addrs.get(idx, []))
        label = ("%s · %s" % (kind, name)) if name else (kind or "未知")
        if not direct:
            label += "（经默认网关）"
        out[ip] = (label, kind)
    return out


def _build_nic_map_route(ips):
    """兜底：非 Windows 或系统 API 不可用时，自己按路由表做最长前缀匹配。

    只能算「按路由表该走哪块卡」，和 Windows 真实选路可能不一致
    （这正是 Windows 上要优先走 GetBestInterface 的原因），所以仅作降级用。
    """
    adapters = local_adapters()
    routes = ipv4_routes()
    default_iface = next((r[2] for r in routes if r[0] == 0), None)
    out = {}
    for ip in ips:
        try:
            v = int(ipaddress.IPv4Address(ip))
        except Exception:
            continue
        iface, hit_direct = None, False
        for plen, netint, ifc, gwc in routes:
            mask = (0xFFFFFFFF << (32 - plen)) & 0xFFFFFFFF
            if plen == 0 or (v & mask) == netint:
                iface = ifc
                hit_direct = plen > 0
                break
        name, kind = adapters.get(iface, ("", ""))
        if name:
            label = "%s · %s" % (kind, name)
        elif iface:
            label = iface
        else:
            label = "未知"
        if not hit_direct and iface == default_iface:
            label = (label or iface or "未知") + "（经默认网关）"
        out[ip] = (label, kind if hit_direct else "")
    return out


# --------------------------------------------------------------------------
# 界面
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 常用设备地址表
#
# 现场固定地址的设备，扫到就自动填「设备名称」（在线设备列表和导出的设备表都用它）。
# 要加设备直接往下面这张表加一行就行：  "192.168.1.x": "设备名",
# 同一台设备在不同网段用不同地址时，把两个地址都写上即可。
# --------------------------------------------------------------------------
DEVICE_NAMES = {
    "192.168.1.6": "信捷PLC",
    "192.168.6.6": "信捷PLC",        # 同一台设备换网段后用的地址
    "192.168.1.88": "汇川PLC",
    "192.168.1.125": "宇泰CAN盒",
    "192.168.1.100": "工控机",
}


def device_name(ip: str):
    """按常用设备表取名字；表里没配过的返回空串，不瞎猜。"""
    return DEVICE_NAMES.get(ip, "")


def _ip_key(ip: str):
    """IP 排序键：按数值大小排。

    直接按字符串排的话 192.168.1.10 会排在 192.168.1.9 前面，看着就是乱的。
    """
    try:
        return int(ipaddress.IPv4Address(ip))
    except Exception:
        return 0


MODE_HINTS = {
    "自动识别": "支持混写：192.168.1.0/24　192.168.1.1-192.168.1.254　192.168.1.10-50　192.168.1.*　10.0.0.5",
    "单个 IP": "例：192.168.1.1",
    "IP 范围": "例：192.168.1.1-192.168.1.254，或简写 192.168.1.10-50",
    "整个网段(CIDR)": "例：192.168.1.0/24（自动扫描 .1 ~ .254 共 254 个地址）",
    "多网段批量": "每行一个网段，例：\n192.168.1.0/24\n10.0.0.0/28",
}

# 网段后缀 /24 的含义说明，跟着模式提示一起显示。
# 斜杠后面的数字是「子网掩码的位数」：前 N 位是网络号，剩下的位数才是主机号。
# /24 → 主机位 8 位 → 2^8 = 256 个地址（.0 网络号、.255 广播，能用的 254 个）
CIDR_HINT = "　｜　/24 里的 24 = 掩码位数（前 24 位是网络号）→ 256 个地址；数字越小网段越大：/25=128、/23=512"

# --------------------------------------------------------------------------
# 能写的输入格式清单
#
# 界面上的「写法总览」和「格式说明」窗口共用这一份数据，改这里两处都跟着变。
# 每行 4 段：(格式名, 写法范例, 展开后多少个, 用来校验的输入)。
# 最后一段是给自测脚本用的真实输入（第 2 段是给人看的说明，可能不是能直接粘的字符串），
# 自测会拿它跑一遍 parse_targets()，核对「展开后」里写的数量是不是真的
# —— 所以改解析逻辑（expand_spec）后，跑一次自测就知道这张表有没有说谎。
# --------------------------------------------------------------------------
INPUT_FORMATS = [
    ("单个 IP", "192.168.1.100", "1 个：就探这一个地址",
     "192.168.1.100"),
    ("起止范围", "192.168.1.1-192.168.1.254", "254 个：首尾都算在内",
     "192.168.1.1-192.168.1.254"),
    ("起止范围（简写）", "192.168.1.10-50", "41 个：只写尾码，前三段沿用",
     "192.168.1.10-50"),
    ("整个网段 CIDR", "192.168.1.0/24", "254 个：.1 ~ .254",
     "192.168.1.0/24"),
    ("整个网段 CIDR", "10.0.0.0/28", "14 个：10.0.0.1 ~ 10.0.0.14",
     "10.0.0.0/28"),
    ("整个网段 CIDR", "192.168.4.0/23", "510 个：192.168.4.1 ~ 192.168.5.254",
     "192.168.4.0/23"),
    ("整段通配", "192.168.1.*", "254 个：等于 192.168.1.0/24",
     "192.168.1.*"),
    ("整段通配", "192.168.1.", "254 个：结尾一个点也认，同上",
     "192.168.1."),
    ("多网段批量", "192.168.1.0/24 和 10.0.0.0/28 各占一行", "268 个：254 + 14，每行一个网段",
     "192.168.1.0/24\n10.0.0.0/28"),
    ("混写（最常用）", "192.168.1.10-50, 10.0.0.0/28, 172.16.0.1", "56 个：上面几种随便混着写",
     "192.168.1.10-50, 10.0.0.0/28, 172.16.0.1"),
]

# 掩码位数对照：(掩码, 网段里的地址总数, 实际会扫的个数)
CIDR_TABLE = [
    ("/30", "4", "2"), ("/29", "8", "6"), ("/28", "16", "14"), ("/27", "32", "30"),
    ("/26", "64", "62"), ("/25", "128", "126"), ("/24", "256", "254"),
    ("/23", "512", "510"), ("/22", "1024", "1022"), ("/16", "65536", "65534"),
]

# 「格式说明」窗口底部的注意事项
FORMAT_NOTES = [
    "自动跳过网络号（.0）和广播地址（.255），所以 /24 实际扫 254 个，而不是 256 个。",
    "分隔符：空格、逗号、分号、顿号、换行都行；一行里写多个和分成多行写，效果一样。",
    "跨网段的范围要两头写全，例如 192.168.1.5-192.168.2.7；简写形式（192.168.1.5-10.0.0.5）只在同一段内有效。",
    "192.168.*.* 这种前两段通配也认，但会一次展开 6 万多个地址，很慢，不建议用。",
    "单次最多 65536 个地址，超了会被拦下来提示拆分——分几次扫就行。",
    "「扫描模式」下拉框只是个提示，选哪个都不影响能写什么：以上写法在任何模式下都认。",
]

# 常驻在目标框下面的写法总览（详细说明在「格式说明」按钮里）
FORMAT_LEGEND = (
    "可输入的写法（下面几种可以混着写，用 空格 / 逗号 / 分号 / 换行 分开）：\n"
    "① 单个 IP　192.168.1.100　　② 起止范围　192.168.1.1-192.168.1.254（254 个）"
    "或简写 192.168.1.10-50（41 个）\n"
    "③ 整个网段　192.168.1.0/24（254 个）　　10.0.0.0/28（14 个）　　"
    "192.168.4.0/23（510 个）\n"
    "④ 整段通配　192.168.1.*　或　192.168.1.（都等于 192.168.1.0/24，254 个）\n"
    "⑤ 多段批量　一行写一个网段（第一行 192.168.1.0/24、第二行 10.0.0.0/28）\n"
    "⑥ 混　　写　192.168.1.10-50, 10.0.0.0/28, 172.16.0.1（56 个）"
)


def _mix(c1: str, c2: str, t: float) -> str:
    """把颜色 c1 按比例 t 往 c2 混合（t=0 全是 c1，t=1 全是 c2）。"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# --------------------------------------------------------------------------
# 按钮配色
#
# 界面上每类操作一个颜色，扫一眼就能找到按钮。clam 主题下 ttk.Button 的底色
# 要用 style.configure 同时设 background 和 bordercolor，只设 background 的话
# 会露出主题自带的浅色边框，看着像没生效。
# 禁用态特意不设成白色：比如扫描中「停止」按钮要保持红色系，只是变淡。
# --------------------------------------------------------------------------
BTN_COLORS = {
    #   key       样式名               底色       字色       悬停底色    边框色
    "blue":   ("BtnBlue.TButton",   "#2f6feb", "#ffffff", "#1f5ad4", "#2f6feb"),
    "green":  ("BtnGreen.TButton",  "#1a7f37", "#ffffff", "#146c2e", "#1a7f37"),
    "teal":   ("BtnTeal.TButton",   "#0f7b8a", "#ffffff", "#0b646f", "#0f7b8a"),
    "orange": ("BtnOrange.TButton", "#c05f14", "#ffffff", "#a34f0f", "#c05f14"),
    "purple": ("BtnPurple.TButton", "#6b3fbf", "#ffffff", "#5a33a4", "#6b3fbf"),
    "red":    ("BtnRed.TButton",    "#c0392b", "#ffffff", "#a32e22", "#c0392b"),
    "indigo": ("BtnIndigo.TButton", "#4c5fd5", "#ffffff", "#3d4db6", "#4c5fd5"),
    "slate":  ("BtnSlate.TButton",  "#5b6b7c", "#ffffff", "#4a5866", "#5b6b7c"),
    "gray":   ("BtnGray.TButton",   "#eaeef2", "#1f2328", "#dde3e9", "#c9d1d9"),
}


# --------------------------------------------------------------------------
# 地址显示区
#
# 把扫描目标按 C 段（前三段）分组，每段画 16×16 = 256 个格子，格子里只写尾码
# （0~255）。格子颜色直接反映状态，一眼就能看出哪几台活着。
# --------------------------------------------------------------------------
class AddressGrid(ttk.Labelframe):
    PAD = 8                   # 画布内边距
    HEAD_H = 20               # 每个 C 段的标题行高度
    SEP = 10                  # C 段之间的间距
    GAP = 3                   # 格子间距
    MAX_GROUPS = 8            # 最多画 8 个 C 段（本机有 7 个网段时 /23 会占 2 段），再多界面会卡
    MAX_TILES = 1536

    # 状态 -> (底色, 字色, 边框色)
    STYLE = {
        "none":  ("#f7f8fa", "#c9cfd6", "#eceff2"),   # 不在扫描范围
        "idle":  ("#ffffff", "#9aa1a9", "#dfe3e8"),   # 待扫描
        "alive": ("#d7f0e1", "#0f5c34", "#79c69c"),   # 在线
        "self":  ("#c9dcff", "#1440b8", "#5b8def"),   # 本机
        "dead":  ("#eef0f2", "#b6bcc3", "#e0e4e8"),   # 离线
        "hidden":("#e2e6ec", "#7d8794", "#c2cad4"),   # 已隐藏（被「只看网线直连」过滤掉的经无线设备）
    }
    STATE_TEXT = {"none": "不在扫描范围", "idle": "待扫描", "alive": "在线",
                  "self": "本机", "dead": "离线", "hidden": "已隐藏（经无线网卡）"}
    HINT = "把鼠标移到格子上看详细结果，双击格子复制 IP"

    def _px(self, v):
        """逻辑像素 -> 当前系统缩放下应使用的物理像素。"""
        return int(round(v * self.ui))

    def __init__(self, master, ui=1.0):
        self.ui = max(1.0, float(ui))
        super().__init__(master, text=" 地址显示区 ",
                         padding=(self._px(8), self._px(6), self._px(8), self._px(5)))
        # 像素尺寸按系统缩放同步放大，才能和自动放大的字号保持比例
        self.pad = self._px(self.PAD)
        self.head_h = self._px(self.HEAD_H)
        self.sep = self._px(self.SEP)
        self.gap = self._px(self.GAP)
        self.mac_source = lambda ip: ""      # 由 App 注入，用来在详情里补 MAC

        self._items = {}      # ip -> (矩形 id, 文字 id)
        self._states = {}     # ip -> 状态
        self._res = {}        # ip -> 扫描结果 dict
        self._local = set()   # 本机 IP
        self._groups = []     # [(前三段, {尾码...}), ...]
        self._hidden = 0      # 因为超限没画出来的 C 段数量
        self._hidden_ips = set()   # 被「只看网线直连」过滤掉的 IP（画成「已隐藏」灰）
        self._pinned = None   # 被点击固定住的格子
        self._cols, self._tw, self._th = 16, 38, 21
        self._relayout_job = None

        head = ttk.Frame(self, style="Card.TFrame")
        head.pack(fill="x")
        self.title_var = tk.StringVar(value="地址图")
        ttk.Label(head, textvariable=self.title_var, style="Card.TLabel").pack(side="left")
        self.detail_var = tk.StringVar(value=self.HINT)
        ttk.Label(head, textvariable=self.detail_var, style="Hint.TLabel").pack(side="right")

        body = ttk.Frame(self, style="Card.TFrame")
        body.pack(fill="both", expand=True, pady=(self._px(5), 0))
        self.canvas = tk.Canvas(body, bg="#ffffff", highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vs = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.vs.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self._sync_scrollbar)
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Configure>", self._on_resize)

        foot = ttk.Frame(self, style="Card.TFrame")
        foot.pack(fill="x", pady=(self._px(5), 0))
        for text, key in (("在线", "alive"), ("本机", "self"), ("离线", "dead"),
                          ("待扫描", "idle"), ("不在范围", "none"), ("已隐藏", "hidden")):
            bg, fg, bd = self.STYLE[key]
            tk.Label(foot, text=text, bg=bg, fg=fg, font=("Microsoft YaHei UI", 8),
                     padx=self._px(6), pady=self._px(1), bd=0, highlightthickness=1,
                     highlightbackground=bd).pack(side="left", padx=(0, self._px(5)))
        self.foot_var = tk.StringVar(value="")
        ttk.Label(foot, textvariable=self.foot_var, style="Hint.TLabel").pack(side="right")
        self._draw()

    # ---------- 目标 ----------
    def set_targets(self, ips, note=""):
        """传入目标 IP 列表（可以是完整展开后的），重建整张格子图。"""
        self._res.clear()
        self._states.clear()
        self._pinned = None
        self.detail_var.set(self.HINT)

        groups, order = {}, []
        for ip in ips:
            prefix, _, tail = ip.rpartition(".")
            if not prefix.isdigit() and prefix.count(".") != 2:
                continue
            if prefix not in groups:
                groups[prefix] = set()
                order.append(prefix)
            try:
                groups[prefix].add(int(tail))
            except ValueError:
                continue
        self._hidden = max(0, len(order) - self.MAX_GROUPS)
        self._groups = [(p, groups[p]) for p in order[:self.MAX_GROUPS]]
        self._draw()

        n = sum(len(h) for _, h in self._groups)
        if self._groups:
            extra = "，仅显示前 %d 段" % self.MAX_GROUPS if self._hidden else ""
            self.title_var.set("地址图 · %d 个目标 · %d 个 C 段（尾码 0~255）%s"
                               % (n, len(self._groups), extra))
        else:
            self.title_var.set("地址图")
        self.foot_var.set(note or ("还有 %d 个 C 段未显示" % self._hidden if self._hidden else ""))

    def set_local(self, ips):
        self._local = set(ips)
        for ip in list(self._items):
            self._paint(ip)

    def apply_result(self, res):
        ip = res["ip"]
        if ip not in self._items:
            return
        self._res[ip] = res
        self._paint(ip)

    def reset_states(self):
        self._res.clear()
        self._pinned = None
        self.detail_var.set(self.HINT)
        for ip in list(self._items):
            self._paint(ip)

    def set_hidden_ips(self, hidden):
        """告诉地址图哪些 IP 被「只看网线直连」过滤掉了：这些格子画成「已隐藏」灰，
        不再显示成绿色「在线」。hidden 是 ip 集合（由 App 按系统选路 + 当前开关算好传进来）。
        """
        self._hidden_ips = set(hidden)
        for ip in list(self._items):
            self._paint(ip)

    # ---------- 绘制 ----------
    def _sync_scrollbar(self, first, last):
        """整段一屏放得下就把滚动条收起来，放不下才显示。"""
        need = not (float(first) <= 0.0 and float(last) >= 1.0)
        try:
            if need and not self.vs.winfo_manager():
                self.vs.pack(side="right", fill="y")
            elif not need and self.vs.winfo_manager():
                self.vs.pack_forget()
        except tk.TclError:
            pass
        self.vs.set(first, last)

    def _on_resize(self, _event=None):
        """窗口大小变了，重新算格子尺寸（防抖）。"""
        if self._relayout_job:
            try:
                self.after_cancel(self._relayout_job)
            except Exception:
                pass
        self._relayout_job = self.after(150, self._relayout)

    def _relayout(self):
        self._relayout_job = None
        if self._groups:
            self._draw()

    # 每档：(列数, 格子最小高度)；都按系统缩放换算
    MIN_TH = ((16, 16.0), (32, 14.0), (16, 12.5), (32, 11.0))

    def _metrics(self):
        """按画布可用空间挑格子尺寸：优先 16 列（16×16 好读），放不下就换 32 列。
        目标是把整个网段一屏放下，尽量不出现滚动条。"""
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 120 or h < 80:
            return None
        n = max(1, len(self._groups))
        for cols, min_th in self.MIN_TH:
            rows = 256 // cols
            avail = h - 2 * self.pad - n * (self.head_h + self.sep)
            th = avail / float(rows * n) - self.gap
            if th < min_th * self.ui:
                continue
            th = min(26.0 * self.ui, th)
            tw = min(int(round(th * 1.8)), int((w - 2 * self.pad) / cols) - self.gap - 1)
            if tw < int(round(18 * self.ui)):
                continue
            return cols, tw, int(th)
        # 窗口被拖得太小、或展开明细表把地址区压扁时：不把格子继续压小，
        # 而是给一个还能看的下限，让画布滚动
        cols = 32
        rows = 256 // cols
        avail = h - 2 * self.pad - n * (self.head_h + self.sep)
        th = max(int(round(16 * self.ui)),
                 int(round(avail / float(rows * n) - self.gap)))
        tw = max(16, min(int(round(th * 1.8)), int((w - 2 * self.pad) / cols) - self.gap - 1))
        return cols, tw, th

    def _draw(self):
        m = self._metrics()
        if m:
            self._cols, self._tw, self._th = m
        c = self.canvas
        c.delete("all")
        self._items.clear()
        self._states.clear()

        if not self._groups:
            c.create_text(self.pad, self.pad, anchor="nw", fill="#9aa1a9",
                          font=("Microsoft YaHei UI", 9),
                          text="填好扫描目标后，这里会按 C 段显示 0~255 的地址格子。")
            c.configure(scrollregion=(0, 0, self._px(620), self._px(60)))
            return

        cols, tw, th = self._cols, self._tw, self._th
        rows = 256 // cols
        cw, ch = tw + self.gap, th + self.gap
        y = self.pad
        for prefix, hosts in self._groups:
            c.create_text(self.pad, y + self.head_h // 2, anchor="w", fill="#374151",
                          font=("Microsoft YaHei UI", 9, "bold"), text="%s.x" % prefix)
            c.create_text(self.pad + self._px(170), y + self.head_h // 2, anchor="w",
                          fill="#8b929c", font=("Microsoft YaHei UI", 8),
                          text="扫描 %d 个地址" % len(hosts))
            y += self.head_h + self._px(4)
            for n in range(256):
                col, row = n % cols, n // cols
                x0, y0 = self.pad + col * cw, y + row * ch
                ip = "%s.%d" % (prefix, n)
                is_target = n in hosts
                state = ("hidden" if (is_target and ip in self._hidden_ips) else
                         "self" if (is_target and ip in self._local) else
                         ("idle" if is_target else "none"))
                bg, fg, bd = self.STYLE[state]
                rect = c.create_rectangle(x0, y0, x0 + tw, y0 + th,
                                          fill=bg, outline=bd, width=1, tags=("tile", ip))
                txt = c.create_text(x0 + tw / 2, y0 + th / 2, text=str(n),
                                    fill=fg, font=("Consolas", 8 if th < 20 * self.ui else 9),
                                    tags=("tile", ip))
                if is_target:
                    self._items[ip] = (rect, txt)
                    self._states[ip] = state
                    c.tag_bind(ip, "<Enter>", lambda e, i=ip: self._hover(i))
                    c.tag_bind(ip, "<Leave>", lambda e: self._leave())
                    c.tag_bind(ip, "<Button-1>", lambda e, i=ip: self._click(i))
                    c.tag_bind(ip, "<Double-1>", lambda e, i=ip: self._copy(i))
            y += rows * ch + self.sep
        c.configure(scrollregion=(0, 0, self.pad * 2 + cols * cw, y))

    def _paint(self, ip, state=None):
        rect, txt = self._items[ip]
        if state is None:
            res = self._res.get(ip)
            if ip in self._hidden_ips:
                state = "hidden"          # 被「只看网线直连」过滤掉：不画成在线绿
            elif ip in self._local:
                state = "self"
            elif res is None:
                state = "idle"
            else:
                state = "alive" if res["alive"] else "dead"
        self._states[ip] = state
        bg, fg, bd = self.STYLE[state]
        self.canvas.itemconfigure(rect, fill=bg, outline=bd)
        self.canvas.itemconfigure(txt, fill=fg)
        if ip == self._pinned:
            self._show_detail(ip)

    # ---------- 交互 ----------
    def _hover(self, ip):
        if not self._pinned:
            self._show_detail(ip)

    def _leave(self):
        if not self._pinned:
            self.detail_var.set(self.HINT)

    def _click(self, ip):
        self._pinned = None if self._pinned == ip else ip
        if self._pinned:
            self._show_detail(ip)
        else:
            self.detail_var.set(self.HINT)

    def _copy(self, ip):
        try:
            self.clipboard_clear()
            self.clipboard_append(ip)
        except tk.TclError:
            pass
        self.detail_var.set("已复制 %s 到剪贴板" % ip)

    def _show_detail(self, ip):
        if ip not in self._items:
            return
        state = self._states.get(ip, "idle")
        res = self._res.get(ip) or {}
        parts = [ip, self.STATE_TEXT.get(state, "")]
        if state in ("alive", "self"):
            ms = res.get("ms")
            if ms is not None:
                parts.append("延迟 <1 ms" if ms < 1 else "延迟 %.0f ms" % ms)
            if res.get("ttl") is not None:
                parts.append("TTL %d" % res["ttl"])
            if res.get("host"):
                parts.append(res["host"])
            mac = self.mac_source(ip) or ""
            if mac:
                parts.append("MAC %s" % mac)
        elif state == "none":
            parts.append("网络号 / 广播地址")
        self.detail_var.set("　·　".join(p for p in parts if p))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        # 系统缩放系数（100% = 1.0）。开了 DPI 感知后字号会自动按 DPI 放大，
        # 所以像素类尺寸也要同步放大，界面才不会显得局促。
        self.ui = max(1.0, min(2.0, self.winfo_fpixels("1i") / 96.0))
        self._fit_window()
        self.configure(bg="#f4f5f7")

        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.scanning = False
        self.rows = {}          # ip -> dict
        self.order = []         # 结果出现顺序
        self.local_ips = set()
        self.local_ready = threading.Event()     # 本机网段识别是否已完成
        self.arp_table = {}
        self.total = 0
        self.grid_total = 0
        self.alive_count = 0
        self.started_at = 0.0
        self._table_shown = False
        self.online_view = False         # 主区当前显示的是在线设备列表而不是地址图
        self._preview_job = None
        self.custom_names = {}           # ip -> 手写的设备名称（覆盖常用设备表，随配置存盘）
        self._name_edit = None           # 正在编辑设备名称时： (ip, StringVar, Entry)
        self.nic_of = {}                 # ip -> (出口网卡文本, 传输方式)，扫描开始时按路由表算一次

        self._init_style()
        self._build_ui()
        self.addr_grid.mac_source = lambda ip: self.arp_table.get(ip, "")
        self._load_config()
        threading.Thread(target=self._detect_local, daemon=True).start()
        self.after(80, self._poll_queue)
        self.after(150, self._preview_grid)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 尺寸 ----------------
    def _px(self, v):
        """逻辑像素 -> 当前系统缩放下应使用的物理像素。"""
        return int(round(v * self.ui))

    def _work_area(self):
        """Windows 工作区（屏幕去掉任务栏）的 (left, top, right, bottom)，物理像素。"""
        if IS_WIN:
            try:
                rect = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(
                        0x0030, 0, ctypes.byref(rect), 0):        # SPI_GETWORKAREA
                    return rect.left, rect.top, rect.right, rect.bottom
            except Exception:
                pass
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    def _fit_window(self):
        """按屏幕可用空间决定初始窗口大小和位置。

        原来固定 1120x800，在 125% 缩放的 1080p 屏上实际要占 1400x1030 物理像素，
        加上标题栏正好顶到任务栏，最下面的图例和统计会被压到屏幕外。
        这里改成「需要多大」和「工作区装得下多大」取小值，并贴着工作区顶部摆放。
        """
        wx, wy, wr, wb = self._work_area()
        avail_w, avail_h = wr - wx, wb - wy
        w = max(self._px(880), min(self._px(1120), avail_w - self._px(24)))
        h = max(self._px(560), min(self._px(830), avail_h - self._px(64)))
        x = wx + max(0, (avail_w - w) // 2)
        y = wy + max(0, min(self._px(24), (avail_h - h) // 4))
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.minsize(self._px(880), self._px(560))

    # ---------------- 样式 ----------------
    def _init_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        base_font = ("Microsoft YaHei UI", 9)
        self.option_add("*Font", base_font)
        style.configure(".", font=base_font, background="#f4f5f7")
        style.configure("TFrame", background="#f4f5f7")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f4f5f7", foreground="#1f2328")
        style.configure("Card.TLabel", background="#ffffff", foreground="#1f2328")
        style.configure("Hint.TLabel", background="#ffffff", foreground="#6b7280", font=("Microsoft YaHei UI", 8))
        style.configure("Stat.TLabel", background="#f4f5f7", foreground="#374151", font=("Microsoft YaHei UI", 9))
        style.configure("Stats.TLabel", background="#f4f5f7", foreground="#1f2328",
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Panedwindow", background="#f4f5f7")
        style.configure("TLabelframe", background="#ffffff", bordercolor="#d8dee4", relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background="#ffffff", foreground="#2f6feb",
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TButton", background="#ffffff", foreground="#1f2328", bordercolor="#d0d7de",
                        padding=(self._px(11), self._px(4)), relief="flat", focusthickness=0)
        style.map("TButton",
                  background=[("active", "#eef1f5"), ("disabled", "#f3f4f6")],
                  foreground=[("disabled", "#9ca3af")],
                  bordercolor=[("active", "#b9c0c8")])
        # 彩色按钮：每类操作一个颜色（配色见文件开头的 BTN_COLORS）
        for _name, _bg, _fg, _hover, _border in BTN_COLORS.values():
            _dim = _mix(_bg, "#ffffff", 0.62)          # 禁用态 = 同色系变淡，不改成白色
            style.configure(_name, background=_bg, foreground=_fg, bordercolor=_border,
                            focuscolor=_bg, padding=(self._px(11), self._px(4)),
                            relief="flat", focusthickness=0)
            style.map(_name,
                      background=[("active", _hover), ("pressed", _hover), ("disabled", _dim)],
                      foreground=[("disabled", "#9aa4b0")],
                      bordercolor=[("active", _hover), ("disabled", _dim)],
                      focuscolor=[("active", _bg), ("disabled", _dim)])
        style.configure("TCheckbutton", background="#ffffff", foreground="#1f2328")
        style.map("TCheckbutton", background=[("active", "#ffffff")])
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor="#d0d7de", padding=4)
        style.configure("TCombobox", fieldbackground="#ffffff", padding=3)
        style.configure("TSpinbox", fieldbackground="#ffffff", padding=4)
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                        foreground="#1f2328", bordercolor="#e5e7eb", borderwidth=0,
                        rowheight=self._px(24), font=("Consolas", 9))
        style.configure("Treeview.Heading", background="#eef1f4", foreground="#374151",
                        relief="flat", font=("Microsoft YaHei UI", 9, "bold"),
                        padding=(self._px(4), self._px(5)))
        style.map("Treeview.Heading", background=[("active", "#e3e8ee")])
        style.map("Treeview", background=[("selected", "#d6e4ff")], foreground=[("selected", "#1f2328")])
        style.configure("TProgressbar", background="#2f6feb", troughcolor="#e5e7eb",
                        bordercolor="#e5e7eb", lightcolor="#2f6feb", darkcolor="#2f6feb")

    # ---------------- 布局 ----------------
    def _cbox(self, parent, text, var, command=None):
        """原生 Checkbutton。clam 主题的 ttk 版会把勾选记号画成 ✗，和未选中的方框
        风格不统一，很难看，所以这里用 tk 原生的系统样式。"""
        return tk.Checkbutton(
            parent, text=text, variable=var, command=command,
            bg="#ffffff", activebackground="#ffffff", selectcolor="#ffffff",
            highlightthickness=0, bd=0, anchor="w", padx=2,
            font=("Microsoft YaHei UI", 9), fg="#1f2328",
        )

    def _btn(self, parent, text, command, kind="gray", **kw):
        """建一个带背景色的按钮。kind 见 BTN_COLORS，界面上一类操作一个颜色。"""
        style_name = BTN_COLORS.get(kind, BTN_COLORS["gray"])[0]
        return ttk.Button(parent, text=text, command=command, style=style_name, **kw)

    def _build_ui(self):
        outer = ttk.Frame(self, padding=self._px(10))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        # ---- 目标配置卡片 ----
        card = ttk.Labelframe(outer, text=" 扫描目标 ",
                              padding=(self._px(10), self._px(6), self._px(10), self._px(5)))
        card.grid(row=0, column=0, sticky="ew")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="扫描模式", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.mode_var = tk.StringVar(value="自动识别")
        self.mode_box = ttk.Combobox(card, textvariable=self.mode_var, state="readonly",
                                     values=list(MODE_HINTS.keys()), width=16)
        self.mode_box.grid(row=0, column=1, sticky="w")
        self.mode_box.bind("<<ComboboxSelected>>", self._on_mode_change)

        ttk.Label(card, text="本机 IP（Ctrl 多选，双击填入）", style="Card.TLabel").grid(
            row=0, column=2, sticky="ne", padx=(16, 6))
        # 直接读电脑自己的 IPv4 地址列出来：可单选，Ctrl / Shift 可多选。
        # 「填入本机网段 / 整段扫描」只作用于勾中的那几个 IP 对应的网段
        lbwrap = ttk.Frame(card, style="Card.TFrame")
        lbwrap.grid(row=0, column=3, sticky="w")
        self.local_list = tk.Listbox(lbwrap, height=4, width=34, selectmode="extended",
                                     exportselection=0, activestyle="none",
                                     font=("Consolas", 9), bg="#ffffff", fg="#1f2328",
                                     relief="solid", borderwidth=1, highlightthickness=0,
                                     selectbackground="#d6e4ff", selectforeground="#1f2328")
        self.local_list.pack(side="left")
        lsb = ttk.Scrollbar(lbwrap, orient="vertical", command=self.local_list.yview)
        lsb.pack(side="left", fill="y")
        self.local_list.configure(yscrollcommand=lsb.set)
        self.local_list.insert("end", "识别中…")
        self.local_list.bind("<<ListboxSelect>>", lambda _e: self._show_local_tip())
        # 双击某一行 → 把该行（多选时是勾中的全部）对应的网段填进下面的目标框
        self.local_list.bind("<Double-1>", self._local_double_click)

        self._btn(card, "填入本机网段", self._fill_local, "blue").grid(row=0, column=4, padx=(6, 0))
        self._btn(card, "整段扫描", self._one_click_scan_local, "green").grid(row=0, column=5, padx=(6, 0))

        ttk.Label(card, text="目标地址 / 网段", style="Card.TLabel").grid(
            row=1, column=0, sticky="nw", padx=(0, 6), pady=(self._px(6), 0))
        self.target_text = tk.Text(card, height=2, wrap="word", font=("Consolas", 10),
                                   relief="solid", borderwidth=1, highlightthickness=0,
                                   bg="#ffffff", fg="#1f2328", insertbackground="#1f2328")
        self.target_text.grid(row=1, column=1, columnspan=4, sticky="ew", pady=(self._px(6), 0))
        self.target_text.insert("1.0", "192.168.1.0/24")
        self._btn(card, "清空", self._clear_target, "gray").grid(
            row=1, column=5, sticky="e", padx=(6, 0), pady=(self._px(6), 0))

        # 勾上后，「本机 IP」列表和「填入本机网段 / 整段扫描」都只保留有线网卡连的网段，
        # 不把无线网卡（WiFi）连的网段（如家里 192.168.4.0/23）也填进去。
        self.excl_wifi_var = tk.BooleanVar(value=False)
        self._cbox(card, "排除无线网卡网段", self.excl_wifi_var, self._apply_nets_filter).grid(
            row=2, column=4, sticky="w", padx=(10, 0), pady=(self._px(4), 0))

        self.hint_var = tk.StringVar(value=MODE_HINTS["自动识别"])
        self.fmt_label = ttk.Label(card, textvariable=self.hint_var, style="Hint.TLabel",
                                   justify="left", anchor="w")
        self.fmt_label.grid(row=2, column=0, columnspan=4, sticky="w", pady=(self._px(4), 0))
        self._btn(card, "格式说明", self._show_format_help, "slate").grid(
            row=2, column=5, sticky="e", pady=(self._px(4), 0))

        # 写法总览：常驻显示，不用点按钮也能看到所有能写的格式（详细说明在「格式说明」里）
        self.legend_label = ttk.Label(card, text=FORMAT_LEGEND, style="Hint.TLabel",
                                      justify="left", anchor="w")
        self.legend_label.grid(row=3, column=0, columnspan=6, sticky="w", pady=(self._px(4), 0))
        # 两段提示都按卡片宽度自动折行，写死宽度的话窗口一拉就会串行或被裁掉
        card.bind("<Configure>", self._on_card_resize)

        # ---- 高级选项 ----
        opt = ttk.Labelframe(outer, text=" 高级选项 ",
                             padding=(self._px(10), self._px(5), self._px(10), self._px(5)))
        opt.grid(row=1, column=0, sticky="ew", pady=(self._px(6), 0))

        ttk.Label(opt, text="并发数", style="Card.TLabel").grid(row=0, column=0, padx=(0, 4))
        self.workers_var = tk.IntVar(value=100)
        ttk.Spinbox(opt, from_=1, to=512, increment=16, width=2, textvariable=self.workers_var,
                    justify="center").grid(row=0, column=1, padx=(0, 14))

        ttk.Label(opt, text="超时(ms)", style="Card.TLabel").grid(row=0, column=2, padx=(0, 4))
        self.timeout_var = tk.IntVar(value=800)
        ttk.Spinbox(opt, from_=100, to=10000, increment=200, width=5, textvariable=self.timeout_var,
                    justify="center").grid(row=0, column=3, padx=(0, 14))

        ttk.Label(opt, text="重试次数", style="Card.TLabel").grid(row=0, column=4, padx=(0, 4))
        self.retry_var = tk.IntVar(value=2)
        ttk.Spinbox(opt, from_=0, to=5, width=2, textvariable=self.retry_var,
                    justify="center").grid(row=0, column=5, padx=(0, 18))

        self.skip_self_var = tk.BooleanVar(value=True)
        self.alive_only_var = tk.BooleanVar(value=False)
        self.sort_var = tk.BooleanVar(value=True)
        self.hostname_var = tk.BooleanVar(value=False)
        self.mac_var = tk.BooleanVar(value=True)
        self.wired_only_var = tk.BooleanVar(value=True)

        self._cbox(opt, "跳过本机", self.skip_self_var).grid(row=0, column=6, padx=(0, 10))
        self._cbox(opt, "只显示在线", self.alive_only_var, self._render_all).grid(row=0, column=7, padx=(0, 10))
        self._cbox(opt, "结束后按 IP 排序", self.sort_var).grid(row=0, column=8, padx=(0, 10))
        self._cbox(opt, "解析主机名(较慢)", self.hostname_var).grid(row=0, column=9, padx=(0, 10))
        self._cbox(opt, "读取 MAC", self.mac_var).grid(row=0, column=10)

        # 结果表 / 在线列表里，凡是经无线网卡（默认网关）绕进来的地址一律藏掉。
        # 实测：勾上「排除无线网卡网段」只影响「填入本机网段」，扫描结果照样会列出
        # 经 WiFi 绕进来的设备；要的是「只看真挂在网线上的」，就用这个开关。
        self._cbox(opt, "只看网线直连（隐藏经无线网卡/默认网关拿到的结果）",
                   self.wired_only_var, self._on_wired_only).grid(
            row=1, column=0, columnspan=12, sticky="w", pady=(self._px(4), 0))

        # ---- 操作按钮 ----
        bar = ttk.Frame(outer)
        bar.grid(row=2, column=0, sticky="new", pady=(self._px(6), self._px(4)))
        outer.rowconfigure(2, weight=0)

        self.btn_start = self._btn(bar, "▶  开始扫描", self.start_scan, "blue")
        self.btn_start.pack(side="left")
        self.btn_stop = self._btn(bar, "■  停止", self.stop_scan, "red", state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))
        self._btn(bar, "清空结果", self.clear_results, "gray").pack(side="left", padx=(8, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=12)
        self._btn(bar, "导出详细结果", self.export_csv, "green").pack(side="left")
        self._btn(bar, "导出设备表", self.export_device_table, "teal").pack(side="left", padx=(8, 0))
        self._btn(bar, "复制在线 IP", self.copy_alive, "purple").pack(side="left", padx=(8, 0))
        self._btn(bar, "重新读取 MAC", self.refresh_arp, "orange").pack(side="left", padx=(8, 0))
        self.btn_table = self._btn(bar, "显示明细表", self._toggle_table, "slate")
        self.btn_table.pack(side="right")
        self.btn_online = self._btn(bar, "仅显示在线 IP", self._toggle_online_view, "indigo")
        self.btn_online.pack(side="right", padx=(8, 0))

        # ---- 主区：地址显示区（默认占满） + 结果明细（按需展开） ----
        self.pane = ttk.PanedWindow(outer, orient="vertical")
        self.pane.grid(row=3, column=0, sticky="nsew")
        outer.rowconfigure(3, weight=1)

        self.addr_grid = AddressGrid(self.pane, ui=self.ui)
        self.pane.add(self.addr_grid, weight=1)

        # ---- 结果表 ----
        table = self.table_frame = ttk.Labelframe(self.pane, text=" 结果明细 ", padding=(6, 4, 6, 6))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        cols = ("ip", "status", "nic", "latency", "ttl", "host", "mac")
        self.MAIN_COLS = cols
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        heads = {"ip": ("IP 地址", 150, "w"), "status": ("状态", 80, "center"),
                 "nic": ("出口网卡", 150, "w"),
                 "latency": ("延迟(ms)", 90, "e"), "ttl": ("TTL", 60, "center"),
                 "host": ("主机名", 240, "w"), "mac": ("MAC 地址", 160, "w")}
        for c in cols:
            text, width, anchor = heads[c]
            self.tree.heading(c, text=text, command=lambda cc=c: self._sort_by(cc))
            self.tree.column(c, width=width, anchor=anchor, stretch=(c in ("host",)))
        self.tree.grid(row=0, column=0, sticky="nsew")

        vs = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vs.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vs.set)

        self.tree.tag_configure("alive", background="#e9f7ef", foreground="#12663a")
        self.tree.tag_configure("dead", background="#ffffff", foreground="#9aa0a6")
        self.tree.tag_configure("self", background="#eef2f7", foreground="#5b6b7c")
        self.tree.bind("<Double-1>", self._on_row_double_click)
        # 默认收起明细表，让地址图占满主区；需要看主机名/MAC 时再展开

        # ---- 在线设备列表：点「仅显示在线 IP」后，用它替换掉地址图 ----
        onf = self.online_frame = ttk.Labelframe(
            self.pane, text=" 在线设备（只列在线　·　双击「设备名称」可直接改名字，改完随导出一起走） ",
            padding=(6, 4, 6, 6))
        onf.columnconfigure(0, weight=1)
        onf.rowconfigure(0, weight=1)
        ocols = ("name", "ip", "nic", "latency", "ttl", "host", "mac")
        self.ONLINE_COLS = ocols
        self.online_tree = ttk.Treeview(onf, columns=ocols, show="headings", selectmode="extended")
        oheads = {"name": ("设备名称（双击可改）", 200, "w"), "ip": ("IP 地址", 130, "w"),
                  "nic": ("出口网卡", 150, "w"),
                  "latency": ("延迟(ms)", 90, "e"), "ttl": ("TTL", 60, "center"),
                  "host": ("主机名", 220, "w"), "mac": ("MAC 地址", 160, "w")}
        for c in ocols:
            text, width, anchor = oheads[c]
            self.online_tree.heading(c, text=text, command=lambda cc=c: self._sort_online(cc))
            self.online_tree.column(c, width=width, anchor=anchor, stretch=(c in ("host", "mac")))
        self.online_tree.grid(row=0, column=0, sticky="nsew")
        ovs = ttk.Scrollbar(onf, orient="vertical", command=self.online_tree.yview)
        ovs.grid(row=0, column=1, sticky="ns")
        self.online_tree.configure(yscrollcommand=ovs.set)
        self.online_tree.tag_configure("alive", background="#e9f7ef", foreground="#12663a")
        self.online_tree.tag_configure("self", background="#eef2f7", foreground="#5b6b7c")
        # 双击「设备名称」列→就地改名字；双击其他列→还是复制 IP
        self.online_tree.bind("<Double-1>", self._on_online_double_click)

        # ---- 状态栏：进度条 + 状态 + 右下角总数统计，压成一行省纵向空间 ----
        status = ttk.Frame(outer)
        status.grid(row=4, column=0, sticky="ew", pady=(self._px(6), 0))
        status.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(status, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.stat_var = tk.StringVar(value="就绪 · 正在识别本机网段…")
        ttk.Label(status, textvariable=self.stat_var, style="Stat.TLabel").grid(
            row=0, column=1, sticky="w", padx=(self._px(10), 0))
        # 总数统计：窗口右下角
        self.stats_var = tk.StringVar(value="总数 0 ｜ 在线 0 ｜ 离线 0")
        ttk.Label(status, textvariable=self.stats_var, style="Stats.TLabel").grid(
            row=0, column=2, sticky="e", padx=(self._px(12), 0))

    # ---------------- 配置持久化 ----------------
    def _load_config(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.target_text.delete("1.0", "end")
            self.target_text.insert("1.0", cfg.get("target", "192.168.1.0/24"))
            self.mode_var.set(cfg.get("mode", "自动识别"))
            self.workers_var.set(int(cfg.get("workers", 100)))
            self.timeout_var.set(int(cfg.get("timeout", 800)))
            self.retry_var.set(int(cfg.get("retry", 2)))
            self.skip_self_var.set(bool(cfg.get("skip_self", True)))
            self.hostname_var.set(bool(cfg.get("hostname", False)))
            self.mac_var.set(bool(cfg.get("mac", True)))
            self.excl_wifi_var.set(bool(cfg.get("exclude_wifi", False)))
            # v2.1 起「只看网线直连」默认勾上。老配置里存的 False 是旧默认值，
            # 不算用户本意，所以不带 cfg_version（<2）的配置一律按新默认 True 处理；
            # 带版本的配置才尊重用户自己存的值。
            try:
                cfg_ver = int(cfg.get("cfg_version", 1))
            except Exception:
                cfg_ver = 1
            if cfg_ver >= 2:
                self.wired_only_var.set(bool(cfg.get("wired_only", True)))
            else:
                self.wired_only_var.set(True)
            # 手写的设备名称也记在配置里，下次打开还在（这张表优先级高于 DEVICE_NAMES）
            self.custom_names = {str(k): str(v) for k, v in (cfg.get("device_names") or {}).items()}
            self._on_mode_change()
        except Exception:
            pass
        self.target_text.bind("<KeyRelease>", self._on_target_edit)

    def _save_config(self):
        cfg = {
            "cfg_version": CFG_VERSION,
            "target": self.target_text.get("1.0", "end").strip(),
            "mode": self.mode_var.get(),
            "workers": self.workers_var.get(),
            "timeout": self.timeout_var.get(),
            "retry": self.retry_var.get(),
            "skip_self": self.skip_self_var.get(),
            "hostname": self.hostname_var.get(),
            "mac": self.mac_var.get(),
            "exclude_wifi": self.excl_wifi_var.get(),
            "wired_only": self.wired_only_var.get(),
            "device_names": self.custom_names,
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- 交互 ----------------
    def _on_mode_change(self, *_):
        mode = self.mode_var.get()
        # 提示后面统一附一句 /24 是什么意思，省得再猜斜杠后面的数字
        self.hint_var.set(MODE_HINTS.get(mode, MODE_HINTS["自动识别"]) + CIDR_HINT)

    def _on_card_resize(self, event):
        """按卡片实际宽度给两段提示文字设折行宽度（写死宽度的话窗口一拉就串行/被裁）。"""
        wrap = max(self._px(420), event.width - self._px(26))
        self.fmt_label.configure(wraplength=wrap)
        self.legend_label.configure(wraplength=wrap)

    def _show_format_help(self):
        """「格式说明」窗口：能写哪些格式、怎么写、展开多少个地址，一次列清楚。"""
        win = tk.Toplevel(self)
        win.title("输入格式说明")
        win.configure(bg="#f4f5f7")
        win.transient(self)
        body = ttk.Frame(win, padding=self._px(12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="① 能输入的写法（可以混着写，用 空格 / 逗号 / 分号 / 顿号 / 换行 分开）",
                  style="Stat.TLabel").grid(row=0, column=0, columnspan=2, sticky="w",
                                            pady=(0, self._px(4)))
        tv = ttk.Treeview(body, columns=("kind", "sample", "result"), show="headings",
                          height=len(INPUT_FORMATS))
        for col, (text, width, anchor) in {"kind": ("格式", 150, "w"),
                                           "sample": ("写法范例", 330, "w"),
                                           "result": ("展开后（实测）", 230, "w")}.items():
            tv.heading(col, text=text)
            tv.column(col, width=self._px(width), anchor=anchor, stretch=(col != "kind"))
        for kind, sample, result, _spec in INPUT_FORMATS:
            tv.insert("", "end", values=(kind, sample, result))
        tv.grid(row=1, column=0, columnspan=2, sticky="ew")

        ttk.Label(body, text="② 斜杠后面的数字（掩码位数）对照", style="Stat.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(self._px(10), self._px(3)))
        pairs = ["%s → %s 个（扫 %s 个）" % (m, total, scan) for m, total, scan in CIDR_TABLE]
        half = (len(pairs) + 1) // 2
        cidr_txt = "    ".join(pairs[:half]) + "\n" + "    ".join(pairs[half:])
        ttk.Label(body, text=cidr_txt, style="Card.TLabel", font=("Consolas", 9),
                  justify="left").grid(row=3, column=0, columnspan=2, sticky="w")

        ttk.Label(body, text="③ 注意事项", style="Stat.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(self._px(10), self._px(3)))
        ttk.Label(body, text="\n".join("· " + n for n in FORMAT_NOTES), style="Card.TLabel",
                  justify="left").grid(row=5, column=0, columnspan=2, sticky="w")

        self._btn(body, "知道了", win.destroy, "blue").grid(
            row=6, column=1, sticky="e", pady=(self._px(12), 0))

        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        # 居中：基准用 winfo_x/y（客户区坐标），不是 winfo_rootx/rooty（差一个标题栏）
        x = self.winfo_x() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_y() + max(0, (self.winfo_height() - h) // 4)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        try:
            win.grab_set()
        except tk.TclError:
            pass

    # ---------------- 地址显示区 ----------------
    def _fit_target_box(self, lines):
        """按内容行数调输入框高度（2~4 行）。本机有 7 个网段时，2 行高会让人
        以为只填进去了两条。"""
        self.target_text.configure(height=max(2, min(4, int(lines))))

    def _clear_target(self):
        self.target_text.delete("1.0", "end")
        self._fit_target_box(2)
        self._preview_grid()

    def _toggle_table(self):
        """展开 / 收起结果明细表。"""
        try:
            if self._table_shown:
                self.pane.forget(self.table_frame)
                self.btn_table.configure(text="显示明细表")
            else:
                self.pane.add(self.table_frame, weight=1)
                self.btn_table.configure(text="隐藏明细表")
                self.after(120, self._place_sash)
                self.after(400, self._place_sash)     # 布局稳定后再补一次
        except tk.TclError:
            return
        self._table_shown = not self._table_shown

    def _place_sash(self):
        """明细表展开后，把分隔条放在中间偏上：地址图留一半多，明细表也保证够看。"""
        try:
            h = self.pane.winfo_height()
            if h <= self._px(240):
                return
            top = min(int(h * 0.55), h - self._px(150))
            self.pane.sashpos(0, max(self._px(180), top))
        except tk.TclError:
            pass

    def _selected_nets(self):
        """本机 IP 列表里勾中的那些 IP 对应的网段；一个都没勾时按全选处理。"""
        nets = getattr(self, "_nets", [])
        if not nets:
            return []
        sel = self.local_list.curselection()
        if not sel:
            return nets
        return [nets[i] for i in sel if i < len(nets)]

    def _apply_nets_filter(self):
        """按「排除无线网卡网段」开关，决定本机 IP 列表里显示 / 可填入哪些网段。

        全量网段存在 self._all_nets；勾选开关后只保留有线网卡连的网段（WiFi 段去掉）。
        列表框、self._nets（填入本机网段 / 双击 / 整段扫描都读它）、状态栏提示都跟着更新。
        """
        all_nets = getattr(self, "_all_nets", [])
        excl = getattr(self, "excl_wifi_var", None)
        excl = excl.get() if excl is not None else False
        adapters = getattr(self, "_adapters", {})
        kept = []
        for net, ip in all_nets:
            kind = adapters.get(ip, ("", ""))[1]
            if excl and kind == "WiFi":
                continue
            kept.append((net, ip))
        self._nets = kept
        self.local_list.delete(0, "end")
        for net, ip in kept:
            self.local_list.insert("end", "%-15s → %s" % (ip, net))
        if kept:
            self.local_list.selection_set(0, "end")    # 默认全选
        else:
            self.local_list.insert("end", "未读到本机 IPv4")
        self._show_local_tip()

    def _local_double_click(self, event):
        """双击本机 IP 列表里的一行 → 把该行对应的网段填进下面的「目标地址 / 网段」。

        多选（Ctrl / Shift 勾了好几行）时双击，就把勾中的网段**全部**填进去，
        一行一个 —— 相当于「只想扫这几段」的快捷方式，不用再去点按钮。
        """
        nets_all = getattr(self, "_nets", [])
        if not nets_all:
            return "break"
        idx = self.local_list.nearest(event.y)
        if idx < 0 or idx >= len(nets_all):
            return "break"
        picked = self.local_list.curselection()
        if idx not in picked:                      # 双击没勾中的行，就以这一行为准
            self.local_list.selection_clear(0, "end")
            self.local_list.selection_set(idx)
            picked = (idx,)
        picked = sorted({i for i in picked if 0 <= i < len(nets_all)})
        chosen = [nets_all[i][0] for i in picked] or [nets_all[idx][0]]

        self.target_text.delete("1.0", "end")
        self._fit_target_box(len(chosen))
        self.target_text.insert("1.0", "\n".join(chosen))
        self.mode_var.set("多网段批量" if len(chosen) > 1 else "整个网段(CIDR)")
        self._on_mode_change()
        self._preview_grid()
        self.stat_var.set("已填入 %d 个网段：%s（直接点「开始扫描」即可）"
                          % (len(chosen), "、".join(chosen)))
        return "break"

    # ---------------- 仅显示在线 IP ----------------
    def _add_pane_first(self, w):
        """把 w 放到主区最上面那一格（明细表展开时也要在它前面）。

        注意顺序：必须先 add/insert 再 forget 另一个，倒过来做的话中间会出现
        「一个 pane 都没有」的空档，此时 insert(0) 会报 Slave index 0 out of bounds。
        """
        if self.pane.panes():
            self.pane.insert(0, w, weight=1)
        else:
            self.pane.add(w, weight=1)

    def _toggle_online_view(self):
        """主区在「地址图」和「在线设备列表」之间来回切换。"""
        try:
            if self.online_view:
                self._add_pane_first(self.addr_grid)
                self.pane.forget(self.online_frame)
                self.btn_online.configure(text="仅显示在线 IP")
                self.online_view = False
            else:
                self._add_pane_first(self.online_frame)
                self.pane.forget(self.addr_grid)
                self.btn_online.configure(text="← 返回地址图")
                self.online_view = True
                self._render_online()
            if self._table_shown:
                self.after(120, self._place_sash)
        except tk.TclError:
            return

    def _alive_sorted(self):
        """在线 IP，按数值大小从小到大排。

        不能直接按字符串排：那样 192.168.1.10 会排在 192.168.1.9 前面。
        """
        ips = [ip for ip in self.order if self.rows.get(ip, {}).get("alive")]
        ips.sort(key=_ip_key)
        return ips

    # ---------------- 只看网线直连（隐藏经无线网卡绕进来的结果） ----------------
    def _wifi_src(self, ip):
        """这个地址是不是经无线网卡（默认网关）回来的。

        nic_of 里的类型来自系统自己报告的网卡类型（802.11 就是无线），不是猜的。
        """
        return self.nic_of.get(ip, ("", ""))[1] == "WiFi"

    def _hidden(self, ip):
        """勾了「只看网线直连」后，这个地址要不要藏起来。"""
        var = getattr(self, "wired_only_var", None)
        return bool(var is not None and var.get() and self._wifi_src(ip))

    def _wifi_alive_count(self):
        """在线里有多少个是经无线网卡拿到的（不勾开关也统计，好让用户知道）。

        直接遍历 rows 不排序 —— 边扫边被 _refresh_stats 调用，别在里面做多余的排序。
        """
        return sum(1 for ip, r in self.rows.items()
                   if r.get("alive") and self._wifi_src(ip))

    def _alive_visible(self):
        """在线且当前要显示的地址 —— 导出也读它，保证「看到的 = 导出的」。"""
        return [ip for ip in self._alive_sorted() if not self._hidden(ip)]

    def _on_wired_only(self):
        """切换「只看网线直连」：明细表 / 在线列表 / 地址图 / 统计 一起刷新。"""
        # 地址图里已画出的所有目标重新判一次隐藏（含本次没画出来的段不管）
        self.addr_grid.set_hidden_ips(
            {ip for ip in self.addr_grid._items if self._hidden(ip)})
        self._render_all()
        self._render_online()
        self._refresh_stats()
        n = self._wifi_alive_count()
        if self.wired_only_var.get():
            self.stat_var.set("已隐藏 %d 个经无线网卡（默认网关）拿到的地址 —— "
                              "它们不在本机网线上，是按默认路由绕过去的。" % n)
        elif n:
            self.stat_var.set("已显示全部结果；其中 %d 个是经无线网卡（默认网关）拿到的，"
                              "不在本机网线上。" % n)
        else:
            self.stat_var.set("已显示全部结果（都在本机网线上）。")

    def _render_online(self):
        """重建在线设备列表：只列在线、按 IP 大小排序、设备名称自动填。"""
        self.online_tree.delete(*self.online_tree.get_children())
        for ip in self._alive_visible():
            self._insert_online(ip, self.rows[ip])

    def _insert_online(self, ip, res):
        ms = res["ms"]
        latency = "<1" if (ms is not None and ms < 1) else ("—" if ms is None else "%.0f" % ms)
        tag = "self" if ip in self.local_ips else "alive"
        if self.online_tree.exists(ip):
            self.online_tree.delete(ip)
        self.online_tree.insert("", "end", iid=ip, tags=(tag,), values=(
            self._disp_name(ip),
            ip, self._nic_text(ip), latency,
            "" if res["ttl"] is None else str(res["ttl"]),
            res.get("host") or "",
            self.arp_table.get(ip, "")))

    def _nic_text(self, ip):
        """结果里「出口网卡」那一列显示什么。没算过就留空。"""
        return self.nic_of.get(ip, ("—", ""))[0]

    def _sort_online(self, col):
        """在线列表点表头排序（IP 这一列一律按数值大小排）。"""
        ips = self._alive_visible()
        if not ips:
            return
        keymap = {
            "name": lambda ip: (self._disp_name(ip) or "~"),
            "ip": _ip_key,
            "latency": lambda ip: (self.rows[ip]["ms"] if self.rows[ip]["ms"] is not None else 99999),
            "ttl": lambda ip: (self.rows[ip]["ttl"] if self.rows[ip]["ttl"] is not None else -1),
            "host": lambda ip: (self.rows[ip].get("host") or "~"),
            "mac": lambda ip: (self.arp_table.get(ip) or "~"),
            "nic": lambda ip: (self._nic_text(ip) or "~"),
        }
        ips.sort(key=keymap.get(col, _ip_key), reverse=col in ("latency", "ttl"))
        self.online_tree.delete(*self.online_tree.get_children())
        for ip in ips:
            self._insert_online(ip, self.rows[ip])

    # ---------------- 在线列表：手写设备名称 ----------------
    def _disp_name(self, ip):
        """在线列表 / 导出用的设备名：手写的优先 → 常用设备表 → 主机名。"""
        return (self.custom_names.get(ip) or device_name(ip)
                or (self.rows.get(ip, {}).get("host") or ""))

    def _on_online_double_click(self, event):
        """双击「设备名称」那一格 → 就地改名；双击其他列 → 复制 IP（原行为）。"""
        tree = self.online_tree
        row = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if row and col == "#1" and tree.identify_region(event.x, event.y) == "cell":
            self._edit_online_name(row)
            return "break"               # 拦下这次双击，别再触发复制
        self._copy_selected(tree)

    def _edit_online_name(self, ip):
        """在单元格上浮一个输入框手写设备名称。

        ttk.Treeview 没有单元格编辑，只能先用 bbox() 量出这一格的坐标，
        再把 Entry 用 place() 盖上去。回车或点到别处提交，Esc 放弃。
        """
        tree = self.online_tree
        self._commit_online_name()       # 上一个还没收尾的先提交
        if not tree.exists(ip):
            return
        bbox = tree.bbox(ip, "#1")
        if not bbox:
            return
        x, y, w, h = bbox
        vals = tree.item(ip, "values")
        var = tk.StringVar(value=(vals[0] if vals else ""))
        ent = tk.Entry(tree, textvariable=var, font=("Microsoft YaHei UI", 9),
                       relief="solid", borderwidth=1, highlightthickness=0,
                       bg="#fffceb", fg="#1f2328", insertbackground="#1f2328")
        ent.place(x=x, y=y, width=w, height=h)
        ent.focus_set()
        ent.select_range(0, "end")
        self._name_edit = (ip, var, ent)
        ent.bind("<Return>", self._on_name_enter)
        ent.bind("<Escape>", self._cancel_online_name)
        ent.bind("<FocusOut>", self._on_name_enter)

    def _on_name_enter(self, _event=None):
        self._commit_online_name()
        return "break"

    def _cancel_online_name(self, _event=None):
        cur = self._name_edit
        self._name_edit = None           # 先清掉，免得 destroy 触发的 FocusOut 又提交一次
        if cur:
            try:
                cur[2].destroy()
            except Exception:
                pass
        return "break"

    def _commit_online_name(self):
        """把输入框里的名字写到行上，并记进配置（导出设备表用的就是它）。"""
        cur = self._name_edit
        if not cur:
            return
        self._name_edit = None
        ip, var, ent = cur
        try:
            text = var.get().strip()
        except Exception:
            text = ""
        try:
            ent.destroy()
        except Exception:
            pass
        if text:
            self.custom_names[ip] = text
        else:
            self.custom_names.pop(ip, None)      # 清空 = 退回自动命名
        shown = text or self._disp_name(ip)
        if self.online_tree.exists(ip):
            vals = list(self.online_tree.item(ip, "values"))
            vals[0] = shown
            self.online_tree.item(ip, values=vals)
        self._save_config()
        self.stat_var.set("设备名称已保存：%s → %s（导出设备表会带上这个名字）"
                          % (ip, shown or "（空）"))

    def _copy_selected(self, tree):
        """双击行把勾中的 IP 复制到剪贴板（多选时一行一个）。"""
        sel = tree.selection()
        if not sel:
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(sel))
        if len(sel) > 1:
            self.stat_var.set("已复制 %d 个 IP 到剪贴板" % len(sel))
        else:
            self.stat_var.set("已复制 %s 到剪贴板" % sel[0])

    def _on_target_edit(self, _event=None):
        """目标输入变化后，稍等一下再刷新地址图（防抖，别每敲一个字就重画）。"""
        if self._preview_job:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.after(700, self._preview_grid)

    def _preview_grid(self):
        """按当前输入的目标，先把地址图铺出来（还没扫也能看到整个网段的格子）。"""
        self._preview_job = None
        text = self.target_text.get("1.0", "end")
        try:
            ips, _err = parse_targets(text)
        except Exception:
            ips = []
        self.total = len(ips)
        self.grid_total = len(ips)
        if not ips:
            self.addr_grid.set_targets([])
        elif len(ips) > AddressGrid.MAX_TILES * AddressGrid.MAX_GROUPS:
            self.addr_grid.set_targets([], "目标太多（%d 个），地址图不显示" % len(ips))
        else:
            self.addr_grid.set_targets(ips)
        self._refresh_stats()

    def _refresh_stats(self):
        """右下角的总数统计：总数按地址图上的格子数算，本机单独一档。"""
        total = self.grid_total
        scanned = len(self.rows)
        alive = self.alive_count
        local_only = sum(1 for ip in self.local_ips
                         if ip in self.addr_grid._items and ip not in self.rows)
        wifi_alive = self._wifi_alive_count()
        parts = ["总数 %d" % total,
                 ("在线 %d" % alive) + ("（经无线 %d）" % wifi_alive if wifi_alive else ""),
                 "离线 %d" % (scanned - alive)]
        if local_only:
            parts.append("本机 %d" % local_only)
        pending = total - scanned - local_only
        if pending > 0:
            parts.append("未扫 %d" % pending)
        self.stats_var.set(" ｜ ".join(parts))

    def _detect_local(self):
        try:
            nets = local_networks()
        except Exception:
            nets = []
        self.q.put(("local", nets))
        self.local_ready.set()

    def _show_local_tip(self):
        """状态栏说明读到的本机地址，以及当前勾了几个。"""
        nets = getattr(self, "_nets", [])
        if not nets:
            self.stat_var.set("就绪 · 未读到本机 IPv4 地址（可能只有回环网卡）")
            return
        picked = self._selected_nets()
        if len(nets) == 1:
            self.stat_var.set("就绪 · 本机网段 %s（本机 %s）" % (nets[0][0], nets[0][1]))
        elif len(picked) == len(nets):
            self.stat_var.set("就绪 · 本机 %d 个 IP（全选）→ %d 个网段"
                              % (len(nets), len({n[0] for n in nets})))
        else:
            self.stat_var.set("就绪 · 本机 %d 个 IP，已勾 %d 个 → %d 个网段"
                              % (len(nets), len(picked), len({n[0] for n in picked})))

    def _fill_local(self):
        """把勾中的本机 IP 对应的网段填进目标框（勾了多个就是多网段批量模式）。"""
        nets = self._selected_nets()
        if not nets:
            messagebox.showinfo("提示", "没有读到本机 IPv4 地址（可能只有回环网卡）。", parent=self)
            return
        specs = list(dict.fromkeys(n[0] for n in nets))     # 去重，保持顺序
        self.target_text.delete("1.0", "end")
        self._fit_target_box(len(specs))
        if len(specs) == 1:
            self.target_text.insert("1.0", specs[0])
        else:
            self.target_text.insert("1.0", "\n".join(specs))
            self.mode_var.set("多网段批量")
            self._on_mode_change()
        self._preview_grid()

    def _one_click_scan_local(self):
        """把本机所有网段填进目标框，然后立刻开扫。"""
        if not getattr(self, "_nets", []):
            messagebox.showinfo("提示", "没有读到本机 IPv4 地址。", parent=self)
            return
        self._fill_local()
        self.start_scan()

    def _on_row_double_click(self, _event):
        self._copy_selected(self.tree)

    # ---------------- 扫描 ----------------
    def start_scan(self):
        if self.scanning:
            return
        text = self.target_text.get("1.0", "end")
        ips, err = parse_targets(text)
        if err:
            messagebox.showerror("输入有问题", err, parent=self)
            if not ips:
                return
        if not ips:
            messagebox.showwarning("提示", "没有解析到任何 IP。", parent=self)
            return

        # 地址图按「完整目标」铺（本机也画出来，标成本机色），扫描时才跳过本机
        self.addr_grid.set_targets(ips)
        self.grid_total = len(ips)
        self._refresh_stats()

        if self.skip_self_var.get():
            if not self.local_ready.is_set():
                # 后台的本机网段识别还没回来（比如刚打开就点了扫描）。
                # 这里同步补一次，否则「跳过本机」会静默失效，本机地址会被当成普通目标扫。
                self.stat_var.set("正在识别本机网段…")
                self.update_idletasks()
                try:
                    nets = local_networks()
                    self.local_ips = {n[1] for n in nets}
                    self.addr_grid.set_local(self.local_ips)
                except Exception:
                    pass
            ips = [ip for ip in ips if ip not in self.local_ips]
        if not ips:
            messagebox.showinfo("提示", "目标全部是本机地址，已全部跳过。", parent=self)
            return

        if len(ips) > 4096:
            if not messagebox.askyesno(
                "确认", "本次将扫描 %d 个地址，可能需要较长时间。确定继续？" % len(ips), parent=self
            ):
                return

        self._save_config()
        self.clear_results()
        # 先算出每个目标会走哪块网卡（问系统选路，不发额外包），
        # 结果表里那列「出口网卡」读的就是它，所以必须在结果进来之前算好。
        try:
            self.nic_of = build_nic_map(ips)
        except Exception:
            self.nic_of = {}
        # 地址图也要吃「只看网线直连」：勾上时，经无线网卡（默认网关）的目标在图上画「已隐藏」灰，
        # 不再亮成在线绿 —— 否则顶部地址图会绕过过滤，看着像"WiFi 设备还在"。
        self.addr_grid.set_hidden_ips({ip for ip in ips if self._hidden(ip)})
        self.stop_event.clear()
        self.scanning = True
        self.total = len(ips)
        self.started_at = time.time()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.configure(maximum=self.total, value=0)
        self.stat_var.set("扫描中…  目标 %d 个" % self.total)

        opts = {
            "timeout": max(100, int(self.timeout_var.get())),
            "retry": max(0, int(self.retry_var.get())),
            "workers": max(1, min(512, int(self.workers_var.get()))),
            "hostname": self.hostname_var.get(),
        }
        if opts["hostname"]:
            socket.setdefaulttimeout(1.2)
        threading.Thread(target=self._scan_worker, args=(ips, opts), daemon=True).start()

    def stop_scan(self):
        if self.scanning:
            self.stop_event.set()
            self.stat_var.set("正在停止…")

    def _scan_worker(self, ips, opts):
        done = alive = 0
        try:
            with ThreadPoolExecutor(max_workers=opts["workers"]) as ex:
                futures = {ex.submit(self._probe, ip, opts): ip for ip in ips}
                for fut in as_completed(futures):
                    if self.stop_event.is_set():
                        for f in futures:
                            f.cancel()
                        break
                    ip = futures[fut]
                    try:
                        res = fut.result()
                    except Exception as e:
                        res = {"ip": ip, "alive": False, "ms": None, "ttl": None, "host": "", "err": str(e)}
                    done += 1
                    if res["alive"]:
                        alive += 1
                    self.q.put(("result", res))
                    if done % 5 == 0 or done == len(ips):
                        self.q.put(("progress", (done, len(ips), alive, time.time() - self.started_at)))
        except Exception as e:
            self.q.put(("fatal", str(e)))
        self.q.put(("done", (done, len(ips), alive, time.time() - self.started_at, self.stop_event.is_set())))

    def _probe(self, ip, opts):
        res = {"ip": ip, "alive": False, "ms": None, "ttl": None, "host": ""}
        if self.stop_event.is_set():
            return res
        for attempt in range(opts["retry"] + 1):
            ok, ms, ttl = ping_once(ip, opts["timeout"])
            if ok:
                res["alive"], res["ms"], res["ttl"] = True, ms, ttl
                break
        if res["alive"] and opts["hostname"]:
            try:
                res["host"] = socket.gethostbyaddr(ip)[0]
            except Exception:
                res["host"] = ""
        return res

    # ---------------- 结果渲染 ----------------
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "local":
                    self._all_nets = payload
                    self._adapters = local_adapters()
                    self.local_ips = {n[1] for n in payload}   # 全量：供跳过本机 / 地址图高亮
                    self.addr_grid.set_local(self.local_ips)
                    self._apply_nets_filter()                  # 按「排除无线网卡网段」生成列表
                elif kind == "result":
                    self._add_row(payload)
                elif kind == "progress":
                    done, total, alive, elapsed = payload
                    self.progress.configure(value=done)
                    self.stat_var.set(self._stat_text(done, total, alive, elapsed, False))
                    self._refresh_stats()
                elif kind == "done":
                    done, total, alive, elapsed, stopped = payload
                    self.progress.configure(value=done)
                    self.stat_var.set(self._stat_text(done, total, alive, elapsed, stopped))
                    self._refresh_stats()
                    self._finish_scan()
                elif kind == "arp":
                    self.arp_table = payload
                    self._apply_arp()
                elif kind == "fatal":
                    messagebox.showerror("扫描出错", payload, parent=self)
                    self._finish_scan()
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    @staticmethod
    def _stat_text(done, total, alive, elapsed, stopped):
        head = "已停止" if stopped else ("完成" if done >= total else "扫描中")
        return ("%s · 目标 %d · 已扫 %d · 在线 %d · 离线 %d · 进度 %.1f%% · 耗时 %.1f s"
                % (head, total, done, alive, done - alive, done * 100.0 / max(1, total), elapsed))

    def _add_row(self, res):
        ip = res["ip"]
        if ip in self.rows:
            return
        self.rows[ip] = res
        self.order.append(ip)
        if res["alive"]:
            self.alive_count += 1
        self.addr_grid.apply_result(res)
        self._refresh_stats()
        if self.online_view and res["alive"] and not self._hidden(ip):
            self._insert_online(ip, res)     # 正在看在线列表时，边扫边往上加
        if self.alive_only_var.get() and not res["alive"]:
            return
        if self._hidden(ip):
            return                           # 勾了「只看网线直连」，明细表里也不列
        self._insert_tree(ip, res)

    def _insert_tree(self, ip, res):
        if res["alive"]:
            tag = "self" if ip in self.local_ips else "alive"
            status = "本机" if ip in self.local_ips else "在线"
            ms = res["ms"]
            latency = "<1" if (ms is not None and ms < 1) else ("—" if ms is None else "%.0f" % ms)
            ttl = "" if res["ttl"] is None else str(res["ttl"])
        else:
            tag, status, latency, ttl = "dead", "离线", "—", ""
        self.tree.insert("", "end", iid=ip, tags=(tag,),
                         values=(ip, status, self._nic_text(ip), latency, ttl,
                                 res.get("host") or "",
                                 self.arp_table.get(ip, "")))

    def _render_all(self):
        self.tree.delete(*self.tree.get_children())
        for ip in self.order:
            res = self.rows[ip]
            if self.alive_only_var.get() and not res["alive"]:
                continue
            if self._hidden(ip):
                continue
            self._insert_tree(ip, res)

    def _sort_by(self, col):
        """点表头排序。"""
        items = list(self.rows.values())
        if not items:
            return
        keymap = {
            "ip": lambda r: int(ipaddress.IPv4Address(r["ip"])),
            "status": lambda r: (not r["alive"], int(ipaddress.IPv4Address(r["ip"]))),
            "latency": lambda r: (r["ms"] if r["ms"] is not None else 99999),
            "ttl": lambda r: (r["ttl"] if r["ttl"] is not None else -1),
            "host": lambda r: (r.get("host") or "~"),
            "mac": lambda r: (self.arp_table.get(r["ip"]) or "~"),
            "nic": lambda r: (self._nic_text(r["ip"]) or "~"),
        }
        reverse = col in ("latency", "ttl")
        items.sort(key=keymap.get(col, keymap["ip"]), reverse=reverse)
        self.order = [r["ip"] for r in items]
        self._render_all()

    def _apply_arp(self):
        # 列的顺序可能调整，MAC 的下标按列名查，别写死，否则加列就错位
        mi = self.MAIN_COLS.index("mac")
        oi = self.ONLINE_COLS.index("mac")
        for ip, mac in self.arp_table.items():
            if self.tree.exists(ip):
                vals = list(self.tree.item(ip, "values"))
                vals[mi] = mac
                self.tree.item(ip, values=vals)
            if self.online_tree.exists(ip):
                vals = list(self.online_tree.item(ip, "values"))
                vals[oi] = mac
                self.online_tree.item(ip, values=vals)

    def refresh_arp(self):
        self.arp_table = read_arp_table()
        self._apply_arp()
        self.stat_var.set("已从 ARP 缓存读取 %d 条记录" % len(self.arp_table))

    def _finish_scan(self):
        self.scanning = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if self.sort_var.get():
            self.order.sort(key=_ip_key)
            self._render_all()
        self._render_online()     # 在线列表重新按 IP 大小排一遍
        # 明说一句：这次在线的设备里有多少其实是经无线网卡（默认网关）绕进来的。
        # 它们并不在本机网线上 —— 关掉 WiFi 就搜不到了，别当成网线上的设备。
        total_alive = len(self._alive_sorted())
        n = self._wifi_alive_count()
        if n and self.wired_only_var.get():
            self.stat_var.set("完成 · 在线 %d 个，已隐藏 %d 个经无线网卡（默认网关）的，"
                              "当前显示 %d 个" % (total_alive, n, total_alive - n))
        elif n:
            self.stat_var.set("完成 · 在线 %d 个，其中 %d 个是经无线网卡（默认网关）拿到的，"
                              "不在本机网线上" % (total_alive, n))
        elif total_alive:
            self.stat_var.set("完成 · 在线 %d 个（都在本机网线上）" % total_alive)
        # 结束后补读一次 ARP，让在线设备带上 MAC（仅同广播域有效）
        if self.mac_var.get():
            threading.Thread(target=lambda: self.q.put(("arp", read_arp_table())), daemon=True).start()

    def clear_results(self):
        self.tree.delete(*self.tree.get_children())
        self.online_tree.delete(*self.online_tree.get_children())
        self.rows.clear()
        self.order.clear()
        self.nic_of.clear()
        self.alive_count = 0
        self.progress.configure(value=0)
        self.addr_grid.set_hidden_ips(set())
        self.addr_grid.reset_states()
        self._refresh_stats()

    # ---------------- 导出 / 复制 ----------------
    def export_device_table(self):
        """扫描完成后，把在线设备导成三列表格：设备名称 / IP地址/串口 / 备注。

        设备名称取 _disp_name()：在线列表里手写过的名字优先，
        其次是文件开头 DEVICE_NAMES 常用设备表，最后退到主机名；
        IP 一律按数值大小排序（不是字符串），避免 .10 排到 .9 前面。
        """
        alive = self._alive_visible()
        if not alive:
            messagebox.showinfo("提示", "还没有在线设备，先扫描一次吧。", parent=self)
            return

        stamp = time.strftime("%m%d_%H%M")
        path = filedialog.asksaveasfilename(
            parent=self, title="导出在线设备表",
            defaultextension=".xlsx", initialfile="在线设备表_%s.xlsx" % stamp,
            filetypes=[("Excel 工作簿", "*.xlsx"), ("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return

        # 「出口网卡」追加在最末一列，前面三列顺序保持不动，
        # 下游按设备名称 / IP / 备注来读的表不受影响。
        headers = ["设备名称", "IP地址/串口", "备注", "出口网卡"]
        rows = [(self._disp_name(ip), ip, "", self._nic_text(ip)) for ip in alive]
        try:
            if path.lower().endswith(".csv"):
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(headers)
                    w.writerows(rows)
            else:
                write_xlsx(path, headers, rows, "在线设备", widths=(26, 20, 34, 18))
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)
            return

        self.stat_var.set("已导出 %d 台在线设备到 %s" % (len(rows), path))
        hidden = len(self._alive_sorted()) - len(rows)
        tail = ("\n（已按「只看网线直连」隐藏 %d 台经无线网卡/默认网关拿到的设备）" % hidden
                if hidden else "")
        if messagebox.askyesno(
                "导出成功",
                "已导出 %d 台在线设备（设备名称 / IP地址/串口 / 备注 / 出口网卡）。%s\n是否打开所在文件夹？"
                % (len(rows), tail),
                parent=self):
            try:
                os.startfile(os.path.dirname(path))
            except Exception:
                pass

    def export_csv(self):
        if not self.rows:
            messagebox.showinfo("提示", "还没有结果可以导出。", parent=self)
            return
        # 导出的范围跟着当前显示走：勾了「只看网线直连」就不导经无线绕进来的那些
        order = [ip for ip in self.order if not self._hidden(ip)]
        if not order:
            messagebox.showinfo("提示", "当前显示范围内没有结果可以导出。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="导出扫描结果",
            defaultextension=".csv", initialfile="ping_result.csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["IP 地址", "状态", "出口网卡", "延迟(ms)", "TTL", "主机名", "MAC 地址"])
                for ip in order:
                    r = self.rows[ip]
                    ms = r["ms"]
                    w.writerow([
                        ip,
                        "在线" if r["alive"] else "离线",
                        self._nic_text(ip),
                        "" if ms is None else ("<1" if ms < 1 else "%.0f" % ms),
                        "" if r["ttl"] is None else r["ttl"],
                        r.get("host") or "",
                        self.arp_table.get(ip, ""),
                    ])
            self.stat_var.set("已导出 %d 条记录到 %s" % (len(order), path))
            if messagebox.askyesno("导出成功", "已导出 %d 条记录。\n是否打开所在文件夹？" % len(order), parent=self):
                try:
                    os.startfile(os.path.dirname(path))
                except Exception:
                    pass
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self)

    def copy_alive(self):
        ips = [ip for ip in self.order if self.rows[ip]["alive"]]
        if not ips:
            messagebox.showinfo("提示", "当前没有在线 IP。", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(ips))
        self.stat_var.set("已复制 %d 个在线 IP 到剪贴板" % len(ips))

    def _on_close(self):
        self.stop_event.set()
        self._save_config()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
