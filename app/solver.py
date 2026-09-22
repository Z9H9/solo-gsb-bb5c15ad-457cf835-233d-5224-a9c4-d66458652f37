"""配液约束求解器。

数学模型（线性）：
  设第 j 种库存液取用 x_j (mL)，稀释剂补量 x_d (mL)，目标总体积 V (mL)。
  对每一种溶质 i，库存液 j 中该溶质的规范浓度为 c_ij：
      Σ_j c_ij * x_j = C_i * V          （溶质浓度约束，质量/摩尔/体积守恒）
      Σ_j x_j + x_d = V                 （体积守恒）
      0 <= x_j <= U_j                   （库存可用体积上限）
      x_d >= 0

由于目标配方中每种溶质相互独立，单溶质子问题为一维线性可行问题：
最小化 Σ x_j 时的贪心策略 —— 按浓度从高到低依次取液，即为最优解
（浓度越高，达到同样溶质量所需体积越小）。全局最小取液量若 <= V 即可行，
剩余体积全部由稀释剂补足。
"""

from dataclasses import dataclass, field

from .units import (
    EPS,
    amount_for_volume,
    canonical_concentration,
    canonical_to_display,
    concentration_from_amount,
    concentration_to_display,
    convert_density,
    convert_volume,
    effective_conc,
    families_compatible,
    fmt_num,
    fmt_volume,
    volume_for_amount,
)


@dataclass
class ParsedStock:
    id: object
    name: str
    solute: str
    family: str
    conc_canonical: float          # 规范浓度
    conc_display: str
    available_ml: float
    density_g_per_ml: float = None
    raw: dict = field(default_factory=dict)


@dataclass
class ParsedTarget:
    solute: str
    family: str
    conc_canonical: float
    conc_display: str


def _norm_solute(name: str) -> str:
    return (name or "").strip().lower()


def parse_stock(s: dict) -> ParsedStock:
    """校验并解析一条库存液记录。"""
    name = (s.get("name") or "").strip()
    solute = (s.get("solute") or "").strip()
    if not name:
        raise ValueError("存在未命名的库存液")
    if not solute:
        raise ValueError(f"库存液「{name}」未填写溶质名称")

    conc = s.get("concentration")
    unit = s.get("concentration_unit")
    if conc is None or not unit:
        raise ValueError(f"库存液「{name}」缺少浓度或浓度单位")
    if conc <= 0:
        raise ValueError(f"库存液「{name}」浓度必须为正数")

    avail = s.get("available_volume")
    vunit = s.get("volume_unit", "mL")
    if avail is None:
        raise ValueError(f"库存液「{name}」缺少可用体积")
    if avail <= 0:
        raise ValueError(f"库存液「{name}」可用体积必须为正数")

    density_gml = None
    if s.get("density") is not None:
        if s.get("density", 0) <= 0:
            raise ValueError(f"库存液「{name}」密度必须为正数")
        density_gml = convert_density(s["density"], s.get("density_unit", "g/mL"))

    family, c = canonical_concentration(conc, unit, density_gml)
    if c <= 0:
        raise ValueError(f"库存液「{name}」的浓度换算结果无效")

    return ParsedStock(
        id=s.get("id"),
        name=name,
        solute=solute,
        family=family,
        conc_canonical=c,
        conc_display=f"{fmt_num(conc)} {unit}",
        available_ml=convert_volume(avail, vunit),
        density_g_per_ml=density_gml,
        raw=s,
    )


def parse_target(t: dict) -> ParsedTarget:
    solute = (t.get("solute") or "").strip()
    if not solute:
        raise ValueError("存在未填写溶质名称的目标条目")
    conc = t.get("concentration")
    unit = t.get("concentration_unit")
    if conc is None or not unit:
        raise ValueError(f"溶质「{solute}」缺少目标浓度或单位")
    if conc <= 0:
        raise ValueError(f"溶质「{solute}」目标浓度必须为正数")
    family, c = canonical_concentration(conc, unit)
    return ParsedTarget(
        solute=solute,
        family=family,
        conc_canonical=c,
        conc_display=f"{fmt_num(conc)} {unit}",
    )


def solve_plan(stocks_raw: list, targets_raw: list, total_volume: float,
               volume_unit: str = "mL") -> dict:
    """求解取液方案。

    返回 dict：
      feasible=True  -> usage（各库存液用量 mL）、diluent_ml、取液量合计等
      feasible=False -> reason（明确不可行原因）、details（逐溶质诊断）
    """
    # ------------------------------------------------------------------
    # 0. 基础校验
    # ------------------------------------------------------------------
    if total_volume is None or total_volume <= 0:
        return _infeasible("目标总体积必须为正数")
    try:
        V = convert_volume(total_volume, volume_unit)
    except Exception as exc:
        return _infeasible(str(exc))

    try:
        stocks = [parse_stock(s) for s in stocks_raw]
    except Exception as exc:  # UnitError 也是 ValueError 子类
        return _infeasible(f"库存液数据有误：{exc}")

    try:
        targets = [parse_target(t) for t in targets_raw]
    except Exception as exc:
        return _infeasible(f"目标配方数据有误：{exc}")

    if not targets:
        return _infeasible("目标配方中至少需要一种溶质")

    # 目标溶质去重（忽略大小写与首尾空格）
    seen = {}
    for t in targets:
        key = _norm_solute(t.solute)
        if key in seen:
            return _infeasible(
                f"目标配方中溶质「{t.solute}」重复出现（与「{seen[key]}」同名）"
            )
        seen[key] = t.solute

    # 按目标溶质名对库存液分组
    by_solute: dict[str, list[ParsedStock]] = {}
    for st in stocks:
        by_solute.setdefault(_norm_solute(st.solute), []).append(st)

    # ------------------------------------------------------------------
    # 1. 逐溶质贪心求解最小取液量
    # ------------------------------------------------------------------
    usage = {st.id: 0.0 for st in stocks}
    per_solute = []
    total_stock_ml = 0.0

    for t in targets:
        key = _norm_solute(t.solute)
        candidates = by_solute.get(key, [])

        if not candidates:
            return _infeasible(
                f"库存中没有任何含溶质「{t.solute}」的溶液，"
                f"却要求目标浓度 {t.conc_display}，无法配制",
                per_solute,
            )

        # 单位族兼容性检查
        bad = [st for st in candidates if not families_compatible(st.family, t.family)]
        good = [st for st in candidates if families_compatible(st.family, t.family)]
        if not good:
            fam_name = {
                "molar": "摩尔浓度（如 M、mM）",
                "mass": "质量浓度（如 g/L、mg/mL）",
                "ww": "质量分数（%(w/w)，质量量纲）",
                "volfrac": "体积分数（%(v/v)）",
            }
            st = bad[0]
            return _infeasible(
                f"溶质「{t.solute}」的目标使用{fam_name.get(t.family, t.family)}，"
                f"但库存液「{st.name}」使用的是{fam_name.get(st.family, st.family)}，"
                "二者量纲不同且无法在缺少摩尔质量的情况下互相换算，"
                "请统一该溶质的浓度单位族",
                per_solute,
            )

        # 需要的溶质量（规范量纲）
        required = amount_for_volume(t.conc_canonical, V, t.family)

        # 换算到目标单位族口径的等效浓度（质量族内 ww<->g/L 可互转），
        # 用于浓度高低比较与贪心排序；溶质量仍按各库存自身族计算（同为克）
        for st in good:
            st.eff_conc = effective_conc(st.conc_canonical, st.family, t.family)

        # 浓度从高到低（浓度相同按可用体积大者优先，结果稳定）
        good.sort(key=lambda st: (-st.eff_conc, -st.available_ml, st.name))

        remaining = required
        picked = []
        for st in good:
            if remaining <= EPS:
                break
            # 该库存液最多能提供的溶质量：c(规范) × U(mL)
            cap = amount_for_volume(st.conc_canonical, st.available_ml, st.family)
            if cap <= EPS:
                continue
            take_amount = min(remaining, cap)
            take_ml = volume_for_amount(take_amount, st.conc_canonical, st.family)
            # 数值修正到库存上限
            if take_ml > st.available_ml:
                take_ml = st.available_ml
            usage[st.id] += take_ml
            remaining -= take_amount
            picked.append((st, take_ml, take_amount))

        if remaining > 1e-7:
            # 库存总溶质量不足
            total_capacity = sum(
                amount_for_volume(st.conc_canonical, st.available_ml, st.family)
                for st in good
            )
            shortage = required - total_capacity
            return _infeasible(
                f"溶质「{t.solute}」库存总量不足：目标需要 "
                f"{canonical_to_display(required, t.family)}，"
                f"全部库存仅能提供 {canonical_to_display(max(0.0, total_capacity), t.family)}，"
                f"缺口 {canonical_to_display(shortage, t.family)}。"
                "请补充该溶质的库存液或降低目标浓度/总体积",
                per_solute + [{
                    "solute": t.solute,
                    "target_concentration": t.conc_display,
                    "required_amount": canonical_to_display(required, t.family),
                    "available_amount": canonical_to_display(max(0.0, total_capacity), t.family),
                    "shortage": canonical_to_display(shortage, t.family),
                }],
            )

        used_ml = sum(ml for _, ml, _ in picked)
        total_stock_ml += used_ml
        per_solute.append({
            "solute": t.solute,
            "target_concentration": t.conc_display,
            "required_amount": canonical_to_display(required, t.family),
            "stock_volume_used": fmt_volume(used_ml),
            "sources": [
                {
                    "stock_name": st.name,
                    "stock_concentration": st.conc_display,
                    "volume_ml": round(ml, 6),
                    "volume_display": fmt_volume(ml),
                    "amount": canonical_to_display(am, st.family),
                }
                for st, ml, am in picked if ml > EPS
            ],
        })

    # ------------------------------------------------------------------
    # 2. 全局体积守恒检查
    # ------------------------------------------------------------------
    if total_stock_ml > V + 1e-6:
        return _infeasible(
            f"为满足所有目标浓度，至少需要取用各种库存液合计 "
            f"{fmt_volume(total_stock_ml)}，已超过目标总体积 {fmt_volume(V)}"
            f"（超出 {fmt_volume(total_stock_ml - V)}）。"
            "原因是目标浓度相对库存浓度过高，稀释剂无压缩空间；"
            "请提高库存液浓度、增大目标总体积或降低目标浓度",
            per_solute,
        )

    diluent_ml = max(0.0, V - total_stock_ml)

    used_stocks = []
    for st in stocks:
        ml = usage[st.id]
        if ml > EPS:
            used_stocks.append({
                "stock_id": st.id,
                "stock_name": st.name,
                "solute": st.solute,
                "stock_concentration": st.conc_display,
                "volume_ml": round(ml, 6),
                "volume_display": fmt_volume(ml),
                "available_ml": round(st.available_ml, 6),
                "utilization_pct": round(100.0 * ml / st.available_ml, 2)
                if st.available_ml > EPS else 0.0,
            })
    # 按用量降序，方便阅读
    used_stocks.sort(key=lambda x: -x["volume_ml"])

    # 验证性回算：实际浓度 vs 目标浓度
    checks = []
    for t in targets:
        got_amount = 0.0
        for st in by_solute[_norm_solute(t.solute)]:
            if families_compatible(st.family, t.family):
                got_amount += amount_for_volume(
                    st.conc_canonical, usage[st.id], st.family
                )
        got_conc = concentration_from_amount(got_amount, V, t.family)
        target_amount = amount_for_volume(t.conc_canonical, V, t.family)
        rel_err = (
            abs(got_amount - target_amount) / target_amount
            if target_amount > EPS else 0.0
        )
        checks.append({
            "solute": t.solute,
            "target": t.conc_display,
            "achieved": concentration_to_display(got_conc, t.family),
            "relative_error": f"{rel_err:.2e}",
        })

    return {
        "feasible": True,
        "reason": None,
        "total_volume_ml": round(V, 6),
        "total_volume_display": fmt_volume(V),
        "total_stock_volume_ml": round(total_stock_ml, 6),
        "total_stock_volume_display": fmt_volume(total_stock_ml),
        "diluent_volume_ml": round(diluent_ml, 6),
        "diluent_volume_display": fmt_volume(diluent_ml),
        "used_stocks": used_stocks,
        "per_solute": per_solute,
        "verification": checks,
        "needs_diluent": diluent_ml > EPS,
    }


def _infeasible(reason: str, details=None) -> dict:
    return {
        "feasible": False,
        "reason": reason,
        "details": details or [],
    }
