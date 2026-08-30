from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

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
from token_context_mcp.index.runner import build_index
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
    index.add_argument("--repo-id", required=True)
    index.add_argument("--config", type=Path, default=default_config_path())
    index.add_argument("--network-policy", default="declared-deny-not-enforced")
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
            config = load_config(args.config)
            repository = get_repository(config, args.repo_id)
            _emit(build_index(repository, index_directory(args.config), network_policy=args.network_policy))
        elif args.command == "harden":
            _emit(harden_registry(args.config, check_only=args.check))
        elif args.command == "status":
            service = RetrievalService(load_config(args.config), args.config)
            _emit(service.status(args.repo_id))
        elif args.command == "serve":
            run_stdio(args.config)
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


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
