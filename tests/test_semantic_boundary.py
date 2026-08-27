from __future__ import annotations

from token_context_mcp.parse.lsp import lsp_backend_status
from token_context_mcp.parse.scip import scip_backend_status


def test_semantic_backends_are_explicitly_disabled() -> None:
    assert not lsp_backend_status().enabled
    assert "allowlisted" in lsp_backend_status().reason
    assert not scip_backend_status().enabled
    assert "allowlisted" in scip_backend_status().reason

