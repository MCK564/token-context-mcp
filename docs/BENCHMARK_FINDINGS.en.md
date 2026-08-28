# token-context-mcp — Benchmark findings

This companion contains sections §2.7–§2.16 extracted from the remediation plan. It records measured findings, benchmark design decisions and the R/E/RK work series.

---

## 2.7 C3 pilot post-mortem (2026-08-27) — the pilot measured nothing about the tool

First C3 run, `T1-orientation` on `bench-invoice`, 1 task x 1 seed:

| Arm | MCP calls | Total tokens | Latency | Success |
|---|---|---|---|---|
| B0 native-only | 0 | 315,262 | 90.59 s | yes |
| B1 token-context | 2 | 288,545 | 117.80 s | yes |

Reported as "B1 saves 8.5%, 1.30x slower". **Both conclusions are artifacts.** The session logs show why.

### Finding 1 — nothing ran twice

Commands appear duplicated in the logs because Codex emits `item.started` **and** `item.completed` for the same item. Distinct items: B0 = 8 (3 `agent_message` + 5 `command_execution`); B1 = 10 (4 `agent_message` + 2 `mcp_tool_call` + 4 `command_execution`). No command executed twice.

### Finding 2 — both MCP calls returned errors

```
get_index_status  repo_id="D:\AI\bench\invoice-scanner-frozen"                      -> error, 89 tok
get_repo_map      repo_id="D:\AI\bench\invoice-scanner-frozen", budget_tokens=5000  -> error, 89 tok
```

Total contribution of token-context to B1: **178 tokens of error envelope.** The 8.5% is run-to-run variance in how each arm phrased ripgrep — B0 emitted 42,265 tokens of shell output over 5 commands, B1 emitted 29,339 over 4. **The pilot compared two native-only sessions.**

Three independent causes, each sufficient on its own:

- **C-a. `repo_id` was a filesystem path.** The registered id is `bench-invoice`; `validate_repo_id` rejects anything not matching `^[a-z][a-z0-9_-]{0,63}$`.
- **C-b. `budget_tokens: 5000` exceeds `max_result_tokens: 2048`.** The call would have failed even with the correct id.
- **C-c. The agent could not self-correct.** `server._invoke` collapses every exception into `"request rejected by read-only repository policy"`. The agent learned neither that the id was wrong, nor that a budget ceiling existed, nor what a valid id looks like — so it abandoned the tool after two attempts and fell back to native shell.

C-c is the design defect. **No tool exposes the registered `repo_id` list**, and the agent instruction in `INTEGRATION.md` never states that `repo_id` is a short registered name rather than a path. Every tool demands a value the agent has no way to discover.

### Finding 3 — the C1 baseline is a strawman

C1 compares against "read every `.py` file" = 201,767 tokens for `bench-invoice`, giving 25x-184x. **B0 never did that.** A competent agent greps: B0 answered the task with 42,265 tokens of shell output — 4.8x less than the naive baseline.

Measured against what an agent actually does, the honest comparison is `repo_map` versus `rg --files`, and for orientation `rg` wins on coverage per token:

| `repo_map` budget | Payload | Symbols shown | Coverage of 437 |
|---|---|---|---|
| 1,024 | 992 | 8 | 1.8% |
| 2,048 | 1,969 | 16 | 3.7% |
| 4,096 | 3,996 | 32 | 7.3% |
| 8,192 | 8,125 | 63 | 14.4% |

B0's single `rg --files` dump cost 18,228 tokens and returned the **complete** file listing. At the server cap of 2,048 the tool offers 3.7% of symbols. **For T1-orientation, `repo_map` is not competitive with ripgrep**, and no amount of fixing the accounting changes that.

This is a real limit, not a bug: `repo_map` returns ranked symbols with metadata — richer per item, far less coverage per token. Its advantage should appear on **localisation and impact** tasks (T2, T3, T5), where `rg` must be run repeatedly and the graph is the thing being asked for. Those tasks have not been run.

### New work items

- **W13 — make `repo_id` discoverable.** Add a `list_repositories` tool returning ids only (never roots — those are the sensitive half). Without it the tool surface is unusable by an agent that was not hand-configured.
- **W14 — make errors actionable without leaking paths.** Distinguish `unknown_repo_id`, `budget_out_of_range` (naming the ceiling) and `policy_rejected`. The current single opaque message is why two recoverable mistakes became a total abandonment.
- **W15 — state the contract in the agent instruction.** `INTEGRATION.md` must say: `repo_id` is a registered short name, call `list_repositories` first, and `budget_tokens` must not exceed the server ceiling.

### Protocol corrections before re-running C3

1. Fix W13-W15 first. A pilot where the tool errors on every call measures nothing.
2. **Assert tool health in the runner**: fail the run if any `mcp_tool_call` returns an `error` envelope. This pilot would have aborted in 4 seconds instead of producing a misleading 8.5%.
3. **Report two baselines**: naive full-read (C1, an upper bound) *and* competent-native (B0's actual shell output, the honest denominator). Quote the second.
4. **Run T2/T3/T5, not just T1.** Orientation is the task where the tool is structurally weakest.
5. Record `cached_input_tokens` separately — 83% of input in both arms was cache replay, so total-token deltas mostly reflect conversation length, not retrieval volume.


### Fixes applied (2026-08-28)

Three defects found while investigating why the validated C3 pilot's own numbers looked wrong:

**Fix A — stop duplicating every MCP response.** `server.py`'s tools returned a plain dict and let `structured_output=True` JSON-dump that same dict into a `content` text block *in addition to* `structured_content` — 42% of every measured response was a byte-for-byte copy of the other half. Each tool now returns a `CallToolResult` directly: `structured_content` carries the full envelope (unchanged — every existing test already asserted against `structured_content`, never `content`), and `content` carries a short one-line summary (`repo_id=... freshness=... symbols=16 omitted_count=421`) instead of a copy. Measured on `bench-invoice`, `repo_map`@2048: wire size ~3,938 tok -> 2,048 tok, roughly halved, with the response now landing inside the configured cap instead of exceeding it.

**Fix B — measure the wire, not the service return value.** `evals/measure_context_cost.py` previously called `RetrievalService` directly and measured that dict — the same layer Fix A found duplicating. It now wraps every response through `server._result()` (the same code path a live MCP call takes) before measuring, so `calls_over_server_cap` and the accounting-gap gate reflect what an agent is actually billed for. Re-run after Fix A: worst gap 34.6x -> 1.28x on `bench-invoice`, 32.1x -> 1.14x on `token-context`; `calls_over_server_cap` 3 -> 0 on both.

**Fix C — count MCP result bytes as retrieved content.** `evals/run_c3.py` accumulated bytes from `command_execution` items only; `mcp_tool_call` results were counted (`mcp_completed_call_count`) but never sized. This produced `native_command_output_estimated_tokens: 296` for a B1 run that had actually pulled in 30,491 tokens through 9 successful MCP calls, making the arm look like it barely retrieved anything relative to B0's 33,670-token shell dump. The runner now also accumulates `mcp_result_output_bytes` from each completed `mcp_tool_call.result`, and records `mcp_result_output_estimated_tokens` and `retrieved_content_estimated_tokens = native + mcp` per run. `benchmark-report` now reports `median_retrieved_content_estimated_tokens` alongside the legacy native-only field. Recomputed from the validated pilot's own session logs: T2 retrieved content was actually B0 33,670 vs B1 30,787 (roughly even, not "B1 retrieved almost nothing"); T5 was B0 76,293 vs B1 30,746 (B1 genuinely retrieved less).

None of this changes `total_tokens` (the provider-billed figure the paired-reduction statistic is computed from) for the three already-recorded pilot rows — those runs predate Fix A and cannot be corrected retroactively. **The validated pilot's `-0.32%` conclusion still stands as reported and is still not evidence of a saving** (`paired_count: 3`, CI95 `[-0.53, +0.33]`); what changes is that a re-run today would (a) send roughly half the wire bytes per MCP call, and (b) log an honest content-retrieval number instead of one that made B1 look like it wasn't using the tool. Re-running C3 is still open work.

**Verification:** `pytest` — 32 passed, 1 skipped, no regressions. `evals/measure_context_cost.py --repo-id bench-invoice` and `--repo-id token-context` re-run and reports attached (`evals/reports/c1-bench-invoice.json`, `evals/reports/c1-token-context.json`).

---

## 2.8 Validated C3 rerun (2026-08-27) — tool health fixed; no efficiency claim yet

The rerun used the source-only frozen repository `bench-invoice`, matched prompt SHA-256 values inside every B0/B1 pair, and ran T2, T3, and T5 once each. B1 first called `list_repositories`, selected `bench-invoice`, and every B1 run had `mcp_health: passed` with no MCP error envelope. `evals/run_c3.py` now refuses to write a usage row on an MCP error; the report also rejects MCP-error rows and mismatched prompt hashes.

| Task | B0 total / latency | B1 total / latency | B1 MCP calls | Paired token reduction |
|---|---:|---:|---:|---:|
| T2 locate | 468,382 / 100.27 s | 718,246 / 138.72 s | 10 | -53.35% |
| T3 impact | 998,548 / 207.83 s | 1,001,735 / 208.83 s | 4 | -0.32% |
| T5 evidence | 879,958 / 177.62 s | 589,001 / 163.16 s | 6 | +33.06% |

Both arms produced source-backed answers for all three tasks; this is a manual task-success check, not a formal quality/non-inferiority score. The median of the three paired reductions is **-0.32%** (B1 slightly worse), with observed task values from **-53.35% to +33.06%**. This pilot therefore does **not** support an end-to-end token-saving claim.

`cached_input_tokens` was 89-92% of input in every row, so it must be reported separately and total-token deltas must not be read as retrieval volume. The competent-native-output estimate is a local `utf8-bytes / 4` diagnostic, not provider billing; it was lower for B1 on T2/T5 but higher on T3.

The rerun exposes two remaining issues: the agent still uses native reads after MCP discovery, and `repo_map` ranking was noisy for T5. The next C3 gate is a predeclared call policy (including a call budget), the remaining tasks and seeds, and a defined quality gate. Do not publish a saving figure until the full 5-task x 3-seed paired matrix passes.

The content-enriched projection was recomputed directly from the raw session logs while preserving every provider token field. It reports T2 B1 as **296 native + 30,491 MCP = 30,787 retrieved-content tokens**, and T5 B1 as **12,232 native + 18,514 MCP = 30,746**. These are local retrieval-content diagnostics, not billing numbers; T3 is also included and totals 57,404 retrieved-content tokens for B1.

Artifacts: `evals/reports/c3-validated-content.jsonl`, `evals/reports/c3-validated-content-summary.json`, and `evals/runs/c3-rerun/`. The older `c3-invoice-*`, `c3-rerun.jsonl`, and pre-C content report remain audit evidence only and must not be used for a performance claim.

---

## 2.9 Why the hybrid workflow cannot show a saving — root causes (2026-08-28)

The working hypothesis after the validated pilot was "caps are too low, and the prompt lets the agent fall back to native". Measurement says the caps are the *least* important of four causes, and one proposed cap change would mask a bug rather than fix it.

### R1 — The index cannot find code by what it does, only by what it is named

`find_symbols` matches SQL `name LIKE ? OR qualified_name LIKE ?`. `rank_symbols` scores against `path + name + qualified_name + signature`. **Neither ever sees a function body.** `rg` sees every byte.

Measured on `bench-invoice`, term `ocr`:

| | |
|---|---|
| Files whose source body mentions `ocr` | **41** |
| Symbols living in those files | **270** |
| Symbols with `ocr` in the name — findable via `find_symbols` | **27** |
| **Symbols invisible to `find_symbols` despite being OCR code** | **243 (90%)** |

`repo_map(query="ocr")` cannot close this either, because it ranks the same name-only haystack:

| budget | symbols returned | of which in an OCR file | omitted |
|---|---|---|---|
| 1,024 | 8 | 7 | 429 |
| 2,048 | 16 | 13 | 421 |
| 4,096 | 33 | 25 | 404 |
| 8,192 | 64 | 48 | 373 |

At the **maximum configurable budget** the tool returns 64 of 437 symbols (14.6%). Reaching the 270 OCR-adjacent symbols would cost roughly 35,000 tokens of `repo_map`; `rg -n 'ocr'` located all 41 files in one command. This is why T2 and T5 send the agent to ripgrep, and **no value of `max_result_tokens` changes it**.

### R2 — `graph_node_limit_capped_by_server` fires when nothing was capped

`service.py:422` emits the warning when `effective_max_nodes < max_nodes` — that is, whenever the *request* was clamped, regardless of whether the traversal ever approached the limit. `symbol_limit_capped_by_server` (line 184) has the same shape.

Measured on `parse_receipt_number`, the T3 subject:

| `max_nodes` | nodes returned | edges | wire tokens | warnings |
|---|---|---|---|---|
| 75 | 23 | 24 | 5,546 | none |
| 200 | 23 | 24 | 5,546 | none |
| 500 | 23 | 24 | 5,546 | none |

**The real graph is 23 nodes.** The cap was never binding at any setting. But the agent requested `max_nodes=100` against a server cap of 75, so `100 > 75` fired `graph_node_limit_capped_by_server`, the agent correctly read that as "this graph may be incomplete", and went to ripgrep — **48,735 tokens of native output on T3, more than B0's 39,404**, driven by a warning about truncation that did not happen.

This is the same defect class as W3 (`truncated: false` by construction): *a status field computed from the request instead of from the result.*

Note what this means for the proposed cap change. Raising `max_graph_nodes` to 200 makes `min(100, 200) = 100`, the clamp disappears, and the warning goes silent — so the symptom improves while the bug survives for anyone who requests more than 200. **Fix the warning; do not tune around it.**

### R3 — The imports table is indexed and never served

`index/sqlite_store.py` maintains an `imports` table, populated on every run: **579 rows across 96 files** on `bench-invoice`. No retrieval tool reads it — `imports_for_path` is called only by the indexer's own reuse path.

Import edges are the one part of this index that is *parsed rather than guessed*. They are exactly the evidence a "who depends on this module" question (T3) needs, and they carry none of the 22% lexical ambiguity. The tool currently answers dependency questions with its least reliable data while its most reliable data sits unread.

### R4 — Ambiguity is concentrated, not diffuse

The 22% ambiguous-edge rate on `bench-invoice` is not spread evenly across 601 symbols. It is a handful of common method names:

```
run 127 · available 25 · _geometry 17 · main 14 · recognise 13
__init__ 13 · set_cell_margins 12 · build 11 · get_inputs 11 · draw_box 10
```

`run` alone is 127 of 336 ambiguous edges (38%); the top ten names are roughly 75%. A full semantic backend (O4, 1–2 weeks) is the complete answer, but **file-and-module-scoped resolution** — prefer a same-file definition, then same-package, before declaring ambiguity — would resolve most of these for a fraction of the cost.

### What this means for the benchmark

In a hybrid workflow, MCP is **additive**, not substitutive: the agent pays for the tool *and* for the verification reads it prompts. The recomputed retrieval volumes show exactly that:

| Task | B0 native | B1 native + MCP | B1 total |
|---|---|---|---|
| T2-locate | 33,670 | 296 + 30,491 | 30,787 (−9%) |
| T3-impact | 39,404 | 48,735 + 8,669 | **57,404 (+46%)** |
| T5-evidence | 76,293 | 12,232 + 18,514 | 30,746 (−60%) |

T3 is not noise — it is R2 causing a false incompleteness signal, and R1/R3 leaving the agent no reliable way to enumerate callers. **Until R1–R3 are fixed, a hybrid benchmark measures the cost of distrust, not the value of retrieval.**

---

## 2.10 Plan: R-series

Ordering rule: fix what makes the agent distrust the tool before spending anything on capacity.

### R-P0 — Stop lying about truncation *(~0.5 day)*

- Emit `graph_node_limit_capped_by_server` only when the traversal actually stopped at the limit (`len(visited) >= effective_max_nodes`), not when the request was clamped. Same for `symbol_limit_capped_by_server`: fire only when the store returned exactly `effective_limit` rows.
- Add `nodes_visited`, `node_limit_reached: bool` to the impact-slice envelope so the agent can see the difference between "23 nodes, complete" and "75 nodes, stopped".
- **Acceptance:** `impact_slice` on `parse_receipt_number` at `max_nodes=100`, server cap 75, returns 23 nodes and **no** cap warning. A symbol whose graph genuinely exceeds the cap still warns.
- **Expected effect:** removes the trigger that cost T3 ~49k tokens of native re-reading.

### R-P1 — Serve the imports table *(~0.5 day)*

- New tool `get_module_dependents(repo_id, path | module)` returning importers and imported modules from the `imports` table, with `basis: "parsed_import_statements"` to distinguish it from lexical edges.
- Include `imports` and `imported_by` counts in `get_file_skeleton` and `get_index_status`.
- **Acceptance:** for any file in `bench-invoice`, the tool returns the same importer set as `rg -n "^\s*(from|import).*<module>"`, with zero ambiguous entries.
- **Why first:** it is the cheapest way to give T3-shaped questions an answer the agent can trust without verification.

### R-P2 — Body-text search *(~2 days, the one that matters)*

This is the fix for R1 and the only change that addresses why the agent reaches for `rg`.

- Add an FTS5 virtual table over symbol bodies at index time. SQLite 3.45.3 in this venv has FTS5 compiled in — verified, no new dependency.
- New tool `search_source(repo_id, query, limit, max_tokens)`: full-text match over bodies, returning `symbol_id`, path, line span and a bounded snippet — the structured equivalent of `rg -n`, with spans and IDs `rg` cannot give.
- Extend `rank_symbols` to add a body-match term so `repo_map(query=…)` stops ranking on names alone.
- Storage cost: bodies are already read during indexing; FTS5 adds roughly the source size again on disk (~800 KB for `bench-invoice`). Cap it with the existing `max_file_bytes`.
- **Acceptance:** `search_source(query="ocr")` returns ≥35 of the 41 files `rg` finds, within a stated token budget. Re-run C1 and record the coverage-per-token ratio against `rg -n`.
- **Note honestly:** this makes the tool *competitive* with ripgrep on locality, not obviously superior. Its edge remains the structured span + symbol id + graph, not raw recall.

### R-P3 — Scoped edge resolution *(~1 day)*

- Resolve an identifier against same-file definitions first, then same-package, before falling back to the global name index; mark the scope used in `EdgeRecord.evidence`.
- **Acceptance:** ambiguous-edge rate on `bench-invoice` drops from 22.0%; report the new rate and the per-name breakdown. Do not claim a target number before measuring.
- Keep `lexical_edges_are_not_complete_semantic_analysis` — scoping narrows the error, it does not eliminate it.

### R-P4 — Config, last and smallest *(~10 minutes)*

Only after R-P0. The proposed `4096 / 200 / 30` is reasonable but should be adopted for the right reason: `max_result_tokens = 4096` genuinely doubles `repo_map` coverage (16 → 33 symbols) at double the cost, which is a fair trade for orientation. `max_graph_nodes = 200` should **not** be adopted as a fix for the T3 warning — R-P0 fixes that, and raising the cap merely hides it.

Suggested settings and their measured justification:

| Key | Current | Proposed | Measured basis |
|---|---|---|---|
| `max_result_tokens` | 2,048 | 4,096 | `repo_map` coverage 3.7% → 7.3% on `bench-invoice` |
| `max_graph_nodes` | 75 | 200 | No measured effect on T3 (graph is 23 nodes); adopt only to stop clamping legitimate requests |
| `max_symbol_results` | 15 | 30 | `find_symbols("ocr")` currently truncates at 15 of 27 name matches |

### R-P5 — Two benchmark protocols, not one *(~1 day)*

The hybrid arm answers "does this help a real agent?" The MCP-only arm answers "how good is the retrieval?" They are different questions and the current single arm conflates them.

- **B1-hybrid** — current prompt. Report `retrieved_content_estimated_tokens` split by channel; expect MCP to be additive until R-P0–R-P2 land.
- **B2-mcp-first** — native shell permitted at most once per task, only to confirm a specific line already located via MCP. Any second native call fails the run. This measures retrieval completeness directly.
- Add a **verification-trigger log**: for each native command in B1, record which MCP warning preceded it. That turns "the agent didn't trust the tool" from an inference into a measurement, and would have named R2 on the first pilot.

### Order

```
R-P0  truncation honesty      0.5 d   <- removes the false signal that cost T3 ~49k tokens
R-P1  serve imports           0.5 d   <- trustworthy dependency answers, data already indexed
R-P2  body-text search (FTS5) 2 d     <- the actual reason the agent uses rg
R-P3  scoped edge resolution  1 d     <- 22% ambiguity is 10 names, not 601 symbols
R-P4  config bump             10 min  <- only after R-P0, and only for coverage
R-P5  split the protocols     1 d     <- then re-run 5 tasks x 3 seeds
```

**Do not re-run the full C3 matrix before R-P0 and R-P2.** The current agent behaviour is a rational response to a tool that under-reports its own completeness and cannot search bodies; 30 runs would measure that response 30 times.

### R-series implementation status (2026-08-28)

R-P0 through R-P5 are now implemented:

- impact and symbol cap warnings are based on actual omitted results, with
  nodes_visited and node_limit_reached;
- get_module_dependents serves parsed import relationships and import counts;
- FTS5 indexes symbol bodies and complete indexed source files; search_source
  returns bounded snippets, spans and source-backed IDs;
- lexical resolution prefers same-file and same-package definitions before the
  global name index;
- the live registry is set to max_result_tokens=4096, max_graph_nodes=200
  and max_symbol_results=30.

On the rebuilt bench-invoice index, search_source(query="ocr", limit=100,
max_tokens=4096) returned 41 files in 3,900 estimated tokens with no
truncation; 36 matches were associated with a symbol ID. R-P5 is implemented
in the runner (hybrid and mcp-first protocols plus verification-trigger
logging). The full 5-task × 3-seed C3 matrix remains pending.

---

## 2.11 Adaptive budgets and elasticity — measured basis (2026-08-28)

An independent verification pass raised three things: MCP figures were mixing service payload with wire payload, `repo_map@1024` returns only 8 symbols, and `repo_map@1024` takes ~15 s rather than ~1 s. All three reproduce. Root causes below; two are not what they look like.

### E1 — 8 symbols is an encoding problem, not a capacity problem

`repo_map` fills `budget_tokens` with whole entries. Measured cost of one entry on `invoice-scanner`:

```json
{"rank": 75.75,
 "symbol": {"symbol_id": "python:src/invoice_core/contracts.py:ScanResult:b5482a5c4f4ad30c",
            "path": "src/invoice_core/contracts.py", "name": "ScanResult",
            "qualified_name": "ScanResult", "kind": "class", "signature": "class ScanResult",
            "start_line": 60, "end_line": 76, "is_private": false},
 "evidence": [{"path": "src/invoice_core/contracts.py", "start_line": 60,
               "end_line": 76, "sha256": "73ca8b5fa606"}]}
```

| | tokens |
|---|---|
| `symbol` | 71 |
| `evidence` | 26 |
| `rank` | 2 |
| **entry total** | **107** |
| **minimal useful form** `src/invoice_core/contracts.py:60 class ScanResult` | **13** |

**8.2x of every entry is redundancy**, and it is mechanical:

- `evidence` repeats `path`, `start_line`, `end_line` already present in `symbol`, plus a digest identical for every symbol in the same file.
- `symbol_id` already encodes `path` + `qualified_name`; both are then repeated as their own fields.
- `qualified_name` equals `name` for every top-level symbol.
- `is_private` is `name.startswith("_")`.

Coverage at each budget, measured (503 non-test symbols):

| budget | wire | kept | omitted | coverage | tok/symbol |
|---|---|---|---|---|---|
| 512 | 495 | 3 | 500 | 0.6% | 165 |
| 1,024 | 1,051 | 8 | 495 | 1.6% | 131 |
| 2,048 | 2,049 | 16 | 487 | 3.2% | 128 |
| 4,096 | 4,110 | 33 | 470 | 6.6% | 125 |

At ~13 tok/entry the same 1,024-token budget would carry roughly **70 symbols instead of 8**. Raising the cap to 4,096 — four times the context cost — buys 33. **Cheaper entries beat a bigger cap by an order of magnitude, and cost nothing per call.**

### E2 — The 15 s is three N+1 query loops, not freshness

Profiling `repo_map@1024`: **1,077 SQLite `execute` calls, 7.71 s of 9.05 s total.**

| Site | Calls | Time | Fix |
|---|---|---|---|
| `_evidence_for_symbol` → `store.file(path)` per ranked entry | 565 | 4.31 s | Load the files table once into a dict |
| `pack_by_budget` render lambda → `store.edges_from()` per candidate | 503 | 3.77 s | `store.edges()` — one query |
| `_freshness` re-hash, invoked once per `build_response` attempt | 7 | 0.82 s | Compute once per request |

`store.edges()` already exists and returns all 1,658 edges in **0.02 s** against 5.82 s for the N+1 loop — a measured **248x**. And note the packer calls its render function on all 503 candidates to keep 8: the cost scales with the *index*, not with the budget.

Freshness was the suspect in W8/O3 and is **not** the problem here — 220 files re-hash in 0.09 s. It would matter on `video-lecturer` (4,559 files); it does not matter at this scale.

### E3 — `search_source` exceeds the cap it was given

With `max_result_tokens = 4096`, `search_source(query="ocr", max_tokens=4096)` returns a **4,173-token wire payload** — 77 over. The independent report is right that `calls_over_server_cap` should read 1 for that measurement.

The cause is the one W1 left open: `_pack_to_budget` bounds the *service* payload, and the `content` summary line plus `CallToolResult` framing is added afterwards, outside the budget. Every tool therefore overshoots by a small, variable amount. It only crosses the line when a call is packed close to the ceiling, which `search_source` at 4096 is.

### E4 — The hard-coded surface

Every one of these is a compile-time constant today, and each one is a policy that should vary by repository size or task shape:

| Constant | Value | Where | Should depend on |
|---|---|---|---|
| `budget_tokens` default | 1024 | `server.py:55` | task class |
| `max_tokens` (`file_skeleton`) | 1024 | `server.py:122` | file size |
| `max_tokens` (`symbol_context`) | 2048 | `server.py:141` | depth, `include_body` |
| `limit` (`find_symbols`, `search_source`) | 20 | `server.py:75,103` | task class |
| `depth` / `max_nodes` (`impact_slice`) | 2 / 100 | `server.py:165-166` | graph size |
| `depth` range | 0–3 | `service.py:501,576` | fixed is defensible; document why |
| `limit` range | 1–100 | `service.py:201,281` | index size |
| ranking weights | `2.0 / 0.5 / 8.0 / 12.0 / 0.25` | `ranking.py:24-30` | never tuned; no evaluation exists |
| `max_edges_per_symbol` | 100 | `lexical_edges.py:12` | symbol body length |
| edge confidence | `0.55 / 0.2` | `lexical_edges.py:42` | should come from a calibration, not a literal |

The ranking weights deserve a flag: `12.0` and `8.0` are large enough to dominate graph degree entirely, and **no measurement has ever justified any of the five numbers.** Making them configurable without an evaluation only moves the guess into a file.

---

## 2.12 Plan: E-series (elastic budgets)

### E-P0 — Make entries cheap before making budgets bigger *(~1 day)*

The single highest-leverage change in this document. Nothing else in the E-series matters as much.

- Drop `evidence` from `repo_map` entries; it duplicates fields already present. Keep the file digest **once per response** in a `file_digests` map keyed by path, not once per symbol.
- Drop `qualified_name` when it equals `name`; drop `is_private` (derivable); drop `path` and `qualified_name` from the entry when `symbol_id` already carries them, or shorten `symbol_id` to an opaque index key and keep the readable fields.
- Add `format: "compact" | "full"` to `repo_map`, defaulting to compact. Full stays available for callers that want provenance per symbol.
- **Acceptance:** entry cost ≤ 25 tokens; `repo_map@1024` returns ≥ 40 symbols on `invoice-scanner`; `evals/measure_context_cost.py` records the new tok/symbol figure. Do not claim a specific coverage number in advance of that run.

### E-P1 — Eliminate the three N+1 loops *(~0.5 day)*

- `repo_map`: one `store.edges()` call instead of 503 `edges_from()` calls.
- `_evidence_for_symbol` / `_repo_map_entry`: hoist `store.files()` into a `dict[path, FileRecord]` per request.
- `_freshness`: compute once per request, pass the result into `build_response`.
- Add `mtime_ns` + `size` pre-check before hashing (the W8/O3 item), so this stays cheap on 4,000-file repositories even though it is not the bottleneck at 220.
- **Acceptance:** `repo_map@1024` on `invoice-scanner` under 1 s; SQLite `execute` count under 20 per call. Assert the query count in a test — a count is what makes an N+1 regression visible.

### E-P2 — Budget the wire, not the service payload *(~0.5 day)*

Finishes what W1 started and closes E3.

- Move budget enforcement to the outermost layer: pack against the serialised `CallToolResult`, or reserve a measured allowance for the envelope and summary before packing.
- **Acceptance:** for every tool at every budget on both repositories, `wire_tokens ≤ max_result_tokens`; `calls_over_server_cap` is 0 including `search_source(ocr)@4096`.

### E-P3 — Per-task budget profiles *(~1 day)*

Only after E-P0, because the right budget depends on what an entry costs.

Add a `[budget_profiles]` config block with named profiles the caller selects by intent, rather than guessing token counts:

```toml
[budget_profiles.locate]      # "where is X" - few precise hits
tools = ["find_symbols", "search_source"]
budget_tokens = 1024
limit = 30

[budget_profiles.orient]      # "what is in this repo" - breadth
tools = ["repo_map"]
budget_tokens = 4096
format = "compact"

[budget_profiles.impact]      # "what breaks if I change X" - graph
tools = ["impact_slice", "get_module_dependents"]
budget_tokens = 4096
max_nodes = 200
depth = 2

[budget_profiles.read]        # "show me this file/symbol"
tools = ["file_skeleton", "symbol_context"]
budget_tokens = 2048
include_body = true
```

- New optional `profile` argument on each tool; explicit arguments always win over the profile.
- `list_repositories` returns the available profile names and their budgets, so an agent can pick one instead of inventing a number — the same discoverability failure as W13, applied to budgets.
- **Do not** make profiles adjust themselves automatically from index size in this step. Ship fixed named profiles first, measure which one each task class actually picks, then consider derivation. A self-tuning budget that nobody has measured is a second layer of guessing.

### E-P4 — Scale-aware defaults *(~0.5 day)*

Where a default genuinely should track repository size:

- `max_edges_per_symbol`: derive from median symbol body length rather than a flat 100.
- `find_symbols` / `search_source` `limit` ceiling: scale with indexed symbol count, floor 30, cap 100.
- `impact_slice` `max_nodes` default: `min(server_cap, 2 x median_component_size)` measured at index time and stored in the manifest.
- Record every derived value in the index manifest so a response can state which policy produced it.
- **Acceptance:** two repositories of very different size get different derived defaults, and both are visible in `get_index_status`.

### E-P5 — Do not make ranking weights configurable yet *(0 days — a decision, not work)*

`ranking.py` carries five untuned constants. Exposing them as config would let a caller tune a scoring function that has never been evaluated against any relevance judgement. **Leave them hard-coded and add a comment saying they are unevaluated**, until there is a labelled set of (query, relevant-symbol) pairs to tune against. That set is the prerequisite, not the config plumbing.

The same applies to `lexical_edges.py`'s `0.55 / 0.2` confidences: they should become measurements (R-P3 scoped resolution, then a calibration), never config knobs.

### Order

```
E-P0  cheap entries          1 d     <- 8x more symbols per token, no capacity change
E-P1  kill the N+1 loops     0.5 d   <- 15 s -> under 1 s, measured 248x on edges alone
E-P2  budget the wire        0.5 d   <- closes the search_source over-cap
 |
E-P3  per-task profiles      1 d     <- meaningful only once an entry is cheap
E-P4  scale-aware defaults   0.5 d
E-P5  ranking stays fixed    0 d     <- decision: no tuning without an evaluation set
```

**E-P0 before E-P3.** Tuning budgets while each entry wastes 8x is optimising the wrong variable: at 13 tokens per entry the default 1,024 budget already outperforms today's 4,096.

### E-series implementation status (2026-08-28)

E-P0 and E-P1 are implemented and verified:

- compact `repo_map` is now the default; each symbol is `[short_id, path:line, kind/name, optional rank marker]`, with file digests emitted once in `file_digests`;
- `format="full"` preserves the old per-symbol evidence form for callers that need provenance;
- compact `repo_map@1024` on the live `invoice-scanner` index returned 40 symbols; the largest serialized entry was 24 estimated tokens and the mean was 17.4;
- `repo_map@1024` completed in about 0.16 seconds and used three SQLite statements (files, symbols, edges), satisfying the under-one-second and under-20-query acceptance checks;
- freshness is computed once per request, file records are cached per request, and the existing `mtime_ns`/size pre-check avoids hashing unchanged files.
- ranking weights remain hard-coded with an explicit note that they are unevaluated; no tuning knob was added without a labelled relevance set.

The measurement harness now records returned symbols, tokens per symbol, entry-size statistics, elapsed time and SQLite statement count. The service payload for `repo_map@1024` was 1,015 estimated tokens and the MCP-wire estimate was 1,090 because the outer result envelope still costs tokens. E-P2 remains open for budgeting the complete wire result; `search_source(ocr)@4096` is still over the configured wire cap.

---

## 2.13 Ranking specification — measured against a labelled set (2026-08-28)

Two orientation reports on `invoice-scanner`, one native-only and one token-context, disagreed on the architecture. Checking both against the repository showed the MCP report was wrong on two facts, and the cause was ranking, not capacity. This section specifies the fix and the measurement that gates it.

### The baseline, measured

`evals/rank_eval.py` against `evals/relevance/orientation_invoice_scanner.json`, `repo_map@4096`, k=10:

```
 #  grade  symbol                       path
 1      3  ScanResult                   src/invoice_core/contracts.py
 2      2  PageDetection                src/invoice_core/contracts.py
 3      2  OcrResult                    src/invoice_core/contracts.py
 4      0  rgb                          scripts/build_s0_s6_report_revised.py   <- noise
 5      -  probe                        src/invoice_frontend_dl/degradation.py
 6      1  QualityReport                src/invoice_core/contracts.py
 7      1  TextBox                      src/invoice_core/contracts.py
 8      0  merge                        src/invoice_core/config.py              <- noise
 9      0  audit                        scripts/prepare_datasets.py             <- noise
10      1  GeometryInfo                 src/invoice_core/contracts.py

essential recall : 1/6 = 0.167
essential missing: InvoiceProcessor, FrontendPipeline, GeomFrontend, DlFrontend, get_frontend
noise in top-10  : 3
nDCG@10          : 0.4235
```

Five of six essential symbols never surface, three of ten slots are noise, and six of ten come from one file. This is the measurement the fix has to move.

### Why the current formula inverts architectural importance

`ranking.py` scores `1.0 + 2.0*in_degree + 0.5*out_degree + 8.0*per query term + 12.0*<exact> + 0.25*<class>`. In-degree dominates, and in-degree measures *how often a name is referenced*, which in a typed codebase means **data types outrank logic**:

| Symbol | grade | in | out | shape | class |
|---|---|---|---|---|---|
| `ScanResult` | 3 | 36 | 5 | connector | src |
| `InvoiceProcessor` | 3 | 5 | 18 | connector | src |
| `DlFrontend` | 3 | 6 | 10 | connector | src |
| `get_frontend` | 3 | 5 | 3 | connector | src |
| `FrontendPipeline` | 3 | 2 | 2 | connector | src |
| `GeomFrontend` | 3 | 1 | 2 | near-source | src |
| `rgb` | 0 | 24 | 0 | **pure sink** | **scripts** |
| `merge` | 0 | 16 | 0 | **pure sink** | src |
| `audit` | 0 | 14 | 1 | connector | **scripts** |
| `build_document` | 0 | 1 | 28 | **near-source** | **scripts** |

`rgb`, a colour helper in a report generator, outranks `InvoiceProcessor` — the orchestrator and the most-named symbol in the design docs — by five times on in-degree alone.

Three structural reasons the essentials score low:

- **Orchestrators are called, not referenced.** `InvoiceProcessor` is the declared console-script entry; nothing names it internally.
- **Protocols have almost no references.** `FrontendPipeline` (in=2) is the interface both competing frontends implement.
- **Registry wiring is string-keyed.** `register("geom", GeomFrontend)` and `register("dl", DlFrontend)` mean each frontend has one lexical reference. `GeomFrontend` at in=1 never surfaces — which is exactly why the MCP report described an A/B architecture **missing one of its two branches**.

Switching to out-degree does not help: its top four are `build_document` (28), `EnsembleAdapter` (24), `_build_tab` (21) and a unit test (19). **Neither degree alone identifies architecturally central code.**

### Specification

Three changes, in order of evidence strength. Signals 1 and 2 are facts read from the parse tree and the project manifest; signal 3 is a heuristic and is weighted accordingly.

**S1 — Structural role markers (hard evidence, promotes).**
Recorded at index time as `SymbolRecord.roles: list[str]`, each with the evidence that produced it:

| Role | Detected from | Applies to |
|---|---|---|
| `protocol_definition` | Tree-sitter: class with a `Protocol` base | `FrontendPipeline`, `OcrEngine` |
| `protocol_implementation` | class whose method set covers a known Protocol, or registered via a factory typed as one | `GeomFrontend`, `DlFrontend`, `PassthroughFrontend`, the three OCR engines |
| `declared_entry_point` | `[project.scripts]` / `[project.entry-points]` in `pyproject.toml` | `invoice_backend.processor:main` |
| `module_entry_point` | `if __name__ == "__main__"` in the defining module | `app.py` and 11 scripts |
| `registry_wiring` | call to a function whose parameter is typed as a Protocol | `register`, `get_frontend` |

These are the only signals that can surface `FrontendPipeline` (in=2) and `GeomFrontend` (in=1). No weighting of degree reaches them.

**S2 — Degree shape, not degree magnitude (demotes).**
Replace `2.0*in + 0.5*out` with a term over the *shape* of the pair:

- `out == 0` → pure sink. Leaf utility or data type; cap its contribution.
- `in <= 1` → near-source. Script root or dead code; cap its contribution.
- both non-trivial → connector; this is the shape every grade-3 symbol has except `GeomFrontend`.

This alone demotes `rgb` (24/0), `merge` (16/0) and `build_document` (1/28) — three of the four labelled noise items — without touching any essential.

**S3 — Path class (heuristic, weak weight).**
`src` 209 symbols, `tests` 164, `scripts` 153, `ui` 70, `evaluation` 62. For an orientation task `scripts/` and `evaluation/` are tooling, not architecture. Apply a modest demotion, **configurable per repository**, and record which class produced the adjustment in the response so a caller can see it. This is the one signal here that is a guess; it must not outweigh S1.

**Not in scope.** `include_tests=False` already excludes `tests/`. Query-term weights (`8.0`, `12.0`) stay untouched: this set has `query: null`, so it cannot evaluate them, and tuning a weight a set cannot measure is how the current numbers got there.

### The labelled set

`evals/relevance/orientation_invoice_scanner.json` — 22 symbols graded 0–3, each carrying the evidence for its grade. Labels come from repository evidence (design-doc mentions, `pyproject.toml`, Protocol definitions, registry keys), **not** from either agent's output; the two reports are treated as hypotheses that the set checks.

The grade-0 items are the discriminating half. `build_document` is included specifically so that a naive switch to out-degree ranking also fails.

Stated limits, in the file itself: one repository, one task, 22 symbols, `query: null`. **This set can detect a gross ranking inversion. It cannot establish that one ranking is generally better than another.** Treat a passing score as "the known defect is gone", never as "ranking is good".

### Acceptance

Run `python evals/rank_eval.py --set evals/relevance/orientation_invoice_scanner.json --budget 4096 --compare evals/reports/rank-before.json`:

| Metric | Before | Target |
|---|---|---|
| essential recall @10 | 0.167 (1/6) | **≥ 0.67 (4/6)** |
| noise in top-10 | 3 | **0** |
| nDCG@10 | 0.4235 | **≥ 0.70** |

`GeomFrontend` (in=1, near-source) is the hardest item and is deliberately excluded from the 4/6 target: reaching it requires S1 `protocol_implementation` detection to work through the registry indirection. If it surfaces, the S1 implementation is genuinely working.

Additional gate: `evals/measure_context_cost.py` must show no regression in tok/symbol, and `repo_map@1024` must still return ≥40 symbols on `invoice-scanner`. Ranking is not allowed to buy relevance with payload size.

### A capability neither report delivered

`pyproject.toml` declares `invoice-scan = "invoice_backend.processor:main"`, and **`processor.py` defines no `main`**. Both orientation reports repeated the declaration as fact; the native one read the file and still missed it, because it read the file for something else.

Resolving declared entry points against indexed symbols is one query against data already in the index, and ripgrep cannot do it without being told what to look for. Add it to `get_index_status` as `entry_points: [{declared, resolved: bool}]`. It is a small, concrete answer to "what does the index give me that grep does not" — worth more to that argument than any token ratio in this document.

---

## 2.14 SWOT — the "Semantic Graph Bootstrapping" proposal (2026-08-28)

Proposal: run a **one-time warm-up** in which an LLM reads the whole codebase and labels each node semantically (`ENTRYPOINT` / `CORE_LOGIC` / `CONTRACT` / `UTILITY`), persist that to a local graph DB, then serve **pure-MCP runtime** with two-tier seed-node retrieval and Personalized PageRank.

Assessed below against the repository and against this package's architectural constraints.

### What the proposal gets right, independently confirmed

The "high in-degree trap" diagnosis is **correct**, and §2.13 measured it before this proposal was read: `rgb` (in=24, a colour helper in a report script) outranks `InvoiceProcessor` (in=5, the orchestrator) **five to one**. `essential recall @10 = 1/6`. This is a measured defect, not a theoretical concern.

Three of its technical suggestions also point the right way:

- **Node categorization** overlaps substantially with **S1** in §2.13.
- **Personalized PageRank / seed-biased walk** is the right direction and **needs no LLM**.
- **Lazy two-tier retrieval** is achievable with today's tools: `find_symbols` → `symbol_context` → `impact_slice`. That is a **protocol** change, not a code change.

### Strengths — where adoption pays

- **Categorization solves what ranking cannot.** `FrontendPipeline` (in=2) and `GeomFrontend` (in=1) cannot be surfaced by any weighting of degree. Only role labels reach them.
- **Separating warm-up from runtime matches the existing architecture.** `index` is already an admin command that writes the snapshot; `serve` is already read-only.
- **The cost can be incremental, not one-time.** The indexer already tracks `files_reused` / `files_reparsed` by sha256. Semantic labels can be cached per file hash and recomputed only for changed files, turning "220k tokens every warm-up" into "a few hundred tokens per commit".
- **Seed-biased ranking sidesteps the root problem.** Global PageRank asks "what matters most in this repo" — the question `rgb` wins. Seed-biased PPR asks "what matters *to this problem*" — the right question, and no LLM is required.

### Weaknesses — where the proposal is wrong for this repository

- **Folder-name damping fires on nothing.** The proposal suggests demoting `utils/`, `helpers/`, `log/`, `common/`, `constants/` by 70%. This repository has **none of those directories**, and the noise item `merge` lives in `src/invoice_core/config.py` — a legitimate `src/` path. The heuristic **misses exactly what it targets**.
- **The "hidden edges" concern names the wrong mechanism.** It worries about decorators (`@router.get`), DI (`Depends()`) and event-driven dispatch. Grepping all of `src/` and `ui/`: **none of those patterns exist here**. The real hidden edge is **string-keyed registry dispatch**: `register("geom", GeomFrontend)`. An LLM reading the code would *guess* that link, not resolve it. The honest fix remains a semantic backend (O4), not LLM labels.
- **"90–95% token reduction" is unevidenced and contradicted.** §2.9 measured MCP as **additive** in a hybrid workflow, with T3 retrieval volume up 46%. On orientation, native was both cheaper and more accurate. Nothing in this project supports 90–95%.
- **"100% accurate context" does not hold.** LLM labels are **inferences**, not parse facts. They can be wrong, and wrong invisibly.
- **Warm-up cost scales badly.** `invoice-scanner` at 220,576 tokens is feasible. `video-lecturer` at **1,841,549 tokens** exceeds most context windows. "Read everything once" fails at exactly the scale where the tool matters most.

### Opportunities

- **Take the categorization, drop the LLM.** §2.13 S1 already specifies five roles derived from **parse evidence**: `protocol_definition`, `protocol_implementation`, `declared_entry_point`, `module_entry_point`, `registry_wiring`. Cheaper, **verifiable**, no network, and it produces the label class the proposal wants.
- **If LLM labels are still wanted, put them in the admin tier.** A separate `token-context enrich --repo-id X`, run outside the server, writing to a **separate table** with `basis: "llm_inferred"` plus model id and prompt hash. The server stays read-only. This is the only path that does not break the security boundary.
- **Seed-node PPR is the highest-value item that needs no LLM at all.**
- **Two-tier retrieval can be trialled today** — no new code, just a prompt protocol, measured with `rank_eval.py` and `measure_context_cost.py`.

### Threats

- **It breaks the read-only boundary.** `SECURITY.md:3` states the package *"deliberately has no tools for shell execution, **writes**, reindexing, registration or arbitrary filesystem paths"*. A "label then persist" loop requires the write path the project deliberately refuses. Letting an agent write labels back through MCP collapses the whole security model.
- **No network calls are permitted.** `README:17`: the server *"does not edit files, execute shell commands, listen on HTTP, **call network APIs**"*. It cannot call an LLM itself, and D-003 forbids it besides.
- **Provenance collapse — the largest threat.** This package's distinguishing property is that **every claim carries its evidence**: `completeness.basis`, SHA-256-backed `evidence`, the `lexical_edges_are_not_complete_semantic_analysis` warning. Mixing LLM labels into the same index without a provenance boundary converts a tool that *knows its limits* into one that *guesses confidently* — precisely what this document spent weeks removing from Task 2.
- **Stale labels are more dangerous than a stale index.** A stale index is caught by `freshness` via sha256. A stale semantic label — "this module is CORE_LOGIC" — keeps *looking* right long after the code changed role. It needs a TTL and hash binding, or it silently misleads.
- **LLM labels cannot be validated without a labelled set.** The proposal assumes the LLM assigns roles correctly. `orientation_invoice_scanner.json` exists to test exactly that — and it has 22 items on one repository. Shipping LLM labels before an evaluation set repeats the mistake the current ranking weights represent: numbers nobody measured.

### Verdict

| Component | Feasible | Note |
|---|---|---|
| In-degree trap diagnosis | **Confirmed** | Independently measured in §2.13 |
| Node categorization | **Do it now** | But derive from parse (S1), not from an LLM |
| Seed-biased PPR | **Do it** | No LLM needed, high value |
| Lazy two-tier retrieval | **Trial today** | Protocol change, no code |
| Folder-name damping | **Drop** | Fires on 0 symbols here |
| sha256-keyed label cache | **Do it if enriching** | Turns one-time cost into incremental |
| LLM warm-up labelling | **Admin CLI tier only** | Never in the server; separate `basis` |
| "Pure MCP, 90–95% saving" | **Unevidenced** | Current measurements contradict it |
| "100% accurate context" | **Reject** | Inferred labels are not facts |

**Recommended order:** ship S1 + S2 from §2.13 first — parse-derived, cheap, verifiable, and already gated by an acceptance target. Re-measure with `rank_eval.py`. **Only if** essential recall still falls short should an LLM enrichment tier be considered, and then as a separate admin command, separate table, separate `basis`, with sha256-bound TTL.

The reason for that order: S1 solves the exact cases the proposal cites (`FrontendPipeline`, `GeomFrontend`) at a fraction of the cost, and **without trading away the one asset this package actually has** — that it tells the truth about what it knows.

---

## 2.15 Plan: RK-series (ranking fix)

§2.13 is a specification and §2.14 is a SWOT verdict. This section is the **ordered work breakdown** drawn from both — the piece that was missing.

Rule: every step must move a number in `rank_eval.py`, or it does not belong here.

Baseline to beat (`evals/reports/rank-before.json`):

```
essential recall @10 : 0.167 (1/6)
noise in top-10      : 3
nDCG@10              : 0.4235
```

### RK-P0 — Record structural roles at index time *(~1.5 days, the largest piece)*

Implements **S1**. The only step that can reach `FrontendPipeline` (in=2) and `GeomFrontend` (in=1).

Files changed:

| File | Work |
|---|---|
| `models.py` | Add `roles: list[str]` and `role_evidence: dict[str, str]` to `SymbolRecord` |
| `parse/treesitter.py` | Detect `protocol_definition` (class with a `Protocol` base), `module_entry_point` (`if __name__ == "__main__"`) |
| `index/runner.py` | Read `[project.scripts]` / `[project.entry-points]` from `pyproject.toml` → `declared_entry_point`; infer `protocol_implementation`; detect `registry_wiring` |
| `index/sqlite_store.py` | Add a `roles_json` column; update `_symbol_from_row` |

**Migration risk to handle:** the reuse path at `runner.py:41-47` opens the **previous** snapshot to re-read symbols by sha256. An older DB without `roles_json` will make `_symbol_from_row` raise. Two options, pick one and state it:

- Wrap the `previous_store` read in `try/except` and fall back to a full reparse (simple, one slow index run).
- Or write a `schema_version` into the `metadata` table and skip reuse on mismatch (cleaner, preferred).

The second is worth doing because it also closes an existing gap: `write_snapshot` currently just `DELETE FROM`s and re-inserts, so **nothing detects a schema change today**.

**Acceptance:** `get_index_status` reports how many symbols carry at least one role; `FrontendPipeline` and `OcrEngine` carry `protocol_definition`; `GeomFrontend` and `DlFrontend` carry `protocol_implementation`. Ranking is untouched at this step — this only records data.

### RK-P1 — Degree shape instead of degree magnitude *(~0.5 day)*

Implements **S2**. Touches `ranking.py` only.

Replace `2.0*in + 0.5*out` with a term over the pair's shape: `out == 0` → pure sink, `in <= 1` → near-source, both non-trivial → connector.

**Acceptance:** `rgb` (24/0), `merge` (16/0) and `build_document` (1/28) leave the top 10. `noise in top-10` goes from 3 to **≤1**. Run `rank_eval.py --compare rank-before.json`.

**Independent of RK-P0** — it can run in parallel, and it is the cheapest measurable improvement available.

### RK-P2 — Use roles in the ranking formula *(~0.5 day, needs RK-P0)*

Add a bonus term for `roles`, plus a light path-class demotion (**S3**, configurable, never outweighing S1). Record `rank_basis` on each entry so a caller can see which signal promoted it.

**Acceptance — this is the series' main gate:**

| Metric | Before | Target |
|---|---|---|
| essential recall @10 | 0.167 | **≥ 0.67** |
| noise in top-10 | 3 | **0** |
| nDCG@10 | 0.4235 | **≥ 0.70** |

Plus a no-regression gate: `repo_map@1024` still returns ≥40 symbols, and tok/symbol does not rise.

### RK-P3 — Resolve declared entry points *(~0.5 day, needs RK-P0)*

Add `entry_points: [{declared, resolved: bool}]` to `get_index_status`. The data exists after RK-P0.

**Acceptance:** on `invoice-scanner`, report `invoice-scan = invoice_backend.processor:main` with `resolved: false` — a real defect **both** orientation reports missed.

Small, but it is the most concrete answer available to "what does the index give me that grep does not".

### RK-P4 — Seed-biased ranking *(~1 day, needs RK-P1)*

From §2.14 — the highest-value item that needs **no LLM**.

When a call carries a `query` or `symbol_id`, score with a seed-biased random walk instead of global degree. Global PageRank asks "what matters most in this repo" — the question `rgb` wins. Seed-biased asks "what matters *to this problem*".

**Prerequisite:** a second labelled set **with a `query`**. The current set is `query: null` and therefore **cannot measure this change**. Do not implement RK-P4 before that set exists — that is exactly the mistake that produced the current `8.0` / `12.0` weights.

### RK-P5 — Trial the two-tier retrieval protocol *(~0.5 day, no code)*

From §2.14. A prompt protocol only: start with `find_symbols` / `search_source`, expand with `symbol_context` depth=1, fetch bodies only for filtered nodes. Measure with `measure_context_cost.py` and a separate C3 arm.

Can be trialled **today**, independent of everything above.

### Explicitly out of scope

- **Query-term weights `8.0` / `12.0`** — the current set is `query: null` and cannot measure them. Leave them alone.
- **LLM-generated semantic labels** — §2.14's verdict: admin CLI tier only, separate table, separate `basis`, and only **if** RK-P2 misses its gate.
- **Folder-name damping** — fires on 0 symbols in this repository.

### Order

```
RK-P1  degree shape          0.5 d   <- cheapest, independent, drops 3 noise items
RK-P0  roles at index time   1.5 d   <- can run in parallel with RK-P1
 |
RK-P2  roles into ranking    0.5 d   <- MAIN GATE (recall >=0.67, noise 0)
RK-P3  entry point resolution 0.5 d
 |
[needs a second labelled set with a query]
RK-P4  seed-biased PPR         1 d
RK-P5  two-tier trial        0.5 d   <- available any time
```

**RK-P1 first** because it is cheap, independent, and moves a number immediately — confirming the `rank_eval.py` harness works before committing 1.5 days to RK-P0.

**Restating the limit:** 22 symbols, one repository, one task. Passing the gate means "the measured defect is gone", **not** "ranking is good". A stronger claim needs a second labelled set on a different repository — which is also RK-P4's prerequisite.

### RK-series implementation status (2026-08-28)

RK-P0 through RK-P3 are implemented and verified on the live `invoice-scanner`
index. The index now uses schema `2.0`, stores structural role evidence, and
reports `symbols_with_roles`, `role_counts`, and declared entry-point
resolution through `get_index_status`. The declared entry point
`invoice-scan = invoice_backend.processor:main` is reported as
`resolved: false`.

RK-P1 moved the labelled set from recall `0.167` / noise `3` / nDCG `0.4235`
to recall `0.333` / noise `0` / nDCG `0.4464`. RK-P2 then added measured role
bonuses, path damping, and `rank_basis` in full map entries. Its final result
is recall `0.833` (5/6), noise `0`, and nDCG `0.7742`; the 1024-token compact
map returns 42 symbols on `invoice-scanner` and 42 on `token-context`.

The compact pack preserves the first ten ranked symbols, then fills from
already represented files so the one-per-file digest does not consume the
breadth budget. This keeps provenance and meets the no-regression coverage
gate without changing the measured ranking head.

RK-P5 is documented in `docs/INTEGRATION.md` as a two-tier protocol:
MCP-first locating and bounded symbol expansion, followed by native read-only
verification only for concrete ambiguous or truncated source claims. A bounded
pilot completed with `mcp_health: passed`, six MCP calls, zero native commands,
and no MCP errors; the runner recorded 2,558 estimated retrieved-content
tokens and 135,852 provider total tokens (120,832 cached input). This is a
protocol-health result, not a saving claim or a substitute for paired C3.

RK-P4 remains intentionally open. The repository has no second labelled set
with a non-null `query`, so seed-biased ranking cannot yet be measured without
repeating the earlier untuned-weight mistake. The existing `search_source`
wire-cap issue belongs to E-P2, not the RK series, and remains separately
tracked.

---

## 2.16 RK-P4's labelled set, and what gates the full C3 matrix (2026-08-28)

### Correction: E-P2 is smaller than I rated it

The wire overshoot is **constant, not payload-scaling**:

| Call | service | wire | overshoot | % |
|---|---|---|---|---|
| `repo_map@512` | 493 | 568 | 75 | **15.2%** |
| `repo_map@1024` | 1,024 | 1,098 | 74 | 7.2% |
| `repo_map@4096` | 4,079 | 4,154 | 75 | 1.8% |
| `search_source(ocr)@4096` | 4,103 | 4,173 | 70 | **1.7%** |
| `find_symbols(Invoice,30)` | 993 | 1,049 | 56 | 5.6% |

It is the `content` summary line plus `CallToolResult` framing — a fixed cost that was never budgeted for, **not** a scaling defect. Fix by reserving `envelope_reserve_tokens = 96` before packing: **~30 minutes, not 0.5 day**.

One caveat survives: at small budgets the relative overshoot is far worse (15.2% at 512). If E-P3 introduces a `locate` profile at 512, this reserve becomes **mandatory** rather than optional.

**E-P2 does not gate the C3 matrix.**

### RK-P4's labelled set: use test files as a topic oracle

The hard part of a query-bearing set is ground truth. It must not come from an agent's output (self-confirming), and it must not come from `search_source` itself (that makes the measurement a tautology).

This repository ships an oracle that is **independent of every agent and every ranking**: **20 topic-named test files**, whose imports the team wrote themselves.

```
tests/unit/test_s8_ocr.py   -> s8_ocr, RapidOcrEngine, TextBox
tests/unit/test_fields.py   -> s9_fields, OcrResult, TextBox
tests/unit/test_registry.py -> registry, FrontendPipeline
tests/unit/test_s7_render.py, test_frontend_geom.py, test_ensemble.py, ...
```

**Construction, four steps:**

1. **Take topics from test file names.** `test_s8_ocr` → query `"ocr text recognition"`; `test_fields` → `"field extraction amount date"`; `test_registry` → `"frontend registry selection"`. Pick the 5–6 with the clearest topic.
2. **Grade-3 seeds are the symbols the test file imports directly.** The team declared these central to the topic by importing them to test it.
3. **Grade-2 is symbols defined in those modules that the test does not call directly.** Related, not essential.
4. **Grade-0 is noise drawn from a *different* topic.** For query `"ocr"`, include `rgb`, `merge`, and a grade-3 symbol from `test_frontend_geom`. This is the discriminating half: a globally-ranked list returns the same top-10 for **every** query, and cross-topic noise is what exposes that.

**What the set measures:** whether ranking **responds to the query at all**. A global-degree ranking produces identical output for every query, and this set names that directly. Seed-biased PPR does not.

**Limit to state in the file:** imports signal *what is tested*, not *what is relevant to a question*. An important symbol with no test is graded unfairly low. So the set compares **ranking A against ranking B on the same query**; it does not establish absolute coverage.

**Cost:** ~0.5 day, mostly reading six test files and checking each label.

### The full C3 matrix: what actually gates it

Nothing technical. The runner works, the protocols exist, `--max-mcp-calls` exists. The four items below are **design decisions to settle first**, not defects to fix.

**1. The arm count moved from 2 to 3.** RK-P5 added the bounded mcp-first protocol:

```
B0 native-only  |  B1 hybrid  |  B2 mcp-first (bounded)
5 tasks x 3 seeds x 3 arms = 45 runs
```

At 90–210 s per run that is roughly 2–2.5 hours of wall clock plus token cost. Settle two arms or three **before running**, because adding an arm afterwards breaks pairing.

**2. The primary metric is unsettled — and `total_tokens` is the wrong choice.** Your bounded pilot: **2,558 tokens of retrieved content against 120,832 cached input**. Content is 2% of the total. `total_tokens` measures **conversation length**, not retrieval efficiency — the point §2.9 raised and that is still unaddressed.

Report three metrics separately, and say which is primary:

| Metric | Measures |
|---|---|
| `retrieved_content_estimated_tokens` | **primary** — real retrieval volume |
| `uncached_input_tokens` | true marginal cost |
| `total_tokens` | secondary, dominated by turn count |

**3. There is no repeatable grading procedure.** T1–T5 have prose criteria in §2.2 but no grader. Across 45 runs the grading must be fixed **before token counts are seen**, or it walks straight into grading-after-seeing-cost.

**4. T1 is now self-grading — that is new.** `orientation_invoice_scanner.json` is ground truth for T1. Instead of a manual pass/fail, grade the report's named symbols with `essential_recall` and `noise_in_top_k`. **This is stronger evidence than tokens**: it measures correctness, and correctness is what the MCP orientation report lost on (Streamlit for Gradio, `invoice_frontend_geom` missing entirely).

### Suggested order

```
E-P2 envelope reserve         30 min    <- cheap, clears the over-cap warning
query-bearing labelled set    0.5 d     <- unblocks RK-P4
 |
RK-P4 seed-biased PPR         1 d
 |
settle arms + metric + grader 0.5 d     <- decisions, not code
full C3 matrix                2-3 h run
```

**Do not run C3 before the primary metric is settled.** Leaving `total_tokens` primary means 45 runs produce a result dominated by conversation length — exactly what the three pilots already produced, fifteen times over.

### A note on this document

It is now around 960 lines with sixteen subsections and four work series (R, E, RK, plus the original remediation). It has passed the point of comfortable navigation. `§2.7–2.16` should be split into `BENCHMARK_FINDINGS.en.md` with a pointer left behind — before a seventeenth section is added.

---
