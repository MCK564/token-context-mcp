"""Semantic-backend contract; execution is intentionally disabled in the read-only MVP."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticBackendStatus:
    backend: str
    enabled: bool
    reason: str


def lsp_backend_status() -> SemanticBackendStatus:
    """Report why LSP is not spawned by this package.

    A language server is an executable dependency and must be version-pinned,
    sandboxed and validated on a language-specific corpus before it can add
    semantic edges. The local MVP therefore exposes no subprocess bridge.
    """

    return SemanticBackendStatus(
        backend="lsp",
        enabled=False,
        reason="disabled: no allowlisted sandboxed language-server backend configured",
    )

