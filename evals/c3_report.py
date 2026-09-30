"""Aggregate and report C3 evaluation metrics (M12.5.7).

Calculates per-arm and per-group success rates, bootstrap CIs, violation rates,
and token savings (paired differences B1 vs B0, B2 vs B0, B2 vs B1).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any

BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20261001


def bootstrap_ci(values: list[float], samples: int = BOOTSTRAP_SAMPLES) -> list[float] | None:
    """95% CI of the mean using fixed deterministic seed."""
    if not values:
        return None
    if len(values) == 1:
        return [round(values[0], 4), round(values[0], 4)]
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(
        statistics.fmean(values[rng.randrange(len(values))] for _ in values)
        for _ in range(samples)
    )
    lo = round(means[int(0.025 * (len(means) - 1))], 4)
    hi = round(means[int(0.975 * (len(means) - 1))], 4)
    return [lo, hi]


def paired_diff(
    a_records: list[dict[str, Any]],
    b_records: list[dict[str, Any]],
    metric: str,
) -> dict[str, Any]:
    """Calculate mean(a - b) over matching (task_id, seed) pairs with bootstrap CI95."""
    b_map = {(r["task_id"], r["seed"]): r for r in b_records if "task_id" in r and "seed" in r}
    diffs: list[float] = []
    a_vals: list[float] = []
    b_vals: list[float] = []

    for r in a_records:
        key = (r.get("task_id"), r.get("seed"))
        if key in b_map:
            b_item = b_map[key]
            va = r.get(metric)
            vb = b_item.get(metric)
            if va is not None and vb is not None:
                fa = float(va)
                fb = float(vb)
                diffs.append(fa - fb)
                a_vals.append(fa)
                b_vals.append(fb)

    if not diffs:
        return {"pairs": 0, "mean_diff": None, "ci95": None, "percent_reduction": None}

    mean_diff = round(statistics.fmean(diffs), 4)
    b_mean = statistics.fmean(b_vals) if b_vals else 0.0
    pct_red = round((-(mean_diff) / b_mean) * 100.0, 2) if b_mean > 0 else None

    return {
        "pairs": len(diffs),
        "mean_diff": mean_diff,
        "ci95": bootstrap_ci(diffs),
        "percent_reduction": pct_red,
    }


def analyze_runs(
    records: list[dict[str, Any]],
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute full aggregated statistics from run records."""
    task_meta: dict[str, dict[str, Any]] = {}
    if manifest and isinstance(manifest.get("tasks"), list):
        for t in manifest["tasks"]:
            if isinstance(t, dict) and "id" in t:
                task_meta[str(t["id"])] = t

    total_runs = len(records)
    failures = [r for r in records if r.get("failure_type")]
    violations = [r for r in records if r.get("failure_type") == "protocol_violation"]
    infra_fails = [r for r in records if r.get("failure_type") == "infra_failure"]
    runtime_errs = [r for r in records if r.get("failure_type") == "runtime_error"]

    per_arm_records: dict[str, list[dict[str, Any]]] = {"B0": [], "B1": [], "B2": []}
    for r in records:
        arm = str(r.get("arm", "unknown"))
        if arm in per_arm_records:
            per_arm_records[arm].append(r)

    arm_summaries: dict[str, Any] = {}
    for arm, arm_recs in per_arm_records.items():
        n = len(arm_recs)
        if n == 0:
            arm_summaries[arm] = {"runs": 0}
            continue

        successes = [1.0 if r.get("task_success") else 0.0 for r in arm_recs]
        succ_rate = round(statistics.fmean(successes), 4)
        succ_ci = bootstrap_ci(successes)

        retrieved_tokens = [float(r["retrieved_content_estimated_tokens"]) for r in arm_recs if "retrieved_content_estimated_tokens" in r]
        input_tokens = [float(r["input_tokens"]) for r in arm_recs if "input_tokens" in r]
        output_tokens = [float(r["output_tokens"]) for r in arm_recs if "output_tokens" in r]
        total_tokens = [float(r["total_tokens"]) for r in arm_recs if "total_tokens" in r]
        cached_tokens = [float(r["cached_input_tokens"]) for r in arm_recs if "cached_input_tokens" in r]
        latencies = [float(r["latency_seconds"]) for r in arm_recs if "latency_seconds" in r]
        mcp_calls = [float(r["mcp_completed_call_count"]) for r in arm_recs if "mcp_completed_call_count" in r]
        native_calls = [float(r["native_command_count"]) for r in arm_recs if "native_command_count" in r]

        arm_summaries[arm] = {
            "runs": n,
            "success_rate": succ_rate,
            "success_ci95": succ_ci,
            "retrieved_tokens_mean": round(statistics.fmean(retrieved_tokens), 1) if retrieved_tokens else None,
            "retrieved_tokens_ci95": bootstrap_ci(retrieved_tokens) if retrieved_tokens else None,
            "input_tokens_mean": round(statistics.fmean(input_tokens), 1) if input_tokens else None,
            "output_tokens_mean": round(statistics.fmean(output_tokens), 1) if output_tokens else None,
            "total_tokens_mean": round(statistics.fmean(total_tokens), 1) if total_tokens else None,
            "total_tokens_ci95": bootstrap_ci(total_tokens) if total_tokens else None,
            "cached_tokens_mean": round(statistics.fmean(cached_tokens), 1) if cached_tokens else None,
            "latency_mean_s": round(statistics.fmean(latencies), 2) if latencies else None,
            "mcp_calls_mean": round(statistics.fmean(mcp_calls), 2) if mcp_calls else 0.0,
            "native_calls_mean": round(statistics.fmean(native_calls), 2) if native_calls else 0.0,
        }

    # Paired comparisons
    b0 = per_arm_records["B0"]
    b1 = per_arm_records["B1"]
    b2 = per_arm_records["B2"]

    paired_results = {
        "b1_vs_b0": {
            "retrieved_tokens": paired_diff(b1, b0, "retrieved_content_estimated_tokens"),
            "total_tokens": paired_diff(b1, b0, "total_tokens"),
            "task_success": paired_diff(b1, b0, "task_success"),
        },
        "b2_vs_b0": {
            "retrieved_tokens": paired_diff(b2, b0, "retrieved_content_estimated_tokens"),
            "total_tokens": paired_diff(b2, b0, "total_tokens"),
            "task_success": paired_diff(b2, b0, "task_success"),
        },
        "b2_vs_b1": {
            "retrieved_tokens": paired_diff(b2, b1, "retrieved_content_estimated_tokens"),
            "total_tokens": paired_diff(b2, b1, "total_tokens"),
            "task_success": paired_diff(b2, b1, "task_success"),
        },
    }

    # Group breakdown
    group_summaries: dict[str, dict[str, Any]] = {}
    if task_meta:
        groups = sorted({meta.get("group") for meta in task_meta.values() if meta.get("group")})
        for grp in groups:
            group_summaries[grp] = {}
            for arm in ("B0", "B1", "B2"):
                grp_recs = [
                    r for r in per_arm_records[arm]
                    if task_meta.get(str(r.get("task_id")), {}).get("group") == grp
                ]
                if grp_recs:
                    succs = [1.0 if r.get("task_success") else 0.0 for r in grp_recs]
                    toks = [float(r["retrieved_content_estimated_tokens"]) for r in grp_recs if "retrieved_content_estimated_tokens" in r]
                    group_summaries[grp][arm] = {
                        "runs": len(grp_recs),
                        "success_rate": round(statistics.fmean(succs), 4),
                        "retrieved_tokens_mean": round(statistics.fmean(toks), 1) if toks else None,
                    }

    return {
        "total_runs": total_runs,
        "completed_runs": total_runs - len(failures),
        "failures_count": len(failures),
        "protocol_violations": len(violations),
        "infra_failures": len(infra_fails),
        "runtime_errors": len(runtime_errs),
        "protocol_violation_rate": round(len(violations) / total_runs, 4) if total_runs else 0.0,
        "infra_failure_rate": round(len(infra_fails) / total_runs, 4) if total_runs else 0.0,
        "arms": arm_summaries,
        "paired": paired_results,
        "groups": group_summaries,
    }


def format_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# C3 Benchmark Report",
        "",
        f"- **Total Runs:** {summary['total_runs']}",
        f"- **Completed:** {summary['completed_runs']}",
        f"- **Protocol Violations:** {summary['protocol_violations']} ({summary['protocol_violation_rate']*100:.2f}%)",
        f"- **Infra Failures:** {summary['infra_failures']} ({summary['infra_failure_rate']*100:.2f}%)",
        "",
        "## Arm Summary",
        "",
        "| Arm | Runs | Success Rate (CI95) | Retrieved Tokens (CI95) | Total Tokens (CI95) | MCP Calls | Native Calls | Latency (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for arm, data in summary.get("arms", {}).items():
        if data.get("runs", 0) == 0:
            continue
        sr = f"{data['success_rate']*100:.1f}% ({data['success_ci95'][0]*100:.1f}%..{data['success_ci95'][1]*100:.1f}%)" if data.get("success_ci95") else f"{data.get('success_rate', 0)*100:.1f}%"
        rt_ci = f"{data['retrieved_tokens_ci95'][0]:.0f}..{data['retrieved_tokens_ci95'][1]:.0f}" if data.get("retrieved_tokens_ci95") else "-"
        tt_ci = f"{data['total_tokens_ci95'][0]:.0f}..{data['total_tokens_ci95'][1]:.0f}" if data.get("total_tokens_ci95") else "-"
        lines.append(
            f"| {arm} | {data['runs']} | {sr} | {data.get('retrieved_tokens_mean', '-')} ({rt_ci}) | {data.get('total_tokens_mean', '-')} ({tt_ci}) | {data.get('mcp_calls_mean', 0):.1f} | {data.get('native_calls_mean', 0):.1f} | {data.get('latency_mean_s', '-')} |"
        )

    lines.extend([
        "",
        "## Paired Reductions",
        "",
        "| Comparison | Metric | Pairs | Mean Diff | CI95 | % Reduction |",
        "|---|---|---:|---:|---:|---:|",
    ])

    for comp, comp_data in summary.get("paired", {}).items():
        for m_name, m_data in comp_data.items():
            if m_data.get("pairs", 0) > 0:
                ci_str = f"{m_data['ci95'][0]}..{m_data['ci95'][1]}" if m_data.get("ci95") else "-"
                pct_str = f"{m_data['percent_reduction']}%" if m_data.get("percent_reduction") is not None else "-"
                lines.append(
                    f"| {comp} | {m_name} | {m_data['pairs']} | {m_data['mean_diff']} | {ci_str} | {pct_str} |"
                )

    if summary.get("groups"):
        lines.extend([
            "",
            "## Group Performance",
            "",
            "| Group | B0 Success | B1 Success | B2 Success | B0 Retrieved | B1 Retrieved | B2 Retrieved |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ])
        for grp, g_arms in summary["groups"].items():
            b0_s = f"{g_arms.get('B0', {}).get('success_rate', 0)*100:.1f}%" if "B0" in g_arms else "-"
            b1_s = f"{g_arms.get('B1', {}).get('success_rate', 0)*100:.1f}%" if "B1" in g_arms else "-"
            b2_s = f"{g_arms.get('B2', {}).get('success_rate', 0)*100:.1f}%" if "B2" in g_arms else "-"
            b0_r = f"{g_arms.get('B0', {}).get('retrieved_tokens_mean', '-')}" if "B0" in g_arms else "-"
            b1_r = f"{g_arms.get('B1', {}).get('retrieved_tokens_mean', '-')}" if "B1" in g_arms else "-"
            b2_r = f"{g_arms.get('B2', {}).get('retrieved_tokens_mean', '-')}" if "B2" in g_arms else "-"
            lines.append(f"| {grp} | {b0_s} | {b1_s} | {b2_s} | {b0_r} | {b1_r} | {b2_r} |")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate C3 evaluation report")
    parser.add_argument("--runs-file", type=Path, required=True, help="Path to JSONL usage file")
    parser.add_argument("--manifest", type=Path, default=None, help="Path to manifest JSON")
    parser.add_argument("--output", type=Path, default=None, help="Path to write report")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)

    if not args.runs_file.exists():
        raise FileNotFoundError(f"Runs file not found: {args.runs_file}")

    records: list[dict[str, Any]] = []
    for line in args.runs_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    manifest: dict[str, Any] | None = None
    if args.manifest and args.manifest.exists():
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    summary = analyze_runs(records, manifest)

    if args.format == "json":
        out_text = json.dumps(summary, indent=2) + "\n"
    else:
        out_text = format_markdown(summary)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out_text, encoding="utf-8")
        print(f"Report saved to {args.output}")
    else:
        print(out_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
