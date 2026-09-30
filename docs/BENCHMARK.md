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

