from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from token_context_mcp.gui.main_window import MainWindow
from token_context_mcp.gui.theme import DARK_STYLESHEET


def main(argv: list[str] | None = None) -> int:
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
