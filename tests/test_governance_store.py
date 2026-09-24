"""Tests for SQLite WAL GovernanceStore, cross-process synchronization, and agent identity."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import time
import pytest

from token_context_mcp.security.access_control import (
    AccessControlManager,
    AgentState,
    PolicyProfile,
    resolve_effective_agent_id,
)
from token_context_mcp.security.governance_store import GovernanceStore, merge_seen_agents
from token_context_mcp.server import build_server


def test_governance_store_agent_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "gov.sqlite"
    store = GovernanceStore(db_path)

    # Initial empty list
    assert store.list_agents() == []
    assert store.get_agent("agent-1") is None

    # Upsert new agent
    store.upsert_agent("agent-1", "ACTIVE", "Initial registration")
    ag = store.get_agent("agent-1")
    assert ag is not None
    assert ag["agent_id"] == "agent-1"
    assert ag["status"] == "ACTIVE"
    assert ag["reason"] == "Initial registration"
    assert ag["registered_at"] != ""
    assert ag["updated_at"] != ""

    # Update agent status
    store.upsert_agent("agent-1", "PAUSED", "Under inspection")
    ag2 = store.get_agent("agent-1")
    assert ag2 is not None
    assert ag2["status"] == "PAUSED"
    assert ag2["reason"] == "Under inspection"

    # List agents sorted
    store.upsert_agent("agent-0", "BLOCKED", "Compromised")
    all_agents = store.list_agents()
    assert len(all_agents) == 2
    assert [a["agent_id"] for a in all_agents] == ["agent-0", "agent-1"]


def test_merge_seen_agents() -> None:
    registered = [
        {"agent_id": "reg-1", "status": "PAUSED", "reason": "Paused by admin", "role": "builder"},
        {"agent_id": "reg-2", "status": "ACTIVE", "reason": "", "role": "tester"},
    ]
    active_traces = [
        {"agent_id": "reg-1", "status": "ACTIVE", "call_count": 42, "last_active": 100.0},
        {"agent_id": "unreg-1", "call_count": 5, "last_active": 105.0},
    ]

    merged = merge_seen_agents(registered, active_traces)
    merged_map = {m["agent_id"]: m for m in merged}

    # reg-1 must PRESERVE PAUSED status and reason from registered, but get call_count from trace
    assert merged_map["reg-1"]["status"] == "PAUSED"
    assert merged_map["reg-1"]["reason"] == "Paused by admin"
    assert merged_map["reg-1"]["call_count"] == 42
    assert merged_map["reg-1"]["last_active"] == 100.0

    # reg-2 remains ACTIVE
    assert merged_map["reg-2"]["status"] == "ACTIVE"

    # unreg-1 is added with ACTIVE status
    assert merged_map["unreg-1"]["status"] == "ACTIVE"
    assert merged_map["unreg-1"]["call_count"] == 5


def test_governance_store_emergency_halt(tmp_path: Path) -> None:
    db_path = tmp_path / "gov.sqlite"
    store = GovernanceStore(db_path)

    # Initial state is not halted
    halted, reason = store.is_emergency_halted()
    assert halted is False
    assert reason == ""

    # Set halt
    store.set_emergency_halt(True, "Critical anomaly")
    halted, reason = store.is_emergency_halted()
    assert halted is True
    assert reason == "Critical anomaly"

    # Resume halt
    store.set_emergency_halt(False, "")
    halted, reason = store.is_emergency_halted()
    assert halted is False
    assert reason == ""


def test_governance_store_heartbeat_and_stale(tmp_path: Path) -> None:
    db_path = tmp_path / "gov.sqlite"
    store = GovernanceStore(db_path)

    store.record_heartbeat("server-live", 12345)

    # Manually write a stale heartbeat in the past
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    with store._get_connection() as conn:
        conn.execute(
            "INSERT INTO server_heartbeats (server_id, pid, last_seen, status) VALUES (?, ?, ?, 'running')",
            ("server-stale", 99999, stale_time),
        )
        conn.commit()

    active = store.get_active_servers(stale_threshold_sec=30.0)
    active_ids = [s["server_id"] for s in active]
    assert "server-live" in active_ids
    assert "server-stale" not in active_ids


def test_cross_process_propagation(tmp_path: Path) -> None:
    db_path = tmp_path / "gov.sqlite"
    store_a = GovernanceStore(db_path)
    store_b = GovernanceStore(db_path)

    # Process A manager, Process B manager
    mgr_a = AccessControlManager(store=store_a)
    mgr_b = AccessControlManager(store=store_b)

    # Initially agent-1 is active in B
    assert mgr_b.get_agent_state("agent-1") == AgentState.ACTIVE

    # Process A pauses agent-1
    mgr_a.pause_agent("agent-1", "Paused from GUI")

    # Before TTL expires (0s), if we wait 1.05s, mgr_b cache refreshes
    time.sleep(1.05)
    assert mgr_b.get_agent_state("agent-1") == AgentState.PAUSED

    # Process A emergency halts
    mgr_a.emergency_halt("Stop all")
    time.sleep(1.05)
    assert mgr_b.is_emergency_halted is True
    assert mgr_b.emergency_reason == "Stop all"

    # Process A resumes
    mgr_a.emergency_resume()
    time.sleep(1.05)
    assert mgr_b.is_emergency_halted is False


def test_process_identity_and_anonymous(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token = "admin-secret-xyz"
    monkeypatch.setenv("TOKEN_CONTEXT_ADMIN_TOKEN", token)
    monkeypatch.delenv("TOKEN_CONTEXT_AGENT_ID", raising=False)

    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)

    # 1. Without agent_id and TOKEN_CONTEXT_AGENT_ID, effective agent is "anonymous"
    res1 = asyncio.run(server.call_tool("list_repositories", {}))
    assert len(res1.structured_content["repo_ids"]) >= 1

    # 2. Pause "anonymous" agent via admin
    pause_res = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "pause", "agent_id": "anonymous", "reason": "No anonymous calls allowed", "admin_token": token},
        )
    )
    assert pause_res.structured_content["status"] == "PAUSED"

    # Now anonymous call is rejected
    blocked_res = asyncio.run(server.call_tool("list_repositories", {}))
    assert blocked_res.structured_content["error"]["code"] == "permission_revoked"
    assert "PAUSED" in blocked_res.structured_content["error"]["message"]

    # 3. Resume "anonymous"
    resume_res = asyncio.run(
        server.call_tool(
            "agent_control",
            {"action": "resume", "agent_id": "anonymous", "admin_token": token},
        )
    )
    assert resume_res.structured_content["status"] == "ACTIVE"

    # Anonymous call succeeds again
    res2 = asyncio.run(server.call_tool("list_repositories", {}))
    assert len(res2.structured_content["repo_ids"]) >= 1


def test_invalid_agent_id_rejected(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=False)

    # 1. Invalid characters in TOKEN_CONTEXT_AGENT_ID
    monkeypatch.setenv("TOKEN_CONTEXT_AGENT_ID", "agent/invalid;injection")
    res1 = asyncio.run(server.call_tool("list_repositories", {}))
    assert res1.structured_content["error"]["code"] == "invalid_request"
    assert "Invalid TOKEN_CONTEXT_AGENT_ID" in res1.structured_content["error"]["message"]

    # 2. Too long agent ID (> 64 chars)
    monkeypatch.setenv("TOKEN_CONTEXT_AGENT_ID", "a" * 65)
    res2 = asyncio.run(server.call_tool("list_repositories", {}))
    assert res2.structured_content["error"]["code"] == "invalid_request"
    assert "Invalid TOKEN_CONTEXT_AGENT_ID" in res2.structured_content["error"]["message"]

    # 3. Valid agent ID works
    monkeypatch.setenv("TOKEN_CONTEXT_AGENT_ID", "valid_agent-123")
    res3 = asyncio.run(server.call_tool("list_repositories", {}))
    assert len(res3.structured_content["repo_ids"]) >= 1


def test_server_heartbeat_recording(indexed_config: Path) -> None:
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=False)
    gov_store: GovernanceStore = getattr(server, "governance_store")
    assert gov_store is not None

    active = gov_store.get_active_servers(stale_threshold_sec=10.0)
    assert len(active) >= 1
    assert any(s["pid"] == os.getpid() for s in active)
