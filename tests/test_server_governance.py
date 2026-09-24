"""Tests for server-level agent control, permission revocation, and audit logging."""
from __future__ import annotations

import asyncio
from pathlib import Path

from token_context_mcp.server import build_server


def test_server_agent_control_and_audit(indexed_config: Path) -> None:
    # Build server with extensions enabled
    server = build_server(indexed_config, enable_extensions=True)

    # 1. Normal call with memory_lock
    lock_res = asyncio.run(
        server.call_tool(
            "memory_lock",
            {"resource_key": "auth_module", "agent_id": "subagent-1", "timeout_sec": 60},
        )
    )
    assert lock_res.structured_content["status"] == "acquired"
    assert lock_res.structured_content["acquired"] is True

    # Check status via agent_control tool
    status_res = asyncio.run(
        server.call_tool("agent_control", {"action": "status"})
    )
    assert status_res.structured_content["emergency_halt"] is False
    assert len(status_res.structured_content["active_locks"]) >= 1

    # 2. Pause agent
    pause_res = asyncio.run(
        server.call_tool("agent_control", {"action": "pause", "agent_id": "subagent-1", "reason": "Code review in progress"})
    )
    assert pause_res.structured_content["status"] == "PAUSED"

    # Now subagent-1 tries to call memory_lock again -> Denied!
    denied_call = asyncio.run(
        server.call_tool(
            "memory_lock",
            {"resource_key": "other_module", "agent_id": "subagent-1"},
        )
    )
    assert denied_call.structured_content["error"]["code"] == "permission_revoked"
    assert "PAUSED" in denied_call.structured_content["error"]["message"]

    # 3. Revoke locks
    revoke_res = asyncio.run(
        server.call_tool("agent_control", {"action": "revoke_locks", "agent_id": "subagent-1"})
    )
    assert revoke_res.structured_content["revoked_count"] >= 1

    # 4. Resume agent
    resume_res = asyncio.run(
        server.call_tool("agent_control", {"action": "resume", "agent_id": "subagent-1"})
    )
    assert resume_res.structured_content["status"] == "ACTIVE"

    # 5. Check audit logs
    audit_res = asyncio.run(
        server.call_tool("audit_logs", {"limit": 10})
    )
    logs = audit_res.structured_content["logs"]
    assert len(logs) > 0
    # There must be a DENIED log recorded
    denied_entries = [log for log in logs if log["status"] == "DENIED"]
    assert len(denied_entries) >= 1
    assert denied_entries[0]["agent_id"] == "subagent-1"


def test_server_emergency_halt(indexed_config: Path) -> None:
    server = build_server(indexed_config, enable_extensions=True)

    # Trigger emergency halt
    halt_res = asyncio.run(
        server.call_tool("agent_control", {"action": "emergency_halt", "reason": "Immediate security audit"})
    )
    assert halt_res.structured_content["status"] == "HALTED"

    # Any tool call with agent_id will be rejected
    rejected = asyncio.run(
        server.call_tool("memory_lock", {"resource_key": "foo", "agent_id": "any-agent"})
    )
    assert rejected.structured_content["error"]["code"] == "permission_revoked"
    assert "Global emergency stop" in rejected.structured_content["error"]["message"]
