"""Structured prompt templates for nested LLM sampling and deterministic compression."""
from __future__ import annotations

COMPRESSION_PROMPT_TEMPLATE = """You are a deterministic code-context compression engine.
Analyze the following source context or graph dump and produce a strictly valid JSON response.
Do NOT include markdown fences, conversational text, or explanations.

Intent: {intent}
Max target tokens: {max_tokens}

Source Context:
{text}

JSON Output Format:
{{
  "summary": "<one sentence overview>",
  "key_symbols": ["<symbol1>", "<symbol2>"],
  "relationships": [{{"source": "<A>", "target": "<B>", "relation": "calls|inherits|imports"}}],
  "critical_notes": ["<note1>"]
}}"""
