"""Comprehensive regression tests for MemoryStore schema migration (G1)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from token_context_mcp.memory.store import MemoryStore, _TARGET_USER_VERSION

OLD_SCHEMA_V1 = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS key_values (
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  session_id TEXT,
  value_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL,
  PRIMARY KEY (scope, key)
);
CREATE INDEX IF NOT EXISTS kv_scope_idx ON key_values(scope);
CREATE INDEX IF NOT EXISTS kv_expires_idx ON key_values(expires_at);

CREATE TABLE IF NOT EXISTS locks (
  resource_key TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  acquired_at REAL NOT NULL,
  expires_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  scope UNINDEXED,
  key UNINDEXED,
  content
);
"""


def test_migration_from_v1_database(tmp_path: Path) -> None:
    db_file = tmp_path / "memory_v1.sqlite"
    now = time.time()

    # 1. Build a real v1 database with unredacted secret
    conn = sqlite3.connect(str(db_file))
    conn.executescript(OLD_SCHEMA_V1)
    conn.execute(
        "INSERT INTO key_values (scope, key, session_id, value_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("session", "k_sess", "s1", json.dumps({"token": "token = secret123"}), now, None),
    )
    conn.execute(
        "INSERT INTO memory_fts (scope, key, content) VALUES (?, ?, ?)",
        ("session", "k_sess", 'k_sess {"token": "token = secret123"}'),
    )
    conn.execute(
        "INSERT INTO key_values (scope, key, session_id, value_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("project", "k_proj", None, json.dumps({"plan": "migration plan"}), now, None),
    )
    conn.execute(
        "INSERT INTO memory_fts (scope, key, content) VALUES (?, ?, ?)",
        ("project", "k_proj", 'k_proj {"plan": "migration plan"}'),
    )
    conn.execute("PRAGMA user_version = 1;")
    conn.commit()
    conn.close()

    # 2. Open with new MemoryStore
    store = MemoryStore(db_file)

    # 3. Verify backup created
    bak_files = list(tmp_path.glob("memory_v1.sqlite.bak-v1*"))
    assert len(bak_files) >= 1, "Backup file for v1 must be created"

    # 4. Check user_version is 3
    with sqlite3.connect(str(db_file)) as c:
        ver = c.execute("PRAGMA user_version;").fetchone()[0]
        assert ver == 3

    # 5. search("plan") finds project row
    search_res = store.search("plan")
    assert search_res["matches_count"] >= 1
    assert any(m["key"] == "k_proj" for m in search_res["matches"])

    # 6. get("k_sess", scope="session", session_id="s1") reads session row
    get_res = store.get("k_sess", scope="session", session_id="s1")
    assert get_res["status"] == "found"
    assert get_res["namespace"] == "s1"

    # 7. put new key works
    put_res = store.put("k_new", {"data": "fresh_entry"}, scope="session", namespace="s1")
    assert put_res["status"] == "stored"

    # 8. Secret was redacted on disk in legacy row
    with sqlite3.connect(str(db_file)) as c:
        raw_val = c.execute("SELECT value_json FROM key_values WHERE key = 'k_sess'").fetchone()[0]
        assert "secret123" not in raw_val
        assert "[REDACTED" in raw_val


def test_migration_from_broken_v2_database(tmp_path: Path) -> None:
    db_file = tmp_path / "memory_broken_v2.sqlite"
    now = time.time()

    # Create a broken v2 database:
    # key_values has namespace column, but session rows have namespace=''
    # memory_fts is old v1 FTS table (no namespace column)
    # user_version is 2
    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE key_values (
      scope TEXT NOT NULL,
      namespace TEXT NOT NULL DEFAULT '',
      key TEXT NOT NULL,
      session_id TEXT,
      value_json TEXT NOT NULL,
      created_at REAL NOT NULL,
      expires_at REAL,
      PRIMARY KEY (scope, namespace, key)
    );
    CREATE VIRTUAL TABLE memory_fts USING fts5(
      scope UNINDEXED,
      key UNINDEXED,
      content
    );
    """)
    conn.execute(
        "INSERT INTO key_values (scope, namespace, key, session_id, value_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("session", "", "k_sess", "s2", json.dumps({"token": "token = broken_secret_99"}), now, None),
    )
    conn.execute(
        "INSERT INTO memory_fts (scope, key, content) VALUES (?, ?, ?)",
        ("session", "k_sess", 'k_sess {"token": "token = broken_secret_99"}'),
    )
    conn.execute(
        "INSERT INTO key_values (scope, namespace, key, session_id, value_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("project", "", "k_plan", None, json.dumps({"title": "project plan v2"}), now, None),
    )
    conn.execute(
        "INSERT INTO memory_fts (scope, key, content) VALUES (?, ?, ?)",
        ("project", "k_plan", 'k_plan {"title": "project plan v2"}'),
    )
    conn.execute("PRAGMA user_version = 2;")
    conn.commit()
    conn.close()

    # Open with new MemoryStore
    store = MemoryStore(db_file)

    # Backup for v2 exists
    bak_files = list(tmp_path.glob("memory_broken_v2.sqlite.bak-v2*"))
    assert len(bak_files) >= 1

    # user_version upgraded to 3
    with sqlite3.connect(str(db_file)) as c:
        ver = c.execute("PRAGMA user_version;").fetchone()[0]
        assert ver == 3

    # search("plan") succeeds without invalid_query
    res = store.search("plan")
    assert "warnings" not in res or "invalid_query" not in res.get("warnings", [])
    assert res["matches_count"] >= 1

    # session row has namespace='s2'
    get_res = store.get("k_sess", scope="session", session_id="s2")
    assert get_res["status"] == "found"
    assert get_res["namespace"] == "s2"

    # Secret redacted
    with sqlite3.connect(str(db_file)) as c:
        raw_val = c.execute("SELECT value_json FROM key_values WHERE key = 'k_sess'").fetchone()[0]
        assert "broken_secret_99" not in raw_val


def test_fts_syntax_error_returns_invalid_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import contextmanager

    store = MemoryStore(tmp_path / "mem.sqlite")
    original_conn = store._connection

    class ProxyConn:
        def __init__(self, real_conn):
            self._real = real_conn

        def execute(self, sql, params=()):
            if "MATCH" in sql:
                raise sqlite3.OperationalError("fts5: syntax error near 'AND'")
            return self._real.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._real, name)

    @contextmanager
    def mock_conn():
        with original_conn() as conn:
            yield ProxyConn(conn)

    monkeypatch.setattr(store, "_connection", mock_conn)
    res = store.search("AND OR NOT")
    assert "invalid_query" in res.get("warnings", [])




def test_structural_operational_error_is_raised(tmp_path: Path) -> None:
    db_file = tmp_path / "struct_err.sqlite"
    store = MemoryStore(db_file)

    # Intentionally corrupt the table by dropping a column needed by query
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("DROP TABLE memory_fts;")
        conn.execute("CREATE VIRTUAL TABLE memory_fts USING fts5(scope UNINDEXED, content);")
        conn.commit()

    # Calling search must re-raise OperationalError (not swallow as invalid_query)
    with pytest.raises(sqlite3.OperationalError):
        store.search("test")
