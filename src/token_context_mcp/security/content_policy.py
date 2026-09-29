from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from token_context_mcp.constants import HARD_DENY_DIRECTORIES, HARD_DENY_FILE_NAMES, HARD_DENY_SUFFIXES

_SECRET_LINE_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|private[_-]?key|authorization)\b\s*(?:=|:|=>)\s*(?:[\"'][^\"']{4,}[\"']|[^\s\"']{4,})"
)
_PEM_RE = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")


def is_hard_denied(relative_path: str) -> bool:
    path = Path(relative_path)
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & HARD_DENY_DIRECTORIES:
        return True
    name = path.name.lower()
    if name in HARD_DENY_FILE_NAMES or name.startswith(".env"):
        return True
    return path.suffix.lower() in HARD_DENY_SUFFIXES


def redact_text(text: str) -> tuple[str, int]:
    redacted = 0
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        if _SECRET_LINE_RE.search(line) or _PEM_RE.search(line):
            ending = "\n" if line.endswith("\n") else ""
            output.append("[REDACTED: potential secret]" + ending)
            redacted += 1
        else:
            output.append(line)
    return "".join(output), redacted


def is_probably_binary(raw: bytes) -> bool:
    return b"\x00" in raw[:8192]


# M9.6: repository text is data, never instructions. These phrases are the usual "ignore the above" hooks; a hit only
# raises a warning (nothing is redacted or dropped), so a false positive costs a few tokens, a miss costs nothing new.
_INJECTION_RE = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"
    r"|disregard\s+(?:all\s+)?(?:previous|prior|above)"
    r"|you\s+are\s+now"
    r"|new\s+system\s+prompt"
    r"|<\s*/?\s*system\s*>"
    r"|BEGIN\s+SYSTEM\s+PROMPT",
    re.IGNORECASE,
)
MAX_INJECTION_HITS = 10


def scan_prompt_injection(text: str) -> list[int]:
    """1-based numbers of the lines of ``text`` that contain a prompt-injection marker."""
    if not text:
        return []
    return [number for number, line in enumerate(text.splitlines(), start=1) if _INJECTION_RE.search(line)]


def injection_hits(blocks: Iterable[tuple[str, int, str | None]], limit: int = MAX_INJECTION_HITS) -> list[str]:
    """``path:line`` for every marker in the blocks ``(path, first_line_number, text)``; de-duplicated, capped."""
    hits: list[str] = []
    for path, first_line, text in blocks:
        if not text:
            continue
        for offset in scan_prompt_injection(text):
            hit = f"{path}:{first_line + offset - 1}"
            if hit not in hits:
                hits.append(hit)
                if len(hits) >= limit:
                    return hits
    return hits
