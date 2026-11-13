from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

ESTIMATOR_VERSION = "utf8-bytes-div-4-v1"
_O200K_ENCODER: Any | None = None
_O200K_CHECKED = False


def count_tokens_o200k(value: Any) -> tuple[int, str]:
    """Count tokens using tiktoken o200k_base when installed, else utf8-bytes-div-4-v1."""
    global _O200K_ENCODER, _O200K_CHECKED
    if not isinstance(value, str):
        value = repr(value)
    if not value:
        return 0, "o200k_base" if _O200K_ENCODER is not None else ESTIMATOR_VERSION
    if not _O200K_CHECKED:
        _O200K_CHECKED = True
        try:
            import tiktoken  # type: ignore[import-not-found]
            _O200K_ENCODER = tiktoken.get_encoding("o200k_base")
        except Exception:
            _O200K_ENCODER = None
    if _O200K_ENCODER is not None:
        return len(_O200K_ENCODER.encode(value)), "o200k_base"
    return estimate_tokens(value), ESTIMATOR_VERSION


def estimate_tokens(value: Any) -> int:
    if not isinstance(value, str):
        value = repr(value)
    if not value:
        return 0
    return max(1, math.ceil(len(value.encode("utf-8")) / 4))


def pack_by_budget[T](
    items: Iterable[T],
    render: callable,
    budget_tokens: int,
    preserve_first: bool = True,
) -> tuple[list[T], list[T], int]:
    chosen: list[T] = []
    omitted: list[T] = []
    used = 0
    for idx, item in enumerate(items):
        estimated = estimate_tokens(render(item))
        if chosen and used + estimated > budget_tokens:
            omitted.append(item)
            continue
        if not chosen and estimated > budget_tokens:
            if preserve_first and idx == 0:
                chosen.append(item)
                used += estimated
                continue
            omitted.append(item)
            continue
        chosen.append(item)
        used += estimated
    return chosen, omitted, used

