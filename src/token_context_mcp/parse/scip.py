"""SCIP import contract; binary index ingestion is intentionally disabled in 0.1.0."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticBackendStatus:
    backend: str
    enabled: bool
    reason: str


def scip_backend_status() -> SemanticBackendStatus:
    """Report the explicit semantic-index capability boundary.

    SCIP can carry richer semantic information, but accepting arbitrary index
    files needs a pinned parser, size limits and per-language validation.
    """

    return SemanticBackendStatus(
        backend="scip",
        enabled=False,
        reason="disabled: SCIP ingestion requires an allowlisted parser and precision evaluation",
    )

