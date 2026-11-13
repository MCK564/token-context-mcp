from __future__ import annotations

import json

from token_context_mcp.ledger.signature import build_query_signature, jaccard_similarity


def test_signature_canonical_and_stopword_free() -> None:
    s1 = build_query_signature("Does Console.export_svg render the SVG?")
    s2 = build_query_signature("render SVG export_svg in Console")
    s3 = build_query_signature("render SVG exportSvg in Console")
    s4 = build_query_signature("render export svg in Console")
    assert s1.sig_hash == s2.sig_hash == s3.sig_hash == s4.sig_hash
    assert s1.tokens == s2.tokens == s3.tokens == s4.tokens
    assert "export_svg" not in s1.tokens
    assert "the" not in s1.tokens
    assert "does" not in s1.tokens
    parsed = json.loads(s1.sig_tokens_json)
    assert parsed == list(s1.tokens)
    assert parsed == sorted(parsed)


def test_jaccard_similarity_and_overlap() -> None:
    a = ("consol", "export", "svg", "render")
    b = ("consol", "export", "svg", "text")
    score, overlap = jaccard_similarity(a, b)
    assert overlap == 3
    assert abs(score - 0.6) < 1e-9

    score0, overlap0 = jaccard_similarity(a, ("other", "word"))
    assert score0 == 0.0
    assert overlap0 == 0
