from __future__ import annotations

# Design tokens (Catppuccin Macchiato / Dark Surface Hierarchy)
COLOR_MANTLE = "#181825"
COLOR_BASE = "#1e1e2e"
COLOR_SURFACE = "#24273a"
COLOR_OVERLAY = "#313244"
COLOR_BORDER = "#363a4f"
COLOR_ACCENT = "#89b4fa"
COLOR_ACCENT_HOVER = "#b4befe"
COLOR_SUCCESS = "#a6da95"
COLOR_WARNING = "#eed49f"
COLOR_DANGER = "#ed8796"
COLOR_TEXT_PRIMARY = "#cad3f5"
COLOR_TEXT_MUTED = "#a5adcb"
COLOR_TEXT_SUBTLE = "#6e738d"
COLOR_CRUST = "#11111b"

DARK_STYLESHEET = f"""
/* Base & Dialog Surfaces (prevent Windows/OS light bleed-through) */
QMainWindow, QDialog, QMessageBox {{
    background-color: {COLOR_BASE};
    color: {COLOR_TEXT_PRIMARY};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

QWidget {{
    color: {COLOR_TEXT_PRIMARY};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

QWidget#MainContent, QStackedWidget#MainStack, QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: {COLOR_BASE};
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}

/* Status Bar */
QStatusBar {{
    background-color: {COLOR_MANTLE};
    color: {COLOR_TEXT_MUTED};
    border-top: 1px solid {COLOR_BORDER};
    padding: 3px 10px;
    font-size: 11px;
}}
QStatusBar::item {{
    border: none;
}}

/* Sidebar Navigation */
QFrame#Sidebar {{
    background-color: {COLOR_MANTLE};
    border-right: 1px solid {COLOR_BORDER};
    min-width: 196px;
    max-width: 196px;
}}

QWidget#SidebarHeader {{
    background-color: {COLOR_MANTLE};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QLabel#AppTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {COLOR_ACCENT};
    letter-spacing: 0.4px;
    background: transparent;
}}

QLabel#AppSubtitle {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
    background: transparent;
}}

/* Top Header Bar */
QFrame#TopHeader {{
    background-color: {COLOR_MANTLE};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QLabel#HeaderTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {COLOR_TEXT_PRIMARY};
    background: transparent;
}}

QLabel#HeaderSubtitle {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
    background: transparent;
}}

QLabel#TelemetryPill {{
    color: {COLOR_TEXT_MUTED};
    font-size: 11px;
    font-weight: 500;
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 4px 10px;
}}

/* Sidebar Nav Buttons */
QPushButton#NavButton {{
    background-color: transparent;
    color: {COLOR_TEXT_MUTED};
    border: none;
    border-left: 3px solid transparent;
    border-radius: 6px;
    text-align: left;
    padding: 9px 14px;
    margin: 2px 8px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton#NavButton:hover {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
}}

QPushButton#NavButton:checked {{
    background-color: {COLOR_OVERLAY};
    color: {COLOR_ACCENT};
    font-weight: 600;
    border-left: 3px solid {COLOR_ACCENT};
}}

/* Cards & Group Containers */
QFrame.Card {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}

QFrame.SubCard {{
    background-color: {COLOR_MANTLE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}

QLabel.SectionTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {COLOR_TEXT_PRIMARY};
    background: transparent;
}}

QLabel.MetricValue {{
    font-size: 22px;
    font-weight: 700;
    color: {COLOR_ACCENT};
    background: transparent;
}}

QLabel.MetricLabel {{
    font-size: 10px;
    font-weight: 600;
    color: {COLOR_TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.4px;
    background: transparent;
}}

QLabel.MutedHint {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
    background: transparent;
}}

/* Status Badges */
QLabel[class="BadgeFresh"] {{
    background-color: rgba(166, 218, 149, 0.16);
    color: {COLOR_SUCCESS};
    border: 1px solid rgba(166, 218, 149, 0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 11px;
}}

QLabel[class="BadgeStale"] {{
    background-color: rgba(237, 135, 150, 0.16);
    color: {COLOR_DANGER};
    border: 1px solid rgba(237, 135, 150, 0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 11px;
}}

QLabel[class="BadgeWarning"] {{
    background-color: rgba(238, 212, 159, 0.16);
    color: {COLOR_WARNING};
    border: 1px solid rgba(238, 212, 159, 0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 11px;
}}

QLabel[class="BadgeNeutral"] {{
    background-color: {COLOR_OVERLAY};
    color: {COLOR_TEXT_MUTED};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 11px;
}}

/* Buttons */
QPushButton {{
    background-color: {COLOR_OVERLAY};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 18px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: #3b3e52;
    border-color: {COLOR_ACCENT};
}}

QPushButton:pressed {{
    background-color: #45475a;
}}

QPushButton:disabled {{
    background-color: {COLOR_MANTLE};
    color: {COLOR_TEXT_SUBTLE};
    border-color: {COLOR_BORDER};
}}

QPushButton[class="PrimaryButton"] {{
    background-color: {COLOR_ACCENT};
    color: {COLOR_CRUST};
    font-weight: 600;
    border: 1px solid {COLOR_ACCENT};
}}

QPushButton[class="PrimaryButton"]:hover {{
    background-color: {COLOR_ACCENT_HOVER};
    border-color: {COLOR_ACCENT_HOVER};
}}

QPushButton[class="PrimaryButton"]:disabled {{
    background-color: {COLOR_OVERLAY};
    color: {COLOR_TEXT_SUBTLE};
    border-color: {COLOR_BORDER};
}}

QPushButton[class="DangerButton"] {{
    background-color: rgba(237, 135, 150, 0.16);
    color: {COLOR_DANGER};
    border: 1px solid rgba(237, 135, 150, 0.65);
    font-weight: 600;
}}

QPushButton[class="DangerButton"]:hover {{
    background-color: {COLOR_DANGER};
    color: {COLOR_CRUST};
}}

QPushButton[class="DangerSolidButton"] {{
    background-color: {COLOR_DANGER};
    color: {COLOR_CRUST};
    border: 1px solid {COLOR_DANGER};
    font-weight: 700;
}}

QPushButton[class="DangerSolidButton"]:hover {{
    background-color: #f38ba8;
}}

/* Tables & Lists */
QTableWidget, QTableView, QListWidget {{
    background-color: {COLOR_MANTLE};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    gridline-color: {COLOR_BORDER};
    selection-background-color: {COLOR_OVERLAY};
    selection-color: {COLOR_TEXT_PRIMARY};
    alternate-background-color: #1b1c2a;
    outline: 0;
}}

QHeaderView::section {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_MUTED};
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    border-right: 1px solid {COLOR_BORDER};
    font-weight: 600;
    font-size: 11px;
}}

QTableWidget::item, QTableView::item, QListWidget::item {{
    padding: 5px 8px;
}}

QListWidget::item:selected {{
    background-color: {COLOR_OVERLAY};
    color: {COLOR_TEXT_PRIMARY};
}}

/* CheckBoxes */
QCheckBox {{
    spacing: 8px;
    color: {COLOR_TEXT_PRIMARY};
    background: transparent;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_MANTLE};
}}

QCheckBox::indicator:hover {{
    border-color: {COLOR_ACCENT};
}}

QCheckBox::indicator:checked {{
    background-color: {COLOR_ACCENT};
    border-color: {COLOR_ACCENT};
}}

/* Inputs & Combos */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {COLOR_MANTLE};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: {COLOR_CRUST};
}}

QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {COLOR_ACCENT};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_OVERLAY};
}}

/* TabWidget (for sub-views) */
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    background-color: {COLOR_SURFACE};
    top: -1px;
}}

QTabBar::tab {{
    background-color: {COLOR_MANTLE};
    color: {COLOR_TEXT_MUTED};
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 7px 14px;
    margin-right: 4px;
    font-weight: 500;
}}

QTabBar::tab:selected {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_ACCENT};
    font-weight: 600;
}}

/* Menus & Tooltips */
QMenu {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 18px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {COLOR_OVERLAY};
    color: {COLOR_ACCENT};
}}

QToolTip {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_ACCENT};
    padding: 5px 8px;
    border-radius: 4px;
}}

/* Progress Bar */
QProgressBar {{
    background-color: {COLOR_MANTLE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    text-align: center;
    color: {COLOR_TEXT_PRIMARY};
    min-height: 16px;
    font-size: 11px;
    font-weight: 600;
}}

QProgressBar::chunk {{
    background-color: {COLOR_ACCENT};
    border-radius: 5px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_OVERLAY};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLOR_TEXT_SUBTLE};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
    margin: 0 2px;
}}
QScrollBar::handle:horizontal {{
    background: {COLOR_OVERLAY};
    border-radius: 4px;
    min-width: 24px;
}}
"""
