"""M2.4: Session isolation via namespace, value redaction, TTL cleanup, and schema migration."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from token_context_mcp.memory.store import MemoryStore, _TARGET_USER_VERSION, _TTL_CLEANUP_INTERVAL, _redact_value


# ---------------------------------------------------------------------------
# _redact_value
# ---------------------------------------------------------------------------

class TestRedactValue:
    def test_redact_plain_string_no_secret(self):
        result = _redact_value("hello world")
        assert result == "hello world"

    def test_redact_string_with_api_key(self):
        # _redact_value applies redact_text line-by-line; the line must contain
        # a keyword assignment pattern (e.g. "token = ...") per content_policy regex.
        result = _redact_value("token = sk-1234567890abcdef1234567890abcdef12345678")
        assert "sk-1234567890abcdef1234567890abcdef12345678" not in result

    def test_redact_dict_leaf_values(self):
        # The regex matches lines containing keyword=value patterns.
        data = {
            "name": "test",
            "token": "token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        }
        result = _redact_value(data)
        assert result["name"] == "test"
        assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in str(result["token"])

    def test_redact_nested_structure(self):
        data = {
            "config": {
                "secret": "secret = AKIAIOSFODNN7EXAMPLE",
                "other": [1, 2, "safe"],
            }
        }
        result = _redact_value(data)
        assert "AKIAIOSFODNN7EXAMPLE" not in str(result)
        # Non-secret values preserved
        assert result["config"]["other"] == [1, 2, "safe"]

    def test_non_string_passthrough(self):
        assert _redact_value(42) == 42
        assert _redact_value(3.14) == 3.14
        assert _redact_value(None) is None
        assert _redact_value(True) is True


# ---------------------------------------------------------------------------
# Namespace isolation in put/get/delete
# ---------------------------------------------------------------------------

class TestNamespaceIsolation:
    def test_same_key_different_namespace_isolated(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "mem.sqlite")
        store.put("key1", "value-A", scope="session", namespace="ns-a")
        store.put("key1", "value-B", scope="session", namespace="ns-b")

        res_a = store.get("key1", scope="session", namespace="ns-a")
        res_b = store.get("key1", scope="session", namespace="ns-b")

        assert res_a["status"] == "found"
        assert res_a["value"] == "value-A"
        assert res_b["status"] == "found"
        assert res_b["value"] == "value-B"

    def test_get_missing_namespace_returns_not_found(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "mem.sqlite")
        store.put("key1", "value-A", scope="session", namespace="ns-a")

        # Same key, different namespace — not found
        res = store.get("key1", scope="session", namespace="ns-other")
        assert res["status"] == "not_found"

    def test_delete_scoped_to_namespace(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "mem.sqlite")
        store.put("key1", "value-A", scope="session", namespace="ns-a")
        store.put("key1", "value-B", scope="session", namespace="ns-b")

        store.delete("key1", scope="session", namespace="ns-a")

        assert store.get("key1", scope="session", namespace="ns-a")["status"] == "not_found"
        assert store.get("key1", scope="session", namespace="ns-b")["status"] == "found"

    def test_default_namespace_empty_string(self):
        store = MemoryStore()
        store.put("key1", "default-ns")
        res = store.get("key1")
        assert res["status"] == "found"
        assert res["namespace"] == ""

    def test_list_entries_filter_by_namespace(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "mem.sqlite")
        store.put("k1", "v1", scope="session", namespace="ns-a")
        store.put("k2", "v2", scope="session", namespace="ns-b")
        store.put("k3", "v3", scope="session", namespace="ns-a")

        entries_a = store.list_entries(scope="session", namespace="ns-a")
        entries_b = store.list_entries(scope="session", namespace="ns-b")

        assert len(entries_a) == 2
        assert all(e["namespace"] == "ns-a" for e in entries_a)
        assert len(entries_b) == 1

    def test_search_filter_by_namespace(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "mem.sqlite")
        store.put("alpha-key", "apple fruit basket", scope="session", namespace="grocery")
        store.put("other-key", "apple device phone", scope="session", namespace="tech")

        results = store.search("apple", namespace="grocery")
        assert results["matches_count"] == 1
        assert results["matches"][0]["namespace"] == "grocery"

    def test_put_response_includes_namespace(self):
        store = MemoryStore()
        res = store.put("key1", "val1", namespace="myns")
        assert res["namespace"] == "myns"

    def test_get_response_includes_namespace(self):
        store = MemoryStore()
        store.put("key1", "val1", namespace="myns")
        res = store.get("key1", namespace="myns")
        assert res["status"] == "found"
        assert res["namespace"] == "myns"


# ---------------------------------------------------------------------------
# Schema migration (v0 → v2 with backup)
# ---------------------------------------------------------------------------

class TestSchemaMigration:
    def test_fresh_db_gets_user_version_2(self, tmp_path: Path):
        import sqlite3
        store = MemoryStore(tmp_path / "fresh.sqlite")
        with sqlite3.connect(str(tmp_path / "fresh.sqlite")) as conn:
            ver = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert ver == _TARGET_USER_VERSION

    def test_migration_creates_backup_for_old_db(self, tmp_path: Path):
        import sqlite3
        db_path = tmp_path / "old.sqlite"
        # Create a v0 database manually
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE key_values (
                  scope TEXT NOT NULL,
                  key TEXT NOT NULL,
                  session_id TEXT,
                  value_json TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  expires_at REAL,
                  PRIMARY KEY (scope, key)
                )
            """)
            conn.execute("PRAGMA user_version = 0;")
            conn.commit()

        # Trigger migration
        store = MemoryStore(db_path)

        bak_path = db_path.with_suffix(".sqlite.bak-v0")
        assert bak_path.exists(), "backup file must be created before migration"

        with sqlite3.connect(str(db_path)) as conn:
            ver = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert ver == _TARGET_USER_VERSION

    def test_migrated_db_can_store_and_retrieve_with_namespace(self, tmp_path: Path):
        import sqlite3
        db_path = tmp_path / "old2.sqlite"
        # Create a v0 database
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE key_values (
                  scope TEXT NOT NULL,
                  key TEXT NOT NULL,
                  session_id TEXT,
                  value_json TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  expires_at REAL,
                  PRIMARY KEY (scope, key)
                )
            """)
            conn.execute("PRAGMA user_version = 0;")
            conn.commit()

        store = MemoryStore(db_path)
        store.put("k1", "hello", scope="session", namespace="ns1")
        res = store.get("k1", scope="session", namespace="ns1")
        assert res["status"] == "found"
        assert res["value"] == "hello"


# ---------------------------------------------------------------------------
# TTL cleanup
# ---------------------------------------------------------------------------

class TestTTLCleanup:
    def test_ttl_cleanup_runs_every_n_puts(self, tmp_path: Path):
        import sqlite3
        store = MemoryStore(tmp_path / "ttl.sqlite")
        now = time.time()
        # Insert an already-expired entry directly
        with sqlite3.connect(str(tmp_path / "ttl.sqlite")) as conn:
            conn.execute(
                "INSERT INTO key_values (scope, namespace, key, session_id, value_json, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                ("session", "", "expired_entry", None, '"old"', now - 1000, now - 500),
            )
            conn.commit()

        # Verify it's there
        with sqlite3.connect(str(tmp_path / "ttl.sqlite")) as conn:
            count_before = conn.execute("SELECT COUNT(*) FROM key_values WHERE key = 'expired_entry'").fetchone()[0]
        assert count_before == 1

        # Trigger N puts to force cleanup
        for i in range(_TTL_CLEANUP_INTERVAL):
            store.put(f"live-key-{i}", f"v{i}")

        # Expired entry should be deleted
        with sqlite3.connect(str(tmp_path / "ttl.sqlite")) as conn:
            count_after = conn.execute("SELECT COUNT(*) FROM key_values WHERE key = 'expired_entry'").fetchone()[0]
        assert count_after == 0, "TTL cleanup must remove expired entries after N puts"

    def test_live_entries_not_deleted_by_cleanup(self, tmp_path: Path):
        store = MemoryStore(tmp_path / "ttl2.sqlite")
        store.put("permanent", "keep-me", ttl=None)
        store.put("long-lived", "also-keep", ttl=86400)

        for i in range(_TTL_CLEANUP_INTERVAL):
            store.put(f"filler-{i}", f"v{i}")

        assert store.get("permanent")["status"] == "found"
        assert store.get("long-lived")["status"] == "found"
