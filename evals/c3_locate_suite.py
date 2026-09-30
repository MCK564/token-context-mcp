"""Generate locate_v2 manifest for C3 v2 agent evaluation (M12.5.4).

Selects 5 tasks per repo across 4 repos (1 a_keyword, 2 b_hidden_dep, 2 c_multi_file)
deterministically with seed 20261001, plus 1 uncounted probe task.

``--role heldout`` reads ``heldout_<name>.json`` (must be ``reviewed: true``); ``--role dev`` reads the dev
``bench_<name>.json`` files.  There is no fallback between the two: a held-out manifest is never silently built from
dev tasks (M12 review).  The role is recorded in the manifest and printed by the matrix runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

SEED = 20261001

TASK_PROMPT_TEMPLATE = """You are working in a local checkout of the open-source repository "{repo_name}" ({language}). The current directory is its root. Do not create, modify or delete any file.

Question: {query}

Find where this is implemented. When you are done, end your reply with exactly one fenced JSON block and nothing after it:
```json
{{"files": ["<repo-relative path>", "..."], "symbols": [{{"path": "<repo-relative path>", "name": "<Class.method or function name>"}}]}}
```
List at most 5 files, most likely first, and at most 10 symbols."""

ARM_PREAMBLE_TEMPLATES = {
    "B0": "Use your built-in tools to read and search the code.",
    "B1": 'You can use your built-in tools and the MCP server "tcbench" (repo_id "{repo_id}"). Use at most 12 tcbench calls.',
    "B2": 'Start with the MCP server "tcbench" (repo_id "{repo_id}"). After at least one tcbench call you may make at most one built-in file-reading or search call to verify. Use at most 12 tcbench calls.',
}

REPO_DEFAULTS = {
    "heldout": [
        {"repo_id": "heldout-starlette", "repo_name": "starlette", "language": "Python", "task_file": "heldout_starlette.json"},
        {"repo_id": "heldout-zod", "repo_name": "zod", "language": "TypeScript", "task_file": "heldout_zod.json"},
        {"repo_id": "heldout-express", "repo_name": "express", "language": "JavaScript", "task_file": "heldout_express.json"},
        {"repo_id": "heldout-serilog", "repo_name": "serilog", "language": "C#", "task_file": "heldout_serilog.json"},
    ],
    "dev": [
        {"repo_id": "bench-rich", "repo_name": "rich", "language": "Python", "task_file": "bench_rich.json"},
        {"repo_id": "bench-hono", "repo_name": "hono", "language": "TypeScript", "task_file": "bench_hono.json"},
        {"repo_id": "bench-fastify", "repo_name": "fastify", "language": "JavaScript", "task_file": "bench_fastify.json"},
        {"repo_id": "bench-csvhelper", "repo_name": "csvhelper", "language": "C#", "task_file": "bench_csvhelper.json"},
    ],
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(tasks_dir: Path | None = None, role: str = "heldout") -> dict[str, Any]:
    if role not in REPO_DEFAULTS:
        raise ValueError(f"role must be one of {sorted(REPO_DEFAULTS)}")
    tdir = tasks_dir or (HERE / "tasks")
    rng = random.Random(SEED)

    selected_tasks: list[dict[str, Any]] = []

    repos = REPO_DEFAULTS[role]
    for rinfo in repos:
        repo_id = rinfo["repo_id"]
        repo_name = rinfo["repo_name"]
        language = rinfo["language"]

        task_path = tdir / rinfo["task_file"]
        if not task_path.exists():
            raise FileNotFoundError(f"No {role} task file for {repo_name}: {task_path}")
        data = json.loads(task_path.read_text(encoding="utf-8"))
        if role == "heldout" and data.get("reviewed") is not True:
            raise ValueError(f"{task_path.name} is not reviewed: true; refusing to build a held-out manifest from it")
        loaded_tasks = data.get("tasks", [])
        if not loaded_tasks:
            raise ValueError(f"{task_path.name} has no tasks")
        repo_id = data.get("repo_id", repo_id) if role == "dev" else repo_id

        # Filter out js_assigned_method tasks and group by category
        by_group: dict[str, list[dict[str, Any]]] = {
            "a_keyword": [],
            "b_hidden_dep": [],
            "c_multi_file": [],
        }
        for t in loaded_tasks:
            grp = t.get("group")
            if t.get("subgroup") == "js_assigned_method" or grp == "js_assigned_method":
                continue
            if grp in by_group:
                by_group[grp].append(t)

        # Sort tasks deterministically before sampling
        for tasks_list in by_group.values():
            tasks_list.sort(key=lambda x: str(x.get("id")))

        # Deterministic sample: 1 a_keyword, 2 b_hidden_dep, 2 c_multi_file
        a_picks = rng.sample(by_group["a_keyword"], min(1, len(by_group["a_keyword"])))
        b_picks = rng.sample(by_group["b_hidden_dep"], min(2, len(by_group["b_hidden_dep"])))
        c_picks = rng.sample(by_group["c_multi_file"], min(2, len(by_group["c_multi_file"])))

        picked = a_picks + b_picks + c_picks
        for t in picked:
            tid = f"{repo_name}_{t['id']}"
            query = t["query"]
            task_prompt = TASK_PROMPT_TEMPLATE.format(
                repo_name=repo_name,
                language=language,
                query=query,
            )
            task_sha = _sha256(task_prompt)

            preambles = {}
            preamble_shas = {}
            for arm, tpl in ARM_PREAMBLE_TEMPLATES.items():
                pre = tpl.format(repo_id=repo_id)
                preambles[arm] = pre
                preamble_shas[arm] = _sha256(pre)

            selected_tasks.append({
                "id": tid,
                "repo_id": repo_id,
                "repo_name": repo_name,
                "language": language,
                "group": t.get("group"),
                "query": query,
                "gold_files": t.get("gold_files", []),
                "gold_symbols": t.get("gold_symbols", []),
                "counted": True,
                "task_prompt": task_prompt,
                "task_prompt_sha256": task_sha,
                "arm_preambles": preambles,
                "arm_preamble_sha256": preamble_shas,
            })

    # Add 1 probe task (counted: false) on Python repo
    probe_query = "Where does this project parse its command-line arguments or configuration? Give the main file."
    py_repo = repos[0]["repo_name"]
    py_id = repos[0]["repo_id"]
    probe_task_prompt = TASK_PROMPT_TEMPLATE.format(
        repo_name=py_repo,
        language="Python",
        query=probe_query,
    )
    probe_preambles = {}
    probe_preamble_shas = {}
    for arm, tpl in ARM_PREAMBLE_TEMPLATES.items():
        pre = tpl.format(repo_id=py_id)
        probe_preambles[arm] = pre
        probe_preamble_shas[arm] = _sha256(pre)

    probe_task = {
        "id": "probe",
        "repo_id": py_id,
        "repo_name": py_repo,
        "language": "Python",
        "group": "probe",
        "query": probe_query,
        "gold_files": [],
        "gold_symbols": [],
        "counted": False,
        "task_prompt": probe_task_prompt,
        "task_prompt_sha256": _sha256(probe_task_prompt),
        "arm_preambles": probe_preambles,
        "arm_preamble_sha256": probe_preamble_shas,
    }
    selected_tasks.append(probe_task)

    return {
        "suite": "locate_v2",
        "role": role,
        "seed": SEED,
        "total_tasks": len(selected_tasks),
        "counted_tasks": sum(1 for t in selected_tasks if t.get("counted", True)),
        "tasks": selected_tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate locate_v2 manifest for C3 v2")
    parser.add_argument("--tasks-dir", type=Path, default=None)
    parser.add_argument("--role", choices=sorted(REPO_DEFAULTS), required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.output is None:
        name = "locate_v2_manifest.json" if args.role == "heldout" else "locate_v2_dev_manifest.json"
        args.output = HERE / "c3" / name

    manifest = build_manifest(args.tasks_dir, args.role)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote locate_v2 ({args.role}) manifest with {manifest['counted_tasks']} counted tasks to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
