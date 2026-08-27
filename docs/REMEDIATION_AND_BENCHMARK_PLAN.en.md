# token-context-mcp — Remediation Priority, Benchmark Design, Opportunity Roadmap

**Created:** 2026-08-27 · **Against:** 0.1.0 @ `791ddce`
**Companion:** `PIPELINE_EXPLAINED.en.md` (architecture + SWOT)
**Every number below is measured on this machine**, on three registered repositories of increasing size.

---

## 0. The measured "before" state

A third repository was indexed to test whether the SWOT findings scale: `invoice-scanner` — 124 Python files, 882 KB, 667 symbols, 1,658 edges.

### 0.1 The saving is real and grows with repository size

| Repository | Symbols | Baseline (read all `.py`) | `repo_map`@1024 payload | **Real saving** |
|---|---|---|---|---|
| `token-context` | 134 | 20,370 tok | 7,803 tok | 2.6x |
| `task2-demo` | 202 | 68,259 tok | 8,849 tok | 7.7x |
| **`invoice-scanner`** | **667** | **220,576 tok** | **8,823 tok** | **25.0x** |

This is the strongest argument for the tool and it was not previously measured: **the payload stays roughly constant (~8.8k) while the baseline grows linearly**, so the saving multiplies with repository size. At 667 symbols the tool returns 1/25th of the naive read.

### 0.2 The accounting bug does *not* shrink with size

| Call | Declared `estimated_tokens` | Actual payload | Gap |
|---|---|---|---|
| `repo_map`@1024 | 1,024 | 8,823 | **8.6x** |
| `repo_map`@2048 | 2,046 | 14,349 | 7.0x |
| `symbol_context`@1024 | 47 | 1,510 | **32.1x** |
| `symbol_context`@2048 | 47 | 1,510 | **32.1x — identical, `max_tokens` does not bind** |
| `impact_slice`(d2,n75) | 6,149 | 7,480 | `truncated: false`, **server cap is 2,048** |

### 0.2b `max_result_tokens` bounds nothing that is actually emitted

Running `evals/measure_context_cost.py` on both repositories shows the cap is violated by **3 of 8 calls**, and not only by `impact_slice`:

| Call | Payload | Server cap | |
|---|---|---|---|
| `repo_map`@512 | 5,468 | 2,048 | over |
| `repo_map`@1024 | 8,823 | 2,048 | over |
| `repo_map`@2048 | 14,349 | 2,048 | over |

`_validate_budget` checks the **requested budget parameter** against `max_result_tokens`; nothing ever checks the **emitted payload**. So a server configured for 2,048 tokens routinely returns 14,349, and `repo_map`@2048 passes validation precisely because 2048 ≤ 2048. The cap is a limit on what may be *asked for*, never on what is *sent* — which makes it useless as a resource control.

This widens W2: the fix is not "give `impact_slice` a budget" but "make every response respect the server cap".

### 0.3 Ambiguity scales with size — the SWOT threat, now confirmed

| Repository | Symbols | Ambiguous edges |
|---|---|---|
| `token-context` | 134 | 18 / 498 = **3.6%** |
| `task2-demo` | 202 | 56 / 690 = **8.1%** |
| `invoice-scanner` | 667 | 356 / 1,658 = **21.5%** |

Five times the symbols, six times the ambiguity rate. Lexical resolution degrades exactly where the tool is most needed. This is not fixable by tuning — it is the documented cost of the lexical backend, and the roadmap treats it as such (§3, O4).

---

## 1. Remediation priority

Ordering rule: **fix what makes a caller act on a wrong number before fixing what merely costs tokens.** A budget that under-reports by 32x is a correctness bug in an agent's context planner, not an inefficiency.

### P0 — Correctness of the contract *(~2 days)*

**W1. Pack against the emitted entry, not the rendered string.**
`pack_by_budget` measures `f"{path}:{line} {signature}"` (20 tok) while the envelope emits the full `symbol_as_dict()` plus `evidence` (158 tok). Change the `render` callback in `repo_map`, `file_skeleton` and `symbol_context` to `lambda item: json.dumps(entry_as_emitted(item))`.
*Acceptance:* for every tool and every budget, `estimated_tokens ≤ actual_payload_tokens ≤ 1.15 × estimated_tokens`. Add a test that serialises the response and asserts the bound — the bug exists because nothing ever compared the two.

**W2. Make every response respect `max_result_tokens`.**
`_validate_budget` checks the *requested* parameter, never the *emitted* payload (§0.2b), so 3 of 8 measured calls exceed the cap — `repo_map` at every budget, plus `impact_slice`, which additionally has no `max_tokens` parameter at all and whose only bound (`max_nodes`) constrains graph nodes rather than bytes. Add `max_tokens` to `impact_slice` (default `min(2048, server.max_result_tokens)`), pack its symbols and edges through `pack_by_budget`, return `omitted_edge_count`, and add a final envelope-level assertion that the serialised response fits the cap.
*Acceptance:* `evals/measure_context_cost.py` reports `calls_over_server_cap: 0` on both repositories, including `impact_slice(depth=3, max_nodes=500)`.

**W3. Fix `truncated` when `requested_tokens == 0`.**
`_envelope` computes `(estimated > requested if requested else False)` — zero is falsy, so `truncated` is `False` by construction for `impact_slice`, `find_symbols` and `status`. Replace with an explicit `truncated: bool | None`, where `None` means "not budget-controlled" rather than "nothing was dropped".
*Acceptance:* no response reports `truncated: false` while omitting content.

W1–W3 are one coherent change: **the envelope must not state a number it did not compute.** That is the same principle the package already applies to `completeness.basis`; it simply was not applied to `budget`.

### P1 — Payload efficiency *(~1 day)*

**W4. `omitted_symbol_ids` costs more than the budget it reports against.**
2,321 tokens at `budget_tokens=1024` — 2.3x the entire request — spent listing full `python:path/to/file.py:Qualified.Name:hexdigest` strings. Replace with `omitted_count` plus at most 10 ids, behind an opt-in `include_omitted_ids`.
*Expected:* `repo_map`@1024 payload 8,823 → ~6,500.

**W5. Truncate evidence digests to 12 hex characters.**
1,633 tokens of 64-character SHA-256, one per symbol. Twelve characters retain collision resistance for change detection within one repository. *Expected:* −1,200 tok.

**W6. Drop byte offsets from emitted symbols.**
`start_byte`, `end_byte`, `body_start_byte`, `body_end_byte` are internal slicing coordinates; a caller has `start_line`/`end_line`. Keep them in SQLite, omit them from the wire. *Expected:* −800 tok.

**W7. Bind `symbol_context`'s edges.**
The `edges` array is emitted outside the packer, which is why the payload is byte-identical at 1024 and 2048. Route it through the same budget.

Combined P1 effect, projected: `repo_map`@1024 from **8,823 → ~4,300 tokens**, taking `invoice-scanner` from 25.0x to **~51x**. The measured saving roughly doubles without removing anything a caller uses.

### P2 — Operational sharp edges *(~0.5 day)*

**W8. Cheap freshness.** `_freshness` re-hashes every indexed file on *every* tool call — 220 files for `invoice-scanner`, 4,559 for `video-lecturer`. Compare `mtime_ns` and `size` first; hash only on mismatch. `FileRecord` already stores both.

**W9. `cli.py` has no `__main__` guard.** `python -m token_context_mcp.cli register …` exits 0 and does nothing — indistinguishable from success. Add the guard, or delete the module path so only `python -m token_context_mcp` exists.

**W10. `uv run token-context …` fails while the server is running** — Windows locks the console script. Document `python -m token_context_mcp` as the admin entry point in `INTEGRATION.md`.

**W11. No `unregister` / `update` command.** Re-registering raises (correctly), so the only recovery is hand-editing TOML. Add both, with `update` requiring `--force`.

### P3 — Honesty about ambiguity *(~0.5 day)*

**W12. Surface the ambiguity rate where it is acted on.** 21.5% on `invoice-scanner` is currently visible only as a boolean warning string. Put `edge_precision: {ambiguous_rate, resolved_rate, basis}` in the envelope of every graph-returning tool, and report the repository-wide rate in `status`. A caller deciding whether to trust an impact slice needs the number, not the adjective.

---

## 2. The benchmark — three comparisons, not one

The repository already ships the right harness (`benchmark-report`: paired reduction, deterministic bootstrap, quality non-inferiority delta). It has never been fed real data — `evals/sample-runs.jsonl` holds two synthetic rows. This section specifies what to feed it.

### 2.1 Freeze the target first

`invoice-scanner` is 1.5 GB, of which **code is 2.2 MB** (`weights/` 219 MB, `data/` 642 MB, `output/` 151 MB, `artifacts/` 371 MB). Copy code only:

```powershell
robocopy D:\AI\invoice_scan\invoice-scanner D:\AI\bench\invoice-scanner-frozen /E `
  /XD .venv __pycache__ weights data output artifacts .git `
  /XF *.png *.zip *.jpg
cd D:\AI\token-context-mcp
.venv\Scripts\python.exe -m token_context_mcp register --repo-id bench-invoice --root D:/AI/bench/invoice-scanner-frozen
.venv\Scripts\python.exe -m token_context_mcp index --repo-id bench-invoice
```

**Freeze it and never edit it.** A moving target makes before/after incomparable — which is precisely the confound that makes most tool benchmarks worthless.

### 2.2 The five tasks

Chosen so each exercises a different tool and has a checkable answer:

| id | Task | Primary tool | Success criterion |
|---|---|---|---|
| `T1-orient` | "List the main modules of this repository and what each is responsible for." | `repo_map` | Names ≥5 real top-level modules; no invented ones |
| `T2-locate` | "Where is invoice OCR post-processing implemented? Give file and line." | `find_symbols` | Cites a real path + line within ±10 lines |
| `T3-impact` | "If the signature of `<symbol>` changes, which call sites must be updated?" | `impact_slice` | Lists ≥1 true caller; flags that lexical edges are incomplete |
| `T4-surface` | "What is the public interface of `<module>`? Signatures only." | `file_skeleton` | All public defs, no bodies, no private symbols |
| `T5-trace` | "Trace how an invoice moves from input to stored result." | `symbol_context` + `impact_slice` | Names ≥3 stages in correct order |

Grade each **before** looking at token counts. A token win on a wrong answer is not a win, and grading after seeing the cost is how that mistake gets made.

### 2.3 Comparison C1 — does the tool save? *(deterministic, runnable today)*

Context-cost only, no provider, no cost, fully reproducible:

- **Arm A0** — naive: tokens to read every file the task plausibly touches.
- **Arm A1** — token-context: sum of actual payload tokens across the tool calls needed.

Already measured for orientation: 220,576 vs 8,823 = **25.0x**. Extend to all five tasks. This is the honest headline number and it needs no agent.

### 2.4 Comparison C2 — did the fixes help? *(deterministic, after §1)*

Same script, `0.1.0` vs `0.2.0`. Expected: `repo_map`@1024 8,823 → ~4,300; `symbol_context` gap 32.1x → ≤1.15x; `impact_slice` 7,480 → ≤2,048.

**Pin this as a regression test.** The accounting bug existed because nothing compared declared to actual; C2 is that comparison, run in CI.

### 2.5 Comparison C3 — does it save end-to-end? *(needs an agent; you must run this)*

None of `codex`, `antigravity`, `gemini`, `aider` is on `PATH` on this machine, so I cannot execute or measure this half. The protocol:

- **B0** — agent with its native file tools only, MCP disabled.
- **B1** — same agent, same model, same prompt, token-context MCP enabled, native file reads discouraged by the system prompt.
- 5 tasks × 3 seeds × 2 arms = **30 runs per agent**. Same model and temperature throughout; the only variable is tool availability.

Record one JSONL line per run, in the schema `benchmark-report` already validates:

```json
{"arm":"B1","task_id":"T2-locate","seed":1,"input_tokens":4120,"output_tokens":310,
 "total_tokens":4430,"latency_seconds":11.4,"task_success":true}
```

Then:

```powershell
.venv\Scripts\python.exe -m token_context_mcp benchmark-report `
  --input evals/invoice-runs.jsonl --output evals/reports/invoice-summary.json
```

**Use provider-reported `input_tokens`/`output_tokens`, never local estimates.** `estimate_tokens` is `bytes/4`; §0.2 is the demonstration of what happens when a local estimate is trusted as a billing figure.

Wiring per agent — all of them take the same `stdio` command; `.mcp.json.example` is the template:

| Agent | Config location |
|---|---|
| Claude Code | `.mcp.json` at project root, or user scope |
| Codex CLI/IDE | `config.toml` MCP servers section (`docs/INTEGRATION.md` §Codex) |
| Antigravity / other | any client that starts a local `stdio` process with `uv` on `PATH` |

Restart the client after registry changes — the registry is read at process start.

### 2.6 What C3 can and cannot show

It **can** show whether an agent with the tool completes the same tasks for fewer provider tokens at non-inferior quality. That is the claim worth making.

It **cannot** show a universal saving. Five tasks on one repository with one model is one data point, and the honest write-up says so — as `BENCHMARK.md` already does. Expect C3 to show a *smaller* reduction than C1's 25x: an agent still spends tokens on reasoning and output, and the tool only compresses the retrieval half.

**Prediction, recorded now so it can be wrong:** C1 ≈ 25x on orientation, C3 ≈ 1.5–3x on total tokens for the same tasks. If C3 comes back near 1.0x, the likely cause is the agent reading files anyway despite the tool being available — check tool-call logs before concluding the tool does not help.

---

## 3. Opportunity roadmap — after the fixes ship

Sequenced by *evidence unlocked per unit of work*, not by appeal.

**O1 — Publish the C1/C2 numbers. (1 day, after §1)**
The repository's central claim is currently unevidenced. C1 and C2 are deterministic, need no provider, and turn "designed to reduce crawling" into a measured ratio with a stated method. Highest value per hour in the entire roadmap. Put the table in `README.md` with the measurement script alongside it.

**O2 — Run C3 on one agent. (2–3 days, mostly your time)**
Converts the claim from "smaller context packets" to "fewer tokens for the same completed task". Do one agent well rather than three badly.

**O3 — Cheap freshness. (0.5 day)** = W8. Makes the tool usable on large repositories where it currently re-hashes thousands of files per call.

**O4 — Activate a semantic backend. (1–2 weeks)**
The single largest quality lever, and the answer to §0.3's 21.5% ambiguity. `SemanticBackendStatus` is already designed and both stubs state their conditions: a pinned, sandboxed language server validated on a language-specific corpus. Start with Python and `pyright`, keep `backend: "lexical"` as the fallback, and let `confidence` become a measurement rather than the constants 0.55/0.2. **Gate it on a precision evaluation** — an unvalidated semantic backend that silently mis-resolves is worse than an honest lexical one.

**O5 — More languages. (0.5 day each)**
One `SUPPORTED_EXTENSIONS` entry plus one `_NODE_KINDS` block. Go and Rust first — both have clean Tree-sitter grammars and clear function/method/type node kinds.

**O6 — Distribution. (1–2 days, only after O1)**
Tag `v0.2.0`, publish to PyPI, add a GitHub Actions run of the test suite plus the C2 regression. `supply-chain/sbom.cdx.json` and `provenance.intoto.json` already exist and are currently unsigned starters — sign them in the release workflow. **Do not distribute before O1:** a tool whose headline claim is token saving should ship with the measurement, not a promise of one.

**O7 — `unregister` / `update`. (0.5 day)** = W11. Small, and the first thing anyone hits after a typo in a path.

---

## 4. Order of work

```
P0  W1-W3  contract correctness      2 d   <- an agent is currently mis-planning context by up to 32x
 |
P1  W4-W7  payload efficiency        1 d   <- 25x -> ~51x, no loss of usable content
 |
C1 + C2    deterministic benchmark   1 d   <- the evidence, and the regression test
 |
O1         publish the numbers       1 d
 |
P2  W8-W11 operational edges        0.5 d
P3  W12    ambiguity in envelope    0.5 d
 |
O2         C3 with one agent        2-3 d  (your time; no agent CLI on this machine)
 |
O6         tag, PyPI, CI            1-2 d
 |
O4         semantic backend         1-2 wk (gated on precision evaluation)
O5         Go + Rust                 1 d
```

**Why P0 before everything.** The tool's purpose is to let an agent plan its context. An agent that reads `budget.estimated_tokens = 47` and receives 1,510 tokens has been given a number that is wrong in the direction that causes overruns. Publishing a saving measured with that bug in place would mean publishing a number the code cannot honour.

**Why C1/C2 before C3.** They are deterministic, cost nothing, and would have caught the accounting bug on day one. C3 is more persuasive but far more expensive and confounded by agent behaviour. Land the cheap evidence first.

---

## 5. Regression tests to add alongside the fixes

Each is a defect that shipped because nothing compared two things that should agree:

- **`test_declared_budget_bounds_actual_payload`** — for every tool and budget, `estimated_tokens ≤ len(json.dumps(response))/4 ≤ 1.15 × estimated_tokens`. Catches W1, W4–W7 and prevents their return.
- **`test_no_tool_exceeds_server_max_result_tokens`** — including `impact_slice` at `depth=3, max_nodes=500`. Catches W2.
- **`test_truncated_is_never_false_while_omitting`** — assert over every tool that omits. Catches W3.
- **`test_cli_module_entrypoint_acts_or_fails`** — `python -m token_context_mcp.cli register …` must either register or exit non-zero. Catches W9.
- **`test_freshness_does_not_rehash_unchanged_files`** — count `sha256_file` calls across two consecutive `status()` calls. Catches W8 and pins O3.
