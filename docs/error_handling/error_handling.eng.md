# TROUBLESHOOTING & ERROR HANDLING MANUAL FOR TOKEN CONTEXT MCP
# (Comprehensive Guide for LLM & MCP Client Incompatibilities)

This guide provides exhaustive diagnostics and solutions for issues where LLM clients (Claude Desktop, Claude Code, Cursor, Google Antigravity, VS Code Copilot, Codex CLI, etc.) fail to spawn, disconnect, or encounter errors when invoking `token-context-mcp` tools.

---

## 1. QUICK SYMPTOM LOOKUP TABLE

| Symptom | Root Cause | Immediate Fix |
| :--- | :--- | :--- |
| **Server failed to spawn / Exited with code 1** | Invalid Python executable path or binary locked on Windows | Use absolute `.venv` Python path with `-m token_context_mcp serve` |
| **LLM receives only a one-line summary / missing payload** | Client does not support MCP `structuredContent` | Add `--output-mode text` to the server invocation flags |
| **Tool schema validation errors on Gemini / Antigravity** | Gemini API rejects `null` union branches, `$ref`, `$defs` | Add `--schema-profile gemini_safe` to server flags |
| **Tool returns "Repository not found / not registered"** | Repository ID missing from `repos.toml` registry | Register the repository via `python -m token_context_mcp register` |
| **Warning: `index_schema_outdated_reindex_recommended`** | Snapshot built on legacy schema (< 2.4) | Run `python -m token_context_mcp index --all` |
| **SQLite error: `database is locked`** | Lingering WAL lock or ungraceful shutdown | Run safe VACUUM via Desktop GUI or remove `-wal`/`-shm` temp files |
| **Calling `sample_summarize` times out or stalls** | Ollama running 7B model on low-spec CPU | Switch to 1.5B model or terminate Ollama for instant Heuristic Fallback |
| **CLI / pytest hangs indefinitely on Windows** | Global git configuration enforces `commit.gpgsign = true` | Temporarily bypass GPG signing via environment variables |

---

## 2. IN-DEPTH ERROR RESOLUTION

---

### ERROR 1: Client Reports "Failed to spawn MCP process" or "Server exited with code 1"

#### Manifestation:
- On Claude Desktop or Cursor: MCP status indicator remains red (Disconnected).
- Client log output displays: `spawn python ENOENT`, `FileNotFoundError`, or `PermissionError`.

#### Root Causes:
1. Client configuration points to a generic system `python` instead of the project-specific virtual environment containing the dependencies.
2. On Windows, if invoking `token-context.exe`, the OS may lock the binary if an existing server process is still lingering.

#### Resolution:
In your client configuration file (e.g., `claude_desktop_config.json`), **always specify the absolute path to the virtual environment Python interpreter** and invoke as a Python module:

**Windows:**
```json
{
  "mcpServers": {
    "token-context": {
      "command": "D:\\AI\\token-context-mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "token_context_mcp",
        "serve",
        "--output-mode",
        "text"
      ]
    }
  }
}
```

**Linux / macOS:**
```json
{
  "mcpServers": {
    "token-context": {
      "command": "/path/to/token-context-mcp/.venv/bin/python",
      "args": [
        "-m",
        "token_context_mcp",
        "serve",
        "--output-mode",
        "text"
      ]
    }
  }
}
```

---

### ERROR 2: LLM Invokes Tool Successfully but Content Is Missing (Empty Payload)

#### Manifestation:
- The LLM calls `inspect_symbol` or `search_source`, the tool completes successfully, but the LLM states: *"I called the tool but only received a summary line"* or fails to see the code packet.

#### Root Causes:
Under MCP SDK v2, tools return both `structuredContent` (full JSON object) and `content[0].text` (concise human-readable summary).
- Many clients (such as older Claude Desktop versions, Cursor, or VS Code Copilot) **only parse the text field**, discarding `structuredContent`.

#### Resolution:
Append `--output-mode text` to the `serve` command arguments:
```json
"args": [
  "-m",
  "token_context_mcp",
  "serve",
  "--output-mode",
  "text"
]
```
*(This serializes the complete structured JSON payload directly into the text field, ensuring 100% visibility across all models).*

---

### ERROR 3: Tool Schema Validation Rejection on Google Gemini / Antigravity

#### Manifestation:
- Starting the MCP server in Gemini CLI or Google Antigravity fails with:
  `Invalid JSON Schema: anyOf with null is not supported` or `$ref / $defs cannot be resolved`.

#### Root Causes:
The Google Gemini function-calling API enforces strict JSON Schema specifications: nullable unions (`anyOf: [..., null]`), schema references (`$ref`, `$defs`), and arrays lacking an explicit `items` property are rejected.

#### Resolution:
Add `--schema-profile gemini_safe` (or `--schema-profile auto`):
```json
"args": [
  "-m",
  "token_context_mcp",
  "serve",
  "--schema-profile",
  "gemini_safe",
  "--output-mode",
  "text"
]
```
*(Server middleware automatically sanitizes and inlines all 20 tool schemas to adhere strictly to Gemini's format requirements without altering runtime behavior).*

---

### ERROR 4: Tool Returns "Repository not registered" or "Repository not found"

#### Manifestation:
The model attempts a query and receives:
`Repository 'my-repo' is not registered in the local config.`

#### Root Causes:
`token-context-mcp` operates under a **Read-Only & Strict Boundary Security Model**: tools accept registered `repo_id` identifiers only. Arbitrary disk browsing by the model is strictly denied.

#### Resolution:
Open your terminal and register the target repository prior to querying:
```bash
# Register using absolute path:
python -m token_context_mcp register --repo-id my-repo --root "D:/path/to/my-repo"

# Build its initial index:
python -m token_context_mcp index --repo-id my-repo
```

---

### ERROR 5: Warning `index_schema_outdated_reindex_recommended`

#### Manifestation:
Calling `get_index_status` returns:
`"warnings": ["index_schema_outdated_reindex_recommended"]`

#### Root Causes:
The repository snapshot was indexed using an older database schema (Schema 2.3 or earlier), lacking modern v0.2.0 metadata (Schema 2.4) such as `external_stubs`, `commit_sha` tracking, and arity-based overload indexing.

#### Resolution:
Run a comprehensive re-index across all registered repositories:
```bash
python -m token_context_mcp index --all
```
*(Verify by checking `python -m token_context_mcp status --repo-id <name>`; schema should report `2.4`).*

---

### ERROR 6: SQLite Concurrency Lock (`database is locked`)

#### Manifestation:
Server logs output: `sqlite3.OperationalError: database is locked`.

#### Root Causes:
Occurs if multiple processes contend for `memory.sqlite` or `governance.sqlite`, or if a previous process terminated ungracefully, leaving orphaned `-wal` / `-shm` shared memory locks.

#### Resolution:
1. Terminate lingering Python / MCP processes:
   - **Windows:** `Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force`
   - **Linux / macOS:** `pkill -f token_context_mcp`
2. Open Desktop Controller GUI -> Switch to **Cache & Storage** tab -> Select databases and click **"Run VACUUM"**.
3. If locks persist, navigate to the config folder (`%APPDATA%\token-context` or `~/.config/token-context`) and manually delete temporary `-wal` or `-shm` sidecar files.

---

### ERROR 7: Tool `sample_summarize` Stalls or Times Out

#### Manifestation:
When the model invokes `sample_summarize`, execution stalls for 30–60 seconds before triggering a timeout.

#### Root Causes:
The router probes Ollama on `localhost:11434`. If the host lacks dedicated GPU acceleration (VRAM >= 6GB) and Ollama loads a heavy 7B model onto CPU threads, token generation throughput drops drastically.

#### Resolution:
- **Approach 1: Enforce lightweight model (Recommended):**
  Set the sampling model environment variable to 1.5B:
  - Windows: `$env:TOKEN_CONTEXT_SAMPLING_MODEL = "qwen2.5-coder:1.5b"`
  - Linux / macOS: `export TOKEN_CONTEXT_SAMPLING_MODEL="qwen2.5-coder:1.5b"`
- **Approach 2: Stop Ollama to engage instant Heuristic Fallback:**
  Stop the Ollama service (`ollama stop`). `token-context-mcp` automatically detects the absence of Ollama and triggers the CPU **Deterministic Heuristic Engine**, executing in < 10ms with zero latency overhead.

---

### ERROR 8: Tests or CLI Commands Hang Indefinitely on Windows

#### Manifestation:
Running `pytest` or git-aware CLI commands pauses indefinitely at certain tests.

#### Root Causes:
Global Git configuration has `commit.gpgsign = true`, prompting `gpg.exe` in the background for a smartcard PIN or passphrase dialog without exposing a console prompt.

#### Resolution:
Bypass GPG signing for the current shell session:
- **Windows PowerShell:**
  ```powershell
  $env:GIT_CONFIG_COUNT="1"; $env:GIT_CONFIG_KEY_0="commit.gpgsign"; $env:GIT_CONFIG_VALUE_0="false"
  ```
- **Linux / macOS Bash:**
  ```bash
  export GIT_CONFIG_COUNT=1; export GIT_CONFIG_KEY_0="commit.gpgsign"; export GIT_CONFIG_VALUE_0="false"
  ```
Then re-execute your target command.

---

## 3. THREE-STEP VERIFICATION HEALTHCHECK

Before starting your coding session, run these 3 validation commands in terminal:

```bash
# 1. Version sanity check (expected: 0.2.0)
python -m token_context_mcp --version

# 2. Protocol smoke test (expected: stdio_smoke ok)
python evals/stdio_smoke.py

# 3. Repository status check (expected: freshness = fresh, schema = 2.4)
python -m token_context_mcp status --repo-id <repo-name>
```
If all three checks succeed, your MCP Server installation is fully operational and healthy.
