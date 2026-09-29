"""Gather the raw material for a context packet (M6.2).

Everything here reads the cached graph and at most one source file (the target's); the result is a
:class:`~token_context_mcp.retrieve.packet.PacketInputs` that :func:`build_context_packet` turns into
the budgeted, deterministic packet.  Kept apart from ``service.py`` so the service stays focused on the
single-purpose retrieval tools.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from token_context_mcp.models import SymbolRecord
from token_context_mcp.retrieve.expansion import edge_is_traversable
from token_context_mcp.retrieve.packet import (
    CALLEE_MIN_CONFIDENCE,
    CALLER_MIN_CONFIDENCE,
    Neighbor,
    PacketInputs,
    path_group,
)
from token_context_mcp.security.content_policy import redact_text
from token_context_mcp.security.path_policy import PathPolicyError, safe_relative_path

if TYPE_CHECKING:  # pragma: no cover
    from token_context_mcp.retrieve.service import RetrievalService

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IMPORT_STOP = frozenset({"import", "from", "as", "type", "export", "default", "require"})
_DOC_STARTS = ('"""', "'''", 'r"""', "r'''", "/**", "///", "//!")


def _graph_index(graph: object) -> tuple[dict[tuple[str, str], SymbolRecord], dict[str, list[SymbolRecord]]]:
    """``(path, qualified_name) -> symbol`` and ``path -> symbols by start line`` (memoised on the graph)."""
    cached = graph.__dict__.get("_packet_index")  # type: ignore[attr-defined]
    if cached is not None:
        return cached
    by_qn: dict[tuple[str, str], SymbolRecord] = {}
    by_path: dict[str, list[SymbolRecord]] = {}
    for sym in graph.symbols:  # type: ignore[attr-defined]
        by_qn.setdefault((sym.path, sym.qualified_name), sym)
        by_path.setdefault(sym.path, []).append(sym)
    for items in by_path.values():
        items.sort(key=lambda s: (s.start_line, s.end_line, s.symbol_id))
    graph.__dict__["_packet_index"] = (by_qn, by_path)  # type: ignore[attr-defined]
    return by_qn, by_path


def _one_line(text: str) -> str:
    return " ".join(part.strip() for part in text.splitlines() if part.strip())


def _direct_children(cls: SymbolRecord, by_path: dict[str, list[SymbolRecord]]) -> list[SymbolRecord]:
    prefix = cls.qualified_name + "."
    out = []
    for sym in by_path.get(cls.path, []):
        if sym.symbol_id == cls.symbol_id:
            continue
        if not (cls.start_line <= sym.start_line and sym.end_line <= cls.end_line):
            continue
        rest = sym.qualified_name[len(prefix):] if sym.qualified_name.startswith(prefix) else None
        if rest and "." not in rest:
            out.append(sym)
    return out


def _bound_names(line: str) -> set[str]:
    return {w for w in _WORD_RE.findall(line) if w not in _IMPORT_STOP}


def gather_packet_inputs(service: "RetrievalService", repo_id: str, *, symbol_id: str) -> PacketInputs:
    from token_context_mcp.retrieve.service import (  # local import: service imports this module lazily
        RetrievalError,
        _compact_declaration,
        _compact_symbol_ref,
        _source_bytes,
        _source_import_lines,
    )

    repository, store, metadata = service._repository_store(repo_id)
    index_run_id = str(metadata.get("index_run_id", ""))
    graph = service._graph_cache.get_graph(repository.repo_id, index_run_id, store)
    canonical = service._resolve_symbol_id(store, symbol_id, graph=graph)
    target = graph.get_symbol(canonical) if canonical else None
    if target is None:
        raise RetrievalError("unknown symbol_id")
    by_qn, by_path = _graph_index(graph)
    root = repository.root
    allow_symlinks = repository.allow_symlinks
    file_records = graph.file_records
    warnings: list[str] = []

    fresh: dict[str, bool] = {}

    def is_fresh(path: str) -> bool:
        if path not in fresh:
            record = file_records.get(path) or store.file(path)
            if record is None:
                fresh[path] = False
            else:
                state, sha = service._freshness_cache.path_state(root, record, allow_symlinks=allow_symlinks)
                fresh[path] = state == "fresh" and sha == record.sha256
        return fresh[path]

    def signature_of(sym: SymbolRecord) -> str | None:
        if not is_fresh(sym.path):
            if "stale_content_unavailable" not in warnings:
                warnings.append("stale_content_unavailable")
            return None
        chosen = sym
        if sym.kind == "class":  # a constructor call is described by __init__, not by the class header
            init = by_qn.get((sym.path, sym.qualified_name + ".__init__"))
            if init is not None:
                chosen = init
        return _one_line(chosen.signature) or None

    def neighbor(sym: SymbolRecord, relation: str, confidence: float | None) -> Neighbor:
        return Neighbor(
            ref=_compact_symbol_ref(sym.symbol_id),
            path=sym.path,
            line=sym.start_line,
            decl=_compact_declaration(sym),
            signature=signature_of(sym),
            confidence=confidence,
            relation=relation,
        )

    # ---- edges -------------------------------------------------------------------------
    raw_out = graph.out_edges.get(target.symbol_id, [])
    raw_in = graph.in_edges.get(target.symbol_id, [])
    callee_best: dict[str, float] = {}
    callee_first_line: dict[str, tuple[int, str]] = {}
    call_lines: set[int] = set()
    retained = 0
    for edge in raw_out:
        if edge.target_symbol_id == target.symbol_id or not edge_is_traversable(edge, CALLEE_MIN_CONFIDENCE):
            continue
        if graph.get_symbol(edge.target_symbol_id) is None:  # type: ignore[arg-type]
            continue
        retained += 1
        call_lines.add(edge.source_line)
        conf = float(edge.confidence)  # type: ignore[arg-type]
        tid = edge.target_symbol_id  # type: ignore[assignment]
        callee_best[tid] = max(callee_best.get(tid, 0.0), conf)  # type: ignore[index]
        callee_first_line[tid] = min(callee_first_line.get(tid, (edge.source_line, edge.source_path)), (edge.source_line, edge.source_path))  # type: ignore[index]
    caller_best: dict[str, float] = {}
    for edge in raw_in:
        if edge.source_symbol_id == target.symbol_id or not edge_is_traversable(edge, CALLER_MIN_CONFIDENCE):
            continue
        if graph.get_symbol(edge.source_symbol_id) is None:
            continue
        retained += 1
        conf = float(edge.confidence)  # type: ignore[arg-type]
        caller_best[edge.source_symbol_id] = max(caller_best.get(edge.source_symbol_id, 0.0), conf)

    callee_syms = [(graph.get_symbol(i), c) for i, c in callee_best.items()]
    # callees: order of first appearance in the target body (M6.2 table row 2), then a stable tiebreak
    callee_syms.sort(key=lambda p: (callee_first_line[p[0].symbol_id][0], -p[1], p[0].path, p[0].start_line, p[0].symbol_id))  # type: ignore[union-attr]
    callers_syms = [(graph.get_symbol(i), c) for i, c in caller_best.items()]
    ranks = graph.global_ranks

    def rank_of(sym_id: str) -> float:
        value = ranks.get(sym_id)
        return float(value[0]) if value else 0.0

    # callers: regular code, then evals/, then tests/; inside a group by global rank, path, line
    callers_syms.sort(
        key=lambda p: (path_group(p[0].path), -rank_of(p[0].symbol_id), p[0].path, p[0].start_line, p[0].symbol_id)  # type: ignore[union-attr]
    )
    callees = tuple(neighbor(s, "callee", c) for s, c in callee_syms)  # type: ignore[arg-type]
    callers = tuple(neighbor(s, "caller", c) for s, c in callers_syms)  # type: ignore[arg-type]

    # ---- target body -------------------------------------------------------------------
    source_lines: tuple[str, ...] | None = None
    signature_line_count = 1
    docstring_line: int | None = None
    imports: list[str] = []
    skeleton: tuple[tuple[int, int, str], ...] = ()
    target_text = ""
    record = file_records.get(target.path) or store.file(target.path)
    if record is None or not is_fresh(target.path):
        warnings.append("stale_content_unavailable")
    else:
        try:
            path = safe_relative_path(root, target.path, allow_symlinks=allow_symlinks)
            source = path.read_bytes().decode("utf-8", errors="replace")
        except (PathPolicyError, OSError):
            source = None
            warnings.append("stale_content_unavailable")
        if source is not None:
            span, _redacted = redact_text(_source_bytes(source, target.start_byte, target.end_byte))
            body_lines = span.replace("\r\n", "\n").rstrip().split("\n")
            target_text = "\n".join(body_lines)
            if target.kind != "class":
                source_lines = tuple(body_lines)
                if target.body_start_byte and target.body_start_byte > target.start_byte:
                    head = _source_bytes(source, target.start_byte, target.body_start_byte).rstrip()
                    signature_line_count = max(1, head.count("\n") + 1)
                else:
                    signature_line_count = max(1, (target.signature or "").count("\n") + 1)
                signature_line_count = min(signature_line_count, len(source_lines))
                for offset in range(signature_line_count, len(source_lines)):
                    stripped = source_lines[offset].strip()
                    if not stripped:
                        continue
                    if stripped.startswith(_DOC_STARTS):
                        docstring_line = target.start_line + offset
                    break
            for _number, text in _source_import_lines(source):
                stripped = text.strip()
                if stripped.startswith("from __future__"):
                    continue
                names = _bound_names(stripped)
                body_words = set(_WORD_RE.findall(target_text))
                if names & body_words:
                    imports.append(stripped)

    if target.kind == "class":
        entries: list[tuple[int, int, str]] = [(target.start_line, target.start_line, _one_line(target.signature))]
        for child in _direct_children(target, by_path):
            entries.append((child.start_line, child.end_line, _one_line(child.signature)))
        skeleton = tuple(entries) if len(entries) > 1 or entries[0][2] else ()

    # ---- class siblings ----------------------------------------------------------------
    class_methods: tuple[Neighbor, ...] = ()
    if target.kind != "class" and "." in target.qualified_name:
        parent = by_qn.get((target.path, target.qualified_name.rsplit(".", 1)[0]))
        if parent is not None and parent.kind == "class":
            class_methods = tuple(
                neighbor(child, "method", None)
                for child in _direct_children(parent, by_path)
                if child.symbol_id != target.symbol_id
            )

    # ---- file fingerprints -------------------------------------------------------------
    paths = {target.path}
    paths.update(n.path for n in callees)
    paths.update(n.path for n in callers)
    paths.update(n.path for n in class_methods)
    file_sha = {p: file_records[p].sha256[:12] for p in paths if p in file_records}

    return PacketInputs(
        target_ref=_compact_symbol_ref(target.symbol_id),
        target_symbol_id=target.symbol_id,
        path=target.path,
        qualified_name=target.qualified_name,
        kind=target.kind,
        start_line=target.start_line,
        end_line=target.end_line,
        source_lines=source_lines,
        signature_line_count=signature_line_count,
        docstring_line=docstring_line,
        call_lines=tuple(sorted(call_lines)),
        skeleton=skeleton,
        callees=callees,
        callers=callers,
        imports=tuple(dict.fromkeys(imports)),
        class_methods=class_methods,
        file_sha=file_sha,
        warnings=tuple(warnings),
        raw_edge_count=len(raw_out) + len(raw_in),
        retained_edge_count=retained,
    )
