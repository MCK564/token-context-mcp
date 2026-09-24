"""AST Tree-sitter semantic anchor extraction and skeleton hybrid context builder."""
from __future__ import annotations

import re
from typing import Sequence

from token_context_mcp.parse.treesitter import parse_source


def extract_symbol_anchors(text: str, language_hint: str = "python") -> list[str]:
    """Extract verified class and function/method names using Tree-sitter with regex fallback."""
    raw = text.encode("utf-8")
    symbols: list[str] = []

    # 1. Try Tree-sitter
    ts_lang = language_hint
    if ts_lang in {"py", "python"}:
        ts_lang = "python"
    elif ts_lang in {"js", "javascript"}:
        ts_lang = "javascript"
    elif ts_lang in {"ts", "typescript", "tsx"}:
        ts_lang = "typescript"
    elif ts_lang in {"java"}:
        ts_lang = "java"
    elif ts_lang in {"cs", "c_sharp", "c#"}:
        ts_lang = "c_sharp"
    else:
        ts_lang = "python"

    try:
        parsed = parse_source("snippet", raw, ts_lang)
        for sym in parsed.symbols:
            if sym.name and sym.name not in symbols:
                symbols.append(sym.name)
    except Exception:
        pass

    # 2. Regex fallback if Tree-sitter found nothing or language not supported
    if not symbols:
        class_matches = re.findall(r"(?:class|interface|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        func_matches = re.findall(r"(?:def|function|async def)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        for name in class_matches + func_matches:
            if name not in symbols:
                symbols.append(name)

    return symbols


def build_hybrid_context(
    text: str,
    intent: str,
    target_symbols: Sequence[str] | None = None,
    max_chars: int = 3000,
    language_hint: str = "python",
) -> tuple[str, list[str]]:
    """Build anchor-preserved hybrid context without blind truncation.
    
    If text length exceeds max_chars:
      - Preserves full file skeleton (imports, class declarations, method signatures)
      - Retains complete function bodies for symbols matching intent / target_symbols
      - Elides bodies for unrelated symbols
    """
    detected_symbols = extract_symbol_anchors(text, language_hint)
    verified_symbols = list(dict.fromkeys(list(target_symbols or []) + detected_symbols))

    if len(text) <= max_chars:
        return text, verified_symbols

    # Extract intent keywords for relevance ranking
    intent_words = {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", intent)}
    relevant_symbols = {
        s for s in verified_symbols
        if s.lower() in intent_words or any(w in s.lower() for w in intent_words)
    }
    # If no symbol explicitly matches intent words, prioritize the first 3 symbols
    if not relevant_symbols and verified_symbols:
        relevant_symbols = set(verified_symbols[:3])

    # Parse line by line to construct hybrid skeleton
    lines = text.splitlines()
    output_lines: list[str] = []
    in_elided_function = False
    elided_indent = 0

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        # Check if line defines a function or method
        func_match = re.match(r"\s*(?:async\s+def|def|function)\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if func_match:
            fn_name = func_match.group(1)
            output_lines.append(line)
            if fn_name not in relevant_symbols:
                in_elided_function = True
                elided_indent = indent
                output_lines.append(" " * (indent + 4) + "... # [Skeleton: body elided for context preservation]")
            else:
                in_elided_function = False
            continue

        # If currently inside an elided function, check if indentation returned to parent level
        if in_elided_function:
            if stripped and indent <= elided_indent:
                in_elided_function = False
            else:
                continue

        output_lines.append(line)

    hybrid_text = "\n".join(output_lines)
    # Ensure it's bounded
    if len(hybrid_text) > max_chars * 2:
        hybrid_text = hybrid_text[: max_chars * 2] + "\n... # [Truncated safely after skeleton preservation]"

    return hybrid_text, verified_symbols
