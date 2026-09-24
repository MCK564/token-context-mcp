"""Pydantic v2 schemas for structured LLM sampling output with verbatim grounding."""
from __future__ import annotations

from typing import Any, Union
from pydantic import BaseModel, Field


class ConstraintEvidence(BaseModel):
    """Grounded constraint with verbatim code proof (learned from Google Cloud GenAI)."""
    verbatim_quote: str = Field(
        ...,
        description="Exact line or snippet of code quoted verbatim (e.g. 'if amount <= 0:' or 'raise InvalidAmountException(...)')",
    )
    rule: str = Field(..., description="Technical constraint, validation check, or business rule")
    line: int | None = Field(default=None, description="Source line number where the constraint is defined")


class SymbolAnalysis(BaseModel):
    name: str = Field(..., description="Exact name of the class or function")
    responsibility: str = Field(..., description="Concise purpose and role of this symbol")
    critical_constraints: list[Union[ConstraintEvidence, str]] = Field(
        default_factory=list,
        description="Key constraints, validation rules, or exceptions raised, backed by verbatim quotes",
    )
    calls_external: list[str] = Field(
        default_factory=list,
        description="Dependencies, external services, or downstream methods called",
    )
    line_span: list[int] | None = Field(
        default=None,
        description="[start_line, end_line] in source code for direct IDE navigation",
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

        # Flatten constraint evidences for legacy string lists if necessary
        flat_constraints: list[str] = []
        for s in self.analyzed_symbols:
            for c in s.critical_constraints:
                if isinstance(c, ConstraintEvidence):
                    flat_constraints.append(f"{c.rule} (quote: {c.verbatim_quote})")
                elif isinstance(c, dict):
                    flat_constraints.append(f"{c.get('rule', '')} (quote: {c.get('verbatim_quote', '')})")
                else:
                    flat_constraints.append(str(c))

        base["summary"] = self.intent_alignment
        base["key_symbols"] = key_symbols
        base["relationships"] = relationships
        base["critical_notes"] = list(dict.fromkeys(self.technical_caveats + flat_constraints[:5]))
        return base
