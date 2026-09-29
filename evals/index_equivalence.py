"""Invariant I1 (M7): an incremental index is equivalent to a from-scratch index of the same tree.

``dump_snapshot`` turns a snapshot into a canonical form (row multisets per table, without run ids, timestamps,
mtimes, rowids and stub ids; ranks rounded to 6 digits; file communities as a partition), ``compare_dumps``
diffs two of them, and ``run_chain`` mutates a copy of a repository in five chained steps
(edit a body, rename a function with a cross-file caller, add a file, delete a file, change an import) and after
every step compares "incremental on top of the previous snapshot" with "full build into an empty directory".

    uv run python evals/index_equivalence.py --root <repo> --repo-id tc-pinned --output evals/out/m7/equivalence_tc_pinned.json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import math

from token_context_mcp.index.runner import build_index, database_path
from token_context_mcp.parse import lexical_edges
from token_context_mcp.models import RepositoryConfig
from token_context_mcp.retrieve.expansion import file_communities

# table -> (SQL, index of the score column to round or None)
_TABLE_QUERIES: dict[str, str] = {
    "files": "SELECT path, sha256, size, language, parse_status, warnings_json FROM files",
    "symbols": (
        "SELECT symbol_id, path, name, qualified_name, kind, signature, start_line, end_line, start_byte,"
        " end_byte, body_start_byte, body_end_byte, is_private, roles_json, role_evidence_json FROM symbols"
    ),
    "edges": (
        "SELECT e.source_symbol_id, e.target_symbol_id, s.package, s.export_path, s.member_name, e.target_name,"
        " e.edge_kind, e.status, e.backend, e.confidence, e.source_path, e.source_line, e.evidence_json"
        " FROM edges e LEFT JOIN external_stubs s ON s.stub_id = e.target_stub_id"
    ),
    "imports": "SELECT path, module FROM imports",
    "class_hierarchy": "SELECT class_symbol_id, parent_name, parent_symbol_id FROM class_hierarchy",
    "symbol_rank": "SELECT symbol_id, score, basis_json FROM symbol_rank",
    "symbol_fts": "SELECT symbol_id, path, name, qualified_name, code_tokens, own_body FROM symbol_fts",
    "symbol_bodies": "SELECT symbol_id, path, body FROM symbol_bodies",
    "source_bodies": "SELECT path, body FROM source_bodies",
    "external_stubs": "SELECT package, export_path, member_name, signature, doc_summary FROM external_stubs",
    "file_parse_artifacts": (
        "SELECT path, sha256, parser_version, language, calls_json, inheritance_json, imports_json,"
        " warnings_json, facts_json FROM file_parse_artifacts"
    ),
}
_METADATA_KEYS = (
    "index_schema_version", "files_indexed", "files_skipped", "symbols_indexed", "edges_indexed", "stubs_indexed",
    "entry_points", "role_counts", "derived_defaults", "warnings", "parser_artifact_version",
)


# The per-file circuit breaker of edge resolution is wall-clock based, so two builds of the same tree can differ
# on a loaded machine.  I1 is about the incremental logic, not about timing: switch the breaker off here.
lexical_edges.FILE_CIRCUIT_BREAKER_SECONDS = math.inf


def dump_snapshot(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        dump: dict[str, Any] = {}
        for table, sql in _TABLE_QUERIES.items():
            try:
                rows = connection.execute(sql).fetchall()
            except sqlite3.Error:
                dump[table] = None  # table missing in this snapshot version
                continue
            if table == "symbol_rank":
                rows = [(row[0], round(float(row[1]), 6), row[2]) for row in rows]
            elif table == "edges":
                rows = [
                    tuple(round(float(v), 6) if index == 9 and v is not None else v for index, v in enumerate(row))
                    for row in rows
                ]
            dump[table] = Counter(tuple(row) for row in rows)
        metadata = {key: json.loads(value) for key, value in connection.execute("SELECT key, value FROM metadata")}
        dump["metadata"] = {key: metadata.get(key) for key in _METADATA_KEYS}
        dump["metadata"]["warnings"] = sorted(dump["metadata"]["warnings"] or [])
        paths = sorted(row[0] for row in connection.execute("SELECT path FROM files"))
        pairs = sorted((row[0], row[1]) for row in connection.execute("SELECT path, module FROM imports"))
        communities = file_communities(paths, pairs)
        groups: dict[int, list[str]] = {}
        for path, label in communities.items():
            groups.setdefault(label, []).append(path)
        dump["file_community"] = Counter(tuple(sorted(group)) for group in groups.values())
        return dump
    finally:
        connection.close()


def compare_dumps(full: dict[str, Any], incremental: dict[str, Any], *, samples: int = 3) -> dict[str, Any]:
    """Empty dict when equivalent, otherwise per-table missing/extra counts with a few samples."""
    problems: dict[str, Any] = {}
    for table in [*_TABLE_QUERIES, "file_community"]:
        a, b = full.get(table), incremental.get(table)
        if a is None and b is None:
            continue
        if a is None or b is None:
            problems[table] = {"error": "table present in only one snapshot"}
            continue
        missing = a - b
        extra = b - a
        if missing or extra:
            problems[table] = {
                "only_in_full": sum(missing.values()),
                "only_in_incremental": sum(extra.values()),
                "sample_only_in_full": [repr(item)[:300] for item in list(missing)[:samples]],
                "sample_only_in_incremental": [repr(item)[:300] for item in list(extra)[:samples]],
            }
    for key in _METADATA_KEYS:
        if full["metadata"].get(key) != incremental["metadata"].get(key):
            problems[f"metadata.{key}"] = {"full": full["metadata"].get(key), "incremental": incremental["metadata"].get(key)}
    return problems


def _repository(repo_id: str, root: Path) -> RepositoryConfig:
    return RepositoryConfig(repo_id=repo_id, root=root.resolve())


def build_full(repo_id: str, root: Path, directory: Path, **kwargs: Any) -> dict[str, Any]:
    """From-scratch build into ``directory`` (which must not hold an earlier snapshot)."""
    if directory.exists():
        shutil.rmtree(directory)
    return build_index(_repository(repo_id, root), directory, network_policy="declared-deny-not-enforced", **kwargs)


def build_incremental(repo_id: str, root: Path, directory: Path, **kwargs: Any) -> dict[str, Any]:
    return build_index(_repository(repo_id, root), directory, network_policy="declared-deny-not-enforced", **kwargs)


def age_files(root: Path, seconds: int = 3600) -> None:
    """Give every file an old mtime so the racy-timestamp rule does not force a rehash of untouched files."""
    old = time.time() - seconds
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))


# ------------------------------------------------------------------------------------------- mutations


def _python_files(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if path.name == "__init__.py" or any(part.startswith(".") for part in rel.split("/")):
            continue
        found.append(path)
    return found


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def _first_function(path: Path) -> ast.FunctionDef | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.body and node.body[0].lineno > node.lineno:
            first = node.body[0]
            # skip one-line bodies and functions whose first statement shares the ``def`` line
            if first.col_offset > node.col_offset:
                return node
    return None


def _touch(path: Path) -> None:
    os.utime(path, None)


def op_setup(root: Path, rng: random.Random) -> dict[str, Any]:
    """Ensure a top-level function with a cross-file caller exists (needed by the rename step)."""
    files = _python_files(root)
    a, b = files[len(files) // 3], files[(2 * len(files)) // 3]
    if a == b:
        b = files[-1]
    a.write_text(a.read_text(encoding="utf-8").rstrip("\n") + "\n\n\ndef m7_shared_util(value):\n    return value + 1\n", encoding="utf-8")
    b.write_text(
        f"from {_module_name(root, a)} import m7_shared_util\n"
        + b.read_text(encoding="utf-8").rstrip("\n")
        + "\n\n\ndef m7_shared_caller():\n    return m7_shared_util(41)\n",
        encoding="utf-8",
    )
    return {"op": "setup", "touched": [a, b], "removed": [], "partner": [a, b]}


def op_edit_body(root: Path, rng: random.Random) -> dict[str, Any]:
    candidates = _python_files(root)
    rng.shuffle(candidates)
    for path in candidates:
        node = _first_function(path)
        if node is None:
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        first = node.body[0]
        insert_at = first.lineno - 1
        if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str):
            insert_at = first.end_lineno  # after the docstring
            if insert_at >= len(lines):
                continue
        indent = " " * first.col_offset
        lines.insert(insert_at, f"{indent}_m7_marker = 'edit-body'\n")
        path.write_text("".join(lines), encoding="utf-8")
        return {"op": "edit_body", "touched": [path], "removed": [], "function": node.name}
    raise RuntimeError("no function to edit")


def op_rename(root: Path, rng: random.Random) -> dict[str, Any]:
    touched: list[Path] = []
    pattern = re.compile(r"\bm7_shared_util\b")
    for path in _python_files(root):
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            path.write_text(pattern.sub("m7_shared_util_renamed", text), encoding="utf-8")
            touched.append(path)
    return {"op": "rename_function", "touched": touched, "removed": []}


def op_add_file(root: Path, rng: random.Random) -> dict[str, Any]:
    files = _python_files(root)
    anchor = files[len(files) // 2]
    fresh = anchor.parent / "m7_added_module.py"
    fresh.write_text(
        f"from {_module_name(root, anchor)} import *\n\n\nclass M7Added:\n    def run(self):\n        return 1\n\n\n"
        "def m7_added_entry():\n    return M7Added().run()\n",
        encoding="utf-8",
    )
    return {"op": "add_file", "touched": [fresh], "removed": []}


def op_delete_file(root: Path, rng: random.Random) -> dict[str, Any]:
    protected = re.compile(r"m7_")
    files = [p for p in _python_files(root) if not protected.search(p.name)]
    sizes = sorted(files, key=lambda p: (p.stat().st_size, p.as_posix()))
    victim = sizes[len(sizes) // 4]
    # a file that no step touched and that carries symbols
    text = victim.read_text(encoding="utf-8")
    victim.unlink()
    return {"op": "delete_file", "touched": [], "removed": [victim], "bytes": len(text)}


def op_change_import(root: Path, rng: random.Random) -> dict[str, Any]:
    files = _python_files(root)
    target = files[len(files) // 5]
    if not target.exists():
        target = files[len(files) // 5 + 1]
    other = files[(len(files) * 4) // 5]
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith(("import ", "from ")) and "__future__" not in line:
            insert_at = index + 1
    lines.insert(insert_at, f"from {_module_name(root, other)} import m7_shared_caller\n")
    target.write_text("".join(lines), encoding="utf-8")
    return {"op": "change_import", "touched": [target], "removed": []}


CHAIN = (op_edit_body, op_rename, op_add_file, op_delete_file, op_change_import)


def run_chain(
    root: Path,
    repo_id: str,
    work_dir: Path,
    *,
    seed: int = 7,
    workers: int | None = None,
    pool_min_files: int | None = None,
    verify_hashes: bool = False,
) -> dict[str, Any]:
    """Copy ``root`` to ``work_dir/tree`` and run the five chained scenarios; returns the report."""
    tree = work_dir / "tree"
    if tree.exists():
        shutil.rmtree(tree)
    shutil.copytree(root, tree, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    rng = random.Random(seed)
    extra: dict[str, Any] = {}
    if workers is not None:
        extra["workers"] = workers
    if pool_min_files is not None:
        extra["pool_min_files"] = pool_min_files
        extra["pool_min_bytes"] = 0
    setup = op_setup(tree, rng)
    age_files(tree)
    inc_dir = work_dir / "inc"
    if inc_dir.exists():
        shutil.rmtree(inc_dir)
    base = build_incremental(repo_id, tree, inc_dir, **extra)
    steps: list[dict[str, Any]] = [
        {"step": "base", "parse_source_calls": base["parse_source_calls"], "files_reparsed": base["files_reparsed"], "equivalent": True}
    ]
    ok = True
    for index, operation in enumerate(CHAIN, start=1):
        mutation = operation(tree, rng)
        started = time.perf_counter()
        manifest = build_incremental(repo_id, tree, inc_dir, verify_hashes=verify_hashes, **extra)
        inc_seconds = time.perf_counter() - started
        full_manifest = build_full(repo_id, tree, work_dir / "full", **extra)
        problems = compare_dumps(
            dump_snapshot(database_path(work_dir / "full", repo_id)),
            dump_snapshot(database_path(inc_dir, repo_id)),
        )
        expected_parses = len([p for p in mutation["touched"] if p.exists()])
        step = {
            "step": f"{index}:{mutation['op']}",
            "touched": [p.relative_to(tree).as_posix() for p in mutation["touched"]],
            "removed": [p.relative_to(tree).as_posix() for p in mutation["removed"]],
            "expected_parse_source_calls": expected_parses if not verify_hashes else None,
            "parse_source_calls": manifest["parse_source_calls"],
            "files_reparsed": manifest["files_reparsed"],
            "files_stat_skipped": manifest.get("files_stat_skipped"),
            "edge_resolution": manifest.get("edge_resolution"),
            "incremental_seconds": round(inc_seconds, 3),
            "full_manifest_symbols": full_manifest["symbols_indexed"],
            "incremental_manifest_symbols": manifest["symbols_indexed"],
            "equivalent": not problems,
            "problems": problems,
        }
        steps.append(step)
        ok = ok and not problems
    return {"repo_id": repo_id, "setup": {"touched": [p.relative_to(tree).as_posix() for p in setup["touched"]]}, "steps": steps, "all_equivalent": ok}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--pool-min-files", type=int, default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    work = args.work_dir or Path(tempfile.mkdtemp(prefix="index-equivalence-"))
    work.mkdir(parents=True, exist_ok=True)
    report = run_chain(args.root, args.repo_id, work, seed=args.seed, workers=args.workers, pool_min_files=args.pool_min_files)
    text = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    summary = {
        "repo_id": report["repo_id"],
        "all_equivalent": report["all_equivalent"],
        "steps": [
            {k: step[k] for k in ("step", "parse_source_calls", "expected_parse_source_calls", "equivalent", "edge_resolution") if k in step}
            for step in report["steps"]
        ],
    }
    print(json.dumps(summary, indent=1))
    for step in report["steps"]:
        if step.get("problems"):
            print(json.dumps({step["step"]: step["problems"]}, indent=1)[:3000])
    return 0 if report["all_equivalent"] else 1


if __name__ == "__main__":
    sys.exit(main())
