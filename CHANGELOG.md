# Changelog

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
