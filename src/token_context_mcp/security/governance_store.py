"""Shared governance store using SQLite WAL for cross-process state synchronization."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def merge_seen_agents(registered: list[dict[str, Any]], active_traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure function merging registered agents from DB with active traces.
    
    Never overwrites the registered status or reason of an agent already in DB.
    """
    merged: dict[str, dict[str, Any]] = {}
    for r in registered:
        aid = r.get("agent_id")
        if aid:
            merged[aid] = dict(r)

    for trace in active_traces:
        aid = trace.get("agent_id")
        if not aid:
            continue
        if aid in merged:
            entry = merged[aid]
            for k, v in trace.items():
                if k not in entry:
                    entry[k] = v
                elif k in {"last_active", "call_count"}:
                    entry[k] = v
        else:
            entry = {
                "agent_id": aid,
                "status": "ACTIVE",
                "reason": "",
                "registered_at": "",
                "updated_at": "",
            }
            entry.update(trace)
            entry["status"] = "ACTIVE"
            merged[aid] = entry

    return sorted(merged.values(), key=lambda x: str(x.get("agent_id", "")))


class GovernanceStore:
    """SQLite-backed shared governance store with WAL mode and busy timeout."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    reason TEXT NOT NULL DEFAULT '',
                    registered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS emergency (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    halted INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS server_heartbeats (
                    server_id TEXT PRIMARY KEY,
                    pid INTEGER NOT NULL,
                    last_seen TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running'
                );
                """
            )
            now = _utc_now_iso()
            conn.execute(
                "INSERT OR IGNORE INTO emergency (id, halted, reason, updated_at) VALUES (1, 0, '', ?)",
                (now,),
            )
            conn.commit()

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT agent_id, status, reason, registered_at, updated_at FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)

    def upsert_agent(self, agent_id: str, status: str, reason: str = "") -> None:
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO agents (agent_id, status, reason, registered_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (agent_id, status, reason, now, now),
            )
            conn.commit()

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT agent_id, status, reason, registered_at, updated_at FROM agents ORDER BY agent_id"
            )
            return [dict(row) for row in cur.fetchall()]

    def is_emergency_halted(self) -> tuple[bool, str]:
        with self._connection() as conn:
            cur = conn.execute("SELECT halted, reason FROM emergency WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                return False, ""
            return bool(row["halted"]), str(row["reason"] or "")

    def set_emergency_halt(self, halted: bool, reason: str = "") -> None:
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO emergency (id, halted, reason, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    halted = excluded.halted,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (1 if halted else 0, reason, now),
            )
            conn.commit()

    def record_heartbeat(self, server_id: str, pid: int) -> None:
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO server_heartbeats (server_id, pid, last_seen, status)
                VALUES (?, ?, ?, 'running')
                ON CONFLICT(server_id) DO UPDATE SET
                    pid = excluded.pid,
                    last_seen = excluded.last_seen,
                    status = 'running'
                """,
                (server_id, pid, now),
            )
            conn.commit()

    def get_active_servers(self, stale_threshold_sec: float = 30.0) -> list[dict[str, Any]]:
        now_dt = datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        with self._connection() as conn:
            cur = conn.execute("SELECT server_id, pid, last_seen, status FROM server_heartbeats")
            for row in cur.fetchall():
                data = dict(row)
                try:
                    seen_dt = datetime.fromisoformat(data["last_seen"])
                    diff = (now_dt - seen_dt).total_seconds()
                    if diff <= stale_threshold_sec:
                        active.append(data)
                except Exception:
                    continue
        return active

    def close(self) -> None:
        """No-op: each operation opens its own connection. Provided for API symmetry."""
