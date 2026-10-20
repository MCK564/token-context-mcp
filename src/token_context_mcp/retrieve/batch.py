from __future__ import annotations

import logging
from typing import Any, Callable

from token_context_mcp.security.access_control import READ_ONLY_TOOLS

logger = logging.getLogger("token_context_mcp.batch")

BATCHABLE_OPERATIONS: frozenset[str] = frozenset({
    "list_repositories",
    "get_index_status",
    "get_repo_map",
    "find_symbols",
    "get_module_dependents",
    "search_source",
    "get_file_skeleton",
    "get_symbol_context",
    "get_impact_slice",
    "inspect_symbol",
})


def resolve_argument_references(args: dict[str, Any], previous_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve dynamic references like '$prev.data.symbols[0].symbol_id' from earlier batch steps."""
    resolved = dict(args)
    if not previous_results:
        return resolved

    prev = previous_results[-1].get("result", previous_results[-1])
    for k, v in args.items():
        if isinstance(v, str) and v.startswith("$prev."):
            parts = v[6:].split(".")
            val: Any = prev
            try:
                for part in parts:
                    if "[" in part and part.endswith("]"):
                        p_name, idx_str = part[:-1].split("[")
                        if p_name:
                            val = val[p_name]
                        val = val[int(idx_str)]
                    else:
                        val = val[part]
                resolved[k] = val
            except (KeyError, IndexError, TypeError, ValueError):
                pass
    return resolved


class ContextBatchExecutor:
    """Executes declarative multi-step context retrieval batches in a single turn."""

    def __init__(self, service: Any, workflow_engine: Any) -> None:
        self.service = service
        self.workflow_engine = workflow_engine

    def execute_batch(
        self,
        repo_id: str,
        operations: list[dict[str, Any]],
        budget_tokens: int = 4096,
    ) -> dict[str, Any]:
        if not operations:
            return {"status": "error", "error": "operations list cannot be empty"}
        if len(operations) > 10:
            return {"status": "error", "error": "operations count exceeds maximum limit of 10"}

        results: list[dict[str, Any]] = []
        warnings: list[str] = []

        for i, op_spec in enumerate(operations):
            op = op_spec.get("op")
            if not op or op not in BATCHABLE_OPERATIONS:
                return {
                    "status": "error",
                    "error": f"Operation '{op}' at index {i} is not a permitted read-only batch operation",
                    "permitted_operations": sorted(BATCHABLE_OPERATIONS),
                }

            raw_args = op_spec.get("args", {})
            args = resolve_argument_references(raw_args, results)
            args["repo_id"] = repo_id

            try:
                if op == "find_symbols":
                    step_res = self.service.find_symbols(
                        repo_id=repo_id,
                        pattern=args.get("pattern", "*"),
                        kind=args.get("kind"),
                        limit=args.get("limit", 20),
                    )
                elif op == "get_symbol_context":
                    step_res = self.service.symbol_context(
                        repo_id=repo_id,
                        symbol_id=args["symbol_id"],
                        depth=args.get("depth", 0),
                        max_tokens=args.get("max_tokens", budget_tokens // len(operations)),
                        include_body=args.get("include_body", True),
                    )
                elif op == "get_file_skeleton":
                    step_res = self.service.file_skeleton(
                        repo_id=repo_id,
                        path=args["path"],
                        max_tokens=args.get("max_tokens", budget_tokens // len(operations)),
                    )
                elif op == "search_source":
                    step_res = self.service.search_source(
                        repo_id=repo_id,
                        query=args["query"],
                        limit=args.get("limit", 20),
                    )
                elif op == "get_repo_map":
                    step_res = self.service.repo_map(
                        repo_id=repo_id,
                        query=args.get("query"),
                        budget_tokens=args.get("budget_tokens", budget_tokens // len(operations)),
                        format=args.get("format", "compact"),
                    )
                elif op == "get_impact_slice":
                    step_res = self.service.impact_slice(
                        repo_id=repo_id,
                        symbol_id=args["symbol_id"],
                        depth=args.get("depth", 1),
                        max_nodes=args.get("max_nodes", 100),
                    )
                elif op == "inspect_symbol":
                    step_res = self.workflow_engine.inspect_symbol(
                        repo_id=repo_id,
                        query=args.get("query"),
                        symbol_id=args.get("symbol_id"),
                        view=args.get("view", "normal"),
                        budget_tokens=args.get("budget_tokens", budget_tokens // len(operations)),
                    )
                elif op == "get_index_status":
                    step_res = self.service.status(repo_id=repo_id)
                elif op == "list_repositories":
                    step_res = self.service.list_repositories()
                elif op == "get_module_dependents":
                    step_res = self.service.module_dependents(
                        repo_id=repo_id,
                        path=args.get("path"),
                        module=args.get("module"),
                    )
                else:
                    step_res = {"error": f"Unsupported op: {op}"}

                results.append({"op": op, "result": step_res})
            except Exception as exc:
                logger.exception("Batch operation '%s' failed at step %d", op, i)
                results.append({"op": op, "error": str(exc)})
                warnings.append(f"step_{i}_{op}_failed")

        return {
            "schema_version": "1.0",
            "repo_id": repo_id,
            "status": "success",
            "executed_count": len(results),
            "operations": results,
            "warnings": warnings,
        }
