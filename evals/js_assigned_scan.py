"""K1 measurement: how many JavaScript "assigned" methods does the index hold? (M12.6.4)

An independent AST scan (tree-sitter, no use of the indexer's extraction code) lists every method the
patterns of ``docs/SYMBOL_NAMING.md`` define; the index is then asked whether each one is a symbol.

Scan patterns (statement level, ``X`` an identifier declared at module level unless noted):

* ``X.prototype.m = function|arrow``               -> ``X.m``
* ``X.prototype = { m() {}, n: function () {} }``  -> ``X.m``, ``X.n``
* ``Object.defineProperty(X.prototype, 'p', {get(){}})`` and ``Object.defineProperties(X.prototype, {p: {get(){}}})`` -> ``X.p``
* ``X.m = function|arrow``                         -> ``X.m`` (module-level statements only)
* ``this.m = function|arrow`` inside ``function X() {}`` -> ``X.m``
* ``exports.m = …`` / ``module.exports.m = …``     -> ``m``;  ``module.exports = { m() {} }`` -> ``m``
* chained assignments ``a.x = b.y = function`` count once per left-hand side (reported separately as ``chained``)

Outputs recall (scan symbols found in the index with the same path and qualified name), the missing list by
pattern, and a random sample of indexed symbols that were NOT produced by an ordinary declaration, each checked
against the source line (``wrong`` = the sampled symbol is not backed by an assignment / pair / definition).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from tree_sitter import Language, Parser

FUNCTION_TYPES = {"function_expression", "arrow_function", "generator_function", "function"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage"}
SPECIAL = {"this", "module", "exports", "window", "global", "globalThis", "process", "console", "document"}


def _parser() -> Parser:
    import tree_sitter_javascript as tsjs

    return Parser(Language(tsjs.language()))


def _text(node: Any, raw: bytes) -> str:
    return raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace") if node is not None else ""


def _is_test(path: str) -> bool:
    parts = path.lower().split("/")
    name = parts[-1]
    return any(p in {"test", "tests", "__tests__", "spec", "specs"} for p in parts[:-1]) or ".test." in name or ".spec." in name


def _function_value(node: Any) -> bool:
    return node is not None and node.type in FUNCTION_TYPES


def _rhs_chain(assign: Any) -> tuple[list[Any], Any]:
    """Return (all left-hand sides of a chained assignment, final value)."""
    lefts = []
    cur = assign
    while cur is not None and cur.type == "assignment_expression":
        lefts.append(cur.child_by_field_name("left"))
        cur = cur.child_by_field_name("right")
    return lefts, cur


def _object_methods(obj: Any, raw: bytes) -> Iterable[tuple[str, int]]:
    for member in obj.named_children:
        if member.type == "method_definition":
            name = _text(member.child_by_field_name("name"), raw).strip("'\"`")
            if name:
                yield name, member.start_point[0] + 1
        elif member.type == "pair":
            key, value = member.child_by_field_name("key"), member.child_by_field_name("value")
            if key is not None and _function_value(value):
                name = _text(key, raw).strip("'\"`")
                if name:
                    yield name, member.start_point[0] + 1


def scan_file(path: str, raw: bytes, parser: Parser) -> list[dict[str, Any]]:
    tree = parser.parse(raw)
    found: list[dict[str, Any]] = []

    def add(pattern: str, qname: str, line: int, chained: bool = False) -> None:
        found.append({"path": path, "qualified_name": qname, "line": line, "pattern": pattern, "chained": chained})

    def statement(node: Any, top_level: bool, enclosing_fn: str | None) -> None:
        expr = node.named_children[0] if node.named_children else None
        if expr is None:
            return
        line = node.start_point[0] + 1
        if expr.type == "assignment_expression":
            lefts, value = _rhs_chain(expr)
            chained = len(lefts) > 1
            for left in lefts:
                if left is None or left.type != "member_expression":
                    continue
                obj, prop = left.child_by_field_name("object"), left.child_by_field_name("property")
                pname = _text(prop, raw)
                oname = _text(obj, raw)
                if _function_value(value) and pname:
                    if obj.type == "member_expression" and _text(obj.child_by_field_name("property"), raw) == "prototype":
                        add("prototype_method", f"{_text(obj.child_by_field_name('object'), raw)}.{pname}", line, chained)
                    elif oname in {"exports", "module.exports"}:
                        add("exports_member", pname, line, chained)
                    elif obj.type == "this" and enclosing_fn:
                        add("this_member", f"{enclosing_fn}.{pname}", line, chained)
                    elif obj.type == "identifier" and top_level and oname not in SPECIAL:
                        add("object_member", f"{oname}.{pname}", line, chained)
                if pname == "prototype" and value is not None and value.type == "object":
                    for m, mline in _object_methods(value, raw):
                        add("prototype_object", f"{oname}.{m}", mline, chained)
                if oname == "module" and pname == "exports" and value is not None and value.type == "object":
                    for m, mline in _object_methods(value, raw):
                        add("module_exports_object", m, mline, chained)
        elif expr.type == "call_expression":
            fn = _text(expr.child_by_field_name("function"), raw)
            args = expr.child_by_field_name("arguments")
            a = list(args.named_children) if args is not None else []
            if fn == "Object.defineProperty" and len(a) >= 3 and a[0].type == "member_expression":
                if _text(a[0].child_by_field_name("property"), raw) == "prototype" and a[2].type == "object":
                    desc = a[2]
                    if any(
                        (m.type == "method_definition" and _text(m.child_by_field_name("name"), raw) in {"get", "set", "value"})
                        or (m.type == "pair" and _text(m.child_by_field_name("key"), raw) in {"get", "set", "value"} and _function_value(m.child_by_field_name("value")))
                        for m in desc.named_children
                    ):
                        prop_name = _text(a[1], raw).strip("'\"`")
                        add("define_property", f"{_text(a[0].child_by_field_name('object'), raw)}.{prop_name}", line)
            if fn == "Object.defineProperties" and len(a) >= 2 and a[0].type == "member_expression" and a[1].type == "object":
                if _text(a[0].child_by_field_name("property"), raw) == "prototype":
                    cls = _text(a[0].child_by_field_name("object"), raw)
                    for pair in a[1].named_children:
                        if pair.type == "pair":
                            key = _text(pair.child_by_field_name("key"), raw).strip("'\"`")
                            val = pair.child_by_field_name("value")
                            if val is not None and val.type == "object" and any(
                                (m.type == "method_definition" and _text(m.child_by_field_name("name"), raw) in {"get", "set", "value"})
                                or (m.type == "pair" and _text(m.child_by_field_name("key"), raw) in {"get", "set", "value"} and _function_value(m.child_by_field_name("value")))
                                for m in val.named_children
                            ):
                                add("define_property", f"{cls}.{key}", pair.start_point[0] + 1)

    def declared_object_literals(node: Any) -> None:
        # const res = { send() {} }  (module level)  -> res.send
        for child in node.named_children:
            decl = child
            if child.type == "export_statement":
                decl = child.child_by_field_name("declaration") or child
            if decl.type in {"lexical_declaration", "variable_declaration"}:
                for d in decl.named_children:
                    if d.type != "variable_declarator":
                        continue
                    name_node, value = d.child_by_field_name("name"), d.child_by_field_name("value")
                    if name_node is not None and name_node.type == "identifier" and value is not None and value.type == "object":
                        for m, mline in _object_methods(value, raw):
                            add("object_literal", f"{_text(name_node, raw)}.{m}", mline)

    def walk(node: Any, top_level: bool, enclosing_fn: str | None) -> None:
        for child in node.named_children:
            t = child.type
            if t == "expression_statement":
                statement(child, top_level, enclosing_fn)
                # IIFE bodies / callbacks are not module level; do not descend into expression values
            elif t == "function_declaration":
                name = _text(child.child_by_field_name("name"), raw)
                body = child.child_by_field_name("body")
                if body is not None:
                    walk(body, False, name)
            elif t in {"if_statement", "try_statement", "statement_block", "for_statement", "while_statement", "export_statement"}:
                walk(child, top_level, enclosing_fn)

    walk(tree.root_node, True, None)
    declared_object_literals(tree.root_node)
    return found


def scan_repo(root: Path) -> list[dict[str, Any]]:
    parser = _parser()
    out: list[dict[str, Any]] = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix not in {".js", ".mjs", ".cjs"}:
            continue
        rel = f.relative_to(root).as_posix()
        if any(p in SKIP_DIRS for p in rel.split("/")) or _is_test(rel):
            continue
        out.extend(scan_file(rel, f.read_bytes(), parser))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)

    from token_context_mcp.config import index_directory, load_config
    from token_context_mcp.index.runner import database_path
    from token_context_mcp.index.sqlite_store import SQLiteStore

    load_config(args.config)
    store = SQLiteStore(database_path(index_directory(args.config), args.repo_id))
    symbols = list(store.symbols())
    index_keys = {(s.path, s.qualified_name or s.name) for s in symbols}
    scan = scan_repo(args.root)

    unique = {(s["path"], s["qualified_name"]): s for s in scan}
    missing = [s for k, s in unique.items() if k not in index_keys]
    nonchained = [s for k, s in unique.items() if not s["chained"]]
    missing_nonchained = [s for s in nonchained if (s["path"], s["qualified_name"]) not in index_keys]

    by_pattern: dict[str, dict[str, int]] = {}
    for k, s in unique.items():
        p = by_pattern.setdefault(s["pattern"], {"scan": 0, "indexed": 0})
        p["scan"] += 1
        p["indexed"] += 1 if k in index_keys else 0

    # precision sample: indexed symbols whose qualified name is not a plain declaration of the scan, pick those the
    # scan did not predict and those it did, then verify the source line backs them.
    scan_keys = set(unique)
    parser = _parser()
    sym_by_path: dict[str, list[Any]] = {}
    for s in symbols:
        if s.path.endswith((".js", ".mjs", ".cjs")) and not _is_test(s.path):
            sym_by_path.setdefault(s.path, []).append(s)
    candidates = []
    lines_by_path: dict[str, list[str]] = {}
    for path, syms in sym_by_path.items():
        raw = (args.root / path).read_bytes()
        lines = raw.decode("utf-8", errors="replace").splitlines()
        lines_by_path[path] = lines
        for s in syms:
            if not s.qualified_name or "." not in s.qualified_name and s.kind != "method":
                continue
            line = lines[s.start_line - 1] if 0 < s.start_line <= len(lines) else ""
            declared = line.lstrip().startswith(("function ", "async function", "class ", "export ", "const ", "let ", "var "))
            if (path, s.qualified_name) in scan_keys or not declared:
                candidates.append((s, line))
    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    sample = []
    wrong = 0
    for s, line in candidates[: args.sample]:
        name = s.name or s.qualified_name.rsplit(".", 1)[-1]
        window = "\n".join(lines_by_path[s.path][max(0, s.start_line - 9) : s.end_line])
        backed = re.search(r"(?<![A-Za-z0-9_$])" + re.escape(name) + r"(?![A-Za-z0-9_$])", window) is not None
        in_scan = (s.path, s.qualified_name) in scan_keys
        sample.append({"path": s.path, "qualified_name": s.qualified_name, "line": s.start_line, "backed_by_source": backed, "in_scan": in_scan, "source_line": line.strip()[:140]})
        wrong += 0 if backed else 1

    report = {
        "repo_id": args.repo_id,
        "scan_symbols": len(unique),
        "indexed": len(unique) - len(missing),
        "recall": round((len(unique) - len(missing)) / len(unique), 4) if unique else None,
        "recall_excluding_chained": round((len(nonchained) - len(missing_nonchained)) / len(nonchained), 4) if nonchained else None,
        "chained_symbols": len(unique) - len(nonchained),
        "by_pattern": by_pattern,
        "missing": [{k: m[k] for k in ("path", "qualified_name", "line", "pattern", "chained")} for m in missing],
        "precision_sample": {"size": len(sample), "wrong": wrong, "items": sample},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("repo_id", "scan_symbols", "indexed", "recall", "recall_excluding_chained", "chained_symbols")}))
    print("sample wrong:", wrong, "of", len(sample))
    return 0


if __name__ == "__main__":
    sys.exit(main())
