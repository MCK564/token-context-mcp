from __future__ import annotations

import re
from collections import defaultdict

from token_context_mcp.models import EdgeRecord, SymbolRecord

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][$\w]*\b")


def build_lexical_edges(
    symbols: list[SymbolRecord], source_by_path: dict[str, str], *, max_edges_per_symbol: int = 100
) -> list[EdgeRecord]:
    by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in symbols:
        by_name[symbol.name].append(symbol)
    edges: list[EdgeRecord] = []
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
            target, scope = _resolve_candidate(source, candidates)
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
                    confidence=0.55 if target else 0.2,
                    source_path=source.path,
                    source_line=line,
                    evidence=evidence,
                )
            )
            count += 1
    return _deduplicate(edges)


def _resolve_candidate(source: SymbolRecord, candidates: list[SymbolRecord]) -> tuple[SymbolRecord | None, str]:
    same_file = [candidate for candidate in candidates if candidate.path == source.path]
    if len(same_file) == 1:
        return same_file[0], "same_file"
    if len(same_file) > 1:
        return None, "same_file_ambiguous"

    source_package = source.path.rsplit("/", 1)[0]
    same_package = [
        candidate
        for candidate in candidates
        if candidate.path.rsplit("/", 1)[0] == source_package
    ]
    if len(same_package) == 1:
        return same_package[0], "same_package"
    if len(same_package) > 1:
        return None, "same_package_ambiguous"

    if len(candidates) == 1:
        return candidates[0], "global"
    return None, "global_ambiguous"


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
