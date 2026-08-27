from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from token_context_mcp.config import load_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve.service import RetrievalService


def _service(config_path: Path) -> RetrievalService:
    return RetrievalService(load_config(config_path), config_path)


def test_index_excludes_env_and_emits_source_backed_symbols(indexed_config: Path) -> None:
    service = _service(indexed_config)
    status = service.status("demo")
    assert status["freshness"] == "fresh"
    assert status["data"]["files_indexed"] == 4  # .env is hard denied
    found = service.find_symbols("demo", pattern="alpha")
    alpha = found["data"]["symbols"][0]
    assert alpha["path"] == "app.py"
    assert found["evidence"][0]["sha256"]


def test_skeleton_elides_body_and_context_redacts_canary(indexed_config: Path) -> None:
    service = _service(indexed_config)
    skeleton = service.file_skeleton("demo", path="app.py", include_private=True, max_tokens=1024)
    contents = "\n".join(part["content"] for part in skeleton["data"]["skeleton"])
    assert "token-context-canary-123456" not in contents
    assert any(part.get("body_elided") for part in skeleton["data"]["skeleton"])
    private_symbol = service.find_symbols("demo", pattern="private_helper")["data"]["symbols"][0]
    context = service.symbol_context(
        "demo", symbol_id=private_symbol["symbol_id"], depth=0, include_body=True, max_tokens=1024
    )
    body = context["data"]["symbols"][0]["content"]
    assert "token-context-canary-123456" not in body
    assert "[REDACTED: potential secret]" in body


def test_symbol_context_and_impact_mark_lexical_limit(indexed_config: Path) -> None:
    service = _service(indexed_config)
    alpha = service.find_symbols("demo", pattern="alpha")["data"]["symbols"][0]
    context = service.symbol_context("demo", symbol_id=alpha["symbol_id"], depth=1, max_tokens=1024)
    assert context["data"]["symbols"][0]["symbol"]["symbol_id"] == alpha["symbol_id"]
    assert "lexical_edges_are_not_complete_semantic_analysis" in context["warnings"]
    impact = service.impact_slice("demo", symbol_id=alpha["symbol_id"], direction="callees", depth=1)
    assert any(edge["target_name"] == "beta" for edge in impact["data"]["edges"])


def test_status_becomes_stale_when_indexed_file_changes(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    (config.repositories["demo"].root / "app.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
    assert _service(indexed_config).status("demo")["freshness"] == "stale"


def test_result_matches_shared_envelope_schema(indexed_config: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    schema = json.loads((project_root / "schemas" / "mcp-result.schema.json").read_text(encoding="utf-8"))
    result = _service(indexed_config).find_symbols("demo", pattern="alpha")
    jsonschema.validate(result, schema)


def test_second_index_reuses_unchanged_parse_results(indexed_config: Path) -> None:
    config = load_config(indexed_config)
    manifest = build_index(
        config.repositories["demo"], indexed_config.parent / "indexes", network_policy="declared-deny-not-enforced"
    )
    assert manifest["files_reused"] == 3
    assert manifest["files_reparsed"] == 0
