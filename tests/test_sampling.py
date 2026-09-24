from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from token_context_mcp.sampling.guardrail import is_symbol_grounded, verify_and_guard
from token_context_mcp.sampling.hardware_probe import (
    HardwareProfile,
    calculate_adaptive_timeout,
    probe_hardware,
)
from token_context_mcp.sampling.router import SamplingRouter
from token_context_mcp.sampling.schema import (
    CodeSummaryPayload,
    ConstraintEvidence,
    SymbolAnalysis,
)
from token_context_mcp.sampling.skeleton_hybrid import build_hybrid_context, extract_symbol_anchors


def test_hardware_probe_returns_valid_profile() -> None:
    profile = probe_hardware()
    assert isinstance(profile, HardwareProfile)
    assert profile.ram_gb > 0
    assert profile.cpu_cores >= 1
    assert profile.recommended_threads >= 1
    assert profile.recommended_backend in {"local_ollama", "heuristic_fallback"}
    assert profile.backend_mode in {"ollama_gpu", "ollama_cpu", "heuristic_fallback"}


def test_adaptive_timeout_calculation() -> None:
    # On CPU: base 5.0 + 5.0 per 100 tokens, capped at 35.0s
    t_cpu_short = calculate_adaptive_timeout(input_tokens=100, backend_mode="ollama_cpu")
    assert t_cpu_short == 10.0
    t_cpu_long = calculate_adaptive_timeout(input_tokens=1000, backend_mode="ollama_cpu")
    assert t_cpu_long == 35.0  # hits ceiling

    # On GPU: base 3.0 + 1.0 per 100 tokens, capped at 15.0s
    t_gpu_short = calculate_adaptive_timeout(input_tokens=100, backend_mode="ollama_gpu")
    assert t_gpu_short == 4.0
    t_gpu_long = calculate_adaptive_timeout(input_tokens=2000, backend_mode="ollama_gpu")
    assert t_gpu_long == 15.0


def test_pydantic_schema_validation() -> None:
    evidence = ConstraintEvidence(
        verbatim_quote="if amount <= 0: raise InvalidAmountException()",
        rule="amount must be positive",
        line=3,
    )
    sym = SymbolAnalysis(
        name="PaymentService.refund",
        responsibility="Executes refund logic",
        critical_constraints=[evidence],
        calls_external=["gateway.execute"],
        line_span=[1, 5],
    )
    payload = CodeSummaryPayload(
        intent_alignment="Directly handles customer refund request",
        analyzed_symbols=[sym],
        technical_caveats=["Assumes gateway initialized"],
    )
    compat = payload.to_compat_dict()
    assert compat["summary"] == "Directly handles customer refund request"
    assert "PaymentService.refund" in compat["key_symbols"]
    assert len(compat["relationships"]) == 1
    assert compat["relationships"][0]["target"] == "gateway.execute"
    assert any("amount must be positive" in c for c in compat["critical_notes"])

    # Validation from JSON
    raw_json = payload.model_dump_json()
    reparsed = CodeSummaryPayload.model_validate_json(raw_json)
    assert reparsed.analyzed_symbols[0].name == "PaymentService.refund"
    assert reparsed.analyzed_symbols[0].line_span == [1, 5]


def test_skeleton_hybrid_builder_and_anchors() -> None:
    code = """
class PaymentService:
    def validate_account(self, acc_id):
        if not acc_id:
            raise ValueError("empty")
        return True

    def refund(self, tx_id, amount):
        if amount <= 0:
            raise InvalidAmountException("Negative")
        return self.gateway.execute_refund(tx_id, amount)

def unrelated_helper():
    x = 1 + 2
    return x * 10
"""
    anchors = extract_symbol_anchors(code, "python")
    assert "PaymentService" in anchors
    assert "validate_account" in anchors
    assert "refund" in anchors
    assert "unrelated_helper" in anchors

    # Large text test for hybrid builder
    large_code = code + "\n" + ("# filler comment line\n" * 150)
    assert len(large_code) > 3000
    hybrid_text, verified_anchors = build_hybrid_context(
        large_code,
        intent="refund processing logic",
        max_chars=1000,
    )
    # The relevant method 'refund' should be retained while unrelated functions are elided
    assert "def refund" in hybrid_text
    assert "InvalidAmountException" in hybrid_text
    assert "... # [Skeleton: body elided for context preservation]" in hybrid_text


def test_hallucination_guardrail_filters_ungrounded_symbols() -> None:
    verified_anchors = ["PaymentService", "refund", "cancel_order"]

    payload = CodeSummaryPayload(
        intent_alignment="Processes refund",
        analyzed_symbols=[
            SymbolAnalysis(
                name="PaymentService.refund",
                responsibility="Validates amount",
                critical_constraints=["amount > 0"],
            ),
            SymbolAnalysis(
                name="FakeCryptoEngine.mine",  # Hallucinated symbol!
                responsibility="Mines tokens",
                critical_constraints=[],
            ),
        ],
        technical_caveats=[],
    )

    guarded, cov_rate, crr = verify_and_guard(payload, verified_anchors)
    assert len(guarded.analyzed_symbols) == 1
    assert guarded.analyzed_symbols[0].name == "PaymentService.refund"
    assert cov_rate == 0.5  # 1 out of 2 was grounded
    assert crr == 0.667  # 2 out of 3 anchors covered (PaymentService & refund covered, cancel_order not covered)


def test_sampling_router_heuristic_fallback() -> None:
    mock_hardware = HardwareProfile(
        has_cuda=False,
        vram_gb=0.0,
        ram_gb=8.0,
        has_ollama=False,
        recommended_backend="heuristic_fallback",
        backend_mode="heuristic_fallback",
    )
    router = SamplingRouter(hardware=mock_hardware)
    sample_text = """
import os
import sys

class InvoiceScanner:
    def scan(self, document):
        if not document:
            raise EmptyDocError("doc empty")
        return self.parse(document)

def helper():
    pass
"""
    result = router.summarize(sample_text, intent="scan documents and parse", max_tokens=250)
    assert result["status"] == "success"
    assert result["backend"] == "heuristic_fallback"
    assert result["engine"] == "deterministic_ast_extractor"
    assert "latency_ms" in result
    assert result["symbol_coverage_rate"] == 1.0

    data = result["data"]
    assert "InvoiceScanner" in data["key_symbols"]
    assert "scan" in data["key_symbols"]
    assert len(data["relationships"]) > 0

    payload = result["payload"]
    assert len(payload["analyzed_symbols"]) >= 2
    # Verify constraint was extracted
    scan_symbol = next(s for s in payload["analyzed_symbols"] if s["name"] == "scan")
    assert any("EmptyDocError" in (c if isinstance(c, str) else str(c)) for c in scan_symbol["critical_constraints"])
    assert scan_symbol.get("line_span") is not None


def test_sampling_router_ollama_mock() -> None:
    mock_hardware = HardwareProfile(
        has_cuda=False,
        vram_gb=0.0,
        ram_gb=16.0,
        has_ollama=True,
        recommended_backend="local_ollama",
        backend_mode="ollama_cpu",
        recommended_threads=7,
        recommended_model="qwen2.5-coder:7b-instruct-q4_K_M",
    )
    router = SamplingRouter(hardware=mock_hardware)

    mock_ollama_response = {
        "response": json.dumps(
            {
                "intent_alignment": "Successfully processes refund with validation",
                "analyzed_symbols": [
                    {
                        "name": "PaymentService.refund",
                        "responsibility": "Executes customer refund",
                        "critical_constraints": [
                            {
                                "verbatim_quote": "if amount <= 0: raise InvalidAmountException('Amount must be positive')",
                                "rule": "amount > 0",
                                "line": 4,
                            }
                        ],
                        "calls_external": ["gateway.execute_refund"],
                        "line_span": [2, 6],
                    }
                ],
                "technical_caveats": ["Assumes gateway initialized"],
            }
        )
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_ollama_response).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        code = """
class PaymentService:
    def refund(self, tx_id, amount):
        if amount <= 0:
            raise InvalidAmountException("Amount must be positive")
        return self.gateway.execute_refund(tx_id, amount)
"""
        result = router.summarize(code, intent="refund validation", max_tokens=512)
        assert result["status"] == "success"
        assert result["backend"] == "ollama_cpu"
        assert result["engine"] == "qwen2.5-coder:7b-instruct-q4_K_M"
        assert result["symbol_coverage_rate"] == 1.0
        assert "PaymentService.refund" in result["data"]["key_symbols"]
        first_sym = result["payload"]["analyzed_symbols"][0]
        assert first_sym["line_span"] == [2, 6]
