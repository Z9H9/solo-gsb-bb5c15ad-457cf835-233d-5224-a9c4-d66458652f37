"""单位换算模块：把浓度、密度、体积统一到内部标准单位。

内部标准（规范单位）：
- 体积：mL
- 密度：g/mL
- 摩尔浓度族（molar）： mol/L，amount 以 mol 表示
- 质量浓度族（mass）： g/L，  amount 以 g 表示
- 体积分数族（volfrac）：mL/mL（无量纲比值），amount 以 mL 表示
- 质量分数族（ww）：    每 mL 溶液中溶质的克数 g/mL，amount 以 g 表示
  （需要密度才能与其它单位族互转，因此 ww 仅在同时提供密度时有效）
"""

# ---------------------------------------------------------------------------
# 体积：统一到 mL
# ---------------------------------------------------------------------------
VOLUME_TO_ML = {
    "mL": 1.0,
    "L": 1000.0,
    "uL": 0.001,
    "µL": 0.001,  # 兼容希腊字母 mu
}

# ---------------------------------------------------------------------------
# 密度：统一到 g/mL
# ---------------------------------------------------------------------------
DENSITY_TO_G_PER_ML = {
    "g/mL": 1.0,
    "g/L": 0.001,
    "kg/L": 1.0,
    "kg/m3": 0.001,
}

# ---------------------------------------------------------------------------
# 浓度单位 -> (族, 换算为规范浓度的系数)
# molar 族规范为 mol/L；mass 族规范为 g/L；volfrac 族规范为 mL/mL
# ---------------------------------------------------------------------------
MOLAR_UNITS = {
    "M": 1.0,
    "mM": 0.001,
    "uM": 1e-6,
    "µM": 1e-6,
    "mol/L": 1.0,
    "mmol/L": 0.001,
}

MASS_UNITS = {
    "g/L": 1.0,
    "mg/L": 0.001,
    "mg/mL": 1.0,
    "g/mL": 1000.0,
    "ug/mL": 0.001,
    "µg/mL": 0.001,
    "kg/m3": 1.0,  # 1 kg/m³ == 1 g/L
}

VOLFRAC_UNITS = {
    "%(v/v)": 0.01,
    "v/v": 1.0,
}

WW_UNITS = {
    "%(w/w)": 0.01,
    "w/w": 1.0,
}

# 族 -> 规范单位名称
CANONICAL_UNIT = {
    "molar": "mol/L",
    "mass": "g/L",
    "volfrac": "v/v",
    "ww": "g/mL",
}

EPS = 1e-9


class UnitError(ValueError):
    """单位不受支持或缺少必要参数（如密度）。"""


def convert_volume(value: float, unit: str) -> float:
    """体积换算为 mL。"""
    factor = VOLUME_TO_ML.get(unit)
    if factor is None:
        raise UnitError(f"不支持的体积单位：{unit}")
    return value * factor


def convert_density(value: float, unit: str) -> float:
    """密度换算为 g/mL。"""
    factor = DENSITY_TO_G_PER_ML.get(unit)
    if factor is None:
        raise UnitError(f"不支持的密度单位：{unit}")
    return value * factor


def concentration_family(unit: str) -> str:
    """返回浓度单位所属族：molar / mass / volfrac / ww。"""
    if unit in MOLAR_UNITS:
        return "molar"
    if unit in MASS_UNITS:
        return "mass"
    if unit in VOLFRAC_UNITS:
        return "volfrac"
    if unit in WW_UNITS:
        return "ww"
    raise UnitError(f"不支持的浓度单位：{unit}")


def canonical_concentration(value: float, unit: str, density_g_per_ml=None):
    """把浓度换算为 (族, 规范浓度值)。

    w/w 族必须提供密度 g/mL，规范为 g/mL（每 mL 溶液中溶质克数）。
    """
    family = concentration_family(unit)
    if family == "molar":
        return family, value * MOLAR_UNITS[unit]
    if family == "mass":
        return family, value * MASS_UNITS[unit]
    if family == "volfrac":
        return family, value * VOLFRAC_UNITS[unit]
    # w/w：质量分数 × 密度(g/mL) = 每 mL 溶液中溶质克数
    if density_g_per_ml is None:
        raise UnitError(
            f"库存液使用 {unit}（质量分数）时必须提供密度，才能与体积守恒联立求解"
        )
    return family, value * WW_UNITS[unit] * density_g_per_ml


def families_compatible(f1: str, f2: str) -> bool:
    """同一种溶质的库存液与目标浓度是否可比较（同量纲族即可，ww 视作质量族）。"""
    return f1 == f2 or {f1, f2} <= {"mass", "ww"}


# 规范浓度 c 与体积 V(mL) 求溶质量时的系数： amount = c * V_mL * factor
# molar(mol/L) / mass(g/L) 的浓度以“每升”计，故 /1000；
# ww(g/mL) / volfrac(mL/mL) 以“每 mL”计，系数为 1
AMOUNT_FACTOR = {
    "molar": 0.001,
    "mass": 0.001,
    "ww": 1.0,
    "volfrac": 1.0,
}


def amount_for_volume(c_canonical: float, volume_ml: float, family: str) -> float:
    """规范浓度 × 体积(mL) -> 溶质的规范量（mol / g / mL）。"""
    return c_canonical * volume_ml * AMOUNT_FACTOR[family]


def volume_for_amount(amount: float, c_canonical: float, family: str) -> float:
    """溶质规范量 -> 所需溶液体积(mL)。"""
    return amount / c_canonical / AMOUNT_FACTOR[family]


def concentration_from_amount(amount: float, volume_ml: float,
                              family: str) -> float:
    """溶质规范量 / 混合体积(mL) -> 规范浓度。"""
    return amount / volume_ml / AMOUNT_FACTOR[family]


def effective_conc(conc_canonical: float, family: str, target_family: str) -> float:
    """把库存液规范浓度换算到目标单位族口径（同质量族 ww<->g/L 可互转）。"""
    if family == target_family:
        return conc_canonical
    # g/mL（ww）= 1000 g/L（mass）；仅质量族内部允许
    if {family, target_family} <= {"mass", "ww"}:
        if family == "ww":
            return conc_canonical * 1000.0
        return conc_canonical / 1000.0
    return conc_canonical  # 不可比的族在求解器中已提前拦截


def amount_to_canonical(amount: float, family: str):
    """兼容旧调用：把 c * V_mL 形式的乘积换算为规范量。"""
    return amount * AMOUNT_FACTOR[family]


def canonical_to_display(value: float, family: str) -> str:
    """把规范量格式化为带单位的展示文本。"""
    v = fmt_num(value)
    if family == "molar":
        return f"{v} mol"
    if family in ("mass", "ww"):
        return f"{v} g"
    return f"{v} mL"


def concentration_to_display(c_canonical: float, family: str) -> str:
    """规范浓度格式化为展示文本。"""
    v = fmt_num(c_canonical)
    return f"{v} {CANONICAL_UNIT[family]}"


def fmt_num(x: float, sig: int = 6) -> str:
    """智能数字格式化：绝对值很小按 0 处理，自动选择小数/科学计数。"""
    if x is None:
        return "-"
    if abs(x) < 5e-10:
        return "0"
    ax = abs(x)
    if ax < 1e-4 or ax >= 1e7:
        return f"{x:.{sig - 1}e}"
    # 普通小数，去掉多余尾零
    text = f"{x:.{sig}g}"
    return text


def fmt_volume(ml: float) -> str:
    """体积智能展示：>=1 L 用 L，否则 mL，微升级提示 uL。"""
    if ml is None:
        return "-"
    if abs(ml) < EPS:
        return "0 mL"
    if abs(ml) >= 1000 - 1e-9:
        return f"{fmt_num(ml / 1000.0)} L"
    if abs(ml) < 0.01:  # 小于 10 uL
        return f"{fmt_num(ml * 1000.0)} µL ({fmt_num(ml)} mL)"
    return f"{fmt_num(ml)} mL"
