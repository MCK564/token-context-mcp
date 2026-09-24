from __future__ import annotations

import time

from token_context_mcp.memory.service import MemoryService


def test_memory_put_and_get() -> None:
    service = MemoryService(":memory:")
    res = service.memory_put("auth_token", {"token": "abc-123", "role": "admin"})
    assert res["status"] == "stored"

    retrieved = service.memory_get("auth_token")
    assert retrieved["status"] == "found"
    assert retrieved["value"]["token"] == "abc-123"
    assert retrieved["value"]["role"] == "admin"


def test_memory_get_nonexistent() -> None:
    service = MemoryService(":memory:")
    retrieved = service.memory_get("missing_key")
    assert retrieved["status"] == "not_found"
    assert retrieved["value"] is None


def test_memory_ttl_expiry() -> None:
    service = MemoryService(":memory:")
    # Set TTL = 1 second
    service.memory_put("short_lived", "temp_value", ttl=1)
    retrieved = service.memory_get("short_lived")
    assert retrieved["status"] == "found"

    time.sleep(1.2)
    expired = service.memory_get("short_lived")
    assert expired["status"] == "expired"
    assert expired["value"] is None


def test_memory_search() -> None:
    service = MemoryService(":memory:")
    service.memory_put("task_1", {"summary": "Refactored invoice scanner parser", "files": 5})
    service.memory_put("task_2", {"summary": "Updated database migrations", "files": 2})

    search_res = service.memory_search("invoice scanner")
    assert search_res["matches_count"] >= 1
    assert search_res["matches"][0]["key"] == "task_1"


def test_memory_lock_concurrency() -> None:
    service = MemoryService(":memory:")
    # Agent A acquires lock
    lock_a = service.memory_lock("core/contracts.py", agent_id="agent_a", timeout_sec=10)
    assert lock_a["status"] == "acquired"
    assert lock_a["acquired"] is True

    # Agent B tries to acquire same lock
    lock_b = service.memory_lock("core/contracts.py", agent_id="agent_b", timeout_sec=10)
    assert lock_b["status"] == "locked"
    assert lock_b["acquired"] is False
    assert lock_b["held_by"] == "agent_a"

    # Agent A releases lock
    rel = service.store.release_lock("core/contracts.py", agent_id="agent_a")
    assert rel["released"] is True

    # Now Agent B can acquire
    lock_b_retry = service.memory_lock("core/contracts.py", agent_id="agent_b", timeout_sec=10)
    assert lock_b_retry["acquired"] is True


def test_memory_consolidate() -> None:
    service = MemoryService(":memory:")
    service.memory_put("step_1", {"plan": "Refactor auth JWT token parser", "status": "done"}, scope="session")
    service.memory_put("step_2", {"plan": "Add verification middleware", "status": "in_progress"}, scope="session")

    res = service.memory_consolidate(
        scope="session",
        target_key="architectural_summary",
        prune_transient=True,
    )
    assert res["status"] == "consolidated"
    assert res["source_entries_count"] == 2
    assert "step_1" in res["pruned_keys"]
    assert "step_2" in res["pruned_keys"]

    # Check that consolidated target_key exists in global scope
    cons = service.memory_get("architectural_summary", scope="global")
    assert cons["status"] == "found"
    assert cons["value"]["source_entries_count"] == 2

    # Check that transient keys were pruned
    assert service.memory_get("step_1", scope="session")["status"] == "not_found"
