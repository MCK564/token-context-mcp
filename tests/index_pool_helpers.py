"""Worker functions for tests/test_index_incremental.py (module level so that spawned workers can import them)."""
from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import psutil

from token_context_mcp.index import runner


def die_in_child(task):
    """Kills the pool worker (a crash such as an OOM kill); the parent process behaves normally."""
    if multiprocessing.parent_process() is not None:
        os._exit(1)
    return runner._process_candidate(task)


def sleepy_worker(task):
    """Registers its pid and then blocks, so a test can cancel the run while workers are busy."""
    Path(os.environ["TOKEN_CONTEXT_TEST_PID_DIR"], f"{os.getpid()}.pid").write_text("x", encoding="utf-8")
    time.sleep(300)
    return None


def pid_is_running(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
