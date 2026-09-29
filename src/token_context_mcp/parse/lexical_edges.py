from __future__ import annotations

import re
import time
from collections import defaultdict
from functools import lru_cache
from typing import TYPE_CHECKING

from token_context_mcp.models import EdgeRecord, ExternalStubRecord, SymbolRecord

if TYPE_CHECKING:
    from token_context_mcp.parse.treesitter import CallRecord

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][$\w]*\b")

# Per-file wall-clock budget of edge resolution (a guard against pathological files).  Time-based, hence
# machine-dependent: evals/index_equivalence.py sets it to infinity so that "incremental == full" (I1) is exact.
FILE_CIRCUIT_BREAKER_SECONDS = 0.030

# Calibrated confidence scores per scope based on evals/out/m4/edge_eval_final.json
# Values rounded down to step 0.05. Scopes with n < 10 retain conservative default values.
SCOPE_CONFIDENCE: dict[str, float] = {
    "same_class": 0.95,
    "cha_inherited": 0.90,
    "attr_type": 0.95,
    "attr_type_inherited": 0.90,
    # M6.0: self.x = <typed constructor/method parameter>. Provisional; not yet
    # calibrated against gold (n < 10 at introduction) — recalibrate per the M4
    # methodology once evals/out/m6/edge_eval_attr_param.json has enough samples.
    "attr_param": 0.90,
    "exact_receiver_type": 0.95,
    "same_file": 0.90,
    "receiver_match": 0.90,
    "import_match": 0.90,
    "import_module_match": 0.75,
    "same_package": 0.75,
    "global": 0.40,
    "virtual_stub": 0.90,
}



def _extract_repo_return_types(symbols: list[SymbolRecord]) -> dict[str, str]:
    repo_return_types: dict[str, str] = {}
    for s in symbols:
        if s.kind in {"function", "method"} and s.signature:
            m = re.search(r"->\s*([A-Za-z_][A-Za-z0-9_]*)", s.signature)
            if m:
                ret = m.group(1)
                if ret not in _BUILTIN_RECEIVERS and ret not in {
                    "None", "Any", "void", "bool", "int", "str", "float",
                    "dict", "list", "set", "tuple", "bytes",
                }:
                    if s.name not in repo_return_types:
                        repo_return_types[s.name] = ret
                    elif repo_return_types[s.name] != ret:
                        repo_return_types[s.name] = ""
    return repo_return_types


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
    repo_return_types = _extract_repo_return_types(symbols)

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
                if not file_timed_out and (time.perf_counter() - file_start > FILE_CIRCUIT_BREAKER_SECONDS):
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

                effective_receiver_type = getattr(call, "receiver_type", None)
                if effective_receiver_type is None and getattr(call, "assigned_from_fn", None):
                    fn_src = call.assigned_from_fn
                    if fn_src and repo_return_types.get(fn_src):
                        effective_receiver_type = repo_return_types[fn_src]

                # Virtual External Stub Resolution
                matched_stub = None
                if external_stubs and call.name in stubs_by_member:
                    matched_stub = _resolve_external_stub(
                        source=source,
                        name=call.name,
                        receiver=call.receiver,
                        receiver_type=effective_receiver_type,
                        imports=imports_map.get(path, []),
                        stubs=stubs_by_member[call.name],
                        class_hierarchy=class_hierarchy,
                    )

                if matched_stub:
                    evidence = ["ast_call", "virtual_stub", f"stub:{matched_stub.package}.{matched_stub.export_path}.{matched_stub.member_name}"]
                    if call.receiver:
                        evidence.append(f"receiver:{call.receiver}")
                    if effective_receiver_type:
                        evidence.append(f"type:{effective_receiver_type}")
                    edges.append(
                        EdgeRecord(
                            source_symbol_id=source.symbol_id,
                            target_symbol_id=None,
                            target_stub_id=matched_stub.stub_id,
                            target_name=call.name,
                            edge_kind="call",
                            status="resolved",
                            backend="virtual_stub",
                            confidence=SCOPE_CONFIDENCE.get("virtual_stub", 0.90),
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
                    receiver_type=effective_receiver_type,
                    receiver_type_source=getattr(call, "receiver_type_source", None),
                    is_tainted=getattr(call, "is_tainted", False),
                    imports=imports_map.get(path, []),
                    class_hierarchy=class_hierarchy,
                )
                status = "resolved" if target else "ambiguous"
                evidence = ["ast_call", f"scope:{scope}"]
                if call.receiver:
                    evidence.append(f"receiver:{call.receiver}")
                if effective_receiver_type:
                    evidence.append(f"type:{effective_receiver_type}")
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


_BUILTIN_RECEIVERS = {
    "os", "sys", "re", "json", "time", "math", "uuid", "shutil", "pathlib", "logging",
    "logger", "log", "tomllib", "hashlib", "sqlite3", "pathspec", "pytest", "io",
    "dict", "list", "set", "tuple", "str", "bytes", "bytearray",
    "raw", "os.environ", "payload", "manifest", "usage", "agent", "topic",
    "i", "d", "data", "resp", "response", "params", "args", "kwargs", "settings",
}

_GENERIC_METHOD_NAMES = {
    "get", "set", "run", "close", "save", "load", "update", "read", "write",
    "execute", "process", "format", "render", "parse", "connect", "handle",
    "start", "stop", "reset", "clear", "build", "create", "delete", "send",
    "items", "keys", "values", "pop", "append", "extend", "strip", "split", "join",
    "search", "match", "sub", "findall", "finditer",
}


@lru_cache(maxsize=65536)
def _path_segments(path_str: str) -> list[str]:
    # cached (M7): called once per (import, candidate) pair, i.e. up to millions of times per index run;
    # the returned list is shared and must not be mutated by callers.
    p = path_str.replace("\\", "/")
    filename = p.rsplit("/", 1)[-1]
    if "." in filename:
        p = p[: -(len(filename) - filename.rfind("."))]
    return [s for s in p.split("/") if s]


@lru_cache(maxsize=16384)
def _import_parts(imp: str) -> tuple[str | None, list[str] | None, list[str]]:
    """(member name, module segments of ``a.b.Name``, segments of the whole import); shared, read-only."""
    member_part: str | None = None
    mod_segs: list[str] | None = None
    if "." in imp:
        mod_part, member_part = imp.rsplit(".", 1)
        mod_segs = [s for s in mod_part.replace(".", "/").split("/") if s]
    imp_segs = [s for s in imp.replace(".", "/").split("/") if s]
    return member_part, mod_segs, imp_segs


def _import_matches_candidate(imp: str, candidate: SymbolRecord) -> bool:
    """Check if an import string accurately matches a candidate symbol's module or path."""
    if not imp:
        return False

    cand_segs = _path_segments(candidate.path)
    if not cand_segs:
        return False

    # 1. from a.b import CandidateName -> imp is "a.b.CandidateName"
    member_part, mod_segs, imp_segs = _import_parts(imp)
    if mod_segs is not None:
        if member_part == candidate.name:
            if len(cand_segs) >= len(mod_segs) and cand_segs[-len(mod_segs) :] == mod_segs:
                return True
    elif imp == candidate.name:
        return True

    # 2. Module import matches candidate file path exactly (as segment suffix)
    if not imp_segs:
        return False

    # Check exact segment suffix match
    if len(cand_segs) >= len(imp_segs) and cand_segs[-len(imp_segs) :] == imp_segs:
        return True

    # Check package __init__
    if cand_segs[-1] == "__init__":
        pkg_segs = cand_segs[:-1]
        if len(pkg_segs) >= len(imp_segs) and pkg_segs[-len(imp_segs) :] == imp_segs:
            return True

    return False


def _resolve_candidate(
    source: SymbolRecord,
    candidates: list[SymbolRecord],
    receiver: str | None = None,
    receiver_type: str | None = None,
    receiver_type_source: str | None = None,
    is_tainted: bool = False,
    imports: list[str] | None = None,
    class_hierarchy: dict[str, list[str]] | None = None,
) -> tuple[SymbolRecord | None, str, float]:
    imports_list = imports or []

    # Defensive Heuristic: Tainted variable (reassigned >= 2 times or assigned in branch)
    if is_tainted:
        return None, "tainted_poly_receiver", 0.10

    # Fast skip for known built-in / standard library receivers when calling generic methods
    if receiver:
        rec_clean = receiver.strip()
        if rec_clean in _BUILTIN_RECEIVERS or (receiver_type and receiver_type in _BUILTIN_RECEIVERS):
            # Check if this receiver is an explicitly imported internal module
            has_internal_import = any(_import_matches_candidate(imp, c) for imp in imports_list for c in candidates if c.path != source.path)
            if not has_internal_import:
                return None, "builtin_receiver_skipped", 0.10

    # 1. Receiver is self / this / cls -> resolve within class if possible
    if receiver in {"self", "this", "cls"}:
        if "." in source.qualified_name:
            class_prefix = source.qualified_name.rsplit(".", 1)[0]
            same_class = [
                c for c in candidates
                if c.path == source.path and c.qualified_name.startswith(f"{class_prefix}.")
            ]
            if len(same_class) == 1:
                return same_class[0], "same_class", SCOPE_CONFIDENCE.get("same_class", 0.95)

            # Class Hierarchy Analysis (CHA) lookup for inherited method
            if class_hierarchy:
                ancestors = _get_ancestors(class_prefix, class_hierarchy)
                for ancestor in ancestors:
                    ancestor_matches = [
                        c for c in candidates
                        if c.qualified_name == f"{ancestor}.{c.name}"
                        or c.qualified_name.startswith(f"{ancestor}.")
                        or c.qualified_name.endswith(f".{ancestor}.{c.name}")
                    ]
                    if len(ancestor_matches) == 1:
                        return ancestor_matches[0], "cha_inherited", SCOPE_CONFIDENCE.get("cha_inherited", 0.90)
                    if len(ancestor_matches) > 1:
                        return None, "cha_ambiguous", 0.10

        # Fallback to same file
        same_file = [c for c in candidates if c.path == source.path]
        if len(same_file) == 1:
            return same_file[0], "same_file", SCOPE_CONFIDENCE.get("same_file", 0.85)
        if len(same_file) > 1:
            return None, "same_file_ambiguous", 0.10

    # 1b. Receiver is an instance attribute (self.x, this.x, cls.x)
    if receiver and any(receiver.startswith(prefix) for prefix in ("self.", "this.", "cls.")):
        if receiver_type and receiver_type not in _BUILTIN_RECEIVERS:
            # M6.0: an attribute type inferred from a typed constructor/method parameter
            # (self.x = <typed param>) is tracked under its own scope so its precision can
            # be calibrated independently of the pre-existing attr_type sources
            # (annotated assignment / constructor call).
            attr_scope = "attr_param" if receiver_type_source == "attr_param" else "attr_type"
            type_matches = [
                c for c in candidates
                if c.qualified_name == f"{receiver_type}.{c.name}"
                or c.qualified_name.startswith(f"{receiver_type}.")
                or c.qualified_name.endswith(f".{receiver_type}.{c.name}")
            ]
            if len(type_matches) == 1:
                return type_matches[0], attr_scope, SCOPE_CONFIDENCE.get(attr_scope, 0.90)
            if len(type_matches) > 1:
                same_file_type = [c for c in type_matches if c.path == source.path]
                if len(same_file_type) == 1:
                    return same_file_type[0], attr_scope, SCOPE_CONFIDENCE.get(attr_scope, 0.90)
                return None, "attr_type_ambiguous", 0.10

            # Try CHA on receiver_type
            if class_hierarchy:
                ancestors = _get_ancestors(receiver_type, class_hierarchy)
                for ancestor in ancestors:
                    ancestor_matches = [
                        c for c in candidates
                        if c.qualified_name == f"{ancestor}.{c.name}"
                        or c.qualified_name.startswith(f"{ancestor}.")
                        or c.qualified_name.endswith(f".{ancestor}.{c.name}")
                    ]
                    if len(ancestor_matches) == 1:
                        return ancestor_matches[0], "attr_type_inherited", SCOPE_CONFIDENCE.get("attr_type_inherited", 0.90)
            return None, "attr_type_unmatched", 0.10

        # Receiver was an instance attribute but receiver_type could not be resolved:
        # DO NOT fall back to global or generic methods!
        return None, "unresolved_receiver", 0.10

    # 2. Inferred receiver type from parameter type hint or single-assignment
    if receiver_type and receiver_type not in _BUILTIN_RECEIVERS:
        type_matches = [
            c for c in candidates
            if c.qualified_name == f"{receiver_type}.{c.name}"
            or c.qualified_name.startswith(f"{receiver_type}.")
            or c.qualified_name.endswith(f".{receiver_type}.{c.name}")
        ]
        if len(type_matches) == 1:
            return type_matches[0], "exact_receiver_type", SCOPE_CONFIDENCE.get("exact_receiver_type", 0.90)
        if len(type_matches) > 1:
            same_file_type = [c for c in type_matches if c.path == source.path]
            if len(same_file_type) == 1:
                return same_file_type[0], "exact_receiver_type", SCOPE_CONFIDENCE.get("exact_receiver_type", 0.90)
            return None, "receiver_type_ambiguous", 0.10

        # Try CHA on receiver_type
        if class_hierarchy:
            ancestors = _get_ancestors(receiver_type, class_hierarchy)
            for ancestor in ancestors:
                ancestor_matches = [
                    c for c in candidates
                    if c.qualified_name == f"{ancestor}.{c.name}"
                    or c.qualified_name.startswith(f"{ancestor}.")
                    or c.qualified_name.endswith(f".{ancestor}.{c.name}")
                ]
                if len(ancestor_matches) == 1:
                    return ancestor_matches[0], "cha_inherited", SCOPE_CONFIDENCE.get("cha_inherited", 0.90)

    # 3. Receiver is an explicit identifier (not self/cls/this)
    if receiver and receiver not in {"self", "this", "cls"}:
        # Match static class or module calls (e.g., Worker.build)
        receiver_matches = [
            c for c in candidates
            if c.qualified_name == f"{receiver}.{c.name}"
            or c.qualified_name.startswith(f"{receiver}.")
            or c.qualified_name.endswith(f".{receiver}.{c.name}")
        ]
        if len(receiver_matches) == 1:
            return receiver_matches[0], "receiver_match", SCOPE_CONFIDENCE.get("receiver_match", 0.90)
        if len(receiver_matches) > 1:
            same_file_rec = [c for c in receiver_matches if c.path == source.path]
            if len(same_file_rec) == 1:
                return same_file_rec[0], "same_file", SCOPE_CONFIDENCE.get("same_file", 0.85)
            if imports_list:
                import_rec = [
                    c for c in receiver_matches
                    if any(_import_matches_candidate(imp, c) for imp in imports_list)
                ]
                if len(import_rec) == 1:
                    return import_rec[0], "import_match", SCOPE_CONFIDENCE.get("import_match", 0.85)
            return None, "receiver_ambiguous", 0.10

        # Receiver might be an imported module name
        matched_imports = [imp for imp in imports_list if receiver in imp.split(".")]
        if matched_imports:
            imp_cands = [
                c for c in candidates
                if any(_import_matches_candidate(imp, c) for imp in matched_imports)
            ]
            if len(imp_cands) == 1:
                return imp_cands[0], "import_module_match", SCOPE_CONFIDENCE.get("import_module_match", 0.75)
            if len(imp_cands) > 1:
                return None, "import_module_ambiguous", 0.10

        # Check if candidate is a method of an imported/same-file class and receiver name matches class name:
        # e.g., receiver="store" matches class="SQLiteStore" or "MemoryStore" (when imported)
        if imports_list or any(c.path == source.path for c in candidates):
            imported_class_matches = []
            for c in candidates:
                if "." in c.qualified_name:
                    cls_name = c.qualified_name.rsplit(".", 1)[0].rsplit(".", 1)[-1]
                    is_available = any(
                        imp == cls_name or imp.endswith(f".{cls_name}") or _import_matches_candidate(imp, c)
                        for imp in imports_list
                    ) or (c.path == source.path)
                    if is_available:
                        rec_clean = receiver.lower().replace("self.", "")
                        cls_clean = cls_name.lower()
                        # Match when variable name is a meaningful substring of class name
                        if rec_clean and (rec_clean in cls_clean or cls_clean in rec_clean):
                            if len(rec_clean) >= 3 and rec_clean not in _BUILTIN_RECEIVERS:
                                imported_class_matches.append(c)

            if len(imported_class_matches) == 1:
                return imported_class_matches[0], "exact_receiver_type", SCOPE_CONFIDENCE.get("exact_receiver_type", 0.85)
            if len(imported_class_matches) > 1:
                return None, "receiver_type_ambiguous", 0.10

        # Receiver was explicit but could not be matched:
        # DO NOT fall back to global search for a method on an unknown receiver!
        return None, "unresolved_receiver", 0.10

    # 4. Direct candidate resolution: same_file -> imported -> same_package -> global
    # (Only for free function calls, direct identifier invocations without receiver)
    same_file = [candidate for candidate in candidates if candidate.path == source.path]
    if len(same_file) == 1:
        return same_file[0], "same_file", SCOPE_CONFIDENCE.get("same_file", 0.85)
    if len(same_file) > 1:
        return None, "same_file_ambiguous", 0.10

    if imports_list:
        imported_cands = [
            c for c in candidates
            if any(_import_matches_candidate(imp, c) for imp in imports_list)
        ]
        if len(imported_cands) == 1:
            return imported_cands[0], "import_match", SCOPE_CONFIDENCE.get("import_match", 0.85)
        if len(imported_cands) > 1:
            return None, "import_ambiguous", 0.10

    source_package = source.path.rsplit("/", 1)[0]
    same_package = [
        candidate
        for candidate in candidates
        if candidate.path.rsplit("/", 1)[0] == source_package
    ]
    if len(same_package) == 1:
        if same_package[0].name not in _GENERIC_METHOD_NAMES:
            return same_package[0], "same_package", SCOPE_CONFIDENCE.get("same_package", 0.75)
    if len(same_package) > 1:
        return None, "same_package_ambiguous", 0.10

    # Restrict global fallback:
    # 1. Never fallback for generic method names (get, set, run, etc.)
    # 2. Never fallback for class methods (must be top-level function or class)
    if len(candidates) == 1:
        cand = candidates[0]
        if cand.name not in _GENERIC_METHOD_NAMES:
            is_class_method = ("." in cand.qualified_name) and (cand.kind in {"method", "function"})
            if not is_class_method:
                return cand, "global", SCOPE_CONFIDENCE.get("global", 0.40)

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

