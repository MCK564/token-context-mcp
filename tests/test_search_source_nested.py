from __future__ import annotations

from pathlib import Path
import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve.service import RetrievalService


@pytest.fixture()
def nested_repo_config(tmp_path: Path) -> Path:
    root = tmp_path / "nested-repo"
    root.mkdir()
    (root / "server.py").write_text(
        """# Server module header

def build_server(config_path: str) -> None:
    # Initialization
    default_timeout = 30

    def _invoke(callback: str, tool_name: str = "tool_call") -> str:
        return f"result of {callback} on {tool_name}"

    return _invoke("run")
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="test-nested", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"test-nested": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def _service(config_path: Path) -> RetrievalService:
    return RetrievalService(load_config(config_path), config_path)


def test_search_source_resolves_innermost_symbol(nested_repo_config: Path) -> None:
    service = _service(nested_repo_config)
    res = service.search_source("test-nested", query="def _invoke", limit=10)
    matches = res["data"]["matches"]
    assert len(matches) >= 1

    invoke_match = next(m for m in matches if m["path"] == "server.py")
    # Must resolve to innermost symbol _invoke, NOT outer build_server
    assert invoke_match["symbol_id"] is not None
    assert "_invoke" in invoke_match["symbol_id"]
    assert "build_server" not in invoke_match["symbol_id"]
    assert invoke_match["start_line"] == 7
    assert "def _invoke" in invoke_match["snippet"]


def test_search_source_caps_at_two_lines_per_file(nested_repo_config: Path) -> None:
    root = load_config(nested_repo_config).repositories["test-nested"].root
    (root / "multimatch.py").write_text(
        """def test_func():
    log("step 1: process target data")
    log("step 2: ignore")
    log("step 3: process target data")
    log("step 4: process target data")
""",
        encoding="utf-8",
    )
    repo = RepositoryConfig(repo_id="test-nested", root=root.resolve())
    build_index(repo, nested_repo_config.parent / "indexes", network_policy="declared-deny-not-enforced")

    service = _service(nested_repo_config)
    res = service.search_source("test-nested", query="process target data", limit=10)
    file_matches = [m for m in res["data"]["matches"] if m["path"] == "multimatch.py"]

    # Maximum 2 lines per file
    assert len(file_matches) == 2
    matched_lines = [m["start_line"] for m in file_matches]
    assert matched_lines == [2, 4]


def test_search_source_symbol_scoring_distinct_terms(nested_repo_config: Path) -> None:
    root = load_config(nested_repo_config).repositories["test-nested"].root
    (root / "scoring.py").write_text(
        """def b():
    x = "term_alpha"
    y = "term_alpha"

def a():
    x = "term_alpha"
    y = "term_beta"
    z = "term_gamma"
""",
        encoding="utf-8",
    )
    repo = RepositoryConfig(repo_id="test-nested", root=root.resolve())
    build_index(repo, nested_repo_config.parent / "indexes", network_policy="declared-deny-not-enforced")

    service = _service(nested_repo_config)
    res = service.search_source("test-nested", query="term_alpha term_beta term_gamma", limit=10)
    file_matches = [m for m in res["data"]["matches"] if m["path"] == "scoring.py"]

    # a() has 3 distinct terms in its span, b() has only 1.
    # Therefore, a() must be scored higher and appear before b().
    assert file_matches
    first_symbol = file_matches[0]["symbol_id"]
    assert first_symbol is not None
    assert "a" in first_symbol


def test_search_source_caps_at_three_symbols_per_file(nested_repo_config: Path) -> None:
    root = load_config(nested_repo_config).repositories["test-nested"].root
    (root / "five_funcs.py").write_text(
        """def f1():
    return "unique_marker_kw"

def f2():
    return "unique_marker_kw"

def f3():
    return "unique_marker_kw"

def f4():
    return "unique_marker_kw"

def f5():
    return "unique_marker_kw"
""",
        encoding="utf-8",
    )
    repo = RepositoryConfig(repo_id="test-nested", root=root.resolve())
    build_index(repo, nested_repo_config.parent / "indexes", network_policy="declared-deny-not-enforced")

    service = _service(nested_repo_config)
    res = service.search_source("test-nested", query="unique_marker_kw", limit=10)
    file_matches = [m for m in res["data"]["matches"] if m["path"] == "five_funcs.py"]

    # Maximum 3 symbols per file
    matched_symbol_ids = {m["symbol_id"] for m in file_matches if m["symbol_id"]}
    assert len(matched_symbol_ids) <= 3
    assert res["data"]["omitted_count"] > 0
    assert res["truncated"] is True

