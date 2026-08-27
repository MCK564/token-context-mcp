from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


REQUIRED_FIELDS = {"arm", "task_id", "seed", "total_tokens", "input_tokens", "output_tokens", "latency_seconds", "task_success"}


def load_runs(path: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            raise ValueError(f"line {line_number} missing fields: {sorted(missing)}")
        runs.append(item)
    return runs


def summarize(runs: Iterable[dict[str, Any]], *, baseline: str = "B0", bootstrap_samples: int = 2000) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[str(run["arm"])].append(run)
    if baseline not in grouped:
        raise ValueError(f"baseline arm missing: {baseline}")
    base_by_key = {(str(item["task_id"]), str(item["seed"])): item for item in grouped[baseline]}
    report: dict[str, Any] = {"baseline": baseline, "arms": {}}
    for arm, items in sorted(grouped.items()):
        paired = []
        for item in items:
            key = (str(item["task_id"]), str(item["seed"]))
            baseline_item = base_by_key.get(key)
            if baseline_item:
                paired.append(
                    (float(baseline_item["total_tokens"]), float(item["total_tokens"]), bool(item["task_success"]), bool(baseline_item["task_success"]))
                )
        reductions = [(base - variant) / base for base, variant, _, _ in paired if base > 0]
        report["arms"][arm] = {
            "run_count": len(items),
            "paired_count": len(paired),
            "median_total_tokens": statistics.median(float(item["total_tokens"]) for item in items),
            "median_input_tokens": statistics.median(float(item["input_tokens"]) for item in items),
            "median_output_tokens": statistics.median(float(item["output_tokens"]) for item in items),
            "median_latency_seconds": statistics.median(float(item["latency_seconds"]) for item in items),
            "success_rate": sum(bool(item["task_success"]) for item in items) / len(items),
            "median_paired_token_reduction": statistics.median(reductions) if reductions else None,
            "paired_reduction_ci95": _bootstrap_ci(reductions, bootstrap_samples) if reductions else None,
            "quality_noninferiority_delta": _success_delta(paired),
        }
    return report


def _bootstrap_ci(values: list[float], samples: int) -> list[float]:
    rng = random.Random(0)
    means = []
    for _ in range(samples):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(statistics.median(sample))
    means.sort()
    return [means[int(0.025 * (len(means) - 1))], means[int(0.975 * (len(means) - 1))]]


def _success_delta(pairs: list[tuple[float, float, bool, bool]]) -> float | None:
    if not pairs:
        return None
    return sum(int(variant) - int(base) for _, _, variant, base in pairs) / len(pairs)

