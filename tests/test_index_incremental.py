"""M7: incremental / parallel / commit-aware indexing.

I1  (equivalence)   an incremental index equals a from-scratch index of the same tree, after each of five chained
                    edits (edit body, rename with cross-file caller, add file, delete file, change import);
I2  (snapshot safety) is covered by tests/test_versioned_snapshots.py and re-checked here for the delta writer.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import index_pool_helpers as helpers  # noqa: E402
from evals import index_equivalence as ie  # noqa: E402
from token_context_mcp.config import RepositoryConfig  # noqa: E402
from token_context_mcp.index import runner  # noqa: E402
from token_context_mcp.index.runner import build_index, database_path  # noqa: E402

NETWORK = "declared-deny-not-enforced"


def make_tree(root: Path, modules: int = 40) -> Path:
    """A small repository with cross-file calls, inheritance, a Protocol + registry and a non-code file."""
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n[project.scripts]\ndemo = "pkg.mod_00:main"\n', encoding="utf-8")
    (pkg / "base.py").write_text(
        "class Base:\n    def run(self) -> int:\n        return self.helper()\n\n    def helper(self) -> int:\n        return 1\n\n\n"
        "class Child(Base):\n    def go(self) -> int:\n        return self.run() + 1\n",
        encoding="utf-8",
    )
    (pkg / "frontends.py").write_text(
        "from typing import Protocol\n\n\nclass Frontend(Protocol):\n    def render(self) -> str: ...\n\n\n"
        "class HtmlFrontend:\n    def render(self) -> str:\n        return 'html'\n\n\n"
        "def register(name, impl):\n    return (name, impl)\n\n\nregister('html', HtmlFrontend)\n",
        encoding="utf-8",
    )
    for index in range(modules):
        previous = f"from pkg.mod_{index - 1:02d} import func_{index - 1:02d}\n" if index else "from pkg.base import Child\n"
        call = f"    return func_{index - 1:02d}(value) + 1\n" if index else "    return Child().go() + value\n"
        (pkg / f"mod_{index:02d}.py").write_text(
            previous
            + f"\n\nclass Service_{index:02d}:\n    def get(self, key):\n        return key\n\n    def run(self):\n        return self.get('x')\n\n\n"
            + f"def func_{index:02d}(value):\n"
            + call
            + ("\n\ndef main():\n    return func_00(1)\n" if index == 0 else ""),
            encoding="utf-8",
        )
    return root


def repo(root: Path, repo_id: str = "demo", **kwargs) -> RepositoryConfig:
    return RepositoryConfig(repo_id=repo_id, root=root.resolve(), **kwargs)


def index(root: Path, out: Path, **kwargs):
    return build_index(repo(root), out, network_policy=NETWORK, **kwargs)


def age(root: Path) -> None:
    ie.age_files(root)


def db_rows(out: Path, sql: str, repo_id: str = "demo"):
    connection = sqlite3.connect(f"file:{database_path(out, repo_id).as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def _deterministic_edges():
    """The per-file edge budget is deterministic (work units); switched off so I1 does not depend on its value."""
    with ie.deterministic_edges():
        yield


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = make_tree(tmp_path / "tree")
    age(root)
    return root


# ------------------------------------------------------------------------------------------- I1


def test_chained_incremental_equals_full(tmp_path: Path) -> None:
    source = make_tree(tmp_path / "source")
    report = ie.run_chain(source, "demo", tmp_path / "work")
    assert report["all_equivalent"], [s for s in report["steps"] if s["problems"]]
    for step in report["steps"][1:]:
        assert step["parse_source_calls"] == step["expected_parse_source_calls"], step
    # the one-file steps really are incremental (nothing else was parsed)
    assert [s["parse_source_calls"] for s in report["steps"]] == [report["steps"][0]["parse_source_calls"], 1, 2, 1, 0, 1]


def test_chained_incremental_equals_full_with_verify_hashes(tmp_path: Path) -> None:
    source = make_tree(tmp_path / "source", modules=12)
    report = ie.run_chain(source, "demo", tmp_path / "work", verify_hashes=True)
    assert report["all_equivalent"], [s for s in report["steps"] if s["problems"]]


def test_equivalence_tool_detects_a_difference(tmp_path: Path, tree: Path) -> None:
    full = tmp_path / "a"
    index(tree, full)
    other = tmp_path / "b"
    (tree / "pkg" / "mod_03.py").write_text("def func_03(value):\n    return 0\n", encoding="utf-8")
    index(tree, other)
    problems = ie.compare_dumps(ie.dump_snapshot(database_path(full, "demo")), ie.dump_snapshot(database_path(other, "demo")))
    assert "symbols" in problems and "source_bodies" in problems


# ------------------------------------------------------------------------------------------- skipping


def test_noop_parses_nothing_and_reads_no_source(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "idx"
    first = index(tree, out)
    assert first["parse_source_calls"] == first["files_reparsed"] > 0
    calls: list[str] = []
    real = runner.parse_source
    monkeypatch.setattr(runner, "parse_source", lambda path, raw, language: calls.append(path) or real(path, raw, language))
    read_paths: list[str] = []
    real_read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: read_paths.append(self.name) or real_read(self))
    second = index(tree, out)
    assert calls == [] and second["parse_source_calls"] == 0 and second["files_reparsed"] == 0
    assert second["files_stat_skipped"] == second["files_indexed"] and second["files_hashed"] == 0
    # the only source read is the lazy one of a file that defines register()/get_frontend (structural roles)
    assert set(read_paths) <= {"frontends.py"}
    assert second["incremental"] is True and second["write_mode"] == "delta"


def test_one_changed_file_is_the_only_parse_call(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    target = tree / "pkg" / "mod_07.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n\ndef extra():\n    return 7\n", encoding="utf-8")
    calls: list[str] = []
    real = runner.parse_source
    monkeypatch.setattr(runner, "parse_source", lambda path, raw, language: calls.append(path) or real(path, raw, language))
    manifest = index(tree, out)
    assert calls == ["pkg/mod_07.py"] and manifest["parse_source_calls"] == 1
    assert db_rows(out, "SELECT COUNT(*) FROM symbols WHERE name = 'extra'") == [(1,)]


def test_touched_but_identical_file_is_hashed_not_parsed(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    target = tree / "pkg" / "mod_05.py"
    os.utime(target, None)  # new mtime, same bytes
    manifest = index(tree, out)
    assert manifest["parse_source_calls"] == 0 and manifest["files_hashed"] == 1 and manifest["files_reparsed"] == 0
    assert db_rows(out, "SELECT mtime_ns FROM files WHERE path = 'pkg/mod_05.py'")[0][0] == target.stat().st_mtime_ns


def test_non_code_change_updates_hash_without_parsing(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    (tree / "README.md").write_bytes(b"# changed\n")
    manifest = index(tree, out)
    assert manifest["parse_source_calls"] == 0 and manifest["files_hashed"] == 1
    sha = db_rows(out, "SELECT sha256 FROM files WHERE path = 'README.md'")[0][0]
    assert sha == runner.sha256_bytes(b"# changed\n")


def test_deleted_file_disappears_from_every_table(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    (tree / "pkg" / "mod_09.py").unlink()
    index(tree, out)
    for sql in (
        "SELECT COUNT(*) FROM files WHERE path = 'pkg/mod_09.py'",
        "SELECT COUNT(*) FROM symbols WHERE path = 'pkg/mod_09.py'",
        "SELECT COUNT(*) FROM symbol_fts WHERE path = 'pkg/mod_09.py'",
        "SELECT COUNT(*) FROM symbol_bodies WHERE path = 'pkg/mod_09.py'",
        "SELECT COUNT(*) FROM source_bodies WHERE path = 'pkg/mod_09.py'",
        "SELECT COUNT(*) FROM file_parse_artifacts WHERE path = 'pkg/mod_09.py'",
        "SELECT COUNT(*) FROM edges WHERE source_path = 'pkg/mod_09.py'",
    ):
        assert db_rows(out, sql) == [(0,)], sql


def test_oversized_file_is_skipped_by_stat(tmp_path: Path, tree: Path) -> None:
    (tree / "big.py").write_text("x = 1\n" * 400, encoding="utf-8")
    manifest = build_index(repo(tree, max_file_bytes=1000), tmp_path / "idx", network_policy=NETWORK)
    assert db_rows(tmp_path / "idx", "SELECT COUNT(*) FROM files WHERE path = 'big.py'") == [(0,)]
    assert manifest["files_skipped"] >= 1


# ------------------------------------------------------------------------------------------- racy mtimes


def _same_size_edit_keeping_mtime(path: Path) -> None:
    stat = path.stat()
    text = path.read_text(encoding="utf-8")
    edited = text.replace("return key", "return kez", 1)
    assert edited != text and len(edited) == len(text)
    path.write_text(edited, encoding="utf-8")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def test_racy_timestamp_forces_a_rehash(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "tree")  # NOT aged: every mtime is inside the racy window of the first scan
    out = tmp_path / "idx"
    index(tree, out)
    target = tree / "pkg" / "mod_04.py"
    _same_size_edit_keeping_mtime(target)  # same size, same mtime_ns, different bytes
    manifest = index(tree, out)
    assert manifest["files_reparsed"] == 1 and manifest["parse_source_calls"] == 1
    assert "kez" in db_rows(out, "SELECT body FROM source_bodies WHERE path = 'pkg/mod_04.py'")[0][0]


def test_old_timestamp_is_trusted_unless_verify_hashes(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    target = tree / "pkg" / "mod_04.py"
    _same_size_edit_keeping_mtime(target)
    trusted = index(tree, out)
    assert trusted["parse_source_calls"] == 0  # documented limitation of (size, mtime_ns)
    verified = index(tree, out, verify_hashes=True)
    assert verified["parse_source_calls"] == 1 and verified["files_hashed"] == verified["files_indexed"]
    assert "kez" in db_rows(out, "SELECT body FROM source_bodies WHERE path = 'pkg/mod_04.py'")[0][0]


# ------------------------------------------------------------------------------------------- previous snapshot handling


def test_previous_snapshot_without_artifacts_is_rebuilt(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    first = index(tree, out)
    connection = sqlite3.connect(database_path(out, "demo"))
    connection.execute("UPDATE metadata SET value = '\"2.3\"' WHERE key = 'index_schema_version'")
    connection.commit()
    connection.close()
    second = index(tree, out)
    assert second["incremental"] is False and second["parse_source_calls"] == first["parse_source_calls"]
    assert second["index_schema_version"] == "2.4"


def test_other_repository_root_is_not_reused(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    clone = tmp_path / "clone"
    shutil.copytree(tree, clone)
    manifest = index(clone, out)
    assert manifest["incremental"] is False


def test_artifact_version_bump_reparses_everything(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "idx"
    first = index(tree, out)
    monkeypatch.setattr(runner, "PARSER_ARTIFACT_VERSION", runner.PARSER_ARTIFACT_VERSION + 1)
    second = index(tree, out)
    assert second["incremental"] is False and second["parse_source_calls"] == first["parse_source_calls"]


@pytest.mark.parametrize("key", ["FTS_BUILDER_VERSION", "RESOLVER_VERSION"])
def test_builder_version_bump_rebuilds_everything(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    """Rule 20: FTS builder and edge resolver changes carry their own version key, and a changed key is a full rebuild."""
    out = tmp_path / "idx"
    first = index(tree, out)
    monkeypatch.setattr(runner, key, getattr(runner, key) + 1)
    second = index(tree, out)
    assert second["incremental"] is False and second["parse_source_calls"] == first["parse_source_calls"]
    assert second[key.lower()] == getattr(runner, key)


def test_i1_holds_across_a_version_bump(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule 20 (I1 across versions): full build with the old keys, then an incremental run with the new keys, equals a
    from-scratch build with the new keys, table by table."""
    upgraded = tmp_path / "upgraded"
    with monkeypatch.context() as old:
        old.setattr(runner, "FTS_BUILDER_VERSION", runner.FTS_BUILDER_VERSION - 1)
        old.setattr(runner, "RESOLVER_VERSION", runner.RESOLVER_VERSION - 1)
        index(tree, upgraded)
    (tree / "pkg" / "mod_05.py").write_text("def func_05(value):\n    return value * 2\n", encoding="utf-8")
    age(tree)
    index(tree, upgraded)  # current keys: the old snapshot must not be reused
    fresh = tmp_path / "fresh"
    index(tree, fresh)
    problems = ie.compare_dumps(ie.dump_snapshot(database_path(upgraded, "demo")), ie.dump_snapshot(database_path(fresh, "demo")))
    assert not problems, problems


def test_parse_error_files_are_not_reparsed_every_run(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(path: str, raw: bytes, language: str):
        if path.endswith("mod_02.py"):
            raise runner.ParseError("boom")
        return real(path, raw, language)

    real = runner.parse_source
    monkeypatch.setattr(runner, "parse_source", failing)
    out = tmp_path / "idx"
    first = index(tree, out)
    assert "parse_error:pkg/mod_02.py" in first["warnings"]
    second = index(tree, out)
    assert second["parse_source_calls"] == 0 and second["files_reparsed"] == 0


def test_stale_role_is_not_carried_over(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    roles = db_rows(out, "SELECT roles_json FROM symbols WHERE name = 'HtmlFrontend'")[0][0]
    (tree / "pkg" / "frontends.py").write_text(
        (tree / "pkg" / "frontends.py").read_text(encoding="utf-8").replace("register('html', HtmlFrontend)", "pass"),
        encoding="utf-8",
    )
    index(tree, out)
    after = db_rows(out, "SELECT roles_json FROM symbols WHERE name = 'HtmlFrontend'")[0][0]
    assert "registry_wiring" in roles and "registry_wiring" not in after


# ------------------------------------------------------------------------------------------- edges (M7.5)


def test_body_edit_re_resolves_only_the_edited_file(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    target = tree / "pkg" / "mod_10.py"
    target.write_text(target.read_text(encoding="utf-8").replace("return func_09(value) + 1", "value = 2\n    return func_09(value) + 1"), encoding="utf-8")
    manifest = index(tree, out)
    report = manifest["edge_resolution"]
    assert report["mode"] == "scoped" and report["files_resolved"] == 1 and report["changed_names"] == 0
    # ids of the symbols after the edit moved, the reused edges must follow them
    ids = {row[0] for row in db_rows(out, "SELECT symbol_id FROM symbols")}
    for source, target_id in db_rows(out, "SELECT source_symbol_id, target_symbol_id FROM edges"):
        assert source in ids and (target_id is None or target_id in ids)


def test_inheritance_change_falls_back_to_full_resolution(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    (tree / "pkg" / "base.py").write_text(
        (tree / "pkg" / "base.py").read_text(encoding="utf-8").replace("class Child(Base):", "class Child:"), encoding="utf-8"
    )
    manifest = index(tree, out)
    assert manifest["edge_resolution"]["mode"] == "full"


# ------------------------------------------------------------------------------------------- write path


def test_delta_generations_are_capped(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "MAX_DELTA_GENERATIONS", 2)
    out = tmp_path / "idx"
    modes = [index(tree, out)["write_mode"] for _ in range(4)]
    assert modes == ["rewrite", "delta", "delta", "rewrite"]


def test_legacy_copy_is_a_hardlink_or_a_copy(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    current = database_path(out, "demo")
    legacy = out / "demo.sqlite"
    assert legacy.read_bytes() == current.read_bytes()
    if hasattr(os, "link"):
        assert os.path.samefile(legacy, current)
    monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("no hardlinks here")))
    (tree / "pkg" / "mod_01.py").write_text("def func_01(value):\n    return value\n", encoding="utf-8")
    index(tree, out)
    assert legacy.read_bytes() == database_path(out, "demo").read_bytes()
    assert not any(out.glob("*.tmp-*"))


def test_reader_of_previous_snapshot_is_undisturbed_by_a_delta_write(tree: Path, tmp_path: Path) -> None:
    out = tmp_path / "idx"
    index(tree, out)
    old_db = database_path(out, "demo")
    reader = sqlite3.connect(f"file:{old_db.as_posix()}?mode=ro", uri=True)
    before = reader.execute("SELECT COUNT(*), SUM(LENGTH(body)) FROM source_bodies").fetchone()
    (tree / "pkg" / "mod_02.py").write_text("def func_02(value):\n    return -value\n", encoding="utf-8")
    manifest = index(tree, out)
    assert manifest["write_mode"] == "delta" and database_path(out, "demo") != old_db
    assert reader.execute("SELECT COUNT(*), SUM(LENGTH(body)) FROM source_bodies").fetchone() == before
    assert reader.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    reader.close()
    fresh = sqlite3.connect(f"file:{database_path(out, 'demo').as_posix()}?mode=ro", uri=True)
    assert fresh.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    fresh.close()


# ------------------------------------------------------------------------------------------- roles / fts helpers


def test_own_body_matches_the_definition_on_nested_symbols() -> None:
    from token_context_mcp.parse.treesitter import parse_source

    source = (
        "import os\n\nclass A:\n    x = 1\n\n    def f(self):\n        def inner():\n            return 1\n        return inner()\n\n"
        "    def g(self):\n        return 2\n\n\ndef top():\n    return 3\n\nTAIL = 4\n"
    )
    parsed = parse_source("m.py", source.encode(), "python")
    rows = {row[3]: row[5] for row in runner._fts_rows("m.py", "python", source, parsed.symbols)}

    def reference(sym) -> str:  # the pre-M7 definition, verbatim
        lines = source.splitlines()
        child_lines: set[int] = set()
        for c in parsed.symbols:
            if c.symbol_id != sym.symbol_id and sym.start_line <= c.start_line and c.end_line <= sym.end_line:
                child_lines.update(range(c.start_line, c.end_line + 1))
        return "\n".join(lines[i] for i in range(sym.start_line - 1, min(sym.end_line, len(lines))) if (i + 1) not in child_lines)

    for sym in parsed.symbols:
        assert rows[sym.qualified_name] == reference(sym), sym.qualified_name
    lines = source.splitlines()
    covered = {i for s in parsed.symbols for i in range(s.start_line, s.end_line + 1)}
    assert rows["<module>"] == "\n".join(lines[i] for i in range(len(lines)) if (i + 1) not in covered)


# ------------------------------------------------------------------------------------------- process pool


def test_pool_result_equals_sequential(tree: Path, tmp_path: Path) -> None:
    sequential = tmp_path / "seq"
    parallel = tmp_path / "par"
    index(tree, sequential, workers=1)
    manifest = index(tree, parallel, workers=2, pool_min_files=1, pool_min_bytes=0)
    assert manifest["parse_mode"]["mode"] == "spawn-pool" and manifest["parse_mode"]["fallback"] is None
    assert not ie.compare_dumps(
        ie.dump_snapshot(database_path(sequential, "demo")), ie.dump_snapshot(database_path(parallel, "demo"))
    )


def test_small_batches_stay_in_process(tree: Path, tmp_path: Path) -> None:
    manifest = index(tree, tmp_path / "idx", workers=4)  # 43 files but far below PARSE_POOL_MIN_BYTES
    assert manifest["parse_mode"]["mode"] == "sequential"
    out = tmp_path / "idx"
    (tree / "pkg" / "mod_00.py").write_text("def func_00(value):\n    return value\n", encoding="utf-8")
    assert index(tree, out, workers=4, pool_min_bytes=0)["parse_mode"]["mode"] == "sequential"  # 1 file < 32


def test_pool_failure_falls_back_to_sequential(tree: Path) -> None:
    tasks = [(f"pkg/mod_{i:02d}.py", str(tree / "pkg" / f"mod_{i:02d}.py"), "python", 2_000_000, None) for i in range(8)]
    outcomes, report = runner._run_tasks(tasks, workers=2, worker_fn=helpers.die_in_child, pool_min_files=1)
    assert report["mode"] == "sequential-fallback" and report["fallback"]
    assert sorted(outcomes) == sorted(task[0] for task in tasks)
    assert all(outcome.kind == "parsed" for outcome in outcomes.values())


def test_unpicklable_worker_falls_back(tree: Path) -> None:
    tasks = [(f"pkg/mod_{i:02d}.py", str(tree / "pkg" / f"mod_{i:02d}.py"), "python", 2_000_000, None) for i in range(4)]
    outcomes, report = runner._run_tasks(tasks, workers=2, worker_fn=lambda task: runner._process_candidate(task), pool_min_files=1)
    assert report["mode"] == "sequential-fallback" and len(outcomes) == 4


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM cannot be caught on Windows; see SIGBREAK handling")
def test_cancelling_a_parallel_index_leaves_no_orphan_workers(tmp_path: Path) -> None:
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    script = tmp_path / "run_pool.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(TESTS_DIR)!r})\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "import index_pool_helpers as helpers\n"
        "from token_context_mcp.index import runner\n"
        "if __name__ == '__main__':\n"
        "    tasks = [(f'f{i}.py', 'x', 'python', 1, None) for i in range(40)]\n"
        "    runner._run_tasks(tasks, workers=2, worker_fn=helpers.sleepy_worker, pool_min_files=1)\n",
        encoding="utf-8",
    )
    env = dict(os.environ, TOKEN_CONTEXT_TEST_PID_DIR=str(pid_dir))
    proc = subprocess.Popen([sys.executable, str(script)], env=env, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + 60
        while len(list(pid_dir.glob("*.pid"))) < 2 and time.time() < deadline:
            time.sleep(0.2)
        pids = [int(p.stem) for p in pid_dir.glob("*.pid")]
        assert len(pids) >= 2, "workers did not start"
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
        gone_by = time.time() + 15
        alive = pids
        while alive and time.time() < gone_by:
            alive = [pid for pid in alive if helpers.pid_is_running(pid)]
            time.sleep(0.2)
        assert alive == [], f"orphan workers left: {alive}"
    finally:
        if proc.poll() is None:
            proc.kill()
        for pid in [int(p.stem) for p in pid_dir.glob("*.pid")]:
            if helpers.pid_is_running(pid):
                os.kill(pid, signal.SIGKILL)


def test_default_worker_count_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_CONTEXT_INDEX_WORKERS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert runner.default_worker_count() == 1
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    assert runner.default_worker_count() == 8
    monkeypatch.setenv("TOKEN_CONTEXT_INDEX_WORKERS", "3")
    assert runner.default_worker_count() == 3


def test_parent_process_is_none_in_the_test_process() -> None:
    assert multiprocessing.parent_process() is None
