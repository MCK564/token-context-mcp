from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

_DOT_SEGMENTS = {"", ".", ".."}


class PathPolicyError(ValueError):
    """A supplied path crosses the repository capability boundary."""


def is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes  # type: ignore[attr-defined]
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def canonical_repository_root(root: Path) -> Path:
    try:
        resolved = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise PathPolicyError(f"repository root does not exist: {root}") from error
    if not resolved.is_dir():
        raise PathPolicyError("repository root must be a directory")
    if is_reparse_point(root):
        raise PathPolicyError("repository root may not be a symlink or reparse point")
    return resolved


def repository_relative_parts(supplied: str) -> tuple[str, ...]:
    """Validate a repository-relative path and split it into components.

    Validation is deliberately Windows-shaped on every host because those
    rules are the stricter set: a drive letter, a UNC prefix or a leading
    separator is refused wherever the server runs, so a registry written on
    one platform cannot smuggle an escape past another.

    Only the split is platform-specific. On POSIX a backslash is an ordinary
    filename character, so splitting on it there would invent components the
    caller never wrote and lose the real file behind them.
    """
    if not isinstance(supplied, str) or not supplied or "\x00" in supplied:
        raise PathPolicyError("path must be a non-empty string without NUL")
    normalized = supplied.replace("/", "\\")
    win_path = PureWindowsPath(normalized)
    if win_path.is_absolute() or win_path.drive or win_path.root or normalized.startswith("\\\\"):
        raise PathPolicyError("absolute and UNC paths are not allowed")
    if any(part in _DOT_SEGMENTS for part in win_path.parts):
        raise PathPolicyError("dot segments are not allowed")
    if os.name == "nt":
        return win_path.parts
    posix_path = PurePosixPath(supplied)
    if posix_path.is_absolute():
        raise PathPolicyError("absolute and UNC paths are not allowed")
    if any(part in _DOT_SEGMENTS for part in posix_path.parts):
        raise PathPolicyError("dot segments are not allowed")
    return posix_path.parts


def safe_relative_path(root: Path, supplied: str, *, allow_symlinks: bool = False) -> Path:
    parts = repository_relative_parts(supplied)
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise PathPolicyError("path does not exist in the registered repository") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise PathPolicyError("path resolves outside the registered repository") from error
    if not allow_symlinks:
        current = root
        for part in parts:
            current = current / part
            if is_reparse_point(current):
                raise PathPolicyError("symlinks and reparse points are not allowed")
    if not resolved.is_file():
        raise PathPolicyError("path must identify a regular file")
    return resolved


def relative_posix(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except ValueError as error:
        raise PathPolicyError("path is outside repository root") from error
