"""M8.10: does the GUI stay responsive? (offscreen, report only - nothing here asserts).

1. 50 tiny repositories, indexed once with ``index --all``;
2. start the main window (time to first paint), switch through all six tabs three times (click -> rendered);
3. index a 1,000-file synthetic repository through the GUI's child process while the event loop is watched.

Writes evals/out/m8/gui_perf.json:  tab_switch_ms, first_paint_ms, stalls during indexing (count / max ms).

    QT_QPA_PLATFORM=offscreen uv run python evals/gui_perf.py [--repos 50] [--files 1000]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from evals.make_synthetic_repo import generate_synthetic_repo  # noqa: E402
from token_context_mcp.gui.bridge import RepoManager  # noqa: E402
from token_context_mcp.gui.main_window import MainWindow  # noqa: E402
from token_context_mcp.gui.perf import EventLoopWatchdog  # noqa: E402
from token_context_mcp.gui.workers import pending_count, wait_idle  # noqa: E402

TAB_NAMES = ["dashboard", "repositories", "tasks", "cache", "agents", "settings"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", type=int, default=50)
    parser.add_argument("--files", type=int, default=1000)
    parser.add_argument("--out", default=str(ROOT / "evals" / "out" / "m8" / "gui_perf.json"))
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    report: dict = {"repos": args.repos, "synthetic_files": args.files, "platform": sys.platform}
    with tempfile.TemporaryDirectory(prefix="tcmcp_gui_perf_") as tmp:
        root = Path(tmp)
        config_path = root / "repos.toml"
        mgr = RepoManager(config_path)
        for i in range(args.repos):
            repo = root / "repos" / f"r{i:02d}"
            repo.mkdir(parents=True)
            (repo / "m.py").write_text(f"def f{i}():\n    return {i}\n\n\ndef g{i}():\n    return f{i}()\n", encoding="utf-8")
            mgr.add_repository(f"r{i:02d}", repo)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", "token_context_mcp", "index", "--all", "--config", str(config_path)],
            capture_output=True,
            text=True,
            timeout=900,
        )
        report["index_all_seconds"] = round(time.perf_counter() - t0, 1)
        if proc.returncode != 0:
            report["index_all_error"] = proc.stderr[-500:]

        # -- start-up ---------------------------------------------------------------------------------------------
        t0 = time.perf_counter()
        window = MainWindow(config_path=config_path)
        window.show()
        app.processEvents()
        report["first_paint_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        wait_idle(60_000)
        dog = EventLoopWatchdog(window, debug=False)
        dog.start()

        # -- tab switching ----------------------------------------------------------------------------------------
        switches: dict[str, list[float]] = {name: [] for name in TAB_NAMES}
        blocked: dict[str, list[float]] = {name: [] for name in TAB_NAMES}
        for _round in range(3):
            for idx, name in enumerate(TAB_NAMES):
                t0 = time.perf_counter()
                window._on_nav_clicked(idx)
                blocked[name].append(round((time.perf_counter() - t0) * 1000, 2))  # synchronous part of the click
                wait_idle(30_000)
                switches[name].append(round((time.perf_counter() - t0) * 1000, 1))  # click -> rendered
        report["tab_switch_ms"] = {n: {"median": statistics.median(v), "max": max(v)} for n, v in switches.items()}
        report["tab_click_blocking_ms"] = {n: max(v) for n, v in blocked.items()}
        report["tab_switch_all_under_100ms"] = all(max(v) < 100 for v in switches.values())
        report["stalls_during_tab_switching"] = {"count": dog.stall_count, "max_ms": max(dog.stalls_ms, default=0)}
        report["repositories_rows"] = window.tab_repos.model.rowCount()

        # -- indexing a synthetic repo through the GUI's child process ---------------------------------------------
        synth = root / "synthetic-1k"
        generate_synthetic_repo(synth, num_files=args.files)
        mgr.add_repository("synthetic-1k", synth)
        window.tab_repos.silent_errors = True
        dog.stalls_ms.clear()
        done: list = []
        window.tab_repos.indexing_finished.connect(done.append)
        t0 = time.perf_counter()
        window.tab_repos.start_indexing("synthetic-1k")
        deadline = t0 + 900
        while not done and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)
        wait_idle(30_000)
        report["synthetic_index_seconds"] = round(time.perf_counter() - t0, 1)
        report["synthetic_index_finished"] = bool(done)
        report["stalls_during_indexing"] = {
            "count": dog.stall_count,
            "max_ms": max(dog.stalls_ms, default=0),
            "all_ms": dog.stalls_ms[:50],
        }
        report["pending_tasks_at_end"] = pending_count()
        dog.stop()
        window.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("tab_click_blocking_ms",)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
