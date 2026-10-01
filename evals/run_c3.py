"""Run one instrumented C3 arm and stop on an MCP error envelope or protocol violation.

The command after ``--`` must emit JSONL on stdout (Codex, Claude, or Gemini stream-json).
Supports adapters for multi-agent evaluation (Claude Code, Gemini CLI, Codex).
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from evals.c3_adapters import (
        AgentAdapter,
        Init,
        ToolCall,
        ToolResult,
        Usage,
        get_adapter,
    )
    from evals.c3_grade import grade_answer
except (ImportError, ModuleNotFoundError):
    from c3_adapters import (  # type: ignore
        AgentAdapter,
        Init,
        ToolCall,
        ToolResult,
        Usage,
        get_adapter,
    )
    from c3_grade import grade_answer  # type: ignore



class McpToolError(RuntimeError):
    """A Codex/Agent MCP tool call returned an error envelope."""

    def __init__(self, server: str, tool: str, error: dict[str, Any]) -> None:
        code = str(error.get("code", "unknown_error"))
        message = str(error.get("message", "MCP tool returned an error"))
        super().__init__(f"{server}.{tool}: {code}: {message}")
        self.server = server
        self.tool = tool
        self.error = error


class ProtocolViolation(RuntimeError):
    """The agent violated the selected C3 tool-use protocol."""


class InfraFailure(RuntimeError):
    """An unrecoverable infrastructure failure occurred (MCP connect failure, auth, rate limit)."""


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
    mcp_optional: bool = False,
    protocol: str = "hybrid",
    max_mcp_calls: int | None = None,
    telemetry: dict[str, Any] | None = None,
    agent: str = "codex",
    adapter: AgentAdapter | None = None,
    arm: str | None = None,
    stdin_prompt: str | None = None,
    timeout_s: float | None = None,
    workdir: Path | None = None,
) -> tuple[dict[str, Any], set[str], int, int, int, float]:
    """Run JSONL-producing command and return its final provider usage.

    Raises ``McpToolError``, ``ProtocolViolation``, or ``InfraFailure`` on violations.
    """

    if protocol not in {"hybrid", "mcp-first"}:
        raise ValueError("protocol must be hybrid or mcp-first")
    if max_mcp_calls is not None and max_mcp_calls < 1:
        raise ValueError("max_mcp_calls must be at least 1")
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    stderr_output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    stdin_mode = subprocess.PIPE if stdin_prompt is not None else subprocess.DEVNULL
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=stdin_mode,
        cwd=str(workdir) if workdir else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None

    if stdin_prompt is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_prompt)
            process.stdin.flush()
        except OSError:
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    stderr_thread = threading.Thread(target=_copy_stream, args=(process.stderr, stderr_output), daemon=True)
    stderr_thread.start()

    # The read loop below blocks on the agent's stdout, so a timeout checked only afterwards never fires for a hung
    # agent.  A watchdog timer kills the process tree instead; the loop then ends and the timeout is reported.
    timed_out = threading.Event()

    def _on_timeout() -> None:
        timed_out.set()
        _terminate(process)

    watchdog = threading.Timer(timeout_s, _on_timeout) if timeout_s else None
    if watchdog is not None:
        watchdog.daemon = True
        watchdog.start()

    final_usage: dict[str, Any] | None = None
    mcp_servers: set[str] = set()
    mcp_call_count = 0
    native_command_output_bytes = 0
    mcp_result_output_bytes = 0
    failure: Exception | None = None
    native_command_count = 0
    verification_triggers: list[dict[str, Any]] = []
    last_mcp_warnings: list[str] = []

    # Use specialized adapter loop when agent is not codex or adapter provided
    active_adapter = adapter or (get_adapter(agent) if agent in {"claude", "gemini"} else None)

    with raw_output.open("w", encoding="utf-8", newline="\n") as raw_file:
        for line in process.stdout:
            raw_file.write(line)
            raw_file.flush()
            event = _json_object(line)
            if event is None:
                continue

            if active_adapter is not None:
                norm_events = active_adapter.feed(event)
                for ev in norm_events:
                    if isinstance(ev, Init):
                        if agent == "claude" and arm in {"B1", "B2"}:
                            tcbench_server = next(
                                (
                                    s
                                    for s in ev.mcp_servers
                                    if isinstance(s, dict) and s.get("name") in {"tcbench", "token-context"}
                                ),
                                None,
                            )
                            if tcbench_server and tcbench_server.get("status") in {"failed", "error", "disconnected"}:
                                failure = InfraFailure(f"MCP server not connected: {tcbench_server}")
                                _terminate(process)
                                break

                    elif isinstance(ev, ToolCall):
                        if ev.category == "forbidden":
                            failure = ProtocolViolation(f"Forbidden tool called: {ev.name}")
                            _terminate(process)
                            break
                        if arm == "B0" and ev.category == "mcp":
                            failure = InfraFailure(f"B0 arm received MCP tool call: {ev.name}")
                            _terminate(process)
                            break
                        if protocol == "mcp-first":
                            if mcp_call_count == 0 and ev.category == "native_read":
                                failure = ProtocolViolation("mcp-first requires a successful MCP call before native verification")
                                _terminate(process)
                                break
                            if ev.category == "native_read" and native_command_count >= 1:
                                failure = ProtocolViolation("mcp-first permits at most one native command per task")
                                _terminate(process)
                                break
                        if ev.category == "native_read":
                            native_command_count += 1
                        elif ev.category == "mcp":
                            mcp_call_count += 1
                            if max_mcp_calls is not None and mcp_call_count > max_mcp_calls:
                                failure = ProtocolViolation(
                                    f"MCP call budget exceeded: {mcp_call_count} > {max_mcp_calls}"
                                )
                                _terminate(process)
                                break
                            mcp_servers.add(ev.server or "tcbench")

                    elif isinstance(ev, ToolResult):
                        if ev.is_error:
                            last_c = active_adapter.pending_tool_calls.get(ev.id)
                            if last_c and last_c.category == "mcp":
                                failure = McpToolError(
                                    last_c.server or "tcbench",
                                    last_c.name,
                                    {"code": ev.error_code or "tool_error", "message": ev.text},
                                )
                                _terminate(process)
                                break
                        last_c = active_adapter.pending_tool_calls.get(ev.id)
                        if last_c and last_c.category == "mcp":
                            mcp_result_output_bytes += ev.bytes
                        elif last_c and last_c.category == "native_read":
                            native_command_output_bytes += ev.bytes

                    elif isinstance(ev, Usage):
                        # provider ``raw`` first: its ``input_tokens`` counts only the uncached tokens (Claude Code) and
                        # must not overwrite the normalised totals
                        final_usage = {
                            **ev.raw,
                            "input_tokens": ev.input_total,
                            "uncached_input_tokens": ev.input_uncached,
                            "output_tokens": ev.output,
                            "cached_input_tokens": ev.cached,
                            "cost_usd": ev.cost_usd,
                        }
                if failure is not None:
                    break

            else:
                # Codex backward-compatible branch
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
                result = item.get("result")
                if result is not None:
                    mcp_result_output_bytes += len(json.dumps(result).encode("utf-8"))
                last_mcp_warnings = _mcp_warnings_from_item(item)

    try:
        return_code = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _terminate(process)
        failure = ProtocolViolation(f"Agent command timed out after {timeout_s}s")
        return_code = -1
    finally:
        if watchdog is not None:
            watchdog.cancel()
    if timed_out.is_set() and failure is None:
        failure = ProtocolViolation(f"Agent command timed out after {timeout_s}s")
        return_code = -1

    stderr_thread.join(timeout=5)
    latency = time.monotonic() - started

    if failure is not None:
        raise failure
    if return_code != 0:
        raise RuntimeError(f"agent command exited with status {return_code}")
    if final_usage is None:
        raise RuntimeError("agent command completed without a turn.completed usage event")
    if required_mcp_server and not mcp_optional and required_mcp_server not in mcp_servers:
        raise RuntimeError(f"agent command completed without calling required MCP server: {required_mcp_server}")
    if telemetry is not None:
        telemetry.update(
            {
                "native_command_count": native_command_count,
                "verification_triggers": verification_triggers,
                "final_answer": active_adapter.final().final_answer if active_adapter else "",
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
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
        else:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    except (OSError, subprocess.SubprocessError):
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one C3 arm and fail fast on MCP error envelopes")
    parser.add_argument("--arm", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--task-success", choices=("true", "false"), default=None)
    parser.add_argument("--grade-with", type=Path, default=None, help="Path to manifest JSON to auto-grade answer")
    parser.add_argument("--prompt-sha256", required=True)
    parser.add_argument("--raw-output", required=True, type=Path)
    parser.add_argument("--stderr-output", required=True, type=Path)
    parser.add_argument("--usage-output", required=True, type=Path)
    parser.add_argument("--require-mcp-server")
    parser.add_argument(
        "--mcp-optional",
        action="store_true",
        help="record the run even if the agent never calls the MCP server (hybrid arm: adoption is a result, not a failure)",
    )
    parser.add_argument("--protocol", choices=("hybrid", "mcp-first"), default="hybrid")
    parser.add_argument("--max-mcp-calls", type=int)
    parser.add_argument("--agent", choices=("codex", "claude", "gemini"), default="codex")
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--stdin-prompt", default=None)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a JSONL-producing agent command is required after --")

    if args.task_success is None and args.grade_with is None:
        parser.error("either --task-success or --grade-with must be specified")

    telemetry: dict[str, Any] = {}
    failure_type: str | None = None
    failure_msg: str | None = None
    usage: dict[str, Any] = {}
    mcp_servers: set[str] = set()
    call_count = 0
    native_command_output_bytes = 0
    mcp_result_output_bytes = 0
    latency = 0.0

    try:
        usage, mcp_servers, call_count, native_command_output_bytes, mcp_result_output_bytes, latency = run_command(
            command,
            raw_output=args.raw_output,
            stderr_output=args.stderr_output,
            required_mcp_server=args.require_mcp_server,
            mcp_optional=args.mcp_optional,
            protocol=args.protocol,
            max_mcp_calls=args.max_mcp_calls,
            telemetry=telemetry,
            agent=args.agent,
            arm=args.arm,
            stdin_prompt=args.stdin_prompt,
            timeout_s=args.timeout_s,
            workdir=args.workdir,
        )
    except ProtocolViolation as error:
        failure_type = "protocol_violation"
        failure_msg = str(error)
        print(f"C3 protocol violation: {error}", file=sys.stderr)
    except InfraFailure as error:
        failure_type = "infra_failure"
        failure_msg = str(error)
        print(f"C3 infrastructure failure: {error}", file=sys.stderr)
    except (McpToolError, RuntimeError) as error:
        failure_type = "runtime_error"
        failure_msg = str(error)
        print(f"C3 run rejected: {error}", file=sys.stderr)

    if failure_type:
        record = {
            "agent": args.agent,
            "arm": args.arm,
            "protocol": args.protocol,
            "task_id": args.task_id,
            "seed": args.seed,
            "task_success": False,
            "prompt_sha256": args.prompt_sha256,
            "failure_type": failure_type,
            "failure_message": failure_msg,
            "mcp_health": "failed" if failure_type == "infra_failure" else "passed",
            "protocol_violation": failure_msg if failure_type == "protocol_violation" else None,
            "infra_failure": failure_type == "infra_failure",
            "raw_session_log": str(args.raw_output),
        }
        args.usage_output.parent.mkdir(parents=True, exist_ok=True)
        with args.usage_output.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(record, sort_keys=True) + "\n")
        print(json.dumps(record, sort_keys=True))
        return 2

    # Grade task if --grade-with provided
    task_success = args.task_success == "true" if args.task_success is not None else False
    grading_info = None
    if args.grade_with:
        try:
            m_data = json.loads(args.grade_with.read_text(encoding="utf-8"))
            task_obj = next((t for t in m_data.get("tasks", []) if t["id"] == args.task_id), None)
            if task_obj:
                final_ans = telemetry.get("final_answer", "")
                grading_info = grade_answer(task_obj, final_ans, workdir=args.workdir)
                task_success = grading_info.get("task_success", False)
        except Exception as exc:  # noqa: BLE001
            grading_info = {"error": f"grading_failed: {exc}"}
            task_success = False

    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    native_tokens = (native_command_output_bytes + 3) // 4
    mcp_tokens = (mcp_result_output_bytes + 3) // 4
    record = {
        "agent": args.agent,
        "arm": args.arm,
        "protocol": args.protocol,
        "max_mcp_calls": args.max_mcp_calls,
        "task_id": args.task_id,
        "seed": args.seed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "latency_seconds": round(latency, 2),
        "task_success": task_success,
        "grading": grading_info,
        "prompt_sha256": args.prompt_sha256,
        "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
        "uncached_input_tokens": int(usage.get("uncached_input_tokens", input_tokens)),
        "cost_usd": usage.get("cost_usd"),
        "mcp_adopted": call_count > 0,
        "reasoning_output_tokens": int(usage.get("reasoning_output_tokens", 0)),
        "mcp_health": "passed",
        "mcp_errors": [],
        "mcp_completed_call_count": call_count,
        "mcp_servers": sorted(mcp_servers),
        "native_command_count": telemetry.get("native_command_count", 0),
        "verification_triggers": telemetry.get("verification_triggers", []),
        "native_command_output_estimated_tokens": native_tokens,
        "mcp_result_output_estimated_tokens": mcp_tokens,
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
