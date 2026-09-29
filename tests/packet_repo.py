"""Shared fixture repository for the M6 context-packet tests and the inspect_symbol snapshots."""
from __future__ import annotations

from pathlib import Path

from token_context_mcp.config import AppConfig, RepositoryConfig, ServerConfig, save_config
from token_context_mcp.index.runner import build_index

REPO_ID = "packet-repo"

MODEL_PY = '''"""Domain model."""
from __future__ import annotations


class Base:
    """Common base."""

    def label(self) -> str:
        return "base"


class Item(Base):
    """A named thing."""

    def __init__(self, name: str, weight: int = 1) -> None:
        self.name = name
        self.weight = weight

    def describe(self) -> str:
        return f"{self.name}:{self.weight}"

    def rename(self, new_name: str) -> None:
        self.name = new_name
'''

UTIL_PY = '''"""Small helpers."""
from __future__ import annotations

import os


def helper_short(value: int) -> int:
    """Return value plus one."""
    return value + 1


def helper_two(flag: bool = False) -> str:
    return "two" if flag else os.sep


def helper_three(text: str) -> str:
    return text.strip()
'''

SERVICE_PY = '''"""Service layer."""
from __future__ import annotations

import json
import os

from pkg.model import Item
from pkg.util import helper_short, helper_three, helper_two


class Service:
    """Owns a list of items."""

    def __init__(self) -> None:
        self.items: list[Item] = []

    def add(self, name: str) -> int:
        """Add an item and return the new count."""
        item = Item(name)
        self.items.append(item)
        return helper_short(len(self.items))

    def summary(self) -> str:
        return json.dumps([i.describe() for i in self.items])

    def run(self, names: list[str], flag: bool = False) -> str:
        """Add every name then summarize."""
        for name in names:
            self.add(name)
        prefix = helper_two(flag)
        return prefix + self.summary()

    def clean(self, raw: str) -> str:
        return helper_three(raw)


def make_service() -> Service:
    return Service()


def env_name() -> str:
    return os.environ.get("SERVICE_NAME", "svc")
'''


def _long_function() -> str:
    """A ~130 line function whose call sites to helpers are spread far apart."""
    lines = [
        "def process_batch(values: list[int], flag: bool = False) -> int:",
        '    """Process a long batch with several helper calls spread through the body."""',
        "    total = 0",
    ]
    for i in range(1, 41):
        lines.append(f"    total += values[{i % 3}] * {i}  # filler line {i}")
    lines.append("    total = helper_short(total)")
    for i in range(41, 81):
        lines.append(f"    total += values[{i % 3}] * {i}  # filler line {i}")
    lines.append("    label = helper_two(flag)")
    for i in range(81, 121):
        lines.append(f"    total += values[{i % 3}] * {i}  # filler line {i}")
    lines.append("    text = helper_three(label)")
    lines.append("    return total + len(text)")
    return "\n".join(lines) + "\n"


BATCH_PY = (
    '"""Batch processing."""\nfrom __future__ import annotations\n\nimport os\n\n'
    "from pkg.util import helper_short, helper_three, helper_two\n\n\n" + _long_function()
)

TEST_PY = '''from pkg.service import Service, make_service


def test_add_counts() -> None:
    svc = make_service()
    assert svc.add("a") == 2


def test_run_returns_summary() -> None:
    svc = Service()
    assert "a" in svc.run(["a"])
'''


def build_packet_repo(tmp_path: Path, *, repo_id: str = REPO_ID) -> Path:
    """Write the fixture repo under tmp_path, index it, and return the config path."""
    root = tmp_path / "packet-src"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    (root / "pkg" / "model.py").write_text(MODEL_PY, encoding="utf-8", newline="\n")
    (root / "pkg" / "util.py").write_text(UTIL_PY, encoding="utf-8", newline="\n")
    (root / "pkg" / "service.py").write_text(SERVICE_PY, encoding="utf-8", newline="\n")
    (root / "pkg" / "batch.py").write_text(BATCH_PY, encoding="utf-8", newline="\n")
    (root / "tests" / "test_service.py").write_text(TEST_PY, encoding="utf-8", newline="\n")
    config_path = tmp_path / "config" / "repos.toml"
    repo = RepositoryConfig(repo_id=repo_id, root=root.resolve())
    save_config(config_path, AppConfig(repositories={repo_id: repo}, server=ServerConfig()))
    build_index(repo, config_path.parent / "indexes", network_policy="declared-deny-not-enforced")
    return config_path
