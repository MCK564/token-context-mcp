"""SQLite-first storage engine for shared state, locks, and persistent memory."""
from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("token_context_mcp.memory.store")

# Schema v3: namespace column for session isolation in key_values and memory_fts
MEMORY_SCHEMA_V3 = """
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
# Retain alias for any external references
MEMORY_SCHEMA_V2 = MEMORY_SCHEMA_V3

_TARGET_USER_VERSION = 3
_TTL_CLEANUP_INTERVAL = 100  # run cleanup every N put calls


def _needs_repair(conn: sqlite3.Connection) -> bool:
    """Return True if the database schema is outdated or missing required columns."""
    cur_ver = conn.execute("PRAGMA user_version;").fetchone()[0]
    if cur_ver < _TARGET_USER_VERSION:
        return True
    try:
        kv_cols = [r[1] for r in conn.execute("PRAGMA table_info(key_values);")]
        if kv_cols and "namespace" not in kv_cols:
            return True
        fts_cols = [r[1] for r in conn.execute("PRAGMA table_info(memory_fts);")]
        if fts_cols and "namespace" not in fts_cols:
            return True
    except sqlite3.OperationalError:
        return True
    return False


def _fts_match_query(query: str) -> str | None:
    """Build an FTS5 MATCH expression: whitespace-separated words are ANDed; each word, and each
    "double quoted phrase", is matched as an exact token sequence. ``app-config-v2`` or ``models.py``
    therefore only match where those tokens are adjacent and in order, not anywhere in the entry.
    Returns ``None`` when the query has no word character at all."""
    phrases: list[str] = []
    for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', query):
        text = quoted or bare.replace('"', "")  # a stray unbalanced quote is noise, not syntax
        if not re.search(r"\w", text):
            continue
        phrases.append('"' + text + '"')
    return " AND ".join(phrases) if phrases else None


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
        self._migration_error: str | None = None
        if self.db_path == ":memory:":
            self._persistent_conn: sqlite3.Connection | None = sqlite3.connect(":memory:", timeout=5.0, check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA busy_timeout = 5000;")
            self._persistent_conn.executescript(MEMORY_SCHEMA_V3)
            self._persistent_conn.execute(f"PRAGMA user_version = {_TARGET_USER_VERSION};")
            self._persistent_conn.commit()
        else:
            self._persistent_conn = None
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Run schema migration if needed. Backs up the DB before migrating."""
        if not _needs_repair(conn):
            conn.executescript(MEMORY_SCHEMA_V3)
            return

        # Backup before migrating (file-based DB only)
        if self.db_path != ":memory:":
            db_path = Path(self.db_path)
            if db_path.exists():
                cur_ver = conn.execute("PRAGMA user_version;").fetchone()[0]
                bak_path = db_path.with_suffix(f".sqlite.bak-v{cur_ver}")
                if bak_path.exists():
                    ts = int(time.time())
                    bak_path = db_path.with_suffix(f".sqlite.bak-v{cur_ver}-{ts}")
                try:
                    shutil.copy2(str(db_path), str(bak_path))
                except Exception as exc:
                    logger.warning("Failed to create backup at %s: %s", bak_path, exc)

        # Migrate all tables within a single transaction
        try:
            conn.execute("PRAGMA foreign_keys = OFF;")
            existing_tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            }

            rows_to_insert: list[tuple[str, str, str, str | None, str, float, float | None]] = []
            if "key_values" in existing_tables:
                kv_cols = [r[1] for r in conn.execute("PRAGMA table_info(key_values);")]
                has_ns = "namespace" in kv_cols

                if has_ns:
                    sql = "SELECT scope, namespace, key, session_id, value_json, created_at, expires_at FROM key_values"
                    for r in conn.execute(sql):
                        scope, ns, key, sid, val_raw, cat, exp = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
                        if scope == "session" and (not ns or ns == ""):
                            effective_ns = sid or "default"
                        elif scope != "session":
                            effective_ns = ""
                        else:
                            effective_ns = ns or ""
                        try:
                            val_obj = json.loads(val_raw)
                            val_redacted = _redact_value(val_obj)
                            val_json = json.dumps(val_redacted, ensure_ascii=False)
                        except Exception:
                            val_json = val_raw
                        rows_to_insert.append((scope, effective_ns, key, sid, val_json, cat, exp))
                else:
                    sql = "SELECT scope, key, session_id, value_json, created_at, expires_at FROM key_values"
                    for r in conn.execute(sql):
                        scope, key, sid, val_raw, cat, exp = r[0], r[1], r[2], r[3], r[4], r[5]
                        if scope == "session":
                            effective_ns = sid or "default"
                        else:
                            effective_ns = ""
                        try:
                            val_obj = json.loads(val_raw)
                            val_redacted = _redact_value(val_obj)
                            val_json = json.dumps(val_redacted, ensure_ascii=False)
                        except Exception:
                            val_json = val_raw
                        rows_to_insert.append((scope, effective_ns, key, sid, val_json, cat, exp))

            # Drop old key_values and old memory_fts, then re-create with schema v3
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DROP TABLE IF EXISTS key_values;")
            conn.execute("DROP TABLE IF EXISTS memory_fts;")
            conn.executescript(MEMORY_SCHEMA_V3)

            for row in rows_to_insert:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO key_values
                      (scope, namespace, key, session_id, value_json, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )
                content_text = f"{row[2]} {row[4]}"
                conn.execute(
                    "INSERT INTO memory_fts (scope, namespace, key, content) VALUES (?, ?, ?, ?)",
                    (row[0], row[1], row[2], content_text),
                )

            conn.execute(f"PRAGMA user_version = {_TARGET_USER_VERSION};")
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON;")
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("Failed to migrate memory schema: %s", exc)
            self._migration_error = str(exc)




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
        if self._migration_error:
            return {
                "status": "error",
                "error": "memory_store_migration_failed",
                "details": self._migration_error,
            }
        if not key or len(key.encode("utf-8")) > 256:
            raise ValueError("Key must be non-empty and at most 256 bytes")
        now = time.time()
        expires_at = now + ttl if ttl and ttl > 0 else None

        effective_ns = namespace if namespace != "" else ((session_id or "default") if scope == "session" and session_id else "")

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
                {"scope": scope, "ns": effective_ns, "key": key, "sid": session_id, "val": value_json, "now": now, "exp": expires_at},
            )
            # Update FTS
            conn.execute(
                "DELETE FROM memory_fts WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": effective_ns, "key": key},
            )
            conn.execute(
                "INSERT INTO memory_fts (scope, namespace, key, content) VALUES (?, ?, ?, ?)",
                (scope, effective_ns, key, content_text),
            )

            # Periodic TTL cleanup every _TTL_CLEANUP_INTERVAL puts
            self._put_count += 1
            if self._put_count % _TTL_CLEANUP_INTERVAL == 0:
                # Search rows first, while key_values still identifies the expired entries.
                conn.execute(
                    "DELETE FROM memory_fts WHERE (scope, namespace, key) IN "
                    "(SELECT scope, namespace, key FROM key_values WHERE expires_at IS NOT NULL AND expires_at < :now)",
                    {"now": now},
                )
                conn.execute("DELETE FROM key_values WHERE expires_at IS NOT NULL AND expires_at < :now", {"now": now})

        return {
            "status": "stored",
            "scope": scope,
            "namespace": effective_ns,
            "key": key,
            "ttl": ttl,
            "expires_at": expires_at,
        }

    def get(
        self,
        key: str,
        *,
        scope: str = "session",
        namespace: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if self._migration_error:
            return {
                "status": "error",
                "error": "memory_store_migration_failed",
                "details": self._migration_error,
                "scope": scope,
                "namespace": namespace,
                "key": key,
                "value": None,
            }
        effective_ns = namespace if namespace != "" else ((session_id or "default") if scope == "session" and session_id else "")
        now = time.time()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT session_id, value_json, created_at, expires_at FROM key_values WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": effective_ns, "key": key},
            ).fetchone()

        if not row:
            return {"status": "not_found", "scope": scope, "namespace": effective_ns, "key": key, "value": None}

        if row["expires_at"] and row["expires_at"] < now:
            self.delete(key, scope=scope, namespace=effective_ns)
            return {"status": "expired", "scope": scope, "namespace": effective_ns, "key": key, "value": None}

        try:
            value = json.loads(row["value_json"])
        except json.JSONDecodeError:
            value = row["value_json"]

        return {
            "status": "found",
            "scope": scope,
            "namespace": effective_ns,
            "key": key,
            "value": value,
            "session_id": row["session_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    def delete(
        self,
        key: str,
        *,
        scope: str = "session",
        namespace: str = "",
        session_id: str | None = None,
    ) -> bool:
        if self._migration_error:
            return False
        effective_ns = namespace if namespace != "" else ((session_id or "default") if scope == "session" and session_id else "")
        with self._connection() as conn:
            cur = conn.execute(
                "DELETE FROM key_values WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": effective_ns, "key": key},
            )
            deleted = cur.rowcount > 0
            conn.execute(
                "DELETE FROM memory_fts WHERE scope = :scope AND namespace = :ns AND key = :key",
                {"scope": scope, "ns": effective_ns, "key": key},
            )
        return deleted

    def search(self, query: str, *, scope: str | None = None, namespace: str | None = None, limit: int = 5) -> dict[str, Any]:
        if self._migration_error:
            return {
                "query": query,
                "matches_count": 0,
                "matches": [],
                "error": "memory_store_migration_failed",
                "warnings": ["memory_store_migration_failed"],
            }
        now = time.time()
        fts_query = _fts_match_query(query)
        if fts_query is None:
            return {"query": query, "matches_count": 0, "matches": []}

        sql = """
            SELECT m.scope, m.namespace, m.key, kv.value_json, kv.created_at, kv.expires_at
            FROM memory_fts m
            JOIN key_values kv ON m.scope = kv.scope AND m.namespace = kv.namespace AND m.key = kv.key
            WHERE memory_fts MATCH ?
              AND (kv.expires_at IS NULL OR kv.expires_at >= ?)
        """
        params: list[Any] = [fts_query, now]
        if scope:
            sql += " AND m.scope = ?"
            params.append(scope)
        if namespace is not None:
            sql += " AND m.namespace = ?"
            params.append(namespace)
        sql += " ORDER BY bm25(memory_fts) LIMIT ?"
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
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "fts5: syntax error" in msg or "malformed match" in msg or "syntax error" in msg:
                return {
                    "query": query,
                    "matches_count": 0,
                    "matches": [],
                    "warnings": ["invalid_query"],
                }
            # Re-raise structural errors (e.g. 'no such column', 'no such table')
            raise

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
