"""plan 版本快照与来源记录

对应 spec FR-32（可撤销与版本快照）。每次 /generate 与每次动态变更都生成快照，
存 SQLite plan_versions 表，便于一键回滚到任意历史版本。
"""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "cache.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS plan_versions (
            version_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            parent_version_id TEXT,
            ts REAL NOT NULL,
            trigger_reason TEXT,
            diff_json TEXT,
            plan_json TEXT NOT NULL,
            adopted INTEGER DEFAULT 1
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY,
            session_id TEXT,
            destination TEXT,
            prefs_json TEXT,
            created_ts REAL
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS kv_cache (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            ts REAL NOT NULL,
            ttl_sec INTEGER NOT NULL
        )
        """)
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_plan_versions_plan ON plan_versions(plan_id, ts DESC)
        """)
        c.execute("""
        CREATE INDEX IF NOT EXISTS idx_plans_dest ON plans(destination, created_ts DESC)
        """)


def new_version_id() -> str:
    return f"ver_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"


def save_plan(plan_id: str, session_id: str, destination: str, prefs: Dict[str, Any]) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO plans(plan_id, session_id, destination, prefs_json, created_ts) VALUES(?,?,?,?,?)",
            (plan_id, session_id, destination, json.dumps(prefs, ensure_ascii=False), time.time()),
        )


def save_version(
    plan_id: str,
    plan: Dict[str, Any],
    parent_version_id: Optional[str] = None,
    trigger_reason: Optional[str] = None,
    diff: Optional[List[Dict[str, Any]]] = None,
    adopted: bool = True,
) -> str:
    version_id = new_version_id()
    with _conn() as c:
        c.execute(
            "INSERT INTO plan_versions(version_id, plan_id, parent_version_id, ts, trigger_reason, diff_json, plan_json, adopted) VALUES(?,?,?,?,?,?,?,?)",
            (
                version_id, plan_id, parent_version_id, time.time(),
                trigger_reason,
                json.dumps(diff or [], ensure_ascii=False),
                json.dumps(plan, ensure_ascii=False),
                1 if adopted else 0,
            ),
        )
    return version_id


def get_version(version_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM plan_versions WHERE version_id=?", (version_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["plan"] = json.loads(d.pop("plan_json"))
    except json.JSONDecodeError:
        d["plan"] = {}
    try:
        d["diff"] = json.loads(d.pop("diff_json") or "[]")
    except json.JSONDecodeError:
        d["diff"] = []
    return d


def list_versions(plan_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT version_id, plan_id, parent_version_id, ts, trigger_reason, adopted FROM plan_versions WHERE plan_id=? ORDER BY ts DESC LIMIT ?",
            (plan_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def latest_version_id(plan_id: str) -> Optional[str]:
    with _conn() as c:
        row = c.execute(
            "SELECT version_id FROM plan_versions WHERE plan_id=? AND adopted=1 ORDER BY ts DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
    return row["version_id"] if row else None
