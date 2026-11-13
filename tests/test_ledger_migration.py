from __future__ import annotations

import sqlite3
from pathlib import Path

from token_context_mcp.ledger.store import SCHEMA_VERSION, LedgerStore


def test_ledger_migration_sets_user_version_and_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    LedgerStore(db_path)
    with sqlite3.connect(db_path) as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
    assert ver == SCHEMA_VERSION
    assert {"cards", "card_items", "cards_fts", "ledger_meta"} <= tables
