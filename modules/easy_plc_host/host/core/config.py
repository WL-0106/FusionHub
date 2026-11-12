"""连接配置读写 (JSON)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")


@dataclass
class ConnectionConfig:
    mode: str = "TCP"  # TCP | RTU
    # TCP
    host: str = "192.168.1.88"
    port: int = 502
    # RTU
    com_port: str = "COM3"
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1
    # common
    slave: int = 1
    series: str = "EASY300"
    poll_interval: float = 0.2
    x_count: int = 32
    y_count: int = 32
    m_count: int = 64
    d_count: int = 64

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ConnectionConfig":
        cfg = ConnectionConfig()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg


def save_config(cfg: ConnectionConfig, path: str = DEFAULT_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)


def load_config(path: str = DEFAULT_PATH) -> ConnectionConfig:
    if not os.path.isfile(path):
        return ConnectionConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ConnectionConfig.from_dict(data)
    except (OSError, json.JSONDecodeError, TypeError):
        return ConnectionConfig()
