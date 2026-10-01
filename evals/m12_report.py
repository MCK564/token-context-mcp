"""M12.6 report: old (m12-base) vs new code over bench outputs; paired CI95 and the predeclared KPIs K1..K10.

Reads only JSON written by ``bench_retrieval.py``, ``edge_audit.py``, ``edge_gold_eval.py``, ``js_assigned_scan.py`` and
``bench_latency.py``; makes no measurement itself.  Usage::

    python evals/m12_report.py --base out/held_base --new out/held_new --repos starlette:python zod:typescript \
        express:javascript serilog:csharp --prefix "" --output evals/out/m12/heldout_report.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Any

ARMS = ("R0-grep", "R0-grep@R2", "R1", "R2")


def _rows(path: Path) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def bootstrap(values: list[float], samples: int = 2000, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    means = sorted(statistics.fmean(values[rng.randrange(len(values))] for _ in values) for _ in range(samples))
    return [round(means[int(0.025 * (samples - 1))], 4), round(means[int(0.975 * (samples - 1))], 4)]


def paired(a: dict[str, dict], b: dict[str, dict], field: str, only: set[str] | None = None) -> dict[str, Any]:
    ids = [i for i in a if i in b and (only is None or i in only) and a[i].get(field) is not None and b[i].get(field) is not None]
    diffs = [float(a[i][field]) - float(b[i][field]) for i in ids]
    if not diffs:
        return {"mean": None, "ci95": None, "pairs": 0}
    return {"mean": round(statistics.fmean(diffs), 4), "ci95": bootstrap(diffs), "pairs": len(diffs)}


def mean(rows: dict[str, dict], field: str, only: set[str] | None = None) -> float | None:
    vals = [float(r[field]) for i, r in rows.items() if (only is None or i in only) and r.get(field) is not None]
    return round(statistics.fmean(vals), 4) if vals else None


def load_repo(root: Path, name: str) -> dict[str, Any]:
    d = root / f"bench_{name}"
    out: dict[str, Any] = {"arms": {}, "summary": json.loads((d / f"bench_{name}_summary.json").read_text(encoding="utf-8"))}
    for arm in ARMS + ("R3",):
        p = d / f"bench_{name}_{arm}.jsonl"
        if p.exists():
            out["arms"][arm] = _rows(p)
    audit = json.loads((root / f"edge_audit_{name}.json").read_text(encoding="utf-8"))
    total = audit["total_edges"]
    amb = audit["status_counts"].get("ambiguous", 0)
    out["edges"] = {"total": total, "ambiguous": amb, "ambiguous_rate": round(amb / total, 4) if total else None, "symbols": audit["total_symbols"]}
    g = root / f"edge_gold_{name}.json"
    if g.exists():
        gold = json.loads(g.read_text(encoding="utf-8"))
        out["edge_gold"] = {"precision": gold["precision"], "recall": gold["recall"], "internal_sites": gold["internal_call_sites"]}
    return out


def build(base: Path, new: Path, repos: list[tuple[str, str]]) -> dict[str, Any]:
    report: dict[str, Any] = {"repos": {}}
    for name, lang in repos:
        b, n = load_repo(base, name), load_repo(new, name)
        item: dict[str, Any] = {"language": lang, "tasks": len(n["arms"]["R2"]), "corpus_files": n["summary"].get("corpus_files")}
        groups: dict[str, set[str]] = {}
        for tid, row in n["arms"]["R2"].items():
            groups.setdefault(row.get("group", "?"), set()).add(tid)
        for arm in ARMS:
            if arm not in n["arms"]:
                continue
            item[arm] = {
                "file_acc_at_5": {"base": mean(b["arms"][arm], "file_acc_at_5"), "new": mean(n["arms"][arm], "file_acc_at_5"),
                                  "diff": paired(n["arms"][arm], b["arms"][arm], "file_acc_at_5")},
                "sym_recall_at_10": {"base": mean(b["arms"][arm], "sym_recall_at_10"), "new": mean(n["arms"][arm], "sym_recall_at_10"),
                                     "diff": paired(n["arms"][arm], b["arms"][arm], "sym_recall_at_10")},
                "wire_tokens": {"base": mean(b["arms"][arm], "wire_tokens"), "new": mean(n["arms"][arm], "wire_tokens")},
            }
        item["R2_by_group_file_acc_at_5"] = {g: {"base": mean(b["arms"]["R2"], "file_acc_at_5", ids), "new": mean(n["arms"]["R2"], "file_acc_at_5", ids), "n": len(ids)} for g, ids in sorted(groups.items())}
        item["R2_minus_R0grep_new"] = paired(n["arms"]["R2"], n["arms"]["R0-grep"], "file_acc_at_5")
        if "R3" in n["arms"] and "R3" in b["arms"]:
            item["R3"] = {
                "ref_coverage": {"base": mean(b["arms"]["R3"], "ref_coverage"), "new": mean(n["arms"]["R3"], "ref_coverage"), "diff": paired(n["arms"]["R3"], b["arms"]["R3"], "ref_coverage")},
                "savings_vs_read": {"base": mean(b["arms"]["R3"], "savings_vs_read"), "new": mean(n["arms"]["R3"], "savings_vs_read")},
            }
        item["edges"] = {"base": b["edges"], "new": n["edges"],
                         "ambiguous_ratio_new_over_base": round(n["edges"]["ambiguous_rate"] / b["edges"]["ambiguous_rate"], 4) if b["edges"]["ambiguous_rate"] else None}
        if "edge_gold" in n:
            item["edge_gold"] = {"base": b.get("edge_gold"), "new": n["edge_gold"]}
        report["repos"][name] = item
    return report


def kpis(report: dict[str, Any], scan: dict[str, Any] | None, latency: dict[str, Any] | None, python_repos: list[str],
         js: str | None, cs: str | None, ts: str | None) -> list[dict[str, Any]]:
    R = report["repos"]
    rows: list[dict[str, Any]] = []

    def add(k: str, desc: str, value: Any, threshold: str, met: bool | None, note: str = "") -> None:
        rows.append({"id": k, "metric": desc, "value": value, "threshold": threshold, "met": met, "note": note})

    if scan is not None:
        add("K1", "JS assigned-method recall in the index (scan), 30-symbol precision sample", {"recall": scan["recall"], "recall_excluding_chained": scan["recall_excluding_chained"], "wrong_in_sample": scan["precision_sample"]["wrong"], "sample": scan["precision_sample"]["size"]},
            ">= 0.95 and 0 wrong", scan["recall"] is not None and scan["recall"] >= 0.95 and scan["precision_sample"]["wrong"] == 0,
            f"{scan['chained_symbols']} chained-assignment symbols are not indexed" if scan["chained_symbols"] else "")
    if js:
        d = R[js]["R2"]["file_acc_at_5"]["diff"]
        add("K2", f"JS ({js}) R2 File Acc@5 new - old", d, ">= 0", d["mean"] is not None and d["mean"] >= 0)
    if cs:
        d = R[cs]["R2_minus_R0grep_new"]
        add("K3", f"C# ({cs}) R2 - R0-grep File Acc@5", d, ">= -0.05", d["mean"] is not None and d["mean"] >= -0.05)
        d = R[cs]["R2"]["file_acc_at_5"]["diff"]
        add("K4", f"C# ({cs}) R2 File Acc@5 new - old", d, ">= +0.10", d["mean"] is not None and d["mean"] >= 0.10)
        gb = R[cs]["R2_by_group_file_acc_at_5"].get("b_hidden_dep", {})
        add("K5", f"C# ({cs}) b_hidden_dep R2 File Acc@5", gb, ">= 0.40", gb.get("new") is not None and gb["new"] >= 0.40)
    amb = {n: R[n]["edges"]["ambiguous_ratio_new_over_base"] for n in (js, ts, cs) if n}
    add("K6", "ambiguous_rate new/old per repo (JS/TS/C#)", amb, "<= 0.70 each", all(v is not None and v <= 0.70 for v in amb.values()))
    r3 = {n: R[n]["R3"]["ref_coverage"]["diff"] for n in (js, ts, cs) if n and "R3" in R[n]}
    add("K7", "R3 ref_coverage new - old (JS/TS/C#)", r3, ">= +0.10 each", all(v["mean"] is not None and v["mean"] >= 0.10 for v in r3.values()))
    prec = {n: (R[n].get("edge_gold") or {}).get("new", {}).get("precision", {}).get("precision") for n in (js, ts, cs) if n}
    add("K8", "edge-gold precision, conf >= 0.6, held-out", prec, ">= 0.95", all(v is not None and v >= 0.95 for v in prec.values()))
    ident = {}
    for n in python_repos:
        ident[n] = all(R[n][a][m]["diff"]["mean"] == 0.0 for a in ("R1", "R2") for m in ("file_acc_at_5", "sym_recall_at_10"))
    add("K9", "Python File Acc@5 and Symbol Recall@10 identical", ident, "identical", all(ident.values()) if ident else None)
    if latency is not None:
        add("K10", "p50 latency of search_source on a fixed query set (same queries on both code versions)", latency, "<= +20 %", latency.get("all_within_20pct"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--repos", nargs="+", required=True, help="name:language, e.g. express:javascript")
    ap.add_argument("--scan", type=Path, default=None)
    ap.add_argument("--latency", type=Path, default=None, help="JSON with the K10 comparison, optional")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    repos = [tuple(r.split(":", 1)) for r in args.repos]
    report = build(args.base, args.new, repos)  # type: ignore[arg-type]
    lang = {n: l for n, l in repos}
    pick = lambda l: next((n for n, ll in repos if ll == l), None)  # noqa: E731
    scan = json.loads(args.scan.read_text(encoding="utf-8")) if args.scan else None
    latency = json.loads(args.latency.read_text(encoding="utf-8")) if args.latency else None
    report["kpis"] = kpis(report, scan, latency, [n for n, l in repos if l == "python"], pick("javascript"), pick("csharp"), pick("typescript"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for k in report["kpis"]:
        print(k["id"], "MET" if k["met"] else ("n/a" if k["met"] is None else "NOT MET"), "|", k["metric"], "|", json.dumps(k["value"])[:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
