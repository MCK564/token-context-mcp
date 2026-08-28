from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from token_context_mcp.config import load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.models import (
    AppConfig,
    RepositoryConfig,
    ServerConfig,
    SymbolRecord,
)
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.retrieve.token_budget import estimate_tokens


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


def test_module_dependents_uses_parsed_imports(indexed_config: Path) -> None:
    service = _service(indexed_config)
    by_path = service.module_dependents("demo", path="helpers.py")
    assert by_path["data"]["basis"] == "parsed_import_statements"
    assert by_path["data"]["imports"] == []
    assert by_path["data"]["imported_by"] == ["app.py"]

    by_module = service.module_dependents("demo", module="helpers")
    assert by_module["data"]["matched_paths"] == ["helpers.py"]
    assert by_module["data"]["imported_by"] == ["app.py"]


def test_search_source_returns_bounded_body_evidence(indexed_config: Path) -> None:
    service = _service(indexed_config)
    response = service.search_source("demo", query="beta", limit=10, max_tokens=512)
    assert response["data"]["matches"]
    app_match = next(item for item in response["data"]["matches"] if item["path"] == "app.py")
    assert app_match["symbol_id"]
    assert app_match["start_line"] >= 1

    redacted = service.search_source("demo", query="token-context-canary", limit=10, max_tokens=512)
    assert redacted["data"]["matches"]
    assert "token-context-canary-123456" not in str(redacted)
    assert "[REDACTED: potential secret]" in str(redacted)


def test_repo_map_query_uses_body_matches(indexed_config: Path) -> None:
    response = _service(indexed_config).repo_map(
        "demo", query="token-context-canary", budget_tokens=512, format="full"
    )
    assert response["data"]["symbols"]
    assert response["data"]["symbols"][0]["symbol"]["name"] == "private_helper"


def test_lexical_edges_prefer_scoped_candidates() -> None:
    def symbol(symbol_id: str, path: str, name: str, start: int) -> SymbolRecord:
        return SymbolRecord(
            symbol_id=symbol_id,
            path=path,
            name=name,
            qualified_name=name,
            kind="function",
            signature=f"def {name}()",
            start_line=start,
            end_line=start + 1,
            start_byte=0,
            end_byte=40,
            body_start_byte=10,
            body_end_byte=40,
            is_private=False,
        )

    caller = symbol("caller", "pkg/caller.py", "caller", 1)
    local_run = symbol("local-run", "pkg/caller.py", "run", 4)
    other_run = symbol("other-run", "other.py", "run", 1)
    edges = build_lexical_edges(
        [caller, local_run, other_run],
        {"pkg/caller.py": "def caller():\n    return run()\n"},
    )
    edge = next(edge for edge in edges if edge.source_symbol_id == "caller" and edge.target_name == "run")
    assert edge.status == "resolved"
    assert edge.target_symbol_id == "local-run"
    assert "scope:same_file" in edge.evidence


def test_file_and_status_expose_import_counts(indexed_config: Path) -> None:
    service = _service(indexed_config)
    skeleton = service.file_skeleton("demo", path="app.py")
    assert skeleton["data"]["imports"] == 1
    assert skeleton["data"]["imported_by"] == 0
    status = service.status("demo")
    assert status["data"]["imports"] == 1
    assert status["data"]["imported_by"] == 1


def test_profiles_are_discoverable_and_equivalent_to_explicit_arguments(indexed_config: Path) -> None:
    service = _service(indexed_config)
    listed = service.list_repositories()
    assert set(listed["budget_profiles"]) == {"impact", "locate", "orient", "read"}

    profiled = service.repo_map("demo", profile="orient")
    explicit = service.repo_map("demo", budget_tokens=4096, format="compact")
    assert profiled == explicit
    assert profiled["budget"]["envelope_reserve"] == 96

    profiled_find = service.find_symbols("demo", pattern="alpha", profile="locate")
    explicit_find = service.find_symbols("demo", pattern="alpha", limit=30, max_tokens=1024)
    assert profiled_find == explicit_find


def test_status_exposes_scale_aware_index_defaults(indexed_config: Path) -> None:
    status = _service(indexed_config).status("demo")
    defaults = status["data"]["derived_defaults"]
    assert defaults["max_edges_per_symbol"]["value"] >= 25
    assert defaults["limit_ceiling"]["value"] >= 30
    assert defaults["impact_max_nodes"]["value"] >= 30
    assert all(defaults[key]["formula"] for key in defaults)


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


def test_declared_budget_bounds_serialized_payload(indexed_config: Path) -> None:
    service = _service(indexed_config)
    alpha = service.find_symbols("demo", pattern="alpha")["data"]["symbols"][0]
    responses = [
        service.repo_map("demo", budget_tokens=1024),
        service.file_skeleton("demo", path="app.py", max_tokens=1024),
        service.symbol_context("demo", symbol_id=alpha["symbol_id"], depth=1, max_tokens=1024),
        service.impact_slice("demo", symbol_id=alpha["symbol_id"], depth=3, max_nodes=500),
    ]
    for response in responses:
        declared = response["budget"]["estimated_tokens"]
        actual = estimate_tokens(json.dumps(response, sort_keys=True, ensure_ascii=False))
        assert declared <= actual
        assert actual <= declared * 1.15 + 1
        assert actual <= response["budget"]["requested_tokens"]


def test_impact_slice_has_budget_and_precision_metadata(indexed_config: Path) -> None:
    service = _service(indexed_config)
    alpha = service.find_symbols("demo", pattern="alpha")["data"]["symbols"][0]
    response = service.impact_slice("demo", symbol_id=alpha["symbol_id"], depth=3, max_nodes=500)
    assert response["budget"]["requested_tokens"] == 2048
    assert response["budget"]["estimated_tokens"] <= 2048
    assert response["edge_precision"]["basis"] == "edge_status / observed_edges"
    assert "omitted_edge_count" in response["data"]


def test_wire_symbols_omit_byte_offsets_and_evidence_is_compact(indexed_config: Path) -> None:
    response = _service(indexed_config).repo_map("demo", budget_tokens=1024, format="full")
    symbol = response["data"]["symbols"][0]["symbol"]
    assert not {"start_byte", "end_byte", "body_start_byte", "body_end_byte"} & symbol.keys()
    assert len(response["data"]["symbols"][0]["evidence"][0]["sha256"]) == 12


def test_repo_map_compact_entries_are_dense_and_follow_up_resolvable(indexed_config: Path) -> None:
    service = _service(indexed_config)
    response = service.repo_map("demo", budget_tokens=512)
    entries = response["data"]["symbols"]
    assert response["data"]["format"] == "compact"
    assert entries
    assert all(isinstance(entry, list) and len(entry) == 3 for entry in entries)
    assert all(estimate_tokens(json.dumps(entry)) <= 25 for entry in entries)
    assert response["data"]["file_digests"]
    assert service.last_query_count <= 20

    context = service.symbol_context("demo", symbol_id=entries[0][0], depth=0, max_tokens=512)
    assert context["data"]["root_symbol_id"]


def test_index_records_structural_roles_and_entry_point_resolution(tmp_path: Path) -> None:
    root = tmp_path / "role-repo"
    package = root / "pkg"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "role-repo"\n\n[project.scripts]\nrole-cli = "pkg.app:missing"\n',
        encoding="utf-8",
    )
    (package / "contracts.py").write_text(
        "from typing import Protocol\n\n"
        "class FrontendPipeline(Protocol):\n"
        "    def run(self, value: str) -> str: ...\n",
        encoding="utf-8",
    )
    (package / "impl.py").write_text(
        "from .contracts import FrontendPipeline\n"
        "from .registry import register\n\n"
        "class FrontendImpl:\n"
        "    def run(self, value: str) -> str:\n"
        "        return value\n\n"
        'register("impl", FrontendImpl)\n',
        encoding="utf-8",
    )
    (package / "registry.py").write_text(
        "from typing import Callable\n\n"
        "def register(name: str, factory: Callable[[], object]) -> None:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (package / "app.py").write_text(
        "def start() -> None:\n    return None\n\n"
        'if __name__ == "__main__":\n    start()\n',
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="roles", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"roles": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")

    service = _service(config_path)
    status = service.status("roles")
    assert status["data"]["entry_points"] == [
        {"declared": "role-cli = pkg.app:missing", "resolved": False}
    ]
    assert status["data"]["role_counts"]["protocol_definition"] == 1
    assert status["data"]["role_counts"]["protocol_implementation"] == 1
    assert status["data"]["role_counts"]["registry_wiring"] >= 1
    assert status["data"]["symbols_with_roles"] >= 3

    full = service.repo_map("roles", budget_tokens=1024, format="full")
    assert all(entry["rank_basis"] for entry in full["data"]["symbols"])


def test_omitted_ids_are_opt_in_and_truncation_is_truthful(indexed_config: Path) -> None:
    service = _service(indexed_config)
    full = service.repo_map("demo", budget_tokens=512, format="full")
    assert full["truncated"]
    assert "omitted_symbol_ids" not in full["data"]
    opted_in = service.repo_map("demo", budget_tokens=1024, include_omitted_ids=True, format="full")
    assert len(opted_in["data"]["omitted_symbol_ids"]) <= 10
    config = load_config(indexed_config)
    save_config(
        indexed_config,
        AppConfig(
            repositories=config.repositories,
            server=ServerConfig(
                max_result_tokens=config.server.max_result_tokens,
                max_graph_nodes=config.server.max_graph_nodes,
                max_symbol_results=1,
            ),
        ),
    )
    capped = _service(indexed_config).find_symbols("demo", pattern="a", limit=100)
    assert capped["truncated"]


def test_freshness_does_not_hash_unchanged_files(indexed_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(indexed_config)
    calls = 0

    def counted_hash(path: Path) -> str:
        nonlocal calls
        calls += 1
        raise AssertionError("unchanged files should be checked by stat only")

    monkeypatch.setattr("token_context_mcp.retrieve.service.sha256_file", counted_hash)
    assert service.status("demo")["freshness"] == "fresh"
    assert service.status("demo")["freshness"] == "fresh"
    assert calls == 0
