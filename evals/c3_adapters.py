"""Normalized event adapters for C3 v2 agent evaluation (M12.5).

Supports three agent harnesses:
1. CodexAdapter: parses `codex exec --json` stream events.
2. ClaudeAdapter: parses `claude -p --output-format stream-json --verbose` stream events.
3. GeminiAdapter: parses `gemini -p --output-format stream-json` stream events.
"""
from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from token_context_mcp.discovery.catalog import TOOL_CATALOG
    TOKEN_CONTEXT_TOOL_NAMES = set(TOOL_CATALOG.keys())
except (ImportError, ModuleNotFoundError):
    TOKEN_CONTEXT_TOOL_NAMES = {
        "list_repositories",
        "get_repo_map",
        "find_symbols",
        "get_module_dependents",
        "search_source",
        "get_file_skeleton",
        "get_symbol_context",
        "get_impact_slice",
        "get_index_status",
        "inspect_symbol",
        "list_available_tools",
        "search_tools",
        "get_tool_schema",
        "memory_put",
        "memory_get",
        "memory_search",
        "memory_lock",
        "memory_unlock",
        "memory_consolidate",
        "sample_summarize",
    }

FORBIDDEN_TOOLS = {
    "edit",
    "write",
    "notebookedit",
    "webfetch",
    "websearch",
    "agent",
    "task",
    "bash",
    "write_file",
    "replace",
    "web_fetch",
    "google_web_search",
    "run_shell_command",
}

NATIVE_READ_TOOLS = {
    "read",
    "grep",
    "glob",
    "ls",
    "read_file",
    "read_many_files",
    "grep_search",
    "search_file_content",
    "list_directory",
}

NEUTRAL_TOOLS = {
    "todowrite",
    "write_todos",
    "think",
    "thought",
}


def classify_tool(tool_name: str, allowed_mcp_servers: set[str] | None = None) -> tuple[str, str]:
    """Classify tool name into category: 'mcp', 'forbidden', 'native_read', or 'neutral'.
    
    Returns (category, normalized_name).
    """
    clean_name = (tool_name or "").strip()
    lower_name = clean_name.lower()

    # Check forbidden tools first
    if lower_name in FORBIDDEN_TOOLS or any(lower_name.endswith(f"__{f}") for f in FORBIDDEN_TOOLS):
        return "forbidden", clean_name

    # Check MCP prefixes
    # Claude: mcp__<server>__<tool>
    # Gemini: mcp_<server>_<tool> or <server>__<tool>
    if clean_name.startswith("mcp__"):
        parts = clean_name.split("__", 2)
        if len(parts) >= 3:
            return "mcp", parts[2]
        return "mcp", clean_name

    if clean_name.startswith("mcp_"):
        parts = clean_name.split("_", 2)
        if len(parts) >= 3:
            return "mcp", parts[2]
        return "mcp", clean_name

    if "__" in clean_name:
        prefix, rest = clean_name.split("__", 1)
        if prefix in (allowed_mcp_servers or {"tcbench", "token-context", "token_context"}):
            return "mcp", rest

    # Check bare MCP tool names
    if clean_name in TOKEN_CONTEXT_TOOL_NAMES or lower_name in {t.lower() for t in TOKEN_CONTEXT_TOOL_NAMES}:
        return "mcp", clean_name

    if lower_name in NEUTRAL_TOOLS:
        return "neutral", clean_name

    if lower_name in NATIVE_READ_TOOLS:
        return "native_read", clean_name

    # Conservative default for unrecognized tools
    return "native_read", clean_name


@dataclass
class ToolCall:
    id: str
    name: str
    category: str  # "mcp" | "native_read" | "neutral" | "forbidden"
    input: Any = None
    server: str | None = None


@dataclass
class ToolResult:
    id: str
    bytes: int
    is_error: bool
    text: str = ""
    error_code: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class AssistantText:
    text: str


@dataclass
class Usage:
    input_total: int
    input_uncached: int
    cached: int
    output: int
    cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Init:
    model: str | None = None
    tools: list[str] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)


NormalizedEvent = ToolCall | ToolResult | AssistantText | Usage | Init


@dataclass
class FinalRecord:
    usage: Usage | None = None
    final_answer: str = ""
    assistant_texts: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    mcp_call_count: int = 0
    native_read_count: int = 0
    forbidden_call_count: int = 0
    mcp_bytes: int = 0
    native_bytes: int = 0
    is_error: bool = False
    error_reason: str | None = None
    init: Init | None = None
    infra_failure: bool = False
    protocol_violation: str | None = None
    mcp_servers_seen: set[str] = field(default_factory=set)


class AgentAdapter(abc.ABC):
    """Abstract interface for C3 agent adapters."""

    def __init__(self, allowed_mcp_servers: set[str] | None = None) -> None:
        self.allowed_mcp_servers = allowed_mcp_servers or {"tcbench", "token-context", "token_context"}
        self.record = FinalRecord()
        self.pending_tool_calls: dict[str, ToolCall] = {}

    @abc.abstractmethod
    def build_command(
        self,
        arm: str,
        prompt_text: str,
        workdir: Path,
        mcp_config: dict[str, Any] | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None, dict[str, str]]:
        """Return (argv, stdin_text, env)."""

    @abc.abstractmethod
    def feed(self, obj: dict[str, Any]) -> list[NormalizedEvent]:
        """Convert one raw JSON event into 0..N normalized events."""

    def final(self) -> FinalRecord:
        """Return finalized run summary record."""
        return self.record


class CodexAdapter(AgentAdapter):
    """Adapter for `codex exec --json`."""

    def build_command(
        self,
        arm: str,
        prompt_text: str,
        workdir: Path,
        mcp_config: dict[str, Any] | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None, dict[str, str]]:
        cmd = [
            "codex",
            "exec",
            "--ephemeral",
            "--json",
            "--sandbox",
            "read-only",
            "--workdir",
            str(workdir),
        ]
        if arm == "B0":
            cmd.extend(["-c", "mcp_servers.token-context.enabled=false"])
        return cmd, prompt_text, {}

    def feed(self, obj: dict[str, Any]) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        ev_type = obj.get("type")

        if ev_type == "turn.completed" and isinstance(obj.get("usage"), dict):
            raw_u = obj["usage"]
            in_tok = int(raw_u.get("input_tokens", 0))
            out_tok = int(raw_u.get("output_tokens", 0))
            cached = int(raw_u.get("cached_tokens", 0))
            usage = Usage(
                input_total=in_tok,
                input_uncached=max(0, in_tok - cached),
                cached=cached,
                output=out_tok,
                cost_usd=None,
                raw=raw_u,
            )
            self.record.usage = usage
            events.append(usage)

        elif ev_type == "item.completed":
            item = obj.get("item")
            if not isinstance(item, dict):
                return events

            item_type = item.get("type")
            if item_type == "command_execution":
                cmd_text = str(item.get("command", ""))
                call = ToolCall(id="cmd", name="command_execution", category="native_read", input=cmd_text)
                self.record.tools_called.append("command_execution")
                self.record.native_read_count += 1
                events.append(call)

                out_str = str(item.get("aggregated_output", ""))
                out_b = len(out_str.encode("utf-8"))
                self.record.native_bytes += out_b
                exit_code = item.get("exit_code", 0)
                res = ToolResult(id="cmd", bytes=out_b, is_error=exit_code != 0, text=out_str)
                events.append(res)

            elif item_type == "mcp_tool_call":
                server = str(item.get("server", "unknown-server"))
                tool = str(item.get("tool", "unknown-tool"))
                self.record.mcp_servers_seen.add(server)
                call_name = f"{server}__{tool}"
                call = ToolCall(id=call_name, name=call_name, category="mcp", input=item.get("arguments"), server=server)
                self.record.tools_called.append(call_name)
                self.record.mcp_call_count += 1
                events.append(call)

                # Mcp error detection
                err = item.get("error")
                err_code = None
                if isinstance(err, dict):
                    err_code = str(err.get("code", "unknown_error"))
                res_obj = item.get("result")
                res_b = len(json.dumps(res_obj).encode("utf-8")) if res_obj is not None else 0
                self.record.mcp_bytes += res_b
                res = ToolResult(id=call_name, bytes=res_b, is_error=err is not None, error_code=err_code)
                events.append(res)

        return events


class ClaudeAdapter(AgentAdapter):
    """Adapter for Claude Code (`claude -p --output-format stream-json --verbose`)."""

    def build_command(
        self,
        arm: str,
        prompt_text: str,
        workdir: Path,
        mcp_config: dict[str, Any] | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None, dict[str, str]]:
        extra = extra_config or {}
        agent_bin = extra.get("agent_command", ["claude"])[0]
        cmd = [
            agent_bin,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--tools",
            "Read,Grep,Glob",
            "--allowedTools",
            "Read,Grep,Glob",
            "--disallowedTools",
            "Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent,Task,Bash",
            "--permission-mode",
            "dontAsk",
            "--disable-slash-commands",
            "--max-turns",
            str(extra.get("max_turns", 40)),
        ]
        if extra.get("max_budget_usd") is not None:
            cmd.extend(["--max-budget-usd", str(extra["max_budget_usd"])])
        if arm in {"B1", "B2"}:
            cmd.extend(["--allowedTools", "mcp__tcbench"])
        if extra.get("model"):
            cmd.extend(["--model", str(extra["model"])])
        if extra.get("mcp_config_path"):
            cmd.extend(["--mcp-config", str(extra["mcp_config_path"])])
        env = dict(extra.get("env", {}))
        env.pop("CLAUDECODE", None)
        return cmd, prompt_text, env

    def feed(self, obj: dict[str, Any]) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        ev_type = obj.get("type")

        if ev_type == "system" and obj.get("subtype") == "init":
            init_ev = Init(
                model=obj.get("model"),
                tools=obj.get("tools", []),
                mcp_servers=obj.get("mcp_servers", []),
            )
            self.record.init = init_ev
            for s in init_ev.mcp_servers:
                if isinstance(s, dict) and s.get("name"):
                    self.record.mcp_servers_seen.add(s["name"])
            events.append(init_ev)

        elif ev_type == "assistant":
            msg = obj.get("message", {})
            for block in msg.get("content", []):
                if not isinstance(block, dict):
                    continue
                b_type = block.get("type")
                if b_type == "tool_use":
                    t_id = str(block.get("id", ""))
                    t_name = str(block.get("name", ""))
                    cat, norm_name = classify_tool(t_name, self.allowed_mcp_servers)
                    call = ToolCall(id=t_id, name=norm_name, category=cat, input=block.get("input"))
                    self.record.tools_called.append(norm_name)
                    if cat == "mcp":
                        self.record.mcp_call_count += 1
                        self.record.mcp_servers_seen.add("tcbench")
                    elif cat == "native_read":
                        self.record.native_read_count += 1
                    elif cat == "forbidden":
                        self.record.forbidden_call_count += 1
                    self.pending_tool_calls[t_id] = call
                    events.append(call)

                elif b_type == "text":
                    txt = str(block.get("text", ""))
                    self.record.assistant_texts.append(txt)
                    events.append(AssistantText(text=txt))

        elif ev_type == "user":
            msg = obj.get("message", {})
            for block in msg.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                t_id = str(block.get("tool_use_id", ""))
                is_err = bool(block.get("is_error", False))
                raw_c = block.get("content", "")
                if isinstance(raw_c, list):
                    txt = "".join(str(b.get("text", "")) for b in raw_c if isinstance(b, dict))
                else:
                    txt = str(raw_c)

                b_len = len(txt.encode("utf-8"))
                call = self.pending_tool_calls.get(t_id)
                if call and call.category == "mcp":
                    self.record.mcp_bytes += b_len
                elif call and call.category == "native_read":
                    self.record.native_bytes += b_len

                res = ToolResult(id=t_id, bytes=b_len, is_error=is_err, text=txt)
                events.append(res)

        elif ev_type == "result":
            res_str = str(obj.get("result", ""))
            self.record.final_answer = res_str
            raw_u = obj.get("usage", {})
            in_tok = int(raw_u.get("input_tokens", 0))
            cache_create = int(raw_u.get("cache_creation_input_tokens", 0))
            cache_read = int(raw_u.get("cache_read_input_tokens", 0))
            out_tok = int(raw_u.get("output_tokens", 0))
            total_in = in_tok + cache_create + cache_read
            cost = obj.get("total_cost_usd")

            usage = Usage(
                input_total=total_in,
                input_uncached=in_tok + cache_create,
                cached=cache_read,
                output=out_tok,
                cost_usd=float(cost) if cost is not None else None,
                raw=raw_u,
            )
            self.record.usage = usage
            events.append(usage)

        return events


class GeminiAdapter(AgentAdapter):
    """Adapter for Gemini CLI (`gemini -p ... --output-format stream-json`)."""

    def build_command(
        self,
        arm: str,
        prompt_text: str,
        workdir: Path,
        mcp_config: dict[str, Any] | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> tuple[list[str], str | None, dict[str, str]]:
        extra = extra_config or {}
        agent_bin = extra.get("agent_command", ["gemini"])
        cmd = list(agent_bin)
        cmd.extend(["-p", " ", "--output-format", "stream-json"])
        # Headless Gemini CLI denies any tool that needs confirmation.  MCP tools need confirmation unless the server
        # is marked ``"trust": true`` in the Gemini settings; set that (or pass ``approval_mode`` here) and verify
        # with the probe task before a matrix run (docs: evals/c3_protocol_v2.md, "Gemini").
        if extra.get("approval_mode"):
            cmd.extend(["--approval-mode", str(extra["approval_mode"])])
        if arm in {"B1", "B2"}:
            cmd.extend(["--allowed-mcp-server-names", "tcbench"])
        elif arm == "B0":
            cmd.extend(["--allowed-mcp-server-names", "__none__"])
        env = dict(extra.get("env", {}))
        return cmd, prompt_text, env

    def feed(self, obj: dict[str, Any]) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        ev_type = obj.get("type")

        if ev_type == "init":
            init_ev = Init(
                model=obj.get("model"),
                tools=obj.get("tools", []),
                mcp_servers=[],
            )
            self.record.init = init_ev
            events.append(init_ev)

        elif ev_type in {"tool_use", "tool_call"}:
            t_id = str(obj.get("tool_id", "") or obj.get("id", ""))
            t_name = str(obj.get("tool_name", "") or obj.get("tool", "") or obj.get("name", ""))
            cat, norm_name = classify_tool(t_name, self.allowed_mcp_servers)
            call = ToolCall(id=t_id, name=norm_name, category=cat, input=obj.get("parameters") or obj.get("input"))
            self.record.tools_called.append(norm_name)
            if cat == "mcp":
                self.record.mcp_call_count += 1
                self.record.mcp_servers_seen.add("tcbench")
            elif cat == "native_read":
                self.record.native_read_count += 1
            elif cat == "forbidden":
                self.record.forbidden_call_count += 1
            self.pending_tool_calls[t_id] = call
            events.append(call)

        elif ev_type == "tool_result":
            t_id = str(obj.get("tool_id", "") or obj.get("id", ""))
            status = obj.get("status")
            err = obj.get("error")
            is_err = status == "error" or bool(err)
            out_c = obj.get("output", "") or obj.get("result", "") or err or ""
            txt = str(out_c)
            b_len = len(txt.encode("utf-8"))

            call = self.pending_tool_calls.get(t_id)
            if call and call.category == "mcp":
                self.record.mcp_bytes += b_len
            elif call and call.category == "native_read":
                self.record.native_bytes += b_len

            res = ToolResult(id=t_id, bytes=b_len, is_error=is_err, text=txt)
            events.append(res)

        elif ev_type == "message" and obj.get("role") == "assistant":
            txt = str(obj.get("content", "") or obj.get("delta", ""))
            if txt:
                self.record.assistant_texts.append(txt)
                events.append(AssistantText(text=txt))

        elif ev_type == "result":
            stats = obj.get("stats", {})
            in_tok = int(stats.get("input_tokens", 0))
            cached = int(stats.get("cached", 0))
            out_tok = int(stats.get("output_tokens", 0))
            input_uncached = int(stats.get("input", max(0, in_tok - cached)))

            raw_stats = dict(stats)
            if stats.get("input") is not None and in_tok != (int(stats["input"]) + cached):
                raw_stats["usage_semantics_warning"] = (
                    f"input_tokens ({in_tok}) != input ({stats.get('input')}) + cached ({cached})"
                )

            usage = Usage(
                input_total=in_tok,
                input_uncached=input_uncached,
                cached=cached,
                output=out_tok,
                cost_usd=None,
                raw=raw_stats,
            )
            self.record.usage = usage
            res_content = str(obj.get("content", "") or obj.get("result", ""))
            if res_content and not self.record.assistant_texts:
                self.record.assistant_texts.append(res_content)
            self.record.final_answer = "\n".join(self.record.assistant_texts)
            events.append(usage)

        return events


def get_adapter(agent: str, allowed_mcp_servers: set[str] | None = None) -> AgentAdapter:
    """Factory function for AgentAdapter."""
    ag = (agent or "codex").lower()
    if ag == "claude":
        return ClaudeAdapter(allowed_mcp_servers)
    elif ag == "gemini":
        return GeminiAdapter(allowed_mcp_servers)
    elif ag == "codex":
        return CodexAdapter(allowed_mcp_servers)
    raise ValueError(f"Unknown agent: {agent}")
