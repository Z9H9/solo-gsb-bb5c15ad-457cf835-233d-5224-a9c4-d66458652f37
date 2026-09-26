"""FastAPI 入口：配液求解 API + 静态页面。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import database
from .models import SavePlanRequest, SolveRequest
from .solver import InfeasibleError, solve
from .units import UnitError, mg_per_ml_to, volume_to_ml

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="实验室配液约束求解器", version="1.0.0")


def _format_result(req: SolveRequest, result) -> dict:
    """把内部单位的求解结果转换为用户单位的可展示结构。"""
    # 体积结果按目标体积单位回算
    vol_factor = volume_to_ml(1.0, req.volume_unit)  # 1 (用户单位) = factor mL
    to_user_vol = lambda ml: ml / vol_factor

    usages = [
        {
            "stock_name": name,
            "volume_ml": round(ml, 6),
            "volume_display": round(to_user_vol(ml), 6),
        }
        for name, ml in sorted(result.usages, key=lambda u: -u[1])
        if ml > 1e-9
    ]

    # 实际浓度按每种目标溶质的输入单位回算
    conc_check = []
    for t in req.targets:
        target_mgml, actual_mgml = result.achieved[t.solute]
        actual = mg_per_ml_to(
            actual_mgml, t.conc_unit, molar_mass=t.molar_mass
        )
        rel_err = (
            abs(actual - t.concentration) / abs(t.concentration)
            if t.concentration > 0 else 0.0
        )
        conc_check.append(
            {
                "solute": t.solute,
                "target_concentration": t.concentration,
                "actual_concentration": round(actual, 8),
                "conc_unit": t.conc_unit,
                "relative_error": round(rel_err, 10),
            }
        )

    return {
        "feasible": True,
        "target_volume": req.target_volume,
        "volume_unit": req.volume_unit,
        "usages": usages,
        "total_stock_volume_display": round(
            to_user_vol(result.total_stock_ml), 6
        ),
        "extra_diluent": {
            "used": result.used_extra_diluent,
            "name": result.extra_diluent_name,
            "volume_display": round(to_user_vol(result.extra_diluent_ml), 6),
        },
        "concentration_check": conc_check,
    }


@app.post("/api/solve")
def api_solve(req: SolveRequest) -> dict:
    if not req.targets:
        raise HTTPException(status_code=422, detail="请至少填写一种目标溶质")
    if not req.stocks:
        raise HTTPException(status_code=422, detail="请至少填写一种库存溶液")
    try:
        result = solve(req)
    except UnitError as exc:
        # 单位换算类错误归为输入问题
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InfeasibleError as exc:
        return {"feasible": False, "reasons": exc.reasons}
    return _format_result(req, result)


@app.get("/api/plans")
def api_list_plans() -> list[dict]:
    return database.list_plans()


@app.post("/api/plans")
def api_save_plan(body: SavePlanRequest) -> dict:
    # 保存时顺便重算一次，保证结果与输入一致
    formatted = None
    try:
        result = solve(body.input)
        formatted = _format_result(body.input, result)
    except (InfeasibleError, UnitError, ValidationError):
        # 允许保存不可行/有问题的方案草稿，但不带结果
        formatted = None
    plan_id = database.save_plan(
        body.name, body.input.model_dump(), formatted
    )
    return {"id": plan_id, "name": body.name, "result": formatted}


@app.get("/api/plans/{plan_id}")
def api_get_plan(plan_id: int) -> dict:
    plan = database.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="方案不存在")
    return plan


@app.delete("/api/plans/{plan_id}")
def api_delete_plan(plan_id: int) -> dict:
    if not database.delete_plan(plan_id):
        raise HTTPException(status_code=404, detail="方案不存在")
    return {"deleted": plan_id}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.mount(
    "/",
    StaticFiles(directory=STATIC_DIR, html=True),
    name="static",
)
