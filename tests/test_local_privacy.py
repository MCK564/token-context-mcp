from __future__ import annotations

import os
from pathlib import Path

import pytest

from token_context_mcp.cli import main
from token_context_mcp.config import (
    AppConfig,
    RepositoryConfig,
    ServerConfig,
    index_directory,
    load_config,
    save_config,
)
from token_context_mcp.index.runner import build_index, database_path, manifest_path
from token_context_mcp.security.local_privacy import describe_mode, harden_registry, uses_posix_modes
from token_context_mcp.security.path_policy import PathPolicyError, repository_relative_parts

posix_only = pytest.mark.skipif(not uses_posix_modes(), reason="POSIX mode bits do not exist on this platform")


@pytest.fixture()
def registry(tmp_path: Path, sample_repo: Path) -> Path:
    """A registry in the directory layout the tool creates for itself."""
    config_path = tmp_path / "token-context-mcp" / "repos.toml"
    repo = RepositoryConfig(repo_id="demo", root=sample_repo.resolve())
    save_config(config_path, AppConfig(repositories={"demo": repo}, server=ServerConfig()))
    return config_path


def _build_snapshot(registry: Path) -> Path:
    indexes = index_directory(registry)
    repository = load_config(registry).repositories["demo"]
    build_index(repository, indexes, network_policy="declared-deny-not-enforced")
    return indexes


@posix_only
def test_snapshot_is_owner_only_under_a_permissive_umask(registry: Path) -> None:
    # 0022 is the common default and would otherwise publish indexed source
    # bodies to every account on the host.
    previous = os.umask(0o022)
    try:
        indexes = _build_snapshot(registry)
    finally:
        os.umask(previous)
    assert describe_mode(indexes) == "0700"
    assert describe_mode(database_path(indexes, "demo")) == "0600"
    assert describe_mode(manifest_path(indexes, "demo")) == "0600"
    assert describe_mode(registry) == "0600"
    assert describe_mode(registry.parent) == "0700"


@posix_only
def test_harden_repairs_a_loosened_snapshot(registry: Path) -> None:
    indexes = _build_snapshot(registry)
    database = database_path(indexes, "demo")
    os.chmod(database, 0o644)
    os.chmod(indexes, 0o755)

    checked = harden_registry(registry, check_only=True)
    assert checked["result"]["status"] == "needs_repair"
    assert describe_mode(database) == "0644", "a check must not change anything"

    repaired = harden_registry(registry)
    assert repaired["result"]["status"] == "repaired"
    assert describe_mode(database) == "0600"
    assert describe_mode(indexes) == "0700"


@posix_only
def test_harden_leaves_a_directory_it_does_not_own(tmp_path: Path) -> None:
    # TOKEN_CONTEXT_CONFIG can point at a shared or home directory; chmod 0700
    # there would lock the operator out of unrelated files.
    home_like = tmp_path / "home"
    home_like.mkdir(mode=0o755)
    config_path = home_like / "repos.toml"
    save_config(config_path, AppConfig(repositories={}, server=ServerConfig()))
    unrelated = home_like / "notes.txt"
    unrelated.write_text("keep me readable\n", encoding="utf-8")
    os.chmod(unrelated, 0o644)

    report = harden_registry(config_path)

    assert report["parent_directory"]["status"] == "not_owned"
    assert describe_mode(unrelated) == "0644"
    assert describe_mode(config_path) == "0600"


def test_harden_command_reports_a_status_on_every_platform(
    registry: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["harden", "--check", "--config", str(registry)]) == 0
    payload = capsys.readouterr().out
    assert '"platform"' in payload
    assert "token-context-mcp" in payload


def test_posix_filenames_containing_a_backslash_survive_the_split() -> None:
    parts = repository_relative_parts("src/odd\\name.py")
    if os.name == "nt":
        assert parts == ("src", "odd", "name.py")
    else:
        assert parts == ("src", "odd\\name.py")


@pytest.mark.parametrize(
    "candidate",
    ["/etc/passwd", "C:\\Windows\\win.ini", "\\\\server\\share\\secret", "../secret", "a/../../b"],
)
def test_escapes_are_refused_on_every_platform(candidate: str) -> None:
    with pytest.raises(PathPolicyError):
        repository_relative_parts(candidate)
