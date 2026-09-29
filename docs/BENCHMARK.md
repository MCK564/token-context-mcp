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

**Tasks.** `evals/tasks/bench_rich.json`: 30 locate tasks (10 `a_keyword`, 10 `b_hidden_dep` whose query avoids the target name, 10 `c_multi_file`) and 10 packet tasks. Every task is a test task: nothing is tuned on them. Every gold item was found in the index and its body read (`evals/out/m10/bench_rich_gold_verification.json`). The set was written by one Claude session and reviewed by the repository owner before any number was produced (`bench_retrieval.py` refuses to run while `reviewed` is not `true`).

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

**Status: results produced (owner-reviewed task set).** The owner confirmed the review on 2026-09-29; the task file was not changed (`reviewed: true`, `tasks_file_sha256 accd46af12eb…`). Run on the 2-core dev VM at `git_head` 86bef29 with the harness frozen at `m10-freeze`; raw records and summary: `evals/out/m10/bench_rich_*.jsonl`, `bench_rich_summary.json`. Index run `run_20260929T075303Z_51e099b5`, schema 2.4, 213 corpus files, 30 locate tasks and 10 packet tasks, tokens = `utf8-bytes-div-4-v1`.

### Locate tasks (30)

| Arm | File Acc@5 (CI95) | Symbol Recall@10 (CI95) | Mean wire tokens | Latency p50 (ms) |
|---|---|---|---:|---:|
| `R0-grep` (unbounded grep simulation) | 0.93 [0.83, 1.00] | 0.22 [0.09, 0.38] | 17,553 | 180 |
| `R0-grep@R2` (grep cut to R2's tokens) | 0.57 [0.40, 0.73] | 0.10 [0.00, 0.20] | 1,878 | 180 |
| `R0-read` (5 files read whole) | 0.93 [0.83, 1.00] | 0.22 [0.09, 0.38] | 48,243 | 180 |
| `R1` `search_source(expand="none")` | 0.97 [0.90, 1.00] | 0.52 [0.34, 0.69] | 1,897 | 22 |
| `R2` `search_source(profile="locate")` | 0.90 [0.80, 1.00] | 0.54 [0.37, 0.71] | 1,886 | 24 |

By group (means only; 10 tasks per group, so the intervals are wide, see the summary file):

| Group | Arm | File Acc@5 | Symbol Recall@10 | Mean wire tokens |
|---|---|---|---|---:|
| a_keyword | R0-grep | 1.00 | 0.60 | 16,252 |
| a_keyword | R0-grep@R2 | 0.70 | 0.30 | 1,888 |
| a_keyword | R1 | 1.00 | 0.90 | 1,890 |
| a_keyword | R2 | 1.00 | 0.80 | 1,895 |
| b_hidden_dep | R0-grep | 0.80 | 0.00 | 16,311 |
| b_hidden_dep | R0-grep@R2 | 0.30 | 0.00 | 1,875 |
| b_hidden_dep | R1 | 0.90 | 0.50 | 1,907 |
| b_hidden_dep | R2 | 0.90 | 0.50 | 1,885 |
| c_multi_file | R0-grep | 1.00 | 0.07 | 20,096 |
| c_multi_file | R0-grep@R2 | 0.70 | 0.00 | 1,871 |
| c_multi_file | R1 | 1.00 | 0.17 | 1,893 |
| c_multi_file | R2 | 0.80 | 0.33 | 1,878 |

### Packet tasks (10), `inspect_symbol(view="full", budget_tokens=4096)` versus reading the files (R3)

`sig_coverage` 0.983 [0.95, 1.00], `ref_coverage` 0.983 [0.95, 1.00], `reach_ceiling` 1.00, `savings_vs_read` 0.915 [0.89, 0.93] (2,204 wire tokens against 26,644 to read the files), `body_coverage` 0.00 (by design: a packet carries signatures of neighbours, not their bodies). 0 errors.

### Pre-registered KPIs

| KPI | Result | Threshold | Met |
|---|---|---|---|
| R2 − `R0-grep@R2` File Acc@5 (same cost) | +0.333 [0.13, 0.53] | ≥ +0.10, CI excludes 0 | yes |
| R2 − unbounded `R0-grep` File Acc@5 | -0.033 [-0.17, 0.07] | ≥ −0.05 | yes on the mean; the CI reaches −0.167 |
| R3 `sig_coverage` | 0.983 | ≥ 0.60 | yes |
| R3 `ref_coverage` | 0.983 | ≥ 0.80 | yes |
| R3 `savings_vs_read` | 0.915 | ≥ 0.70 | yes |
| R2 vs R1 (no threshold) | File Acc@5 -0.067 [-0.17, 0.00]; Symbol Recall@10 +0.022 [-0.10, 0.14] | report only | n/a |

R2 puts 0.107 of the tokens of unbounded `R0-grep` in front of the agent (about 89 % fewer) for a File Acc@5 that is 3 points lower on the mean.

### How to read this

- At equal cost (about 1.9k tokens) token-context finds the right file far more often than grep cut to the same size (0.90 against 0.57), and it returns the right *symbol* (Recall@10 0.54 against 0.10), which grep cannot name.
- Unbounded grep has the highest File Acc@5 on the `c_multi_file` group (1.00 against 0.80 for R2) and reads 9 times more tokens (17.6k against 1.9k on average). `b_hidden_dep` (query without the target's name) is where lexical grep fails at symbol level (Recall@10 0.00 against 0.50).
- **The graph expansion of R2 did not beat plain FTS (R1) on this set**: File Acc@5 0.90 against 0.97 (paired difference −0.067, CI [−0.167, 0.000]), Symbol Recall@10 about equal. The expansion costs nothing in tokens but did not help here.
- The packet (R3) gives about 92 % fewer tokens than reading the files while covering 98 % of the gold neighbour signatures and references.

### Limits

One Python repository (`rich`), 30 + 10 tasks written by one Claude session and reviewed by the owner, so the intervals are wide and group-level differences are indicative only. `R0` is a Python simulation of `rg -n -C 2` (its latency is not that of `rg`) that takes the symbol of its best line from the index, which favours R0. Locate tasks measure retrieval, not task success; end-to-end savings are measured only by the C3 matrix (not run for `bench-rich`). No third-party figures are used (`benchmark_sources.json` stays empty). No JS/TS or Go repository was benchmarked.

Reproduce with:

```
uv run python evals/bench_retrieval.py --tasks evals/tasks/bench_rich.json --config <dev repos.toml> --name rich
```

The harness and the retrieval code in `src/` are frozen at the local tag `m10-freeze` (after it only `gui/main.py` changed, for the GUI install hint).


## M11 — second language: TypeScript (`honojs/hono`)

Same harness, same arms, same pre-registered KPIs as the `rich` benchmark above, run on a TypeScript repository so that the result does not rest on Python alone.

**Repository (pinned).** `honojs/hono` v4.9.9, commit `16eb88269ffb0ae68590ad55ac9ac58807850f26`, MIT, 359 corpus files. The index reports an ambiguous-edge rate of 45 % for this repository (Python repositories: about 2–10 %), which matters for the packet result below.

**Tasks.** `evals/tasks/bench_hono.json`: 30 locate tasks (10 per group) and 10 packet tasks. **Review status: written by one Claude session and reviewed by a different Claude session, not by the repository owner.** The reviewer read every gold symbol in the source and changed 8 of 40 tasks (log: `evals/out/m11/bench_hono_review_log.md`); no retrieval tool was used to write or review them. After the first run aborted on a 205-character query (the tool accepts at most 200), the coordinator shortened that one query before any result had been seen. The owner has not reviewed this set, so treat these numbers as one notch less firm than the `rich` ones.

Raw records and summary: `evals/out/m11/bench_hono_*`. Reproduce with `uv run python evals/bench_retrieval.py --tasks evals/tasks/bench_hono.json --config <dev repos.toml> --name hono --out-dir evals/out/m11`.

### Locate tasks (30)

| Arm | File Acc@5 (CI95) | Symbol Recall@10 (CI95) | Mean wire tokens | Latency p50 (ms) |
|---|---|---|---:|---:|
| `R0-grep` (unbounded) | 0.63 [0.43, 0.80] | 0.13 [0.03, 0.25] | 20,934 | 445 |
| `R0-grep@R2` (cut to R2's tokens) | 0.23 [0.10, 0.40] | 0.01 [0.00, 0.03] | 1,877 | 445 |
| `R0-read` (5 files whole) | 0.63 [0.43, 0.80] | 0.09 [0.01, 0.19] | 35,325 | 445 |
| `R1` `search_source(expand="none")` | 0.80 [0.63, 0.93] | 0.55 [0.39, 0.71] | 1,878 | 23 |
| `R2` `search_source(profile="locate")` | 0.80 [0.63, 0.93] | 0.66 [0.50, 0.81] | 1,888 | 25 |

By group (means only; 10 tasks per group):

| Group | Arm | File Acc@5 | Symbol Recall@10 | Mean wire tokens |
|---|---|---|---|---:|
| a_keyword | R0-grep | 0.70 | 0.20 | 22,560 |
| a_keyword | R0-grep@R2 | 0.10 | 0.00 | 1,891 |
| a_keyword | R1 | 0.80 | 0.70 | 1,887 |
| a_keyword | R2 | 0.80 | 0.80 | 1,899 |
| b_hidden_dep | R0-grep | 0.50 | 0.10 | 19,551 |
| b_hidden_dep | R0-grep@R2 | 0.30 | 0.00 | 1,872 |
| b_hidden_dep | R1 | 0.80 | 0.50 | 1,868 |
| b_hidden_dep | R2 | 0.80 | 0.70 | 1,886 |
| c_multi_file | R0-grep | 0.70 | 0.08 | 20,692 |
| c_multi_file | R0-grep@R2 | 0.30 | 0.03 | 1,867 |
| c_multi_file | R1 | 0.80 | 0.46 | 1,880 |
| c_multi_file | R2 | 0.80 | 0.49 | 1,877 |

### Packet tasks (10)

`sig_coverage` 0.575 [0.41, 0.74], `ref_coverage` 0.575 [0.41, 0.74], `reach_ceiling` 0.575, `savings_vs_read` 0.569 [0.45, 0.69] (1,238 wire tokens against 4,124 to read the files).

### Pre-registered KPIs

| KPI | Result | Threshold | Met |
|---|---|---|---|
| R2 − `R0-grep@R2` File Acc@5 (same cost) | +0.567 [0.40, 0.73] | ≥ +0.10, CI excludes 0 | yes |
| R2 − unbounded `R0-grep` File Acc@5 | +0.167 [0.00, 0.33] | ≥ −0.05 | yes |
| R3 `sig_coverage` | 0.575 | ≥ 0.60 | **no** |
| R3 `ref_coverage` | 0.575 | ≥ 0.80 | **no** |
| R3 `savings_vs_read` | 0.569 | ≥ 0.70 | **no** |
| R2 vs R1 (no threshold) | File Acc@5 +0.000; Symbol Recall@10 +0.111 [0.01, 0.23] | report only | n/a |

### How to read this

- **Locating works on TypeScript too.** At equal cost (about 1.9k tokens) R2 finds the right file in 80 % of tasks against 23 % for grep cut to the same size, and unbounded grep, which reads about 11 times more tokens (20,934 against 1,888), reaches only 63 %. Symbol Recall@10 is 0.66 against 0.13 for grep.
- **Graph expansion helps here.** Unlike `rich`, R2 beats R1 on symbols (+0.11, CI95 excludes 0) at the same File Acc@5. One repository per language cannot say whether that is a language effect.
- **The packet does not meet its targets on TypeScript.** Coverage (0.57) equals the reach ceiling (0.57): the packet returns what the call graph reaches, and 21 of the 48 gold neighbours (type definitions such as `Context` and `HTTPException`, callers through re-exports and adapters) are not reachable by the graph, because call edges are heavily ambiguous in this repository. The saving against reading is also smaller (0.57) because Hono's files are short. On Python (`rich`) the same KPIs were met (0.98 / 0.98 / 0.91).

### Limits

One repository, 30 + 10 tasks, wide intervals, a simulated grep baseline (its latency is not that of `rg`), retrieval only. The task set was reviewed by another Claude session but not by the owner. There is still no end-to-end (C3) measurement.
