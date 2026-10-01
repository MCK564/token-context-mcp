"""Rule 17: the held-out guard, exercised against real (temporary) git repositories, not mocks."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))

import guard  # noqa: E402
from guard import check_heldout_guard  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false", *args],
        cwd=root, check=True, capture_output=True,
    )


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "token_context_mcp").mkdir(parents=True)
    (root / "evals").mkdir()
    (root / "src" / "token_context_mcp" / "__init__.py").write_text("__version__ = '0'\n")
    (root / "src" / "token_context_mcp" / "core.py").write_text("X = 1\n")
    for name in ("bench_retrieval.py", "edge_gold_eval.py", "loc_eval.py", "guard.py"):
        (root / "evals" / name).write_text(f"# {name}\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "tag", "m12-base")
    return root


def freeze(root: Path) -> None:
    git(root, "tag", "-a", "m12-freeze", "-m", "freeze")


def test_dev_role_is_never_guarded(tmp_path: Path) -> None:
    check_heldout_guard("dev", repo_root=tmp_path)  # not even a git repository


def test_heldout_refused_without_freeze_tag(sandbox: Path) -> None:
    with pytest.raises(RuntimeError, match="m12-freeze.*does not exist"):
        check_heldout_guard("heldout", repo_root=sandbox)


def test_heldout_allowed_on_frozen_clean_tree(sandbox: Path) -> None:
    freeze(sandbox)
    check_heldout_guard("heldout", repo_root=sandbox)


@pytest.mark.parametrize("protected", ["src/token_context_mcp/core.py", "evals/bench_retrieval.py", "evals/loc_eval.py", "evals/guard.py"])
def test_heldout_refused_when_a_protected_file_changes_after_freeze(sandbox: Path, protected: str) -> None:
    freeze(sandbox)
    (sandbox / protected).write_text("changed\n")
    with pytest.raises(RuntimeError, match="not empty"):
        check_heldout_guard("heldout", repo_root=sandbox)


def test_heldout_refused_when_a_new_file_appears_in_src(sandbox: Path) -> None:
    freeze(sandbox)
    (sandbox / "src" / "token_context_mcp" / "new_module.py").write_text("Y = 2\n")
    with pytest.raises(RuntimeError, match="not empty"):
        check_heldout_guard("heldout", repo_root=sandbox)


def test_unprotected_changes_do_not_block(sandbox: Path) -> None:
    freeze(sandbox)
    (sandbox / "README.md").write_text("docs are free to change\n")
    (sandbox / "evals" / "some_other_script.py").write_text("print(1)\n")
    check_heldout_guard("heldout", repo_root=sandbox)


def baseline_copy(sandbox: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "base_src"
    dest.mkdir()
    subprocess.run(f"git archive m12-base src | tar -x -C {dest}", shell=True, cwd=sandbox, check=True)
    return dest / "src"


def test_baseline_flag_accepts_only_the_real_baseline_tree(sandbox: Path, tmp_path: Path) -> None:
    base = baseline_copy(sandbox, tmp_path)
    origin = base / "token_context_mcp" / "__init__.py"
    check_heldout_guard("heldout", allow_baseline_code=base, repo_root=sandbox, imported_package_file=origin)


def test_baseline_flag_rejects_a_modified_tree(sandbox: Path, tmp_path: Path) -> None:
    base = baseline_copy(sandbox, tmp_path)
    (base / "token_context_mcp" / "core.py").write_text("X = 999\n")
    with pytest.raises(RuntimeError, match="not byte-identical.*modified core.py"):
        check_heldout_guard("heldout", allow_baseline_code=base, repo_root=sandbox, imported_package_file=base / "token_context_mcp" / "__init__.py")


def test_baseline_flag_rejects_an_extra_file(sandbox: Path, tmp_path: Path) -> None:
    base = baseline_copy(sandbox, tmp_path)
    (base / "token_context_mcp" / "extra.py").write_text("Z = 3\n")
    with pytest.raises(RuntimeError, match="extra extra.py"):
        check_heldout_guard("heldout", allow_baseline_code=base, repo_root=sandbox, imported_package_file=base / "token_context_mcp" / "__init__.py")


def test_baseline_flag_accepts_crlf_checkout(sandbox: Path, tmp_path: Path) -> None:
    base = baseline_copy(sandbox, tmp_path)
    core = base / "token_context_mcp" / "core.py"
    core.write_bytes(core.read_bytes().replace(b"\n", b"\r\n"))
    check_heldout_guard("heldout", allow_baseline_code=base, repo_root=sandbox, imported_package_file=base / "token_context_mcp" / "__init__.py")


def test_baseline_flag_rejects_an_arbitrary_existing_path(sandbox: Path, tmp_path: Path) -> None:
    anywhere = tmp_path / "anywhere"
    anywhere.mkdir()
    with pytest.raises(RuntimeError, match="does not contain a token_context_mcp package"):
        check_heldout_guard("heldout", allow_baseline_code=anywhere, repo_root=sandbox)


def test_baseline_flag_requires_that_the_process_imports_the_baseline(sandbox: Path, tmp_path: Path) -> None:
    base = baseline_copy(sandbox, tmp_path)
    with pytest.raises(RuntimeError, match="not the code this process imports"):
        check_heldout_guard("heldout", allow_baseline_code=base, repo_root=sandbox, imported_package_file=sandbox / "src" / "token_context_mcp" / "__init__.py")


def test_baseline_flag_needs_the_baseline_tag(sandbox: Path, tmp_path: Path) -> None:
    base = baseline_copy(sandbox, tmp_path)
    git(sandbox, "tag", "-d", "m12-base")
    with pytest.raises(RuntimeError, match="m12-base"):
        check_heldout_guard("heldout", allow_baseline_code=base, repo_root=sandbox, imported_package_file=base / "token_context_mcp" / "__init__.py")


def test_missing_baseline_path_is_an_error(sandbox: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        check_heldout_guard("heldout", allow_baseline_code=tmp_path / "nope", repo_root=sandbox)


def test_guard_protects_the_modules_bench_retrieval_imports() -> None:
    """bench_retrieval imports loc_eval: a change there must trip the guard, so both are protected."""
    assert {"evals/loc_eval.py", "evals/guard.py", "evals/bench_retrieval.py", "evals/edge_gold_eval.py", "src"} <= set(guard.PROTECTED_PATHS)
