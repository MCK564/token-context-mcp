"""Tests for C3 v2 multi-agent harness, adapters, and grading (M12.5.8)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.c3_adapters import (
    AssistantText,
    ClaudeAdapter,
    CodexAdapter,
    GeminiAdapter,
    Init,
    ToolCall,
    ToolResult,
    Usage,
    classify_tool,
)
from evals.c3_grade import extract_fenced_json, grade_answer, normalize_path
from evals.run_c3 import (
    InfraFailure,
    ProtocolViolation,
    run_command,
)
from evals.run_c3_matrix import main as matrix_main

# ---------------------------------------------------------------------------
# 1. Adapter Stream Parsing Tests
# ---------------------------------------------------------------------------


def test_classify_tool() -> None:
    # Forbidden
    assert classify_tool("Bash")[0] == "forbidden"
    assert classify_tool("write_file")[0] == "forbidden"
    assert classify_tool("Edit")[0] == "forbidden"

    # MCP
    cat, name = classify_tool("mcp__tcbench__find_symbols")
    assert cat == "mcp"
    assert name == "find_symbols"

    cat, name = classify_tool("mcp_tcbench_find_symbols")
    assert cat == "mcp"
    assert name == "find_symbols"

    # Native read
    assert classify_tool("Read")[0] == "native_read"
    assert classify_tool("grep")[0] == "native_read"
    assert classify_tool("read_file")[0] == "native_read"

    # Neutral
    assert classify_tool("thought")[0] == "neutral"


def test_claude_adapter_synthetic_stream() -> None:
    adapter = ClaudeAdapter()

    # 1. System init
    init_evs = adapter.feed({
        "type": "system",
        "subtype": "init",
        "model": "claude-3-7-sonnet",
        "tools": ["Read", "Grep"],
        "mcp_servers": [{"name": "tcbench", "status": "connected"}],
    })
    assert len(init_evs) == 1
    assert isinstance(init_evs[0], Init)
    assert init_evs[0].model == "claude-3-7-sonnet"

    # 2. Assistant tool use (MCP)
    call_evs = adapter.feed({
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "mcp__tcbench__find_symbols",
                    "input": {"query": "parse"},
                },
                {"type": "text", "text": "Searching for symbol..."},
            ]
        },
    })
    assert len(call_evs) == 2
    assert isinstance(call_evs[0], ToolCall)
    assert call_evs[0].name == "find_symbols"
    assert call_evs[0].category == "mcp"
    assert isinstance(call_evs[1], AssistantText)

    # 3. User tool result
    res_evs = adapter.feed({
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": '{"symbols": [{"name": "parse"}]}',
                    "is_error": False,
                }
            ]
        },
    })
    assert len(res_evs) == 1
    assert isinstance(res_evs[0], ToolResult)
    assert not res_evs[0].is_error
    assert res_evs[0].bytes > 0

    # 4. Result and usage
    final_evs = adapter.feed({
        "type": "result",
        "result": '```json\n{"files": ["src/main.py"], "symbols": []}\n```',
        "total_cost_usd": 0.015,
        "usage": {
            "input_tokens": 1200,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 400,
            "output_tokens": 350,
        },
    })
    assert len(final_evs) == 1
    assert isinstance(final_evs[0], Usage)
    assert final_evs[0].input_total == 1700
    assert final_evs[0].cached == 400
    assert final_evs[0].cost_usd == 0.015

    record = adapter.final()
    assert record.mcp_call_count == 1
    assert record.native_read_count == 0
    assert "src/main.py" in record.final_answer


def test_gemini_adapter_synthetic_stream() -> None:
    adapter = GeminiAdapter()

    # 1. Init
    init_evs = adapter.feed({"type": "init", "model": "gemini-2.5-pro", "tools": ["read_file"]})
    assert len(init_evs) == 1
    assert isinstance(init_evs[0], Init)

    # 2. Tool call
    call_evs = adapter.feed({
        "type": "tool_call",
        "id": "g_call_1",
        "tool": "mcp_tcbench_search_source",
        "parameters": {"query": "config"},
    })
    assert len(call_evs) == 1
    assert isinstance(call_evs[0], ToolCall)
    assert call_evs[0].category == "mcp"
    assert call_evs[0].name == "search_source"

    # 3. Tool result
    res_evs = adapter.feed({
        "type": "tool_result",
        "id": "g_call_1",
        "result": "found 1 file",
        "error": None,
    })
    assert len(res_evs) == 1
    assert isinstance(res_evs[0], ToolResult)
    assert res_evs[0].bytes > 0

    # 4. Result
    final_evs = adapter.feed({
        "type": "result",
        "content": '```json\n{"files": ["config.py"]}\n```',
        "stats": {
            "input_tokens": 800,
            "output_tokens": 120,
            "cached": 200,
        },
    })
    assert len(final_evs) == 1
    assert isinstance(final_evs[0], Usage)
    assert final_evs[0].input_total == 800

    record = adapter.final()
    assert record.mcp_call_count == 1
    assert "config.py" in record.final_answer


def test_codex_adapter_synthetic_stream() -> None:
    adapter = CodexAdapter()

    # turn completed usage
    evs = adapter.feed({
        "type": "turn.completed",
        "usage": {"input_tokens": 500, "output_tokens": 100, "cached_tokens": 50},
    })
    assert len(evs) == 1
    assert isinstance(evs[0], Usage)
    assert evs[0].input_total == 500

    # item completed
    item_evs = adapter.feed({
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "tcbench",
            "tool": "find_symbols",
            "result": {"symbols": []},
        },
    })
    assert len(item_evs) == 2  # ToolCall + ToolResult
    assert isinstance(item_evs[0], ToolCall)
    assert isinstance(item_evs[1], ToolResult)
    assert adapter.final().mcp_call_count == 1


# ---------------------------------------------------------------------------
# 2. Protocol Violations & Arm Enforcement
# ---------------------------------------------------------------------------


DEV_MANIFEST = Path(__file__).resolve().parent.parent / "evals" / "c3" / "locate_v2_dev_manifest.json"


def _make_jsonl_proc_script(events: list[dict]) -> list[str]:
    lines = "; ".join(f"print({json.dumps(json.dumps(ev))}, flush=True)" for ev in events)
    return [sys.executable, "-c", f"import json, time; {lines}"]


def test_claude_b0_mcp_leak_fails_with_infra_failure(tmp_path: Path) -> None:
    events = [
        {"type": "system", "subtype": "init", "mcp_servers": []},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "1", "name": "mcp__tcbench__find_symbols", "input": {}}
                ]
            },
        },
    ]
    cmd = _make_jsonl_proc_script(events)
    with pytest.raises(InfraFailure, match="B0 arm received MCP tool call"):
        run_command(
            cmd,
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "err.log",
            agent="claude",
            arm="B0",
            protocol="hybrid",
        )


def test_b2_native_before_mcp_violates_protocol(tmp_path: Path) -> None:
    events = [
        {"type": "system", "subtype": "init", "mcp_servers": []},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "1", "name": "Read", "input": {"path": "main.py"}}
                ]
            },
        },
    ]
    cmd = _make_jsonl_proc_script(events)
    with pytest.raises(ProtocolViolation, match="mcp-first requires a successful MCP call before native verification"):
        run_command(
            cmd,
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "err.log",
            agent="claude",
            arm="B2",
            protocol="mcp-first",
        )


def test_b2_more_than_one_native_read_violates_protocol(tmp_path: Path) -> None:
    events = [
        {"type": "system", "subtype": "init", "mcp_servers": []},
        # 1st: MCP call
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": "1", "name": "mcp__tcbench__find_symbols", "input": {}}]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "1", "content": "{}", "is_error": False}]
            },
        },
        # 2nd: First native verification read (allowed)
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": "2", "name": "Read", "input": {"path": "main.py"}}]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "2", "content": "code", "is_error": False}]
            },
        },
        # 3rd: Second native verification read (FORBIDDEN in B2)
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": "3", "name": "Grep", "input": {"path": "util.py"}}]
            },
        },
    ]
    cmd = _make_jsonl_proc_script(events)
    with pytest.raises(ProtocolViolation, match="mcp-first permits at most one native command per task"):
        run_command(
            cmd,
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "err.log",
            agent="claude",
            arm="B2",
            protocol="mcp-first",
        )


def test_forbidden_tool_call_violates_protocol(tmp_path: Path) -> None:
    events = [
        {"type": "system", "subtype": "init", "mcp_servers": []},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "1", "name": "Bash", "input": {"command": "ls"}}
                ]
            },
        },
    ]
    cmd = _make_jsonl_proc_script(events)
    with pytest.raises(ProtocolViolation, match="Forbidden tool called"):
        run_command(
            cmd,
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "err.log",
            agent="claude",
            arm="B1",
            protocol="hybrid",
        )


def test_claude_init_mcp_disconnected_raises_infra_failure(tmp_path: Path) -> None:
    events = [
        {
            "type": "system",
            "subtype": "init",
            "mcp_servers": [{"name": "tcbench", "status": "failed"}],
        },
    ]
    cmd = _make_jsonl_proc_script(events)
    with pytest.raises(InfraFailure, match="MCP server not connected"):
        run_command(
            cmd,
            raw_output=tmp_path / "raw.jsonl",
            stderr_output=tmp_path / "err.log",
            agent="claude",
            arm="B1",
            protocol="hybrid",
        )


# ---------------------------------------------------------------------------
# 3. Path Normalization & Grading Tests
# ---------------------------------------------------------------------------


def test_normalize_path() -> None:
    assert normalize_path(r"src\foo\bar.py") == "src/foo/bar.py"
    assert normalize_path("./src/foo/bar.py") == "src/foo/bar.py"
    assert normalize_path("/src/foo/bar.py") == "src/foo/bar.py"
    assert normalize_path("D:/AI/repo/src/foo.py", workdir="D:/AI/repo") == "src/foo.py"
    assert normalize_path(r"D:\AI\repo\src\foo.py", workdir="D:/AI/repo") == "src/foo.py"


def test_extract_fenced_json() -> None:
    text = """Here is the result:
```json
{
  "files": ["rich/console.py"],
  "symbols": [{"path": "rich/console.py", "name": "Console.print"}]
}
```
"""
    data = extract_fenced_json(text)
    assert data is not None
    assert data["files"] == ["rich/console.py"]

    # Trailing content after block
    text_with_trailer = text + "\nExtra notes"
    data = extract_fenced_json(text_with_trailer)
    assert data is not None
    assert data["files"] == ["rich/console.py"]


def test_grade_answer_group_a_and_b() -> None:
    task = {
        "id": "rich_t04",
        "group": "a_keyword",
        "gold_files": ["rich/syntax.py"],
        "counted": True,
    }

    # Success: in top 3
    ans_pass = '```json\n{"files": ["rich/syntax.py", "rich/other.py"]}\n```'
    g_pass = grade_answer(task, ans_pass)
    assert g_pass["task_success"] is True

    # Fail: at rank 4 (> 3)
    ans_fail = '```json\n{"files": ["f1.py", "f2.py", "f3.py", "rich/syntax.py"]}\n```'
    g_fail = grade_answer(task, ans_fail)
    assert g_fail["task_success"] is False

    # Fail: parse error
    ans_bad = "No JSON here!"
    g_bad = grade_answer(task, ans_bad)
    assert g_bad["task_success"] is False
    assert g_bad["error"] == "answer_parse_error"


def test_grade_answer_group_c_multi_file() -> None:
    task = {
        "id": "hono_t21",
        "group": "c_multi_file",
        "gold_files": ["src/router.ts", "src/context.ts", "src/hono.ts"],
        "counted": True,
    }

    # Recall 2/3 = 0.67 >= 0.5 in top 5 -> pass
    ans_pass = '```json\n{"files": ["src/router.ts", "src/context.ts", "other.ts"]}\n```'
    g_pass = grade_answer(task, ans_pass)
    assert g_pass["task_success"] is True
    assert g_pass["file_recall"] == pytest.approx(2 / 3, 0.01)

    # Recall 1/3 = 0.33 < 0.5 -> fail
    ans_fail = '```json\n{"files": ["src/router.ts", "other1.ts", "other2.ts"]}\n```'
    g_fail = grade_answer(task, ans_fail)
    assert g_fail["task_success"] is False
    assert g_fail["file_recall"] == pytest.approx(1 / 3, 0.01)


def test_grade_answer_uncounted_probe() -> None:
    task = {
        "id": "probe",
        "group": "probe",
        "gold_files": [],
        "counted": False,
    }
    res = grade_answer(task, "any answer")
    assert res["task_success"] is True
    assert res["counted"] is False


# ---------------------------------------------------------------------------
# 4. Matrix Dry-Run Acceptance Gate Tests
# ---------------------------------------------------------------------------


def test_matrix_dry_run_locate_v2_exact_120_runs() -> None:
    for agent in ("claude", "gemini", "codex"):
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            ret = matrix_main(["--suite", "locate_v2", "--agent", agent, "--dry-run", "--manifest", str(DEV_MANIFEST)])
        finally:
            sys.stdout = old_stdout

        assert ret == 0
        output = buf.getvalue().strip().splitlines()
        assert len(output) == 120, f"Expected 120 dry-run runs for {agent}, got {len(output)}"

        # Verify deterministic seed shuffling: check that arm order varies across tasks
        records = [json.loads(line) for line in output]
        arm_orders = [r["arm"] for r in records[:6]]
        # In sorted arms, order would be B0, B1, B2, B0, B1, B2. Shuffled will differ.
        assert len(arm_orders) == 6
        assert len(records) == 120
        # Probe task must be skipped
        task_ids = {r["task_id"] for r in records}
        assert "probe" not in task_ids


# ---------------------------------------------------------------------------
# 5. M12 review: budget B1, watchdog, stdin, resume, run-config, suite roles, path case
# ---------------------------------------------------------------------------


def _mcp_call_events(count: int) -> list[dict]:
    events: list[dict] = [{"type": "system", "subtype": "init", "mcp_servers": [{"name": "tcbench", "status": "connected"}]}]
    for index in range(count):
        events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": str(index), "name": "mcp__tcbench__search_source", "input": {}}]}})
        events.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": str(index), "content": "{}", "is_error": False}]}})
    return events


def test_b1_thirteenth_mcp_call_exceeds_the_budget(tmp_path: Path) -> None:
    with pytest.raises(ProtocolViolation, match="MCP call budget exceeded: 13 > 12"):
        run_command(_make_jsonl_proc_script(_mcp_call_events(13)), raw_output=tmp_path / "raw.jsonl", stderr_output=tmp_path / "err.log",
                    agent="claude", arm="B1", protocol="hybrid", max_mcp_calls=12)


def test_b1_twelve_mcp_calls_are_within_the_budget(tmp_path: Path) -> None:
    events = _mcp_call_events(12) + [{"type": "result", "result": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}}]
    usage, _servers, mcp_calls, *_rest = run_command(
        _make_jsonl_proc_script(events), raw_output=tmp_path / "raw.jsonl", stderr_output=tmp_path / "err.log",
        agent="claude", arm="B1", protocol="hybrid", max_mcp_calls=12)
    assert mcp_calls == 12 and usage["output_tokens"] == 1


def test_b1_without_any_mcp_call_is_recorded_when_mcp_is_optional(tmp_path: Path) -> None:
    events = [
        {"type": "system", "subtype": "init", "mcp_servers": [{"name": "tcbench", "status": "connected"}]},
        {"type": "result", "result": "ok", "usage": {"input_tokens": 4, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 7}},
    ]
    kwargs = dict(raw_output=tmp_path / "raw.jsonl", stderr_output=tmp_path / "err.log", agent="claude", arm="B1", protocol="hybrid", max_mcp_calls=12, required_mcp_server="tcbench")
    with pytest.raises(RuntimeError, match="without calling required MCP server"):
        run_command(_make_jsonl_proc_script(events), **kwargs)
    usage, _servers, mcp_calls, *_rest = run_command(_make_jsonl_proc_script(events), mcp_optional=True, **kwargs)
    assert mcp_calls == 0
    # the normalised totals must not be overwritten by the provider's uncached-only ``input_tokens``
    assert usage["input_tokens"] == 104 and usage["uncached_input_tokens"] == 14 and usage["cached_input_tokens"] == 90


def test_matrix_marks_only_the_hybrid_arm_as_mcp_optional() -> None:
    buf, old = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        matrix_main(["--suite", "locate_v2", "--agent", "claude", "--dry-run", "--manifest", str(DEV_MANIFEST), "--max-runs", "6"])
    finally:
        sys.stdout = old
    for record in (json.loads(line) for line in buf.getvalue().strip().splitlines()):
        assert ("--mcp-optional" in record["command"]) == (record["arm"] == "B1")


def test_hung_agent_is_killed_by_the_watchdog(tmp_path: Path) -> None:
    import time

    hang = [sys.executable, "-c", "import time; print('{\"type\": \"system\", \"subtype\": \"init\", \"mcp_servers\": []}', flush=True); time.sleep(60)"]
    started = time.monotonic()
    with pytest.raises(ProtocolViolation, match="timed out after 2"):
        run_command(hang, raw_output=tmp_path / "raw.jsonl", stderr_output=tmp_path / "err.log", agent="claude", arm="B0", protocol="hybrid", timeout_s=2)
    assert time.monotonic() - started < 20


def test_prompt_reaches_the_agent_on_stdin_not_argv(tmp_path: Path) -> None:
    prompt = "Question: where is X?\n" + "y" * 50_000  # far beyond any sane argv limit on Windows
    echo = [sys.executable, "-c", (
        "import json,sys; text=sys.stdin.read(); "
        "print(json.dumps({'type':'result','result':str(len(text)),'usage':{'input_tokens':1,'output_tokens':1}}), flush=True)"
    )]
    telemetry: dict = {}
    run_command(echo, raw_output=tmp_path / "raw.jsonl", stderr_output=tmp_path / "err.log", agent="claude", arm="B0",
                protocol="hybrid", stdin_prompt=prompt, telemetry=telemetry)
    assert telemetry["final_answer"] == str(len(prompt))


def test_claude_command_has_isolation_and_turn_limit() -> None:
    cmd, stdin_text, env = ClaudeAdapter().build_command("B2", "PROMPT", Path("."), extra_config={"mcp_config_path": "m.json", "max_budget_usd": 2})
    assert stdin_text == "PROMPT" and "CLAUDECODE" not in env
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands", "--max-turns", "--max-budget-usd", "--mcp-config"):
        assert flag in cmd
    assert cmd[cmd.index("--max-turns") + 1] == "40"
    b0, *_ = ClaudeAdapter().build_command("B0", "P", Path("."))
    assert "mcp__tcbench" not in b0
    with_model, *_ = ClaudeAdapter().build_command("B0", "P", Path("."), extra_config={"model": "claude-sonnet-5-5", "effort": "medium"})
    assert with_model[with_model.index("--model") + 1] == "claude-sonnet-5-5" and with_model[with_model.index("--effort") + 1] == "medium"


def test_gemini_command_limits_mcp_servers_per_arm() -> None:
    b0, *_ = GeminiAdapter().build_command("B0", "P", Path("."))
    b1, *_ = GeminiAdapter().build_command("B1", "P", Path("."), extra_config={"approval_mode": "default"})
    assert b0[b0.index("--allowed-mcp-server-names") + 1] == "__none__"
    assert b1[b1.index("--allowed-mcp-server-names") + 1] == "tcbench" and b1[b1.index("--approval-mode") + 1] == "default"


def test_normalize_path_keeps_case_and_strips_the_workdir() -> None:
    assert normalize_path("D:\\Repos\\CsvHelper\\src\\CsvHelper\\CsvReader.cs", "d:/repos/csvhelper") == "src/CsvHelper/CsvReader.cs"
    assert normalize_path("./Rich/Syntax.py") == "Rich/Syntax.py"


def test_matrix_run_config_and_resume(tmp_path: Path) -> None:
    usage = tmp_path / "usage.jsonl"
    cfg = tmp_path / "run.json"
    cfg.write_text(json.dumps({"agent_command": ["claude-fake"], "max_turns": 7}), encoding="utf-8")
    args = ["--suite", "locate_v2", "--agent", "claude", "--manifest", str(DEV_MANIFEST), "--run-config", str(cfg), "--usage-output", str(usage), "--dry-run"]
    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        assert matrix_main(args) == 0
    finally:
        sys.stdout = old
    first = json.loads(buf.getvalue().splitlines()[0])
    assert "claude-fake" in " ".join(first["command"]) or first["agent"] == "claude"
    # --resume skips what the usage file already records
    done = {"agent": "claude", "arm": first["arm"], "task_id": first["task_id"], "seed": first["seed"]}
    usage.write_text(json.dumps(done) + "\n", encoding="utf-8")
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert matrix_main(args + ["--resume"]) == 0
    finally:
        sys.stdout = old
    assert len(buf.getvalue().strip().splitlines()) == 119


def test_suite_generator_never_falls_back_from_heldout_to_dev(tmp_path: Path) -> None:
    from evals.c3_locate_suite import build_manifest

    tasks = Path(__file__).resolve().parent.parent / "evals" / "tasks"
    dev = build_manifest(tasks, role="dev")
    assert dev["role"] == "dev" and dev["counted_tasks"] == 20
    assert all(t["repo_id"].startswith("bench-") for t in dev["tasks"] if t["counted"])
    with pytest.raises(FileNotFoundError):  # an empty directory has no held-out files: no silent fallback
        build_manifest(tmp_path, role="heldout")
    unreviewed = tmp_path / "heldout_starlette.json"
    unreviewed.write_text(json.dumps({"reviewed": False, "tasks": [{"id": "t01", "group": "a_keyword", "query": "q"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="not reviewed"):
        build_manifest(tmp_path, role="heldout")
