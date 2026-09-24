from __future__ import annotations

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
