"""Tests for server-level agent control, permission revocation, and audit logging."""
from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from token_context_mcp.config import load_config, save_config
from token_context_mcp.models import AppConfig, ServerConfig
from token_context_mcp.server import build_server


def test_admin_tools_disabled_by_default(indexed_config: Path) -> None:
    # Build server with default admin_tools (disabled)
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=False)

    server_tools = asyncio.run(server.list_tools())
    tool_names = {t.name for t in server_tools}
    assert "agent_control" not in tool_names
    assert "audit_logs" not in tool_names

    # Discovery tools should not expose them
    list_res = asyncio.run(server.call_tool("list_available_tools", {}))
    categories = list_res.structured_content["categories"]
    all_disc_tools = [t["name"] for cat in categories.values() for t in cat]
    assert "agent_control" not in all_disc_tools
    assert "audit_logs" not in all_disc_tools

    search_res = asyncio.run(server.call_tool("search_tools", {"query": "halt audit control"}))
    search_names = [t["name"] for t in search_res.structured_content["tools"]]
    assert "agent_control" not in search_names
    assert "audit_logs" not in search_names

    schema_ctrl = asyncio.run(server.call_tool("get_tool_schema", {"tool_name": "agent_control"}))
    assert schema_ctrl.structured_content["status"] == "not_found"

    schema_audit = asyncio.run(server.call_tool("get_tool_schema", {"tool_name": "audit_logs"}))
    assert schema_audit.structured_content["status"] == "not_found"


def test_server_agent_control_token_protection(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. TOKEN_CONTEXT_ADMIN_TOKEN not set
    monkeypatch.delenv("TOKEN_CONTEXT_ADMIN_TOKEN", raising=False)
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)

    denied = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "pause", "agent_id": "subagent-1", "admin_token": "any-token"},
        )
    )
    assert denied.structured_content["error"]["code"] == "permission_revoked"
    assert "TOKEN_CONTEXT_ADMIN_TOKEN environment variable is not set" in denied.structured_content["error"]["message"]

    # 2. TOKEN_CONTEXT_ADMIN_TOKEN is set
    token = "correct-admin-secret-token"
    monkeypatch.setenv("TOKEN_CONTEXT_ADMIN_TOKEN", token)

    # Status does not need token
    status_res = asyncio.run(
        server.call_tool("agent_control", {"action": "status"})
    )
    assert status_res.structured_content["emergency_halt"] is False

    # Calling with invalid token fails and does not leak token into audit logs
    bad_token = "attacker-injected-token-xyz"
    bad_res = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "pause", "agent_id": "subagent-1", "admin_token": bad_token},
        )
    )
    assert bad_res.structured_content["error"]["code"] == "permission_revoked"
    assert "Invalid admin token" in bad_res.structured_content["error"]["message"]

    # Check audit log does not leak bad_token
    audit_res = asyncio.run(server.call_tool("audit_logs", {"limit": 10}))
    logs = audit_res.structured_content["logs"]
    assert any(log["status"] == "DENIED" for log in logs)
    for log in logs:
        assert bad_token not in str(log)
        assert token not in str(log)

    # 3. Cannot pause admin agent
    admin_pause = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "pause", "agent_id": "admin", "admin_token": token},
        )
    )
    assert admin_pause.structured_content["error"]["code"] == "permission_revoked"
    assert "Cannot pause or block admin agent" in admin_pause.structured_content["error"]["message"]


def test_server_agent_control_and_audit(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-admin-token"
    monkeypatch.setenv("TOKEN_CONTEXT_ADMIN_TOKEN", token)
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)

    # 1. Normal call with memory_lock
    lock_res = asyncio.run(
        server.call_tool(
            "memory_lock",
            {"resource_key": "auth_module", "agent_id": "subagent-1", "timeout_sec": 60},
        )
    )
    assert lock_res.structured_content["status"] == "acquired"
    assert lock_res.structured_content["acquired"] is True

    # Check status via agent_control tool (no token required)
    status_res = asyncio.run(
        server.call_tool("agent_control", {"action": "status"})
    )
    assert status_res.structured_content["emergency_halt"] is False
    assert len(status_res.structured_content["active_locks"]) >= 1

    # 2. Pause agent (token required)
    pause_res = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "pause", "agent_id": "subagent-1", "reason": "Code review in progress", "admin_token": token},
        )
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
        server.call_tool("agent_control", {"action": "revoke_locks", "agent_id": "subagent-1", "admin_token": token})
    )
    assert revoke_res.structured_content["revoked_count"] >= 1

    # 4. Resume agent
    resume_res = asyncio.run(
        server.call_tool("agent_control", {"action": "resume", "agent_id": "subagent-1", "admin_token": token})
    )
    assert resume_res.structured_content["status"] == "ACTIVE"

    # 5. Check audit logs
    audit_res = asyncio.run(
        server.call_tool("audit_logs", {"limit": 10})
    )
    logs = audit_res.structured_content["logs"]
    assert len(logs) > 0
    denied_entries = [log for log in logs if log["status"] == "DENIED"]
    assert len(denied_entries) >= 1
    assert denied_entries[0]["agent_id"] == "subagent-1"


def test_server_emergency_halt_and_resume(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = "test-admin-token"
    monkeypatch.setenv("TOKEN_CONTEXT_ADMIN_TOKEN", token)
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)

    # Trigger emergency halt
    halt_res = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "emergency_halt", "reason": "Immediate security audit", "admin_token": token},
        )
    )
    assert halt_res.structured_content["status"] == "HALTED"

    # Any tool call with agent_id will be rejected
    rejected = asyncio.run(
        server.call_tool("memory_lock", {"resource_key": "foo", "agent_id": "any-agent"})
    )
    assert rejected.structured_content["error"]["code"] == "permission_revoked"
    assert "Global emergency stop" in rejected.structured_content["error"]["message"]

    # agent_control(action="status") can bypass halt to inspect state
    status_res = asyncio.run(
        server.call_tool("agent_control", {"action": "status"})
    )
    assert status_res.structured_content["emergency_halt"] is True

    # agent_control(action="emergency_resume") can bypass halt to restore system
    resume_res = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "emergency_resume", "reason": "Audit complete", "admin_token": token},
        )
    )
    assert resume_res.structured_content["status"] == "ACTIVE"
    assert resume_res.structured_content["emergency_halt"] is False

    # After resume, memory_lock succeeds
    lock_res = asyncio.run(
        server.call_tool(
            "memory_lock",
            {"resource_key": "foo", "agent_id": "any-agent", "timeout_sec": 60},
        )
    )
    assert lock_res.structured_content["status"] == "acquired"


def test_config_roundtrip_enable_admin_tools(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.json"
    cfg = AppConfig(
        server=ServerConfig(enable_extensions=True, enable_admin_tools=True),
        repositories={},
    )
    save_config(cfg_file, cfg)
    loaded = load_config(cfg_file)
    assert loaded.server.enable_admin_tools is True

    cfg2 = AppConfig(
        server=ServerConfig(enable_extensions=True, enable_admin_tools=False),
        repositories={},
    )
    save_config(cfg_file, cfg2)
    loaded2 = load_config(cfg_file)
    assert loaded2.server.enable_admin_tools is False
