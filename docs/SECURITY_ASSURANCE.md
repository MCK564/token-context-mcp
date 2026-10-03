# Security assurance

The reviewed `935511f` tree was below the project's **A1 (tested)** bar: its regression suite could pass only in a working tree containing an ignored package, so a clean clone could not collect it. The remediation branch reaches A1 only after the source suite and clean-room wheel checks pass in CI. It is not A2 because no project can self-enforce Windows firewall, container isolation, signing or an independent review solely from Python code.

The test suite covers path traversal, secret canaries, stale files, resource bounds and a real MCP `stdio` round trip. For an A2 deployment:

1. Run under a dedicated OS account with read access only to registered roots.
2. Enforce outbound network deny with a Windows Firewall rule, container or VM profile and retain the policy/exported test evidence.
3. Verify package and grammar hashes from the lockfile before launch.
4. Keep the index database and config ACL-restricted.
5. Treat all repository content as prompt-injection-capable, and remember MCP host/model routing may send returned snippets to a provider.

Generate local, unsigned starter supply-chain artifacts with:

```powershell
uv run token-context release-materials --output supply-chain
```

Sign the release and attest the build in CI before claiming A3.

---

## M2 — Governance & Memory Safety (branch `feat/m2-governance`, 2026-09-24)

### M2.1 — `enable_admin_tools` flag and token-protected `agent_control`

- `ServerConfig.enable_admin_tools: bool = False` — admin tools off by default.
- `agent_control` registered only when `enable_admin_tools=True`; `action=status` always exempt from token check.
- Admin token validated via `hmac.compare_digest`; invalid token returns `permission_revoked` + generic reason, never leaks token value to audit log.
- CLI: `--enable-admin-tools` flag.

### M2.2 — SQLite-backed shared governance store with heartbeat

- `security/governance_store.py`: WAL-mode SQLite with tables `agents`, `emergency`, `server_heartbeats`; busy-timeout 5 s.
- `AccessControlManager` accepts optional `GovernanceStore`; all mutating calls write through; 1 s monotonic TTL cache.
- `resolve_effective_agent_id()` reads `TOKEN_CONTEXT_AGENT_ID` env, validates `^[a-zA-Z0-9_-]{1,64}$`, falls back to `"anonymous"`. (0.3.3) When the env id is set, an explicit `agent_id` that differs is rejected; `admin` is reserved and only claimable by the internal `agent_control` call.
- Anonymous agent is subject to pause/block/halt and (since 0.3.3) to rate limiting. Without `TOKEN_CONTEXT_AGENT_ID` the id is self-declared, so these controls are advisory.
- Server records heartbeat every ≥15 s per tool call; `server_id = f"server-{pid}-{epoch}"`.

### M2.3 — Atomic `memory_lock` and `memory_unlock`

- Lock acquisition rewritten as single `INSERT … ON CONFLICT DO UPDATE WHERE expires_at <= :now OR agent_id = excluded.agent_id`; `rowcount > 0` = acquired.
- `MemoryStore.unlock(resource_key, agent_id)` — deletes only when agent matches.
- New MCP tool `memory_unlock`; `memory_unlock` added to `WRITE_OR_MUTATING_TOOLS` and catalog.
- Stress-tested: 5 rounds × 8 concurrent subprocesses, exactly 1 winner per round.

### M2.4 — Session isolation namespace and value redaction

- `key_values` schema migrated to v2: `PRIMARY KEY (scope, namespace, key)`; old DBs backed up as `memory.sqlite.bak-v0` before migration.
- `_redact_value(value)` — recursively applies `content_policy.redact_text` to all leaf strings before storage (not just FTS indexing).
- TTL cleanup runs every `_TTL_CLEANUP_INTERVAL = 100` `put` calls.
- `namespace=""` default preserves full backward compatibility.
- All CRUD (`put`, `get`, `delete`, `search`, `list_entries`) and MCP tool handlers updated with `namespace` param.

### M2.5 — GUI read-only governance refresh

- `GovernanceRefreshWorker(QThread)` polls `governance.sqlite` every 5 s; emits `servers_updated`, `agents_refreshed`, `halt_state_changed`.
- Worker is **read-only** — never writes to the store.
- `AgentSecurityController` starts the worker automatically when `governance.sqlite` exists; exposes new `active_servers_updated` signal.
- On halt state change from server side, GUI reflects it without requiring a user action.
- `GovernanceStore.close()` added (no-op, API symmetry).

### Test inventory (M2, branch total)

| File | Tests | What |
|------|-------|------|
| `test_server_governance.py` | 5 | enable_admin_tools flag, token protection, halt/resume, config roundtrip |
| `test_governance_store.py` | 9 | CRUD, TTL cache, cross-process propagation, agent policy sync, heartbeat |
| `test_memory_lock_atomic.py` | 3 | Concurrency stress (5×8 subprocesses), unlock lifecycle, renewal |
| `test_memory_namespace.py` | 18 | _redact_value, namespace isolation, schema migration+backup, TTL cleanup |
| `test_memory_migration.py` | 4 | V1->V3 migration, legacy V2 repair, FTS syntax vs operational errors |
| `test_governance_e2e.py` | 2 | Emergency halt/resume propagation <=1.1s, GUI pure query refresh |
| `test_gui_bridge.py` | 7 | Controller wiring, GovernanceRefreshWorker, server status signals |
| `test_inspect_symbol_budget.py` | 6 | Context fallback, compact relationships, budget truncation warnings |

---

## M2-F — Remediation & Hardening (branch `feat/m2-governance`, 2026-09-25)

### G1 — MemoryStore v3 Migration & Automatic Repair
- `MemoryStore` detects missing columns or schema versions (`user_version < 3` or missing `namespace` in `memory_fts`).
- Creates timestamped/versioned backup `memory.sqlite.bak-v<ver>`.
- Rebuilds `key_values` and `memory_fts` with `(scope, namespace, key, value)` in an atomic transaction.
- Applies `_redact_value()` to unredacted legacy entries during migration.
- `search()` gracefully handles FTS syntax errors as `invalid_query` while re-raising underlying SQLite structural `OperationalError`.

### G2 — GUI Bridge Read/Write Separation
- `AgentSecurityController` connects directly to `GovernanceStore` and passes it to `AccessControlManager`.
- `refresh_data()` queries `governance_store.get_all_agents()` and updates UI state using `merge_seen_agents()` without calling `register_agent()`, ensuring zero database mutations during read refreshes.

### G3 — Agent Policy Synchronization & 0.5s Cache TTL
- `governance.sqlite` `agents` table schema extended with `policy TEXT` and `custom_tools_json TEXT`.
- `AccessControlManager` cache TTL reduced from 1.0s to 0.5s.
- `set_agent_policy()` writes through to `GovernanceStore.upsert_agent()` with `COALESCE` update semantics.
- Cross-process propagation validated under 0.6s.

### G4 — Compact Relationships & Truncation Warnings in `inspect_symbol`
- `inspect_symbol` returns lightweight relationships (`{source, target, kind, confidence}`) in `normal` view to preserve token budget.
- Allocates `slice_tokens = max(edge_budget, 1536)` when `budget_tokens >= 2048` to avoid premature edge omission in `impact_slice`.
- When relationships exceed token budget, surfaces `relationships_truncated` warning and `relationships_omitted` count.


