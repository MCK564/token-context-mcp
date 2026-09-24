"""High-level service interface for shared memory."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from token_context_mcp.memory.store import MemoryStore


class MemoryService:
    def __init__(self, storage_path: Path | str | None = None) -> None:
        if storage_path is None:
            # Default to in-memory store if not specified
            self.store = MemoryStore(":memory:")
        else:
            self.store = MemoryStore(storage_path)

    def memory_put(
        self,
        key: str,
        value: Any,
        scope: str = "session",
        ttl: int | None = 86400,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not key or not isinstance(key, str):
            raise ValueError("key must be a non-empty string")
        return self.store.put(key=key, value=value, scope=scope, ttl=ttl, session_id=session_id)

    def memory_get(self, key: str, scope: str = "session") -> dict[str, Any]:
        if not key or not isinstance(key, str):
            raise ValueError("key must be a non-empty string")
        return self.store.get(key=key, scope=scope)

    def memory_search(self, query: str, scope: str | None = None, limit: int = 5) -> dict[str, Any]:
        if not query or not isinstance(query, str):
            raise ValueError("query must be a non-empty string")
        return self.store.search(query=query, scope=scope, limit=limit)

    def memory_lock(self, resource_key: str, agent_id: str, timeout_sec: int = 60) -> dict[str, Any]:
        if not resource_key or not agent_id:
            raise ValueError("resource_key and agent_id are required")
        return self.store.lock(resource_key=resource_key, agent_id=agent_id, timeout_sec=timeout_sec)
