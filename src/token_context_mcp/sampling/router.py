"""Sampling router with hardware awareness and graceful fallback."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib import error as urllib_error, request as urllib_request

from token_context_mcp.sampling.hardware_probe import HardwareProfile, probe_hardware
from token_context_mcp.sampling.prompts import COMPRESSION_PROMPT_TEMPLATE


class SamplingRouter:
    def __init__(self, hardware: HardwareProfile | None = None) -> None:
        self.hardware = hardware or probe_hardware()

    def summarize(
        self,
        text: str,
        *,
        intent: str = "general_code_summary",
        max_tokens: int = 250,
    ) -> dict[str, Any]:
        """Compress code/graph text using the best available backend."""
        # Try local Ollama if hardware permits
        if self.hardware.recommended_backend == "local_ollama":
            result = self._try_ollama(text, intent, max_tokens)
            if result:
                return result

        # Fallback to rule-based heuristic compression
        return self._heuristic_compress(text, intent, max_tokens)

    def _try_ollama(self, text: str, intent: str, max_tokens: int) -> dict[str, Any] | None:
        url = "http://localhost:11434/api/generate"
        prompt = COMPRESSION_PROMPT_TEMPLATE.format(intent=intent, max_tokens=max_tokens, text=text[:3000])
        payload = json.dumps(
            {
                "model": "qwen2.5-coder:1.5b",
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_predict": max_tokens},
            }
        ).encode("utf-8")

        req = urllib_request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib_request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                response_text = data.get("response", "")
                parsed = json.loads(response_text)
                return {
                    "backend": "local_ollama",
                    "status": "success",
                    "data": parsed,
                }
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None

    def _heuristic_compress(self, text: str, intent: str, max_tokens: int) -> dict[str, Any]:
        """Deterministic rule-based compression when no LLM inference backend is available."""
        lines = text.splitlines()
        classes = [re.sub(r"[^\w.]", "", line.split("class ")[1].split("(")[0].split(":")[0]) for line in lines if "class " in line]
        functions = [re.sub(r"[^\w.]", "", line.split("def ")[1].split("(")[0]) for line in lines if "def " in line or "function " in line]
        imports = [line.strip() for line in lines if line.strip().startswith(("import ", "from ", "using "))]

        summary = f"Code segment contains {len(classes)} classes, {len(functions)} functions, and {len(imports)} imports."
        key_symbols = (classes + functions)[:10]

        return {
            "backend": "heuristic_fallback",
            "status": "success",
            "data": {
                "summary": summary,
                "key_symbols": key_symbols,
                "relationships": [{"source": c, "relation": "defined"} for c in key_symbols[:5]],
                "critical_notes": [f"Intent: {intent}", f"Lines compressed: {len(lines)}"],
            },
        }
