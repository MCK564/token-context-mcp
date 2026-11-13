"""Service facade for the verified evidence ledger."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from token_context_mcp.config import get_repository, index_directory
from token_context_mcp.index.runner import current_pointer_path, database_path
from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.kernel.context import get_current_context
from token_context_mcp.kernel.pipeline import StructuredToolError
from token_context_mcp.ledger.gate import WriteGate
from token_context_mcp.ledger.signature import build_query_signature
from token_context_mcp.ledger.store import CardRecord, LedgerStore
from token_context_mcp.models import AppConfig
from token_context_mcp.retrieve.freshness import FreshnessCache


class LedgerService:
    """Coordinates verified writes and operator management of ledger.sqlite."""

    def __init__(self, config: AppConfig, config_path: Path) -> None:
        self.config = config
        self.config_path = config_path
        self.store = LedgerStore(
            config_path.parent / "ledger.sqlite",
            max_cards_per_repo=config.ledger.max_cards_per_repo,
            ttl_days=config.ledger.ttl_days,
        )
        self.gate = WriteGate()
        self.freshness = FreshnessCache()

    def _index_store(self, repo_id: str) -> SQLiteStore:
        idx_dir = index_directory(self.config_path)
        ptr_file = current_pointer_path(idx_dir, repo_id)
        db: Path | None = None
        if ptr_file.is_file():
            try:
                data = json.loads(ptr_file.read_text(encoding="utf-8"))
                db_name = data.get("db")
                if db_name:
                    cand = idx_dir / str(db_name)
                    if cand.exists():
                        db = cand
            except Exception:
                db = None
        if db is None:
            db = database_path(idx_dir, repo_id)
        if not db.exists():
            raise StructuredToolError("index_missing", f"No index database found for repo_id '{repo_id}'")
        return SQLiteStore(db, read_only=True)

    def trajectory_record(
        self,
        repo_id: str,
        query: str,
        answers: list[str],
        steps: list[str] | None = None,
        decoys: list[str] | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        repo_cfg = get_repository(self.config, repo_id)
        ctx = get_current_context()
        eff_agent = agent_id or (ctx.effective_agent_id if ctx else "anonymous")
        eff_run = run_id or (ctx.run_id if ctx and ctx.run_id else "run_local")

        steps_list = steps or []
        decoys_list = decoys or []
        self.gate.check_rate_and_limits(eff_agent, answers, steps_list, decoys_list)

        sig = build_query_signature(query)
        if not sig.tokens:
            raise StructuredToolError("empty_signature", "query produced no indexable signature tokens")

        idx_store = self._index_store(repo_id)
        index_run_id = str(idx_store.metadata().get("index_run_id") or "unknown")
        gate_res = self.gate.validate(
            store=idx_store,
            root=repo_cfg.root,
            freshness=self.freshness,
            allow_symlinks=repo_cfg.allow_symlinks,
            answers=answers,
            steps=steps_list,
            decoys=decoys_list,
        )

        card_id: int | None = None
        card_status = "rejected"
        ledger_rev = self.store.get_rev(repo_id)

        has_verified_answer = any(it.role == "answer" for it in gate_res.verified_items)
        if has_verified_answer:
            card_id, card_status, ledger_rev = self.store.upsert_card(
                repo_id=repo_id,
                sig_tokens_json=sig.sig_tokens_json,
                sig_hash=sig.sig_hash,
                fts_text=sig.fts_text,
                agent_id=eff_agent,
                run_id=eff_run,
                index_run_id=index_run_id,
                items=gate_res.verified_items,
            )

        return {
            "schema_version": "1.0",
            "repo_id": repo_id,
            "data": {
                "card_id": card_id,
                "sig_hash": sig.sig_hash,
                "status": card_status,
                "ledger_rev": ledger_rev,
                "verified_count": len(gate_res.verified_items),
                "answers": gate_res.answer_results,
                "steps": gate_res.step_results,
                "decoys": gate_res.decoy_results,
            },
        }

    def list_cards(self, repo_id: str | None = None) -> list[dict[str, Any]]:
        cards = self.store.list_cards(repo_id=repo_id)
        return [
            {
                "card_id": c.card_id,
                "repo_id": c.repo_id,
                "sig_hash": c.sig_hash,
                "sig_tokens": list(c.sig_tokens),
                "status": c.status,
                "confirmations": c.confirmations,
                "items_count": len(c.items),
                "agent_id": c.agent_id,
                "run_id": c.run_id,
            }
            for c in cards
        ]

    def show_card(self, card_id: int) -> dict[str, Any] | None:
        card = self.store.get_card(card_id)
        if card is None:
            return None
        return asdict(card)

    def confirm_card(self, card_id: int) -> bool:
        return self.store.confirm_card(card_id)

    def forget_card(self, card_id: int) -> bool:
        return self.store.forget_card(card_id)

    def prune(self, repo_id: str | None = None) -> int:
        return self.store.prune(repo_id=repo_id)

    def export_cards(self, repo_id: str | None = None, fmt: str = "json") -> str:
        cards = self.store.list_cards(repo_id=repo_id)
        if fmt == "json":
            return json.dumps([asdict(c) for c in cards], indent=2)
        if fmt == "md":
            lines = ["# Verified Evidence Ledger Export", ""]
            for c in cards:
                lines.append(f"## Card #{c.card_id} (`{c.repo_id}` · `{c.status}` · sig `{c.sig_hash}`)")
                lines.append(f"- Tokens: `{', '.join(c.sig_tokens)}`")
                for it in c.items:
                    extra = f" -> `{it.next_qualified_name}`" if it.next_qualified_name else ""
                    reason = f" ({it.reason_code})" if it.reason_code else ""
                    line_ref = f":{it.evidence_line}" if it.evidence_line else ""
                    lines.append(f"  - [{it.role}] `{it.path}{line_ref}` `{it.qualified_name}`{extra}{reason}")
                lines.append("")
            return "\n".join(lines)
        raise ValueError(f"Unsupported export format: {fmt}")
