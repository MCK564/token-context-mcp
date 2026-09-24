from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from token_context_mcp.models import EdgeRecord, ExternalStubRecord, SymbolRecord

if TYPE_CHECKING:
    from token_context_mcp.parse.treesitter import CallRecord

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][$\w]*\b")


def _get_ancestors(cls_name: str, inheritance_map: dict[str, list[str]] | None) -> list[str]:
    if not inheritance_map or not cls_name:
        return []
    short_name = cls_name.rsplit(".", 1)[-1]
    parents = inheritance_map.get(cls_name) or inheritance_map.get(short_name) or []
    ancestors: list[str] = []
    queue = list(parents)
    visited = set(queue)
    while queue:
        curr = queue.pop(0)
        ancestors.append(curr)
        curr_short = curr.rsplit(".", 1)[-1]
        next_parents = inheritance_map.get(curr) or inheritance_map.get(curr_short) or []
        for p in next_parents:
            if p not in visited:
                visited.add(p)
                queue.append(p)
    return ancestors


def build_lexical_edges(
    symbols: list[SymbolRecord],
    source_by_path: dict[str, str],
    *,
    max_edges_per_symbol: int = 100,
    calls_by_path: dict[str, list[CallRecord]] | None = None,
    imports_by_path: dict[str, list[str]] | None = None,
    class_hierarchy: dict[str, list[str]] | None = None,
    external_stubs: list[ExternalStubRecord] | None = None,
) -> list[EdgeRecord]:
    by_name: dict[str, list[SymbolRecord]] = defaultdict(list)
    symbols_by_path: dict[str, list[SymbolRecord]] = defaultdict(list)
    for symbol in symbols:
        by_name[symbol.name].append(symbol)
        symbols_by_path[symbol.path].append(symbol)

    stubs_by_member: dict[str, list[ExternalStubRecord]] = defaultdict(list)
    if external_stubs:
        for stub in external_stubs:
            stubs_by_member[stub.member_name].append(stub)

    edges: list[EdgeRecord] = []
    imports_map = imports_by_path or {}

    if calls_by_path is not None:
        # Use AST-extracted calls for precise edge resolution
        for path, calls in calls_by_path.items():
            path_symbols = symbols_by_path.get(path, [])
            if not path_symbols:
                continue

            sorted_symbols = sorted(path_symbols, key=lambda s: (s.start_byte, -s.end_byte))
            file_start = time.perf_counter()
            file_timed_out = False

            for call in calls:
                enclosing = [
                    s for s in sorted_symbols
                    if s.start_byte <= call.start_byte <= s.end_byte
                ]
                if not enclosing:
                    continue
                source = min(enclosing, key=lambda s: s.end_byte - s.start_byte)

                # 30ms circuit breaker per file
                if not file_timed_out and (time.perf_counter() - file_start > 0.030):
                    file_timed_out = True

                if file_timed_out:
                    edges.append(
                        EdgeRecord(
                            source_symbol_id=source.symbol_id,
                            target_symbol_id=None,
                            target_name=call.name,
                            edge_kind="call",
                            status="ambiguous",
                            backend="lexical",
                            confidence=0.10,
                            source_path=source.path,
                            source_line=call.line,
                            evidence=["ast_call", "circuit_breaker_timeout"],
                        )
                    )
                    continue

                candidates = [c for c in by_name.get(call.name, []) if c.symbol_id != source.symbol_id]

                # Virtual External Stub Resolution
                matched_stub = None
                if external_stubs and call.name in stubs_by_member:
                    matched_stub = _resolve_external_stub(
                        source=source,
                        name=call.name,
                        receiver=call.receiver,
                        receiver_type=getattr(call, "receiver_type", None),
                        imports=imports_map.get(path, []),
                        stubs=stubs_by_member[call.name],
                        class_hierarchy=class_hierarchy,
                    )

                if matched_stub:
                    evidence = ["ast_call", "virtual_stub", f"stub:{matched_stub.package}.{matched_stub.export_path}.{matched_stub.member_name}"]
                    if call.receiver:
                        evidence.append(f"receiver:{call.receiver}")
                    if getattr(call, "receiver_type", None):
                        evidence.append(f"type:{call.receiver_type}")
                    edges.append(
                        EdgeRecord(
                            source_symbol_id=source.symbol_id,
                            target_symbol_id=None,
                            target_stub_id=matched_stub.stub_id,
                            target_name=call.name,
                            edge_kind="call",
                            status="resolved",
                            backend="virtual_stub",
                            confidence=0.90,
                            source_path=source.path,
                            source_line=call.line,
                            evidence=evidence,
                        )
                    )
                    continue

                if not candidates:
                    continue

                target, scope, confidence = _resolve_candidate(
                    source,
                    candidates,
                    receiver=call.receiver,
                    receiver_type=getattr(call, "receiver_type", None),
                    is_tainted=getattr(call, "is_tainted", False),
                    imports=imports_map.get(path, []),
                    class_hierarchy=class_hierarchy,
                )
                status = "resolved" if target else "ambiguous"
                evidence = ["ast_call", f"scope:{scope}"]
                if call.receiver:
                    evidence.append(f"receiver:{call.receiver}")
                if getattr(call, "receiver_type", None):
                    evidence.append(f"type:{call.receiver_type}")
                if getattr(call, "is_tainted", False):
                    evidence.append("tainted_poly_receiver")

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
            target, scope, confidence = _resolve_candidate(
                source,
                candidates,
                receiver=None,
                imports=imports_map.get(source.path, []),
                class_hierarchy=class_hierarchy,
            )
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
    receiver_type: str | None = None,
    is_tainted: bool = False,
    imports: list[str] | None = None,
    class_hierarchy: dict[str, list[str]] | None = None,
) -> tuple[SymbolRecord | None, str, float]:
    imports_list = imports or []

    # Defensive Heuristic: Tainted variable (reassigned >= 2 times or assigned in branch)
    # Immediately downgrade to ambiguous 0.10 to prevent false positive edges
    if is_tainted:
        return None, "tainted_poly_receiver", 0.10

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

            # Class Hierarchy Analysis (CHA) lookup for inherited method
            if class_hierarchy:
                ancestors = _get_ancestors(class_prefix, class_hierarchy)
                for ancestor in ancestors:
                    ancestor_matches = [
                        c for c in candidates
                        if c.qualified_name.startswith(f"{ancestor}.") or c.qualified_name.endswith(f"{ancestor}.{c.name}")
                    ]
                    if len(ancestor_matches) == 1:
                        return ancestor_matches[0], "cha_inherited", 0.90
                    if len(ancestor_matches) > 1:
                        return None, "cha_ambiguous", 0.10

        # Fallback to same file
        same_file = [c for c in candidates if c.path == source.path]
        if len(same_file) == 1:
            return same_file[0], "same_file", 0.85
        if len(same_file) > 1:
            return None, "same_file_ambiguous", 0.10

    # 2. Inferred receiver type from parameter type hint or single-assignment
    if receiver_type:
        type_matches = [
            c for c in candidates
            if c.qualified_name.startswith(f"{receiver_type}.") or c.qualified_name.endswith(f"{receiver_type}.{c.name}")
        ]
        if len(type_matches) == 1:
            return type_matches[0], "exact_receiver_type", 0.90
        if len(type_matches) > 1:
            # Narrow with same file or imports if multiple matches
            same_file_type = [c for c in type_matches if c.path == source.path]
            if len(same_file_type) == 1:
                return same_file_type[0], "exact_receiver_type", 0.90
            return None, "receiver_type_ambiguous", 0.10

        # Try CHA on receiver_type
        if class_hierarchy:
            ancestors = _get_ancestors(receiver_type, class_hierarchy)
            for ancestor in ancestors:
                ancestor_matches = [
                    c for c in candidates
                    if c.qualified_name.startswith(f"{ancestor}.") or c.qualified_name.endswith(f"{ancestor}.{c.name}")
                ]
                if len(ancestor_matches) == 1:
                    return ancestor_matches[0], "cha_inherited", 0.90

    # 3. Receiver is an explicit identifier (not self/cls/this)
    if receiver and receiver not in {"self", "this", "cls"}:
        # Match static class or module calls (e.g., Worker.build)
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
            return None, "receiver_ambiguous", 0.10

        # Receiver might be an imported module name
        matched_imports = [imp for imp in imports_list if receiver in imp.split(".")]
        if matched_imports:
            imp_cands = [
                c for c in candidates
                if any(imp.replace(".", "/") in c.path.replace("\\", "/") for imp in matched_imports)
            ]
            if len(imp_cands) == 1:
                return imp_cands[0], "import_module_match", 0.75
            if len(imp_cands) > 1:
                return None, "import_module_ambiguous", 0.10

    # 4. Direct candidate resolution: same_file -> imported -> same_package -> global
    same_file = [candidate for candidate in candidates if candidate.path == source.path]
    if len(same_file) == 1:
        return same_file[0], "same_file", 0.85
    if len(same_file) > 1:
        return None, "same_file_ambiguous", 0.10

    if imports_list:
        imported_cands = [
            c for c in candidates
            if any(imp.replace(".", "/") in c.path.replace("\\", "/") or imp.endswith(f".{c.name}") for imp in imports_list)
        ]
        if len(imported_cands) == 1:
            return imported_cands[0], "import_match", 0.85
        if len(imported_cands) > 1:
            return None, "import_ambiguous", 0.10

    source_package = source.path.rsplit("/", 1)[0]
    same_package = [
        candidate
        for candidate in candidates
        if candidate.path.rsplit("/", 1)[0] == source_package
    ]
    if len(same_package) == 1:
        return same_package[0], "same_package", 0.75
    if len(same_package) > 1:
        return None, "same_package_ambiguous", 0.10

    if len(candidates) == 1:
        return candidates[0], "global", 0.40
    return None, "global_ambiguous", 0.10


def _slice_by_byte(text: str, start_byte: int, end_byte: int) -> str:
    raw = text.encode("utf-8")
    return raw[start_byte:end_byte].decode("utf-8", errors="replace")


def _deduplicate(edges: list[EdgeRecord]) -> list[EdgeRecord]:
    seen: set[tuple[str, str | None, int | None, str, str]] = set()
    unique: list[EdgeRecord] = []
    for edge in edges:
        key = (edge.source_symbol_id, edge.target_symbol_id, edge.target_stub_id, edge.target_name, edge.edge_kind)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return unique


def _resolve_external_stub(
    source: SymbolRecord,
    name: str,
    receiver: str | None,
    receiver_type: str | None,
    imports: list[str],
    stubs: list[ExternalStubRecord],
    class_hierarchy: dict[str, list[str]] | None = None,
) -> ExternalStubRecord | None:
    if not stubs:
        return None

    # 1. Receiver matches package name or module name (e.g. requests.get, pytest.raises)
    if receiver and receiver not in {"self", "this", "cls"}:
        rec_matches = [
            s for s in stubs
            if s.package == receiver
            or s.export_path == receiver
            or f"{s.package}.{s.export_path}".startswith(f"{receiver}.")
        ]
        if len(rec_matches) == 1:
            return rec_matches[0]

    # 2. Receiver is self / this / cls (e.g. self.assertEqual in unittest.TestCase)
    if receiver in {"self", "this", "cls"}:
        if "." in source.qualified_name:
            class_prefix = source.qualified_name.rsplit(".", 1)[0]
            ancestors = [class_prefix]
            if class_hierarchy:
                ancestors.extend(_get_ancestors(class_prefix, class_hierarchy))

            for s in stubs:
                for anc in ancestors:
                    anc_short = anc.rsplit(".", 1)[-1]
                    if anc_short == s.export_path or anc == s.export_path:
                        return s
                    if s.package == "unittest" and ("TestCase" in anc_short or anc_short.startswith("Test")):
                        if any(imp.startswith("unittest") for imp in imports):
                            return s

    # 3. Receiver type matches export_path (e.g. model.model_dump where receiver_type is BaseModel or inherits BaseModel)
    if receiver_type:
        type_ancestors = [receiver_type]
        if class_hierarchy:
            type_ancestors.extend(_get_ancestors(receiver_type, class_hierarchy))
        for s in stubs:
            for t_anc in type_ancestors:
                t_short = t_anc.rsplit(".", 1)[-1]
                if t_short == s.export_path or t_anc == s.export_path:
                    return s

    # 4. Direct call without receiver, or receiver matches package (e.g. raises(...) from pytest)
    if receiver is None or receiver in {s.package for s in stubs}:
        imported_stubs = [
            s for s in stubs
            if any(
                imp == s.package
                or imp == f"{s.package}.{s.export_path}"
                or imp == f"{s.package}.{s.member_name}"
                or imp.endswith(f".{s.member_name}")
                for imp in imports
            )
        ]
        if len(imported_stubs) == 1:
            return imported_stubs[0]

    return None

