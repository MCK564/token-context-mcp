from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path

from token_context_mcp.constants import DEFAULT_MAX_FILE_BYTES, DEFAULT_MAX_FILES
from token_context_mcp.models import AppConfig, RepositoryConfig, ServerConfig
from token_context_mcp.security.path_policy import canonical_repository_root

_REPO_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ConfigError(ValueError):
    """A local configuration does not satisfy the security contract."""


def default_config_path() -> Path:
    """Return the per-user registry path, independent of a working repository.

    ``TOKEN_CONTEXT_CONFIG`` is an explicit override for portable/team setups.
    The default must not depend on the process working directory because Codex
    starts an MCP process from many different repositories.
    """
    override = os.environ.get("TOKEN_CONTEXT_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if app_data:
            return Path(app_data) / "token-context-mcp" / "repos.toml"
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "token-context-mcp" / "repos.toml"
    return Path.home() / ".config" / "token-context-mcp" / "repos.toml"


def validate_repo_id(repo_id: str) -> str:
    if not _REPO_ID_RE.fullmatch(repo_id):
        raise ConfigError("repo_id must match ^[a-z][a-z0-9_-]{0,63}$")
    return repo_id


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig(repositories={})
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    raw_server = raw.get("server", {})
    server = ServerConfig(
        max_request_bytes=int(raw_server.get("max_request_bytes", ServerConfig.max_request_bytes)),
        max_result_tokens=int(raw_server.get("max_result_tokens", ServerConfig.max_result_tokens)),
        max_graph_nodes=int(raw_server.get("max_graph_nodes", ServerConfig.max_graph_nodes)),
        max_symbol_results=int(raw_server.get("max_symbol_results", ServerConfig.max_symbol_results)),
        network_policy=str(raw_server.get("network_policy", ServerConfig.network_policy)),
    )
    _validate_server(server)
    repositories: dict[str, RepositoryConfig] = {}
    for repo_id, settings in raw.get("repos", {}).items():
        validate_repo_id(repo_id)
        if not isinstance(settings, dict) or "root" not in settings:
            raise ConfigError(f"repos.{repo_id} must have a root")
        root = canonical_repository_root(Path(str(settings["root"])))
        repositories[repo_id] = RepositoryConfig(
            repo_id=repo_id,
            root=root,
            allow_symlinks=bool(settings.get("allow_symlinks", False)),
            max_file_bytes=int(settings.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)),
            max_files=int(settings.get("max_files", DEFAULT_MAX_FILES)),
        )
    return AppConfig(repositories=repositories, server=server)


def save_config(path: Path, config: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[server]",
        f"max_request_bytes = {config.server.max_request_bytes}",
        f"max_result_tokens = {config.server.max_result_tokens}",
        f"max_graph_nodes = {config.server.max_graph_nodes}",
        f"max_symbol_results = {config.server.max_symbol_results}",
        f'network_policy = "{_toml_string(config.server.network_policy)}"',
        "",
    ]
    for repo_id in sorted(config.repositories):
        repo = config.repositories[repo_id]
        lines.extend(
            [
                f"[repos.{repo_id}]",
                f'root = "{_toml_string(repo.root.as_posix())}"',
                f"allow_symlinks = {'true' if repo.allow_symlinks else 'false'}",
                f"max_file_bytes = {repo.max_file_bytes}",
                f"max_files = {repo.max_files}",
                "",
            ]
        )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    temporary.replace(path)


def register_repository(path: Path, repo_id: str, root: Path) -> RepositoryConfig:
    repo_id = validate_repo_id(repo_id)
    config = load_config(path)
    if repo_id in config.repositories:
        raise ConfigError(f"repository already registered: {repo_id}")
    repository = RepositoryConfig(repo_id=repo_id, root=canonical_repository_root(root))
    repositories = dict(config.repositories)
    repositories[repo_id] = repository
    save_config(path, AppConfig(repositories=repositories, server=config.server))
    return repository


def get_repository(config: AppConfig, repo_id: str) -> RepositoryConfig:
    try:
        return config.repositories[repo_id]
    except KeyError as error:
        raise ConfigError(f"unknown repo_id: {repo_id}") from error


def index_directory(config_path: Path) -> Path:
    return config_path.parent / "indexes"


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _validate_server(server: ServerConfig) -> None:
    if not 1_024 <= server.max_request_bytes <= 1_048_576:
        raise ConfigError("server.max_request_bytes must be between 1024 and 1048576")
    if not 32 <= server.max_result_tokens <= 8_192:
        raise ConfigError("server.max_result_tokens must be between 32 and 8192")
    if not 1 <= server.max_graph_nodes <= 500:
        raise ConfigError("server.max_graph_nodes must be between 1 and 500")
    if not 1 <= server.max_symbol_results <= 100:
        raise ConfigError("server.max_symbol_results must be between 1 and 100")
