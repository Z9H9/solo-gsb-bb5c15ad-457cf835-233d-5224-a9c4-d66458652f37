"""实验室配液约束求解器 —— FastAPI 应用入口。"""

from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from . import database as db
from .solver import solve_plan
from .units import (
    DENSITY_TO_G_PER_ML,
    MASS_UNITS,
    MOLAR_UNITS,
    VOLFRAC_UNITS,
    VOLUME_TO_ML,
    WW_UNITS,
)

CONC_UNITS = (
    list(MOLAR_UNITS) + list(MASS_UNITS) + list(VOLFRAC_UNITS) + list(WW_UNITS)
)


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------
class StockIn(BaseModel):
    name: str = Field(..., min_length=1, description="库存液名称")
    solute: str = Field(..., min_length=1, description="溶质名称")
    concentration: float = Field(..., gt=0)
    concentration_unit: str
    density: Optional[float] = Field(None, gt=0)
    density_unit: str = "g/mL"
    available_volume: float = Field(..., gt=0)
    volume_unit: str = "mL"

    @field_validator("name", "solute")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空字符串")
        return v

    @field_validator("concentration_unit")
    @classmethod
    def _check_conc(cls, v: str) -> str:
        if v not in CONC_UNITS:
            raise ValueError(
                f"浓度单位 {v} 不支持，可选：{', '.join(CONC_UNITS)}"
            )
        return v

    @field_validator("volume_unit")
    @classmethod
    def _check_vol(cls, v: str) -> str:
        if v not in VOLUME_TO_ML:
            raise ValueError(f"体积单位 {v} 不支持")
        return v

    @field_validator("density_unit")
    @classmethod
    def _check_density(cls, v: str) -> str:
        if v not in DENSITY_TO_G_PER_ML:
            raise ValueError(f"密度单位 {v} 不支持")
        return v

    @model_validator(mode="after")
    def _check_ww_needs_density(self):
        if self.concentration_unit in WW_UNITS and self.density is None:
            raise ValueError(
                "使用质量分数 %(w/w)/w/w 时必须提供溶液密度，"
                "否则无法把质量分数换算为单位体积的溶质量进行求解"
            )
        return self


class TargetIn(BaseModel):
    solute: str = Field(..., min_length=1)
    concentration: float = Field(..., gt=0)
    concentration_unit: str

    @field_validator("solute")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空字符串")
        return v

    @field_validator("concentration_unit")
    @classmethod
    def _check_conc(cls, v: str) -> str:
        if v not in CONC_UNITS:
            raise ValueError(f"浓度单位 {v} 不支持")
        # 目标浓度不允许 w/w：目标是最终混合液，质量分数需混合液密度，
        # 而混合液密度在配制前未知。请改用 g/L、%(v/v) 等单位。
        if v in WW_UNITS:
            raise ValueError(
                "目标浓度不支持质量分数 %(w/w)/w/w（混合液密度未知），"
                "请改用 g/L、mg/mL、M 或 %(v/v) 等单位"
            )
        return v


class SolveRequest(BaseModel):
    total_volume: float = Field(..., gt=0)
    volume_unit: str = "mL"
    targets: List[TargetIn] = Field(..., min_length=1)
    # 可选：直接传入库存液进行试算；为空则使用数据库中保存的库存
    stocks: Optional[List[StockIn]] = None

    @field_validator("volume_unit")
    @classmethod
    def _check_vol(cls, v: str) -> str:
        if v not in VOLUME_TO_ML:
            raise ValueError(f"体积单位 {v} 不支持")
        return v


class PlanIn(BaseModel):
    name: str = Field(..., min_length=1)
    total_volume: float = Field(..., gt=0)
    volume_unit: str = "mL"
    targets: List[TargetIn] = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("方案名称不能为空")
        return v

    @field_validator("volume_unit")
    @classmethod
    def _check_vol(cls, v: str) -> str:
        if v not in VOLUME_TO_ML:
            raise ValueError(f"体积单位 {v} 不支持")
        return v


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
app = FastAPI(
    title="实验室配液约束求解器",
    description="统一单位后求解满足体积守恒、浓度约束与库存上限的取液方案",
    version="1.0.0",
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    """返回前端下拉框需要的单位选项。"""
    return {
        "concentration_units": {
            "molar": [u for u in MOLAR_UNITS],
            "mass": [u for u in MASS_UNITS],
            "volfrac": [u for u in VOLFRAC_UNITS],
            "ww": [u for u in WW_UNITS],
        },
        "volume_units": list(VOLUME_TO_ML),
        "density_units": list(DENSITY_TO_G_PER_ML),
    }


# ---- 库存液 CRUD ----------------------------------------------------------
@app.get("/api/stocks")
def api_list_stocks() -> list[dict]:
    return db.list_stocks()


@app.post("/api/stocks", status_code=201)
def api_create_stock(item: StockIn) -> dict:
    return db.create_stock(item.model_dump())


@app.put("/api/stocks/{stock_id}")
def api_update_stock(stock_id: int, item: StockIn) -> dict:
    row = db.update_stock(stock_id, item.model_dump())
    if row is None:
        raise HTTPException(404, f"库存液 #{stock_id} 不存在")
    return row


@app.delete("/api/stocks/{stock_id}", status_code=204)
def api_delete_stock(stock_id: int):
    if not db.delete_stock(stock_id):
        raise HTTPException(404, f"库存液 #{stock_id} 不存在")


# ---- 求解 -----------------------------------------------------------------
def _do_solve(req: SolveRequest) -> dict:
    if req.stocks:
        stocks_raw = [s.model_dump() for s in req.stocks]
    else:
        stocks_raw = db.list_stocks()
    return solve_plan(
        stocks_raw=stocks_raw,
        targets_raw=[t.model_dump() for t in req.targets],
        total_volume=req.total_volume,
        volume_unit=req.volume_unit,
    )


@app.post("/api/solve")
def api_solve(req: SolveRequest) -> dict:
    """基于请求内库存或数据库库存求解（不落库）。"""
    return _do_solve(req)


# ---- 方案保存与再计算 ------------------------------------------------------
@app.get("/api/plans")
def api_list_plans() -> list[dict]:
    return db.list_plans()


@app.get("/api/plans/{plan_id}")
def api_get_plan(plan_id: int) -> dict:
    row = db.get_plan(plan_id)
    if row is None:
        raise HTTPException(404, f"方案 #{plan_id} 不存在")
    return row


@app.post("/api/plans", status_code=201)
def api_create_plan(plan: PlanIn) -> dict:
    """保存方案：先用当前库存计算，再把配方快照与结果一起落库。"""
    result = solve_plan(
        stocks_raw=db.list_stocks(),
        targets_raw=[t.model_dump() for t in plan.targets],
        total_volume=plan.total_volume,
        volume_unit=plan.volume_unit,
    )
    return db.create_plan(
        name=plan.name,
        total_volume=plan.total_volume,
        volume_unit=plan.volume_unit,
        targets=[t.model_dump() for t in plan.targets],
        result=result,
    )


@app.post("/api/plans/{plan_id}/recalculate")
def api_recalculate_plan(plan_id: int) -> dict:
    """用最新库存对已保存配方重新求解，并更新保存的结果。"""
    row = db.get_plan(plan_id)
    if row is None:
        raise HTTPException(404, f"方案 #{plan_id} 不存在")
    result = solve_plan(
        stocks_raw=db.list_stocks(),
        targets_raw=row["targets"],
        total_volume=row["total_volume"],
        volume_unit=row["volume_unit"],
    )
    return db.update_plan_result(plan_id, result)


@app.delete("/api/plans/{plan_id}", status_code=204)
def api_delete_plan(plan_id: int):
    if not db.delete_plan(plan_id):
        raise HTTPException(404, f"方案 #{plan_id} 不存在")


# ---- 演示数据（方便快速体验） ----------------------------------------------
DEMO_STOCKS = [
    dict(name="NaCl 储液", solute="NaCl", concentration=5,
         concentration_unit="M", density=None, density_unit="g/mL",
         available_volume=200, volume_unit="mL"),
    dict(name="NaCl 稀液", solute="NaCl", concentration=0.5,
         concentration_unit="M", density=None, density_unit="g/mL",
         available_volume=500, volume_unit="mL"),
    dict(name="葡萄糖储液", solute="葡萄糖", concentration=200,
         concentration_unit="g/L", density=None, density_unit="g/mL",
         available_volume=100, volume_unit="mL"),
    dict(name="浓盐酸", solute="HCl", concentration=37,
         concentration_unit="%(w/w)", density=1.19, density_unit="g/mL",
         available_volume=500, volume_unit="mL"),
]


@app.post("/api/demo", status_code=201)
def api_seed_demo() -> dict:
    """库存为空时写入一组演示库存液；已有数据则拒绝覆盖。"""
    if db.count_stocks() > 0:
        raise HTTPException(409, "库存中已有数据，为避免覆盖请先清空后再试")
    created = [db.create_stock(s) for s in DEMO_STOCKS]
    return {"created": len(created), "stocks": created}


# ---- 静态前端 -------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
