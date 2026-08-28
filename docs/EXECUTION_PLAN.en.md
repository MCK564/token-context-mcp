# Execution plan — open items

**Date:** 2026-08-28 · **Vietnamese:** `EXECUTION_PLAN.vi.md`
**Analysis and measured basis:** `REMEDIATION_AND_BENCHMARK_PLAN.en.md` §2.7–2.16. This document carries **only the work**; it does not repeat the reasoning.

## Execution status (2026-08-28)

| Item | Status | Evidence |
|---|---|---|
| X1 envelope reserve | **done** | C1 wire reports: zero calls over the 4,096-token server cap on both repositories |
| X8 split documentation | **done** | `BENCHMARK_FINDINGS.{en,vi}.md` now carries sections 2.7–2.16 |
| X2 query-labelled set | **done** | `evals/relevance/query_invoice_scanner.json` and baseline report |
| X4 C3 protocol | **done** | `evals/c3_protocol.md`, three arms and primary content metric fixed before runs |
| X3 seed-biased ranking | **done** | five query lists differ; mean essential recall 0.667; orientation 0.833 with zero noise |
| X5 budget profiles | **done** | four discoverable profiles; profile/explicit-argument equivalence test |
| X7 scale-aware defaults | **done** | live status: invoice-scanner 667 symbols vs token-context 273, with distinct derived values |
| X6 full C3 matrix | **pending** | protocol and fail-fast runner are ready; the 45 provider sessions have not all been run |

The X6 row is intentionally not presented as complete: existing pilot rows
cannot substitute for the predeclared 5-task × 3-seed matrix.

## Verified state (2026-08-28)

| Series | Status |
|---|---|
| W1–W3 budget contract | done |
| R-P0 truncation honesty | **done** — `node_limit_reached` computed from the traversal, `nodes_visited` exposed |
| R-P1 serve imports | done — `get_module_dependents` |
| R-P2 body-text search | done — `search_source` + FTS5 |
| R-P3 scoped edge resolution | **taking effect** — ambiguity 22.0% → 15.0% (`invoice-scanner`) |
| E-P0 cheap entries | done — 107 → 24 tok/entry, 42 symbols @1024 |
| E-P1 kill N+1 | done — 1,077 → 3 queries, 13.87 s → 0.164 s |
| E-P5 keep ranking fixed | done (decision), now **superseded** by RK |
| RK-P0…P3, P5 | done — recall 0.167 → 0.833; noise 3 → 0; nDCG 0.4235 → 0.7742 |

The historical open-item list below predates the X-series implementation;
the execution-status table above is authoritative for this plan.

---

## X1 — Envelope reserve *(~30 minutes)*

Closes E-P2. The overshoot is a **constant 56–75 tokens** (the `content` summary line plus `CallToolResult` framing), not payload-scaling.

- `service.py`: add `ENVELOPE_RESERVE_TOKENS = 96`; subtract it from the effective budget **before** packing, in every budgeted tool.
- Report `envelope_reserve` inside the response's `budget` so a caller can see what was withheld.

**Acceptance:** `measure_context_cost.py` reports `calls_over_server_cap: 0` on both repositories, including `search_source(ocr)@4096`.

**Note:** at a 512 budget the overshoot is 15.2%, so this is a **prerequisite** for X5's `locate` profile, not an optional tidy-up.

---

## X2 — Query-bearing labelled set *(~0.5 day)*

Unblocks X3. Ground truth comes from the **20 topic-named test files** — independent of every agent and every ranking.

Create `evals/relevance/query_invoice_scanner.json` with 5–6 topics:

| Topic | Query | Grade-3 source |
|---|---|---|
| OCR | `"ocr text recognition"` | imports of `tests/unit/test_s8_ocr.py` |
| Field extraction | `"field extraction amount date"` | `test_fields.py` |
| Registry | `"frontend registry selection"` | `test_registry.py` |
| Render | `"render display ocr input"` | `test_s7_render.py` |
| Geometry | `"page detection corners geometry"` | `test_frontend_geom.py` |

Grading rules:

- **grade 3** — symbols the test file **imports directly**. The team declared them central to the topic by importing them to test it.
- **grade 2** — symbols defined in those modules that the test does not call directly.
- **grade 0** — noise drawn from a **different topic**, plus `rgb` and `merge`. **This is the discriminating half**: a global-degree ranking returns the same top-10 for every query, and cross-topic noise is what exposes that.

State in the file: imports signal *what is tested*, not *what is relevant to a question*; an important symbol with no test is graded unfairly low. The set compares **ranking A against B on the same query**; it does not establish absolute coverage.

**Acceptance:** `rank_eval.py` runs against the new set; baseline written to `evals/reports/rank-query-before.json`.

---

## X3 — RK-P4 seed-biased ranking *(~1 day, needs X2)*

- When a call carries a `query` or `symbol_id`, score with a seed-biased random walk instead of global degree.
- Keep the global-degree path for calls without a query.
- Report `rank_mode: "global" | "seed_biased"`.

**Acceptance:** on `query_invoice_scanner.json`, against `rank-query-before.json`:
- top-10 **must differ between queries** (the global baseline returns identical output — that is the primary test);
- `essential_recall` improves on ≥4 of 5 topics;
- no regression on `orientation_invoice_scanner.json` (recall ≥0.833, noise 0).

---

## X4 — Settle three decisions before C3 *(~0.5 day, not code)*

These must be fixed **before** running, because changing them afterwards breaks pairing.

**1. Arm count.** RK-P5 added the bounded mcp-first protocol, so there are three candidates:

```
B0 native-only  |  B1 hybrid  |  B2 mcp-first (bounded)
```

`5 tasks × 3 seeds × 3 arms = 45 runs` ≈ 2–2.5 hours. Choose two or three and record the choice.

**2. Primary metric.** `total_tokens` must **not** be primary — the pilot showed 2,558 tokens of content against 120,832 cached input, so content is 2% and `total_tokens` measures conversation length.

| Metric | Role |
|---|---|
| `retrieved_content_estimated_tokens` | **primary** |
| `uncached_input_tokens` | true marginal cost |
| `total_tokens` | secondary, dominated by turn count |

**3. Grader.** Fix how T1–T5 are graded **before token counts are seen**. T1 is now self-grading: use `orientation_invoice_scanner.json` to score the symbols a report names, via `essential_recall` and `noise_in_top_k`. The other four need written pass/fail criteria, agreed in advance.

**Acceptance:** an `evals/c3_protocol.md` recording all three decisions, committed **before** the first run.

---

## X5 — E-P3 per-task budget profiles *(~1 day, needs X1)*

A `[budget_profiles]` config block; explicit arguments always win over a profile.

```toml
[budget_profiles.locate]   # "where is X"
tools = ["find_symbols", "search_source"]
budget_tokens = 1024
limit = 30

[budget_profiles.orient]   # "what is in this repo"
tools = ["repo_map"]
budget_tokens = 4096
format = "compact"

[budget_profiles.impact]   # "what breaks if I change X"
tools = ["impact_slice", "get_module_dependents"]
budget_tokens = 4096
max_nodes = 200
depth = 2

[budget_profiles.read]     # "show me this file/symbol"
tools = ["file_skeleton", "symbol_context"]
budget_tokens = 2048
include_body = true
```

- Add an optional `profile` argument to each tool.
- `list_repositories` returns profile names and budgets so an agent can **choose** rather than **invent** — the same discoverability failure as W13, applied to budgets.
- **Do not** let profiles self-tune from index size in this step. Ship fixed profiles, measure which one each task class picks, then consider derivation.

**Acceptance:** calling with `profile="locate"` yields exactly what passing that parameter set by hand yields; `list_repositories` lists the profiles.

---

## X6 — Full C3 matrix *(2–3 hours run, needs X4)*

Run under the protocol settled in X4. The runner, `--max-mcp-calls` and fail-fast are all in place — **nothing technical is blocking**.

**Acceptance:** `benchmark-report` produces a summary with full `paired_count`; the report names the primary metric; every saving claim carries a confidence interval and a sample size.

---

## X7 — E-P4 scale-aware defaults *(~0.5 day, optional)*

- `max_edges_per_symbol`: derive from median symbol body length instead of a flat 100.
- `limit` ceiling: scale with indexed symbol count, floor 30, cap 100.
- `impact_slice` `max_nodes` default: measured at index time, stored in the manifest.
- Record every derived value in the manifest and expose it via `get_index_status`.

**Acceptance:** two repositories of different size get different derived defaults, both visible.

---

## X8 — Split the documentation *(~30 minutes)*

`REMEDIATION_AND_BENCHMARK_PLAN.{vi,en}.md` is now 1,149 lines, sixteen subsections, four work series.

- Move `§2.7–2.16` into `BENCHMARK_FINDINGS.{vi,en}.md`.
- Leave a pointer in the original.
- Keep `§0–2.6` (original remediation) and `§3–5` (roadmap, order, regression tests) in place.

---

## Order

```
X1  envelope reserve       30 min    <- independent, do now
X8  split the docs         30 min    <- independent, do now
 |
X2  query labelled set     0.5 d
X4  settle C3 protocol     0.5 d     <- parallel with X2
 |
X3  seed-biased ranking    1 d       (needs X2)
X5  budget profiles        1 d       (needs X1, parallel with X3)
 |
X6  full C3 matrix         2-3 h     (needs X4)
 |
X7  scale-aware defaults   0.5 d     (optional)
```

Critical path: **~3.5 days** plus 2–3 hours of runtime.

**Two stop rules:**

- **Do not run X6 before X4 settles the primary metric.** Leaving `total_tokens` primary means 45 runs produce a result dominated by conversation length — exactly what the three pilots already produced, fifteen times over.
- **Do not implement X3 before X2 exists.** Implementing seed-biased ranking without being able to measure it is the mistake that produced the original `8.0` / `12.0` weights.
