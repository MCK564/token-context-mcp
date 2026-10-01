"""M10.1: verify every gold symbol of a bench task file via symbol_context(include_body=true).

Also reports (informational) how many packet gold items lie within one hop of their target
(callee conf >= 0.6, caller conf >= 0.5) or in the same class -- the packet reach ceiling.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from token_context_mcp.config import index_directory, load_config
from token_context_mcp.index.runner import database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.retrieve.service import RetrievalService


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    cfg = load_config(args.config)
    svc = RetrievalService(cfg, args.config)
    store = SQLiteStore(database_path(index_directory(args.config), args.repo_id))
    by_key = {(s.path, s.qualified_name or s.name): s for s in store.symbols()}
    by_id = {s.symbol_id: s for s in by_key.values()}
    data = json.loads(args.tasks.read_text(encoding="utf-8"))

    def check(path: str, qname: str, pending: bool = False) -> dict:
        s = by_key.get((path, qname))
        if s is None and pending:
            return {"path": path, "qualified_name": qname, "found": False, "pending": True}
        if s is None:
            return {"path": path, "qualified_name": qname, "found": False}
        resp = svc.symbol_context(args.repo_id, symbol_id=s.symbol_id, depth=0, include_body=True, max_tokens=4000)
        data_keys = sorted(resp["data"])
        content = None
        for item in resp["data"].get("symbols", []):
            if item.get("symbol_id") == s.symbol_id or content is None:
                content = item.get("content") or content
        return {
            "path": path, "qualified_name": qname, "found": True, "kind": s.kind,
            "span": f"{s.start_line}-{s.end_line}", "lines": s.end_line - s.start_line + 1,
            "body_returned": bool(content), "body_chars": len(content or ""), "data_keys": data_keys,
            "warnings": resp.get("warnings", []),
        }

    out: dict = {"tasks_file": str(args.tasks), "repo_id": args.repo_id, "loc": [], "packet": []}
    for t in data.get("tasks", []):
        out["loc"].append({"id": t["id"], "gold": [
            check(g["path"], g["qualified_name"], bool(g.get("gold_pending_indexer"))) for g in t["gold_symbols"]]})
    reach_total = reach_hit = 0
    for t in data.get("packet_tasks", []):
        if t["target"].get("gold_pending_indexer") and (t["target"]["path"], t["target"]["qualified_name"]) not in by_key:
            out["packet"].append({"id": t["id"], "target": {**t["target"], "found": False, "pending": True}, "gold": []})
            continue
        tgt = by_key[(t["target"]["path"], t["target"]["qualified_name"])]
        rel = svc.symbol_relationships(args.repo_id, symbol_id=tgt.symbol_id, min_confidence=0.5)
        near = set()
        for e in rel["edges"]:
            oid = e["target_symbol_id"] if e["relation"] == "callee" else e["source_symbol_id"]
            if e["relation"] == "callee" and (e.get("confidence") or 0) < 0.6:
                continue
            near.add(oid)
        cls = tgt.qualified_name.rsplit(".", 1)[0] + "." if "." in tgt.qualified_name else None
        entry = {"id": t["id"], "target": check(tgt.path, tgt.qualified_name), "gold": []}
        for g in t["gold_context"]:
            c = check(g["path"], g["qualified_name"], bool(g.get("gold_pending_indexer")))
            s = by_key.get((g["path"], g["qualified_name"]))
            in_hop = bool(s and s.symbol_id in near)
            same_cls = bool(s and cls and s.path == tgt.path and (s.qualified_name or "").startswith(cls))
            c["within_one_hop"] = in_hop
            c["same_class"] = same_cls
            c["reachable"] = in_hop or same_cls
            reach_total += 1
            reach_hit += 1 if c["reachable"] else 0
            entry["gold"].append(c)
        out["packet"].append(entry)
    missing = [g for t in out["loc"] for g in t["gold"] if not g["found"] and not g.get("pending")] + [
        g for t in out["packet"] for g in t["gold"] if not g["found"] and not g.get("pending")]
    out["summary"] = {
        "loc_tasks": len(out["loc"]), "packet_tasks": len(out["packet"]),
        "missing_gold": len(missing), "packet_reach_items": reach_total, "packet_reach_hit": reach_hit,
        "packet_reach_ceiling": round(reach_hit / reach_total, 4) if reach_total else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"]))
    unreachable = [(t["id"], g["qualified_name"]) for t in out["packet"] for g in t["gold"] if not g["reachable"]]
    print("unreachable packet gold:", unreachable)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
