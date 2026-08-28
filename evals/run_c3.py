"""Run one instrumented Codex C3 arm and stop on an MCP error envelope.

The command after ``--`` must emit Codex JSONL on stdout, typically
``codex exec --json ...``. Successful runs append provider-reported usage to
the requested JSONL file; a failed MCP call terminates the agent before a
misleading native-fallback result can be recorded.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


class McpToolError(RuntimeError):
    """A Codex MCP tool call returned an error envelope."""

    def __init__(self, server: str, tool: str, error: dict[str, Any]) -> None:
        code = str(error.get("code", "unknown_error"))
        message = str(error.get("message", "MCP tool returned an error"))
        super().__init__(f"{server}.{tool}: {code}: {message}")
        self.server = server
        self.tool = tool
        self.error = error


class ProtocolViolation(RuntimeError):
    """The agent violated the selected C3 tool-use protocol."""


def mcp_error_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return an MCP error whether Codex placed it on the item or in its result."""

    direct = item.get("error")
    if isinstance(direct, dict):
        return direct
    if direct:
        return {"code": "tool_call_failed", "message": str(direct)}
    result = item.get("result")
    if not isinstance(result, dict):
        return None
    for key in ("structured_content", "structuredContent"):
        structured = result.get(key)
        if isinstance(structured, dict) and isinstance(structured.get("error"), dict):
            return structured["error"]
    for content in result.get("content", []):
        if not isinstance(content, dict) or content.get("type") != "text":
            continue
        try:
            decoded = json.loads(str(content.get("text", "")))
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict) and isinstance(decoded.get("error"), dict):
            return decoded["error"]
    return None


def run_command(
    command: list[str],
    *,
    raw_output: Path,
    stderr_output: Path,
    required_mcp_server: str | None = None,
    protocol: str = "hybrid",
    max_mcp_calls: int | None = None,
    telemetry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], set[str], int, int, int, float]:
    """Run JSONL-producing command and return its final provider usage.

    Raises ``McpToolError`` immediately after an MCP error response appears.
    """

    if protocol not in {"hybrid", "mcp-first"}:
        raise ValueError("protocol must be hybrid or mcp-first")
    if max_mcp_calls is not None and max_mcp_calls < 1:
        raise ValueError("max_mcp_calls must be at least 1")
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    stderr_output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stderr_thread = threading.Thread(target=_copy_stream, args=(process.stderr, stderr_output), daemon=True)
    stderr_thread.start()
    final_usage: dict[str, Any] | None = None
    mcp_servers: set[str] = set()
    mcp_call_count = 0
    native_command_output_bytes = 0
    mcp_result_output_bytes = 0
    failure: McpToolError | None = None
    native_command_count = 0
    verification_triggers: list[dict[str, Any]] = []
    last_mcp_warnings: list[str] = []
    with raw_output.open("w", encoding="utf-8", newline="\n") as raw_file:
        for line in process.stdout:
            raw_file.write(line)
            raw_file.flush()
            event = _json_object(line)
            if event is None:
                continue
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                final_usage = event["usage"]
            item = event.get("item")
            if event.get("type") != "item.completed" or not isinstance(item, dict):
                continue
            if item.get("type") == "command_execution":
                native_command_count += 1
                verification_triggers.append(
                    {
                        "native_command_index": native_command_count,
                        "preceding_mcp_warnings": last_mcp_warnings,
                    }
                )
                if protocol == "mcp-first" and mcp_call_count == 0:
                    failure = ProtocolViolation("mcp-first requires a successful MCP call before native verification")
                    _terminate(process)
                    break
                if protocol == "mcp-first" and native_command_count > 1:
                    failure = ProtocolViolation("mcp-first permits at most one native command per task")
                    _terminate(process)
                    break
                output = item.get("aggregated_output")
                if isinstance(output, str):
                    native_command_output_bytes += len(output.encode("utf-8"))
                continue
            if item.get("type") != "mcp_tool_call":
                continue
            mcp_call_count += 1
            if max_mcp_calls is not None and mcp_call_count > max_mcp_calls:
                failure = ProtocolViolation(
                    f"MCP call budget exceeded: {mcp_call_count} > {max_mcp_calls}"
                )
                _terminate(process)
                break
            server = str(item.get("server", "unknown-server"))
            tool = str(item.get("tool", "unknown-tool"))
            mcp_servers.add(server)
            error = mcp_error_from_item(item)
            if error is not None:
                failure = McpToolError(server, tool, error)
                _terminate(process)
                break
            # Same-shaped bytes as native_command_output: what the agent
            # actually received back for this call, not what a local
            # RetrievalService return value would measure. Without this an
            # arm that leans on MCP looks like it retrieved almost nothing
            # (see docs/REMEDIATION_AND_BENCHMARK_PLAN.en.md S2.7 finding 2 —
            # the pilot that motivated this counter).
            result = item.get("result")
            if result is not None:
                mcp_result_output_bytes += len(json.dumps(result).encode("utf-8"))
            last_mcp_warnings = _mcp_warnings_from_item(item)
    return_code = process.wait()
    stderr_thread.join(timeout=5)
    latency = time.monotonic() - started
    if failure is not None:
        raise failure
    if return_code != 0:
        raise RuntimeError(f"agent command exited with status {return_code}")
    if final_usage is None:
        raise RuntimeError("agent command completed without a turn.completed usage event")
    if required_mcp_server and required_mcp_server not in mcp_servers:
        raise RuntimeError(f"agent command completed without calling required MCP server: {required_mcp_server}")
    if telemetry is not None:
        telemetry.update(
            {
                "native_command_count": native_command_count,
                "verification_triggers": verification_triggers,
            }
        )
    return final_usage, mcp_servers, mcp_call_count, native_command_output_bytes, mcp_result_output_bytes, latency


def _copy_stream(stream: Any, destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for line in stream:
            output.write(line)


def _json_object(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _mcp_warnings_from_item(item: dict[str, Any]) -> list[str]:
    result = item.get("result")
    if not isinstance(result, dict):
        return []
    for key in ("structured_content", "structuredContent"):
        structured = result.get(key)
        if isinstance(structured, dict) and isinstance(structured.get("warnings"), list):
            return [str(warning) for warning in structured["warnings"]]
    return []


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one C3 arm and fail fast on MCP error envelopes")
    parser.add_argument("--arm", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--task-success", required=True, choices=("true", "false"))
    parser.add_argument("--prompt-sha256", required=True)
    parser.add_argument("--raw-output", required=True, type=Path)
    parser.add_argument("--stderr-output", required=True, type=Path)
    parser.add_argument("--usage-output", required=True, type=Path)
    parser.add_argument("--require-mcp-server")
    parser.add_argument("--protocol", choices=("hybrid", "mcp-first"), default="hybrid")
    parser.add_argument("--max-mcp-calls", type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a JSONL-producing agent command is required after --")
    try:
        telemetry: dict[str, Any] = {}
        usage, mcp_servers, call_count, native_command_output_bytes, mcp_result_output_bytes, latency = run_command(
            command,
            raw_output=args.raw_output,
            stderr_output=args.stderr_output,
            required_mcp_server=args.require_mcp_server,
            protocol=args.protocol,
            max_mcp_calls=args.max_mcp_calls,
            telemetry=telemetry,
        )
    except (McpToolError, RuntimeError) as error:
        print(f"C3 run rejected: {error}", file=sys.stderr)
        return 2
    input_tokens = int(usage["input_tokens"])
    output_tokens = int(usage["output_tokens"])
    native_tokens = (native_command_output_bytes + 3) // 4
    mcp_tokens = (mcp_result_output_bytes + 3) // 4
    record = {
        "arm": args.arm,
        "protocol": args.protocol,
        "max_mcp_calls": args.max_mcp_calls,
        "task_id": args.task_id,
        "seed": args.seed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "latency_seconds": round(latency, 2),
        "task_success": args.task_success == "true",
        "prompt_sha256": args.prompt_sha256,
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
        "reasoning_output_tokens": int(usage.get("reasoning_output_tokens", 0)),
        "mcp_health": "passed",
        "mcp_errors": [],
        "mcp_completed_call_count": call_count,
        "mcp_servers": sorted(mcp_servers),
        "native_command_count": telemetry.get("native_command_count", 0),
        "verification_triggers": telemetry.get("verification_triggers", []),
        "native_command_output_estimated_tokens": native_tokens,
        "mcp_result_output_estimated_tokens": mcp_tokens,
        # Sum of both channels an arm can retrieve content through. Comparing
        # native_command_output_estimated_tokens alone between arms is
        # misleading for any arm that used MCP tools instead of shell reads —
        # this is the number to diff for "how much content did this arm pull in".
        "retrieved_content_estimated_tokens": native_tokens + mcp_tokens,
        "content_estimator": "utf8-bytes-div-4-v1",
        "raw_session_log": str(args.raw_output),
    }
    args.usage_output.parent.mkdir(parents=True, exist_ok=True)
    with args.usage_output.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
