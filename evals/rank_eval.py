"""Measure repo_map ranking quality against a labelled relevance set.

Answers one question: does the ranked slice a caller actually receives contain
the symbols an orientation task needs, and does it keep out the ones it does
not? Reports precision@k, recall of essential symbols, nDCG@k, and — the
metric that motivated this harness — how many grade-0 items reach the top 10.

This is a *relevance* measurement, not a token measurement. Run
evals/measure_context_cost.py for cost.

Usage:
    python evals/rank_eval.py --set evals/relevance/orientation_invoice_scanner.json
    python evals/rank_eval.py --set ... --budget 4096 --output evals/reports/rank-before.json
    python evals/rank_eval.py --set ... --compare evals/reports/rank-before.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from token_context_mcp.config import default_config_path, load_config
from token_context_mcp.retrieve.service import RetrievalService


def load_set(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for field in ("repo_id",):
        if field not in data:
            raise ValueError(f"relevance set is missing '{field}'")
    if "items" not in data and "topics" not in data:
        raise ValueError("relevance set must contain 'items' or 'topics'")
    if "topics" in data and not isinstance(data["topics"], list):
        raise ValueError("relevance set 'topics' must be a list")
    return data


def ranked_symbols(service: RetrievalService, repo_id: str, *, query: str | None, budget: int) -> list[dict[str, Any]]:
    """Return the ranked slice a caller receives, in either response format.

    compact (E-P0 default): ["<short_id>", "<path>:<line>", "<kind> <name>", optional marker]
    full:                   {"rank": .., "symbol": {"name": .., "path": ..}, ..}
    """
    response = service.repo_map(repo_id, query=query, budget_tokens=budget)
    if "error" in response:
        raise RuntimeError(f"repo_map returned an error envelope: {response['error']}")
    data = response.get("data", {})
    out: list[dict[str, Any]] = []
    for entry in data.get("symbols", []):
        if isinstance(entry, list):
            if len(entry) < 3:
                continue
            location = str(entry[1])
            path = location.rsplit(":", 1)[0] if ":" in location else location
            name = str(entry[2]).split(" ", 1)[-1].strip()
            out.append({"name": name, "path": path, "rank": None})
            continue
        symbol = entry.get("symbol", entry)
        name, path = symbol.get("name"), symbol.get("path")
        if name is not None:
            out.append({"name": name, "path": path, "rank": entry.get("rank")})
    if not out:
        raise RuntimeError(f"could not parse repo_map format={data.get('format')!r}")
    return out


def evaluate(ranked: list[dict[str, Any]], items: list[dict[str, Any]], *, k: int) -> dict[str, Any]:
    grade_by_key = {(i["symbol"], i["path"]): i["grade"] for i in items}
    grade_by_name: dict[str, int] = {}
    for i in items:
        grade_by_name.setdefault(i["symbol"], i["grade"])

    def grade_of(entry: dict[str, Any]) -> int | None:
        key = (entry["name"], entry.get("path"))
        if key in grade_by_key:
            return grade_by_key[key]
        # Compact entries still carry a repository-relative path, so do not
        # misgrade duplicate names (especially the many ``run`` functions).
        # Name-only fallback is reserved for response formats that omit path.
        return grade_by_name.get(entry["name"]) if not entry.get("path") else None

    top = ranked[:k]
    graded = [(e, grade_of(e)) for e in top]
    labelled = [(e, g) for e, g in graded if g is not None]

    essential = [i for i in items if i["grade"] == 3]
    found_essential = [
        i
        for i in essential
        if any(
            e["name"] == i["symbol"]
            and (not i.get("path") or e.get("path") == i["path"])
            for e in top
        )
    ]
    noise_in_top = [e for e, g in labelled if g == 0]

    gains = [(g if g is not None else 0) for _, g in graded]
    dcg = sum((2 ** g - 1) / math.log2(rank + 2) for rank, g in enumerate(gains))
    ideal = sorted((i["grade"] for i in items), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(rank + 2) for rank, g in enumerate(ideal))

    return {
        "k": k,
        "returned": len(ranked),
        "labelled_in_top_k": len(labelled),
        "essential_total": len(essential),
        "essential_found": len(found_essential),
        "essential_recall": round(len(found_essential) / len(essential), 3) if essential else None,
        "essential_missing": sorted(
            i["symbol"] for i in essential if i not in found_essential
        ),
        "noise_in_top_k": len(noise_in_top),
        "noise_names": [e["name"] for e in noise_in_top],
        "ndcg_at_k": round(dcg / idcg, 4) if idcg else None,
        "top_k_listing": [
            {"name": e["name"], "path": e.get("path"), "grade": g}
            for e, g in graded
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure repo_map ranking against a labelled relevance set")
    parser.add_argument("--set", dest="set_path", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--budget", type=int, default=4096)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path, help="an earlier --output file to diff against")
    parser.add_argument(
        "--global-rank",
        action="store_true",
        help="evaluate every topic against the query-free global ranking (baseline arm)",
    )
    args = parser.parse_args()

    spec = load_set(args.set_path)
    config = load_config(args.config)
    budget = min(args.budget, config.server.max_result_tokens)
    service = RetrievalService(config, args.config)

    if "topics" in spec:
        topic_reports = []
        for topic in spec["topics"]:
            if not isinstance(topic, dict) or "query" not in topic or "items" not in topic:
                raise ValueError("each topic must contain query and items")
            ranked = ranked_symbols(
                service,
                spec["repo_id"],
                query=None if args.global_rank else topic["query"],
                budget=budget,
            )
            topic_reports.append(
                {
                    "topic_id": topic.get("topic_id", topic["query"]),
                    "query": topic["query"],
                    "result": evaluate(ranked, topic["items"], k=args.k),
                }
            )
        result = {
            "topic_count": len(topic_reports),
            "topics": topic_reports,
            "mean_essential_recall": round(
                sum(item["result"]["essential_recall"] or 0 for item in topic_reports) / len(topic_reports),
                3,
            )
            if topic_reports
            else None,
            "topics_with_zero_noise": sum(item["result"]["noise_in_top_k"] == 0 for item in topic_reports),
            "distinct_top_k_count": len(
                {
                    tuple(row["name"] for row in item["result"]["top_k_listing"])
                    for item in topic_reports
                }
            ),
        }
        report = {
            "set_id": spec.get("set_id"),
            "repo_id": spec["repo_id"],
            "budget_tokens": budget,
            "server_max_result_tokens": config.server.max_result_tokens,
            "rank_mode": "global" if args.global_rank or spec.get("query") is None else "seed_biased",
            "result": result,
        }
    else:
        ranked = ranked_symbols(service, spec["repo_id"], query=spec.get("query"), budget=budget)
        result = evaluate(ranked, spec["items"], k=args.k)
        report = {
            "set_id": spec.get("set_id"),
            "repo_id": spec["repo_id"],
            "budget_tokens": budget,
            "server_max_result_tokens": config.server.max_result_tokens,
            "rank_mode": "global" if args.global_rank or spec.get("query") is None else "seed_biased",
            "result": result,
        }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    print(f"set     : {report['set_id']}")
    print(f"repo    : {report['repo_id']}   budget={budget}   k={args.k}")
    if "topics" in result:
        for topic in result["topics"]:
            topic_result = topic["result"]
            print(f"\n[{topic['topic_id']}] query={topic['query']}")
            print(f"  essential recall : {topic_result['essential_found']}/{topic_result['essential_total']} = {topic_result['essential_recall']}")
            print(f"  noise in top-{args.k} : {topic_result['noise_in_top_k']} {topic_result['noise_names']}")
            print(f"  nDCG@{args.k}          : {topic_result['ndcg_at_k']}")
        print(f"\n  mean essential recall : {result['mean_essential_recall']}")
        print(f"  distinct top-{args.k} lists: {result['distinct_top_k_count']}")
    else:
        print(f"returned: {result['returned']} symbols\n")
        print(f"  {'#':>2} {'grade':>5}  {'symbol':28s} path")
        for rank, row in enumerate(result["top_k_listing"], start=1):
            grade = "-" if row["grade"] is None else str(row["grade"])
            flag = "  <-- NOISE" if row["grade"] == 0 else ""
            print(f"  {rank:>2} {grade:>5}  {row['name']:28s} {row['path'] or ''}{flag}")
        print()
        print(f"  essential recall : {result['essential_found']}/{result['essential_total']} = {result['essential_recall']}")
        if result["essential_missing"]:
            print(f"  essential missing: {', '.join(result['essential_missing'])}")
        print(f"  noise in top-{args.k}   : {result['noise_in_top_k']} {result['noise_names']}")
        print(f"  nDCG@{args.k}          : {result['ndcg_at_k']}")

    if args.compare and args.compare.exists():
        before = json.loads(args.compare.read_text(encoding="utf-8"))["result"]
        print(f"\n  vs {args.compare.name}:")
        if "topics" in result:
            print(
                f"    mean essential recall {before.get('mean_essential_recall')} -> "
                f"{result.get('mean_essential_recall')}"
            )
            print(
                f"    distinct top-{args.k} lists {before.get('distinct_top_k_count')} -> "
                f"{result.get('distinct_top_k_count')}"
            )
            return 0
        for field in ("essential_recall", "ndcg_at_k", "noise_in_top_k"):
            was, now = before.get(field), result.get(field)
            if was is None or now is None:
                continue
            arrow = "->" if was == now else ("improved" if (now > was) == (field != "noise_in_top_k") else "REGRESSED")
            print(f"    {field:18s} {was} -> {now}   {arrow}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
