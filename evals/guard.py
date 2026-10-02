"""Rule 17 held-out harness guard.

Guarantees that held-out evaluations cannot be run prematurely or against unfrozen code.

``--role heldout`` is allowed only when one of the following holds:

1. the git tag ``<milestone>-freeze`` (``m12``; ``TC_GUARD_MILESTONE`` selects another, e.g. ``m13``) exists and
   ``git diff <milestone>-freeze`` over every protected path is empty (uncommitted changes count), or
2. ``--allow-baseline-code <path>`` names a tree that is *byte-identical* to ``<milestone>-base:src/token_context_mcp`` and
   that is the code this process actually imports (the baseline arm of the held-out comparison).  A bare "path
   exists" check would let any caller run held-out tasks on unfrozen code, so it is not accepted.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

# The milestone whose held-out sets are being measured: ``TC_GUARD_MILESTONE=m13`` makes the guard require ``m13-freeze``
# (and ``m13-base`` for the baseline arm).  M12 stays the default so that its recorded runs and tests are unchanged.
MILESTONE = os.environ.get("TC_GUARD_MILESTONE", "m12")
FREEZE_TAG = f"{MILESTONE}-freeze"
BASELINE_TAG = f"{MILESTONE}-base"
BASELINE_PACKAGE = "src/token_context_mcp"

# Everything that can change a held-out number: the library, both held-out entry points, the modules they import
# (``loc_eval`` is imported by ``bench_retrieval``) and this guard itself.
PROTECTED_PATHS = (
    "src",
    "evals/bench_retrieval.py",
    "evals/edge_gold_eval.py",
    "evals/loc_eval.py",
    "evals/guard.py",
)


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Failed to run git {' '.join(args)}: {exc}") from exc


def _blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git object id, not security


def _package_dir(path: Path) -> Path:
    """Accept ``<x>/src`` (contains ``token_context_mcp``) or ``<x>/token_context_mcp`` itself."""
    if (path / "token_context_mcp").is_dir():
        return path / "token_context_mcp"
    if path.name == "token_context_mcp" and path.is_dir():
        return path
    raise RuntimeError(
        f"Rule 17 violation: --allow-baseline-code {path} does not contain a token_context_mcp package"
    )


def _verify_baseline_tree(package_dir: Path, root: Path) -> None:
    """The tree must equal ``<milestone>-base:src/token_context_mcp`` file by file (line endings normalised)."""
    tag = _git(["rev-parse", "--verify", f"refs/tags/{BASELINE_TAG}"], root)
    if tag.returncode != 0:
        raise RuntimeError(
            f"Rule 17 violation: --allow-baseline-code needs the git tag '{BASELINE_TAG}' to verify the baseline tree."
        )
    listing = _git(["ls-tree", "-r", BASELINE_TAG, "--", BASELINE_PACKAGE], root)
    if listing.returncode != 0:
        raise RuntimeError(f"Rule 17 violation: cannot list {BASELINE_TAG}:{BASELINE_PACKAGE}: {listing.stderr.strip()}")
    expected: dict[str, str] = {}
    for line in listing.stdout.splitlines():
        meta, _, name = line.partition("\t")
        expected[name[len(BASELINE_PACKAGE) + 1 :]] = meta.split()[2]
    found: dict[str, str] = {}
    for file in sorted(package_dir.rglob("*")):
        if not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc":
            continue
        rel = file.relative_to(package_dir).as_posix()
        raw = file.read_bytes()
        found[rel] = raw
    problems: list[str] = []
    for rel in sorted(set(expected) | set(found)):
        if rel not in found:
            problems.append(f"missing {rel}")
        elif rel not in expected:
            problems.append(f"extra {rel}")
        else:
            raw = found[rel]
            if expected[rel] not in {_blob_sha1(raw), _blob_sha1(raw.replace(b"\r\n", b"\n"))}:
                problems.append(f"modified {rel}")
    if problems:
        raise RuntimeError(
            f"Rule 17 violation: --allow-baseline-code {package_dir} is not byte-identical to {BASELINE_TAG}:"
            f"{BASELINE_PACKAGE} ({len(problems)} difference(s), e.g. {', '.join(problems[:3])})."
        )


def _imported_package_file() -> Path | None:
    spec = importlib.util.find_spec("token_context_mcp")
    return Path(spec.origin).resolve() if spec and spec.origin else None


def check_heldout_guard(
    role: str,
    allow_baseline_code: Path | str | None = None,
    repo_root: Path | None = None,
    imported_package_file: Path | None = None,
) -> None:
    """Enforce Rule 17 guard conditions (no-op unless ``role == 'heldout'``)."""
    if role != "heldout":
        return

    root = Path(repo_root) if repo_root else REPO_ROOT

    if allow_baseline_code is not None:
        p = Path(allow_baseline_code)
        if not p.exists():
            raise FileNotFoundError(f"--allow-baseline-code path does not exist: {allow_baseline_code}")
        package_dir = _package_dir(p.resolve())
        _verify_baseline_tree(package_dir, root)
        origin = imported_package_file if imported_package_file is not None else _imported_package_file()
        if origin is None or package_dir.resolve() not in Path(origin).resolve().parents:
            raise RuntimeError(
                f"Rule 17 violation: --allow-baseline-code {package_dir} is not the code this process imports "
                f"(token_context_mcp is loaded from {origin}). Put the baseline on PYTHONPATH."
            )
        return

    tag_check = _git(["rev-parse", "--verify", f"refs/tags/{FREEZE_TAG}"], root)
    if tag_check.returncode != 0:
        raise RuntimeError(
            f"Rule 17 violation: Cannot run benchmark with --role heldout because git tag '{FREEZE_TAG}' does not exist. "
            "Held-out evaluations are strictly forbidden until code freeze."
        )

    diff_check = _git(["diff", FREEZE_TAG, "--", *PROTECTED_PATHS], root)
    untracked = _git(["ls-files", "--others", "--exclude-standard", "--", *PROTECTED_PATHS], root)  # new files
    if diff_check.returncode != 0 or diff_check.stdout.strip() or untracked.stdout.strip():
        snippet = (diff_check.stdout.strip() or "untracked: " + untracked.stdout.strip())[:300]
        raise RuntimeError(
            f"Rule 17 violation: Cannot run benchmark with --role heldout because git diff against '{FREEZE_TAG}' is not empty "
            f"for protected paths: {', '.join(PROTECTED_PATHS)}.\nDiff:\n{snippet}"
        )
