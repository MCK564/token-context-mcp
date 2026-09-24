"""Tests for AuditLogger: recording, querying, and retention."""
from __future__ import annotations

import time
from token_context_mcp.security.audit import AuditLogger


def test_audit_logger_record_and_query() -> None:
    logger = AuditLogger(":memory:")

    # Log several events
    logger.log("find_symbols", "agent-alpha", "SUCCESS", 1.25, {"pattern": "auth*"})
    logger.log("memory_put", "agent-beta", "DENIED", 0.05, {"reason": "READ_ONLY"})
    logger.log("get_repo_map", "agent-alpha", "SUCCESS", 3.42)

    logs = logger.query_logs(limit=10)
    assert len(logs) == 3

    # Most recent first
    assert logs[0]["tool_name"] == "get_repo_map"
    assert logs[0]["agent_id"] == "agent-alpha"

    # Filter by agent
    alpha_logs = logger.query_logs(agent_id="agent-alpha")
    assert len(alpha_logs) == 2

    # Filter by status
    denied_logs = logger.query_logs(status="DENIED")
    assert len(denied_logs) == 1
    assert denied_logs[0]["details"]["reason"] == "READ_ONLY"


def test_audit_logger_retention() -> None:
    logger = AuditLogger(":memory:")

    # Insert an old event directly
    old_time = time.time() - (10 * 86400)  # 10 days ago
    with logger._conn:
        logger._conn.execute(
            "INSERT INTO audit_logs (timestamp, agent_id, tool_name, status, duration_ms, details_json) VALUES (?, ?, ?, ?, ?, ?)",
            (old_time, "old-agent", "search_source", "SUCCESS", 2.0, "{}"),
        )

    logger.log("find_symbols", "new-agent", "SUCCESS", 1.0)
    assert len(logger.query_logs()) == 2

    purged = logger.clear_old_logs(days_to_keep=7)
    assert purged == 1

    remaining = logger.query_logs()
    assert len(remaining) == 1
    assert remaining[0]["agent_id"] == "new-agent"
