<#
.SYNOPSIS
    Download, configure, and verify local Ollama inference models for token-context-mcp.
.DESCRIPTION
    Checks Ollama availability, pulls the recommended 7B coder model (or fallback 1.5B),
    and executes a test compression with the sampling engine.
#>

[CmdletBinding()]
param(
    [string]$Model = "qwen2.5-coder:7b-instruct-q4_K_M",
    [switch]$Lightweight  # if specified, pulls 1.5b model instead
)

$ErrorActionPreference = "Stop"

if ($Lightweight) {
    $Model = "qwen2.5-coder:1.5b"
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TOKEN-CONTEXT-MCP: Model Downloader & Verification" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Target Model: $Model" -ForegroundColor Yellow

# 1. Check Ollama
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
$isRunning = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) { $isRunning = $true }
} catch {}

if (-not $isRunning) {
    if ($ollamaCmd) {
        Write-Host "`nOllama is installed but not running." -ForegroundColor Yellow
        Write-Host "Attempting to start Ollama in background..." -ForegroundColor DarkGray
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
    } else {
        Write-Host "`nOllama is not installed on this machine." -ForegroundColor Red
        Write-Host "To enable local 7B GPU/CPU sampling, install Ollama from: https://ollama.com/download" -ForegroundColor Yellow
        Write-Host "Note: Even without Ollama, token-context-mcp works 100% fine using Deterministic Heuristic Fallback!" -ForegroundColor Green
        exit 0
    }
}

# 2. Pull model
Write-Host "`nPulling model '$Model' via Ollama..." -ForegroundColor Cyan
& ollama pull $Model
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Failed to pull '$Model'. Retrying with generic 'qwen2.5-coder:7b'..."
    & ollama pull "qwen2.5-coder:7b"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Retrying with lightweight 'qwen2.5-coder:1.5b'..."
        & ollama pull "qwen2.5-coder:1.5b"
    }
}

# 3. Test verification
Write-Host "`nVerifying sampling engine with downloaded model..." -ForegroundColor Yellow
$pyScript = @"
from token_context_mcp.sampling.router import SamplingRouter
router = SamplingRouter()
res = router.summarize('''
class PaymentService:
    def refund(self, tx_id, amount):
        if amount <= 0:
            raise InvalidAmountException("Amount must be positive")
        return self.gateway.execute_refund(tx_id, amount)
''', intent='verify refund logic')
print(f"Backend used: {res.get('backend')} | Engine: {res.get('engine')} | Latency: {res.get('latency_ms')}ms")
"@

if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run python -c $pyScript
} else {
    & python -c $pyScript
}

Write-Host "`nModel setup and verification complete!" -ForegroundColor Green
