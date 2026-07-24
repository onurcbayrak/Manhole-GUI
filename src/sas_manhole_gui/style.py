SUCCESS = "#3ddc97"
SAM_COLOR = "#c77dff"
WARNING = "#ffb84f"
DANGER = "#ff5c5c"
BG_DARK = "#1e2126"
BG_PANEL = "#262a31"
BG_PANEL_ALT = "#2c313a"
BORDER = "#3a3f47"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#6ea0ff"
TEXT = "#e6e8eb"
TEXT_DIM = "#9aa0a8"

CLASS_COLORS = [
    "#ff5c5c",
    "#4f8cff",
    "#3ddc97",
    "#ffb84f",
    "#c77dff",
    "#4fd8ff",
    "#ffd93d",
    "#ff7ab6",
    "#8bc34a",
    "#b0bec5",
]

APP_STYLESHEET = f"""
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT};
    font-family: 'Segoe UI', sans-serif;
    font-size: 10.5pt;
}}

QMainWindow {{
    background-color: {BG_DARK};
}}

QDockWidget {{
    titlebar-close-icon: none;
    color: {TEXT_DIM};
    font-weight: 600;
}}
QDockWidget::title {{
    background: {BG_PANEL};
    padding: 6px 8px;
    border-bottom: 1px solid {BORDER};
}}

QToolBar {{
    background: {BG_PANEL};
    border: none;
    padding: 4px;
    spacing: 6px;
}}
QToolButton {{
    background: transparent;
    border-radius: 6px;
    padding: 6px 12px;
    color: {TEXT};
}}
QToolButton:hover {{
    background: {BG_PANEL_ALT};
}}
QToolButton:pressed, QToolButton:checked {{
    background: {ACCENT};
    color: white;
}}
QToolButton:disabled {{
    color: {TEXT_DIM};
}}
QToolButton#primaryToolButton {{
    background: {ACCENT};
    color: white;
    font-weight: 600;
    padding: 6px 16px;
}}
QToolButton#primaryToolButton:hover {{
    background: {ACCENT_HOVER};
}}
QToolButton#primaryToolButton:disabled {{
    background: {BG_PANEL_ALT};
    color: {TEXT_DIM};
}}
QToolBar::separator {{
    background: {BORDER};
    width: 1px;
    margin: 6px 6px;
}}

QStatusBar {{
    background: {BG_PANEL};
    border-top: 1px solid {BORDER};
    padding: 2px 6px;
}}
QStatusBar::item {{
    border: none;
}}
QPushButton#statusPauseButton {{
    background: {BG_PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 12px;
    color: {TEXT};
    min-width: 66px;
}}
QPushButton#statusPauseButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}
QPushButton#statusPauseButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QPushButton#statusStopButton {{
    background: {BG_PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 3px 12px;
    color: {TEXT};
    min-width: 60px;
}}
QPushButton#statusStopButton:hover {{
    border-color: {DANGER};
    color: {DANGER};
}}
QPushButton#statusStopButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QLabel#statusDivider {{
    color: {BORDER};
    padding: 0 4px;
}}
QLabel#statusHint {{
    color: {TEXT_DIM};
}}

QListWidget, QTreeWidget, QTableWidget {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 4px;
    border-radius: 4px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {ACCENT};
    color: white;
}}
QListWidget::item:hover:!selected {{
    background: {BG_PANEL_ALT};
}}

QPushButton {{
    background: {BG_PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background: {ACCENT};
}}
QPushButton#primaryButton {{
    background: {ACCENT};
    border: none;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {BG_PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 6px;
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}

QProgressBar {{
    background: {BG_PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: {TEXT_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}

QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QMenu {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background: {ACCENT};
}}
"""


def class_color(index: int) -> str:
    return CLASS_COLORS[index % len(CLASS_COLORS)]
