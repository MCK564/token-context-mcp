"""Run ``inspect_symbol`` on the packet-task targets and dump the raw responses as JSONL (M6.4).

Used by ``evals/packet_eval.py`` in a child process so that the same driver can run against the pre-M6 code
(arm P0: ``PYTHONPATH=tmp/p0/src``) and against the current tree (arm P1).  It only touches public entry
points that exist in both trees: ``RetrievalService`` and ``CompositeWorkflowEngine.inspect_symbol``.

Target resolution is deterministic and identical for both arms: ``find_symbols`` is wrapped so that it
always returns exactly the symbol whose ``(path, qualified_name)`` the task names, instead of relying on
name matching (which can be ambiguous).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _apply_constants(shares: str | None, callers_k: int | None) -> None:
    if shares is None and callers_k is None:
        return
    from token_context_mcp.retrieve import packet  # only exists on the P1 tree

    if shares:
        for part in shares.split(","):
            key, value = part.split("=")
            packet.DEFAULT_SHARES[key.strip()] = float(value)
    if callers_k is not None:
        packet.CALLERS_K = callers_k


def main() -> int:
    parser = argparse.ArgumentParser(description="inspect_symbol driver for packet_eval")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    parser.add_argument("--budget", type=int, default=4096)
    parser.add_argument("--view", default="full")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shares", default=None, help="e.g. target=0.45,callees=0.2 (P1 tree only)")
    parser.add_argument("--callers-k", type=int, default=None)
    args = parser.parse_args()

    from token_context_mcp.config import load_config
    from token_context_mcp.models import symbol_as_dict
    from token_context_mcp.retrieve.service import RetrievalService
    from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine

    _apply_constants(args.shares, args.callers_k)
    config_path = args.config.resolve()
    service = RetrievalService(load_config(config_path), config_path)
    engine = CompositeWorkflowEngine(service)
    _repo, store, _meta = service._repository_store(args.repo_id)
    by_key: dict[tuple[str, str], Any] = {}
    for sym in sorted(store.symbols(), key=lambda s: (s.path, s.start_line, s.symbol_id)):
        by_key.setdefault((sym.path, sym.qualified_name), sym)

    spec = json.loads(args.tasks.read_text(encoding="utf-8"))
    original_find = service.find_symbols
    rows: list[dict[str, Any]] = []
    for task in spec["tasks"]:
        if args.split != "all" and task.get("split") != args.split:
            continue
        key = (task["target"]["path"], task["target"]["qualified_name"])
        sym = by_key.get(key)
        if sym is None:
            rows.append({"id": task["id"], "error": f"target not in index: {key}"})
            continue

        def pinned_find(repo_id: str, *, pattern: str, _sym: Any = sym, **kw: Any) -> dict[str, Any]:
            res = original_find(repo_id, pattern=_sym.name, **{k: v for k, v in kw.items() if k != "limit"}, limit=1)
            res["data"]["symbols"] = [symbol_as_dict(_sym)]
            return res

        service.find_symbols = pinned_find  # type: ignore[method-assign]
        started = time.perf_counter()
        try:
            response = engine.inspect_symbol(args.repo_id, query=sym.name, view=args.view, budget_tokens=args.budget)
        finally:
            service.find_symbols = original_find  # type: ignore[method-assign]
        latency_ms = (time.perf_counter() - started) * 1000.0
        rows.append(
            {
                "id": task["id"],
                "target_symbol_id": sym.symbol_id,
                "budget": args.budget,
                "latency_ms": round(latency_ms, 2),
                "response": response,
            }
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} responses -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
