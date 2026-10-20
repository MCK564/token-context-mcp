from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol

from token_context_mcp.config import ConfigError, UnknownRepositoryError
from token_context_mcp.kernel.context import (
    InvocationContext,
    reset_current_context,
    set_current_context,
)
from token_context_mcp.retrieve.service import (
    ArgumentOutOfRangeError,
    BudgetOutOfRangeError,
    RetrievalError,
)
from token_context_mcp.security.access_control import (
    AccessControlManager,
    resolve_effective_agent_id,
)
from token_context_mcp.security.audit import AuditLogger
from token_context_mcp.security.path_policy import PathPolicyError

logger = logging.getLogger("token_context_mcp.kernel")


def format_error(code: str, message: str, **details: object) -> dict[str, Any]:
    """Format standardized structured MCP error envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"schema_version": "1.0", "error": error}


class Middleware(Protocol):
    def __call__(
        self,
        ctx: InvocationContext,
        call_next: Callable[[InvocationContext], dict[str, Any]],
    ) -> dict[str, Any]:
        ...


class AuthMiddleware:
    """Stage 1: Identity resolution, env-bound check, and reserved admin isolation."""

    def __init__(self, audit_logger: AuditLogger | None = None) -> None:
        self.audit_logger = audit_logger

    def __call__(
        self,
        ctx: InvocationContext,
        call_next: Callable[[InvocationContext], dict[str, Any]],
    ) -> dict[str, Any]:
        effective_agent_id, agent_err = resolve_effective_agent_id(
            ctx.raw_agent_id, trusted=ctx.trusted_identity
        )
        if agent_err is not None:
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.raw_agent_id or "invalid",
                    "DENIED",
                    ctx.elapsed_ms,
                    {"reason": agent_err},
                )
            return format_error("invalid_request", agent_err)

        ctx.effective_agent_id = effective_agent_id
        return call_next(ctx)


class GovernanceMiddleware:
    """Stage 2: Access policy, emergency halt, pause/block state, and rate limits."""

    def __init__(
        self,
        access_control: AccessControlManager | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.access_control = access_control
        self.audit_logger = audit_logger

    def __call__(
        self,
        ctx: InvocationContext,
        call_next: Callable[[InvocationContext], dict[str, Any]],
    ) -> dict[str, Any]:
        if self.access_control is not None:
            allowed, reason = self.access_control.check_access(
                ctx.tool_name,
                ctx.effective_agent_id,
                bypass_halt=ctx.bypass_halt,
            )
            if not allowed:
                if self.audit_logger is not None:
                    self.audit_logger.log(
                        ctx.tool_name,
                        ctx.effective_agent_id,
                        "DENIED",
                        ctx.elapsed_ms,
                        {"reason": reason},
                    )
                return format_error(
                    "permission_revoked",
                    reason or "Operation denied by access control policy",
                    agent_id=ctx.effective_agent_id,
                )

        return call_next(ctx)


class ExecutionMiddleware:
    """Stage 3: Dispatch to execution callback and domain exception translation."""

    def __init__(
        self,
        callback: Callable[[], dict[str, Any]],
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.callback = callback
        self.audit_logger = audit_logger

    def __call__(
        self,
        ctx: InvocationContext,
        call_next: Callable[[InvocationContext], dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            result = self.callback()
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.effective_agent_id,
                    "SUCCESS",
                    ctx.elapsed_ms,
                )
            ctx.result = result
            return result
        except UnknownRepositoryError:
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.effective_agent_id,
                    "ERROR",
                    ctx.elapsed_ms,
                    {"code": "unknown_repo_id"},
                )
            logger.warning("tool request rejected: unknown repo_id")
            return format_error(
                "unknown_repo_id",
                "repo_id is not registered; call list_repositories and use one returned ID",
            )
        except BudgetOutOfRangeError as error:
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.effective_agent_id,
                    "ERROR",
                    ctx.elapsed_ms,
                    {"code": "budget_out_of_range"},
                )
            logger.warning("tool request rejected: budget out of range")
            return format_error(
                "budget_out_of_range",
                str(error),
                minimum_tokens=error.minimum,
                maximum_tokens=error.maximum,
            )
        except ArgumentOutOfRangeError as error:
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.effective_agent_id,
                    "ERROR",
                    ctx.elapsed_ms,
                    {"code": "argument_out_of_range"},
                )
            logger.warning("tool request rejected: %s out of range", error.field_name)
            return format_error(
                "argument_out_of_range",
                str(error),
                field=error.field_name,
                minimum=error.minimum,
                maximum=error.maximum,
            )
        except PathPolicyError:
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.effective_agent_id,
                    "ERROR",
                    ctx.elapsed_ms,
                    {"code": "policy_rejected"},
                )
            logger.warning("tool request rejected by repository path policy")
            return format_error("policy_rejected", "request rejected by read-only repository policy")
        except (ConfigError, RetrievalError, ValueError) as error:
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.effective_agent_id,
                    "ERROR",
                    ctx.elapsed_ms,
                    {"code": "invalid_request", "type": type(error).__name__},
                )
            logger.warning("tool request rejected: %s", type(error).__name__)
            return format_error("invalid_request", "request violates the read-only retrieval contract")
        except Exception as exc:
            if self.audit_logger is not None:
                self.audit_logger.log(
                    ctx.tool_name,
                    ctx.effective_agent_id,
                    "ERROR",
                    ctx.elapsed_ms,
                    {"code": "internal_error", "error": str(exc)},
                )
            logger.exception("tool request failed")
            return format_error("internal_error", "context service could not complete the request")


class InvocationPipeline:
    """Sequential middleware waterfall conforming to DeepSeek Harness / Cordis."""

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self.middlewares: list[Middleware] = middlewares or []

    def execute(self, ctx: InvocationContext) -> dict[str, Any]:
        token = set_current_context(ctx)
        try:
            index = 0

            def call_next(c: InvocationContext) -> dict[str, Any]:
                nonlocal index
                if index < len(self.middlewares):
                    current_mw = self.middlewares[index]
                    index += 1
                    return current_mw(c, call_next)
                return {}

            return call_next(ctx)
        finally:
            reset_current_context(token)
