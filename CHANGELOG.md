# Changelog

## Unreleased — M6 Session 1: `attr_param` recall + `inspect_symbol` relationship contract fix (2026-09-27, branch `feat/m6-hcp-packet`)

- **M6.0 — typed-parameter → self-attribute recall (`parse/treesitter.py`, `parse/lexical_edges.py`)**:
  - `_extract_class_attributes` now also resolves `self.x = <param>` when `<param>` carries a type annotation on the enclosing method — both `typed_parameter` and `typed_default_parameter` AST nodes (e.g. constructor dependency injection: `def __init__(self, service: RetrievalService): self.service = service`). This was the single largest source of `unresolved_receiver` edges in the repo: the pattern is used throughout the GUI controllers and across `retrieve/workflows.py`.
  - Container-typed parameters (`dict[...]`, `list[...]`, …) are skipped, and an attribute assigned from parameters of two different types across methods stays tainted/unresolved — same rules M4.3 already applied to `self.x = Cls(...)`.
  - New edge scope `attr_param`, confidence 0.90 (provisional, uncalibrated: n=25 at introduction — see `evals/out/m6/edge_audit_after_m6.json`'s `scope_counts`).
  - Effect on the real repo, isolated via `git stash`/`sync_index.sh`/eval so only this diff differs between the two measurements (`evals/out/m6/edge_audit_before_m6.json` vs `edge_audit_after_m6.json`): `scope:unresolved_receiver` 300 → 280 (-20), `scope:attr_param` 0 → 25 (new), `scope:attr_type` 64 → 65 (stable, no cannibalization), 0 active false positives before and after (`evals/out/m6/edge_eval_{before,after}_m6.json`, Part A `active_false_positives`). The 25 newly-resolved call sites (source path:line → target), including the motivating `CompositeWorkflowEngine._inspect_symbol_scoped` → `RetrievalService.find_symbols`/`symbol_context`/`symbol_relationships` example, are listed in full in `evals/out/m6/attr_param_new_edges_m6.json`.
  - Note: the gold-set-relative Part A/B numbers in those same eval files (accuracy ~57-58%, Part B recall 30%) read far below the M4-era baseline (84.67%/88.33%) — confirmed pre-existing and orthogonal to this change (identical in both before/after measurements): `evals/gold/edges_token_context.json` is keyed by exact `source_symbol_id`/`source_path`+`source_line`, which has drifted as the repo grew across M5/M6. Tracked as a backlog item; not a M6.0 regression.
- **E14 — `inspect_symbol` relationship contract fix (`retrieve/service.py`, `retrieve/workflows.py`)**: root cause was that `_inspect_symbol_scoped` fetched relationships via `impact_slice`, which has its own internal packing budget — at `budget_tokens < 2048` this gave `impact_slice` as little as 256 tokens, which could fail its own budget check and silently return zero edges regardless of how much of the *caller's* budget was actually free. Supersedes the partial mitigation in the M2/G4 entry above (raising `slice_tokens`), which reduced but did not eliminate the failure mode.
  - Added `RetrievalService.symbol_relationships(repo_id, symbol_id, min_confidence=0.5)`: reads one-hop in/out edges directly from the cached `RepoGraph` and applies the shared `edge_is_traversable` predicate (promoted from `retrieve/expansion.py`, now used by both M5 graph-expansion and this method) — resolved, `backend=lexical`, real target, `confidence >= min_confidence`. No dependency on any other call's budget.
  - `_inspect_symbol_scoped` now packs this pre-filtered, deterministically-sorted (confidence desc, then symbol_id) edge list into whatever budget remains after the symbol body, via a new `_pack_rows_to_budget` helper — a relationship is only ever dropped for genuinely not fitting, never by an unrelated internal budget.
  - **Contract changes (approved for M6)**:
    - `minimal` view `relationships`: compact list `[[symbol_id, "callee"|"caller", confidence], ...]`, quality-filtered as above.
    - `normal` view: same filter; unchanged dict shape (`source`/`target`/`kind`/`confidence`).
    - `full` view: `relationships` is now the same filtered/packed list as `normal` (previously: `normal`'s edges plus raw, unfiltered ones). `data.packet` is **not** part of this change — that is M6 Session 2 (M6.1/M6.2).
    - New `data.relationships_filtered` field: count of edges excluded by the quality filter (ambiguous / stub / `confidence < 0.5`), kept distinct from the pre-existing `data.relationships_omitted` (budget-driven truncation).
  - Test coverage: `tests/test_inspect_symbol_budget.py` (4 new tests against a fixture mirroring a pattern confirmed live on the real repo — a resolved same-file callee, an ambiguous unresolved-receiver call, and a stdlib `virtual_stub` call — plus 1 pre-existing test updated: 5→12 synthetic callees, because the fix itself made a 5-callee/256-token case no longer "tight").
- Full pytest suite: 276 tests collected, all passing (1 pre-existing skip), no regressions from either change.

## Unreleased — M5.2/M5.3 LARGER-lite graph expansion in `search_source` (2026-09-27, branch `feat/m5-larger-lite`)

- **`search_source` contract (additive)**: new optional arguments `expand` (`auto` | `none` | `graph`, default `auto`), `expand_k` (1–8, default 3), `expand_hops` (1–2, default 1), `min_confidence` (0–1, default 0.6). Concrete types with defaults, no nullable `anyOf`.
  - `expand="auto"` resolves to `graph` only for `profile="locate"`; calls without a profile keep the M5.1 behaviour (`none`). Output for `expand="none"`/`auto` without profile is byte-identical to M5.1 (tested).
  - With `graph`, the response adds `neighbors: [[symbol_id, "path:line", "<kind> <name>", "callee|caller|test", score, anchor_id], ...]` and `retrieval: {expand_effective, profile_effective, anchors, neighbors, expand_k, expand_hops, min_confidence}`. The text summary shows `neighbors=<n>`.
  - Neighbors take at most 25% of the packing budget and come out of the same `max_tokens`; neighbors whose anchor was packed out are dropped.
- **Expansion (`retrieve/expansion.py`)**: top-5 matches are anchors; `<module>` anchors keep their rank but are not expanded. BFS over edges that are `resolved`, `backend=lexical`, point at a real symbol and have `confidence >= min_confidence` (excludes `global` 0.40, `unknown_receiver` 0.10, stubs). Score = best path product × 1.2 same file community × 0.5 utility hub (in-degree z > 3) × 0.5 test/eval path × (1 + 0.5·query terms in the name). Deterministic ordering (anchor rank, score, path, line). Relation labels: `callee`, `caller`, `test` only (the DB has `call` edges only; no `inherit`).
- **File communities (M5.3)**: deterministic label propagation over the undirected in-repo import graph, computed lazily per index run and cached on `RepoGraph`. Deviation from plan: no `file_community` table and no schema bump; index schema stays 2.3. `SQLiteStore.import_pairs()` added.
- **Ranking of AND/OR rows**: AND and OR top-up rows are now ranked together: non-test before `tests/`/`evals/`, AST symbols before `<module>`, AND before OR, then bm25. Fixes an eval file that embedded a task query outranking all source hits. Term-coverage ranking (F9) was implemented and **rejected on the dev split** (sym MRR 0.494 → 0.293 body-coverage, 0.423 name-coverage); kept behind `_COVERAGE_RANKING = "off"` for ablation only.
- **Evals**: `loc_eval` now ranks each neighbor right after its anchor (was: after every match, so neighbors could never enter top-10) and reports `sym_recall_in_response` and `mean_neighbor_count`. New `evals/bench_search_source.py` replays the task queries per expand mode (M5 latency protocol). `evals/stdio_smoke.py` search check is now clean-room (temp repo) instead of depending on the local registry.
- **Correction to the M5.1 entry below**: "latency p50 5.08 ms" was measured on a single easy query; on the 30 task queries M5.1 measured p50 ≈ 40–48 ms on Windows. See `evals/out/m5/latency_search_source_m5_2_vm.json` for the task-query protocol.

## Unreleased — M5.1 Symbol-level FTS & Code Tokenization (2026-09-26, branch `feat/m5-larger-lite`)

- **Index Schema 2.3 (`symbol_fts`)**:
  - Added SQLite FTS5 virtual table `symbol_fts` using `unicode61 remove_diacritics 2 tokenchars '_'` tokenizer.
  - Columns indexed: `symbol_id`, `path`, `name`, `code_tokens`, `docstring`, `body`.
  - Nested body exclusion: symbols only index their `own_body` statements, stripping child symbol line spans to prevent parent classes or functions from diluting BM25 match density.
  - File-level pseudo-symbols: created `<module>` symbol per file (`symbol_id = f"{lang}:{path}:<module>"`) to index top-level statements, imports, and constants.
  - Snapshot migration: preserves backward compatibility with `source_bodies` in `sqlite_store.py`.
- **Code Tokenization (`code_tokens.py`)**:
  - Deterministic splitting of programming identifiers across `snake_case`, `camelCase`, `PascalCase`, numbers (`parseV2Config` -> `parse`, `v2`, `config`), acronyms (`HTTPServer` -> `http`, `server`), Vietnamese diacritics, and file path segments.
- **Output Contract & Retrieval Optimization**:
  - `search_source` contract refined: returns 1 entry per matching symbol (capped at 3 symbols per file) with new `lines: [[line_number, snippet_text], ...]` array preserving top matching spans.
  - Backward compatibility: `start_line` and `snippet` fields preserved, pointing to the top scoring line of the symbol.
  - Zero N+1 queries: `SQLiteStore.search_symbol_matches` performs `LEFT JOIN files` and `LEFT JOIN symbols` to eagerly retrieve file hashes and AST kinds within a single query (`last_query_count <= 3`).
  - Search latency p50 reduced to 5.08 ms (< 40 ms threshold), symbol recall@10 jumped from 0.1500 to 0.7250 on heldout eval tasks.

## Unreleased — M4 Edge Accuracy & Resolution Calibration (2026-09-26, branch `feat/m4-edge-accuracy`)

- **Root Cause Fixes for False Positive Edges**:
  - Eliminated naive substring matching (`imp in c.path`) in favor of exact segment suffix matching (`_path_segments` and `_import_matches_candidate`).
  - Added receiver-type resolution via class-level attribute extraction and PyCG-style type inference (`attr_type` scope with confidence 0.95).
  - Scope naming convention note:
    - `import_match`: symbol imported directly (`from mod import func`) or imported module path segment match. Corresponds conceptually to contract specification `name_imported`. Retained to maintain index compatibility.
    - `import_module_match`: call qualified by imported module alias/name (`mod.func()`). Corresponds conceptually to contract specification `module_exact`. Retained to maintain index compatibility.
- **SCOPE_CONFIDENCE Calibration**:
  - Calibrated based on empirical precision from evaluated gold set (150 samples: 114 TP, 36 FP; 0 active FP, precision 100.0%):
    - `exact_receiver_type`: 0.95 (n=30, prec 1.0)
    - `same_class`: 0.95 (n=22, prec 1.0)
    - `import_match`: 0.95 (n=26, prec 1.0)
    - `same_file`: 0.95 (n=23, prec 1.0)
    - `attr_type`: 0.95 (receiver attribute type match)
    - `import_module_match`: 0.75 (n=5, prec 1.0, conservative default for n < 10)
    - `same_package`: 0.75 (n=3, conservative default for n < 10)
    - `global`: 0.40 (n=5, elim FP 20, TP 2)
    - `virtual_stub`: 0.90 (virtual external stubs)
    - `unknown_receiver` / `unresolved_receiver`: 0.10 (ambiguous fallback)
  - Ceiling rule: empirical precision is conservatively capped at 0.95 rather than 1.00 to account for statistical generalization.
- **Top-20 In-Degree Normalization**:
  - `MemoryStore.get` in-degree reduced from 96 (dominated by false generic calls like `dict.get`, `os.environ.get`) to 10 legitimate callers.
  - Overall accuracy achieved 85.33% (128/150 raw eval); recall achieved 85.00% (1.159x baseline).
- **Known Ranking Regression (dynamic_mode)**:
  - Pruning of false positive edges shifted relative node degrees, causing `extract_with_trace` (rank 5 -> 8) and `run_with_diagnostics` (rank 7 -> 11) to drop in dynamic on-the-fly ranking, reducing dynamic nDCG@10 from 0.5248 to 0.4908 (-0.034).
  - In contrast, production index-time `cached_mode` nDCG@10 improved significantly from 0.4224 to 0.5410 (+0.1186). M5 commits to no further regression.

## Unreleased — M3 Query IO, Latency & Freshness Caching (2026-09-25, branch `feat/m3b-rank-cache`)

- **FreshnessCache & ReadConnectionPool**: In-memory mtime cache with zero disk I/O when unchanged, snapshot-isolated read pool.
- **PageRank & Personalized PageRank**: Index-time global PageRank and fast query-time local push PPR.
- **RepoGraph Cache**: In-memory caching of adjacency graphs for sub-millisecond graph traversals.

## Unreleased — M2-F Remediation & Bug Fixes (2026-09-25, branch `feat/m2-governance`)

- **G1 (P0 Memory Migration & Auto-repair)**: `MemoryStore` v3 migration, automated detection and rebuild of broken legacy FTS tables lacking `namespace` column, backup to `.bak-v<ver>`, leaf string value re-redaction, refined SQLite error handling distinguishing syntax errors from structural errors.
- **G2 (GUI Bridge Read/Write Separation)**: `AgentSecurityController` wired to `GovernanceStore`, `refresh_data()` made pure query via `merge_seen_agents()`, eliminating unexpected write mutations on GUI refresh.
- **G3 (Agent Policy Synchronization)**: Added `policy` and `custom_tools_json` columns to `governance.sqlite` `agents` table, reduced access control cache TTL to 0.5s, cross-process policy sync verified within 0.6s.
- **G4 (inspect_symbol Compact Relationships)**: Used compact edge dicts in `normal` view, increased edge retrieval ceiling (`slice_tokens`), added explicit `relationships_truncated` warning and `relationships_omitted` field when truncated.

## Unreleased — M2 Governance & Memory Safety (2026-09-24, branch `feat/m2-governance`)

- **Admin tools gate** (`enable_admin_tools: bool = False`): `agent_control` and `audit_logs` only registered when opt-in flag is set; `action=status` always public, all other actions require `TOKEN_CONTEXT_ADMIN_TOKEN`.
- **Token protection**: admin token verified with `hmac.compare_digest`; never reflected in audit log; invalid token returns `permission_revoked` with opaque reason.
- **Shared governance store** (`security/governance_store.py`): WAL-mode SQLite (`governance.sqlite`) with tables `agents`, `emergency`, `server_heartbeats`; 5 s busy-timeout; server records heartbeat every ≥15 s per call.
- **Agent identity resolution** (`resolve_effective_agent_id`): reads `TOKEN_CONTEXT_AGENT_ID` env, validates `^[a-zA-Z0-9_-]{1,64}$`, falls back to `"anonymous"`; anonymous agent exempt from rate limiting but subject to all other controls.
- **Atomic memory lock**: single `INSERT … ON CONFLICT DO UPDATE WHERE …` — one winner across any number of concurrent processes; `memory_unlock` tool added.
- **Memory namespace isolation**: `key_values` schema v2 — `PRIMARY KEY (scope, namespace, key)`; existing DBs backed up before migration; `namespace=""` default preserves backward compatibility.
- **Value redaction** (`_redact_value`): recursively applies `content_policy.redact_text` to all leaf strings before storage.
- **Periodic TTL cleanup**: expired entries purged every 100 `put` calls.
- **GUI read-only governance refresh** (`GovernanceRefreshWorker`): polls `governance.sqlite` every 5 s; never writes; `AgentSecurityController` starts it automatically; `active_servers_updated` signal added.
- **Test coverage**: 161 passed, 6 skipped (GUI tests); new files `test_server_governance.py`, `test_governance_store.py`, `test_memory_lock_atomic.py`, `test_memory_namespace.py`; 3 new tests in `test_gui_bridge.py`.

## Unreleased — POSIX hosts and snapshot privacy (2026-08-30)

- Created the registry, snapshots, manifests and WAL sidecars owner-only (`0700`/`0600`) instead of inheriting the process umask, which left indexed source bodies world-readable under a default `0022`.
- Added `token-context harden`, with `--check`, to repair existing files and to report the ACL principals of the config directory on Windows.
- Kept repository-relative paths intact on POSIX, where a backslash is a filename character rather than a separator; the stricter Windows-shaped validation still applies on every host.
- Documented Linux/macOS registry paths, VS Code Remote-SSH placement, and multi-user host guidance in the README and `SECURITY.md`.
- Added `docs/PLATFORMS.en.md` and `docs/PLATFORMS.vi.md`: supported operating systems, remote/SSH placement, every enforced limit, and the permission model.

## Unreleased — remediation after review 935511f (2026-08-28)

- Restored the `token_context_mcp.security` package to the publishable source tree and added clean-room wheel checks.
- Added cross-platform CI for source tests and an installed-wheel MCP stdio handshake.
- Replaced regex import extraction with Tree-sitter extraction, including relative, aliased, re-export, and dynamic-import warnings.
- Indexed TypeScript/TSX arrow functions, function expressions, anonymous default exports, and zero-symbol parse warnings.
- Prevented stale symbol offsets from returning content under an old source hash.
- Measured freshness-scan cost at the 1,000, 10,000, and 25,000-file scales.

`v0.1.0` remains untagged until the required CI checks are green.
