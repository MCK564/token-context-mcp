from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from token_context_mcp.models import EdgeRecord, SymbolRecord

if TYPE_CHECKING:
    from token_context_mcp.parse.treesitter import CallRecord

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][$\w]*\b")


def build_lexical_edges(
    symbols: list[SymbolRecord],
    source_by_path: dict[str, str],
    *,
    max_edges_per_symbol: int = 100,
    calls_by_path: dict[str, list[CallRecord]] | None = None,
    imports_by_path: dict[str, list[str]] | None = None,
) -> list[EdgeRecord]:
    by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
    symbols_by_path: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in symbols:
        by_name[symbol.name].append(symbol)
        symbols_by_path[symbol.path].append(symbol)

    edges: list[EdgeRecord] = []
    imports_map = imports_by_path or {}

    if calls_by_path is not None:
        # Use AST-extracted calls for precise edge resolution
        for path, calls in calls_by_path.items():
            path_symbols = symbols_by_path.get(path, [])
            if not path_symbols:
                continue

            for call in calls:
                enclosing = [
                    s for s in path_symbols
                    if s.start_byte <= call.start_byte <= s.end_byte
                ]
                if not enclosing:
                    continue
                source = min(enclosing, key=lambda s: s.end_byte - s.start_byte)
                candidates = [c for c in by_name.get(call.name, []) if c.symbol_id != source.symbol_id]
                if not candidates:
                    continue

                target, scope, confidence = _resolve_candidate(
                    source, candidates, receiver=call.receiver, imports=imports_map.get(path, [])
                )
                status = "resolved" if target else "ambiguous"
                evidence = ["ast_call", f"scope:{scope}"]
                if call.receiver:
                    evidence.append(f"receiver:{call.receiver}")

                edges.append(
                    EdgeRecord(
                        source_symbol_id=source.symbol_id,
                        target_symbol_id=target.symbol_id if target else None,
                        target_name=call.name,
                        edge_kind="call",
                        status=status,
                        backend="lexical",
                        confidence=confidence,
                        source_path=source.path,
                        source_line=call.line,
                        evidence=evidence,
                    )
                )
        return _deduplicate(edges)

    # Fallback to regex identifier scanning (backward compatibility)
    for source in symbols:
        source_text = source_by_path.get(source.path, "")
        body = _slice_by_byte(source_text, source.start_byte, source.end_byte)
        count = 0
        for match in _IDENTIFIER_RE.finditer(body):
            if count >= max_edges_per_symbol:
                break
            name = match.group(0)
            candidates = [candidate for candidate in by_name.get(name, []) if candidate.symbol_id != source.symbol_id]
            if not candidates:
                continue
            line = source.start_line + body[: match.start()].count("\n")
            target, scope, confidence = _resolve_candidate(source, candidates, receiver=None, imports=imports_map.get(source.path, []))
            status = "resolved" if target else "ambiguous"
            edge_kind = "call" if body[match.end() :].lstrip().startswith("(") else "reference"
            evidence = ["identifier_match", f"scope:{scope}"]
            edges.append(
                EdgeRecord(
                    source_symbol_id=source.symbol_id,
                    target_symbol_id=target.symbol_id if target else None,
                    target_name=name,
                    edge_kind=edge_kind,
                    status=status,
                    backend="lexical",
                    confidence=confidence,
                    source_path=source.path,
                    source_line=line,
                    evidence=evidence,
                )
            )
            count += 1
    return _deduplicate(edges)


def _resolve_candidate(
    source: SymbolRecord,
    candidates: list[SymbolRecord],
    receiver: str | None = None,
    imports: list[str] | None = None,
) -> tuple[SymbolRecord | None, str, float]:
    imports_list = imports or []

    # 1. Receiver is self / this / cls -> resolve within class if possible
    if receiver in {"self", "this", "cls"}:
        if "." in source.qualified_name:
            class_prefix = source.qualified_name.rsplit(".", 1)[0]
            same_class = [
                c for c in candidates
                if c.path == source.path and c.qualified_name.startswith(f"{class_prefix}.")
            ]
            if len(same_class) == 1:
                return same_class[0], "same_class", 0.95
        # Fallback to same file
        same_file = [c for c in candidates if c.path == source.path]
        if len(same_file) == 1:
            return same_file[0], "same_file", 0.85
        if len(same_file) > 1:
            return None, "same_file_ambiguous", 0.20

    # 2. Receiver is a specific class or module identifier
    if receiver and receiver not in {"self", "this", "cls"}:
        # Match candidates with receiver in qualified_name (e.g., Receiver.method)
        receiver_matches = [
            c for c in candidates
            if c.qualified_name.endswith(f"{receiver}.{c.name}")
        ]
        if len(receiver_matches) == 1:
            return receiver_matches[0], "receiver_match", 0.90
        if len(receiver_matches) > 1:
            same_file_rec = [c for c in receiver_matches if c.path == source.path]
            if len(same_file_rec) == 1:
                return same_file_rec[0], "same_file", 0.90
            # Narrow with imports
            if imports_list:
                import_rec = [
                    c for c in receiver_matches
                    if any(imp.replace(".", "/") in c.path.replace("\\", "/") for imp in imports_list)
                ]
                if len(import_rec) == 1:
                    return import_rec[0], "import_match", 0.90
            return None, "receiver_ambiguous", 0.20

        # Receiver might be an imported module name
        matched_imports = [imp for imp in imports_list if receiver in imp.split(".")]
        if matched_imports:
            imp_cands = [
                c for c in candidates
                if any(imp.replace(".", "/") in c.path.replace("\\", "/") for imp in matched_imports)
            ]
            if len(imp_cands) == 1:
                return imp_cands[0], "import_module_match", 0.85
            if len(imp_cands) > 1:
                return None, "import_module_ambiguous", 0.20

    # 3. Direct candidate resolution: same_file -> imported -> same_package -> global
    same_file = [candidate for candidate in candidates if candidate.path == source.path]
    if len(same_file) == 1:
        return same_file[0], "same_file", 0.85
    if len(same_file) > 1:
        return None, "same_file_ambiguous", 0.20

    if imports_list:
        imported_cands = [
            c for c in candidates
            if any(imp.replace(".", "/") in c.path.replace("\\", "/") or imp.endswith(f".{c.name}") for imp in imports_list)
        ]
        if len(imported_cands) == 1:
            return imported_cands[0], "import_match", 0.85
        if len(imported_cands) > 1:
            return None, "import_ambiguous", 0.20

    source_package = source.path.rsplit("/", 1)[0]
    same_package = [
        candidate
        for candidate in candidates
        if candidate.path.rsplit("/", 1)[0] == source_package
    ]
    if len(same_package) == 1:
        return same_package[0], "same_package", 0.70
    if len(same_package) > 1:
        return None, "same_package_ambiguous", 0.20

    if len(candidates) == 1:
        return candidates[0], "global", 0.35
    return None, "global_ambiguous", 0.10


def _slice_by_byte(text: str, start_byte: int, end_byte: int) -> str:
    raw = text.encode("utf-8")
    return raw[start_byte:end_byte].decode("utf-8", errors="replace")


def _deduplicate(edges: list[EdgeRecord]) -> list[EdgeRecord]:
    seen: set[tuple[str, str | None, str, str]] = set()
    unique: list[EdgeRecord] = []
    for edge in edges:
        key = (edge.source_symbol_id, edge.target_symbol_id, edge.target_name, edge.edge_kind)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return unique
