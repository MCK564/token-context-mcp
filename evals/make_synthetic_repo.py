"""Generate a deterministic synthetic 5,000-file repository for stress testing (M0 baseline).

Generates 5,000 files with fixed seed containing patterns:
  - dict.get
  - os.environ.get
  - self.x = Cls()
Registers the repository in a temporary config TOML with repo_id=synthetic-5k.
"""
from __future__ import annotations

import argparse
import os
import random
from pathlib import Path

from token_context_mcp.constants import DEFAULT_MAX_FILE_BYTES
from token_context_mcp.models import AppConfig, RepositoryConfig, ServerConfig


FILE_TEMPLATE = """\
\"\"\"Module {pkg_id}_{mod_id} - deterministic synthetic file for stress testing.\"\"\"
from __future__ import annotations

import os

class Service_{pkg_id}_{mod_id}:
    \"\"\"Service class with generic method names to test edge disambiguation.\"\"\"

    def __init__(self) -> None:
        self.config_data = {{"env": "test", "timeout": 30}}
        self.name = "{pkg_id}_{mod_id}"

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.config_data.get(key, default)

    def run(self) -> None:
        # Pattern 1: dict.get
        val = self.config_data.get("timeout")

        # Pattern 2: os.environ.get
        flag = os.environ.get("SYNTHETIC_FLAG", "false")

    def execute(self) -> None:
        pass


class Worker_{pkg_id}_{mod_id}:
    \"\"\"Worker class testing instantiation patterns.\"\"\"

    def __init__(self) -> None:
        # Pattern 3: self.x = Cls()
        self.service = Service_{pkg_id}_{mod_id}()

    def process(self) -> None:
        self.service.run()
        res = self.service.get("env")
"""


def generate_synthetic_repo(
    root: Path,
    num_files: int = 5000,
    seed: int = 42,
) -> int:
    """Generate deterministic python files in subdirectories."""
    random.seed(seed)
    root.mkdir(parents=True, exist_ok=True)

    # 50 packages, 100 files each for 5000 files
    num_pkgs = 50
    files_per_pkg = (num_files + num_pkgs - 1) // num_pkgs

    count = 0
    for p in range(num_pkgs):
        pkg_dir = root / f"pkg_{p:02d}"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        init_file = pkg_dir / "__init__.py"
        init_file.write_text('"""Package init."""\n', encoding="utf-8")

        for m in range(files_per_pkg):
            if count >= num_files:
                break
            mod_file = pkg_dir / f"mod_{m:02d}.py"
            content = FILE_TEMPLATE.format(pkg_id=f"{p:02d}", mod_id=f"{m:02d}")
            mod_file.write_text(content, encoding="utf-8")
            count += 1
            if count % 1000 == 0:
                print(f"  Generated {count}/{num_files} files...")

    # Write pyproject.toml in root
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "synthetic-5k"\nversion = "0.1.0"\n[project.scripts]\nsynthetic-cli = "pkg_00.mod_00:main"\n',
        encoding="utf-8",
    )
    print(f"Finished generating {count} files in {root}")
    return count


def create_temp_config(
    repo_root: Path,
    config_file: Path,
    index_dir: Path | None = None,
    repo_id: str = "synthetic-5k",
) -> Path:
    """Create a temporary configuration registering synthetic-5k."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_root = repo_root.resolve()

    toml_content = f"""\
[server]
max_request_bytes = 1048576
max_result_tokens = 8192
max_graph_nodes = 500
max_symbol_results = 100
network_policy = "deny_all"
output_mode = "structured"
default_view = "normal"
enable_extensions = true

[repos.{repo_id}]
root = "{str(resolved_root).replace('\\', '/')}"
allow_symlinks = false
max_file_bytes = 2000000
max_files = 25000
"""
    config_file.write_text(toml_content, encoding="utf-8")
    print(f"Created temporary config at: {config_file}")
    return config_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic 5k-file repository.")
    parser.add_argument("--output-dir", default="tmp/synthetic_5k", help="Target directory for synthetic repo")
    parser.add_argument("--config-out", default="evals/out/m0/synthetic_5k_config.toml", help="Path for generated repos.toml")
    parser.add_argument("--num-files", type=int, default=5000, help="Number of files to generate (default 5000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42)")
    parser.add_argument("--index", action="store_true", help="Run indexing immediately on the generated repo")

    args = parser.parse_args()

    repo_dir = Path(args.output_dir).expanduser().resolve()
    config_path = Path(args.config_out).expanduser().resolve()

    print(f"Generating synthetic repository in: {repo_dir} (target files: {args.num_files}, seed: {args.seed})")
    count = generate_synthetic_repo(repo_dir, num_files=args.num_files, seed=args.seed)

    create_temp_config(repo_dir, config_path, repo_id="synthetic-5k")

    if args.index:
        print("\nIndexing synthetic repository using runner...")
        from token_context_mcp.config import index_directory, load_config
        from token_context_mcp.index.runner import build_index
        cfg = load_config(config_path)
        idx_dir = index_directory(config_path)
        repo_cfg = cfg.repositories["synthetic-5k"]
        manifest = build_index(repo_cfg, idx_dir, network_policy=cfg.server.network_policy)
        print("Indexing completed!")
        print(f"  Files indexed: {manifest.get('files_indexed')}")
        print(f"  Symbols indexed: {manifest.get('symbols_indexed')}")
        print(f"  Edges indexed: {manifest.get('edges_indexed')}")


if __name__ == "__main__":
    main()
