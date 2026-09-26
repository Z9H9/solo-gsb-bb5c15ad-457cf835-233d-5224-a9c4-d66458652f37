"""SQLite 持久化层：保存配液方案（输入 + 最近一次求解结果）。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "plans.db"
DB_PATH = Path(os.environ.get("LAB_SOLVER_DB", str(_DEFAULT_DB)))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    input_json   TEXT NOT NULL,
    result_json  TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_plans() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, updated_at FROM plans ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_plan(plan_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, input_json, result_json, created_at, updated_at "
            "FROM plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "input": json.loads(row["input_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def save_plan(name: str, input_obj: dict[str, Any], result_obj: dict[str, Any] | None) -> int:
    """按名称 upsert，返回 id。"""
    init_db()
    now = _now()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM plans WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE plans SET input_json=?, result_json=?, updated_at=? WHERE id=?",
                (json.dumps(input_obj, ensure_ascii=False),
                 json.dumps(result_obj, ensure_ascii=False) if result_obj else None,
                 now, existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO plans (name, input_json, result_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name,
             json.dumps(input_obj, ensure_ascii=False),
             json.dumps(result_obj, ensure_ascii=False) if result_obj else None,
             now, now),
        )
        return int(cur.lastrowid)


def delete_plan(plan_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        return cur.rowcount > 0
