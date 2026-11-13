"""Canonical query signature extraction using code_tokens stemming."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from token_context_mcp.retrieve.code_tokens import (
    QUERY_STOPWORDS,
    porter_stem,
    split_identifier,
)

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


@dataclass(frozen=True)
class QuerySignature:
    """Normalized, stemmed query signature without raw query text."""

    tokens: tuple[str, ...]
    sig_tokens_json: str
    sig_hash: str
    fts_text: str


def extract_atomic_stems(text: str) -> set[str]:
    """Extract atomic stemmed tokens from text, splitting snake_case and camelCase."""
    stems: set[str] = set()
    for raw in _TOKEN_RE.findall(text):
        parts = split_identifier(raw)
        # When split_identifier decomposes a compound token (e.g. export_svg -> ['export', 'svg', 'export_svg']),
        # drop the trailing compound original_lower so 'export_svg' and 'export svg' produce identical stems.
        atomic_parts = parts[:-1] if len(parts) > 1 and parts[-1] == raw.lower() else parts
        for part in atomic_parts:
            lower = part.lower()
            if len(lower) < 2 or lower in QUERY_STOPWORDS:
                continue
            stemmed = porter_stem(lower)
            if len(stemmed) >= 2 and stemmed not in QUERY_STOPWORDS:
                stems.add(stemmed)
    return stems


def build_query_signature(query: str) -> QuerySignature:
    """Compute sorted unique stemmed tokens and their 16-hex SHA-256 digest."""
    ordered = tuple(sorted(extract_atomic_stems(query)))
    sig_tokens_json = json.dumps(list(ordered), separators=(",", ":"))
    sig_hash = hashlib.sha256(sig_tokens_json.encode("utf-8")).hexdigest()[:16]
    return QuerySignature(
        tokens=ordered,
        sig_tokens_json=sig_tokens_json,
        sig_hash=sig_hash,
        fts_text=" ".join(ordered),
    )


def jaccard_similarity(a: set[str] | tuple[str, ...], b: set[str] | tuple[str, ...]) -> tuple[float, int]:
    """Return (jaccard_score, overlap_count) between two token collections."""
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0, 0
    overlap = len(sa & sb)
    if overlap == 0:
        return 0.0, 0
    union = len(sa | sb)
    return overlap / union, overlap
