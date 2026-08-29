# Token Context MCP

`token-context-mcp` is a read-only local MCP server that indexes registered repositories and returns small, source-hashed code-context packets. It is designed to reduce broad repository crawling without pretending that syntax analysis is a complete semantic model.

## What is implemented in 0.1.0

- explicit repository registration; MCP tools receive a `repo_id`, never an arbitrary path;
- Tree-sitter parsing for Python, JavaScript and TypeScript/TSX;
- SQLite snapshots with files, symbols, lexical edges, manifests and source hashes;
- token-budgeted repository maps, source-backed skeletons, symbol context and bounded impact slices;
- FTS5 search over symbol bodies and complete indexed files, returning bounded snippets with symbol IDs and line spans;
- Tree-sitter import relationships served directly, rather than inferred from the lexical call graph;
- lexical resolution that prefers same-file and same-package definitions before the global name index;
- compact repository-map encoding and four named budget profiles (`locate`, `orient`, `impact`, `read`);
- truncation and cap warnings computed from actual results, not from the request;
- strict read-only tool surface over MCP `stdio`;
- hard deny rules for secrets/metadata, path traversal/reparse-point checks and resource limits;
- security, integration and benchmark harnesses that report evidence rather than claiming universal savings.

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

Median paired total-token reduction: **−0.3%**, CI95 **−53% to +33%**, n=3. **This does not support a headline token-saving claim**, and none is made — the full 5-task × 3-seed matrix is still pending. What it does support is that *the shape of the question decides the outcome*: savings come from localisation, not enumeration. See [`docs/PROMPTING.en.md`](docs/PROMPTING.en.md) ([tiếng Việt](docs/PROMPTING.vi.md)) for which questions to ask.

Two figures worth reading before interpreting any of the above: `cached_input_tokens` was **89–92% of input** in every pilot row, and in one run retrieved content was 2,558 tokens against 120,832 cached — **2%** of the total. A `total_tokens` delta mostly measures conversation length, which is why the primary metric is retrieved content.

## Non-goals and security boundary

This server does not edit files, execute shell commands, listen on HTTP, call network APIs, or accept arbitrary repository paths. `stdio` is not an OS sandbox: deploy with a no-egress/least-privilege policy if an enforced network boundary is required. Tool results may still be placed in the MCP host's LLM context.

## Quick start

```powershell
uv sync --extra dev
uv run token-context register --repo-id demo --root D:\AI\some-repo
uv run token-context index --repo-id demo
uv run token-context status --repo-id demo
uv run token-context serve
```

By default the registry is global for the current Windows user at `%APPDATA%\token-context-mcp\repos.toml`; it is independent of the current working directory. Set `TOKEN_CONTEXT_CONFIG` to use an explicit shared/portable TOML path. For Codex, launch the package through a configured `stdio` MCP command. Use only the read-only tools listed by the server.

## Register repositories safely

Registration is an explicit local allowlist decision, not an upload, Git operation, or source-code change. `--repo-id` is a stable identifier used in MCP requests; `--root` is the only canonical repository directory that the server is allowed to read.

```powershell
Set-Location D:\AI\token-context-mcp
uv run token-context register --repo-id video-lecturer --root D:\AI\video_lecturer
uv run token-context index --repo-id video-lecturer
uv run token-context status --repo-id video-lecturer
```

Use a specific project root, never a broad parent such as `D:\AI`. Re-run `index` after relevant changes; it reuses unchanged parsing results. Existing registrations and index databases are shared by every MCP process launched under the same Windows user.

To use a different registry location for one terminal or a portable deployment, set it before registering, indexing, and starting the MCP server:

```powershell
$env:TOKEN_CONTEXT_CONFIG = 'D:\trusted-shared-config\repos.toml'
uv run token-context register --repo-id myrepo --root D:\projects\myrepo
uv run token-context index --repo-id myrepo
```

## Use from coding agents

This is a local MCP `stdio` server. It works with a client that can start local processes and has `uv` available on its `PATH`. Each client process launched under the same Windows user automatically reads the same global repository registry. Restart the client after changing the registry or its policy.

| Client | Local `stdio` support | Setup status |
| --- | --- | --- |
| Codex CLI / IDE | Yes | Installed and end-to-end tested on this machine. |
| Claude Code | Yes | Supported; add it at user or project scope. |
| GitHub Copilot CLI | Yes | Supported through the CLI user configuration or project config. |
| GitHub Copilot Chat in VS Code | Yes | Supported through `.vscode/mcp.json` or the MCP UI. |
| Google Antigravity IDE / CLI | Yes | Supported through global or workspace `mcp_config.json`. |
| Claude Desktop | Conditional | It supports local MCP through Desktop Extensions, but this project does not yet publish a `.dxt` package. |

Cloud/web agents cannot start this server on this Windows machine. They need a separately deployed, authenticated HTTP MCP service; this project intentionally ships only local `stdio` transport.

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

## Token and resource limits

The global registry has an enforceable `[server]` policy. Edit the TOML and restart Codex to apply a change:

```toml
[server]
max_request_bytes = 65536
max_result_tokens = 4096
max_graph_nodes = 200
max_symbol_results = 30
network_policy = "declared-deny-not-enforced"
```

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

## Commands

- `register`: add a canonical, non-link repository root to a local TOML registry.
- `unregister`: remove a repository registration.
- `update`: change a repository root; requires `--force`.
- `index`: build an atomic SQLite snapshot and JSON manifest.
- `status`: inspect the stored snapshot and detect files changed after indexing.
- `serve`: start the MCP `stdio` server.
- `benchmark-report`: calculate summary statistics from an instrumented JSONL run log.
- `release-materials`: produce an SBOM/provenance starter artifact; signing and OS sandbox evidence remain deployment responsibilities.

## Tool contract

Nine read-only tools. `list_repositories` is the entry point: it returns the registered
`repo_id` values and the budget profiles, and never exposes a repository root.

| Tool | Returns | `profile` |
| --- | --- | --- |
| `list_repositories` | registered `repo_id` values and the four budget profiles | — |
| `get_index_status` | snapshot metadata, freshness, edge precision, derived defaults | — |
| `get_repo_map` | ranked definitions within a token budget, compact by default | `orient` |
| `find_symbols` | symbols matching a name or qualified-name fragment, with spans | `locate` |
| `search_source` | FTS5 matches in symbol bodies and indexed files, with snippets and IDs | `locate` |
| `get_file_skeleton` | imports and source-backed headers for one file; bodies elided | `read` |
| `get_symbol_context` | a bounded packet around one symbol plus observed edges | `read` |
| `get_impact_slice` | caller/callee traversal from a symbol — a candidate, not a proof | `impact` |
| `get_module_dependents` | Tree-sitter import relationships for a path or module | `impact` |

Call `list_repositories` first and pass a short registered `repo_id`; a filesystem path is
rejected. Explicit per-tool arguments override a profile.

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

Step-by-step setup for every supported agent — Claude Code, Codex, GitHub Copilot (VS Code and CLI), Antigravity — is in [`docs/SETUP.en.md`](docs/SETUP.en.md) ([tiếng Việt](docs/SETUP.vi.md)). Which question shapes actually save tokens is in [`docs/PROMPTING.en.md`](docs/PROMPTING.en.md) ([tiếng Việt](docs/PROMPTING.vi.md)). The procedure for running the full C3 benchmark matrix is in [`docs/X6_RUNBOOK.en.md`](docs/X6_RUNBOOK.en.md) ([tiếng Việt](docs/X6_RUNBOOK.vi.md)).

See [`SECURITY.md`](SECURITY.md) and [`docs/`](docs/) for the threat model, integration instructions and benchmark protocol.
