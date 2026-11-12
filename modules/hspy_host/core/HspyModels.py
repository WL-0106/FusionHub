# -*- coding: utf-8 -*-
"""
HSPY 电源「机型预设」表
=======================
把各机型的量程与换算关系固化下来，界面上一键切换即可，不必再手算小数位。

为什么会「设 1 A 实出 10 A」？
    上位机下发的永远是 16 位整数（原始值），
        原始值 = 物理量 × 10^小数位
    各机型（甚至同型号不同批次）对「小数位」的理解并不一致：
      · 官方通用协议表写「电流 3 位小数（÷1000）」——那是低压机型口径
      · HSPY-1000-01 实测电流是 4 位小数（÷10000，1 LSB = 0.1 mA）
      · HSPY-30-20 实测电流是 2 位小数（÷100，1 LSB = 10 mA）
    差一个小数位 = 差 10 倍。所以本表把每种机型的正确值直接固化。

每个预设包含：
    vmax / imax / pmax   —— 滑块与输入校验用的量程上限
    vdec / vshow         —— 电压「设定 / 显示」小数位
    idec / ishow         —— 电流「设定 / 显示」小数位
    pdec / pshow         —— 功率「设定 / 显示」小数位
    ovpdec / ocpdec      —— 过压 / 过流保护门限的小数位
    power                —— 额定功率，用于仿真
    note / source        —— 说明与依据
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 「通用 / 自定义」＝协议文档默认口径，也是没选机型时的兜底
GENERIC = '通用 / 自定义（协议默认）'
HSPY_1000_01 = 'HSPY-1000-01（1000V / 1A）'
HSPY_30_20 = 'HSPY-30-20（30V / 20A）'
CUSTOM = '自定义（手动填写）'

DEFAULT_MODEL = GENERIC


@dataclass(frozen=True)
class ModelPreset:
    name: str
    vmax: float
    imax: float
    pmax: float
    vdec: int
    vshow: int
    idec: int
    ishow: int
    pdec: int
    pshow: int
    ovpdec: int
    ocpdec: int
    note: str = ''
    source: str = ''
    extra: dict = field(default_factory=dict)

    # ---- 换算系数：1 个原始值代表多少物理量，等价于 ×10、×10000 这种写法 ---- #
    @property
    def v_scale(self) -> float:
        return float(10 ** self.vdec)

    @property
    def i_scale(self) -> float:
        return float(10 ** self.idec)

    @property
    def p_scale(self) -> float:
        return float(10 ** self.pdec)

    def summary(self) -> str:
        return (f'{self.name}：电压 {self.vmax:g} V（×{self.v_scale:g}，'
                f'{self.vdec} 位小数）· 电流 {self.imax:g} A（×{self.i_scale:g}，'
                f'{self.idec} 位小数）· 功率 {self.pmax:g} W')


MODELS: dict[str, ModelPreset] = {
    GENERIC: ModelPreset(
        name=GENERIC,
        vmax=60.0, imax=10.0, pmax=600.0,
        vdec=2, vshow=2, idec=3, ishow=3, pdec=1, pshow=1,
        ovpdec=2, ocpdec=3,
        note='协议文档（HSPY 大功率 2020）默认口径：电压 2 位、电流 3 位、功率 1 位小数。',
        source='《HSPY大功率通讯协议(2020)》',
    ),
    HSPY_1000_01: ModelPreset(
        name=HSPY_1000_01,
        vmax=1000.0, imax=1.0, pmax=1000.0,
        vdec=0, vshow=0, idec=4, ishow=4, pdec=1, pshow=1,
        ovpdec=0, ocpdec=4,
        note='高压机：电压系数 ×1（1 LSB = 1 V，0 位小数，2026-11-05 用户实测确认，'
             '原按面板反推的 ×10 作废）；电流 4 位小数（1 LSB = 0.1 mA，×10000）。'
             '面板电流以 mA 显示并保留 1 位小数，故为 ×10000 而非 ×1000。',
        source='实物面板反推 + 用户实测验证（电压系数 ×1）',
    ),
    HSPY_30_20: ModelPreset(
        name=HSPY_30_20,
        vmax=30.0, imax=20.0, pmax=600.0,
        vdec=2, vshow=2, idec=2, ishow=2, pdec=1, pshow=1,
        ovpdec=2, ocpdec=2,
        note='低压大电流机：电压 2 位小数（×100）；'
             '电流实测为 2 位小数（1 LSB = 10 mA，×100），不是文档写的 3 位。',
        source='现场实测：下发原始值 1000，面板显示 10.00 A',
    ),
}


def model_names() -> list[str]:
    """下拉框用：可选机型列表（自定义放最后）。"""
    return [GENERIC, HSPY_1000_01, HSPY_30_20, CUSTOM]


def get_model(name: str) -> ModelPreset:
    return MODELS.get(name, MODELS[DEFAULT_MODEL])


def detect_by_ranges(vmax, imax, vdec, idec) -> str:
    """按当前量程/小数位反向识别是哪台机型，认不出就返回「自定义」。"""
    for key, p in MODELS.items():
        if (abs(float(vmax) - p.vmax) < 1e-6 and abs(float(imax) - p.imax) < 1e-6
                and int(vdec) == p.vdec and int(idec) == p.idec):
            return key
    return CUSTOM


if __name__ == '__main__':
    for k in model_names():
        print(get_model(k).summary())
    assert get_model(HSPY_1000_01).i_scale == 10000
    assert get_model(HSPY_30_20).idec == 2
    assert detect_by_ranges(1000, 1, 0, 4) == HSPY_1000_01
    assert detect_by_ranges(30, 20, 2, 2) == HSPY_30_20
    assert detect_by_ranges(60, 10, 2, 3) == GENERIC
    assert detect_by_ranges(12, 3, 2, 3) == CUSTOM
    print('HspyModels 自检通过 ✔')
