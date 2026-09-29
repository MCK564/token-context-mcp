"""M7.6-M7.11: cheap status, NDJSON progress, commit sha, ``index --all``, ``index --watch``, schema 2.4."""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from test_index_incremental import make_tree  # noqa: E402
from token_context_mcp import cli  # noqa: E402
from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, load_config, save_config  # noqa: E402
from token_context_mcp.index import runner, watch  # noqa: E402
from token_context_mcp.index.gitinfo import git_head  # noqa: E402
from token_context_mcp.index.runner import database_path  # noqa: E402
from token_context_mcp.retrieve.edge_stats import edge_precision, version_tuple  # noqa: E402
from token_context_mcp.retrieve.service import RetrievalService  # noqa: E402


def write_config(path: Path, repos: dict[str, RepositoryConfig]) -> Path:
    save_config(path, AppConfig(repositories=repos, server=ServerConfig()))
    return path


@pytest.fixture()
def project(tmp_path: Path):
    root = make_tree(tmp_path / "tree", modules=6)
    config = write_config(tmp_path / "cfg" / "repos.toml", {"demo": RepositoryConfig(repo_id="demo", root=root.resolve())})
    return root, config


# ------------------------------------------------------------------------------------------- M7.6 status


def test_version_tuple_orders_numerically() -> None:
    assert version_tuple("2.10") > version_tuple("2.9")
    assert version_tuple("2.3") < version_tuple("2.4") < version_tuple("3")
    assert version_tuple("2.x") == (2, 0)


def test_status_uses_manifest_aggregates_and_matches_row_scan(project) -> None:
    root, config = project
    assert cli.main(["index", "--repo-id", "demo", "--config", str(config)]) == 0
    service = RetrievalService(load_config(config), config)
    fast = service.status("demo")
    store = service._store("demo")
    symbols = store.symbols()
    assert fast["data"]["symbols_with_roles"] == sum(bool(s.roles) for s in symbols) > 0
    assert fast["edge_precision"] == edge_precision(store.edges())
    assert fast["data"]["imports"] == store.import_count() and fast["data"]["imported_by"] == store.importer_count()
    assert fast["data"]["index_schema_version"] == "2.4"
    assert "index_schema_outdated_reindex_recommended" not in fast["warnings"]


def test_status_reads_older_snapshots_and_recommends_reindex(project) -> None:
    root, config = project
    cli.main(["index", "--repo-id", "demo", "--config", str(config)])
    reference = RetrievalService(load_config(config), config).status("demo")
    db = database_path(config.parent / "indexes", "demo")
    connection = sqlite3.connect(db)
    connection.execute("UPDATE metadata SET value = '\"2.3\"' WHERE key = 'index_schema_version'")
    connection.execute("DELETE FROM metadata WHERE key IN ('symbols_with_roles','edge_precision','import_count','importer_count')")
    connection.commit()
    connection.close()
    old = RetrievalService(load_config(config), config).status("demo")
    assert old["data"]["symbols_with_roles"] == reference["data"]["symbols_with_roles"]
    assert old["edge_precision"] == reference["edge_precision"]
    assert old["data"]["imports"] == reference["data"]["imports"]
    assert "index_schema_outdated_reindex_recommended" in old["warnings"]


def test_status_avoids_loading_symbols_and_edges(project, monkeypatch: pytest.MonkeyPatch) -> None:
    root, config = project
    cli.main(["index", "--repo-id", "demo", "--config", str(config)])
    service = RetrievalService(load_config(config), config)
    store_cls = type(service._store("demo"))

    def boom(*args, **kwargs):
        raise AssertionError("status must not scan symbols/edges when the manifest has the aggregates")

    monkeypatch.setattr(store_cls, "symbols", boom)
    monkeypatch.setattr(store_cls, "edges", boom)
    assert service.status("demo")["data"]["symbols_indexed"] > 0


# ------------------------------------------------------------------------------------------- M7.7 ndjson


def test_stage_names_are_stable() -> None:
    assert runner.stage_of_message("Scanning pkg/a.py") == "scan"
    assert runner.stage_of_message("Assigning structural roles...") == "roles"
    assert runner.stage_of_message("Resolving lexical graph edges...") == "edges"
    assert runner.stage_of_message("Computing global symbol PageRank...") == "ranks"
    assert runner.stage_of_message("Writing atomic SQLite snapshot...") == "write"
    assert runner.stage_of_message("Index snapshot complete!") == "done"
    assert runner.stage_of_message("something else") == "other"


def test_ndjson_progress_is_rate_limited_and_done_always_goes_out(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])
    stream = io.StringIO()
    progress = cli._NdjsonProgress(stream)
    for step in range(200):  # 200 events in 1 second of fake time
        clock[0] += 0.005
        progress("Scanning x", step, 200)
    progress.done({"files_indexed": 3})
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(lines) - 1 <= 10
    assert lines[-1]["stage"] == "done" and lines[-1]["manifest"] == {"files_indexed": 3}
    assert all(set(line) >= {"stage", "ts"} for line in lines)
    assert all({"current", "total"} <= set(line) for line in lines[:-1])


def test_index_ndjson_output_is_machine_readable(project, capsys: pytest.CaptureFixture[str]) -> None:
    root, config = project
    assert cli.main(["index", "--repo-id", "demo", "--config", str(config), "--progress-format", "ndjson"]) == 0
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines()]  # every stdout line is JSON
    assert lines[-1]["stage"] == "done" and lines[-1]["manifest"]["files_indexed"] > 0
    assert {line["stage"] for line in lines[:-1]} <= {"scan", "roles", "edges", "ranks", "write", "other"}


# ------------------------------------------------------------------------------------------- M7.8 commit sha


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_commit_sha_and_head_change_detection(project) -> None:
    root, config = project

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "one")
    head = git("rev-parse", "HEAD")
    assert git_head(root) == head
    cli.main(["index", "--repo-id", "demo", "--config", str(config)])
    from token_context_mcp.index import gitinfo

    gitinfo._CACHE.clear()
    service = RetrievalService(load_config(config), config)
    data = service.status("demo")["data"]
    assert data["commit_sha"] == head and data["head_changed_since_index"] is False
    (root / "pkg" / "extra.py").write_text("def extra():\n    return 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "two")
    gitinfo._CACHE.clear()
    assert RetrievalService(load_config(config), config).status("demo")["data"]["head_changed_since_index"] is True


def test_no_git_means_unknown(project) -> None:
    root, config = project
    cli.main(["index", "--repo-id", "demo", "--config", str(config)])
    data = RetrievalService(load_config(config), config).status("demo")["data"]
    assert data["commit_sha"] is None and data["head_changed_since_index"] is None


def test_git_head_is_bounded_and_quiet(tmp_path: Path) -> None:
    assert git_head(tmp_path / "does-not-exist") is None
    assert git_head(tmp_path) is None


# ------------------------------------------------------------------------------------------- M7.9 --all


def test_index_all_summarises_and_survives_a_failing_repository(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = make_tree(tmp_path / "good", modules=3)
    other = make_tree(tmp_path / "other", modules=3)
    config = write_config(
        tmp_path / "cfg" / "repos.toml",
        {
            "a-good": RepositoryConfig(repo_id="a-good", root=good.resolve()),
            "b-tiny-limit": RepositoryConfig(repo_id="b-tiny-limit", root=other.resolve(), max_files=2),
            "c-good": RepositoryConfig(repo_id="c-good", root=good.resolve()),
        },
    )
    code = cli.main(["index", "--all", "--config", str(config)])
    summary = json.loads(capsys.readouterr().out)
    assert code == 1 and summary["indexed"] == 2 and summary["failed"] == 1
    by_id = {item["repo_id"]: item for item in summary["repositories"]}
    assert by_id["a-good"]["ok"] and by_id["c-good"]["ok"] and by_id["a-good"]["files_indexed"] > 0
    assert not by_id["b-tiny-limit"]["ok"] and "max_files" in by_id["b-tiny-limit"]["error"]
    assert database_path(config.parent / "indexes", "a-good").is_file()


def test_index_all_second_run_is_incremental(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_tree(tmp_path / "r", modules=3)
    config = write_config(tmp_path / "cfg" / "repos.toml", {"r": RepositoryConfig(repo_id="r", root=root.resolve())})
    cli.main(["index", "--all", "--config", str(config)])
    capsys.readouterr()
    cli.main(["index", "--all", "--config", str(config)])
    summary = json.loads(capsys.readouterr().out)
    assert summary["repositories"][0]["incremental"] is True


def test_repo_id_and_all_are_exclusive(project) -> None:
    root, config = project
    with pytest.raises(SystemExit):
        cli.main(["index", "--all", "--repo-id", "demo", "--config", str(config)])
    with pytest.raises(SystemExit):
        cli.main(["index", "--config", str(config)])


# ------------------------------------------------------------------------------------------- M7.10 --watch


def _watch_thread(repository: RepositoryConfig, out: Path, seen: list[dict], stop: threading.Event, **kwargs) -> threading.Thread:
    thread = threading.Thread(
        target=lambda: watch.watch_index(
            repository,
            out,
            network_policy="declared-deny-not-enforced",
            stop=stop,
            on_index=seen.append,
            use_watchdog=False,
            **kwargs,
        ),
        daemon=True,
    )
    thread.start()
    return thread


def _wait_for(predicate, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_watch_debounces_a_burst_into_one_reindex(tmp_path: Path) -> None:
    root = make_tree(tmp_path / "tree", modules=4)
    repository = RepositoryConfig(repo_id="demo", root=root.resolve())
    seen: list[dict] = []
    stop = threading.Event()
    thread = _watch_thread(repository, tmp_path / "idx", seen, stop, debounce_seconds=0.6, poll_seconds=0.1)
    try:
        assert _wait_for(lambda: len(seen) == 1)
        for index in range(5):  # a burst: every write restarts the debounce window
            (root / "pkg" / "mod_01.py").write_text(f"def func_01(value):\n    return {index}\n", encoding="utf-8")
            time.sleep(0.15)
        assert _wait_for(lambda: len(seen) == 2)
        time.sleep(1.2)  # no further re-index without further changes
        assert len(seen) == 2
        assert seen[1]["incremental"] is True and seen[1]["parse_source_calls"] == 1
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()


def test_watch_ignores_changes_outside_the_index_policy(tmp_path: Path) -> None:
    root = make_tree(tmp_path / "tree", modules=3)
    (root / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    repository = RepositoryConfig(repo_id="demo", root=root.resolve())
    seen: list[dict] = []
    stop = threading.Event()
    thread = _watch_thread(repository, tmp_path / "idx", seen, stop, debounce_seconds=0.3, poll_seconds=0.1)
    try:
        assert _wait_for(lambda: len(seen) == 1)
        (root / "scratch").mkdir()
        (root / "scratch" / "junk.py").write_text("x = 1\n", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "dep.js").write_text("var a = 1;\n", encoding="utf-8")
        time.sleep(1.0)
        assert len(seen) == 1
    finally:
        stop.set()
        thread.join(timeout=10)


def test_tree_signature_changes_with_size_or_mtime(tmp_path: Path) -> None:
    root = make_tree(tmp_path / "tree", modules=2)
    repository = RepositoryConfig(repo_id="demo", root=root.resolve())
    before = watch.tree_signature(repository)
    assert watch.tree_signature(repository) == before
    (root / "pkg" / "mod_00.py").write_text("x = 1\n", encoding="utf-8")
    assert watch.tree_signature(repository) != before


def test_watchdog_is_optional() -> None:
    assert isinstance(watch.watchdog_available(), bool)
