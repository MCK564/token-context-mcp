#!/usr/bin/env bash
# ==============================================================================
# TOKEN-CONTEXT-MCP: Automated Environment Setup (Linux / macOS / WSL)
# ==============================================================================

set -e

MODEL="${1:-qwen2.5-coder:7b-instruct-q4_K_M}"

echo "=========================================================="
echo "  TOKEN-CONTEXT-MCP: Automated Environment Setup"
echo "=========================================================="

# 1. Check Python
echo -e "\n[1/6] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Please install Python >= 3.12."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Found Python $PY_VER"

# 2. Check uv
echo -e "\n[2/6] Checking 'uv' package manager..."
if ! command -v uv &> /dev/null; then
    echo "  'uv' not found. Installing via Astral bootstrap..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# 3. Synchronize dependencies
echo -e "\n[3/6] Synchronizing project dependencies..."
if command -v uv &> /dev/null; then
    uv sync --extra dev
else
    python3 -m pip install -e ".[dev]"
fi
echo "  Dependencies synchronized successfully."

# 4. Configure repos.toml
echo -e "\n[4/6] Configuring global repos.toml..."
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/token-context-mcp"
CONFIG_FILE="$CONFIG_DIR/repos.toml"
mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_FILE" ]; then
    cat <<EOF > "$CONFIG_FILE"
[server]
max_request_bytes = 65536
max_result_tokens = 4096
max_graph_nodes = 200
max_symbol_results = 30
network_policy = "declared-deny-not-enforced"
output_mode = "structured"
default_view = "normal"
enable_extensions = true
EOF
    echo "  Created repos.toml with enable_extensions = true at $CONFIG_FILE"
else
    if ! grep -q "enable_extensions = true" "$CONFIG_FILE"; then
        sed -i 's/\[server\]/\[server\]\nenable_extensions = true/' "$CONFIG_FILE" 2>/dev/null || true
        echo "  Updated existing repos.toml to enable extensions."
    else
        echo "  repos.toml already has enable_extensions = true."
    fi
fi

# 5. Check Ollama
echo -e "\n[5/6] Checking Local Inference / Ollama..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  Ollama HTTP server is RUNNING on http://localhost:11434."
    if command -v ollama &> /dev/null; then
        echo "  Pulling model '$MODEL'..."
        ollama pull "$MODEL" || true
    fi
else
    echo "  Ollama is not running. System will use Deterministic Heuristic Fallback (<5ms latency)."
fi

# 6. Verification tests
echo -e "\n[6/6] Running verification test suite..."
if command -v uv &> /dev/null; then
    uv run --extra dev pytest -q
else
    pytest -q
fi

echo "=========================================================="
echo "  SETUP COMPLETE! Next Steps:"
echo "  1. Register a repo:   uv run token-context register --repo-id myrepo --root /path/to/repo"
echo "  2. Build index:       uv run token-context index --repo-id myrepo"
echo "  3. Start MCP server:  uv run token-context serve"
echo "=========================================================="
