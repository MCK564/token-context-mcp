"""Live MCP stdio multi-step (steps >= 2) agent evaluation for Verified Evidence Ledger.

Spawns real `python -m token_context_mcp serve` over stdio JSON-RPC and measures:
1. Natural `prior_evidence` hit rate on q2/q3 follow-ups after `trajectory_record(..., steps>=2)`.
2. Token savings (`o200k_base`) when an agent checks `prior_evidence` first and skips redundant
   `search_source` + `get_symbol_context` calls vs baseline (`ledger.enabled=False`).
3. Multi-step prefix invalidation (`VERIFY_FAILED` + `recheck_from`) when an intermediate step
   file is modified and re-indexed between MCP turns.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from token_context_mcp.config import default_config_path, index_directory, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.models import AppConfig, LedgerConfig, ServerConfig

ROOT = Path(__file__).resolve().parents[1]
TASK_FILES = [
    ROOT / "evals" / "tasks" / "chain_rich.json",
    ROOT / "evals" / "tasks" / "chain_fastify.json",
]


def _count_o200k(text: str) -> tuple[int, str]:
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text)), "o200k_base"
    except Exception:
        return max(1, (len(text.encode("utf-8")) + 3) // 4), "utf8-bytes-div-4-v1"


def _payload_tokens(result: Any) -> tuple[int, str]:
    sc = getattr(result, "structured_content", None)
    if sc is not None:
        raw = json.dumps(sc, ensure_ascii=False, separators=(",", ":"))
    else:
        raw = "\n".join(getattr(c, "text", "") for c in getattr(result, "content", []))
    return _count_o200k(raw)


def _extract_symbol_ids(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("symbols", "matches", "results", "neighbors", "callers", "callees"):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("symbol_id"):
                    out.append(str(item["symbol_id"]))
                elif isinstance(item, list) and item:
                    out.append(str(item[0]))
    return list(dict.fromkeys(out))


async def _find_target_symbol(
    client: Client, repo_id: str, gold_symbols: list[dict[str, Any]]
) -> tuple[str, int] | None:
    if not gold_symbols:
        return None
    gs = gold_symbols[0]
    qname = str(gs.get("qualified_name", ""))
    path = str(gs.get("path", ""))
    short_name = qname.split(".")[-1]
    res = await client.call_tool(
        "find_symbols",
        {"repo_id": repo_id, "pattern": short_name, "limit": 20},
    )
    data = (res.structured_content or {}).get("data", {})
    items = data.get("symbols") or data.get("matches") or []
    for sym in items:
        if sym.get("path") == path and sym.get("qualified_name") == qname:
            return str(sym["symbol_id"]), int(sym.get("start_line") or 1)
    for sym in items:
        if sym.get("path") == path:
            return str(sym["symbol_id"]), int(sym.get("start_line") or 1)
    return None


async def _run_mcp_arm(
    base_config_path: Path,
    *,
    ledger_enabled: bool,
    limit_chains: int = 8,
) -> dict[str, Any]:
    base_cfg = load_config(base_config_path)
    src_idx_dir = index_directory(base_config_path)

    with tempfile.TemporaryDirectory(prefix=f"tcmcp_mcpeval_{int(ledger_enabled)}_", ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        eval_cfg_path = tmp / "repos.toml"
        eval_idx_dir = tmp / "indexes"
        eval_idx_dir.mkdir(parents=True, exist_ok=True)

        # Share existing snapshots read-only via copy for active repo pointers
        needed_repos = {}
        for tf in TASK_FILES:
            payload = json.loads(tf.read_text(encoding="utf-8"))
            rid = payload["repo_id"]
            if rid in base_cfg.repositories:
                needed_repos[rid] = base_cfg.repositories[rid]
                for p in src_idx_dir.glob(f"{rid}*"):
                    if p.is_file():
                        shutil.copy2(p, eval_idx_dir / p.name)

        cfg = AppConfig(
            repositories=needed_repos,
            server=ServerConfig(
                max_result_tokens=8192,
                output_mode="structured",
                enable_extensions=True,
                enable_admin_tools=False,
            ),
            ledger=LedgerConfig(enabled=ledger_enabled, overlay_enabled=False),
        )
        save_config(eval_cfg_path, cfg)

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "token_context_mcp", "serve", "--config", str(eval_cfg_path)],
        )

        followup_tokens: list[int] = []
        tokenizer_name = "o200k_base"
        natural_hits = 0
        search_skipped = 0
        total_followups = 0
        multistep_cards_recorded = 0
        chain_details: list[dict[str, Any]] = []

        async with Client(stdio_client(params)) as client:
            tools_res = await client.list_tools()
            tool_names = {t.name for t in tools_res.tools}
            assert "trajectory_record" in tool_names

            for tf in TASK_FILES:
                doc = json.loads(tf.read_text(encoding="utf-8"))
                repo_id = doc["repo_id"]
                if repo_id not in needed_repos:
                    continue

                for chain in doc["chains"][:limit_chains]:
                    q1 = chain["q1"]
                    q1_found = await _find_target_symbol(client, repo_id, q1["gold_symbols"])
                    if not q1_found:
                        continue
                    q1_sym, q1_line = q1_found

                    # Cold q1 multi-hop discovery: map -> search -> context -> inspect
                    r_map = await client.call_tool(
                        "get_repo_map",
                        {"repo_id": repo_id, "query": q1["query"], "budget_tokens": 1024},
                    )
                    await client.call_tool(
                        "search_source",
                        {"repo_id": repo_id, "query": q1["query"], "budget_tokens": 1024},
                    )
                    r_ctx = await client.call_tool(
                        "get_symbol_context",
                        {"repo_id": repo_id, "symbol_id": q1_sym, "budget_tokens": 1024},
                    )
                    await client.call_tool(
                        "inspect_symbol",
                        {"repo_id": repo_id, "symbol_id": q1_sym, "max_tokens": 1024},
                    )

                    # Build >= 2 intermediate steps from discovered symbols
                    ctx_data = (r_ctx.structured_content or {}).get("data", {})
                    map_data = (r_map.structured_content or {}).get("data", {})
                    candidates = _extract_symbol_ids(ctx_data) + _extract_symbol_ids(map_data)
                    step_syms = [s for s in candidates if s != q1_sym][:2]
                    if len(step_syms) < 2:
                        step_syms = [q1_sym, q1_sym]

                    # Also find decoy symbol if possible from map
                    decoys = [
                        f"{s}!not_relevant"
                        for s in _extract_symbol_ids(map_data)
                        if s != q1_sym and s not in step_syms
                    ][:1]

                    if ledger_enabled:
                        # Record multi-step card with >= 2 steps for q1 query
                        rec_res = await client.call_tool(
                            "trajectory_record",
                            {
                                "repo_id": repo_id,
                                "query": q1["query"],
                                "answers": [f"{q1_sym}@{q1_line}"],
                                "steps": [f"{step_syms[0]}>{step_syms[1]}@1", f"{step_syms[1]}>{q1_sym}@{q1_line}"],
                                "decoys": decoys,
                            },
                        )
                        rec_data = (rec_res.structured_content or {}).get("data", {})
                        if rec_data.get("card_id"):
                            multistep_cards_recorded += 1

                    # Follow-ups: q1_paraphrase (re-phrased follow-up) + q2 + q3
                    q1_words = [w for w in q1["query"].split() if len(w) > 2]
                    paraphrase_q = " ".join(q1_words[:5]) if len(q1_words) >= 3 else q1["query"]
                    followup_items = [
                        ("q1_paraphrase", {"query": paraphrase_q, "gold_symbols": q1["gold_symbols"]}),
                        ("q2", chain["q2"]),
                        ("q3", chain["q3"]),
                    ]
                    for qkey, qobj in followup_items:
                        target_found = await _find_target_symbol(client, repo_id, qobj["gold_symbols"])
                        if not target_found:
                            continue
                        target_sym, _ = target_found
                        total_followups += 1
                        turn_tokens = 0

                        # Step 1 of follow-up: lightweight map lookup (which carries prior_evidence)
                        rmap = await client.call_tool(
                            "get_repo_map",
                            {"repo_id": repo_id, "query": qobj["query"], "budget_tokens": 1024},
                        )
                        toks, tokenizer_name = _payload_tokens(rmap)
                        turn_tokens += toks

                        pe = ((rmap.structured_content or {}).get("data") or {}).get("prior_evidence")
                        hit_valid = bool(pe and isinstance(pe, dict) and pe.get("answers"))
                        if hit_valid:
                            natural_hits += 1

                        if ledger_enabled and hit_valid:
                            # Agent sees prior_evidence -> skips search_source & get_symbol_context!
                            search_skipped += 1
                            r_ins = await client.call_tool(
                                "inspect_symbol",
                                {"repo_id": repo_id, "symbol_id": target_sym, "max_tokens": 1024},
                            )
                            toks_ins, _ = _payload_tokens(r_ins)
                            turn_tokens += toks_ins
                        else:
                            # Baseline or miss: agent must run search_source + get_symbol_context + inspect_symbol
                            r_src = await client.call_tool(
                                "search_source",
                                {"repo_id": repo_id, "query": qobj["query"], "budget_tokens": 1024},
                            )
                            r_c = await client.call_tool(
                                "get_symbol_context",
                                {"repo_id": repo_id, "symbol_id": target_sym, "budget_tokens": 1024},
                            )
                            r_i = await client.call_tool(
                                "inspect_symbol",
                                {"repo_id": repo_id, "symbol_id": target_sym, "max_tokens": 1024},
                            )
                            for r in (r_src, r_c, r_i):
                                t_r, _ = _payload_tokens(r)
                                turn_tokens += t_r

                        followup_tokens.append(turn_tokens)
                        chain_details.append(
                            {
                                "chain_id": chain["id"],
                                "turn": qkey,
                                "hit_prior_evidence": hit_valid,
                                "skipped_search": bool(ledger_enabled and hit_valid),
                                "tokens": turn_tokens,
                            }
                        )

        return {
            "tokenizer": tokenizer_name,
            "total_followups": total_followups,
            "natural_hits": natural_hits,
            "natural_hit_rate": round(natural_hits / max(1, total_followups), 4),
            "search_source_skipped": search_skipped,
            "multistep_cards_recorded": multistep_cards_recorded,
            "median_followup_tokens": round(statistics.median(followup_tokens), 2) if followup_tokens else 0.0,
            "mean_followup_tokens": round(statistics.mean(followup_tokens), 2) if followup_tokens else 0.0,
            "details": chain_details,
        }


async def _run_stale_multistep_check() -> dict[str, Any]:
    """Verify multi-step (steps=2) prefix invalidation over real MCP stdio after file edit."""
    with tempfile.TemporaryDirectory(prefix="tcmcp_mcpstale_", ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        repo = tmp / "sample_repo"
        repo.mkdir()
        (repo / "target_mod.py").write_text("def final_target():\n    return 42\n", encoding="utf-8")
        (repo / "step_two.py").write_text(
            "from target_mod import final_target\n\ndef step_two():\n    return final_target()\n",
            encoding="utf-8",
        )
        (repo / "step_one.py").write_text(
            "from step_two import step_two\n\ndef step_one():\n    return step_two()\n",
            encoding="utf-8",
        )

        cfg_path = tmp / "repos.toml"
        idx_dir = tmp / "indexes"
        from token_context_mcp.models import RepositoryConfig

        cfg = AppConfig(
            repositories={"stale-demo": RepositoryConfig(repo_id="stale-demo", root=repo)},
            server=ServerConfig(output_mode="structured", enable_extensions=True),
            ledger=LedgerConfig(enabled=True, overlay_enabled=False),
        )
        save_config(cfg_path, cfg)
        build_index(cfg.repositories["stale-demo"], idx_dir, network_policy="declared-deny-not-enforced")

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "token_context_mcp", "serve", "--config", str(cfg_path)],
        )
        async with Client(stdio_client(params)) as client:
            f1 = await _find_target_symbol(client, "stale-demo", [{"path": "step_one.py", "qualified_name": "step_one"}])
            f2 = await _find_target_symbol(client, "stale-demo", [{"path": "step_two.py", "qualified_name": "step_two"}])
            fans = await _find_target_symbol(client, "stale-demo", [{"path": "target_mod.py", "qualified_name": "final_target"}])
            assert f1 and f2 and fans
            s1, l1 = f1
            s2, l2 = f2
            ans, lans = fans

            await client.call_tool(
                "trajectory_record",
                {
                    "repo_id": "stale-demo",
                    "query": "locate final_target execution pipeline",
                    "answers": [f"{ans}@{lans}"],
                    "steps": [f"{s1}>{s2}@4", f"{s2}>{ans}@4"],
                },
            )
            hit_before = await client.call_tool(
                "get_repo_map",
                {"repo_id": "stale-demo", "query": "locate final_target execution pipeline", "budget_tokens": 1024},
            )
            pe_before = ((hit_before.structured_content or {}).get("data") or {}).get("prior_evidence")

        # Mutate step_two.py on disk and re-index
        (repo / "step_two.py").write_text(
            "from target_mod import final_target\n\ndef step_two():\n    return final_target() + 999\n",
            encoding="utf-8",
        )
        build_index(cfg.repositories["stale-demo"], idx_dir, network_policy="declared-deny-not-enforced")

        async with Client(stdio_client(params)) as client:
            hit_after = await client.call_tool(
                "get_repo_map",
                {"repo_id": "stale-demo", "query": "locate final_target execution pipeline", "budget_tokens": 1024},
            )
            sc_after = hit_after.structured_content or {}
            pe_after = (sc_after.get("data") or {}).get("prior_evidence") or {}
            warnings_after = sc_after.get("warnings") or []

        steps_before = pe_before.get("steps") if isinstance(pe_before, dict) else []
        return {
            "before_steps_valid": bool(len(steps_before) == 2 and all(st[-1] == "valid" for st in steps_before)),
            "after_recheck_from": pe_after.get("recheck_from"),
            "after_verify_failed": any("VERIFY_FAILED" in str(w) or "recheck_from" in str(w) for w in warnings_after)
            or pe_after.get("recheck_from") is not None,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live MCP stdio multi-step (steps >= 2) ledger eval")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--limit-chains", type=int, default=8)
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "reports" / "mcp_chain_eval.json")
    args = parser.parse_args(argv)

    async def _run_all() -> dict[str, Any]:
        baseline = await _run_mcp_arm(args.config, ledger_enabled=False, limit_chains=args.limit_chains)
        ledger = await _run_mcp_arm(args.config, ledger_enabled=True, limit_chains=args.limit_chains)
        stale_check = await _run_stale_multistep_check()

        base_med = baseline["median_followup_tokens"]
        led_med = ledger["median_followup_tokens"]
        savings_pct = round(((base_med - led_med) / base_med) * 100.0, 2) if base_med > 0 else 0.0

        return {
            "schema_version": "1.0",
            "mode": "live_mcp_stdio",
            "tokenizer": ledger["tokenizer"],
            "baseline_no_ledger": {k: v for k, v in baseline.items() if k != "details"},
            "ledger_multistep": {k: v for k, v in ledger.items() if k != "details"},
            "median_followup_token_savings_pct": savings_pct,
            "stale_multistep_invalidation": stale_check,
        }

    report = asyncio.run(_run_all())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
