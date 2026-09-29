<#
.SYNOPSIS
    One-click PowerShell launcher for Token Context MCP Desktop Controller
.DESCRIPTION
    Starts the GUI from the project's .venv. If the environment or the 'gui' extra
    (PySide6, psutil) is missing, it says so instead of failing silently.
#>

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$venvPython  = Join-Path $repoRoot ".venv\Scripts\python.exe"
$venvPythonW = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"

$hint = @"
Install the project environment with all extras, then start again:
    uv sync --all-extras
(uv is available from https://docs.astral.sh/uv/ ; `uv sync --extra dev` alone does NOT install PySide6.)
"@

if (-not (Test-Path $venvPython)) {
    Write-Host "No .venv found in $repoRoot." -ForegroundColor Red
    Write-Host $hint
    exit 1
}

& $venvPython -c "import PySide6, psutil" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "The GUI dependencies (PySide6, psutil) are not installed in .venv." -ForegroundColor Red
    Write-Host $hint
    exit 1
}

Start-Process -FilePath $venvPythonW -ArgumentList "-m", "token_context_mcp.gui.main"
