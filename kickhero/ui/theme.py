"""Design tokens (colours, spacing, radii, type sizes) and the Qt stylesheet for the dark theme."""

# Surfaces, from the window background up: BG < PANEL (cards, sidebar) < PANEL_2 (controls) < SURFACE_3 (hover)
BG = "#0f1117"
PANEL = "#171a23"
PANEL_2 = "#20242f"
SURFACE_3 = "#2a2f3c"
BORDER = "#292e3b"
TEXT = "#eceef4"
MUTED = "#8a90a3"
FAINT = "#5c6275"      # tertiary text: captions, disabled
ACCENT = "#ff7a59"
ACCENT_HOVER = "#ff9173"
ACCENT_SOFT = "#3b2620"  # a switched-on toggle, a selected item: the accent at low strength
SELECT = "#262c3e"      # selected rows and list items
GOOD = "#5be49b"
WARN = "#ffd166"
BAD = "#ff5d73"
ON = ACCENT_SOFT

GRADE_COLORS = {"perfect": GOOD, "good": WARN, "ok": "#ffab5e", "miss": BAD, "extra": BAD}

# 8 px spacing grid, radii and type scale (pt)
SPACE = 8
RADIUS = 8        # controls
RADIUS_CARD = 14
FONT = '"Segoe UI Variable Text", "Segoe UI", sans-serif'
SIZE_BODY, SIZE_SMALL, SIZE_H3, SIZE_H2, SIZE_H1, SIZE_DISPLAY = 10, 9, 12, 15, 21, 28

STYLESHEET = f"""
* {{ font-family: {FONT}; font-size: {SIZE_BODY}pt; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}

/* sidebar */
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QLabel#appname {{ font-size: {SIZE_H3}pt; font-weight: 700; padding: 0 4px; }}
QPushButton#nav {{
    text-align: left; padding: 10px 14px; border: none; border-radius: {RADIUS}px; margin: 1px 10px;
    background: transparent; color: {MUTED}; font-size: 10.5pt; font-weight: 600;
}}
QPushButton#nav:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QPushButton#status, QPushButton#status:disabled {{
    text-align: left; padding: 6px 12px; border: none; border-radius: {RADIUS}px; margin: 0 10px;
    background: transparent; color: {MUTED}; font-size: {SIZE_SMALL}pt;
}}
QPushButton#status:hover:enabled {{ background: {PANEL_2}; color: {TEXT}; }}

/* text */
QLabel#display {{ font-size: {SIZE_DISPLAY}pt; font-weight: 700; }}
QLabel#h1 {{ font-size: {SIZE_H1}pt; font-weight: 700; }}
QLabel#h2 {{ font-size: {SIZE_H2}pt; font-weight: 600; }}
QLabel#h3 {{ font-size: {SIZE_H3}pt; font-weight: 600; }}
QLabel#muted, QLabel#hint {{ color: {MUTED}; }}
QLabel#caption {{ color: {MUTED}; font-size: {SIZE_SMALL}pt; }}
QLabel#group {{ color: {FAINT}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}

/* surfaces */
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: {RADIUS_CARD}px; }}
QFrame#bar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: {RADIUS_CARD}px; }}

/* buttons: same padding and 1px border in every state, so nothing shifts when toggled */
QPushButton, QToolButton {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover, QToolButton:hover {{ background: {SURFACE_3}; border-color: {SURFACE_3}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {FAINT}; background: {PANEL}; border-color: {BORDER}; }}
QPushButton:focus {{ outline: none; border-color: {MUTED}; }}   /* keyboard focus ring */
QPushButton#primary {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: #1a0f0b; font-weight: 700; padding: 8px 20px;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: #e86a4b; }}
QPushButton#primary:disabled {{ background: {PANEL_2}; color: {FAINT}; border: 1px solid {BORDER}; }}
QPushButton#primary:focus {{ border-color: #ffc2b0; }}
QPushButton#flat, QToolButton#flat {{ background: transparent; border-color: transparent; color: {MUTED}; }}
QPushButton#flat:hover, QToolButton#flat:hover {{ background: {PANEL_2}; color: {TEXT}; }}
QPushButton:checked, QToolButton:checked {{ background: {ACCENT_SOFT}; border: 1px solid {ACCENT}; color: #ffffff; }}
QPushButton:checked:hover, QToolButton:checked:hover {{ background: #4a2f27; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#chip {{
    background: transparent; border: 1px solid {BORDER}; border-radius: 14px; padding: 5px 14px;
    color: {MUTED}; font-weight: 600;
}}
QPushButton#chip:hover {{ border-color: {FAINT}; color: {TEXT}; background: transparent; }}
QPushButton#chip:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: #ffffff; }}

/* inputs */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 6px 10px;
    selection-background-color: {ACCENT_SOFT};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{ border-color: {SURFACE_3}; }}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: {SELECT}; outline: none;
}}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {FAINT}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {FAINT}; background: {PANEL_2};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {MUTED}; }}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{
    border-color: {ACCENT};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                stop:0 #1a0f0b, stop:0.42 #1a0f0b, stop:0.5 {ACCENT}, stop:1 {ACCENT});
}}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}

/* lists and tables */
QTableWidget, QListWidget {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: {RADIUS_CARD}px; gridline-color: transparent;
    selection-background-color: {SELECT}; outline: none;
}}
QTableWidget::item {{ padding: 8px; border-bottom: 1px solid {BORDER}; }}
QTableWidget::item:hover {{ background: {PANEL_2}; }}
QTableWidget::item:selected {{ background: {SELECT}; color: {TEXT}; }}
QHeaderView::section {{
    background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 8px;
    font-size: {SIZE_SMALL}pt; font-weight: 600;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* popups */
QDialog {{ background: {BG}; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 6px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 4px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 8px; border-radius: 6px; }}
"""


def check_css(check_png):
    """The tick inside a checked checkbox: an image file (a stylesheet can't draw one), made at startup."""
    url = str(check_png).replace("\\", "/")
    return f"QCheckBox::indicator:checked {{ image: url({url}); }}\n"
