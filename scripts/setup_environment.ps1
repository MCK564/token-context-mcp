<#
.SYNOPSIS
    Automated environment setup script for token-context-mcp on Windows.
.DESCRIPTION
    1. Verifies Python >= 3.12
    2. Installs or verifies uv package manager
    3. Synchronizes project dependencies
    4. Initializes global repos.toml configuration with enable_extensions = true
    5. Optionally downloads recommended local Ollama coder models
    6. Runs verification test suite
#>

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipModelDownload,
    [string]$Model = "qwen2.5-coder:7b-instruct-q4_K_M"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  TOKEN-CONTEXT-MCP: Automated Environment Setup (Windows)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Python version
Write-Host "`n[1/6] Checking Python installation..." -ForegroundColor Yellow
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Write-Error "Python was not found on PATH. Please install Python >= 3.12."
}
$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "  Found Python $pyVersion" -ForegroundColor Green
$versionParts = $pyVersion.Split('.')
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 12)) {
    Write-Error "Python >= 3.12 is required (found $pyVersion)."
}

# 2. Check or install uv
Write-Host "`n[2/6] Checking 'uv' package manager..." -ForegroundColor Yellow
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    $uvLocalPath = "$env:APPDATA\Python\Python312\Scripts\uv.exe"
    if (Test-Path $uvLocalPath) {
        $env:PATH = "$env:APPDATA\Python\Python312\Scripts;" + $env:PATH
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    }
}

if (-not $uvCmd) {
    Write-Host "  'uv' not found. Installing uv via official bootstrap..." -ForegroundColor DarkYellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:PATH = "$env:USERPROFILE\.cargo\bin;$env:APPDATA\Python\Python312\Scripts;" + $env:PATH
}

# 3. Synchronize dependencies
Write-Host "`n[3/6] Synchronizing project dependencies..." -ForegroundColor Yellow
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "  Running 'uv sync --extra dev'..." -ForegroundColor DarkGray
    & uv sync --extra dev
} else {
    Write-Host "  'uv' unavailable; falling back to 'python -m pip install -e .[dev]'..." -ForegroundColor DarkYellow
    & python -m pip install -e ".[dev]"
}
Write-Host "  Dependencies synchronized successfully." -ForegroundColor Green

# 4. Configure global repos.toml
Write-Host "`n[4/6] Configuring global repos.toml..." -ForegroundColor Yellow
$configDir = "$env:APPDATA\token-context-mcp"
$configFile = "$configDir\repos.toml"

if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

if (-not (Test-Path $configFile)) {
    $defaultConfig = @"
[server]
max_request_bytes = 65536
max_result_tokens = 4096
max_graph_nodes = 200
max_symbol_results = 30
network_policy = "declared-deny-not-enforced"
output_mode = "structured"
default_view = "normal"
enable_extensions = true
"@
    Set-Content -Path $configFile -Value $defaultConfig -Encoding UTF8
    Write-Host "  Created initial repos.toml with enable_extensions = true at: $configFile" -ForegroundColor Green
} else {
    $existing = Get-Content -Path $configFile -Raw -Encoding UTF8
    if ($existing -notmatch "enable_extensions\s*=\s*true") {
        if ($existing -match "\[server\]") {
            $updated = $existing -replace "\[server\]", "[server]`nenable_extensions = true"
            Set-Content -Path $configFile -Value $updated -Encoding UTF8
            Write-Host "  Updated existing repos.toml to enable extensions." -ForegroundColor Green
        }
    } else {
        Write-Host "  repos.toml already has enable_extensions = true." -ForegroundColor Green
    }
}

# 5. Check Ollama and Model setup
Write-Host "`n[5/6] Checking Local Inference / Ollama Setup..." -ForegroundColor Yellow
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
$ollamaRunning = $false

try {
    $resp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) { $ollamaRunning = $true }
} catch {}

if ($ollamaRunning) {
    Write-Host "  Ollama HTTP server is RUNNING on http://localhost:11434." -ForegroundColor Green
    if (-not $SkipModelDownload) {
        Write-Host "  Checking if model '$Model' is pulled..." -ForegroundColor DarkGray
        $tagsData = & ollama list
        if ($tagsData -notmatch ($Model.Split(':')[0])) {
            Write-Host "  Pulling model '$Model' (this may take a few minutes)..." -ForegroundColor Cyan
            & ollama pull $Model
        } else {
            Write-Host "  Model '$Model' is already available." -ForegroundColor Green
        }
    }
} elseif ($ollamaCmd) {
    Write-Host "  Ollama is installed but not currently running." -ForegroundColor DarkYellow
    Write-Host "  Start it with 'ollama serve' in another terminal to enable local 7B GPU/CPU inference." -ForegroundColor DarkYellow
} else {
    Write-Host "  Ollama is not installed. System will use Deterministic Heuristic Fallback (<5ms latency, 0 token cost)." -ForegroundColor DarkGray
}

# 6. Run verification tests
if (-not $SkipTests) {
    Write-Host "`n[6/6] Running verification test suite..." -ForegroundColor Yellow
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run --extra dev pytest -q
    } else {
        & pytest -q
    }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  All test suites passed!" -ForegroundColor Green
    } else {
        Write-Warning "Some tests failed. Please review output above."
    }
} else {
    Write-Host "`n[6/6] Verification tests skipped by user." -ForegroundColor DarkGray
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "  SETUP COMPLETE! Next Steps:" -ForegroundColor Cyan
Write-Host "  1. Register a repository:   uv run token-context register --repo-id myrepo --root D:\path\to\repo"
Write-Host "  2. Build AST index:         uv run token-context index --repo-id myrepo"
Write-Host "  3. Start stdio MCP server:  uv run token-context serve"
Write-Host "==========================================================" -ForegroundColor Cyan
