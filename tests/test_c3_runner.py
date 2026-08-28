from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest


def _runner_module():
    script = Path(__file__).resolve().parents[1] / "evals" / "run_c3.py"
    spec = importlib.util.spec_from_file_location("c3_runner", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_detects_structured_mcp_error_envelope() -> None:
    runner = _runner_module()
    error = runner.mcp_error_from_item(
        {
            "error": None,
            "result": {
                "structured_content": {
                    "schema_version": "1.0",
                    "error": {"code": "unknown_repo_id", "message": "call list_repositories"},
                }
            },
        }
    )
    assert error == {"code": "unknown_repo_id", "message": "call list_repositories"}


def test_runner_ignores_successful_mcp_result() -> None:
    runner = _runner_module()
    assert runner.mcp_error_from_item({"error": None, "result": {"structured_content": {"repo_id": "demo"}}}) is None


def test_runner_stops_the_agent_on_first_mcp_error(tmp_path: Path) -> None:
    runner = _runner_module()
    event = {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "token-context",
            "tool": "get_repo_map",
            "error": None,
            "result": {"structured_content": {"error": {"code": "unknown_repo_id", "message": "bad id"}}},
        },
    }
    command = [
        sys.executable,
        "-c",
        f"import time; print({json.dumps(json.dumps(event))}, flush=True); time.sleep(30)",
    ]
    started = time.monotonic()
    with pytest.raises(runner.McpToolError, match="unknown_repo_id"):
        runner.run_command(
            command,
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "stderr.log",
        )
    assert time.monotonic() - started < 5


def test_runner_counts_mcp_result_output_separately(tmp_path: Path) -> None:
    runner = _runner_module()
    result = {"content": [{"type": "text", "text": "repo_id=demo"}], "structured_content": {"repo_id": "demo"}}
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "token-context",
                "tool": "get_index_status",
                "error": None,
                "result": result,
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
    ]
    source = "import json; " + "; ".join(
        f"print({json.dumps(json.dumps(event))}, flush=True)" for event in events
    )
    usage, servers, calls, native_bytes, mcp_bytes, _latency = runner.run_command(
        [sys.executable, "-c", source],
        raw_output=tmp_path / "raw.jsonl",
        stderr_output=tmp_path / "stderr.log",
    )
    assert usage["input_tokens"] == 10
    assert servers == {"token-context"}
    assert calls == 1
    assert native_bytes == 0
    assert mcp_bytes == len(json.dumps(result).encode("utf-8"))


def test_mcp_first_allows_one_native_verification_and_logs_warnings(tmp_path: Path) -> None:
    runner = _runner_module()
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "token-context",
                "tool": "get_impact_slice",
                "result": {
                    "structured_content": {
                        "repo_id": "demo",
                        "warnings": ["lexical_edges_are_not_complete_semantic_analysis"],
                    }
                },
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "aggregated_output": "app.py:4",
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
    ]
    source = "; ".join(f"print({json.dumps(json.dumps(event))}, flush=True)" for event in events)
    telemetry: dict[str, object] = {}
    runner.run_command(
        [sys.executable, "-c", source],
        raw_output=tmp_path / "raw.jsonl",
        stderr_output=tmp_path / "stderr.log",
        protocol="mcp-first",
        telemetry=telemetry,
    )
    assert telemetry["native_command_count"] == 1
    assert telemetry["verification_triggers"] == [
        {
            "native_command_index": 1,
            "preceding_mcp_warnings": ["lexical_edges_are_not_complete_semantic_analysis"],
        }
    ]


def test_mcp_first_rejects_a_second_native_command(tmp_path: Path) -> None:
    runner = _runner_module()
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "server": "token-context",
                "tool": "get_index_status",
                "result": {"structured_content": {"repo_id": "demo", "warnings": []}},
            },
        },
        {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "one"}},
        {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "two"}},
    ]
    source = "; ".join(
        [f"print({json.dumps(json.dumps(event))}, flush=True)" for event in events]
        + ["import time; time.sleep(30)"]
    )
    with pytest.raises(runner.ProtocolViolation, match="at most one"):
        runner.run_command(
            [sys.executable, "-c", source],
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "stderr.log",
            protocol="mcp-first",
        )


def test_runner_rejects_an_mcp_call_budget_overrun(tmp_path: Path) -> None:
    runner = _runner_module()
    event = {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "token-context",
            "tool": "get_repo_map",
            "result": {"structured_content": {"repo_id": "demo"}},
        },
    }
    source = "; ".join(
        [f"print({json.dumps(json.dumps(event))}, flush=True)" for _ in range(2)]
        + ["import time; time.sleep(30)"]
    )
    started = time.monotonic()
    with pytest.raises(runner.ProtocolViolation, match="MCP call budget exceeded"):
        runner.run_command(
            [sys.executable, "-c", source],
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "stderr.log",
            max_mcp_calls=1,
        )
    assert time.monotonic() - started < 5
