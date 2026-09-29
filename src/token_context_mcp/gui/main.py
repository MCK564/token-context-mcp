from __future__ import annotations

import argparse
import sys
from pathlib import Path

MISSING_GUI_DEPS_MESSAGE = (
    "The desktop GUI needs the optional 'gui' extra (PySide6, psutil, pyinstaller), "
    "which is not installed in this environment.\n"
    "Install it with:\n"
    "    uv sync --all-extras          (or: uv sync --extra dev --extra gui)\n"
    "and start the GUI with:\n"
    "    uv run token-context-gui\n"
    "Note: `uv sync` removes packages that are not in the selected extras, so always pass "
    "every extra you use in the same command."
)

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from token_context_mcp.gui.main_window import MainWindow
    from token_context_mcp.gui.theme import DARK_STYLESHEET
except ModuleNotFoundError as exc:  # PySide6 / psutil not installed
    _IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _IMPORT_ERROR = None


def main(argv: list[str] | None = None) -> int:
    if _IMPORT_ERROR is not None:
        print(f"error: {_IMPORT_ERROR}\n{MISSING_GUI_DEPS_MESSAGE}", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description="Token Context MCP Desktop Controller")
    parser.add_argument("--config", type=Path, default=None, help="Path to custom repos.toml configuration")
    args = parser.parse_args(argv)

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv if argv is None else [sys.argv[0]] + argv)
    app.setApplicationName("TokenContextDesktop")
    app.setOrganizationName("TokenContextMCP")
    app.setStyleSheet(DARK_STYLESHEET)

    window = MainWindow(config_path=args.config)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
