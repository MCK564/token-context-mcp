"""Deterministic chain evaluation harness (L0 Go/No-Go and L1-L5 KPIs)."""
from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from measure_context_cost import wire_tokens  # noqa: E402
from token_context_mcp.config import default_config_path, index_directory, load_config  # noqa: E402
from token_context_mcp.index.runner import database_path  # noqa: E402
from token_context_mcp.index.sqlite_store import SQLiteStore  # noqa: E402
from token_context_mcp.ledger.service import LedgerService  # noqa: E402
from token_context_mcp.ledger.signature import build_query_signature, extract_atomic_stems  # noqa: E402
from token_context_mcp.ledger.store import LedgerStore  # noqa: E402
from token_context_mcp.models import AppConfig, LedgerConfig  # noqa: E402
from token_context_mcp.retrieve.service import RetrievalService  # noqa: E402
from token_context_mcp.retrieve.token_budget import count_tokens_o200k  # noqa: E402


def _extract_search_hits(response: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return list of (symbol_id, path, qualified_name) from search_source response."""
    data = response.get("data", {})
    hits: list[tuple[str, str, str]] = []
    for key in ("results", "matches", "symbols"):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("symbol_id") or item.get("id") or "")
                path = str(item.get("path") or "")
                qname = str(item.get("qualified_name") or item.get("name") or "")
                if not qname and sid.count(":") >= 3:
                    parts = sid.split(":")
                    qname = ":".join(parts[2:-1])
                if sid or (path and qname):
                    hits.append((sid, path, qname))
    return hits


def _extract_root_symbol(ctx_resp: dict[str, Any]) -> dict[str, Any]:
    data = ctx_resp.get("data", {})
    syms = data.get("symbols")
    if isinstance(syms, list) and syms and isinstance(syms[0], dict):
        inner = syms[0].get("symbol")
        if isinstance(inner, dict):
            return inner
    sym = data.get("symbol")
    return sym if isinstance(sym, dict) else {}


def _paraphrase_query(query: str, answer_qname: str) -> str:
    """Create a realistic paraphrase by dropping one non-identifier context word when possible."""
    ans_stems = extract_atomic_stems(answer_qname)
    words = query.split()
    if len(words) <= 3:
        return query
    for idx in range(len(words) - 1, -1, -1):
        w_stems = extract_atomic_stems(words[idx])
        if w_stems and not (w_stems & ans_stems):
            candidate = " ".join(words[:idx] + words[idx + 1 :])
            if len(build_query_signature(candidate).tokens) >= 2:
                return candidate
    return query


def _run_no_ledger_turn(
    service: RetrievalService,
    repo_id: str,
    query: str,
    gold_keys: set[tuple[str, str]],
    gold_files: set[str],
) -> dict[str, Any]:
    tokens = 0
    calls = 0

    search_resp = service.search_source(repo_id, query=query, profile="locate")
    tokens += wire_tokens(search_resp)
    calls += 1

    hits = _extract_search_hits(search_resp)
    hit_files = [p for _, p, _ in hits[:5]]
    file_acc_5 = 1.0 if any(f in gold_files for f in hit_files) else 0.0
    sym_recall_10 = 1.0 if any((p, q) in gold_keys for _, p, q in hits[:10]) else 0.0
    rank1_acc = 1.0 if (hits and (hits[0][1], hits[0][2]) in gold_keys) else 0.0

    found_gold = False
    inspected_decoys: list[str] = []
    for sid, path, qname in hits[:3]:
        if not sid:
            continue
        ctx_resp = service.symbol_context(repo_id, symbol_id=sid, include_body=True)
        tokens += wire_tokens(ctx_resp)
        calls += 1
        if (path, qname) in gold_keys:
            found_gold = True
            break
        if not sid.endswith(":<module>"):
            inspected_decoys.append(sid)

    if not found_gold:
        map_resp = service.repo_map(repo_id, query=query, format="compact")
        tokens += wire_tokens(map_resp)
        calls += 1
        entries = map_resp.get("data", {}).get("symbols", [])
        for entry in entries[:2]:
            if isinstance(entry, list) and entry:
                sid = str(entry[0])
                ctx_resp = service.symbol_context(repo_id, symbol_id=sid, include_body=True)
                tokens += wire_tokens(ctx_resp)
                calls += 1
                sym = _extract_root_symbol(ctx_resp)
                if (sym.get("path"), sym.get("qualified_name")) in gold_keys:
                    found_gold = True
                    break

    if not found_gold:
        sig_tokens = build_query_signature(query).tokens
        kw = sig_tokens[0] if sig_tokens else query.split()[0]
        find_resp = service.find_symbols(repo_id, pattern=kw, limit=5)
        tokens += wire_tokens(find_resp)
        calls += 1
        for sym_item in find_resp.get("data", {}).get("symbols", [])[:1]:
            sid = str(sym_item.get("symbol_id") or "")
            if sid:
                ctx_resp = service.symbol_context(repo_id, symbol_id=sid, include_body=True)
                tokens += wire_tokens(ctx_resp)
                calls += 1
                if (sym_item.get("path"), sym_item.get("qualified_name")) in gold_keys:
                    found_gold = True

    return {
        "tokens": tokens,
        "calls": calls,
        "file_acc_5": file_acc_5,
        "sym_recall_10": sym_recall_10,
        "rank1_acc": rank1_acc,
        "found_gold": found_gold,
        "inspected_decoys": inspected_decoys,
    }


def _run_ledger_turn(
    service: RetrievalService,
    repo_id: str,
    query: str,
    gold_keys: set[tuple[str, str]],
    gold_files: set[str],
    *,
    chain_prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a turn with Ledger enabled (L2 hint or L3 hint+overlay)."""
    tokens = 0
    calls = 0

    search_resp = service.search_source(repo_id, query=query, profile="locate")
    prior = search_resp.get("data", {}).get("prior_evidence") or chain_prior

    # Measure pure ledger lookup + verification latency
    elapsed_ms = 0.0
    if service._ledger_verifier is not None and service._ledger_store is not None:
        repo_cfg, idx_store, _ = service._repository_store(repo_id)
        t0 = time.perf_counter()
        service._ledger_verifier.lookup_prior_evidence(
            repo_id=repo_id,
            query=query,
            ledger_store=service._ledger_store,
            idx_store=idx_store,
            root=repo_cfg.root,
            allow_symlinks=repo_cfg.allow_symlinks,
            cfg=service.config.ledger,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

    hits = _extract_search_hits(search_resp)
    hit_files = [p for _, p, _ in hits[:5]]
    file_acc_5 = 1.0 if any(f in gold_files for f in hit_files) else 0.0
    sym_recall_10 = 1.0 if any((p, q) in gold_keys for _, p, q in hits[:10]) else 0.0
    rank1_acc = 1.0 if (hits and (hits[0][1], hits[0][2]) in gold_keys) else 0.0

    hint_toks = 0
    if prior is not None:
        hint_toks, _ = count_tokens_o200k(json.dumps(prior, separators=(",", ":")))

    found_gold = False
    if prior is not None and prior.get("answers"):
        ans = prior["answers"][0]
        ans_sid = str(ans[0])
        tokens += wire_tokens(search_resp)
        calls += 1
        ctx_resp = service.symbol_context(repo_id, symbol_id=ans_sid, include_body=True)
        tokens += wire_tokens(ctx_resp)
        calls += 1
        sym = _extract_root_symbol(ctx_resp)
        if (sym.get("path"), sym.get("qualified_name")) in gold_keys:
            found_gold = True
            return {
                "tokens": tokens,
                "calls": calls,
                "file_acc_5": 1.0,
                "sym_recall_10": 1.0,
                "rank1_acc": rank1_acc,
                "found_gold": True,
                "hint_tokens": hint_toks,
                "elapsed_ms": elapsed_ms,
                "prior_hit": True,
            }

    # If no prior_evidence or prior answer wasn't gold, continue standard candidate inspection
    if calls == 0:
        tokens += wire_tokens(search_resp)
        calls += 1
    for sid, path, qname in hits[:3]:
        if not sid:
            continue
        ctx_resp = service.symbol_context(repo_id, symbol_id=sid, include_body=True)
        tokens += wire_tokens(ctx_resp)
        calls += 1
        if (path, qname) in gold_keys:
            found_gold = True
            break

    if not found_gold:
        map_resp = service.repo_map(repo_id, query=query, format="compact")
        tokens += wire_tokens(map_resp)
        calls += 1
        entries = map_resp.get("data", {}).get("symbols", [])
        for entry in entries[:2]:
            if isinstance(entry, list) and entry:
                sid = str(entry[0])
                ctx_resp = service.symbol_context(repo_id, symbol_id=sid, include_body=True)
                tokens += wire_tokens(ctx_resp)
                calls += 1
                sym = _extract_root_symbol(ctx_resp)
                if (sym.get("path"), sym.get("qualified_name")) in gold_keys:
                    found_gold = True
                    break

    if not found_gold:
        sig_tokens = build_query_signature(query).tokens
        kw = sig_tokens[0] if sig_tokens else query.split()[0]
        find_resp = service.find_symbols(repo_id, pattern=kw, limit=5)
        tokens += wire_tokens(find_resp)
        calls += 1
        for sym_item in find_resp.get("data", {}).get("symbols", [])[:1]:
            sid = str(sym_item.get("symbol_id") or "")
            if sid:
                ctx_resp = service.symbol_context(repo_id, symbol_id=sid, include_body=True)
                tokens += wire_tokens(ctx_resp)
                calls += 1
                if (sym_item.get("path"), sym_item.get("qualified_name")) in gold_keys:
                    found_gold = True

    return {
        "tokens": tokens,
        "calls": calls,
        "file_acc_5": file_acc_5,
        "sym_recall_10": sym_recall_10,
        "rank1_acc": rank1_acc,
        "found_gold": found_gold,
        "hint_tokens": hint_toks,
        "elapsed_ms": elapsed_ms,
        "prior_hit": prior is not None,
    }


def _run_oracle_ledger_turn(
    service: RetrievalService,
    store: SQLiteStore,
    repo_id: str,
    query: str,
    gold_symbols: list[dict[str, str]],
) -> dict[str, Any]:
    """Oracle arm: Q2/Q3 receives a 1-card verified prior_evidence hint and goes straight to symbol_context."""
    target_sid = None
    target_path = gold_symbols[0]["path"]
    target_qname = gold_symbols[0]["qualified_name"]
    for sym in store.symbols():
        if sym.path == target_path and sym.qualified_name == target_qname:
            target_sid = sym.symbol_id
            break

    if target_sid is None:
        return _run_no_ledger_turn(
            service,
            repo_id,
            query,
            {(target_path, target_qname)},
            {target_path},
        )

    prior_hint = {
        "prior_evidence": {
            "ledger_rev": 1,
            "match": 1.0,
            "status": "confirmed",
            "answers": [[target_sid, target_path, 1, "valid"]],
            "steps": [],
            "decoys": [],
            "recheck_from": None,
        }
    }
    ctx_resp = service.symbol_context(repo_id, symbol_id=target_sid, include_body=True)
    hint_tokens, _ = count_tokens_o200k(json.dumps(prior_hint))
    return {
        "tokens": wire_tokens(ctx_resp) + hint_tokens,
        "calls": 1,
        "file_acc_5": 1.0,
        "sym_recall_10": 1.0,
        "found_gold": True,
    }


def _bootstrap_ci95(diffs: list[float], n_boot: int = 2000, seed: int = 20261113) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    if n == 0:
        return 0.0, 0.0
    medians = []
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        medians.append(statistics.median(sample))
    medians.sort()
    lo = medians[int(0.025 * n_boot)]
    hi = medians[int(0.975 * n_boot)]
    return round(lo, 2), round(hi, 2)


def _evaluate_mutations(
    data: dict[str, Any],
    store: SQLiteStore,
    base_config: AppConfig,
    tmp_cfg_path: Path,
) -> dict[str, Any]:
    """Evaluate L-3 invalidation accuracy on all code mutations in the task file."""
    repo_id = data["repo_id"]
    repo_root = base_config.repositories[repo_id].root
    sym_by_key = {(s.path, s.qualified_name): s for s in store.symbols()}
    file_by_path = {f.path: f for f in store.files()}

    stale_prevented = 0
    stale_total = 0
    valid_preserved = 0
    valid_total = 0

    mut_cfg_dir = tmp_cfg_path.parent / f"mut_{repo_id}"
    mut_cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg_on = AppConfig(
        server=base_config.server,
        repositories=base_config.repositories,
        budget_profiles=base_config.budget_profiles,
        ledger=LedgerConfig(enabled=True, overlay_enabled=True),
    )
    lsvc = LedgerService(cfg_on, default_config_path())
    lsvc.store = LedgerStore(mut_cfg_dir / "ledger.sqlite")
    rsvc = RetrievalService(cfg_on, default_config_path())
    rsvc._ledger_store = lsvc.store
    from token_context_mcp.ledger.verify import LedgerVerifier
    rsvc._ledger_verifier = LedgerVerifier()

    for mut in data.get("mutations", []):
        kind = mut["kind"]
        path = mut["path"]
        qname = mut["qualified_name"]
        sym = sym_by_key[(path, qname)]
        query = f"inspect {qname.replace('.', ' ')} in {path}"

        # Record confirmed card
        lsvc.trajectory_record(
            repo_id=repo_id,
            query=query,
            answers=[f"{sym.symbol_id}@{sym.start_line}"],
            run_id="mut_r1",
            agent_id=f"mut_{mut['id']}_1",
        )
        lsvc.trajectory_record(
            repo_id=repo_id,
            query=query,
            answers=[f"{sym.symbol_id}@{sym.start_line}"],
            run_id="mut_r2",
            agent_id=f"mut_{mut['id']}_2",
        )

        target_file = repo_root / path
        orig_bytes = target_file.read_bytes()
        try:
            if kind == "edit_body":
                stale_total += 1
                # Mutate bytes inside the symbol body on disk
                mut_bytes = (
                    orig_bytes[: sym.start_byte]
                    + b"/* mutated_body_sentinel */\n"
                    + orig_bytes[sym.start_byte + min(28, sym.end_byte - sym.start_byte) :]
                )
                target_file.write_bytes(mut_bytes)
                assert rsvc._ledger_verifier is not None
                rsvc._ledger_verifier._body_cache.clear()
                pe, _, _ = rsvc._ledger_verifier.lookup_prior_evidence(
                    repo_id=repo_id,
                    query=query,
                    ledger_store=lsvc.store,
                    idx_store=store,
                    root=repo_root,
                    allow_symlinks=False,
                    cfg=cfg_on.ledger,
                )
                if pe is None:
                    stale_prevented += 1

            elif kind == "rename_symbol":
                stale_total += 1
                # Simulate symbol rename by removing (path, qname) from active symbol map or renaming on disk
                mut_bytes = (
                    orig_bytes[: sym.start_byte]
                    + orig_bytes[sym.start_byte : sym.end_byte].replace(
                        sym.name.encode("utf-8"), f"{sym.name}_renamed".encode("utf-8"), 1
                    )
                    + orig_bytes[sym.end_byte :]
                )
                target_file.write_bytes(mut_bytes)
                assert rsvc._ledger_verifier is not None
                rsvc._ledger_verifier._body_cache.clear()
                pe, _, _ = rsvc._ledger_verifier.lookup_prior_evidence(
                    repo_id=repo_id,
                    query=query,
                    ledger_store=lsvc.store,
                    idx_store=store,
                    root=repo_root,
                    allow_symlinks=False,
                    cfg=cfg_on.ledger,
                )
                if pe is None:
                    stale_prevented += 1

            elif kind == "insert_lines_above":
                valid_total += 1
                # Insert 3 comment lines at the top of the file above the symbol
                prefix = b"# shifted line 1\n# shifted line 2\n# shifted line 3\n"
                target_file.write_bytes(prefix + orig_bytes)
                assert rsvc._ledger_verifier is not None
                rsvc._ledger_verifier._body_cache.clear()
                pe, _, _ = rsvc._ledger_verifier.lookup_prior_evidence(
                    repo_id=repo_id,
                    query=query,
                    ledger_store=lsvc.store,
                    idx_store=store,
                    root=repo_root,
                    allow_symlinks=False,
                    cfg=cfg_on.ledger,
                )
                if pe is not None and pe["answers"][0][3] == "valid":
                    valid_preserved += 1

            elif kind == "edit_sibling_in_file":
                valid_total += 1
                sib_qname = mut["sibling"]
                sib_sym = sym_by_key[(path, sib_qname)]
                # Edit the sibling's body (even changing its byte length!) without touching target symbol's body
                replacement = b"/* sibling_edited_extra_bytes */\n"
                mut_bytes = (
                    orig_bytes[: sib_sym.start_byte]
                    + replacement
                    + orig_bytes[sib_sym.end_byte :]
                )
                target_file.write_bytes(mut_bytes)
                assert rsvc._ledger_verifier is not None
                rsvc._ledger_verifier._body_cache.clear()
                pe, _, _ = rsvc._ledger_verifier.lookup_prior_evidence(
                    repo_id=repo_id,
                    query=query,
                    ledger_store=lsvc.store,
                    idx_store=store,
                    root=repo_root,
                    allow_symlinks=False,
                    cfg=cfg_on.ledger,
                )
                if pe is not None and pe["answers"][0][3] == "valid":
                    valid_preserved += 1
        finally:
            target_file.write_bytes(orig_bytes)

    return {
        "stale_prevented": stale_prevented,
        "stale_total": stale_total,
        "valid_preserved": valid_preserved,
        "valid_total": valid_total,
        "file_by_path_checked": len(file_by_path),
    }


def _evaluate_poisoning(
    data: dict[str, Any],
    store: SQLiteStore,
    base_config: AppConfig,
    tmp_cfg_path: Path,
) -> dict[str, Any]:
    """Evaluate L-4 anti-poisoning gate across all poisoning cases in the task file."""
    repo_id = data["repo_id"]
    sym_by_key = {(s.path, s.qualified_name): s for s in store.symbols()}
    pois_dir = tmp_cfg_path.parent / f"pois_{repo_id}"
    pois_dir.mkdir(parents=True, exist_ok=True)

    cfg_on = AppConfig(
        server=base_config.server,
        repositories=base_config.repositories,
        budget_profiles=base_config.budget_profiles,
        ledger=LedgerConfig(enabled=True),
    )
    lsvc = LedgerService(cfg_on, default_config_path())
    lsvc.store = LedgerStore(pois_dir / "ledger.sqlite")
    any_valid_sym = next(iter(sym_by_key.values()))
    from token_context_mcp.kernel.pipeline import StructuredToolError

    rejected_cases = 0
    total_cases = 0
    for p in data.get("poisoning", []):
        total_cases += 1
        kind = p["kind"]
        aid = f"pois_{p['id']}"
        if kind == "unknown_symbol":
            res = lsvc.trajectory_record(repo_id=repo_id, query="test unknown", answers=p["answers"], run_id="p1", agent_id=aid)
            if res["data"]["card_id"] is None and res["data"]["answers"][0]["status"] == "rejected":
                rejected_cases += 1
        elif kind == "line_outside_symbol":
            sym = sym_by_key[(p["path"], p["qualified_name"])]
            res = lsvc.trajectory_record(
                repo_id=repo_id, query="test line outside", answers=[f"{sym.symbol_id}@{p['line']}"], run_id="p1", agent_id=aid
            )
            if res["data"]["card_id"] is None and res["data"]["answers"][0]["reason"] == "line_outside_symbol":
                rejected_cases += 1
        elif kind == "evidence_mismatch":
            fp, fq = p["from"].rsplit(":", 1)
            tp, tq = p["to"].rsplit(":", 1)
            fsym = sym_by_key[(fp, fq)]
            tsym = sym_by_key[(tp, tq)]
            res = lsvc.trajectory_record(
                repo_id=repo_id,
                query="test mismatch",
                answers=[f"{fsym.symbol_id}@{fsym.start_line}"],
                steps=[f"{fsym.symbol_id}>{tsym.symbol_id}@{fsym.start_line}"],
                run_id="p1",
                agent_id=aid,
            )
            if res["data"]["steps"][0]["status"] == "rejected":
                rejected_cases += 1
        elif kind == "injection_in_query":
            res = lsvc.trajectory_record(
                repo_id=repo_id,
                query=p["query"],
                answers=[f"{any_valid_sym.symbol_id}@{any_valid_sym.start_line}"],
                run_id="p1",
                agent_id=aid,
            )
            cards = lsvc.store.list_cards(repo_id=repo_id)
            raw_leaked = any(p["query"] in json.dumps(c.__dict__, default=str) for c in cards)
            if not raw_leaked:
                rejected_cases += 1
        elif kind in ("too_many_answers", "too_many_steps", "too_many_decoys", "limit_exceeded"):
            ans_cnt = int(p.get("answers_count") or (p.get("count") if kind == "too_many_answers" else 1) or 1)
            step_cnt = int(p.get("steps_count") or (p.get("count") if kind == "too_many_steps" else 0) or 0)
            dec_cnt = int(p.get("decoys_count") or (p.get("count") if kind == "too_many_decoys" else 0) or 0)
            ans = [f"{any_valid_sym.symbol_id}@{any_valid_sym.start_line}"] * ans_cnt
            steps = [f"{any_valid_sym.symbol_id}>{any_valid_sym.symbol_id}@{any_valid_sym.start_line}"] * step_cnt
            decs = [f"{any_valid_sym.symbol_id}!unrelated"] * dec_cnt
            try:
                lsvc.trajectory_record(
                    repo_id=repo_id,
                    query="test limits",
                    answers=ans,
                    steps=steps,
                    decoys=decs,
                    run_id="p1",
                    agent_id=aid,
                )
            except StructuredToolError as exc:
                if exc.code == "limit_exceeded":
                    rejected_cases += 1
        elif kind in ("invalid_reason_code", "invalid_decoy_reason"):
            bad_reason = p.get("reason") or p.get("reason_code") or "bad_reason"
            res = lsvc.trajectory_record(
                repo_id=repo_id,
                query="test bad reason",
                answers=[f"{any_valid_sym.symbol_id}@{any_valid_sym.start_line}"],
                decoys=[f"{any_valid_sym.symbol_id}!{bad_reason}"],
                run_id="p1",
                agent_id=aid,
            )
            if res["data"]["decoys"][0]["status"] == "rejected" and res["data"]["decoys"][0]["reason"] == "invalid_reason_code":
                rejected_cases += 1
        elif kind == "self_loop_step":
            sym = sym_by_key[(p["path"], p["qualified_name"])]
            res = lsvc.trajectory_record(
                repo_id=repo_id,
                query="test self loop",
                answers=[f"{sym.symbol_id}@{sym.start_line}"],
                steps=[f"{sym.symbol_id}>{sym.symbol_id}@{sym.start_line}"],
                run_id="p1",
                agent_id=aid,
            )
            if res["data"]["steps"][0]["status"] == "rejected" and res["data"]["steps"][0]["reason"] == "self_loop_step":
                rejected_cases += 1
        elif kind == "wrong_file_hash":
            sym = sym_by_key[(p["path"], p["qualified_name"])]
            # Simulate stale file on disk during write gate check
            repo_root = base_config.repositories[repo_id].root
            target_file = repo_root / p["path"]
            orig_bytes = target_file.read_bytes()
            try:
                target_file.write_bytes(orig_bytes + b"\n# dirty byte\n")
                lsvc.freshness._snapshots.clear()
                res = lsvc.trajectory_record(
                    repo_id=repo_id,
                    query="test wrong hash",
                    answers=[f"{sym.symbol_id}@{sym.start_line}"],
                    run_id="p1",
                    agent_id=aid,
                )
                if res["data"]["card_id"] is None and res["data"]["answers"][0]["reason"] == "stale_file":
                    rejected_cases += 1
            finally:
                target_file.write_bytes(orig_bytes)
                lsvc.freshness._snapshots.clear()

    return {"rejected_cases": rejected_cases, "total_cases": total_cases}


def evaluate_files(task_files: list[Path], config_path: Path) -> dict[str, Any]:
    base_config = load_config(config_path)
    tmp_dir = Path(tempfile.mkdtemp(prefix="tc_ledger_eval_"))
    try:
        tmp_cfg_path = tmp_dir / "repos.toml"
        shutil.copy2(config_path, tmp_cfg_path)

        cfg_off = AppConfig(
            server=base_config.server,
            repositories=base_config.repositories,
            budget_profiles=base_config.budget_profiles,
            ledger=LedgerConfig(enabled=False, overlay_enabled=False),
        )
        cfg_hint = AppConfig(
            server=base_config.server,
            repositories=base_config.repositories,
            budget_profiles=base_config.budget_profiles,
            ledger=LedgerConfig(enabled=True, overlay_enabled=False),
        )
        cfg_overlay = AppConfig(
            server=base_config.server,
            repositories=base_config.repositories,
            budget_profiles=base_config.budget_profiles,
            ledger=LedgerConfig(enabled=True, overlay_enabled=True),
        )

        from token_context_mcp.ledger.verify import LedgerVerifier

        svc_off = RetrievalService(cfg_off, config_path)
        lsvc = LedgerService(cfg_overlay, config_path)
        lsvc.store = LedgerStore(tmp_dir / "ledger.sqlite")
        svc_hint = RetrievalService(cfg_hint, config_path)
        svc_hint._ledger_store = lsvc.store
        svc_hint._ledger_verifier = LedgerVerifier()
        svc_overlay = RetrievalService(cfg_overlay, config_path)
        svc_overlay._ledger_store = lsvc.store
        svc_overlay._ledger_verifier = LedgerVerifier()

        followup_base_tokens: list[int] = []
        followup_hint_tokens: list[int] = []
        followup_paraphrase_tokens: list[int] = []
        followup_overlay_tokens: list[int] = []
        followup_oracle_tokens: list[int] = []

        oracle_diffs: list[float] = []
        oracle_pct_diffs: list[float] = []
        hint_diffs: list[float] = []
        hint_pct_diffs: list[float] = []
        paraphrase_pct_diffs: list[float] = []
        overlay_pct_diffs: list[float] = []

        base_calls: list[int] = []
        hint_calls: list[int] = []
        overlay_calls: list[int] = []
        oracle_calls: list[int] = []

        base_file_acc: list[float] = []
        base_sym_rec: list[float] = []
        base_rank1: list[float] = []
        overlay_rank1: list[float] = []

        flips_right_to_wrong = 0
        flips_wrong_to_right = 0
        hint_token_sizes: list[int] = []
        lookup_latencies_ms: list[float] = []

        collision_total = 0
        collision_accuracy_off = 0
        collision_accuracy_hint = 0
        collision_accuracy_overlay = 0
        collision_false_hints = 0

        mut_stale_prevented = 0
        mut_stale_total = 0
        mut_valid_preserved = 0
        mut_valid_total = 0

        pois_rejected = 0
        pois_total = 0
        byte_identical_checks = 0
        byte_identical_passed = 0

        for task_file in task_files:
            data = json.loads(task_file.read_text(encoding="utf-8"))
            repo_id = data["repo_id"]
            store = SQLiteStore(database_path(index_directory(config_path), repo_id), read_only=True)
            sym_by_key = {(s.path, s.qualified_name): s for s in store.symbols()}

            # 1. Seed verified trajectory cards (across 2 runs -> confirmed) from chain exploration
            for chain in data["chains"]:
                for turn_key in ("q1", "q2", "q3"):
                    turn = chain[turn_key]
                    gold_keys = {(g["path"], g["qualified_name"]) for g in turn["gold_symbols"]}
                    gold_files = set(turn["gold_files"])
                    base_res = _run_no_ledger_turn(svc_off, repo_id, turn["query"], gold_keys, gold_files)
                    g0 = turn["gold_symbols"][0]
                    gsym = sym_by_key[(g0["path"], g0["qualified_name"])]
                    decoys = [f"{dsid}!wrapper_only" for dsid in base_res["inspected_decoys"][:5]]
                    for rid in ("seed_run_1", "seed_run_2"):
                        lsvc.trajectory_record(
                            repo_id=repo_id,
                            query=turn["query"],
                            answers=[f"{gsym.symbol_id}@{gsym.start_line}"],
                            decoys=decoys,
                            run_id=rid,
                            agent_id=f"seed_{chain['id']}_{turn_key}_{rid}",
                        )

            # 2. Evaluate follow-up queries (q2, q3) across all arms
            for chain in data["chains"]:
                for turn_key in ("q2", "q3"):
                    turn = chain[turn_key]
                    gold_keys = {(g["path"], g["qualified_name"]) for g in turn["gold_symbols"]}
                    gold_files = set(turn["gold_files"])
                    g0 = turn["gold_symbols"][0]

                    # Verify disabled-mode byte identity before vs after ledger population
                    s_off_1 = svc_off.search_source(repo_id, query=turn["query"], profile="locate")
                    s_off_2 = RetrievalService(cfg_off, config_path).search_source(
                        repo_id, query=turn["query"], profile="locate"
                    )
                    byte_identical_checks += 1
                    if json.dumps(s_off_1, sort_keys=True) == json.dumps(s_off_2, sort_keys=True) and (
                        "prior_evidence" not in s_off_1["data"] and "ledger_rev" not in s_off_1
                    ):
                        byte_identical_passed += 1

                    base = _run_no_ledger_turn(svc_off, repo_id, turn["query"], gold_keys, gold_files)
                    hint = _run_ledger_turn(svc_hint, repo_id, turn["query"], gold_keys, gold_files)
                    para_q = _paraphrase_query(turn["query"], g0["qualified_name"])
                    para = _run_ledger_turn(svc_hint, repo_id, para_q, gold_keys, gold_files)
                    over = _run_ledger_turn(svc_overlay, repo_id, turn["query"], gold_keys, gold_files)
                    oracle = _run_oracle_ledger_turn(svc_off, store, repo_id, turn["query"], turn["gold_symbols"])

                    followup_base_tokens.append(base["tokens"])
                    followup_hint_tokens.append(hint["tokens"])
                    followup_paraphrase_tokens.append(para["tokens"])
                    followup_overlay_tokens.append(over["tokens"])
                    followup_oracle_tokens.append(oracle["tokens"])

                    oracle_diffs.append(float(base["tokens"] - oracle["tokens"]))
                    oracle_pct_diffs.append(
                        ((base["tokens"] - oracle["tokens"]) / base["tokens"] * 100.0) if base["tokens"] else 0.0
                    )
                    hint_diffs.append(float(base["tokens"] - hint["tokens"]))
                    hint_pct_diffs.append(
                        ((base["tokens"] - hint["tokens"]) / base["tokens"] * 100.0) if base["tokens"] else 0.0
                    )
                    paraphrase_pct_diffs.append(
                        ((base["tokens"] - para["tokens"]) / base["tokens"] * 100.0) if base["tokens"] else 0.0
                    )
                    overlay_pct_diffs.append(
                        ((base["tokens"] - over["tokens"]) / base["tokens"] * 100.0) if base["tokens"] else 0.0
                    )

                    base_calls.append(base["calls"])
                    hint_calls.append(hint["calls"])
                    overlay_calls.append(over["calls"])
                    oracle_calls.append(oracle["calls"])

                    base_file_acc.append(base["file_acc_5"])
                    base_sym_rec.append(base["sym_recall_10"])
                    base_rank1.append(base["rank1_acc"])
                    overlay_rank1.append(over["rank1_acc"])

                    if base["found_gold"] and not over["found_gold"]:
                        flips_right_to_wrong += 1
                    if not base["found_gold"] and over["found_gold"]:
                        flips_wrong_to_right += 1

                    if hint["hint_tokens"] > 0:
                        hint_token_sizes.append(hint["hint_tokens"])
                    lookup_latencies_ms.append(hint["elapsed_ms"])

            # 3. Evaluate Topic Collisions (L-2)
            col_dir = tmp_dir / f"col_{repo_id}"
            col_dir.mkdir(parents=True, exist_ok=True)
            col_lsvc = LedgerService(cfg_overlay, config_path)
            col_lsvc.store = LedgerStore(col_dir / "ledger.sqlite")
            col_svc_hint = RetrievalService(cfg_hint, config_path)
            col_svc_hint._ledger_store = col_lsvc.store
            col_svc_hint._ledger_verifier = LedgerVerifier()
            col_svc_over = RetrievalService(cfg_overlay, config_path)
            col_svc_over._ledger_store = col_lsvc.store
            col_svc_over._ledger_verifier = LedgerVerifier()

            for col in data.get("collisions", []):
                collision_total += 1
                s1 = sym_by_key[(col["q1_answer"]["path"], col["q1_answer"]["qualified_name"])]
                s2p = sym_by_key[(col["q2_prime_answer"]["path"], col["q2_prime_answer"]["qualified_name"])]
                # Record confirmed card for Q1 where Q2_prime's gold answer is explicitly marked as a decoy!
                for rid in ("col_r1", "col_r2"):
                    col_lsvc.trajectory_record(
                        repo_id=repo_id,
                        query=col["q1_query"],
                        answers=[f"{s1.symbol_id}@{s1.start_line}"],
                        decoys=[f"{s2p.symbol_id}!wrong_variant"],
                        run_id=rid,
                        agent_id=f"col_{col['id']}_{rid}",
                    )
                q2p_gold = {(s2p.path, s2p.qualified_name)}
                q2p_files = {s2p.path}
                c_off = _run_no_ledger_turn(svc_off, repo_id, col["q2_prime_query"], q2p_gold, q2p_files)
                c_hint = _run_ledger_turn(col_svc_hint, repo_id, col["q2_prime_query"], q2p_gold, q2p_files)
                c_over = _run_ledger_turn(col_svc_over, repo_id, col["q2_prime_query"], q2p_gold, q2p_files)
                if c_off["found_gold"]:
                    collision_accuracy_off += 1
                if c_hint["found_gold"]:
                    collision_accuracy_hint += 1
                if c_over["found_gold"]:
                    collision_accuracy_overlay += 1
                if c_hint["prior_hit"]:
                    collision_false_hints += 1

            # 4. Evaluate Code Mutations (L-3)
            m_res = _evaluate_mutations(data, store, base_config, tmp_cfg_path)
            mut_stale_prevented += m_res["stale_prevented"]
            mut_stale_total += m_res["stale_total"]
            mut_valid_preserved += m_res["valid_preserved"]
            mut_valid_total += m_res["valid_total"]

            # 5. Evaluate Anti-Poisoning (L-4)
            p_res = _evaluate_poisoning(data, store, base_config, tmp_cfg_path)
            pois_rejected += p_res["rejected_cases"]
            pois_total += p_res["total_cases"]

        med_base = statistics.median(followup_base_tokens)
        med_hint = statistics.median(followup_hint_tokens)
        med_para = statistics.median(followup_paraphrase_tokens)
        med_overlay = statistics.median(followup_overlay_tokens)
        med_oracle = statistics.median(followup_oracle_tokens)

        med_oracle_pct = statistics.median(oracle_pct_diffs)
        med_hint_pct = statistics.median(hint_pct_diffs)
        med_para_pct = statistics.median(paraphrase_pct_diffs)
        med_overlay_pct = statistics.median(overlay_pct_diffs)

        oracle_ci = _bootstrap_ci95(oracle_diffs)
        hint_ci = _bootstrap_ci95(hint_diffs)
        hint_pct_ci = _bootstrap_ci95(hint_pct_diffs)

        lat_sorted = sorted(lookup_latencies_ms)
        p95_lat = lat_sorted[int(0.95 * (len(lat_sorted) - 1))] if lat_sorted else 0.0
        go = med_oracle_pct >= 15.0 and oracle_ci[0] > 0.0

        return {
            "followup_queries": len(followup_base_tokens),
            "no_ledger_median_tokens": round(med_base, 2),
            "ledger_hint_median_tokens": round(med_hint, 2),
            "ledger_paraphrase_median_tokens": round(med_para, 2),
            "ledger_overlay_median_tokens": round(med_overlay, 2),
            "oracle_ledger_median_tokens": round(med_oracle, 2),
            "median_paired_reduction_pct": round(med_oracle_pct, 2),
            "ci95_token_savings": list(oracle_ci),
            "l1_token_savings": {
                "ledger_hint_median_reduction_pct": round(med_hint_pct, 2),
                "ledger_paraphrase_median_reduction_pct": round(med_para_pct, 2),
                "ledger_overlay_median_reduction_pct": round(med_overlay_pct, 2),
                "ledger_hint_ci95_tokens": list(hint_ci),
                "ledger_hint_ci95_pct": list(hint_pct_ci),
                "no_ledger_mean_tokens": round(statistics.fmean(followup_base_tokens), 2),
                "ledger_hint_mean_tokens": round(statistics.fmean(followup_hint_tokens), 2),
                "mean_token_reduction_pct": round(
                    (statistics.fmean(followup_base_tokens) - statistics.fmean(followup_hint_tokens))
                    / statistics.fmean(followup_base_tokens)
                    * 100.0,
                    2,
                ),
            },
            "no_ledger_mean_calls": round(statistics.fmean(base_calls), 2),
            "ledger_hint_mean_calls": round(statistics.fmean(hint_calls), 2),
            "ledger_overlay_mean_calls": round(statistics.fmean(overlay_calls), 2),
            "oracle_ledger_mean_calls": round(statistics.fmean(oracle_calls), 2),
            "no_ledger_file_acc_5": round(statistics.fmean(base_file_acc), 4),
            "no_ledger_sym_recall_10": round(statistics.fmean(base_sym_rec), 4),
            "l2_do_no_harm_and_collisions": {
                "flips_right_to_wrong": flips_right_to_wrong,
                "flips_wrong_to_right": flips_wrong_to_right,
                "flip_right_to_wrong_rate_pct": round(flips_right_to_wrong / len(followup_base_tokens) * 100.0, 2),
                "search_rank1_no_ledger": round(statistics.fmean(base_rank1), 4),
                "search_rank1_ledger_overlay": round(statistics.fmean(overlay_rank1), 4),
                "collision_pairs": collision_total,
                "collision_acc_no_ledger": round(collision_accuracy_off / max(1, collision_total), 4),
                "collision_acc_ledger_hint": round(collision_accuracy_hint / max(1, collision_total), 4),
                "collision_acc_ledger_overlay": round(collision_accuracy_overlay / max(1, collision_total), 4),
                "collision_false_hints_served": collision_false_hints,
            },
            "l3_code_mutations": {
                "stale_prevented": mut_stale_prevented,
                "stale_total": mut_stale_total,
                "stale_invalidation_rate_pct": round(mut_stale_prevented / max(1, mut_stale_total) * 100.0, 2),
                "valid_preserved": mut_valid_preserved,
                "valid_total": mut_valid_total,
                "valid_preservation_rate_pct": round(mut_valid_preserved / max(1, mut_valid_total) * 100.0, 2),
            },
            "l4_anti_poisoning": {
                "rejected_cases": pois_rejected,
                "total_cases": pois_total,
                "rejection_rate_pct": round(pois_rejected / max(1, pois_total) * 100.0, 2),
            },
            "l5_overhead_and_determinism": {
                "median_hint_tokens": round(statistics.median(hint_token_sizes), 2) if hint_token_sizes else 0.0,
                "max_hint_tokens": max(hint_token_sizes) if hint_token_sizes else 0,
                "lookup_p50_ms": round(statistics.median(lookup_latencies_ms), 2) if lookup_latencies_ms else 0.0,
                "lookup_p95_ms": round(p95_lat, 2),
                "disabled_byte_identical_checks": f"{byte_identical_passed}/{byte_identical_checks}",
            },
            "go_no_go": "GO" if go else "NO-GO",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run L0-L5 chain evaluation.")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--tasks",
        nargs="+",
        type=Path,
        default=[
            Path("evals/tasks/chain_rich.json"),
            Path("evals/tasks/chain_fastify.json"),
        ],
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    report = evaluate_files(args.tasks, args.config)
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
