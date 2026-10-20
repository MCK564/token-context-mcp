"""AST Tree-sitter semantic anchor extraction and skeleton hybrid context builder."""
from __future__ import annotations

import re
from typing import Sequence

from token_context_mcp.parse.treesitter import parse_source


def _normalize_lang(language_hint: str) -> str:
    lang = language_hint.lower().strip()
    if lang in {"py", "python"}:
        return "python"
    elif lang in {"js", "javascript"}:
        return "javascript"
    elif lang in {"ts", "typescript", "tsx"}:
        return "typescript"
    elif lang in {"java"}:
        return "java"
    elif lang in {"cs", "c_sharp", "c#", "csharp"}:
        return "c_sharp"
    elif lang in {"go", "golang"}:
        return "go"
    return "python"


def extract_symbol_anchors(text: str, language_hint: str = "python") -> list[str]:
    """Extract verified class and function/method names using Tree-sitter with regex fallback."""
    raw = text.encode("utf-8")
    symbols: list[str] = []

    # 1. Try Tree-sitter
    ts_lang = _normalize_lang(language_hint)

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
      - Elides bodies for unrelated symbols using AST byte-spans with regex fallback
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

    # 1. Primary path: AST byte-span body elision via Tree-sitter
    ts_lang = _normalize_lang(language_hint)
    raw = text.encode("utf-8")
    ast_succeeded = False
    hybrid_text = ""

    try:
        parsed = parse_source("snippet", raw, ts_lang)
        elision_symbols = [
            s for s in parsed.symbols
            if s.body_start_byte is not None
            and s.body_end_byte is not None
            and s.body_end_byte > s.body_start_byte
            and s.kind not in ("class", "module", "namespace", "interface")
            and s.name not in relevant_symbols
        ]
        if elision_symbols:
            # Sort from end of file to start of file so byte offsets remain stable
            sorted_targets = sorted(elision_symbols, key=lambda s: s.body_start_byte, reverse=True)
            new_raw = raw
            for s in sorted_targets:
                b_start = s.body_start_byte
                b_end = s.body_end_byte
                raw_body = new_raw[b_start:b_end]
                if raw_body.strip().startswith(b"{") and raw_body.strip().endswith(b"}"):
                    replacement = b"{\n        ... # [Skeleton: body elided for context preservation]\n    }"
                else:
                    replacement = b"... # [Skeleton: body elided for context preservation]"
                new_raw = new_raw[:b_start] + replacement + new_raw[b_end:]

            hybrid_text = new_raw.decode("utf-8", errors="replace")
            ast_succeeded = True
    except Exception:
        ast_succeeded = False

    # 2. Fallback path: regex line-by-line parsing if AST parsing failed or found no elidable symbols
    if not ast_succeeded or not hybrid_text:
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
