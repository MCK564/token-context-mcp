"""SQLite persistence for the verified evidence ledger."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from token_context_mcp.security.local_privacy import secure_directory, secure_file

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CardItemRecord:
    card_id: int
    role: str  # answer | step | decoy
    ord: int
    language: str
    path: str
    qualified_name: str
    body_sha256: str
    evidence_line: int | None = None
    line_sha: str | None = None
    next_qualified_name: str | None = None
    reason_code: str | None = None
    check_kind: str = "source_verified"  # source_verified | asserted
    index_edge_missing: bool = False


@dataclass(frozen=True)
class CardRecord:
    card_id: int
    repo_id: str
    sig_tokens: tuple[str, ...]
    sig_hash: str
    status: str  # asserted | confirmed | conflicted | retired
    confirmations: int
    created_at: float
    last_verified_at: float
    last_used_at: float | None
    expires_at: float
    agent_id: str
    run_id: str
    index_run_id: str
    items: tuple[CardItemRecord, ...] = ()


class LedgerStore:
    """Thread-safe SQLite store for verified evidence cards (`ledger.sqlite`)."""

    def __init__(self, db_path: Path, *, max_cards_per_repo: int = 500, ttl_days: int = 28) -> None:
        self.db_path = db_path
        self.max_cards_per_repo = max_cards_per_repo
        self.ttl_days = ttl_days
        self._local = threading.local()
        secure_directory(self.db_path.parent)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                self._local.conn = None
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self._migrate_v0_to_v1(conn)
            elif version != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported ledger schema version: {version}")
        if self.db_path.exists():
            secure_file(self.db_path)

    def _migrate_v0_to_v1(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards (
                card_id INTEGER PRIMARY KEY,
                repo_id TEXT NOT NULL,
                sig_tokens TEXT NOT NULL,
                sig_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                confirmations INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                last_verified_at REAL NOT NULL,
                last_used_at REAL,
                expires_at REAL NOT NULL,
                agent_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                index_run_id TEXT NOT NULL,
                UNIQUE (repo_id, sig_hash)
            );
            CREATE TABLE IF NOT EXISTS card_items (
                card_id INTEGER NOT NULL REFERENCES cards(card_id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                ord INTEGER NOT NULL,
                language TEXT NOT NULL,
                path TEXT NOT NULL,
                qualified_name TEXT NOT NULL,
                body_sha256 TEXT NOT NULL,
                evidence_line INTEGER,
                line_sha TEXT,
                next_qualified_name TEXT,
                reason_code TEXT,
                check_kind TEXT NOT NULL,
                index_edge_missing INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (card_id, role, ord, path, qualified_name)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
                card_id UNINDEXED,
                repo_id UNINDEXED,
                sig
            );
            CREATE TABLE IF NOT EXISTS ledger_meta (
                repo_id TEXT PRIMARY KEY,
                rev INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_cards_repo_status ON cards(repo_id, status);
            CREATE INDEX IF NOT EXISTS idx_cards_expires ON cards(expires_at);
            PRAGMA user_version = 1;
            """
        )

    def get_rev(self, repo_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rev FROM ledger_meta WHERE repo_id = ?", (repo_id,)
            ).fetchone()
            return int(row["rev"]) if row else 0

    def _bump_rev(self, conn: sqlite3.Connection, repo_id: str) -> int:
        conn.execute(
            """
            INSERT INTO ledger_meta (repo_id, rev) VALUES (?, 1)
            ON CONFLICT(repo_id) DO UPDATE SET rev = rev + 1
            """,
            (repo_id,),
        )
        row = conn.execute("SELECT rev FROM ledger_meta WHERE repo_id = ?", (repo_id,)).fetchone()
        return int(row["rev"]) if row else 1

    def upsert_card(
        self,
        *,
        repo_id: str,
        sig_tokens_json: str,
        sig_hash: str,
        fts_text: str,
        agent_id: str,
        run_id: str,
        index_run_id: str,
        items: list[CardItemRecord],
        now: float | None = None,
    ) -> tuple[int, str, int]:
        """Insert or update a card. Returns (card_id, status, ledger_rev)."""
        ts = now if now is not None else time.time()
        expires_at = ts + self.ttl_days * 86400.0
        new_answers = {(it.path, it.qualified_name) for it in items if it.role == "answer"}
        new_decoys = {(it.path, it.qualified_name) for it in items if it.role == "decoy"}

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM cards WHERE repo_id = ? AND sig_hash = ?",
                (repo_id, sig_hash),
            ).fetchone()

            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO cards (
                        repo_id, sig_tokens, sig_hash, status, confirmations,
                        created_at, last_verified_at, last_used_at, expires_at,
                        agent_id, run_id, index_run_id
                    ) VALUES (?, ?, ?, 'asserted', 1, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        repo_id,
                        sig_tokens_json,
                        sig_hash,
                        ts,
                        ts,
                        expires_at,
                        agent_id,
                        run_id,
                        index_run_id,
                    ),
                )
                card_id = int(cur.lastrowid)
                self._replace_items(conn, card_id, items)
                conn.execute(
                    "INSERT INTO cards_fts (card_id, repo_id, sig) VALUES (?, ?, ?)",
                    (card_id, repo_id, fts_text),
                )
                self._evict_if_needed(conn, repo_id)
                rev = self._bump_rev(conn, repo_id)
                return card_id, "asserted", rev

            card_id = int(existing["card_id"])
            old_items = self._load_items(conn, card_id)
            old_answers = {(it.path, it.qualified_name) for it in old_items if it.role == "answer"}
            old_decoys = {(it.path, it.qualified_name) for it in old_items if it.role == "decoy"}

            conflict = bool((old_answers & new_decoys) or (old_decoys & new_answers))
            status = str(existing["status"])
            confirmations = int(existing["confirmations"])

            if conflict:
                status = "conflicted"
            elif status == "retired":
                status = "asserted"
                confirmations = 1
                self._replace_items(conn, card_id, items)
            elif status != "conflicted":
                same_answers = bool(old_answers and old_answers == new_answers)
                if same_answers:
                    if str(existing["run_id"]) != run_id:
                        confirmations += 1
                        status = "confirmed"
                    self._replace_items(conn, card_id, items)
                else:
                    if str(existing["run_id"]) != run_id:
                        # Different runs disagree on the answer for the same query signature
                        status = "conflicted"
                    else:
                        status = "asserted"
                        confirmations = 1
                        self._replace_items(conn, card_id, items)

            conn.execute(
                """
                UPDATE cards
                SET status = ?, confirmations = ?, last_verified_at = ?,
                    expires_at = ?, agent_id = ?, run_id = ?, index_run_id = ?
                WHERE card_id = ?
                """,
                (status, confirmations, ts, expires_at, agent_id, run_id, index_run_id, card_id),
            )
            rev = self._bump_rev(conn, repo_id)
            return card_id, status, rev

    def _replace_items(
        self, conn: sqlite3.Connection, card_id: int, items: list[CardItemRecord]
    ) -> None:
        conn.execute("DELETE FROM card_items WHERE card_id = ?", (card_id,))
        for it in items:
            conn.execute(
                """
                INSERT INTO card_items (
                    card_id, role, ord, language, path, qualified_name,
                    body_sha256, evidence_line, line_sha, next_qualified_name,
                    reason_code, check_kind, index_edge_missing
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    it.role,
                    it.ord,
                    it.language,
                    it.path,
                    it.qualified_name,
                    it.body_sha256,
                    it.evidence_line,
                    it.line_sha,
                    it.next_qualified_name,
                    it.reason_code,
                    it.check_kind,
                    1 if it.index_edge_missing else 0,
                ),
            )

    def _evict_if_needed(self, conn: sqlite3.Connection, repo_id: str) -> None:
        count = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE repo_id = ?", (repo_id,)
        ).fetchone()[0]
        excess = int(count) - self.max_cards_per_repo
        if excess <= 0:
            return
        victims = conn.execute(
            """
            SELECT card_id FROM cards
            WHERE repo_id = ?
            ORDER BY COALESCE(last_used_at, created_at) ASC, card_id ASC
            LIMIT ?
            """,
            (repo_id, excess),
        ).fetchall()
        for row in victims:
            cid = int(row["card_id"])
            conn.execute("DELETE FROM cards_fts WHERE card_id = ?", (cid,))
            conn.execute("DELETE FROM cards WHERE card_id = ?", (cid,))

    def _load_items(self, conn: sqlite3.Connection, card_id: int) -> tuple[CardItemRecord, ...]:
        rows = conn.execute(
            "SELECT * FROM card_items WHERE card_id = ? ORDER BY role ASC, ord ASC",
            (card_id,),
        ).fetchall()
        return tuple(
            CardItemRecord(
                card_id=int(r["card_id"]),
                role=str(r["role"]),
                ord=int(r["ord"]),
                language=str(r["language"]),
                path=str(r["path"]),
                qualified_name=str(r["qualified_name"]),
                body_sha256=str(r["body_sha256"]),
                evidence_line=int(r["evidence_line"]) if r["evidence_line"] is not None else None,
                line_sha=str(r["line_sha"]) if r["line_sha"] is not None else None,
                next_qualified_name=(
                    str(r["next_qualified_name"]) if r["next_qualified_name"] is not None else None
                ),
                reason_code=str(r["reason_code"]) if r["reason_code"] is not None else None,
                check_kind=str(r["check_kind"]),
                index_edge_missing=bool(r["index_edge_missing"]),
            )
            for r in rows
        )

    def _row_to_card(self, conn: sqlite3.Connection, row: sqlite3.Row) -> CardRecord:
        cid = int(row["card_id"])
        return CardRecord(
            card_id=cid,
            repo_id=str(row["repo_id"]),
            sig_tokens=tuple(json.loads(str(row["sig_tokens"]))),
            sig_hash=str(row["sig_hash"]),
            status=str(row["status"]),
            confirmations=int(row["confirmations"]),
            created_at=float(row["created_at"]),
            last_verified_at=float(row["last_verified_at"]),
            last_used_at=float(row["last_used_at"]) if row["last_used_at"] is not None else None,
            expires_at=float(row["expires_at"]),
            agent_id=str(row["agent_id"]),
            run_id=str(row["run_id"]),
            index_run_id=str(row["index_run_id"]),
            items=self._load_items(conn, cid),
        )

    def find_candidates(
        self, repo_id: str, tokens: tuple[str, ...], *, now: float | None = None, limit: int = 20
    ) -> list[CardRecord]:
        if not tokens:
            return []
        ts = now if now is not None else time.time()
        safe_terms = ['"' + t.replace('"', '""') + '"' for t in tokens if t]
        if not safe_terms:
            return []
        fts_query = " OR ".join(safe_terms)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*
                FROM cards_fts f
                JOIN cards c ON c.card_id = f.card_id
                WHERE f.repo_id = ?
                  AND f.sig MATCH ?
                  AND c.status IN ('asserted', 'confirmed')
                  AND c.expires_at >= ?
                LIMIT ?
                """,
                (repo_id, fts_query, ts, limit),
            ).fetchall()
            return [self._row_to_card(conn, r) for r in rows]

    def mark_used(self, card_id: int, *, now: float | None = None) -> None:
        ts = now if now is not None else time.time()
        expires_at = ts + self.ttl_days * 86400.0
        with self._connect() as conn:
            conn.execute(
                "UPDATE cards SET last_used_at = ?, expires_at = ? WHERE card_id = ?",
                (ts, expires_at, card_id),
            )

    def set_status(self, card_id: int, status: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT repo_id FROM cards WHERE card_id = ?", (card_id,)).fetchone()
            if row is None:
                return False
            conn.execute("UPDATE cards SET status = ? WHERE card_id = ?", (status, card_id))
            self._bump_rev(conn, str(row["repo_id"]))
            return True

    def confirm_card(self, card_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT repo_id FROM cards WHERE card_id = ?", (card_id,)).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE cards SET status = 'confirmed', confirmations = confirmations + 1 WHERE card_id = ?",
                (card_id,),
            )
            self._bump_rev(conn, str(row["repo_id"]))
            return True

    def forget_card(self, card_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT repo_id FROM cards WHERE card_id = ?", (card_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM cards_fts WHERE card_id = ?", (card_id,))
            conn.execute("DELETE FROM cards WHERE card_id = ?", (card_id,))
            self._bump_rev(conn, str(row["repo_id"]))
            return True

    def prune(self, repo_id: str | None = None, *, now: float | None = None) -> int:
        ts = now if now is not None else time.time()
        with self._connect() as conn:
            if repo_id:
                rows = conn.execute(
                    "SELECT card_id FROM cards WHERE repo_id = ? AND (expires_at < ? OR status = 'retired')",
                    (repo_id, ts),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT card_id, repo_id FROM cards WHERE expires_at < ? OR status = 'retired'",
                    (ts,),
                ).fetchall()
            for r in rows:
                cid = int(r["card_id"])
                conn.execute("DELETE FROM cards_fts WHERE card_id = ?", (cid,))
                conn.execute("DELETE FROM cards WHERE card_id = ?", (cid,))
            if rows and repo_id:
                self._bump_rev(conn, repo_id)
            elif rows:
                for rid in {str(r["repo_id"]) for r in rows}:
                    self._bump_rev(conn, rid)
            return len(rows)

    def list_cards(self, repo_id: str | None = None) -> list[CardRecord]:
        with self._connect() as conn:
            if repo_id:
                rows = conn.execute(
                    "SELECT * FROM cards WHERE repo_id = ? ORDER BY card_id DESC", (repo_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM cards ORDER BY card_id DESC").fetchall()
            return [self._row_to_card(conn, r) for r in rows]

    def get_card(self, card_id: int) -> CardRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cards WHERE card_id = ?", (card_id,)).fetchone()
            return self._row_to_card(conn, row) if row is not None else None
