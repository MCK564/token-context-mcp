"""Index benchmark (M7.0): full / no-op / one-file-changed, RSS of the whole process tree, median of N runs.

Each case runs ``evals/index_child.py`` in a child process; the parent samples the RSS of the child and all its
descendants (pool workers included) every 100 ms with psutil.  ``--tracemalloc`` adds one extra, untimed run per
case that reports the main process' tracemalloc peak.  The repository is copied to a scratch directory so the
"one file changed" case never touches the source tree.

    uv run python evals/index_bench.py --root <dir> --repo-id tc-pinned --runs 3 --output evals/out/m7/baseline_tc_pinned.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent


def _run_child(cmd: list[str], env: dict[str, str]) -> tuple[dict, float]:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    peak = 0
    done = threading.Event()

    def sample() -> None:
        nonlocal peak
        try:
            root = psutil.Process(proc.pid)
        except psutil.Error:
            return
        while not done.is_set():
            total = 0
            try:
                procs = [root, *root.children(recursive=True)]
            except psutil.Error:
                procs = [root]
            for p in procs:
                try:
                    total += p.memory_info().rss
                except psutil.Error:
                    pass
            peak = max(peak, total)
            time.sleep(0.1)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    out, err = proc.communicate()
    done.set()
    thread.join(timeout=1)
    if proc.returncode != 0:
        raise RuntimeError(f"child failed ({proc.returncode}): {err[-800:]}")
    line = next(l for l in out.splitlines() if l.startswith("RESULT "))
    return json.loads(line[len("RESULT "):]), peak / 1e6


def _write_config(path: Path, repo_id: str, root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[server]\nnetwork_policy = \"declared-deny-not-enforced\"\n\n"
        f"[repos.{repo_id}]\nroot = \"{root.as_posix()}\"\nallow_symlinks = false\nmax_file_bytes = 2000000\nmax_files = 25000\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="repository directory to copy and index")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--work-dir", type=Path, default=None, help="scratch directory (default: a temp dir)")
    parser.add_argument("--change-file", default=None, help="file (relative) to modify for the one-file case")
    parser.add_argument("--tracemalloc", action="store_true")
    parser.add_argument("--cases", default="full,noop,one")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    work = args.work_dir or Path(tempfile.mkdtemp(prefix="index-bench-"))
    src = work / "src"
    if src.exists():
        shutil.rmtree(src)
    shutil.copytree(args.root, src, ignore=shutil.ignore_patterns(".git"))
    change_rel = args.change_file
    if change_rel is None:
        candidates = sorted((p for p in src.rglob("*.py")), key=lambda p: (p.stat().st_size, p.as_posix()))
        change_rel = candidates[len(candidates) // 2].relative_to(src).as_posix()
    change_path = src / change_rel
    original = change_path.read_bytes()

    env = dict(os.environ)
    child = [sys.executable, str(HERE / "index_child.py"), "--repo-id", args.repo_id]
    if args.workers is not None:
        child += ["--workers", str(args.workers)]
    cases = args.cases.split(",")
    results: dict[str, list[dict]] = {c: [] for c in cases}

    for run in range(args.runs):
        cfg = work / f"run{run}" / "repos.toml"
        _write_config(cfg, args.repo_id, src)
        cmd = [*child, "--config", str(cfg)]
        change_path.write_bytes(original)
        os.utime(change_path, None)
        if "full" in cases or "noop" in cases or "one" in cases:
            res, rss = _run_child(cmd, env)  # always needed as the base of noop / one
            if "full" in cases:
                results["full"].append({**res, "rss_peak_mb": round(rss, 1)})
        if "noop" in cases:
            res, rss = _run_child(cmd, env)
            results["noop"].append({**res, "rss_peak_mb": round(rss, 1)})
        if "one" in cases:
            time.sleep(0.05)
            change_path.write_bytes(original + b"\n# bench edit\n")
            res, rss = _run_child(cmd, env)
            results["one"].append({**res, "rss_peak_mb": round(rss, 1)})
            change_path.write_bytes(original)

    tm_peaks: dict[str, float] = {}
    if args.tracemalloc:
        cfg = work / "tm" / "repos.toml"
        _write_config(cfg, args.repo_id, src)
        res, _ = _run_child([*child, "--config", str(cfg), "--tracemalloc"], env)
        tm_peaks["full"] = res.get("tracemalloc_peak_mb")
        res, _ = _run_child([*child, "--config", str(cfg), "--tracemalloc"], env)
        tm_peaks["noop"] = res.get("tracemalloc_peak_mb")

    summary: dict[str, dict] = {}
    for case, runs in results.items():
        if not runs:
            continue
        walls = [r["wall_s"] for r in runs]
        stage_names = runs[0]["manifest"]["timings_ms"].keys()
        summary[case] = {
            "median_wall_s": round(statistics.median(walls), 3),
            "wall_s_runs": walls,
            "median_rss_peak_mb": round(statistics.median(r["rss_peak_mb"] for r in runs), 1),
            "median_timings_ms": {
                s: round(statistics.median(r["manifest"]["timings_ms"][s] for r in runs), 1) for s in stage_names
            },
            "parse_source_calls": [r["manifest"]["parse_source_calls"] for r in runs],
            "files_reparsed": [r["manifest"]["files_reparsed"] for r in runs],
        }
    report = {
        "repo_id": args.repo_id,
        "files_indexed": next(iter(results.values()))[0]["manifest"]["files_indexed"],
        "symbols_indexed": next(iter(results.values()))[0]["manifest"]["symbols_indexed"],
        "changed_file": change_rel,
        "runs": args.runs,
        "environment": {"platform": platform.platform(), "python": sys.version.split()[0], "cpu_count": os.cpu_count()},
        "tracemalloc_peak_mb": tm_peaks,
        "summary": summary,
        "raw": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"repo": args.repo_id, "changed": change_rel, "summary": summary, "tracemalloc_peak_mb": tm_peaks}, indent=1))
    shutil.rmtree(work / "run0", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
