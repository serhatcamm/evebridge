"""
UI Themes
----------
Generates the app's QSS stylesheet from a named color palette. All themes
share the same widget structure/rules (see _STYLESHEET_TEMPLATE) — only the
colors change, so adding a new theme is just adding a new palette dict below.

Design notes (per the ui-ux-pro-max / frontend-design skills):
  - Colors are semantic tokens defined once per palette; components never
    hardcode raw hex (use the QLabel#muted / #accentText / #warn / #dangerText
    roles instead of inline setStyleSheet colors).
  - Every interactive state is covered: hover, pressed, focus, disabled.
  - Focus rings are always visible (keyboard accessibility floor).
"""

_STYLESHEET_TEMPLATE = """
QMainWindow {{
    background-color: {bg};
}}
QWidget {{
    background-color: {bg};
    color: {text};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QMessageBox {{
    messagebox-text-interaction-flags: 5;
}}

/* ---------- semantic text roles (no raw hex in components) ---------- */
QLabel#muted {{
    color: {text_dim};
    font-style: italic;
}}
QLabel#accentText {{
    color: {accent};
    font-weight: bold;
}}
QLabel#warn {{
    color: {warning};
    font-weight: bold;
}}
QLabel#dangerText {{
    color: {danger};
    font-weight: bold;
}}

/* ---------- group boxes ---------- */
QGroupBox {{
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 12px;
    font-weight: bold;
    color: {text_dim};
    padding-top: 4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {accent};
}}

/* ---------- buttons: base + every state (soft vertical gradients) ---------- */
QPushButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {bg_alt_hover}, stop:1 {bg_alt});
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 7px 15px;
    min-height: 16px;
    font-weight: 600;
    color: {text};
}}
QPushButton:hover {{
    background-color: {bg_alt_hover};
    border-color: {accent};
}}
QPushButton:pressed {{
    background-color: {bg_pressed};
}}
QPushButton:focus {{
    border: 1px solid {accent};
    outline: none;
}}
QPushButton:disabled {{
    background-color: {bg_alt};
    color: {text_disabled};
    border-color: {border};
}}
QPushButton#btnPrimary {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {accent_solid}, stop:1 {accent_solid_hover});
    border: 1px solid {accent_solid_hover};
    color: {on_accent_text};
}}
QPushButton#btnPrimary:hover {{
    background-color: {accent_solid_hover};
    border-color: {accent_solid_hover};
}}
QPushButton#btnPrimary:pressed {{
    background-color: {bg_pressed};
}}
QPushButton#btnDanger {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {danger}, stop:1 {danger_hover});
    border: 1px solid {danger_hover};
    color: white;
}}
QPushButton#btnDanger:hover {{
    background-color: {danger_hover};
    border-color: {danger_hover};
}}
QPushButton#btnSuccess {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {success}, stop:1 {success_hover});
    border: 1px solid {success_hover};
    color: white;
}}
QPushButton#btnSuccess:hover {{
    background-color: {success_hover};
    border-color: {success_hover};
}}

/* ---------- inputs: visible focus ring everywhere ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
QComboBox, QListWidget {{
    background-color: {bg_alt};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 6px;
    min-height: 24px;
    color: {text};
    selection-background-color: {accent_solid};
    selection-color: {on_accent_text};
}}
QLineEdit:hover, QTextEdit:hover, QSpinBox:hover, QComboBox:hover {{
    border-color: {border_strong};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QComboBox:focus, QListWidget:focus {{
    border: 1px solid {accent};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {text_disabled};
    background-color: {bg};
}}
QLineEdit[echoMode="2"] {{
    letter-spacing: 1px;
}}

/* ---------- combo dropdown ---------- */
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {bg_alt};
    border: 1px solid {border_strong};
    border-radius: 6px;
    color: {text};
    selection-background-color: {accent_solid};
    selection-color: {on_accent_text};
    outline: none;
}}

/* ---------- checkboxes ---------- */
QCheckBox {{
    spacing: 7px;
    color: {text};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {border_strong};
    border-radius: 4px;
    background-color: {bg_alt};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {accent_solid};
    border-color: {accent_solid};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {accent};
}}
QCheckBox::indicator:disabled {{
    border-color: {border};
    background-color: {bg};
}}

/* ---------- tables ---------- */
QTableWidget {{
    background-color: {bg_alt};
    alternate-background-color: {bg};
    gridline-color: {border};
    border: 1px solid {border};
    border-radius: 8px;
    selection-background-color: {accent_solid};
    selection-color: {on_accent_text};
}}
QTableWidget::item {{
    padding: 4px 6px;
}}
QHeaderView::section {{
    background-color: {bg};
    color: {text_dim};
    padding: 7px 6px;
    font-weight: bold;
    border: none;
    border-bottom: 2px solid {border_strong};
}}

/* ---------- tabs ---------- */
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {bg_alt};
    border: 1px solid {border};
    padding: 8px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: {text_dim};
    font-weight: bold;
}}
QTabBar::tab:hover {{
    background-color: {bg_alt_hover};
    color: {text};
}}
QTabBar::tab:selected {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {accent_solid}, stop:1 {accent_solid_hover});
    color: {on_accent_text};
    border-color: {accent_solid_hover};
}}

/* ---------- progress bars ---------- */
QProgressBar {{
    background-color: {bg_alt};
    border: 1px solid {border};
    border-radius: 6px;
    text-align: center;
    color: {text};
    font-weight: bold;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {accent_solid}, stop:1 {accent_solid_hover});
    border-radius: 5px;
}}

/* ---------- menus (incl. table context menu) ---------- */
QMenu {{
    background-color: {bg_alt};
    border: 1px solid {border_strong};
    border-radius: 8px;
    color: {text};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px;
    border-radius: 4px;
    background-color: transparent;
}}
QMenu::item:selected {{
    background-color: {accent_solid};
    color: {on_accent_text};
}}
QMenu::item:disabled {{
    color: {text_disabled};
}}
QMenu::separator {{
    height: 1px;
    background-color: {border};
    margin: 5px 8px;
}}

/* ---------- tooltips ---------- */
QToolTip {{
    background-color: {bg_alt};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 4px;
    padding: 4px 6px;
}}

/* ---------- slim themed scrollbars ---------- */
QScrollBar:vertical {{
    background-color: transparent;
    width: 11px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {border_strong};
    border-radius: 5px;
    min-height: 28px;
    margin: 2px 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {accent};
}}
QScrollBar:horizontal {{
    background-color: transparent;
    height: 11px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {border_strong};
    border-radius: 5px;
    min-width: 28px;
    margin: 2px 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {accent};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background-color: transparent;
}}
"""

# Tokens shared by every theme unless a palette overrides them.
_TOKEN_DEFAULTS = {
    "warning": "#f59e0b",
    "text_disabled": "#8294ab",
}

# Each palette drives the whole app's look. Keys must match the template's
# {placeholders} above.
THEMES = {
    "Dark Navy (default)": {
        "bg": "#0f172a", "bg_alt": "#1e293b", "bg_alt_hover": "#334155", "bg_pressed": "#090d16",
        "border": "#334155", "border_strong": "#475569",
        "text": "#f8fafc", "text_dim": "#94a3b8",
        "accent": "#38bdf8", "accent_solid": "#0284c7", "accent_solid_hover": "#0369a1",
        "on_accent_text": "white",
        "danger": "#be123c", "danger_hover": "#9f1239",
        "success": "#15803d", "success_hover": "#166534",
    },
    "Midnight Purple": {
        "bg": "#191324", "bg_alt": "#241b34", "bg_alt_hover": "#382a4f", "bg_pressed": "#0f0a17",
        "border": "#3d2f57", "border_strong": "#54406f",
        "text": "#f4f0fb", "text_dim": "#a99ecb",
        "accent": "#c084fc", "accent_solid": "#7c3aed", "accent_solid_hover": "#6d28d9",
        "on_accent_text": "white",
        "danger": "#be123c", "danger_hover": "#9f1239",
        "success": "#15803d", "success_hover": "#166534",
    },
    "Nord": {
        "bg": "#2e3440", "bg_alt": "#3b4252", "bg_alt_hover": "#434c5e", "bg_pressed": "#242933",
        "border": "#4c566a", "border_strong": "#5b6578",
        "text": "#eceff4", "text_dim": "#a8b2c4",
        "accent": "#88c0d0", "accent_solid": "#5e81ac", "accent_solid_hover": "#81a1c1",
        "on_accent_text": "white",
        "danger": "#bf616a", "danger_hover": "#a5464f",
        "success": "#a3be8c", "success_hover": "#8caf70",
    },
    "Solarized Dark": {
        "bg": "#002b36", "bg_alt": "#073642", "bg_alt_hover": "#0d4a5a", "bg_pressed": "#00212a",
        "border": "#0d4a5a", "border_strong": "#155b6e",
        "text": "#eee8d5", "text_dim": "#93a1a1",
        "accent": "#2aa198", "accent_solid": "#268bd2", "accent_solid_hover": "#1e6fa8",
        "on_accent_text": "white",
        "danger": "#dc322f", "danger_hover": "#b52b28",
        "success": "#859900", "success_hover": "#6b7a00",
    },
    "Forest": {
        "bg": "#0f1912", "bg_alt": "#1a2b1f", "bg_alt_hover": "#25402c", "bg_pressed": "#0a120c",
        "border": "#2d4534", "border_strong": "#3c5a45",
        "text": "#eaf4ec", "text_dim": "#9ab8a3",
        "accent": "#4ade80", "accent_solid": "#16a34a", "accent_solid_hover": "#15803d",
        "on_accent_text": "white",
        "danger": "#be123c", "danger_hover": "#9f1239",
        "success": "#4ade80", "success_hover": "#22c55e",
    },
    "Light": {
        "bg": "#f8fafc", "bg_alt": "#ffffff", "bg_alt_hover": "#e2e8f0", "bg_pressed": "#cbd5e1",
        "border": "#cbd5e1", "border_strong": "#94a3b8",
        "text": "#0f172a", "text_dim": "#475569",
        "accent": "#0284c7", "accent_solid": "#0284c7", "accent_solid_hover": "#0369a1",
        "on_accent_text": "white",
        "danger": "#dc2626", "danger_hover": "#b91c1c",
        "success": "#16a34a", "success_hover": "#15803d",
        "warning": "#b45309",
        "text_disabled": "#94a3b8",
    },
    "Glass (Frosted Dark)": {
        # Simulates a glassmorphism look using translucent (rgba) panels over a
        # deep indigo backdrop — true background blur isn't possible in plain
        # QSS, but semi-transparent layered panels with soft light borders get
        # a similar "frosted glass" feel.
        "bg": "#12101c", "bg_alt": "rgba(255, 255, 255, 18)", "bg_alt_hover": "rgba(255, 255, 255, 32)",
        "bg_pressed": "rgba(255, 255, 255, 10)",
        "border": "rgba(255, 255, 255, 40)", "border_strong": "rgba(255, 255, 255, 70)",
        "text": "#f5f3ff", "text_dim": "#b9b3d9",
        "accent": "#a5b4fc", "accent_solid": "rgba(99, 102, 241, 200)", "accent_solid_hover": "rgba(79, 70, 229, 220)",
        "on_accent_text": "white",
        "danger": "rgba(225, 29, 72, 200)", "danger_hover": "rgba(190, 18, 60, 220)",
        "success": "rgba(34, 197, 94, 190)", "success_hover": "rgba(21, 128, 61, 210)",
    },
    "macOS Light": {
        "bg": "#f5f5f7", "bg_alt": "#ffffff", "bg_alt_hover": "#e8e8ed", "bg_pressed": "#d2d2d7",
        "border": "#d2d2d7", "border_strong": "#b8b8bd",
        "text": "#1d1d1f", "text_dim": "#6e6e73",
        "accent": "#0071e3", "accent_solid": "#0071e3", "accent_solid_hover": "#0058b0",
        "on_accent_text": "white",
        "danger": "#ff3b30", "danger_hover": "#d70015",
        "success": "#34c759", "success_hover": "#248a3d",
        "warning": "#b25000",
        "text_disabled": "#aeaeb2",
    },
    "macOS Dark": {
        "bg": "#1e1e1e", "bg_alt": "#2c2c2e", "bg_alt_hover": "#3a3a3c", "bg_pressed": "#141414",
        "border": "#3a3a3c", "border_strong": "#48484a",
        "text": "#f5f5f7", "text_dim": "#98989d",
        "accent": "#409cff", "accent_solid": "#0a84ff", "accent_solid_hover": "#0060c0",
        "on_accent_text": "white",
        "danger": "#ff453a", "danger_hover": "#c9231a",
        "success": "#32d74b", "success_hover": "#25a838",
    },
}

THEME_NAMES = list(THEMES.keys())
DEFAULT_THEME = THEME_NAMES[0]


def get_palette(theme_name: str) -> dict:
    """Returns the full token dict for a named theme, falling back to the default."""
    palette = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    return {**_TOKEN_DEFAULTS, **palette}


def get_stylesheet(theme_name: str) -> str:
    """Returns the full QSS stylesheet for a named theme, falling back to the default if unknown."""
    return _STYLESHEET_TEMPLATE.format(**get_palette(theme_name))
