from __future__ import annotations

from pathlib import Path

import pytest

from token_context_mcp.security.path_policy import PathPolicyError, safe_relative_path


def test_rejects_parent_absolute_and_unc_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "safe.py").write_text("pass\n", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    for candidate in ("../secret.txt", "C:\\Windows\\win.ini", "\\\\server\\share\\secret.txt", "safe.py/../secret.txt"):
        with pytest.raises(PathPolicyError):
            safe_relative_path(root, candidate)


def test_accepts_normal_repository_relative_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    nested = root / "src"
    nested.mkdir()
    expected = nested / "a.py"
    expected.write_text("pass\n", encoding="utf-8")
    assert safe_relative_path(root, "src/a.py") == expected.resolve()


def test_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("OS policy does not allow symlink fixtures")
    with pytest.raises(PathPolicyError):
        safe_relative_path(root, "escape.txt")
