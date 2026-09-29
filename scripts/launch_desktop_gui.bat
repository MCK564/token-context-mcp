@echo off
rem Launcher for Token Context MCP Desktop Controller
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo No .venv found. Run: uv sync --all-extras
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import PySide6, psutil" 2>nul
if errorlevel 1 (
    echo The GUI dependencies (PySide6, psutil) are not installed in .venv.
    echo Run: uv sync --all-extras    ^(uv sync --extra dev alone does not install PySide6^)
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -m token_context_mcp.gui.main %*
