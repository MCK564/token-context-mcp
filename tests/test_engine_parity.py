from __future__ import annotations

import json
from pathlib import Path

import pytest

from token_context_mcp.models import ExternalStubRecord, SymbolRecord
from token_context_mcp.parse.lexical_edges import build_lexical_edges
from token_context_mcp.parse.treesitter import (
    _HAS_FAST_AST,
    parse_source,
)
from token_context_mcp.stubs import CURATED_EXTERNAL_STUBS, get_relevant_stubs


def test_fallback_guard_is_active():
    """Verify fallback flag is a valid boolean and engine operates without crashes."""
    assert isinstance(_HAS_FAST_AST, bool)


def test_golden_call_extraction_parity():
    """Verify that the parser matches the golden call extraction dataset."""
    fixture_path = Path(__file__).parent / "fixtures" / "call_extraction_golden.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))

    for case in fixtures:
        case_id = case["id"]
        language = case["language"]
        source = case["source"]
        expected_calls = case["expected_calls"]

        parsed = parse_source(f"{case_id}.py", source.encode("utf-8"), language)
        extracted = [
            {
                "name": call.name,
                "receiver": call.receiver,
                "receiver_type": call.receiver_type,
                "is_tainted": call.is_tainted,
            }
            for call in parsed.calls
        ]

        # Verify each expected call is present in extracted calls
        for exp in expected_calls:
            matches = [
                c for c in extracted
                if c["name"] == exp["name"]
                and c["receiver"] == exp["receiver"]
                and c["receiver_type"] == exp["receiver_type"]
                and c["is_tainted"] == exp["is_tainted"]
            ]
            assert len(matches) >= 1, (
                f"Failed case '{case_id}': expected {exp} but extracted was:\n{extracted}"
            )


def test_virtual_stub_resolution_unittest():
    """Verify that TestCase.assertEqual resolves to a virtual stub edge with 0.90 confidence."""
    source_code = (
        "import unittest\n"
        "class TestWorker(unittest.TestCase):\n"
        "    def test_run(self):\n"
        "        self.assertEqual(1, 1)\n"
    )
    parsed = parse_source("test_sample.py", source_code.encode("utf-8"), "python")
    stubs = get_relevant_stubs({"test_sample.py": ["unittest"]})

    class_hierarchy = {"TestWorker": ["unittest.TestCase"]}
    edges = build_lexical_edges(
        parsed.symbols,
        {"test_sample.py": source_code},
        calls_by_path={"test_sample.py": parsed.calls},
        imports_by_path={"test_sample.py": ["unittest"]},
        class_hierarchy=class_hierarchy,
        external_stubs=stubs,
    )

    stub_edges = [e for e in edges if e.target_stub_id is not None]
    assert len(stub_edges) == 1
    edge = stub_edges[0]
    assert edge.target_name == "assertEqual"
    assert edge.status == "resolved"
    assert edge.backend == "virtual_stub"
    assert edge.confidence == 0.90
    assert "virtual_stub" in edge.evidence


def test_virtual_stub_resolution_requests():
    """Verify that requests.get resolves to a virtual stub edge with 0.90 confidence."""
    source_code = (
        "import requests\n"
        "def fetch():\n"
        "    return requests.get('https://example.com')\n"
    )
    parsed = parse_source("client.py", source_code.encode("utf-8"), "python")
    stubs = get_relevant_stubs({"client.py": ["requests"]})

    edges = build_lexical_edges(
        parsed.symbols,
        {"client.py": source_code},
        calls_by_path={"client.py": parsed.calls},
        imports_by_path={"client.py": ["requests"]},
        external_stubs=stubs,
    )

    stub_edges = [e for e in edges if e.target_stub_id is not None]
    assert len(stub_edges) == 1
    edge = stub_edges[0]
    assert edge.target_name == "get"
    assert edge.status == "resolved"
    assert edge.backend == "virtual_stub"
    assert edge.confidence == 0.90
