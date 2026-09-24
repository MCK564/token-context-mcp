@echo off
rem Launcher for Token Context MCP Desktop Controller
setlocal
cd /d "%~dp0\.."

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m token_context_mcp.gui.main %*
) else (
    where uv >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        start "" uv run python -m token_context_mcp.gui.main %*
    ) else (
        start "" pythonw -m token_context_mcp.gui.main %*
    )
)
