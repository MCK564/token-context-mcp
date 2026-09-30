from __future__ import annotations

import json
import math
import os
import pickle
import re
import shutil
import signal
import sqlite3
import threading
import time
import tomllib
import uuid
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import astuple, dataclass, field, replace
from functools import lru_cache
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import pathspec

from token_context_mcp import __version__

from token_context_mcp.constants import (
    DEFAULT_MAX_GRAPH_NODES,
    INDEX_SCHEMA_VERSION,
    SUPPORTED_EXTENSIONS,
)
from token_context_mcp.index.gitinfo import git_head
from token_context_mcp.index.hashing import sha256_bytes, sha256_file
from token_context_mcp.index.sqlite_store import SQLiteStore, snapshot_free_ratio
from token_context_mcp.models import (
    EdgeRecord,
    FileRecord,
    RepositoryConfig,
    SymbolRecord,
)
from token_context_mcp.parse.lexical_edges import RESOLVER_VERSION, build_lexical_edges
from token_context_mcp.parse.treesitter import PARSER_ARTIFACT_VERSION, CallRecord, ParseError, parse_source
from token_context_mcp.stubs import get_relevant_stubs
from token_context_mcp.retrieve.code_tokens import path_tokens, split_identifier
from token_context_mcp.retrieve.edge_stats import edge_precision
from token_context_mcp.retrieve.ranking import compute_global_ranks
from token_context_mcp.security.content_policy import is_hard_denied, is_probably_binary
from token_context_mcp.security.local_privacy import (
    secure_directory,
    secure_file,
    secure_sqlite_artifacts,
)
from token_context_mcp.security.path_policy import is_reparse_point, relative_posix

# A file whose mtime is within this window before the previous scan started may have been written again
# inside the filesystem's timestamp granularity, so (size, mtime_ns) cannot vouch for its content: rehash it.
RACY_WINDOW_NS = 2_000_000_000
# Below this many files to (re)parse a process pool costs more than it saves.
PARSE_POOL_MIN_FILES = 32
# ... and that much source: measured on the 2-core dev VM, spawning two workers costs ~0.8 s (they re-import the
# package and the grammars), about what 300 files of parsing cost, so 32 small files alone never pay for a pool.
PARSE_POOL_MIN_BYTES = 1_000_000

FTS_BUILDER_VERSION = 2  # 1: base, 2: M12.2 doc comment attached to member instead of container own_body
_FTS_DOC_COMMENTS = os.environ.get("TOKEN_CONTEXT_FTS_DOC_COMMENTS", "c_sharp,java")
_FTS_INTERFACE_DOC = os.environ.get("TOKEN_CONTEXT_FTS_INTERFACE_DOC", "c_sharp,java")
# Delta writes (page copy of the previous snapshot + row-level changes of its full-text tables) leave free pages
# and fragmented FTS segments behind; after this many in a row, or above this free-page ratio, write from scratch.
MAX_DELTA_GENERATIONS = 25
MAX_DELTA_FREE_RATIO = 0.25
_REGISTER_CALL_RE = re.compile(r"\bregister\s*\([^)]*,\s*([A-Z][A-Za-z0-9_]*)\s*\)")
_STRUCTURAL_KEPT_ROLES = {"protocol_definition", "module_entry_point"}
_CLASS_KINDS = {"class", "interface", "struct", "record"}

STAGE_BY_MESSAGE_PREFIX = (
    ("Scanning", "scan"),
    ("Assigning", "roles"),
    ("Resolving", "edges"),
    ("Computing", "ranks"),
    ("Writing", "write"),
    ("Index snapshot complete", "done"),
)


def stage_of_message(message: str) -> str:
    """Stable machine name of a human progress message (used by ``index --progress-format ndjson``)."""
    for prefix, stage in STAGE_BY_MESSAGE_PREFIX:
        if message.startswith(prefix):
            return stage
    return "other"


class _Timings:
    """Accumulates wall-clock milliseconds per index stage (M7.0)."""

    STAGES = ("inventory", "read_hash", "parse", "roles", "edges", "fts_prep", "ranks", "write", "finalize")

    def __init__(self) -> None:
        self.ms: dict[str, float] = {name: 0.0 for name in self.STAGES}

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] += (time.perf_counter() - started) * 1000.0

    def add(self, name: str, started: float) -> None:
        self.ms[name] += (time.perf_counter() - started) * 1000.0

    def add_ms(self, name: str, ms: float) -> None:
        self.ms[name] += ms

    def as_dict(self) -> dict[str, float]:
        return {name: round(value, 1) for name, value in self.ms.items()}


def current_pointer_path(index_directory: Path, repo_id: str) -> Path:
    return index_directory / f"{repo_id}.current.json"


def gc_snapshots(
    index_directory: Path,
    repo_id: str,
    current_db_name: str,
    max_age_seconds: float = 600.0,
) -> list[str]:
    """Garbage collect older snapshot files older than max_age_seconds."""
    removed: list[str] = []
    now = time.time()
    for item in index_directory.glob(f"{repo_id}.*.sqlite"):
        if item.name == current_db_name or item.name == f"{repo_id}.sqlite":
            continue
        try:
            mtime = item.stat().st_mtime
            if (now - mtime) >= max_age_seconds:
                for suffix in ("", "-wal", "-shm"):
                    p = item.parent / f"{item.name}{suffix}"
                    try:
                        p.unlink(missing_ok=True)
                    except (PermissionError, OSError):
                        pass
                removed.append(item.name)
        except (PermissionError, OSError):
            pass
    return removed


def database_path(index_directory: Path, repo_id: str) -> Path:
    pointer = current_pointer_path(index_directory, repo_id)
    if pointer.is_file():
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            db_name = data.get("db")
            if db_name:
                cand = index_directory / db_name
                if cand.exists():
                    return cand
        except Exception:
            pass
    return index_directory / f"{repo_id}.sqlite"


def manifest_path(index_directory: Path, repo_id: str) -> Path:
    return index_directory / f"{repo_id}.manifest.json"


# ---------------------------------------------------------------------------------------------------------
# per-file work (runs in the parent for small batches, in spawned pool workers for large ones)
# ---------------------------------------------------------------------------------------------------------


@dataclass
class _Outcome:
    """Everything one file contributes to a snapshot.  Plain data so it can cross a process boundary."""

    relative: str
    kind: str  # parsed | parse_error | same | unsupported | skipped | read_error
    sha256: str = ""
    size: int = 0
    status: str = ""
    warnings: list[str] = field(default_factory=list)
    symbols: list[SymbolRecord] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    inheritance: dict[str, list[str]] = field(default_factory=dict)
    registry_names: list[str] = field(default_factory=list)
    symbol_body_rows: list[tuple[str, str, str]] = field(default_factory=list)
    source_body: str | None = None
    fts_rows: list[tuple[str, str, str, str, str, str]] = field(default_factory=list)
    namespaces: list[str] = field(default_factory=list)
    module_bindings: dict[str, str] = field(default_factory=dict)
    parse_attempts: int = 0
    read_ms: float = 0.0
    parse_ms: float = 0.0
    text_ms: float = 0.0
    error: str = ""


# task = (relative, absolute path, language | None, max_file_bytes, known_sha | None)
_Task = tuple[str, str, "str | None", int, "str | None"]


def _process_candidate(task: _Task) -> _Outcome:
    relative, path_text, language, max_file_bytes, known_sha = task
    started = time.perf_counter()
    try:
        raw = Path(path_text).read_bytes()
    except OSError as error:
        return _Outcome(relative, "read_error", error=type(error).__name__)
    if len(raw) > max_file_bytes or is_probably_binary(raw):
        return _Outcome(relative, "skipped")
    sha = sha256_bytes(raw)
    read_ms = (time.perf_counter() - started) * 1000.0
    if language is None:
        return _Outcome(relative, "unsupported", sha256=sha, size=len(raw), status="unsupported", read_ms=read_ms)
    if known_sha is not None and known_sha == sha:
        return _Outcome(relative, "same", sha256=sha, size=len(raw), read_ms=read_ms)
    source = raw.decode("utf-8", errors="replace")
    registry_names = sorted({match.group(1) for match in _REGISTER_CALL_RE.finditer(source)})
    parse_started = time.perf_counter()
    try:
        parsed = parse_source(relative, raw, language)
    except ParseError as error:
        parse_ms = (time.perf_counter() - parse_started) * 1000.0
        text_started = time.perf_counter()
        outcome = _Outcome(
            relative,
            "parse_error",
            sha256=sha,
            size=len(raw),
            status="parse_error",
            warnings=[type(error).__name__],
            registry_names=registry_names,
            source_body=_search_text(source),
            fts_rows=_fts_rows(relative, language, source, []),
            parse_attempts=1,
            read_ms=read_ms,
            parse_ms=parse_ms,
        )
        outcome.text_ms = (time.perf_counter() - text_started) * 1000.0
        return outcome
    parse_ms = (time.perf_counter() - parse_started) * 1000.0
    text_started = time.perf_counter()
    encoded = source.encode("utf-8")
    symbol_body_rows = [
        (
            symbol.symbol_id,
            symbol.symbol_id.split(":", 2)[1],
            _search_text(encoded[symbol.start_byte : symbol.end_byte].decode("utf-8", errors="replace")),
        )
        for symbol in parsed.symbols
    ]
    outcome = _Outcome(
        relative,
        "parsed",
        sha256=sha,
        size=len(raw),
        status="parsed_with_warnings" if parsed.warnings else "parsed",
        warnings=parsed.warnings,
        symbols=parsed.symbols,
        imports=parsed.imports,
        calls=parsed.calls,
        inheritance=parsed.inheritance,
        registry_names=registry_names,
        symbol_body_rows=symbol_body_rows,
        source_body=_search_text(source),
        fts_rows=_fts_rows(relative, language, source, parsed.symbols),
        parse_attempts=1,
        read_ms=read_ms,
        parse_ms=parse_ms,
        namespaces=parsed.namespaces,
        module_bindings=getattr(parsed, "module_bindings", {}),
    )
    outcome.text_ms = (time.perf_counter() - text_started) * 1000.0
    return outcome


def _process_chunk(worker: Callable[[_Task], _Outcome], chunk: list[_Task]) -> list[_Outcome]:
    return [worker(task) for task in chunk]


def _pool_worker_init() -> None:
    # Ctrl-C reaches the whole foreground process group; only the parent should react to it.
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, OSError):
        pass


def default_worker_count() -> int:
    override = os.environ.get("TOKEN_CONTEXT_INDEX_WORKERS")
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass
    return max(1, min(8, (os.cpu_count() or 1) - 1))


def _terminate_pool(pool) -> None:  # noqa: ANN001 - concurrent.futures.ProcessPoolExecutor
    processes = list(getattr(pool, "_processes", {}).values())
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001 - best effort during cancellation
        pass
    for process in processes:
        try:
            if process.is_alive():
                process.terminate()
        except Exception:  # noqa: BLE001
            pass
    for process in processes:
        try:
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def _sigterm_as_interrupt():
    """Turn SIGTERM into KeyboardInterrupt while a pool is alive so ``finally`` blocks reap the workers."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[int, object] = {}

    def _handler(signum, frame):  # noqa: ANN001
        raise KeyboardInterrupt(f"signal {signum}")

    for name in ("SIGTERM", "SIGBREAK"):  # SIGBREAK: Ctrl-Break on Windows
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            previous[number] = signal.signal(number, _handler)
        except (ValueError, OSError):
            continue
    try:
        yield
    finally:
        for number, handler in previous.items():
            try:
                signal.signal(number, handler)  # type: ignore[arg-type]
            except (ValueError, OSError, TypeError):
                pass


def _run_tasks(
    tasks: list[_Task],
    *,
    workers: int,
    worker_fn: Callable[[_Task], _Outcome] = _process_candidate,
    pool_min_files: int = PARSE_POOL_MIN_FILES,
    pool_min_bytes: int = 0,
    total_bytes: int = 0,
    on_progress: Callable[[int], None] | None = None,
) -> tuple[dict[str, _Outcome], dict[str, object]]:
    """Run ``worker_fn`` over ``tasks``; returns outcomes keyed by path and a small report about how it ran."""
    outcomes: dict[str, _Outcome] = {}
    report: dict[str, object] = {"mode": "sequential", "workers": 1, "fallback": None}
    done = 0

    def run_sequential(items: list[_Task]) -> None:
        nonlocal done
        for task in items:
            outcome = worker_fn(task)
            outcomes[outcome.relative] = outcome
            done += 1
            if on_progress and done % 10 == 0:
                on_progress(done)

    if workers < 2 or len(tasks) < pool_min_files or total_bytes < pool_min_bytes:
        run_sequential(tasks)
        return outcomes, report

    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool

    chunk_size = max(1, min(64, len(tasks) // (workers * 6) or 1))
    chunks = [tasks[i : i + chunk_size] for i in range(0, len(tasks), chunk_size)]
    report.update({"mode": "spawn-pool", "workers": workers})
    pool = None
    try:
        with _sigterm_as_interrupt():
            try:
                pool = ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=_pool_worker_init,
                )
                futures = [pool.submit(_process_chunk, worker_fn, chunk) for chunk in chunks]
                for future in futures:
                    for outcome in future.result():
                        outcomes[outcome.relative] = outcome
                        done += 1
                    if on_progress:
                        on_progress(done)
            except (BrokenProcessPool, pickle.PickleError, OSError, RuntimeError, AttributeError, TypeError, ImportError) as error:
                # Pool could not start, a worker died, or something was not picklable: finish in-process.
                report.update({"mode": "sequential-fallback", "workers": 1, "fallback": type(error).__name__})
                if pool is not None:
                    _terminate_pool(pool)
                    pool = None
                run_sequential([task for task in tasks if task[0] not in outcomes])
    finally:
        if pool is not None:
            _terminate_pool(pool)
    return outcomes, report


# ---------------------------------------------------------------------------------------------------------
# previous snapshot (schema 2.4) used as the incremental base
# ---------------------------------------------------------------------------------------------------------


@dataclass
class _Previous:
    path: Path
    files: dict[str, FileRecord]
    artifacts: dict[str, tuple]
    symbols_by_path: dict[str, list[SymbolRecord]]
    scan_started_at_ns: int
    edges_by_path: dict[str, list[EdgeRecord]]
    edge_context_sha256: str | None
    generation: int


def _parser_fingerprint() -> str:
    from importlib import metadata

    parts: list[str] = []
    for name in (
        "tree-sitter",
        "tree-sitter-python",
        "tree-sitter-javascript",
        "tree-sitter-typescript",
        "tree-sitter-java",
        "tree-sitter-c-sharp",
        "tree-sitter-html",
        "tree-sitter-css",
        "tree-sitter-go",
    ):
        try:
            parts.append(f"{name}={metadata.version(name)}")
        except metadata.PackageNotFoundError:
            continue
    return f"artifact-v{PARSER_ARTIFACT_VERSION};fts-v{FTS_BUILDER_VERSION};resolver-v{RESOLVER_VERSION};" + ";".join(parts)


def _load_previous(destination: Path, repository: RepositoryConfig, fingerprint: str) -> _Previous | None:
    """Read the active snapshot as an incremental base; ``None`` means "index from scratch"."""
    if not destination.exists():
        return None
    uri = f"file:{destination.as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True)
        metadata = {key: json.loads(value) for key, value in connection.execute("SELECT key, value FROM metadata")}
        if metadata.get("index_schema_version") != INDEX_SCHEMA_VERSION:
            return None  # 2.1-2.3 snapshots carry no parse artifacts: the first run after an upgrade is a full one
        if metadata.get("repo_root_id") != sha256_bytes(str(repository.root).encode()):
            return None
        if metadata.get("parser_fingerprint") != fingerprint:
            return None
        scan_started = metadata.get("scan_started_at_ns")
        if not isinstance(scan_started, int):
            return None
        files = {
            row[0]: FileRecord(
                path=row[0], sha256=row[1], size=row[2], mtime_ns=row[3], language=row[4],
                parse_status=row[5], warnings=json.loads(row[6]),
            )
            for row in connection.execute(
                "SELECT path, sha256, size, mtime_ns, language, parse_status, warnings_json FROM files"
            )
        }
        artifacts = {
            row[0]: row
            for row in connection.execute(
                "SELECT path, sha256, parser_version, language, calls_json, inheritance_json, imports_json,"
                " warnings_json, facts_json FROM file_parse_artifacts"
            )
        }
        symbols_by_path: dict[str, list[SymbolRecord]] = {}
        for row in connection.execute(
            "SELECT symbol_id, path, name, qualified_name, kind, signature, start_line, end_line, start_byte,"
            " end_byte, body_start_byte, body_end_byte, is_private, roles_json, role_evidence_json"
            " FROM symbols ORDER BY rowid"
        ):
            symbols_by_path.setdefault(row[1], []).append(
                SymbolRecord(
                    symbol_id=row[0], path=row[1], name=row[2], qualified_name=row[3], kind=row[4],
                    signature=row[5], start_line=row[6], end_line=row[7], start_byte=row[8], end_byte=row[9],
                    body_start_byte=row[10], body_end_byte=row[11], is_private=bool(row[12]),
                    roles=[] if row[13] == "[]" else json.loads(row[13]),
                    role_evidence={} if row[14] == "{}" else json.loads(row[14]),
                )
            )
        edges_by_path: dict[str, list[EdgeRecord]] = {}
        for row in connection.execute(
            "SELECT source_symbol_id, target_symbol_id, target_stub_id, target_name, edge_kind, status, backend,"
            " confidence, source_path, source_line, evidence_json FROM edges ORDER BY edge_id"
        ):
            edges_by_path.setdefault(row[8], []).append(
                EdgeRecord(
                    source_symbol_id=row[0], target_symbol_id=row[1], target_stub_id=row[2], target_name=row[3],
                    edge_kind=row[4], status=row[5], backend=row[6], confidence=row[7], source_path=row[8],
                    source_line=row[9], evidence=json.loads(row[10]),
                )
            )
        return _Previous(
            destination, files, artifacts, symbols_by_path, scan_started, edges_by_path,
            metadata.get("edge_context_sha256"),
            int(metadata.get("snapshot_generation") or 0),
        )
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return None
    finally:
        if connection is not None:
            connection.close()


def _artifact_is_valid(previous: _Previous, record: FileRecord, language: str | None) -> bool:
    if language is None or record.language != language:
        return False
    artifact = previous.artifacts.get(record.path)
    return (
        artifact is not None
        and artifact[1] == record.sha256
        and artifact[2] == PARSER_ARTIFACT_VERSION
        and artifact[3] == language
        and record.parse_status in {"parsed", "parsed_with_warnings", "parse_error"}
    )


def _calls_to_json(calls: list[CallRecord]) -> str:
    return json.dumps([astuple(call) for call in calls], separators=(",", ":"))


def _calls_from_json(text: str) -> list[CallRecord]:
    return [CallRecord(*row) for row in json.loads(text)]


def _artifact_row(outcome: _Outcome, language: str) -> tuple:
    return (
        outcome.relative,
        outcome.sha256,
        PARSER_ARTIFACT_VERSION,
        language,
        _calls_to_json(outcome.calls),
        json.dumps(outcome.inheritance, separators=(",", ":"), sort_keys=True),
        json.dumps(outcome.imports, separators=(",", ":")),
        json.dumps(outcome.warnings, separators=(",", ":")),
        json.dumps(
            {
                "registry_names": outcome.registry_names,
                "call_names": sorted({call.name for call in outcome.calls}),
                "assigned_from": sorted({call.assigned_from_fn for call in outcome.calls if call.assigned_from_fn}),
                "namespaces": outcome.namespaces,
                "module_bindings": outcome.module_bindings,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def build_index(
    repository: RepositoryConfig,
    index_directory: Path,
    *,
    network_policy: str,
    progress_callback: Callable[[str, int, int], None] | None = None,
    verify_hashes: bool = False,
    workers: int | None = None,
    full_rebuild: bool = False,
    pool_min_files: int = PARSE_POOL_MIN_FILES,
    pool_min_bytes: int = PARSE_POOL_MIN_BYTES,
) -> dict[str, object]:
    """Build a new immutable snapshot, reusing whatever the active snapshot already knows.

    Files whose ``(size, mtime_ns)`` are unchanged (and not racy, see ``RACY_WINDOW_NS``) are neither read nor
    parsed; files whose content hash is unchanged are read but not parsed; only new or modified files reach
    tree-sitter.  ``verify_hashes`` makes every file be read and hashed, ``full_rebuild`` ignores the active
    snapshot entirely.  The result is equivalent to a from-scratch build (invariant I1, ``evals/index_equivalence.py``).
    """
    secure_directory(index_directory)
    timings = _Timings()
    scan_started_at_ns = time.time_ns()
    fingerprint = _parser_fingerprint()
    destination = database_path(index_directory, repository.repo_id)
    previous = None if full_rebuild else _load_previous(destination, repository, fingerprint)
    racy_cutoff_ns = (previous.scan_started_at_ns - RACY_WINDOW_NS) if previous else 0
    worker_count = workers if workers is not None else default_worker_count()

    files: list[FileRecord] = []
    symbols: list[SymbolRecord] = []
    imports: dict[str, list[str]] = {}
    calls_by_path: dict[str, list[CallRecord] | str] = {}  # str = JSON of a reused artifact, decoded on demand
    facts_by_path: dict[str, dict] = {}
    reparsed_paths: set[str] = set()
    inheritance_by_path: dict[str, dict[str, list[str]]] = {}
    registry_names: set[str] = set()
    warnings: list[str] = []
    files_seen = 0
    files_skipped = 0
    files_reused = 0
    files_reparsed = 0
    files_hashed = 0
    files_stat_skipped = 0
    parse_source_calls = 0
    artifact_rows: list[tuple] = []
    symbol_body_rows: list[tuple[str, str, str]] = []
    source_body_rows: list[tuple[str, str]] = []
    fts_rows: list[tuple[str, str, str, str, str, str]] = []
    reuse_paths: set[str] = set()

    with timings.stage("inventory"):
        inventory = _inventory(repository)

    # -- classify: which files can be vouched for by (size, mtime_ns), which must be read -------------------
    _t_scan = time.perf_counter()
    slots: list[tuple[str, str, object]] = []  # (relative, "prev" | "cand", FileRecord | stat_result)
    tasks: list[_Task] = []
    task_bytes = 0
    for file_path in inventory:
        files_seen += 1
        relative = relative_posix(repository.root, file_path)
        if progress_callback and files_seen % 10 == 0:
            progress_callback(f"Scanning {relative}", files_seen, len(inventory))
        if is_hard_denied(relative):
            files_skipped += 1
            continue
        try:
            stat = file_path.stat()  # BEFORE the read: a later write then shows up as a different mtime
        except OSError as error:
            files_skipped += 1
            warnings.append(f"read_error:{relative}:{type(error).__name__}")
            continue
        if stat.st_size > repository.max_file_bytes:
            files_skipped += 1
            continue
        language = SUPPORTED_EXTENSIONS.get(file_path.suffix.lower())
        prior = previous.files.get(relative) if previous else None
        if (
            previous is not None
            and prior is not None
            and not verify_hashes
            and prior.size == stat.st_size
            and prior.mtime_ns == stat.st_mtime_ns
            and prior.mtime_ns < racy_cutoff_ns
            and prior.language == language
            and (language is None or _artifact_is_valid(previous, prior, language))
        ):
            slots.append((relative, "prev", prior))
            files_stat_skipped += 1
            continue
        known_sha = (
            prior.sha256
            if previous is not None and prior is not None and _artifact_is_valid(previous, prior, language)
            else None
        )
        slots.append((relative, "cand", stat))
        task_bytes += stat.st_size
        tasks.append((relative, str(file_path), language, repository.max_file_bytes, known_sha))
    timings.add("read_hash", _t_scan)

    # -- read / hash / parse the candidates ---------------------------------------------------------------
    _t_parse = time.perf_counter()

    def _on_progress(done: int) -> None:
        if progress_callback:
            progress_callback("Scanning & parsing", done, len(tasks))

    outcomes, pool_report = _run_tasks(
        tasks,
        workers=worker_count,
        pool_min_files=pool_min_files,
        pool_min_bytes=pool_min_bytes,
        total_bytes=task_bytes,
        on_progress=_on_progress,
    )
    parse_wall_ms = (time.perf_counter() - _t_parse) * 1000.0
    text_ms = sum(outcome.text_ms for outcome in outcomes.values())
    if pool_report["mode"] == "spawn-pool":
        timings.add_ms("parse", parse_wall_ms)  # text preparation ran inside the workers
    else:
        timings.add_ms("parse", max(0.0, parse_wall_ms - text_ms))
        timings.add_ms("fts_prep", text_ms)
    parse_source_calls = sum(outcome.parse_attempts for outcome in outcomes.values())

    # -- assemble in inventory order (order feeds the deterministic graph stages) ----------------------------
    def reuse(record: FileRecord, language: str) -> None:
        nonlocal files_reused
        assert previous is not None
        artifact = previous.artifacts[record.path]
        files.append(record)
        symbols.extend(previous.symbols_by_path.get(record.path, ()))
        if record.parse_status != "parse_error":
            imports[record.path] = json.loads(artifact[6])
            calls_by_path[record.path] = artifact[4]
            inheritance_by_path[record.path] = json.loads(artifact[5])
        facts = json.loads(artifact[8])
        facts_by_path[record.path] = facts
        registry_names.update(facts.get("registry_names", ()))
        artifact_rows.append(artifact)
        reuse_paths.add(record.path)
        files_reused += 1

    for relative, mode, data in slots:
        if mode == "prev":
            record = data  # type: ignore[assignment]
            if record.language is None:
                files.append(record)
                fts_rows.append(_module_fts_row(relative, "unknown", ""))
            else:
                reuse(record, record.language)
            continue
        stat = data
        outcome = outcomes[relative]
        if outcome.kind == "read_error":
            files_skipped += 1
            warnings.append(f"read_error:{relative}:{outcome.error}")
            continue
        if outcome.kind == "skipped":
            files_skipped += 1
            continue
        files_hashed += 1
        language = SUPPORTED_EXTENSIONS.get(Path(relative).suffix.lower())
        if outcome.kind == "unsupported":
            files.append(
                FileRecord(relative, outcome.sha256, outcome.size, stat.st_mtime_ns, None, "unsupported", [])  # type: ignore[attr-defined]
            )
            fts_rows.append(_module_fts_row(relative, "unknown", ""))
            continue
        assert language is not None
        if outcome.kind == "same":
            assert previous is not None
            prior = previous.files[relative]
            reuse(
                FileRecord(
                    relative, outcome.sha256, outcome.size, stat.st_mtime_ns, language,  # type: ignore[attr-defined]
                    prior.parse_status, prior.warnings,
                ),
                language,
            )
            continue
        files_reparsed += 1
        reparsed_paths.add(relative)
        files.append(
            FileRecord(relative, outcome.sha256, outcome.size, stat.st_mtime_ns, language, outcome.status, outcome.warnings)  # type: ignore[attr-defined]
        )
        if outcome.kind == "parse_error":
            warnings.append(f"parse_error:{relative}")
        else:
            symbols.extend(outcome.symbols)
            imports[relative] = outcome.imports
            calls_by_path[relative] = outcome.calls
            inheritance_by_path[relative] = outcome.inheritance
            if outcome.namespaces:
                facts_by_path.setdefault(relative, {})["namespaces"] = outcome.namespaces
            if outcome.module_bindings:
                facts_by_path.setdefault(relative, {})["module_bindings"] = outcome.module_bindings
        registry_names.update(outcome.registry_names)
        artifact_rows.append(_artifact_row(outcome, language))
        symbol_body_rows.extend(outcome.symbol_body_rows)
        if outcome.source_body is not None:
            source_body_rows.append((relative, outcome.source_body))
        fts_rows.extend(outcome.fts_rows)

    if progress_callback:
        progress_callback("Assigning structural roles...", files_seen, len(symbols))
    _t_roles = time.perf_counter()
    declared_entry_points = _declared_entry_points(repository.root)
    sources = _LazySources(repository.root)
    symbols, entry_points = _assign_structural_roles(
        symbols,
        {},
        declared_entry_points,
        registry_wired_names=registry_names,
        source_lookup=sources,
    )
    body_lengths = [
        max(1, symbol.end_byte - (symbol.body_start_byte or symbol.end_byte))
        for symbol in symbols
    ]
    median_symbol_body_bytes = round(median(body_lengths)) if body_lengths else 1
    max_edges_per_symbol = max(25, min(200, math.ceil(median_symbol_body_bytes / 10)))
    derived_limit_ceiling = max(30, min(100, math.ceil(len(symbols) / 10)))
    derived_impact_max_nodes = max(
        30, min(DEFAULT_MAX_GRAPH_NODES, math.ceil(math.sqrt(max(1, len(symbols))) * 3))
    )
    derived_defaults = {
        "max_edges_per_symbol": {
            "value": max_edges_per_symbol,
            "median_symbol_body_bytes": median_symbol_body_bytes,
            "formula": "ceil(median_symbol_body_bytes / 10), floor=25, cap=200",
        },
        "limit_ceiling": {
            "value": derived_limit_ceiling,
            "symbol_count": len(symbols),
            "formula": "ceil(symbol_count / 10), floor=30, cap=100",
        },
        "impact_max_nodes": {
            "value": derived_impact_max_nodes,
            "symbol_count": len(symbols),
            "formula": "ceil(3 * sqrt(symbol_count)), floor=30, cap=500",
        },
    }
    timings.add("roles", _t_roles)
    _t_edges = time.perf_counter()
    class_hierarchy_map: dict[str, list[str]] = {}
    for inh in inheritance_by_path.values():
        for cls_name, parents in inh.items():
            class_hierarchy_map[cls_name] = parents

    class_hierarchy_rows: list[tuple[str, str, str | None]] = []
    class_symbol_map = {s.name: s.symbol_id for s in symbols if s.kind in _CLASS_KINDS}
    for symbol in symbols:
        if symbol.kind in _CLASS_KINDS:
            parents = class_hierarchy_map.get(symbol.name, [])
            for p_name in parents:
                short_p = p_name.rsplit(".", 1)[-1]
                p_sym_id = class_symbol_map.get(p_name) or class_symbol_map.get(short_p)
                class_hierarchy_rows.append((symbol.symbol_id, p_name, p_sym_id))

    fts_rows = _inherit_interface_doc_tokens(symbols, fts_rows, class_hierarchy_map)

    if progress_callback:
        progress_callback("Resolving lexical graph edges...", files_seen, len(symbols))
    active_stubs = get_relevant_stubs(imports)
    file_namespaces: dict[str, list[str]] = {
        path: facts["namespaces"]
        for path, facts in facts_by_path.items()
        if facts.get("namespaces")
    }
    js_module_bindings: dict[str, dict[str, str]] = {
        path: facts["module_bindings"]
        for path, facts in facts_by_path.items()
        if facts.get("module_bindings")
    }
    edges, edge_context_sha256, edge_report = _resolve_edges(
        symbols=symbols,
        calls_by_path=calls_by_path,
        facts_by_path=facts_by_path,
        imports=imports,
        class_hierarchy_map=class_hierarchy_map,
        active_stubs=active_stubs,
        max_edges_per_symbol=max_edges_per_symbol,
        previous=previous,
        reparsed_paths=reparsed_paths,
        file_namespaces=file_namespaces,
        js_module_bindings=js_module_bindings,
    )
    timings.add("edges", _t_edges)

    dir_mtimes: dict[str, int] = {}
    try:
        dir_mtimes["."] = repository.root.stat().st_mtime_ns
    except OSError:
        pass
    for item in files:
        rel_p = Path(item.path)
        parent_rel = str(rel_p.parent).replace("\\", "/")
        dir_key = "." if parent_rel in (".", "") else parent_rel
        if dir_key not in dir_mtimes:
            try:
                full_d = repository.root if dir_key == "." else (repository.root / dir_key)
                dir_mtimes[dir_key] = full_d.stat().st_mtime_ns
            except OSError:
                pass

    use_delta = False
    code_files = sum(1 for item in files if item.language)
    if previous is not None and len(reuse_paths) * 2 >= max(1, code_files) and previous.generation < MAX_DELTA_GENERATIONS:
        try:
            use_delta = snapshot_free_ratio(previous.path) <= MAX_DELTA_FREE_RATIO
        except (OSError, sqlite3.Error):
            use_delta = False

    index_run_id = _new_run_id()
    ns_to_files: dict[str, list[str]] = defaultdict(list)
    for p, ns_list in file_namespaces.items():
        for ns in ns_list:
            ns_to_files[ns].append(p)
    csharp_ns_map = {ns: sorted(flist) for ns, flist in sorted(ns_to_files.items())}

    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "csharp_namespaces": csharp_ns_map,
        "js_module_bindings": js_module_bindings,
        "repo_id": repository.repo_id,
        "repo_root_id": sha256_bytes(str(repository.root).encode()),
        "commit_sha": git_head(repository.root),
        "index_run_id": index_run_id,
        "indexer_version": __version__,
        "parser_versions": {"backend": "tree-sitter", "languages": sorted({item.language for item in files if item.language})},
        "parser_fingerprint": fingerprint,
        "parser_artifact_version": PARSER_ARTIFACT_VERSION,
        "fts_builder_version": FTS_BUILDER_VERSION,
        "resolver_version": RESOLVER_VERSION,
        "scan_started_at_ns": scan_started_at_ns,
        "generated_at": datetime.now(UTC).isoformat(),
        "files_seen": files_seen,
        "files_indexed": len(files),
        "files_skipped": files_skipped,
        "files_reused": files_reused,
        "files_reparsed": files_reparsed,
        "files_stat_skipped": files_stat_skipped,
        "files_hashed": files_hashed,
        "symbols_indexed": len(symbols),
        "edges_indexed": len(edges),
        "stubs_indexed": len(active_stubs),
        "entry_points": entry_points,
        "role_counts": _role_counts(symbols),
        # aggregates get_index_status used to recompute from every symbol/edge row on each call (M7.6)
        "symbols_with_roles": sum(bool(symbol.roles) for symbol in symbols),
        "edge_precision": edge_precision(edges),
        "import_count": sum(len(modules) for modules in imports.values()),
        "importer_count": sum(1 for modules in imports.values() if modules),
        "derived_defaults": derived_defaults,
        "dir_mtimes": dir_mtimes,
        "warnings": warnings,
        "parse_source_calls": parse_source_calls,
        "edge_context_sha256": edge_context_sha256,
        "edge_resolution": edge_report,
        "incremental": previous is not None,
        "snapshot_generation": (previous.generation + 1) if use_delta and previous is not None else 0,
        "write_mode": "delta" if use_delta else "rewrite",
        "parse_mode": pool_report,
        "timings_ms": timings.as_dict(),
        "network_policy": network_policy,
        "network_policy_status": "declared_only; enforce at OS/container boundary",
    }
    run_db_name = f"{repository.repo_id}.{index_run_id}.sqlite"
    run_destination = index_directory / run_db_name
    temporary = index_directory / f"{run_db_name}.tmp-{uuid.uuid4().hex}.sqlite"
    try:
        if progress_callback:
            progress_callback("Computing global symbol PageRank...", files_seen, len(symbols))
        _t_ranks = time.perf_counter()
        global_ranks = compute_global_ranks(symbols, edges)
        timings.add("ranks", _t_ranks)

        if progress_callback:
            progress_callback("Writing atomic SQLite snapshot...", files_seen, len(symbols))
        _t_write = time.perf_counter()
        SQLiteStore(temporary).write_snapshot(
            metadata=manifest,
            files=files,
            symbols=symbols,
            edges=edges,
            imports=imports,
            symbol_bodies={},
            source_bodies={},
            class_hierarchy=class_hierarchy_rows,
            external_stubs=active_stubs,
            symbol_ranks=global_ranks,
            symbol_fts_records=fts_rows,
            symbol_body_rows=symbol_body_rows,
            source_body_rows=source_body_rows,
            parse_artifact_rows=artifact_rows,
            reuse_text_from=previous.path if previous is not None else None,
            reuse_text_paths=reuse_paths,
            delta_from_base=use_delta,
        )
        timings.add("write", _t_write)
        _t_final = time.perf_counter()
        _atomic_replace(temporary, run_destination)
        secure_sqlite_artifacts(run_destination)
        manifest["artifact_sha256"] = sha256_file(run_destination)

        # Write pointer file <repo>.current.json atomically
        pointer_dest = current_pointer_path(index_directory, repository.repo_id)
        pointer_tmp = pointer_dest.with_suffix(f".tmp-{uuid.uuid4().hex}.json")
        pointer_data = {
            "db": run_db_name,
            "index_run_id": index_run_id,
            "repo_id": repository.repo_id,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        pointer_tmp.write_text(json.dumps(pointer_data, indent=2) + "\n", encoding="utf-8")
        secure_file(pointer_tmp)
        os.replace(str(pointer_tmp), str(pointer_dest))

        # Backward compatibility: <repo>.sqlite next to the versioned snapshot (hardlink, copy if the fs refuses)
        _publish_legacy_copy(run_destination, index_directory / f"{repository.repo_id}.sqlite")

        # GC older snapshots
        gc_snapshots(index_directory, repository.repo_id, current_db_name=run_db_name)
        timings.add("finalize", _t_final)
        manifest["timings_ms"] = timings.as_dict()
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        temporary_manifest = manifest_path(index_directory, repository.repo_id).with_suffix(".tmp.json")
        temporary_manifest.write_text(manifest_json, encoding="utf-8", newline="\n")
        secure_file(temporary_manifest)
        temporary_manifest.replace(manifest_path(index_directory, repository.repo_id))

        if progress_callback:
            progress_callback("Index snapshot complete!", files_seen, len(symbols))
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def _edge_context_sha256(
    class_hierarchy_map: dict[str, list[str]], active_stubs: list, max_edges_per_symbol: int
) -> str:
    """Fingerprint of the global inputs of edge resolution that are not per-file (see ``_resolve_edges``)."""
    payload = {
        # classes without parents cannot change any ancestor lookup, so they stay out of the fingerprint
        "hierarchy": {name: parents for name, parents in class_hierarchy_map.items() if parents},
        "stubs": [
            (stub.stub_id, stub.package, stub.export_path, stub.member_name, stub.signature, stub.doc_summary)
            for stub in active_stubs
        ],
        "max_edges_per_symbol": max_edges_per_symbol,
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))


def _name_index(symbols: Iterable[SymbolRecord]) -> dict[str, list[tuple[str, str, str, str]]]:
    """name -> ordered (path, qualified_name, kind, signature) of every symbol with that name.

    These are exactly the symbol attributes lexical edge resolution looks at (ids only name the winner)."""
    index: dict[str, list[tuple[str, str, str, str]]] = {}
    for symbol in symbols:
        index.setdefault(symbol.name, []).append((symbol.path, symbol.qualified_name, symbol.kind, symbol.signature))
    return index


def _resolve_edges(
    *,
    symbols: list[SymbolRecord],
    calls_by_path: dict[str, "list[CallRecord] | str"],
    facts_by_path: dict[str, dict],
    imports: dict[str, list[str]],
    class_hierarchy_map: dict[str, list[str]],
    active_stubs: list,
    max_edges_per_symbol: int,
    previous: _Previous | None,
    reparsed_paths: set[str],
    file_namespaces: dict[str, list[str]] | None = None,
    js_module_bindings: dict[str, dict[str, str]] | None = None,
) -> tuple[list[EdgeRecord], str, dict[str, object]]:
    """Edges of the whole graph, re-resolving only what a change can affect (M7.5).

    The edges of an unchanged file only depend on (a) its own calls/imports, (b) the candidates of every name
    it calls (path, qualified name, kind, signature - the ids merely name the winner), (c) the return types
    behind ``assigned_from_fn`` names (also derived from signatures), (d) the global class hierarchy and
    stub set.  When (d) is unchanged and no name its calls mention changed in (b)/(c), its previous edges are
    kept, with the ids of symbols of re-parsed files remapped by (path, qualified name, kind).  Every other
    file is resolved from scratch, exactly as a full build would, and the result keeps the file order of a
    full build.  Anything unexpected falls back to a full resolution.
    """
    context_sha = _edge_context_sha256(class_hierarchy_map, active_stubs, max_edges_per_symbol)

    def decode(path: str) -> list[CallRecord]:
        value = calls_by_path[path]
        return value if isinstance(value, list) else _calls_from_json(value)

    def resolve(paths: Iterable[str]) -> list[EdgeRecord]:
        return build_lexical_edges(
            symbols,
            {},  # source text is only read by the regex fallback, which is used when calls_by_path is None
            max_edges_per_symbol=max_edges_per_symbol,
            calls_by_path={path: decode(path) for path in paths},
            imports_by_path=imports,
            class_hierarchy=class_hierarchy_map,
            external_stubs=active_stubs,
            file_namespaces=file_namespaces,
            js_module_bindings=js_module_bindings,
        )

    if previous is None or previous.edge_context_sha256 != context_sha:
        return resolve(calls_by_path), context_sha, {"mode": "full", "files_resolved": len(calls_by_path)}

    old_names = _name_index(symbol for group in previous.symbols_by_path.values() for symbol in group)
    new_names = _name_index(symbols)
    changed_names = {name for name in old_names.keys() | new_names.keys() if old_names.get(name) != new_names.get(name)}

    new_by_path: dict[str, list[SymbolRecord]] = {}
    for symbol in symbols:
        new_by_path.setdefault(symbol.path, []).append(symbol)
    new_ids = {symbol.symbol_id for symbol in symbols}
    id_map: dict[str, str] = {}
    for path in reparsed_paths:
        old_keys: dict[tuple[str, str], list[str]] = {}
        for symbol in previous.symbols_by_path.get(path, ()):
            old_keys.setdefault((symbol.qualified_name, symbol.kind), []).append(symbol.symbol_id)
        new_keys: dict[tuple[str, str], list[str]] = {}
        for symbol in new_by_path.get(path, ()):
            new_keys.setdefault((symbol.qualified_name, symbol.kind), []).append(symbol.symbol_id)
        for key, old_ids in old_keys.items():
            new_id_list = new_keys.get(key)
            if len(old_ids) == 1 and new_id_list is not None and len(new_id_list) == 1:
                id_map[old_ids[0]] = new_id_list[0]

    reused: dict[str, list[EdgeRecord]] = {}
    dirty: list[str] = []
    for path in calls_by_path:
        if path in reparsed_paths or path not in previous.files:
            dirty.append(path)
            continue
        facts = facts_by_path.get(path, {})
        if changed_names.intersection(facts.get("call_names", ())) or changed_names.intersection(
            facts.get("assigned_from", ())
        ):
            dirty.append(path)
            continue
        kept: list[EdgeRecord] = []
        for edge in previous.edges_by_path.get(path, ()):
            target = edge.target_symbol_id
            if target is not None:
                target = id_map.get(target, target)
            if edge.source_symbol_id not in new_ids or (target is not None and target not in new_ids):
                kept = None  # type: ignore[assignment]
                break
            kept.append(edge if target == edge.target_symbol_id else replace(edge, target_symbol_id=target))
        if kept is None:
            dirty.append(path)
        else:
            reused[path] = kept

    fresh: dict[str, list[EdgeRecord]] = {}
    if dirty:
        for edge in resolve(dirty):
            fresh.setdefault(edge.source_path, []).append(edge)
    edges: list[EdgeRecord] = []
    for path in calls_by_path:
        edges.extend(reused[path] if path in reused else fresh.get(path, ()))
    report = {
        "mode": "scoped",
        "files_resolved": len(dirty),
        "files_reused": len(reused),
        "changed_names": len(changed_names),
    }
    return edges, context_sha, report


def _publish_legacy_copy(run_destination: Path, legacy_dest: Path) -> None:
    staging = legacy_dest.with_name(f"{legacy_dest.name}.tmp-{uuid.uuid4().hex}")
    try:
        try:
            os.link(run_destination, staging)
        except (OSError, NotImplementedError):
            shutil.copy2(str(run_destination), str(staging))
        os.replace(staging, legacy_dest)
    except (PermissionError, OSError):
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


class _LazySources:
    """Decoded source text of a repository file, read on demand (only ``register``/``get_frontend`` need it)."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[str, str] = {}

    def __call__(self, path: str) -> str:
        cached = self._cache.get(path)
        if cached is None:
            try:
                cached = (self._root / path).read_bytes().decode("utf-8", errors="replace")
            except OSError:
                cached = ""
            self._cache[path] = cached
        return cached


def _declared_entry_points(root: Path) -> list[tuple[str, str]]:
    path = root / "pyproject.toml"
    try:
        with path.open("rb") as handle:
            project = tomllib.load(handle).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return []
    if not isinstance(project, dict):
        return []
    entries: list[tuple[str, str]] = []
    scripts = project.get("scripts", {})
    if isinstance(scripts, dict):
        entries.extend(
            (f"{name} = {target}", str(target))
            for name, target in sorted(scripts.items())
            if isinstance(name, str) and isinstance(target, str)
        )
    groups = project.get("entry-points", {})
    if isinstance(groups, dict):
        for group, values in sorted(groups.items()):
            if not isinstance(group, str) or not isinstance(values, dict):
                continue
            entries.extend(
                (f"{group}.{name} = {target}", str(target))
                for name, target in sorted(values.items())
                if isinstance(name, str) and isinstance(target, str)
            )
    return entries


def _assign_structural_roles(
    symbols: list[SymbolRecord],
    source_by_path: dict[str, str],
    declared_entry_points: list[tuple[str, str]],
    *,
    registry_wired_names: set[str] | None = None,
    source_lookup: Callable[[str], str] | None = None,
) -> tuple[list[SymbolRecord], list[dict[str, object]]]:
    """Assign structural roles in O(n) (M7): children are indexed by parent qualified name once.

    ``registry_wired_names`` (names passed as the last argument of ``register(...)`` anywhere in the sources)
    and ``source_lookup`` (source text of a path, only consulted for ``register``/``get_frontend`` functions)
    let the caller avoid holding every source in memory; with neither, both come from ``source_by_path``.
    """
    if registry_wired_names is None:
        registry_wired_names = {
            match.group(1)
            for source in source_by_path.values()
            for match in _REGISTER_CALL_RE.finditer(source)
        }
    lookup = source_lookup if source_lookup is not None else (lambda path: source_by_path.get(path, ""))

    # A symbol is a direct child of Q when its qualified name is Q + "." + <name without dots>, i.e. when
    # everything before its last "." equals Q.
    children_by_parent: dict[str, list[SymbolRecord]] = {}
    for item in symbols:
        cut = item.qualified_name.rfind(".")
        if cut >= 0:
            children_by_parent.setdefault(item.qualified_name[:cut], []).append(item)

    protocols = {
        symbol.name: symbol
        for symbol in symbols
        if "protocol_definition" in symbol.roles
    }
    protocol_methods: dict[str, set[str]] = {}
    protocol_signatures: dict[str, dict[str, str]] = {}
    for protocol_name, protocol in protocols.items():
        method_symbols = children_by_parent.get(protocol.qualified_name, [])
        protocol_methods[protocol_name] = {symbol.name for symbol in method_symbols}
        protocol_signatures[protocol_name] = {
            symbol.name: symbol.signature for symbol in method_symbols
        }

    updated: list[SymbolRecord] = []
    for symbol in symbols:
        # Recompute inferred roles on every index run. This prevents a stale
        # role from a previous implementation of the heuristic surviving a
        # content-reuse pass.
        roles = [role for role in symbol.roles if role in _STRUCTURAL_KEPT_ROLES]
        evidence = {role: symbol.role_evidence[role] for role in roles if role in symbol.role_evidence}
        if symbol.kind == "class" and "protocol_definition" not in roles:
            methods = {
                item.name: item
                for item in children_by_parent.get(symbol.qualified_name, ())
                if item.kind in {"method", "function"}
            }
            for protocol_name, required_methods in protocol_methods.items():
                if not required_methods or not required_methods.issubset(methods):
                    continue
                if not all(
                    _compatible_method_signature(
                        protocol_signatures[protocol_name][method_name], methods[method_name].signature
                    )
                    for method_name in required_methods
                ):
                    continue
                if not _looks_like_protocol_implementation(symbol, protocol_name):
                    continue
                _add_role(
                    roles,
                    evidence,
                    "protocol_implementation",
                    f"implements {protocol_name} via methods: {', '.join(sorted(required_methods))}",
                )
                break

        if (
            protocols
            and symbol.kind in {"function", "method"}
            and symbol.name in {"register", "get_frontend"}
        ):
            signature_and_body = f"{symbol.signature} {lookup(symbol.path)}"
            if any(protocol_name in signature_and_body for protocol_name in protocols):
                _add_role(roles, evidence, "registry_wiring", "protocol-typed registry function")
        if symbol.kind == "class" and symbol.name in registry_wired_names:
            _add_role(roles, evidence, "registry_wiring", "registered implementation referenced by register(..., ClassName)")
        if roles == symbol.roles and evidence == symbol.role_evidence:
            updated.append(symbol)
        else:
            updated.append(replace(symbol, roles=roles, role_evidence=evidence))

    entry_points: list[dict[str, object]] = []
    for declared, target in declared_entry_points:
        resolved = _resolve_entry_point(updated, target)
        if resolved is not None:
            for index, symbol in enumerate(updated):
                if symbol.symbol_id == resolved.symbol_id:
                    roles = list(symbol.roles)
                    evidence = dict(symbol.role_evidence)
                    _add_role(roles, evidence, "declared_entry_point", declared)
                    updated[index] = replace(symbol, roles=roles, role_evidence=evidence)
                    break
        entry_points.append({"declared": declared, "resolved": resolved is not None})
    return updated, entry_points


def _looks_like_protocol_implementation(symbol: SymbolRecord, protocol_name: str) -> bool:
    lowered_name = symbol.name.lower()
    lowered_path = symbol.path.lower()
    if "frontend" in protocol_name.lower():
        return "frontend" in lowered_name or "frontend" in lowered_path
    if "engine" in protocol_name.lower():
        return "engine" in lowered_name or "ocr" in lowered_path
    return True


def _compatible_method_signature(protocol_signature: str, candidate_signature: str) -> bool:
    protocol_return = _return_annotation(protocol_signature)
    candidate_return = _return_annotation(candidate_signature)
    return bool(protocol_return and protocol_return == candidate_return and "self" in candidate_signature)


def _return_annotation(signature: str) -> str:
    if "->" not in signature:
        return ""
    return signature.split("->", 1)[1].strip().rstrip(":")


def _resolve_entry_point(symbols: list[SymbolRecord], target: str) -> SymbolRecord | None:
    module, separator, attribute = target.partition(":")
    if not separator:
        return None
    attribute = attribute.split(" ", 1)[0].strip()
    if not module or not attribute:
        return None
    matches = [
        symbol
        for symbol in symbols
        if module in _module_candidates(symbol.path)
        and (symbol.qualified_name == attribute or symbol.name == attribute)
    ]
    return matches[0] if len(matches) == 1 else None


@lru_cache(maxsize=None)
def _module_candidates(path: str) -> frozenset[str]:
    normalized = path.replace("\\", "/").strip("/")
    filename = normalized.rsplit("/", 1)[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    parts = (
        [part for part in normalized[: -len(filename)].split("/") if part]
        if len(filename) < len(normalized)
        else []
    )
    parts.append(stem)
    candidates = {".".join(part for part in parts if part)}
    if parts and parts[0] == "src":
        candidates.add(".".join(parts[1:]))
    if stem == "__init__":
        package = parts[:-1]
        candidates.add(".".join(package))
        if package and package[0] == "src":
            candidates.add(".".join(package[1:]))
    return frozenset(candidate for candidate in candidates if candidate)


def _add_role(roles: list[str], evidence: dict[str, str], role: str, reason: str) -> None:
    if role not in roles:
        roles.append(role)
    evidence[role] = reason


def _role_counts(symbols: list[SymbolRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for symbol in symbols:
        for role in symbol.roles:
            counts[role] = counts.get(role, 0) + 1
    return dict(sorted(counts.items()))


def _inventory(repository: RepositoryConfig) -> list[Path]:
    gitignore = _gitignore_spec(repository.root)
    found: list[Path] = []
    for current_root, directories, filenames in os.walk(repository.root, topdown=True, followlinks=False):
        current = Path(current_root)
        safe_directories: list[str] = []
        for directory in directories:
            path = current / directory
            relative = relative_posix(repository.root, path)
            if is_reparse_point(path) or is_hard_denied(relative) or gitignore.match_file(relative + "/"):
                continue
            safe_directories.append(directory)
        directories[:] = safe_directories
        for filename in filenames:
            path = current / filename
            relative = relative_posix(repository.root, path)
            if len(found) >= repository.max_files:
                raise RuntimeError("repository exceeds max_files")
            if is_reparse_point(path) or is_hard_denied(relative) or gitignore.match_file(relative):
                continue
            if path.is_file():
                found.append(path)
    return sorted(found)


def _gitignore_spec(root: Path) -> pathspec.GitIgnoreSpec:
    ignore_file = root / ".gitignore"
    if not ignore_file.is_file():
        return pathspec.GitIgnoreSpec.from_lines([])
    try:
        return pathspec.GitIgnoreSpec.from_lines(ignore_file.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return pathspec.GitIgnoreSpec.from_lines([])


def _atomic_replace(temporary: Path, destination: Path) -> None:
    for suffix in ("-wal", "-shm"):
        (destination.parent / f"{destination.name}{suffix}").unlink(missing_ok=True)
    shutil.move(str(temporary), str(destination))


def _find_preceding_doc_block(lines: list[str], start_line: int, min_line: int) -> int:
    """Find 1-indexed starting line of comment/attribute block immediately preceding start_line.
    Returns start_line if no preceding comment block exists.
    """
    idx = start_line - 2  # 0-indexed line immediately above start_line
    min_idx = min_line - 1
    if idx < min_idx or idx >= len(lines):
        return start_line

    first_comment_idx = start_line - 1
    curr = idx
    while curr >= min_idx:
        raw_l = lines[curr]
        stripped = raw_l.strip()
        if not stripped:
            break
        if (
            stripped.startswith("///")
            or stripped.startswith("//")
            or stripped.startswith("*")
            or stripped.startswith("/*")
            or stripped.endswith("*/")
        ):
            first_comment_idx = curr
            curr -= 1
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            first_comment_idx = curr
            curr -= 1
            continue
        break
    return first_comment_idx + 1


def _fts_rows(
    path: str, language: str | None, source: str, symbols: list[SymbolRecord]
) -> list[tuple[str, str, str, str, str, str]]:
    """``symbol_fts`` rows of one file: one per symbol (own body = its lines minus nested symbols) + the module.

    Nesting is by line span, exactly as before M7, but each symbol only looks at the symbols that *start*
    inside its span (bisect on the start lines) instead of at all symbols of the file.
    """
    lines = source.splitlines()
    by_start = sorted(symbols, key=lambda item: (item.start_line, item.end_line))
    starts = [item.start_line for item in by_start]

    use_doc_shift = False
    if _FTS_DOC_COMMENTS != "off" and language is not None:
        target_langs = {lang.strip() for lang in _FTS_DOC_COMMENTS.split(",")}
        use_doc_shift = language in target_langs

    preceding_starts: dict[str, int] = {}
    if use_doc_shift:
        for i, sym in enumerate(by_start):
            min_l = 1
            for other in reversed(by_start[:i]):
                if other.start_line < sym.start_line and other.end_line >= sym.end_line:
                    min_l = other.start_line + 1
                    break
                elif other.end_line < sym.start_line:
                    min_l = max(min_l, other.end_line + 1)
            preceding_starts[sym.symbol_id] = _find_preceding_doc_block(lines, sym.start_line, min_l)

    rows: list[tuple[str, str, str, str, str, str]] = []
    for sym in symbols:
        low = bisect_left(starts, sym.start_line)
        high = bisect_right(starts, sym.end_line)
        cursor = sym.start_line
        parts: list[str] = []
        for child in by_start[low:high]:
            if child.symbol_id == sym.symbol_id or child.end_line > sym.end_line:
                continue
            child_cut = preceding_starts.get(child.symbol_id, child.start_line)
            if child_cut > cursor:
                parts.extend(lines[max(cursor - 1, 0) : child_cut - 1])
            if child.end_line + 1 > cursor:
                cursor = child.end_line + 1
        if cursor <= sym.end_line:
            parts.extend(lines[max(cursor - 1, 0) : sym.end_line])

        sym_p_start = preceding_starts.get(sym.symbol_id, sym.start_line)
        preceding_lines = lines[sym_p_start - 1 : sym.start_line - 1] if sym_p_start < sym.start_line else []
        own_body = "\n".join(preceding_lines + parts)

        tokens: list[str] = []
        seen_tokens: set[str] = set()

        def add_token(text: str) -> None:
            cleaned = text.strip().lower()
            if cleaned and cleaned not in seen_tokens:
                seen_tokens.add(cleaned)
                tokens.append(cleaned)

        for piece in split_identifier(sym.name):
            add_token(piece)
        for piece in split_identifier(sym.qualified_name):
            add_token(piece)
        if sym.signature:
            for piece in split_identifier(sym.signature):
                add_token(piece)
        for piece in path_tokens(sym.path):
            add_token(piece)
        rows.append((sym.symbol_id, sym.path, sym.name, sym.qualified_name, " ".join(tokens), own_body))

    cursor = 1
    module_parts: list[str] = []
    for item in by_start:
        item_cut = preceding_starts.get(item.symbol_id, item.start_line)
        if item_cut > cursor:
            module_parts.extend(lines[max(cursor - 1, 0) : item_cut - 1])
        if item.end_line + 1 > cursor:
            cursor = item.end_line + 1
    if cursor <= len(lines):
        module_parts.extend(lines[max(cursor - 1, 0) :])
    rows.append(_module_fts_row(path, language or "unknown", "\n".join(module_parts)))
    return rows


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _inherit_interface_doc_tokens(
    symbols: list[SymbolRecord],
    fts_rows: list[tuple[str, str, str, str, str, str]],
    class_hierarchy_map: dict[str, list[str]],
) -> list[tuple[str, str, str, str, str, str]]:
    if _FTS_INTERFACE_DOC == "off":
        return fts_rows

    target_langs = {lang.strip() for lang in _FTS_INTERFACE_DOC.split(",")}
    fts_by_id: dict[str, list[str]] = {row[0]: list(row) for row in fts_rows}

    method_symbols: dict[tuple[str, str], SymbolRecord] = {}
    interface_doc_tokens: dict[tuple[str, str], list[str]] = {}

    for s in symbols:
        lang = s.symbol_id.split(":", 1)[0]
        if lang not in target_langs:
            continue
        if s.kind in {"method", "constructor"} and "." in s.qualified_name:
            parent_name, m_name = s.qualified_name.rsplit(".", 1)
            clean_parent = parent_name.split("`")[0]
            clean_m = m_name.split("<")[0]
            method_symbols[(clean_parent, clean_m)] = s

            fts_row = fts_by_id.get(s.symbol_id)
            if fts_row:
                body = fts_row[5]
                words = [w.lower() for w in _WORD_RE.findall(body) if len(w) >= 3 and not w.startswith("http")]
                if words:
                    interface_doc_tokens[(clean_parent, clean_m)] = words

    for (cls_name, m_name), sym in method_symbols.items():
        parents = class_hierarchy_map.get(cls_name, [])
        if not parents:
            continue
        fts_row = fts_by_id.get(sym.symbol_id)
        if not fts_row:
            continue
        own_body = fts_row[5]
        has_inheritdoc = "<inheritdoc" in own_body.lower()
        has_doc = "/// <summary>" in own_body or "/**" in own_body or "///" in own_body
        if has_inheritdoc or not has_doc:
            for p_name in parents:
                clean_p = p_name.split("<")[0].split("`")[0]
                if (clean_p, m_name) in interface_doc_tokens:
                    inherited = interface_doc_tokens[(clean_p, m_name)]
                    existing_tokens = fts_row[4].split()
                    seen = set(existing_tokens)
                    to_add = [tok for tok in inherited if tok not in seen]
                    if to_add:
                        fts_row[4] = fts_row[4] + " " + " ".join(to_add)
                        break

    return [tuple(r) for r in fts_by_id.values()]


def _module_fts_row(path: str, language: str, module_body: str) -> tuple[str, str, str, str, str, str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for piece in ("module", *path_tokens(path)):
        cleaned = piece.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            tokens.append(cleaned)
    return (f"{language}:{path}:<module>", path, "<module>", "<module>", " ".join(tokens), module_body)


def _search_text(source: str) -> str:
    # FTS5 tokenizes OcrResult and PaddleOCR as one token, while a source
    # search for ocr should behave like the substring-oriented lookup users
    # expect from rg. Keep the original text and add camel-case boundaries
    # for indexing; callers reconstruct snippets from source.
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", source)
    separated = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", separated)
    return f"{source}\n{separated}"


def _new_run_id() -> str:
    return f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
