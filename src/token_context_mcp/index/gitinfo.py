"""``git rev-parse HEAD`` of a repository root, with a hard timeout and no side effects (M7.8)."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_CACHE: dict[str, tuple[float, str | None]] = {}


def git_head(root: Path, *, timeout: float = 2.0) -> str | None:
    """Full commit hash of ``HEAD`` or ``None`` (not a git repository, git missing, unborn branch, timeout)."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip().lower()
    return value if _SHA.fullmatch(value) else None


def cached_git_head(root: Path, *, ttl: float = 5.0) -> str | None:
    """``git_head`` remembered for ``ttl`` seconds (status calls must not spawn git every time)."""
    key = str(root)
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    value = git_head(root)
    _CACHE[key] = (now, value)
    return value
