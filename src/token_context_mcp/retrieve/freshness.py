"""Freshness cache and incremental change detection."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from token_context_mcp.constants import SUPPORTED_EXTENSIONS
from token_context_mcp.index.hashing import sha256_bytes
from token_context_mcp.index.runner import _gitignore_spec
from token_context_mcp.models import FileRecord
from token_context_mcp.security.content_policy import is_hard_denied
from token_context_mcp.security.path_policy import PathPolicyError, safe_relative_path


@dataclass
class FreshnessSnapshot:
    """Snapshot of repository freshness."""

    status: str  # "fresh" | "stale"
    path_states: dict[str, str] = field(default_factory=dict)  # path -> "fresh" | "changed" | "missing"
    path_hashes: dict[str, str] = field(default_factory=dict)  # path -> sha256
    added_paths: list[str] = field(default_factory=list)
    changed_non_indexed: list[str] = field(default_factory=list)
    stale_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp: float = 0.0


class FreshnessCache:
    """Cache for repo-level and path-level freshness checks.

    Keyed by (repo_id, index_run_id) with 2.0s TTL.
    Maintains a hash cache keyed by (path, size, mtime_ns) to eliminate duplicate hashing.
    """

    def __init__(self, ttl: float = 30.0) -> None:
        self.ttl = ttl
        self._snapshots: dict[tuple[str, str], FreshnessSnapshot] = {}
        # (path, size, mtime_ns) -> sha256
        self._hash_cache: dict[tuple[str, int, int], str] = {}

    def path_state(
        self,
        root: Path,
        record: FileRecord,
        *,
        allow_symlinks: bool = False,
    ) -> tuple[str, str | None]:
        """Check freshness of a single file record.

        Returns (state, sha256), where state is 'fresh' | 'changed' | 'missing'.
        When size and mtime_ns match the record, returns 'fresh' with record.sha256 (0 hashes).
        When mtime or size differs, hashes once and caches by (path, size, mtime_ns).
        """
        try:
            current = safe_relative_path(root, record.path, allow_symlinks=allow_symlinks)
        except PathPolicyError:
            return "missing", None

        try:
            stat = current.stat()
        except OSError:
            return "missing", None

        if stat.st_size == record.size and stat.st_mtime_ns == record.mtime_ns:
            return "fresh", record.sha256

        # Size or mtime differs: compute or lookup hash
        cache_key = (record.path, stat.st_size, stat.st_mtime_ns)
        if cache_key in self._hash_cache:
            curr_hash = self._hash_cache[cache_key]
        else:
            try:
                raw = current.read_bytes()
                curr_hash = sha256_bytes(raw)
                self._hash_cache[cache_key] = curr_hash
            except OSError:
                return "missing", None

        if curr_hash == record.sha256:
            return "fresh", curr_hash
        return "changed", curr_hash

    def get_snapshot(
        self,
        repo_id: str,
        index_run_id: str,
        root: Path,
        files: list[FileRecord],
        metadata: dict[str, Any] | None = None,
        *,
        allow_symlinks: bool = False,
    ) -> FreshnessSnapshot:
        """Get or compute repository freshness snapshot within TTL."""
        now = time.monotonic()
        key = (repo_id, index_run_id)
        cached = self._snapshots.get(key)
        if cached is not None and (now - cached.timestamp) <= self.ttl:
            return cached

        snapshot = self._compute_snapshot(
            repo_id, index_run_id, root, files, metadata, allow_symlinks=allow_symlinks
        )
        snapshot.timestamp = now
        self._snapshots[key] = snapshot
        return snapshot

    def _compute_snapshot(
        self,
        repo_id: str,
        index_run_id: str,
        root: Path,
        files: list[FileRecord],
        metadata: dict[str, Any] | None = None,
        *,
        allow_symlinks: bool = False,
    ) -> FreshnessSnapshot:
        meta = metadata or {}
        warnings: list[str] = []
        path_states: dict[str, str] = {}
        path_hashes: dict[str, str] = {}
        stale_paths: list[str] = []
        changed_non_indexed: list[str] = []
        indexed_paths_set = {f.path for f in files}

        # 1. Added file detection via directory mtimes
        dir_mtimes = meta.get("dir_mtimes")
        added_paths: list[str] = []
        if dir_mtimes is None or not isinstance(dir_mtimes, dict):
            warnings.append("added_file_detection_unavailable")
        else:
            gitignore = _gitignore_spec(root)
            for rel_dir, expected_mtime in dir_mtimes.items():
                dir_full = root if rel_dir == "." else (root / rel_dir)
                try:
                    st = dir_full.stat()
                    if st.st_mtime_ns != expected_mtime:
                        for entry in os.scandir(dir_full):
                            if entry.is_file():
                                p = Path(entry.path)
                                if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                                    try:
                                        rel_file = str(p.relative_to(root)).replace("\\", "/")
                                    except ValueError:
                                        continue
                                    if (
                                        rel_file not in indexed_paths_set
                                        and rel_file not in added_paths
                                        and not is_hard_denied(rel_file)
                                        and not gitignore.match_file(rel_file)
                                    ):
                                        added_paths.append(rel_file)
                except OSError:
                    pass

            added_paths.sort()

        # 2. Check indexed files
        for record in files:
            state, file_hash = self.path_state(root, record, allow_symlinks=allow_symlinks)
            path_states[record.path] = state
            if file_hash is not None:
                path_hashes[record.path] = file_hash

            is_parsed = record.parse_status.startswith("parsed")
            if state != "fresh":
                if is_parsed:
                    stale_paths.append(record.path)
                else:
                    changed_non_indexed.append(record.path)

        stale_paths.sort()
        changed_non_indexed.sort()

        # 3. Overall status
        overall_status = "stale" if (stale_paths or added_paths) else "fresh"

        return FreshnessSnapshot(
            status=overall_status,
            path_states=path_states,
            path_hashes=path_hashes,
            added_paths=added_paths,
            changed_non_indexed=changed_non_indexed,
            stale_paths=stale_paths,
            warnings=warnings,
        )

    def invalidate(self, repo_id: str | None = None) -> None:
        """Invalidate cached snapshots."""
        if repo_id is None:
            self._snapshots.clear()
        else:
            self._snapshots = {k: v for k, v in self._snapshots.items() if k[0] != repo_id}
