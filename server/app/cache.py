"""tg-cache 等价实现

对应 spec FR-18。三级粒度：
1. 抓取素材：per (target_url+query)
2. LLM 中间结果：per (prompt+inputs hash)
3. 最终方案：per (destination+prefs hash)

TTL 默认 7 天。命中时跳过 Scrapling 与 LLM 调用。
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "cache.db"
DEFAULT_TTL = 7 * 24 * 3600


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _key(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def get(key: str) -> Optional[Any]:
    with _conn() as c:
        row = c.execute(
            "SELECT value_json, ts, ttl_sec FROM kv_cache WHERE key=?", (key,)
        ).fetchone()
    if not row:
        return None
    if time.time() - row["ts"] > row["ttl_sec"]:
        return None
    try:
        return json.loads(row["value_json"])
    except json.JSONDecodeError:
        return None


def set_(key: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO kv_cache(key, value_json, ts, ttl_sec) VALUES(?,?,?,?)",
            (key, json.dumps(value, ensure_ascii=False), time.time(), ttl),
        )


def invalidate_prefix(prefix: str) -> int:
    """按 key 前缀批量失效。返回删除条数。"""
    with _conn() as c:
        cur = c.execute("DELETE FROM kv_cache WHERE key LIKE ?", (prefix + "%",))
        return cur.rowcount


def clear_all() -> int:
    with _conn() as c:
        cur = c.execute("DELETE FROM kv_cache")
        return cur.rowcount


# ====== 三级粒度封装 ======
def key_scrape(target_url: str, query: str) -> str:
    return "scrape:" + _key(target_url, query)


def key_llm(prompt: str, inputs_hash: str) -> str:
    return "llm:" + _key(prompt, inputs_hash)


def key_plan(destination: str, prefs: Dict[str, Any]) -> str:
    return "plan:" + _key(destination, json.dumps(prefs, sort_keys=True, ensure_ascii=False))


def get_scrape(target_url: str, query: str) -> Optional[Any]:
    return get(key_scrape(target_url, query))


def set_scrape(target_url: str, query: str, value: Any, ttl: int = DEFAULT_TTL) -> None:
    set_(key_scrape(target_url, query), value, ttl)


def get_plan(destination: str, prefs: Dict[str, Any]) -> Optional[Any]:
    return get(key_plan(destination, prefs))


def set_plan(destination: str, prefs: Dict[str, Any], value: Any, ttl: int = DEFAULT_TTL) -> None:
    set_(key_plan(destination, prefs), value, ttl)
