"""M9.7: how many matches fit the ``locate`` profile, and what it costs, on the dev localization tasks.

    uv run python evals/locate_profile_probe.py --repo-id tc-pinned --config tmp/dev/repos.toml --output evals/out/m9/locate_probe.json

Variants (no contract change, no field removed from a match):
  base   locate as shipped (shipped before M9.7: 1.024 tokens, 2 snippet lines)
  a      snippet_lines = 1
  b      budget_tokens = 2.048
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
from pathlib import Path

from token_context_mcp.config import DEFAULT_BUDGET_PROFILES, default_config_path, load_config
from token_context_mcp.retrieve.service import RetrievalService, _payload_tokens

VARIANTS = {
    "base": {},
    "a_one_line": {"snippet_lines": 1},
    "b_2048": {"budget_tokens": 2048},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=Path("evals/tasks/loc_token_context.json"))
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--repo-id", default="tc-pinned")
    parser.add_argument("--split", default="dev")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    tasks = [t for t in json.loads(args.tasks.read_text(encoding="utf-8"))["tasks"] if t["split"] == args.split]
    report: dict[str, object] = {"split": args.split, "tasks": len(tasks), "variants": {}}
    for name, override in VARIANTS.items():
        config = load_config(args.config)
        profile = {**copy.deepcopy(DEFAULT_BUDGET_PROFILES["locate"]), **override}
        config.budget_profiles["locate"] = profile
        service = RetrievalService(config, args.config)
        matches, tokens, hits = [], [], 0
        for task in tasks:
            response = service.search_source(args.repo_id, query=task["query"], profile="locate")
            rows = response["data"]["matches"]
            matches.append(len(rows))
            tokens.append(_payload_tokens(response))
            top_files: list[str] = []
            for row in rows:
                if row["path"] not in top_files:
                    top_files.append(row["path"])
            if set(top_files[:5]) & set(task["gold_files"]):
                hits += 1
        report["variants"][name] = {
            "profile": profile,
            "matches_mean": round(statistics.mean(matches), 2),
            "matches_median": statistics.median(matches),
            "matches_min": min(matches),
            "file_acc_at_5": round(hits / len(tasks), 4),
            "tokens_mean": round(statistics.mean(tokens), 1),
            "tokens_max": max(tokens),
        }
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
