# Manual Orchestration Recipes (Path A / M1)

This guide provides tested operational recipes for manual orchestration within a single prompt, where a strong coordinator delegates tightly scoped subtasks to economical workers while retaining control over validation and final synthesis.

---

## Recipe R01: One-Prompt Repository Audit

### 1. When to Use
- You want to conduct a multi-faceted audit of a codebase (e.g. evaluating architecture, security, or token efficiency) within an interactive host session.
- Subagents are available in your host environment with configurable role-based model aliases.
- **Anti-pattern**: Spawning unbounded workers that traverse arbitrary files without scope limits or contract expectations.

### 2. Prerequisites
- Verified host platform supporting native subagents (e.g. Codex CLI `0.153.4` or compatible host).
- Mapped model aliases: `MODEL_STRONG` (e.g. Claude 3.7 Sonnet / GPT-4o) and `MODEL_ECONOMY` (e.g. Gemini 1.5 Flash / GPT-4o-mini).
- Token-Context MCP or equivalent read-only codebase retrieval tools connected.

### 3. Inputs & Outputs
- **Input**: User objective specifying repository audit criteria and target directories.
- **Outputs**:
  - Two bounded `WorkerResult` records containing extracted source spans and hashes.
  - One integrated synthesis report produced by the supervisor highlighting verified findings and unresolved items.

### 4. Step-by-Step Procedure
1. **Supervisor Initialization**: Strong parent ingests the user request, formulates the overall audit plan, and checks available budget.
2. **Decomposition & Boundary Framing**: Supervisor carves out at most 2 independent subtasks (e.g. Worker A audits retrieval packing; Worker B audits index freshness).
3. **Dispatch with Scoped Briefs**: Supervisor invokes subagents with minimal context briefs, forbidding recursive subagent spawning.
4. **Execution & Awaiting Results**: Workers execute concurrently (or sequentially if host requires sync calls).
5. **Mechanical Verification**: Supervisor inspects returned file paths, line spans, and content hashes against local files.
6. **Parent Continuation & Synthesis**: Supervisor handles cross-module implications itself and synthesizes the unified final response.

### 5. Concrete Prompt Example (Labeled Illustrative)

```text
You are the primary coordinator operating under MODEL_STRONG.
Objective: Audit token efficiency and index freshness in the token-context-mcp repository.

Operational Rules:
1. If independent subtasks are worth delegating, invoke at most 2 subagents using MODEL_ECONOMY.
2. Subagent 1 (Scope: src/token_context_mcp/retrieve/token_budget.py):
   - Locate how pack_by_budget handles oversized items.
   - Return exact file path, line span, SHA-256 hash, and whether items are dropped or sliced.
3. Subagent 2 (Scope: src/token_context_mcp/index/freshness.py):
   - Locate how file modification time (mtime) and size are validated.
   - Return exact file path, line span, SHA-256 hash, and whether untracked new files are detected.
4. Output Contract for workers: Concise summary, verified evidence refs, checks run, and remaining unknowns.
5. Workers must NOT spawn further subagents and must NOT perform write operations.
6. Await both results, mechanically verify citations against repository files, and synthesize the final audit report yourself.
```

### 6. Result Verification
- Check that worker outputs strictly adhere to `WorkerResult` schema.
- Confirm that citations match actual file paths:
  - `src/token_context_mcp/retrieve/token_budget.py#L18-42`
  - `src/token_context_mcp/index/freshness.py#L25-60`
- Confirm that neither subagent attempted file writes or created child subagents.

### 7. Common Pitfalls & Recovery
- **Pitfall**: Host leaks full conversation transcript to subagents, multiplying input token costs.
  - *Recovery*: Explicitly restrict context in the invocation brief; avoid full-history forking if host allows clean subagent creation.
- **Pitfall**: Worker returns vague assertions without line spans or hashes.
  - *Recovery*: Supervisor rejects the output; if repair is within budget, request one bounded re-extraction specifying line numbers.

### 8. Cost & Risk Profile
- **Token Overhead**: Supervisor initial brief (~1,200 tokens) + 2 Worker calls (~1,500 tokens each) + Supervisor final synthesis (~2,000 tokens) = ~6,200 tokens total.
- **Cost Comparison**: Using `MODEL_ECONOMY` for workers reduces extraction token cost by 80–90% compared to running the entire extraction loop on `MODEL_STRONG`.

### 9. Sources & Version Anchors
- Grounded in `DOC-CODEX-SUBAGENTS` and `LIT-ANTHROPIC-AGENTS` (Orchestrator-Workers pattern).

---

## Recipe R02: Task Too Small / No-Delegate Branch

### 1. When to Use
- The subtask can be resolved using a single deterministic tool call (e.g. counting lines, searching a symbol, filtering JSON) or requires fewer than 200 output tokens.
- **Anti-pattern**: Spawning an economical worker LLM to perform basic string filtering, regex matching, or simple file reading.

### 2. Prerequisites
- Direct access to deterministic tools (e.g. `grep_search`, `find_by_name`, `view_file`, or script runners).

### 3. Inputs & Outputs
- **Input**: A narrow query (e.g. "Find all references to `ServerConfig`").
- **Output**: Structured list of matching occurrences returned directly to the supervisor without subagent invocation.

### 4. Step-by-Step Procedure
1. **Capability Gate Evaluation**: Supervisor checks if the subtask has a known deterministic algorithm.
2. **Short-Circuit Decision**: If yes, bypass subagent creation entirely (`delegate=false`).
3. **Direct Tool Execution**: Execute the local tool directly.
4. **Immediate Ingestion**: Supervisor processes the raw tool output within its own working context.

### 5. Concrete Execution Trace (Labeled Illustrative)

```text
[SUPERVISOR]: Subtask received: "List all Python files defining MCPServer in src/"
[SUPERVISOR DECISION]: Task is purely deterministic lexical discovery. Spawning an LLM worker would introduce ~1,500 token overhead and 3s latency. Triggering no-delegate branch.
[CALL]: grep_search(Query="class MCPServer", SearchPath="src/token_context_mcp/server.py")
[RESULT]: Found 1 match at src/token_context_mcp/server.py:24
[SUPERVISOR]: Verification passed immediately. Continuing synthesis without worker dispatch.
```

### 6. Result Verification
- Ensure `worker_invocations == 0`.
- Verify tool returned non-empty, validated data matching the query.

### 7. Cost & Risk Profile
- **Token Consumption**: 0 worker tokens incurred. Saves ~1,000 to ~3,000 tokens of coordination and agent framing overhead per trivial task.
