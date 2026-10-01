# DESKTOP CONTROLLER GUI USER MANUAL (`token-context-gui`)

The Desktop Controller GUI for **Token Context MCP** is built on **PySide6 (Qt6)** with a fully asynchronous architecture (Multi-threading + Subprocess execution). It guarantees **Zero UI-thread blocking**, remaining completely responsive even when indexing large-scale repositories.

---

## 1. How to Launch the GUI

Depending on your environment, launch the GUI using one of the following methods:

### Method 1: Via CLI
```bash
# Using uv:
uv run token-context-gui

# Or activate your .venv and run via Python module:
# Windows:
.\.venv\Scripts\python.exe -m token_context_mcp.gui.main
# Linux / macOS:
./.venv/bin/python -m token_context_mcp.gui.main
```

### Method 2: Via Desktop Launchers (Windows)
Double-click or execute the launcher script in the `scripts/` folder:
- `scripts\launch_desktop_gui.bat`
- `scripts\launch_desktop_gui.ps1`

*(Note: In headless or remote SSH environments without an X11/Wayland display server, you can test offscreen rendering using: `QT_QPA_PLATFORM=offscreen uv run token-context-gui`).*

---

## 2. Functional Tab Breakdown

The interface is structured into 6 specialized tabs accessible via the left navigation panel:

```
┌────────────────────────────────────────────────────────────────────────┐
│  TOKEN CONTEXT MCP - DESKTOP CONTROLLER                                │
├──────────────┬─────────────────────────────────────────────────────────┤
│ 📊 Dashboard │  Hardware Telemetry, Hardware Probes, Active Servers    │
│ 📁 Repos     │  Repository Registry, Freshness Badges, Re-index, Cancel│
│ ⚡ Tasks     │  Execution Queue, Visual AST Graph, Live Log Stream     │
│ 🧹 Cache     │  Snapshot Storage, Safe VACUUM, GC Legacy Snapshots     │
│ 🛡️ Agents    │  Agent Governance, Policy Controls, Audit Logs, Halt    │
│ ⚙️ Settings  │  Server Configurations, Client Matrix, Quick JSON Export│
└──────────────┴─────────────────────────────────────────────────────────┘
```

---

### 2.1 Tab 1: 📊 Dashboard (System Telemetry & Monitoring)
- **Hardware Telemetry:**
  - Real-time utilization for CPU, RAM, and GPU VRAM (NVIDIA CUDA or Apple Silicon Unified Memory).
  - Automatic detection of **Ollama** service status and available local Coder LLM models.
- **Active MCP Servers Panel:**
  - Real-time discovery of running MCP `stdio` server sessions, showing PID, heartbeat timestamps, active `output_mode`, and active `schema_profile`.
- **"Copy Client Config" Button:**
  - Instant one-click JSON configuration generation tailored for major MCP clients (Claude Desktop, Claude Code, VS Code Copilot, Google Antigravity, Cursor, and Codex CLI).

---

### 2.2 Tab 2: 📁 Repositories (Registry & Indexing)
Central control table managing all registered codebases:
- **Status Badge System:**
  - 🟢 `FRESH`: Snapshot is fully synchronized with current source files. Ready for LLM querying.
  - 🟡 `STALE`: Source code modified since the last index run.
  - 🟠 `DOCS_CHANGED`: Only documentation or markdown files modified (source AST remains valid).
  - 🔴 `SCHEMA_OUTDATED`: Snapshot built on older schema (< Schema 2.4); re-index recommended.
  - ⚪ `NOT_INDEXED`: Registered but no snapshot exists yet.
- **Indexing Operations:**
  - **Re-index Selected:** Rebuilds AST snapshot for the highlighted repository.
  - **Re-index All:** Sequentially indexes all registered repositories.
  - **Isolated Subprocess (`IndexProcess`):** Runs indexing in an independent child process with NDJSON progress streaming at a smooth 10 fps limit.
  - **Safe Process-Tree Cancellation:** Clicking **Cancel** recursively terminates the entire process tree (`psutil.kill_tree`), preventing lingering worker processes or locked SQLite handles.

---

### 2.3 Tab 3: ⚡ Tasks (Execution Queue & Graph Inspection)
- **Pipeline Stage Monitoring:** Real-time visibility into AST parsing phases: `scan` -> `roles` -> `edges` -> `ranks` -> `write`.
- **Buffered Log Console:** 5,000-line capped output with batched 100ms updates to prevent UI stutter.
- **Structural Visualization:** Inspect hierarchy maps and symbol relational density.

---

### 2.4 Tab 4: 🧹 Cache & Storage (Optimization & Maintenance)
- **Disk Usage Breakdown:** Inspect exact file sizes for per-repository index snapshots and state databases (`memory.sqlite`, `governance.sqlite`, `audit.sqlite`).
- **Safe VACUUM Maintenance:**
  - Selectively run VACUUM across mutable databases (`memory`, `governance`, `audit`).
  - **Safety Invariant:** Never touches immutable index snapshot databases to preserve deterministic file hashes.
  - Automatically retries up to 3 times with backoff if encountering SQLite `database is locked`.
- **Garbage Collection (Clean Old Snapshots):** Prunes superseded historical snapshots to reclaim disk space.

---

### 2.5 Tab 5: 🛡️ Agents & Security (Governance & Audit)
- **Agent Identity Resolution:** Identifies agents via `TOKEN_CONTEXT_AGENT_ID` or tracks anonymous sessions.
- **Access Control Policies:**
  - Enforce permission tiers: `allow_all`, `read_only`, or `restricted_tools`.
  - Gate administrative tools (`admin_tools`, `memory_lock`, `agent_control`).
- **Emergency Halt Button:** Instantly freezes all agent operations in case of suspicious behaviour or runaway queries.
- **Audit Logging:** Live audit inspection backed by SQLite WAL mode with sub-0.05ms write overhead.

---

### 2.6 Tab 6: ⚙️ Settings (Configuration Management)
- **Visual `repos.toml` Editor:** Review and adjust key server parameters:
  - `max_request_bytes`: Maximum request wire size (default: 64 KB).
  - `max_result_tokens`: Maximum response token ceiling (default: 8192).
  - `enable_extensions`: Enable/disable 9 extended tools (Memory, Tool Discovery, Sampling).
  - `output_mode`: Output mode (`auto`, `structured`, `text`).
- Hot-reloads configuration without requiring a full desktop application restart.

---

## 3. Quick Usage Tips

1. **After Upgrading to v0.2.0:**
   - Navigate to the **Repositories** tab and click **"Re-index all"** to migrate all snapshot databases to Schema 2.4.
2. **Adding a New Repository:**
   - Add directly within the **Repositories** tab (using the *Add Repository* action) or run `token-context register` via CLI.
3. **Diagnosing UI Stalls:**
   - Set `TOKEN_CONTEXT_GUI_DEBUG=1` before launching the GUI to engage the built-in `EventLoopWatchdog` (automatically dumps faulthandler tracebacks if any UI operation exceeds 100ms).
