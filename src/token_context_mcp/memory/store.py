"""SQLite-first storage engine for shared state, locks, and persistent memory."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Schema v2: adds namespace column for session isolation
MEMORY_SCHEMA_V2 = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS key_values (
  scope TEXT NOT NULL,
  namespace TEXT NOT NULL DEFAULT '',
  key TEXT NOT NULL,
  session_id TEXT,
  value_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL,
  PRIMARY KEY (scope, namespace, key)
);
CREATE INDEX IF NOT EXISTS kv_scope_ns_idx ON key_values(scope, namespace);
CREATE INDEX IF NOT EXISTS kv_expires_idx ON key_values(expires_at);

CREATE TABLE IF NOT EXISTS locks (
  resource_key TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  acquired_at REAL NOT NULL,
  expires_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  scope UNINDEXED,
  namespace UNINDEXED,
  key UNINDEXED,
  content
);
"""

_TARGET_USER_VERSION = 2
_TTL_CLEANUP_INTERVAL = 100  # run cleanup every N put calls


def _redact_value(value: Any) -> Any:
    """Recursively redact secrets from leaf strings using content policy."""
    from token_context_mcp.security.content_policy import redact_text
    if isinstance(value, str):
        redacted, _ = redact_text(value)
        return redacted
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


class MemoryStore:
    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._put_count = 0
        if self.db_path == ":memory:":
            self._persistent_conn: sqlite3.Connection | None = sqlite3.connect(":memory:", timeout=5.0, check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA busy_timeout = 5000;")
            self._persistent_conn.executescript(MEMORY_SCHEMA_V2)
            self._persistent_conn.execute(f"PRAGMA user_version = {_TARGET_USER_VERSION};")
            self._persistent_conn.commit()
        else:
            self._persistent_conn = None
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Run schema migration if needed. Backs up the DB before migrating."""
        cur_ver = conn.execute("PRAGMA user_version;").fetchone()[0]
        if cur_ver >= _TARGET_USER_VERSION:
            conn.executescript(MEMORY_SCHEMA_V2)
            return

        # Backup before migrating
        db_path = Path(self.db_path)
        bak_path = db_path.with_suffix(f".sqlite.bak-v{cur_ver}")
        if db_path.exists() and not bak_path.exists():
            shutil.copy2(str(db_path), str(bak_path))

        # SQLite cannot ALTER PRIMARY KEY. Rebuild key_values with the new
        # (scope, namespace, key) PK if the old table exists.
        existing_tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        }
        if "key_values" in existing_tables:
            conn.executescript("""
                PRAGMA foreign_keys = OFF;
                BEGIN;
                CREATE TABLE IF NOT EXISTS key_values_new (
                  scope TEXT NOT NULL,
                  namespace TEXT NOT NULL DEFAULT '',
                  key TEXT NOT NULL,
                  session_id TEXT,
                  value_json TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  expires_at REAL,
                  PRIMARY KEY (scope, namespace, key)
                );
                INSERT OR IGNORE INTO key_values_new
                  (scope, namespace, key, session_id, value_json, created_at, expires_at)
                SELECT scope, '', key, session_id, value_json, created_at, expires_at
                FROM key_values;
                DROP TABLE key_values;
                ALTER TABLE key_values_new RENAME TO key_values;
                COMMIT;
                PRAGMA foreign_keys = ON;
            """)

        # Now run the full schema (CREATE TABLE IF NOT EXISTS + indexes + other tables)
        conn.executescript(MEMORY_SCHEMA_V2)

        # Set new version
        conn.execute(f"PRAGMA user_version = {_TARGET_USER_VERSION};")
        conn.commit()



    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._persistent_conn is not None:
            yield self._persistent_conn
            self._persistent_conn.commit()
        else:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000;")
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
        namespace: str = "",
        ttl: int | None = 86400,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not key or len(key.encode("utf-8")) > 256:
            raise ValueError("Key must be non-empty and at most 256 bytes")
        now = time.time()
        expires_at = now + ttl if ttl and ttl > 0 else None

        # Redact values before storage
        redacted_value = _redact_value(value)
        value_json = json.dumps(redacted_value, ensure_ascii=False)
        if len(value_json.encode("utf-8")) > 1_048_576:
            raise ValueError("Payload exceeds maximum size limit of 1MB")

        content_text = f"{key} {value_json}"

        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO key_values (scope, namespace, key, session_id, value_json, created_at, expires_at)
                VALUES (:scope, :ns, :key, :sid, :val, :now, :exp)
                ON CONFLICT(scope, namespace, key) DO UPDATE SET
                  session_id = excluded.session_id,
                  value_json = excluded.value_json,
                  created_at = excluded.created_at,
                  expires_at = excluded.expires_at
                """,
                {"scope": scope, "ns": namespace, "key": key, "sid": session_id, "val": value_json, "now": now, "exp": expires_at},
            )
            # Update FTS
            conn.execute(
                "DELETE FROM memory_fts WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": namespace, "key": key},
            )
            conn.execute(
                "INSERT INTO memory_fts (scope, namespace, key, content) VALUES (?, ?, ?, ?)",
                (scope, namespace, key, content_text),
            )

            # Periodic TTL cleanup every _TTL_CLEANUP_INTERVAL puts
            self._put_count += 1
            if self._put_count % _TTL_CLEANUP_INTERVAL == 0:
                conn.execute("DELETE FROM key_values WHERE expires_at IS NOT NULL AND expires_at < :now", {"now": now})

        return {
            "status": "stored",
            "scope": scope,
            "namespace": namespace,
            "key": key,
            "ttl": ttl,
            "expires_at": expires_at,
        }

    def get(self, key: str, *, scope: str = "session", namespace: str = "") -> dict[str, Any]:
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT session_id, value_json, created_at, expires_at FROM key_values WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": namespace, "key": key},
            ).fetchone()

        if not row:
            return {"status": "not_found", "scope": scope, "namespace": namespace, "key": key, "value": None}

        if row["expires_at"] and row["expires_at"] < now:
            self.delete(key, scope=scope, namespace=namespace)
            return {"status": "expired", "scope": scope, "namespace": namespace, "key": key, "value": None}

        try:
            value = json.loads(row["value_json"])
        except json.JSONDecodeError:
            value = row["value_json"]

        return {
            "status": "found",
            "scope": scope,
            "namespace": namespace,
            "key": key,
            "value": value,
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    def delete(self, key: str, *, scope: str = "session", namespace: str = "") -> bool:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM key_values WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": namespace, "key": key},
            )
            conn.execute(
                "DELETE FROM memory_fts WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": namespace, "key": key},
            )
        return True

    def search(self, query: str, *, scope: str | None = None, namespace: str | None = None, limit: int = 5) -> dict[str, Any]:
        now = time.time()
        terms = re.findall(r"\w+", query)
        if not terms:
            return {"query": query, "matches_count": 0, "matches": []}

        formatted_terms = [f'"{term}"' for term in terms]
        fts_query = " AND ".join(formatted_terms)

        sql = """
            SELECT m.scope, m.namespace, m.key, kv.value_json, kv.created_at, kv.expires_at
            FROM memory_fts m
            JOIN key_values kv ON m.scope = kv.scope AND m.namespace = kv.namespace AND m.key = kv.key
            WHERE memory_fts MATCH ?
        """
        params: list[Any] = [fts_query]
        if scope:
            sql += " AND m.scope = ?"
            params.append(scope)
        if namespace is not None:
            sql += " AND m.namespace = ?"
            params.append(namespace)
        sql += " LIMIT ?"
        params.append(limit)

        matches: list[dict[str, Any]] = []
        try:
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
                            "namespace": row["namespace"],
                            "key": row["key"],
                            "value": val,
                            "created_at": row["created_at"],
                        }
                    )
        except sqlite3.OperationalError:
            return {
                "query": query,
                "matches_count": 0,
                "matches": [],
                "warnings": ["invalid_query"],
            }

        return {"query": query, "matches_count": len(matches), "matches": matches}

    def lock(self, resource_key: str, agent_id: str, timeout_sec: int = 60) -> dict[str, Any]:
        now = time.time()
        expires_at = now + timeout_sec

        with self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO locks (resource_key, agent_id, acquired_at, expires_at)
                VALUES (:key, :agent, :now, :expires)
                ON CONFLICT(resource_key) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                WHERE locks.expires_at <= :now
                   OR locks.agent_id = excluded.agent_id;
                """,
                {"key": resource_key, "agent": agent_id, "now": now, "expires": expires_at},
            )
            if cur.rowcount > 0:
                return {
                    "status": "acquired",
                    "acquired": True,
                    "resource_key": resource_key,
                    "agent_id": agent_id,
                    "expires_in_sec": timeout_sec,
                }

            row = conn.execute(
                "SELECT agent_id, expires_at FROM locks WHERE resource_key = :key",
                {"key": resource_key},
            ).fetchone()
            held_by = row["agent_id"] if row else "unknown"
            rem = max(0.0, round(row["expires_at"] - now, 1)) if row else 0.0
            return {
                "status": "locked",
                "acquired": False,
                "resource_key": resource_key,
                "held_by": held_by,
                "remaining_sec": rem,
            }

    def unlock(self, resource_key: str, agent_id: str) -> bool:
        with self._connection() as conn:
            cur = conn.execute(
                "DELETE FROM locks WHERE resource_key = :key AND agent_id = :agent",
                {"key": resource_key, "agent": agent_id},
            )
            return cur.rowcount > 0

    def release_lock(self, resource_key: str, agent_id: str) -> dict[str, Any]:
        released = self.unlock(resource_key, agent_id)
        return {"resource_key": resource_key, "released": released}

    def revoke_agent_locks(self, agent_id: str) -> int:
        """Forcefully revoke all resource locks held by a specific agent."""
        with self._connection() as conn:
            cur = conn.execute("DELETE FROM locks WHERE agent_id = ?", (agent_id,))
            return cur.rowcount

    def revoke_all_locks(self) -> int:
        """Emergency release of all resource locks across all agents."""
        with self._connection() as conn:
            cur = conn.execute("DELETE FROM locks")
            return cur.rowcount

    def list_active_locks(self) -> list[dict[str, Any]]:
        """List currently active (non-expired) resource locks."""
        now = time.time()
        results: list[dict[str, Any]] = []
        with self._connection() as conn:
            rows = conn.execute("SELECT resource_key, agent_id, acquired_at, expires_at FROM locks WHERE expires_at > ? ORDER BY acquired_at DESC", (now,)).fetchall()
            for r in rows:
                results.append({
                    "resource_key": r["resource_key"],
                    "agent_id": r["agent_id"],
                    "acquired_at": r["acquired_at"],
                    "expires_at": r["expires_at"],
                    "remaining_sec": max(0.0, round(r["expires_at"] - now, 1)),
                })
        return results

    def list_entries(self, *, scope: str | None = None, namespace: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List active unexpired memory entries for inspection or consolidation."""
        now = time.time()
        sql = "SELECT scope, namespace, key, session_id, value_json, created_at, expires_at FROM key_values"
        where_clauses: list[str] = []
        params: list[Any] = []
        if scope:
            where_clauses.append("scope = ?")
            params.append(scope)
        if namespace is not None:
            where_clauses.append("namespace = ?")
            params.append(namespace)
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
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
                        "namespace": row["namespace"],
                        "key": row["key"],
                        "session_id": row["session_id"],
                        "value": val,
                        "created_at": row["created_at"],
                    }
                )
        return results
