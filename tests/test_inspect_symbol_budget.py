from __future__ import annotations

import json
from pathlib import Path
import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine


@pytest.fixture()
def large_func_repo_config(tmp_path: Path) -> Path:
    root = tmp_path / "large-repo"
    root.mkdir()

    # Generate an ~80 line function
    lines = ["def process_large_workload(items: list[int]) -> int:", "    total = 0"]
    for i in range(1, 75):
        lines.append(f"    total += items[{i % 5}] * {i}")
    lines.append("    # End of workload processing")
    lines.append("    return total")
    lines.append("")
    # Add ambiguous symbols with same name in two different classes
    lines.append("class WorkerA:")
    lines.append("    def execute(self) -> None:")
    lines.append("        pass")
    lines.append("")
    lines.append("class WorkerB:")
    lines.append("    def execute(self) -> None:")
    lines.append("        pass")
    lines.append("")

    (root / "workload.py").write_text("\n".join(lines), encoding="utf-8")

    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-large", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-large": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def _service_and_wf(config_path: Path) -> tuple[RetrievalService, CompositeWorkflowEngine]:
    svc = RetrievalService(load_config(config_path), config_path)
    wf = CompositeWorkflowEngine(svc)
    return svc, wf


def test_inspect_symbol_returns_content_when_budget_sufficient(large_func_repo_config: Path) -> None:
    svc, wf = _service_and_wf(large_func_repo_config)
    res = wf.inspect_symbol("test-large", query="process_large_workload", view="normal", budget_tokens=2048)

    assert res["data"]["status"] == "resolved"
    content = res["data"]["content"]
    assert content is not None
    assert "return total" in content
    assert "content_omitted_budget" not in res["warnings"]
    assert "retry_hint" not in res["data"]


def test_inspect_symbol_handles_tight_budget(large_func_repo_config: Path) -> None:
    svc, wf = _service_and_wf(large_func_repo_config)
    res = wf.inspect_symbol("test-large", query="process_large_workload", view="normal", budget_tokens=256)

    assert res["data"]["status"] == "resolved"
    assert res["data"]["content"] is None
    assert "content_omitted_budget" in res["warnings"]
    assert "retry_hint" in res["data"]
    assert res["data"]["retry_hint"]["tool"] == "get_symbol_context"
    assert res["data"]["retry_hint"]["include_body"] is True
    assert res["data"]["retry_hint"]["depth"] == 0
    assert res["data"]["retry_hint"]["max_tokens"] == 4096


def test_inspect_symbol_all_views_envelope_keys(large_func_repo_config: Path) -> None:
    svc, wf = _service_and_wf(large_func_repo_config)
    for view in ("minimal", "normal", "full"):
        res = wf.inspect_symbol("test-large", query="process_large_workload", view=view, budget_tokens=1024)
        assert "budget" in res
        assert "truncated" in res
        assert "warnings" in res
        assert isinstance(res["warnings"], list)
        assert res["budget"]["requested_tokens"] == 1024
        assert res["budget"]["estimated_tokens"] <= 1024
        assert "evidence" in res


def test_inspect_symbol_ambiguous_candidates_have_integer_start_line(large_func_repo_config: Path) -> None:
    svc, wf = _service_and_wf(large_func_repo_config)
    res = wf.inspect_symbol("test-large", query="execute", view="normal", budget_tokens=1024)

    assert res["data"]["status"] == "ambiguous"
    candidates = res["data"]["candidates"]
    assert len(candidates) >= 2
    for cand in candidates:
        assert isinstance(cand.get("start_line"), int)
        assert cand["start_line"] > 0


def test_symbol_context_fallback_omits_body_not_root_symbol(large_func_repo_config: Path) -> None:
    svc, wf = _service_and_wf(large_func_repo_config)
    symbols = svc.find_symbols("test-large", pattern="process_large_workload")
    symbol_id = symbols["data"]["symbols"][0]["symbol_id"]

    # Budget smaller than function body (~80 lines ~750 tokens) but large enough for symbol metadata (~340 tokens)
    ctx = svc.symbol_context("test-large", symbol_id=symbol_id, include_body=True, depth=0, max_tokens=500)

    assert len(ctx["data"]["symbols"]) >= 1
    root = ctx["data"]["symbols"][0]
    assert root["symbol"]["symbol_id"] == symbol_id
    assert root["body_included"] is False
    assert "root_body_omitted_budget" in ctx["warnings"]
    assert "root_body_tokens_needed" in ctx["data"]


def test_symbol_context_omitted_body_points_to_windowed_read(large_func_repo_config: Path) -> None:
    svc, _wf = _service_and_wf(large_func_repo_config)
    symbol_id = svc.find_symbols("test-large", pattern="process_large_workload")["data"]["symbols"][0]["symbol_id"]

    ctx = svc.symbol_context(
        "test-large", symbol_id=symbol_id, include_body=True, depth=0, max_tokens=500, body_paging_hint=True
    )

    assert "root_body_omitted_budget" in ctx["warnings"]
    assert ctx["data"]["root_body_lines"] >= 70
    assert "body_offset_line" in ctx["data"]["root_body_hint"]


def test_symbol_context_body_windows_cover_the_whole_body(large_func_repo_config: Path) -> None:
    svc, _wf = _service_and_wf(large_func_repo_config)
    symbol_id = svc.find_symbols("test-large", pattern="process_large_workload")["data"]["symbols"][0]["symbol_id"]
    whole = svc.symbol_context("test-large", symbol_id=symbol_id, include_body=True, depth=0, max_tokens=4096)
    expected = whole["data"]["symbols"][0]["content"].split("\n")
    assert whole["data"]["symbols"][0]["body_included"] is True

    collected: list[str] = []
    offset: int | None = 1
    windows = 0
    while offset is not None:
        ctx = svc.symbol_context(
            "test-large", symbol_id=symbol_id, depth=0, max_tokens=500, body_offset_line=offset
        )
        root = ctx["data"]["symbols"][0]
        window = root["body_window"]
        assert root["body_included"] is True
        assert window["start_line"] == offset
        assert window["total_lines"] == len(expected)
        assert ctx["budget"]["estimated_tokens"] <= 500
        collected.extend(root["content"].split("\n"))
        offset = window["next_offset"]
        if offset is not None:
            assert "root_body_window_truncated" in ctx["warnings"]
        windows += 1
        assert windows < 50

    assert windows >= 2
    assert collected == expected


def test_symbol_context_body_offset_out_of_range(large_func_repo_config: Path) -> None:
    from token_context_mcp.retrieve.service import ArgumentOutOfRangeError

    svc, _wf = _service_and_wf(large_func_repo_config)
    symbol_id = svc.find_symbols("test-large", pattern="process_large_workload")["data"]["symbols"][0]["symbol_id"]
    with pytest.raises(ArgumentOutOfRangeError):
        svc.symbol_context("test-large", symbol_id=symbol_id, depth=0, max_tokens=500, body_offset_line=0)
    with pytest.raises(ArgumentOutOfRangeError):
        svc.symbol_context("test-large", symbol_id=symbol_id, depth=0, max_tokens=500, body_offset_line=10_000)


@pytest.fixture()
def callee_repo_config(tmp_path: Path) -> Path:
    root = tmp_path / "callee-repo"
    root.mkdir()

    # 12 callees, not 5: the E14 fix (pulling relationships straight from the graph
    # instead of through impact_slice's own internal budget) means edge_budget's 256-token
    # floor now comfortably holds 5 small relationship dicts (~192 tokens), so 5 callees
    # no longer characterizes a "tight" budget. 12 (~460 tokens) still fits the largest
    # possible edge_budget (1024, at budget_tokens ~4096) but overflows the 256 floor,
    # so the truncation case below stays genuinely tight under the corrected behaviour.
    lines = [f"def callee_{i:02d}(): pass" for i in range(12)]
    lines.append("")
    lines.append("def caller_func():")
    lines.extend(f"    callee_{i:02d}()" for i in range(12))
    (root / "caller.py").write_text("\n".join(lines), encoding="utf-8")

    config_path = tmp_path / "config_callee" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-callee", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-callee": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def test_inspect_symbol_relationships_normal_and_truncated(callee_repo_config: Path) -> None:
    svc, wf = _service_and_wf(callee_repo_config)

    # 1. View normal, budget 4096 (edge_budget maxes out at 1024) -> all 12 relationships
    res = wf.inspect_symbol("test-callee", query="caller_func", view="normal", budget_tokens=4096)
    assert res["data"]["status"] == "resolved"
    assert res["data"]["relationship_count"] == 12
    assert len(res["data"]["relationships"]) == 12
    # Compact format check: {source, target, kind, confidence}
    rel0 = res["data"]["relationships"][0]
    assert set(rel0.keys()) == {"source", "target", "kind", "confidence"}
    assert res["budget"]["estimated_tokens"] <= 4096
    assert "relationships_truncated" not in res["warnings"]

    # 2. Budget 256 (the edge_budget floor) -> too small for all 12, still truncates
    res_tight = wf.inspect_symbol("test-callee", query="caller_func", view="normal", budget_tokens=256)
    assert "relationships_truncated" in res_tight["warnings"]
    assert res_tight["data"].get("relationships_omitted", 0) > 0 or res_tight["data"]["relationship_count"] < 12


# --- E14: inspect_symbol relationship contract compliance (M6) -----------------------
#
# Fixture mirrors a pattern confirmed live on the real repo (get_impact_slice on
# rank_symbols, 2026-09-27): a resolved same-file callee (local_push_ppr), an
# ambiguous unresolved-receiver call (`get`, confidence 0.10), and a stdlib virtual_stub
# call (`append`). The E14 fix must surface the first and exclude the other two in
# every view.


@pytest.fixture()
def relationship_filter_repo_config(tmp_path: Path) -> Path:
    root = tmp_path / "relfilter-repo"
    root.mkdir()
    lines = [
        "def local_push_ppr(x):",
        "    return x",
        "",
        "class Decoy:",
        "    def get(self, k):",
        "        return None",
        "",
        "def target_fn(ppr, ranked: list):",
        "    local_push_ppr(ppr)",
        "    ppr.get('k')",
        "    ranked.append(1)",
        "    return ranked",
    ]
    (root / "mod.py").write_text("\n".join(lines), encoding="utf-8")

    config_path = tmp_path / "config_relfilter" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-relfilter", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-relfilter": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def test_inspect_symbol_minimal_relationships_filtered(relationship_filter_repo_config: Path) -> None:
    """minimal at budget 1024 must include local_push_ppr and must NOT include the
    ambiguous `get` call or the stub `append` call."""
    svc, wf = _service_and_wf(relationship_filter_repo_config)
    res = wf.inspect_symbol("test-relfilter", query="target_fn", view="minimal", budget_tokens=1024)

    assert res["data"]["status"] == "resolved"
    rels = res["data"]["relationships"]
    assert len(rels) == 1
    other_id, relation, confidence = rels[0]
    assert "local_push_ppr" in other_id
    assert relation == "callee"
    assert confidence >= 0.5
    # the ambiguous `get` (0.10) and the virtual_stub `append` were excluded by the
    # quality filter, not by budget -- relationships_filtered counts them separately
    # from relationships_omitted.
    assert res["data"]["relationships_filtered"] == 2
    assert "relationships_truncated" not in res["warnings"]


def test_inspect_symbol_normal_relationships_exclude_ambiguous_and_stub(
    relationship_filter_repo_config: Path,
) -> None:
    svc, wf = _service_and_wf(relationship_filter_repo_config)
    res = wf.inspect_symbol("test-relfilter", query="target_fn", view="normal", budget_tokens=2048)

    rels = res["data"]["relationships"]
    assert len(rels) == 1
    assert set(rels[0].keys()) == {"source", "target", "kind", "confidence"}
    assert rels[0]["confidence"] >= 0.5
    assert "local_push_ppr" in rels[0]["target"]
    assert res["data"]["relationships_filtered"] == 2


def test_inspect_symbol_full_relationships_match_normal(relationship_filter_repo_config: Path) -> None:
    """full's relationships are the same filtered/packed list as normal (M6 contract) --
    no more raw, unfiltered edges in full view."""
    svc, wf = _service_and_wf(relationship_filter_repo_config)
    normal = wf.inspect_symbol("test-relfilter", query="target_fn", view="normal", budget_tokens=2048)
    full = wf.inspect_symbol("test-relfilter", query="target_fn", view="full", budget_tokens=2048)
    # M6 phase 2 (D9): `full` carries a context packet instead of `relationships`; every relationship of
    # `normal` shows up in the packet (callees + callers + more) when the budget is generous.
    assert "relationships" not in full["data"]
    assert "content" not in full["data"]
    from token_context_mcp.retrieve.service import _compact_symbol_ref

    target_id = normal["data"]["target_symbol_id"]
    normal_refs = set()
    for rel in normal["data"]["relationships"]:
        other = rel["target"] if rel["source"] == target_id else rel["source"]
        normal_refs.add(_compact_symbol_ref(other))
    packet = full["data"]["packet"]
    packet_refs = {row[0] for key in ("callees", "callers", "more") for row in packet[key]}
    assert normal_refs and normal_refs <= packet_refs
    assert full["data"]["relationships_filtered"] == normal["data"]["relationships_filtered"]


def test_inspect_symbol_view_size_ordering_and_determinism(relationship_filter_repo_config: Path) -> None:
    svc, wf = _service_and_wf(relationship_filter_repo_config)
    sizes = {}
    for view in ("minimal", "normal", "full"):
        res = wf.inspect_symbol("test-relfilter", query="target_fn", view=view, budget_tokens=2048)
        sizes[view] = len(json.dumps(res))
        res2 = wf.inspect_symbol("test-relfilter", query="target_fn", view=view, budget_tokens=2048)
        assert json.dumps(res, sort_keys=True) == json.dumps(res2, sort_keys=True)

    assert sizes["full"] >= sizes["normal"] >= sizes["minimal"]

