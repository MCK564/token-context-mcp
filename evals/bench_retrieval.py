"""Public retrieval benchmark (M10.5): token-context vs a grep baseline on a pinned open-source repository.

Deterministic (no model, no network).  Arms, all on the same machine, index and queries:

* ``R0-grep``     - Python re-implementation of ``rg -n -C 2`` over the indexed files (identifier terms, idf ranking).
* ``R0-grep@R2``  - the output of R0-grep cut, by whole lines in rank order, to the wire tokens of R2 on the same task.
* ``R0-read``     - the first five files of R0-grep read whole (upper bound of what a grep-then-read agent spends).
* ``R1``          - ``search_source(expand="none")``, budget 2048.
* ``R2``          - ``search_source(profile="locate")`` (graph expansion, profile budget).
* ``R3``          - ``inspect_symbol(view="full", budget_tokens=4096)`` on the packet tasks, against reading the files (READ).

R0 is a *simulated* baseline, not a real agent: its symbol is taken from the index (an advantage for R0).
The task file must be ``reviewed: true``; otherwise the run refuses (exit code 3) so that nobody tunes on
unreviewed answers.  Nothing is tuned on these tasks: they are all test tasks.

    uv run python evals/bench_retrieval.py --tasks tmp/review/bench_rich.json --config tmp/dev/repos.toml --name rich
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import loc_eval  # noqa: E402
from guard import FREEZE_TAG, check_heldout_guard  # noqa: E402
from token_context_mcp import __version__  # noqa: E402
from token_context_mcp.retrieve.code_tokens import split_identifier  # noqa: E402

BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 0
TOP_FILES = 10
READ_FILES = 5
CONTEXT_LINES = 2
MAX_LINES_PER_FILE = 200
MIN_TERM_LENGTH = 3
LATENCY_REPS = 5  # first one discarded, like loc_eval
R3_BUDGET = 4096
ARMS = ("R0-grep", "R0-grep@R2", "R0-read", "R1", "R2")

METRICS = ("file_acc_at_5", "file_mrr", "sym_recall_at_10", "sym_mrr", "wire_tokens", "latency_ms")


def tokens_of(text: str) -> int:
    """utf8-bytes-div-4-v1, like every other estimate in the project."""
    return max(1, math.ceil(len(text.encode("utf-8")) / 4)) if text else 0


# ---------------------------------------------------------------------------------------------------------------
# R0: grep baseline
# ---------------------------------------------------------------------------------------------------------------
def query_terms(query: str) -> list[str]:
    """Identifier parts of the query words, lower-cased, at least three characters, order of first appearance."""
    terms: list[str] = []
    for word in re.findall(r"[A-Za-z0-9_]+", query):
        for part in split_identifier(word):
            if len(part) >= MIN_TERM_LENGTH and part not in terms:
                terms.append(part)
    return terms


def term_regex(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.IGNORECASE)


class Corpus:
    """The indexed files of one repository (parse_status starting with "parsed") and their symbol spans."""

    def __init__(self, files: dict[str, str], symbols: list[tuple[str, str, int, int]]) -> None:
        self.files = dict(sorted(files.items()))
        self.lines = {path: text.split("\n") for path, text in self.files.items()}
        self.spans: dict[str, list[tuple[int, int, str]]] = {}
        for path, qualified_name, start, end in symbols:
            self.spans.setdefault(path, []).append((start, end, qualified_name))
        self._term_files: dict[str, set[str]] = {}

    def files_matching(self, term: str) -> set[str]:
        if term not in self._term_files:
            pattern = term_regex(term)
            self._term_files[term] = {path for path, text in self.files.items() if pattern.search(text)}
        return self._term_files[term]

    def innermost_symbol(self, path: str, line: int) -> str | None:
        best: tuple[int, int, str] | None = None
        for start, end, name in self.spans.get(path, []):
            if start <= line <= end and (best is None or (end - start) < (best[1] - best[0])):
                best = (start, end, name)
        return best[2] if best else None


def grep_rank(corpus: Corpus, query: str) -> dict[str, Any]:
    """Rank files by sum of idf over matched terms; pick each file's best line (most distinct terms, then first)."""
    terms = query_terms(query)
    total = max(1, len(corpus.files))
    idf = {term: math.log(1 + total / max(1, len(corpus.files_matching(term)))) for term in terms}
    patterns = {term: term_regex(term) for term in terms}
    scored: list[tuple[float, str, list[tuple[int, set[str]]]]] = []
    for path in sorted({p for term in terms for p in corpus.files_matching(term)}):
        hits: list[tuple[int, set[str]]] = []
        matched: set[str] = set()
        for number, text in enumerate(corpus.lines[path], start=1):
            found = {term for term, pattern in patterns.items() if pattern.search(text)}
            if found:
                hits.append((number, found))
                matched |= found
        scored.append((sum(idf[t] for t in matched), path, hits))
    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked = []
    for score, path, hits in scored[:TOP_FILES]:
        best_line = max(hits, key=lambda h: (len(h[1]), -h[0]))[0]
        ranked.append({"path": path, "score": round(score, 6), "hit_lines": [h[0] for h in hits], "best_line": best_line,
                       "symbol": corpus.innermost_symbol(path, best_line)})
    return {"terms": terms, "ranked": ranked}


def grep_output_lines(corpus: Corpus, ranked: list[dict[str, Any]]) -> list[tuple[int, str, int]]:
    """``rg -n -C 2`` style output for the ranked files: (file_rank, "path:line:text", line_number)."""
    out: list[tuple[int, str, int]] = []
    for rank, item in enumerate(ranked):
        lines = corpus.lines[item["path"]]
        keep: set[int] = set()
        for number in item["hit_lines"]:
            keep.update(range(max(1, number - CONTEXT_LINES), min(len(lines), number + CONTEXT_LINES) + 1))
        for count, number in enumerate(sorted(keep)):
            if count >= MAX_LINES_PER_FILE:
                break
            out.append((rank, f'{item["path"]}:{number}:{lines[number - 1]}', number))
    return out


def as_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    """A search_source-shaped response, so that the loc_eval metric code scores every arm identically."""
    matches = []
    for item in items:
        match: dict[str, Any] = {"path": item["path"]}
        if item.get("symbol"):
            match["qualified_name"] = item["symbol"]
        matches.append(match)
    return {"data": {"matches": matches, "neighbors": []}}


def run_r0(corpus: Corpus, query: str) -> dict[str, Any]:
    ranking = grep_rank(corpus, query)
    lines = grep_output_lines(corpus, ranking["ranked"])
    text = "\n".join(line for _, line, _ in lines)
    return {"ranking": ranking, "lines": lines, "text": text, "tokens": tokens_of(text)}


def cut_to_tokens(corpus: Corpus, r0: dict[str, Any], budget_tokens: int) -> dict[str, Any]:
    """Keep whole output lines, in rank order, while the text stays within ``budget_tokens``; score what remains."""
    kept: list[tuple[int, str, int]] = []
    used_bytes = 0
    for rank, line, number in r0["lines"]:
        extra = len(line.encode("utf-8")) + (1 if kept else 0)
        if math.ceil((used_bytes + extra) / 4) > budget_tokens:
            break
        kept.append((rank, line, number))
        used_bytes += extra
    ranked = r0["ranking"]["ranked"]
    present = {rank for rank, _, _ in kept}
    kept_numbers = {(rank, number) for rank, _, number in kept}
    items = []
    for rank, item in enumerate(ranked):
        if rank in present:
            shown_symbol = item["symbol"] if (rank, item["best_line"]) in kept_numbers else None
            items.append({"path": item["path"], "symbol": shown_symbol})
    text = "\n".join(line for _, line, _ in kept)
    return {"items": items, "tokens": tokens_of(text), "lines": len(kept)}


def read_top(corpus: Corpus, r0: dict[str, Any]) -> dict[str, Any]:
    ranked = r0["ranking"]["ranked"][:READ_FILES]
    tokens = sum(tokens_of(corpus.files[item["path"]]) for item in ranked)
    return {"items": [{"path": i["path"], "symbol": i["symbol"]} for i in ranked], "tokens": tokens}


# ---------------------------------------------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------------------------------------------
def bootstrap_ci(values: list[float], samples: int = BOOTSTRAP_SAMPLES) -> list[float] | None:
    """95% CI of the mean, fixed seed.  (telemetry.benchmark._bootstrap_ci resamples the median, which is degenerate
    for 0/1 metrics; the resampling scheme and the seed are the same.)"""
    if not values:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(statistics.fmean(values[rng.randrange(len(values))] for _ in values) for _ in range(samples))
    return [round(means[int(0.025 * (len(means) - 1))], 4), round(means[int(0.975 * (len(means) - 1))], 4)]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"tasks": len(rows)}
    for metric in METRICS:
        values = [float(r[metric]) for r in rows if r.get(metric) is not None]
        out[metric] = {"mean": round(statistics.fmean(values), 4) if values else None, "ci95": bootstrap_ci(values)}
    latencies = [x for r in rows for x in r.get("latencies_ms", [])]
    out["latency_p50_ms"] = round(loc_eval.percentile(latencies, 50), 2) if latencies else None
    out["latency_p95_ms"] = round(loc_eval.percentile(latencies, 95), 2) if latencies else None
    return out


def paired_diff(a: list[dict[str, Any]], b: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    """mean(a - b) over tasks with a CI95 from paired resampling."""
    b_by_id = {r["id"]: r for r in b}
    diffs = [float(r[metric]) - float(b_by_id[r["id"]][metric]) for r in a if r["id"] in b_by_id]
    return {"mean": round(statistics.fmean(diffs), 4) if diffs else None, "ci95": bootstrap_ci(diffs), "pairs": len(diffs)}


def kpis(per_arm: dict[str, list[dict[str, Any]]], r3: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    same_cost = paired_diff(per_arm["R2"], per_arm["R0-grep@R2"], "file_acc_at_5")
    result["same_cost_file_acc_at_5_R2_minus_R0grepR2"] = {
        **same_cost, "threshold": 0.10,
        "met": bool(same_cost["mean"] is not None and same_cost["mean"] >= 0.10 and same_cost["ci95"] and same_cost["ci95"][0] > 0),
    }
    vs_grep = paired_diff(per_arm["R2"], per_arm["R0-grep"], "file_acc_at_5")
    result["file_acc_at_5_R2_minus_R0grep"] = {**vs_grep, "threshold": -0.05, "met": bool(vs_grep["mean"] is not None and vs_grep["mean"] >= -0.05)}
    r2_tokens = statistics.fmean(r["wire_tokens"] for r in per_arm["R2"])
    r0_tokens = statistics.fmean(r["wire_tokens"] for r in per_arm["R0-grep"])
    result["token_ratio_R2_over_R0grep"] = {"value": round(r2_tokens / r0_tokens, 4) if r0_tokens else None, "note": "report only"}
    result["R2_vs_R1"] = {
        "file_acc_at_5": paired_diff(per_arm["R2"], per_arm["R1"], "file_acc_at_5"),
        "sym_recall_at_10": paired_diff(per_arm["R2"], per_arm["R1"], "sym_recall_at_10"),
        "note": "report only, no threshold",
    }
    if r3 is not None:
        result["R3"] = {
            "sig_coverage": {"value": r3["sig_coverage"]["mean"], "threshold": 0.60, "met": (r3["sig_coverage"]["mean"] or 0) >= 0.60},
            "ref_coverage": {"value": r3["ref_coverage"]["mean"], "threshold": 0.80, "met": (r3["ref_coverage"]["mean"] or 0) >= 0.80},
            "savings_vs_read": {"value": r3["savings_vs_read"]["mean"], "threshold": 0.70, "met": (r3["savings_vs_read"]["mean"] or 0) >= 0.70},
        }
    return result


# ---------------------------------------------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------------------------------------------
def _timed(fn: Any) -> tuple[Any, list[float]]:
    latencies: list[float] = []
    result = None
    for rep in range(LATENCY_REPS):
        started = time.perf_counter()
        result = fn()
        if rep > 0:
            latencies.append((time.perf_counter() - started) * 1000.0)
    return result, latencies


def _score(task: dict[str, Any], response: dict[str, Any], symbol_id_map: dict[str, tuple[str, str]], latencies: list[float], tokens: int) -> dict[str, Any]:
    row = loc_eval.evaluate_single_task(task, response, symbol_id_map, latencies)
    row["wire_tokens"] = tokens
    return row


def run_locate_arms(service: Any, repo_id: str, tasks: list[dict[str, Any]], corpus: Corpus, symbol_id_map: dict[str, tuple[str, str]]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    for task in tasks:
        query = task["query"]
        r1, r1_lat = _timed(lambda: service.search_source(repo_id, query=query, limit=20, max_tokens=2048, expand="none"))
        r2, r2_lat = _timed(lambda: service.search_source(repo_id, query=query, limit=20, profile="locate"))
        r2_tokens = loc_eval.estimate_wire_tokens(r2)
        r0, r0_lat = _timed(lambda: run_r0(corpus, query))
        cut = cut_to_tokens(corpus, r0, r2_tokens)
        read = read_top(corpus, r0)
        r0_items = [{"path": i["path"], "symbol": i["symbol"]} for i in r0["ranking"]["ranked"]]
        rows["R1"].append(_score(task, r1, symbol_id_map, r1_lat, loc_eval.estimate_wire_tokens(r1)))
        rows["R2"].append(_score(task, r2, symbol_id_map, r2_lat, r2_tokens))
        rows["R0-grep"].append(_score(task, as_response(r0_items), symbol_id_map, r0_lat, r0["tokens"]))
        rows["R0-grep@R2"].append(_score(task, as_response(cut["items"]), symbol_id_map, r0_lat, cut["tokens"]))
        rows["R0-read"].append(_score(task, as_response(read["items"]), symbol_id_map, r0_lat, read["tokens"]))
    return rows


def run_r3(args: argparse.Namespace, spec: dict[str, Any], repo_id: str) -> dict[str, Any] | None:
    """R3 through the packet evaluation (arms P1 and READ), on the packet tasks of the benchmark file."""
    packet_tasks = spec.get("packet_tasks") or []
    if not packet_tasks:
        return None
    import packet_eval

    with tempfile.TemporaryDirectory(prefix="bench_packet_") as tmp:
        tasks_file = Path(tmp) / "packet_tasks.json"
        tasks_file.write_text(json.dumps({"repo_id": repo_id, "tasks": packet_tasks}), encoding="utf-8")
        results: dict[str, Any] = {}
        for arm in ("P1", "READ"):
            ns = argparse.Namespace(
                arm=arm, tasks=tasks_file, split="all", budget=R3_BUDGET, config=args.config, repo_id=repo_id, p0_src=None,
                shares=None, callers_k=None, raw=str(Path(tmp) / f"raw_{arm}.jsonl"), reuse_raw=False,
            )
            results[arm] = packet_eval.evaluate(ns, arm)
    p1 = results["P1"]
    rows = p1["tasks"]
    summary: dict[str, Any] = {"budget": R3_BUDGET, "tasks": len(rows), "errors": p1["overall"]["errors"]}
    for metric in ("sig_coverage", "ref_coverage", "body_coverage", "reach_ceiling", "wire_tokens", "read_tokens", "savings_vs_read"):
        values = [float(t[metric]) for t in rows if t.get(metric) is not None]
        summary[metric] = {"mean": round(statistics.fmean(values), 4) if values else None, "ci95": bootstrap_ci(values)}
    summary["rows"] = rows
    return summary


def load_corpus(service: Any, repo_id: str) -> tuple[Corpus, dict[str, tuple[str, str]], dict[str, Any]]:
    repository, store, meta = service._repository_store(repo_id)
    files: dict[str, str] = {}
    for record in store.files():
        if record.parse_status.startswith("parsed"):
            files[record.path] = (Path(repository.root) / record.path).read_text(encoding="utf-8", errors="replace")
    symbols = store.symbols()
    corpus = Corpus(files, [(s.path, s.qualified_name or s.name, s.start_line, s.end_line) for s in symbols])
    return corpus, {s.symbol_id: (s.path, s.qualified_name or s.name) for s in symbols}, meta


def git_value(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, cwd=HERE.parent).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def run(args: argparse.Namespace) -> int:
    role = getattr(args, "role", "dev")
    allow_baseline_code = getattr(args, "allow_baseline_code", None)
    check_heldout_guard(role, allow_baseline_code=allow_baseline_code)

    spec = json.loads(args.tasks.read_text(encoding="utf-8"))
    if spec.get("reviewed") is not True:
        print("bench_retrieval: the task set is not reviewed (reviewed != true); refusing to run.", file=sys.stderr)
        return 3
    from token_context_mcp.config import load_config
    from token_context_mcp.retrieve.service import RetrievalService

    config_path = args.config.resolve()
    service = RetrievalService(load_config(config_path), config_path)
    repo_id = args.repo_id or spec["repo_id"]
    corpus, symbol_id_map, meta = load_corpus(service, repo_id)
    tasks = spec["tasks"]
    rows = run_locate_arms(service, repo_id, tasks, corpus, symbol_id_map)
    r3 = run_r3(args, spec, repo_id)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for arm, arm_rows in rows.items():
        slim = [{k: v for k, v in row.items() if k != "latencies_ms"} | {"latencies_ms": row["latencies_ms"]} for row in arm_rows]
        (out_dir / f"bench_{args.name}_{arm}.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in slim) + "\n", encoding="utf-8")
    if r3 is not None:
        (out_dir / f"bench_{args.name}_R3.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in r3["rows"]) + "\n", encoding="utf-8")

    groups = sorted({t.get("group", "") for t in tasks})
    summary = {
        "benchmark": f"bench_{args.name}",
        "repo": {k: spec.get(k) for k in ("repo_id", "repo_url", "tag", "commit_sha", "license")},
        "tasks_file": str(args.tasks),
        "tasks_file_sha256": hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
        "reviewed": True,
        "review_note": spec.get("review_note"),
        "role": role,
        "token_context_version": __version__,
        "git_head": git_value("rev-parse", "HEAD"),
        "freeze_tag": git_value("rev-parse", FREEZE_TAG) or git_value("rev-parse", "m12-freeze") or git_value("rev-parse", "m10-freeze"),
        "index_run_id": meta.get("index_run_id"),
        "index_schema_version": meta.get("index_schema_version"),
        "corpus_files": len(corpus.files),
        "estimator": "utf8-bytes-div-4-v1",
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED, "statistic": "mean"},
        "arms": {arm: summarize(arm_rows) for arm, arm_rows in rows.items()},
        "by_group": {g: {arm: summarize([r for r in arm_rows if r.get("group") == g]) for arm, arm_rows in rows.items()} for g in groups},
        "r3": {k: v for k, v in (r3 or {}).items() if k != "rows"} or None,
        "kpis": kpis(rows, r3),
        "limits": "R0 is a simulated baseline (identifier terms, idf ranking, symbol taken from the index), not a real agent.",
    }
    out_path = out_dir / f"bench_{args.name}_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"arms": {a: {m: s[m]["mean"] for m in ("file_acc_at_5", "sym_recall_at_10", "wire_tokens")} for a, s in summary["arms"].items()}, "kpis": summary["kpis"]}, indent=2))
    print(f"-> {out_path}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Public retrieval benchmark (M10.5)")
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repo-id", default=None)
    parser.add_argument("--name", required=True, help="short name used in output files, e.g. rich")
    parser.add_argument("--out-dir", type=Path, default=HERE / "out" / "m10")
    parser.add_argument("--role", default="dev", choices=["dev", "heldout"], help="Run role (dev or heldout)")
    parser.add_argument("--allow-baseline-code", type=Path, default=None, help="Path to baseline code to allow running before freeze")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
