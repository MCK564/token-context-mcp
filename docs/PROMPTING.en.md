# Prompting — which questions save tokens, and which do not

This document answers one question: **what should you ask, so that calling
token-context costs less than not calling it?**

Every number below comes from this repository's own measurements. Nothing here is
projected. See `BENCHMARK_FINDINGS.en.md` §2.8–§2.12 and `evals/reports/` for the
raw records.

## The one-line answer

Savings come from **localisation**, not from **enumeration**.

A prompt that names a target — a file, a symbol, a module — can save 60–95% of the
retrieval that native reads would cost. A prompt that asks the tool to *enumerate a
repository* is usually more expensive than a single `rg`, and a prompt that asks for
*callers* has been measured costing **46% more** than not using the tool at all.

## What was actually measured

Paired C3 pilot, `bench-invoice`, one seed per task, retrieved-content tokens:

| Prompt shape | Native only | With token-context | Result |
|---|---:|---:|---|
| **T5 evidence/trace** | 76,293 | 12,232 native + 18,514 MCP = 30,746 | **−60%** |
| **T2 locate by name** | 33,670 | 296 native + 30,491 MCP = 30,787 | **−9%** |
| **T3 impact / callers** | 39,404 | 48,735 native + 8,669 MCP = 57,404 | **+46% worse** |

Median paired total-token reduction across the three: **−0.3%**, CI95 spanning
**−53% to +33%**, n=3. Read that honestly: **this pilot does not support a headline
token-saving claim.** The full 5-task × 3-seed matrix is still pending. What it does
support is a per-prompt-shape ranking, which is what this page is for.

Mechanism-level measurements on `invoice-scanner` (124 Python files, ≈220,576 tokens):

| Mechanism | Before | After |
|---|---|---|
| Signature instead of body | whole file, 19,327 tokens | `get_file_skeleton` ≈985 tokens |
| Compact instead of full map entries | 107 tokens/symbol | 24 tokens/symbol |
| Ranking correctness | recall 0.167, 3 noise items | recall 0.833, 0 noise |

---

## Tier A — reliably saves. Name a target.

### A1. "Show me the public surface of *this file*"

The single largest measured win: **19,327 → ≈985 tokens, about 95%.**

```text
List the public API of src/invoice_backend/s9_fields.py — signatures only, no bodies.
Use get_file_skeleton; do not read the file.
```

Why it works: you asked for the shape of one named thing, and the tool's whole job is
to return shape without bytes.

The version that does **not** work: *"show me that file"*. That forces a full read, and
you pay for the skeleton *and* the file.

### A2. "Trace this pipeline / show me the evidence for X"

**76,293 → 30,746 tokens, −60%** on the T5 trace task.

```text
Trace how a receipt goes from input to stored result in invoice-scanner.
Name the stages in source order with source-backed paths or symbols.
```

Why it works: the answer is a handful of symbols scattered across a large tree. Native
tooling has to grep repeatedly and read broadly to find them; the index already knows
where they are.

### A3. "What surrounds this symbol"

```text
Find the symbol extract_with_trace, then give me its context at depth=1.
Request include_body=true only for the final symbol whose implementation I need.
```

Why it works: `find_symbols` → `get_symbol_context` is the cheapest path from a name to
its neighbourhood. Bodies are the expensive part, so ask for them last and only once.

---

## Tier B — saves a little, or breaks even

### B1. Locate by name

**33,670 → 30,787 tokens, −9%.** Real but small. Worth doing because it is also faster
to write than a good `rg` invocation, not because it transforms the budget.

### B2. Body-text search

`search_source(query="ocr", limit=100, max_tokens=4096)` returned **41 files in 3,900
estimated tokens** with no truncation, on the rebuilt `bench-invoice` index.

That is roughly comparable to `rg` on cost. The reason to prefer it is what comes back:
symbol IDs and line spans you can feed straight into `get_symbol_context`, instead of
raw lines you then have to locate.

---

## Tier C — usually does not save, and sometimes costs more

### C1. Impact and caller questions — measured **+46% worse**

This is the one to be careful with. On T3 the agent used MCP **and then grepped anyway**,
paying twice: 48,735 tokens of native output on top of 8,669 tokens of MCP results.

The cause was a false incompleteness signal, since fixed — but the underlying tension
remains: lexical edges are **not** a semantic call graph, the tool says so, and a careful
agent responds to that by verifying natively.

If you ask an impact question, say what you will accept:

```text
Who calls parse_receipt_number? Use get_impact_slice.
A candidate lexical graph is acceptable — label it as such and do not verify with
native search. If the result reports node_limit_reached=false, treat the traversal
as complete for my purposes.
```

Without that permission, expect to pay for both paths.

### C2. Pure orientation and enumeration

One `rg --files` returns the **complete** file listing for 18,228 tokens. `get_repo_map`
at a 4,096 budget returns about **6.6% of symbols** — and you cannot tell from the result
what the other 93% were.

Use `repo_map` for a first orientation when you want *ranked* entry points. Do not use it
when you want *all* of anything.

### C3. "Find the code that does X" with no name to go on

Measured on `bench-invoice` for the term `ocr`:

| | |
|---|---:|
| Files whose body mentions `ocr` | 41 |
| Symbols living in those files | 270 |
| Symbols with `ocr` in the **name** | 27 |
| **Invisible to `find_symbols`** | **243 (90%)** |

`find_symbols` matches names and qualified names. `rank_symbols` scores path, name,
qualified name and signature. **Neither reads a function body.** So a behavioural query
against those tools misses ~90% of the relevant code.

Use `search_source` for this — it does read bodies. Do not use `find_symbols` or
`repo_map` and conclude the code is not there.

### C4. Anything that needs the actual bytes

Whole-file review, refactoring, editing. You need the source either way, so a skeleton
first is simply an extra payment. Go straight to reading the file.

### C5. Repositories and languages the index does not cover

- **Unregistered repositories are invisible by design.** The server accepts a registered
  `repo_id`, never a path.
- **Symbol-level tools cover Python, JavaScript and TypeScript/TSX only.** Other
  languages have no symbols, so `find_symbols`, `repo_map`, `symbol_context` and
  `impact_slice` have nothing to return for them.

### C6. Small repositories

`list_repositories` → `get_index_status` → `repo_map` is a fixed handshake cost. Below
roughly a few thousand tokens of source, reading the files is cheaper than orienting.

---

## Prompt hygiene — mistakes that cost a whole run

These are not hypothetical. The first C3 pilot produced a "B1 saves 8.5%" headline that
was **entirely an artifact**: both MCP calls had failed, contributing 178 tokens of error
envelope, and the benchmark had compared two native-only sessions against each other.

| Rule | What goes wrong without it |
|---|---|
| `repo_id` is a **short registered name**, never a filesystem path | `validate_repo_id` rejects it; every call fails silently into native fallback |
| Keep `budget_tokens` / `max_tokens` within the server ceiling | `budget_out_of_range`; the call fails even with a correct id |
| Graph `depth` is 0–3 | rejected request |
| Budget profile names are `locate`, `orient`, `impact`, `read` | an invented name is not a profile |
| On an error envelope, **correct the request** — do not fall back silently | you get native cost plus zero tool value, and think the tool was measured |

The instruction block in `SETUP.en.md` §6 encodes all of these. Paste it into the agent's
system prompt; it matters as much as the server configuration.

---

## Copy-paste templates

**Surface of a file** (Tier A, best case)
```text
Give me the public definitions of <path> — signatures only, bodies elided.
Use get_file_skeleton with the registered repo_id. Do not read the file natively.
```

**Locate then expand** (Tier A)
```text
Find <symbol_name> in <repo_id>. Use find_symbols, then get_symbol_context at depth=1.
Request include_body=true only for the one symbol I need to modify.
```

**Trace** (Tier A, measured −60%)
```text
Trace <input> to <output> in <repo_id>. Name the stages in source order with
source-backed paths. Use the "read" budget profile.
```

**Impact, with the fallback closed** (Tier C — read C1 first)
```text
Who calls <symbol>? Use get_impact_slice with the "impact" profile.
A candidate lexical graph is acceptable; label it as such and do not verify natively
unless the result reports truncation or ambiguity.
```

**Behavioural search** (Tier C3)
```text
Which code handles <behaviour> in <repo_id>? Use search_source — it reads bodies.
Do not conclude from find_symbols or repo_map that the code is absent.
```

---

## Why `total_tokens` is the wrong yardstick

In the validated pilot, `cached_input_tokens` was **89–92% of input** in every row. In
one run, retrieved content was 2,558 tokens against 120,832 cached input tokens —
content was **2%** of the total. A total-token delta mostly measures conversation length,
not retrieval.

The benchmark's primary metric is `retrieved_content_estimated_tokens`. Judge a prompt
shape by that, and by whether the agent still had to read source natively afterwards.

## When the saving actually appears

Restating `SETUP.en.md` §8.4 in one sentence: the saving is real exactly when MCP returns
enough that the agent **does not re-read source natively** — which requires
`truncated=false`, `omitted_count=0`, `freshness=fresh`, and no ambiguity warning. If any
flag is set, verifying natively is correct, and the tool becomes additive rather than
substitutive. That is not a bug in the prompt; it is the tool telling the truth about
what it knows.
