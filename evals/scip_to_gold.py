"""Extract all call sites in repository using tree-sitter and match with SCIP occurrences (M14.1.1).

Scans AST of non-test source files for:
- C#: invocation_expression, object_creation_expression
- Java: method_invocation, object_creation_expression, explicit_constructor_invocation

Matches identifier position of callee against SCIP occurrences in <repo>.occ.jsonl.gz:
- internal target: symbol defined within the repository -> {path, def_line, scip_symbol}
- external: symbol not defined in repository -> "external"
- unlabelled: no occurrence in SCIP (e.g. inactive #if branch, unindexed code) -> filtered out

Outputs:
evals/oracle/<repo>.calls.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

from token_context_mcp.parse.treesitter import _load_language, _new_parser


_CSHARP_CALL_TYPES = {"invocation_expression", "object_creation_expression"}
_JAVA_CALL_TYPES = {"method_invocation", "object_creation_expression", "explicit_constructor_invocation"}


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    parts = p.split("/")
    return any(
        part in {"test", "tests", "test_data", "testing"}
        or part.endswith("tests")
        or part.endswith("test")
        for part in parts
    )


def _find_identifier_node(node: Any, language_name: str) -> Any | None:
    if language_name == "c_sharp":
        if node.type == "invocation_expression":
            expr = node.child_by_field_name("function") or node.child_by_field_name("expression")
            if expr:
                if expr.type == "member_access_expression":
                    return expr.child_by_field_name("name")
                elif expr.type == "identifier":
                    return expr
                elif expr.type == "generic_name":
                    return expr.child_by_field_name("name") or expr
        elif node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node:
                if type_node.type == "identifier":
                    return type_node
                elif type_node.type == "qualified_name":
                    return type_node.child_by_field_name("name")
                elif type_node.type == "generic_name":
                    return type_node.child_by_field_name("name") or type_node
    elif language_name == "java":
        if node.type == "method_invocation":
            return node.child_by_field_name("name")
        elif node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node:
                if type_node.type == "type_identifier":
                    return type_node
                elif type_node.type == "scoped_type_identifier":
                    return type_node.child_by_field_name("name")
                elif type_node.type == "generic_type":
                    # first child is usually type_identifier
                    for ch in type_node.children:
                        if ch.type in {"type_identifier", "scoped_type_identifier"}:
                            return ch
        elif node.type == "explicit_constructor_invocation":
            # this(...) or super(...)
            for ch in node.children:
                if ch.type in {"this", "super"}:
                    return ch
    return None


def extract_call_sites_from_tree(root: Any, raw: bytes, language_name: str) -> list[dict[str, Any]]:
    sites = []
    target_types = _CSHARP_CALL_TYPES if language_name == "c_sharp" else _JAVA_CALL_TYPES

    stack = [root]
    while stack:
        curr = stack.pop()
        if curr.type in target_types:
            id_node = _find_identifier_node(curr, language_name)
            if id_node:
                start_pt = id_node.start_point
                end_pt = id_node.end_point
                callee_name = raw[id_node.start_byte : id_node.end_byte].decode("utf-8", errors="replace")
                sites.append({
                    "call_type": curr.type,
                    "callee_name": callee_name,
                    "line": start_pt[0] + 1,  # 1-indexed line
                    "start_col": start_pt[1],
                    "end_col": end_pt[1],
                })
        for child in reversed(curr.children):
            stack.append(child)
    return sites


def load_occurrences_map(occ_path: Path) -> tuple[dict[tuple[str, int, int], dict[str, Any]], set[str], dict[str, tuple[str, int]]]:
    """Loads occurrences and definition symbols from <repo>.occ.jsonl.gz.

    Returns:
    - occ_map: (path, line, start_col) -> occ dict
    - def_symbols: set of symbols that have a definition occurrence in this repo
    - symbol_def_locations: symbol -> (path, def_line)
    """
    occ_map: dict[tuple[str, int, int], dict[str, Any]] = {}
    def_symbols: set[str] = set()
    symbol_def_locations: dict[str, tuple[str, int]] = {}

    if not occ_path.exists():
        return occ_map, def_symbols, symbol_def_locations

    with gzip.open(occ_path, "rt", encoding="utf-8") as f:
        for line_str in f:
            if not line_str.strip():
                continue
            data = json.loads(line_str)
            if data.get("_meta") == "symbols":
                continue
            p = data.get("path", "")
            for occ in data.get("occurrences", []):
                roles = occ.get("roles", 0)
                sym = occ.get("symbol", "")
                line = occ.get("line", 0) + 1  # SCIP 0-indexed to 1-indexed
                start_col = occ.get("start_col", 0)

                # Bit 0 (1) in SCIP roles is Definition
                if roles & 1:
                    def_symbols.add(sym)
                    if sym not in symbol_def_locations:
                        symbol_def_locations[sym] = (p, line)

                occ_map[(p, line, start_col)] = {
                    "symbol": sym,
                    "roles": roles,
                    "end_col": occ.get("end_col", 0),
                }

    return occ_map, def_symbols, symbol_def_locations


def build_oracle_calls(
    repo_root: Path,
    language_name: str,
    occ_path: Path,
    output_path: Path,
) -> dict[str, int]:
    occ_map, def_symbols, def_locs = load_occurrences_map(occ_path)
    lang = _load_language(language_name)
    parser = _new_parser(lang)

    ext = ".cs" if language_name == "c_sharp" else ".java"
    counts = {"internal": 0, "external": 0, "unlabelled": 0}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", encoding="utf-8") as out:
        for file_path in sorted(repo_root.rglob(f"*{ext}")):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(repo_root).as_posix()
            if is_test_path(rel_path):
                continue

            raw = file_path.read_bytes()
            tree = parser.parse(raw)
            if not tree.root_node:
                continue

            sites = extract_call_sites_from_tree(tree.root_node, raw, language_name)
            for site in sites:
                key = (rel_path, site["line"], site["start_col"])
                occ = occ_map.get(key)
                if not occ:
                    # check col +- 1 or search matching line
                    for (p, l, sc), o in occ_map.items():
                        if p == rel_path and l == site["line"] and abs(sc - site["start_col"]) <= 2:
                            occ = o
                            break

                record = {
                    "path": rel_path,
                    "line": site["line"],
                    "start_col": site["start_col"],
                    "callee_name": site["callee_name"],
                    "call_type": site["call_type"],
                }

                if not occ:
                    record["classification"] = "unlabelled"
                    counts["unlabelled"] += 1
                else:
                    sym = occ["symbol"]
                    if sym in def_symbols:
                        record["classification"] = "internal"
                        def_path, def_line = def_locs.get(sym, (rel_path, 0))
                        record["target"] = {
                            "path": def_path,
                            "def_line": def_line,
                            "scip_symbol": sym,
                        }
                        counts["internal"] += 1
                    else:
                        record["classification"] = "external"
                        record["scip_symbol"] = sym
                        counts["external"] += 1

                out.write(json.dumps(record, ensure_ascii=False) + "\n")

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract call sites and match with SCIP occurrences")
    parser.add_argument("--repo-root", type=Path, required=True, help="Path to repository root")
    parser.add_argument("--language", type=str, required=True, choices=["c_sharp", "java"], help="Target language")
    parser.add_argument("--occ", type=Path, required=True, help="Path to <repo>.occ.jsonl.gz")
    parser.add_argument("--output", type=Path, required=True, help="Output <repo>.calls.jsonl.gz path")
    args = parser.parse_args()

    counts = build_oracle_calls(args.repo_root, args.language, args.occ, args.output)
    print(f"Extraction completed: internal={counts['internal']}, external={counts['external']}, unlabelled={counts['unlabelled']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
