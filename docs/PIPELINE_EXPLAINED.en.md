# token-context-mcp — Source, Config, Pipeline, Token Economics, SWOT

**Written:** 2026-08-27 · **Against:** version 0.1.0, 2083 lines across 27 modules in `src/token_context_mcp/`
**Method:** the architecture is read from source; every number in §4 was measured by running the service on this machine against two registered repositories.

---

## 1. What the package is

A **read-only, local MCP `stdio` server** that indexes explicitly registered repositories into a SQLite snapshot and answers six retrieval tools with small, source-hashed context packets.

The design premise is negative and stated plainly in the README: *reduce broad repository crawling without pretending that syntax analysis is a complete semantic model.* Almost every design decision follows from taking that limitation seriously.

Non-goals, enforced in code: it does not edit files, run shell commands, listen on HTTP, call network APIs, or accept arbitrary paths.

---

## 2. The modules

### 2.1 Foundation

| Module | Lines | Role |
|---|---|---|
| `constants.py` | 24 | Limits and deny-lists. `SUPPORTED_EXTENSIONS` maps 6 suffixes to 4 grammars; `HARD_DENY_DIRECTORIES` blocks `.git`, `.ssh`, `.aws`, `.gnupg`, `node_modules`, `.venv`, `site-packages`, caches; `HARD_DENY_FILE_NAMES` and `HARD_DENY_SUFFIXES` block `id_rsa`, `credentials.json`, `.pem`, `.key`, `.p12`, `.kdbx` |
| `models.py` | 94 | Six frozen dataclasses — `RepositoryConfig`, `ServerConfig`, `AppConfig`, `FileRecord`, `SymbolRecord`, `EdgeRecord`, plus `Evidence`. Frozen throughout: a snapshot record cannot be mutated after it is read |
| `config.py` | 139 | TOML registry load/save, `repo_id` validation against `^[a-z][a-z0-9_-]{0,63}$`, and **bounds-checking on every server limit** at load time |

`default_config_path()` is worth calling out. It resolves `TOKEN_CONTEXT_CONFIG` → `%APPDATA%` (Windows) → `$XDG_CONFIG_HOME` → `~/.config`, and the docstring says why: *"the default must not depend on the process working directory because Codex starts an MCP process from many different repositories."* One global registry per user, deliberately.

### 2.2 Security

| Module | Lines | Role |
|---|---|---|
| `security/path_policy.py` | 67 | Path containment. `canonical_repository_root` resolves strictly and refuses symlinks/reparse points. `safe_relative_path` rejects NUL bytes, absolute paths, drive letters, UNC prefixes and any `.`/`..` segment, then resolves and re-checks `relative_to(root)`, then walks **each path component** checking for reparse points |
| `security/content_policy.py` | 39 | `is_hard_denied` on the relative path; `redact_text` replaces whole lines matching a secret-assignment regex or a PEM header with `[REDACTED: potential secret]` and returns a count; `is_probably_binary` looks for NUL in the first 8 KB |

The reparse-point check is Windows-specific and correct: `os.lstat(path).st_file_attributes & 0x400` catches junctions that `is_symlink()` misses.

### 2.3 Indexing

| Module | Lines | Role |
|---|---|---|
| `index/hashing.py` | 17 | SHA-256 over bytes and over files in 1 MB chunks |
| `index/freshness.py` | 22 | `pending_paths` re-hashes indexed files against disk. Its docstring states the trade-off: *"detect source changes without a persistent watcher or filesystem writes"* |
| `index/sqlite_store.py` | 291 | Schema and access. Five tables — `metadata`, `files`, `symbols`, `edges`, `imports` — with indices on `symbols(path)`, `symbols(name)`, `edges(source_symbol_id)`, `edges(target_symbol_id)`. Read connections use `file:…?mode=ro` |
| `index/runner.py` | 215 | The indexing pipeline (§3) |

### 2.4 Parsing

| Module | Lines | Role |
|---|---|---|
| `parse/treesitter.py` | 200 | Tree-sitter walk. `_NODE_KINDS` maps grammar node types to symbol kinds per language. Extracts signature (start byte → body start byte), line and byte spans, `is_private` from a leading underscore. `symbol_id` = `{language}:{path}:{qualified_name}:{sha256[:16]}` |
| `parse/lexical_edges.py` | 65 | Identifier-match edges. For each symbol body, every identifier is looked up in a name index; **exactly one** match → `resolved` at confidence 0.55; several → `ambiguous` at 0.2; `edge_kind` is `call` if a `(` follows, else `reference`. Capped at 100 edges per symbol, then deduplicated |
| `parse/lsp.py`, `parse/scip.py` | 28 + 27 | **Deliberate stubs.** Both return `enabled: False` with a reason. Neither spawns a process |

The stubs are a design statement rather than a gap: a language server is an executable dependency that must be pinned, sandboxed and validated before it may add semantic edges. The package declares the boundary instead of crossing it quietly.

### 2.5 Retrieval

| Module | Lines | Role |
|---|---|---|
| `retrieve/token_budget.py` | 33 | `estimate_tokens` = `ceil(utf8_bytes / 4)`, versioned `utf8-bytes-div-4-v1`. `pack_by_budget` greedily fills to a budget and returns `(chosen, omitted, used)` |
| `retrieve/ranking.py` | 25 | Score = `1.0 + 2.0·in_degree + 0.5·out_degree + 8.0·(per query term hit) + 0.25·(class or interface)` |
| `retrieve/service.py` | 416 | The six tools, the graph traversal, and the response envelope |
| `server.py` | 135 | MCP tool registration. `_invoke` catches everything and returns a generic error — no stack traces, no path leakage |

---

## 3. The pipeline, phase by phase

```
  register ──> [P1 inventory] ──> [P2 parse] ──> [P3 edges] ──> [P4 snapshot]
                                                                    │
   MCP tool call <── [P7 envelope] <── [P6 budget] <── [P5 retrieve]┘
```

### P0 — Registration (`config.register_repository`)

An explicit local allowlist decision. `repo_id` is validated against the regex; `root` is canonicalised and refused if it is missing, not a directory, or a reparse point. **Re-registering an existing `repo_id` raises** rather than silently rebinding a name to a new root — an unusual and correct choice, since a silent rebind would redirect every future tool call.

Written atomically: build the full TOML in memory → write `repos.toml.tmp` → `replace()`.

### P1 — Inventory (`runner._inventory`)

`os.walk(topdown=True, followlinks=False)`, pruning `directories[:]` in place so denied subtrees are never descended. Three filters, applied to directories and files alike: reparse point, hard-deny list, and the repository's own `.gitignore` (via `pathspec.GitIgnoreSpec`). Exceeding `max_files` raises rather than truncating silently.

The result is sorted, which makes the snapshot deterministic for a fixed tree.

### P2 — Parse (`runner.build_index` + `treesitter.parse_source`)

Per file: read bytes → skip if over `max_file_bytes` or binary → record `FileRecord` with SHA-256 → parse if the extension is supported.

**The incremental path is the important part.** Before parsing, the runner opens the *previous* snapshot read-only and reuses the parse when `previous.sha256 == current.sha256` and the previous status starts with `parsed` — copying symbols and imports straight from the old database. The manifest then reports `files_reused` and `files_reparsed` separately, so reuse is auditable rather than assumed.

Parse failures are contained: the file is kept with `parse_status: "parse_error"` and a warning, never dropped silently. A tree containing error nodes still yields symbols, flagged `parsed_with_warnings`.

### P3 — Edge construction (`build_lexical_edges`)

Runs once over all symbols after every file is parsed, because resolution needs the global name index.

This phase is where the package is most honest about its own weakness. An edge is `resolved` only when a name has **exactly one** definition anywhere in the repository. Two functions named `run` anywhere in the tree make every reference to `run` ambiguous. Confidence is hard-coded — 0.55 resolved, 0.2 ambiguous — and those are declared constants, not calibrated probabilities.

### P4 — Snapshot (`sqlite_store.write_snapshot` + atomic replace)

Write to `{repo_id}.tmp-{uuid}.sqlite`, then `shutil.move` over the destination after unlinking stale `-wal`/`-shm` files. A reader either sees the whole previous snapshot or the whole new one.

The manifest is written twice on purpose: once to compute the database's SHA-256, then again with `artifact_sha256` embedded.

### P5 — Retrieval (`RetrievalService`)

Six tools, each opening the SQLite snapshot **read-only**:

| Tool | Answers | Bound by |
|---|---|---|
| `get_repo_map` | "What is in this repository?" | `budget_tokens` |
| `find_symbols` | "Where is X defined?" | `limit`, capped by `max_symbol_results` |
| `get_file_skeleton` | "What is in this file?" | `max_tokens` |
| `get_symbol_context` | "What does this symbol look like and touch?" | `max_tokens`, `depth` ≤ 3 |
| `get_impact_slice` | "What might break if I change this?" | `max_nodes`, capped by `max_graph_nodes` |
| `get_index_status` | "Is the index still valid?" | — |

`get_file_skeleton` is the clearest illustration of the core idea: it returns **import lines plus symbol headers with bodies elided**, reserving a quarter of the budget for imports before packing headers into the rest.

Traversal (`_traverse`) is BFS with a `visited` set and a `max_nodes` ceiling checked in both the loop condition and the enqueue branch.

### P6 — Budget packing

`pack_by_budget` walks ranked items and admits each while `used + estimated ≤ budget`, with one carve-out: the first item is admitted even if it alone exceeds the budget, so a request never returns empty. Omitted items are returned, not discarded — the caller learns what it did not get.

### P7 — Envelope

Every response carries the same shape, and it is the most mature part of the design:

```json
{ "schema_version", "repo_id", "index_run_id",
  "freshness": "fresh|stale",
  "budget": {"requested_tokens", "estimated_tokens"},
  "truncated": bool,
  "completeness": {"value", "basis"},
  "warnings": [...],
  "evidence": [{"path","start_line","end_line","sha256"}],
  "data": {...} }
```

`completeness` carries its own `basis` string (`resolved_edges / observed_edges`, or `no_edges_observed`) so a number is never separated from what produced it. Warnings are explicit about epistemics: `lexical_edges_are_not_complete_semantic_analysis`, `ambiguous_lexical_edges_present`, `indexed_hash_differs_from_current_file`, `potential_secrets_redacted`, `network_policy_not_enforced_by_process`.

Freshness is computed by re-hashing every indexed file on **every** call.

---

## 4. Token economics — mechanism, and what it actually measures

### 4.1 The four mechanisms

1. **Signature instead of body.** A symbol costs its header, not its implementation. `get_file_skeleton` on a 2,396-token source file returns ~1,008 tokens.
2. **Ranking instead of enumeration.** In-degree, out-degree and query-term hits decide what a fixed budget is spent on, so the first N items are the connected, query-relevant ones.
3. **Hard budget instead of hope.** The caller states `budget_tokens`; the packer stops. What was dropped comes back as `omitted_count` and `omitted_symbol_ids`.
4. **Snapshot instead of re-reading.** Parsing happens once per content hash. Unchanged files are reused from the previous database.

### 4.2 Measured on this machine

Baseline = reading every `.py` file under `src/` at `bytes/4`.

| Repository | Baseline | `repo_map` @1024 payload | **Real ratio** |
|---|---|---|---|
| Repository A (38 files, 273 KB) | 68,259 tok | 8,849 tok | **7.7x** |
| Repository B — this repo (27 files, 81 KB) | 20,370 tok | 7,803 tok | **2.6x** |

A real saving, and worth having. But the declared budget is not what arrives.

### 4.3 The budget under-counts the payload

`pack_by_budget` measures the *rendered* string it is handed. `get_repo_map` renders `f"{path}:{line} {signature}"` for packing — then emits the full `symbol_as_dict()` **plus** an `evidence` block per symbol.

One entry, measured:

```
what pack_by_budget measured : 20 tokens   'src/.../error_codes.py:25 class PipelineException(Exception)'
what is actually emitted     : 158 tokens  (symbol_id, qualified_name, 4 byte offsets, is_private, evidence+sha256)
```

Across the whole `repo_map` response at `budget_tokens=1024`:

| Tool | `estimated_tokens` | Actual payload | Gap |
|---|---|---|---|
| `repo_map` @1024 | 1,020 | 8,849 | **8.7x** |
| `file_skeleton` @1024 | 192 | 1,008 | 5.2x |
| `symbol_context` @1024 | 395 | 7,253 | **18.4x** |
| `symbol_context` @2048 | 395 | 7,253 | 18.4x — *identical; `max_tokens` does not bind* |
| `find_symbols` limit=5 | 575 | 895 | 1.6x |
| `impact_slice` d=2 n=50 | 25,141 | 28,618 | 1.1x |

Where the 8,849 goes:

```
symbol dicts        4,411
omitted_symbol_ids  2,321   <- 2.3x the entire declared budget, spent listing what was left out
evidence            1,633   <- a 64-char SHA-256 per symbol
envelope overhead      39
```

`omitted_symbol_ids` costs more than twice the budget the caller asked for. Each id is a full `python:path/to/file.py:Qualified.Name:hexdigest` string, and up to 100 are returned.

### 4.4 `impact_slice` has no token bound at all

Measured against a server configured with `max_result_tokens = 2048`:

```
impact_slice(depth=2, max_nodes=50) -> 28,618 tokens, truncated: False
```

Fourteen times the configured ceiling, and flagged as *not* truncated. Three code paths combine:

- `impact_slice` never calls `_validate_budget` — that check only runs where a budget parameter exists.
- It passes `requested_tokens=0`, and `_envelope` computes `truncated` as `(estimated > requested if requested else False)`. Zero is falsy, so `truncated` is `False` by construction.
- Its only bound is `max_nodes`, which bounds *graph nodes*, not tokens. Fifty symbols and 182 edges serialise to 28 KB of JSON.

The same `requested_tokens=0` pattern applies to `find_symbols` and `status`, where the payloads happen to be small.

**None of this makes the tool useless** — 7.7x on orientation is real. It means the numbers a caller sees in `budget` are not the numbers the model pays for, and one tool can blow through the configured ceiling without saying so.

### 4.5 There is no end-to-end evidence yet

`evals/sample-runs.jsonl` contains **two records** — one `B0`, one `B1`. The resulting `median_paired_token_reduction: 0.254` has `paired_count: 1` and a CI95 of `[0.254, 0.254]`: a degenerate interval from a single synthetic pair.

The repository does not hide this. `BENCHMARK.md` says a publishable result requires paired B0–B6 tasks with the same model, prompt, permissions and seed, using provider-reported token counts. The harness itself is sound — paired reduction, deterministic bootstrap, a quality non-inferiority delta so a token win that breaks the task is visible. It has simply never been fed a real run.

---

## 5. Config files

| File | Purpose |
|---|---|
| `%APPDATA%\token-context-mcp\repos.toml` | The live per-user registry: `[server]` limits and one `[repos.<id>]` block per repository. Overridable via `TOKEN_CONTEXT_CONFIG` |
| `%APPDATA%\token-context-mcp\indexes\<repo_id>.sqlite` | The snapshot. Path derived as `config_path.parent / "indexes"` |
| `%APPDATA%\token-context-mcp\indexes\<repo_id>.manifest.json` | Run metadata plus `artifact_sha256` of the database |
| `config/repos.example.toml` | Template |
| `.mcp.json` | Claude Code / Codex `stdio` launch config |
| `schemas/index-manifest.schema.json`, `schemas/mcp-result.schema.json` | JSON Schema for the manifest and the response envelope |

`[server]` keys, with the ranges enforced at load:

| Key | Range | Effect |
|---|---|---|
| `max_request_bytes` | 1,024 – 1,048,576 | Rejects oversized tool arguments |
| `max_result_tokens` | 32 – 8,192 | Ceiling on any `budget_tokens` / `max_tokens` — **not applied to `impact_slice`** |
| `max_graph_nodes` | 1 – 500 | Caps traversal breadth |
| `max_symbol_results` | 1 – 100 | Caps `find_symbols` |
| `network_policy` | string | Declared only. The manifest states `declared_only; enforce at OS/container boundary` |

Per-repository: `root`, `allow_symlinks` (default `false`), `max_file_bytes` (2 MB), `max_files` (25,000).

---

## 6. SWOT

### Strengths

- **Epistemic honesty is implemented, not just documented.** `completeness.basis`, `lexical_edges_are_not_complete_semantic_analysis`, `enabled: False` stubs with reasons, `evidence` with a SHA-256 on every claim. Very few retrieval tools tell the caller how much to trust the answer.
- **Security is layered and enforced at the boundary.** Registration allowlist → deny-lists → gitignore → reparse-point checks per path component → containment re-check after resolve → secret redaction → read-only SQLite → generic errors. Path traversal and junction escapes are handled properly on Windows.
- **Snapshot atomicity and reuse.** Temp-file-then-replace means a reader never sees a half-written index; hash-keyed reuse makes re-indexing cheap and reports `files_reused` honestly.
- **Small and legible.** 2083 lines, frozen dataclasses, no inheritance hierarchies. The whole thing can be read in an afternoon and audited in a day.
- **Deterministic.** Sorted inventory, sorted imports, seeded bootstrap, versioned estimator string.

### Weaknesses

- **The budget does not measure the payload** (§4.3). 8.7x under-count on `repo_map`, 18.4x on `symbol_context`. `omitted_symbol_ids` alone exceeds the requested budget by 2.3x.
- **`impact_slice` is unbounded in tokens** (§4.4). 28,618 tokens from a 2,048-token server, marked `truncated: false`.
- **`symbol_context`'s `max_tokens` does not bind.** Identical payload at 1024 and 2048 — the `edges` array is emitted outside the packer.
- **Lexical edges resolve only globally-unique names.** Any repository with two `run`, `main` or `handle` definitions degrades toward ambiguity. Confidence values are constants, never calibrated.
- **Freshness costs a full re-hash per call.** `_freshness` re-hashes every indexed file on every tool invocation; on `video-lecturer` that is 4,559 files.
- **Four languages only.** No Go, Rust, Java, C#, Ruby, PHP. Markdown, JSON, YAML and TOML are indexed as files but yield no symbols.
- **No measured end-to-end saving** (§4.5). Two sample rows.
- **CLI ergonomics fail silently.** `python -m token_context_mcp.cli register …` exits 0 and does nothing — `cli.py` has no `__main__` guard. Separately, `uv run token-context …` fails while the MCP server holds the console script on Windows.
- **`repo_id` cannot be re-pointed.** Correct as a safety property, but there is no `unregister` or `update` command, so the only path is hand-editing the TOML.

### Opportunities

- **Fix the accounting and the real ratio improves.** Dropping `omitted_symbol_ids` to a count, trimming byte offsets from emitted symbols, and truncating evidence hashes to 12 characters would cut the `repo_map` payload from 8,849 toward ~4,000 with no loss of usable content — roughly doubling the measured 7.7x.
- **Budget the envelope, not the render.** Packing against `estimate_tokens(json.dumps(entry))` would make `estimated_tokens` mean what a caller assumes it means.
- **Run the benchmark for real.** The harness is finished; it needs paired B0–B6 tasks against a provider. That converts the central claim from plausible to demonstrated.
- **Cheap freshness.** Check `mtime_ns` and `size` first, hashing only when they differ. `FileRecord` already stores both.
- **The stubs are ready to activate.** `SemanticBackendStatus` is designed; a pinned, sandboxed `pyright`/`tsserver` would upgrade `confidence` from a constant to a measurement.
- **Languages are cheap to add.** Adding a grammar is one `SUPPORTED_EXTENSIONS` entry plus one `_NODE_KINDS` block.

### Threats

- **A false sense of coverage.** `repo_map` with `truncated: true` and 133 omitted symbols can read like a complete map. The envelope says otherwise, but envelopes get skimmed.
- **Silent budget overrun.** An agent trusting `budget.estimated_tokens` for context planning will be wrong by 8–18x, and `impact_slice` can inject 28 KB unannounced. This is the threat most likely to bite in production.
- **Ambiguity growth with repository size.** Lexical resolution degrades as name collisions increase — precisely where the tool is most needed.
- **Stale-index drift.** `freshness` reports it, but nothing prevents serving a stale snapshot; a caller that ignores the field gets confidently wrong line numbers.
- **`network_policy` reads like enforcement.** It is declarative. The manifest and warnings say so, but the key name invites the wrong assumption.
- **Redaction is regex-based.** A secret not matching `key|secret|token|password|private_key|authorization` assignment shapes passes through. It reduces exposure; it does not prevent it.

---

## 7. Priority reading order

1. `constants.py` and `models.py` — the vocabulary
2. `index/runner.py:build_index` — P1 to P4 in one function
3. `retrieve/service.py:_envelope` — the contract every answer honours
4. `parse/lexical_edges.py` — where precision is lost, and where it is declared
5. `retrieve/token_budget.py` — 33 lines, and the source of §4.3
