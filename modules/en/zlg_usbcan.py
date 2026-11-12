# -*- coding: utf-8 -*-
"""
ZLG USBCAN-2E-U (CAN-2E-U) USB CAN 盒驱动 —— 双后端
接口与 UT6502Driver 对齐。

后端 1：ControlCAN.dll  (VCI_*，老驱动 / 兼容层)
后端 2：zlgcan.dll      (ZCAN_*，ZIGCAN 新驱动 —— 设备管理器出现 ZIGCAN 时用这个)

两块 CAN 卡插同一台电脑时用「设备序号」区分（0=第一块，1=第二块）。
"""
import ctypes
import os
import sys
import threading
import time
from collections import deque
from ctypes import (
    POINTER, Structure, byref, c_char_p, c_ubyte, c_uint, c_int,
    c_uint64, c_void_p, windll,
)

STATUS_OK = 1
# USBCAN-2E-U=21, USBCAN-E-U=20 优先；其余兜底
DEV_TYPES = (21, 20, 4, 3, 31, 34)

BAUD_TABLE = {
    5: (0xBF, 0xFF), 10: (0x31, 0x1C), 20: (0x18, 0x1C), 40: (0x87, 0xFF),
    50: (0x09, 0x1C), 80: (0x83, 0xFF), 100: (0x04, 0x1C), 125: (0x03, 0x1C),
    200: (0x81, 0xFA), 250: (0x01, 0x1C), 400: (0x80, 0xFA), 500: (0x00, 0x1C),
    800: (0x00, 0x16), 1000: (0x00, 0x14),
}

# flags 位: bit0=扩展帧, bit1=远程帧
FLAG_EXT, FLAG_RTR = 0x01, 0x02


class VCI_INIT_CONFIG(Structure):
    _fields_ = [
        ("AccCode", c_uint), ("AccMask", c_uint), ("Reserved", c_uint),
        ("Filter", c_ubyte), ("Timing0", c_ubyte), ("Timing1", c_ubyte),
        ("Mode", c_ubyte),
    ]


class VCI_CAN_OBJ(Structure):
    _fields_ = [
        ("ID", c_uint), ("TimeStamp", c_uint), ("TimeFlag", c_ubyte),
        ("SendType", c_ubyte), ("RemoteFlag", c_ubyte), ("ExternFlag", c_ubyte),
        ("DataLen", c_ubyte), ("Data", c_ubyte * 8), ("Reserved", c_ubyte * 3),
    ]


# ---- zlgcan (ZCAN_*) 结构体（官方 zlgcan.h / canframe.h）----
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ID_MASK = 0x1FFFFFFF


class ZCAN_CHANNEL_INIT_CONFIG(Structure):
    class _CAN(Structure):
        _fields_ = [
            ("acc_code", c_uint), ("acc_mask", c_uint), ("reserved", c_uint),
            ("filter", c_ubyte), ("timing0", c_ubyte), ("timing1", c_ubyte),
            ("mode", c_ubyte),
        ]

    _fields_ = [
        ("can_type", c_uint),  # 0=CAN, 1=CANFD
        ("can", _CAN),
    ]


class can_frame(Structure):
    _fields_ = [
        ("can_id", c_uint),
        ("can_dlc", c_ubyte),
        ("__pad", c_ubyte),
        ("__res0", c_ubyte),
        ("__res1", c_ubyte),
        ("data", c_ubyte * 8),
    ]


class ZCAN_Transmit_Data(Structure):
    _fields_ = [("frame", can_frame), ("transmit_type", c_uint)]


class ZCAN_Receive_Data(Structure):
    _fields_ = [("frame", can_frame), ("timestamp", c_uint64)]


ZCAN_Receive_Data_Array = ZCAN_Receive_Data * 64


# --------------------------------------------------------------- 路径收集 ----
def candidate_dll_paths(dll_name="ControlCAN.dll"):
    here = os.path.dirname(os.path.abspath(__file__))
    pkg_root = os.path.dirname(here)
    proj_root = os.path.dirname(pkg_root)
    frozen = getattr(sys, "frozen", False)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if frozen else proj_root
    meipass = getattr(sys, "_MEIPASS", exe_dir)
    windir = os.environ.get("WINDIR", r"C:\Windows")
    env_candidates = [
        os.path.join(windir, "System32", dll_name),
        os.path.join(windir, "SysWOW64", dll_name),
        r"C:\Program Files\ZLG\USB_CAN\%s" % dll_name,
        r"C:\Program Files\ZLG\USB_CAN64\%s" % dll_name,
        r"C:\Program Files\ZLG\ZLG_CAN\%s" % dll_name,
        r"C:\Program Files\ZLG\ZLG_CAN64\%s" % dll_name,
        r"C:\Program Files\ZLG\ZLGCAN\%s" % dll_name,
        r"C:\Program Files\ZLG\CANFDNET\%s" % dll_name,
        r"C:\Program Files (x86)\ZLG\USB_CAN\%s" % dll_name,
        r"C:\Program Files (x86)\ZLG\ZLG_CAN\%s" % dll_name,
        r"C:\Program Files (x86)\ZLG\ZLGCAN\%s" % dll_name,
        r"C:\Program Files (x86)\USB_CAN TOOL\%s" % dll_name,
        r"C:\Program Files (x86)\InfyComm\%s" % dll_name,
        r"C:\Program Files\ZLG\ZLG_USBCAN\%s" % dll_name,
    ]
    local_candidates = [
        os.path.join(exe_dir, "assets", dll_name),
        os.path.join(meipass, "assets", dll_name),
        os.path.join(proj_root, "assets", dll_name),
        os.path.join(here, dll_name),
        os.path.join(exe_dir, dll_name),
    ]
    out, seen = [], set()
    for p in local_candidates + env_candidates:
        p = os.path.normpath(p) if p else ""
        if p and p not in seen and os.path.isfile(p):
            seen.add(p)
            out.append(p)
    # 兜底：全盘扫描到的同名文件（懒扫描，一次）
    try:
        for p in scan_zlg_files():
            if os.path.basename(p).lower() == dll_name.lower() and p not in seen:
                seen.add(p)
                out.append(p)
    except Exception:
        pass
    return out


def scan_zlg_files(extra_dirs=None):
    """在常见目录里找 zlg*/ControlCAN 相关文件（含驱动目录）。"""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    roots = extra_dirs or []
    roots += [
        os.path.join(windir, "System32"),
        os.path.join(windir, "SysWOW64"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\Users\Public\Documents",
        r"C:\Users\Public",
        "D:\\",
        "E:\\",
        "F:\\",
    ]
    keys = ("zlgcan", "controlcan", "zlgkernl", "usbcandrv", "zlg_usb")
    found = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        # 目录本身下一层（含 ZLG* 子目录）
        for name in entries:
            low = name.lower()
            full = os.path.join(root, name)
            if os.path.isfile(full) and any(k in low for k in keys) and low.endswith((".dll", ".sys", ".lib")):
                found.append(full)
            elif os.path.isdir(full) and ("zlg" in low or "can" in low):
                # 深入一层找 dll/sys
                try:
                    for sub in os.listdir(full):
                        low2 = sub.lower()
                        if any(k in low2 for k in keys) and low2.endswith((".dll", ".sys", ".lib")):
                            found.append(os.path.join(full, sub))
                        elif os.path.isdir(os.path.join(full, sub)):
                            # 再深一层
                            try:
                                for sub2 in os.listdir(os.path.join(full, sub)):
                                    low3 = sub2.lower()
                                    if any(k in low3 for k in keys) and low3.endswith((".dll", ".sys", ".lib")):
                                        found.append(os.path.join(full, sub, sub2))
                            except OSError:
                                pass
                except OSError:
                    pass
    return sorted(set(found))


def _is_x64(path):
    try:
        with open(path, "rb") as f:
            f.seek(0x3C)
            pe = int.from_bytes(f.read(4), "little")
            f.seek(pe + 4)
            machine = int.from_bytes(f.read(2), "little")
        return machine == 0x8664
    except Exception:
        return False


def _load_dll(path):
    return windll.LoadLibrary(path)


# --------------------------------------------------------------- VCI 后端 ----
class VciBackend:
    name = "ControlCAN/VCI"

    def __init__(self, dll, path):
        self.dll, self.path = dll, path
        self.dtype, self.dev, self.can = 21, 0, 0

    def open(self, dtype, dev, can):
        ret = self.dll.VCI_OpenDevice(dtype, dev, 0)
        if ret != STATUS_OK:
            return False, "VCI_OpenDevice(%d,%d)=%s" % (dtype, dev, ret)
        self.dtype, self.dev, self.can = dtype, dev, can
        return True, "VCI_OpenDevice(%d,%d) OK" % (dtype, dev)

    def init_start(self, baud):
        t0, t1 = BAUD_TABLE.get(baud, (0x03, 0x1C))
        cfg = VCI_INIT_CONFIG(0x80000000, 0xFFFFFFFF, 0, 0, t0, t1, 0)
        r1 = self.dll.VCI_InitCAN(self.dtype, self.dev, self.can, byref(cfg))
        if r1 != STATUS_OK:
            return False, "VCI_InitCAN(ch=%d,%dk)=%s" % (self.can, baud, r1)
        r2 = self.dll.VCI_StartCAN(self.dtype, self.dev, self.can)
        return r2 == STATUS_OK, "VCI_StartCAN=%s" % r2

    def transmit(self, can_id, data, ext, rtr):
        dlc = min(len(data), 8)
        pad = data[:dlc] + b"\x00" * (8 - dlc)
        obj = VCI_CAN_OBJ(can_id & 0xFFFFFFFF, 0, 0, 0,
                          1 if rtr else 0, 1 if ext else 0,
                          dlc, (c_ubyte * 8)(*pad), (c_ubyte * 3)(0, 0, 0))
        ret = self.dll.VCI_Transmit(self.dtype, self.dev, self.can, byref(obj), 1)
        return int(ret or 0) > 0

    def receive(self, n=64):
        arr_t = VCI_CAN_OBJ * n
        arr = arr_t()
        ret = self.dll.VCI_Receive(self.dtype, self.dev, self.can, byref(arr), n, 5)
        try:
            cnt = int(ret or 0)
        except Exception:
            cnt = 0
        out = []
        for i in range(min(cnt, n)):
            o = arr[i]
            dlc = int(o.DataLen) if o.DataLen else 8
            out.append((int(o.ID), bytes(bytearray(o.Data[:8])),
                        bool(o.ExternFlag), bool(o.RemoteFlag), dlc))
        return out

    def close(self):
        try:
            self.dll.VCI_CloseDevice(self.dtype, self.dev)
        except Exception:
            pass


# --------------------------------------------------------------- ZCAN 后端 ----
class ZcanBackend:
    """zlgcan.dll 新接口：InitCAN 返回通道句柄，收发走 can_frame。"""
    name = "zlgcan/ZCAN"

    def __init__(self, dll, path):
        self.dll, self.path = dll, path
        self.handle = None       # DEVICE_HANDLE
        self.chandle = None      # CHANNEL_HANDLE
        self.dev = 0
        self.can = 0

    def _bind(self):
        d = self.dll
        d.ZCAN_OpenDevice.restype = c_void_p
        d.ZCAN_OpenDevice.argtypes = [c_uint, c_uint, c_uint]
        d.ZCAN_CloseDevice.restype = c_uint
        d.ZCAN_CloseDevice.argtypes = [c_void_p]
        d.ZCAN_InitCAN.restype = c_void_p
        d.ZCAN_InitCAN.argtypes = [c_void_p, c_uint, c_void_p]
        d.ZCAN_StartCAN.restype = c_uint
        d.ZCAN_StartCAN.argtypes = [c_void_p]
        d.ZCAN_Transmit.restype = c_uint
        d.ZCAN_Transmit.argtypes = [c_void_p, c_void_p, c_uint]
        d.ZCAN_Receive.restype = c_uint
        d.ZCAN_Receive.argtypes = [c_void_p, c_void_p, c_uint, c_int]
        if hasattr(d, "ZCAN_SetValue"):
            d.ZCAN_SetValue.restype = c_uint
            d.ZCAN_SetValue.argtypes = [c_void_p, c_char_p, c_char_p]

    def open(self, dtype, dev, can):
        if not hasattr(self.dll, "ZCAN_OpenDevice"):
            return False, "无 ZCAN_OpenDevice 导出"
        self._bind()
        h = self.dll.ZCAN_OpenDevice(dtype, dev, 0)
        if not h:
            return False, "ZCAN_OpenDevice(%d,%d)=NULL" % (dtype, dev)
        self.handle = h
        self.dev, self.can = dev, can
        return True, "ZCAN_OpenDevice(%d,%d) handle=%s" % (dtype, dev, hex(h))

    def init_start(self, baud):
        # 2E-U 系列波特率走 SetValue("n/baud_rate")
        try:
            self.dll.ZCAN_SetValue(self.handle,
                                   b"%d/baud_rate" % self.can,
                                   b"%d" % (baud * 1000))
        except Exception:
            pass
        t0, t1 = BAUD_TABLE.get(baud, (0x03, 0x1C))
        cfg = ZCAN_CHANNEL_INIT_CONFIG()
        cfg.can_type = 0
        cfg.can.acc_code = 0
        cfg.can.acc_mask = 0xFFFFFFFF
        cfg.can.filter = 0
        cfg.can.timing0 = t0
        cfg.can.timing1 = t1
        cfg.can.mode = 0
        ch = self.dll.ZCAN_InitCAN(self.handle, self.can, byref(cfg))
        if not ch:
            return False, "ZCAN_InitCAN(ch=%d,%dk)=NULL" % (self.can, baud)
        self.chandle = ch
        r2 = self.dll.ZCAN_StartCAN(ch)
        return int(r2 or 0) == 1, "ZCAN_StartCAN(ch=%d)=%s" % (self.can, r2)

    def transmit(self, can_id, data, ext, rtr):
        if not self.chandle:
            return False
        dlc = min(len(data), 8)
        f = ZCAN_Transmit_Data()
        f.frame.can_id = (int(can_id) & CAN_ID_MASK) | (CAN_EFF_FLAG if ext else 0) | (CAN_RTR_FLAG if rtr else 0)
        f.frame.can_dlc = dlc
        for i in range(dlc):
            f.frame.data[i] = data[i]
        f.transmit_type = 0
        try:
            ret = self.dll.ZCAN_Transmit(self.chandle, byref(f), 1)
        except Exception:
            return False
        return int(ret or 0) > 0

    def receive(self, n=32):
        if not self.chandle:
            return []
        arr_t = ZCAN_Receive_Data * n
        arr = arr_t()
        try:
            ret = self.dll.ZCAN_Receive(self.chandle, byref(arr), n, 5)
        except Exception:
            return []
        try:
            cnt = int(ret or 0)
        except Exception:
            cnt = 0
        out = []
        for i in range(min(cnt, n)):
            fr = arr[i].frame
            dlc = int(fr.can_dlc) if fr.can_dlc else 8
            ext = bool(fr.can_id & CAN_EFF_FLAG)
            rtr = bool(fr.can_id & CAN_RTR_FLAG)
            cid = int(fr.can_id) & CAN_ID_MASK
            out.append((cid, bytes(bytearray(fr.data[:8])), ext, rtr, dlc))
        return out

    def close(self):
        try:
            if self.handle:
                self.dll.ZCAN_CloseDevice(self.handle)
        except Exception:
            pass
        self.handle = None
        self.chandle = None


# --------------------------------------------------------------- 驱动门面 ----
class ZLGUsbCanDriver:
    """USBCAN-2E-U 驱动，接口与 UT6502Driver 一致。"""

    def __init__(self, device_index=0, channel=0, baud_kbps=125):
        self.device_index = device_index      # 第几块卡 (0=第一块, 1=第二块)
        self.channel = channel                # 卡上的 CAN0 / CAN1
        self.baud_kbps = baud_kbps
        self._backend = None
        self._connected = False
        self._lock = threading.Lock()
        self._recv_thread = None
        self._running = False
        self._rx_queue = deque(maxlen=500)
        self._rx_callbacks = []
        self._wait_lock = threading.Lock()
        self._pending_match = None
        self._pending_response = None
        self._pending_event = threading.Event()
        self.attempts = []

    @property
    def connected(self):
        return self._connected

    def connect(self, ip=None, port=None, timeout=3.0):
        self.disconnect()
        self.attempts = []
        be = self._open_any_backend()
        if not be:
            zlg_n = len(candidate_dll_paths("zlgcan.dll"))
            extra = ("" if zlg_n else
                     "\n*** 未找到 zlgcan.dll。你的设备是 ZIGCAN 新驱动（如 USBCANalyst-II Plus），"
                     "必须用官方 64 位 zlgcan.dll 或新版 ControlCAN.dll。"
                     "\n*** 请到 ZLG 驱动安装目录/开发包找到该文件，拷贝到软件 assets 目录后重试。")
            raise OSError(
                "打开 ZLG CAN 盒失败。请检查：\n"
                "1) 盒子已插好，设备管理器无感叹号\n"
                "2) 关闭 USB_CAN_TOOL / FTCanTool / CANTest 等占用程序\n"
                "3) 两块卡时把「设备」切到另一路试试\n"
                "4) 跑一次  统一上位机单体版.exe --zlgprobe  查看诊断"
                + extra + "\n尝试记录：\n" + "\n".join(self.attempts[-20:]))
        self._backend = be
        self._connected = True
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        return True

    def _open_any_backend(self):
        is64 = ctypes.sizeof(ctypes.c_void_p) == 8

        # 优先 zlgcan.dll（ZIGCAN 新驱动），其次 ControlCAN.dll
        for name, factory in (("zlgcan.dll", ZcanBackend),
                              ("ControlCAN.dll", VciBackend)):
            for p in candidate_dll_paths(name):
                if is64 and not _is_x64(p):
                    self.attempts.append("跳过 %s（x86）" % p)
                    continue
                try:
                    dll = _load_dll(p)
                except OSError as e:
                    self.attempts.append("加载失败 %s: %s" % (p, e))
                    continue
                self.attempts.append("已加载 %s" % p)
                # 组合：用户选的设备+通道；再兜底扫
                combos = [(self.device_index, self.channel)]
                combos += [(self.device_index, 1 - self.channel)]
                combos += [(self.device_index, 0)]
                if factory is VciBackend:
                    # 老驱动双通道也可以走 (dev=0, can=通道)
                    combos += [(0, self.channel), (0, 0), (1, 0)]
                for dtype in DEV_TYPES:
                    for dev, can in combos:
                        be = factory(dll, p)
                        ok, msg = be.open(dtype, dev, can)
                        self.attempts.append("%s [%s] type=%d dev=%d can=%d -> %s"
                                             % (name, factory.name, dtype, dev, can, msg))
                        if not ok:
                            continue
                        ok2, msg2 = be.init_start(self.baud_kbps)
                        self.attempts.append("  " + msg2)
                        if ok2:
                            return be
                        be.close()
        return None

    def disconnect(self):
        self._running = False
        self._connected = False
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=1.0)
        self._recv_thread = None
        if self._backend:
            self._backend.close()
            self._backend = None

    def _recv_loop(self):
        while self._running and self._connected and self._backend:
            try:
                frames = self._backend.receive()
                for can_id, data, ext, rtr, dlc in frames:
                    self._process_frame(can_id, data, ext, rtr, dlc)
                if not frames:
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.01)
        self._connected = False

    def _process_frame(self, can_id, can_data, is_extended, is_rtr, dlc):
        with self._wait_lock:
            if self._pending_match is not None:
                tx_cmd, tx_dest = self._pending_match
                rx_cmd = (can_id >> 16) & 0x3F
                rx_src = can_id & 0xFF
                rx_dest = (can_id >> 8) & 0xFF
                if rx_cmd == tx_cmd and rx_src == tx_dest and rx_dest == 0xF0:
                    self._pending_response = (can_id, can_data)
                    self._pending_event.set()
                    self._pending_match = None
                    return
        self._rx_queue.append((can_id, can_data, is_extended, is_rtr, dlc))
        for cb in self._rx_callbacks:
            try:
                cb(can_id, can_data, is_extended, is_rtr, dlc)
            except Exception:
                pass

    def add_rx_callback(self, callback):
        self._rx_callbacks.append(callback)

    def remove_rx_callback(self, callback):
        if callback in self._rx_callbacks:
            self._rx_callbacks.remove(callback)

    def get_rx_message(self):
        if self._rx_queue:
            return self._rx_queue.popleft()
        return None

    def send_can_frame(self, can_id, data, is_extended=True, is_rtr=False):
        if not self._connected or not self._backend:
            return False
        try:
            with self._lock:
                return self._backend.transmit(can_id, data, is_extended, is_rtr)
        except Exception:
            return False

    def send_and_wait(self, can_id, data, timeout=2.0, is_extended=True):
        tx_cmd = (can_id >> 16) & 0x3F
        tx_dest = (can_id >> 8) & 0xFF
        with self._wait_lock:
            self._pending_response = None
            self._pending_event.clear()
            self._pending_match = (tx_cmd, tx_dest)
        if not self.send_can_frame(can_id, data, is_extended):
            with self._wait_lock:
                self._pending_match = None
            return None
        got = self._pending_event.wait(timeout=timeout)
        with self._wait_lock:
            self._pending_match = None
            response = self._pending_response
            self._pending_response = None
        return response if got else None


# ------------------------------------------------------------------ 诊断 ----
def run_probe(out_path=None):
    """诊断：枚举 DLL/设备/驱动文件。"""
    import datetime
    import subprocess
    lines = []
    add = lines.append
    add("==== ZLG CAN-2E-U 诊断 %s ====" % datetime.datetime.now().strftime("%F %T"))
    add("Python %s  %d-bit" % (sys.version.split()[0], ctypes.sizeof(ctypes.c_void_p) * 8))
    is64 = ctypes.sizeof(ctypes.c_void_p) == 8

    add("\n---- 设备管理器中的 ZLG 设备 ----")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice | Where-Object { $_.FriendlyName -match 'USBCAN|ZIGCAN|ZLG|CANALYST' } | "
             "Select-Object Status,FriendlyName,InstanceId,Service | Format-List"],
            capture_output=True, text=True, timeout=15, encoding="utf-8", errors="ignore")
        add((out.stdout or "").strip() or "(无输出)")
    except Exception as e:
        add("查询失败: %s" % e)

    add("\n---- 系统中找到的 ZLG 相关文件 ----")
    files = scan_zlg_files()
    if not files:
        add("  (未找到 zlgcan.dll / ControlCAN.dll 等)")
    for f in files:
        tag = "x64" if f.lower().endswith(".dll") and _is_x64(f) else "-"
        add("  [%s] %s" % (tag, f))

    add("\n---- 候选路径 ----")
    for name in ("zlgcan.dll", "ControlCAN.dll"):
        paths = candidate_dll_paths(name)
        add("%s: %d 个" % (name, len(paths)))
        for p in paths:
            add("  [%s] %s" % ("x64" if _is_x64(p) else "x86", p))

    add("\n---- 扫描 OpenDevice (dev=0/1/2, type=21/20/4/3) ----")
    found = False
    for name, factory in (("zlgcan.dll", ZcanBackend), ("ControlCAN.dll", VciBackend)):
        for p in candidate_dll_paths(name):
            if is64 and not _is_x64(p):
                continue
            try:
                dll = _load_dll(p)
            except OSError as e:
                add("加载失败 %s: %s" % (p, e))
                continue
            add("已加载 %s (%s)" % (p, factory.name))
            for dtype in DEV_TYPES:
                for dev in (0, 1, 2):
                    be = factory(dll, p)
                    ok, msg = be.open(dtype, dev, 0)
                    add("  [%s] type=%d dev=%d -> %s" % (factory.name, dtype, dev, msg))
                    if ok:
                        found = True
                        be.close()
    add("")
    add("结论: %s" % ("有设备能打开" if found else "全部失败"))
    add("提示: 1) 关闭 USB_CAN_TOOL/FTCanTool  2) 若未找到 zlgcan.dll，"
        "请把 ZLG 驱动安装目录的 zlgcan.dll 或 ControlCAN.dll 拷到软件 assets 目录")
    text = "\n".join(lines)
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
    return text
