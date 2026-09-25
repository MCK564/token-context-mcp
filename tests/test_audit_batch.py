"""Tests for M3.7 batch audit logging."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from token_context_mcp.security.audit import AuditLogger


def test_audit_batch_commits_1000_logs(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite"
    logger = AuditLogger(db_path)

    for i in range(1000):
        logger.log(
            tool_name="test_tool",
            agent_id="agent_1",
            status="success",
            duration_ms=1.5,
            details={"i": i},
        )

    # Wait briefly or flush
    logger.flush()
    logs = logger.query_logs(limit=1000)
    assert len(logs) == 1000

    # 1,000 logs batched by 100 entries should yield <= 15 commits
    assert logger.commit_count <= 15
    logger.close()


def test_audit_query_logs_immediate_visibility(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_imm.sqlite"
    logger = AuditLogger(db_path)

    logger.log(
        tool_name="immediate_tool",
        agent_id="agent_immediate",
        status="ok",
        duration_ms=2.0,
        details={"key": "val"},
    )

    # query_logs must auto-flush and immediately see the record
    logs = logger.query_logs(agent_id="agent_immediate")
    assert len(logs) == 1
    assert logs[0]["tool_name"] == "immediate_tool"
    assert logs[0]["details"] == {"key": "val"}
    logger.close()


def test_audit_subprocess_durability(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_sub.sqlite"

    script = f"""
from token_context_mcp.security.audit import AuditLogger
logger = AuditLogger(r'{db_path}')
for i in range(50):
    logger.log('sub_tool', 'sub_agent', 'ok', 1.0, {{'idx': i}})
# Process terminates without explicit close() - atexit flushes
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0

    # Verify parent process can read all 50 entries
    reader = AuditLogger(db_path)
    logs = reader.query_logs(limit=100)
    assert len(logs) == 50
    reader.close()
