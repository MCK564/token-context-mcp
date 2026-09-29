from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil
from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Signal

from token_context_mcp.config import (
    ConfigError,
    default_config_path,
    index_directory,
    load_config,
    register_repository,
    save_config,
    unregister_repository,
    validate_repo_id,
)
from token_context_mcp.constants import INDEX_SCHEMA_VERSION
from token_context_mcp.index.runner import (
    current_pointer_path,
    database_path,
    gc_snapshots,
    manifest_path,
)
from token_context_mcp.retrieve.edge_stats import version_tuple
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.security.path_policy import canonical_repository_root

logger = logging.getLogger("token_context_mcp.gui.bridge")


@dataclass
class SystemTelemetry:
    cpu_percent: float
    cpu_count_logical: int
    cpu_count_physical: int
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    ai_hardware: str
    disk_free_gb: float
    disk_total_gb: float


def detect_ai_hardware() -> str:
    """Detect if local machine has GPU/CUDA, MPS, or falls back to CPU."""
    # Check CUDA / NVIDIA
    try:
        if shutil.which("nvidia-smi"):
            out = subprocess.check_output(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True, timeout=2)
            gpu_name = out.strip().split("\n")[0]
            if gpu_name:
                return f"NVIDIA GPU: {gpu_name}"
    except Exception:
        pass

    # Check Apple Silicon
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "Apple Silicon (MPS Engine)"

    # Check Ollama status
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "token-context-gui"})
        with urllib.request.urlopen(req, timeout=1) as resp:
            if resp.status == 200:
                return "CPU Inference (Ollama 7B Active)"
    except Exception:
        pass

    return "CPU Only (Deterministic Fallback)"


class SystemMonitor(QThread):
    telemetry_updated = Signal(object)

    def __init__(self, parent: QObject | None = None, interval: float = 2.5) -> None:
        super().__init__(parent)
        self.interval = interval
        self._running = True
        self._ai_hardware = "Detecting hardware..."

    def run(self) -> None:
        # M8.8: the hardware probe (nvidia-smi, an HTTP call to Ollama) may take seconds; it runs here, on the
        # monitor thread, never on the UI thread.
        try:
            self._ai_hardware = detect_ai_hardware()
        except Exception as e:  # pragma: no cover - probe is best effort
            logger.debug("hardware probe failed: %s", e)
            self._ai_hardware = "Unknown"
        # Prime psutil cpu measurement
        psutil.cpu_percent(interval=None)
        while self._running:
            try:
                cpu_pct = psutil.cpu_percent(interval=None)
                cpu_logical = psutil.cpu_count(logical=True) or 1
                cpu_physical = psutil.cpu_count(logical=False) or cpu_logical

                mem = psutil.virtual_memory()
                ram_used = mem.used / (1024**3)
                ram_total = mem.total / (1024**3)
                ram_pct = mem.percent

                disk = psutil.disk_usage(os.path.abspath(os.sep))
                disk_free = disk.free / (1024**3)
                disk_total = disk.total / (1024**3)

                telemetry = SystemTelemetry(
                    cpu_percent=cpu_pct,
                    cpu_count_logical=cpu_logical,
                    cpu_count_physical=cpu_physical,
                    ram_used_gb=ram_used,
                    ram_total_gb=ram_total,
                    ram_percent=ram_pct,
                    ai_hardware=self._ai_hardware,
                    disk_free_gb=disk_free,
                    disk_total_gb=disk_total,
                )
                self.telemetry_updated.emit(telemetry)
            except Exception as e:
                logger.debug("Error collecting telemetry: %s", e)

            # Sleep in increments so we can exit quickly
            for _ in range(int(self.interval * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


def classify_repo(status: dict[str, Any] | None) -> str:
    """The badge of a repository from its ``get_index_status`` data (M8.5).

    NOT_INDEXED > SCHEMA_OUTDATED > STALE (indexed files changed) > DOCS_CHANGED (only unindexed files changed) > FRESH.
    """
    if not status:
        return "NOT_INDEXED"
    version = status.get("index_schema_version")
    if version is not None and version_tuple(str(version)) < version_tuple(INDEX_SCHEMA_VERSION):
        return "SCHEMA_OUTDATED"
    if status.get("pending_path_count") or status.get("freshness") == "stale":
        return "STALE"
    if status.get("changed_non_indexed"):
        return "DOCS_CHANGED"
    return "FRESH"


class RepoManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_config_path()
        self._cached_repos: list[dict[str, Any]] | None = None

    def get_index_dir(self) -> Path:
        return index_directory(self.config_path)

    def invalidate_cache(self) -> None:
        self._cached_repos = None

    def list_repositories(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """One row per registered repository. Pure I/O, meant to run in a worker (``run_async``).

        ``status`` is the badge of ``classify_repo``; ``ambiguous_rate`` is a 0-1 ratio like everywhere else in
        the MCP responses (the table model turns it into a percentage for display only).
        """
        if self._cached_repos is not None and not force_refresh:
            return self._cached_repos

        config = load_config(self.config_path)
        idx_dir = self.get_index_dir()
        results: list[dict[str, Any]] = []
        service: RetrievalService | None = None

        for repo_id in sorted(config.repositories):
            repo = config.repositories[repo_id]
            db_path = database_path(idx_dir, repo_id)
            mf_path = manifest_path(idx_dir, repo_id)

            db_size_mb = 0.0
            if db_path.exists():
                db_size_mb = round(db_path.stat().st_size / (1024 * 1024), 2)

            status_data: dict[str, Any] | None = None
            manifest: dict[str, Any] = {}
            edge_precision: dict[str, Any] = {}
            if db_path.exists() and mf_path.exists():
                try:
                    manifest = json.loads(mf_path.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.debug("Failed reading manifest for %s: %s", repo_id, e)
                try:
                    if service is None:
                        service = RetrievalService(config, self.config_path)
                    response = service.status(repo_id)  # M7.6 status: manifest aggregates, no table scans
                    status_data = {**response.get("data", {}), "freshness": response.get("freshness")}
                    edge_precision = response.get("edge_precision") or {}
                except Exception as e:
                    logger.debug("status failed for %s: %s", repo_id, e)
                    status_data = {"index_schema_version": manifest.get("index_schema_version"), "freshness": "unknown"}

            ambiguous_rate = float(edge_precision.get("ambiguous_rate") or 0.0)
            parsers = manifest.get("parser_versions", {}) if isinstance(manifest, dict) else {}
            results.append(
                {
                    "repo_id": repo_id,
                    "root": repo.root.as_posix(),
                    "allow_symlinks": repo.allow_symlinks,
                    "max_file_bytes": repo.max_file_bytes,
                    "max_files": repo.max_files,
                    "status": classify_repo(status_data),
                    "freshness": (status_data or {}).get("freshness") or "not_indexed",
                    "index_schema_version": (status_data or {}).get("index_schema_version"),
                    "pending_path_count": int((status_data or {}).get("pending_path_count") or 0),
                    "symbols_count": int((status_data or {}).get("symbols_indexed") or manifest.get("symbols_indexed", 0) or 0),
                    "files_count": int((status_data or {}).get("files_indexed") or manifest.get("files_indexed", 0) or 0),
                    "db_size_mb": db_size_mb,
                    "ambiguous_rate": ambiguous_rate,
                    "languages": parsers.get("languages", []) if isinstance(parsers, dict) else [],
                }
            )

        self._cached_repos = results
        return results

    def repo_detail(self, repo_id: str) -> dict[str, Any]:
        """Languages, edge precision and entry points of one repository (worker-side, read only)."""
        idx_dir = self.get_index_dir()
        db_path = database_path(idx_dir, repo_id)
        mf_path = manifest_path(idx_dir, repo_id)
        if not db_path.exists() or not mf_path.exists():
            return {"repo_id": repo_id, "indexed": False}
        manifest = json.loads(mf_path.read_text(encoding="utf-8"))
        parsers = manifest.get("parser_versions", {})
        resolved_rate: float | None = None
        precision = manifest.get("edge_precision")
        if isinstance(precision, dict) and precision.get("resolved_rate") is not None:
            resolved_rate = float(precision["resolved_rate"])
        else:  # older snapshot: count once
            try:
                con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
                total, ambiguous = con.execute(
                    "SELECT count(*), count(CASE WHEN status='ambiguous' THEN 1 END) FROM edges"
                ).fetchone()
                con.close()
                resolved_rate = ((total - ambiguous) / total) if total else None
            except Exception:
                resolved_rate = None
        return {
            "repo_id": repo_id,
            "indexed": True,
            "languages": parsers.get("languages", []),
            "resolved_rate": resolved_rate,
            "entry_points": manifest.get("entry_points", []),
        }

    def fetch_active_servers(self) -> list[dict[str, Any]]:
        """Heartbeats of the MCP servers currently running (read only, worker-side)."""
        from token_context_mcp.security.governance_store import GovernanceStore

        db = self.config_path.parent / "governance.sqlite"
        if not db.exists():
            return []
        return GovernanceStore(db).get_active_servers(stale_threshold_sec=60)

    def add_repository(self, repo_id: str, root_path: str | Path) -> dict[str, Any]:
        repo_id = validate_repo_id(repo_id.strip())
        root = canonical_repository_root(Path(root_path))
        repo = register_repository(self.config_path, repo_id, root)
        self.invalidate_cache()
        return {"repo_id": repo.repo_id, "root": repo.root.as_posix()}

    def delete_repository(self, repo_id: str, purge_db: bool = False) -> None:
        unregister_repository(self.config_path, repo_id)
        if purge_db:
            idx_dir = self.get_index_dir()
            db_file = database_path(idx_dir, repo_id)
            mf_file = manifest_path(idx_dir, repo_id)
            if db_file.exists():
                db_file.unlink(missing_ok=True)
            if mf_file.exists():
                mf_file.unlink(missing_ok=True)
        self.invalidate_cache()

    def get_server_config(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        return {
            "max_request_bytes": config.server.max_request_bytes,
            "max_result_tokens": config.server.max_result_tokens,
            "max_graph_nodes": config.server.max_graph_nodes,
            "max_symbol_results": config.server.max_symbol_results,
            "network_policy": config.server.network_policy,
            "output_mode": config.server.output_mode,
            "default_view": config.server.default_view,
            "enable_extensions": config.server.enable_extensions,
        }

    def update_server_config(self, settings: dict[str, Any]) -> None:
        import dataclasses
        from token_context_mcp.models import ServerConfig
        config = load_config(self.config_path)
        valid_keys = {f.name for f in dataclasses.fields(ServerConfig)}
        filtered = {k: v for k, v in settings.items() if k in valid_keys}
        new_server = dataclasses.replace(config.server, **filtered)
        new_app = dataclasses.replace(config, server=new_server)
        save_config(self.config_path, new_app)
        self.invalidate_cache()


def kill_process_tree(pid: int, *, grace_seconds: float = 3.0) -> list[int]:
    """Stop ``pid`` and everything below it (pool workers included); returns the pids that were signalled.

    Children first (so no orphan keeps running once the parent is gone), then the parent; whatever ignores
    SIGTERM within the grace period is killed.
    """
    try:
        parent = psutil.Process(pid)
        family = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return []
    for proc in family:
        try:
            proc.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(family, timeout=grace_seconds)
    for proc in alive:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=grace_seconds)
    return [proc.pid for proc in family]


class IndexProcess(QObject):
    """Indexing in a child process (M8.3): ``python -m token_context_mcp index ... --progress-format ndjson``.

    The GUI parses the NDJSON lines and forwards at most ten progress updates per second; Cancel stops the whole
    process tree. Signals keep the names of the old ``IndexWorker`` (``index_failed`` also reports a cancel, with
    ``cancelled`` True).
    """

    progress_changed = Signal(str, int, int)  # stage message, current, total
    index_finished = Signal(str, dict)        # repo_id ("*" for --all), manifest / summary
    index_failed = Signal(str, str)           # repo_id, error message
    log_emitted = Signal(str)

    FLUSH_INTERVAL_MS = 100
    STAGE_LABELS = {
        "scan": "Scanning files",
        "roles": "Assigning structural roles",
        "edges": "Resolving lexical graph edges",
        "ranks": "Computing global symbol PageRank",
        "write": "Writing atomic SQLite snapshot",
        "other": "Indexing",
    }

    def __init__(
        self,
        repo_id: str | None,
        config_path: Path | None = None,
        parent: QObject | None = None,
        *,
        all_repos: bool = False,
        command: tuple[str, list[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.repo_id = "*" if all_repos else (repo_id or "")
        self.all_repos = all_repos
        self.config_path = config_path or default_config_path()
        self._command = command
        self._process: QProcess | None = None
        self._out_buffer = ""
        self._latest: tuple[str, int, int] | None = None
        self._log: list[str] = []
        self._stderr_tail: list[str] = []
        self._result: dict[str, Any] | None = None
        self.cancelled = False
        self.killed_pids: list[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(self.FLUSH_INTERVAL_MS)
        self._timer.timeout.connect(self._flush)

    # -- control ------------------------------------------------------------------------------------------------
    def build_command(self) -> tuple[str, list[str]]:
        if self._command is not None:
            return self._command
        args = ["-m", "token_context_mcp", "index"]
        args += ["--all"] if self.all_repos else ["--repo-id", self.repo_id]
        args += ["--config", str(self.config_path), "--progress-format", "ndjson"]
        return sys.executable, args

    def start(self) -> None:
        program, args = self.build_command()
        self._process = QProcess(self)
        self._process.setProgram(program)
        self._process.setArguments(args)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._log.append(f"Starting index build for '{self.repo_id}' (child process)...")
        self._process.start()  # asynchronous: no waitForStarted on the UI thread
        self._timer.start()

    def isRunning(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def pid(self) -> int:
        return int(self._process.processId()) if self._process is not None else 0

    def cancel(self) -> None:
        if not self.isRunning():
            return
        self.cancelled = True
        pid = self.pid()
        self._log.append(f"Cancelling index of '{self.repo_id}' (process tree of PID {pid})...")
        if pid:
            self.killed_pids = kill_process_tree(pid)
        elif self._process is not None:
            self._process.kill()

    # -- output -------------------------------------------------------------------------------------------------
    def _on_stdout(self) -> None:
        if self._process is None:
            return
        self._out_buffer += self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        *lines, self._out_buffer = self._out_buffer.split("\n")
        for line in lines:
            self._handle_line(line.strip())

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            event = json.loads(line)
        except ValueError:
            self._log.append(line)
            return
        stage = event.get("stage")
        if stage == "done":
            self._result = event.get("manifest") or {}
        elif stage == "all_done":
            self._result = event.get("summary") or {}
        elif stage is not None:
            label = self.STAGE_LABELS.get(str(stage), str(stage))
            repo = event.get("repo_id")
            message = f"[{repo}] {label}" if repo else label
            self._latest = (message, int(event.get("current") or 0), int(event.get("total") or 0))

    def _on_stderr(self) -> None:
        if self._process is None:
            return
        text = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                self._log.append(f"[stderr] {line}")
                self._stderr_tail = (self._stderr_tail + [line])[-8:]

    def _flush(self) -> None:
        """Called every 100 ms: at most ten UI updates per second, whatever the child prints."""
        if self._latest is not None:
            message, current, total = self._latest
            self._latest = None
            self.progress_changed.emit(message, current, total)
        if self._log:
            chunk, self._log = "\n".join(self._log), []
            self.log_emitted.emit(chunk)

    def _on_error(self, error: Any) -> None:
        if self._process is not None and self._process.state() == QProcess.ProcessState.NotRunning and not self.cancelled:
            self._log.append(f"Index process error: {error}")

    def _on_finished(self, exit_code: int, exit_status: Any) -> None:
        self._timer.stop()
        if self._process is not None:
            self._on_stdout()
            self._on_stderr()
        if self._out_buffer.strip():
            self._handle_line(self._out_buffer.strip())
            self._out_buffer = ""
        self._flush()
        if self.cancelled:
            self.index_failed.emit(self.repo_id, "Cancelled")
        elif exit_code == 0 and self._result is not None:
            self.progress_changed.emit("Complete", 100, 100)
            self.index_finished.emit(self.repo_id, self._result)
        else:
            detail = " | ".join(self._stderr_tail) or f"exit code {exit_code}"
            if self._result and self.all_repos and self._result.get("failed"):
                detail = f"{self._result['failed']} repository(ies) failed"
            self.index_failed.emit(self.repo_id, detail)


class ServerController(QObject):
    """Client-configuration generator (M8.7, D2).

    The GUI no longer starts, stops or restarts an MCP server: a stdio server belongs to the client that spawns it,
    and a process started here never had a client. Running servers are listed from their heartbeats instead.
    """

    # flags per client, from docs/CLIENT_MATRIX.md (only what the matrix recommends)
    CLIENTS: dict[str, dict[str, Any]] = {
        "claude": {"style": "mcpServers", "flags": []},
        "claude-code": {"style": "mcpServers", "flags": ["--output-mode", "structured"]},
        "vscode": {"style": "servers", "flags": ["--output-mode", "text"]},
        "antigravity": {"style": "mcpServers", "flags": ["--schema-profile", "gemini_safe", "--output-mode", "text"]},
        "codex": {"style": "codex_toml", "flags": ["--output-mode", "text"]},
        "cursor": {"style": "mcpServers", "flags": []},
    }

    def __init__(self, config_path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config_path = config_path or default_config_path()

    def get_client_config(self, client: str = "claude") -> str:
        """Ready-to-paste configuration for ``client`` (unknown names get the ``mcpServers`` shape)."""
        key = client.lower()
        key = {"copilot": "vscode"}.get(key, key)
        spec = self.CLIENTS.get(key, {"style": "mcpServers", "flags": []})
        python_exec = sys.executable.replace("\\", "/")
        config_path_posix = str(self.config_path).replace("\\", "/")
        args = ["-m", "token_context_mcp", "serve", "--transport", "stdio", "--config", config_path_posix, *spec["flags"]]
        if spec["style"] == "codex_toml":
            rendered = ", ".join(json.dumps(a) for a in args)
            return f'[mcp_servers.token-context]\ncommand = {json.dumps(python_exec)}\nargs = [{rendered}]\n'
        entry: dict[str, Any] = {"command": python_exec, "args": args}
        if spec["style"] == "servers":
            return json.dumps({"servers": {"token-context": {"type": "stdio", **entry}}}, indent=2)
        return json.dumps({"mcpServers": {"token-context": entry}}, indent=2)


class CacheManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_config_path()

    def get_storage_stats(self) -> dict[str, Any]:
        idx_dir = index_directory(self.config_path)
        total_bytes = 0
        repo_dbs: list[dict[str, Any]] = []

        if idx_dir.exists():
            for sqlite_file in idx_dir.glob("*.sqlite"):
                sz = sqlite_file.stat().st_size
                total_bytes += sz
                repo_id = sqlite_file.name.split(".", 1)[0]
                repo_dbs.append(
                    {
                        "repo_id": repo_id,
                        "file_name": sqlite_file.name,
                        "size_mb": round(sz / (1024 * 1024), 2),
                        "path": str(sqlite_file),
                    }
                )

        # Check episodic memory DB
        memory_db = self.config_path.parent / "memory.sqlite"
        memory_size_mb = 0.0
        if memory_db.exists():
            sz = memory_db.stat().st_size
            total_bytes += sz
            memory_size_mb = round(sz / (1024 * 1024), 2)

        return {
            "total_size_mb": round(total_bytes / (1024 * 1024), 2),
            "indexes_directory": str(idx_dir),
            "databases_count": len(repo_dbs),
            "databases": repo_dbs,
            "memory_db_size_mb": memory_size_mb,
        }

    # M8.9: only databases that are written in place may be vacuumed. Index snapshots are immutable (VACUUM would
    # change their bytes and break artifact_sha256), so they are not even offered.
    VACUUMABLE_DBS = ("memory.sqlite", "governance.sqlite", "audit.sqlite")
    VACUUM_RETRIES = 3
    VACUUM_BACKOFF_SECONDS = 0.5

    def vacuum_targets(self) -> list[dict[str, Any]]:
        """The databases the user may pick from: name, path, size in bytes (existing ones only)."""
        found: list[dict[str, Any]] = []
        for name in self.VACUUMABLE_DBS:
            path = self.config_path.parent / name
            if path.is_file():
                found.append({"name": name, "path": str(path), "size_bytes": path.stat().st_size})
        return found

    def vacuum_one(self, name: str) -> dict[str, Any]:
        """VACUUM one mutable database; retries ``database is locked`` three times (0.5 s, 1 s, 1.5 s backoff).

        Returns ``{"name", "status": "ok"|"error", "reclaimed_bytes", "error"}``; never raises for a database error.
        """
        if name not in self.VACUUMABLE_DBS:
            raise ValueError(f"{name!r} cannot be vacuumed: only {', '.join(self.VACUUMABLE_DBS)} are mutable databases")
        path = self.config_path.parent / name
        if not path.is_file():
            return {"name": name, "status": "error", "reclaimed_bytes": 0, "error": "database does not exist"}
        before = path.stat().st_size
        last_error = ""
        for attempt in range(self.VACUUM_RETRIES + 1):
            try:
                con = sqlite3.connect(str(path), timeout=0.2)
                try:
                    con.execute("VACUUM;")
                finally:
                    con.close()
                after = path.stat().st_size
                return {"name": name, "status": "ok", "reclaimed_bytes": max(0, before - after), "error": ""}
            except sqlite3.OperationalError as exc:
                last_error = str(exc)
                if "locked" not in last_error.lower() or attempt == self.VACUUM_RETRIES:
                    break
                time.sleep(self.VACUUM_BACKOFF_SECONDS * (attempt + 1))
            except Exception as exc:  # noqa: BLE001 - reported per database
                last_error = str(exc)
                break
        logger.warning("VACUUM of %s failed: %s", name, last_error)
        return {"name": name, "status": "error", "reclaimed_bytes": 0, "error": last_error}

    def vacuum_databases(self, names: list[str]) -> list[dict[str, Any]]:
        return [self.vacuum_one(name) for name in names]

    def clean_stale_snapshots(self) -> list[str]:
        """Remove SQLite files for repos no longer registered in repos.toml."""
        config = load_config(self.config_path)
        idx_dir = index_directory(self.config_path)
        removed: list[str] = []

        if not idx_dir.exists():
            return removed

        active_repos = set(config.repositories.keys())
        for sqlite_file in idx_dir.glob("*.sqlite"):
            repo_id = sqlite_file.name.split(".", 1)[0]
            if repo_id not in active_repos:
                mf_file = manifest_path(idx_dir, repo_id)
                sqlite_file.unlink(missing_ok=True)
                mf_file.unlink(missing_ok=True)
                ptr_file = current_pointer_path(idx_dir, repo_id)
                ptr_file.unlink(missing_ok=True)
                removed.append(repo_id)

        # Also garbage collect old snapshots for active repos
        for repo_id in active_repos:
            ptr = current_pointer_path(idx_dir, repo_id)
            current_db = ""
            if ptr.is_file():
                try:
                    current_db = json.loads(ptr.read_text(encoding="utf-8")).get("db", "")
                except Exception:
                    pass
            removed_gc = gc_snapshots(idx_dir, repo_id, current_db_name=current_db)
            removed.extend(removed_gc)

        return removed

    def purge_all_cache(self) -> int:
        """Delete all indexed databases while keeping repos.toml intact."""
        idx_dir = index_directory(self.config_path)
        count = 0
        if idx_dir.exists():
            for f in idx_dir.glob("*.*"):
                f.unlink(missing_ok=True)
                count += 1
        return count


class GovernanceRefreshWorker(QThread):
    """Read-only background worker that polls governance.sqlite for live server/agent state.

    This thread NEVER writes to the GovernanceStore — it only reads, so the GUI
    acts as a passive observer of the running MCP server processes.
    """

    servers_updated = Signal(list)   # list of server heartbeat dicts
    agents_refreshed = Signal(list)  # list of merged agent dicts
    halt_state_changed = Signal(bool, str)  # is_halted, reason

    def __init__(
        self,
        governance_db_path: Path,
        interval_sec: float = 5.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.governance_db_path = governance_db_path
        self.interval_sec = interval_sec
        self._running = True

    def run(self) -> None:
        while self._running:
            self._poll_once()
            for _ in range(int(self.interval_sec * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def _poll_once(self) -> None:
        if not self.governance_db_path.exists():
            return
        try:
            from token_context_mcp.security.governance_store import GovernanceStore
            store = GovernanceStore(self.governance_db_path)
            # Read-only queries only
            servers = store.get_active_servers(stale_threshold_sec=60)
            agents = store.list_agents()
            is_halted, halt_reason = store.is_emergency_halted()
            store.close()

            self.servers_updated.emit(servers)
            self.agents_refreshed.emit(agents)
            self.halt_state_changed.emit(is_halted, halt_reason)
        except Exception as exc:
            logger.debug("GovernanceRefreshWorker poll error: %s", exc)

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


class AgentSecurityController(QObject):
    """Bridge for Agent Access Control, Mutex Lock Management, and Audit Log Telemetry."""

    agents_updated = Signal(list)     # list of agent dicts
    locks_updated = Signal(list)      # list of lock dicts
    audit_logs_updated = Signal(list) # list of audit log dicts
    emergency_state_changed = Signal(bool, str) # is_halted, reason
    active_servers_updated = Signal(list)  # list of server heartbeat dicts (M2.5)

    def __init__(self, config_path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config_path = config_path or default_config_path()
        from token_context_mcp.security.access_control import AccessControlManager, PolicyProfile
        from token_context_mcp.security.audit import AuditLogger
        from token_context_mcp.security.governance_store import GovernanceStore
        from token_context_mcp.memory.store import MemoryStore

        governance_db = self.config_path.parent / "governance.sqlite"
        self._governance = GovernanceStore(governance_db)
        self._access_control = AccessControlManager(store=self._governance)
        self._audit_logger = AuditLogger(self.config_path.parent / "audit.sqlite")
        self._memory_store = MemoryStore(self.config_path.parent / "memory.sqlite")

        # M2.5: connect GovernanceRefreshWorker to poll live server heartbeats
        self._governance_refresh_worker: GovernanceRefreshWorker | None = None
        self._start_governance_refresh(governance_db)

    def _start_governance_refresh(self, governance_db: Path) -> None:
        """Start background read-only governance polling (M2.5)."""
        if self._governance_refresh_worker and self._governance_refresh_worker.isRunning():
            return
        worker = GovernanceRefreshWorker(governance_db, interval_sec=5.0, parent=self)
        worker.servers_updated.connect(self.active_servers_updated.emit)
        worker.agents_refreshed.connect(self._on_governance_agents)
        worker.halt_state_changed.connect(self._on_governance_halt)
        worker.start()
        self._governance_refresh_worker = worker

    def _on_governance_agents(self, governance_agents: list[dict[str, Any]]) -> None:
        """Merge governance agents into local view (read-only merge, no mutation)."""
        local_agents = self._access_control.list_agents()
        local_ids = {a["agent_id"] for a in local_agents}
        # Add agents seen by the live server but not yet in local view
        for ga in governance_agents:
            if ga["agent_id"] not in local_ids:
                local_agents.append(ga)
                local_ids.add(ga["agent_id"])
        self.agents_updated.emit(local_agents)

    def _on_governance_halt(self, is_halted: bool, reason: str) -> None:
        """Reflect server-side halt state in the GUI (read-only)."""
        self.emergency_state_changed.emit(is_halted, reason or self._access_control.emergency_reason)

    @property
    def access_control(self) -> Any:
        return self._access_control

    @property
    def is_emergency_halted(self) -> bool:
        return self._access_control.is_emergency_halted

    @property
    def emergency_reason(self) -> str:
        return self._access_control.emergency_reason

    def refresh_data(self) -> None:
        """Synchronous refresh (collect + apply). The GUI uses collect_snapshot() in a worker instead."""
        self.apply_snapshot(self.collect_snapshot())

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        """UI-thread half of a refresh: only emits the signals the tab renders from."""
        self.agents_updated.emit(snapshot["agents"])
        self.locks_updated.emit(snapshot["locks"])
        self.audit_logs_updated.emit(snapshot["logs"])
        self.emergency_state_changed.emit(snapshot["halted"], snapshot["halt_reason"])

    def collect_snapshot(self) -> dict[str, Any]:
        """Worker-side half of a refresh: reads governance, memory and audit databases, touches no widget."""
        from token_context_mcp.security.governance_store import merge_seen_agents

        agents = self._access_control.list_agents()
        locks = self._memory_store.list_active_locks()
        logs = self._audit_logger.query_logs(limit=50)
        active_servers = self._governance.get_active_servers()

        traces: list[dict[str, Any]] = []
        for l in locks:
            ag_id = l.get("agent_id")
            if ag_id:
                traces.append({"agent_id": ag_id, "role": "external_agent"})
        for log_entry in logs:
            ag_id = log_entry.get("agent_id")
            if ag_id and ag_id not in ("anonymous", "admin"):
                traces.append({"agent_id": ag_id, "role": "external_client"})
        for srv in active_servers:
            srv_id = srv.get("server_id")
            if srv_id:
                traces.append({"agent_id": srv_id, "role": "server_node"})

        merged = merge_seen_agents(agents, traces)
        return {
            "agents": merged,
            "locks": locks,
            "logs": logs,
            "halted": self._access_control.is_emergency_halted,
            "halt_reason": self._access_control.emergency_reason,
        }


    def pause_agent(self, agent_id: str, reason: str = "Paused by user via Desktop GUI") -> None:
        self._access_control.pause_agent(agent_id, reason)
        self.refresh_data()

    def resume_agent(self, agent_id: str) -> None:
        self._access_control.resume_agent(agent_id)
        self.refresh_data()

    def block_agent(self, agent_id: str, reason: str = "Blocked by user via Desktop GUI") -> None:
        self._access_control.block_agent(agent_id, reason)
        self.refresh_data()

    def unblock_agent(self, agent_id: str) -> None:
        self._access_control.unblock_agent(agent_id)
        self.refresh_data()

    def set_agent_policy(self, agent_id: str, policy_str: str) -> None:
        from token_context_mcp.security.access_control import PolicyProfile
        try:
            policy = PolicyProfile(policy_str)
            self._access_control.set_agent_policy(agent_id, policy)
            self.refresh_data()
        except Exception:
            pass

    def revoke_agent_locks(self, agent_id: str) -> int:
        count = self._memory_store.revoke_agent_locks(agent_id)
        self.refresh_data()
        return count

    def revoke_all_locks(self) -> int:
        count = self._memory_store.revoke_all_locks()
        self.refresh_data()
        return count

    def emergency_halt(self, reason: str = "Emergency Stop triggered from Desktop GUI") -> None:
        self._access_control.emergency_halt(reason)
        self.emergency_state_changed.emit(True, reason)
        self.refresh_data()

    def emergency_resume(self) -> None:
        self._access_control.emergency_resume()
        self.emergency_state_changed.emit(False, "")
        self.refresh_data()

    def close(self) -> None:
        if self._governance_refresh_worker and self._governance_refresh_worker.isRunning():
            self._governance_refresh_worker.stop()
        try:
            self._audit_logger.close()
        except Exception:
            pass

