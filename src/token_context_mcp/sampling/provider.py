from __future__ import annotations

import json
import logging
import re
import urllib.request as urllib_request
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("token_context_mcp.sampling.provider")


class ModelProvider(ABC):
    """Abstract provider seam conforming to DeepSeek Harness / Cordis provider model."""

    @abstractmethod
    def generate(
        self,
        model_name: str,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.05,
        timeout_sec: float = 10.0,
        threads: int = 4,
    ) -> str:
        """Execute inference and return raw text output."""
        ...


class OllamaProvider(ModelProvider):
    """Local Ollama inference provider with automatic thinking-tag stripping."""

    def __init__(self, endpoint: str = "http://localhost:11434") -> None:
        self.endpoint = endpoint.rstrip("/")

    def generate(
        self,
        model_name: str,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.05,
        timeout_sec: float = 10.0,
        threads: int = 4,
    ) -> str:
        url = f"{self.endpoint}/api/generate"
        payload_dict = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "num_predict": max_tokens,
                "num_thread": threads,
            },
        }
        req_data = json.dumps(payload_dict).encode("utf-8")
        req = urllib_request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
        with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_response = data.get("response", "").strip()

            # Clean reasoning / thinking tags (e.g. DeepSeek R1, QwQ)
            clean_str = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()

            # Clean markdown fences if present
            clean_json_str = re.sub(r"^```(?:json)?\s*", "", clean_str)
            return re.sub(r"\s*```$", "", clean_json_str).strip()


class MockModelProvider(ModelProvider):
    """Deterministic mock provider for unit tests and offline environments."""

    def __init__(self, canned_response: str = "{}") -> None:
        self.canned_response = canned_response

    def generate(
        self,
        model_name: str,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.05,
        timeout_sec: float = 10.0,
        threads: int = 4,
    ) -> str:
        return self.canned_response
