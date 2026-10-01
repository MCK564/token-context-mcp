# Token Context MCP

> English edition. The main [`README.md`](README.md) is kept in sync and still contains a few Vietnamese passages.

`token-context-mcp` is a read-only local MCP server that indexes registered repositories and returns small, source-hashed code-context packets. It is designed to reduce broad repository crawling without pretending that syntax analysis is a complete semantic model.

## What's new in 0.3.x

Full details: [`CHANGELOG.md`](CHANGELOG.md), measurements in [`docs/BENCHMARK.md`](docs/BENCHMARK.md) (M12) and [Benchmark status (0.3.x)](#benchmark-status-03x) below.

- **JavaScript** — methods assigned through `X.prototype.m = …`, `X.prototype = {…}`, `Object.defineProperty(X.prototype, …)`, `this.m = …` in constructor functions, `exports.m` / `module.exports = {…}` and object literals are now symbols; 0.3.1 also binds chained assignments (`res.set = res.header = function …`) and fixes a 0.3.0 regression that dropped methods of object literals passed as arguments (`describe("x", { test() {} })`).
- **C#** — implementation methods outrank interface/abstract declarations, doc comments attach to the member rather than the container, interface documentation is inherited, vendored CSS/JS is demoted.
- **Fewer ambiguous call edges (JS/TS/C#)** — implicit `this`, overloads by arity, C# namespaces, local variable types, fields without `this.`, `new X()` instantiation edges, CommonJS and ES-module bindings, TypeScript property-signature types.
- **Deterministic edge budget** — the 30 ms wall-clock circuit breaker made the call graph depend on machine load; it is replaced by a deterministic work budget, and the resolver version now takes part in the index fingerprint.
- **Honest evaluation** — task sets for four *held-out* repositories (Python `starlette`, TypeScript `zod`, JavaScript `express`, C# `serilog`) were written and reviewed by independent sessions before any measurement, the code was frozen (tag `m12-freeze`) and each held-out set was measured once. Several predeclared targets were **not** met; they are listed below rather than hidden.
- **Upgrade:** `PARSER_ARTIFACT_VERSION` (7), `FTS_BUILDER_VERSION` (2) and `RESOLVER_VERSION` (3) changed, so the first `token-context index --all` after upgrading re-indexes every repository. Python results are unchanged byte for byte.

## What was new in 0.2.0

Full details: [`CHANGELOG.md`](CHANGELOG.md), report [`docs/reports/M6_M10_REPORT.vi.md`](docs/reports/M6_M10_REPORT.vi.md), client results [`docs/CLIENT_MATRIX.md`](docs/CLIENT_MATRIX.md).

- **Context packet** — `inspect_symbol(view="full")` returns `data.packet`: the target body (or its kept lines), callee/caller signatures, remaining relations, imports and sibling methods, with file hashes, inside the response budget. `minimal` and `normal` are unchanged. Short 8-character symbol refs are accepted by `get_symbol_context` and `get_impact_slice`.
- **Incremental, parallel, commit-aware index (schema 2.4)** — files are skipped by `(size, mtime_ns)`, parse results are cached per file hash, edges are re-resolved only where needed, and `get_index_status` reads manifest aggregates and reports `commit_sha` / `head_changed_since_index`. **After upgrading, re-index every repository once: `token-context index --all`.**
- **Client compatibility** — `serve --output-mode {auto,structured,text,legacy_dual}` and `serve --schema-profile {auto,default,gemini_safe}`; `get_tool_schema` returns the real schema; repository text is flagged as untrusted and scanned for prompt-injection patterns (warning only, nothing is redacted).
- **Desktop GUI that does not block** — no I/O on the UI thread, indexing in a child process with a Cancel that kills the whole tree, honest status badges, a running-servers panel instead of Start/Stop, VACUUM only for the mutable databases.
- **Go** is now parsed (`.go`, tree-sitter-go). Go call edges are name based, so Go graphs are more ambiguous than Python's.
- **Single version source** (`token_context_mcp.__version__`) and a deterministic retrieval benchmark, `evals/bench_retrieval.py`, with results on a public repository (see [Benchmark status](#benchmark-status-020)).

## What is implemented

- explicit repository registration; MCP tools receive a `repo_id`, never an arbitrary path;
- Tree-sitter parsing for Python, JavaScript, TypeScript/TSX, Java, C#/.NET, Go, HTML and CSS;
- SQLite snapshots with files, symbols, lexical edges, manifests and source hashes;
- AST call-expression query extraction with receiver recognition (`self`, `cls`, `this`, class prefixes) and import linking, cutting ambiguous lexical edges down from ~15–22% to <3% on Python (Go edges are name based and remain more ambiguous);
- token-budgeted repository maps, source-backed skeletons, symbol context and bounded impact slices;
- FTS5 search over symbol bodies and complete indexed files, returning bounded snippets with symbol IDs and line spans;
- Tree-sitter import relationships served directly, rather than inferred from the lexical call graph;
- lexical resolution that prefers same-file and same-package definitions before the global name index;
- compact repository-map encoding and four named budget profiles (`locate`, `orient`, `impact`, `read`);
- truncation and cap warnings computed from actual results, not from the request;
- zero-waste wire transport: eliminates payload duplication between text and structured_content, cutting wire tokens by ~55–60%;
- composite retrieval: `inspect_symbol` combines candidate resolution, definition context, and 1-hop impact graph in a single turn (saving 81.3% prompt replay tokens);
- server-side projection presets (`minimal`, `normal`, `full`) and root entity preservation under strict token budgets;
- Dynamic Tool Discovery (`list_available_tools`, `search_tools`, `get_tool_schema`) eliminating tool definition tax in agent context windows;
- Shared State & Long-term Memory (`memory_put`, `memory_get`, `memory_search`, `memory_lock`) with zero external daemons (SQLite-first) and timed soft-mutex locks;
- Hardware-Aware LLM Sampling (`sample_summarize`) with Ollama auto-routing and deterministic heuristic fallback;
- Agent Governance & Permission Revocation Control Plane (`agent_control`): pause, resume, block, and emergency-halt agents (Claude, Antigravity, Cursor, Codex) with sub-0.05ms fast-path in-memory checks;
- Real-time Security Audit Logging (`audit_logs`) via SQLite WAL mode, capturing forensics, latency, and authorization results with zero response-time penalty;
- incremental and parallel indexing (`index --all`, `--watch`, `--workers`, `--verify-hashes`, `--full`, NDJSON progress) with per-file parse artifacts stored in the snapshot;
- context packets from `inspect_symbol(view="full")`, and per-client output modes and schema profiles for `serve`;
- Desktop Controller (PySide6) with hardware telemetry, interactive graph viewer, task queueing and a dedicated **Agents & Security** management tab; all reads run off the UI thread;
- Virtual External Stubs Engine (`external_stubs` table): import-driven tree-shaking for standard library and 3rd-party dependencies (`pydantic`, `unittest`, `requests`, `fastapi`, `pytest`, `builtins`), resolving external calls with 0.90 confidence and 0 false positives;
- Flow-Sensitive Type Narrowing: scoped type stacking up to depth 12 for `if isinstance(...)` and `match/case` blocks, untainting narrowed identifiers inside guarded scopes;
- Defensive heuristics: a deterministic per-file work budget in the edge resolver (`FILE_EDGE_WORK_BUDGET`, the same graph on every machine; the earlier 30 ms wall-clock breaker made graphs depend on machine load and was removed in 0.3.0) and Pseudo-SSA taint analysis preventing hallucinated edges in generated or polymorphic code;
- Robust Multi-OS CI/CD Pipeline: automated GitHub Actions testing across Ubuntu Linux and Windows with isolated clean-room wheel validation, headless Qt (`PySide6`) test harness, and cross-engine golden test parity;
- Abbreviation & Terminology Guide: formal compiler and graph theory definitions detailed in [`docs/ABBREVIATIONS.md`](docs/ABBREVIATIONS.md);
- strict read-only tool surface over MCP `stdio`;
- hard deny rules for secrets/metadata, path traversal/reparse-point checks and resource limits;
- security, integration and benchmark harnesses that report evidence rather than claiming universal savings.

## Is it useful on my language? (0.3.x, held-out evidence)

Short answer: **yes for locating code in Python, JavaScript and TypeScript, usable with limits in C#; the call graph and the context packet are only as good as the language's edge resolution** (best in Python, partial elsewhere). Numbers are from four repositories that were *not* used to develop 0.3.0 (30 locate tasks each, one measurement, frozen code; [details](#benchmark-status-03x)). `R2` is `search_source(profile="locate")` at about 1.9k tokens per answer.

| Language (repository, files) | File Acc@5, R2 | grep cut to the same size | grep, unbounded (tokens read) | Symbol Recall@10, R2 | What to expect |
| --- | ---: | ---: | ---: | ---: | --- |
| Python (`starlette`, 88) | 0.77 | 0.47 | 0.77 (23.8k) | 0.44 (grep 0.28) | **Good.** Unchanged by 0.3.x. Hidden-dependency questions (no names in the query) find the file in 4 of 10 cases. |
| JavaScript (`express`, 154) | **0.93** (was 0.80) | 0.67 | 0.97 (15.9k) | 0.67 (grep 0.16) | **Good**, and the language that gained most: edges 11 → 191, ambiguous 64 % → 43 %, packet reference coverage 0.00 → 0.39. |
| TypeScript (`zod`, 517) | 0.73 (unchanged) | 0.43 | 0.60 (43.9k) | 0.61 (was 0.56; grep 0.13) | **Good for locating**, modest gains. The call graph stays weak (56 % ambiguous; 0 edges at confidence ≥ 0.6 on the gold sample) and packets cover 42 % of neighbours. |
| C# (`serilog`, 216) | 0.70 (was 0.73) | 0.50 | 0.80 (29.5k) | **0.64** (was 0.43; grep 0.09) | **Usable, with a caveat.** Symbols and call edges improved clearly (edge recall 5/17 → 13/17 with 11/11 correct at confidence ≥ 0.6), but file accuracy did not rise and behavioural questions without a name in the query find the file in only 4 of 10 cases. Unbounded grep is 0.10 ahead on file accuracy (not significant, CI95 −0.30 to +0.10) at 16 times the tokens. |

Go, Java, HTML and CSS are parsed but were not benchmarked in M12 (Go call edges are name based). In every language the answer to "which file?" is bounded to about 1.9k tokens where an unbounded grep reads 8 to 23 times more; none of the differences between `R2` and unbounded grep is statistically significant at 30 tasks per repository. Task sets were written and reviewed by independent Claude sessions, not by a human reviewer.

## Architecture & Indexing Pipeline

```mermaid
flowchart TD
    subgraph Ingestion ["1. Source Ingestion & Inventory"]
        SRC["Source Files"] --> DENY{"Hard Deny & Binary Check"}
        DENY -->|Pass| TS["Tree-sitter CST Parser"]
    end

    subgraph Extraction ["2. Syntactic & Semantic Extraction"]
        TS --> SYM["Symbol Definitions & Spans"]
        TS --> IMP["Import Dependency Extraction"]
        TS --> CHA["Class Hierarchy Analysis (CHA)"]
        TS --> CALL["AST Call Extraction + Pseudo-SSA"]
        CALL --> NARROW["Flow-Sensitive Type Narrowing (depth <= 12)"]
    end

    subgraph Resolution ["3. Graph Resolution & Stubs"]
        IMP --> STUBS["Virtual External Stubs (Tree-Shaking)"]
        CALL --> RESOLVE["Lexical Edge Resolution Engine"]
        CHA --> RESOLVE
        STUBS --> RESOLVE
        RESOLVE --> CB{"Deterministic per-file work budget"}
        CB -->|Within budget| EDGES["Resolved & Ambiguous Edges"]
        CB -->|Budget exhausted| AMBIG["Degraded Ambiguous Edge (0.10)"]
    end

    subgraph Storage ["4. Atomic SQLite Snapshot"]
        SYM --> SQLITE[("SQLite Store (WAL Mode)")]
        EDGES --> SQLITE
        AMBIG --> SQLITE
        STUBS --> SQLITE
        CHA --> SQLITE
        SQLITE --> MANIFEST["Manifest & Source Fingerprint"]
    end
```

## CI/CD & Verification Pipeline

```mermaid
flowchart LR
    COMMIT["Git Push / PR"] --> CI["GitHub Actions Matrix"]
    CI --> LINUX["Ubuntu Linux (Headless Qt / libegl1 / libgl1)"]
    CI --> WIN["Windows Server"]
    LINUX --> TEST["Source Tests & Golden Parity (uv run pytest)"]
    WIN --> TEST
    TEST --> WHEEL["Clean-room Wheel Build (uv build)"]
    WHEEL --> ISOLATED["Isolated Venv Verification & Stdio Smoke Test"]
```

## Benchmark highlights

Measured in this repository. Method and raw records: [`docs/BENCHMARK_FINDINGS.en.md`](docs/BENCHMARK_FINDINGS.en.md) and [`evals/reports/`](evals/reports).

**Mechanism level** — what each design decision is worth, on `invoice-scanner` (124 Python files, ≈220,576 tokens):

| Mechanism | Before | After |
| --- | ---: | ---: |
| Signature instead of body (`get_file_skeleton`) | 19,327 tok | **≈985 tok** |
| Compact instead of full map entries | 107 tok/symbol | **24 tok/symbol** |
| Ranking correctness (essential-symbol recall) | 0.167, 3 noise items | **0.833, 0 noise** |
| Removing the N+1 query loops (`repo_map@1024`) | 1,077 queries, 13.87 s | **3 queries, 0.164 s** |
| Naive read of all source vs `repo_map@1024` (wire) | 220,576 tok | **994 tok** |

**End-to-end, paired against a native-only agent** — the honest picture. C3 pilot, `bench-invoice`, one seed per task, `retrieved_content_estimated_tokens`:

| Prompt shape | Native only | With token-context | Result |
| --- | ---: | ---: | --- |
| Trace / evidence | 76,293 | 30,746 | **−60%** |
| Locate by name | 33,670 | 30,787 | −9% |
| Callers / impact | 39,404 | 57,404 | **+46% worse** |

Median paired total-token reduction: **−0.3%**, CI95 **−53% to +33%**, n=3. **This does not support a headline token-saving claim**, and none is made — the full 5-task × 3-seed matrix was never run (a different, partial C3 v2 run on held-out repositories is under Benchmark status (0.3.x)). What it does support is that *the shape of the question decides the outcome*: savings come from localisation, not enumeration. See [`docs/PROMPTING.en.md`](docs/PROMPTING.en.md) ([tiếng Việt](docs/PROMPTING.vi.md)) for which questions to ask.

Two figures worth reading before interpreting any of the above: `cached_input_tokens` was **89–92% of input** in every pilot row, and in one run retrieved content was 2,558 tokens against 120,832 cached — **2%** of the total. A `total_tokens` delta mostly measures conversation length, which is why the primary metric is retrieved content.

### Benchmark status (0.3.x)

**What was measured.** Four repositories that were not used to develop 0.3.0 — `encode/starlette` (Python), `colinhacks/zod` (TypeScript), `expressjs/express` (JavaScript), `serilog/serilog` (C#) — with 30 locate tasks and 10 packet tasks each, written by one independent session and reviewed by another that had no retrieval tools (human review pending). The code was frozen first (tag `m12-freeze`, guard `evals/guard.py`), then the old code (0.2.0 baseline, `m12-base`) and the new code were run on the same tasks, once. No model is in the loop; CI95 is a bootstrap over tasks. Full tables, raw outputs and the development-set before/after are in [`docs/BENCHMARK.md`](docs/BENCHMARK.md) (M12) and `evals/out/m12/`.

Old → new, File Acc@5 / Symbol Recall@10 of `R2` (≈1.9k tokens), and reference coverage of the packet (`R3`):

| Repository | File Acc@5 | Symbol Recall@10 | Packet ref. coverage | Ambiguous edges |
| --- | ---: | ---: | ---: | ---: |
| starlette (Python) | 0.77 → 0.77 | 0.44 → 0.44 | 0.52 → 0.52 | 31 % → 31 % |
| zod (TypeScript) | 0.73 → 0.73 | 0.56 → 0.61 | 0.34 → 0.42 | 65 % → 56 % |
| express (JavaScript) | 0.80 → **0.93** (+0.13, CI95 0.00 to +0.30) | 0.68 → 0.67 | 0.00 → **0.39** | 64 % → 43 % |
| serilog (C#) | 0.73 → 0.70 | 0.43 → **0.64** (+0.21, CI95 +0.08 to +0.36) | 0.30 → **0.47** | 69 % → 40 % |

**Predeclared targets, honestly.** Of ten targets set before the run, four were met and six were not:

| | Target | Result | Met |
| --- | --- | --- | :-: |
| K1 | JS assigned-method recall in the index ≥ 0.95, 0 wrong in a 30-symbol sample | 0.933 (every miss is a chained assignment; 1.00 without them), 0 wrong | no |
| K2 | JS File Acc@5, new − old ≥ 0 | +0.13 (CI95 0.00 to +0.30) | yes |
| K3 | C# `R2` − unbounded grep ≥ −0.05 | −0.10 (CI95 −0.30 to +0.10) | no |
| K4 | C# File Acc@5, new − old ≥ +0.10 | −0.03 (CI95 −0.13 to 0.00) | no |
| K5 | C# hidden-dependency tasks ≥ 0.40 | 0.40 (unchanged from the old code) | yes |
| K6 | ambiguous-edge ratio new/old ≤ 0.70 in JS, TS and C# | 0.68, **0.85**, 0.58 | no (zod) |
| K7 | packet reference coverage +0.10 in JS, TS and C# | +0.28, **+0.08**, +0.17 | no (zod) |
| K8 | edge precision ≥ 0.95 at confidence ≥ 0.6 | 1.00 in all three (2, **0** and 11 edges above the threshold: vacuous for TypeScript) | yes |
| K9 | Python identical | identical, byte for byte | yes |
| K10 | median latency ≤ +20 % | up to +27 % (≤ 3.3 ms absolute) on 2 of 12 fixed queries | no |

What this means: M12 clearly helped **JavaScript** and **C# symbols and call edges**, did **not** raise C# file accuracy, helped TypeScript only a little, and left Python untouched. A 0.3.0 regression found afterwards — methods of object literals passed as arguments stopped being indexed, the likely reason the TypeScript call-graph gold sample fell from 2/12 to 0/12 — and the chained-assignment miss behind K1 are fixed in **0.3.1** (`tests/test_js_object_methods.py`); 0.3.1 was re-measured on the development repositories only, because the held-out sets are measured once, so the table above describes 0.3.0.

**End to end (C3 v2, Claude Sonnet 5.5, medium reasoning, 20 held-out tasks × 3 arms).** *Incomplete and not validated:* only seed 1 of 2 was run (60 of 120 runs); the rest was stopped for cost. Every arm solved all 20 tasks (a ceiling: success cannot separate the arms). MCP-first (B2) used **20 % fewer total tokens** than the native-only agent (about 65k against 82k per run, paired CI95 −25.1k to −8.6k) and was about 13 % faster, because it needs fewer turns; it retrieved *more* content (1,387 against 753 estimated tokens) and the provider-reported cost was the same (US$1.08 per 20 runs each), since the saving is mostly cheaper cache reads. In the hybrid arm (B1) the agent never called the MCP server (0 of 20 runs), so B1 only shows run-to-run noise. This says nothing about harder tasks or weaker models, and the repositories are well known to the model. Details and caveats: [`docs/BENCHMARK.md`](docs/BENCHMARK.md) (M12, C3 subsection).

Limits: one repository per language and 30 tasks each (wide intervals), a simulated grep baseline, independent-session but not human review of the task sets, retrieval quality rather than agent productivity, a single agent and model for C3, and well-known public repositories that a model may partly remember.

### Future directions (light)

None of this is done; it is where the measurements point.

- **Ranking:** find out why fastify's Symbol Recall@10 fell (new assigned-method symbols crowd the top ten) and weigh method bodies for C# behavioural queries, where file accuracy did not move.
- **Call graph:** receiver typing for JavaScript and TypeScript (43 to 56 % of edges are still ambiguous, which caps what a packet can return), and re-measuring the TypeScript edge-gold sample after the 0.3.1 fix.
- **Agent adoption:** the hybrid mode did not make the agent call the MCP server at all; prompting or tool descriptions that make it use `search_source` first are worth testing, with harder tasks, less famous repositories, more seeds, a weaker model and the Gemini and Codex adapters (all built, none run).
- **Evaluation hygiene:** a fresh held-out set with a human reviewer for the next round, fixed-query latency in `bench_latency.py`, and closing the baseline-on-`PYTHONPATH` loophole in the Rule 17 guard.

### Benchmark status (0.2.0)

The figures above come from the earlier pilot and the X1 measurements. Version 0.2.0 adds a deterministic retrieval benchmark (`evals/bench_retrieval.py`, protocol and full tables in [`docs/BENCHMARK.md`](docs/BENCHMARK.md)). It ran on the public `Textualize/rich` v15.0.0 (30 locate tasks and 10 packet tasks, task set reviewed by the repository owner, no model in the loop, CI95 by bootstrap):

| Locate, 30 tasks | File Acc@5 | Symbol Recall@10 | Mean tokens |
| --- | ---: | ---: | ---: |
| grep simulation, unbounded | 0.93 | 0.22 | 17,553 |
| grep simulation, cut to the same size as R2 | 0.57 | 0.10 | 1,878 |
| `search_source` (FTS) | 0.97 | 0.52 | 1,897 |
| `search_source(profile="locate")` (with graph expansion) | 0.90 | 0.54 | 1,886 |

At equal cost token-context finds the right file far more often than grep (0.90 against 0.57, paired difference +0.33, CI95 +0.13 to +0.53) and names the right symbol. Unbounded grep reads about 9 times more tokens for a File Acc@5 only about 3 points higher (the difference is not significant, CI95 −0.17 to +0.07), and it wins on the multi-file group (1.00 against 0.80). The graph expansion did not beat plain FTS on this set (0.90 against 0.97). For `inspect_symbol(view="full")` packets, 98% of the gold neighbour signatures and references were covered with 91% fewer tokens than reading the files (`savings_vs_read` 0.915, CI95 0.89 to 0.93).

On a second, TypeScript repository (`honojs/hono` v4.9.9; task set reviewed by another Claude session, not yet by the owner) the locate result holds: at equal cost `search_source(profile="locate")` finds the right file in 80% of tasks against 23% for grep cut to the same size (63% for unbounded grep, which reads about 11 times more tokens). **The packet did not meet its targets there** (signature and reference coverage 0.58 against targets of 0.60 and 0.80, saving against reading 0.57 against 0.70) because call edges in TypeScript are far more ambiguous, so the packet can only return what the graph reaches. Details in [`docs/BENCHMARK.md`](docs/BENCHMARK.md).

Two more repositories, JavaScript (`fastify`) and C# (`CsvHelper`), give a four-language picture (task sets reviewed by another Claude session, not by the owner). File Acc@5 at equal cost: `rich` (Python) 0.90 vs 0.57, hono (TypeScript) 0.80 vs 0.23, fastify (JavaScript) 0.90 vs 0.27, CsvHelper (C#) 0.60 vs 0.43; against unbounded grep the tool is roughly level in Python (0.90 vs 0.93), ahead in TypeScript (0.80 vs 0.63) and JavaScript (0.90 vs 0.57), and **behind in C#** (0.60 vs 0.77, significantly), where behavioural queries mostly fail (declarations, attributes and interfaces outrank implementations). The packet meets its targets only in Python (coverage 0.98, saving 0.91); in TypeScript, JavaScript (0.46) and C# (0.47) it misses, tracking the share of ambiguous call edges (17 %, 45 %, 72 %, 90 %). At the time, the JavaScript indexer did not index prototype-assigned methods (fixed in 0.3.0). Details and cross-language table in [`docs/BENCHMARK.md`](docs/BENCHMARK.md).

Limits: one repository per language, wide intervals, a simulated grep baseline, and retrieval quality only, not agent task success. At the time the end-to-end C3 matrix had not been run; a partial C3 run (seed 1 only, Claude Sonnet 5.5) is reported under Benchmark status (0.3.x) above and is not validated. Measured M7/M8 results, including the targets that were missed, are in the [changelog](CHANGELOG.md) and the [M6–M10 report](docs/reports/M6_M10_REPORT.vi.md).

## Non-goals and security boundary

This server does not edit files, execute shell commands, listen on HTTP, call network APIs, or accept arbitrary repository paths. `stdio` is not an OS sandbox: deploy with a no-egress/least-privilege policy if an enforced network boundary is required. Tool results may still be placed in the MCP host's LLM context.

## Prerequisites and installation

Everything below is needed only for the part you use. The MCP server alone needs Python and `uv`; the GUI, the `.exe` build, the file watcher and the local 7B summariser are optional add-ons.

| Component | Needed for | How to get it |
| --- | --- | --- |
| Git | cloning the repository | <https://git-scm.com/downloads> |
| Python 3.12 or newer | everything | <https://www.python.org/downloads/> or, once `uv` is installed, `uv python install 3.12` |
| `uv` | environment and dependency management | Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`; Linux/macOS: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python libraries | see below | `uv sync --all-extras` |
| Ollama + a coder model (optional) | `sample_summarize` with a local 7B model | see [Local model](#local-model-optional) |

### Python libraries

`uv sync` installs the exact versions in `uv.lock` into `.venv/`. The libraries are grouped:

| Group | Contents | Install |
| --- | --- | --- |
| core (always) | `mcp`, `mcp-types`, `pydantic`, `pathspec`, `tree-sitter` and the grammars for Python, JavaScript, TypeScript/TSX, Java, C#, HTML, CSS and Go | `uv sync` |
| `dev` | `pytest`, `pytest-cov`, `jsonschema`, `psutil` | `uv sync --extra dev` |
| `gui` | `PySide6`, `psutil`, `pyinstaller` (desktop GUI and the `.exe` build) | `uv sync --extra gui` |
| `watch` | `watchdog` (event-based `index --watch`; without it the watcher polls) | `uv sync --extra watch` |

**Recommended for a full development machine:**

```powershell
uv sync --all-extras
```

> `uv sync` is exact: it *removes* packages that are not in the extras you list. Running only `uv sync --extra dev` therefore leaves PySide6 out (or uninstalls it if it was there), and `uv run token-context-gui` then fails with `No module named 'PySide6'`. Always pass every extra you need in the same command (or use `--all-extras`).

Run project tools through `uv run` (`uv run token-context-gui`, `uv run python scripts/build_desktop_exe.py`), not with a bare `python`, so that they use `.venv` and not the system Python.

### Local model (optional)

`sample_summarize` can compress text with a local model served by [Ollama](https://ollama.com/download). Without Ollama, or on a machine with too little memory, it falls back to a deterministic heuristic on the CPU; no other feature depends on a model, and no embedding model is used.

1. Install Ollama from <https://ollama.com/download> and make sure it is running (`ollama serve`; the desktop app starts it for you). The server probes `http://localhost:11434`.
2. Download the model, either with the helper script or by hand:

   ```powershell
   .\scripts\download_models.ps1              # qwen2.5-coder:7b-instruct-q4_K_M (recommended)
   .\scripts\download_models.ps1 -Lightweight # qwen2.5-coder:1.5b, for small machines
   # or directly:
   ollama pull qwen2.5-coder:7b-instruct-q4_K_M
   ollama pull qwen2.5-coder:1.5b
   ```

   On Linux/macOS: `./scripts/download_models.sh` (`--lightweight` for the 1.5B model).
3. Check it: `ollama list` should show the model, and `uv run python -c "from token_context_mcp.sampling.router import SamplingRouter; print(SamplingRouter().summarize('def f(x): return x+1', intent='describe'))"` reports the `backend` used (`ollama_gpu`, `ollama_cpu` or `heuristic_fallback`).

The Ollama backend is chosen only when Ollama is reachable and the host has a CUDA GPU with at least 6 GB of VRAM (`ollama_gpu`) or at least 6 GB of RAM (`ollama_cpu`); otherwise the heuristic fallback is used.

## Quick start

```powershell
uv sync --all-extras          # see Prerequisites; plain `uv sync` is enough for the server alone
uv run token-context register --repo-id demo --root D:\AI\some-repo
uv run token-context index --repo-id demo      # or: index --all
uv run token-context status --repo-id demo
uv run token-context serve
```

Useful `index` options: `--all` (every registered repository, JSON summary), `--watch` (re-index after the tree has been quiet; uses `watchdog` if installed, otherwise polls), `--workers N`, `--verify-hashes` (hash every file, ignore the mtime shortcut), `--full` (ignore the previous snapshot) and `--progress-format ndjson` (one JSON object per line on stdout).

### Desktop GUI Controller (PySide6)

In addition to the CLI, `token-context-mcp` includes a modern desktop graphical user interface with hardware telemetry, visual repository management, live indexing progress, log streaming, and cache controls:

Requires the `gui` extra (`uv sync --all-extras`); without it the command stops with an install hint.

```powershell
# Launch Desktop GUI
uv run token-context-gui

# Or using 1-click launcher scripts:
.\scripts\launch_desktop_gui.bat    # Windows Batch
.\scripts\launch_desktop_gui.ps1    # PowerShell

# Build a standalone portable .exe (needs PyInstaller from the gui extra):
uv run python scripts/build_desktop_exe.py --clean   # -> dist\desktop\TokenContextDesktop\TokenContextDesktop.exe
```

Key GUI Capabilities:
- **📊 Dashboard & Telemetry:** Real-time CPU & RAM gauges, AI hardware detection (NVIDIA CUDA, Apple Silicon MPS, Ollama 7B, CPU Heuristic), a table of running MCP servers (clients start and stop them; the GUI does not), and 1-click "Copy client config" for Claude, Claude Code, VS Code, Codex and Antigravity with the recommended `serve` flags.
- **📁 Repository Management:** Table with repository roots, snapshot badges (`FRESH`, `STALE`, `DOCS_CHANGED`, `SCHEMA_OUTDATED`, `NOT_INDEXED`), symbol counts, ambiguous edge rates, "Add Repository" folder picker, per-repository and "Re-index all" actions. Indexing runs in a child process and Cancel stops the whole process tree.
- **⚡ Tasks & Graph Visualizer:** Live stdout/stderr log stream, language distribution breakdown, lexical edge confidence progress, and top architectural entry-point symbols.
- **💾 Cache & Storage Controller:** SQLite file breakdown, database size inspection, VACUUM of `memory.sqlite`, `governance.sqlite` and `audit.sqlite` only (never index snapshots), stale snapshot cleaner, and cache purge.
- **⚙️ Server Settings:** Interactive editor for `repos.toml` resource caps and the 20 tools extension toggle.

By default the registry is global for the current user at `%APPDATA%\token-context-mcp\repos.toml` on Windows and `~/.config/token-context-mcp/repos.toml` on Linux and macOS; it is independent of the current working directory. Set `TOKEN_CONTEXT_CONFIG` to use an explicit shared/portable TOML path — on a multi-user host, read [Keeping the registry and snapshots private](#keeping-the-registry-and-snapshots-private) before pointing several accounts at one file. For Codex, launch the package through a configured `stdio` MCP command. Use only the read-only tools listed by the server.

## Register repositories safely

Registration is an explicit local allowlist decision, not an upload, Git operation, or source-code change. `--repo-id` is a stable identifier used in MCP requests; `--root` is the only canonical repository directory that the server is allowed to read.

```powershell
Set-Location D:\AI\token-context-mcp
uv run token-context register --repo-id video-lecturer --root D:\AI\video_lecturer
uv run token-context index --repo-id video-lecturer
uv run token-context status --repo-id video-lecturer
```

Use a specific project root, never a broad parent such as `D:\AI`. Re-run `index` after relevant changes; it reuses unchanged parsing results. Existing registrations and index databases are shared by every MCP process launched under the same account, on that machine only.

To use a different registry location for one terminal or a portable deployment, set it before registering, indexing, and starting the MCP server:

```powershell
$env:TOKEN_CONTEXT_CONFIG = 'D:\trusted-shared-config\repos.toml'
uv run token-context register --repo-id myrepo --root D:\projects\myrepo
uv run token-context index --repo-id myrepo
```

## Use from coding agents

This is a local MCP `stdio` server. It works with a client that can start local processes and has `uv` available on its `PATH`. Each client process launched under the same account on the same machine automatically reads the same global repository registry. Restart the client after changing the registry or its policy.

| Client | Local `stdio` support | Setup status |
| --- | --- | --- |
| Codex CLI / IDE | Yes | Installed and end-to-end tested on this machine. |
| Claude Code | Yes | Supported; add it at user or project scope. |
| GitHub Copilot CLI | Yes | Supported through the CLI user configuration or project config. |
| GitHub Copilot Chat in VS Code | Yes | Supported through `.vscode/mcp.json` or the MCP UI. |
| Google Antigravity IDE / CLI | Yes | Supported through global or workspace `mcp_config.json`. |
| Claude Desktop | Conditional | It supports local MCP through Desktop Extensions, but this project does not yet publish a `.dxt` package. |

Recommended `serve` flags per client and the real check results (only one client is recorded so far) are in [`docs/CLIENT_MATRIX.md`](docs/CLIENT_MATRIX.md). A client that reads only the text content should use `--output-mode text`; Gemini-family clients and Antigravity should use `--schema-profile gemini_safe`. Restart the client session after changing flags.

For an editor connected to another host over SSH, see [Linux, macOS and VS Code Remote-SSH](#linux-macos-and-vs-code-remote-ssh): the configuration has to live on the host that holds the source.

Cloud/web agents cannot start this server on a local machine. They need a separately deployed, authenticated HTTP MCP service; this project intentionally ships only local `stdio` transport.

### Which prompts save tokens

Configuring the server is half the job; asking the right *shape* of question is the other half.
Measured on this repository's own C3 pilot, the same tool ranged from **−60%** retrieved
content on a trace task to **+46% worse** on a caller/impact task. Savings come from
**localisation**, not enumeration.

| Prompt shape | Measured | Use the tool? |
| --- | --- | --- |
| Public surface of a named file | 19,327 → ≈985 tokens | Yes — best case |
| Trace / evidence across a large tree | −60% | Yes |
| Locate a named symbol | −9% | Yes, modest |
| Body-text search | ≈3,900 tokens for 41 files | Comparable to `rg`; better return shape |
| Callers / impact | **+46% worse** | Only with the native fallback explicitly closed |
| Enumerate everything | `rg --files` = 18,228 tokens, complete | No — `repo_map@4096` returns ~6.6% of symbols |
| Behavioural query, no name | 90% of matching symbols invisible to `find_symbols` | Use `search_source`, not `find_symbols` |

Full guidance, copy-paste templates, and the prompt-hygiene rules that once invalidated an
entire benchmark run: [`docs/PROMPTING.en.md`](docs/PROMPTING.en.md) ([tiếng Việt](docs/PROMPTING.vi.md)).

### Codex

There are two ways to connect Codex to `token-context-mcp`:

#### Method A: Via Codex CLI
```powershell
codex mcp add token-context -- uv run --directory D:\AI\token-context-mcp token-context serve --transport stdio
codex mcp get token-context
```

#### Method B: Direct Config File (`~/.codex/config.toml`)
If the `codex` command is not available in your PowerShell PATH, directly add the server to `%USERPROFILE%\.codex\config.toml`:

```toml
[mcp_servers.token-context]
command = "uv"
args = ["run", "--no-sync", "--directory", "D:\\AI\\token-context-mcp", "python", "-m", "token_context_mcp.cli", "serve", "--transport", "stdio"]
```

> **Tip for GUI:** If Codex cannot find `uv`, replace `"uv"` with the absolute path: `"C:\\Users\\<YourUser>\\AppData\\Roaming\\Python\\Python312\\Scripts\\uv.exe"`.

---

### Claude (Claude Code & Claude Desktop)

#### 1. Claude Code (CLI)
```powershell
claude mcp add --transport stdio --scope user token-context -- uv run --no-sync --directory D:\AI\token-context-mcp python -m token_context_mcp.cli serve --transport stdio
claude mcp get token-context
```

#### 2. Claude Desktop (Windows App)
Open or create `%APPDATA%\Claude\claude_desktop_config.json` (e.g. `C:\Users\<YourUser>\AppData\Roaming\Claude\claude_desktop_config.json`) and add:

```json
{
  "mcpServers": {
    "token-context": {
      "command": "uv",
      "args": [
        "run",
        "--no-sync",
        "--directory",
        "D:\\AI\\token-context-mcp",
        "python",
        "-m",
        "token_context_mcp.cli",
        "serve",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

---

### Registering and Using `task2-demo`

#### 1. Register and Index Repository
Run these commands in PowerShell (registers globally in `%APPDATA%\token-context-mcp\repos.toml`):

```powershell
# Register repository
uv run --directory D:\AI\token-context-mcp token-context register --repo-id task2-demo --root D:\AI\video_lecturer\task\task2_demo

# Build index
uv run --directory D:\AI\token-context-mcp token-context index --repo-id task2-demo

# Check status
uv run --directory D:\AI\token-context-mcp token-context status --repo-id task2-demo
```

#### 2. Example Prompt for Codex / Claude / Antigravity
After restarting Codex, Claude, or Antigravity, send this prompt in the chat:

```text
Use token-context for repo_id "task2-demo".
Start with get_repo_map at 512 tokens to inspect the project structure,
then use get_file_skeleton for "src/lecturer_demo/cli.py".
```

If a client cannot start the server, first run `uv run --directory D:\AI\token-context-mcp token-context serve --transport stdio` in PowerShell to check its Python environment. GUI clients sometimes do not inherit a terminal's `PATH`; in that case set `command` to the absolute path of `uv.exe`, then restart the client.

Official client setup references: [OpenAI Codex](https://developers.openai.com/codex/mcp), [Claude Code](https://code.claude.com/docs/en/mcp), [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers), [GitHub Copilot in IDEs](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp-in-your-ide/extend-copilot-chat-with-mcp), [Antigravity](https://antigravity.google/docs/mcp), and [Claude Desktop](https://support.anthropic.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

## Linux, macOS and VS Code Remote-SSH

Full reference — supported systems, remote placement, every limit and the permission model:
[`docs/PLATFORMS.en.md`](docs/PLATFORMS.en.md) ([tiếng Việt](docs/PLATFORMS.vi.md)).

The package is cross-platform; CI runs the test suite on Ubuntu and Windows. Only the
registry path differs:

| Host | Registry | Snapshots |
| --- | --- | --- |
| Windows | `%APPDATA%\token-context-mcp\repos.toml` | `%APPDATA%\token-context-mcp\indexes\` |
| Linux | `$XDG_CONFIG_HOME/token-context-mcp/repos.toml`, else `~/.config/...` | `~/.config/token-context-mcp/indexes/` |
| macOS | `~/.config/token-context-mcp/repos.toml` | `~/.config/token-context-mcp/indexes/` |

```bash
uv sync --extra dev
uv run token-context register --repo-id demo --root ~/code/some-repo
uv run token-context index --repo-id demo
uv run token-context status --repo-id demo
uv run token-context harden
```

### Where the server has to run

The transport is `stdio` only. The client starts the server as a child process and talks
to it over stdin/stdout, and the server reads the filesystem it is started on. **Source and
server must therefore live on the same machine.** A server started on a Windows laptop
indexes that laptop, whatever the editor window is connected to.

VS Code decides that by where the configuration lives:

| Configuration | Server runs on | Works against remote source |
| --- | --- | --- |
| User profile (`MCP: Open User Configuration`) | the local machine | no |
| `.vscode/mcp.json` in a workspace on the remote | the remote host | yes |
| Remote user settings (`Remote [SSH: host]`) | the remote host | yes |

So on Remote-SSH, register and index from a **terminal on the server**, and put the
configuration in the workspace that lives on the server:

```json
{
  "servers": {
    "token-context": {
      "type": "stdio",
      "command": "/home/you/.local/bin/uv",
      "args": [
        "run", "--no-sync",
        "--directory", "/home/you/token-context-mcp",
        "token-context", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

Two details that cause most of the failures:

- Use `.vscode/mcp.json` with the `"servers"` key, not a repository-root `.mcp.json`. VS Code
  before 1.135.0 converts a workspace path with `URI.fsPath` and sends a Windows-shaped path
  to the Linux host, which fails as `spawn ... ENOENT`.
- Give `command` the absolute path to `uv`. The server is not spawned through a login shell,
  so `~/.local/bin` is usually missing from `PATH`. Run `which uv` on the server and paste
  the result.

A client on the local machine can also start the server over SSH, because `ssh` forwards
stdin and stdout unchanged:

```json
{
  "servers": {
    "token-context": {
      "type": "stdio",
      "command": "ssh",
      "args": ["myserver", "/home/you/.local/bin/uv run --no-sync --directory /home/you/token-context-mcp token-context serve --transport stdio"]
    }
  }
}
```

This also covers AWS SSM, where `~/.ssh/config` carries the `ProxyCommand`; the MCP side sees
plain SSH either way. The cost is a session per start, and any server banner or MOTD printed
on stdout corrupts the JSON-RPC stream.

Registry and snapshots are per machine and per account. Registering on the laptop does
nothing for the server, and vice versa.

## Keeping the registry and snapshots private

A snapshot stores verbatim source bodies so that `search_source` and `get_symbol_context` can
return them. It must therefore never be easier to read than the repository it came from — an
index under a default umask hands your source to every account on the host, whatever the
repository's own permissions say.

Registry, snapshots and manifests are created owner-only (`0700` directories, `0600` files) on
POSIX rather than inheriting the umask. `harden` re-applies that to files created earlier and
reports what it found:

```bash
uv run token-context harden --check   # report only
uv run token-context harden           # repair
```

```powershell
uv run token-context harden --check
```

Windows has no POSIX mode bits, so the same command inspects the ACL instead and lists any
principal beyond the owner, `SYSTEM` and `Administrators`. Without `--check` it resets
inheritance and re-grants those three. That is worth checking on a machine where tooling has
added a group to the profile ACL — a sandbox users group there can read every snapshot.

Root, and on Windows `SYSTEM` and local administrators, can read the files regardless; that
is a property of the operating system, not something the tool can withhold. On a host you do
not control at that level, do not index a repository you would not disclose.

## Token and resource limits

The global registry has an enforceable `[server]` policy. Edit the TOML and restart Codex to apply a change:

```toml
[server]
max_request_bytes = 65536
max_result_tokens = 4096
max_graph_nodes = 200
max_symbol_results = 30
network_policy = "declared-deny-not-enforced"
output_mode = "structured"   # structured | text | legacy_dual | auto
default_view = "normal"
enable_extensions = true
```

- `enable_extensions`: enables discovery tools (`list_available_tools`, `search_tools`, `get_tool_schema`), shared state & memory tools (`memory_put`, `memory_get`, `memory_search`, `memory_lock`), and hardware-aware sampling (`sample_summarize`). Set `true` in `repos.toml` to activate these capabilities. Default: `false`.
- `output_mode`: controls serialization over MCP wire transport: `"structured"` (default, concise metadata summary in text + full payload in `structured_content`), `"text"` (compact JSON for text-only clients), `"legacy_dual"`, or `"auto"` (`structured` only for clients known to read it, otherwise `text`). `serve --output-mode` overrides the config value; `serve --schema-profile {auto,default,gemini_safe}` adjusts advertised tool schemas for strict clients.
- `default_view`: preset projection view for responses (`"minimal"` for IDs/paths only, `"normal"` for standard context, `"full"` for complete evidence).
- `max_result_tokens` caps output from maps, skeletons, symbol context, impact slices, and uncapped search/status responses. This is the main control for model-context consumption.
- `max_graph_nodes` caps impact-slice traversal.
- `get_module_dependents` reports Tree-sitter-extracted lexical import relationships; its `basis` is
  `lexical_import_statements`. It does not resolve imports semantically, and dynamic imports are flagged rather than resolved.
- `search_source` searches indexed symbol bodies and returns bounded snippets
  with source-backed symbol IDs and line evidence.
- `list_repositories` also advertises four named budget profiles: `locate`,
  `orient`, `impact`, and `read`. Pass `profile` to a retrieval tool to use
  one; explicit per-tool arguments override the profile. The response budget
  includes the reserved MCP envelope allowance.

Example profile-based calls:

```text
list_repositories()
get_repo_map(repo_id="myrepo", profile="orient")
find_symbols(repo_id="myrepo", pattern="Invoice", profile="locate")
get_impact_slice(repo_id="myrepo", symbol_id="...", profile="impact")
```

Lower values reduce tokens but cause more truncation and follow-up calls. The server limits only the context it returns; it cannot impose a hard provider billing limit for an entire Codex/model session.

## Deterministic context-cost checks

The repository includes a provider-free C1/C2 measurement script. It compares a
naive read of all source files with the serialized payloads returned by the
retrieval tools; all figures are local `utf8 bytes / 4` estimates, not billing
claims.

```powershell
uv run python evals/measure_context_cost.py `
  --repo-id token-context `
  --config $env:APPDATA\token-context-mcp\repos.toml `
  --output evals/reports/c1-token-context.json
```

The post-remediation measurements checked into this repository are:

| Repository | Naive source read | `repo_map` @1024 (wire) | Saving | Worst accounting gap | Calls over server cap |
| --- | ---: | ---: | ---: | ---: | ---: |
| `token-context` | 60,760 tok | 994 tok | 61.1x | 1.19x | 0 |
| `invoice-scanner` | 220,576 tok | 994 tok | 221.9x | 1.20x | 0 |

See [`evals/measure_context_cost.py`](evals/measure_context_cost.py),
[`evals/reports/c1-token-context-x1.json`](evals/reports/c1-token-context-x1.json)
and [`evals/reports/c1-invoice-scanner-x1.json`](evals/reports/c1-invoice-scanner-x1.json)
for the method and complete call table. These X1 measurements use the MCP
wire envelope and show zero calls over the configured 4,096-token cap. The
remaining gap between the service estimate and wire size is fixed framing;
the 96-token reserve keeps the emitted response within the requested cap.
The C3 protocol is recorded in [`evals/c3_protocol.md`](evals/c3_protocol.md);
the full provider-run matrix remains a separate runtime step.

## Updating existing installations

When updating `token-context-mcp` on a machine or remote VM where it is already set up (Codex, Claude Code, Claude Desktop, Antigravity, VS Code Remote-SSH), follow these steps:

### Windows (PowerShell)

```powershell
# 1. Go to the token-context-mcp repository
Set-Location D:\AI\token-context-mcp   # replace with your local path

# 2. Pull the latest code
git fetch origin
git pull origin main

# 3. Re-sync the environment / dependencies with uv
uv sync --all-extras

# 4. (Optional) run the tests to confirm the update
uv run pytest

# 5. Restart the MCP client (Codex CLI/IDE, Claude Code/Desktop, Antigravity)
# The client configuration does not need to change; the client starts the new code.
```

### Linux & macOS (Bash)

```bash
# 1. Go to the token-context-mcp repository
cd /path/to/token-context-mcp

# 2. Pull the latest code
git fetch origin
git pull origin main

# 3. Re-sync the environment / dependencies with uv
uv sync --all-extras

# 4. (Optional) run the tests
uv run pytest

# 5. Restart the MCP client
```

> **Upgrading to 0.3.x:** `PARSER_ARTIFACT_VERSION` (7), `FTS_BUILDER_VERSION` (2) and `RESOLVER_VERSION` (3) changed, so the first `uv run token-context index --all` after upgrading re-parses and re-indexes every file of every repository (run it once; no need to `register` again). If you skip it, the old index stays readable but keeps the old JS/TS/C# symbols and call graph.
>
> **Upgrading to 0.2.0:** the index schema changes to 2.4 and the parser artifact version changes (Go was added), so the first index run after the upgrade re-parses every file. Run `uv run token-context index --all` once. Older snapshots can still be read, but `get_index_status` warns that they need re-indexing.
>
> **About registered repositories and indexes:**
> - Your registry (`repos.toml`) and the index databases (`indexes/`) are kept as they are; you do not need to `register` again.
> - When the source of a repository changes, re-run the index command to refresh its snapshot:
>   `uv run token-context index --repo-id <repo-id>`

---

## Acknowledgments & Architecture Lineage

This project acknowledges architectural principles and advanced prompting techniques learned from, adopted and adapted out of the open-source [**Google Cloud Platform Generative AI Repository** (`GoogleCloudPlatform/generative-ai`)](https://github.com/GoogleCloudPlatform/generative-ai):

1. **Vectorless structured memory and memory consolidation:**
   - **Inspiration:** [`gemini/agents/always-on-memory-agent`](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/agents/always-on-memory-agent).
   - **Applied in `token-context-mcp`:** no heavyweight vector database for agent memory; a structured SQLite-first store with WAL. The `memory_consolidate` tool follows the idea of Google's `ConsolidateAgent`: merging fragmented memories into higher-level insights and avoiding duplicate-link growth (Google Issue #2945).

2. **Delimited context envelopes and quote-before-synthesize fact grounding:**
   - **Inspiration:** the [`gemini/prompts/`](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/prompts/) library and Google Cloud's text-extraction and safety-guardrail examples.
   - **Applied in `token-context-mcp`:** source code is wrapped in `<<<SOURCE_CODE_START>>>` / `<<<SOURCE_CODE_END>>>` with an instruction to treat it as untrusted data (protection against prompt injection from code comments). The 7B model must also extract a verbatim quote (`verbatim_quote`) before stating a `critical_constraints` conclusion.

3. **Tool-chaining cards (A2A):**
   - **Inspiration:** the Agent-to-Agent (A2A) protocol and the Agent Engine toolbox in [`agents/agent_engine/`](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/agents/agent_engine/).
   - **Applied in `token-context-mcp`:** `recommended_followups` (which tool to call next) and `prerequisites` metadata in `TOOL_CATALOG` and in `search_tools` / `get_tool_schema`, so agents can chain actions without guessing.

---

## Commands

- `register`: add a canonical, non-link repository root to a local TOML registry.
- `unregister`: remove a repository registration.
- `update`: change a repository root; requires `--force`.
- `index`: build an atomic SQLite snapshot and JSON manifest incrementally; `--all`, `--watch`, `--workers`, `--verify-hashes`, `--full`, `--progress-format ndjson`.
- `status`: inspect the stored snapshot and detect files changed after indexing.
- `harden`: restrict the registry and snapshots to the owning account; `--check` reports without changing.
- `serve`: start the MCP `stdio` server; `--output-mode`, `--schema-profile`.
- `benchmark-report`: calculate summary statistics from an instrumented JSONL run log.
- `release-materials`: produce an SBOM/provenance starter artifact; signing and OS sandbox evidence remain deployment responsibilities.

## Tool contract

The server exposes **20 tools** when `enable_extensions = true` (22 with `enable_admin_tools`; 10 core tools when extensions are disabled). `list_repositories` is the primary entry point for code retrieval: it returns the registered `repo_id` values and the budget profiles, and never exposes a repository root.

### 1. Core Code-Context Retrieval Tools (10 tools)

| Tool | Returns / Summary | `profile` | Purpose |
| --- | --- | --- | --- |
| `list_repositories` | registered `repo_id` values and four budget profiles | — | Entry point for repository queries; roots are never exposed. |
| `get_index_status` | snapshot metadata, freshness, `commit_sha`, edge precision, ambiguous rate | — | Check index health, freshness, and AST edge resolution stats. |
| `get_repo_map` | ranked definitions within a token budget, compact by default | `orient` | High-level architectural map of symbols and entry points. |
| `find_symbols` | symbols matching a name or qualified-name fragment, with spans | `locate` | Exact or pattern-based symbol location across the codebase. |
| `search_source` | FTS5 matches in symbol bodies and indexed files, with snippets | `locate` | Full-text code search across indexed symbols and source files. |
| `get_file_skeleton` | imports and source-backed headers for one file; bodies elided | `read` | File surface with ~95% token reduction vs full file read. |
| `get_symbol_context` | bounded packet around one symbol plus observed edges | `read` | Full symbol body, docstrings, and callers/callees. |
| `get_impact_slice` | caller/callee traversal from a symbol with confidence filtering | `impact` | Blast-radius candidate traversal (filtered by confidence >= 0.5). |
| `get_module_dependents` | Tree-sitter import relationships for a path or module | `impact` | Direct import dependency graph analysis. |
| `inspect_symbol` | composite: symbol resolution + definition context + 1-hop impact; `view="full"` returns a context packet (`data.packet`) | `read` | Single-turn inspection saving ~81% prompt replay tokens. |

### 2. Dynamic Tool Discovery Meta-Tools (3 tools)

Meta-tools that prevent LLM context-window exhaustion from massive tool definition catalogs.

| Tool | Parameters | Returns | Purpose |
| --- | --- | --- | --- |
| `list_available_tools` | `category` (optional) | Grouped summary of tools with token estimates | Compact catalog of tools without full schemas. |
| `search_tools` | `query` (required), `limit` (default: 3) | Ranked list of matching tools with relevance scores | Intent-based tool discovery via BM25 and tags. |
| `get_tool_schema` | `tool_name` (required) | Registered input schema of the requested tool (after the active schema profile) | Lazy on-demand schema loading for the LLM. |

### 3. Shared State & Long-term Memory Tools (5 tools)

Zero-daemon, SQLite-first persistent state storage, multi-agent coordination, and memory consolidation.

| Tool | Parameters | Returns | Purpose |
| --- | --- | --- | --- |
| `memory_put` | `key`, `value`, `scope` ("session"\|"global"), `ttl`, `session_id` | `{"stored": true, "key": ...}` | Persist state, plans, or cross-agent artifacts. |
| `memory_get` | `key`, `scope` ("session"\|"global") | Stored value and metadata, or error if not found | Retrieve state without bloating chat prompt history. |
| `memory_search` | `query`, `scope`, `limit` (default: 5) | Matching memory records ranked by FTS5 score | Full-text search over stored memory entries. |
| `memory_lock` | `resource_key`, `agent_id`, `timeout_sec` (default: 60) | `{"acquired": true/false, "expires_at": ...}` | Timed mutex lock preventing multi-agent collisions. |
| `memory_consolidate` | `scope`, `target_key`, `prune_transient` | `{"status": "consolidated", "insights": ...}` | Synthesize scattered memory checkpoints into high-level architectural insights (learned from Google Always-On Memory Agent). |

### 4. Hardware-Aware LLM Sampling (1 tool)

Local context compression adapted to host hardware resources.

| Tool | Parameters | Returns | Purpose |
| --- | --- | --- | --- |
| `sample_summarize` | `text`, `intent`, `max_tokens` (default: 250) | Compressed summary JSON | Summarizes code/context via local Ollama or heuristic fallback. |

Text taken from repositories is marked `untrusted_repository_content` and a possible prompt-injection line adds a `possible_prompt_injection` warning; treat it as data, never as instructions.

Call `list_repositories` first and pass a short registered `repo_id`; a filesystem path is
rejected. Explicit per-tool arguments override a profile.

---

## Extended Capabilities & Guide for the Newer Tools

These features address the two biggest problems of coding agents: **running out of token context window** and **no coordination or memory between sessions (multi-agent state and memory)**.

---

### 1. Removing ambiguous edges from the code graph (AST call extraction)

- **The old problem:** the earlier regex identifier scan matched common strings (`run`, `build`, `name`, `status`) indiscriminately, pushing the ambiguous-edge rate (`ambiguous_rate`) to 15–22%. Agents then hesitated and repeated expensive file reads ("paying twice").
- **The mechanism:**
  - A Tree-sitter AST query recognises `call_expression` precisely in Python, TypeScript/JS, Java and C# (Go edges are name based).
  - The receiver is recognised: `self.method()`, `cls.method()`, `this.method()` or `ClassName.method()`.
  - Calls are matched against the `imports` table in SQLite to find the exact source file and original definition.
  - Confidence has five levels (`0.95`, `0.85`, `0.70`, `0.40`, `0.10`).
  - Result: the **ambiguous rate fell from 10.5% to 2.4%** (edge resolution of **97.6%**).
- **Using it with `get_impact_slice`:**
  - `min_confidence`: minimum confidence (default `0.5`); weak guessed edges are dropped automatically.
  - `filter_ambiguous`: default `true`; ambiguous edges are filtered out so the agent only receives well-evidenced relations.

```python
# Example call with the automatic filter:
get_impact_slice(
    repo_id="token-context",
    symbol_id="src/token_context_mcp/server.py:build_server",
    direction="both",
    min_confidence=0.5,
    filter_ambiguous=True
)
```

---

### 2. Dynamic Tool Discovery (saves tokens)

- **Why:** if all tool JSON schemas are loaded into the system prompt on every turn, an agent spends 3,000–5,000 tokens (the "tool definition tax") per turn even when it needs one tool.
- **The three-step solution:**
  1. `list_available_tools(category="retrieval" | "memory" | "sampling" | "discovery")`: a short catalog with tool name, category and estimated tokens (~100 tokens instead of ~4,000).
  2. `search_tools(query="find callers and impact analysis", limit=3)`: BM25 plus tag matching finds the tool that fits the agent's intent.
  3. `get_tool_schema(tool_name="get_impact_slice")`: lazy schema loading; the detailed schema enters the context only for the tool the agent chose.

#### Example: an agent finding its own tool
```text
Step 1: the agent looks for a tool to lock a resource
> search_tools(query="lock shared resource mutex", limit=2)
< {"tools": [{"name": "memory_lock", "score": 8.5, "description": "Acquire a timed mutex lock..."}]}

Step 2: the agent fetches the schema of memory_lock
> get_tool_schema(tool_name="memory_lock")
< full JSON schema with resource_key, agent_id, timeout_sec

Step 3: the agent calls the tool without having spent extra tokens earlier
> memory_lock(resource_key="auth_module", agent_id="agent_1", timeout_sec=120)
```

---

### 3. Shared state & long-term memory (multi-agent coordination)

- **SQLite-first architecture:** runs entirely locally through a `memory.sqlite` file (in the same directory as `repos.toml`). No Redis, ChromaDB or Docker to install or run.
- **Durable and safe:** SQLite WAL mode, FTS5 full-text search, and automatic cleanup of records past their TTL.

#### The memory tools
1. `memory_put`:
   - Stores execution state, architecture plans or analysis summaries for reuse across chat sessions or between agents.
   - Parameters:
     - `key` (required): identifier (e.g. `"plan:refactor_auth"`, `"benchmark_baseline"`).
     - `value` (required): text, JSON or a structured object.
     - `scope`: `"session"` (current session) or `"global"` (shared by every session).
     - `ttl`: lifetime in seconds (default 86400 s = 24 h; `null` to keep forever).
     - `session_id`: optional session grouping label.
2. `memory_get`: retrieves stored data by `key` and `scope` in one turn at minimal token cost.
3. `memory_search`: FTS5 full-text search of the shared memory by keyword, so an agent can find conclusions and analysis notes from earlier sessions without re-reading the code.
4. `memory_lock`:
   - A timed **soft-mutex lease** that coordinates several agents working on one codebase without overwriting each other or creating race conditions.
   - After `timeout_sec` (default 60 s) the lock is released automatically, which prevents deadlock if an agent crashes.
5. `memory_consolidate` *(inspired by the Google Cloud GenAI Always-On Memory Agent)*:
   - **Compress and merge memory:** like human sleep or Google's `ConsolidateAgent`, it scans the fragmented checkpoints saved in a session, synthesises them into a complete architectural summary (`project_architectural_insights`), removes duplicate links and cleans up transient notes (`prune_transient=True`).

#### Example: agents coordinating through memory
```python
# Agent 1 (architect) plans and stores the plan
memory_put(
    key="refactor_plan",
    value='{"target": "auth.py", "steps": ["extract JWT", "add middleware"]}',
    scope="global"
)

# Agent 2 (developer) takes the job and acquires the lock before editing
lock = memory_lock(resource_key="file:auth.py", agent_id="coder_subagent", timeout_sec=180)
if lock["acquired"]:
    plan = memory_get(key="refactor_plan", scope="global")
    # refactor according to the plan...
```

---

### 4. Hardware-aware 7B sampling & guardrail engine

- **Goal:** compress context with a **7B** model (`qwen2.5-coder:7b-instruct-q4_K_M`) while preserving logic and edge conditions, and keep it running smoothly on machines without a GPU (CPU-only guarantee).
- **Four layers of protection:**
  1. **Semantic anchors and hybrid skeleton (no blind truncation):**
     - Tree-sitter extracts the anchor symbols (`verified_symbol_names`) first.
     - When the text exceeds the context threshold (> 3,000 characters), the system keeps the `file_skeleton` (imports, classes, method signatures) and embeds only the full bodies of symbols directly related to `user_raw_intent`, removing the risk of blind cut-off.
  2. **Pure-CPU optimisation:**
     - Threads: `num_thread = max(1, os.cpu_count() - 1)` (one core is left free so the MCP stdio process stays responsive).
     - Adaptive dynamic timeout, scaled to the context length:
       $$\text{Timeout (seconds)} = \text{base\_timeout (5s)} + \left(\frac{\text{input\_tokens}}{100} \times \text{sec\_per\_100\_tok}\right)$$
       This avoids static timeouts that drop the connection midway on a CPU.
  3. **Pydantic v2 constrained JSON decoding (no broken JSON):**
     - The model output must follow the `CodeSummaryPayload` schema:
       - `intent_alignment`: how well the text answers the user's intent.
       - `analyzed_symbols`: symbols with `name`, `responsibility`, `critical_constraints` (`if-else` conditions, `raise` exceptions) and `calls_external`.
       - `technical_caveats`: technical notes, assumptions, timeouts.
  4. **Verification guardrail (against hallucination):**
     - The symbols generated by the model are checked against the Tree-sitter anchors; symbols that do not exist in the source are stripped.
     - Metadata is attached: `backend` (`ollama_gpu` | `ollama_cpu` | `heuristic_fallback`), `engine`, `latency_ms`, `symbol_coverage_rate`, `context_retention_rate`.

#### Calling `sample_summarize`
```python
sample_summarize(
    text=very_long_analysis_output,
    intent="validate refund logic and exception handling",
    max_tokens=512,
    target_symbols=["PaymentService.refund"]
)
```

---

### 5. End-to-end workflow

A sample workflow that combines all 20 tools:

```
[Agent starts]
       |
       v
1. list_available_tools(category="retrieval") --> ~100 tokens to get oriented
       |
       v
2. get_repo_map(repo_id="my-repo", profile="orient") --> overall architecture
       |
       v
3. inspect_symbol(repo_id="my-repo", symbol_name="AuthService") --> three steps in one turn
       |
       v
4. get_impact_slice(..., filter_ambiguous=True) --> only well-evidenced edges (2.4% ambiguous)
       |
       v
5. sample_summarize(text=impact_data, max_tokens=200) --> compressed by a local Ollama model (no cost)
       |
       v
6. memory_put(key="auth_impact_summary", value=compressed_data) --> stored in SQLite memory
       |
       v
[Other agents call memory_get("auth_impact_summary") immediately, without re-analysing]
```

`get_repo_map` defaults to a compact `symbols` array. Each entry is
`[short_symbol_id, "path:line", "kind/name", optional_rank_marker]`; pass the
first field to a follow-up symbol or impact tool. The optional marker is one
of `E` (declared entry point), `W` (registry wiring), `D` (protocol
definition), `I` (protocol implementation), or `M` (module entry point). Use
`format="full"` when detailed per-symbol provenance and `rank_basis` are
needed. Compact responses keep file SHA-256 digests once in the
`file_digests` map instead of repeating evidence for every symbol.

Every result is a JSON envelope with `index_run_id`, `freshness`, budget, warnings and source evidence. A lexical edge is explicitly marked `ambiguous`; an unresolved edge is not proof that no relation exists.

## Development

```powershell
uv run pytest
uv run token-context release-materials --output supply-chain
```

Supported operating systems, remote/SSH placement, every limit and the permission model are in [`docs/PLATFORMS.en.md`](docs/PLATFORMS.en.md) ([tiếng Việt](docs/PLATFORMS.vi.md)). Step-by-step setup for every supported agent — Claude Code, Codex, GitHub Copilot (VS Code and CLI), Antigravity — is in [`docs/SETUP.en.md`](docs/SETUP.en.md) ([tiếng Việt](docs/SETUP.vi.md)). Which question shapes actually save tokens is in [`docs/PROMPTING.en.md`](docs/PROMPTING.en.md) ([tiếng Việt](docs/PROMPTING.vi.md)). The procedure for running the full C3 benchmark matrix is in [`docs/X6_RUNBOOK.en.md`](docs/X6_RUNBOOK.en.md) ([tiếng Việt](docs/X6_RUNBOOK.vi.md)).

See [`SECURITY.md`](SECURITY.md) and [`docs/`](docs/) for the threat model, integration instructions and benchmark protocol.
