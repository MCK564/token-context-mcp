"""Automatic answer grading for C3 v2 agent evaluation (M12.5.5).

Extracts the last fenced ```json block from agent output, normalizes file paths,
and evaluates task_success against manifest gold criteria:
- group a/b: at least 1 gold file in top 3 files.
- group c: recall of gold files in top 5 files >= 0.5.
- parse error: task_success = False, error = "answer_parse_error".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from evals.c3_adapters import get_adapter
except (ImportError, ModuleNotFoundError):
    from c3_adapters import get_adapter  # type: ignore

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def normalize_path(path_str: str, workdir: Path | str | None = None) -> str:
    """Normalize file path for robust cross-platform comparison."""
    if not path_str:
        return ""
    p = str(path_str).strip().strip("\"'").replace("\\", "/")
    if workdir:
        w = str(workdir).strip().strip("\"'").replace("\\", "/")
        if not w.endswith("/"):
            w += "/"
        if p.lower().startswith(w.lower()):
            p = p[len(w):]
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    return p.lower()


def extract_fenced_json(text: str) -> dict[str, Any] | None:
    """Extract and parse the last fenced JSON block in the given text."""
    if not text:
        return None
    matches = _JSON_BLOCK_RE.findall(text)
    if not matches:
        # Fallback: check if entire string is valid JSON object
        trimmed = text.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                obj = json.loads(trimmed)
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                pass
        return None

    # Pick the last matched block
    last_block = matches[-1]
    try:
        obj = json.loads(last_block)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        # Try trimming trailing content
        trimmed = last_block.strip()
        try:
            obj = json.loads(trimmed)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


def grade_answer(
    task: dict[str, Any],
    answer_text: str,
    workdir: Path | str | None = None,
) -> dict[str, Any]:
    """Grade an agent's answer against a task in locate_v2 manifest."""
    group = task.get("group", "unknown")
    gold_files = [normalize_path(f, workdir) for f in task.get("gold_files", [])]
    gold_symbols = task.get("gold_symbols", [])

    if not task.get("counted", True):
        return {
            "task_id": task.get("id"),
            "task_success": True,
            "counted": False,
            "error": None,
            "files_found": [],
            "symbols_found": [],
            "top_files": [],
            "file_recall": 1.0,
            "sym_recall": 1.0,
        }

    parsed = extract_fenced_json(answer_text)
    if not parsed:
        return {
            "task_id": task.get("id"),
            "task_success": False,
            "counted": True,
            "error": "answer_parse_error",
            "files_found": [],
            "symbols_found": [],
            "top_files": [],
            "file_recall": 0.0,
            "sym_recall": 0.0,
        }

    raw_files = parsed.get("files", [])
    if isinstance(raw_files, list):
        pred_files = [normalize_path(str(f), workdir) for f in raw_files if f]
    else:
        pred_files = []

    raw_symbols = parsed.get("symbols", [])
    pred_symbols: list[dict[str, str]] = []
    if isinstance(raw_symbols, list):
        for s in raw_symbols:
            if isinstance(s, dict):
                pred_symbols.append({
                    "path": normalize_path(str(s.get("path", "")), workdir),
                    "name": str(s.get("name", "")).strip(),
                })

    # File evaluation
    gold_set = set(gold_files)
    top3 = pred_files[:3]
    top5 = pred_files[:5]
    top5_set = set(top5)

    hit_top3 = any(f in gold_set for f in top3)
    c_recall = len(gold_set & top5_set) / len(gold_set) if gold_set else 0.0

    if group in {"a_keyword", "b_hidden_dep"}:
        task_success = hit_top3
    elif group == "c_multi_file":
        task_success = (c_recall >= 0.5)
    else:
        task_success = hit_top3 or (c_recall >= 0.5)

    # Symbol evaluation (for reporting)
    sym_correct = 0
    for g_sym in gold_symbols:
        g_p = normalize_path(g_sym.get("path", ""), workdir)
        g_qname = str(g_sym.get("qualified_name", "")).strip().lower()
        g_name = str(g_sym.get("name", "")).strip().lower()
        for p_sym in pred_symbols[:10]:
            p_p = p_sym["path"]
            p_n = p_sym["name"].lower()
            if p_p == g_p and (p_n == g_name or p_n == g_qname or g_qname.endswith(f".{p_n}")):
                sym_correct += 1
                break
    sym_recall = (sym_correct / len(gold_symbols)) if gold_symbols else 0.0

    return {
        "task_id": task.get("id"),
        "task_success": task_success,
        "counted": True,
        "error": None,
        "group": group,
        "pred_files": pred_files,
        "gold_files": gold_files,
        "file_recall": round(c_recall, 4),
        "file_recall_top5": round(c_recall, 4),
        "hit_top3": hit_top3,
        "sym_recall": round(sym_recall, 4),
        "sym_recall_top10": round(sym_recall, 4),
    }


def grade_run_log(
    manifest: dict[str, Any],
    log_path: Path,
    agent: str = "claude",
    workdir: Path | str | None = None,
) -> dict[str, Any]:
    """Grade a single raw run log file using the appropriate adapter."""
    adapter = get_adapter(agent)
    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            adapter.feed(obj)

    final_rec = adapter.final()
    task_id = log_path.stem.split("-seed")[0].split("-", 1)[-1] if "-seed" in log_path.stem else log_path.stem

    task = next((t for t in manifest.get("tasks", []) if t["id"] == task_id), None)
    if not task:
        # Try matching by suffix
        task = next((t for t in manifest.get("tasks", []) if task_id.endswith(t["id"])), None)

    if not task:
        return {
            "log": str(log_path),
            "task_id": task_id,
            "task_success": False,
            "error": "task_not_found_in_manifest",
        }

    graded = grade_answer(task, final_rec.final_answer, workdir=workdir)
    return {
        "log": str(log_path),
        **graded,
        "mcp_calls": final_rec.mcp_call_count,
        "native_reads": final_rec.native_read_count,
        "usage": {
            "input_total": final_rec.usage.input_total if final_rec.usage else 0,
            "cached": final_rec.usage.cached if final_rec.usage else 0,
            "output": final_rec.usage.output if final_rec.usage else 0,
        } if final_rec.usage else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade C3 v2 agent answers")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to locate_v2_manifest.json")
    parser.add_argument("--runs-dir", type=Path, required=True, help="Directory containing raw JSONL runs")
    parser.add_argument("--agent", choices=("claude", "gemini", "codex"), default="claude")
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    log_files = sorted(args.runs_dir.glob("*.jsonl"))

    results = []
    successes = 0
    total_counted = 0

    for lf in log_files:
        res = grade_run_log(manifest, lf, agent=args.agent, workdir=args.workdir)
        results.append(res)
        if res.get("counted", True):
            total_counted += 1
            if res.get("task_success"):
                successes += 1

    summary = {
        "agent": args.agent,
        "manifest": str(args.manifest),
        "total_runs": len(results),
        "counted_runs": total_counted,
        "successes": successes,
        "success_rate": round(successes / total_counted, 4) if total_counted else 0.0,
        "runs": results,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Saved grade report to {args.output}")

    print(f"Graded {total_counted} runs: {successes} successes ({summary['success_rate']*100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
