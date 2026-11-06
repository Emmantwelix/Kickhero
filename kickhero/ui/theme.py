"""Colours and the Qt stylesheet for the dark theme."""

BG = "#12141c"
PANEL = "#1b1e2a"
PANEL_2 = "#232737"
BORDER = "#2e3346"
TEXT = "#e8eaf2"
MUTED = "#8b90a5"
ACCENT = "#ff7a59"
GOOD = "#5be49b"
WARN = "#ffd166"
BAD = "#ff5d73"

GRADE_COLORS = {"perfect": GOOD, "good": WARN, "ok": "#ffab5e", "miss": BAD, "extra": BAD}

STYLESHEET = f"""
* {{ font-family: "Segoe UI", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QLabel#appname {{ font-size: 13pt; font-weight: 700; padding: 18px 16px 12px 16px; }}
QPushButton#nav {{
    text-align: left; padding: 10px 16px; border: none; border-radius: 8px; margin: 2px 8px;
    background: transparent; color: {MUTED}; font-size: 10.5pt;
}}
QPushButton#nav:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {PANEL_2}; color: {TEXT}; font-weight: 600; }}
QLabel#h1 {{ font-size: 18pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 600; }}
QLabel#muted, QLabel#hint {{ color: {MUTED}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QPushButton {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {MUTED}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: #1a0f0b; font-weight: 700; padding: 8px 20px; }}
QPushButton#primary:hover {{ background: #ff9274; }}
QPushButton:checked {{ background: #3a3150; border-color: {ACCENT}; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
}}
QComboBox QAbstractItemView {{ background: {PANEL_2}; selection-background-color: #3a3150; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QTableWidget {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; gridline-color: transparent;
    selection-background-color: #3a3150;
}}
QTableWidget::item {{ padding: 8px; border-bottom: 1px solid {BORDER}; }}
QTableWidget::item:selected {{ background: #3a3150; color: {TEXT}; }}
QHeaderView::section {{
    background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 8px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QDialog {{ background: {BG}; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: #3a3150; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 4px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QToolTip {{ background: {PANEL_2}; border: 1px solid {BORDER}; padding: 4px; }}
"""
