"""SQLite 数据访问层：库存液与已保存方案的持久化。"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("SOLVER_DB", "/data/solver.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    solute           TEXT NOT NULL,
    concentration    REAL NOT NULL,
    concentration_unit TEXT NOT NULL,
    density          REAL,
    density_unit     TEXT,
    available_volume REAL NOT NULL,
    volume_unit      TEXT NOT NULL DEFAULT 'mL',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT NOT NULL,
    total_volume         REAL NOT NULL,
    volume_unit          TEXT NOT NULL DEFAULT 'mL',
    targets_json         TEXT NOT NULL,
    result_json          TEXT NOT NULL,
    feasible             INTEGER NOT NULL,
    created_at           TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# 库存液
# ---------------------------------------------------------------------------
def _stock_row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "solute": r["solute"],
        "concentration": r["concentration"],
        "concentration_unit": r["concentration_unit"],
        "density": r["density"],
        "density_unit": r["density_unit"],
        "available_volume": r["available_volume"],
        "volume_unit": r["volume_unit"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def list_stocks() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM stocks ORDER BY solute, name"
        ).fetchall()
    return [_stock_row(r) for r in rows]


def get_stock(stock_id: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM stocks WHERE id = ?", (stock_id,)).fetchone()
    return _stock_row(r) if r else None


def create_stock(data: dict) -> dict:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO stocks (name, solute, concentration, concentration_unit,
                                   density, density_unit, available_volume, volume_unit,
                                   created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"], data["solute"], data["concentration"],
                data["concentration_unit"], data.get("density"),
                data.get("density_unit"), data["available_volume"],
                data.get("volume_unit", "mL"), now, now,
            ),
        )
        stock_id = cur.lastrowid
    return get_stock(stock_id)


def update_stock(stock_id: int, data: dict) -> dict | None:
    if get_stock(stock_id) is None:
        return None
    with get_conn() as conn:
        conn.execute(
            """UPDATE stocks SET name=?, solute=?, concentration=?,
                   concentration_unit=?, density=?, density_unit=?,
                   available_volume=?, volume_unit=?, updated_at=?
               WHERE id=?""",
            (
                data["name"], data["solute"], data["concentration"],
                data["concentration_unit"], data.get("density"),
                data.get("density_unit"), data["available_volume"],
                data.get("volume_unit", "mL"), _now(), stock_id,
            ),
        )
    return get_stock(stock_id)


def delete_stock(stock_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM stocks WHERE id = ?", (stock_id,))
        return cur.rowcount > 0


def count_stocks() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM stocks").fetchone()["n"]


# ---------------------------------------------------------------------------
# 方案
# ---------------------------------------------------------------------------
def _plan_row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "total_volume": r["total_volume"],
        "volume_unit": r["volume_unit"],
        "targets": json.loads(r["targets_json"]),
        "result": json.loads(r["result_json"]),
        "feasible": bool(r["feasible"]),
        "created_at": r["created_at"],
    }


def list_plans() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM plans ORDER BY id DESC").fetchall()
    return [_plan_row(r) for r in rows]


def get_plan(plan_id: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return _plan_row(r) if r else None


def create_plan(name: str, total_volume: float, volume_unit: str,
                targets: list, result: dict) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO plans (name, total_volume, volume_unit, targets_json,
                                  result_json, feasible, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name, total_volume, volume_unit,
                json.dumps(targets, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                1 if result.get("feasible") else 0, _now(),
            ),
        )
        plan_id = cur.lastrowid
    return get_plan(plan_id)


def update_plan_result(plan_id: int, result: dict) -> dict | None:
    """用最新库存重新求解后，更新方案结果。"""
    if get_plan(plan_id) is None:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE plans SET result_json=?, feasible=? WHERE id=?",
            (
                json.dumps(result, ensure_ascii=False),
                1 if result.get("feasible") else 0,
                plan_id,
            ),
        )
    return get_plan(plan_id)


def delete_plan(plan_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        return cur.rowcount > 0
