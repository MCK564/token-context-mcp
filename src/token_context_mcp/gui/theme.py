"""
Modern Dark Theme (Nord / Fluent design inspired) for token-context-mcp desktop GUI.
"""

from __future__ import annotations

# Palette Constants
COLOR_BG_BASE = "#181825"
COLOR_BG_SURFACE = "#1e1e2e"
COLOR_BG_CARD = "#24273a"
COLOR_BG_CARD_HOVER = "#2a2d42"
COLOR_BG_INPUT = "#1e1e2e"
COLOR_BORDER = "#363a4f"
COLOR_BORDER_FOCUS = "#89b4fa"

COLOR_TEXT_PRIMARY = "#cad3f5"
COLOR_TEXT_SECONDARY = "#a5adcb"
COLOR_TEXT_MUTED = "#6e738d"

COLOR_ACCENT_PRIMARY = "#89b4fa"
COLOR_ACCENT_HOVER = "#b4befe"
COLOR_SUCCESS = "#a6da95"
COLOR_WARNING = "#eed49f"
COLOR_DANGER = "#ed8796"
COLOR_INFO = "#8aadf4"

DARK_STYLESHEET = f"""
QMainWindow, QDialog {{
    background-color: {COLOR_BG_BASE};
    color: {COLOR_TEXT_PRIMARY};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}}

QWidget {{
    background-color: transparent;
    color: {COLOR_TEXT_PRIMARY};
}}

/* Sidebar navigation */
#Sidebar {{
    background-color: {COLOR_BG_BASE};
    border-right: 1px solid {COLOR_BORDER};
    min-width: 220px;
    max-width: 220px;
}}

#SidebarHeader {{
    padding: 16px 14px;
    border-bottom: 1px solid {COLOR_BORDER};
}}

#AppTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {COLOR_ACCENT_PRIMARY};
    letter-spacing: 0.5px;
}}

#AppSubtitle {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
}}

#NavButton {{
    text-align: left;
    padding: 10px 16px;
    border-radius: 8px;
    border: none;
    font-size: 13px;
    font-weight: 500;
    color: {COLOR_TEXT_SECONDARY};
    background-color: transparent;
    margin: 3px 10px;
}}

#NavButton:hover {{
    background-color: {COLOR_BG_CARD};
    color: {COLOR_TEXT_PRIMARY};
}}

#NavButton:checked {{
    background-color: {COLOR_BG_CARD};
    color: {COLOR_ACCENT_PRIMARY};
    font-weight: 600;
    border-left: 3px solid {COLOR_ACCENT_PRIMARY};
}}

/* Cards & Content Areas */
.Card {{
    background-color: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    padding: 14px;
}}

.CardHeader {{
    font-size: 14px;
    font-weight: 600;
    color: {COLOR_TEXT_PRIMARY};
}}

.MetricValue {{
    font-size: 22px;
    font-weight: 700;
    color: {COLOR_ACCENT_PRIMARY};
}}

.MetricLabel {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* Buttons */
QPushButton {{
    background-color: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 7px 14px;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {COLOR_BG_CARD_HOVER};
    border-color: {COLOR_BORDER_FOCUS};
}}

QPushButton:pressed {{
    background-color: {COLOR_BG_SURFACE};
}}

QPushButton:disabled {{
    background-color: {COLOR_BG_BASE};
    border-color: {COLOR_BORDER};
    color: {COLOR_TEXT_MUTED};
}}

QPushButton.PrimaryButton {{
    background-color: {COLOR_ACCENT_PRIMARY};
    color: {COLOR_BG_BASE};
    border: none;
    font-weight: 600;
}}

QPushButton.PrimaryButton:hover {{
    background-color: {COLOR_ACCENT_HOVER};
}}

QPushButton.DangerButton {{
    background-color: transparent;
    color: {COLOR_DANGER};
    border: 1px solid {COLOR_DANGER};
}}

QPushButton.DangerButton:hover {{
    background-color: {COLOR_DANGER};
    color: {COLOR_BG_BASE};
}}

QPushButton.SuccessButton {{
    background-color: {COLOR_SUCCESS};
    color: {COLOR_BG_BASE};
    border: none;
    font-weight: 600;
}}

QPushButton.SuccessButton:hover {{
    background-color: #94e2d5;
}}

/* Form inputs */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {COLOR_BORDER_FOCUS};
}}

QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_BG_CARD_HOVER};
    selection-color: {COLOR_ACCENT_PRIMARY};
}}

/* Tables */
QTableWidget {{
    background-color: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    gridline-color: {COLOR_BORDER};
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    selection-background-color: {COLOR_BG_CARD_HOVER};
    selection-color: {COLOR_ACCENT_PRIMARY};
}}

QHeaderView::section {{
    background-color: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_SECONDARY};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    font-weight: 600;
    font-size: 12px;
}}

/* Progress bar */
QProgressBar {{
    background-color: {COLOR_BG_BASE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 5px;
    text-align: center;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 11px;
    font-weight: 600;
    height: 16px;
}}

QProgressBar::chunk {{
    background-color: {COLOR_ACCENT_PRIMARY};
    border-radius: 4px;
}}

/* Monospace Log Viewer */
QPlainTextEdit.LogConsole {{
    background-color: #11111b;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    color: #a6da95;
    font-family: "Cascadia Code", Consolas, "Courier New", monospace;
    font-size: 12px;
    padding: 8px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background-color: {COLOR_BG_BASE};
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {COLOR_BORDER};
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLOR_TEXT_MUTED};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* Badges */
QLabel.BadgeRunning {{
    background-color: rgba(166, 218, 149, 0.2);
    color: {COLOR_SUCCESS};
    border: 1px solid {COLOR_SUCCESS};
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel.BadgeStopped {{
    background-color: rgba(237, 135, 150, 0.2);
    color: {COLOR_DANGER};
    border: 1px solid {COLOR_DANGER};
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel.BadgeFresh {{
    background-color: rgba(166, 218, 149, 0.15);
    color: {COLOR_SUCCESS};
    border-radius: 8px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel.BadgeStale {{
    background-color: rgba(238, 212, 159, 0.15);
    color: {COLOR_WARNING};
    border-radius: 8px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}}

QLabel.BadgeNotIndexed {{
    background-color: rgba(110, 115, 141, 0.2);
    color: {COLOR_TEXT_MUTED};
    border-radius: 8px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}}
"""
