from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from token_context_mcp.config import load_config, save_config
from token_context_mcp.models import AppConfig, ServerConfig
from token_context_mcp.retrieve.projection import OutputProjector
from token_context_mcp.retrieve.serialization import ResultFinalizer, serialize_compact, summarize_payload
from token_context_mcp.retrieve.token_budget import pack_by_budget
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.server import build_server


def test_result_finalizer_modes() -> None:
    payload = {
        "schema_version": "1.0",
        "repo_id": "demo",
        "freshness": "fresh",
        "truncated": False,
        "warnings": ["test_warning"],
        "data": {
            "symbols": [{"name": "foo", "path": "a.py"}, {"name": "bar", "path": "b.py"}],
            "count": 2,
        },
    }

    # 1. Structured mode
    structured_finalizer = ResultFinalizer(output_mode="structured")
    res_struct = structured_finalizer.finalize(payload)
    assert res_struct.structured_content == payload
    assert len(res_struct.content) == 1
    assert "repo_id=demo" in res_struct.content[0].text
    assert "freshness=fresh" in res_struct.content[0].text
    assert "symbols=2" in res_struct.content[0].text
    assert len(res_struct.content[0].text) < 200

    # 2. Text mode
    text_finalizer = ResultFinalizer(output_mode="text")
    res_text = text_finalizer.finalize(payload)
    assert res_text.structured_content is None
    assert len(res_text.content) == 1
    assert "foo" in res_text.content[0].text
    assert serialize_compact(payload) == res_text.content[0].text

    # 3. Legacy dual mode
    dual_finalizer = ResultFinalizer(output_mode="legacy_dual")
    res_dual = dual_finalizer.finalize(payload)
    assert res_dual.structured_content == payload
    assert res_dual.content[0].text == serialize_compact(payload)


def test_output_projector_presets() -> None:
    symbol = {
        "symbol_id": "sym1",
        "name": "calc",
        "kind": "function",
        "path": "math.py",
        "start_line": 10,
        "end_line": 20,
        "signature": "def calc(x: int) -> int",
        "docstring": "Calculates something expensive.",
        "extra_debug_info": "should be stripped in minimal",
    }
    payload = {
        "schema_version": "1.0",
        "repo_id": "demo",
        "freshness": "fresh",
        "data": {
            "symbols": [symbol],
        },
    }

    # Minimal view strips signature, docstring, extra fields
    minimal = OutputProjector.project(payload, view="minimal")
    proj_sym = minimal["data"]["symbols"][0]
    assert "symbol_id" in proj_sym
    assert "name" in proj_sym
    assert "path" in proj_sym
    assert "signature" not in proj_sym
    assert "docstring" not in proj_sym
    assert "extra_debug_info" not in proj_sym

    # Normal view keeps standard signature
    normal = OutputProjector.project(payload, view="normal")
    proj_norm = normal["data"]["symbols"][0]
    assert "signature" in proj_norm

    # Full view keeps everything
    full = OutputProjector.project(payload, view="full")
    proj_full = full["data"]["symbols"][0]
    assert "signature" in proj_full
    assert "extra_debug_info" in proj_full


def test_pack_by_budget_preserves_first_item() -> None:
    # An item that takes 100 tokens, but budget is only 50 tokens
    large_item = {"name": "very_large_item", "data": "x" * 400}
    small_item = {"name": "small", "data": "y" * 10}

    # With preserve_first=True, large_item is kept despite exceeding budget
    packed, omitted, used = pack_by_budget(
        [large_item, small_item],
        render=lambda x: x["data"],
        budget_tokens=50,
        preserve_first=True,
    )
    assert len(packed) == 1
    assert packed[0]["name"] == "very_large_item"
    assert len(omitted) == 1
    assert omitted[0]["name"] == "small"

    # With preserve_first=False: large_item is skipped because it exceeds budget,
    # and subsequent small_item is packed.
    packed_none, omitted_none, used_none = pack_by_budget(
        [large_item, small_item],
        render=lambda x: x["data"],
        budget_tokens=50,
        preserve_first=False,
    )
    assert len(packed_none) == 1
    assert packed_none[0]["name"] == "small"
    assert len(omitted_none) == 1
    assert omitted_none[0]["name"] == "very_large_item"


def test_composite_inspect_symbol_workflow(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    service = RetrievalService(config, indexed_config)
    engine = CompositeWorkflowEngine(service)

    # Test resolved symbol
    res = engine.inspect_symbol(repo_id="demo", query="alpha")
    assert res["schema_version"] == "1.0"
    assert res["data"]["status"] == "resolved"
    assert res["data"]["target_symbol_id"]
    assert "symbol" in res["data"]
    assert "relationships" in res["data"]

    # Test minimal projection
    res_min = engine.inspect_symbol(repo_id="demo", query="alpha", view="minimal")
    assert res_min["data"]["status"] == "resolved"

    # Test not found
    res_not_found = engine.inspect_symbol(repo_id="demo", query="non_existent_symbol_xyz")
    assert res_not_found["data"]["status"] == "not_found"


def test_server_config_output_mode_and_default_view(tmp_path: Path, sample_repo: Path) -> None:
    config_path = tmp_path / "repos.toml"
    server_cfg = ServerConfig(
        output_mode="text",
        default_view="minimal",
    )
    app_cfg = AppConfig(
        repositories={},
        server=server_cfg,
    )
    save_config(config_path, app_cfg)

    loaded = load_config(config_path)
    assert loaded.server.output_mode == "text"
    assert loaded.server.default_view == "minimal"
