from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import TextIO

from token_context_mcp import __version__
from token_context_mcp.config import (
    ConfigError,
    default_config_path,
    get_repository,
    index_directory,
    load_config,
    register_repository,
    unregister_repository,
    update_repository,
)
from token_context_mcp.index.runner import build_index, stage_of_message
from token_context_mcp.release import write_release_materials
from token_context_mcp.retrieve.service import RetrievalService
from token_context_mcp.security.local_privacy import harden_registry
from token_context_mcp.server import run_stdio
from token_context_mcp.telemetry.benchmark import load_runs, summarize


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-context", description="Read-only local code-context MCP server")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser("register", help="Register a repository root (admin-only)")
    register.add_argument("--repo-id", required=True)
    register.add_argument("--root", required=True, type=Path)
    register.add_argument("--config", type=Path, default=default_config_path())
    unregister = subparsers.add_parser("unregister", help="Remove a repository from the local registry (admin-only)")
    unregister.add_argument("--repo-id", required=True)
    unregister.add_argument("--config", type=Path, default=default_config_path())
    update = subparsers.add_parser("update", help="Update a registered repository root (admin-only)")
    update.add_argument("--repo-id", required=True)
    update.add_argument("--root", required=True, type=Path)
    update.add_argument("--force", action="store_true", help="Acknowledge that the registered root will change")
    update.add_argument("--config", type=Path, default=default_config_path())
    index = subparsers.add_parser("index", help="Build a local immutable snapshot (admin-only)")
    target = index.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo-id", help="Index one registered repository")
    target.add_argument("--all", action="store_true", help="Index every registered repository (JSON summary)")
    index.add_argument("--config", type=Path, default=default_config_path())
    index.add_argument("--network-policy", default="declared-deny-not-enforced")
    index.add_argument(
        "--progress-format",
        choices=["none", "ndjson"],
        default="none",
        help='"ndjson": one JSON object per line on stdout ({"stage","current","total","ts"}, at most 10 per second), '
        'the last one {"stage":"done","manifest":{...}}; logs stay on stderr',
    )
    index.add_argument("--workers", type=int, default=None, help="Parser worker processes (default: min(8, CPUs - 1))")
    index.add_argument(
        "--verify-hashes",
        action="store_true",
        help="Read and hash every file instead of trusting (size, mtime_ns) of unchanged files",
    )
    index.add_argument("--full", action="store_true", help="Ignore the active snapshot and index from scratch")
    index.add_argument("--watch", action="store_true", help="Keep running: re-index after the working tree settles")
    index.add_argument("--debounce", type=float, default=1.5, help="--watch: quiet time before re-indexing (seconds)")
    index.add_argument("--poll-interval", type=float, default=2.0, help="--watch without watchdog: poll period (seconds)")
    harden = subparsers.add_parser("harden", help="Restrict the registry and snapshots to the owning account")
    harden.add_argument("--config", type=Path, default=default_config_path())
    harden.add_argument("--check", action="store_true", help="Report current permissions without changing them")
    status = subparsers.add_parser("status", help="Read active snapshot status")
    status.add_argument("--repo-id", required=True)
    status.add_argument("--config", type=Path, default=default_config_path())
    serve = subparsers.add_parser("serve", help="Start the read-only MCP stdio server")
    serve.add_argument("--config", type=Path, default=default_config_path())
    serve.add_argument("--transport", choices=["stdio"], default="stdio")
    serve.add_argument("--network-policy", default="declared-deny-not-enforced")
    serve.add_argument("--enable-admin-tools", action="store_true", default=False, help="Enable admin tools (agent_control, audit_logs)")
    report = subparsers.add_parser("benchmark-report", help="Summarize an instrumented benchmark JSONL")
    report.add_argument("--input", type=Path, required=True)
    report.add_argument("--output", type=Path)
    report.add_argument("--baseline", default="B0")
    materials = subparsers.add_parser("release-materials", help="Generate unsigned local SBOM/provenance starter artifacts")
    materials.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "register":
            repository = register_repository(args.config, args.repo_id, args.root)
            _emit({"repo_id": repository.repo_id, "root": repository.root.as_posix(), "config": str(args.config)})
        elif args.command == "unregister":
            repository = unregister_repository(args.config, args.repo_id)
            _emit({"repo_id": repository.repo_id, "root": repository.root.as_posix(), "config": str(args.config)})
        elif args.command == "update":
            repository = update_repository(args.config, args.repo_id, args.root, force=args.force)
            _emit({"repo_id": repository.repo_id, "root": repository.root.as_posix(), "config": str(args.config)})
        elif args.command == "index":
            return _run_index(args)
        elif args.command == "harden":
            _emit(harden_registry(args.config, check_only=args.check))
        elif args.command == "status":
            service = RetrievalService(load_config(args.config), args.config)
            _emit(service.status(args.repo_id))
        elif args.command == "serve":
            run_stdio(args.config, enable_admin_tools=args.enable_admin_tools)
        elif args.command == "benchmark-report":
            report = summarize(load_runs(args.input), baseline=args.baseline)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _emit(report)
        elif args.command == "release-materials":
            _emit({key: str(value) for key, value in write_release_materials(Path.cwd(), args.output).items()})
        return 0
    except (ConfigError, ValueError, RuntimeError, OSError) as error:
        logging.getLogger("token_context_mcp").error("%s", error)
        return 2


class _NdjsonProgress:
    """Progress lines for ``index --progress-format ndjson``: at most ten per second, ``done`` always goes out."""

    MIN_INTERVAL = 0.1

    def __init__(self, stream: TextIO | None = None, repo_id: str | None = None) -> None:
        self._stream = stream or sys.stdout
        self._repo_id = repo_id
        self._last = 0.0

    def __call__(self, message: str, current: int, total: int) -> None:
        now = time.monotonic()
        if now - self._last < self.MIN_INTERVAL:
            return
        self._last = now
        self._write({"stage": stage_of_message(message), "current": current, "total": total})

    def done(self, manifest: dict[str, object]) -> None:
        self._write({"stage": "done", "manifest": manifest})

    def _write(self, payload: dict[str, object]) -> None:
        line = {**payload, "ts": round(time.time(), 3)}
        if self._repo_id is not None:
            line["repo_id"] = self._repo_id
        self._stream.write(json.dumps(line, sort_keys=True, default=str) + "\n")
        self._stream.flush()


def _index_kwargs(args: argparse.Namespace) -> dict[str, object]:
    kwargs: dict[str, object] = {"verify_hashes": args.verify_hashes, "full_rebuild": args.full}
    if args.workers is not None:
        kwargs["workers"] = max(1, args.workers)
    return kwargs


def _run_index(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    directory = index_directory(args.config)
    ndjson = args.progress_format == "ndjson"
    if args.all:
        return _index_all(config, directory, args, ndjson)
    repository = get_repository(config, args.repo_id)
    progress = _NdjsonProgress(repo_id=None) if ndjson else None
    kwargs = _index_kwargs(args)
    if args.watch:
        from token_context_mcp.index.watch import watch_index

        def show(manifest: dict[str, object]) -> None:
            if progress is not None:
                progress.done(manifest)
            else:
                _emit(manifest)

        # each run gets a fresh progress callback so the rate limiter starts clean
        watch_index(
            repository,
            directory,
            network_policy=args.network_policy,
            debounce_seconds=args.debounce,
            poll_seconds=args.poll_interval,
            on_index=show,
            index_kwargs={**kwargs, **({"progress_callback": progress} if progress is not None else {})},
        )
        return 0
    manifest = build_index(
        repository,
        directory,
        network_policy=args.network_policy,
        progress_callback=progress,
        **kwargs,
    )
    if progress is not None:
        progress.done(manifest)
    else:
        _emit(manifest)
    return 0


def _index_all(config: object, directory: Path, args: argparse.Namespace, ndjson: bool) -> int:
    repositories = getattr(config, "repositories")
    if args.watch:
        raise ValueError("--watch works on one repository; use --repo-id")
    kwargs = _index_kwargs(args)
    results: list[dict[str, object]] = []
    for repo_id in sorted(repositories):
        started = time.perf_counter()
        progress = _NdjsonProgress(repo_id=repo_id) if ndjson else None
        try:
            manifest = build_index(
                repositories[repo_id],
                directory,
                network_policy=args.network_policy,
                progress_callback=progress,
                **kwargs,
            )
        except (ValueError, RuntimeError, OSError) as error:
            logging.getLogger("token_context_mcp").error("index %s failed: %s", repo_id, error)
            results.append({"repo_id": repo_id, "ok": False, "error": f"{type(error).__name__}: {error}"})
            continue
        if progress is not None:
            progress.done(manifest)
        results.append(
            {
                "repo_id": repo_id,
                "ok": True,
                "seconds": round(time.perf_counter() - started, 3),
                "incremental": manifest.get("incremental"),
                "files_indexed": manifest.get("files_indexed"),
                "files_reparsed": manifest.get("files_reparsed"),
                "symbols_indexed": manifest.get("symbols_indexed"),
                "edges_indexed": manifest.get("edges_indexed"),
                "index_run_id": manifest.get("index_run_id"),
            }
        )
    failed = [item for item in results if not item["ok"]]
    summary = {"repositories": results, "indexed": len(results) - len(failed), "failed": len(failed)}
    if ndjson:
        sys.stdout.write(json.dumps({"stage": "all_done", "summary": summary, "ts": round(time.time(), 3)}, sort_keys=True) + "\n")
        sys.stdout.flush()
    else:
        _emit(summary)
    return 1 if failed else 0


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
