# Changelog

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
