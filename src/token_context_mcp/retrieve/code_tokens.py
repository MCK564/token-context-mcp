"""Pure, deterministic identifier and path tokenization utilities for code search."""

import re
from collections.abc import Iterable
from functools import lru_cache
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


# ----------------------------------------------------------------------------------------------------------------
# M13: word-form normalisation for identifier-heavy languages (C#, Java)
# ----------------------------------------------------------------------------------------------------------------
# The FTS5 tokenizer of ``symbol_fts`` has no stemming, so "records" never matches ``RecordWriter`` ("record") and
# "writing" never matches ``Write``.  For C#/Java rows the index additionally stores the Porter stem of every word, and
# for repositories dominated by those languages the query is expanded with the stem of every plain word (see
# ``retrieve.service``).  Both sides use the same function, so only equivalence classes matter, not the stem spelling.

_P_VOWELS = frozenset("aeiou")


def _p_cons(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _P_VOWELS:
        return False
    if ch == "y":
        return True if i == 0 else not _p_cons(word, i - 1)
    return True


def _p_measure(stem: str) -> int:
    """Porter's m: the number of VC sequences in ``stem``."""
    n = 0
    i = 0
    length = len(stem)
    while i < length and _p_cons(stem, i):
        i += 1
    while i < length:
        while i < length and not _p_cons(stem, i):
            i += 1
        if i >= length:
            break
        while i < length and _p_cons(stem, i):
            i += 1
        n += 1
    return n


def _p_has_vowel(stem: str) -> bool:
    return any(not _p_cons(stem, i) for i in range(len(stem)))


def _p_double_cons(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _p_cons(word, len(word) - 1)


def _p_cvc(word: str) -> bool:
    if len(word) < 3:
        return False
    return (
        _p_cons(word, len(word) - 3)
        and not _p_cons(word, len(word) - 2)
        and _p_cons(word, len(word) - 1)
        and word[-1] not in "wxy"
    )


_P_STEP2 = (
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"), ("abli", "able"),
    ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"),
    ("iviti", "ive"), ("biliti", "ble"),
)
_P_STEP3 = (
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", ""),
)
_P_STEP4 = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism", "ate",
    "iti", "ous", "ive", "ize",
)


@lru_cache(maxsize=1 << 18)
def porter_stem(word: str) -> str:
    """The classic Porter (1980) stemmer for one lower-case ASCII word; anything else is returned unchanged."""
    if len(word) <= 2 or not word.isascii() or not word.isalpha():
        return word
    w = word
    # step 1a
    if w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # step 1b
    flag = False
    if w.endswith("eed"):
        if _p_measure(w[:-3]) > 0:
            w = w[:-1]
    elif w.endswith("ed") and _p_has_vowel(w[:-2]):
        w = w[:-2]
        flag = True
    elif w.endswith("ing") and _p_has_vowel(w[:-3]):
        w = w[:-3]
        flag = True
    if flag:
        if w.endswith(("at", "bl", "iz")):
            w += "e"
        elif _p_double_cons(w) and w[-1] not in "lsz":
            w = w[:-1]
        elif _p_measure(w) == 1 and _p_cvc(w):
            w += "e"
    # step 1c
    if w.endswith("y") and _p_has_vowel(w[:-1]):
        w = w[:-1] + "i"
    # step 2
    for suffix, replacement in _P_STEP2:
        if w.endswith(suffix):
            if _p_measure(w[: -len(suffix)]) > 0:
                w = w[: -len(suffix)] + replacement
            break
    # step 3
    for suffix, replacement in _P_STEP3:
        if w.endswith(suffix):
            if _p_measure(w[: -len(suffix)]) > 0:
                w = w[: -len(suffix)] + replacement
            break
    # step 4
    for suffix in _P_STEP4:
        if w.endswith(suffix):
            stem = w[: -len(suffix)]
            if _p_measure(stem) > 1 and (suffix != "ion" or stem.endswith(("s", "t"))):
                w = stem
            break
    # step 5
    if w.endswith("e"):
        stem = w[:-1]
        measure = _p_measure(stem)
        if measure > 1 or (measure == 1 and not _p_cvc(stem)):
            w = stem
    if _p_measure(w) > 1 and _p_double_cons(w) and w.endswith("l"):
        w = w[:-1]
    return w


# Function words of English questions ("how a class instance is written as a CSV row"): they carry no signal against
# code and only add low-idf noise to an OR query.  Deliberately small; negations (not, no) and code words (if, new,
# null, true, false, return, ...) stay.
QUERY_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "from", "with", "into", "onto", "than", "then",
        "and", "or", "but", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its", "that", "this",
        "these", "those", "which", "who", "whom", "whose", "when", "while", "so", "such", "also", "any", "each",
        "per", "via", "up", "out", "off", "over", "their", "there", "they", "them", "we", "our", "you", "your",
        "can", "could", "should", "would", "will", "may", "might", "must", "do", "does", "did", "has", "have", "had",
    }
)


def word_stems(words: Iterable[str]) -> List[str]:
    """Porter stems of ``words`` that differ from the word itself, in first-appearance order, without duplicates."""
    seen: Set[str] = set()
    out: List[str] = []
    for word in words:
        stem = porter_stem(word)
        if stem != word and stem not in seen:
            seen.add(stem)
            out.append(stem)
    return out


_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def identifier_subwords(text: str, limit: int = 400) -> List[str]:
    """Lower-cased camel/Pascal/snake parts of the multi-word identifiers in ``text`` (first-appearance order).

    ``HasHeaderRecord`` contributes ``has``, ``header``, ``record``; one-word identifiers contribute nothing (they are
    already searchable verbatim in the body)."""
    seen: Set[str] = set()
    out: List[str] = []
    for identifier in _IDENTIFIER_RE.findall(text):
        if len(identifier) < 4:
            continue
        parts = split_identifier(identifier)
        if len(parts) < 3:  # split_identifier appends the whole word; fewer than 2 real parts means one word
            continue
        whole = identifier.lower()
        for part in parts:
            if part != whole and len(part) >= 2 and part not in seen:
                seen.add(part)
                out.append(part)
                if len(out) >= limit:
                    return out
    return out
