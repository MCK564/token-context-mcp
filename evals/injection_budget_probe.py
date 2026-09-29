"""M9.6: mean number of search_source matches @2.048 (and tokens) on the dev localization tasks, plus a repository scan.

    PYTHONPATH=<src of the code under test> uv run python evals/injection_budget_probe.py --config C --repo-id R --output F
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import token_context_mcp
from token_context_mcp.config import load_config
from token_context_mcp.retrieve.service import RetrievalService, _payload_tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=Path("evals/tasks/loc_token_context.json"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repo-id", default="tc-pinned")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    tasks = [t for t in json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"] if t["split"] == "dev"]
    service = RetrievalService(load_config(args.config), args.config)
    counts, tokens = [], []
    for task in tasks:
        response = service.search_source(args.repo_id, query=task["query"], max_tokens=args.max_tokens, expand="none")
        counts.append(len(response["data"]["matches"]))
        tokens.append(_payload_tokens(response))
    report = {
        "code": str(Path(token_context_mcp.__file__).parent),
        "max_tokens": args.max_tokens,
        "dev_tasks": len(tasks),
        "matches_mean": round(statistics.mean(counts), 3),
        "matches": counts,
        "tokens_mean": round(statistics.mean(tokens), 1),
    }
    print(json.dumps(report))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
