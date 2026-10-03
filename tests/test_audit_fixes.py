"""Regression tests for the 0.3.3 audit fixes (identity, rate limit, policy, memory, lock ownership)."""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from token_context_mcp.memory.service import MemoryService
from token_context_mcp.memory.store import MemoryStore, _fts_match_query
from token_context_mcp.security.access_control import AccessControlManager, resolve_effective_agent_id
from token_context_mcp.server import build_server

TOKEN = "admin-secret-xyz"


def _call(server: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(server.call_tool(name, args)).structured_content


# --- BUG-01: rate limit applies to anonymous too ---------------------------------------------------------------

def test_anonymous_is_rate_limited_in_its_own_bucket() -> None:
    manager = AccessControlManager(max_calls_per_minute=3)
    assert all(manager.check_access("find_symbols", None)[0] for _ in range(3))
    allowed, reason = manager.check_access("find_symbols", None)
    assert allowed is False and reason is not None and reason.startswith("RATE_LIMITED")
    assert manager.check_access("find_symbols", "named-agent")[0] is True  # separate bucket


# --- BUG-02: no impersonation -----------------------------------------------------------------------------------

def test_env_bound_identity_rejects_a_different_agent_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_CONTEXT_AGENT_ID", "agent-a")
    assert resolve_effective_agent_id(None) == ("agent-a", None)
    assert resolve_effective_agent_id("agent-a") == ("agent-a", None)
    agent_id, error = resolve_effective_agent_id("agent-b")
    assert agent_id == "" and error is not None and "does not match" in error
    assert resolve_effective_agent_id("admin", trusted=True) == ("admin", None)


def test_reserved_admin_identity_cannot_be_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_CONTEXT_AGENT_ID", raising=False)
    agent_id, error = resolve_effective_agent_id("admin")
    assert agent_id == "" and error is not None and "reserved" in error
    assert resolve_effective_agent_id("admin", trusted=True) == ("admin", None)
    assert resolve_effective_agent_id("worker-1") == ("worker-1", None)
    assert resolve_effective_agent_id(None) == ("anonymous", None)


# --- BUG-05: lock ownership -------------------------------------------------------------------------------------

def test_bound_agent_cannot_lock_or_unlock_as_someone_else(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_CONTEXT_AGENT_ID", "agent-a")
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=False)

    assert _call(server, "memory_lock", {"resource_key": "git", "agent_id": "agent-a"})["acquired"] is True
    for tool, args in (
        ("memory_lock", {"resource_key": "git", "agent_id": "agent-b"}),
        ("memory_unlock", {"resource_key": "git", "agent_id": "agent-b"}),
    ):
        result = _call(server, tool, args)
        assert result["error"]["code"] == "invalid_request"
        assert "does not match" in result["error"]["message"]
    # the lock is still held by agent-a
    assert _call(server, "memory_unlock", {"resource_key": "git"})["status"] == "released"


def test_declared_agents_cannot_release_each_others_locks(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_CONTEXT_AGENT_ID", raising=False)
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=False)

    assert _call(server, "memory_lock", {"resource_key": "build", "agent_id": "agent-a"})["acquired"] is True
    assert _call(server, "memory_lock", {"resource_key": "build", "agent_id": "agent-b"})["acquired"] is False
    assert _call(server, "memory_unlock", {"resource_key": "build", "agent_id": "agent-b"})["status"] == "not_locked"
    assert _call(server, "memory_unlock", {"resource_key": "build", "agent_id": "agent-a"})["status"] == "released"
    assert _call(server, "memory_lock", {"resource_key": "build", "agent_id": "admin"})["error"]["code"] == "invalid_request"


# --- BUG-04: session_id round trip ------------------------------------------------------------------------------

def test_memory_get_accepts_session_id(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_CONTEXT_AGENT_ID", raising=False)
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=False)

    _call(server, "memory_put", {"key": "cursor", "value": {"n": 1}, "scope": "session", "session_id": "S1"})
    assert _call(server, "memory_get", {"key": "cursor", "scope": "session", "session_id": "S1"})["value"] == {"n": 1}
    assert _call(server, "memory_get", {"key": "cursor", "scope": "session", "namespace": "S1"})["status"] == "found"
    assert _call(server, "memory_get", {"key": "cursor", "scope": "session"})["status"] == "not_found"
    assert _call(server, "memory_get", {"key": "cursor", "scope": "session", "session_id": "S2"})["status"] == "not_found"


def test_memory_put_session_id_is_not_the_callers_identity(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_CONTEXT_AGENT_ID", "agent-a")
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=False)
    stored = _call(server, "memory_put", {"key": "k", "value": 1, "scope": "session", "session_id": "some-session"})
    assert stored["status"] == "stored"


# --- BUG-03: agent_control set_policy ---------------------------------------------------------------------------

def test_agent_control_set_policy(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_CONTEXT_ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("TOKEN_CONTEXT_AGENT_ID", raising=False)
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)
    lock = {"resource_key": "r", "agent_id": "worker"}

    def control(**args: Any) -> dict[str, Any]:
        return _call(server, "agent_control", {"admin_token": TOKEN, **args})

    assert control(action="set_policy", agent_id="worker", policy="READ_ONLY") == {
        "action": "set_policy", "agent_id": "worker", "policy": "READ_ONLY",
    }
    denied = _call(server, "memory_lock", lock)
    assert denied["error"]["code"] == "permission_revoked" and "READ_ONLY" in denied["error"]["message"]

    assert control(action="set_policy", agent_id="worker", policy="FULL_ACCESS")["policy"] == "FULL_ACCESS"
    assert _call(server, "memory_lock", lock)["acquired"] is True
    _call(server, "memory_unlock", {"resource_key": "r", "agent_id": "worker"})

    assert control(action="set_policy", agent_id="worker", policy="CUSTOM", custom_tools=["memory_get"])["policy"] == "CUSTOM"
    assert _call(server, "memory_lock", lock)["error"]["code"] == "permission_revoked"
    assert _call(server, "memory_get", {"key": "none"})["status"] == "not_found"  # anonymous is unaffected

    assert control(action="set_policy", agent_id="worker")["error"]["code"] == "invalid_request"  # policy missing
    assert control(action="set_policy", policy="READ_ONLY")["error"]["code"] == "invalid_request"  # agent_id missing
    assert control(action="set_policy", agent_id="worker", policy="CUSTOM")["error"]["code"] == "invalid_request"
    assert control(action="set_policy", agent_id="admin", policy="READ_ONLY")["error"]["code"] == "permission_revoked"
    assert _call(server, "agent_control", {"action": "set_policy", "agent_id": "worker", "policy": "READ_ONLY"})["error"][
        "code"
    ] == "permission_revoked"  # no admin token


def test_agent_control_still_works_when_identity_is_env_bound(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_CONTEXT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("TOKEN_CONTEXT_AGENT_ID", "agent-a")
    server = build_server(indexed_config, enable_extensions=True, enable_admin_tools=True)
    result = _call(server, "agent_control", {"action": "pause", "agent_id": "agent-z", "admin_token": TOKEN})
    assert result["status"] == "PAUSED"


# --- BUG-10 / BUG-11 and memory housekeeping -------------------------------------------------------------------

def test_fts_match_query_keeps_identifiers_as_phrases() -> None:
    assert _fts_match_query("app-config-v2") == '"app-config-v2"'
    assert _fts_match_query('models.py "exact phrase" --') == '"models.py" AND "exact phrase"'
    assert _fts_match_query("--- ...") is None
    assert _fts_match_query('say "hi') == '"say" AND "hi"'


def test_memory_search_matches_adjacent_tokens_only(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.sqlite")
    store.put("a", {"file": "app-config-v2 models.py"}, scope="project", namespace="repo:x")
    store.put("b", {"file": "app v2 config elsewhere"}, scope="project", namespace="repo:x")
    assert [m["key"] for m in store.search("app-config-v2", scope="project")["matches"]] == ["a"]
    assert [m["key"] for m in store.search("models.py", scope="project")["matches"]] == ["a"]
    assert {m["key"] for m in store.search("app config v2", scope="project")["matches"]} == {"a", "b"}
    assert store.search("---")["matches"] == []


def test_consolidate_prunes_in_the_namespace_it_read(tmp_path: Path) -> None:
    service = MemoryService(tmp_path / "m.sqlite")
    service.memory_put("p1", "v", scope="session", session_id="S1")
    service.memory_put("p2", "v", scope="session", session_id="S2")

    result = service.memory_consolidate(scope="session", prune_transient=True, namespace="S1")

    assert result["pruned_keys"] == ["p1"]
    assert service.memory_get("p1", session_id="S1")["status"] == "not_found"
    assert service.memory_get("p2", session_id="S2")["status"] == "found"


def test_store_delete_reports_whether_something_was_deleted(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.sqlite")
    store.put("k", 1, scope="project", namespace="ns")
    assert store.delete("k", scope="project", namespace="ns") is True
    assert store.delete("k", scope="project", namespace="ns") is False


def test_ttl_cleanup_also_removes_search_rows(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite"
    store = MemoryStore(db)
    store.put("old", "needle", ttl=1)
    time.sleep(1.2)
    for i in range(100):  # the periodic cleanup runs every 100 puts
        store.put(f"n{i}", "x")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_fts WHERE key = 'old'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM key_values WHERE key = 'old'").fetchone()[0] == 0


# --- BUG-13: pool connections of finished threads are released ---------------------------------------------------

def test_read_pool_closes_connections_of_finished_threads(tmp_path: Path) -> None:
    import threading

    from token_context_mcp.index.sqlite_store import ReadConnectionPool

    db = tmp_path / "snap.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
    pool = ReadConnectionPool()
    held: list[sqlite3.Connection] = []

    worker = threading.Thread(target=lambda: held.append(pool.get_connection(db)))
    worker.start()
    worker.join()
    assert len(pool._connections) == 1  # the finished worker's connection is still registered

    mine = pool.get_connection(db)  # the next connection to be created sweeps the dead thread's one
    assert list(pool._connections.values()) == [mine]
    with pytest.raises(sqlite3.ProgrammingError):
        held[0].execute("SELECT 1")  # closed
    assert mine.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    pool.close_all()


# --- BUG-09: file swaps retry when Windows holds the file ---------------------------------------------------------

def test_replace_retries_permission_errors_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from token_context_mcp.index import runner

    sleeps: list[float] = []
    monkeypatch.setattr(runner.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def flaky() -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("[WinError 32] The process cannot access the file")

    runner._retry_on_permission_error(flaky)
    assert calls["n"] == 3 and sleeps == [0.05, 0.1]


def test_replace_gives_up_after_the_last_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from token_context_mcp.index import runner

    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    calls = {"n": 0}

    def always_locked() -> None:
        calls["n"] += 1
        raise PermissionError("locked")

    with pytest.raises(PermissionError):
        runner._retry_on_permission_error(always_locked)
    assert calls["n"] == len(runner._REPLACE_RETRY_DELAYS_SEC) + 1


def test_pointer_swap_survives_a_transient_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, save_config
    from token_context_mcp.index import runner

    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    repo = RepositoryConfig(repo_id="demo", root=root.resolve())
    save_config(tmp_path / "config" / "repos.toml", AppConfig(repositories={"demo": repo}, server=ServerConfig()))
    index_dir = tmp_path / "config" / "indexes"

    real_replace = runner.os.replace
    failures = {"left": 2}

    def locked_twice(src: Any, dst: Any) -> None:
        if str(dst).endswith(".current.json") and failures["left"] > 0:
            failures["left"] -= 1
            raise PermissionError("[WinError 32] pointer is being read")
        real_replace(src, dst)

    monkeypatch.setattr(runner.os, "replace", locked_twice)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    runner.build_index(repo, index_dir, network_policy="declared-deny-not-enforced")

    assert failures["left"] == 0
    assert runner.current_pointer_path(index_dir, "demo").is_file()
