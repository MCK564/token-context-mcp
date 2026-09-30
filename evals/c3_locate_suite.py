"""Generate locate_v2 manifest for C3 v2 agent evaluation (M12.5.4).

Selects 5 tasks per repo across 4 repos (1 a_keyword, 2 b_hidden_dep, 2 c_multi_file)
deterministically with seed 20261001, plus 1 uncounted probe task.
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

REPO_DEFAULTS = [
    {
        "repo_id": "heldout-starlette",
        "repo_name": "starlette",
        "language": "Python",
        "task_files": ["heldout_starlette.json", "bench_rich.json"],
    },
    {
        "repo_id": "heldout-zod",
        "repo_name": "zod",
        "language": "TypeScript",
        "task_files": ["heldout_zod.json", "bench_hono.json"],
    },
    {
        "repo_id": "heldout-express",
        "repo_name": "express",
        "language": "JavaScript",
        "task_files": ["heldout_express.json", "bench_fastify.json"],
    },
    {
        "repo_id": "heldout-serilog",
        "repo_name": "serilog",
        "language": "C#",
        "task_files": ["heldout_serilog.json", "bench_csvhelper.json"],
    },
]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(tasks_dir: Path | None = None) -> dict[str, Any]:
    tdir = tasks_dir or (HERE / "tasks")
    rng = random.Random(SEED)

    selected_tasks: list[dict[str, Any]] = []

    for rinfo in REPO_DEFAULTS:
        repo_id = rinfo["repo_id"]
        repo_name = rinfo["repo_name"]
        language = rinfo["language"]

        # Find best available task file
        loaded_tasks: list[dict[str, Any]] = []
        for cand in rinfo["task_files"]:
            p = tdir / cand
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                loaded_tasks = data.get("tasks", [])
                if cand.startswith("bench_"):
                    # fallback repo_id from bench file
                    repo_id = data.get("repo_id", repo_id)
                    repo_name = repo_id.replace("bench-", "")
                break

        if not loaded_tasks:
            raise FileNotFoundError(f"No task file found for {repo_name} in {tdir}")

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
    py_repo = REPO_DEFAULTS[0]["repo_name"]
    py_id = REPO_DEFAULTS[0]["repo_id"]
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
        "seed": SEED,
        "total_tasks": len(selected_tasks),
        "counted_tasks": sum(1 for t in selected_tasks if t.get("counted", True)),
        "tasks": selected_tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate locate_v2 manifest for C3 v2")
    parser.add_argument("--tasks-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=HERE / "c3" / "locate_v2_manifest.json")
    args = parser.parse_args()

    manifest = build_manifest(args.tasks_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote locate_v2 manifest with {manifest['counted_tasks']} counted tasks to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
