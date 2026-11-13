"""Write gate G1-G6 for the verified evidence ledger."""
from __future__ import annotations

import collections
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from token_context_mcp.index.sqlite_store import SQLiteStore
from token_context_mcp.kernel.pipeline import StructuredToolError
from token_context_mcp.ledger.store import CardItemRecord
from token_context_mcp.models import FileRecord, SymbolRecord
from token_context_mcp.retrieve.freshness import FreshnessCache
from token_context_mcp.security.path_policy import PathPolicyError, safe_relative_path

VALID_DECOY_REASONS: frozenset[str] = frozenset(
    {"no_reference", "test_only", "wrapper_only", "unrelated"}
)

MAX_ANSWERS = 8
MAX_STEPS = 12
MAX_DECOYS = 8
RATE_LIMIT_PER_MIN = 10


def compute_body_sha256(
    root: Path,
    symbol: SymbolRecord,
    *,
    allow_symlinks: bool = False,
) -> str | None:
    """Compute SHA-256 of the symbol's byte span [start_byte:end_byte] on disk."""
    try:
        target = safe_relative_path(root, symbol.path, allow_symlinks=allow_symlinks)
        raw = target.read_bytes()
    except (PathPolicyError, OSError):
        return None
    if symbol.start_byte < 0 or symbol.end_byte > len(raw) or symbol.start_byte >= symbol.end_byte:
        return None
    return hashlib.sha256(raw[symbol.start_byte : symbol.end_byte]).hexdigest()


def _read_line(
    root: Path,
    rel_path: str,
    line_no: int,
    *,
    allow_symlinks: bool = False,
) -> str | None:
    try:
        target = safe_relative_path(root, rel_path, allow_symlinks=allow_symlinks)
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except (PathPolicyError, OSError):
        return None
    if line_no < 1 or line_no > len(lines):
        return None
    return lines[line_no - 1]


def _language_from_symbol_id(symbol_id: str) -> str:
    return symbol_id.split(":", 1)[0] if ":" in symbol_id else "unknown"


@dataclass
class GateResult:
    verified_items: list[CardItemRecord]
    answer_results: list[dict[str, Any]]
    step_results: list[dict[str, Any]]
    decoy_results: list[dict[str, Any]]


class WriteGate:
    """Validates G1-G6 before any trajectory evidence enters ledger.sqlite."""

    def __init__(self) -> None:
        self._rate_windows: dict[str, collections.deque[float]] = collections.defaultdict(
            collections.deque
        )

    def check_rate_and_limits(
        self,
        agent_id: str,
        answers: list[str],
        steps: list[str],
        decoys: list[str],
        *,
        now: float | None = None,
    ) -> None:
        if len(answers) > MAX_ANSWERS:
            raise StructuredToolError(
                "limit_exceeded",
                f"answers count {len(answers)} exceeds limit {MAX_ANSWERS}",
                field="answers",
                limit=MAX_ANSWERS,
            )
        if len(steps) > MAX_STEPS:
            raise StructuredToolError(
                "limit_exceeded",
                f"steps count {len(steps)} exceeds limit {MAX_STEPS}",
                field="steps",
                limit=MAX_STEPS,
            )
        if len(decoys) > MAX_DECOYS:
            raise StructuredToolError(
                "limit_exceeded",
                f"decoys count {len(decoys)} exceeds limit {MAX_DECOYS}",
                field="decoys",
                limit=MAX_DECOYS,
            )

        ts = now if now is not None else time.monotonic()
        win = self._rate_windows[agent_id]
        cutoff = ts - 60.0
        while win and win[0] < cutoff:
            win.popleft()
        if len(win) >= RATE_LIMIT_PER_MIN:
            raise StructuredToolError(
                "limit_exceeded",
                f"trajectory_record rate limit ({RATE_LIMIT_PER_MIN}/min) exceeded for agent '{agent_id}'",
                limit=RATE_LIMIT_PER_MIN,
            )
        win.append(ts)

    def validate(
        self,
        *,
        store: SQLiteStore,
        root: Path,
        freshness: FreshnessCache,
        allow_symlinks: bool,
        answers: list[str],
        steps: list[str],
        decoys: list[str],
    ) -> GateResult:
        file_map: dict[str, FileRecord] = {f.path: f for f in store.files()}
        verified: list[CardItemRecord] = []
        ans_res: list[dict[str, Any]] = []
        step_res: list[dict[str, Any]] = []
        decoy_res: list[dict[str, Any]] = []

        def _check_fresh(path: str) -> bool:
            rec = file_map.get(path)
            if rec is None:
                return False
            state, _ = freshness.path_state(root, rec, allow_symlinks=allow_symlinks)
            return state == "fresh"

        for ord_idx, raw in enumerate(answers):
            if "@" not in raw:
                ans_res.append({"input": raw, "status": "rejected", "reason": "invalid_format"})
                continue
            sid, line_str = raw.rsplit("@", 1)
            try:
                line_no = int(line_str)
            except ValueError:
                ans_res.append({"input": raw, "status": "rejected", "reason": "invalid_format"})
                continue

            sym = store.symbol(sid)
            if sym is None:
                ans_res.append({"input": raw, "status": "rejected", "reason": "unknown_symbol"})
                continue
            if not _check_fresh(sym.path):
                ans_res.append({"input": raw, "status": "rejected", "reason": "stale_file"})
                continue
            if not (sym.start_line <= line_no <= sym.end_line):
                ans_res.append({"input": raw, "status": "rejected", "reason": "line_outside_symbol"})
                continue
            line_text = _read_line(root, sym.path, line_no, allow_symlinks=allow_symlinks)
            body_sha = compute_body_sha256(root, sym, allow_symlinks=allow_symlinks)
            if line_text is None or body_sha is None:
                ans_res.append({"input": raw, "status": "rejected", "reason": "stale_file"})
                continue
            line_sha = hashlib.sha256(line_text.encode("utf-8")).hexdigest()[:12]
            verified.append(
                CardItemRecord(
                    card_id=0,
                    role="answer",
                    ord=ord_idx,
                    language=_language_from_symbol_id(sym.symbol_id),
                    path=sym.path,
                    qualified_name=sym.qualified_name,
                    body_sha256=body_sha,
                    evidence_line=line_no,
                    line_sha=line_sha,
                    check_kind="source_verified",
                )
            )
            ans_res.append({"input": raw, "status": "verified"})

        for ord_idx, raw in enumerate(steps):
            if ">" not in raw or "@" not in raw:
                step_res.append({"input": raw, "status": "rejected", "reason": "invalid_format"})
                continue
            pair_part, line_str = raw.rsplit("@", 1)
            if ">" not in pair_part:
                step_res.append({"input": raw, "status": "rejected", "reason": "invalid_format"})
                continue
            from_id, to_id = pair_part.split(">", 1)
            try:
                line_no = int(line_str)
            except ValueError:
                step_res.append({"input": raw, "status": "rejected", "reason": "invalid_format"})
                continue

            if from_id == to_id:
                step_res.append({"input": raw, "status": "rejected", "reason": "self_loop_step"})
                continue

            from_sym = store.symbol(from_id)
            to_sym = store.symbol(to_id)
            if from_sym is None or to_sym is None:
                step_res.append({"input": raw, "status": "rejected", "reason": "unknown_symbol"})
                continue
            if not _check_fresh(from_sym.path):
                step_res.append({"input": raw, "status": "rejected", "reason": "stale_file"})
                continue
            if not (from_sym.start_line <= line_no <= from_sym.end_line):
                step_res.append({"input": raw, "status": "rejected", "reason": "line_outside_symbol"})
                continue
            line_text = _read_line(root, from_sym.path, line_no, allow_symlinks=allow_symlinks)
            body_sha = compute_body_sha256(root, from_sym, allow_symlinks=allow_symlinks)
            if line_text is None or body_sha is None:
                step_res.append({"input": raw, "status": "rejected", "reason": "stale_file"})
                continue
            # G4: target symbol's name must appear as an identifier on that disk line
            if not re.search(rf"\b{re.escape(to_sym.name)}\b", line_text):
                step_res.append({"input": raw, "status": "rejected", "reason": "evidence_mismatch"})
                continue

            out_edges = store.edges_from(from_sym.symbol_id)
            edge_exists = any(e.target_symbol_id == to_sym.symbol_id for e in out_edges)
            line_sha = hashlib.sha256(line_text.encode("utf-8")).hexdigest()[:12]
            verified.append(
                CardItemRecord(
                    card_id=0,
                    role="step",
                    ord=ord_idx,
                    language=_language_from_symbol_id(from_sym.symbol_id),
                    path=from_sym.path,
                    qualified_name=from_sym.qualified_name,
                    body_sha256=body_sha,
                    evidence_line=line_no,
                    line_sha=line_sha,
                    next_qualified_name=to_sym.qualified_name,
                    check_kind="source_verified",
                    index_edge_missing=not edge_exists,
                )
            )
            item_res: dict[str, Any] = {"input": raw, "status": "verified"}
            if not edge_exists:
                item_res["index_edge_missing"] = True
            step_res.append(item_res)

        for ord_idx, raw in enumerate(decoys):
            if "!" not in raw:
                decoy_res.append({"input": raw, "status": "rejected", "reason": "invalid_format"})
                continue
            sym_part, reason_code = raw.rsplit("!", 1)
            if reason_code not in VALID_DECOY_REASONS:
                decoy_res.append({"input": raw, "status": "rejected", "reason": "invalid_reason_code"})
                continue

            target_sym: SymbolRecord | None = None
            if ">" in sym_part:
                u_id, v_id = sym_part.split(">", 1)
                sym = store.symbol(u_id)
                target_sym = store.symbol(v_id)
                if sym is None or target_sym is None:
                    decoy_res.append({"input": raw, "status": "rejected", "reason": "unknown_symbol"})
                    continue
            else:
                sym = store.symbol(sym_part)
                if sym is None:
                    decoy_res.append({"input": raw, "status": "rejected", "reason": "unknown_symbol"})
                    continue

            if not _check_fresh(sym.path):
                decoy_res.append({"input": raw, "status": "rejected", "reason": "stale_file"})
                continue
            body_sha = compute_body_sha256(root, sym, allow_symlinks=allow_symlinks)
            if body_sha is None:
                decoy_res.append({"input": raw, "status": "rejected", "reason": "stale_file"})
                continue

            check_kind = "source_verified"
            if reason_code == "no_reference":
                if target_sym is not None:
                    try:
                        target_file = safe_relative_path(root, sym.path, allow_symlinks=allow_symlinks)
                        span_text = target_file.read_bytes()[sym.start_byte : sym.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                        if re.search(rf"\b{re.escape(target_sym.name)}\b", span_text):
                            check_kind = "asserted"
                    except (PathPolicyError, OSError):
                        check_kind = "asserted"
                else:
                    check_kind = "asserted"

            verified.append(
                CardItemRecord(
                    card_id=0,
                    role="decoy",
                    ord=ord_idx,
                    language=_language_from_symbol_id(sym.symbol_id),
                    path=sym.path,
                    qualified_name=sym.qualified_name,
                    body_sha256=body_sha,
                    next_qualified_name=target_sym.qualified_name if target_sym else None,
                    reason_code=reason_code,
                    check_kind=check_kind,
                )
            )
            decoy_res.append({"input": raw, "status": "verified", "check_kind": check_kind})

        return GateResult(
            verified_items=verified,
            answer_results=ans_res,
            step_results=step_res,
            decoy_results=decoy_res,
        )
