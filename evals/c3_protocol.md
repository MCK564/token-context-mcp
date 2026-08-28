# C3 protocol (X4)

Status: fixed before the X6 matrix. Date: 2026-08-28.

## Scope and pairing

The matrix uses the registered `invoice-scanner` repository and the frozen
prompts in `evals/c3_prompts.json` for every arm and seed. Each B0/B1/B2 triplet must use the
same model, prompt bytes, working tree, tool permissions, and seed. The
runner's `prompt_sha256` is the pairing key; a missing or mismatched hash is a
protocol failure, not a benchmark result.

The task prompts are intentionally arm-neutral: they say to use token-context
when available, so disabling the server produces the native baseline without
changing prompt bytes. T3 fixes the target symbol as `extract_with_trace`, and
T4 fixes the requested module as `src/invoice_backend/s9_fields.py`; this
removes the placeholders from the earlier remediation document.

The matrix is 5 tasks × 3 seeds × 3 arms = 45 runs:

| Arm | Protocol | Native commands | MCP calls |
|---|---|---:|---:|
| B0 | native-only | unrestricted read-only | 0 |
| B1 | hybrid | unrestricted read-only | max 12 |
| B2 | mcp-first | at most 1 read-only verification command, and only after MCP | max 12 |

B1 measures the behavior of a real hybrid agent. B2 is the bounded retrieval
protocol and measures whether MCP can replace broad native discovery. A run
that violates its protocol or receives an MCP error is failed before provider
usage is recorded.

## Metrics

The primary metric is `retrieved_content_estimated_tokens`, the local
`utf8-bytes / 4` estimate of native command output plus MCP result payloads.
It measures retrieved context rather than conversation length.

Secondary metrics are `uncached_input_tokens`, provider-reported
`total_tokens`, `output_tokens`, latency, MCP call count, and task success.
`cached_input_tokens` is reported separately and is not interpreted as newly
retrieved repository context. Token-saving claims use paired reductions,
sample size, and the deterministic bootstrap CI95 from `benchmark-report`.

## Predeclared quality grader

Quality is graded independently of token counts, after each answer is
captured but before aggregate cost results are inspected:

| Task | Pass condition |
|---|---|
| T1 orientation | Names at least five real top-level modules, gives no invented module, and reports the essential-symbol score from `orientation_invoice_scanner.json`; essential recall must be ≥0.833 and grade-0 noise in the named top-10 must be 0. |
| T2 locate | Gives the real post-processing symbol/path and a line within ±10 lines of the indexed definition. |
| T3 impact | Names at least one true caller, labels the result as a candidate lexical graph, and does not claim complete semantic coverage. |
| T4 surface | Lists every public definition in the requested module, omits private definitions, and contains signatures without function bodies. |
| T5 trace | Names at least three real pipeline stages in source order from input to stored result, with source-backed paths or symbols. |

Any failed quality criterion means the run does not support a saving claim,
even when its token count is lower. MCP errors, stale-index use, or missing
source evidence are also quality failures.

## Execution gate

Run X6 only after this file is present and unchanged. Use
`evals/run_c3_matrix.py` with `evals/c3_prompts.json` to enumerate all 45
attempts; it delegates each arm to `evals/run_c3.py`. Use
`--require-mcp-server token-context` for B1
and B2, `--protocol hybrid` for B1, `--protocol mcp-first` for B2, and
`--max-mcp-calls 12` for both MCP arms. Feed only successful, paired records
to `benchmark-report`; report the primary metric explicitly beside the
legacy total-token statistic.

The matrix command requires an explicit `--task-success true|false`. Grade
the captured answers against the table above before choosing that value; a
successful process exit alone is not a quality pass.
