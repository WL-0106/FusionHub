# -*- coding: utf-8 -*-
"""仪器注册表：新增仪器只需在 instruments/ 下新建模块并 register(spec)，框架零改动。"""
from typing import Dict, List

from .spec import InstrumentSpec

SPECS: Dict[str, InstrumentSpec] = {}

# 二级目录（左侧导航固定五类）；spec.group 留空时按 category 自动归类
NAV_GROUPS = ["AC/DC源", "仪器仪表", "调试助手", "PLC", "采集卡"]
GROUP_BY_CATEGORY = {
    "直流电源": "AC/DC源", "交流电源": "AC/DC源", "AC/DC源": "AC/DC源",
    "万用表": "仪器仪表", "电子负载": "仪器仪表", "示波器": "仪器仪表",
    "仪器仪表": "仪器仪表",
    "调试助手": "调试助手", "PLC": "PLC", "采集卡": "采集卡",
}


def register(spec: InstrumentSpec) -> InstrumentSpec:
    if spec.id in SPECS:
        raise ValueError(f"仪器 id 重复: {spec.id}")
    if not spec.group:
        spec.group = GROUP_BY_CATEGORY.get(spec.category, "仪器仪表")
    SPECS[spec.id] = spec
    return spec


def all_specs() -> List[InstrumentSpec]:
    return list(SPECS.values())


def get_spec(spec_id: str) -> InstrumentSpec:
    return SPECS[spec_id]


def categories() -> "Dict[str, List[InstrumentSpec]]":
    """按 category 分组，保持注册顺序。"""
    grouped: Dict[str, List[InstrumentSpec]] = {}
    for spec in SPECS.values():
        grouped.setdefault(spec.category, []).append(spec)
    return grouped


def by_group() -> "Dict[str, List[InstrumentSpec]]":
    """按二级目录（NAV_GROUPS）分组，五类全部返回（空类为空列表）。"""
    grouped: Dict[str, List[InstrumentSpec]] = {g: [] for g in NAV_GROUPS}
    for spec in SPECS.values():
        grouped.setdefault(spec.group, []).append(spec)
    return grouped
