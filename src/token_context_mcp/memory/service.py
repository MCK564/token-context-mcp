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

    def revoke_agent_locks(self, agent_id: str) -> int:
        return self.store.revoke_agent_locks(agent_id=agent_id)

    def revoke_all_locks(self) -> int:
        return self.store.revoke_all_locks()

    def list_active_locks(self) -> list[dict[str, Any]]:
        return self.store.list_active_locks()

    def memory_consolidate(
        self,
        scope: str = "session",
        target_key: str = "project_architectural_insights",
        prune_transient: bool = False,
    ) -> dict[str, Any]:
        """Consolidate fragmented memory checkpoints into a unified architectural artifact.
        
        Learned from Google Cloud GenAI Always-On Memory Agent (ConsolidateAgent pattern).
        Deduplicates redundant connections and synthesizes cross-session patterns.
        """
        import json
        import time

        entries = self.store.list_entries(scope=scope, limit=100)
        source_entries = [e for e in entries if e["key"] != target_key]

        if not source_entries:
            return {
                "status": "noop",
                "message": f"No active entries found in scope '{scope}' to consolidate.",
                "source_entries_count": 0,
                "target_key": target_key,
            }

        lines = [f"# Memory Scope: {scope} ({len(source_entries)} entries)"]
        for e in source_entries:
            val_str = json.dumps(e["value"], ensure_ascii=False) if isinstance(e["value"], (dict, list)) else str(e["value"])
            lines.append(f"- Key: `{e['key']}` | Value: {val_str}")
        compiled_context = "\n".join(lines)

        from token_context_mcp.sampling.router import SamplingRouter
        router = SamplingRouter()
        intent = "Consolidate fragmented memory checkpoints, extract architectural insights, and deduplicate redundant entities"
        summary_res = router.summarize(text=compiled_context, intent=intent, max_tokens=512)

        consolidated_payload = {
            "consolidation_timestamp": time.time(),
            "source_entries_count": len(source_entries),
            "source_keys": [e["key"] for e in source_entries],
            "synthesis": summary_res.get("data") or summary_res.get("payload") or {},
            "backend_engine": summary_res.get("engine", "heuristic"),
        }

        self.store.put(
            key=target_key,
            value=consolidated_payload,
            scope="global",
            ttl=None,
        )

        pruned_keys: list[str] = []
        if prune_transient:
            for e in source_entries:
                self.store.delete(key=e["key"], scope=scope)
                pruned_keys.append(e["key"])

        return {
            "status": "consolidated",
            "target_key": target_key,
            "target_scope": "global",
            "source_entries_count": len(source_entries),
            "pruned_keys": pruned_keys,
            "insights": consolidated_payload["synthesis"],
        }
