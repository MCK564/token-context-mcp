from __future__ import annotations

import re
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
