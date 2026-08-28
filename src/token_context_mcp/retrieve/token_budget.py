from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

ESTIMATOR_VERSION = "utf8-bytes-div-4-v1"


def estimate_tokens(value: Any) -> int:
    if not isinstance(value, str):
        value = repr(value)
    if not value:
        return 0
    return max(1, math.ceil(len(value.encode("utf-8")) / 4))


def pack_by_budget[T](items: Iterable[T], render: callable, budget_tokens: int) -> tuple[list[T], list[T], int]:
    chosen: list[T] = []
    omitted: list[T] = []
    used = 0
    for item in items:
        estimated = estimate_tokens(render(item))
        if chosen and used + estimated > budget_tokens:
            omitted.append(item)
            continue
        if not chosen and estimated > budget_tokens:
            omitted.append(item)
            continue
        chosen.append(item)
        used += estimated
    return chosen, omitted, used

