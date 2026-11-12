# -*- coding: utf-8 -*-
"""PK9015 12 路电流采集模块 · 逻辑层。

- protocol.py   Modbus RTU 协议栈（手写 CRC16/FC03/FC06）+ PK9015 设备对象 + 传输层
- registers.py  寄存器表与电流换算（单一事实源）
- simulator.py  模拟从站（TCP 串口服务器，无真机开发/演示用）

界面 page.py 只消费 protocol.PK9015 语义接口，不接触帧字节。
"""
