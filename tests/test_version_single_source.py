"""M10.4: one version, everywhere (pyproject, __version__, SBOM, index manifest)."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import token_context_mcp
from token_context_mcp.release import write_release_materials

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_and_package_version_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == token_context_mcp.__version__ == "0.3.1"


def test_sbom_uses_the_package_version(tmp_path):
    paths = write_release_materials(ROOT, tmp_path)
    texts = " ".join(p.read_text(encoding="utf-8") for p in paths.values() if p.suffix == ".json")
    assert f'"version": "{token_context_mcp.__version__}"' in texts or token_context_mcp.__version__ in texts
    assert "0.1.0" not in json.dumps([json.loads(p.read_text(encoding="utf-8")) for p in paths.values() if p.suffix == ".json" and "sbom" in p.name.lower()])


def test_index_manifest_records_the_package_version(tmp_path):
    from token_context_mcp.config import RepositoryConfig
    from token_context_mcp.index.runner import build_index

    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    manifest = build_index(
        RepositoryConfig(repo_id="r", root=repo, allow_symlinks=False, max_file_bytes=100_000, max_files=100),
        tmp_path / "idx",
        network_policy="declared-deny-not-enforced",
    )
    assert manifest["indexer_version"] == token_context_mcp.__version__
