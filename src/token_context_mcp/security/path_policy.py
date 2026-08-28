from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath


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


def safe_relative_path(root: Path, supplied: str, *, allow_symlinks: bool = False) -> Path:
    if not isinstance(supplied, str) or not supplied or "\x00" in supplied:
        raise PathPolicyError("path must be a non-empty string without NUL")
    normalized = supplied.replace("/", "\\")
    win_path = PureWindowsPath(normalized)
    if win_path.is_absolute() or win_path.drive or normalized.startswith("\\\\"):
        raise PathPolicyError("absolute and UNC paths are not allowed")
    if any(part in {"", ".", ".."} for part in win_path.parts):
        raise PathPolicyError("dot segments are not allowed")
    candidate = root.joinpath(*win_path.parts)
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
        for part in win_path.parts:
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
