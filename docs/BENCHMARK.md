# Benchmark protocol

The harness reads JSONL records with:

```json
{"arm":"B0","task_id":"architecture-01","seed":1,"input_tokens":1000,"output_tokens":200,"total_tokens":1200,"latency_seconds":2.1,"task_success":true}
```

Run:

```powershell
uv run token-context benchmark-report --input evals/sample-runs.jsonl --output evals/reports/sample-summary.json
```

The report calculates paired median total-token reduction and a deterministic bootstrap interval. It does not contact a provider and cannot turn local byte estimates into a billing claim.

For the deterministic context-only comparisons (C1/C2), run:

```powershell
uv run python evals/measure_context_cost.py `
  --repo-id token-context `
  --config $env:APPDATA\token-context-mcp\repos.toml `
  --output evals/reports/c1-token-context-x1.json
```

This records both the naive source-read baseline and the serialized payload
received from each retrieval tool, including whether any call exceeds the
configured `max_result_tokens` cap. The X1 reports cover `token-context` and
`invoice-scanner`; they are local `utf8 bytes / 4` estimates, not provider
usage. C3 requires paired agent runs with provider-reported token counts.

## C3 tool-health gate

Run every instrumented C3 arm through `evals/run_c3.py`. It streams Codex JSONL,
terminates the agent as soon as an MCP tool returns an `error` envelope, and
only then appends a provider-usage record. `benchmark-report` also rejects any
record declaring MCP errors.

```powershell
uv run --no-sync python evals/run_c3.py `
  --arm B1 --task-id T2-locate --seed 1 --task-success true --prompt-sha256 <same-hash-as-B0> `
  --raw-output evals/runs/c3/B1-T2.jsonl `
  --stderr-output evals/runs/c3/B1-T2.stderr.log `
  --usage-output evals/reports/c3-runs.jsonl `
  --require-mcp-server token-context `
  -- codex exec --ephemeral --json --color never --sandbox danger-full-access --skip-git-repo-check `
  -C D:\AI\bench\invoice-scanner-frozen "<same prompt used by B0>"
```

Record `cached_input_tokens` separately. It is cache replay, not newly supplied
repository context, and can otherwise dominate a one-turn provider comparison.
The runner also records native command output using the clearly labelled local
`utf8-bytes-div-4-v1` estimate, so a competent-native baseline can sit beside
the naive full-source C1 upper bound without being mistaken for provider usage.
For MCP arms it separately records `mcp_result_output_estimated_tokens` and
`retrieved_content_estimated_tokens` (native output plus MCP result output);
compare the latter when measuring retrieved content across arms.

For a publishable result, run the paired B0/B1/B2 matrix defined in
[`evals/c3_protocol.md`](../evals/c3_protocol.md): 5 tasks × 3 seeds × 3 arms. Use the
same model, prompt bytes, tool permissions and working tree, collect provider
`input_tokens`, `output_tokens`, cache and cost fields, and apply the declared
quality gate before aggregating savings.

## Hybrid and MCP-first protocols

The C3 runner accepts `--protocol hybrid` (the B1 behavior) or
`--protocol mcp-first` (B2). MCP-first requires a successful MCP call before
native verification and rejects a second native command in the same task.
Both protocols record `verification_triggers`, including warnings returned by
the most recent MCP call before each native command.

Use `--max-mcp-calls N` to make the retrieval budget explicit for a C3 arm. The
runner rejects the run before writing provider usage when the agent exceeds
that call budget; this prevents an ostensibly MCP-first prompt from turning
into an unbounded sequence of follow-up lookups.

## M10 — public retrieval benchmark

Positioning: **evidence-first, local-first code context.** This benchmark answers one narrow question without a model in the loop: *for the same query, how much of the right code does token-context put in front of an agent compared with grep, and at what token cost?*

**Repository (pinned).** `Textualize/rich` v15.0.0, commit `6ac483cbea39cab124dfd3483bba70ffafb71050`, MIT, 532 files in the index (`bench-rich`, of which the Python sources form the search corpus). It is public, was never used to tune token-context, and is chosen for its size (Python sources within the 80–600 file window). No JS/TS repository was benchmarked.

**Tasks.** `evals/tasks/bench_rich.json`: 30 locate tasks (10 `a_keyword`, 10 `b_hidden_dep` whose query avoids the target name, 10 `c_multi_file`) and 10 packet tasks. Every task is a test task: nothing is tuned on them. Every gold item was found in the index and its body read (`evals/out/m10/bench_rich_gold_verification.json`). The set was written by one Claude session and must be reviewed by the repo owner or by a different Claude session before any number is produced: `bench_retrieval.py` refuses to run while `reviewed` is not `true`.

**Arms** (same machine, same index, same queries; corpus = files of the index with `parse_status` starting with `parsed`):

| Arm | What it is |
|---|---|
| `R0-grep` | Python re-implementation of `rg -n -C 2`: identifier parts of the query (≥3 chars) as whole-word, case-insensitive terms; files ranked by Σ idf; top 10 files, ≤200 lines each |
| `R0-grep@R2` | `R0-grep` output cut by whole lines, in rank order, to the wire tokens of `R2` on the same task (equal-cost comparison) |
| `R0-read` | the first 5 files of `R0-grep` read whole |
| `R1` | `search_source(expand="none")`, 2,048 tokens |
| `R2` | `search_source(profile="locate")` (graph expansion) |
| `R3` | `inspect_symbol(view="full", budget_tokens=4096)` on the packet tasks versus reading the files |

**Metrics.** File Acc@5, File MRR, Symbol Recall@10, Symbol MRR, wire tokens (`utf8-bytes-div-4-v1`), latency p50/p95 (5 runs, first discarded); for R3 `sig_coverage`, `ref_coverage`, `savings_vs_read`. CI95: bootstrap of the mean over tasks (2,000 resamples, seed 0; paired for differences).

**Pre-registered KPIs (soft; the numbers are reported whether or not they are met).** R2 − R0-grep@R2 File Acc@5 ≥ +10 points with a CI95 that excludes 0; R2 within 5 points of unbounded R0-grep; R3 `sig_coverage` ≥ 0.60, `ref_coverage` ≥ 0.80, `savings_vs_read` ≥ 0.70. R2 vs R1 is reported without a threshold.

**Status: waiting for review of the task set.** No benchmark number exists yet, by design. After review:

```
uv run python evals/bench_retrieval.py --tasks <reviewed bench_rich.json> --config <dev repos.toml> --name rich
```

writes `evals/out/m10/bench_rich_<arm>.jsonl` and `bench_rich_summary.json`. The harness and `src/` are frozen at the local tag `m10-freeze` (`git diff m10-freeze -- src evals/bench_retrieval.py` is empty).

**Limits.** `R0` is a simulated baseline, not a real agent: it takes the symbol of its best line from the index (an advantage for R0) and has no reading strategy. Locate tasks measure retrieval, not task success; end-to-end token savings are measured by the C3 matrix above (prepared for `bench-rich`, 45 runs, not executed: it spends provider money). Third-party figures must be listed in [`benchmark_sources.json`](benchmark_sources.json); there are none yet.
