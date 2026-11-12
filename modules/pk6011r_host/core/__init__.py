# -*- coding: utf-8 -*-
"""PK6011R 单相电参数采集模块 · 逻辑层（零改动复用原上位机）。

- protocol.py   Modbus RTU 协议栈（手写 CRC16/FC03/FC06）+ PK60xx 设备对象 + 传输层
- registers.py  寄存器表与工程量换算（单一事实源）
- simulator.py  模拟从站（TCP 串口服务器，无真机开发/演示用）

界面 page.py 只消费 protocol.PK60xx 语义接口，不接触帧字节。
"""