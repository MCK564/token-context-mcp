"""Benchmark server wire-payload token usage across Old, New, and Compact-Text configurations.

Measures serialized ``CallToolResult.content[0].text`` wire tokens using ``tiktoken``
(``o200k_base``) across 5 representative calls matching the Antigravity P1..P5 suite
against ``token-context`` in ``repos.toml``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import tiktoken

from token_context_mcp.config import load_config
from token_context_mcp.retrieve.serialization import ResultFinalizer
from token_context_mcp.retrieve.service import RetrievalService

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = Path(r"C:\Users\KHA\AppData\Roaming\token-context-mcp\repos.toml")
DEFAULT_REPO_ID = "token-context"
DEFAULT_OUT_DIR = REPO_ROOT / "evals" / "reports"


def _savings_pct(tokens: int, baseline: int) -> float:
    if baseline <= 0:
        return 0.0
    return round(100.0 * (baseline - tokens) / baseline, 1)


def _fmt_delta(tokens: int, baseline: int) -> str:
    if baseline <= 0:
        return "N/A"
    diff = 100.0 * (tokens - baseline) / baseline
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.1f}%"


def _extract_symbol_id(find_res: dict[str, Any], preferred_name: str) -> str:
    symbols = find_res.get("data", {}).get("symbols", [])
    if not isinstance(symbols, list) or not symbols:
        raise RuntimeError(f"Could not resolve symbol_id for {preferred_name!r}")
    for entry in symbols:
        if isinstance(entry, dict) and entry.get("name") == preferred_name:
            sid = entry.get("symbol_id") or entry.get("id")
            if sid:
                return str(sid)
    first = symbols[0]
    if isinstance(first, dict):
        sid = first.get("symbol_id") or first.get("id")
        if sid:
            return str(sid)
    if isinstance(first, (list, tuple)) and first:
        return str(first[0])
    raise RuntimeError(f"Unsupported find_symbols entry format for {preferred_name!r}: {first!r}")


def _measure_wire(
    payload: dict[str, Any],
    finalizer: ResultFinalizer,
    enc: tiktoken.Encoding,
    *,
    baseline_tokens: int | None = None,
) -> dict[str, Any]:
    result = finalizer.finalize(payload)
    wire_text = result.content[0].text if result.content else ""
    wire_tokens = len(enc.encode(wire_text, disallowed_special=()))
    row: dict[str, Any] = {
        "wire_tokens": wire_tokens,
        "wire_chars": len(wire_text),
        "wire_bytes": len(wire_text.encode("utf-8")),
        "truncated": bool(payload.get("truncated", False)),
        "freshness": payload.get("freshness"),
        "output_mode": finalizer.output_mode,
    }
    if baseline_tokens is not None:
        row["savings_vs_old_pct"] = _savings_pct(wire_tokens, baseline_tokens)
    return row


def run_benchmark(config_path: Path, repo_id: str) -> dict[str, Any]:
    cfg = load_config(config_path)
    svc = RetrievalService(cfg, config_path)
    enc = tiktoken.get_encoding("o200k_base")
    fin_text = ResultFinalizer(output_mode="text")
    fin_compact = ResultFinalizer(output_mode="compact_text")

    find_res = svc.find_symbols(repo_id, pattern="_lookup_prior_evidence")
    impact_sid = _extract_symbol_id(find_res, "_lookup_prior_evidence")

    # 1. get_index_status
    status_old_payload = svc.status(repo_id, verbose=True)
    status_new_payload = svc.status(repo_id, verbose=False)
    status_old = _measure_wire(status_old_payload, fin_text, enc)
    status_old_t = status_old["wire_tokens"]

    # 2. get_repo_map
    rm_query = "kernel middleware pipeline server tool register"
    rm_old_payload = svc.repo_map(
        repo_id,
        query=rm_query,
        budget_tokens=4096,
        format="compact",
        include_digests=True,
    )
    rm_new_compact_payload = svc.repo_map(
        repo_id,
        query=rm_query,
        budget_tokens=1024,
        format="compact",
        include_digests=False,
    )
    rm_new_grouped_payload = svc.repo_map(
        repo_id,
        query=rm_query,
        budget_tokens=1024,
        format="grouped",
        include_digests=False,
    )
    rm_old = _measure_wire(rm_old_payload, fin_text, enc)
    rm_old_t = rm_old["wire_tokens"]

    # 3. search_source
    ss_query = "rate limit stale_file decoy"
    ss_old_payload = svc.search_source(
        repo_id, query=ss_query, max_tokens=2048, limit=30, profile="locate"
    )
    ss_new_payload = svc.search_source(
        repo_id, query=ss_query, max_tokens=1280, limit=20, profile="locate"
    )
    ss_old = _measure_wire(ss_old_payload, fin_text, enc)
    ss_old_t = ss_old["wire_tokens"]

    # 4. get_file_skeleton
    skel_path = "src/token_context_mcp/ledger/store.py"
    skel_old_payload = svc.file_skeleton(repo_id, path=skel_path, max_tokens=2048)
    skel_new_payload = svc.file_skeleton(repo_id, path=skel_path, max_tokens=1536)
    skel_old = _measure_wire(skel_old_payload, fin_text, enc)
    skel_old_t = skel_old["wire_tokens"]

    # 5. get_impact_slice
    imp_old_payload = svc.impact_slice(
        repo_id, symbol_id=impact_sid, direction="callers", depth=2, max_nodes=200, max_tokens=4096
    )
    imp_new_payload = svc.impact_slice(
        repo_id, symbol_id=impact_sid, direction="callers", depth=2, max_nodes=120, max_tokens=1536
    )
    imp_old = _measure_wire(imp_old_payload, fin_text, enc)
    imp_old_t = imp_old["wire_tokens"]

    tools: list[dict[str, Any]] = [
        {
            "tool": "get_index_status",
            "prompt_match": "P1/Pre-flight",
            "variants": {
                "Old": status_old,
                "New": _measure_wire(status_new_payload, fin_text, enc, baseline_tokens=status_old_t),
                "Compact-Text": _measure_wire(status_new_payload, fin_compact, enc, baseline_tokens=status_old_t),
            },
        },
        {
            "tool": "get_repo_map",
            "prompt_match": "P1",
            "variants": {
                "Old": rm_old,
                "New-Compact": _measure_wire(rm_new_compact_payload, fin_text, enc, baseline_tokens=rm_old_t),
                "New-Grouped": _measure_wire(rm_new_grouped_payload, fin_text, enc, baseline_tokens=rm_old_t),
                "Compact-Text": _measure_wire(rm_new_grouped_payload, fin_compact, enc, baseline_tokens=rm_old_t),
            },
        },
        {
            "tool": "search_source",
            "prompt_match": "P2",
            "variants": {
                "Old": ss_old,
                "New": _measure_wire(ss_new_payload, fin_text, enc, baseline_tokens=ss_old_t),
                "Compact-Text": _measure_wire(ss_new_payload, fin_compact, enc, baseline_tokens=ss_old_t),
            },
        },
        {
            "tool": "get_file_skeleton",
            "prompt_match": "P3",
            "variants": {
                "Old": skel_old,
                "New": _measure_wire(skel_new_payload, fin_text, enc, baseline_tokens=skel_old_t),
                "Compact-Text": _measure_wire(skel_new_payload, fin_compact, enc, baseline_tokens=skel_old_t),
            },
        },
        {
            "tool": "get_impact_slice",
            "prompt_match": "P4",
            "impact_symbol_id": impact_sid,
            "variants": {
                "Old": imp_old,
                "New": _measure_wire(imp_new_payload, fin_text, enc, baseline_tokens=imp_old_t),
                "Compact-Text": _measure_wire(imp_new_payload, fin_compact, enc, baseline_tokens=imp_old_t),
            },
        },
    ]

    total_old = sum(t["variants"]["Old"]["wire_tokens"] for t in tools)
    total_new_text = sum(
        (t["variants"].get("New") or t["variants"]["New-Compact"])["wire_tokens"] for t in tools
    )
    total_new_grouped_text = sum(
        (t["variants"].get("New") or t["variants"]["New-Grouped"])["wire_tokens"] for t in tools
    )
    total_compact_text = sum(t["variants"]["Compact-Text"]["wire_tokens"] for t in tools)

    totals = {
        "Old_text": {"wire_tokens": total_old, "savings_vs_old_pct": 0.0},
        "New_text_compact_map": {
            "wire_tokens": total_new_text,
            "savings_vs_old_pct": _savings_pct(total_new_text, total_old),
        },
        "New_text_grouped_map": {
            "wire_tokens": total_new_grouped_text,
            "savings_vs_old_pct": _savings_pct(total_new_grouped_text, total_old),
        },
        "Compact_Text": {
            "wire_tokens": total_compact_text,
            "savings_vs_old_pct": _savings_pct(total_compact_text, total_old),
        },
    }

    return {
        "repo_id": repo_id,
        "config_path": str(config_path),
        "tokenizer": "o200k_base",
        "impact_symbol_id": impact_sid,
        "tools": tools,
        "totals": totals,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Server Wire-Payload Token Benchmark (`o200k_base`)",
        "",
        f"- **Repository:** `{report['repo_id']}` (`{report['config_path']}`)",
        f"- **Tokenizer:** `{report['tokenizer']}` on `CallToolResult.content[0].text`",
        f"- **Impact Symbol (`_lookup_prior_evidence`):** `{report['impact_symbol_id']}`",
        "",
        "## 1. Per-Tool Wire Token Counts",
        "",
        "| Tool | Prompt | Variant | Output Mode | Wire Tokens | Wire Bytes | Truncated | Δ vs Old |",
        "| :--- | :---: | :--- | :--- | ---: | ---: | :---: | ---: |",
    ]
    for t in report["tools"]:
        old_tokens = t["variants"]["Old"]["wire_tokens"]
        for vname, vdata in t["variants"].items():
            delta = "—" if vname == "Old" else _fmt_delta(vdata["wire_tokens"], old_tokens)
            lines.append(
                f"| `{t['tool']}` | {t['prompt_match']} | **{vname}** | `{vdata['output_mode']}` | "
                f"{vdata['wire_tokens']:,} | {vdata['wire_bytes']:,} | "
                f"{'yes' if vdata['truncated'] else 'no'} | {delta} |"
            )

    totals = report["totals"]
    old_total = totals["Old_text"]["wire_tokens"]
    lines.extend([
        "",
        "## 2. 5-Tool Totals & Savings vs Old",
        "",
        "| Configuration | Total Wire Tokens | Savings vs Old |",
        "| :--- | ---: | ---: |",
        f"| **Old (`text`)** | {old_total:,} | — |",
        f"| **New (`text`, compact `repo_map`)** | {totals['New_text_compact_map']['wire_tokens']:,} | {_fmt_delta(totals['New_text_compact_map']['wire_tokens'], old_total)} |",
        f"| **New (`text`, grouped `repo_map`)** | {totals['New_text_grouped_map']['wire_tokens']:,} | {_fmt_delta(totals['New_text_grouped_map']['wire_tokens'], old_total)} |",
        f"| **Compact-Text (`compact_text`, grouped `repo_map`)** | {totals['Compact_Text']['wire_tokens']:,} | {_fmt_delta(totals['Compact_Text']['wire_tokens'], old_total)} |",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    report = run_benchmark(args.config, args.repo_id)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "server_payload_bench.json"
    md_path = args.out_dir / "server_payload_bench.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
