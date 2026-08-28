# Changelog

## Unreleased — remediation after review 935511f (2026-08-28)

- Restored the `token_context_mcp.security` package to the publishable source tree and added clean-room wheel checks.
- Added cross-platform CI for source tests and an installed-wheel MCP stdio handshake.
- Replaced regex import extraction with Tree-sitter extraction, including relative, aliased, re-export, and dynamic-import warnings.
- Indexed TypeScript/TSX arrow functions, function expressions, anonymous default exports, and zero-symbol parse warnings.
- Prevented stale symbol offsets from returning content under an old source hash.
- Measured freshness-scan cost at the 1,000, 10,000, and 25,000-file scales.

`v0.1.0` remains untagged until the required CI checks are green.
