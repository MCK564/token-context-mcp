#!/usr/bin/env bash
# ==============================================================================
# TOKEN-CONTEXT-MCP: Model Downloader & Verification (Linux / macOS / WSL)
# ==============================================================================
set -euo pipefail

MODEL="qwen2.5-coder:7b-instruct-q4_K_M"
LIGHTWEIGHT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lightweight|-l)
      LIGHTWEIGHT=true
      shift
      ;;
    --model|-m)
      MODEL="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [ "$LIGHTWEIGHT" = true ]; then
  MODEL="qwen2.5-coder:1.5b"
fi

echo "=========================================================="
echo "  TOKEN-CONTEXT-MCP: Model Downloader & Verification"
echo "=========================================================="
echo "Target Model: $MODEL"

# 1. Check Ollama
is_running=false
if curl -s -f http://localhost:11434/api/tags >/dev/null 2>&1; then
  is_running=true
fi

if [ "$is_running" = false ]; then
  if command -v ollama >/dev/null 2>&1; then
    echo "Ollama is installed but not running. Starting 'ollama serve' in background..."
    nohup ollama serve >/dev/null 2>&1 &
    sleep 3
  else
    echo -e "\nOllama is not installed on this machine."
    echo "To enable local 7B GPU/CPU sampling, install Ollama from: https://ollama.com/download"
    echo "Note: Even without Ollama, token-context-mcp works 100% fine using Deterministic Heuristic Fallback!"
    exit 0
  fi
fi

# 2. Pull model
echo -e "\nPulling model '$MODEL' via Ollama..."
if ! ollama pull "$MODEL"; then
  echo "Warning: Failed to pull '$MODEL'. Retrying with generic 'qwen2.5-coder:7b'..."
  if ! ollama pull "qwen2.5-coder:7b"; then
    echo "Warning: Retrying with lightweight 'qwen2.5-coder:1.5b'..."
    ollama pull "qwen2.5-coder:1.5b"
  fi
fi

# 3. Test verification
echo -e "\nVerifying sampling engine with downloaded model..."
VERIFY_SCRIPT="
from token_context_mcp.sampling.router import SamplingRouter
router = SamplingRouter()
res = router.summarize('''
class PaymentService:
    def refund(self, tx_id, amount):
        if amount <= 0:
            raise InvalidAmountException('Amount must be positive')
        return self.gateway.execute_refund(tx_id, amount)
''', intent='verify refund logic')
print(f\"Backend used: {res.get('backend')} | Engine: {res.get('engine')} | Latency: {res.get('latency_ms')}ms\")
"

if command -v uv >/dev/null 2>&1; then
  uv run python -c "$VERIFY_SCRIPT"
elif command -v python3 >/dev/null 2>&1; then
  python3 -c "$VERIFY_SCRIPT"
else
  python -c "$VERIFY_SCRIPT"
fi

echo -e "\nModel setup and verification complete!"
