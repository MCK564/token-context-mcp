"""Pure, deterministic identifier and path tokenization utilities for code search."""

from pathlib import PurePosixPath
from typing import List, Set


def split_identifier(s: str) -> List[str]:
    """Split snake_case, camelCase, PascalCase, numbers, and acronyms into tokens.

    Returns the lowercased constituent parts AND the original lowercased string.
    Deterministic, pure function.
    """
    if not s:
        return []
    s_stripped = s.strip()
    if not s_stripped:
        return []
    original_lower = s_stripped.lower()

    words: List[str] = []
    current: List[str] = []

    def flush() -> None:
        if current:
            words.append("".join(current).lower())
            current.clear()

    n = len(s_stripped)
    for i, ch in enumerate(s_stripped):
        if not ch.isalnum():
            flush()
            continue

        if current:
            prev = current[-1]
            # Transition: lowercase or digit followed by uppercase (e.g., parseV2 -> parse V2)
            if (prev.islower() or prev.isdigit()) and ch.isupper():
                flush()
            # Transition: uppercase sequence followed by lowercase (e.g., HTTPServer -> HTTP Server)
            elif prev.isupper() and ch.isupper() and (i + 1 < n and s_stripped[i + 1].islower()):
                flush()

        current.append(ch)
    flush()

    res: List[str] = []
    seen: Set[str] = set()
    for w in words:
        if w not in seen:
            seen.add(w)
            res.append(w)

    if original_lower not in seen and original_lower:
        res.append(original_lower)

    return res


def path_tokens(path: str) -> List[str]:
    """Extract directory names and file stem from path, dropping 'src' and extension.

    Also decomposes components with split_identifier.
    """
    if not path:
        return []
    p = PurePosixPath(path.replace("\\", "/"))
    parts = list(p.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if not parts:
        return []

    filename = parts[-1]
    stem = PurePosixPath(filename).stem
    dirs = parts[:-1]

    res: List[str] = []
    seen: Set[str] = set()

    def add_token(t: str) -> None:
        t_clean = t.strip().lower()
        if t_clean and t_clean not in seen:
            seen.add(t_clean)
            res.append(t_clean)

    for d in dirs:
        add_token(d)
        for sub in split_identifier(d):
            add_token(sub)
    add_token(stem)
    for sub in split_identifier(stem):
        add_token(sub)

    return res
