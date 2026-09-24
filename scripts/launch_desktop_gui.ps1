<#
.SYNOPSIS
    One-click PowerShell launcher for Token Context MCP Desktop Controller
#>

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$venvPythonW = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
if (Test-Path $venvPythonW) {
    Start-Process -FilePath $venvPythonW -ArgumentList "-m", "token_context_mcp.gui.main"
} elseif (Get-Command uv -ErrorAction SilentlyContinue) {
    Start-Process -FilePath "uv" -ArgumentList "run", "pythonw", "-m", "token_context_mcp.gui.main"
} else {
    Start-Process -FilePath "pythonw" -ArgumentList "-m", "token_context_mcp.gui.main"
}
