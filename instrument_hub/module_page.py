# -*- coding: utf-8 -*-
"""模块上位机融合页：把各厂商独立上位机工程的模块页嵌入本 UI（充电模块/仪器仪表/PLC/调试助手）。

接入契约（与 modules/ 各模块包 __init__.py 约定一致）：
- modules.<id>.create_page(parent) -> QWidget   构造可嵌入主窗口
- modules.<id>.shutdown(page)                   退出/卸载时停机、断开、回收线程

风格适配：模块原工程各自带独立主题（多为深色 QSS），嵌入后统一替换为本 UI 主题
（instrument_hub.theme.QSS），仅保留语义化状态色（在线/故障/告警），保证融合页
与整体 UI 风格一致；模块加载失败时显示错误卡片，不影响上位机其余功能。
"""
import importlib
import re
import traceback
import types
from typing import Dict, List

from PyQt5.QtCore import QEvent, QObject, Qt, QTimer
from PyQt5.QtWidgets import (QBoxLayout, QCheckBox, QComboBox, QFrame, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPushButton, QScrollArea, QSpinBox, QSplitter,
                             QTableWidget, QTableView, QVBoxLayout, QWidget)

from .theme import QSS_EMBED
from .widgets import Card, Chip
from .comm_state import get_indicator

# 二级目录默认归属：未显式指定 group 的模块按充电模块归入 AC/DC 源（与 registry.NAV_GROUPS 一致）
GROUP = "AC/DC源"

# 充电模块 8 厂商（帮助文案/批量操作说明按此区分，其余模块用通用说明）
CHARGING_IDS = frozenset({"lm_can", "lm_485", "infy", "yonglian", "youyou", "en", "asby", "hbtw"})

# 模块注册表（源自统一上位机 app/registry.py，字段保持单一事实源同步）
CHARGE_MODULES: List[Dict] = [
    dict(id="lm_can", name="联明CAN通讯上位机", vendor="联明",
         proto="CAN · UT-6502", pkg="modules.lm_can",
         summary="联明充电模块 CAN 通讯调试：设备扫描 / 批量设定 / 实时监控 / 日志"),
    dict(id="lm_485", name="联明485通讯上位机", vendor="联明源",
         proto="RS485 · Modbus", pkg="modules.lm_485",
         summary="联明充电模块 RS-485 Modbus 调试：总线扫描 / 寄存器读写 / 日志"),
    dict(id="infy", name="英飞源REG模块上位机", vendor="英飞源",
         proto="REG · 以太网-CAN", pkg="modules.infy",
         summary="英飞源 REG 充电模块调试：网口接入 / 参数下发 / 监控"),
    dict(id="yonglian", name="永联UXR模块上位机", vendor="永联",
         proto="UXR · UT-6502", pkg="modules.yonglian",
         summary="永联 UXR 充电模块调试：连接 / 批量 / 监控 / 日志"),
    dict(id="youyou", name="优优绿能模块上位机", vendor="优优绿能",
         proto="双向 · UT-6502", pkg="modules.youyou",
         summary="优优绿能双向充电模块调试：扫描 / 参数设定 / 实时数据"),
    dict(id="en", name="EN+模块上位机", vendor="EN",
         proto="EN+ · UT-6502", pkg="modules.en",
         summary="EN+ 充电模块调试：CAN 接入 / 故障码 / 监控（ZLG CAN-2E-U）"),
    dict(id="asby", name="安世博模块上位机", vendor="安世博源",
         proto="UAB · UT-6502", pkg="modules.asby",
         summary="安世博充电模块调试：设备初始化 / 扫描 / 故障码查询"),
    dict(id="hbtw", name="禾享源模块上位机", vendor="禾享源",
         proto="HBTW · UT-6502", pkg="modules.hbtw",
         summary="禾享源充电模块调试：连接 / 参数配置 / 实时数据（读 settings_hbtw.json）"),
    dict(id="ping_scan", name="网段Ping扫描助手", vendor="调试工具",
         proto="ICMP / ARP · 网段扫描", pkg="modules.ping_scan",
         summary="网段 Ping 扫描：目标混写（IP/范围/网段）并发探活，在线统计、MAC 回填、结果导出",
         group="调试助手"),
    dict(id="an96hc", name="安规综合分析仪上位机", vendor="艾诺 AN9637HC",
         proto="SE / Ainuo ASCII / SCPI · RS232/485", pkg="modules.an96hc",
         summary="安规测试（ACW/DCW/IR/接地）：参数编辑下发、启动/停止（高压二次确认）、结果查询、协议诊断",
         group="仪器仪表"),
    dict(id="relay", name="继电器板卡上位机", vendor="测控机箱 AXI1018",
         proto="Modbus RTU · RS485 / TCP", pkg="modules.relay",
         summary="继电器板卡(12CH)：单路/全控/广播（闭合二次确认）、16 路开入与软硬件版本回读、帧日志",
         group="PLC"),
    dict(id="ru_power", name="RU电源上位机", vendor="RU 灵巧系列",
         proto="Modbus RTU · RS232/485 / TCP", pkg="modules.ru_power",
         summary="可编程直流电源：设定 V/I、OVP/OCP 保护、输出开关（二次确认）、实时电压电流回读",
         group="AC/DC源"),
    dict(id="fluke8808a_host", name="FLUKE8808A上位机", vendor="Fluke",
         proto="SCPI · RS232", pkg="modules.fluke8808a_host",
         summary="FLUKE 8808A 万用表真机上位机：测量/量程/速率/触发设置、趋势图、模拟器与自动测试",
         group="仪器仪表"),
    dict(id="dm3058_host", name="DM3058上位机", vendor="RIGOL",
         proto="SCPI · 串口/网口/USB-TMC", pkg="modules.dm3058_host",
         summary="RIGOL DM3058/3058E 万用表：11 种测量功能（DCV/ACV/DCI/ACI/电阻/频率/电容等）、量程/速率设置、实时读数",
         group="仪器仪表"),
    dict(id="gpp_host", name="GPP电源上位机", vendor="GPP 系列",
         proto="SCPI · 串口/网口", pkg="modules.gpp_host",
         summary="GPP 可编程直流电源：多通道卡片（设定/输出/回读）、趋势图、数据记录导出",
         group="AC/DC源"),
    dict(id="it8500_host", name="IT8500上位机", vendor="IT8500 系列",
         proto="IT 协议 · 串口/网口", pkg="modules.it8500_host",
         summary="IT8500 电子负载：实时测量、定值设置、动态测试、LIST 列表、系统保护、数据记录",
         group="仪器仪表"),
    dict(id="hspy_host", name="HSPY电源上位机", vendor="HSPY 系列",
         proto="Modbus-RTU · 串口", pkg="modules.hspy_host",
         summary="HSPY 可编程直流电源（多机型融合）：机型预设换算、运行监控、参数设置、"
                 "量程标定、寄存器表读写、CSV 记录",
         group="AC/DC源"),
    dict(id="tp613_host", name="TP613电量仪上位机", vendor="TP613 系列",
         proto="Modbus-RTU · 串口/网口", pkg="modules.tp613_host",
         summary="TP613 三相智能电量仪配置：实时数据采集（电压/电流/功率/电能）、"
                 "参数读写(FC06/10)、自定义报文、清电能/需量",
         group="仪器仪表"),
    dict(id="res_tx_host", name="电阻变送器上位机", vendor="电阻变送器（2946060166）",
         proto="Modbus-RTU · RS485", pkg="modules.res_tx_host",
         summary="电阻变送器：电阻值实时读取（整数寄存器0 + Float 寄存器2048）、"
                 "RS485 参数读写（自动先写 7166=0xCCAA 开许可）、手动发帧自动补 CRC、报文日志",
         group="仪器仪表"),
    dict(id="mfg2000_host", name="MFG2000信号源上位机", vendor="MFG-2000 系列",
         proto="SCPI · 串口/网口", pkg="modules.mfg2000_host",
         summary="GW INSTEK MFG-2000 函数/任意波形发生器：三通道输出（波形/频率/幅值/偏移）、"
                 "AM/FM/PM 调制、扫描、脉冲串、计频器、错误队列，命令表驱动",
         group="仪器仪表"),
    dict(id="easy_plc_host", name="汇川PLC上位机", vendor="汇川 EASY300/500",
         proto="Modbus RTU/TCP", pkg="modules.easy_plc_host",
         summary="汇川 EASY300/EASY500 小型 PLC：X/Y/M I/O 实时监控与强制输出、"
                 "D 寄存器读写、PLC RUN/STOP 监视、通信诊断",
         group="PLC"),
    dict(id="xinje_plc_host", name="信捷PLC上位机", vendor="信捷 XD/XL 系列",
         proto="Modbus RTU/TCP", pkg="modules.xinje_plc_host",
         summary="信捷 XD/XL 系列 PLC：X/Y/M/S/T/C/D/HD 等软元件 I/O 监视与强制、"
                 "寄存器监视写入、实时趋势曲线、报警事件、通讯诊断",
         group="PLC"),
    dict(id="jt6321a_host", name="JT6321A电子负载上位机", vendor="Jartul JT632xA",
         proto="SCPI · RS232", pkg="modules.jt6321a_host",
         summary="Jartul JT632xA 直流电子负载：CC/CV/CP/CR/DYNA/LED 模式、拉载设定、"
                 "OCP 过流测试、动态模式、V/I/P/R 实时监测、保护状态位、短路模拟",
         group="仪器仪表"),
    dict(id="msp_host", name="美恩斯电源上位机", vendor="美恩斯 MSP65/MSP62",
         proto="Modbus-RTU · 串口", pkg="modules.msp_host",
         summary="美恩斯 MSP65/MSP62 可编程直流电源：量程小数位配置、V/I 设定、OVP/OCP 保护、"
                 "输出开关（二次确认）、实时测量与波形、寄存器表调试、模拟从站",
         group="AC/DC源"),
    dict(id="gdm906x_host", name="GDM-906X万用表上位机", vendor="GW Instek GDM-9060/9061",
         proto="SCPI · 串口/网口", pkg="modules.gdm906x_host",
         summary="GW Instek GDM-9060/9061 数字万用表：12 种测量功能（DCV/ACV/DCI/ACI/"
                 "电阻/频率/周期/电容/通断/二极管/温度）、量程/NPLC/副显示/相对值设置、"
                 "单次与连续测量、趋势图与统计、设备控制与屏幕截图、SCPI 透传",
         group="仪器仪表"),
    dict(id="serial_debug_host", name="串口调试助手上位机", vendor="二合一调试助手 V2.1",
         proto="串口 / TCP·UDP / Modbus-RTU", pkg="modules.serial_debug_host",
         summary="串口调试（SSCOM 风格）：HEX 收发/编码选择/定时发送/快捷指令/文件发送/"
                 "数据落盘、TCP Client/Server/UDP 接入、串口↔TCP 双向转发与二选一自动切换；"
                 "MODBUS RTU 面板：01H~10H 指令读写、任意指令+CRC、响应解析/异常码/超时提示，"
                 "两页独立串口可同时连接",
         group="调试助手"),
    dict(id="pk6011r_host", name="PK6011R采集模块上位机", vendor="锐测 RISE / 上海域信 PK6011R",
         proto="Modbus RTU · RS485 / TCP", pkg="modules.pk6011r_host",
         summary="PK6011R 单相电参数采集模块：电压/电流/有功/无功/功率因数/视在/频率/电能采集、"
                 "变比 UBB/IBB 读写、量程与变比回读、模块搜索、地址与波特率修改、通讯日志",
         group="采集卡"),
    dict(id="pk9015_host", name="PK9015采集模块上位机", vendor="锐测 RISE / 上海域信 PK9015",
         proto="Modbus RTU · RS485 / TCP", pkg="modules.pk9015_host",
         summary="PK9015 12 路电流采集模块：I0~I11 实时采集、量程切换（0-20mA/4-20mA/0-10V）、"
                 "模块搜索、地址与波特率修改、通讯日志",
         group="采集卡"),
    dict(id="pk9018b_host", name="PK9018B-8采集模块上位机", vendor="锐测 RISE / 上海域信 PK9018B-8",
         proto="Modbus RTU · RS485 / TCP", pkg="modules.pk9018b_host",
         summary="PK9018B-8 8 通道热电阻温度采集模块：CH0~CH7 实时温度采集（-50~300℃/0~650℃）、"
                 "温度修正值读写、模块搜索、地址与波特率修改、通讯日志",
         group="采集卡"),
    dict(id="pk9015f_host", name="PK9015F电压模块上位机", vendor="锐测 RISE / 上海域信 PK9015F",
         proto="Modbus RTU · RS485 / TCP", pkg="modules.pk9015f_host",
         summary="PK9015F 交流电压测量模块：12/24 通道电压采集（AC 250V）、量程读取、"
                 "电压修正值读写、模块搜索、地址与波特率修改、通讯日志",
         group="采集卡"),
    dict(id="pk9015_32_host", name="PK9015-32采集模块上位机", vendor="锐测 RISE / 上海域信 PK9015-32",
         proto="Modbus RTU · RS485 / TCP", pkg="modules.pk9015_32_host",
         summary="PK9015-32 32 通道模拟量输入模块：CH0~CH31 实时采集（电流/电压）、"
                 "CT 变比一次侧/二次侧换算、量程读取、模块搜索、地址与波特率修改、通讯日志",
         group="采集卡"),
    dict(id="zczh_host", name="中创智合采集卡上位机", vendor="深圳中创智合 ZCZH",
         proto="Modbus RTU · RS485 / TCP", pkg="modules.zczh_host",
         summary="温度/电压/电流/混合四大系列共用 Modbus 协议：温度 16 路（÷10，℃）、"
                 "电压/电流（×量程÷10000）、24 路交直流组合；系列切换 + 量程值 + 协议切换 + "
                 "关键寄存器参考 + 直接发报文 + 通讯日志",
         group="采集卡"),
    dict(id="keysight_dmm_host", name="Keysight DMM上位机", vendor="Keysight",
         proto="SCPI · 串口/LAN", pkg="modules.keysight_dmm_host",
         summary="Keysight Truevolt 34461A/34465A/34470A 数字万用表：12 种测量功能"
                 "（直流/交流电压电流、2线/4线电阻、电容、频率、周期、温度、通断、二极管）、"
                 "NPLC/触发源/显示文本配置、单次与连续采集、模拟从站、错误队列人话提示",
         group="仪器仪表"),
    dict(id="huayuan_acload_host", name="华源交流负载上位机", vendor="华源",
         proto="Modbus-RTU · RS232/485 / TCP", pkg="modules.huayuan_acload_host",
         summary="华源交流回馈式负载（MODBUS V1.4）：输出开关（二次确认）、操作/控制模式、"
                 "总功率/总电流与 15 通道设定（一键按手册顺序下发）、三相/15 通道实测、"
                 "故障位表、寄存器读写调试、本地量程拦截、模拟从站",
         group="仪器仪表"),
    dict(id="xinsheng_load_host", name="新胜负载箱上位机", vendor="新胜",
         proto="Modbus-RTU · RS485 / TCP", pkg="modules.xinsheng_load_host",
         summary="新胜负载箱（FC03/FC06）：风机开关（状态寄存器2确认）、急停/解除（1=正常0=急停）、"
                 "风机延时开/关、独立/同步模式、A/B/C 相功率档加载（10 倍输入，二次确认）、"
                 "分相/一键卸载、实时监控、功率档地址双方案（表 51/53/55 或手册示例 50/52/54）",
         group="仪器仪表"),
]


# 各模块通讯协议要点（帮助手册「协议与调试规范」页自动派生展示；与 CHARGE_MODULES 同源维护）
# 串口/网口转 CAN 类模块标注默认波特率（取自源码默认值，未写清的不猜测）
PROTO_NOTES: Dict[str, str] = {
    "lm_can": "CAN 2.0B 自定义帧（29 位扩展帧）经 UT-6502 以太网-CAN 转换器透传；"
              "CAN 默认波特率 125 kbps，转换器默认 TCP 端口 5001；命令/响应成对，"
              "含扫描、批量设定与实时数据帧",
    "lm_485": "Modbus-RTU（RS485，CRC16，默认波特率 9600）；寄存器读写（FC03/FC06/FC10），"
              "从机地址 + 波特率可配",
    "infy": "REG 协议 · 以太网-CAN 混合：CAN2.0B 125Kbps、29 位扩展标识符；"
            "UT-6502 默认 TCP 5001 / ZLG 默认 TCP 4001；命令帧含设备地址/功能域，参数下发 + 实时监控",
    "yonglian": "UXR 自定义帧（NXR 应用层 29 位扩展帧 + UT-6502 链路层 13 字节固定格式）；"
                "转换器默认 TCP 端口 5000，CAN 波特率按 UT-6502 侧配置（源码未固定）；"
                "连接握手 + 批量设定 + 监控帧，帧校验 + 超时重发上限",
    "youyou": "双向充电模块自定义协议（CAN 2.0B 扩展帧 29 位 ID）经 UT-6502 透传；"
              "CAN 默认波特率 125 kbps，转换器默认 TCP 端口 5001；扫描/参数设定/实时数据三类命令帧",
    "en": "EN+ 自定义帧（CAN2.0B 扩展帧 29 位 ID）经 ZLG CAN-2E-U USB-CAN 卡接入；"
          "CAN 默认波特率 125 kbps（可选 250k/500k/1M）；故障码查询与实时监控命令",
    "asby": "UAB 自定义帧经 UT-6502 透传；CAN 125k / 扩展帧 / 固定格式，转换器默认 TCP 端口 5001；"
            "设备初始化 / 扫描 / 故障码查询命令序列",
    "hbtw": "HBTW 自定义帧经 UT-6502 透传；CAN 波特率 1 Mbps / 扩展帧 / 固定格式，"
            "转换器默认 TCP 端口 5001；连接 / 参数配置 / 实时数据，配置参数读 settings_hbtw.json",
    "ping_scan": "ICMP Ping / ARP 并发探活（网络层协议，无波特率概念）；"
                 "目标混写解析（IP/范围/网段）+ 在线统计 + MAC 回填",
    "an96hc": "三种方言可切换：SE 报文 / Ainuo ASCII / SCPI（RS232/RS485，默认波特率 9600）；"
              "命令帧 + 校验，覆盖耐压/绝缘/接地等测试项指令，异常码映射人话提示",
    "relay": "Modbus-RTU（RS485，默认波特率 9600）/ Modbus-TCP（RTU over TCP 网口透传）；"
             "线圈强制（FC05/FC15）、状态读取（FC01/FC02），12 路继电器，"
             "单开/单关/全开/全关 + 断开/全开二次确认",
    "ru_power": "Modbus-RTU（RS232/RS485，默认波特率 9600，支持 1200~115200）/ Modbus-TCP；"
                "寄存器读写（FC03/FC06/FC10），电压/电流/功率设定与回读、输出开关、故障状态寄存器",
    "fluke8808a_host": "FLUKE 8808A ASCII 命令集（RS232，默认波特率 9600，面板可选 300~19200）；"
                       "查询命令带 ? 与 SET 命令成对，读数回 ASCII 报文，测量功能/量程切换命令",
    "dm3058_host": "SCPI（RS232/USB/LAN，串口默认波特率 9600）；*IDN? / MEAS? 等标准命令，"
                   "READ/CONF 组合查询，RIGOL DM3058 万用表寄存器映射",
    "gpp_host": "SCPI（RS232/USB/LAN，串口默认波特率 115200）；多通道 CH1~CHn 设定（VOLT/CURR）、"
                "OUTP 开关、MEAS 回读，GPP 系列可编程直流电源命令表",
    "it8500_host": "IT8500 帧格式（FRAME）协议（注意：SCPI 模式不可用）；"
                   "经通讯转换模块 IT-E121 接入上位机，RS232 串口须使用直连线；"
                   "串口默认波特率 9600（可选 4800/19200/38400），从机地址 0~31，"
                   "电压/电流/功率/电阻拉载设定与测量回读",
    "hspy_host": "Modbus-RTU（CRC16，FC03/FC06/FC10，默认波特率 9600-8-N-2）；"
                 "HSPY 系列电源电压/电流设定与回读、输出开关，机型预设表（小数位/量程按机型换算）",
    "tp613_host": "Modbus-RTU（RS485/TCP，默认波特率 9600）；三相电量采集块 + 参数读写（FC03/FC06/FC10），"
                  "电压/电流/功率/电能寄存器，FLOAT（ABCD 双寄存器）+ 4-20mA 输出设定",
    "res_tx_host": "Modbus-RTU（RS485，8 数据位，默认波特率 9600 8N1，可选 2400~115200，从站 1~247）；"
                   "FC03/04 读量值/参数、FC06/10 写参数；电阻值两路：寄存器 0（UShort 无符号整数）"
                   "与寄存器 2048~2049（IEEE754 Float，ABCD 高字在前）；通信参数：7166=许可开关"
                   "（写 0xCCAA 才允许改参）、7167=地址、7168=波特率（0~6）、7169=数据格式（0=8N1 1=8O1 2=8E1 3=8N2）；"
                   "CRC16 多项式 0xA001 低字节在前；改参前必须先写 7166=0xCCAA",
    "mfg2000_host": "SCPI 1994 / IEEE 488.2-1992（RS232/USB/LAN，串口默认波特率 115200）；"
                    "命令表驱动（49 命令 8 组），参数校验/SCPI 生成/回读解析由命令表派生，"
                    "含 AM/FM/PM 调制、扫描、脉冲串、计频器；双系列可选（MFG-2000 / "
                    "AFG-2000，AFG-2225 规格 25MHz/10VPP/脉宽 20ns 起），两系列 SCPI 同源",
    "easy_plc_host": "Modbus-RTU（RS485）/ Modbus-TCP；默认波特率 EASY300 为 9600、EASY500 为 19200；"
                     "X/Y 八进制编号（X=0xF800、Y=0xFC00 基址）、M/D 十进制编号；"
                     "线圈强制 + 寄存器读写，X/Y/M/D 轮询 + M8000 RUN/STOP 监视",
    "xinje_plc_host": "Modbus-RTU（RS485，默认波特率 9600）/ Modbus-TCP；X/Y 八进制编号（Y10=0x6008）、"
                      "HD 基址 0xA080，SM/S/HS/T/C/D/SD/FD/ID/QD 软元件映射；"
                      "强制输出带回读校验，不一致自动持续强制",
    "jt6321a_host": "SCPI（隔离 RS232，全 ASCII，帧尾 NL，默认波特率 9600，支持 2400~115200）；"
                    "查询命令带 ? 回一行，设置命令无应答靠回读确认；MODE/INP/CURR:PROT/POW:PROT/"
                    "DYN/OCP 命令族，STAT:QUES:COND 状态字 8 保护位；注意 Multi-Point 多点通讯需关闭、"
                    "RS232 串口须使用直连线",
    "msp_host": "Modbus-RTU（8N1）；默认波特率 MSP65 为 115200、MSP62 为 9600；"
                "功能码 0x03 读可写区 / 0x04 读只读区 / 0x06 写单 / 0x10 写多，单帧 1~20 寄存器、"
                "地址连续（可读 1000~2022、可写 2000~2022）；CRC-16/MODBUS 低字节在前；"
                "设备地址默认 1（有效 1~100，寄存器 2000 可改）；16 位无符号定点数，"
                "物理量按小数位换算（MSP65 按额定值推导、MSP62 按面板显示配置）",
    "gdm906x_host": "SCPI（指令长/短格式均可，CONF:VOLT:DC == CONFigure:VOLTage:DC）；"
                    "RS232 / USB-CDC（串口默认波特率 115200-8-N-1）/ LAN（SCPI 走 TCP 默认端口 3001，"
                    "Telnet 会话 3000）；消息终结符串口 CR+LF、TCP LF；自动量程时禁止附带分辨率参数；"
                    "READ? 触发测量，DATA:LAST? / DATA2:LAST? 查最近值，+9.9E37 为超量程/开路哨兵"
                    "（非通信故障）；屏幕截图 HCOP:SDUM:DATA? 返回 IEEE488.2 定长 BMP 块",
    "serial_debug_host": "串口透传调试（RS232/USB-CDC，波特率 1200~921600，默认 115200-8-N-1）；"
                         "TCP/UDP 三模式（TCP Client/Server/UDP，Server/UDP 绑定本地端口、"
                         "Client 连远程）；串口与 TCP 二选一自动切换（勾双向转发可并存、互转数据）；"
                         "Modbus-RTU 面板 FC01~FC06/FC10 自动组帧 + CRC16（低字节在前），"
                         "响应 900ms 超时、CRC 校验与异常码映射人话提示；两页独立串口互不占用"
                         "（打开前预检端口占用），驱动不接受的 5/6 位数据位/1.5 停止位自动降级 8-1",
    "pk6011r_host": "Modbus-RTU（RS485，默认波特率 9600 支持 1200~19200，8-N-1；无真机/现场走 TCP 串口服务器）；"
                    "FC03 读保持寄存器（地址无偏移 = PLC 地址 - 40001，0x0000~0x0010 共 17 寄存器）、"
                    "FC06 写单寄存器；CRC16 多项式 0xA001 低字节在前；异常码映射人话提示；"
                    "电流量程基准 5A（IBB=量程/5），电压/电流/功率/电能均 ×UBB×IBB；"
                    "寄存器 0x0000 为地址+波特率只写寄存器，改后需按新参数重新连接",
    "pk9015_host": "Modbus-RTU（RS485，默认波特率 9600 支持 1200~19200，8-N-1；无真机/现场走 TCP 串口服务器）；"
                   "FC03 读 12 路电流（寄存器 0x0003~0x000E，每路 16 位无符号，raw/10000 换算，"
                   "满量程 raw=10000 对应满量程电流）、FC06 写单寄存器（量程 0x02BE、地址波特率 0x0000）；"
                   "CRC16 多项式 0xA001 低字节在前；量程 0=0-20mA、1=4-20mA、2=0-10V；"
                   "4-20mA 量程实际电流 = 4 + raw/10000×16 (mA)；"
                   "寄存器 0x0000 为地址+波特率只写寄存器，改后需按新参数重新连接",
    "pk9018b_host": "Modbus-RTU（RS485，默认波特率 9600 支持 1200~19200，8-N-1；无真机/现场走 TCP 串口服务器）；"
                    "FC03 读 8 通道温度（测量值寄存器 0x0009~0x0010，每路 16 位符号-绝对值，BIT15 符号位，"
                    "值/100 = ℃，分辨率 0.01℃）、FC10 写多寄存器（修正值 0x0001~0x0008、地址波特率 0x0000）；"
                    "CRC16 多项式 0xA001 低字节在前；量程 -50~300℃（带符号）或 0~650℃（无符号）；"
                    "修正值同为符号-绝对值 16 位，值/100 = ℃；寄存器 0x0000 高 8 位=地址、低 8 位=波特率码",
    "pk9015f_host": "Modbus-RTU（RS485，默认波特率 9600 支持 1200~19200，8-N-1；无真机/现场走 TCP 串口服务器）；"
                   "FC03 读电压测量值（寄存器 0x0003~，每路 16 位有符号补码，raw×量程/10000 = V）、"
                   "FC06 写单寄存器（地址 0x0000、波特率 0x0001、修正值 0x000F~）；"
                   "量程寄存器 0x0002（值×100 = 实际量程，默认 AC 250V 存 25000）；修正值值/100 = V；"
                   "CRC16 多项式 0xA001 低字节在前；12/24 通道可切换",
    "pk9015_32_host": "Modbus-RTU（RS485，默认波特率 9600 支持 1200~19200，8-N-1；无真机/现场走 TCP 串口服务器）；"
                      "FC03 读 32 通道数据（寄存器 0x0003~0x0022，每路 16 位无符号）、"
                      "FC06 写单寄存器（地址+波特率 0x0000、修正值 0x0023~）；"
                      "寄存器 0x0001=类型（1电流/其他电压）、0x0002=量程（值×100 = 实际量程）；"
                      "电流：二次侧 mA = raw×量程/10000，一次侧 A = 二次侧×CT一次/CT二次/1000；"
                      "CRC16 多项式 0xA001 低字节在前；寄存器 0x0000 高 8 位=地址、低 8 位=波特率码",
    "zczh_host": "Modbus-RTU（RS485）/ Modbus-TCP（以太网），默认波特率 9600，FC03/04 读、FC06 写单、FC10 写多；"
                 "温度系列（ZH-T16PT/TC/NTC）数据寄存器 0000~000F 共 16 路，有符号 16 位 ÷10 = ℃"
                 "（0x7FFF=断线/过温、0x8000=短路/超低温），配置寄存器 0050H 地址/0051H 波特率/0052H 校验/"
                 "0081H 采样速率/01FAH 协议切换；电压电流系列（ZH-4404#D / ZH-4424#）数据无符号 16 位"
                 "×量程÷10000 = V/A（量程见铭牌），配置寄存器 0050H/0051H/0052H/0060H 协议切换/0053H 量程系数；"
                 "组合（ZH-4124#）24 路真有效值；CRC16 多项式 0xA001 低字节在前",
    "keysight_dmm_host": "SCPI（RS232/LAN，串口默认 9600bps，LAN 走 TCP 默认端口 5025）；"
                         "*IDN? / MEASure? / CONFigure / READ? 等标准命令，命令帧 LF 终结、查询带 ? 回一行；"
                         "SYSTem:ERRor? 错误码人话映射；Truevolt 34461A/34465A/34470A",
    "huayuan_acload_host": "Modbus-RTU（RS232/RS485，默认波特率 9600-8-N-1）/ RTU-over-TCP / "
                           "标准 Modbus TCP（MBAP）/ UDP；FC03/06/10，寄存器地址=手册地址（偏移可配）；"
                           "功率单位 0.1W、电流/电压 0.001（写错单位设备回异常码 03），32 位量默认高位字在前"
                           "（可切字序）；输出控制 0x20、清故障 0x28、总功率 0x38/总电流 0x3E、"
                           "操作模式 0x3C/控制模式 0x3D、通道功率 0x40+2(n-1)、三相电流 0xE0~0xE5；"
                           "状态 0x60/0x62 合成 32 位（bit0 运行/bit16 故障/bit17 控制模式/bit19:18 操作模式），"
                           "故障位 0x7E(bit47~32)/0x7F(bit31~16)/0x80(bit15~0)；"
                           "参数下发顺序：关输出→模式→总设定→通道→开输出（顺序错设备拒写）",
    "xinsheng_load_host": "Modbus-RTU（RS485，默认波特率 9600-8-N-1）/ RTU-over-TCP（裸 RTU 帧无 MBAP，"
                          "断线发送自动重连）；FC03 读/FC06 写，地址无偏移（十进制寄存器号=报文 StartReg）；"
                          "寄存器 1 风机开关/2 风机状态/3 高温报警/5 急停（1=正常 0=急停，反直觉）/"
                          "10,20 风机延时（0~32765）/35~38 卸载（上升沿写 1，不回读）/"
                          "51,53,55 功率档（10 倍输入，10Ω 写 100）/200 同步(1)/独立(0)；"
                          "功率档地址双方案：寄存器表 51/53/55（默认）或手册示例 50/52/54（0x32H，"
                          "两帧 CRC 均自洽、现场加载无效时切换）；风机开关写后按状态寄存器 2 循环确认"
                          "（寄存器 1 回显≠已切到位，输出回路切换有延时）",
}


def all_modules() -> List[Dict]:
    return [dict(m, proto_note=PROTO_NOTES.get(m["id"], "")) for m in CHARGE_MODULES]


def recorder_spec(mod: Dict):
    """构造调试记录用的轻量仪器信息（不进 registry，仅供记录行/清单字段）。"""
    group = mod.get("group", GROUP)
    return types.SimpleNamespace(
        id=mod["id"], name=mod["name"], model=mod["vendor"], vendor=mod["vendor"],
        group=group, category=group, iface=mod["proto"],
        ip="-", port_no="-")


def _conn_info(page):
    """从模块界面嗅探连接参数：(IP/COM口, 波特率, 端口号)，未识别为 "-"。"""
    addr = baud = port_no = "-"
    for edit in page.findChildren(QLineEdit):
        t = edit.text().strip()
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", t):
            addr = t
            break
    for combo in page.findChildren(QComboBox):
        t = combo.currentText().strip()
        if addr == "-" and re.match(r"^(COM|/dev/)", t, re.IGNORECASE):
            addr = t
        elif baud == "-" and re.fullmatch(r"\d{4,6}", t):
            baud = t
    for spin in page.findChildren(QSpinBox):
        if 1024 <= spin.value() <= 65535:
            port_no = str(spin.value())
            break
    return addr, baud, port_no


def get_module(mid: str) -> Dict:
    for m in CHARGE_MODULES:
        if m["id"] == mid:
            return m
    raise KeyError(mid)


def _looks_like_log(widget) -> bool:
    """判断某控件是否是通讯日志区（标题/内部含「日志」字样）。"""
    if isinstance(widget, QGroupBox) and "日志" in widget.title():
        return True
    for gb in widget.findChildren(QGroupBox):
        if "日志" in gb.title():
            return True
    for lb in widget.findChildren(QLabel):
        if "日志" in lb.text() and len(lb.text()) <= 24:
            return True
    return False


def _wrap_log_splitter(win) -> bool:
    """把模块页的通讯日志区（主布局最后一项）改造成可拖动分割条。

    各厂商模块的日志区固定在主布局末尾且高度写死，无法缩放；
    这里通用处理：日志之上的内容收进容器，与日志一起装进垂直分割条，
    显式给两边最小尺寸，保证手柄始终拖得动（不被控件最小尺寸提示顶死）。
    """
    central = win.centralWidget() if hasattr(win, "centralWidget") else win
    lay = central.layout() if central is not None else None
    if not isinstance(lay, QVBoxLayout) or lay.count() < 2:
        return False
    log_w = lay.itemAt(lay.count() - 1).widget()
    if log_w is None or isinstance(log_w, QSplitter) or not _looks_like_log(log_w):
        return False   # 模块自带分割布局（如 QSplitter 含日志）则不二次包裹

    container = QWidget()
    cl = QVBoxLayout(container)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(lay.spacing())
    while lay.count() > 1:
        item = lay.takeAt(0)
        if item.widget() is not None:
            cl.addWidget(item.widget())
        elif item.layout() is not None:
            cl.addLayout(item.layout())

    split = QSplitter(Qt.Vertical)
    split.setHandleWidth(14)
    split.setChildrenCollapsible(False)
    # 上方内容包滚动区：日志放大时功能区上下滚动，控件/文字保持原形态不被压扁
    content_scroll = QScrollArea()
    content_scroll.setWidgetResizable(True)
    content_scroll.setFrameShape(QScrollArea.NoFrame)
    content_scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
    content_scroll.setWidget(container)
    content_scroll.setMinimumHeight(120)   # 只约束滚动区：手柄始终拖得动，内容不足时内部滚动
    log_w.setMinimumHeight(110)
    log_w.setMaximumHeight(16777215)  # 解除模块里 setFixedHeight(170) 之类写死的高度，否则拖不动
    split.addWidget(content_scroll)
    split.addWidget(log_w)
    split.setStretchFactor(0, 1)
    split.setStretchFactor(1, 0)
    split.setSizes([520, 190])
    lay.addWidget(split)
    return True


# ================================================================ 融合页按钮上色 / 状态联动
class _CommPressReset(QObject):
    """连接/断开按钮按下瞬间复位通讯状态指示：新会话未收到应答一律「未连接」。"""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.MouseButtonPress:
            try:
                from . import comm_state
                comm_state.reset(self._page)
            except Exception:
                pass
        return False


def _find_btn_row_layout(lay, btn):
    """递归找 btn 直接所在的 QBoxLayout（行内插入指示灯用，避免追加到卡片正文撑高空）。"""
    if lay is None:
        return None
    for i in range(lay.count()):
        it = lay.itemAt(i)
        if it is None:
            continue
        if it.widget() is btn:
            return lay
        sub = it.layout()
        if sub is not None:
            r = _find_btn_row_layout(sub, btn)
            if r is not None:
                return r
    return None


def _attach_conn_indicator(page, state):
    """在连接通讯配置区右侧挂统一「通讯状态」指示灯。

    语义：仅串口/TCP 链路打开 = 「未连接」；模块收到有效应答（各模块 mark_ok）才亮
    「连接成功」。找不到连接按钮的页面不挂载。
    """
    btn = state.get("conn_btn")
    if btn is None:
        return None
    from .comm_state import CommIndicator, attach as _attach
    ind = CommIndicator()
    ind.setMinimumWidth(120)
    host = btn.parentWidget()
    lay = host.layout() if host is not None else None
    placed = False
    try:
        row = _find_btn_row_layout(lay, btn)
        if isinstance(row, QBoxLayout):
            row.addStretch(1)
            row.addWidget(ind)          # 行尾：与连接按钮同行，不撑高卡片
            placed = True
        elif isinstance(row, QGridLayout):
            for i in range(row.count()):
                if row.itemAt(i).widget() is btn:
                    r, _c, _rs, cs = row.getItemPosition(i)
                    row.addWidget(ind, r, row.columnCount())   # 该行最右
                    placed = True
                    break
    except Exception:
        placed = False
    if not placed:
        # 兜底：连接卡片正文末尾一行（不加 stretch，避免撑出空白）
        card = host
        while card is not None and not (isinstance(card, QFrame)
                                        and card.objectName() == "Card"):
            card = card.parentWidget() if hasattr(card, "parentWidget") else None
        body = getattr(card, "body_lay", None) if card is not None else None
        if body is not None:
            row2 = QHBoxLayout()
            row2.addStretch(1)
            row2.addWidget(ind)
            body.addLayout(row2)
            placed = True
    _attach(page, ind)
    return ind if placed else None


class _ConnRepress(QObject):
    """双按钮模块统一交互：连接按钮显「已连接」后再按 = 断开。

    拦截「已连接」按钮的点击并转发给独立的「断开」按钮，避免触发模块自身的
    重连逻辑；单按钮 toggle 模块（无纯「断开」按钮）不安装，由模块自行切换。
    """

    def __init__(self, conn, dis, parent=None):
        super().__init__(parent)
        self._conn, self._dis = conn, dis

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self._conn and ev.type() == QEvent.MouseButtonRelease:
            if self._conn.text().strip() == "已连接" and self._dis.isEnabled():
                self._dis.click()
                return True   # 吃掉事件：不再触发模块自己的连接处理
        return False


def _btn_palette(text: str):
    """按按钮文本给色（年轻化、与整体 UI 协调）：主操作深底白字，安全操作浅底深字。"""
    t = text.strip()
    if not t or len(t) > 16:
        return None
    if "已连接" in t:
        return ("#10B981", "#FFFFFF", "#047857")
    if "停止扫描" in t or "中断扫描" in t or t == "停止":
        return ("#FFF1F2", "#D20A34", "#E11D48")
    if "断开" in t:
        return ("#FFFFFF", "#6B7280", "#D6D3EE")
    if "连接" in t:
        return ("#4F46E5", "#FFFFFF", "#4338CA")
    if "扫描" in t:
        return ("#E0F2FE", "#0369A1", "#7DD3FC")
    if "初始化" in t:
        return ("#EDE9FE", "#6D28D9", "#C4B5FD")
    if any(k in t for k in ("全部关机", "关机", "关闭", "清故障", "故障清除", "单关")) or t.endswith("关"):
        return ("#FFF1F2", "#D20A34", "#FDA4AF")
    if any(k in t for k in ("全部开机", "开机", "开启", "启动", "单开")) or t.endswith("开"):
        return ("#D1FAE5", "#047857", "#6EE7B7")
    if any(k in t for k in ("设置", "设定", "下发", "应用", "发送", "校准", "广播", "改地址", "保存", "导出")):
        return ("#EEF0FF", "#4F46E5", "#C7C3F0")
    if any(k in t for k in ("读取", "查询", "信息", "故障", "详情", "监控", "测试")):
        return ("#FEF3C7", "#B45309", "#FCD34D")
    return ("#FFFFFF", "#4B4A73", "#D6D3EE")


def _in_table(btn) -> bool:
    p = btn.parentWidget()
    while p is not None:
        if isinstance(p, (QTableWidget, QTableView)):
            return True
        p = p.parentWidget()
    return False


def _conn_want_text(connected: bool, comm_ok: bool, had_ok: bool,
                    port_open_only: bool, default: str) -> str:
    """连接按钮显示语义（平台规范「状态语义与显示真相」）：
    「已连接」需设备应答；无应答显示「连接中…」/「已连接·无应答」；透传工具除外。"""
    if not connected:
        return default
    if port_open_only:
        return "已连接"
    if comm_ok:
        return "已连接"
    return "已连接·无应答" if had_ok else "连接中…"


def _on_link_timeout(page, state) -> None:
    """握手超时：连接后 10s 全程无应答 → 询问用户（可继续等待），确认后断开。"""
    ind = state.get("conn_indicator") or get_indicator(page)
    if state.get("had_ok") or (ind is not None and ind.is_ok):
        return
    box = QMessageBox(page)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("连接无应答")
    box.setText("连接后 10 秒设备无任何应答。")
    box.setInformativeText(
        "请检查：串口/网线是否插对、设备是否开机、波特率/地址/接线是否一致。\n"
        "设备慢启动/恢复中可点「继续等待」，仍无应答会再次提示。")
    btn_break = box.addButton("断开连接", QMessageBox.AcceptRole)
    box.addButton("继续等待", QMessageBox.RejectRole)
    box.exec_()
    if box.clickedButton() is not btn_break:
        wd = state.get("wd_timer")
        if wd is not None and state.get("conn_btn") is not None:
            wd.start()
        return
    dis, conn = state.get("dis_btn"), state.get("conn_btn")
    btn = dis if (dis is not None and dis.isEnabled()) else None
    if btn is None and conn is not None and conn.isEnabled():
        btn = conn
    if btn is not None:
        btn.click()


def _paint_buttons(page) -> None:
    for b in page.findChildren(QPushButton):
        if b.property("selfStyled"):   # 状态型切换按钮自带两态配色，不统一上色
            continue
        pal = _btn_palette(b.text())
        if pal is None:
            continue
        bg, fg, bd = pal
        small = _in_table(b)
        # 文本未变不重复 setStyleSheet：周期刷样式会反复触发 unpolish/polish，
        # 拖分割条缩放时与布局循环叠加导致整台 UI 卡顿
        key = f"{bg}|{fg}|{bd}|{int(small)}"
        if b.property("_hubStyleKey") == key:
            continue
        b.setStyleSheet(
            f"QPushButton{{background:{bg}; color:{fg}; border:2px solid {bd}; "
            f"border-radius:{6 if small else 10}px; font-weight:700; "
            f"font-size:{12 if small else 12}px; padding:{2 if small else 3}px {10 if small else 12}px;}}"
            f"QPushButton:pressed{{background:{bd};}}")
        if small:
            # 行内按钮给足尺寸，避免"单关/设置"等两字按钮被列宽压缩裁切
            b.setMinimumHeight(24)
            b.setMinimumWidth(46)
        b.setProperty("_hubStyleKey", key)


def _count_checked(page) -> int:
    n = 0
    for tbl in page.findChildren(QTableWidget):
        for row in range(min(tbl.rowCount(), 300)):
            it = tbl.item(row, 0)
            if it is not None and (it.flags() & Qt.ItemIsUserCheckable) and it.checkState() == Qt.Checked:
                n += 1
            else:
                w = tbl.cellWidget(row, 0)
                if w is not None:
                    chk = w.findChild(QCheckBox)
                    if chk is not None and chk.isChecked():
                        n += 1
    return n


def _post_style(page) -> Dict:
    """一次性后处理：按钮上色、表格列宽（故障列不再吃满）、中部功能区可拖动。"""
    _paint_buttons(page)

    # 表格列宽：故障列固定宽，余量给电压类数据列，解决"故障列占比太宽"
    for tbl in page.findChildren(QTableWidget):
        hdr = tbl.horizontalHeader()
        hdr.setStretchLastSection(False)
        stretch_col = None
        for c in range(tbl.columnCount()):
            item = tbl.horizontalHeaderItem(c)
            t = item.text() if item else ""
            if "故障" in t:
                tbl.setColumnWidth(c, 130)
            elif stretch_col is None and ("电压" in t or "地址" in t):
                stretch_col = c
            # 含行内按钮的列给足宽度，防止"单关/设置"按钮被压缩裁切
            if any(isinstance(tbl.cellWidget(r, c), QPushButton) for r in range(min(tbl.rowCount(), 20))):
                tbl.setColumnWidth(c, max(tbl.columnWidth(c), 64))
        if stretch_col is not None:
            hdr.setSectionResizeMode(stretch_col, hdr.Stretch)

    # 中部水平分割条（表格 | 右侧功能区）：显式最小宽度覆盖最小尺寸提示，保证可拖动缩放
    for sp in page.findChildren(QSplitter):
        if sp.orientation() == Qt.Horizontal and sp.count() == 2:
            sp.setCollapsible(0, False)
            sp.setCollapsible(1, False)
            sp.widget(0).setMinimumWidth(360)
            sp.widget(1).setMinimumWidth(240)
            # 解除模块里 setFixedWidth 之类写死的宽度，否则手柄拖不动
            for i in (0, 1):
                sp.widget(i).setMaximumWidth(16777215)

    state = {"sel_labels": [lb for lb in page.findChildren(QLabel) if "已选" in lb.text()]}
    # 串口下拉自动刷新：插上 USB 转串口即可见，打开页面后无需手动刷新
    from .serial_ports import install_auto_refresh
    state["port_refreshers"] = install_auto_refresh(page)
    # 连接按钮状态跟踪：断开按钮初始禁用的模块，以"断开可用"判定已连接
    state["conn_btn"] = None
    state["dis_btn"] = None
    for b in page.findChildren(QPushButton):
        t = b.text().strip()
        if state["conn_btn"] is None and "连接" in t and "断开" not in t and "已连接" not in t:
            state["conn_btn"] = b
        if state["dis_btn"] is None and "断开" in t:
            state["dis_btn"] = b
    dis = state["dis_btn"]
    state["dis_init_disabled"] = dis is not None and not dis.isEnabled()
    if state["conn_btn"] is not None:
        state["conn_text"] = state["conn_btn"].text().strip()
    # 连接握手语义（平台规范）：「已连接」需设备应答；无应答 10s 自动断开；
    # 透传工具（portOpenOnly，如串口调试助手）保持「已连接=端口打开」语义
    state["had_ok"] = False
    state["port_open_only"] = bool(state["conn_btn"] is not None
                                   and state["conn_btn"].property("portOpenOnly"))
    wd = QTimer(page)
    wd.setSingleShot(True)
    wd.setInterval(10000)
    wd.timeout.connect(lambda _=False, p=page, s=state: _on_link_timeout(p, s))
    state["wd_timer"] = wd
    # 双按钮模块：「已连接」按钮再按 = 转发断开（统一交互）
    state["conn_repress"] = None
    if (state["conn_btn"] is not None and dis is not None
            and dis is not state["conn_btn"]
            and dis.text().strip() in ("断开", "关闭连接")
            and not dis.property("selfStyled")):
        flt = _ConnRepress(state["conn_btn"], dis, state["conn_btn"])
        state["conn_btn"].installEventFilter(flt)
        state["conn_repress"] = flt
    # 通讯状态指示灯：连接配置右侧，真通讯（有效应答）才亮「连接成功」
    state["conn_indicator"] = _attach_conn_indicator(page, state)
    state["comm_reset_filter"] = None
    if state["conn_btn"] is not None:
        crf = _CommPressReset(page, state["conn_btn"])
        state["conn_btn"].installEventFilter(crf)
        if dis is not None:
            dis.installEventFilter(crf)
        state["comm_reset_filter"] = crf
    return state


def _tick(page, state, sel_label=None) -> None:
    """周期刷新：连接按钮「已连接」态、按钮上色纠正、已选数量颜色（0 正常 / ≥1 绿）。"""
    conn, dis = state.get("conn_btn"), state.get("dis_btn")
    if conn is not None:
        connected = (conn.objectName() == "btnConnected"
                     or (state.get("dis_init_disabled") and dis is not None and dis.isEnabled()))
        ind = state.get("conn_indicator") or get_indicator(page)
        comm_ok = bool(ind is not None and ind.is_ok)
        if comm_ok:
            state["had_ok"] = True
        # 不变式：未连接时通讯指示灯必须回「未连接」——断开瞬间的残留应答会把灯
        # 留在「连接成功」，这里每周期强制拉回（真实应答仍会重新点亮）
        if ind is not None and not connected and ind.is_ok:
            from . import comm_state
            comm_state.reset(page)
            comm_ok = False
        if not connected:
            state["had_ok"] = False
            wd = state.get("wd_timer")
            if wd is not None:
                wd.stop()
        elif not state.get("had_ok") and not state.get("port_open_only"):
            # 握手窗口：连接后 10s 内设备全程无应答 → 自动断开（RX=0 不再挂假「已连接」）。
            # 模块自管握手（属性 connecting，自带超时）期间框架让位，避免双看门狗打架
            wd = state.get("wd_timer")
            if (wd is not None and not wd.isActive()
                    and not conn.property("connecting")):
                wd.start()
        want = _conn_want_text(connected, comm_ok, bool(state.get("had_ok")),
                              bool(state.get("port_open_only")),
                              state.get("conn_text", "连接"))
        # 「连接中…」握手态由模块自管时（属性 connecting）框架不回写
        if not conn.property("connecting") and conn.text().strip() != want:
            conn.setText(want)
        # 「已连接」保持可按（再按=断开）；模块自身禁用由统一交互接管
        if connected and state.get("conn_repress") is not None and not conn.isEnabled():
            conn.setEnabled(True)
    _paint_buttons(page)   # 文本更新后再上色（已连接→绿色）

    n = _count_checked(page)
    if sel_label is not None:
        sel_label.setText(f"已选: {n}")
        sel_label.setStyleSheet(
            "color:#047857; font-weight:700; font-size:13px;" if n >= 1
            else "color:#23263A; font-weight:600; font-size:13px;")
    for lb in state.get("sel_labels", []):
        t = lb.text()
        plain = re.sub(r"<[^>]+>", "", t)
        m = re.search(r"已选[:：]?\s*(\d+)", plain)
        if m is None:
            continue
        if int(m.group(1)) >= 1:
            if "<span" not in t:
                lb.setText(re.sub(r"(已选[:：]?\s*\d+)",
                                  r'<span style="color:#047857; font-weight:700">\1</span>', plain))
        elif "<span" in t:
            lb.setText(plain)


class ModuleHostPage(QWidget):
    """单个模块上位机的融合页：头部信息条 + 嵌入的模块主窗口。"""

    def __init__(self, mod: Dict, recorder=None, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.recorder = recorder          # 调试记录器：模块操作同样留痕、可追溯
        self.rec_spec = recorder_spec(mod)
        self._last_conn = None
        self.page = None          # 嵌入的模块主窗口
        self._pkg = None          # 模块包（shutdown 时调用其清理逻辑）

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        head = Card()
        h = QVBoxLayout()
        h.setSpacing(6)
        head.body_lay.addLayout(h)

        row = QHBoxLayout()
        row.setSpacing(10)
        t = QLabel(mod["name"])
        t.setObjectName("H1")
        row.addWidget(t)
        row.addWidget(Chip(mod["vendor"], "#4F46E5", "#EEF0FF"))
        row.addWidget(Chip(mod["proto"], "#0E7490", "#CFFAFE"))
        row.addStretch(1)
        btn_help = QPushButton("帮助")
        btn_help.setToolTip("模块基础参数与快速上手")
        btn_help.clicked.connect(self._show_help)
        row.addWidget(btn_help)
        btn_fault = QPushButton("故障代码查询")
        btn_fault.setToolTip("模块故障代码与调试故障排查")
        btn_fault.clicked.connect(self._show_fault)
        row.addWidget(btn_fault)
        self.sel_label = QLabel("已选: 0")   # 已选数量：0 正常色，≥1 绿色（图二规范）
        self.sel_label.setStyleSheet("color:#23263A; font-weight:600; font-size:13px;")
        row.addWidget(self.sel_label)
        row.addWidget(Chip("融合页 · 统一 UI 风格", "#047857", "#D1FAE5"))
        h.addLayout(row)
        sub = QLabel(f"{mod['summary']}　·　融合自原独立上位机工程（逻辑层复用），风格已适配整体 UI")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        h.addWidget(sub)
        root.addWidget(head)

        self.host = QWidget()
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.host, 1)

        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            self._pkg = importlib.import_module(self.mod["pkg"])
            self.page = self._pkg.create_page(self.host)
            self.page.setStyleSheet(QSS_EMBED)   # 风格适配：替换模块自带主题（紧凑版，防裁切）
            _wrap_log_splitter(self.page)         # 通讯日志区改可拖动分割条（各模块通用）
            from .layout_mem import bind_splitters
            bind_splitters(self.page, self.mod["id"])   # 分割条拖动记忆（关平台重开恢复）
            self._state = _post_style(self.page)  # 按钮上色 / 列宽 / 功能区可拖 / 状态跟踪
            self._hook_events()                   # 按钮操作留痕（调试记录可追溯）
            self._timer = QTimer(self)            # 周期纠正：连接态「已连接」、已选数量颜色
            self._timer.setInterval(700)
            self._timer.timeout.connect(self._on_tick)
            self._timer.start()
            # 包滚动区：嵌入页的最小尺寸不再挤压左侧目录，超宽/超高时滚动而不是撑爆布局
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
            scroll.setWidget(self.page)
            self.host_lay.addWidget(scroll, 1)
        except Exception:
            self.page = None
            err = Card("模块加载失败", "上位机其余功能不受影响；可按下方信息排查依赖")
            msg = QLabel("".join(traceback.format_exception_only(*__import__("sys").exc_info()[:2])).strip())
            msg.setObjectName("Banner")
            msg.setWordWrap(True)
            err.body_lay.addWidget(msg)
            detail = QLabel("<pre style='color:#7A7B93; font-size:11px;'>"
                            + traceback.format_exc().replace("<", "&lt;") + "</pre>")
            detail.setWordWrap(True)
            detail.setTextFormat(1)   # Qt.RichText
            err.body_lay.addWidget(detail)
            self.host_lay.addWidget(err, 1)

    def _on_tick(self) -> None:
        _tick(self.page, self._state, self.sel_label)
        # 连接状态变化 → 记入调试记录（连接/断开留痕）
        conn = self._state.get("conn_btn")
        if conn is not None and self.recorder is not None:
            connected = conn.text().strip() == "已连接"
            if self._last_conn is None:
                self._last_conn = connected
            elif connected != self._last_conn:
                self._last_conn = connected
                self._record_event("通讯连接", "连接", "已连接" if connected else "断开")

    def _hook_events(self) -> None:
        """模块内按钮点击全部留痕：开机/关机/设置/扫描等操作进调试记录，可追溯。"""
        if self.recorder is None:
            return
        for b in self.page.findChildren(QPushButton):
            b.clicked.connect(lambda _=False, btn=b: self._record_event(btn.text(), "操作", "点击"))

    def _record_event(self, item: str, kind: str, value, unit: str = "-", note: str = "") -> None:
        if self.recorder is None or self.page is None:
            return
        addr, baud, port_no = _conn_info(self.page)
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", addr):
            self.rec_spec.ip = addr
            session_addr = addr
        else:
            self.rec_spec.ip = "-"
            session_addr = addr if addr != "-" else "-"
        self.rec_spec.port_no = port_no
        self.recorder.record_event(
            self.rec_spec,
            types.SimpleNamespace(connected=True, port=session_addr, baud=baud),
            item, kind, value, unit, note)

    def _show_help(self) -> None:
        """帮助：模块基础参数 + 协议 + 快速上手，便于快速了解模块和上位机。"""
        m = self.mod
        if m["id"] in CHARGING_IDS:
            steps = ("快速上手：\n"
                     "① 顶部连接配置：填 IP/端口（或串口参数）→ 连接；\n"
                     "② 右上角：一键初始化 / 扫描在线模块 / 故障代码查询；\n"
                     "③ 批量操作：全部开机/关机、批量设置电压电流；\n"
                     "④ 模块实时监控：单模块开机/关机/设置 V/I；\n"
                     "⑤ 底部报文日志：定位通讯问题。\n\n"
                     "安全：开启输出/开机前确认接线与量程；退出上位机自动停机断开。")
        else:
            steps = ("快速上手：\n"
                     "① 顶部连接配置：选择接口并填好通讯参数 → 连接；\n"
                     "② 按页面分区操作：设定/控制区下发命令，监控区看回读；\n"
                     "③ 涉及输出/高压/拉载的操作均有二次确认，确认接线与量程后再执行；\n"
                     "④ 底部报文日志：定位通讯问题。\n\n"
                     "安全：退出上位机自动停机断开。")
        QMessageBox.information(
            self, f"帮助 · {m['name']}",
            f"{m['summary']}\n\n"
            f"厂商：{m['vendor']}　　协议/接口：{m['proto']}\n"
            f"来源：原独立上位机工程（逻辑层复用，界面按整体 UI 风格适配）\n\n"
            + steps)

    def _show_fault(self) -> None:
        """故障代码查询：优先调用模块自带的故障码查询，其次给排查指引。"""
        if self.page is not None:
            for btn in self.page.findChildren(QPushButton):
                # 只点「故障代码/故障查询」类按钮，避免误触发“清除故障”这类指令按钮
                if ("故障代码" in btn.text() or "故障查询" in btn.text()) and btn.isEnabled():
                    try:
                        btn.click()
                    except Exception:
                        traceback.print_exc()
                        QMessageBox.warning(self, "故障代码查询",
                                            "模块自带的故障查询执行出错，已跳过。\n请按下方指引排查。")
                    else:
                        return
                    break
        QMessageBox.information(
            self, "故障代码查询",
            "该模块页未内置故障码查询入口，按以下顺序排查：\n"
            "1) 通讯链路：网线/串口线、IP/端口、波特率、从机地址；\n"
            "2) 模块报文日志：看请求是否有响应、异常码是多少；\n"
            "3) 模块面板故障指示灯/液晶告警；\n"
            "4) 厂家协议手册的故障代码表；\n"
            "5) 本模块调试中遇到的故障可在「调试记录」页归档追溯。")

    def is_connected(self) -> bool:
        """当前模块是否已连接（供目录指示灯/切换弹窗判定）。"""
        st = getattr(self, "_state", None) or {}
        conn, dis = st.get("conn_btn"), st.get("dis_btn")
        if conn is None:
            return False
        return (conn.objectName() == "btnConnected"
                or (st.get("dis_init_disabled") and dis is not None and dis.isEnabled()))

    def shutdown(self) -> None:
        """退出上位机时触发模块清理（停输出、断开连接、回收线程）。"""
        if self._pkg is not None and self.page is not None:
            try:
                self._pkg.shutdown(self.page)
            except Exception:
                pass
