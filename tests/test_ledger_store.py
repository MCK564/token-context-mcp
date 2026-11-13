from __future__ import annotations

import time
from pathlib import Path

from token_context_mcp.ledger.store import CardItemRecord, LedgerStore


def _ans(path: str, qname: str, body_sha: str = "a" * 64) -> CardItemRecord:
    return CardItemRecord(
        card_id=0,
        role="answer",
        ord=0,
        language="python",
        path=path,
        qualified_name=qname,
        body_sha256=body_sha,
        evidence_line=10,
        line_sha="1234567890ab",
        check_kind="source_verified",
    )


def _decoy(path: str, qname: str, reason: str = "unrelated") -> CardItemRecord:
    return CardItemRecord(
        card_id=0,
        role="decoy",
        ord=0,
        language="python",
        path=path,
        qualified_name=qname,
        body_sha256="b" * 64,
        reason_code=reason,
        check_kind="source_verified",
    )


def test_store_asserted_to_confirmed_and_conflict(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.sqlite", max_cards_per_repo=10, ttl_days=28)

    cid1, st1, rev1 = store.upsert_card(
        repo_id="repo1",
        sig_tokens_json='["alpha","beta"]',
        sig_hash="sig1",
        fts_text="alpha beta",
        agent_id="a1",
        run_id="run_1",
        index_run_id="idx_1",
        items=[_ans("a.py", "fn_a")],
    )
    assert st1 == "asserted"
    assert rev1 == 1

    # Same run_id does not promote to confirmed
    cid2, st2, _ = store.upsert_card(
        repo_id="repo1",
        sig_tokens_json='["alpha","beta"]',
        sig_hash="sig1",
        fts_text="alpha beta",
        agent_id="a1",
        run_id="run_1",
        index_run_id="idx_1",
        items=[_ans("a.py", "fn_a")],
    )
    assert cid2 == cid1
    assert st2 == "asserted"

    # Different run_id with same answers promotes to confirmed
    _, st3, _ = store.upsert_card(
        repo_id="repo1",
        sig_tokens_json='["alpha","beta"]',
        sig_hash="sig1",
        fts_text="alpha beta",
        agent_id="a2",
        run_id="run_2",
        index_run_id="idx_1",
        items=[_ans("a.py", "fn_a")],
    )
    assert st3 == "confirmed"

    # Conflict: old answer becomes decoy -> status conflicted and not returned by find_candidates
    _, st4, _ = store.upsert_card(
        repo_id="repo1",
        sig_tokens_json='["alpha","beta"]',
        sig_hash="sig1",
        fts_text="alpha beta",
        agent_id="a3",
        run_id="run_3",
        index_run_id="idx_1",
        items=[_ans("b.py", "fn_b"), _decoy("a.py", "fn_a")],
    )
    assert st4 == "conflicted"
    assert store.find_candidates("repo1", ("alpha", "beta")) == []


def test_store_eviction_and_prune(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.sqlite", max_cards_per_repo=2, ttl_days=1)
    now = time.time()
    store.upsert_card(
        repo_id="r",
        sig_tokens_json='["k1"]',
        sig_hash="h1",
        fts_text="k1",
        agent_id="a",
        run_id="r1",
        index_run_id="i1",
        items=[_ans("a.py", "f1")],
        now=now - 100,
    )
    store.upsert_card(
        repo_id="r",
        sig_tokens_json='["k2"]',
        sig_hash="h2",
        fts_text="k2",
        agent_id="a",
        run_id="r1",
        index_run_id="i1",
        items=[_ans("a.py", "f2")],
        now=now - 50,
    )
    store.upsert_card(
        repo_id="r",
        sig_tokens_json='["k3"]',
        sig_hash="h3",
        fts_text="k3",
        agent_id="a",
        run_id="r1",
        index_run_id="i1",
        items=[_ans("a.py", "f3")],
        now=now,
    )
    cards = store.list_cards("r")
    assert len(cards) == 2
    assert {c.sig_hash for c in cards} == {"h2", "h3"}

    pruned = store.prune("r", now=now + 2 * 86400)
    assert pruned == 2
    assert store.list_cards("r") == []


def test_store_fts5_reserved_keywords_and_confirmed_hijack_guard(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "ledger.sqlite", max_cards_per_repo=10, ttl_days=28)
    store.upsert_card(
        repo_id="r",
        sig_tokens_json='["near","syntax"]',
        sig_hash="h_near",
        fts_text="near syntax",
        agent_id="a1",
        run_id="r1",
        index_run_id="i1",
        items=[_ans("a.py", "fn_orig")],
    )
    store.upsert_card(
        repo_id="r",
        sig_tokens_json='["near","syntax"]',
        sig_hash="h_near",
        fts_text="near syntax",
        agent_id="a2",
        run_id="r2",
        index_run_id="i1",
        items=[_ans("a.py", "fn_orig")],
    )
    # FTS5 reserved words ('near', 'not', 'and', 'or') must not raise OperationalError
    cands = store.find_candidates("r", ("near", "not", "and", "or", "syntax"))
    assert len(cands) == 1
    assert cands[0].status == "confirmed"

    # Attempting to overwrite a confirmed card with a different answer in r3 must mark it conflicted
    _, st, _ = store.upsert_card(
        repo_id="r",
        sig_tokens_json='["near","syntax"]',
        sig_hash="h_near",
        fts_text="near syntax",
        agent_id="a3",
        run_id="r3",
        index_run_id="i1",
        items=[_ans("b.py", "fn_hijack")],
    )
    assert st == "conflicted"
    assert store.find_candidates("r", ("near", "syntax")) == []
