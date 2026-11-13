"""Read-time verification and prior_evidence builder for the evidence ledger."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.ledger.signature import (
    build_query_signature,
    extract_atomic_stems,
    jaccard_similarity,
)
from token_context_mcp.ledger.store import CardItemRecord, CardRecord, LedgerStore
from token_context_mcp.models import FileRecord, LedgerConfig, SymbolRecord
from token_context_mcp.retrieve.token_budget import count_tokens_o200k
from token_context_mcp.security.path_policy import PathPolicyError, safe_relative_path


class LedgerVerifier:
    """Re-verifies ledger citations against current disk bytes before serving."""

    def __init__(self) -> None:
        # (path, qualified_name, start_byte, end_byte, size, mtime_ns) -> body_sha256
        self._body_cache: dict[tuple[str, str, int, int, int, int], str] = {}
        # (repo_id, query) -> exact path-qualified overlay metadata for confirmed cards
        self._overlay_cache: dict[tuple[str, str], dict[str, Any]] = {}
        # (db_path_str, path) -> (dict[qualified_name, SymbolRecord], FileRecord | None)
        self._idx_path_cache: dict[tuple[str, str], tuple[dict[str, SymbolRecord], FileRecord | None]] = {}

    def get_overlay_meta(self, repo_id: str, query: str) -> dict[str, Any] | None:
        return self._overlay_cache.get((repo_id, query))

    def _current_body_sha256(
        self,
        root: Path,
        sym: SymbolRecord,
        *,
        file_rec: FileRecord | None = None,
        expected_sha256: str | None = None,
        allow_symlinks: bool = False,
    ) -> str | None:
        try:
            target = safe_relative_path(root, sym.path, allow_symlinks=allow_symlinks)
            stat = target.stat()
        except (PathPolicyError, OSError):
            return None

        cache_key = (
            sym.path,
            sym.qualified_name,
            sym.start_byte,
            sym.end_byte,
            stat.st_size,
            stat.st_mtime_ns,
        )
        cached = self._body_cache.get(cache_key)
        if cached is not None and (expected_sha256 is None or cached == expected_sha256):
            return cached

        try:
            raw = target.read_bytes()
        except OSError:
            return None

        digest: str | None = None
        if 0 <= sym.start_byte < sym.end_byte <= len(raw):
            digest = hashlib.sha256(raw[sym.start_byte : sym.end_byte]).hexdigest()

        # If lines were inserted/removed above the symbol before re-indexing, check shifted byte slice
        if (
            expected_sha256 is not None
            and digest != expected_sha256
            and file_rec is not None
            and len(raw) != file_rec.size
        ):
            delta = len(raw) - file_rec.size
            s_start = sym.start_byte + delta
            s_end = sym.end_byte + delta
            if 0 <= s_start < s_end <= len(raw):
                shifted = hashlib.sha256(raw[s_start:s_end]).hexdigest()
                if shifted == expected_sha256:
                    digest = shifted

        if digest is not None:
            self._body_cache[cache_key] = digest
        return digest

    def _verify_item(
        self,
        item: CardItemRecord,
        sym_by_key: dict[tuple[str, str], SymbolRecord],
        file_by_path: dict[str, FileRecord],
        root: Path,
        allow_symlinks: bool,
    ) -> tuple[str, SymbolRecord | None]:
        sym = sym_by_key.get((item.path, item.qualified_name))
        if sym is None:
            return "missing", None
        curr_sha = self._current_body_sha256(
            root,
            sym,
            file_rec=file_by_path.get(item.path),
            expected_sha256=item.body_sha256,
            allow_symlinks=allow_symlinks,
        )
        if curr_sha is None:
            return "missing", sym
        if curr_sha != item.body_sha256:
            return "changed", sym
        return "valid", sym

    def select_best_card(
        self,
        repo_id: str,
        query: str,
        ledger_store: LedgerStore,
        cfg: LedgerConfig,
    ) -> tuple[CardRecord | None, float]:
        if ledger_store.get_rev(repo_id) == 0:
            return None, 0.0
        sig = build_query_signature(query)
        if not sig.tokens:
            return None, 0.0
        q_set = set(sig.tokens)
        candidates = ledger_store.find_candidates(repo_id, sig.tokens)
        best_card: CardRecord | None = None
        best_key: tuple[int, float, int] = (-1, 0.0, -1)
        best_score = 0.0
        for card in candidates:
            score, overlap = jaccard_similarity(sig.tokens, card.sig_tokens)
            if score < cfg.answer_jaccard_min or overlap < cfg.answer_min_overlap:
                continue
            c_set = set(card.sig_tokens)
            if q_set != c_set:
                added_terms = q_set - c_set
                dropped_terms = c_set - q_set
                answer_stems: set[str] = set()
                decoy_stems: set[str] = set()
                for it in card.items:
                    if it.role == "answer":
                        answer_stems |= extract_atomic_stems(it.qualified_name)
                    elif it.role == "decoy":
                        decoy_stems |= extract_atomic_stems(it.qualified_name)
                # Contrastive Identifier Guard: reject sibling/collision queries that
                # add a decoy-specific stem or substitute a card token with a non-answer stem.
                if added_terms and (added_terms & (decoy_stems - answer_stems)):
                    continue
                if dropped_terms and added_terms and not (added_terms & answer_stems):
                    continue
            status_rank = 1 if card.status == "confirmed" else 0
            rank_key = (status_rank, round(score, 6), card.confirmations)
            if rank_key > best_key:
                best_key = rank_key
                best_card = card
                best_score = score
        return best_card, best_score

    def lookup_prior_evidence(
        self,
        *,
        repo_id: str,
        query: str,
        ledger_store: LedgerStore,
        idx_store: SQLiteStore,
        root: Path,
        allow_symlinks: bool,
        cfg: LedgerConfig,
    ) -> tuple[dict[str, Any] | None, list[str], int]:
        """Return (prior_evidence_or_none, warnings, ledger_rev)."""
        self._overlay_cache.pop((repo_id, query), None)
        ledger_rev = ledger_store.get_rev(repo_id)
        card, score = self.select_best_card(repo_id, query, ledger_store, cfg)
        if card is None:
            return None, [], ledger_rev

        item_paths = list({it.path for it in card.items})
        db_key = str(getattr(idx_store, "db_path", ""))
        sym_by_key: dict[tuple[str, str], SymbolRecord] = {}
        file_by_path: dict[str, FileRecord] = {}
        uncached_paths: list[str] = []
        for p in item_paths:
            cached_entry = self._idx_path_cache.get((db_key, p))
            if cached_entry is not None:
                s_map, f_rec = cached_entry
                for qn, s_rec in s_map.items():
                    sym_by_key[(p, qn)] = s_rec
                if f_rec is not None:
                    file_by_path[p] = f_rec
            else:
                uncached_paths.append(p)
        if uncached_paths:
            fetched_syms = idx_store.symbols_for_paths(uncached_paths)
            by_p: dict[str, dict[str, SymbolRecord]] = {p: {} for p in uncached_paths}
            for s_rec in fetched_syms:
                by_p.setdefault(s_rec.path, {})[s_rec.qualified_name] = s_rec
                sym_by_key[(s_rec.path, s_rec.qualified_name)] = s_rec
            for p in uncached_paths:
                f_rec = idx_store.file(p)
                if f_rec is not None:
                    file_by_path[p] = f_rec
                self._idx_path_cache[(db_key, p)] = (by_p.get(p, {}), f_rec)

        overlay_roles: dict[tuple[str, str], str] = {}
        overlay_steps: set[tuple[str, str]] = set()
        overlay_decoys: set[tuple[str, str]] = set()

        answers_out: list[list[Any]] = []
        valid_answer_count = 0
        for it in card.items:
            if it.role != "answer":
                continue
            state, sym = self._verify_item(it, sym_by_key, file_by_path, root, allow_symlinks)
            if state == "valid" and sym is not None:
                valid_answer_count += 1
                answers_out.append([sym.symbol_id, it.path, it.evidence_line or sym.start_line, state])
                if card.status == "confirmed":
                    overlay_roles[(it.path, it.qualified_name)] = "answer"

        if valid_answer_count == 0:
            ledger_store.set_status(card.card_id, "retired")
            return None, [], ledger_store.get_rev(repo_id)

        steps_out: list[list[Any]] = []
        recheck_from: int | None = None
        step_items = [it for it in card.items if it.role == "step"]
        for idx, it in enumerate(step_items, start=1):
            state, sym = self._verify_item(it, sym_by_key, file_by_path, root, allow_symlinks)
            if state != "valid":
                recheck_from = idx
                break
            steps_out.append(
                [
                    it.qualified_name,
                    it.next_qualified_name or "",
                    it.path,
                    it.evidence_line or (sym.start_line if sym else 0),
                    state,
                ]
            )
            if card.status == "confirmed" and it.next_qualified_name:
                overlay_steps.add((it.qualified_name, it.next_qualified_name))

        decoys_out: list[list[Any]] = []
        if card.status == "confirmed" and score >= cfg.decoy_jaccard_min:
            for it in card.items:
                if it.role != "decoy":
                    continue
                state, _ = self._verify_item(it, sym_by_key, file_by_path, root, allow_symlinks)
                if state == "valid":
                    decoys_out.append([it.qualified_name, it.reason_code or "unrelated"])
                    overlay_roles.setdefault((it.path, it.qualified_name), "decoy")
                    overlay_decoys.add((it.path, it.qualified_name))

        if card.status == "confirmed":
            self._overlay_cache[(repo_id, query)] = {
                "symbol_roles": overlay_roles,
                "step_edges": overlay_steps,
                "decoys": overlay_decoys,
            }

        prior: dict[str, Any] = {
            "ledger_rev": ledger_rev,
            "match": round(score, 4),
            "status": card.status,
            "answers": answers_out,
            "steps": steps_out,
            "decoys": decoys_out,
            "recheck_from": recheck_from,
        }

        # Enforce max_hint_tokens ceiling (trim decoys first, then trailing steps)
        while count_tokens_o200k(json.dumps(prior, separators=(",", ":")))[0] > cfg.max_hint_tokens:
            if prior["decoys"]:
                prior["decoys"].pop()
            elif prior["steps"]:
                prior["steps"].pop()
            elif len(prior["answers"]) > 1:
                prior["answers"].pop()
            else:
                break

        import time as _time
        now_ts = _time.time()
        if card.last_used_at is None or (now_ts - card.last_used_at) >= 3600.0:
            ledger_store.mark_used(card.card_id, now=now_ts)
        warnings: list[str] = []
        if card.status == "asserted":
            warnings.append("prior_evidence_unconfirmed")

        return prior, warnings, ledger_rev
