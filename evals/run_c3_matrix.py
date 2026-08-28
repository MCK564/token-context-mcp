"""Run the predeclared C3 arm/task/seed matrix.

This orchestrator deliberately requires an explicit ``--task-success`` value.
Quality must be graded independently before benchmark-report is used for a
saving claim; the script does not infer correctness from a zero exit status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path(__file__).with_name("c3_prompts.json")
DEFAULT_RUNNER = Path(__file__).with_name("run_c3.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed C3 arm/task/seed matrix")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--runs-dir", type=Path, default=Path("evals/runs/c3-x6"))
    parser.add_argument("--usage-output", type=Path, default=Path("evals/reports/c3-x6-runs.jsonl"))
    parser.add_argument("--failure-output", type=Path, default=Path("evals/reports/c3-x6-failures.json"))
    parser.add_argument("--task-success", choices=("true", "false"), required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--arms", nargs="+", choices=("B0", "B1", "B2"), default=["B0", "B1", "B2"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    tasks = manifest.get("tasks")
    if not isinstance(tasks, dict) or set(tasks) != {"T1-orient", "T2-locate", "T3-impact", "T4-surface", "T5-trace"}:
        raise ValueError("c3_prompts.json must contain exactly the five protocol tasks")
    root = args.root or Path(str(manifest["root"]))
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for task_id, prompt_value in tasks.items():
        prompt = str(prompt_value)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        for seed in args.seeds:
            for arm in args.arms:
                protocol = "mcp-first" if arm == "B2" else "hybrid"
                raw_output = args.runs_dir / f"{arm}-{task_id}-seed{seed}.jsonl"
                stderr_output = args.runs_dir / f"{arm}-{task_id}-seed{seed}.stderr.log"
                command = [
                    sys.executable,
                    str(args.runner),
                    "--arm",
                    arm,
                    "--task-id",
                    task_id,
                    "--seed",
                    str(seed),
                    "--task-success",
                    args.task_success,
                    "--prompt-sha256",
                    prompt_sha256,
                    "--raw-output",
                    str(raw_output),
                    "--stderr-output",
                    str(stderr_output),
                    "--usage-output",
                    str(args.usage_output),
                    "--protocol",
                    protocol,
                ]
                if arm != "B0":
                    command.extend(("--require-mcp-server", "token-context", "--max-mcp-calls", "12"))
                codex = [
                    args.codex_command,
                    "exec",
                    "--ephemeral",
                    "--json",
                    "--color",
                    "never",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                    "-C",
                    str(root),
                ]
                if arm == "B0":
                    codex.extend(("-c", "mcp_servers.token-context.enabled=false"))
                command.extend(("--", *codex, prompt))
                record = {
                    "arm": arm,
                    "task_id": task_id,
                    "seed": seed,
                    "prompt_sha256": prompt_sha256,
                    "command": command,
                }
                records.append(record)
                if args.dry_run:
                    print(json.dumps(record, sort_keys=True))
                    continue
                completed = subprocess.run(command, check=False)
                if completed.returncode != 0:
                    failure = {**record, "returncode": completed.returncode}
                    failures.append(failure)
                    print(json.dumps(failure, sort_keys=True), file=sys.stderr)

    if args.dry_run:
        return 0
    args.failure_output.parent.mkdir(parents=True, exist_ok=True)
    args.failure_output.write_text(json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"attempted": len(records), "failures": len(failures), "failure_output": str(args.failure_output)}))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
