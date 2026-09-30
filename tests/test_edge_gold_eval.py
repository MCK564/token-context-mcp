"""Tests for evals/edge_gold_eval.py and Rule 17 held-out guard."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))

import edge_gold_eval as ege  # noqa: E402
from guard import check_heldout_guard  # noqa: E402
from token_context_mcp.index.sqlite_store import SQLiteStore  # noqa: E402
from token_context_mcp.models import EdgeRecord, FileRecord, SymbolRecord  # noqa: E402


def test_guard_passes_for_dev_role():
    # Dev role must never trigger the guard
    check_heldout_guard("dev")


def test_guard_bypassed_with_allow_baseline_code(tmp_path: Path):
    fake_baseline = tmp_path / "baseline_code"
    fake_baseline.mkdir()
    # Should succeed because path exists
    check_heldout_guard("heldout", allow_baseline_code=fake_baseline)

    # Should fail if path does not exist
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        check_heldout_guard("heldout", allow_baseline_code=non_existent)


def test_guard_fails_when_m12_freeze_tag_missing():
    # In current state, m12-freeze tag does not exist
    with pytest.raises(RuntimeError, match="Rule 17 violation.*m12-freeze.*does not exist"):
        check_heldout_guard("heldout")


def test_guard_with_mocked_git_success_and_diff(monkeypatch):
    def mock_run(cmd, **kwargs):
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="sha123\n")
        if "diff" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    # Should pass when tag exists and diff is empty
    check_heldout_guard("heldout")

    # Should fail when diff is non-empty
    def mock_run_with_diff(cmd, **kwargs):
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="sha123\n")
        if "diff" in cmd:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="diff --git a/src b/src\n+new line")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run_with_diff)
    with pytest.raises(RuntimeError, match="Rule 17 violation.*diff against 'm12-freeze' is not empty"):
        check_heldout_guard("heldout")


def test_callee_matches_logic():
    assert ege.callee_matches("foo", "foo")
    assert ege.callee_matches("obj.foo", "foo")
    assert ege.callee_matches("obj.foo()", "foo")
    assert ege.callee_matches("ptr->bar", "bar")
    assert ege.callee_matches("new Service()", "Service")
    assert not ege.callee_matches("obj.bar", "foo")
    assert not ege.callee_matches("", "foo")
    assert not ege.callee_matches("foo", "")


def test_target_matches_logic():
    sym = SymbolRecord(
        symbol_id="python:app.py:Service.run:123",
        path="app.py",
        name="run",
        qualified_name="Service.run",
        kind="method",
        signature="def run(self)",
        start_line=10,
        end_line=20,
        start_byte=100,
        end_byte=200,
        body_start_byte=120,
        body_end_byte=200,
        is_private=False,
    )
    sym_overload = SymbolRecord(
        symbol_id="csharp:lib.cs:Parser.Parse:456",
        path="lib.cs",
        name="Parse",
        qualified_name="Parser.Parse(string)",
        kind="method",
        signature="void Parse(string text)",
        start_line=15,
        end_line=25,
        start_byte=150,
        end_byte=250,
        body_start_byte=170,
        body_end_byte=250,
        is_private=False,
    )
    symbols = {sym.symbol_id: sym, sym_overload.symbol_id: sym_overload}

    edge1 = EdgeRecord(
        source_symbol_id="s1",
        target_symbol_id=sym.symbol_id,
        target_name="run",
        edge_kind="call",
        status="resolved",
        backend="ast",
        confidence=0.9,
        source_path="main.py",
        source_line=5,
        evidence=["ast_call", "scope:same_file"],
    )
    assert ege.target_matches(edge1, {"path": "app.py", "qualified_name": "Service.run"}, symbols)
    assert not ege.target_matches(edge1, {"path": "other.py", "qualified_name": "Service.run"}, symbols)
    assert not ege.target_matches(edge1, {"path": "app.py", "qualified_name": "Service.other"}, symbols)

    edge2 = EdgeRecord(
        source_symbol_id="s2",
        target_symbol_id=sym_overload.symbol_id,
        target_name="Parse",
        edge_kind="call",
        status="resolved",
        backend="ast",
        confidence=0.8,
        source_path="consumer.cs",
        source_line=12,
        evidence=["ast_call", "scope:import_match"],
    )
    # Common qualified name without overload arguments should match
    assert ege.target_matches(edge2, {"path": "lib.cs", "qualified_name": "Parser.Parse"}, symbols)


@pytest.fixture
def fake_repo_environment(tmp_path: Path):
    db_path = tmp_path / "indexes" / "test-repo.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db_path)

    # 1. Initialize and write snapshot
    store.initialize()
    file_main = FileRecord("pkg/main.py", 100, 1000, "sha_main", "python", "ok", [])
    file_a = FileRecord("pkg/a.py", 50, 500, "sha_a", "python", "ok", [])
    file_b = FileRecord("pkg/b.py", 50, 500, "sha_b", "python", "ok", [])
    file_c = FileRecord("pkg/c.py", 50, 500, "sha_c", "python", "ok", [])

    # 2. Symbols
    sym_a = SymbolRecord("s_a", "pkg/a.py", "func_a", "pkg.a.func_a", "function", "def func_a()", 1, 5, 0, 50, None, None, False)
    sym_b = SymbolRecord("s_b", "pkg/b.py", "func_b", "pkg.b.func_b", "function", "def func_b()", 1, 5, 0, 50, None, None, False)
    sym_c = SymbolRecord("s_c", "pkg/c.py", "func_c", "pkg.c.func_c", "function", "def func_c()", 1, 5, 0, 50, None, None, False)

    # 3. Edges:
    # - Line 10: call func_a, resolved, conf=0.9, same_file
    # - Line 20: call func_b, resolved, conf=0.8, import_match
    # - Line 30: call func_x, ambiguous, conf=0.1, unresolved_receiver
    # - Line 40: call func_c, resolved, conf=0.7, global (FP!)
    e1 = EdgeRecord("src1", "s_a", "func_a", "call", "resolved", "ast", 0.9, "pkg/main.py", 10, ["ast_call", "scope:same_file"])
    e2 = EdgeRecord("src2", "s_b", "func_b", "call", "resolved", "ast", 0.8, "pkg/main.py", 20, ["ast_call", "scope:import_match"])
    e3 = EdgeRecord("src3", None, "func_x", "call", "ambiguous", "ast", 0.1, "pkg/main.py", 30, ["ast_call", "scope:unresolved_receiver"])
    e4 = EdgeRecord("src4", "s_c", "func_c", "call", "resolved", "ast", 0.7, "pkg/main.py", 40, ["ast_call", "scope:global"])

    store.write_snapshot(
        metadata={
            "index_run_id": "run_test",
            "repo_id": "test-repo",
            "commit_sha": "abcdef",
            "tag": None,
            "file_count": 4,
            "symbol_count": 3,
            "edge_count": 4,
            "manifest_fingerprint": "fp123",
            "created_at": "2026-09-30T00:00:00Z",
        },
        files=[file_main, file_a, file_b, file_c],
        symbols=[sym_a, sym_b, sym_c],
        edges=[e1, e2, e3, e4],
        imports={},
    )

    # 4. Config
    config_path = tmp_path / "repos.toml"
    config_path.write_text(f"""
[server]
output_mode = "text"

[repositories.test-repo]
root = "{tmp_path.as_posix()}"
index_path = "{db_path.as_posix()}"
""", encoding="utf-8")

    # 5. Gold set
    gold_data = {
        "repo_id": "test-repo",
        "reviewed": True,
        "sites": [
            {
                "path": "pkg/main.py",
                "line": 10,
                "col": 5,
                "callee_text": "func_a",
                "expected": {"path": "pkg/a.py", "qualified_name": "pkg.a.func_a"},
                "reason": "Internal call to func_a",
            },
            {
                "path": "pkg/main.py",
                "line": 20,
                "col": 5,
                "callee_text": "b.func_b",
                "expected": {"path": "pkg/b.py", "qualified_name": "pkg.b.func_b"},
                "reason": "Internal call to func_b",
            },
            {
                "path": "pkg/main.py",
                "line": 30,
                "col": 5,
                "callee_text": "x.func_x",
                "expected": {"path": "pkg/x.py", "qualified_name": "pkg.x.func_x"},
                "reason": "Internal call to missing func_x",
            },
            {
                "path": "pkg/main.py",
                "line": 40,
                "col": 5,
                "callee_text": "ext.func_c",
                "expected": "external",
                "reason": "Call to external library function",
            },
        ],
    }
    gold_path = tmp_path / "edge_gold.json"
    gold_path.write_text(json.dumps(gold_data), encoding="utf-8")

    return config_path, gold_path, tmp_path


def test_edge_gold_eval_calculation(fake_repo_environment):
    config_path, gold_path, tmp_path = fake_repo_environment
    gold_data = json.loads(gold_path.read_text(encoding="utf-8"))

    report = ege.run_edge_gold_evaluation(
        repo_id="test-repo",
        gold_data=gold_data,
        config_path=config_path,
        tag="test_run",
        role="dev",
    )

    # 4 call sites total: 3 internal, 1 external
    assert report["total_call_sites"] == 4
    assert report["internal_call_sites"] == 3

    # Recall: 3 internal targets (func_a, func_b, func_x).
    # func_a (line 10) -> resolved correctly (hit)
    # func_b (line 20) -> resolved correctly (hit)
    # func_x (line 30) -> ambiguous (miss)
    # Recall = 2 / 3 = 0.6667
    assert report["recall"]["total_internal_sites"] == 3
    assert report["recall"]["resolved_correctly"] == 2
    assert report["recall"]["recall"] == pytest.approx(0.6667, abs=1e-4)

    # Precision on conf >= 0.6:
    # Line 10 (conf=0.9): resolved to func_a -> CORRECT
    # Line 20 (conf=0.8): resolved to func_b -> CORRECT
    # Line 30 (conf=0.1): ignored (< 0.6)
    # Line 40 (conf=0.7): expected 'external', but resolved to func_c -> FALSE POSITIVE
    # Total ge 0.6 = 3, correct = 2, FP = 1
    # Precision = 2 / 3 = 0.6667
    assert report["precision"]["total_edges_ge_06"] == 3
    assert report["precision"]["correct_edges"] == 2
    assert report["precision"]["false_positives"] == 1
    assert report["precision"]["precision"] == pytest.approx(0.6667, abs=1e-4)

    # Scope breakdown:
    # same_file: 1/1 = 1.0
    # import_match: 1/1 = 1.0
    # global: 0/1 = 0.0 (FP)
    scopes = report["scope_breakdown"]
    assert scopes["same_file"]["precision"] == 1.0
    assert scopes["import_match"]["precision"] == 1.0
    assert scopes["global"]["precision"] == 0.0
    assert scopes["global"]["fp_ge_06"] == 1


def test_edge_gold_eval_cli(fake_repo_environment, monkeypatch):
    config_path, gold_path, tmp_path = fake_repo_environment
    out_json = tmp_path / "out_report.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "edge_gold_eval.py",
            "--gold", str(gold_path),
            "--config", str(config_path),
            "--repo-id", "test-repo",
            "--role", "dev",
            "--output", str(out_json),
        ],
    )
    ret = ege.main()
    assert ret == 0
    assert out_json.exists()
    saved = json.loads(out_json.read_text(encoding="utf-8"))
    assert saved["repo_id"] == "test-repo"
    assert saved["precision"]["total_edges_ge_06"] == 3
