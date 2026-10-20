from __future__ import annotations

import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class EffectRecord:
    """Record of a stateful effect produced during tool execution.
    
    Enables reversible effects / auditing conforming to DeepSeek Harness / Cordis.
    """
    kind: str
    target: str
    data: dict[str, Any] = field(default_factory=dict)
    revert_fn: Callable[[], None] | None = None

    def revert(self) -> None:
        if self.revert_fn is not None:
            self.revert_fn()


@dataclass
class InvocationContext:
    """Unified context passed across the entire middleware waterfall pipeline.
    
    Carries execution identity, spatiotemporal constraints, reactive coeffects,
    and reversible effect logs.
    """
    tool_name: str
    raw_agent_id: str | None = None
    effective_agent_id: str = "anonymous"
    session_id: str | None = None
    tool_call_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.perf_counter)
    bypass_halt: bool = False
    trusted_identity: bool = False
    effects: list[EffectRecord] = field(default_factory=list)
    coeffects: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.start_time) * 1000.0

    def record_effect(
        self,
        kind: str,
        target: str,
        data: dict[str, Any] | None = None,
        revert_fn: Callable[[], None] | None = None,
    ) -> EffectRecord:
        record = EffectRecord(
            kind=kind,
            target=target,
            data=data or {},
            revert_fn=revert_fn,
        )
        self.effects.append(record)
        return record

    def rollback_effects(self) -> None:
        """Revert effects in reverse chronological order."""
        for effect in reversed(self.effects):
            try:
                effect.revert()
            except Exception:
                pass


_CURRENT_CONTEXT: ContextVar[InvocationContext | None] = ContextVar("current_context", default=None)


def get_current_context() -> InvocationContext | None:
    return _CURRENT_CONTEXT.get()


def set_current_context(ctx: InvocationContext | None) -> Token[InvocationContext | None]:
    return _CURRENT_CONTEXT.set(ctx)


def reset_current_context(token: Token[InvocationContext | None]) -> None:
    _CURRENT_CONTEXT.reset(token)
