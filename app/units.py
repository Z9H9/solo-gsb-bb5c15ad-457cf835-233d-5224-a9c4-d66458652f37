"""单位归一化。

服务端把所有量统一到内部基准单位后再求解：
- 体积: mL
- 质量: mg
- 浓度(质量/体积): mg/mL
- 摩尔浓度(mol/L)通过摩尔质量(g/mol)换算为 mg/mL: 1 mol/L = M g/L = M mg/mL
- 密度: g/mL

支持的浓度写法(带常见别名):
  mg/mL, g/L, mg/L, ug/mL(µg/mL), g/100mL, %(w/v), %(w/w)
  mol/L(M), mmol/L(mM)
其中 %(w/v) = g/100mL; %(w/w) 需要借助密度换算为 g/100mL。
"""
from __future__ import annotations


class UnitError(ValueError):
    """用户输入的单位无法识别或缺少换算所需参数。"""


_VOLUME_FACTOR = {  # -> mL
    "ml": 1.0,
    "l": 1000.0,
    "ul": 0.001,  # µL
}

_DENSITY_FACTOR = {  # -> g/mL
    "g/ml": 1.0,
    "g/cm3": 1.0,
    "kg/m3": 0.001,
    "kg/l": 1.0,
    "g/l": 0.001,
}

# 质量/体积类浓度 -> mg/mL
_MASS_VOL_CONC = {
    "mg/ml": 1.0,
    "g/l": 1.0,
    "mg/l": 0.001,
    "ug/ml": 0.001,   # 1 µg/mL = 0.001 mg/mL
    "µg/ml": 0.001,
    "g/100ml": 10.0,  # 1 g/100mL = 10 mg/mL
}

_SUPPORTED_CONC = (
    "mg/mL", "g/L", "mg/L", "µg/mL", "g/100mL",
    "%(w/v)", "%(w/w)", "mol/L", "mmol/L",
)


def normalize_unit(unit: str) -> str:
    return (
        (unit or "")
        .strip()
        .lower()
        .replace("μ", "µ")
        .replace("µ", "u")
        .replace(" ", "")
    )


def volume_to_ml(value: float, unit: str) -> float:
    key = normalize_unit(unit)
    if key not in _VOLUME_FACTOR:
        raise UnitError(f"不支持的体积单位“{unit}”，支持: mL、L、µL")
    return value * _VOLUME_FACTOR[key]


def density_to_g_per_ml(value: float, unit: str) -> float:
    key = normalize_unit(unit)
    if key not in _DENSITY_FACTOR:
        raise UnitError(f"不支持的密度单位“{unit}”，支持: g/mL、g/cm³、kg/m³、kg/L")
    return value * _DENSITY_FACTOR[key]


def is_weight_percent(unit: str) -> bool:
    return normalize_unit(unit) in ("%(w/w)", "wt%", "%w/w", "质量百分比")


def concentration_to_mg_per_ml(
    value: float,
    unit: str,
    *,
    molar_mass: float | None = None,
    density: float | None = None,
) -> float:
    """把任意受支持的浓度值换算为 mg/mL。

    molar_mass 单位 g/mol, mol/L 时必需;
    density 单位 g/mL, %(w/w) 时必需。
    """
    key = normalize_unit(unit)
    if key in _MASS_VOL_CONC:
        return value * _MASS_VOL_CONC[key]
    if key in ("%(w/v)", "%w/v", "质量体积百分比"):
        # 1%(w/v) = 1 g / 100 mL = 10 mg/mL
        return value * 10.0
    if is_weight_percent(unit):
        if density is None:
            raise UnitError("使用 %(w/w) 浓度时必须填写溶液密度")
        # w g 溶质 / 100 g 溶液; 溶液体积 = 100/ρ mL
        # => g/mL = w*ρ/100 => mg/mL = w*ρ*10
        return value * density * 10.0
    if key in ("mol/l", "m", "molar"):
        if not molar_mass:
            raise UnitError("使用 mol/L 浓度时必须填写该溶质的摩尔质量(g/mol)")
        # 1 mol/L = M g/L = M mg/mL
        return value * molar_mass
    if key in ("mmol/l", "mm"):
        if not molar_mass:
            raise UnitError("使用 mmol/L 浓度时必须填写该溶质的摩尔质量(g/mol)")
        # 1 mmol/L = M mg/L = M*0.001 mg/mL
        return value * molar_mass * 0.001
    raise UnitError(
        f"不支持的浓度单位“{unit}”，支持: {', '.join(_SUPPORTED_CONC)}"
    )


def mg_per_ml_to(value_mg_per_ml: float, unit: str, *, molar_mass: float | None = None) -> float:
    """mg/mL 逆换算为指定单位(用于结果按目标单位展示)。

    目标浓度不允许 %(w/w)/%(w/v) 以外的百分比歧义时前端会限制;
    这里只处理线性可逆的单位。
    """
    key = normalize_unit(unit)
    if key in _MASS_VOL_CONC:
        return value_mg_per_ml / _MASS_VOL_CONC[key]
    if key in ("%(w/v)", "%w/v", "质量体积百分比"):
        return value_mg_per_ml / 10.0
    if key in ("mol/l", "m", "molar"):
        if not molar_mass:
            raise UnitError("换算回 mol/L 需要摩尔质量")
        return value_mg_per_ml / molar_mass
    if key in ("mmol/l", "mm"):
        if not molar_mass:
            raise UnitError("换算回 mmol/L 需要摩尔质量")
        return value_mg_per_ml / (molar_mass * 0.001)
    raise UnitError(f"结果不支持换算回单位“{unit}”")
