"""Tests for atomic memory_lock and memory_unlock tool."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time

from token_context_mcp.memory.service import MemoryService
from token_context_mcp.memory.store import MemoryStore
from token_context_mcp.server import build_server

WORKER_CODE = """
import sys, json
from token_context_mcp.memory.store import MemoryStore

db_path = sys.argv[1]
worker_id = sys.argv[2]
lock_key = sys.argv[3]

store = MemoryStore(db_path)
res = store.lock(lock_key, f"worker-{worker_id}", timeout_sec=10)
print(json.dumps({
    "worker_id": worker_id,
    "acquired": res.get("acquired", False),
    "status": res.get("status"),
}))
"""


def test_atomic_lock_concurrency_stress(tmp_path: Path) -> None:
    # Must pass 5 consecutive runs
    for run_idx in range(5):
        db_file = tmp_path / f"stress_lock_{run_idx}.sqlite"
        lock_key = f"critical_section_{run_idx}"

        # Initialize store
        MemoryStore(db_file)

        # Launch 8 worker subprocesses concurrently
        num_workers = 8
        procs = []
        for i in range(num_workers):
            p = subprocess.Popen(
                [sys.executable, "-c", WORKER_CODE, str(db_file), str(i), lock_key],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            procs.append(p)

        results = []
        for p in procs:
            stdout, stderr = p.communicate(timeout=15)
            assert p.returncode == 0, f"Worker failed with stderr: {stderr}"
            results.append(json.loads(stdout.strip()))

        # Exactly 1 worker acquired the lock
        acquired_list = [r for r in results if r["acquired"] is True]
        locked_list = [r for r in results if r["acquired"] is False and r["status"] == "locked"]

        assert len(acquired_list) == 1, f"Expected 1 winner, got {len(acquired_list)} in run {run_idx}: {results}"
        assert len(locked_list) == num_workers - 1, f"Expected {num_workers - 1} locked, got {len(locked_list)}"


def test_memory_unlock_lifecycle(indexed_config: Path) -> None:
    server = build_server(indexed_config, enable_extensions=True)

    # 1. Agent A acquires lock
    res1 = asyncio.run(
        server.call_tool("memory_lock", {"resource_key": "module_xyz", "agent_id": "agent-A", "timeout_sec": 60})
    )
    assert res1.structured_content["status"] == "acquired"
    assert res1.structured_content["acquired"] is True

    # 2. Agent B tries to unlock Agent A's lock -> Fails with not_locked
    res2 = asyncio.run(
        server.call_tool("memory_unlock", {"resource_key": "module_xyz", "agent_id": "agent-B"})
    )
    assert res2.structured_content["status"] == "not_locked"

    # Agent B tries to acquire lock -> locked
    res3 = asyncio.run(
        server.call_tool("memory_lock", {"resource_key": "module_xyz", "agent_id": "agent-B", "timeout_sec": 60})
    )
    assert res3.structured_content["status"] == "locked"
    assert res3.structured_content["acquired"] is False
    assert res3.structured_content["held_by"] == "agent-A"

    # 3. Agent A releases lock -> released
    res4 = asyncio.run(
        server.call_tool("memory_unlock", {"resource_key": "module_xyz", "agent_id": "agent-A"})
    )
    assert res4.structured_content["status"] == "released"

    # 4. Now Agent B can acquire lock
    res5 = asyncio.run(
        server.call_tool("memory_lock", {"resource_key": "module_xyz", "agent_id": "agent-B", "timeout_sec": 60})
    )
    assert res5.structured_content["status"] == "acquired"
    assert res5.structured_content["acquired"] is True


def test_memory_lock_renewal(tmp_path: Path) -> None:
    db_file = tmp_path / "renewal.sqlite"
    store = MemoryStore(db_file)

    t0 = time.time()
    # Acquire with 5s
    res1 = store.lock("res_renew", "agent-X", timeout_sec=5)
    assert res1["acquired"] is True

    time.sleep(0.1)
    # Renew with 60s
    res2 = store.lock("res_renew", "agent-X", timeout_sec=60)
    assert res2["acquired"] is True

    with store._connection() as conn:
        row = conn.execute("SELECT expires_at FROM locks WHERE resource_key = 'res_renew'").fetchone()
        assert row is not None
        assert row["expires_at"] >= t0 + 55
