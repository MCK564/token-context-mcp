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
- `resolve_effective_agent_id()` reads `TOKEN_CONTEXT_AGENT_ID` env, validates `^[a-zA-Z0-9_-]{1,64}$`, falls back to `"anonymous"`.
- Anonymous agent is subject to pause/block/halt but exempt from rate limiting.
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
| `test_governance_store.py` | 8 | CRUD, TTL cache, cross-process propagation, invalid agent id, heartbeat |
| `test_memory_lock_atomic.py` | 3 | Concurrency stress (5×8 subprocesses), unlock lifecycle, renewal |
| `test_memory_namespace.py` | 18 | _redact_value, namespace isolation, schema migration+backup, TTL cleanup |
| `test_gui_bridge.py` | +3 | GovernanceRefreshWorker no-db, with-db, active_servers_updated signal |

Full suite (ignoring GUI tests requiring PySide6): **161 passed, 6 skipped**.

