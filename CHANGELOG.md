# Changelog

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
