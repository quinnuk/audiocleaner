"""
Application-wide theme for AudioCleaner's GUI: a modern dark-mode design
system per the AudioCleaner UI/UX design brief (8px spacing grid, indigo
accent, explicit interactive states).

Applied once via app.setStyleSheet(STYLESHEET) in gui.main(). Individual
buttons opt into the coloured "roles" below by objectName:

    primaryButton  -> main call-to-action (Start)
    dangerButton   -> stops/cancels a running action (Cancel)
    watchButton    -> the Watch toggle (turns solid accent while active)

Everything else falls back to the neutral secondary button style, so no
other code changes are required to pick up the theme.
"""

# --- Spacing grid (8px base) ------------------------------------------------
SPACING_UNIT = 8
OUTER_MARGIN = 24          # fixed outer canvas margin
BLOCK_GAP = 16             # gap between major functional blocks
FIELD_GAP = 8              # gap between a label and its field
PAD_H = 12                 # internal horizontal padding (inputs/buttons)
PAD_V = 8                  # internal vertical padding (inputs/buttons)
BUTTON_HEIGHT = 36
PROGRESS_HEIGHT = 12

# --- Palette (Modern Dark Theme, per brief) --------------------------------
BG = "#121214"              # Deep matte charcoal - primary background
CARD_BG = "#1E1E24"         # Surface / card background
CARD_BG_RAISED = "#26262E"  # slightly lighter still, for hover/raised rows
BORDER = "#2E2E38"
BORDER_STRONG = "#3A3A46"

ACCENT = "#4F46E5"          # Indigo - primary accent
ACCENT_HOVER = "#6D63EF"    # lightened ~10%
ACCENT_PRESSED = "#3B34B8"  # darkened ~15%

SUCCESS = "#10B981"         # Emerald green - completed / success status
WARNING = "#F5B83D"         # gold-ish warning tone for skipped/attention states
DANGER = "#EF4444"
DANGER_HOVER = "#F45F5F"
DANGER_PRESSED = "#C22F2F"

TEXT = "#F3F4F6"            # Primary text
TEXT_MUTED = "#9CA3AF"      # Muted text - paths, labels, secondary data

DISABLED_BG = "#374151"
DISABLED_TEXT = "#6B7280"

SELECTION_BG = "#332F63"    # translucent-feeling indigo selection wash

# Kept as plain aliases so any old imports of these names still resolve.
INK = BG
INDIGO = ACCENT
PURPLE = ACCENT
PURPLE_LIGHT = ACCENT_HOVER
PURPLE_LIGHTER = ACCENT_HOVER
CYAN = SUCCESS
CYAN_DARK = SUCCESS
CYAN_DEEP = SUCCESS
GOLD = WARNING
GOLD_DARK = "#B8860B"
RED = DANGER
RED_DARK = DANGER_PRESSED

STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    font-size: 11pt;
    font-weight: 500;
    selection-background-color: {SELECTION_BG};
    selection-color: {TEXT};
}}

QLabel {{
    background: transparent;
    color: {TEXT};
}}

QMainWindow, QDialog, MainWindow, HistoryDialog {{
    background-color: {BG};
}}

/* ---------------- Section headers (group boxes = cards) ---------------- */
QGroupBox {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: {BLOCK_GAP}px;
    padding-top: {BLOCK_GAP + 6}px;
    padding-left: {PAD_H}px;
    padding-right: {PAD_H}px;
    padding-bottom: {PAD_H}px;
    font-size: 14pt;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: {PAD_H}px;
    padding: 0 {FIELD_GAP}px;
    color: {TEXT};
    font-size: 14pt;
    font-weight: 700;
}}

/* ---------------- Inputs ---------------- */
QListWidget, QPlainTextEdit, QTableWidget, QLineEdit, QComboBox, QSpinBox {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {SELECTION_BG};
    selection-color: {TEXT};
    padding: {PAD_V}px {PAD_H}px;
    font-size: 11pt;
    font-weight: 500;
}}
QPlainTextEdit {{
    font-family: Consolas, "Courier New", monospace;
    font-size: 9.5pt;
    font-weight: 400;
    color: {TEXT_MUTED};
}}

/* ---------------- Lists (no alternating rows, generous row padding) --- */
QListWidget {{
    outline: none;
}}
QListWidget::item {{
    padding: 10px {FIELD_GAP}px;
    border-bottom: 1px solid {BORDER};
}}
QListWidget::item:selected {{
    background-color: {SELECTION_BG};
    color: {TEXT};
    border-radius: 4px;
}}
QListWidget::item:hover {{
    background-color: {CARD_BG_RAISED};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {SELECTION_BG};
}}

/* ---------------- Buttons ---------------- */
/* Qt's style-sheet box model adds padding/border on top of min/max-height,
   so vertical padding is kept at 0 here and the fixed 36px height is
   carried entirely by min/max-height (+ the 1px border each side). */
QPushButton {{
    background-color: rgba(255, 255, 255, 0.04);
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 0px {PAD_H + 4}px;
    min-height: {BUTTON_HEIGHT - 2}px;
    max-height: {BUTTON_HEIGHT - 2}px;
    font-size: 11pt;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: rgba(255, 255, 255, 0.10);
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: rgba(255, 255, 255, 0.02);
}}
QPushButton:disabled {{
    background-color: {DISABLED_BG};
    color: {DISABLED_TEXT};
    border-color: {DISABLED_BG};
}}
QPushButton:checkable:checked {{
    border-color: {ACCENT};
}}

/* Primary action (Start) */
QPushButton#primaryButton {{
    background-color: {ACCENT};
    color: #ffffff;
    border: 1px solid {ACCENT};
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#primaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton#primaryButton:disabled {{
    background-color: {DISABLED_BG};
    color: {DISABLED_TEXT};
    border-color: {DISABLED_BG};
}}

/* Danger / stop action (Cancel) */
QPushButton#dangerButton {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
    font-weight: 700;
}}
QPushButton#dangerButton:hover {{
    background-color: rgba(239, 68, 68, 0.12);
    border-color: {DANGER_HOVER};
    color: {DANGER_HOVER};
}}
QPushButton#dangerButton:pressed {{
    background-color: rgba(239, 68, 68, 0.20);
    border-color: {DANGER_PRESSED};
}}
QPushButton#dangerButton:disabled {{
    background-color: transparent;
    color: {DISABLED_TEXT};
    border-color: {DISABLED_BG};
}}

/* Watch toggle - outlined when idle, solid success colour while active */
QPushButton#watchButton {{
    background-color: rgba(255, 255, 255, 0.04);
    color: {SUCCESS};
    border: 1px solid {SUCCESS};
}}
QPushButton#watchButton:hover {{
    background-color: rgba(16, 185, 129, 0.12);
}}
QPushButton#watchButton:checked {{
    background-color: {SUCCESS};
    color: #0b1f18;
    border: 1px solid {SUCCESS};
}}
QPushButton#watchButton:disabled {{
    background-color: {DISABLED_BG};
    color: {DISABLED_TEXT};
    border-color: {DISABLED_BG};
}}

/* ---------------- Checkboxes ---------------- */
QCheckBox {{
    spacing: {FIELD_GAP}px;
    font-size: 11pt;
    font-weight: 500;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background-color: {CARD_BG};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:disabled {{
    background-color: {DISABLED_BG};
    border-color: {DISABLED_BG};
}}

/* ---------------- Progress bar ---------------- */
QProgressBar {{
    border: none;
    border-radius: 6px;
    background-color: {CARD_BG_RAISED};
    text-align: center;
    color: transparent;
    min-height: {PROGRESS_HEIGHT}px;
    max-height: {PROGRESS_HEIGHT}px;
}}
QProgressBar::chunk {{
    border-radius: 6px;
    background-color: {ACCENT};
}}

/* ---------------- Tables (Processing History) ---------------- */
QHeaderView::section {{
    background-color: {CARD_BG_RAISED};
    color: {TEXT};
    padding: {PAD_V}px {FIELD_GAP}px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 700;
    font-size: 9.5pt;
}}
QTableWidget {{
    gridline-color: {BORDER};
    alternate-background-color: {CARD_BG};
}}
QTableWidget::item {{
    padding: 10px {FIELD_GAP}px;
    border-bottom: 1px solid {BORDER};
}}
QTableWidget::item:selected {{
    background-color: {SELECTION_BG};
    color: {TEXT};
}}

/* ---------------- Scroll areas / bars ---------------- */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QAbstractScrollArea::viewport {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: {BG};
    width: 12px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 6px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* ---------------- Splitter (pane divider) ---------------- */
QSplitter::handle {{
    background-color: {BORDER};
    border-radius: 3px;
}}
QSplitter::handle:hover {{
    background-color: {ACCENT};
}}

/* ---------------- Menus (tray icon context menu) ---------------- */
QMenu {{
    background-color: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QMenu::item {{
    padding: {FIELD_GAP}px 20px;
}}
QMenu::item:selected {{
    background-color: {SELECTION_BG};
    color: {TEXT};
}}
"""

# Warning banner (missing dependencies) - a soft warning tint against the
# dark surface, consistent with the WARNING accent used elsewhere.
DEP_BANNER_STYLE = (
    f"QFrame {{ background-color: rgba(245, 184, 61, 0.10); "
    f"border: 1px solid {WARNING}; border-radius: 8px; }}"
)
MUTED_LABEL_STYLE = f"color: {TEXT_MUTED}; font-size: 9.5pt; font-weight: 400;"
SECTION_HEADER_STYLE = f"color: {TEXT}; font-size: 14pt; font-weight: 700;"
