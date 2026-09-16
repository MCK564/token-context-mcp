"""Request-scoped retrieval context and source memoization (P2)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from token_context_mcp.index.sqlite_store import SQLiteStore


class RetrievalContext:
    """Manages pinned repository snapshot, SQLite connection, and memoized source reads."""

    def __init__(self, repo_id: str, store: SQLiteStore, root_dir: Path) -> None:
        self.repo_id = repo_id
        self.store = store
        self.root_dir = root_dir
        self._source_cache: Dict[Path, Tuple[str, str]] = {}
        self._stats: Dict[str, int] = {"disk_reads": 0, "cache_hits": 0}

    def read_source_file(self, file_path: Path) -> Tuple[str, str]:
        """Read text and compute sha256 once per request context."""
        resolved = file_path.resolve()
        if resolved in self._source_cache:
            self._stats["cache_hits"] += 1
            return self._source_cache[resolved]

        self._stats["disk_reads"] += 1
        try:
            content = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            content = ""

        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self._source_cache[resolved] = (content, h)
        return content, h

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
