"""Analyze Antigravity conversation transcripts for the 5-prompt MCP vs plain benchmark."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACK_PATH = REPO_ROOT / "evals" / "agy_prompt_pack.json"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "evals" / "reports" / "agy_bench_manifest.json"
DEFAULT_REPORT_MD = REPO_ROOT / "evals" / "reports" / "agy_prompt_bench_report.md"
DEFAULT_REPORT_JSON = REPO_ROOT / "evals" / "reports" / "agy_prompt_bench_report.json"
DEFAULT_BRAIN_DIR = Path(
    os.environ.get("ANTIGRAVITY_BRAIN_DIR", r"C:\Users\KHA\.gemini\antigravity\brain")
)

try:
    import tiktoken  # type: ignore

    _ENC = tiktoken.get_encoding("o200k_base")
except Exception:  # pragma: no cover - fallback when tiktoken unavailable
    _ENC = None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENC is not None:
        return len(_ENC.encode(text, disallowed_special=()))
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def load_merged_transcript(conv_dir: Path) -> list[dict[str, Any]]:
    logs_dir = conv_dir / ".system_generated" / "logs"
    compact_path = logs_dir / "transcript.jsonl"
    full_path = logs_dir / "transcript_full.jsonl"
    if not compact_path.exists():
        raise FileNotFoundError(f"Missing transcript.jsonl at {compact_path}")

    full_by_idx: dict[int, dict[str, Any]] = {}
    if full_path.exists():
        for raw in full_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            if "step_index" in obj:
                full_by_idx[int(obj["step_index"])] = obj

    merged: list[dict[str, Any]] = []
    for raw in compact_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if obj.get("truncated_fields") and int(obj.get("step_index", -1)) in full_by_idx:
            obj = full_by_idx[int(obj["step_index"])]
        merged.append(obj)
    return merged


_SENDER_UUID_RE = re.compile(r"sender=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s")


def _is_subagent_prompt_boundary(step: dict[str, Any]) -> bool:
    """Detect incoming parent prompts in subagent SYSTEM_MESSAGE steps.

    Excludes background task notifications (sender=<uuid>/task-...) and system
    notices (sender=system).
    """
    if step.get("type") != "SYSTEM_MESSAGE":
        return False
    content = str(step.get("content") or "")
    return bool(_SENDER_UUID_RE.search(content))


def split_into_turns(steps: list[dict[str, Any]], expected_prompts: int = 5) -> list[list[dict[str, Any]]]:
    """Group transcript steps into P1..P5 turns."""
    boundary_indices: list[int] = [i for i, s in enumerate(steps) if s.get("type") == "USER_INPUT"]
    if len(boundary_indices) < expected_prompts:
        sub_indices = [i for i, s in enumerate(steps) if _is_subagent_prompt_boundary(s)]
        if len(sub_indices) >= len(boundary_indices):
            boundary_indices = sub_indices

    if not boundary_indices:
        return [steps] if steps else []

    turns: list[list[dict[str, Any]]] = []
    for idx_pos, start in enumerate(boundary_indices):
        end = boundary_indices[idx_pos + 1] if idx_pos + 1 < len(boundary_indices) else len(steps)
        turns.append(steps[start:end])
    return turns


def score_gold(reply_text: str, gold_rule: dict[str, Any]) -> tuple[float, list[str]]:
    """Score a turn's final response against gold required_groups (0.0 to 1.0)."""
    groups: list[list[str]] = gold_rule.get("required_groups", [])
    if not groups:
        return 1.0, []
    lower_reply = reply_text.lower()
    missing: list[str] = []
    matched = 0
    for grp in groups:
        if any(cand.lower() in lower_reply for cand in grp):
            matched += 1
        else:
            missing.append(" / ".join(grp))
    passed = 1.0 if not missing else round(matched / len(groups), 2)
    return passed, missing


def _parse_iso_ts(ts_str: str | None) -> float | None:
    if not ts_str:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _unquote_arg(val: Any) -> str:
    """Decode JSON-encoded string values stored inside Antigravity transcript args."""
    if val is None:
        return ""
    s = str(val)
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        try:
            decoded = json.loads(s)
            if isinstance(decoded, str):
                return decoded
        except Exception:
            pass
    return s


def analyze_turn(
    turn_steps: list[dict[str, Any]],
    prompt_id: str,
    gold_rule: dict[str, Any],
    cache_discount: float,
) -> dict[str, Any]:
    uncached_in = 0
    cache_read = 0
    out_tok = 0
    peak_ctx = 0
    planner_steps = 0

    mcp_calls = 0
    mcp_tool_breakdown: dict[str, int] = {}
    mcp_schema_reads = 0
    native_reads = 0
    native_cmds = 0
    other_tools = 0

    mcp_output_tokens = 0
    mcp_schema_tokens = 0
    native_output_tokens = 0

    # Map tool invocation order to subsequent GENERIC tool output steps by matching sequence
    pending_tool_kinds: list[tuple[str, str]] = []
    final_answer = ""
    sent_message_answer = ""

    timestamps: list[float] = []
    for s in turn_steps:
        ts = _parse_iso_ts(s.get("created_at"))
        if ts is not None:
            timestamps.append(ts)

        stype = s.get("type")
        if stype == "PLANNER_RESPONSE":
            planner_steps += 1
            in_t = int(s.get("input_tokens") or 0)
            c_t = int(s.get("cache_read_tokens") or 0)
            out_t = int(s.get("output_tokens") or 0)
            uncached_in += in_t
            cache_read += c_t
            out_tok += out_t
            peak_ctx = max(peak_ctx, in_t + c_t)

            content = str(s.get("content") or "").strip()
            if content:
                final_answer = content

            for tc in s.get("tool_calls") or []:
                name = str(tc.get("name") or "")
                args = tc.get("args") or tc.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                if name == "send_message":
                    msg_body = _unquote_arg(args.get("Message") or args.get("message")).strip()
                    if msg_body:
                        sent_message_answer = msg_body
                    other_tools += 1
                    pending_tool_kinds.append(("other", name))
                elif name == "call_mcp_tool":
                    mcp_calls += 1
                    tname = _unquote_arg(args.get("ToolName") or args.get("tool_name") or "unknown")
                    mcp_tool_breakdown[tname] = mcp_tool_breakdown.get(tname, 0) + 1
                    pending_tool_kinds.append(("mcp", tname))
                elif name.startswith("mcp_"):
                    mcp_calls += 1
                    mcp_tool_breakdown[name] = mcp_tool_breakdown.get(name, 0) + 1
                    pending_tool_kinds.append(("mcp", name))
                elif name == "read_file":
                    path_str = _unquote_arg(args.get("Path") or args.get("path"))
                    norm = path_str.replace("/", "\\").lower()
                    if "\\mcp\\token-context\\" in norm:
                        mcp_schema_reads += 1
                        pending_tool_kinds.append(("schema", name))
                    else:
                        native_reads += 1
                        pending_tool_kinds.append(("native", name))
                elif name in {"run_command", "command_status", "grep_search", "find_by_name", "list_dir"}:
                    native_cmds += 1
                    pending_tool_kinds.append(("native", name))
                else:
                    other_tools += 1
                    pending_tool_kinds.append(("other", name))

        elif stype == "GENERIC":
            # Tool output step
            out_text = str(s.get("content") or "")
            toks = count_tokens(out_text)
            if pending_tool_kinds:
                kind, _ = pending_tool_kinds.pop(0)
            else:
                # Heuristic fallback if step ordering didn't match 1:1
                if '"schema_version":"1.0"' in out_text or '"repo_ids":' in out_text:
                    kind = "mcp"
                else:
                    kind = "native"
            if kind == "mcp":
                mcp_output_tokens += toks
            elif kind == "schema":
                mcp_schema_tokens += toks
            elif kind == "native":
                native_output_tokens += toks

    total_tools = mcp_calls + mcp_schema_reads + native_reads + native_cmds + other_tools
    retrieval_ops = mcp_calls + native_reads + native_cmds
    mcp_adoption_pct = round(100.0 * mcp_calls / retrieval_ops, 1) if retrieval_ops else 0.0
    effective_cost_units = round(uncached_in + cache_discount * cache_read, 1)
    latency_sec = round(max(timestamps) - min(timestamps), 2) if len(timestamps) >= 2 else 0.0

    effective_answer = sent_message_answer or final_answer
    gold_frac, missing_gold = score_gold(effective_answer, gold_rule)
    gold_pass = 1 if not missing_gold else 0

    return {
        "prompt_id": prompt_id,
        "planner_steps": planner_steps,
        "uncached_input_tokens": uncached_in,
        "cache_read_tokens": cache_read,
        "total_billed_input": uncached_in + cache_read,
        "effective_input_cost_units": effective_cost_units,
        "output_tokens": out_tok,
        "peak_context": peak_ctx,
        "mcp_calls": mcp_calls,
        "mcp_tool_breakdown": mcp_tool_breakdown,
        "mcp_schema_reads": mcp_schema_reads,
        "native_reads": native_reads,
        "native_cmds": native_cmds,
        "other_tools": other_tools,
        "total_tools": total_tools,
        "mcp_adoption_pct": mcp_adoption_pct,
        "mcp_output_tokens": mcp_output_tokens,
        "mcp_schema_tokens": mcp_schema_tokens,
        "native_output_tokens": native_output_tokens,
        "retrieved_content_tokens": mcp_output_tokens + mcp_schema_tokens + native_output_tokens,
        "latency_sec": latency_sec,
        "gold_pass": gold_pass,
        "gold_fraction": gold_frac,
        "missing_gold": missing_gold,
        "answer_preview": effective_answer[:240],
    }


def analyze_run(entry: dict[str, Any], pack: dict[str, Any], brain_dir: Path) -> dict[str, Any]:
    conv_id = entry["conversation_id"]
    steps = load_merged_transcript(brain_dir / conv_id)
    prompts = pack["prompts"]
    gold_map = pack["gold"]
    cache_discount = float(entry.get("cache_discount_factor", 0.05))

    turns = split_into_turns(steps, expected_prompts=len(prompts))
    turn_metrics: list[dict[str, Any]] = []
    for idx, p_info in enumerate(prompts):
        pid = p_info["id"]
        t_steps = turns[idx] if idx < len(turns) else []
        turn_metrics.append(analyze_turn(t_steps, pid, gold_map.get(pid, {}), cache_discount))

    sum_uncached = sum(t["uncached_input_tokens"] for t in turn_metrics)
    sum_cache = sum(t["cache_read_tokens"] for t in turn_metrics)
    sum_out = sum(t["output_tokens"] for t in turn_metrics)
    peak_ctx = max((t["peak_context"] for t in turn_metrics), default=0)
    sum_mcp = sum(t["mcp_calls"] for t in turn_metrics)
    sum_schema = sum(t["mcp_schema_reads"] for t in turn_metrics)
    sum_native_r = sum(t["native_reads"] for t in turn_metrics)
    sum_native_c = sum(t["native_cmds"] for t in turn_metrics)
    retrieval_ops = sum_mcp + sum_native_r + sum_native_c

    mcp_breakdown_total: dict[str, int] = {}
    for t in turn_metrics:
        for k, v in t["mcp_tool_breakdown"].items():
            mcp_breakdown_total[k] = mcp_breakdown_total.get(k, 0) + v

    return {
        "run_id": entry["run_id"],
        "model_tier": entry["model_tier"],
        "arm": entry["arm"],
        "arm_label": entry.get("arm_label", entry["arm"]),
        "conversation_id": conv_id,
        "cache_discount_factor": cache_discount,
        "ledger_cards_created": entry.get("ledger_cards_created", 0),
        "notes": entry.get("notes", ""),
        "turns_detected": len(turns),
        "totals": {
            "planner_steps": sum(t["planner_steps"] for t in turn_metrics),
            "uncached_input_tokens": sum_uncached,
            "cache_read_tokens": sum_cache,
            "total_billed_input": sum_uncached + sum_cache,
            "effective_input_cost_units": round(sum_uncached + cache_discount * sum_cache, 1),
            "output_tokens": sum_out,
            "peak_context": peak_ctx,
            "mcp_calls": sum_mcp,
            "mcp_tool_breakdown": mcp_breakdown_total,
            "mcp_schema_reads": sum_schema,
            "native_reads": sum_native_r,
            "native_cmds": sum_native_c,
            "mcp_adoption_pct": round(100.0 * sum_mcp / retrieval_ops, 1) if retrieval_ops else 0.0,
            "mcp_output_tokens": sum(t["mcp_output_tokens"] for t in turn_metrics),
            "mcp_schema_tokens": sum(t["mcp_schema_tokens"] for t in turn_metrics),
            "native_output_tokens": sum(t["native_output_tokens"] for t in turn_metrics),
            "retrieved_content_tokens": sum(t["retrieved_content_tokens"] for t in turn_metrics),
            "latency_sec": round(sum(t["latency_sec"] for t in turn_metrics), 2),
            "gold_score": sum(t["gold_pass"] for t in turn_metrics),
            "gold_fraction_sum": round(sum(t["gold_fraction"] for t in turn_metrics), 2),
        },
        "turns": turn_metrics,
    }


def _pct_delta(new: float, base: float) -> str:
    if base == 0:
        return "N/A"
    diff = 100.0 * (new - base) / base
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.1f}%"


def render_markdown_report(runs: list[dict[str, Any]]) -> str:
    lines: list[str] = [
        "# Antigravity 5-Prompt Benchmark Report: No MCP (A0) vs Plain MCP (A1) vs `sample_prompt.md` (A3) vs Lean Selective (A4)",
        "",
        "> Measured directly from Antigravity `transcript.jsonl` / `transcript_full.jsonl` provider token logs (`input_tokens` = uncached new input, `cache_read_tokens` = cached prefix reads, `output_tokens` = output + thinking).",
        "",
    ]

    by_model: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        by_model.setdefault(r["model_tier"], {})[r["arm"]] = r

    lines.extend([
        "## 1. Summary Table Across Model Tiers & Arms",
        "",
        "| Model | Arm | Steps | Uncached Input | Cache Read | Eff. Input Cost | Peak Context | Output Tokens | Retrieved (MCP / Schema / Native) | MCP Adoption | Gold (0–5) | Ledger Cards | Time (s) |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | :---: | ---: | ---: |",
    ])
    for r in runs:
        t = r["totals"]
        retr = f"{t['retrieved_content_tokens']:,} ({t['mcp_output_tokens']:,} / {t['mcp_schema_tokens']:,} / {t['native_output_tokens']:,})"
        lines.append(
            f"| `{r['model_tier']}` | **{r['arm']}** ({r['arm_label']}) | {t['planner_steps']} | "
            f"{t['uncached_input_tokens']:,} | {t['cache_read_tokens']:,} | {t['effective_input_cost_units']:,.0f} | "
            f"{t['peak_context']:,} | {t['output_tokens']:,} | {retr} | {t['mcp_adoption_pct']:.1f}% | "
            f"{t['gold_score']}/5 | {r['ledger_cards_created']} | {t['latency_sec']:.1f} |"
        )

    lines.extend(["", "## 2. Paired Comparisons (A1 vs A0, A3 vs A0, A4 vs A0, A4 vs A1, A4 vs A3)", ""])
    lines.extend([
        "| Model | Comparison | Δ Uncached Input | Δ Eff. Input Cost | Δ Peak Context | Δ Retrieved Content | Δ Output Tokens |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for model, arms in by_model.items():
        for lhs, rhs in [
            ("A1", "A0"),
            ("A3", "A0"),
            ("A3", "A1"),
            ("A4", "A0"),
            ("A4", "A1"),
            ("A4", "A3"),
            ("A2", "A0"),
            ("A2", "A1"),
            ("A3", "A2"),
        ]:
            if lhs in arms and rhs in arms:
                lt = arms[lhs]["totals"]
                rt = arms[rhs]["totals"]
                lines.append(
                    f"| `{model}` | **{lhs} vs {rhs}** | "
                    f"{_pct_delta(lt['uncached_input_tokens'], rt['uncached_input_tokens'])} | "
                    f"{_pct_delta(lt['effective_input_cost_units'], rt['effective_input_cost_units'])} | "
                    f"{_pct_delta(lt['peak_context'], rt['peak_context'])} | "
                    f"{_pct_delta(lt['retrieved_content_tokens'], rt['retrieved_content_tokens'])} | "
                    f"{_pct_delta(lt['output_tokens'], rt['output_tokens'])} |"
                )

    lines.extend(["", "## 3. Per-Prompt Breakdown (`P1..P5`)", ""])
    for model, arms in by_model.items():
        lines.append(f"### Model `{model}`")
        lines.append("")
        lines.append("| Prompt | Arm | Steps | Uncached Input | Peak Ctx | Retrieved (MCP/Schema/Native) | Tools (MCP / Native) | Gold |")
        lines.append("| :--- | :--- | ---: | ---: | ---: | :---: | :---: | :---: |")
        arm_order = [a for a in ["A0", "A1", "A2", "A3", "A4"] if a in arms]
        num_turns = max((len(arms[a]["turns"]) for a in arm_order), default=0)
        for tidx in range(num_turns):
            for a in arm_order:
                t = arms[a]["turns"][tidx]
                retr = f"{t['retrieved_content_tokens']:,} ({t['mcp_output_tokens']:,}/{t['mcp_schema_tokens']:,}/{t['native_output_tokens']:,})"
                tools_str = f"{t['mcp_calls']} / {t['native_reads'] + t['native_cmds']}"
                g_str = "PASS" if t["gold_pass"] else f"MISS({len(t['missing_gold'])})"
                lines.append(
                    f"| **{t['prompt_id']}** | {a} | {t['planner_steps']} | {t['uncached_input_tokens']:,} | "
                    f"{t['peak_context']:,} | {retr} | {tools_str} | {g_str} |"
                )
        lines.append("")

    lines.extend(["## 4. MCP Tool Usage Breakdown", ""])
    for r in runs:
        if r["totals"]["mcp_calls"] or r["totals"]["mcp_schema_reads"]:
            lines.append(
                f"- **`{r['model_tier']}` / {r['arm']}** (`{r['conversation_id']}`): "
                f"schema_reads={r['totals']['mcp_schema_reads']}, mcp_calls={r['totals']['mcp_calls']} -> {r['totals']['mcp_tool_breakdown']}"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MANIFEST_PATH
    pack_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PACK_PATH

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs_in = manifest.get("runs", [])
    analyzed = [analyze_run(entry, pack, DEFAULT_BRAIN_DIR) for entry in runs_in]

    DEFAULT_REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT_JSON.write_text(json.dumps({"runs": analyzed}, indent=2, ensure_ascii=False), encoding="utf-8")
    md = render_markdown_report(analyzed)
    DEFAULT_REPORT_MD.write_text(md, encoding="utf-8")
    print(f"Wrote {DEFAULT_REPORT_MD} and {DEFAULT_REPORT_JSON} ({len(analyzed)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
