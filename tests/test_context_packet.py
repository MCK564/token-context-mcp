"""M6.3: context packet in ``inspect_symbol(view="full")`` (budget contract, determinism, filters, refs)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from packet_repo import REPO_ID, build_packet_repo
from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config
from token_context_mcp.index.runner import build_index
from token_context_mcp.retrieve import packet as packet_mod
from token_context_mcp.retrieve.packet import (
    DEFAULT_SHARES,
    Neighbor,
    PacketInputs,
    build_context_packet,
    payload_tokens,
)
from token_context_mcp.retrieve.serialization import ResultFinalizer
from token_context_mcp.retrieve.service import RetrievalService, _compact_symbol_ref, _payload_tokens
from token_context_mcp.retrieve.token_budget import estimate_tokens
from token_context_mcp.retrieve.workflows import CompositeWorkflowEngine
from token_context_mcp.server import _result

BUDGETS = [1024, 2048, 4096]


def _long_module(n_lines: int = 330) -> str:
    lines = [
        '"""A module with a >300 line function."""',
        "from __future__ import annotations",
        "",
        "from pkg.util import helper_short, helper_three, helper_two",
        "",
        "",
        "def mega(values: list[int], flag: bool = False) -> int:",
        '    """Very long function."""',
        "    total = 0",
    ]
    for i in range(n_lines):
        if i == 90:
            lines.append("    total = helper_short(total)")
        elif i == 200:
            lines.append("    label = helper_two(flag)")
        elif i == 300:
            lines.append("    text = helper_three(label)")
        else:
            lines.append(f"    total += values[{i % 3}] * {i}  # filler {i}")
    lines.append("    return total + len(text)")
    return "\n".join(lines) + "\n"


def _write_extra(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory):
    tmp = tmp_path_factory.mktemp("packet")
    cfg = build_packet_repo(tmp)
    root = tmp / "packet-src"
    _write_extra(root, {"pkg/mega.py": _long_module()})
    repo = RepositoryConfig(repo_id=REPO_ID, root=root.resolve())
    build_index(repo, cfg.parent / "indexes", network_policy="declared-deny-not-enforced")
    service = RetrievalService(load_config(cfg), cfg)
    return service, CompositeWorkflowEngine(service)


def _full(engine: CompositeWorkflowEngine, query: str, budget: int = 4096) -> dict:
    res = engine.inspect_symbol(REPO_ID, query=query, view="full", budget_tokens=budget)
    assert res["data"]["status"] == "resolved", res
    return res


def _rows(packet: dict) -> dict[str, list[str]]:
    return {
        "callees": [r[0] for r in packet["callees"]],
        "callers": [r[0] for r in packet["callers"]],
        "more": [r[0] for r in packet["more"]],
        "methods": [r[0] for r in packet["context"]["class_methods"]],
    }


# ---------------------------------------------------------------- contract shape

def test_method_target_has_all_five_sections(env) -> None:
    _service, engine = env
    res = _full(engine, "Service.run")
    data = res["data"]
    assert "content" not in data and "relationships" not in data
    packet = data["packet"]
    assert set(packet) == {"target", "callees", "callers", "more", "context", "files", "used_tokens", "omitted"}
    assert packet["target"]["span"] == "pkg/service.py:26-31"
    assert "helper_two(flag)" in packet["target"]["content"]
    assert packet["target"]["truncated_lines"] is None
    assert [r[2] for r in packet["callees"]] == [
        "def add(self, name: str) -> int",
        "def helper_two(flag: bool = False) -> str",
        "def summary(self) -> str",
    ]
    assert packet["callers"] and packet["callers"][0][1].startswith("tests/test_service.py:")
    assert packet["context"]["imports"] == ["from pkg.util import helper_short, helper_three, helper_two"]
    sibling_sigs = {r[2] for r in packet["context"]["class_methods"]}
    assert {"def __init__(self) -> None", "def clean(self, raw: str) -> str"} <= sibling_sigs
    assert "def run(self, names: list[str], flag: bool = False) -> str" not in sibling_sigs
    assert set(packet["files"]) == {"pkg/service.py", "pkg/util.py", "tests/test_service.py"}
    assert all(len(sha) == 12 for sha in packet["files"].values())
    assert set(packet["used_tokens"]) == {"target", "callees", "callers", "more", "context"}
    assert data["relationship_count"] == 4
    assert data["relationships_filtered"] == 0
    assert data["symbol"]["qualified_name"] == "Service.run"


def test_constructor_callee_shows_init_signature(env) -> None:
    _service, engine = env
    packet = _full(engine, "Service.add")["data"]["packet"]
    sigs = {row[2] for row in packet["callees"]}
    assert "def __init__(self, name: str, weight: int = 1) -> None" in sigs
    assert "class Item(Base)" not in sigs


def test_class_target_is_a_skeleton(env) -> None:
    _service, engine = env
    packet = _full(engine, "Item")["data"]["packet"]
    content = packet["target"]["content"]
    assert content.splitlines()[0].endswith("class Item(Base)")
    assert "def __init__(self, name: str, weight: int = 1) -> None" in content
    assert "return f" not in content  # bodies are not part of a class skeleton
    assert packet["context"]["class_methods"] == []


def test_low_confidence_and_stub_edges_never_appear(tmp_path: Path) -> None:
    root = tmp_path / "relsrc"
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
        "",
        "def decoy_caller(obj):",
        "    return obj.get('z')",
    ]
    (root / "mod.py").write_text("\n".join(lines), encoding="utf-8")
    cfg = tmp_path / "cfg" / "repos.toml"
    repo = RepositoryConfig(repo_id="rel", root=root.resolve())
    save_config(cfg, AppConfig(repositories={"rel": repo}, server=ServerConfig()))
    build_index(repo, cfg.parent / "indexes", network_policy="declared-deny-not-enforced")
    engine = CompositeWorkflowEngine(RetrievalService(load_config(cfg), cfg))

    packet = engine.inspect_symbol("rel", query="target_fn", view="full", budget_tokens=2048)["data"]["packet"]
    assert [row[2] for row in packet["callees"]] == ["def local_push_ppr(x)"]
    assert packet["more"] == []
    text = json.dumps([packet["callees"], packet["callers"], packet["more"], packet["context"]])
    assert "append" not in text and "Decoy" not in text and "get" not in text

    decoy = engine.inspect_symbol("rel", query="Decoy.get", view="full", budget_tokens=2048)["data"]
    text = json.dumps([decoy["packet"][k] for k in ("callees", "callers", "more")])
    assert "decoy_caller" not in text and "target_fn" not in text
    assert decoy["relationship_count"] == 0
    full = engine.inspect_symbol("rel", query="target_fn", view="full", budget_tokens=2048)["data"]
    assert full["relationship_count"] == 1
    assert full["relationships_filtered"] == 2  # ambiguous `get` + stub `append`, same meaning as E14


# ---------------------------------------------------------------- budget contract

@pytest.mark.parametrize("budget", BUDGETS)
@pytest.mark.parametrize("query", ["Service.run", "process_batch", "mega", "Item", "helper_short"])
def test_payload_fits_effective_budget_and_wire_modes(env, query: str, budget: int) -> None:
    service, engine = env
    res = _full(engine, query, budget)
    assert _payload_tokens(res) <= service._effective_budget(budget)
    assert res["budget"]["requested_tokens"] == budget
    assert res["budget"]["estimated_tokens"] == _payload_tokens(res)  # measured, not clamped

    structured = _result(res, ResultFinalizer(output_mode="structured"))
    assert estimate_tokens(json.dumps(structured.model_dump(mode="json", exclude_none=True), ensure_ascii=False)) <= budget
    text = _result(res, ResultFinalizer(output_mode="text"))
    assert estimate_tokens(text.content[0].text) <= budget


def test_long_target_truncation_keeps_signature_docstring_and_call_lines(env) -> None:
    _service, engine = env
    res = _full(engine, "mega", 1024)
    packet = res["data"]["packet"]
    target = packet["target"]
    assert res["truncated"] is True
    assert target["truncated_lines"]
    lines = target["content"].splitlines()
    first = int(target["span"].rsplit(":", 1)[1].split("-")[0])
    assert lines[0].startswith(f"{first}: def mega(")
    assert '"""Very long function."""' in lines[1]
    body = target["content"]
    for call in ("helper_short(total)", "helper_two(flag)", "helper_three(label)"):
        assert call in body, call
    # every line of the span is either shown or inside exactly one omitted range
    end = int(target["span"].rsplit("-", 1)[1])
    shown = {int(line.split(":", 1)[0]) for line in lines}
    omitted: set[int] = set()
    for lo, hi in target["truncated_lines"]:
        assert lo <= hi
        assert not (set(range(lo, hi + 1)) & shown)
        omitted |= set(range(lo, hi + 1))
    assert shown | omitted <= set(range(first, end + 1))
    assert all(sha for sha in packet["files"].values())


def test_full_body_when_it_fits(env) -> None:
    _service, engine = env
    packet = _full(engine, "process_batch", 4096)["data"]["packet"]
    assert packet["target"]["truncated_lines"] is None
    assert packet["target"]["content"].startswith("def process_batch(")
    assert packet["target"]["content"].rstrip().endswith("return total + len(text)")


def _synthetic_inputs(n_target: int, n_callees: int, n_callers: int = 0) -> PacketInputs:
    lines = tuple(["def target(a, b):"] + [f"    x{i} = a + {i}" for i in range(n_target - 1)])
    callees = tuple(
        Neighbor(f"c{i:07x}", f"src/lib{i}.py", 10 + i, f"f c{i}", f"def callee_{i}(alpha: int, beta: str = 'x') -> dict", 0.9, "callee")
        for i in range(n_callees)
    )
    callers = tuple(
        Neighbor(f"k{i:07x}", f"src/use{i}.py", 5 + i, f"f k{i}", f"def caller_{i}(z: int) -> None", 0.8, "caller")
        for i in range(n_callers)
    )
    return PacketInputs(
        target_ref="tttttttt",
        target_symbol_id="python:src/t.py:target:0",
        path="src/t.py",
        qualified_name="target",
        kind="function",
        start_line=1,
        end_line=n_target,
        source_lines=lines,
        call_lines=tuple(range(3, 3 + min(n_callees, 5))),
        callees=callees,
        callers=callers,
        file_sha={"src/t.py": "a" * 12},
    )


def test_unused_target_share_carries_over_to_callees() -> None:
    inputs = _synthetic_inputs(n_target=6, n_callees=60)
    budget = 1024
    packet = build_context_packet(inputs, budget)
    row_cost = len(json.dumps(inputs.callees[0].signature_row(), sort_keys=True, ensure_ascii=False).encode()) + 2
    own_share_rows = int(budget * 4 * DEFAULT_SHARES["callees"] // row_cost)
    assert len(packet["callees"]) > own_share_rows
    assert payload_tokens(packet) <= budget
    # what did not fit as a signature is still reachable as a compact ref
    assert len(packet["callees"]) + len(packet["more"]) + packet["omitted"]["more"] == 60


def test_second_pass_returns_leftover_budget_to_a_cut_target() -> None:
    inputs = _synthetic_inputs(n_target=400, n_callees=1)
    budget = 2048
    packet = build_context_packet(inputs, budget)
    assert packet["target"]["truncated_lines"]
    target_share_tokens = DEFAULT_SHARES["target"] * budget
    assert packet["used_tokens"]["target"] > target_share_tokens * 1.5
    assert payload_tokens(packet) <= budget


def test_callers_are_capped_and_the_rest_moves_to_more() -> None:
    inputs = _synthetic_inputs(n_target=8, n_callees=2, n_callers=20)
    packet = build_context_packet(inputs, 8192, callers_k=5)
    assert len(packet["callers"]) == 5
    assert [r[3] for r in packet["more"]].count("caller") == 15
    default = build_context_packet(inputs, 8192)
    assert len(default["callers"]) == min(20, packet_mod.CALLERS_K)


def test_more_rows_label_tests() -> None:
    inputs = _synthetic_inputs(n_target=5, n_callees=0, n_callers=0)
    extra = tuple(
        Neighbor(f"t{i:07x}", f"tests/test_{i}.py", i + 1, f"f test_{i}", None, 0.9, "caller") for i in range(3)
    )
    inputs = PacketInputs(**{**inputs.__dict__, "callers": extra})
    packet = build_context_packet(inputs, 4096, callers_k=1)
    assert [r[3] for r in packet["more"]] == ["test", "test"]


# ---------------------------------------------------------------- determinism, refs, staleness

def test_repeat_call_is_byte_identical(env) -> None:
    _service, engine = env
    for query in ("Service.run", "mega", "Item"):
        a = engine.inspect_symbol(REPO_ID, query=query, view="full", budget_tokens=1024)
        b = engine.inspect_symbol(REPO_ID, query=query, view="full", budget_tokens=1024)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_refs_resolve_through_get_symbol_context_and_impact_slice(env) -> None:
    service, engine = env
    packet = _full(engine, "Service.run")["data"]["packet"]
    refs = _rows(packet)
    assert refs["callees"] and refs["methods"]
    for ref in [*refs["callees"], *refs["callers"], *refs["methods"], packet["target"]["symbol_id"]]:
        ctx = service.symbol_context(REPO_ID, symbol_id=ref, depth=0, include_body=False, max_tokens=1024)
        root = ctx["data"]["symbols"][0]["symbol"]["symbol_id"]
        assert _compact_symbol_ref(root) == ref
        impact = service.impact_slice(REPO_ID, symbol_id=ref, max_tokens=1024)
        assert impact["data"]["root_symbol_id"] == root


def test_packet_token_measure_matches_service_measure() -> None:
    sample = {"a": ["é", 1, None], "b": "x" * 33}
    assert payload_tokens(sample) == _payload_tokens(sample)


def test_stale_neighbour_file_keeps_ref_but_drops_signature(tmp_path: Path) -> None:
    cfg = build_packet_repo(tmp_path)
    util = tmp_path / "packet-src" / "pkg" / "util.py"
    service = RetrievalService(load_config(cfg), cfg)
    engine = CompositeWorkflowEngine(service)
    fresh = engine.inspect_symbol(REPO_ID, query="Service.run", view="full", budget_tokens=2048)
    assert "stale_content_unavailable" not in fresh["warnings"]
    time.sleep(0.02)
    util.write_text(util.read_text(encoding="utf-8") + "\n# edited after indexing\n", encoding="utf-8")
    os.utime(util, None)
    service = RetrievalService(load_config(cfg), cfg)
    engine = CompositeWorkflowEngine(service)
    res = engine.inspect_symbol(REPO_ID, query="Service.run", view="full", budget_tokens=2048)
    assert "stale_content_unavailable" in res["warnings"]
    row = next(r for r in res["data"]["packet"]["callees"] if r[1].startswith("pkg/util.py"))
    assert row[0] and row[2] is None
    other = next(r for r in res["data"]["packet"]["callees"] if r[1].startswith("pkg/service.py"))
    assert other[2]


def test_minimal_and_normal_views_do_not_contain_a_packet(env) -> None:
    _service, engine = env
    for view in ("minimal", "normal"):
        res = engine.inspect_symbol(REPO_ID, query="Service.run", view=view, budget_tokens=2048)
        assert "packet" not in res["data"]
        assert "relationships" in res["data"]


def test_tiny_budget_still_returns_a_well_formed_response(env) -> None:
    _service, engine = env
    res = engine.inspect_symbol(REPO_ID, query="mega", view="full", budget_tokens=256)
    assert res["data"]["status"] == "resolved"
    assert res["truncated"] is True
    assert set(res["data"]["packet"]) >= {"target", "callees", "callers", "more", "context", "files"}
