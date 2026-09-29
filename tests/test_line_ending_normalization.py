from __future__ import annotations

from pathlib import Path
import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve.serialization import ResultFinalizer, normalize_line_endings
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine


def test_normalize_line_endings_helper() -> None:
    data = {
        "text": "line1\r\nline2\r\nline3",
        "nested": ["item1\r\n", {"deep": "deep1\r\ndeep2"}],
        "number": 42,
    }
    normalized = normalize_line_endings(data)
    assert normalized["text"] == "line1\nline2\nline3"
    assert normalized["nested"][0] == "item1\n"
    assert normalized["nested"][1]["deep"] == "deep1\ndeep2"
    assert normalized["number"] == 42


@pytest.fixture()
def crlf_repo_config(tmp_path: Path) -> Path:
    root = tmp_path / "crlf-repo"
    root.mkdir()
    # Explicitly write file with Windows CRLF line endings
    (root / "crlf_module.py").write_bytes(
        b"import os\r\nimport sys\r\n\r\ndef greet(name: str) -> str:\r\n    msg = f'Hello, {name}!'\r\n    return msg\r\n"
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-crlf", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-crlf": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def _service(config_path: Path) -> RetrievalService:
    return RetrievalService(load_config(config_path), config_path)


def test_retrieval_normalizes_crlf_to_lf(crlf_repo_config: Path) -> None:
    service = _service(crlf_repo_config)

    # 1. file_skeleton
    skeleton = service.file_skeleton("test-crlf", path="crlf_module.py")
    assert len(skeleton["data"]["skeleton"]) >= 1
    for item in skeleton["data"]["skeleton"]:
        if item.get("content"):
            assert "\r" not in item["content"]

    # 2. find_symbols -> symbol_context
    symbols = service.find_symbols("test-crlf", pattern="greet")
    symbol_id = symbols["data"]["symbols"][0]["symbol_id"]
    ctx = service.symbol_context("test-crlf", symbol_id=symbol_id, include_body=True)
    symbol_entry = ctx["data"]["symbols"][0]
    assert symbol_entry["content"] is not None
    assert "\r" not in symbol_entry["content"]
    assert "return msg" in symbol_entry["content"]

    # 3. search_source
    search_res = service.search_source("test-crlf", query="greet")
    for match in search_res["data"]["matches"]:
        if match.get("snippet"):
            assert "\r" not in match["snippet"]

    # 4. inspect_symbol workflow
    workflow = CompositeWorkflowEngine(service)
    inspected = workflow.inspect_symbol("test-crlf", query="greet", view="full")
    packet_content = inspected["data"]["packet"]["target"]["content"]
    assert packet_content is not None
    assert "\r" not in packet_content

    # 5. ResultFinalizer
    finalizer = ResultFinalizer(output_mode="structured")
    call_res = finalizer.finalize(ctx)
    assert "\r" not in str(call_res.structured_content)
