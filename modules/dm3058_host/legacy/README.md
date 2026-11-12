# legacy —— 旧版 tkinter 界面（已弃用）

本目录存放 DM3058 万用表**旧版 tkinter 界面**，已从 `core/` 移出，**不再被任何代码引用**。

| 文件 | 说明 |
|---|---|
| `ui_app.py` | 旧版 tkinter 主窗口（`App(tk.Tk)`，1184 行） |
| `ui_chart.py` | 旧版 tkinter 趋势曲线（`TrendChart`） |

## 为何弃用

- 融合平台统一采用 **PyQt5**（`modules/dm3058_host/page.py` 的 `Dm3058Page`）。
- 协议栈（`core/instrument.py`、`core/transport.py`、`core/defs.py`）两版共用，不受影响。
- 旧版内部 `from .ui_chart import TrendChart`、`from .instrument import ...` 使用相对导入，移到 `legacy/` 后**已无法直接运行**——如需参考旧逻辑，可复制回 `core/` 临时查看。

## 功能迁移对照（2026-11-04 逐项核对，防丢功能）

- **已全部迁移到 PyQt5 页面（2.46.0 起零缺项）**：串口（波特率/校验位）、网口、USB-TMC（VISA + pyusb 扫描与自动匹配）、模拟器、11 种测量功能（分类着色+选中态）、量程/速率/交流滤波/DC 输入阻抗/通断极限、采样间隔、双显 FUNCtion2、实时读数、数学运算（REL/dB/dBm/P-F）、统计（MIN/MAX/AVG/CNT）、实时趋势、CSV 记录、SCPI 控制台、仪器自检（*RST/*CLS/查询错误/蜂鸣）、使用说明、通讯日志。
- **无暂缺项**。旧版界面功能面已清零核对完毕。

## 处理建议

- 确认不再需要旧版界面后，可直接删除本目录（删除前按上方对照表确认所需功能均已迁移）。
