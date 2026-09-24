"""Tests for AccessControlManager: fast-path latency, revocation, policies, rate limiting."""
from __future__ import annotations

import time
import pytest

from token_context_mcp.security.access_control import (
    AccessControlManager,
    AgentState,
    PolicyProfile,
    READ_ONLY_TOOLS,
)


def test_fast_path_latency() -> None:
    manager = AccessControlManager(max_calls_per_minute=1_000_000)
    manager.register_agent("agent-speed-test", role="tester")

    # Warmup
    for _ in range(10):
        manager.check_access("find_symbols", "agent-speed-test")

    iterations = 5000
    start = time.perf_counter()
    for _ in range(iterations):
        allowed, reason = manager.check_access("find_symbols", "agent-speed-test")
        assert allowed is True
        assert reason is None
    elapsed = time.perf_counter() - start

    avg_time_ms = (elapsed / iterations) * 1000
    # Must be under 0.05ms (50 microseconds)
    assert avg_time_ms < 0.05, f"Fast-path latency too high: {avg_time_ms:.4f}ms"


def test_pause_and_resume_agent() -> None:
    manager = AccessControlManager()
    agent_id = "claude-worker-1"
    manager.register_agent(agent_id, role="coder")

    allowed, _ = manager.check_access("get_repo_map", agent_id)
    assert allowed is True

    # Pause agent
    manager.pause_agent(agent_id, reason="Reviewing code changes")
    allowed, reason = manager.check_access("get_repo_map", agent_id)
    assert allowed is False
    assert "PAUSED" in reason
    assert "Reviewing code changes" in reason

    # Resume agent
    manager.resume_agent(agent_id)
    allowed, reason = manager.check_access("get_repo_map", agent_id)
    assert allowed is True
    assert reason is None


def test_block_and_unblock_agent() -> None:
    manager = AccessControlManager()
    agent_id = "rogue-agent"

    manager.block_agent(agent_id, reason="Exceeded resource budget")
    allowed, reason = manager.check_access("memory_get", agent_id)
    assert allowed is False
    assert "BLOCKED" in reason
    assert "Exceeded resource budget" in reason

    manager.unblock_agent(agent_id)
    allowed, reason = manager.check_access("memory_get", agent_id)
    assert allowed is True


def test_emergency_halt_panic_button() -> None:
    manager = AccessControlManager()
    manager.register_agent("agent-1")
    manager.register_agent("agent-2")

    assert manager.check_access("find_symbols", "agent-1")[0] is True
    assert manager.check_access("find_symbols", "agent-2")[0] is True

    # Emergency halt
    manager.emergency_halt("Critical security patch underway")
    assert manager.is_emergency_halted is True

    allowed1, reason1 = manager.check_access("find_symbols", "agent-1")
    allowed2, reason2 = manager.check_access("list_repositories", None)  # Even anonymous calls
    assert allowed1 is False
    assert allowed2 is False
    assert "Critical security patch underway" in reason1
    assert "Global emergency stop is active" in reason2

    # Resume
    manager.emergency_resume()
    assert manager.is_emergency_halted is False
    assert manager.check_access("find_symbols", "agent-1")[0] is True


def test_read_only_policy_enforcement() -> None:
    manager = AccessControlManager()
    agent_id = "researcher-readonly"
    manager.register_agent(agent_id, policy=PolicyProfile.READ_ONLY)

    # Allowed read tools
    for tool in ("list_repositories", "get_repo_map", "find_symbols", "memory_get"):
        allowed, reason = manager.check_access(tool, agent_id)
        assert allowed is True, f"Tool {tool} should be allowed under READ_ONLY"

    # Disallowed mutating tools
    for tool in ("memory_put", "memory_lock"):
        allowed, reason = manager.check_access(tool, agent_id)
        assert allowed is False
        assert "READ_ONLY" in reason


def test_custom_tool_policy() -> None:
    manager = AccessControlManager()
    agent_id = "custom-agent"
    manager.register_agent(agent_id, policy=PolicyProfile.CUSTOM, custom_tools={"find_symbols", "search_source"})

    assert manager.check_access("find_symbols", agent_id)[0] is True
    assert manager.check_access("search_source", agent_id)[0] is True
    assert manager.check_access("get_repo_map", agent_id)[0] is False


def test_rate_limiting() -> None:
    manager = AccessControlManager(max_calls_per_minute=5)
    agent_id = "chatter-agent"
    manager.register_agent(agent_id)

    # First 5 calls allowed
    for _ in range(5):
        allowed, _ = manager.check_access("find_symbols", agent_id)
        assert allowed is True

    # 6th call rejected
    allowed, reason = manager.check_access("find_symbols", agent_id)
    assert allowed is False
    assert "RATE_LIMITED" in reason
