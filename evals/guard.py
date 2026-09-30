"""Rule 17 Held-out harness guard.

Guarantees that held-out evaluations cannot be run prematurely or against
unfrozen code.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def check_heldout_guard(
    role: str,
    allow_baseline_code: Path | str | None = None,
    repo_root: Path | None = None,
) -> None:
    """Enforce Rule 17 guard conditions.

    If role == 'heldout':
    1. If allow_baseline_code is provided, the run is explicitly authorized
       to use archived/baseline code.
    2. Otherwise:
       - git tag 'm12-freeze' MUST exist.
       - git diff between 'm12-freeze' and HEAD across protected paths
         ('src', 'evals/bench_retrieval.py', 'evals/edge_gold_eval.py') MUST be completely empty.
    """
    if role != "heldout":
        return

    if allow_baseline_code is not None:
        p = Path(allow_baseline_code)
        if not p.exists():
            raise FileNotFoundError(f"--allow-baseline-code path does not exist: {allow_baseline_code}")
        return

    root = Path(repo_root) if repo_root else REPO_ROOT

    # 1. Verify tag m12-freeze exists
    try:
        tag_check = subprocess.run(
            ["git", "rev-parse", "--verify", "refs/tags/m12-freeze"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Failed to check git tag: {exc}") from exc

    if tag_check.returncode != 0:
        raise RuntimeError(
            "Rule 17 violation: Cannot run benchmark with --role heldout because git tag 'm12-freeze' does not exist. "
            "Held-out evaluations are strictly forbidden until code freeze."
        )

    # 2. Verify git diff against m12-freeze on protected paths is empty
    protected_paths = ["src", "evals/bench_retrieval.py", "evals/edge_gold_eval.py"]
    try:
        diff_check = subprocess.run(
            ["git", "diff", "m12-freeze", "--", *protected_paths],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Failed to check git diff: {exc}") from exc

    if diff_check.returncode != 0 or diff_check.stdout.strip():
        snippet = diff_check.stdout.strip()[:300]
        raise RuntimeError(
            f"Rule 17 violation: Cannot run benchmark with --role heldout because git diff against 'm12-freeze' is not empty "
            f"for protected paths: {', '.join(protected_paths)}.\nDiff:\n{snippet}"
        )
