from __future__ import annotations

import hashlib
import json
import platform
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path


def write_release_materials(project_root: Path, output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    pyproject = project_root / "pyproject.toml"
    lock = project_root / "uv.lock"
    components: list[dict[str, object]] = [
        {"type": "application", "name": "token-context-mcp", "version": "0.1.0"},
        {"type": "file", "name": "pyproject.toml", "hashes": [{"alg": "SHA-256", "content": _sha256(pyproject)}]},
        {"type": "file", "name": "uv.lock", "hashes": [{"alg": "SHA-256", "content": _sha256(lock)}]},
    ]
    with lock.open("rb") as handle:
        locked = tomllib.load(handle)
    for package in locked.get("package", []):
        if not isinstance(package, dict) or not package.get("name") or not package.get("version"):
            continue
        hashes: list[dict[str, str]] = []
        sdist = package.get("sdist")
        if isinstance(sdist, dict) and isinstance(sdist.get("hash"), str) and sdist["hash"].startswith("sha256:"):
            hashes.append({"alg": "SHA-256", "content": sdist["hash"].removeprefix("sha256:")})
        components.append(
            {
                "type": "library",
                "name": str(package["name"]),
                "version": str(package["version"]),
                "purl": f"pkg:pypi/{package['name']}@{package['version']}",
                "hashes": hashes,
            }
        )
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{_sha256(pyproject)[:8]}-{_sha256(lock)[:4]}-0000-0000-000000000000",
        "version": 1,
        "metadata": {"timestamp": datetime.now(UTC).isoformat(), "component": components[0]},
        "components": components[1:],
        "properties": [{"name": "token-context.note", "value": "Starter SBOM; enrich with locked dependency components in CI."}],
    }
    provenance = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": "pyproject.toml", "digest": {"sha256": _sha256(pyproject)}},
            {"name": "uv.lock", "digest": {"sha256": _sha256(lock)}},
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://token-context-mcp.local/build/v1",
                "externalParameters": {"python": sys.version.split()[0], "platform": platform.platform()},
                "resolvedDependencies": [
                    {"uri": "file:pyproject.toml", "digest": {"sha256": _sha256(pyproject)}},
                    {"uri": "file:uv.lock", "digest": {"sha256": _sha256(lock)}},
                ],
            },
            "runDetails": {"builder": {"id": "local-unattested"}, "metadata": {"invocationId": "local-unsigned"}},
        },
    }
    sbom_path = output / "sbom.cdx.json"
    provenance_path = output / "provenance.intoto.json"
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"sbom": sbom_path, "provenance": provenance_path}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
