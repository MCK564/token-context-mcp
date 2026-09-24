"""High-throughput SQLite-first audit logging for multi-agent tool execution."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("token_context_mcp.audit")

AUDIT_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    agent_id TEXT,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_logs(agent_id);
"""


class AuditLogger:
    """Non-blocking, WAL-mode SQLite audit logger for security observability."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)

        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(AUDIT_SCHEMA)

    def close(self) -> None:
        """Close database connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    def log(
        self,
        tool_name: str,
        agent_id: str | None,
        status: str,
        duration_ms: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a tool execution event. Never raises exceptions to caller."""
        try:
            now = time.time()
            details_str = json.dumps(details or {}, ensure_ascii=False)
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO audit_logs (timestamp, agent_id, tool_name, status, duration_ms, details_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (now, agent_id, tool_name, status, round(duration_ms, 3), details_str),
                )
        except Exception:
            logger.exception("Failed to write audit log entry")

    def query_logs(
        self,
        limit: int = 50,
        agent_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent audit logs with optional filtering."""
        try:
            query = "SELECT id, timestamp, agent_id, tool_name, status, duration_ms, details_json FROM audit_logs"
            params: list[Any] = []
            clauses: list[str] = []

            if agent_id:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            if status:
                clauses.append("status = ?")
                params.append(status)

            if clauses:
                query += " WHERE " + " AND ".join(clauses)

            query += " ORDER BY timestamp DESC, id DESC LIMIT ?"
            params.append(limit)

            rows = self._conn.execute(query, params).fetchall()
            results: list[dict[str, Any]] = []
            for r in rows:
                try:
                    parsed_details = json.loads(r["details_json"])
                except Exception:
                    parsed_details = {}
                results.append({
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "agent_id": r["agent_id"] or "anonymous",
                    "tool_name": r["tool_name"],
                    "status": r["status"],
                    "duration_ms": r["duration_ms"],
                    "details": parsed_details,
                })
            return results
        except Exception:
            logger.exception("Failed to query audit logs")
            return []

    def clear_old_logs(self, days_to_keep: int = 7) -> int:
        """Purge logs older than retention period."""
        try:
            cutoff = time.time() - (days_to_keep * 86400)
            with self._conn:
                cur = self._conn.execute("DELETE FROM audit_logs WHERE timestamp < ?", (cutoff,))
                return cur.rowcount
        except Exception:
            logger.exception("Failed to purge old audit logs")
            return 0
