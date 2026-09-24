"""Sampling router with hardware awareness, 7B CPU optimizations, and verification guardrails."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Sequence
from urllib import error as urllib_error, request as urllib_request

from token_context_mcp.sampling.guardrail import verify_and_guard
from token_context_mcp.sampling.hardware_probe import (
    HardwareProfile,
    calculate_adaptive_timeout,
    probe_hardware,
)
from token_context_mcp.sampling.prompts import STRUCTURED_CONTEXT_PROMPT_TEMPLATE
from token_context_mcp.sampling.schema import CodeSummaryPayload, SymbolAnalysis
from token_context_mcp.sampling.skeleton_hybrid import build_hybrid_context


class SamplingRouter:
    def __init__(self, hardware: HardwareProfile | None = None) -> None:
        self.hardware = hardware or probe_hardware()

    def summarize(
        self,
        text: str,
        *,
        intent: str = "general_code_summary",
        max_tokens: int = 512,
        target_symbols: Sequence[str] | None = None,
        language_hint: str = "python",
    ) -> dict[str, Any]:
        """Compress code/graph text using hardware-adapted 7B model or deterministic fallback."""
        start_time = time.perf_counter()

        # 1. Build anchor-preserved hybrid context
        structured_context, verified_symbols = build_hybrid_context(
            text=text,
            intent=intent,
            target_symbols=target_symbols,
            max_chars=3000,
            language_hint=language_hint,
        )

        # 2. Attempt local Ollama inference (GPU or CPU)
        if self.hardware.has_ollama and self.hardware.recommended_backend == "local_ollama":
            result = self._try_ollama(
                structured_context=structured_context,
                verified_symbols=verified_symbols,
                intent=intent,
                max_tokens=max_tokens,
                start_time=start_time,
            )
            if result is not None:
                return result

        # 3. Deterministic heuristic fallback
        return self._heuristic_compress(
            text=text,
            intent=intent,
            max_tokens=max_tokens,
            verified_symbols=verified_symbols,
            start_time=start_time,
        )

    def _try_ollama(
        self,
        structured_context: str,
        verified_symbols: Sequence[str],
        intent: str,
        max_tokens: int,
        start_time: float,
    ) -> dict[str, Any] | None:
        url = "http://localhost:11434/api/generate"
        est_tokens = max(1, len(structured_context) // 4)
        timeout_sec = calculate_adaptive_timeout(est_tokens, self.hardware.backend_mode)

        prompt = STRUCTURED_CONTEXT_PROMPT_TEMPLATE.format(
            user_raw_intent=intent,
            verified_symbol_names=", ".join(verified_symbols) if verified_symbols else "None detected",
            structured_code_context=structured_context,
        )

        model_name = self.hardware.recommended_model
        payload_dict = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.05,
                "top_p": 0.9,
                "num_predict": max_tokens,
                "num_thread": self.hardware.recommended_threads,
            },
        }

        try:
            req_data = json.dumps(payload_dict).encode("utf-8")
            req = urllib_request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
            with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_response = data.get("response", "").strip()

                # Clean markdown fences if present
                clean_json_str = re.sub(r"^```(?:json)?\s*", "", raw_response)
                clean_json_str = re.sub(r"\s*```$", "", clean_json_str)

                # Validate with Pydantic v2
                payload_obj = CodeSummaryPayload.model_validate_json(clean_json_str)

                # Apply Hallucination Guardrail
                guarded_payload, cov_rate, crr = verify_and_guard(payload_obj, verified_symbols)
                latency_ms = int((time.perf_counter() - start_time) * 1000)

                backend_tag = (
                    "ollama_gpu" if self.hardware.backend_mode == "ollama_gpu" else "ollama_cpu"
                )
                compat_data = guarded_payload.to_compat_dict()

                return {
                    "backend": backend_tag,
                    "engine": model_name,
                    "status": "success",
                    "latency_ms": latency_ms,
                    "symbol_coverage_rate": cov_rate,
                    "context_retention_rate": crr,
                    "data": compat_data,
                    "payload": guarded_payload.model_dump(),
                }
        except (urllib_error.URLError, TimeoutError, OSError, json.JSONDecodeError, Exception):
            return None

    def _heuristic_compress(
        self,
        text: str,
        intent: str,
        max_tokens: int,
        verified_symbols: Sequence[str],
        start_time: float,
    ) -> dict[str, Any]:
        """Deterministic rule-based compression when no local LLM backend is available."""
        lines = text.splitlines()

        # Parse classes and functions
        classes = [
            re.sub(r"[^\w.]", "", line.split("class ")[1].split("(")[0].split(":")[0])
            for line in lines
            if "class " in line
        ]
        functions = [
            re.sub(r"[^\w.]", "", line.split("def ")[1].split("(")[0])
            for line in lines
            if "def " in line or "function " in line
        ]
        imports = [line.strip() for line in lines if line.strip().startswith(("import ", "from ", "using "))]

        # Extract constraints and exceptions
        exceptions = re.findall(r"raise\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        if_conditions = [line.strip() for line in lines if line.strip().startswith("if ")][:3]
        critical_constraints: list[str] = []
        if exceptions:
            critical_constraints.append(f"Raises: {', '.join(set(exceptions))}")
        critical_constraints.extend(if_conditions)

        # Extract method calls
        calls_external = re.findall(r"(?:self|this|\w+)\.([A-Za-z_][A-Za-z0-9_]*)\(", text)
        calls_external = list(dict.fromkeys(calls_external))[:5]

        analyzed_symbols: list[SymbolAnalysis] = []
        all_syms = list(dict.fromkeys(classes + functions))
        for sym in all_syms[:10]:
            sym_constraints = [c for c in critical_constraints if sym.lower() in c.lower()] or critical_constraints[:2]
            sym_calls = [c for c in calls_external if c != sym][:3]
            analyzed_symbols.append(
                SymbolAnalysis(
                    name=sym,
                    responsibility=f"Implements {sym} functionality in accordance with {intent}",
                    critical_constraints=sym_constraints,
                    calls_external=sym_calls,
                )
            )

        payload_obj = CodeSummaryPayload(
            intent_alignment=f"Code segment aligns with intent '{intent}' covering {len(classes)} classes, {len(functions)} functions, and {len(imports)} imports.",
            analyzed_symbols=analyzed_symbols,
            technical_caveats=[f"Intent: {intent}", f"Lines compressed: {len(lines)}"],
        )

        guarded_payload, cov_rate, crr = verify_and_guard(payload_obj, verified_symbols)
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        compat_data = guarded_payload.to_compat_dict()

        return {
            "backend": "heuristic_fallback",
            "engine": "deterministic_ast_extractor",
            "status": "success",
            "latency_ms": latency_ms,
            "symbol_coverage_rate": cov_rate,
            "context_retention_rate": crr,
            "data": compat_data,
            "payload": guarded_payload.model_dump(),
        }
