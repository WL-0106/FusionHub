# -*- coding: utf-8 -*-
"""GDM-906X（GW Instek）数字万用表上位机。

模块划分：
  scpi.py       —— SCPI 指令构建、读数解析、单位格式化
  transport.py  —— 串口 / TCP(3001) / 内置模拟器 三种通道
  meter.py      —— 仪表高层 API + 后台轮询线程
  ui.py         —— tkinter 界面
"""

__version__ = "1.0.0"
