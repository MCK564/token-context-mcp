from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pathspec

from token_context_mcp.constants import SUPPORTED_EXTENSIONS
from token_context_mcp.index.hashing import sha256_bytes
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.models import EdgeRecord, FileRecord, RepositoryConfig, SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import ParseError, parse_source
from token_context_mcp.security.content_policy import is_hard_denied, is_probably_binary
from token_context_mcp.security.path_policy import is_reparse_point, relative_posix


def database_path(index_directory: Path, repo_id: str) -> Path:
    return index_directory / f"{repo_id}.sqlite"


def manifest_path(index_directory: Path, repo_id: str) -> Path:
    return index_directory / f"{repo_id}.manifest.json"


def build_index(repository: RepositoryConfig, index_directory: Path, *, network_policy: str) -> dict[str, object]:
    index_directory.mkdir(parents=True, exist_ok=True)
    destination = database_path(index_directory, repository.repo_id)
    previous_files: dict[str, FileRecord] = {}
    previous_store: SQLiteStore | None = None
    if destination.exists():
        try:
            previous_store = SQLiteStore(destination, read_only=True)
            previous_files = {item.path: item for item in previous_store.files()}
        except Exception:
            previous_store = None
            previous_files = {}
    files: list[FileRecord] = []
    symbols: list[SymbolRecord] = []
    imports: dict[str, list[str]] = {}
    source_by_path: dict[str, str] = {}
    warnings: list[str] = []
    files_seen = 0
    files_skipped = 0
    files_reused = 0
    files_reparsed = 0
    for file_path in _inventory(repository):
        files_seen += 1
        relative = relative_posix(repository.root, file_path)
        if is_hard_denied(relative):
            files_skipped += 1
            continue
        try:
            raw = file_path.read_bytes()
        except OSError as error:
            files_skipped += 1
            warnings.append(f"read_error:{relative}:{type(error).__name__}")
            continue
        if len(raw) > repository.max_file_bytes or is_probably_binary(raw):
            files_skipped += 1
            continue
        language = SUPPORTED_EXTENSIONS.get(file_path.suffix.lower())
        stat = file_path.stat()
        file_warnings: list[str] = []
        parse_status = "unsupported" if language is None else "parsed"
        files.append(
            FileRecord(
                path=relative,
                sha256=sha256_bytes(raw),
                size=len(raw),
                mtime_ns=stat.st_mtime_ns,
                language=language,
                parse_status=parse_status,
                warnings=file_warnings,
            )
        )
        if language is None:
            continue
        previous = previous_files.get(relative)
        source_by_path[relative] = raw.decode("utf-8", errors="replace")
        if (
            previous_store is not None
            and previous is not None
            and previous.sha256 == files[-1].sha256
            and previous.parse_status.startswith("parsed")
        ):
            files[-1] = FileRecord(
                path=relative,
                sha256=files[-1].sha256,
                size=files[-1].size,
                mtime_ns=files[-1].mtime_ns,
                language=language,
                parse_status=previous.parse_status,
                warnings=previous.warnings,
            )
            symbols.extend(previous_store.symbols(path=relative))
            imports[relative] = previous_store.imports_for_path(relative)
            files_reused += 1
            continue
        files_reparsed += 1
        try:
            parsed = parse_source(relative, raw, language)
        except ParseError as error:
            files[-1] = FileRecord(
                path=relative,
                sha256=sha256_bytes(raw),
                size=len(raw),
                mtime_ns=stat.st_mtime_ns,
                language=language,
                parse_status="parse_error",
                warnings=[type(error).__name__],
            )
            warnings.append(f"parse_error:{relative}")
            continue
        files[-1] = FileRecord(
            path=relative,
            sha256=sha256_bytes(raw),
            size=len(raw),
            mtime_ns=stat.st_mtime_ns,
            language=language,
            parse_status="parsed_with_warnings" if parsed.warnings else "parsed",
            warnings=parsed.warnings,
        )
        symbols.extend(parsed.symbols)
        imports[relative] = parsed.imports
    edges: list[EdgeRecord] = build_lexical_edges(symbols, source_by_path)
    index_run_id = _new_run_id()
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "repo_id": repository.repo_id,
        "repo_root_id": sha256_bytes(str(repository.root).encode()),
        "commit_sha": None,
        "index_run_id": index_run_id,
        "indexer_version": "0.1.0",
        "parser_versions": {"backend": "tree-sitter", "languages": sorted({item.language for item in files if item.language})},
        "generated_at": datetime.now(UTC).isoformat(),
        "files_seen": files_seen,
        "files_indexed": len(files),
        "files_skipped": files_skipped,
        "files_reused": files_reused,
        "files_reparsed": files_reparsed,
        "symbols_indexed": len(symbols),
        "edges_indexed": len(edges),
        "warnings": warnings,
        "network_policy": network_policy,
        "network_policy_status": "declared_only; enforce at OS/container boundary",
    }
    temporary = destination.with_suffix(f".tmp-{uuid.uuid4().hex}.sqlite")
    try:
        SQLiteStore(temporary).write_snapshot(
            metadata=manifest,
            files=files,
            symbols=symbols,
            edges=edges,
            imports=imports,
        )
        _atomic_replace(temporary, destination)
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        manifest["artifact_sha256"] = sha256_bytes(destination.read_bytes())
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        temporary_manifest = manifest_path(index_directory, repository.repo_id).with_suffix(".tmp.json")
        temporary_manifest.write_text(manifest_json, encoding="utf-8", newline="\n")
        temporary_manifest.replace(manifest_path(index_directory, repository.repo_id))
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _inventory(repository: RepositoryConfig) -> list[Path]:
    gitignore = _gitignore_spec(repository.root)
    found: list[Path] = []
    for current_root, directories, filenames in os.walk(repository.root, topdown=True, followlinks=False):
        current = Path(current_root)
        safe_directories: list[str] = []
        for directory in directories:
            path = current / directory
            relative = relative_posix(repository.root, path)
            if is_reparse_point(path) or is_hard_denied(relative) or gitignore.match_file(relative + "/"):
                continue
            safe_directories.append(directory)
        directories[:] = safe_directories
        for filename in filenames:
            path = current / filename
            relative = relative_posix(repository.root, path)
            if len(found) >= repository.max_files:
                raise RuntimeError("repository exceeds max_files")
            if is_reparse_point(path) or is_hard_denied(relative) or gitignore.match_file(relative):
                continue
            if path.is_file():
                found.append(path)
    return sorted(found)


def _gitignore_spec(root: Path) -> pathspec.GitIgnoreSpec:
    ignore_file = root / ".gitignore"
    if not ignore_file.is_file():
        return pathspec.GitIgnoreSpec.from_lines([])
    try:
        return pathspec.GitIgnoreSpec.from_lines(ignore_file.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return pathspec.GitIgnoreSpec.from_lines([])


def _atomic_replace(temporary: Path, destination: Path) -> None:
    for suffix in ("-wal", "-shm"):
        (destination.parent / f"{destination.name}{suffix}").unlink(missing_ok=True)
    shutil.move(str(temporary), str(destination))


def _new_run_id() -> str:
    return f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
