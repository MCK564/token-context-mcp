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
from PySide6.QtCore import QObject, QProcess, QThread, Signal

from token_context_mcp.config import (
    ConfigError,
    default_config_path,
    get_repository,
    index_directory,
    load_config,
    register_repository,
    save_config,
    unregister_repository,
    validate_repo_id,
)
from token_context_mcp.index.runner import build_index, database_path, manifest_path
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

    def __init__(self, parent: QObject | None = None, interval: float = 1.0) -> None:
        super().__init__(parent)
        self.interval = interval
        self._running = True
        self._ai_hardware = detect_ai_hardware()

    def run(self) -> None:
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


class RepoManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or default_config_path()

    def get_index_dir(self) -> Path:
        return index_directory(self.config_path)

    def list_repositories(self) -> list[dict[str, Any]]:
        config = load_config(self.config_path)
        idx_dir = self.get_index_dir()
        results: list[dict[str, Any]] = []

        service = None
        try:
            service = RetrievalService(config, self.config_path)
        except Exception:
            pass

        for repo_id in sorted(config.repositories):
            repo = config.repositories[repo_id]
            db_path = database_path(idx_dir, repo_id)
            mf_path = manifest_path(idx_dir, repo_id)

            db_size_mb = 0.0
            if db_path.exists():
                db_size_mb = round(db_path.stat().st_size / (1024 * 1024), 2)

            freshness = "not_indexed"
            symbols_count = 0
            files_count = 0
            ambiguous_rate = 0.0
            languages: list[str] = []

            if service and db_path.exists():
                try:
                    stat = service.status(repo_id)
                    freshness = stat.get("freshness", "unknown")
                    data = stat.get("data", {})
                    metadata = data.get("metadata", {})
                    symbols_count = int(metadata.get("symbols_indexed", 0))
                    files_count = int(metadata.get("files_indexed", 0))

                    edge_prec = data.get("edge_precision", {})
                    edges_total = edge_prec.get("edges_total", 0)
                    edges_ambig = edge_prec.get("edges_ambiguous", 0)
                    if edges_total > 0:
                        ambiguous_rate = round((edges_ambig / edges_total) * 100, 1)

                    parser_versions = metadata.get("parser_versions", {})
                    languages = parser_versions.get("languages", [])
                except Exception as e:
                    logger.debug("Failed getting status for %s: %s", repo_id, e)
                    if db_path.exists():
                        freshness = "indexed"

            results.append(
                {
                    "repo_id": repo_id,
                    "root": repo.root.as_posix(),
                    "allow_symlinks": repo.allow_symlinks,
                    "max_file_bytes": repo.max_file_bytes,
                    "max_files": repo.max_files,
                    "freshness": freshness,
                    "symbols_count": symbols_count,
                    "files_count": files_count,
                    "db_size_mb": db_size_mb,
                    "ambiguous_rate": ambiguous_rate,
                    "languages": languages,
                }
            )
        return results

    def add_repository(self, repo_id: str, root_path: str | Path) -> dict[str, Any]:
        repo_id = validate_repo_id(repo_id.strip())
        root = canonical_repository_root(Path(root_path))
        repo = register_repository(self.config_path, repo_id, root)
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


class IndexWorker(QThread):
    progress_changed = Signal(str, int, int)  # stage_message, current, total
    index_finished = Signal(str, dict)        # repo_id, manifest
    index_failed = Signal(str, str)          # repo_id, error_message
    log_emitted = Signal(str)

    def __init__(self, repo_id: str, config_path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.repo_id = repo_id
        self.config_path = config_path or default_config_path()

    def run(self) -> None:
        self.log_emitted.emit(f"Starting index build for '{self.repo_id}'...")
        try:
            config = load_config(self.config_path)
            repo = get_repository(config, self.repo_id)
            idx_dir = index_directory(self.config_path)

            def _progress_cb(msg: str, current: int, total: int) -> None:
                self.progress_changed.emit(msg, current, total)
                self.log_emitted.emit(f"[{self.repo_id}] {msg} ({current}/{total})")

            manifest = build_index(
                repo,
                idx_dir,
                network_policy=config.server.network_policy,
                progress_callback=_progress_cb,
            )
            self.progress_changed.emit("Complete", 100, 100)
            self.log_emitted.emit(f"Index successfully built for '{self.repo_id}'! Indexed {manifest.get('symbols_indexed')} symbols.")
            self.index_finished.emit(self.repo_id, manifest)
        except Exception as e:
            err_msg = str(e)
            self.log_emitted.emit(f"Index FAILED for '{self.repo_id}': {err_msg}")
            self.index_failed.emit(self.repo_id, err_msg)


class ServerController(QObject):
    status_changed = Signal(str, int)  # status, pid
    log_received = Signal(str)

    def __init__(self, config_path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config_path = config_path or default_config_path()
        self._process: QProcess | None = None
        self._status = "STOPPED"
        self._pid = 0

    @property
    def status(self) -> str:
        return self._status

    @property
    def pid(self) -> int:
        return self._pid

    def start_server(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            return

        self._status = "STARTING"
        self.status_changed.emit(self._status, 0)
        self.log_received.emit("Starting MCP Server process...")

        self._process = QProcess(self)
        self._process.setProgram(sys.executable)
        self._process.setArguments(["-m", "token_context_mcp", "serve", "--transport", "stdio", "--config", str(self.config_path)])

        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)

        self._process.start()
        if self._process.waitForStarted(3000):
            self._pid = int(self._process.processId())
            self._status = "RUNNING"
            self.status_changed.emit(self._status, self._pid)
            self.log_received.emit(f"MCP Server RUNNING (PID: {self._pid}) on stdio transport.")
        else:
            self._status = "STOPPED"
            self._pid = 0
            self.status_changed.emit(self._status, 0)
            self.log_received.emit("Failed to start MCP Server process.")

    def stop_server(self) -> None:
        if not self._process or self._process.state() == QProcess.ProcessState.NotRunning:
            self._status = "STOPPED"
            self._pid = 0
            self.status_changed.emit(self._status, 0)
            return

        self.log_received.emit("Stopping MCP Server process...")
        self._process.terminate()
        if not self._process.waitForFinished(2000):
            self._process.kill()
        self._status = "STOPPED"
        self._pid = 0
        self.status_changed.emit(self._status, 0)
        self.log_received.emit("MCP Server process stopped.")

    def restart_server(self) -> None:
        self.stop_server()
        self.start_server()

    def _on_stdout(self) -> None:
        if self._process:
            data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
            for line in data.splitlines():
                if line.strip():
                    self.log_received.emit(f"[stdout] {line}")

    def _on_stderr(self) -> None:
        if self._process:
            data = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
            for line in data.splitlines():
                if line.strip():
                    self.log_received.emit(f"[stderr] {line}")

    def _on_finished(self, exit_code: int, exit_status: Any) -> None:
        self._status = "STOPPED"
        self._pid = 0
        self.status_changed.emit(self._status, 0)
        self.log_received.emit(f"MCP Server process exited with code {exit_code}.")

    def get_client_config(self, client: str = "claude") -> str:
        """Generate ready-to-copy client configuration JSON."""
        python_exec = sys.executable.replace("\\", "/")
        config_path_posix = str(self.config_path).replace("\\", "/")

        if client.lower() in ("claude", "cursor"):
            cfg = {
                "mcpServers": {
                    "token-context": {
                        "command": python_exec,
                        "args": [
                            "-m",
                            "token_context_mcp",
                            "serve",
                            "--transport",
                            "stdio",
                            "--config",
                            config_path_posix,
                        ],
                    }
                }
            }
        elif client.lower() in ("vscode", "copilot"):
            cfg = {
                "servers": {
                    "token-context": {
                        "type": "stdio",
                        "command": python_exec,
                        "args": [
                            "-m",
                            "token_context_mcp",
                            "serve",
                            "--transport",
                            "stdio",
                            "--config",
                            config_path_posix,
                        ],
                    }
                }
            }
        else:  # Antigravity
            cfg = {
                "mcpServers": {
                    "token-context": {
                        "command": python_exec,
                        "args": [
                            "-m",
                            "token_context_mcp",
                            "serve",
                            "--transport",
                            "stdio",
                            "--config",
                            config_path_posix,
                        ],
                    }
                }
            }
        return json.dumps(cfg, indent=2)


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
                repo_id = sqlite_file.stem
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

    def vacuum_database(self, repo_id: str | None = None) -> int:
        """Run VACUUM on database(s) and return reclaimed bytes."""
        idx_dir = index_directory(self.config_path)
        reclaimed = 0

        targets: list[Path] = []
        if repo_id:
            targets.append(database_path(idx_dir, repo_id))
        else:
            if idx_dir.exists():
                targets.extend(idx_dir.glob("*.sqlite"))
            mem_db = self.config_path.parent / "memory.sqlite"
            if mem_db.exists():
                targets.append(mem_db)

        for db_path in targets:
            if not db_path.exists():
                continue
            before = db_path.stat().st_size
            try:
                con = sqlite3.connect(str(db_path))
                con.execute("VACUUM;")
                con.close()
                after = db_path.stat().st_size
                if before > after:
                    reclaimed += (before - after)
            except Exception as e:
                logger.debug("Failed vacuuming %s: %s", db_path, e)

        return reclaimed

    def clean_stale_snapshots(self) -> list[str]:
        """Remove SQLite files for repos no longer registered in repos.toml."""
        config = load_config(self.config_path)
        idx_dir = index_directory(self.config_path)
        removed: list[str] = []

        if not idx_dir.exists():
            return removed

        active_repos = set(config.repositories.keys())
        for sqlite_file in idx_dir.glob("*.sqlite"):
            repo_id = sqlite_file.stem
            if repo_id not in active_repos:
                mf_file = manifest_path(idx_dir, repo_id)
                sqlite_file.unlink(missing_ok=True)
                mf_file.unlink(missing_ok=True)
                removed.append(repo_id)

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
