from __future__ import annotations

import json
from pathlib import Path

from token_context_mcp.release import write_release_materials
from token_context_mcp.telemetry.benchmark import load_runs, summarize


def test_benchmark_summary_uses_paired_reduction(tmp_path: Path) -> None:
    events = tmp_path / "runs.jsonl"
    rows = [
        {"arm": "B0", "task_id": "t1", "seed": 1, "total_tokens": 100, "input_tokens": 80, "output_tokens": 20, "latency_seconds": 1.0, "task_success": True},
        {"arm": "B1", "task_id": "t1", "seed": 1, "total_tokens": 60, "input_tokens": 45, "output_tokens": 15, "latency_seconds": 0.8, "task_success": True},
    ]
    events.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    report = summarize(load_runs(events), bootstrap_samples=20)
    assert report["arms"]["B1"]["median_paired_token_reduction"] == 0.4
    assert report["arms"]["B1"]["quality_noninferiority_delta"] == 0.0


def test_release_materials_are_explicitly_local_starter_artifacts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    output = tmp_path / "materials"
    paths = write_release_materials(project, output)
    assert json.loads(paths["sbom"].read_text(encoding="utf-8"))["bomFormat"] == "CycloneDX"
    provenance = json.loads(paths["provenance"].read_text(encoding="utf-8"))
    assert provenance["predicate"]["runDetails"]["builder"]["id"] == "local-unattested"

