# -*- coding: utf-8 -*-
"""应用配置读写。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .modbus import ModbusConfig


@dataclass
class AppConfig:
    series: str = "XD3"
    mode: str = "rtu"
    port: str = "COM3"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: float = 1
    bytesize: int = 8
    host: str = "192.168.1.10"
    tcp_port: int = 502
    slave_id: int = 1
    timeout: float = 0.5
    poll_interval: float = 0.2
    tags: list = field(default_factory=list)      # [{name,label,kind,...}]
    alarms: list = field(default_factory=list)

    def to_modbus_config(self) -> ModbusConfig:
        return ModbusConfig(
            mode=self.mode,
            port=self.port,
            baudrate=self.baudrate,
            bytesize=self.bytesize,
            parity=self.parity,
            stopbits=self.stopbits,
            host=self.host,
            tcp_port=self.tcp_port,
            slave_id=self.slave_id,
            timeout=self.timeout,
        )


def config_path() -> Path:
    return Path.home() / ".xinje_host" / "config.json"


def load_config(path: Optional[Path] = None) -> AppConfig:
    p = path or config_path()
    if not p.exists():
        return AppConfig()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        known = {k: data[k] for k in data if k in AppConfig.__dataclass_fields__}
        return AppConfig(**known)
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p
