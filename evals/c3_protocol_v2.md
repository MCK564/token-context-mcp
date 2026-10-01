# C3 Protocol v2: Multi-Agent Benchmark (Claude Code, Gemini CLI, Codex)

**Status:** Predeclared and frozen for M12.5.  
**Date:** 2026-10-01.  
**Harness:** `evals/run_c3.py`, `evals/run_c3_matrix.py`, `evals/c3_report.py`.  
**Suite:** `locate_v2` (`evals/c3/locate_v2_manifest.json`).

---

## 1. Scope & Multi-Agent Harnesses

C3 v2 extends the single-agent Codex benchmark to industry-standard agent CLIs:
1. **Claude Code (`claude`):** Run via `claude -p --output-format stream-json --verbose` with `--strict-mcp-config` and strict tool control (`--tools Read,Grep,Glob`, `--disallowedTools Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent,Task,Bash`).
2. **Gemini CLI (`gemini`):** Run via `gemini -p ... --output-format stream-json` with explicit allowed MCP server filtering (`--allowed-mcp-server-names tcbench` on B1/B2, `__none__` on B0).
3. **Codex CLI (`codex`):** Run via `codex exec --ephemeral --json --sandbox read-only`.

Normalized event adapters (`evals/c3_adapters.py`) parse streaming JSONL into standard dataclasses (`Init`, `ToolCall`, `ToolResult`, `AssistantText`, `Usage`).

---

## 2. Benchmark Suite: `locate_v2`

The benchmark suite consists of 20 counted code-location tasks across 4 open-source repositories spanning 4 programming languages:
- **Python:** `encode/starlette` (baseline fallback: `Textualize/rich`)
- **TypeScript:** `colinhacks/zod` (baseline fallback: `honojs/hono`)
- **JavaScript:** `expressjs/express` (baseline fallback: `fastify/fastify`)
- **C#:** `serilog/serilog` (baseline fallback: `CsvHelper/CsvHelper`)

Each repository contributes exactly 5 tasks selected deterministically (seed `20261001`) from three structural retrieval archetypes:
- **Group a (`a_keyword`):** 1 task per repo (symbol name or exact keyword present in query).
- **Group b (`b_hidden_dep`):** 2 tasks per repo (conceptual query avoiding identifier names; requires dependency or call analysis).
- **Group c (`c_multi_file`):** 2 tasks per repo (cross-module implementation spanning multiple related files).
- **Probe task:** 1 uncounted probe task (`counted: false`) to verify harness connectivity and health without impacting benchmark score.

### Experimental Matrix (120 Runs per Agent)
- **Arms:** 3 arms (`B0`, `B1`, `B2`).
- **Seeds:** 2 seeds (`1`, `2`).
- **Total runs per agent:** 20 counted tasks × 3 arms × 2 seeds = **120 runs**.
- **Deterministic arm order shuffling:** To eliminate systematic cache or warm-up order bias, arms are permuted pseudo-randomly per `(task, seed)` using deterministic seed `20261001`.

---

## 3. Arm Rules & Execution Gate

| Arm | Protocol | MCP Calls | Native Commands | Pass Rule |
|---|---|---:|---:|---|
| **B0** (Native) | `hybrid` | **0** (Strictly forbidden) | Unrestricted read-only | Any MCP call aborts run with `InfraFailure` |
| **B1** (Hybrid) | `hybrid` | ≤ 12 | Unrestricted read-only | Standard tool-use; MCP error envelopes abort run |
| **B2** (MCP-first) | `mcp-first` | ≤ 12 | At most **1** read-only command, **only after** successful MCP call | Native before MCP or >1 native command aborts with `ProtocolViolation` |

### Guarded Safety Constraints
- **Zero-Mutation:** Any call to `Edit`, `Write`, `NotebookEdit`, `Bash`, `write_file`, or shell execution aborts the run with `ProtocolViolation`.
- **Tool-Health Gate:** If `tcbench` fails to connect on agent initialization or returns an error envelope, the run fails immediately with `InfraFailure` before recording provider usage.

---

## 4. Automated Grading & Quality Gate

Agents must terminate their response with a fenced JSON block:
```json
{
  "files": ["<repo-relative path>", "..."],
  "symbols": [{"path": "<repo-relative path>", "name": "<Class.method or function name>"}]
}
```

Grading rules (`evals/c3_grade.py`):
1. **Group a & b:** `task_success = True` if at least 1 gold file is listed in the top 3 files.
2. **Group c:** `task_success = True` if file recall in the top 5 files is ≥ 0.50 (at least half of implementation files identified).
3. **Parse failure:** If the agent fails to output a valid fenced JSON block, `task_success = False` with `error = "answer_parse_error"`.
4. **Probe task:** Always marked `task_success = True` and excluded from reported accuracy and token statistics.

---

## 5. Metrics & Statistical Reporting

- **Primary Metric:** `retrieved_content_estimated_tokens` (`utf8-bytes / 4`), measuring repository content actually retrieved across tools.
- **Secondary Metrics:** Provider `total_tokens`, `input_tokens`, `output_tokens`, `cached_input_tokens`, `latency_seconds`, and `task_success`.
- **Statistical Inference:**
  - 95% Confidence Intervals via deterministic bootstrap (2,000 resamples, seed `20261001`).
  - Paired reductions: paired difference for B1 vs B0, B2 vs B0, and B2 vs B1 across matching `(task_id, seed)` runs.
- **Reporting Harness:** `evals/c3_report.py` aggregates logs, generates markdown tables, and flags protocol violation rates.

---

## 6. Record of the M12 acceptance run (what was actually executed)

Added after the run; sections 1–5 are unchanged except where stated here.

- **Agent and model:** Claude Code (`claude -p`, headless) with `--model claude-sonnet-5-5 --effort medium --max-turns 30`, tools restricted to `Read,Grep,Glob` (`--tools`), `--strict-mcp-config`, `--permission-mode dontAsk`. Opus was not used (rate-limit budget). Gemini CLI was not installed in the run environment and Codex was not run, so the "multi-agent" claim of the harness is not exercised: **one agent, one model**.
- **Suite, role and what was NOT run:** the held-out suite (`evals/c3/locate_v2_manifest.json`, role `heldout`: starlette, zod, express, serilog; 20 counted tasks + 1 probe, 3 arms) was run for **seed 1 only (60 of the 120 planned runs)** against the frozen 0.3.0 code and the held-out clones. Seed 2 was not run: the owner stopped further paid runs. The supplementary development suite (`evals/c3/locate_v2_dev_manifest.json`: rich, hono, fastify, CsvHelper; its tasks informed M12 changes, so it was only ever meant as a secondary result) was not run either. Resuming is a matter of `run_c3_matrix.py --seeds 2 --resume` (about 4.6M tokens, US$3, 12 minutes per 60 runs at the measured seed-1 cost).
- **B1 deviation:** with the hybrid protocol the agent never called the MCP server, and the original gate rejected such runs as protocol failures. B1 was therefore run with `--mcp-optional` (the MCP server is available, calls are allowed up to the limit, not required). B1 is "hybrid, MCP optional"; in seed 1 its adoption was **0 of 20 runs**, so B1 behaved like B0. B0 and B2 are unchanged.
- **Usage accounting fix:** the first version of the runner overwrote the normalised `input_tokens` with the provider's uncached count (a handful of tokens when caching is active). Records now carry `input_tokens` (uncached + cache read + cache creation), `uncached_input_tokens`, `cached_input_tokens`, `output_tokens` and `cost_usd`. All reported totals use the fixed fields.
- **Ceiling effect:** all three arms solved every counted task in seed 1 (see `docs/BENCHMARK.md`, M12), so success rate does not discriminate; only token and latency differences are informative. The four held-out repositories are well-known public projects, so a model may answer part of the tasks from memory (contamination is possible and not measured).
- **Per-run overhead:** every Claude Code run carries a fixed system/tool prompt of roughly 25 000 cached input tokens; this dominates `total_tokens` and is why `retrieved_content_estimated_tokens` is the primary metric.
