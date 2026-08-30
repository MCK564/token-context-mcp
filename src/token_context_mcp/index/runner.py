from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import tomllib
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import pathspec

from token_context_mcp.constants import (
    DEFAULT_MAX_GRAPH_NODES,
    INDEX_SCHEMA_VERSION,
    SUPPORTED_EXTENSIONS,
)
from token_context_mcp.index.hashing import sha256_bytes
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.models import (
    EdgeRecord,
    FileRecord,
    RepositoryConfig,
    SymbolRecord,
)
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import ParseError, parse_source
from token_context_mcp.security.content_policy import is_hard_denied, is_probably_binary
from token_context_mcp.security.local_privacy import (
    secure_directory,
    secure_file,
    secure_sqlite_artifacts,
)
from token_context_mcp.security.path_policy import is_reparse_point, relative_posix


def database_path(index_directory: Path, repo_id: str) -> Path:
    return index_directory / f"{repo_id}.sqlite"


def manifest_path(index_directory: Path, repo_id: str) -> Path:
    return index_directory / f"{repo_id}.manifest.json"


def build_index(repository: RepositoryConfig, index_directory: Path, *, network_policy: str) -> dict[str, object]:
    secure_directory(index_directory)
    destination = database_path(index_directory, repository.repo_id)
    previous_files: dict[str, FileRecord] = {}
    previous_store: SQLiteStore | None = None
    if destination.exists():
        try:
            previous_store = SQLiteStore(destination, read_only=True)
            previous_metadata = previous_store.metadata()
            if previous_metadata.get("index_schema_version") == INDEX_SCHEMA_VERSION:
                previous_files = {item.path: item for item in previous_store.files()}
            else:
                # The old snapshot may not have role columns. Reparse it
                # instead of letting the reuse path deserialize a stale row.
                previous_store = None
        except (OSError, sqlite3.Error):
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
    declared_entry_points = _declared_entry_points(repository.root)
    symbols, entry_points = _assign_structural_roles(symbols, source_by_path, declared_entry_points)
    body_lengths = [
        max(1, symbol.end_byte - (symbol.body_start_byte or symbol.end_byte))
        for symbol in symbols
    ]
    median_symbol_body_bytes = round(median(body_lengths)) if body_lengths else 1
    max_edges_per_symbol = max(25, min(200, math.ceil(median_symbol_body_bytes / 10)))
    derived_limit_ceiling = max(30, min(100, math.ceil(len(symbols) / 10)))
    derived_impact_max_nodes = max(
        30, min(DEFAULT_MAX_GRAPH_NODES, math.ceil(math.sqrt(max(1, len(symbols))) * 3))
    )
    derived_defaults = {
        "max_edges_per_symbol": {
            "value": max_edges_per_symbol,
            "median_symbol_body_bytes": median_symbol_body_bytes,
            "formula": "ceil(median_symbol_body_bytes / 10), floor=25, cap=200",
        },
        "limit_ceiling": {
            "value": derived_limit_ceiling,
            "symbol_count": len(symbols),
            "formula": "ceil(symbol_count / 10), floor=30, cap=100",
        },
        "impact_max_nodes": {
            "value": derived_impact_max_nodes,
            "symbol_count": len(symbols),
            "formula": "ceil(3 * sqrt(symbol_count)), floor=30, cap=500",
        },
    }
    edges: list[EdgeRecord] = build_lexical_edges(
        symbols, source_by_path, max_edges_per_symbol=max_edges_per_symbol
    )
    symbol_bodies = {
        symbol.symbol_id: _search_text(_slice_source(source_by_path[symbol.path], symbol.start_byte, symbol.end_byte))
        for symbol in symbols
        if symbol.path in source_by_path
    }
    searchable_sources = {path: _search_text(source) for path, source in source_by_path.items()}
    index_run_id = _new_run_id()
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "index_schema_version": INDEX_SCHEMA_VERSION,
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
        "entry_points": entry_points,
        "role_counts": _role_counts(symbols),
        "derived_defaults": derived_defaults,
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
            symbol_bodies=symbol_bodies,
            source_bodies=searchable_sources,
        )
        _atomic_replace(temporary, destination)
        secure_sqlite_artifacts(destination)
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        manifest["artifact_sha256"] = sha256_bytes(destination.read_bytes())
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        temporary_manifest = manifest_path(index_directory, repository.repo_id).with_suffix(".tmp.json")
        temporary_manifest.write_text(manifest_json, encoding="utf-8", newline="\n")
        secure_file(temporary_manifest)
        temporary_manifest.replace(manifest_path(index_directory, repository.repo_id))
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _declared_entry_points(root: Path) -> list[tuple[str, str]]:
    path = root / "pyproject.toml"
    try:
        with path.open("rb") as handle:
            project = tomllib.load(handle).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return []
    if not isinstance(project, dict):
        return []
    entries: list[tuple[str, str]] = []
    scripts = project.get("scripts", {})
    if isinstance(scripts, dict):
        entries.extend(
            (f"{name} = {target}", str(target))
            for name, target in sorted(scripts.items())
            if isinstance(name, str) and isinstance(target, str)
        )
    groups = project.get("entry-points", {})
    if isinstance(groups, dict):
        for group, values in sorted(groups.items()):
            if not isinstance(group, str) or not isinstance(values, dict):
                continue
            entries.extend(
                (f"{group}.{name} = {target}", str(target))
                for name, target in sorted(values.items())
                if isinstance(name, str) and isinstance(target, str)
            )
    return entries


def _assign_structural_roles(
    symbols: list[SymbolRecord],
    source_by_path: dict[str, str],
    declared_entry_points: list[tuple[str, str]],
) -> tuple[list[SymbolRecord], list[dict[str, object]]]:
    protocols = {
        symbol.name: symbol
        for symbol in symbols
        if "protocol_definition" in symbol.roles
    }
    protocol_methods: dict[str, set[str]] = {}
    protocol_signatures: dict[str, dict[str, str]] = {}
    for protocol_name, protocol in protocols.items():
        prefix = f"{protocol.qualified_name}."
        method_symbols = [
            symbol
            for symbol in symbols
            if symbol.qualified_name.startswith(prefix) and "." not in symbol.qualified_name[len(prefix) :]
        ]
        protocol_methods[protocol_name] = {symbol.name for symbol in method_symbols}
        protocol_signatures[protocol_name] = {
            symbol.name: symbol.signature for symbol in method_symbols
        }
    registry_wired_names = {
        match.group(1)
        for source in source_by_path.values()
        for match in re.finditer(r"\bregister\s*\([^)]*,\s*([A-Z][A-Za-z0-9_]*)\s*\)", source)
    }

    updated: list[SymbolRecord] = []
    for symbol in symbols:
        # Recompute inferred roles on every index run. This prevents a stale
        # role from a previous implementation of the heuristic surviving a
        # content-reuse pass.
        roles = [role for role in symbol.roles if role in {"protocol_definition", "module_entry_point"}]
        evidence = {role: symbol.role_evidence[role] for role in roles if role in symbol.role_evidence}
        if symbol.kind == "class" and "protocol_definition" not in roles:
            methods = {
                item.name: item
                for item in symbols
                if item.qualified_name.startswith(f"{symbol.qualified_name}.")
                and "." not in item.qualified_name[len(symbol.qualified_name) + 1 :]
                and item.kind in {"method", "function"}
            }
            for protocol_name, required_methods in protocol_methods.items():
                if not required_methods or not required_methods.issubset(methods):
                    continue
                if not all(
                    _compatible_method_signature(
                        protocol_signatures[protocol_name][method_name], methods[method_name].signature
                    )
                    for method_name in required_methods
                ):
                    continue
                if not _looks_like_protocol_implementation(symbol, protocol_name):
                    continue
                _add_role(
                    roles,
                    evidence,
                    "protocol_implementation",
                    f"implements {protocol_name} via methods: {', '.join(sorted(required_methods))}",
                )
                break

        signature_and_body = f"{symbol.signature} {source_by_path.get(symbol.path, '')}"
        if (
            symbol.kind in {"function", "method"}
            and symbol.name in {"register", "get_frontend"}
            and any(protocol_name in signature_and_body for protocol_name in protocols)
        ):
            _add_role(roles, evidence, "registry_wiring", "protocol-typed registry function")
        if symbol.kind == "class" and symbol.name in registry_wired_names:
            _add_role(roles, evidence, "registry_wiring", "registered implementation referenced by register(..., ClassName)")
        updated.append(replace(symbol, roles=roles, role_evidence=evidence))

    entry_points: list[dict[str, object]] = []
    for declared, target in declared_entry_points:
        resolved = _resolve_entry_point(updated, target)
        if resolved is not None:
            for index, symbol in enumerate(updated):
                if symbol.symbol_id == resolved.symbol_id:
                    roles = list(symbol.roles)
                    evidence = dict(symbol.role_evidence)
                    _add_role(roles, evidence, "declared_entry_point", declared)
                    updated[index] = replace(symbol, roles=roles, role_evidence=evidence)
                    break
        entry_points.append({"declared": declared, "resolved": resolved is not None})
    return updated, entry_points


def _looks_like_protocol_implementation(symbol: SymbolRecord, protocol_name: str) -> bool:
    lowered_name = symbol.name.lower()
    lowered_path = symbol.path.lower()
    if "frontend" in protocol_name.lower():
        return "frontend" in lowered_name or "frontend" in lowered_path
    if "engine" in protocol_name.lower():
        return "engine" in lowered_name or "ocr" in lowered_path
    return True


def _compatible_method_signature(protocol_signature: str, candidate_signature: str) -> bool:
    protocol_return = _return_annotation(protocol_signature)
    candidate_return = _return_annotation(candidate_signature)
    return bool(protocol_return and protocol_return == candidate_return and "self" in candidate_signature)


def _return_annotation(signature: str) -> str:
    if "->" not in signature:
        return ""
    return signature.split("->", 1)[1].strip().rstrip(":")


def _resolve_entry_point(symbols: list[SymbolRecord], target: str) -> SymbolRecord | None:
    module, separator, attribute = target.partition(":")
    if not separator:
        return None
    attribute = attribute.split(" ", 1)[0].strip()
    if not module or not attribute:
        return None
    matches = [
        symbol
        for symbol in symbols
        if module in _module_candidates(symbol.path)
        and (symbol.qualified_name == attribute or symbol.name == attribute)
    ]
    return matches[0] if len(matches) == 1 else None


def _module_candidates(path: str) -> set[str]:
    normalized = path.replace("\\", "/").strip("/")
    filename = normalized.rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    parts = (
        [part for part in normalized[: -len(filename)].split("/") if part]
        if len(filename) < len(normalized)
        else []
    )
    parts.append(stem)
    candidates = {".".join(part for part in parts if part)}
    if parts and parts[0] == "src":
        candidates.add(".".join(parts[1:]))
    if stem == "__init__":
        package = parts[:-1]
        candidates.add(".".join(package))
        if package and package[0] == "src":
            candidates.add(".".join(package[1:]))
    return {candidate for candidate in candidates if candidate}


def _add_role(roles: list[str], evidence: dict[str, str], role: str, reason: str) -> None:
    if role not in roles:
        roles.append(role)
    evidence[role] = reason


def _role_counts(symbols: list[SymbolRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for symbol in symbols:
        for role in symbol.roles:
            counts[role] = counts.get(role, 0) + 1
    return dict(sorted(counts.items()))


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


def _slice_source(source: str, start_byte: int, end_byte: int) -> str:
    raw = source.encode("utf-8")
    return raw[start_byte:end_byte].decode("utf-8", errors="replace")


def _search_text(source: str) -> str:
    # FTS5 tokenizes OcrResult and PaddleOCR as one token, while a source
    # search for ocr should behave like the substring-oriented lookup users
    # expect from rg. Keep the original text and add camel-case boundaries
    # for indexing; callers reconstruct snippets from source.
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", source)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", separated)
    return f"{source}\n{separated}"


def _new_run_id() -> str:
    return f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
