"""M5.2 / M5.3: anchor-then-expand over the resolved call graph, and file communities."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.models import EdgeRecord, SymbolRecord
from token_context_mcp.retrieve.expansion import expand_anchors, file_communities, hub_ids
from token_context_mcp.retrieve.graph_cache import RepoGraph
from token_context_mcp.retrieve.service import RetrievalService


def _sym(name: str, path: str = "src/m.py", line: int = 1) -> SymbolRecord:
    return SymbolRecord(
        symbol_id=f"python:{path}:{name}:x",
        path=path,
        name=name,
        qualified_name=name,
        kind="function",
        signature=f"def {name}()",
        start_line=line,
        end_line=line + 1,
        start_byte=0,
        end_byte=1,
        body_start_byte=None,
        body_end_byte=None,
        is_private=False,
    )


def _edge(src: SymbolRecord, dst: SymbolRecord | None, conf: float, *, status="resolved", backend="lexical") -> EdgeRecord:
    return EdgeRecord(
        source_symbol_id=src.symbol_id,
        target_symbol_id=dst.symbol_id if dst else None,
        target_name=dst.name if dst else "x",
        edge_kind="call",
        status=status,
        backend=backend,
        confidence=conf,
        source_path=src.path,
        source_line=src.start_line,
        evidence=[],
    )


def _graph(symbols, edges) -> RepoGraph:
    return RepoGraph("r", "run1", symbols, edges)


def test_callee_one_hop_and_two_hops_with_decaying_score() -> None:
    a, b, c = _sym("a", line=1), _sym("b", line=10), _sym("c", line=20)
    g = _graph([a, b, c], [_edge(a, b, 0.9), _edge(b, c, 0.9)])
    one, expanded = expand_anchors(g, [a.symbol_id], "a", k=3, hops=1, min_confidence=0.6, communities={})
    assert expanded == 1
    assert [(n.name, n.relation) for n in one] == [("b", "callee")]
    two, _ = expand_anchors(g, [a.symbol_id], "a", k=3, hops=2, min_confidence=0.6, communities={})
    scores = {n.name: n.score for n in two}
    assert set(scores) == {"b", "c"}
    assert scores["c"] < scores["b"]


def test_caller_relation_and_anchor_not_repeated() -> None:
    a, b = _sym("a"), _sym("b", line=5)
    g = _graph([a, b], [_edge(b, a, 0.9)])
    neighbors, _ = expand_anchors(g, [a.symbol_id], "q", k=3, hops=1, min_confidence=0.6, communities={})
    assert [(n.name, n.relation) for n in neighbors] == [("b", "caller")]
    # b is itself an anchor: it must not be returned as a neighbor
    neighbors, _ = expand_anchors(g, [a.symbol_id, b.symbol_id], "q", k=3, hops=1, min_confidence=0.6, communities={})
    assert neighbors == []


def test_low_confidence_ambiguous_and_stub_edges_are_not_traversed() -> None:
    a, glob, amb, stub = _sym("a"), _sym("glob", line=2), _sym("amb", line=3), _sym("stub", line=4)
    edges = [
        _edge(a, glob, 0.40),  # scope:global after M4 calibration
        _edge(a, amb, 0.9, status="ambiguous"),
        _edge(a, stub, 0.9, backend="virtual_stub"),
        _edge(a, None, 0.9),
    ]
    g = _graph([a, glob, amb, stub], edges)
    neighbors, _ = expand_anchors(g, [a.symbol_id], "a", k=8, hops=2, min_confidence=0.6, communities={})
    assert neighbors == []


def test_module_anchor_is_kept_but_not_expanded() -> None:
    a, b = _sym("a"), _sym("b", line=5)
    g = _graph([a, b], [_edge(a, b, 0.9)])
    neighbors, expanded = expand_anchors(
        g, ["python:src/m.py:<module>", a.symbol_id], "q", k=3, hops=1, min_confidence=0.6, communities={}
    )
    assert expanded == 1
    assert [n.anchor_rank for n in neighbors] == [1]


def test_hub_penalty_and_test_label() -> None:
    hub = _sym("hub", path="src/util.py")
    callers = [_sym(f"c{i}", path=f"src/c{i}.py") for i in range(40)]
    a = _sym("a", path="src/a.py")
    other = _sym("other", path="src/o.py")
    t = _sym("test_a", path="tests/test_a.py")
    edges = [_edge(c, hub, 0.9) for c in callers] + [_edge(a, hub, 0.9), _edge(a, other, 0.9), _edge(t, a, 0.9)]
    g = _graph([hub, a, other, t, *callers], edges)
    assert hub.symbol_id in hub_ids(g, 0.6)
    neighbors, _ = expand_anchors(g, [a.symbol_id], "q", k=3, hops=1, min_confidence=0.6, communities={})
    by_name = {n.name: n for n in neighbors}
    assert by_name["hub"].score < by_name["other"].score
    assert by_name["test_a"].relation == "test"


def test_expansion_is_deterministic() -> None:
    a = _sym("a")
    others = [_sym(f"n{i}", line=10 + i) for i in range(6)]
    g = _graph([a, *others], [_edge(a, o, 0.9) for o in others])
    runs = [
        [n.as_row() for n in expand_anchors(g, [a.symbol_id], "q", k=3, hops=1, min_confidence=0.6, communities={})[0]]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]
    assert [row[2] for row in runs[0]] == ["function n0", "function n1", "function n2"]


def test_file_communities_two_clusters_and_isolated_file() -> None:
    paths = ["src/pkg/a.py", "src/pkg/b.py", "src/other/x.py", "src/other/y.py", "src/lonely.py"]
    imports = [
        ("src/pkg/a.py", "pkg.b"),
        ("src/pkg/b.py", "pkg.a"),
        ("src/other/x.py", "other.y"),
        ("src/other/y.py", "other.x"),
        ("src/pkg/a.py", "os"),
    ]
    first = file_communities(paths, imports)
    second = file_communities(list(reversed(paths)), list(reversed(imports)))
    assert first == second
    assert first["src/pkg/a.py"] == first["src/pkg/b.py"]
    assert first["src/other/x.py"] == first["src/other/y.py"]
    assert first["src/pkg/a.py"] != first["src/other/x.py"]
    assert len(set(first.values())) == 3


@pytest.fixture()
def call_chain_config(tmp_path: Path) -> Path:
    root = tmp_path / "chain"
    root.mkdir()
    (root / "alpha.py").write_text(
        "def parse_widget_header(raw):\n"
        "    return normalize_bytes(raw)\n\n\n"
        "def normalize_bytes(raw):\n"
        "    return encode_payload(raw)\n\n\n"
        "def encode_payload(raw):\n"
        "    return raw\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id="chain", root=root.resolve())
    save_config(config_path, AppConfig(repositories={"chain": repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path


def _service(config_path: Path) -> RetrievalService:
    return RetrievalService(load_config(config_path), config_path)


def test_search_source_graph_adds_neighbors_and_retrieval(call_chain_config: Path) -> None:
    svc = _service(call_chain_config)
    res = svc.search_source("chain", query="widget header", expand="graph", expand_hops=2)
    data = res["data"]
    assert ":parse_widget_header:" in data["matches"][0]["symbol_id"]
    names = [row[2] for row in data["neighbors"]]
    assert "function normalize_bytes" in names
    assert "function encode_payload" in names
    assert data["retrieval"]["expand_effective"] == "graph"
    assert data["retrieval"]["anchors"] >= 1


def test_expand_none_output_identical_to_default(call_chain_config: Path) -> None:
    svc = _service(call_chain_config)
    default = svc.search_source("chain", query="widget header")
    none = svc.search_source("chain", query="widget header", expand="none")
    auto = svc.search_source("chain", query="widget header", expand="auto")
    strip = lambda r: json.dumps({k: v for k, v in r.items() if k != "generated_at"}, sort_keys=True)
    assert strip(default) == strip(none) == strip(auto)
    assert "neighbors" not in none["data"] and "retrieval" not in none["data"]


def test_locate_profile_turns_on_graph(call_chain_config: Path) -> None:
    res = _service(call_chain_config).search_source("chain", query="widget header", profile="locate")
    assert res["data"]["retrieval"]["expand_effective"] == "graph"


def test_graph_response_byte_identical_across_calls(call_chain_config: Path) -> None:
    svc = _service(call_chain_config)
    a = svc.search_source("chain", query="widget header", expand="graph")
    b = svc.search_source("chain", query="widget header", expand="graph")
    assert json.dumps(a["data"], sort_keys=True) == json.dumps(b["data"], sort_keys=True)


@pytest.mark.parametrize("budget", [256, 1024, 4096])
def test_neighbors_stay_within_quarter_budget(call_chain_config: Path, budget: int) -> None:
    from token_context_mcp.retrieve.service import _payload_tokens

    res = _service(call_chain_config).search_source(
        "chain", query="widget header", expand="graph", expand_hops=2, max_tokens=budget
    )
    assert _payload_tokens(res["data"]["neighbors"]) <= budget * 0.25
    assert res["budget"]["estimated_tokens"] <= budget


def test_invalid_expand_arguments_rejected(call_chain_config: Path) -> None:
    svc = _service(call_chain_config)
    with pytest.raises(Exception):
        svc.search_source("chain", query="widget", expand="everything")
    with pytest.raises(Exception):
        svc.search_source("chain", query="widget", expand="graph", expand_k=9)
    with pytest.raises(Exception):
        svc.search_source("chain", query="widget", expand="graph", expand_hops=3)
