"""Sample call sites directly from AST using tree-sitter without reading index."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser


def get_parser(language: str) -> tuple[Parser, set[str], set[str]]:
    lang_lower = language.lower()
    if lang_lower in {"javascript", "js"}:
        import tree_sitter_javascript as tsjs
        parser = Parser(Language(tsjs.language()))
        target_nodes = {"call_expression", "new_expression"}
        extensions = {".js", ".mjs", ".cjs"}
    elif lang_lower in {"typescript", "ts"}:
        import tree_sitter_typescript as tsts
        parser = Parser(Language(tsts.language_typescript()))
        target_nodes = {"call_expression", "new_expression"}
        extensions = {".ts", ".tsx"}
    elif lang_lower in {"c#", "csharp", "cs"}:
        import tree_sitter_c_sharp as tscs
        parser = Parser(Language(tscs.language()))
        target_nodes = {"invocation_expression", "object_creation_expression"}
        extensions = {".cs"}
    elif lang_lower == "java":
        import tree_sitter_java as tsj
        parser = Parser(Language(tsj.language()))
        target_nodes = {"method_invocation", "object_creation_expression"}
        extensions = {".java"}
    else:
        raise ValueError(f"Unsupported language: {language}")
    return parser, target_nodes, extensions


def is_test_file(path_str: str) -> bool:
    p = path_str.lower().replace("\\", "/")
    parts = p.split("/")
    test_dirs = {"test", "tests", "__tests__", "spec", "specs", "test-assets"}
    non_source_dirs = {"samples", "sample", "examples", "example", "benchmark", "benchmarks", "perf", "docs", "demo"}
    for part in parts[:-1]:
        # any directory named like a test project (Newtonsoft.Json.Tests, test-shrinker, ...) is not library source
        if part in test_dirs or "test" in part or part in non_source_dirs:
            return True
    for part in parts:
        if part in test_dirs:
            return True
    filename = parts[-1]
    if "benchmark" in filename:
        return True
    if (
        filename.endswith(".test.ts")
        or filename.endswith(".test.js")
        or filename.endswith(".spec.ts")
        or filename.endswith(".spec.js")
        or filename.startswith("test_")
        or "test" in filename
    ):
        return True
    return False


def extract_callee_text(node: Any, raw: bytes, lang: str) -> str:
    if node.type in {"call_expression", "new_expression"}:
        fn_node = node.child_by_field_name("function") or (node.named_children[0] if node.named_children else None)
        if fn_node:
            return raw[fn_node.start_byte:fn_node.end_byte].decode("utf-8", errors="replace")
    elif node.type == "invocation_expression":
        expr_node = node.child_by_field_name("expression") or (node.named_children[0] if node.named_children else None)
        if expr_node:
            return raw[expr_node.start_byte:expr_node.end_byte].decode("utf-8", errors="replace")
    elif node.type == "method_invocation":
        name_node = node.child_by_field_name("name")
        obj_node = node.child_by_field_name("object")
        name = raw[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace") if name_node else ""
        if obj_node is not None:
            return raw[obj_node.start_byte:obj_node.end_byte].decode("utf-8", errors="replace") + "." + name
        return name
    elif node.type == "object_creation_expression":
        type_node = node.child_by_field_name("type")
        if type_node:
            return raw[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace")
    return raw[node.start_byte:min(node.end_byte, node.start_byte + 50)].decode("utf-8", errors="replace").split("(")[0].strip()


def find_call_sites_in_file(file_path: Path, root: Path, parser: Parser, target_nodes: set[str], lang: str) -> list[dict[str, Any]]:
    try:
        raw = file_path.read_bytes()
    except OSError:
        return []

    lines = raw.decode("utf-8", errors="replace").splitlines()
    tree = parser.parse(raw)
    sites: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if node.type in target_nodes:
            start_row, start_col = node.start_point
            line_1 = start_row + 1
            col_1 = start_col + 1

            snip_start = max(0, start_row - 3)
            snip_end = min(len(lines), start_row + 4)
            snippet = "\n".join(lines[snip_start:snip_end])

            callee = extract_callee_text(node, raw, lang)

            rel_path = str(file_path.relative_to(root)).replace("\\", "/")
            sites.append({
                "path": rel_path,
                "line": line_1,
                "col": col_1,
                "callee_text": callee,
                "snippet": snippet,
                "node_type": node.type,
            })
        for child in node.named_children:
            walk(child)

    walk(tree.root_node)
    return sites


DECLARATION_NODES = {"method_declaration", "constructor_declaration"}
TRIVIAL_SHARED_NAMES = {
    "ToString", "Equals", "GetHashCode", "Dispose", "toString", "equals", "hashCode", "close", "Close", "GetType",
}


def callee_simple_name(callee_text: str) -> str:
    text = callee_text.split("(")[0].strip()
    if text.startswith("new "):
        text = text[4:].strip()
    text = text.split("<")[0].strip()
    return text.rsplit(".", 1)[-1].strip().rstrip("?!")


def collect_declared_name_counts(source_files: list[Path], parser: Parser) -> dict[str, int]:
    """How many method/constructor declarations carry each simple name (overloads and overrides both count)."""
    counts: dict[str, int] = {}
    for f in source_files:
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        stack = [parser.parse(raw).root_node]
        while stack:
            node = stack.pop()
            if node.type in DECLARATION_NODES:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = raw[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    counts[name] = counts.get(name, 0) + 1
            stack.extend(node.named_children)
    return counts


def sample_call_sites(
    root: Path,
    language: str,
    n: int = 30,
    seed: int = 20260930,
    shared_names_only: bool = False,
    min_declarations: int = 2,
) -> list[dict[str, Any]]:
    parser, target_nodes, extensions = get_parser(language)
    rng = random.Random(seed)

    source_files: list[Path] = []
    for ext in extensions:
        for f in root.rglob(f"*{ext}"):
            rel = str(f.relative_to(root)).replace("\\", "/")
            if not is_test_file(rel):
                source_files.append(f)

    source_files.sort()
    declared_counts: dict[str, int] = {}
    if shared_names_only:
        declared_counts = collect_declared_name_counts(source_files, parser)
    rng.shuffle(source_files)

    sites_by_file: list[list[dict[str, Any]]] = []
    for f in source_files:
        f_sites = find_call_sites_in_file(f, root, parser, target_nodes, language)
        if shared_names_only:
            f_sites = [
                site for site in f_sites
                if declared_counts.get(callee_simple_name(site["callee_text"]), 0) >= min_declarations
                and callee_simple_name(site["callee_text"]) not in TRIVIAL_SHARED_NAMES
            ]
        if f_sites:
            rng.shuffle(f_sites)
            sites_by_file.append(f_sites)

    selected: list[dict[str, Any]] = []
    # Round-robin across files for stratification
    idx = 0
    while len(selected) < n and sites_by_file:
        file_idx = idx % len(sites_by_file)
        if sites_by_file[file_idx]:
            selected.append(sites_by_file[file_idx].pop(0))
        else:
            sites_by_file.pop(file_idx)
            continue
        idx += 1

    selected.sort(key=lambda s: (s["path"], s["line"]))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample AST call sites without index.")
    parser.add_argument("--root", type=Path, required=True, help="Repository root path")
    parser.add_argument("--language", required=True, help="Language: javascript, typescript, csharp, java")
    parser.add_argument("--n", type=int, default=30, help="Number of call sites to sample")
    parser.add_argument("--seed", type=int, default=20260930, help="Random seed")
    parser.add_argument(
        "--shared-names-only",
        action="store_true",
        help="Only sample call sites whose callee simple name is declared at least --min-declarations times in the "
        "repository sources (overloaded or overridden members); counted from the AST, no index is read.",
    )
    parser.add_argument("--min-declarations", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True, help="Output JSON/JSONL file")
    args = parser.parse_args()

    sites = sample_call_sites(
        args.root,
        args.language,
        n=args.n,
        seed=args.seed,
        shared_names_only=args.shared_names_only,
        min_declarations=args.min_declarations,
    )
    print(f"Sampled {len(sites)} call sites across {len(set(s['path'] for s in sites))} files.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix == ".jsonl":
        with open(args.output, "w", encoding="utf-8") as f:
            for s in sites:
                f.write(json.dumps(s) + "\n")
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({"language": args.language, "seed": args.seed, "sites": sites}, f, indent=2)

    print(f"Saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
