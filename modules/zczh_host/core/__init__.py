# -*- coding: utf-8 -*-
"""中创智合采集卡 core 包：Modbus 协议栈 + 系列寄存器映射 + 模拟从站。

modbus.py   —— 零依赖 Modbus 协议栈（CRC16 / RTU 帧 / MBAP / 串口 / TCP / Device）
series.py   —— 温度 / 电压 / 电流 / 混合 四大系列寄存器映射表与换算
simulator.py —— 模拟从站（真实维护保持寄存器，支持 RTU / MBAP）

这些模块来自独立 tkinter 项目 zczh_hmi，融合进 FusionHub 时协议层零逻辑改动，
仅将 simulator.py 的顶层导入改为相对导入。
"""
