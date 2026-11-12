# -*- coding: utf-8 -*-
"""RU 灵巧系列电源 —— 从站模拟器 CLI。

用法示例：
  python tools/simulator.py                       # 监听 127.0.0.1:7502
  python tools/simulator.py --port 7502 --unit 1
  python tools/simulator.py --serial COM10 --baud 9600   # 需要成对虚拟串口

上位机里把「传输方式」选成 RTU over TCP，地址/Host 填 127.0.0.1，端口填对应值即可。
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ru.server import SerialSlaveServer, TcpSlaveServer  # noqa: E402
from ru.slave import RUSlave  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="RU 系列电源 Modbus RTU 从站模拟器")
    ap.add_argument("--host", default="127.0.0.1", help="TCP 监听地址（默认 127.0.0.1）")
    ap.add_argument("--port", type=int, default=7502, help="TCP 监听端口（默认 7502）")
    ap.add_argument("--serial", default=None, help="改用串口，例如 COM10")
    ap.add_argument("--baud", type=int, default=9600, help="串口波特率（默认 9600）")
    ap.add_argument("--unit", type=int, default=1, help="从站地址（默认 1）")
    ap.add_argument("--rated-v", type=float, default=100.0, help="额定电压（默认 100V）")
    ap.add_argument("--rated-i", type=float, default=5.0, help="额定电流（默认 5A）")
    ap.add_argument("--load", type=float, default=100.0, help="模拟负载阻抗 Ω（默认 100Ω）")
    args = ap.parse_args()

    slave = RUSlave(unit_id=args.unit, rated_v=args.rated_v, rated_i=args.rated_i,
                    load_ohm=args.load)

    if args.serial:
        srv = SerialSlaveServer(slave, args.serial, args.baud)
        srv.start()
        print("[模拟器] 已挂到串口 %s @%d，从站地址 %d" % (args.serial, args.baud, args.unit))
    else:
        srv = TcpSlaveServer(slave, args.host, args.port)
        port = srv.start()
        print("[模拟器] 已监听 %s:%d（RTU over TCP），从站地址 %d"
              % (args.host, port, args.unit))
    print("[模拟器] 额定 %.1fV / %.1fA，模拟负载 %.1fΩ。Ctrl+C 退出。" % (
        args.rated_v, args.rated_i, args.load))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
        print("\n[模拟器] 已停止。")


if __name__ == "__main__":
    main()
