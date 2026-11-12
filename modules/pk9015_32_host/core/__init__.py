# -*- coding: utf-8 -*-
"""PK9015-32 32 通道模拟量输入模块 · 逻辑层。

- protocol.py   PK9015-32 设备对象（复用同族协议栈底层：CRC/报文/传输层）
- registers.py  寄存器表与换算（单一事实源）
- simulator.py  模拟从站（TCP 串口服务器，无真机开发/演示用）

界面 page.py 只消费 protocol.PK9015_32 语义接口，不接触帧字节。
"""
