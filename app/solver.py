"""配液约束求解器。

统一到内部单位(mg / mL)后建立线性规划:

变量 x_i = 第 i 个库存液的取用量(mL), 0 <= x_i <= 可用体积上限;
     w   = 额外补充稀释剂(mL), 不限量(允许时)或恒为 0。
约束:
  1) 浓度(质量守恒):
       Σ_i C[i, s] * x_i = tgtMass[s]          对每种目标溶质 s
  2) 体积守恒:
       Σ_i x_i + w = V_total
  3) 库存上限:
       x_i <= avail_i
  4) 杂溶质: 含目标之外溶质的库存液默认禁用。

分层目标(两阶段 LP):
  第一优先级  min w          库存稀释剂优先, 不够才额外补水;
  第二优先级  min_stock      min Σ(含溶质库存液用量)——取液最少、偏好浓储液;
              min_diluent    max Σ(含溶质库存液用量)——尽量多用库存液。
求解后再做贪心后处理, 在不劣化上述目标的前提下最小化取液种类。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from .models import SolveRequest
from .units import UnitError, concentration_to_mg_per_ml, density_to_g_per_ml, volume_to_ml


@dataclass
class NormalizedStock:
    name: str
    avail_ml: float
    # solute -> mg/mL
    composition: dict[str, float]
    is_diluent: bool


class InfeasibleError(Exception):
    """无可行取液方案, reasons 给出人类可读的原因列表。"""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("；".join(reasons))


@dataclass
class SolveResult:
    target_volume_ml: float
    # [(stock_name, volume_ml)]
    usages: list[tuple[str, float]]
    extra_diluent_ml: float
    extra_diluent_name: str
    used_extra_diluent: bool
    # 校验信息: solute -> (目标 mg/mL, 实际 mg/mL)
    achieved: dict[str, tuple[float, float]]
    total_stock_ml: float
    feasible: bool = True


def _normalize(req: SolveRequest) -> tuple[float, dict[str, float], list[NormalizedStock]]:
    """返回 (目标总体积 mL, {溶质: 目标质量 mg}, 归一化库存列表)。"""
    V = volume_to_ml(req.target_volume, req.volume_unit)

    target_mass: dict[str, float] = {}
    for t in req.targets:
        if t.solute in target_mass:
            raise UnitError(f"目标溶质“{t.solute}”重复填写")
        c = concentration_to_mg_per_ml(
            t.concentration, t.conc_unit, molar_mass=t.molar_mass
        )
        target_mass[t.solute] = c * V  # mg

    stocks: list[NormalizedStock] = []
    seen_names: set[str] = set()
    for s in req.stocks:
        if s.name in seen_names:
            raise UnitError(f"库存液“{s.name}”名称重复")
        seen_names.add(s.name)
        avail = volume_to_ml(s.available_volume, s.volume_unit)
        dens = (
            density_to_g_per_ml(s.density, s.density_unit)
            if s.density is not None
            else None
        )
        comp: dict[str, float] = {}
        for comp_in in s.compositions:
            if comp_in.solute in comp:
                raise UnitError(f"库存液“{s.name}”中溶质“{comp_in.solute}”重复")
            comp[comp_in.solute] = concentration_to_mg_per_ml(
                comp_in.concentration,
                comp_in.conc_unit,
                molar_mass=comp_in.molar_mass,
                density=dens,
            )
        stocks.append(
            NormalizedStock(
                name=s.name,
                avail_ml=avail,
                composition=comp,
                is_diluent=not comp,
            )
        )
    return V, target_mass, stocks


def solve(req: SolveRequest) -> SolveResult:
    V, target_mass, stocks = _normalize(req)

    solutes = list(target_mass.keys())
    n = len(stocks)

    if n == 0:
        raise InfeasibleError(["未填写任何库存溶液"])

    # ---- 4) 杂溶质过滤: 含目标之外溶质的库存液默认禁用 ----------------------
    blocked: set[int] = set()
    if not req.allow_foreign_solutes:
        for i, st in enumerate(stocks):
            if set(st.composition) - set(solutes):
                blocked.add(i)

    # 浓度矩阵 C[s, i] (mg/mL)
    C = np.zeros((len(solutes), n))
    for si, sol in enumerate(solutes):
        for i, st in enumerate(stocks):
            C[si, i] = st.composition.get(sol, 0.0)

    # ---- 可行性预检: 每种溶质纯库存上限是否够 ------------------------------
    reasons: list[str] = []
    for si, sol in enumerate(solutes):
        need = target_mass[sol]
        target_c = need / V
        # 该溶质在所有(未被杂溶质规则屏蔽的)库存中的最大可用质量
        best = 0.0
        best_name = ""
        total_avail_mass = 0.0
        max_c = 0.0
        # 不考虑屏蔽时的总质量（用于区分"真不足"与"被杂溶质规则禁用"）
        total_all = sum(
            C[si, i] * st.avail_ml
            for i, st in enumerate(stocks) if C[si, i] > 0
        )
        for i, st in enumerate(stocks):
            if i in blocked:
                continue
            c = C[si, i]
            if c > 0:
                m = c * st.avail_ml
                total_avail_mass += m
                if m > best:
                    best, best_name = m, st.name
                if c > max_c:
                    max_c = c
        if max_c + 1e-12 < target_c:
            reasons.append(
                f"溶质“{sol}”目标浓度 {target_c:.4g} mg/mL 高于所有可用库存液中"
                f"该溶质的最高浓度 {max_c:.4g} mg/mL——混合与稀释只能降低浓度，无法增浓"
            )
        elif total_avail_mass + 1e-9 < need:
            if total_avail_mass <= 0:
                reasons.append(
                    f"溶质“{sol}”在所有可用库存液中均不存在，无法配制"
                )
            else:
                reasons.append(
                    f"溶质“{sol}”库存总质量不足：目标需要 {need:.4g} mg，"
                    f"全部库存最多提供 {total_avail_mass:.4g} mg"
                    f"（含量最高的是“{best_name}”）"
                )
                if total_all + 1e-9 >= need:
                    reasons.append(
                        f"注意：含“{sol}”的部分库存液因带有目标之外的溶质而被禁用，"
                        "可开启“允许杂溶质”后重试"
                    )

    # 稀释剂/总体积预检
    if not req.allow_extra_diluent:
        total_avail = sum(
            st.avail_ml for i, st in enumerate(stocks) if i not in blocked
        )
        if total_avail + 1e-9 < V:
            reasons.append(
                f"不允许补充纯水时，库存液总体积 {total_avail:.4g} mL "
                f"小于目标总体积 {V:.4g} mL"
            )

    if reasons:
        raise InfeasibleError(reasons)

    # ---- 建立分层 LP ------------------------------------------------------
    # 决策变量 z = [x_0 ... x_{n-1}, w]
    #   x_i : 第 i 个库存液取用量(mL)
    #   w   : 额外补充稀释剂(mL), 不限量(允许时)或恒为 0
    # 约束:
    #   C x = target_mass                    质量守恒(浓度等式)
    #   Σx + w = V                           体积守恒
    #   0 <= x_i <= avail_i, w>=0(blocked 库存液固定为 0)
    # 分层目标:
    #   第一优先级: min w —— 库存稀释剂优先, 不够才额外补水
    #   第二优先级: min_stock  => min Σ(含溶质库存液 x_i)  取液最少、偏好浓储液
    #              min_diluent => max Σ(含溶质库存液 x_i)  尽量多用库存液
    diluent_idx = {i for i, st in enumerate(stocks) if st.is_diluent}
    w_bound = (0.0, None) if req.allow_extra_diluent else (0.0, 0.0)

    def make_bounds(extra_zero: set[int]) -> list[tuple[float, float | None]]:
        out = []
        for i, st in enumerate(stocks):
            if i in blocked or i in extra_zero:
                out.append((0.0, 0.0))
            else:
                out.append((0.0, st.avail_ml))
        out.append(w_bound)
        return out

    target_vec = np.array([target_mass[s] for s in solutes])  # mg

    # 等式约束: [C | 0] z = b ; [1...1 | 1] z = V
    A_eq = np.hstack([C, np.zeros((len(solutes), 1))])
    b_eq = target_vec
    A_vol = np.ones((1, n + 1))
    b_vol = np.array([V])
    EQ = np.vstack([A_eq, A_vol])
    EQ_b = np.concatenate([b_eq, b_vol])

    def lp(obj: np.ndarray, extra_zero: set[int], extra_ub=None):
        return linprog(
            obj,
            A_ub=extra_ub[0] if extra_ub else None,
            b_ub=extra_ub[1] if extra_ub else None,
            A_eq=EQ,
            b_eq=EQ_b,
            bounds=make_bounds(extra_zero),
            method="highs",
        )

    # 阶段 1: 最小化额外补水 w
    obj1 = np.zeros(n + 1)
    obj1[n] = 1.0
    res1 = lp(obj1, set())
    if not res1.success:
        raise InfeasibleError(
            [
                f"线性规划无可行解（{res1.message}）："
                "各溶质浓度配比与库存体积上限相互冲突，"
                "例如满足 A 溶质所需的某储液体积会使 B 溶质超标。"
            ]
        )
    w_star = max(float(res1.x[n]), 0.0)

    # 阶段 2: 固定补水量 w <= w* + 容差, 优化第二目标
    obj2 = np.zeros(n + 1)
    for i in range(n):
        if i in diluent_idx:
            continue  # 纯稀释剂用量由守恒决定, 不进入策略目标
        obj2[i] = -1.0 if req.strategy == "min_diluent" else 1.0

    w_tol = max(1e-7 * max(w_star, V, 1.0), 1e-8)
    # w <= w_star + tol
    A_w = np.zeros((1, n + 1))
    A_w[0, n] = 1.0
    ub_w = (A_w, np.array([w_star + w_tol]))

    res2 = lp(obj2, set(), extra_ub=ub_w)
    if not res2.success:  # 理论上阶段1可行则阶段2必可行
        raise InfeasibleError([f"第二阶段优化失败：{res2.message}"])

    z = np.clip(res2.x, 0.0, None)
    z[z < 1e-9] = 0.0

    def solution_score(zz: np.ndarray) -> float:
        return float(sum(zz[i] for i in range(n) if i not in diluent_idx))

    def not_worse(zz: np.ndarray, best: float) -> bool:
        val = solution_score(zz)
        tol = max(1e-7 * max(abs(best), V, 1.0), 1e-7)
        if req.strategy == "min_diluent":
            return val >= best - tol
        return val <= best + tol

    # ---- 贪心精简: 主目标不劣化的前提下, 尽量减少取用的库存液种类 ----------
    best_score = solution_score(z)
    forced_zero: set[int] = set()
    while True:
        used = [i for i in range(n) if z[i] > 0.0 and i not in forced_zero]
        # 优先尝试剔除用量最小的
        used.sort(key=lambda i: z[i])
        removed = False
        for cand in used:
            trial = lp(obj2, forced_zero | {cand}, extra_ub=ub_w)
            if trial.success:
                zt = np.clip(trial.x, 0.0, None)
                if not_worse(zt, best_score):
                    forced_zero.add(cand)
                    z = zt
                    z[z < 1e-9] = 0.0
                    best_score = solution_score(z)
                    removed = True
                    break
        if not removed:
            break

    x = z[:n]
    extra = max(float(z[n]), 0.0)
    total_stock = float(x.sum())

    if abs(total_stock + extra - V) > 1e-5:
        raise InfeasibleError(["求解结果未满足体积守恒，请检查输入"])

    usages = [(stocks[i].name, float(x[i])) for i in range(n) if x[i] > 0.0]

    # 校验实际浓度
    achieved: dict[str, tuple[float, float]] = {}
    masses = C @ x
    for si, sol in enumerate(solutes):
        achieved[sol] = (
            target_mass[sol] / V,
            float(masses[si]) / V,
        )

    return SolveResult(
        target_volume_ml=V,
        usages=usages,
        extra_diluent_ml=max(extra, 0.0),
        extra_diluent_name=req.extra_diluent_name,
        used_extra_diluent=extra > 1e-7,
        achieved=achieved,
        total_stock_ml=total_stock,
    )
