from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from token_context_mcp.models import EdgeRecord, ExternalStubRecord, FileRecord, SymbolRecord
from token_context_mcp.security.local_privacy import secure_directory, secure_sqlite_artifacts

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  language TEXT,
  parse_status TEXT NOT NULL,
  warnings_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS symbols (
  symbol_id TEXT PRIMARY KEY,
  path TEXT NOT NULL REFERENCES files(path),
  name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  kind TEXT NOT NULL,
  signature TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  start_byte INTEGER NOT NULL,
  end_byte INTEGER NOT NULL,
  body_start_byte INTEGER,
  body_end_byte INTEGER,
  is_private INTEGER NOT NULL,
  roles_json TEXT NOT NULL,
  role_evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS symbols_path_idx ON symbols(path);
CREATE INDEX IF NOT EXISTS symbols_name_idx ON symbols(name);
CREATE INDEX IF NOT EXISTS symbols_qualified_name_idx ON symbols(qualified_name);
CREATE VIRTUAL TABLE IF NOT EXISTS symbol_bodies USING fts5(
  symbol_id UNINDEXED,
  path UNINDEXED,
  body
);
CREATE VIRTUAL TABLE IF NOT EXISTS source_bodies USING fts5(
  path UNINDEXED,
  body
);
CREATE VIRTUAL TABLE IF NOT EXISTS symbol_fts USING fts5(
  symbol_id UNINDEXED,
  path UNINDEXED,
  name,
  qualified_name,
  code_tokens,
  own_body,
  tokenize = "unicode61 remove_diacritics 2 tokenchars '_'"
);
CREATE TABLE IF NOT EXISTS external_stubs (
  stub_id INTEGER PRIMARY KEY AUTOINCREMENT,
  package TEXT NOT NULL,
  export_path TEXT NOT NULL,
  member_name TEXT NOT NULL,
  signature TEXT,
  doc_summary TEXT,
  UNIQUE(export_path, member_name)
);
CREATE INDEX IF NOT EXISTS external_stubs_pkg_idx ON external_stubs(package);
CREATE INDEX IF NOT EXISTS external_stubs_lookup_idx ON external_stubs(export_path, member_name);
CREATE TABLE IF NOT EXISTS edges (
  edge_id INTEGER PRIMARY KEY,
  source_symbol_id TEXT NOT NULL REFERENCES symbols(symbol_id),
  target_symbol_id TEXT REFERENCES symbols(symbol_id),
  target_stub_id INTEGER REFERENCES external_stubs(stub_id),
  target_name TEXT NOT NULL,
  edge_kind TEXT NOT NULL,
  status TEXT NOT NULL,
  backend TEXT NOT NULL,
  confidence REAL,
  source_path TEXT NOT NULL,
  source_line INTEGER NOT NULL,
  evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS edges_source_idx ON edges(source_symbol_id);
CREATE INDEX IF NOT EXISTS edges_target_idx ON edges(target_symbol_id);
CREATE INDEX IF NOT EXISTS edges_stub_idx ON edges(target_stub_id);
CREATE INDEX IF NOT EXISTS edges_target_name_idx ON edges(target_name);
CREATE TABLE IF NOT EXISTS imports (
  path TEXT NOT NULL REFERENCES files(path),
  module TEXT NOT NULL,
  PRIMARY KEY(path, module)
);
CREATE INDEX IF NOT EXISTS imports_path_idx ON imports(path);
CREATE INDEX IF NOT EXISTS imports_module_idx ON imports(module);
CREATE TABLE IF NOT EXISTS class_hierarchy (
  class_symbol_id TEXT NOT NULL REFERENCES symbols(symbol_id),
  parent_name TEXT NOT NULL,
  parent_symbol_id TEXT REFERENCES symbols(symbol_id),
  PRIMARY KEY (class_symbol_id, parent_name)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS class_hierarchy_parent_idx ON class_hierarchy(parent_name);
CREATE TABLE IF NOT EXISTS symbol_rank (
  symbol_id TEXT PRIMARY KEY REFERENCES symbols(symbol_id),
  score REAL NOT NULL,
  basis_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS symbol_rank_score_idx ON symbol_rank(score DESC);
CREATE TABLE IF NOT EXISTS file_parse_artifacts (
  path TEXT PRIMARY KEY REFERENCES files(path),
  sha256 TEXT NOT NULL,
  parser_version INTEGER NOT NULL,
  language TEXT,
  calls_json TEXT NOT NULL,
  inheritance_json TEXT NOT NULL,
  imports_json TEXT NOT NULL,
  warnings_json TEXT NOT NULL,
  facts_json TEXT NOT NULL DEFAULT '{}'
);
"""


class StoreError(RuntimeError):
    pass


class ReadConnectionPool:
    """Thread-safe connection pool for read-only SQLite database access."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (thread_id, resolved_path_str) -> sqlite3.Connection
        self._connections: dict[tuple[int, str], sqlite3.Connection] = {}

    def get_connection(self, path: Path) -> sqlite3.Connection:
        tid = threading.get_ident()
        resolved = str(path.resolve())
        key = (tid, resolved)
        with self._lock:
            conn = self._connections.get(key)
            if conn is not None:
                return conn

        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON;")
        conn.execute("PRAGMA mmap_size = 268435456;")
        conn.execute("PRAGMA cache_size = -65536;")
        conn.execute("PRAGMA temp_store = MEMORY;")

        with self._lock:
            if key in self._connections:
                conn.close()
                return self._connections[key]
            self._connections[key] = conn
            return conn

    def close_db(self, path: Path) -> None:
        resolved = str(path.resolve())
        with self._lock:
            to_close = [k for k in self._connections if k[1] == resolved]
            for k in to_close:
                conn = self._connections.pop(k, None)
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def close_all(self) -> None:
        with self._lock:
            for conn in self._connections.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()


class SQLiteStore:
    def __init__(
        self,
        path: Path,
        *,
        read_only: bool = False,
        pool: ReadConnectionPool | None = None,
    ) -> None:
        self.path = path
        self.read_only = read_only
        self.pool = pool
        self._query_count = 0

    @property
    def query_count(self) -> int:
        return self._query_count

    def reset_query_count(self) -> None:
        self._query_count = 0

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        from_pool = False
        if self.read_only and self.pool is not None:
            connection = self.pool.get_connection(self.path)
            from_pool = True
        elif self.read_only:
            uri = f"file:{self.path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
        else:
            secure_directory(self.path.parent)
            connection = sqlite3.connect(self.path)
            # SQLite creates the database with the process umask, which on a
            # default POSIX host leaves indexed source bodies world-readable.
            secure_sqlite_artifacts(self.path)
            connection.row_factory = sqlite3.Row

        if os.environ.get("TOKEN_CONTEXT_TRACE_SQL") == "1":
            connection.set_trace_callback(self._count_query)
        else:
            connection.set_trace_callback(None)

        try:
            yield connection
            if not self.read_only:
                connection.commit()
        except Exception:
            if not self.read_only:
                connection.rollback()
            raise
        finally:
            if not from_pool:
                connection.close()
                if not self.read_only:
                    # The WAL sidecars only appear once the session writes.
                    secure_sqlite_artifacts(self.path)

    def _count_query(self, statement: str) -> None:
        raw = statement.strip()
        if raw.startswith(("--", "PRAGMA")) or "_config" in raw:
            return
        self._query_count += 1

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    def write_snapshot(
        self,
        *,
        metadata: dict[str, Any],
        files: list[FileRecord],
        symbols: list[SymbolRecord],
        edges: list[EdgeRecord],
        imports: dict[str, list[str]],
        symbol_bodies: dict[str, str] | None = None,
        source_bodies: dict[str, str] | None = None,
        class_hierarchy: list[tuple[str, str, str | None]] | None = None,
        external_stubs: list[ExternalStubRecord] | None = None,
        symbol_ranks: list[tuple[str, float, list[str]]] | None = None,
        symbol_fts_records: Iterable[tuple[str, str, str, str, str, str]] | None = None,
        symbol_body_rows: Iterable[tuple[str, str, str]] | None = None,
        source_body_rows: Iterable[tuple[str, str]] | None = None,
        parse_artifact_rows: Iterable[tuple] | None = None,
        reuse_text_from: Path | None = None,
        reuse_text_paths: Collection[str] | None = None,
        delta_from_base: bool = False,
    ) -> None:
        """Write a complete snapshot.

        ``symbol_bodies`` / ``source_bodies`` (dicts) and ``symbol_body_rows`` / ``source_body_rows`` (row
        iterables) are alternative ways to give the full-text rows.  ``reuse_text_from`` + ``reuse_text_paths``
        additionally copy the text rows (``symbol_bodies``, ``source_bodies``, ``symbol_fts``) of those paths
        from an earlier snapshot, so unchanged files need not be read again (M7).  With ``delta_from_base`` the
        new file starts as a page-level copy of that snapshot and only the text rows of paths *outside*
        ``reuse_text_paths`` are deleted (the caller re-supplies rows for changed files), so the full-text index
        is not rebuilt for untouched files; every other table is rewritten.
        """
        if self.read_only:
            raise StoreError("cannot write a read-only snapshot")
        delta = bool(delta_from_base and reuse_text_from is not None and reuse_text_paths is not None)
        if delta:
            _clone_snapshot(reuse_text_from, self.path)  # type: ignore[arg-type]
        self.initialize()
        with self.connection() as connection:
            wiped = ("file_parse_artifacts", "external_stubs", "class_hierarchy", "edges", "imports", "symbol_rank", "symbols", "files", "metadata")
            fts_tables = ("symbol_bodies", "source_bodies", "symbol_fts")
            for table in (*wiped, *(() if delta else fts_tables)):
                connection.execute(f"DELETE FROM {table}")
            if delta:
                connection.execute("CREATE TEMP TABLE keep_paths(path TEXT PRIMARY KEY)")
                connection.executemany("INSERT INTO keep_paths(path) VALUES (?)", [(path,) for path in reuse_text_paths])  # type: ignore[union-attr]
                for table in fts_tables:
                    connection.execute(f"DELETE FROM {table} WHERE path NOT IN (SELECT path FROM keep_paths)")
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [(key, json.dumps(value, sort_keys=True)) for key, value in metadata.items()],
            )
            connection.executemany(
                """INSERT INTO files(path, sha256, size, mtime_ns, language, parse_status, warnings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item.path,
                        item.sha256,
                        item.size,
                        item.mtime_ns,
                        item.language,
                        item.parse_status,
                        json.dumps(item.warnings),
                    )
                    for item in files
                ],
            )
            connection.executemany(
                """INSERT INTO symbols(
                    symbol_id, path, name, qualified_name, kind, signature, start_line, end_line,
                    start_byte, end_byte, body_start_byte, body_end_byte, is_private,
                    roles_json, role_evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item.symbol_id,
                        item.path,
                        item.name,
                        item.qualified_name,
                        item.kind,
                        item.signature,
                        item.start_line,
                        item.end_line,
                        item.start_byte,
                        item.end_byte,
                        item.body_start_byte,
                        item.body_end_byte,
                        int(item.is_private),
                        json.dumps(item.roles),
                        json.dumps(item.role_evidence, sort_keys=True),
                    )
                    for item in symbols
                ],
            )
            if class_hierarchy:
                connection.executemany(
                    "INSERT INTO class_hierarchy(class_symbol_id, parent_name, parent_symbol_id) VALUES (?, ?, ?)",
                    class_hierarchy,
                )
            if external_stubs:
                connection.executemany(
                    """INSERT INTO external_stubs(stub_id, package, export_path, member_name, signature, doc_summary)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            s.stub_id,
                            s.package,
                            s.export_path,
                            s.member_name,
                            s.signature,
                            s.doc_summary,
                        )
                        for s in external_stubs
                    ],
                )
            connection.executemany(
                """INSERT INTO edges(
                    source_symbol_id, target_symbol_id, target_stub_id, target_name, edge_kind, status, backend,
                    confidence, source_path, source_line, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item.source_symbol_id,
                        item.target_symbol_id,
                        item.target_stub_id,
                        item.target_name,
                        item.edge_kind,
                        item.status,
                        item.backend,
                        item.confidence,
                        item.source_path,
                        item.source_line,
                        json.dumps(item.evidence),
                    )
                    for item in edges
                ],
            )
            connection.executemany(
                "INSERT INTO imports(path, module) VALUES (?, ?)",
                [(path, module) for path, modules in imports.items() for module in modules],
            )
            connection.executemany(
                "INSERT INTO symbol_bodies(symbol_id, path, body) VALUES (?, ?, ?)",
                [
                    (symbol_id, symbol_id.split(":", 2)[1], body)
                    for symbol_id, body in (symbol_bodies or {}).items()
                ],
            )
            connection.executemany(
                "INSERT INTO source_bodies(path, body) VALUES (?, ?)",
                [(path, body) for path, body in (source_bodies or {}).items()],
            )
            if symbol_body_rows:
                connection.executemany(
                    "INSERT INTO symbol_bodies(symbol_id, path, body) VALUES (?, ?, ?)", symbol_body_rows
                )
            if source_body_rows:
                connection.executemany("INSERT INTO source_bodies(path, body) VALUES (?, ?)", source_body_rows)
            if symbol_fts_records:
                connection.executemany(
                    "INSERT INTO symbol_fts(symbol_id, path, name, qualified_name, code_tokens, own_body) VALUES (?, ?, ?, ?, ?, ?)",
                    symbol_fts_records,
                )
            if parse_artifact_rows:
                connection.executemany(
                    """INSERT INTO file_parse_artifacts(
                        path, sha256, parser_version, language, calls_json, inheritance_json, imports_json,
                        warnings_json, facts_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    parse_artifact_rows,
                )
            if reuse_text_from is not None and reuse_text_paths and not delta:
                _copy_text_rows(connection, reuse_text_from, set(reuse_text_paths))
            if symbol_ranks:
                connection.executemany(
                    "INSERT INTO symbol_rank(symbol_id, score, basis_json) VALUES (?, ?, ?)",
                    [(item[0], item[1], json.dumps(item[2])) for item in symbol_ranks],
                )
        with self.connection() as connection:
            # No VACUUM (M7): the file was just created, so it has no free pages to give back.
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.commit()
            connection.execute("PRAGMA optimize")

    def has_symbol_rank(self) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='symbol_rank'"
            ).fetchone()
            return row is not None

    def symbol_ranks(self) -> dict[str, tuple[float, list[str]]]:
        if not self.has_symbol_rank():
            return {}
        with self.connection() as connection:
            rows = connection.execute("SELECT symbol_id, score, basis_json FROM symbol_rank").fetchall()
        result: dict[str, tuple[float, list[str]]] = {}
        for row in rows:
            basis = json.loads(row["basis_json"]) if row["basis_json"] else []
            result[row["symbol_id"]] = (float(row["score"]), basis)
        return result

    def class_ancestors(self, class_symbol_id: str) -> list[tuple[str, str | None]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT parent_name, parent_symbol_id FROM class_hierarchy WHERE class_symbol_id = ?",
                (class_symbol_id,),
            ).fetchall()
        return [(row["parent_name"], row["parent_symbol_id"]) for row in rows]

    def all_class_hierarchies(self) -> dict[str, list[str]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT class_symbol_id, parent_name FROM class_hierarchy ORDER BY class_symbol_id"
            ).fetchall()
        res: dict[str, list[str]] = {}
        for row in rows:
            res.setdefault(row["class_symbol_id"], []).append(row["parent_name"])
        return res

    def external_stub(self, stub_id: int) -> ExternalStubRecord | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM external_stubs WHERE stub_id = ?", (stub_id,)).fetchone()
        return _external_stub_from_row(row) if row else None

    def external_stubs(self) -> list[ExternalStubRecord]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM external_stubs ORDER BY stub_id").fetchall()
        return [_external_stub_from_row(row) for row in rows]

    def metadata(self) -> dict[str, Any]:
        with self.connection() as connection:
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def files(self) -> list[FileRecord]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM files ORDER BY path").fetchall()
        return [_file_from_row(row) for row in rows]

    def file(self, path: str) -> FileRecord | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        return _file_from_row(row) if row else None

    def symbols(self, *, path: str | None = None) -> list[SymbolRecord]:
        sql = "SELECT * FROM symbols"
        params: tuple[object, ...] = ()
        if path is not None:
            sql += " WHERE path = ?"
            params = (path,)
        sql += " ORDER BY path, start_byte"
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_symbol_from_row(row) for row in rows]

    def find_symbols(self, pattern: str, *, kind: str | None = None, limit: int = 20) -> list[SymbolRecord]:
        where_clauses: list[str] = []
        params: list[object] = []

        if "*" in pattern or "?" in pattern:
            like_pattern = (
                pattern.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                .replace("*", "%")
                .replace("?", "_")
            )
        else:
            escaped = (
                pattern.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            like_pattern = f"%{escaped}%"

        where_clauses.append("(name LIKE ? ESCAPE '\\' OR qualified_name LIKE ? ESCAPE '\\')")
        params.extend([like_pattern, like_pattern])

        if kind == "method":
            where_clauses.append("(kind = 'method' OR (kind = 'function' AND qualified_name LIKE '%.%'))")
        elif kind:
            where_clauses.append("kind = ?")
            params.append(kind)

        clean_target = pattern.replace("*", "").replace("?", "").strip()
        where_sql = " AND ".join(where_clauses)
        test_path_sql = "CASE WHEN path LIKE 'tests/%' OR path LIKE 'evals/%' THEN 2 ELSE 1 END"

        if clean_target:
            order_sql = f"""
                CASE
                    WHEN name = ? THEN 1
                    WHEN lower(name) = lower(?) THEN 2
                    WHEN qualified_name = ? THEN 3
                    WHEN lower(qualified_name) = lower(?) THEN 4
                    WHEN substr(name, 1, ?) = ? THEN 5
                    WHEN lower(name) LIKE lower(?) || '%' ESCAPE '\\' THEN 6
                    WHEN substr(qualified_name, 1, ?) = ? THEN 7
                    WHEN lower(qualified_name) LIKE lower(?) || '%' ESCAPE '\\' THEN 8
                    ELSE 9
                END, {test_path_sql}, length(qualified_name), path, start_line
            """
            target_len = len(clean_target)
            clean_escaped = clean_target.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            order_params = [
                clean_target,
                clean_target,
                clean_target,
                clean_target,
                target_len,
                clean_target,
                clean_escaped,
                target_len,
                clean_target,
                clean_escaped,
            ]
            all_params = tuple(params + order_params + [limit])
        else:
            order_sql = f"{test_path_sql}, name, length(qualified_name), path, start_line"
            all_params = tuple(params + [limit])

        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM symbols WHERE {where_sql} ORDER BY {order_sql} LIMIT ?",
                all_params,
            ).fetchall()
        return [_symbol_from_row(row) for row in rows]

    def count_symbols(self, pattern: str, *, kind: str | None = None) -> int:
        where_clauses: list[str] = []
        params: list[object] = []

        if "*" in pattern or "?" in pattern:
            like_pattern = (
                pattern.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                .replace("*", "%")
                .replace("?", "_")
            )
        else:
            escaped = (
                pattern.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            like_pattern = f"%{escaped}%"

        where_clauses.append("(name LIKE ? ESCAPE '\\' OR qualified_name LIKE ? ESCAPE '\\')")
        params.extend([like_pattern, like_pattern])

        if kind == "method":
            where_clauses.append("(kind = 'method' OR (kind = 'function' AND qualified_name LIKE '%.%'))")
        elif kind:
            where_clauses.append("kind = ?")
            params.append(kind)

        where_sql = " AND ".join(where_clauses)
        with self.connection() as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM symbols WHERE {where_sql}", tuple(params)).fetchone()
        assert row is not None
        return int(row["count"])

    def symbol(self, symbol_id: str) -> SymbolRecord | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM symbols WHERE symbol_id = ?", (symbol_id,)).fetchone()
        return _symbol_from_row(row) if row else None

    def imports_for_path(self, path: str) -> list[str]:
        with self.connection() as connection:
            rows = connection.execute("SELECT module FROM imports WHERE path = ? ORDER BY module", (path,)).fetchall()
        return [str(row["module"]) for row in rows]

    def import_pairs(self) -> list[tuple[str, str]]:
        """All (path, module) import rows, ordered, for file-level graph construction."""
        with self.connection() as connection:
            rows = connection.execute("SELECT path, module FROM imports ORDER BY path, module").fetchall()
        return [(str(row["path"]), str(row["module"])) for row in rows]

    def importers_for_modules(self, modules: list[str]) -> list[str]:
        if not modules:
            return []
        placeholders = ",".join("?" for _ in modules)
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT path FROM imports WHERE module IN ({placeholders}) ORDER BY path",
                tuple(modules),
            ).fetchall()
        return [str(row["path"]) for row in rows]

    def import_count(self) -> int:
        with self.connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM imports").fetchone()
        assert row is not None
        return int(row["count"])

    def importer_count(self) -> int:
        with self.connection() as connection:
            row = connection.execute("SELECT COUNT(DISTINCT path) AS count FROM imports").fetchone()
        assert row is not None
        return int(row["count"])

    def body_match_ids(self, query: str) -> set[str]:
        try:
            with self.connection() as connection:
                rows = connection.execute(
                    "SELECT symbol_id FROM symbol_bodies WHERE body MATCH ?",
                    (query,),
                ).fetchall()
        except sqlite3.OperationalError as error:
            raise StoreError("body search index is unavailable; rebuild the repository index") from error
        return {str(row["symbol_id"]) for row in rows}

    def count_body_matches(self, query: str) -> int:
        try:
            with self.connection() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM symbol_bodies WHERE body MATCH ?",
                    (query,),
                ).fetchone()
        except sqlite3.OperationalError as error:
            raise StoreError("body search index is unavailable; rebuild the repository index") from error
        assert row is not None
        return int(row["count"])

    def search_body_matches(self, query: str, *, limit: int) -> list[dict[str, str]]:
        try:
            with self.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT symbol_id, path,
                           snippet(symbol_bodies, 2, '', '', '…', 24) AS snippet
                    FROM symbol_bodies
                    WHERE body MATCH ?
                    ORDER BY bm25(symbol_bodies), path, symbol_id
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
        except sqlite3.OperationalError as error:
            raise StoreError("body search index is unavailable; rebuild the repository index") from error
        return [
            {"symbol_id": str(row["symbol_id"]), "path": str(row["path"]), "snippet": str(row["snippet"])}
            for row in rows
        ]

    def count_source_matches(self, query: str) -> int:
        try:
            with self.connection() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM source_bodies WHERE body MATCH ?",
                    (query,),
                ).fetchone()
        except sqlite3.OperationalError as error:
            raise StoreError("body search index is unavailable; rebuild the repository index") from error
        assert row is not None
        return int(row["count"])

    def search_source_matches(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            with self.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT f.path, f.sha256, f.size, f.mtime_ns, f.language, f.parse_status, f.warnings_json,
                           snippet(source_bodies, 1, '', '', '…', 24) AS snippet
                    FROM source_bodies
                    JOIN files f ON source_bodies.path = f.path
                    WHERE source_bodies.body MATCH ?
                    ORDER BY bm25(source_bodies), f.path
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
        except sqlite3.OperationalError as error:
            raise StoreError("body search index is unavailable; rebuild the repository index") from error
        return [
            {
                "path": str(row["path"]),
                "snippet": str(row["snippet"]),
                "file_record": _file_from_row(row),
            }
            for row in rows
        ]

    def has_symbol_fts(self) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='symbol_fts'"
            ).fetchone()
            return row is not None

    def count_symbol_matches(self, query: str) -> int:
        try:
            with self.connection() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM symbol_fts WHERE symbol_fts MATCH ?",
                    (query,),
                ).fetchone()
        except sqlite3.OperationalError as error:
            raise StoreError("symbol search index is unavailable; rebuild the repository index") from error
        assert row is not None
        return int(row["count"])

    def search_symbol_matches(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            with self.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT f.symbol_id, f.path, f.name, f.qualified_name, f.code_tokens, f.own_body,
                           s.kind, s.signature,
                           COALESCE(s.start_line, 1) AS start_line,
                           COALESCE(s.end_line, 1) AS end_line,
                           fl.sha256, fl.size, fl.mtime_ns, fl.language, fl.parse_status, fl.warnings_json,
                           bm25(symbol_fts, 0, 0, 10.0, 6.0, 3.0, 1.0) AS score
                    FROM symbol_fts f
                    LEFT JOIN symbols s ON f.symbol_id = s.symbol_id
                    LEFT JOIN files fl ON f.path = fl.path
                    WHERE symbol_fts MATCH ?
                    ORDER BY bm25(symbol_fts, 0, 0, 10.0, 6.0, 3.0, 1.0), f.path, COALESCE(s.start_line, 1)
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
        except sqlite3.OperationalError as error:
            raise StoreError("symbol search index is unavailable; rebuild the repository index") from error
        results = []
        for row in rows:
            file_rec = None
            if row["sha256"] is not None:
                file_rec = FileRecord(
                    path=str(row["path"]),
                    sha256=str(row["sha256"]),
                    size=int(row["size"]),
                    mtime_ns=int(row["mtime_ns"]),
                    language=str(row["language"]) if row["language"] is not None else None,
                    parse_status=str(row["parse_status"]) if row["parse_status"] is not None else "parsed",
                    warnings=json.loads(row["warnings_json"]) if row["warnings_json"] else [],
                )
            results.append(
                {
                    "symbol_id": str(row["symbol_id"]),
                    "path": str(row["path"]),
                    "name": str(row["name"]),
                    "qualified_name": str(row["qualified_name"]),
                    "code_tokens": str(row["code_tokens"] or ""),
                    "own_body": str(row["own_body"] or ""),
                    "kind": str(row["kind"]) if row["kind"] is not None else "module",
                    "signature": str(row["signature"]) if row["signature"] is not None else "",
                    "start_line": int(row["start_line"]),
                    "end_line": int(row["end_line"]),
                    "score": float(row["score"]),
                    "file_record": file_rec,
                }
            )
        return results

    def symbols_for_paths(self, paths: list[str]) -> list[SymbolRecord]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM symbols WHERE path IN ({placeholders}) ORDER BY path, start_line",
                tuple(paths),
            ).fetchall()
        return [_symbol_from_row(row) for row in rows]

    def edges_from(self, symbol_id: str) -> list[EdgeRecord]:
        return self._edges("source_symbol_id = ?", (symbol_id,))

    def edges_to(self, symbol_id: str) -> list[EdgeRecord]:
        return self._edges("target_symbol_id = ?", (symbol_id,))

    def edges(self) -> list[EdgeRecord]:
        return self._edges("1 = 1", ())

    def _edges(self, where: str, params: tuple[object, ...]) -> list[EdgeRecord]:
        with self.connection() as connection:
            rows = connection.execute(f"SELECT * FROM edges WHERE {where} ORDER BY edge_id", params).fetchall()
        return [_edge_from_row(row) for row in rows]


def _clone_snapshot(source: Path, destination: Path) -> None:
    """Consistent copy of a snapshot; the source is only read.

    A finished snapshot has been checkpointed (no WAL content), so its file is complete and a plain file copy is
    enough; if a WAL with content is present the SQLite online backup produces the consistent copy instead."""
    wal = source.with_name(f"{source.name}-wal")
    try:
        wal_bytes = wal.stat().st_size if wal.exists() else 0
    except OSError:
        wal_bytes = 1
    if wal_bytes == 0:
        shutil.copyfile(source, destination)
        return
    old = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    new = sqlite3.connect(destination)
    try:
        old.backup(new)
    finally:
        new.close()
        old.close()


def snapshot_free_ratio(path: Path) -> float:
    """Fraction of a snapshot's pages that are free (bloat left behind by delta writes)."""
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        pages = connection.execute("PRAGMA page_count").fetchone()[0]
        free = connection.execute("PRAGMA freelist_count").fetchone()[0]
    finally:
        connection.close()
    return (free / pages) if pages else 0.0


def _copy_text_rows(connection: sqlite3.Connection, source: Path, paths: set[str]) -> None:
    """Copy full-text rows of ``paths`` from another snapshot, streaming, without materialising them."""
    uri = f"file:{source.as_posix()}?mode=ro"
    old = sqlite3.connect(uri, uri=True)
    try:
        def rows(sql: str, path_index: int):
            cursor = old.execute(sql)
            while True:
                batch = cursor.fetchmany(2000)
                if not batch:
                    return
                for row in batch:
                    if row[path_index] in paths:
                        yield row

        connection.executemany(
            "INSERT INTO symbol_bodies(symbol_id, path, body) VALUES (?, ?, ?)",
            rows("SELECT symbol_id, path, body FROM symbol_bodies", 1),
        )
        connection.executemany(
            "INSERT INTO source_bodies(path, body) VALUES (?, ?)",
            rows("SELECT path, body FROM source_bodies", 0),
        )
        connection.executemany(
            "INSERT INTO symbol_fts(symbol_id, path, name, qualified_name, code_tokens, own_body) VALUES (?, ?, ?, ?, ?, ?)",
            rows("SELECT symbol_id, path, name, qualified_name, code_tokens, own_body FROM symbol_fts", 1),
        )
    finally:
        old.close()


def _file_from_row(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        path=row["path"],
        sha256=row["sha256"],
        size=row["size"],
        mtime_ns=row["mtime_ns"],
        language=row["language"],
        parse_status=row["parse_status"],
        warnings=json.loads(row["warnings_json"]),
    )


def _symbol_from_row(row: sqlite3.Row) -> SymbolRecord:
    columns = row.keys()
    return SymbolRecord(
        symbol_id=row["symbol_id"],
        path=row["path"],
        name=row["name"],
        qualified_name=row["qualified_name"],
        kind=row["kind"],
        signature=row["signature"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        start_byte=row["start_byte"],
        end_byte=row["end_byte"],
        body_start_byte=row["body_start_byte"],
        body_end_byte=row["body_end_byte"],
        is_private=bool(row["is_private"]),
        roles=json.loads(row["roles_json"]) if "roles_json" in columns else [],
        role_evidence=(
            json.loads(row["role_evidence_json"])
            if "role_evidence_json" in columns
            else {}
        ),
    )


def _edge_from_row(row: sqlite3.Row) -> EdgeRecord:
    columns = row.keys()
    return EdgeRecord(
        source_symbol_id=row["source_symbol_id"],
        target_symbol_id=row["target_symbol_id"],
        target_name=row["target_name"],
        edge_kind=row["edge_kind"],
        status=row["status"],
        backend=row["backend"],
        confidence=row["confidence"],
        source_path=row["source_path"],
        source_line=row["source_line"],
        evidence=json.loads(row["evidence_json"]),
        target_stub_id=row["target_stub_id"] if "target_stub_id" in columns else None,
    )


def _external_stub_from_row(row: sqlite3.Row) -> ExternalStubRecord:
    return ExternalStubRecord(
        stub_id=row["stub_id"],
        package=row["package"],
        export_path=row["export_path"],
        member_name=row["member_name"],
        signature=row["signature"],
        doc_summary=row["doc_summary"],
    )

