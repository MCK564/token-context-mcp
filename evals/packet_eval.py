"""Packet evaluation (M6.4): how much of the gold context does ``inspect_symbol(view="full")`` deliver?

Arms
* ``P0``  – pre-M6 code (``bb60f6e``) run against the same index; needs ``--p0-src`` (a ``git archive`` of ``src``).
* ``P1``  – the current tree (context packet).
* ``READ`` – reading every file that contains the target or a gold item, verbatim (token = bytes / 4).
* ``CMP``  – pairs the P0 and P1 result files of one split/budget.

Metrics (pre-registered, see docs/progress and evals/tasks/packet_token_context.json ``review_note``):
``sig_coverage`` (primary), ``ref_coverage``, ``body_coverage`` (report only), ``reach_ceiling``,
``wire_tokens`` and ``savings_vs_read``.  Gold items are matched by ``(path, qualified_name)`` in the index
of ``--repo-id`` and compared through the 8-hex compact ref.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from token_context_mcp.config import default_config_path, load_config  # noqa: E402
from token_context_mcp.retrieve.service import RetrievalService, _compact_symbol_ref  # noqa: E402
from token_context_mcp.retrieve.token_budget import estimate_tokens  # noqa: E402

from measure_context_cost import wire_tokens  # noqa: E402

OUT_DIR = HERE / "out" / "m6"
RAW_DIR = HERE.parent / "tmp" / "packet_raw"  # raw responses stay out of git (tmp/ is ignored)


def _mean(values: list[float | None]) -> float | None:
    real = [v for v in values if v is not None]
    return round(statistics.fmean(real), 4) if real else None


def _load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def _run_driver(args: argparse.Namespace, arm: str, out: Path) -> None:
    cmd = [
        sys.executable, str(HERE / "packet_driver.py"),
        "--config", str(args.config), "--repo-id", args.repo_id, "--tasks", str(args.tasks),
        "--split", args.split, "--budget", str(args.budget), "--out", str(out),
    ]
    env = dict(os.environ)
    if arm == "P0":
        if not args.p0_src:
            raise SystemExit("--p0-src is required for arm P0 (git archive bb60f6e src)")
        env["PYTHONPATH"] = str(Path(args.p0_src).resolve()) + os.pathsep + env.get("PYTHONPATH", "")
    else:
        if args.shares:
            cmd += ["--shares", args.shares]
        if args.callers_k is not None:
            cmd += ["--callers-k", str(args.callers_k)]
    subprocess.run(cmd, check=True, env=env)


def _gold_index(service: RetrievalService, repo_id: str) -> tuple[dict[tuple[str, str], list[Any]], Path]:
    repo, store, _meta = service._repository_store(repo_id)
    index: dict[tuple[str, str], list[Any]] = {}
    for sym in store.symbols():
        index.setdefault((sym.path, sym.qualified_name), []).append(sym)
    return index, Path(repo.root)


def _packet_rows(response: dict[str, Any]) -> dict[str, list[list[Any]]]:
    packet = response.get("data", {}).get("packet") or {}
    ctx = packet.get("context") or {}
    return {
        "callees": packet.get("callees") or [],
        "callers": packet.get("callers") or [],
        "more": packet.get("more") or [],
        "class_methods": ctx.get("class_methods") or [],
    }


def _p1_sets(response: dict[str, Any]) -> tuple[set[str], set[str]]:
    rows = _packet_rows(response)
    sig = {r[0] for key in ("callees", "callers", "class_methods") for r in rows[key] if len(r) > 2 and r[2]}
    anyref = {r[0] for key in rows for r in rows[key]}
    return sig, anyref


def _p0_sets(response: dict[str, Any], target_id: str) -> tuple[set[str], set[str]]:
    refs: set[str] = set()
    for rel in response.get("data", {}).get("relationships") or []:
        if not isinstance(rel, dict):
            continue
        # pre-M6 code returned raw edge dicts (source_symbol_id / target_symbol_id); later trees use source / target
        for key in ("source", "target", "source_symbol_id", "target_symbol_id"):
            value = rel.get(key)
            if isinstance(value, str) and value != target_id and ":" in value:
                refs.add(_compact_symbol_ref(value))
    return set(), refs


def _body_shown(arm: str, response: dict[str, Any]) -> bool:
    data = response.get("data", {})
    if arm == "P1":
        target = (data.get("packet") or {}).get("target") or {}
        return target.get("content") is not None and target.get("truncated_lines") is None
    return data.get("content") is not None and "content_omitted_budget" not in response.get("warnings", [])


def evaluate(args: argparse.Namespace, arm: str) -> dict[str, Any]:
    spec = json.loads(args.tasks.read_text(encoding="utf-8"))
    repo_id = args.repo_id or spec["repo_id"]
    args.repo_id = repo_id
    config_path = args.config.resolve()
    service = RetrievalService(load_config(config_path), config_path)
    gold_index, root = _gold_index(service, repo_id)
    _repo, _store, meta = service._repository_store(repo_id)

    raw_path = Path(args.raw) if args.raw else RAW_DIR / f"packet_raw_{arm}_{args.split}_{args.budget}.jsonl"
    if arm in ("P0", "P1") and not args.reuse_raw:
        _run_driver(args, arm, raw_path)
    responses = _load_jsonl(raw_path) if arm in ("P0", "P1") else {}

    tasks_out: list[dict[str, Any]] = []
    for task in spec["tasks"]:
        if args.split != "all" and task.get("split") != args.split:
            continue
        gold = task["gold_context"]
        target_key = (task["target"]["path"], task["target"]["qualified_name"])
        target_syms = gold_index.get(target_key, [])
        target_id = target_syms[0].symbol_id if target_syms else None
        gold_refs: list[tuple[dict[str, Any], set[str]]] = []
        for item in gold:
            syms = gold_index.get((item["path"], item["qualified_name"]), [])
            gold_refs.append((item, {_compact_symbol_ref(s.symbol_id) for s in syms}))

        # reach ceiling (arm independent): 1-hop under the packet filters, same class, or the class itself
        reach_hits = 0
        if target_id:
            inputs = service.packet_inputs(repo_id, symbol_id=target_id)
            reachable = {n.ref for n in (*inputs.callees, *inputs.callers, *inputs.class_methods)}
            if "." in target_syms[0].qualified_name:
                parent_qn = target_syms[0].qualified_name.rsplit(".", 1)[0]
                reachable |= {_compact_symbol_ref(s.symbol_id) for s in gold_index.get((target_syms[0].path, parent_qn), [])}
            reach_hits = sum(1 for _item, refs in gold_refs if refs & reachable)
        reach = reach_hits / len(gold) if gold else None

        read_files = {task["target"]["path"], *(item["path"] for item in gold)}
        read_tokens = 0
        for rel in sorted(read_files):
            try:
                read_tokens += estimate_tokens((root / rel).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass

        entry: dict[str, Any] = {
            "id": task["id"],
            "target": f"{target_key[0]}::{target_key[1]}",
            "n_gold": len(gold),
            "reach_ceiling": None if reach is None else round(reach, 4),
            "read_tokens": read_tokens,
        }
        if arm == "READ":
            entry.update({"wire_tokens": read_tokens, "sig_coverage": None, "ref_coverage": 1.0 if reach is not None else None})
            tasks_out.append(entry)
            continue

        row = responses.get(task["id"], {})
        response = row.get("response")
        if response is None:
            entry["error"] = row.get("error", "no response")
            tasks_out.append(entry)
            continue
        sig_refs, any_refs = _p1_sets(response) if arm == "P1" else _p0_sets(response, row.get("target_symbol_id", ""))
        sig_hit = [item for item, refs in gold_refs if refs & sig_refs]
        ref_hit = [item for item, refs in gold_refs if refs & any_refs]
        body_items = [(item, refs) for item, refs in gold_refs if item.get("need") == "body"]
        body_hit = 0
        if body_items:
            shown_target = _body_shown(arm, response)
            target_ref = _compact_symbol_ref(target_id) if target_id else None
            body_hit = sum(1 for _item, refs in body_items if shown_target and target_ref in refs)
        wire = wire_tokens(response)
        entry.update(
            {
                "sig_coverage": round(len(sig_hit) / len(gold), 4) if gold else None,
                "ref_coverage": round(len(ref_hit) / len(gold), 4) if gold else None,
                "body_coverage": round(body_hit / len(body_items), 4) if body_items else None,
                "wire_tokens": wire,
                "estimated_tokens": response.get("budget", {}).get("estimated_tokens"),
                "savings_vs_read": round(1 - wire / read_tokens, 4) if read_tokens else None,
                "truncated": bool(response.get("truncated")),
                "latency_ms": row.get("latency_ms"),
                "missing_sig": [f'{i["path"]}::{i["qualified_name"]}' for i, _r in gold_refs if i not in sig_hit] if arm == "P1" else None,
                "missing_ref": [f'{i["path"]}::{i["qualified_name"]}' for i, _r in gold_refs if i not in ref_hit],
            }
        )
        tasks_out.append(entry)

    fields = ("sig_coverage", "ref_coverage", "body_coverage", "reach_ceiling", "wire_tokens", "read_tokens", "savings_vs_read")
    overall = {f"mean_{f}": _mean([t.get(f) for t in tasks_out]) for f in fields}
    overall["tasks"] = len(tasks_out)
    overall["errors"] = sum(1 for t in tasks_out if "error" in t)
    out: dict[str, Any] = {
        "arm": arm,
        "split": args.split,
        "budget": args.budget,
        "repo_id": repo_id,
        "index_run_id": meta.get("index_run_id"),
        "tasks_file": str(args.tasks),
        "estimator": "utf8-bytes-div-4-v1",
        "overall": overall,
        "tasks": tasks_out,
    }
    if arm == "P1":
        from token_context_mcp.retrieve import packet as packet_mod

        shares = dict(packet_mod.DEFAULT_SHARES)
        callers_k = packet_mod.CALLERS_K
        if args.shares:
            shares.update({k.strip(): float(v) for k, v in (p.split("=") for p in args.shares.split(","))})
        if args.callers_k is not None:
            callers_k = args.callers_k
        out["constants"] = {"shares": shares, "callers_k": callers_k}
    return out


def compare(args: argparse.Namespace) -> dict[str, Any]:
    p0 = json.loads((OUT_DIR / f"packet_P0_{args.split}_{args.budget}.json").read_text(encoding="utf-8"))
    p1 = json.loads((OUT_DIR / f"packet_P1_{args.split}_{args.budget}.json").read_text(encoding="utf-8"))
    b_tasks = {t["id"]: t for t in p0["tasks"]}
    rows = []
    for t in p1["tasks"]:
        b = b_tasks.get(t["id"], {})
        rows.append(
            {
                "id": t["id"],
                "p0_ref_coverage": b.get("ref_coverage"),
                "p1_ref_coverage": t.get("ref_coverage"),
                "p1_sig_coverage": t.get("sig_coverage"),
                "p0_wire_tokens": b.get("wire_tokens"),
                "p1_wire_tokens": t.get("wire_tokens"),
                "read_tokens": t.get("read_tokens"),
            }
        )
    return {
        "arm": "CMP",
        "split": args.split,
        "budget": args.budget,
        "p0_index_run_id": p0.get("index_run_id"),
        "p1_index_run_id": p1.get("index_run_id"),
        "overall": {
            "p0": p0["overall"],
            "p1": p1["overall"],
            "ref_coverage_p1_minus_p0": (
                None
                if p0["overall"]["mean_ref_coverage"] is None or p1["overall"]["mean_ref_coverage"] is None
                else round(p1["overall"]["mean_ref_coverage"] - p0["overall"]["mean_ref_coverage"], 4)
            ),
        },
        "tasks": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Packet evaluation (M6.4)")
    parser.add_argument("--arm", choices=["P0", "P1", "READ", "CMP"], required=True)
    parser.add_argument("--tasks", type=Path, default=HERE / "tasks" / "packet_token_context.json")
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    parser.add_argument("--budget", type=int, default=4096)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--repo-id", default=None, help="index to evaluate against (tasks say token-context; use tc-pinned)")
    parser.add_argument("--p0-src", default=None, help="directory with the pre-M6 `src` tree (arm P0)")
    parser.add_argument("--shares", default=None, help="tuning override, e.g. target=0.4,callees=0.25 (arm P1)")
    parser.add_argument("--callers-k", type=int, default=None)
    parser.add_argument("--raw", default=None, help="raw JSONL path (default tmp/packet_raw/packet_raw_<arm>_<split>_<budget>.jsonl)")
    parser.add_argument("--reuse-raw", action="store_true", help="do not call the driver; reuse the raw JSONL")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--print-tasks", action="store_true")
    args = parser.parse_args()

    if args.arm == "CMP":
        result = compare(args)
        default_name = f"packet_CMP_{args.split}_{args.budget}.json"
    else:
        result = evaluate(args, args.arm)
        default_name = f"packet_{args.arm}_{args.split}_{args.budget}.json"
    out_path = args.output or OUT_DIR / default_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["overall"], indent=2, ensure_ascii=False))
    if args.print_tasks:
        for t in result["tasks"]:
            print({k: t.get(k) for k in ("id", "sig_coverage", "ref_coverage", "reach_ceiling", "wire_tokens", "read_tokens")})
    print(f"-> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
