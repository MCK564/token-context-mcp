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

**Repository (pinned).** `honojs/hono` v4.9.9, commit `16eb88269ffb0ae68590ad55ac9ac58807850f26`, MIT, 359 corpus files. The index reports an ambiguous-edge rate of 45 % for this repository (`rich` (Python): 17 %), which matters for the packet result below.

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


## M11 (continued) — JavaScript (`fastify`) and C# (`CsvHelper`), and a four-language comparison

Same harness, arms and pre-registered KPIs. Both task sets follow the `hono` procedure: **written by one Claude session and reviewed by a different Claude session, not by the repository owner**; no retrieval tool was used to write or review them (review logs and gold verification in `evals/out/m11/`). Raw records and summaries: `evals/out/m11/bench_fastify_*`, `bench_csvhelper_*`. The `hono` benchmark above is TypeScript; the JavaScript result below is a separate, plain-JavaScript repository.

### Cross-language summary

| Repository (language) | Corpus files | Ambiguous edges in the index | R2 File Acc@5 | grep File Acc@5 | grep cut to R2's cost | R2 Symbol Recall@10 | grep Symbol Recall@10 | grep tokens ÷ R2 tokens | Packet coverage (sig / ref) | Packet saving vs reading |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `rich` (Python) | 213 | 17 % | 0.90 | 0.93 | 0.57 | 0.54 | 0.22 | 9× | 0.98 / 0.98 | 0.91 |
| `hono` (TypeScript) | 359 | 45 % | 0.80 | 0.63 | 0.23 | 0.66 | 0.13 | 11× | 0.57 / 0.57 | 0.57 |
| `fastify` (JavaScript) | 291 | 72 % | 0.90 | 0.57 | 0.27 | 0.69 | 0.27 | 14× | 0.46 / 0.46 | 0.88 |
| `CsvHelper` (C#) | 446 | 90 % | 0.60 | 0.77 | 0.43 | 0.33 | 0.06 | 28× | 0.47 / 0.47 | 0.82 |

Ambiguous edges are the index's own measure for that repository (`edge_precision.ambiguous_rate`), not a benchmark outcome. Each language is one repository with 30 locate and 10 packet tasks, so differences between languages mix language effects with repository effects.

### JavaScript — `fastify/fastify` v5.8.5 (commit `3983cce8124714242099e8756a7a9a80a0ba0aea`, MIT)

Plain CommonJS JavaScript, 291 corpus files (tests included; gold is in `lib/`). Task set: `evals/tasks/bench_fastify.json` (6 of 40 tasks changed in review).

| Arm | File Acc@5 (CI95) | Symbol Recall@10 (CI95) | Mean wire tokens | Latency p50 (ms) |
|---|---|---|---:|---:|
| `R0-grep` (unbounded) | 0.57 [0.37, 0.73] | 0.27 [0.13, 0.44] | 26,241 | 571 |
| `R0-grep@R2` (cut to R2's tokens) | 0.27 [0.13, 0.43] | 0.10 [0.00, 0.23] | 1,880 | 571 |
| `R0-read` (5 files whole) | 0.57 [0.37, 0.73] | 0.23 [0.10, 0.40] | 41,638 | 571 |
| `R1` `search_source(expand="none")` | 0.90 [0.80, 1.00] | 0.69 [0.53, 0.84] | 1,893 | 37 |
| `R2` `search_source(profile="locate")` | 0.90 [0.80, 1.00] | 0.69 [0.53, 0.84] | 1,888 | 39 |

| Group | grep | grep@R2 | R1 | R2 |
|---|---|---|---|---|
| a_keyword (File Acc@5) | 0.50 | 0.30 | 1.00 | 1.00 |
| b_hidden_dep (File Acc@5) | 0.80 | 0.40 | 0.90 | 0.90 |
| c_multi_file (File Acc@5) | 0.40 | 0.10 | 0.80 | 0.80 |

Packet tasks (10): `sig_coverage` 0.463, `ref_coverage` 0.463, `reach_ceiling` 0.463, `savings_vs_read` 0.884 (972 wire tokens against 10,014 to read the files).

| KPI | Result | Threshold | Met |
|---|---|---|---|
| R2 − `R0-grep@R2` File Acc@5 (same cost) | +0.633 [0.47, 0.80] | ≥ +0.10, CI excludes 0 | yes |
| R2 − unbounded `R0-grep` File Acc@5 | +0.333 [0.17, 0.53] | ≥ −0.05 | yes |
| R3 `sig_coverage` | 0.463 | ≥ 0.60 | **no** |
| R3 `ref_coverage` | 0.463 | ≥ 0.80 | **no** |
| R3 `savings_vs_read` | 0.884 [0.83, 0.92] | ≥ 0.70 | yes |
| R2 vs R1 (no threshold) | File Acc@5 +0.000; Symbol Recall@10 +0.000 [-0.03, 0.03] | report only | n/a |

**Reading.** Locating works best here of the four: R2 finds the right file in 90 % of tasks against 57 % for unbounded grep, which reads about 14 times more tokens, and 27 % for grep at equal cost. The packet's saving against reading is large (0.88) but its coverage is 0.46, below target: the packet returns what the call graph reaches (`reach_ceiling` equals coverage) and 71 % of the index's edges in this repository are ambiguous. **A finding about the indexer, not the benchmark:** methods that fastify assigns to prototypes (for example `Reply.prototype.send`, `Request` members, `ContentTypeParser.prototype.run`) are not indexed as symbols at all, so no task could target them and a user asking about them cannot find them by symbol.

### C# — `JoshClose/CsvHelper` (commit `33970e5183383bdac1fbce3b3fbcdf46b318ca52`, MS-PL / Apache-2.0)

446 corpus files; the generated `docs/` and `docs-src/` folders were removed from the working copy before indexing (vendored `bulma` CSS under `src/CsvHelper.Website` is still in the corpus). Task set: `evals/tasks/bench_csvhelper.json` (9 of 40 tasks changed in review).

| Arm | File Acc@5 (CI95) | Symbol Recall@10 (CI95) | Mean wire tokens | Latency p50 (ms) |
|---|---|---|---:|---:|
| `R0-grep` (unbounded) | 0.77 [0.60, 0.90] | 0.06 [0.00, 0.14] | 52,880 | 573 |
| `R0-grep@R2` (cut to R2's tokens) | 0.43 [0.27, 0.60] | 0.00 [0.00, 0.00] | 1,863 | 573 |
| `R0-read` (5 files whole) | 0.77 [0.60, 0.90] | 0.06 [0.00, 0.14] | 48,527 | 573 |
| `R1` `search_source(expand="none")` | 0.60 [0.43, 0.77] | 0.32 [0.17, 0.48] | 1,863 | 62 |
| `R2` `search_source(profile="locate")` | 0.60 [0.43, 0.77] | 0.33 [0.18, 0.49] | 1,874 | 69 |

| Group | grep | grep@R2 | R1 | R2 |
|---|---|---|---|---|
| a_keyword (File Acc@5) | 1.00 | 0.70 | 1.00 | 1.00 |
| b_hidden_dep (File Acc@5) | 0.40 | 0.20 | 0.10 | 0.10 |
| c_multi_file (File Acc@5) | 0.90 | 0.40 | 0.70 | 0.70 |

Packet tasks (10): `sig_coverage` 0.473, `ref_coverage` 0.473, `reach_ceiling` 0.473, `savings_vs_read` 0.819 (1,690 wire tokens against 10,834 to read the files).

| KPI | Result | Threshold | Met |
|---|---|---|---|
| R2 − `R0-grep@R2` File Acc@5 (same cost) | +0.167 [-0.07, 0.40] | ≥ +0.10, CI excludes 0 | **no** |
| R2 − unbounded `R0-grep` File Acc@5 | -0.167 [-0.33, -0.03] | ≥ −0.05 | **no** |
| R3 `sig_coverage` | 0.473 | ≥ 0.60 | **no** |
| R3 `ref_coverage` | 0.473 | ≥ 0.80 | **no** |
| R3 `savings_vs_read` | 0.819 [0.76, 0.87] | ≥ 0.70 | yes |
| R2 vs R1 (no threshold) | File Acc@5 +0.000; Symbol Recall@10 +0.011 [0.00, 0.03] | report only | n/a |

**Reading.** **C# is where token-context does worst, and the result is negative.** On keyword tasks R2 is perfect (File Acc@5 1.00), but on behavioural tasks whose query does not contain the name it finds the right file in only 1 of 10 cases, and overall it is significantly below unbounded grep (0.60 against 0.77, paired difference −0.17, CI95 −0.33 to −0.03) while using about 3.5 % of grep's tokens (52,880 against 1,874). At equal cost it is still ahead of grep (0.60 against 0.43) but the difference is not significant (+0.17, CI95 −0.07 to +0.40), so that KPI is not met. The packet's coverage is 0.47 and its saving against reading 0.82. Post-hoc look at the nine failed behavioural tasks (not used for any change): the results are dominated by attribute classes, interfaces, `MemberMap`/`MemberMapData` and, once, vendored CSS, rather than by the method that implements the behaviour; 90 % of the index's edges here are ambiguous. In other words the ranking favours declarations with long documentation over implementations, and does not use behaviour words that appear only in method bodies.

### How to read the four languages together

- **Python and JavaScript** are the languages where the tool clearly does what it is meant to do: at equal cost it beats grep by +0.33 (Python) and +0.63 (JavaScript) File Acc@5, with intervals that exclude 0.
- **TypeScript** is in between: the locate result holds (+0.57 at equal cost) but the packet misses its targets.
- **C#** is the weak spot: keyword queries work, behavioural queries do not, and unbounded grep is better on file accuracy.
- **The packet is only as good as the call graph**: coverage equals the reach ceiling in every non-Python repository, and the ambiguous-edge rate rises from 17 % (Python) to 45 % (TypeScript), 72 % (JavaScript) and 90 % (C#). Packet coverage fell from 0.98 to 0.58, 0.46 and 0.47. With four repositories this is a correlation, not a proof.
- **What would change the picture:** better call resolution for JS/TS/C#, indexing of prototype-assigned JavaScript methods, and a ranking that weighs method bodies for behavioural queries in C#. None of that has been done; this section only measures.

### Limits

One repository per language, wide intervals, task sets reviewed by another Claude session but not by the owner, a simulated grep baseline (its latency is not that of `rg`), retrieval only, no end-to-end (C3) run. The four repositories differ in size, test share and coding style, so language and repository effects cannot be separated.

## C3 v2 Multi-Agent Benchmark (M12.5)

> **Status:** the harness supports three agent CLIs, but only Claude Code (Sonnet 5.5, medium effort) was run, seed 1 only (60 of 120 runs), on the held-out suite. Seed 2, the development suite, Gemini CLI and Codex were not run (cost, tool not installed). Results and caveats: [M12](#m12--held-out-evaluation-of-030-and-the-031-follow-up), last subsection; deviations from this protocol: `evals/c3_protocol_v2.md` section 6.

C3 v2 extends the end-to-end agent evaluation harness to support multi-agent benchmarking across three agent CLIs:
1. **Claude Code (`claude`):** streaming via `claude -p --output-format stream-json --verbose` with `--strict-mcp-config`.
2. **Gemini CLI (`gemini`):** streaming via `gemini -p ... --output-format stream-json` with `--allowed-mcp-server-names`.
3. **Codex CLI (`codex`):** streaming via `codex exec --ephemeral --json --sandbox read-only`.

### Benchmark Suite (`locate_v2`)
- **Corpus:** 4 repositories across Python, TypeScript, JavaScript, and C#.
- **Tasks:** 20 counted tasks (5 per repository: 1 `a_keyword`, 2 `b_hidden_dep`, 2 `c_multi_file`) + 1 uncounted probe task (`evals/c3/locate_v2_manifest.json`).
- **Matrix:** 3 arms (`B0` native, `B1` hybrid, `B2` MCP-first) × 2 seeds = **120 runs per agent**.
- **Deterministic arm order shuffling:** Seed `20261001` permutes arm order per `(task, seed)` to remove execution order bias.
- **Automated Grading:** Answers are automatically parsed from fenced JSON (`files` and `symbols`) and graded against gold files (top 3 for group a/b; recall ≥ 0.50 in top 5 for group c).
- **Harness Scripts:**
  - `evals/run_c3.py`: single-run driver with health gate and protocol enforcement.
  - `evals/run_c3_matrix.py`: matrix orchestrator supporting `--agent {codex,claude,gemini}`, `--suite {c3_v1,locate_v2}`, `--dry-run`, `--resume`.
  - `evals/c3_report.py`: statistical aggregator reporting paired reductions and bootstrap CI95.


## M12 — held-out evaluation of 0.3.0 and the 0.3.1 follow-up

**Status:** retrieval benchmark complete (development sets and four held-out repositories, old code against new code). The end-to-end C3 run is **incomplete and unvalidated**: only seed 1 of 2 was run on the held-out suite (60 of 120 runs) and the development-suite C3 was not run, because the owner stopped further paid runs. Raw outputs: `evals/out/m12/` (`heldout_0_3_0/`, `followup_0_3_1/`, `c3_heldout_seed1/`, `final_dev_{base,new}/`, review logs).

### Protocol

- **Code under test.** `m12-base` (the 0.2.0 tree, `main` at `70d8e8f`) is "old"; tag `m12-freeze` (commit `7172665`, version 0.3.0) is "new". The held-out measurement was made on exactly that tree; `evals/guard.py` (Rule 17) checks that the tag exists and that `src/`, `bench_retrieval.py`, `edge_gold_eval.py`, `loc_eval.py` and `guard.py` have an empty diff against it (or, for the baseline run, that the tree is byte-identical to `m12-base`).
- **Held-out repositories** (none was used to develop 0.3.0): `encode/starlette` (Python, 88 indexed files), `colinhacks/zod` (TypeScript, 517), `expressjs/express` (JavaScript, 154), `serilog/serilog` (C#, 216). Each has 30 locate tasks (10 `a_keyword`, 10 `b_hidden_dep`, 10 `c_multi_file`) and 10 packet tasks, plus edge-gold labels for zod, express and serilog. Task sets were written by one independent session and reviewed by a second one without retrieval tools (Rule 16); the executor read none of them before the freeze. Express tasks 26 to 30 are `js_assigned_method` tasks whose gold is pending the indexer (`gold_pending_indexer`) and are skipped by the gold-verification scripts. Review logs: `evals/out/m12/*_review_log.md`. No human reviewed the task sets.
- **Arms** (deterministic, no model in the loop): `R0-grep` (simulated unbounded grep), `R0-grep@R2` (grep cut to the wire size of R2), `R1` (`search_source`), `R2` (`search_source(profile="locate")`, about 1.9k tokens), `R3` (packet from `inspect_symbol(view="full")` against reading the files). CI95 is a bootstrap over tasks (2,000 resamples).
- **Rule 18.** Each held-out set was measured once with each code version. Anything done after that (the 0.3.1 fix) was checked on development sets only.

### Held-out results (0.3.0 against the 0.2.0 baseline)

File Acc@5 (old → new), `R2` at about 1.9k tokens, with the baselines:

| Repository | grep, unbounded (tokens read) | grep, same size as R2 | R1 | R2 | R2 paired difference new − old |
| --- | ---: | ---: | ---: | ---: | --- |
| starlette (Python) | 0.77 (23.8k) | 0.47 | 0.73 → 0.73 | 0.77 → 0.77 | 0.00 (CI95 0.00 to 0.00) |
| zod (TypeScript) | 0.60 (43.9k) | 0.43 | 0.77 → 0.73 | 0.73 → 0.73 | 0.00 (0.00 to 0.00) |
| express (JavaScript) | 0.97 (15.9k) | 0.67 | 0.80 → **0.97** | 0.80 → **0.93** | **+0.13** (0.00 to +0.30) |
| serilog (C#) | 0.80 (29.5k) | 0.50 | 0.73 → 0.73 | 0.73 → 0.70 | −0.03 (−0.13 to 0.00) |

Symbol Recall@10 (old → new):

| Repository | grep, unbounded | R1 | R2 | R2 paired difference |
| --- | ---: | ---: | ---: | --- |
| starlette | 0.28 | 0.44 → 0.44 | 0.44 → 0.44 | 0.00 |
| zod | 0.13 | 0.49 → 0.53 | 0.56 → 0.61 | +0.04 (0.00 to +0.12) |
| express | 0.13 → 0.16 | 0.68 → 0.70 | 0.68 → 0.67 | −0.01 (−0.18 to +0.16) |
| serilog | 0.09 | 0.45 → **0.68** | 0.43 → **0.64** | **+0.21** (+0.08 to +0.36) |

`R2` at equal cost against `R0-grep`: starlette 0.00 (CI95 −0.13 to +0.13), zod +0.13 (−0.03 to +0.33), express −0.03 (−0.13 to +0.07), serilog −0.10 (−0.30 to +0.10). Against unbounded grep nothing is significant in either direction at 30 tasks; the tool reads 8 to 23 times fewer tokens.

`R2` File Acc@5 by group (old → new; `a_keyword` / `b_hidden_dep` / `c_multi_file`): starlette 1.0 / 0.4 / 0.9 (unchanged); zod 1.0 / 0.4 / 0.8 (unchanged); express 1.0 → 0.9 / 0.7 → **0.9** / 0.7 → **1.0**; serilog 0.9 → 0.8 / 0.4 / 0.9 (unchanged). Behavioural queries without a name in the query (`b_hidden_dep`) are the weak group everywhere except JavaScript.

Packet (`R3`, 10 tasks) and call graph:

| Repository | Reference coverage (old → new) | Saving against reading | Edges (old → new) | Ambiguous (old → new) | Symbols (old → new) |
| --- | ---: | ---: | ---: | ---: | ---: |
| starlette | 0.52 → 0.52 | 0.86 | 3,487 → 3,487 | 31.0 % → 31.0 % | 2,063 |
| zod | 0.34 → 0.42 (+0.08, 0.00 to +0.18) | 0.93 | 3,622 → 3,263 | 65.5 % → 55.8 % | 4,386 → 3,898 |
| express | 0.00 → **0.39** (+0.28, +0.12 to +0.42) | 0.93 | 11 → 191 | 63.6 % → 43.5 % | 165 → 259 |
| serilog | 0.30 → **0.47** (+0.17, +0.07 to +0.28) | 0.75 → 0.72 | 2,154 → 2,988 | 68.6 % → 39.7 % | 1,963 |

Edge gold (hand-labelled internal call sites; recall counts a site as correct if the right target is resolved at any confidence, precision counts only edges with confidence ≥ 0.6):

| Repository | Sites | Correct, old → new | Edges ≥ 0.6, old → new | Precision at ≥ 0.6 |
| --- | ---: | ---: | ---: | ---: |
| zod | 12 | 2 → **0** | 2 → 0 | 1.00 → 1.00 (vacuous) |
| express | 11 | 0 → 2 | 0 → 2 | 1.00 |
| serilog | 17 | 5 → **13** | 5 → 11 | 1.00 → 1.00 |

### Predeclared KPIs (K1 to K10), held-out, 0.3.0

| | Target | Result | Met |
| --- | --- | --- | :-: |
| K1 | JS assigned-method recall in the index ≥ 0.95 and 0 wrong in a 30-symbol sample (`evals/js_assigned_scan.py`) | 0.933 (84 of 90 scanned assigned methods indexed), 0 wrong; every miss is a chained assignment, recall without them 1.00 | no |
| K2 | JS `R2` File Acc@5, new − old ≥ 0 | +0.13 (CI95 0.00 to +0.30) | yes |
| K3 | C# `R2` − unbounded grep ≥ −0.05 | −0.10 (−0.30 to +0.10) | no |
| K4 | C# `R2` File Acc@5, new − old ≥ +0.10 | −0.03 (−0.13 to 0.00) | no |
| K5 | C# `b_hidden_dep` `R2` ≥ 0.40 | 0.40 (the old code also scored 0.40) | yes |
| K6 | ambiguous-edge ratio new/old ≤ 0.70 for JS, TS and C# | express 0.68, zod **0.85**, serilog 0.58 | no |
| K7 | `R3` reference coverage new − old ≥ +0.10 for JS, TS and C# | +0.28, zod **+0.08**, +0.17 | no |
| K8 | edge precision ≥ 0.95 at confidence ≥ 0.6 | 1.00 in all three, from 2, 0 and 11 edges (**no evidence for zod**) | yes |
| K9 | Python File Acc@5 and Symbol Recall@10 identical | identical (and byte-identical output) | yes |
| K10 | median `search_source` latency ≤ +20 % on a fixed query set | zod `$ZodError` +25 % (13.1 → 16.4 ms), serilog `LogEvent` +27 % (10.2 → 12.9 ms); the other ten queries within +13 % | no |

**Result: 4 met (K2, K5, K8, K9), 6 not met (K1, K3, K4, K6, K7, K10).** K8 is met only formally for TypeScript. K1 detail: `evals/js_assigned_scan.py` finds 90 assigned methods in express by a syntactic scan and checks them against the index; the 6 chained-assignment symbols were missing (`evals/out/m12/heldout_0_3_0/new/js_assigned_scan_express.json`).

K10 note: `bench_latency.py` picks the first symbol of the index as its query, and the two code versions index a different first symbol for zod (`zod3` against `$ZodError`), so its zod `search_source` comparison (4.83 → 15.89 ms, 3.3x) compares two different queries and is **not** a regression figure. `evals/k10_latency.py` runs the same queries on both versions; its outputs are in `evals/out/m12/heldout_0_3_0/k10/`. Other tools: `get_symbol_context` on serilog 0.78 → 2.58 ms and `inspect_symbol(full)` x10 on serilog +10 %; everything else within noise.

### Development sets (informative, not held-out)

The development repositories informed the M12 changes, so these figures can only show that nothing broke and where the changes landed. Columns: 0.2.0 baseline / 0.3.0 / 0.3.1.

| Repository | Symbols | Edges | Ambiguous | `R2` File Acc@5 | `R2` Symbol Recall@10 | `R3` ref. coverage | Edge-gold sites resolved |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rich` (Python) | 2,096 / 2,096 / 2,096 | 3,797 (all) | 16.6 % (all) | 0.90 (all) | 0.544 (all) | 0.983 (all) | n/a |
| `hono` (TypeScript) | 2,122 / 2,093 / **2,146** | 1,365 / 1,492 / 1,595 | 45.2 / 34.0 / 37.5 % | 0.80 / 0.77 / 0.77 | 0.664 / 0.653 / 0.664 | 0.575 / **0.755** / 0.755 | 7/14 / 10/14 / 10/14 |
| `fastify` (JavaScript) | 1,165 / 1,213 / **1,408** | 771 / 824 / 955 | 71.5 / 63.5 / 68.3 % | 0.90 / 0.93 / 0.93 | 0.691 / 0.602 / **0.596** | 0.463 / 0.488 / 0.488 | 1/10 (all) |
| `CsvHelper` (C#) | 14,460 (all) | 3,178 / 6,510 / 6,510 | 90.3 / 35.3 / 35.3 % | 0.60 / 0.57 / 0.57 | 0.328 / **0.483** / 0.483 | 0.473 / **0.693** / 0.693 | 1/10 / 4/10 / 4/10 |

Python is identical in all three columns. The regression gate of Rule 19 (`tc-pinned` loc A1final/A2 at 8,192 tokens and `edge_eval`, `rich` bench) shows 0 differences. Raw: `evals/out/m12/final_dev_{base,new}/`, `evals/out/m12/followup_0_3_1/dev/`.

### 0.3.1 follow-up (development evidence only)

After the held-out run, a scan of symbol counts showed that 0.3.0 indexed fewer JS/TS symbols than the 0.2.0 baseline in places (hono 2,122 → 2,093, zod 4,386 → 3,898): M12.1 skipped every `method_definition` inside an object literal to avoid double indexing, which also dropped methods of objects passed as arguments (`run("s", { test() {} })`), returned objects, nested objects and objects inside functions, with the edges that start in them. 0.3.1 skips only members that an owning pattern has already emitted, and binds chained assignments (`res.set = res.header = function …`, `exports = module.exports = {…}`). Evidence: `tests/test_js_object_methods.py` (12 cases), full suite green, `PARSER_ARTIFACT_VERSION` 7.

- Symbols restored: hono 2,093 → 2,146, fastify 1,213 → 1,408; on the held-out repositories zod 3,898 → 4,465 and express 259 → 265 (index counts only, no retrieval measured).
- K1 scan on express: 90 of 90 assigned methods indexed, 0 wrong in the 30-symbol sample.
- zod ambiguous-edge rate with 0.3.1: 57.2 % (2,250 of 3,932), ratio 0.87 against the baseline, so K6 would still not be met for TypeScript.
- Not re-measured: held-out retrieval and edge gold for 0.3.1. Whether the zod edge-gold sample (2/12 → 0/12) recovers is therefore **unknown**; that is a hypothesis, not a result.
- Effect on retrieval in the development sets: none on `rich`, `CsvHelper`; hono Symbol Recall@10 0.653 → 0.664; fastify 0.602 → 0.596 (no recovery).

### Known issues after M12

1. **fastify `R2` Symbol Recall@10** fell from 0.691 (0.2.0) to 0.602 (0.3.0) and 0.596 (0.3.1): the new symbols from assigned methods crowd the top ten. Not investigated further.
2. **C# file accuracy did not improve** and behavioural queries stay weak (held-out `b_hidden_dep` 0.40, development CsvHelper 0.10); `R2` is below unbounded grep by 0.10 (not significant) on serilog and by 0.20 on CsvHelper. M12.2 improved symbol ranking, not file ranking.
3. **TypeScript call graph:** 56 to 57 % of zod edges are ambiguous and no edge reached confidence 0.6 on the gold sample, so packets can only return what the graph reaches (reference coverage 0.42).
4. **Python hidden-dependency queries** find the file in 4 of 10 cases on starlette (31 % ambiguous edges).
5. **Latency:** two of twelve fixed `search_source` queries are 25 to 27 % slower in 0.3.0 (≤ 3.3 ms in absolute terms).
6. **Guard loophole (not fixed, guard is a protected path):** a run with the baseline package on `PYTHONPATH` and a clean tree passes `evals/guard.py` without `--allow-baseline-code`. The baseline runs of this report used the flag.
7. **Dev edge gold:** four hono labels were wrong (the tool was right) and were corrected before the final development measurement (`evals/out/m12/edge_gold_hono_corrections.md`); the development hono gold is therefore not independent of the tool.

### Corrections to earlier statements

- An early statement in the review of the M12 run that M12.2 changed Python output (the `rich` artifact in `evals/out/m12/m12_2_rich`) was wrong for committed code: that artifact came from an uncommitted tree. On the committed code Python output is identical to the baseline.
- The run ledger written by the first M12 agent marked M12.0 to M12.6 "done"; at that point no held-out task set had been written or measured, the freeze tag had been made before any held-out review, and the edge resolver kept a per-file wall-clock breaker that made graphs depend on machine load. These were corrected afterwards (deterministic work budget, `RESOLVER_VERSION` in the fingerprint, tag recreated at `7172665` after the independent reviews); the ledger and checkpoint now carry corrective rows.

### C3 (end to end), seed 1 only, **not validated**

- **Setup:** Claude Code headless (`claude -p`), `claude-sonnet-5-5`, `--effort medium`, tools `Read,Grep,Glob`, held-out suite `locate_v2` (20 counted tasks on starlette, zod, express, serilog), arms B0 native only, B1 hybrid with MCP optional, B2 MCP-first, seed 1: 60 of the planned 120 runs. MCP server: frozen 0.3.0 code on the held-out indexes. 0 protocol violations, 0 infrastructure failures. Record: `evals/out/m12/c3_heldout_seed1/` (`c3_report_seed1.md`, `usage_seed1.jsonl`, raw session logs). Protocol and deviations: `evals/c3_protocol_v2.md` section 6.
- **Stopped:** seed 2, the development-suite run and any other model were not run (cost). Gemini CLI was not installed and Codex was not run. Everything below comes from seed 1 alone.

| Arm (20 runs each) | Success | Retrieved tokens (estimated) | Total tokens | MCP calls / run | Native calls / run | Latency | Provider cost (20 runs) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 native | 100 % | 753 (CI95 504 to 1,031) | 82,211 (74,350 to 90,607) | 0 | 2.1 | 12.2 s | US$1.08 |
| B1 hybrid, MCP optional | 100 % | 468 (285 to 669) | 84,507 (71,449 to 98,866) | **0.0** | 2.0 | 12.5 s | US$1.04 |
| B2 MCP-first | 100 % | 1,387 (1,049 to 1,780) | 65,464 (59,205 to 72,782) | 1.1 | 0.1 | 10.6 s | US$1.08 |

Paired differences (20 pairs): B2 against B0 total tokens −16,747 per run (CI95 −25,065 to −8,586, **−20 %**), retrieved tokens +634 (+294 to +975); B1 against B0 total tokens +2,296 (−9,019 to +14,202).

How to read it:
1. **Ceiling effect.** Every arm solved all 20 tasks, so success rate cannot separate the arms and there is no evidence of a quality difference in either direction. The four repositories are well known and the model may know part of the answers.
2. **B1 never used the MCP server** (0 of 20 runs), so B1 is a second sample of the native-only behaviour. Its difference from B0 (retrieved tokens −285 per run, CI95 −561 to −52, although the agent behaved identically in both arms; total tokens +2.8 %, within noise) shows that paired intervals on 20 runs understate run-to-run variation, so narrow intervals in this section should be read with caution. No statement about the hybrid protocol follows.
3. **B2 used 20 % fewer total tokens** and was about 13 % faster, because it answers in about one MCP call and one turn fewer. It also retrieved *more* content (1,387 against 753 estimated tokens), and the provider-reported cost is the same: B2 had 17 % more uncached input (181k against 154k tokens over 20 runs) and 24 % fewer cache-read tokens (1.12M against 1.48M). The total-token difference is therefore mostly cheaper cache reads, not less new information.
4. A fixed overhead of about 25,000 cached input tokens per run (system and tool prompt) dominates every total, which is why total tokens measure the number of turns more than the amount of code read.
5. **What it does and does not show:** on tasks this easy, an MCP-first agent locates files in fewer turns at equal billed cost and equal success. It does not show that token-context raises success, that it helps on hard tasks or on weaker models, or anything about the hybrid mode.

## M13 — Java and C#: overloads, overrides, many-word identifiers (0.3.2)

**Status:** light, deterministic benchmark (no model in the loop, no API cost) on three development repositories and two fresh repositories, old code (`m13-base` = 0.3.1, `e745d52`) against new code (tag `m13-freeze`, `4ada9ee`, version 0.3.2). Raw outputs: `evals/out/m13/` (`dev_{base,new,base_regold}/`, `fresh_{base,new}/`, review logs). Commands: `evals/out/m13/run_m13_eval.sh`, `run_m13_fresh.sh`.

### Protocol and honesty labels

- **Development sets (informative, tuned on):** `CsvHelper` (C#, 30 tasks, 10 internal call sites), `jsoup` (Java, 12 tasks written by the executing session, 11 internal call sites; three gold labels were corrected after reading the source: `NodeInternals:73`, `QueryParser:231`, `RequestAuthHandler:13`), Serilog (C#, 30 tasks, 17 sites; it was used in M12 as held-out and is **burned**, now exploratory). The base side of the edge-gold comparison was re-run with the corrected labels (`dev_base_regold/`).
- **Fresh sets (measured once):** `google/gson` @ `854c825` (Java, Apache-2.0) and `JamesNK/Newtonsoft.Json` @ `52fa3ae` (C#, MIT), each 15 locate tasks (5 `a_keyword`, 5 `b_hidden_dep`, 5 `c_multi_file`) and 12 labelled call sites. Authored by one Claude Sonnet 5.5 session from the library source only, with no retrieval tool and no access to anything the tool produced; the executor read neither file before the freeze (SHA-256 of the files as authored: `fresh_gson` 38988ba2…, `fresh_newtonsoft` bfddca8f…, edge gold gson b3d9a721…, Newtonsoft a3102d23…). The retrieval tasks were then reviewed by a **different** Sonnet session (source reading only; 0 of 30 tasks changed, so `reviewed: true` is set; hashes of the reviewed files in `RUN_LEDGER_M13.md`). The call-site labels were **not** reviewed and were measured before that review; they stay as authored. **No human reviewed any of these sets**; the sets are small (n = 15 and 12), so intervals are wide. The gson and Newtonsoft sources were not used to tune any rule.
- **Guard.** `TC_GUARD_MILESTONE=m13` makes `evals/guard.py` require tag `m13-freeze` (empty diff on `src/` and the three bench scripts) and, for the baseline arm, a tree byte-identical to `m13-base:src/token_context_mcp` (checked). The `freeze_tag` field written into `bench_*_summary.json` still shows the M12 tag because it is hard-coded in the protected `bench_retrieval.py`; `git_head` (`4ada9ee`) is the real reference.
- **Regression gate.** Python and JavaScript/TypeScript outputs are identical between 0.3.1 and 0.3.2: `tc-pinned` loc A1final/A2 and `edge_eval`, and `rich`, `hono`, `fastify` (all six retrieval arms: 0 differing task records; edge gold and edge audit for hono and fastify equal).

### What changed (summary; details in `CHANGELOG.md`)

Typed receivers and argument types per call site, overload choice by arity then types, nearest override, ancestor search level by level, qualified nested types, Java `package` and wildcard imports, C# `#if` retry, external-library receivers, `new` binding to constructor or class, sub-word and stem search tokens for C#/Java identifiers.

### Fresh sets (measured once)

| | gson base → new | Newtonsoft base → new |
| --- | --- | --- |
| Call-site recall (confidence ≥ 0.6) | 2/9 (0.22) → **8/9 (0.89)** | 3/7 (0.43) → **5/7 (0.71)** |
| Edges at confidence ≥ 0.6, correct | 2/4 → 8/10 | 3/3 → 5/7 |
| Exact overload (`def_line`) | 2/9 → 7/9 | 2/7 → 5/7 |
| Edges in the index / ambiguous | 7,708 / 28 % → 9,878 / 15 % | 24,931 / 34 % → 25,262 / 25 % |
| `R1` File Acc@5 | 0.80 → 0.87 | 0.73 → 0.80 |
| `R2` File Acc@5 (grep unbounded 0.87 / 0.60) | 0.80 → **0.93** (paired +0.13, CI95 0.00 to +0.33) | 0.73 → 0.80 (paired +0.07, CI95 −0.13 to +0.27) |
| `R1` Symbol Recall@10 | 0.59 → 0.80 (paired +0.21, CI95 +0.03 to +0.42) | 0.42 → 0.68 (paired +0.26, CI95 +0.04 to +0.50) |
| `R2` Symbol Recall@10 | 0.59 → 0.66 | 0.52 → 0.66 |
| File MRR, `R1` / `R2` | 0.64 → 0.63 / 0.59 → 0.67 | 0.58 → 0.54 / 0.55 → 0.52 |

CI95 is a paired bootstrap over tasks (2,000 resamples). With 15 tasks only the `R1` Symbol Recall@10 gains exclude zero; File Acc@5 moves by one or two tasks. File MRR did not improve for Newtonsoft (0.55 → 0.52): the right file is found about as often but not ranked higher. Latency is not reported.

**Misses and wrong edges on the fresh call-site labels (read after the measurement, nothing was tuned):**

- gson `Excluder.java:143` `delegate().write(...)`: the edge for `write` is not produced (the site is credited to the call to `delegate()` itself); a method returning a generic type is not followed.
- Newtonsoft `JConstructor.Async.cs:53` (`_values[i].WriteToAsync`) and `JToken.Async.cs:157` (`v.SetLineInfo`): receiver from an indexer or a loop variable of a partial class; left unresolved.
- Edges at confidence ≥ 0.6 that the labels call external: Newtonsoft `MethodBinder.cs:338` `.Where` and `ReflectionUtils.cs:947` `targetType.GetFields` resolve to the repository's own `Enumerable.Where` (LinqBridge) and `TypeExtensions.GetFields`, whereas the labels say the BCL method; gson `JsonPrimitive.java:196` `this.getAsNumber().longValue` resolves `getAsNumber` (correct) while the label marks the whole site external. Both gson edges counted wrong are real edges of the *first* call in a chain (`delegate()`, `getAsNumber()`) scored against a label for the outer call, so they are a labelling-granularity effect; the two Newtonsoft ones are the genuine same-name-extension weakness.

### Development sets (informative)

| | CsvHelper (C#) | jsoup (Java) | Serilog (C#, burned) |
| --- | --- | --- | --- |
| Gold recall, ≥ 0.6 | 0.40 → 0.80 | 0.36 → 0.82 | 0.76 → 0.94 |
| Gold precision, ≥ 0.6 | 1.00 (4/4) → 0.80 (8/10) | 1.00 (4/4) → 1.00 (9/9) | 1.00 (11/11) → 1.00 (14/14) |
| Ambiguous edges | 35 % → 23 % | 38 % → 16 % | 40 % → 16 % |
| `R1` File Acc@5 | 0.60 → 0.87 | 0.50 → 0.83 | 0.73 → 0.77 |
| `R2` File Acc@5 | 0.57 → 0.87 | 0.67 → 0.83 | 0.70 → 0.80 |
| `R2` Symbol Recall@10 | 0.48 → 0.73 | 0.35 → 0.47 | 0.64 → 0.66 |
| `R2` minus unbounded grep, File Acc@5 | −0.20 → +0.10 (CI95 −0.07 to +0.27) | −0.25 → −0.08 | −0.10 → 0.00 |
| `R3` packet reference coverage | 0.69 → 0.67 | – | 0.47 → 0.52 |

CsvHelper's two wrong edges are interface-dispatch calls (`ITypeConverter.ConvertToString`-style) that the tool resolves to the interface member while the label names the implementation. Per call site, jsoup moved from unresolved to resolved at about 6,080 sites, changed target at about 1,980 (about 100 sampled by hand, nearly all corrections) and lost 54 (mostly base guesses on `Map`/`List`/`String` receivers that are now correctly external; a few lucky edges lost to type-parameter bounds such as `T extends Node` and interface `toString`). Serilog's symbol count falls 1,963 → 1,910 because mangled symbols in `ILogger.cs` (131) and a few other `#if` files are replaced by correctly qualified ones (`PropertyBinder.ConstructProperty` instead of an unqualified `ConstructProperty`).

### How to read this

- Resolution of calls on typed receivers in Java and C# is now much better and, on the labelled sites, mostly right; the unresolved share fell by 10 to 22 points. It is still static typing without generics, so a call whose receiver type is only known through a generic or a type-parameter bound stays unresolved (a deliberate choice: unresolved is cheaper than wrong).
- File-level retrieval moved by one or two tasks per set; the search-token change helps symbol ranking more than file ranking. Packets (`R3`) were measured on the development sets only and did not change much.
- The suspicious-edge heuristic in `evals/edge_audit.py` is name/receiver based (designed for dynamic languages) and counts typed resolution as "suspicious" more often (jsoup 1.1 % → 1.8 %, gson 1.3 % → 2.0 %); it is not a precision measure and gold precision above is the better guide.

### Limits

Five repositories, two of them fresh with 15 tasks and 12 labelled sites each; one author, no human review; call-site labels not independently reviewed; a simulated grep baseline; retrieval quality only (no agent task success; C3 was not run, to avoid API cost); the jsoup development set was written by the executor; the "family cap" and overload-collapse ideas were tried on the development sets without gain and left off.
