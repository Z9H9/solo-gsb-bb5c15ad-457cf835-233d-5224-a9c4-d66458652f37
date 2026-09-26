"""请求 / 响应数据模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CompositionIn(BaseModel):
    """库存溶液中一种溶质的浓度（一个库存液可声明多种溶质，用于预混液）。"""

    solute: str = Field(..., min_length=1, description="溶质名称")
    concentration: float = Field(..., ge=0, description="浓度数值")
    conc_unit: str = Field("mg/mL", description="浓度单位")
    molar_mass: float | None = Field(None, gt=0, description="摩尔质量 g/mol，mol/L 时必填")


class StockIn(BaseModel):
    """一种库存溶液。compositions 为空表示纯稀释剂。"""

    name: str = Field(..., min_length=1)
    available_volume: float = Field(..., gt=0, description="可用体积")
    volume_unit: str = Field("mL", description="可用体积单位")
    density: float | None = Field(None, gt=0, description="密度，%(w/w) 换算时必填")
    density_unit: str = Field("g/mL")
    compositions: list[CompositionIn] = Field(default_factory=list)


class TargetSolute(BaseModel):
    solute: str = Field(..., min_length=1)
    concentration: float = Field(..., ge=0)
    conc_unit: str = Field("mg/mL")
    molar_mass: float | None = Field(None, gt=0)


class SolveRequest(BaseModel):
    name: str | None = None
    target_volume: float = Field(..., gt=0, description="目标配方总体积")
    volume_unit: str = Field("mL")
    targets: list[TargetSolute] = Field(default_factory=list)
    stocks: list[StockIn] = Field(default_factory=list)
    allow_extra_diluent: bool = Field(
        True, description="库存稀释剂不足时，是否允许用不限量的额外纯水补足体积"
    )
    extra_diluent_name: str = Field("纯水（补充稀释剂）")
    strategy: Literal["min_stock", "min_diluent"] = Field(
        "min_stock",
        description="min_stock=优先用浓储液、取液总量最小；min_diluent=尽量多用库存液、稀释剂最少",
    )
    allow_foreign_solutes: bool = Field(
        False, description="是否允许使用含有目标配方之外溶质的库存液"
    )


class SavePlanRequest(BaseModel):
    name: str = Field(..., min_length=1)
    input: SolveRequest
