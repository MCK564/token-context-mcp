"""SQLite-first storage engine for shared state, locks, and persistent memory."""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MEMORY_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS key_values (
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  session_id TEXT,
  value_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL,
  PRIMARY KEY (scope, key)
);
CREATE INDEX IF NOT EXISTS kv_scope_idx ON key_values(scope);
CREATE INDEX IF NOT EXISTS kv_expires_idx ON key_values(expires_at);

CREATE TABLE IF NOT EXISTS locks (
  resource_key TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  acquired_at REAL NOT NULL,
  expires_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  scope UNINDEXED,
  key UNINDEXED,
  content
);
"""


class MemoryStore:
    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path == ":memory:":
            self._persistent_conn: sqlite3.Connection | None = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.executescript(MEMORY_SCHEMA)
        else:
            self._persistent_conn = None
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                conn.executescript(MEMORY_SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._persistent_conn is not None:
            yield self._persistent_conn
            self._persistent_conn.commit()
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def put(
        self,
        key: str,
        value: Any,
        *,
        scope: str = "session",
        ttl: int | None = 86400,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        expires_at = now + ttl if ttl and ttl > 0 else None
        value_json = json.dumps(value, ensure_ascii=False)
        content_text = f"{key} {value_json}"

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO key_values (scope, key, session_id, value_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, key) DO UPDATE SET
                  session_id=excluded.session_id,
                  value_json=excluded.value_json,
                  created_at=excluded.created_at,
                  expires_at=excluded.expires_at
                """,
                (scope, key, session_id, value_json, now, expires_at),
            )
            # Update FTS
            conn.execute("DELETE FROM memory_fts WHERE scope = ? AND key = ?", (scope, key))
            conn.execute(
                "INSERT INTO memory_fts (scope, key, content) VALUES (?, ?, ?)",
                (scope, key, content_text),
            )

        return {
            "status": "stored",
            "scope": scope,
            "key": key,
            "ttl": ttl,
            "expires_at": expires_at,
        }

    def get(self, key: str, *, scope: str = "session") -> dict[str, Any]:
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT session_id, value_json, created_at, expires_at FROM key_values WHERE scope = ? AND key = ?",
                (scope, key),
            ).fetchone()

        if not row:
            return {"status": "not_found", "scope": scope, "key": key, "value": None}

        if row["expires_at"] and row["expires_at"] < now:
            self.delete(key, scope=scope)
            return {"status": "expired", "scope": scope, "key": key, "value": None}

        try:
            value = json.loads(row["value_json"])
        except json.JSONDecodeError:
            value = row["value_json"]

        return {
            "status": "found",
            "scope": scope,
            "key": key,
            "value": value,
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    def delete(self, key: str, *, scope: str = "session") -> bool:
        with self._connection() as conn:
            conn.execute("DELETE FROM key_values WHERE scope = ? AND key = ?", (scope, key))
            conn.execute("DELETE FROM memory_fts WHERE scope = ? AND key = ?", (scope, key))
        return True

    def search(self, query: str, *, scope: str | None = None, limit: int = 5) -> dict[str, Any]:
        now = time.time()
        escaped_query = "".join(c for c in query if c.isalnum() or c in (" ", "_", "-")).strip()
        if not escaped_query:
            return {"query": query, "matches": []}

        sql = """
            SELECT m.scope, m.key, kv.value_json, kv.created_at, kv.expires_at
            FROM memory_fts m
            JOIN key_values kv ON m.scope = kv.scope AND m.key = kv.key
            WHERE memory_fts MATCH ?
        """
        params: list[Any] = [escaped_query]
        if scope:
            sql += " AND m.scope = ?"
            params.append(scope)
        sql += " LIMIT ?"
        params.append(limit)

        matches: list[dict[str, Any]] = []
        with self._connection() as conn:
            for row in conn.execute(sql, params):
                if row["expires_at"] and row["expires_at"] < now:
                    continue
                try:
                    val = json.loads(row["value_json"])
                except Exception:
                    val = row["value_json"]
                matches.append(
                    {
                        "scope": row["scope"],
                        "key": row["key"],
                        "value": val,
                        "created_at": row["created_at"],
                    }
                )

        return {"query": query, "matches_count": len(matches), "matches": matches}

    def lock(self, resource_key: str, agent_id: str, timeout_sec: int = 60) -> dict[str, Any]:
        now = time.time()
        expires_at = now + timeout_sec

        with self._connection() as conn:
            # Check existing lock
            row = conn.execute("SELECT agent_id, expires_at FROM locks WHERE resource_key = ?", (resource_key,)).fetchone()
            if row:
                if row["expires_at"] > now and row["agent_id"] != agent_id:
                    return {
                        "status": "locked",
                        "acquired": False,
                        "resource_key": resource_key,
                        "held_by": row["agent_id"],
                        "remaining_sec": round(row["expires_at"] - now, 1),
                    }
            # Acquire or renew
            conn.execute(
                """
                INSERT INTO locks (resource_key, agent_id, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(resource_key) DO UPDATE SET
                  agent_id=excluded.agent_id,
                  acquired_at=excluded.acquired_at,
                  expires_at=excluded.expires_at
                """,
                (resource_key, agent_id, now, expires_at),
            )

        return {
            "status": "acquired",
            "acquired": True,
            "resource_key": resource_key,
            "agent_id": agent_id,
            "expires_in_sec": timeout_sec,
        }

    def release_lock(self, resource_key: str, agent_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            cur = conn.execute("DELETE FROM locks WHERE resource_key = ? AND agent_id = ?", (resource_key, agent_id))
            released = cur.rowcount > 0

        return {"resource_key": resource_key, "released": released}

    def list_entries(self, *, scope: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List active unexpired memory entries for inspection or consolidation."""
        now = time.time()
        sql = "SELECT scope, key, session_id, value_json, created_at, expires_at FROM key_values"
        params: list[Any] = []
        if scope:
            sql += " WHERE scope = ?"
            params.append(scope)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)

        results: list[dict[str, Any]] = []
        with self._connection() as conn:
            for row in conn.execute(sql, params):
                if row["expires_at"] and row["expires_at"] < now:
                    continue
                try:
                    val = json.loads(row["value_json"])
                except Exception:
                    val = row["value_json"]
                results.append(
                    {
                        "scope": row["scope"],
                        "key": row["key"],
                        "session_id": row["session_id"],
                        "value": val,
                        "created_at": row["created_at"],
                    }
                )
        return results
