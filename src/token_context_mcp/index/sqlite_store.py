from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from token_context_mcp.models import EdgeRecord, FileRecord, SymbolRecord


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
  is_private INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS symbols_path_idx ON symbols(path);
CREATE INDEX IF NOT EXISTS symbols_name_idx ON symbols(name);
CREATE TABLE IF NOT EXISTS edges (
  edge_id INTEGER PRIMARY KEY,
  source_symbol_id TEXT NOT NULL REFERENCES symbols(symbol_id),
  target_symbol_id TEXT REFERENCES symbols(symbol_id),
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
CREATE TABLE IF NOT EXISTS imports (
  path TEXT NOT NULL REFERENCES files(path),
  module TEXT NOT NULL,
  PRIMARY KEY(path, module)
);
"""


class StoreError(RuntimeError):
    pass


class SQLiteStore:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            uri = f"file:{self.path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            if not self.read_only:
                connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
    ) -> None:
        if self.read_only:
            raise StoreError("cannot write a read-only snapshot")
        self.initialize()
        with self.connection() as connection:
            for table in ("edges", "imports", "symbols", "files", "metadata"):
                connection.execute(f"DELETE FROM {table}")
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
                    start_byte, end_byte, body_start_byte, body_end_byte, is_private
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    )
                    for item in symbols
                ],
            )
            connection.executemany(
                """INSERT INTO edges(
                    source_symbol_id, target_symbol_id, target_name, edge_kind, status, backend,
                    confidence, source_path, source_line, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item.source_symbol_id,
                        item.target_symbol_id,
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
        with self.connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

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
        where = "(name LIKE ? ESCAPE '\\' OR qualified_name LIKE ? ESCAPE '\\')"
        escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params: list[object] = [f"%{escaped}%", f"%{escaped}%"]
        if kind:
            where += " AND kind = ?"
            params.append(kind)
        params.append(limit)
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM symbols WHERE {where} ORDER BY name, path LIMIT ?", tuple(params)
            ).fetchall()
        return [_symbol_from_row(row) for row in rows]

    def symbol(self, symbol_id: str) -> SymbolRecord | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM symbols WHERE symbol_id = ?", (symbol_id,)).fetchone()
        return _symbol_from_row(row) if row else None

    def imports_for_path(self, path: str) -> list[str]:
        with self.connection() as connection:
            rows = connection.execute("SELECT module FROM imports WHERE path = ? ORDER BY module", (path,)).fetchall()
        return [str(row["module"]) for row in rows]

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
    )


def _edge_from_row(row: sqlite3.Row) -> EdgeRecord:
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
    )
