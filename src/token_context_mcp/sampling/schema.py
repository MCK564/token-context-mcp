"""Pydantic v2 schemas for structured LLM sampling output."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class SymbolAnalysis(BaseModel):
    name: str = Field(..., description="Exact name of the class or function")
    responsibility: str = Field(..., description="Concise purpose and role of this symbol")
    critical_constraints: list[str] = Field(
        default_factory=list,
        description="Key constraints, validation rules, or exceptions raised",
    )
    calls_external: list[str] = Field(
        default_factory=list,
        description="Dependencies, external services, or downstream methods called",
    )


class CodeSummaryPayload(BaseModel):
    intent_alignment: str = Field(
        ...,
        description="How the analyzed code directly fulfills or relates to the user intent",
    )
    analyzed_symbols: list[SymbolAnalysis] = Field(
        default_factory=list,
        description="Verified symbols extracted and analyzed from the source code",
    )
    technical_caveats: list[str] = Field(
        default_factory=list,
        description="Preconditions, assumptions, timeouts, or failure modes",
    )

    def to_compat_dict(self) -> dict[str, Any]:
        """Convert to dictionary with backwards-compatible fields for older callers."""
        base = self.model_dump()
        key_symbols = [s.name for s in self.analyzed_symbols]
        relationships = [
            {"source": s.name, "target": target, "relation": "calls"}
            for s in self.analyzed_symbols
            for target in s.calls_external
        ]
        if not relationships:
            relationships = [{"source": s.name, "relation": "defined"} for s in self.analyzed_symbols]

        base["summary"] = self.intent_alignment
        base["key_symbols"] = key_symbols
        base["relationships"] = relationships
        base["critical_notes"] = self.technical_caveats
        return base
