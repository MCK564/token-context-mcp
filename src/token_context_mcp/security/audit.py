"""High-throughput SQLite-first audit logging for multi-agent tool execution."""
from __future__ import annotations

import atexit
import json
import logging
import queue
import sqlite3
import threading
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
    """Non-blocking, batched WAL-mode SQLite audit logger for security observability."""

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

        self._commit_count = 0
        self._write_lock = threading.Lock()
        self._queue: queue.Queue[tuple[float, str | None, str, str, float, str] | None] = queue.Queue()
        self._closed = False
        self._wake_event = threading.Event()

        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="AuditLoggerWorker")
        self._worker.start()
        atexit.register(self.close)

    @property
    def commit_count(self) -> int:
        return self._commit_count

    def _worker_loop(self) -> None:
        while not self._closed:
            self._wake_event.wait(timeout=0.250)
            self._wake_event.clear()
            self._flush_batch()

    def _flush_batch(self) -> None:
        batch: list[tuple[float, str | None, str, str, float, str]] = []
        with self._write_lock:
            while len(batch) < 100:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    self._closed = True
                    break
                batch.append(item)

            if batch:
                try:
                    with self._conn:
                        self._conn.executemany(
                            """
                            INSERT INTO audit_logs (timestamp, agent_id, tool_name, status, duration_ms, details_json)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            batch,
                        )
                    self._commit_count += 1
                except Exception:
                    logger.exception("Failed to write audit log batch")

    def flush(self) -> None:
        """Immediately flush all queued logs into the database."""
        with self._write_lock:
            batch: list[tuple[float, str | None, str, str, float, str]] = []
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    self._closed = True
                    break
                batch.append(item)

            if batch:
                try:
                    with self._conn:
                        self._conn.executemany(
                            """
                            INSERT INTO audit_logs (timestamp, agent_id, tool_name, status, duration_ms, details_json)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            batch,
                        )
                    self._commit_count += 1
                except Exception:
                    logger.exception("Failed to flush audit log batch")

    def close(self) -> None:
        """Close database connection and flush pending logs."""
        if self._closed:
            return
        self._closed = True
        try:
            atexit.unregister(self.close)
        except Exception:
            pass
        self._wake_event.set()
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        self.flush()
        if self._worker.is_alive() and threading.current_thread() != self._worker:
            self._worker.join(timeout=1.0)
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
        if self._closed:
            return
        try:
            now = time.time()
            details_str = json.dumps(details or {}, ensure_ascii=False)
            self._queue.put((now, agent_id, tool_name, status, round(duration_ms, 3), details_str))
            if self._queue.qsize() >= 100:
                self._wake_event.set()
        except Exception:
            logger.exception("Failed to enqueue audit log entry")

    def query_logs(
        self,
        limit: int = 50,
        agent_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent audit logs with optional filtering. Flushes pending queue first."""
        self.flush()
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
        self.flush()
        try:
            cutoff = time.time() - (days_to_keep * 86400)
            with self._conn:
                cur = self._conn.execute("DELETE FROM audit_logs WHERE timestamp < ?", (cutoff,))
                return cur.rowcount
        except Exception:
            logger.exception("Failed to purge old audit logs")
            return 0
