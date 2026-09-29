"""Snapshot guard: `minimal` and `normal` inspect_symbol output must not change with M6.2 (packet only touches `full`).

Snapshots were captured from the code at commit ee5881e, BEFORE any packet code existed.
Regenerate only deliberately with TC_UPDATE_SNAPSHOTS=1 (and only if the contract change is approved).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from packet_repo import REPO_ID, build_packet_repo
from token_context_mcp.config import load_config
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine

SNAP_DIR = Path(__file__).parent / "fixtures" / "inspect_symbol_snapshots"
QUERIES = ["Service.run", "process_batch", "helper_short", "Item", "make_service"]
VIEWS = ["minimal", "normal"]
BUDGETS = [512, 1024, 2048, 4096]


def _normalise(res: dict) -> str:
    res = json.loads(json.dumps(res))
    res.pop("index_run_id", None)
    return json.dumps(res, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> CompositeWorkflowEngine:
    cfg = build_packet_repo(tmp_path_factory.mktemp("snap"))
    return CompositeWorkflowEngine(RetrievalService(load_config(cfg), cfg))


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("budget", BUDGETS)
@pytest.mark.parametrize("query", QUERIES)
def test_minimal_and_normal_unchanged(engine: CompositeWorkflowEngine, query: str, view: str, budget: int) -> None:
    got = _normalise(engine.inspect_symbol(REPO_ID, query=query, view=view, budget_tokens=budget))
    snap = SNAP_DIR / f"{query.replace('.', '_')}__{view}__{budget}.json"
    if os.environ.get("TC_UPDATE_SNAPSHOTS") == "1":
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        snap.write_text(got, encoding="utf-8")
    assert snap.exists(), f"missing snapshot {snap.name}"
    assert got == snap.read_text(encoding="utf-8")
