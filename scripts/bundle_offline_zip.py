"""
Script to create a clean offline ZIP bundle of token-context-mcp.
Supports:
1. Exporting clean codebase (excluding git, venv, caches, local indexes, user configs).
2. Optionally downloading offline wheels for air-gapped environments (`--with-wheels`).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".coverage",
    "htmlcov",
    "dist",
    "build",
    "*.egg-info",
}

EXCLUDE_FILES = {
    "repos.toml",
    "memory.sqlite",
    "*.spec",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
}


def should_exclude(rel_path: Path) -> bool:
    for part in rel_path.parts:
        if part in EXCLUDE_DIRS:
            return True
        if part.endswith(".egg-info"):
            return True
    name = rel_path.name
    if name in EXCLUDE_FILES:
        return True
    if name.endswith((".pyc", ".pyo", ".pyd")):
        return True
    return False


def build_bundle(output_zip: Path, include_wheels: bool = False) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    output_zip = output_zip.resolve()

    print(f"Creating clean bundle from {repo_root} -> {output_zip}")

    with tempfile.TemporaryDirectory(prefix="tcmcp_bundle_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        stage_dir = tmp_path / "token-context-mcp"
        stage_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy clean files
        for root, dirs, files in os.walk(repo_root):
            root_path = Path(root)
            rel_root = root_path.relative_to(repo_root)

            # Skip excluded dirs in-place
            dirs[:] = [d for d in dirs if not should_exclude(rel_root / d)]

            dest_dir = stage_dir / rel_root
            dest_dir.mkdir(parents=True, exist_ok=True)

            for file in files:
                rel_file = rel_root / file
                if not should_exclude(rel_file):
                    shutil.copy2(root_path / file, dest_dir / file)

        # 2. Optionally download wheels for air-gapped environments
        if include_wheels:
            wheels_dir = stage_dir / "wheels"
            wheels_dir.mkdir(parents=True, exist_ok=True)
            print("Downloading dependencies into 'wheels/' for offline installation...")
            cmd = [
                sys.executable,
                "-m",
                "pip",
                "download",
                "-d",
                str(wheels_dir),
                ".",
                ".[dev]",
            ]
            subprocess.run(cmd, cwd=str(stage_dir), check=True)

        # 3. Create zip
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        if output_zip.exists():
            output_zip.unlink()

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(stage_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(stage_dir)
                    zf.write(file_path, arcname)

    print(f"Bundle successfully created: {output_zip} ({output_zip.stat().st_size / (1024*1024):.2f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle token-context-mcp into a clean distribution ZIP.")
    parser.add_argument(
        "-o",
        "--output",
        default="dist/token-context-mcp.zip",
        help="Target output zip file path (default: dist/token-context-mcp.zip)",
    )
    parser.add_argument(
        "--with-wheels",
        action="store_true",
        help="Download binary wheels into wheels/ folder for air-gapped / offline installation",
    )
    args = parser.parse_args()
    build_bundle(Path(args.output), include_wheels=args.with_wheels)


if __name__ == "__main__":
    main()
