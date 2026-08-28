from __future__ import annotations

from pathlib import Path

from token_context_mcp.index.hashing import sha256_file
from token_context_mcp.models import FileRecord
from token_context_mcp.security.path_policy import PathPolicyError, safe_relative_path


def pending_paths(root: Path, files: list[FileRecord], *, allow_symlinks: bool = False) -> list[str]:
    """Detect source changes without a persistent watcher or filesystem writes."""

    pending: list[str] = []
    for record in files:
        try:
            current = safe_relative_path(root, record.path, allow_symlinks=allow_symlinks)
            stat = current.stat()
            if stat.st_size == record.size and stat.st_mtime_ns == record.mtime_ns:
                continue
            if sha256_file(current) != record.sha256:
                pending.append(record.path)
        except (PathPolicyError, OSError):
            pending.append(record.path)
    return pending
