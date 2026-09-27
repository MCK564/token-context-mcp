#!/usr/bin/env python3
"""Generate diagnostic task set evals/tasks/loc_b2_graph_needed.json (M5 LARGER-lite).

Requirements:
- Deterministic, random seed = 20260926.
- Candidate edges: status='resolved', backend='lexical', confidence >= 0.75,
  both source and target in src/, target != '<module>'.
- Query for edge s -> t: tokens of split_identifier(s.name) + first line of docstring of s (if any),
  truncated to at most 8 words.
- Edge rejected if:
  * query violates Rule 3 of lint_tasks.py with respect to t (leaks target name, stem, or qualified_name).
  * t is already in top-10 symbols of A1 (search_source, expand="none", limit=20, max_tokens=2048).
- Sample 20 remaining edges at random (seed 20260926), max 2 edges with the same source symbol.
- Gold = t (symbol + file).
- Save to evals/tasks/loc_b2_graph_needed.json with reviewed=false,
  construction="selected where A1 misses; A1 = 0 by construction".
"""
from __future__ import annotations

import ast
import json
import random
import re
import sys
from pathlib import Path
import sqlite3

# Ensure repo root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from token_context_mcp.config import default_config_path, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.retrieve.code_tokens import split_identifier
from token_context_mcp.retrieve.service import RetrievalService
from evals.lint_tasks import split_identifier_tokens


def get_symbol_docstring(file_path: Path, qname: str) -> str | None:
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        parts = qname.split(".")
        curr_nodes = [tree]
        for part in parts:
            next_nodes = []
            for n in curr_nodes:
                for child in ast.iter_child_nodes(n):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name == part:
                        next_nodes.append(child)
            curr_nodes = next_nodes
            if not curr_nodes:
                break
        if curr_nodes:
            return ast.get_docstring(curr_nodes[0])
    except Exception:
        pass
    return None


def make_b2_tasks() -> dict:
    cfg_p = default_config_path()
    cfg = load_config(cfg_p)
    service = RetrievalService(cfg, cfg_p)
    repo, store, meta = service._repository_store("token-context")
    symbol_id_map = {s.symbol_id: (s.path, s.qualified_name or s.name) for s in store.symbols()}

    idx_dir = cfg_p.parent / "indexes"
    con = sqlite3.connect(database_path(idx_dir, "token-context"))
    con.row_factory = sqlite3.Row

    # Step 1: Candidate edges
    query_sql = """
        SELECT e.edge_id, e.source_symbol_id, e.target_symbol_id, e.edge_kind, e.confidence, e.backend, e.status,
               s1.path as source_path, s1.name as source_name, s1.qualified_name as source_qname,
               s2.path as target_path, s2.name as target_name, s2.qualified_name as target_qname
        FROM edges e
        JOIN symbols s1 ON e.source_symbol_id = s1.symbol_id
        JOIN symbols s2 ON e.target_symbol_id = s2.symbol_id
        WHERE e.status = 'resolved'
          AND e.backend = 'lexical'
          AND e.confidence >= 0.75
          AND s1.path LIKE 'src/%'
          AND s2.path LIKE 'src/%'
          AND s2.name != '<module>'
        ORDER BY e.edge_id ASC
    """
    rows = con.execute(query_sql).fetchall()
    total_candidates = len(rows)

    doc_cache: dict[tuple[str, str], str | None] = {}
    repo_root = Path(repo.root)

    candidates = []
    dropped_rule3 = 0
    dropped_a1_hit = 0

    for r in rows:
        s_path = r["source_path"]
        s_name = r["source_name"]
        s_qname = r["source_qname"]
        t_path = r["target_path"]
        t_name = r["target_name"]
        t_qname = r["target_qname"]

        cache_key = (s_path, s_qname)
        if cache_key not in doc_cache:
            doc_cache[cache_key] = get_symbol_docstring(repo_root / s_path, s_qname)
        doc = doc_cache[cache_key]

        # Step 2: query tokens = split_identifier(s.name) + docstring first line, max 8 words
        raw_name_tokens = split_identifier(s_name)
        name_words: list[str] = []
        for tok in raw_name_tokens:
            for w in re.findall(r"[a-zA-Z0-9]+", tok.lower()):
                if w not in name_words:
                    name_words.append(w)

        doc_words: list[str] = []
        if doc:
            first_line = doc.strip().splitlines()[0]
            for w in re.findall(r"[a-zA-Z0-9]+", first_line.lower()):
                if w not in name_words and w not in doc_words:
                    doc_words.append(w)

        all_words = (name_words + doc_words)[:8]
        query = " ".join(all_words)

        # Step 3: Check Rule 3 of lint_tasks.py
        q_tokens = split_identifier_tokens(query)
        target_name_raw = t_qname.split(".")[-1]
        name_tokens = split_identifier_tokens(target_name_raw)
        qname_tokens = {t for t in split_identifier_tokens(t_qname) if len(t) >= 4}
        filename = t_path.rsplit("/", 1)[-1]
        stem = filename.split(".")[0] if "." in filename else filename
        stem_tokens = split_identifier_tokens(stem)
        forbidden = name_tokens | qname_tokens | stem_tokens
        overlap = q_tokens & forbidden
        if overlap:
            dropped_rule3 += 1
            continue

        # Check A1 hit
        resp = service.search_source("token-context", query=query, limit=20, max_tokens=2048)
        data = resp.get("data", {})
        matches = data.get("matches", [])
        top_10_syms = []
        for m in matches[:10]:
            sid = m.get("symbol_id")
            if sid and sid in symbol_id_map:
                top_10_syms.append(symbol_id_map[sid])
            elif m.get("path") and (m.get("qualified_name") or m.get("name")):
                top_10_syms.append((str(m["path"]).replace("\\", "/"), m.get("qualified_name") or m["name"]))

        target_pair = (t_path.replace("\\", "/"), t_qname)
        if target_pair in top_10_syms:
            dropped_a1_hit += 1
            continue

        candidates.append({
            "edge": r,
            "query": query,
            "target_pair": target_pair,
            "source_pair": (s_path.replace("\\", "/"), s_qname),
        })

    # Step 4: Deterministic random sample 20 edges, max 2 per source
    rng = random.Random(20260926)
    # Sort candidates by edge_id for stable ordering before shuffle
    candidates.sort(key=lambda c: c["edge"]["edge_id"])
    rng.shuffle(candidates)

    selected: list[dict] = []
    source_counts: dict[str, int] = {}
    seen_queries: set[str] = set()
    dropped_source_cap = 0
    dropped_duplicate_query = 0

    for c in candidates:
        if len(selected) >= 20:
            break
        s_id = c["edge"]["source_symbol_id"]
        q = c["query"]
        if q in seen_queries:
            dropped_duplicate_query += 1
            continue
        if source_counts.get(s_id, 0) >= 2:
            dropped_source_cap += 1
            continue
        source_counts[s_id] = source_counts.get(s_id, 0) + 1
        seen_queries.add(q)
        selected.append(c)

    print(f"=== b2_graph_needed Task Set Generation Summary ===")
    print(f"Total candidate edges matching Step 1: {total_candidates}")
    print(f"Dropped by Rule 3 (query leaks target name/stem/qname): {dropped_rule3}")
    print(f"Dropped because A1 found in top-10 symbols: {dropped_a1_hit}")
    print(f"Remaining qualifying candidate edges: {len(candidates)}")
    print(f"Selected tasks: {len(selected)}")
    print(f"Dropped during sampling due to source cap (>2 per source): {dropped_source_cap}")
    print(f"Dropped during sampling due to duplicate query: {dropped_duplicate_query}")

    # Build task JSON structures
    tasks = []
    for idx, c in enumerate(selected, 1):
        edge = c["edge"]
        t_path = edge["target_path"].replace("\\", "/")
        t_qname = edge["target_qname"]
        s_path = edge["source_path"].replace("\\", "/")
        s_qname = edge["source_qname"]
        tasks.append({
            "id": f"b2_{idx:02d}",
            "group": "b_hidden_dep",
            "split": "heldout",
            "query": c["query"],
            "gold_files": [t_path],
            "gold_symbols": [
                {
                    "path": t_path,
                    "qualified_name": t_qname,
                }
            ],
            "source_symbol": {
                "symbol_id": edge["source_symbol_id"],
                "path": s_path,
                "qualified_name": s_qname,
            },
            "edge_kind": edge["edge_kind"],
            "confidence": edge["confidence"],
            "note": f"Diagnostic edge {s_qname} -> {t_qname} via {edge['edge_kind']} (conf={edge['confidence']})",
        })

    result = {
        "repo_id": "token-context",
        "reviewed": False,
        "construction": "selected where A1 misses; A1 = 0 by construction",
        "split_seed": 20260926,
        "tasks": tasks,
    }

    out_file = REPO_ROOT / "evals" / "tasks" / "loc_b2_graph_needed.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(tasks)} tasks to {out_file}")
    return result


if __name__ == "__main__":
    make_b2_tasks()
