"""Run the predeclared C3 arm/task/seed matrix for multi-agent evaluation.

Supports Codex, Claude Code, and Gemini CLI across c3_v1 and locate_v2 suites.
Deterministic arm shuffling per (task, seed) with seed 20261001.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from evals.c3_adapters import ClaudeAdapter, GeminiAdapter
except (ImportError, ModuleNotFoundError):
    from c3_adapters import ClaudeAdapter, GeminiAdapter  # type: ignore

DEFAULT_V1_MANIFEST = Path(__file__).with_name("c3_prompts.json")
DEFAULT_V2_MANIFEST = Path(__file__).resolve().parent / "c3" / "locate_v2_manifest.json"
DEFAULT_RUNNER = Path(__file__).with_name("run_c3.py")
SHUFFLE_SEED = 20261001


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the multi-agent C3 arm/task/seed matrix")
    parser.add_argument("--agent", choices=("codex", "claude", "gemini"), default="claude")
    parser.add_argument("--suite", choices=("c3_v1", "locate_v2"), default="locate_v2")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--run-config", type=Path, default=None)
    parser.add_argument("--seeds", nargs="+", type=int, default=None)
    parser.add_argument("--arms", nargs="+", choices=("B0", "B1", "B2"), default=["B0", "B1", "B2"])
    parser.add_argument("--resume", action="store_true", help="Skip already completed runs")
    parser.add_argument("--dry-run", action="store_true", help="Print scheduled runs without executing")
    parser.add_argument("--max-runs", type=int, default=None, help="Limit number of scheduled runs")
    parser.add_argument("--only-repo", type=str, default=None, help="Filter tasks by repo name/id")
    parser.add_argument("--only-tasks", nargs="+", type=str, default=None, help="Filter tasks by task ID")
    parser.add_argument("--task-success", choices=("true", "false"), default=None)
    parser.add_argument("--runs-dir", type=Path, default=None)
    parser.add_argument("--usage-output", type=Path, default=None)
    parser.add_argument("--failure-output", type=Path, default=None)
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--claude-command", default="claude")
    parser.add_argument("--gemini-command", default="gemini")
    parser.add_argument("--timeout-s", type=float, default=900.0)
    return parser.parse_args(argv)


def load_completed_runs(usage_output: Path) -> set[tuple[str, str, str, int]]:
    """Return set of (agent, arm, task_id, seed) already recorded in usage_output."""
    completed: set[tuple[str, str, str, int]] = set()
    if not usage_output.exists():
        return completed
    for line in usage_output.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                ag = item.get("agent", "")
                arm = item.get("arm", "")
                tid = item.get("task_id", "")
                sd = int(item.get("seed", 0))
                if arm and tid:
                    completed.add((ag, arm, tid, sd))
        except (json.JSONDecodeError, ValueError):
            continue
    return completed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Resolve manifest path
    manifest_path = args.manifest
    if manifest_path is None:
        manifest_path = DEFAULT_V2_MANIFEST if args.suite == "locate_v2" else DEFAULT_V1_MANIFEST

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Resolve seeds
    if args.seeds is not None:
        seeds = list(args.seeds)
    else:
        seeds = [1, 2] if args.suite == "locate_v2" else [1, 2, 3]

    # Resolve paths
    runs_dir = args.runs_dir or Path(f"evals/runs/{args.suite}")
    usage_output = args.usage_output or Path(f"evals/reports/{args.suite}-runs.jsonl")
    failure_output = args.failure_output or Path(f"evals/reports/{args.suite}-failures.json")

    # Load run config
    run_config: dict[str, Any] = {}
    if args.run_config and args.run_config.exists():
        run_config = json.loads(args.run_config.read_text(encoding="utf-8"))

    if args.agent == "claude" and "agent_command" not in run_config:
        run_config["agent_command"] = [args.claude_command]
    elif args.agent == "gemini" and "agent_command" not in run_config:
        run_config["agent_command"] = [args.gemini_command]
    elif args.agent == "codex" and "agent_command" not in run_config:
        run_config["agent_command"] = [args.codex_command]

    # Normalization of tasks list
    task_items: list[dict[str, Any]] = []
    if args.suite == "locate_v2":
        raw_tasks = manifest_data.get("tasks", [])
        for t in raw_tasks:
            # Skip uncounted probe task
            if not t.get("counted", True):
                continue
            task_items.append(t)
    else:
        v1_tasks = manifest_data.get("tasks", {})
        if not isinstance(v1_tasks, dict):
            raise ValueError("c3_v1 manifest must have a 'tasks' dictionary")
        for tid, prompt_val in v1_tasks.items():
            task_items.append({
                "id": tid,
                "task_prompt": str(prompt_val),
                "counted": True,
            })

    # Task filtering
    if args.only_repo:
        repo_filter = args.only_repo.lower()
        task_items = [
            t for t in task_items
            if repo_filter in str(t.get("repo_name", "")).lower() or repo_filter in str(t.get("repo_id", "")).lower()
        ]

    if args.only_tasks:
        task_set = set(args.only_tasks)
        task_items = [t for t in task_items if str(t.get("id")) in task_set]

    completed_runs = load_completed_runs(usage_output) if args.resume else set()

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for task in task_items:
        task_id = str(task["id"])
        base_prompt = str(task.get("task_prompt", ""))
        repo_name = str(task.get("repo_name", ""))

        # Determine workdir
        workdir = args.root
        if workdir is None:
            if "repo_roots" in run_config and repo_name in run_config["repo_roots"]:
                workdir = Path(run_config["repo_roots"][repo_name])
            elif "root" in manifest_data:
                workdir = Path(str(manifest_data["root"]))
            else:
                workdir = Path.cwd()

        for seed in seeds:
            # Deterministic arm shuffling per (task, seed)
            pair_str = f"{SHUFFLE_SEED}_{task_id}_{seed}"
            pair_seed = int(hashlib.sha256(pair_str.encode("utf-8")).hexdigest()[:8], 16)
            task_rng = random.Random(pair_seed)
            shuffled_arms = list(args.arms)
            task_rng.shuffle(shuffled_arms)

            for arm in shuffled_arms:
                if args.max_runs is not None and len(records) >= args.max_runs:
                    break

                if args.resume and (args.agent, arm, task_id, seed) in completed_runs:
                    continue

                protocol = "mcp-first" if arm == "B2" else "hybrid"
                raw_output = runs_dir / f"{args.agent}-{arm}-{task_id}-seed{seed}.jsonl"
                stderr_output = runs_dir / f"{args.agent}-{arm}-{task_id}-seed{seed}.stderr.log"

                # Prompt construction
                if args.suite == "locate_v2":
                    preamble = task.get("arm_preambles", {}).get(arm, "")
                    if preamble:
                        prompt = f"{preamble}\n\n{base_prompt}"
                    else:
                        prompt = base_prompt
                else:
                    prompt = base_prompt

                prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

                # Build runner command
                command = [
                    sys.executable,
                    str(args.runner),
                    "--agent",
                    args.agent,
                    "--arm",
                    arm,
                    "--task-id",
                    task_id,
                    "--seed",
                    str(seed),
                    "--prompt-sha256",
                    prompt_sha256,
                    "--raw-output",
                    str(raw_output),
                    "--stderr-output",
                    str(stderr_output),
                    "--usage-output",
                    str(usage_output),
                    "--protocol",
                    protocol,
                    "--workdir",
                    str(workdir),
                    "--timeout-s",
                    str(args.timeout_s),
                ]

                if args.task_success is not None:
                    command.extend(("--task-success", args.task_success))
                else:
                    command.extend(("--grade-with", str(manifest_path)))

                if arm != "B0":
                    server_name = "tcbench" if args.suite == "locate_v2" else "token-context"
                    command.extend(("--require-mcp-server", server_name, "--max-mcp-calls", "12"))

                # Agent-specific command generation
                if args.agent == "codex":
                    codex_bin = run_config.get("agent_command", [args.codex_command])[0]
                    codex = [
                        codex_bin,
                        "exec",
                        "--ephemeral",
                        "--json",
                        "--color",
                        "never",
                        "--sandbox",
                        "read-only",
                        "--skip-git-repo-check",
                        "-C",
                        str(workdir),
                    ]
                    if arm == "B0":
                        server_prop = "tcbench" if args.suite == "locate_v2" else "token-context"
                        codex.extend(("-c", f"mcp_servers.{server_prop}.enabled=false"))
                    command.extend(("--", *codex, prompt))

                elif args.agent == "claude":
                    claude_adapter = ClaudeAdapter()
                    cmd, stdin_text, _env = claude_adapter.build_command(
                        arm=arm,
                        prompt_text=prompt,
                        workdir=workdir,
                        extra_config=run_config,
                    )
                    if stdin_text:
                        command.extend(("--stdin-prompt", stdin_text))
                    command.extend(("--", *cmd))

                elif args.agent == "gemini":
                    gemini_adapter = GeminiAdapter()
                    cmd, stdin_text, _env = gemini_adapter.build_command(
                        arm=arm,
                        prompt_text=prompt,
                        workdir=workdir,
                        extra_config=run_config,
                    )
                    if stdin_text:
                        command.extend(("--stdin-prompt", stdin_text))
                    command.extend(("--", *cmd))

                record = {
                    "agent": args.agent,
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

            if args.max_runs is not None and len(records) >= args.max_runs:
                break

    if args.dry_run:
        return 0

    failure_output.parent.mkdir(parents=True, exist_ok=True)
    failure_output.write_text(json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "agent": args.agent,
        "suite": args.suite,
        "attempted": len(records),
        "failures": len(failures),
        "failure_output": str(failure_output),
    }))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
