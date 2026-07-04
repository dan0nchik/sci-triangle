"""Persistent sqlite store for C-platform (C14 audit, C15 subscriptions, C16 cache).

Single file `backend/audit.sqlite` with three tables:
  * audit         — every search / document view / export / patch / review
  * subscriptions — saved queries (query + filters + last_checked cursor)
  * search_cache  — last N search results keyed by search_id (for export)

Connections are opened per call (check_same_thread=False) — fine for the demo load
and safe across FastAPI's threadpool.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "audit.sqlite"
SEARCH_CACHE_MAX = 200

_lock = threading.Lock()
_initialized = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    global _initialized
    if _initialized:
        return
    with _lock:
        with _conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    role TEXT,
                    endpoint TEXT,
                    action TEXT,
                    params TEXT,
                    took_ms INTEGER,
                    result_counts TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_action ON audit(action);
                CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    filters TEXT,
                    role TEXT,
                    email TEXT,
                    created_at TEXT,
                    last_checked TEXT
                );

                CREATE TABLE IF NOT EXISTS search_cache (
                    search_id TEXT PRIMARY KEY,
                    query TEXT,
                    role TEXT,
                    created_at TEXT,
                    result TEXT
                );
                """
            )
        _initialized = True


# ----------------------------------------------------------------- C14 audit
def audit_log(role: Optional[str], endpoint: str, action: str,
              params: Any = None, took_ms: Optional[int] = None,
              result_counts: Any = None) -> None:
    init()
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO audit(ts, role, endpoint, action, params, took_ms, result_counts) "
                "VALUES (?,?,?,?,?,?,?)",
                (_now(), role or "anonymous", endpoint, action,
                 json.dumps(params, ensure_ascii=False) if params is not None else None,
                 took_ms,
                 json.dumps(result_counts, ensure_ascii=False) if result_counts is not None else None),
            )
    except Exception:
        # audit must never break the request path
        pass


def audit_query(action: Optional[str] = None, limit: int = 100,
                offset: int = 0) -> Dict[str, Any]:
    init()
    with _conn() as c:
        where, args = "", []
        if action:
            where = "WHERE action = ?"
            args.append(action)
        total = c.execute(f"SELECT count(*) AS c FROM audit {where}", args).fetchone()["c"]
        rows = c.execute(
            f"SELECT ts, role, endpoint, action, params, took_ms, result_counts "
            f"FROM audit {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
    entries = []
    for r in rows:
        entries.append({
            "ts": r["ts"], "role": r["role"], "endpoint": r["endpoint"],
            "action": r["action"],
            "params": _loads(r["params"]),
            "took_ms": r["took_ms"],
            "result_counts": _loads(r["result_counts"]),
        })
    return {"total": total, "limit": limit, "offset": offset, "entries": entries}


def _loads(s: Optional[str]) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


# ----------------------------------------------------------- C16 search cache
def cache_search(search_id: str, query: str, role: Optional[str],
                 result: Dict[str, Any]) -> None:
    init()
    try:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO search_cache(search_id, query, role, created_at, result) "
                "VALUES (?,?,?,?,?)",
                (search_id, query, role or "researcher", _now(),
                 json.dumps(result, ensure_ascii=False)),
            )
            # keep only the last N by created_at
            c.execute(
                "DELETE FROM search_cache WHERE search_id NOT IN "
                "(SELECT search_id FROM search_cache ORDER BY created_at DESC LIMIT ?)",
                (SEARCH_CACHE_MAX,),
            )
    except Exception:
        pass


def get_cached_search(search_id: str) -> Optional[Dict[str, Any]]:
    init()
    with _conn() as c:
        r = c.execute(
            "SELECT query, role, result FROM search_cache WHERE search_id = ?",
            (search_id,),
        ).fetchone()
    if not r:
        return None
    return {"query": r["query"], "role": r["role"], "result": _loads(r["result"])}


# ----------------------------------------------------------- C15 subscriptions
def add_subscription(sub_id: str, query: str, filters: Optional[Dict],
                     role: Optional[str], email: Optional[str]) -> Dict[str, Any]:
    init()
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO subscriptions(id, query, filters, role, email, created_at, last_checked) "
            "VALUES (?,?,?,?,?,?,?)",
            (sub_id, query, json.dumps(filters or {}, ensure_ascii=False),
             role, email, now, now),
        )
    return get_subscription(sub_id)


def get_subscription(sub_id: str) -> Optional[Dict[str, Any]]:
    init()
    with _conn() as c:
        r = c.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
    return _sub_row(r) if r else None


def list_subscriptions() -> List[Dict[str, Any]]:
    init()
    with _conn() as c:
        rows = c.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()
    return [_sub_row(r) for r in rows]


def delete_subscription(sub_id: str) -> bool:
    init()
    with _conn() as c:
        cur = c.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
        return cur.rowcount > 0


def touch_subscription(sub_id: str, ts: Optional[str] = None) -> None:
    init()
    with _conn() as c:
        c.execute("UPDATE subscriptions SET last_checked = ? WHERE id = ?",
                  (ts or _now(), sub_id))


def _sub_row(r: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": r["id"], "query": r["query"],
        "filters": _loads(r["filters"]) or {},
        "role": r["role"], "email": r["email"],
        "created_at": r["created_at"], "last_checked": r["last_checked"],
    }
