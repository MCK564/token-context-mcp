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

    _HEARTBEAT_EXTRA_COLUMNS = ("client_name", "client_version", "output_mode", "schema_profile")

    @classmethod
    def _migrate_heartbeat_columns(cls, conn: sqlite3.Connection) -> None:
        """M9.8: nullable client columns, added with a guard so old databases and old readers keep working."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(server_heartbeats);")}
        for column in cls._HEARTBEAT_EXTRA_COLUMNS:
            if column not in existing:
                try:
                    conn.execute(f"ALTER TABLE server_heartbeats ADD COLUMN {column} TEXT;")
                except sqlite3.OperationalError:  # another process added it first
                    pass
        conn.commit()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    reason TEXT NOT NULL DEFAULT '',
                    policy TEXT NOT NULL DEFAULT '',
                    custom_tools_json TEXT NOT NULL DEFAULT '[]',
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
            self._migrate_heartbeat_columns(conn)
            # Ensure policy and custom_tools_json columns exist if migrating existing DB
            try:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(agents);")]
                if "policy" not in cols:
                    conn.execute("ALTER TABLE agents ADD COLUMN policy TEXT NOT NULL DEFAULT '';")
                if "custom_tools_json" not in cols:
                    conn.execute("ALTER TABLE agents ADD COLUMN custom_tools_json TEXT NOT NULL DEFAULT '[]';")
                conn.commit()
            except sqlite3.OperationalError:
                pass

            now = _utc_now_iso()
            conn.execute(
                "INSERT OR IGNORE INTO emergency (id, halted, reason, updated_at) VALUES (1, 0, '', ?)",
                (now,),
            )
            conn.commit()

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT agent_id, status, reason, policy, custom_tools_json, registered_at, updated_at FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)

    def upsert_agent(
        self,
        agent_id: str,
        status: str | None = None,
        reason: str = "",
        policy: str | None = None,
        custom_tools_json: str | None = None,
    ) -> None:
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO agents (agent_id, status, reason, policy, custom_tools_json, registered_at, updated_at)
                VALUES (:id, COALESCE(:status, 'ACTIVE'), :reason, COALESCE(:policy, ''), COALESCE(:tools, '[]'), :now, :now)
                ON CONFLICT(agent_id) DO UPDATE SET
                    status = COALESCE(:status, agents.status),
                    reason = CASE WHEN :status IS NOT NULL THEN :reason ELSE agents.reason END,
                    policy = COALESCE(:policy, agents.policy),
                    custom_tools_json = COALESCE(:tools, agents.custom_tools_json),
                    updated_at = :now
                """,
                {
                    "id": agent_id,
                    "status": status,
                    "reason": reason,
                    "policy": policy,
                    "tools": custom_tools_json,
                    "now": now,
                },
            )
            conn.commit()

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT agent_id, status, reason, policy, custom_tools_json, registered_at, updated_at FROM agents ORDER BY agent_id"
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

    def record_heartbeat(
        self,
        server_id: str,
        pid: int,
        client_name: str | None = None,
        client_version: str | None = None,
        output_mode: str | None = None,
        schema_profile: str | None = None,
    ) -> None:
        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO server_heartbeats
                    (server_id, pid, last_seen, status, client_name, client_version, output_mode, schema_profile)
                VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
                ON CONFLICT(server_id) DO UPDATE SET
                    pid = excluded.pid,
                    last_seen = excluded.last_seen,
                    status = 'running',
                    client_name = COALESCE(excluded.client_name, client_name),
                    client_version = COALESCE(excluded.client_version, client_version),
                    output_mode = COALESCE(excluded.output_mode, output_mode),
                    schema_profile = COALESCE(excluded.schema_profile, schema_profile)
                """,
                (server_id, pid, now, client_name, client_version, output_mode, schema_profile),
            )
            conn.commit()

    def get_active_servers(self, stale_threshold_sec: float = 30.0) -> list[dict[str, Any]]:
        now_dt = datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT server_id, pid, last_seen, status, client_name, client_version, output_mode, schema_profile "
                "FROM server_heartbeats"
            )
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
