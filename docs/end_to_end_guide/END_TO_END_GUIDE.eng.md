# COMPREHENSIVE END-TO-END GUIDE FOR TOKEN CONTEXT MCP
# Setup, `.vscode/mcp.json` Config, Ollama Qwen Integration, Indexing, Desktop GUI & Test Prompts

This document provides a step-by-step master reference for deploying **Token Context MCP (v0.2.0)** from scratch: package installation, local Ollama Qwen LLM configuration, repository registration, client MCP configuration, Qwen inference verification, Desktop GUI operation, and verification prompt templates.

---

## TABLE OF CONTENTS
1. [Environment & Package Installation (Wheel / Source)](#1-environment--package-installation)
2. [Ollama LLM Setup (Qwen2.5-Coder)](#2-ollama-llm-setup-qwen25-coder)
3. [Repository Registration](#3-repository-registration)
4. [AST Indexing (Snapshot Schema 2.4)](#4-ast-indexing)
5. [Configuring `.vscode/mcp.json`](#5-configuring-vscodemcpjson)
6. [Launching & Using the Desktop GUI](#6-launching--using-the-desktop-gui)
7. [Verifying Qwen LLM Integration (`sample_summarize`)](#7-verifying-qwen-llm-integration)
8. [Standard Test Prompt for AI Coding Assistants](#8-standard-test-prompt)

---

## 1. ENVIRONMENT & PACKAGE INSTALLATION

**Requirements:** Windows 10/11, macOS, or Linux. **Python >= 3.12**.

### Option A: Install from Wheel `.whl` (Recommended for End-Users)
Download `token_context_mcp-0.2.0-py3-none-any.whl` from the GitHub Release assets and install:
```bash
# Create a virtual environment (recommended):
python -m venv .venv

# Activate the virtual environment:
# Windows:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install wheel with Desktop GUI extras:
pip install "token_context_mcp-0.2.0-py3-none-any.whl[gui]"
```

### Option B: Install from Source (Git / ZIP)
```bash
# Using uv:
uv sync --all-extras

# Or using pip:
pip install -e ".[gui,dev,watch]"
```

*Verify installation:*
```bash
token-context --version
# Expected output: 0.2.0
```

---

## 2. OLLAMA LLM SETUP (QWEN2.5-CODER)

`token-context-mcp` utilizes a local LLM for its **`sample_summarize`** tool (structured code compression and constraint synthesis).

### 2.1. Install Ollama
- **Windows / macOS:** Download and install from [ollama.com/download](https://ollama.com/download).
- **Linux:**
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```

### 2.2. Verify Ollama Service
Ensure the Ollama service is active:
- On Windows/macOS: The Ollama tray application runs automatically in the background.
- Alternatively, run `ollama serve` in a terminal.
- Verify connectivity: Navigate to `http://localhost:11434` in your browser (should display *"Ollama is running"*).

### 2.3. Pull the Qwen2.5-Coder Model (Choose one)

#### Option 1: Standard 7B Model (Recommended for systems with >=6GB VRAM or >=16GB RAM)
```bash
ollama pull qwen2.5-coder:7b-instruct-q4_K_M
```
*(Or run script: `powershell .\scripts\download_models.ps1` on Windows / `./scripts/download_models.sh` on Linux).*

#### Option 2: Lightweight 1.5B Model (For low-spec systems running on CPU)
```bash
ollama pull qwen2.5-coder:1.5b
```

### 2.4. Verify Model Availability
```bash
ollama list
```
*You should see `qwen2.5-coder:...` in the output list.*

> **Note:** If no GPU is available or Ollama is absent, the server automatically engages the built-in **Deterministic Heuristic Fallback** engine on CPU with zero disruption.

---

## 3. REPOSITORY REGISTRATION

Before the model can inspect a repository, register its path with the server:

```bash
# Syntax: token-context register --repo-id <REPO_ID> --root <ABSOLUTE_PATH>

# Windows example:
token-context register --repo-id my-project --root "D:\Projects\my-project"

# Linux / macOS example:
token-context register --repo-id my-project --root "/Users/name/projects/my-project"
```

*Configuration Verification:* Inspect `%APPDATA%\token-context\repos.toml` (Windows) or `~/.config/token-context/repos.toml` (Linux/macOS) to view registered repositories.

---

## 4. AST INDEXING

Generate AST snapshots, symbol indexes, and dependency graphs (Schema 2.4):

```bash
# Index a single repository:
token-context index --repo-id my-project

# Or index ALL registered repositories:
token-context index --all
```

*Sanity Check (Freshness Verification):*
```bash
token-context status --repo-id my-project
```
**Expected:** `"freshness"` should report `"fresh"`, and `"index_schema_version"` must be `"2.4"`.

---

## 5. CONFIGURING `.vscode/mcp.json`

Open `.vscode/mcp.json` in your VS Code workspace and configure as follows:

```json
{
  "mcpServers": {
    "token-context": {
      "type": "stdio",
      "command": "token-context",
      "args": [
        "serve",
        "--output-mode",
        "text"
      ]
    }
  }
}
```

### Key Parameter Explanations:
- `"type": "stdio"`: **Keep this property**. It tells VS Code to connect via Standard Input/Output.
- `"command"`: If your virtual environment is not in system PATH, provide the absolute path:
  - Windows: `"D:\\AI\\token-context-mcp\\.venv\\Scripts\\token-context.exe"`
  - Linux/Mac: `"/path/to/.venv/bin/token-context"`
- `"--output-mode", "text"`: **Critical flag**. Serializes full JSON payloads into text fields so all LLM clients can view returned data.
- *(Optional)* For **Google Antigravity / Gemini CLI**, append `--schema-profile gemini_safe`:
  `"args": ["serve", "--schema-profile", "gemini_safe", "--output-mode", "text"]`.

---

## 6. LAUNCHING & USING THE DESKTOP GUI

After installing GUI dependencies (`PySide6` included in `[gui]` extra):

### 6.1. Launching GUI
```bash
token-context-gui
```
*(Or double-click `scripts\launch_desktop_gui.bat` on Windows).*

### 6.2. Key Desktop Workflows:
1. **Dashboard Tab:** Monitor CPU, RAM, and GPU VRAM telemetry; verify Ollama model detection.
2. **Repositories Tab:**
   - Confirm the green 🟢 `FRESH` badge next to your repository.
   - Click **"Re-index all"** if any repository displays 🔴 `SCHEMA_OUTDATED`.
   - Use **"Cancel"** at any time to safely terminate indexing without SQLite corruption.
3. **Settings Tab:** Instant one-click copy of JSON configurations for any MCP client.

---

## 7. VERIFYING QWEN LLM INTEGRATION

Run the Python probe script to verify that `token-context-mcp` connects to Ollama and selects the Qwen model:

```bash
python -c "from token_context_mcp.sampling.hardware_probe import probe_hardware; p = probe_hardware(force_refresh=True); print(f'Ollama Connected: {p.has_ollama}\nBackend Mode: {p.backend_mode}\nDetected Model: {p.recommended_model}\nAvailable Models: {p.available_models}')"
```

### Expected Output:
```text
Ollama Connected: True
Backend Mode: ollama_gpu (or ollama_cpu)
Detected Model: qwen2.5-coder:7b-instruct-q4_K_M (or qwen2.5-coder:1.5b)
Available Models: ['qwen2.5-coder:...']
```

#### Test Live Code Summarization:
```bash
python -c "from token_context_mcp.sampling.router import SamplingRouter; r = SamplingRouter(); res = r.summarize('def add(a, b):\n    return a + b', intent='test'); print('Output:', res.get('summary'))"
```
If a structured summary output appears, your Qwen LLM integration is completely verified!

---

## 8. STANDARD TEST PROMPT

Paste this prompt to your AI Coding Assistant in VS Code / Claude / Cursor to test the retrieval pipeline:

```markdown
You are an expert coding assistant with access to the `token-context-mcp` server.

INPUT:
- Repository: my-project (indexed with "fresh" status)
- Task: "Analyze the entry-point initialization flow and core architectural components."

RETRIEVAL PROCEDURE:
1. Call `get_index_status(repo_id="my-project")` to confirm index freshness.
2. Use `search_source` or `find_symbols` to locate entry-point symbols.
3. Call `inspect_symbol(repo_id="my-project", symbol="<symbol_name>", view="full")` to read context packets without reading whole files.
4. Provide a concise architectural summary referencing specific file paths and line numbers (`file:line`).
```

Once the agent replies with precise references retrieved through `inspect_symbol` and `get_index_status`, your End-to-End setup is 100% verified and production-ready!
